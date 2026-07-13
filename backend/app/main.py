from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import ROOT_DIR, get_settings
from .database import get_session, init_database
from .models import ACTIVE_JOB_STATUSES, ContentItem, Job, JobStatus, Report, SourceApp, Video
from .schemas import BrowserSessionRead, HealthRead, JobCreate, JobRead, TapTapSelection
from .services.exporter import build_csv, build_pdf
from .services.job_runner import init_job_runner
from .sources.browser import init_browser_manager

settings = get_settings()
browser = init_browser_manager(settings)
runner = init_job_runner(settings, browser)


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
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
    )


@app.post("/api/v1/bilibili/login-window", response_model=BrowserSessionRead)
async def open_bilibili_login() -> BrowserSessionRead:
    try:
        await browser.connect(open_login=True)
        running, authenticated = await browser.session_state()
        return BrowserSessionRead(
            running=running,
            authenticated=authenticated,
            message="已打开 B站登录窗口" if not authenticated else "B站登录态可用",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法启动 Chromium，请先运行安装脚本：{type(exc).__name__}",
        ) from exc


@app.get("/api/v1/bilibili/session", response_model=BrowserSessionRead)
async def get_bilibili_session() -> BrowserSessionRead:
    running, authenticated = await browser.session_state()
    message = "B站登录态可用" if authenticated else "浏览器未连接或尚未登录"
    return BrowserSessionRead(running=running, authenticated=authenticated, message=message)


@app.delete("/api/v1/bilibili/session", response_model=BrowserSessionRead)
async def clear_bilibili_session() -> BrowserSessionRead:
    await browser.clear_profile()
    return BrowserSessionRead(running=False, authenticated=False, message="本地 B站登录资料已清除")


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
    return list((await session.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))).all())


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
                    yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
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
    await session.execute(delete(Report).where(Report.job_id == job_id))


@app.post("/api/v1/jobs/{job_id}/retry", response_model=JobRead)
async def retry_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status == JobStatus.AWAITING_TAPTAP_SELECTION.value:
        raise HTTPException(status_code=409, detail="请先选择 TapTap 应用")
    await _clear_job_results(job_id, session)
    job.status = JobStatus.PENDING.value
    job.stage = "等待重试"
    job.progress = 0
    job.message = ""
    job.warnings = []
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
        taptap_app_id=source.taptap_app_id,
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
async def export_pdf(job_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    await _get_report(job_id, session)
    try:
        content = await build_pdf(job_id, str(request.base_url))
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
    if full_path and requested.is_file() and requested.resolve().is_relative_to(frontend_dist.resolve()):
        return FileResponse(requested)
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"name": settings.app_name, "detail": "前端尚未构建，请运行 npm run dev 或 scripts/setup.ps1"}
    )
