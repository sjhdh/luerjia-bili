from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT_DIR, get_settings
from .database import get_session, init_database
from .models import (
    ACTIVE_JOB_STATUSES,
    ContentItem,
    Job,
    JobStatus,
    OfficialAccount,
    Report,
    ReportShare,
    SourceApp,
    Video,
)
from .schemas import (
    AuthSessionRead,
    BrowserInput,
    BrowserSessionRead,
    HealthRead,
    JobCreate,
    JobRead,
    LoginRequest,
    ShareCreate,
    ShareRead,
    TapTapSelection,
)
from .security import (
    SESSION_COOKIE,
    LoginThrottle,
    SessionAccessMiddleware,
    SessionSigner,
    cookie_value,
)
from .services.exporter import build_csv, build_pdf
from .services.job_runner import init_job_runner
from .sources.browser import init_browser_manager

settings = get_settings()
browser = init_browser_manager(settings)
runner = init_job_runner(settings, browser)
signer = SessionSigner(
    settings.session_secret_value,
    ttl_seconds=settings.session_ttl_hours * 60 * 60,
)
login_throttle = LoginThrottle()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_database()
    await runner.start()
    try:
        yield
    finally:
        await runner.stop()
        await browser.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
if settings.admin_password_value:
    app.add_middleware(
        SessionAccessMiddleware,
        signer=signer,
        exempt_prefixes={
            "/api/v1/health",
            "/api/v1/auth/login",
            "/api/v1/auth/session",
            "/api/v1/shared/reports/",
        },
        allowed_origins=settings.allowed_origins,
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", response_model=HealthRead)
async def health() -> HealthRead:
    return HealthRead(
        status="ok",
        model_configured=True,
        llm_configured=bool(
            settings.openai_base_url and settings.openai_api_key and settings.openai_model
        ),
        deployment_mode=settings.deployment_mode,
        access_protected=bool(settings.admin_password_value),
    )


@app.post("/api/v1/auth/login", response_model=AuthSessionRead)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthSessionRead:
    if not settings.admin_password_value:
        return AuthSessionRead(authenticated=True, username=settings.admin_username)
    client_key = request.client.host if request.client else "unknown"
    if login_throttle.is_blocked(client_key):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")
    valid = secrets.compare_digest(payload.username, settings.admin_username) and secrets.compare_digest(
        payload.password, settings.admin_password_value
    )
    if not valid:
        login_throttle.fail(client_key)
        raise HTTPException(status_code=401, detail="账号或密码错误")
    login_throttle.clear(client_key)
    response.set_cookie(
        SESSION_COOKIE,
        signer.issue(settings.admin_username),
        max_age=settings.session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.deployment_mode == "server",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuthSessionRead(authenticated=True, username=settings.admin_username)


@app.get("/api/v1/auth/session", response_model=AuthSessionRead)
async def auth_session(request: Request) -> AuthSessionRead:
    if not settings.admin_password_value:
        return AuthSessionRead(authenticated=True, username=settings.admin_username)
    username = signer.verify(cookie_value(request.scope))
    return AuthSessionRead(authenticated=bool(username), username=username)


@app.post("/api/v1/auth/logout", response_model=AuthSessionRead)
async def logout(response: Response) -> AuthSessionRead:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return AuthSessionRead(authenticated=False)


async def _browser_session_response(
    platform: Literal["bilibili", "taptap"] = "bilibili",
    message: str | None = None,
) -> BrowserSessionRead:
    state = await browser.workspace_state(platform)
    running = bool(state["running"])
    authenticated = bool(state["authenticated"])
    if authenticated:
        resolved_message = f"{'B站' if platform == 'bilibili' else 'TapTap'} 登录态可用"
    elif message:
        resolved_message = message
    else:
        resolved_message = "页面子窗口未连接或尚未登录"
    return BrowserSessionRead(
        platform=platform,
        running=running,
        authenticated=authenticated,
        login_method="window",
        message=resolved_message,
        workspace_ready=bool(state["workspace_ready"]),
        current_url=str(state["current_url"]) if state["current_url"] else None,
        page_title=str(state["page_title"]) if state["page_title"] else None,
        risk_detected=bool(state["risk_detected"]),
    )


@app.post("/api/v1/bilibili/login-window", response_model=BrowserSessionRead)
async def open_bilibili_login() -> BrowserSessionRead:
    try:
        await browser.start_login("bilibili")
        return await _browser_session_response("bilibili", "B站登录页已在页面子窗口打开")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法启动 Chromium，请先运行安装脚本：{type(exc).__name__}",
        ) from exc


@app.post("/api/v1/bilibili/qr-login", response_model=BrowserSessionRead)
async def start_bilibili_qr_login() -> BrowserSessionRead:
    return await open_bilibili_login()


@app.get("/api/v1/bilibili/qr-code.png", response_class=Response)
async def get_bilibili_qr_code() -> Response:
    raise HTTPException(status_code=410, detail="二维码已改为在页面子窗口中实时显示")


@app.get("/api/v1/bilibili/session", response_model=BrowserSessionRead)
async def get_bilibili_session() -> BrowserSessionRead:
    return await _browser_session_response("bilibili")


@app.delete("/api/v1/bilibili/session", response_model=BrowserSessionRead)
async def clear_bilibili_session() -> BrowserSessionRead:
    await browser.clear_profile("bilibili")
    return BrowserSessionRead(
        platform="bilibili",
        running=False,
        authenticated=False,
        login_method="window",
        message="B站登录资料已清除",
    )


@app.post("/api/v1/platforms/{platform}/workspace", response_model=BrowserSessionRead)
async def open_platform_workspace(
    platform: Literal["bilibili", "taptap"],
) -> BrowserSessionRead:
    try:
        await browser.start_login(platform)
        return await _browser_session_response(platform, "登录页已在页面子窗口打开")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"无法打开页面子窗口：{type(exc).__name__}") from exc


@app.get("/api/v1/platforms/{platform}/session", response_model=BrowserSessionRead)
async def get_platform_session(
    platform: Literal["bilibili", "taptap"],
) -> BrowserSessionRead:
    return await _browser_session_response(platform)


@app.delete("/api/v1/platforms/{platform}/session", response_model=BrowserSessionRead)
async def clear_platform_session(
    platform: Literal["bilibili", "taptap"],
) -> BrowserSessionRead:
    await browser.clear_profile(platform)
    return BrowserSessionRead(
        platform=platform,
        running=False,
        authenticated=False,
        login_method="window",
        message="本机登录资料已清除",
    )


@app.get("/api/v1/platforms/{platform}/frame.jpg")
async def get_browser_frame(platform: Literal["bilibili", "taptap"]) -> Response:
    try:
        content = await browser.capture_frame(platform)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"页面画面暂不可用：{type(exc).__name__}") from exc
    return Response(
        content,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.post("/api/v1/platforms/{platform}/input", response_model=BrowserSessionRead)
async def send_browser_input(
    platform: Literal["bilibili", "taptap"], payload: BrowserInput
) -> BrowserSessionRead:
    try:
        values = payload.model_dump(exclude={"type"})
        await browser.browser_input(platform, payload.type, **values)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"无法操作页面子窗口：{type(exc).__name__}") from exc
    return await _browser_session_response(platform)


@app.post("/api/v1/jobs", response_model=JobRead, status_code=201)
async def create_job(payload: JobCreate, session: AsyncSession = Depends(get_session)) -> Job:
    active = await session.scalar(
        select(Job.id).where(Job.status.in_([status.value for status in ACTIVE_JOB_STATUSES]))
    )
    if active:
        raise HTTPException(status_code=409, detail="当前已有任务运行，请等待完成或先取消")
    job = Job(**payload.model_dump())
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await runner.enqueue(job.id)
    return job


@app.get("/api/v1/jobs", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[Job]:
    return list(
        (await session.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))).all()
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/v1/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        last: tuple[object, ...] | None = None
        while True:
            async with runner_session() as session:
                job = await session.get(Job, job_id)
                if not job:
                    yield 'event: error\ndata: {"detail":"任务不存在"}\n\n'
                    return
                current = (job.status, job.stage, job.progress, job.message, job.updated_at)
                if current != last:
                    data = JobRead.model_validate(job).model_dump(mode="json")
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    last = current
                if job.status in {
                    JobStatus.COMPLETED.value,
                    JobStatus.PARTIAL.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                    JobStatus.AWAITING_LOGIN.value,
                    JobStatus.AWAITING_TAPTAP_SELECTION.value,
                }:
                    return
            await asyncio.sleep(0.6)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class runner_session:
    def __init__(self) -> None:
        from .database import SessionLocal

        self.factory = SessionLocal
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        self.session = self.factory()
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        assert self.session is not None
        await self.session.close()


@app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    job.cancel_requested = True
    if job.status in {
        JobStatus.PENDING.value,
        JobStatus.AWAITING_LOGIN.value,
        JobStatus.AWAITING_TAPTAP_SELECTION.value,
    }:
        job.status = JobStatus.CANCELLED.value
        job.stage = "已取消"
        job.progress = 100
        job.message = "任务已取消"
    else:
        job.message = "正在取消任务"
    await session.commit()
    await session.refresh(job)
    return job


async def _clear_job_results(job_id: str, session: AsyncSession) -> None:
    await session.execute(delete(ContentItem).where(ContentItem.job_id == job_id))
    await session.execute(delete(Video).where(Video.job_id == job_id))
    await session.execute(delete(SourceApp).where(SourceApp.job_id == job_id))
    await session.execute(delete(OfficialAccount).where(OfficialAccount.job_id == job_id))
    await session.execute(delete(Report).where(Report.job_id == job_id))


@app.post("/api/v1/jobs/{job_id}/retry", response_model=JobRead)
async def retry_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status == JobStatus.AWAITING_TAPTAP_SELECTION.value:
        raise HTTPException(status_code=409, detail="请先选择 TapTap 应用")
    preserve_checkpoint = bool(
        job.status == JobStatus.AWAITING_LOGIN.value
        or (job.official_mid and (job.collection_metrics or {}).get("official_checkpoint"))
    )
    if not preserve_checkpoint:
        await _clear_job_results(job_id, session)
    job.status = JobStatus.PENDING.value
    job.stage = "等待重试"
    job.progress = 0
    job.message = ""
    job.warnings = []
    if not preserve_checkpoint:
        job.collection_metrics = {}
    job.partial = False
    job.cancel_requested = False
    job.finished_at = None
    await session.commit()
    await session.refresh(job)
    await runner.enqueue(job.id)
    return job


@app.post("/api/v1/jobs/{job_id}/rerun", response_model=JobRead, status_code=201)
async def rerun_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    source = await session.get(Job, job_id)
    if not source:
        raise HTTPException(status_code=404, detail="任务不存在")
    clone = Job(
        keyword=source.keyword,
        time_range=source.time_range,
        depth=source.depth,
        analysis_mode=source.analysis_mode,
        official_bilibili_url=source.official_bilibili_url,
        official_mid=source.official_mid,
        include_discovery=source.include_discovery,
        include_taptap=source.include_taptap,
        taptap_app_id=source.taptap_app_id,
        taptap_app_url=source.taptap_app_url,
    )
    session.add(clone)
    await session.commit()
    await session.refresh(clone)
    await runner.enqueue(clone.id)
    return clone


@app.post("/api/v1/jobs/{job_id}/taptap-selection", response_model=JobRead)
async def select_taptap_app(
    job_id: str,
    payload: TapTapSelection,
    session: AsyncSession = Depends(get_session),
) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    job.taptap_app_id = payload.app_id
    job.taptap_app_url = f"https://www.taptap.cn/app/{payload.app_id}"
    job.taptap_candidates = []
    job.status = JobStatus.PENDING.value
    job.stage = "继续采集"
    job.message = "已确认 TapTap 应用"
    await session.commit()
    await session.refresh(job)
    await runner.enqueue(job.id)
    return job


async def _get_report(job_id: str, session: AsyncSession) -> Report:
    report = await session.scalar(select(Report).where(Report.job_id == job_id))
    if not report:
        raise HTTPException(status_code=404, detail="报告尚未生成")
    return report


@app.get("/api/v1/reports/{job_id}")
async def get_report(job_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    return (await _get_report(job_id, session)).payload


async def _resolve_share(token: str, session: AsyncSession) -> Report:
    token_hash = signer.share_hash(token)
    share = await session.scalar(select(ReportShare).where(ReportShare.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    expires_at = (
        share.expires_at.replace(tzinfo=timezone.utc)
        if share and share.expires_at.tzinfo is None
        else share.expires_at
        if share
        else now
    )
    if not share or share.revoked_at is not None or expires_at <= now:
        raise HTTPException(status_code=404, detail="分享链接不存在、已过期或已撤销")
    report = await session.scalar(select(Report).where(Report.job_id == share.job_id))
    if not report:
        raise HTTPException(status_code=404, detail="报告已过保留期")
    return report


@app.post("/api/v1/reports/{job_id}/shares", response_model=ShareRead, status_code=201)
async def create_report_share(
    job_id: str,
    payload: ShareCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ShareRead:
    await _get_report(job_id, session)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
    share = ReportShare(
        job_id=job_id,
        token_hash=signer.share_hash(token),
        expires_at=expires_at,
    )
    session.add(share)
    await session.commit()
    await session.refresh(share)
    base_url = (settings.public_base_url or str(request.base_url)).rstrip("/")
    return ShareRead(id=share.id, url=f"{base_url}/share/{token}", expires_at=expires_at)


@app.delete("/api/v1/reports/{job_id}/shares/{share_id}", status_code=204)
async def revoke_report_share(
    job_id: str,
    share_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    share = await session.scalar(
        select(ReportShare).where(ReportShare.id == share_id, ReportShare.job_id == job_id)
    )
    if not share:
        raise HTTPException(status_code=404, detail="分享链接不存在")
    share.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=204)


@app.get("/api/v1/shared/reports/{token}")
async def get_shared_report(token: str, session: AsyncSession = Depends(get_session)) -> dict:
    return (await _resolve_share(token, session)).payload


@app.get("/api/v1/reports/{job_id}/export.csv")
async def export_csv(job_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    await _get_report(job_id, session)
    items = list(
        (await session.scalars(select(ContentItem).where(ContentItem.job_id == job_id))).all()
    )
    return Response(
        build_csv(items),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sentiment-{job_id}.csv"'},
    )


@app.get("/api/v1/reports/{job_id}/export.pdf")
async def export_pdf(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> Response:
    await _get_report(job_id, session)
    try:
        content = await build_pdf(
            job_id,
            settings.pdf_base_url or str(request.base_url),
            session_cookie=(
                signer.issue(settings.admin_username) if settings.admin_password_value else None
            ),
            executable_path=settings.browser_executable_path,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PDF 导出失败，请确认 Playwright Chromium 已安装：{type(exc).__name__}",
        ) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="sentiment-{job_id}.pdf"'},
    )


frontend_dist = ROOT_DIR / "frontend" / "dist"
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> Response:
    index = frontend_dist / "index.html"
    requested = frontend_dist / full_path
    if (
        full_path
        and requested.is_file()
        and requested.resolve().is_relative_to(frontend_dist.resolve())
    ):
        return FileResponse(requested)
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "name": settings.app_name,
            "detail": "前端尚未构建，请运行 npm run dev 或 scripts/setup.ps1",
        }
    )
