import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from backend.app.database import SessionLocal
from backend.app.main import app, browser, runner
from backend.app.models import ACTIVE_JOB_STATUSES, ContentItem, Job, Report, ReportShare
from backend.app.services.proxy import ProxyCheck


def test_health_and_job_waiting_for_login() -> None:
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        created = client.post(
            "/api/v1/jobs",
            json={"keyword": "测试游戏", "time_range": "90d", "depth": "light", "analysis_mode": "local"},
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        status = "pending"
        for _ in range(20):
            response = client.get(f"/api/v1/jobs/{job_id}")
            status = response.json()["status"]
            if status == "awaiting_login":
                break
            time.sleep(0.05)
        assert status == "awaiting_login"


def test_embedded_login_api_never_returns_cookie_material(monkeypatch) -> None:
    async def start_login(_platform: str) -> None:
        return None

    async def workspace_state(platform: str) -> dict[str, object]:
        return {
            "platform": platform,
            "running": True,
            "authenticated": False,
            "workspace_ready": True,
            "current_url": "https://passport.bilibili.com/login",
            "page_title": "登录",
            "risk_detected": False,
        }

    monkeypatch.setattr(browser, "start_login", start_login)
    monkeypatch.setattr(browser, "workspace_state", workspace_state)

    client = TestClient(app)
    response = client.post("/api/v1/platforms/bilibili/workspace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_ready"] is True
    assert "cookie" not in str(payload).casefold()
    assert "sessdata" not in str(payload).casefold()


def test_proxy_configuration_api(monkeypatch) -> None:
    state = {
        "mode": "auto",
        "protocol": "https",
        "country_code": "CN",
        "pool_size": 3,
        "manual_proxy": "",
        "active_proxy": "http://192.0.2.20:8080",
        "active_source": "pool",
        "exit_ip": "203.0.113.20",
        "latency_ms": 85,
        "last_checked_at": "2026-07-13T12:00:00+00:00",
        "last_error": None,
        "pool_api": "https://proxy.scdn.io/api/get_proxy.php",
    }

    async def configure_proxy(**_values) -> dict[str, object]:
        return state

    async def test_proxy(_value, _protocol, **_kwargs) -> ProxyCheck:
        return ProxyCheck(
            proxy="http://192.0.2.20:8080",
            reachable=True,
            latency_ms=85,
            exit_ip="203.0.113.20",
            message="代理出口可用",
            checked_at="2026-07-13T12:00:00+00:00",
        )

    monkeypatch.setattr(browser, "configure_proxy", configure_proxy)
    monkeypatch.setattr(browser, "test_proxy", test_proxy)
    with TestClient(app) as client:
        configured = client.put(
            "/api/v1/proxy",
            json={
                "mode": "auto",
                "protocol": "https",
                "country_code": "CN",
                "pool_size": 3,
                "manual_proxy": "",
            },
        )
        assert configured.status_code == 200
        assert configured.json()["active_source"] == "pool"

        checked = client.post(
            "/api/v1/proxy/test",
            json={"proxy": "192.0.2.20:8080", "protocol": "https"},
        )
        assert checked.status_code == 200
        assert checked.json()["reachable"] is True
        assert checked.json()["exit_ip"] == "203.0.113.20"


async def test_reanalysis_reuses_collected_content_without_recollection(monkeypatch) -> None:
    queued: list[tuple[str, bool]] = []

    async def enqueue(job_id: str, *, analysis_only: bool = False) -> None:
        queued.append((job_id, analysis_only))

    monkeypatch.setattr(runner, "enqueue", enqueue)
    with TestClient(app) as client:
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_([status.value for status in ACTIVE_JOB_STATUSES]))
                .values(status="completed", stage="测试清理", progress=100)
            )
            job = Job(
                id="reanalyze-existing-job",
                keyword="失控进化",
                status="completed",
                analysis_mode="local",
                include_discovery=True,
                include_taptap=False,
            )
            session.add(job)
            session.add(
                ContentItem(
                    job_id=job.id,
                    platform="bilibili",
                    kind="comment",
                    source_scope="bilibili_discovery",
                    external_id="existing-comment",
                    author_hash="匿名用户 #0001",
                    text="掉帧问题已经修复，现在很流畅",
                )
            )
            session.add(Report(job_id=job.id, payload={"id": job.id, "version": "before"}))
            await session.commit()

        response = client.post(
            "/api/v1/jobs/reanalyze-existing-job/reanalyze",
            json={"analysis_mode": "full"},
        )
        assert response.status_code == 200
        assert response.json()["analysis_mode"] == "full"
        assert response.json()["progress"] == 90
        assert response.json()["collection_metrics"]["analysis_only"] is True
        assert ("reanalyze-existing-job", True) in queued

        async with SessionLocal() as session:
            stored_job = await session.get(Job, "reanalyze-existing-job")
            assert stored_job is not None
            stored_job.status = "cancelled"
            await session.commit()

        retried = client.post("/api/v1/jobs/reanalyze-existing-job/retry")
        assert retried.status_code == 200
        assert retried.json()["collection_metrics"]["analysis_only"] is True

        async with SessionLocal() as session:
            content_count = await session.scalar(
                select(func.count(ContentItem.id)).where(
                    ContentItem.job_id == "reanalyze-existing-job"
                )
            )
            report = await session.scalar(
                select(Report).where(Report.job_id == "reanalyze-existing-job")
            )
            assert content_count == 1
            assert report is not None
            assert report.payload["version"] == "before"


async def test_rerun_rejects_duplicate_active_clone(monkeypatch) -> None:
    source_id = f"rerun-source-{uuid.uuid4()}"

    async def enqueue(_job_id: str, *, analysis_only: bool = False) -> None:
        assert analysis_only is False

    monkeypatch.setattr(runner, "enqueue", enqueue)
    with TestClient(app) as client:
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_([status.value for status in ACTIVE_JOB_STATUSES]))
                .values(status="cancelled", stage="测试清理", progress=100)
            )
            session.add(
                Job(
                    id=source_id,
                    keyword="失控进化",
                    status="partial",
                    include_discovery=True,
                    include_taptap=True,
                )
            )
            await session.commit()

        first = client.post(f"/api/v1/jobs/{source_id}/rerun")
        second = client.post(f"/api/v1/jobs/{source_id}/rerun")

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["detail"] == "当前已有任务运行，请等待完成或先取消"

        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_([status.value for status in ACTIVE_JOB_STATUSES]))
                .values(status="cancelled", stage="测试清理", progress=100)
            )
            await session.commit()


async def test_retry_reopens_incomplete_sources_and_preserves_content(monkeypatch) -> None:
    job_id = f"retry-partial-{uuid.uuid4()}"
    queued: list[str] = []

    async def enqueue(current_job_id: str, *, analysis_only: bool = False) -> None:
        assert analysis_only is False
        queued.append(current_job_id)

    monkeypatch.setattr(runner, "enqueue", enqueue)
    with TestClient(app) as client:
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_([status.value for status in ACTIVE_JOB_STATUSES]))
                .values(status="cancelled", stage="测试清理", progress=100)
            )
            job = Job(
                id=job_id,
                keyword="失控进化",
                status="partial",
                official_mid="3546785396034301",
                include_discovery=True,
                include_taptap=True,
                collection_metrics={
                    "bilibili_complete": True,
                    "official_phase_complete": True,
                    "taptap_complete": True,
                    "official_checkpoint": {
                        "video_id": "BV-partial",
                        "expected_comments": 10,
                        "collected_comments": 5,
                        "complete": False,
                    },
                    "bilibili": {
                        "official": {
                            "collected_videos": 1,
                            "complete_videos": 0,
                        },
                        "discovery": {"comment_count": 1},
                    },
                },
            )
            session.add(job)
            session.add_all(
                [
                    ContentItem(
                        job_id=job_id,
                        platform="bilibili",
                        kind="comment",
                        source_scope="bilibili_official",
                        external_id="official-existing",
                        author_hash="匿名用户 #0001",
                        text="官号已有评论",
                    ),
                    ContentItem(
                        job_id=job_id,
                        platform="bilibili",
                        kind="comment",
                        source_scope="bilibili_discovery",
                        external_id="discovery-existing",
                        author_hash="匿名用户 #0002",
                        text="发现页已有评论",
                    ),
                ]
            )
            await session.commit()

        response = client.post(f"/api/v1/jobs/{job_id}/retry")

        assert response.status_code == 200
        payload = response.json()
        assert payload["collection_metrics"]["bilibili_complete"] is False
        assert payload["collection_metrics"]["official_phase_complete"] is False
        assert payload["collection_metrics"].get("discovery_phase_complete") is not False
        assert payload["collection_metrics"]["taptap_complete"] is False
        assert queued == [job_id]

        async with SessionLocal() as session:
            content_count = await session.scalar(
                select(func.count(ContentItem.id)).where(ContentItem.job_id == job_id)
            )
            stored = await session.get(Job, job_id)
            assert stored is not None
            stored.status = "cancelled"
            await session.commit()

        assert content_count == 2


async def test_report_share_is_opaque_read_only_and_revocable() -> None:
    with TestClient(app) as client:
        async with SessionLocal() as session:
            job = Job(
                id="share-job",
                keyword="分享测试",
                status="completed",
                collection_metrics={},
            )
            session.add(job)
            session.add(Report(job_id=job.id, payload={"id": job.id, "keyword": job.keyword}))
            await session.commit()

        created = client.post(
            "/api/v1/reports/share-job/shares", json={"expires_in_days": 7}
        )
        assert created.status_code == 201
        share_payload = created.json()
        token = share_payload["url"].rsplit("/", 1)[-1]
        assert len(token) >= 32

        async with SessionLocal() as session:
            stored = await session.scalar(
                select(ReportShare).where(ReportShare.id == share_payload["id"])
            )
            assert stored is not None
            assert token not in stored.token_hash

        shared = client.get(f"/api/v1/shared/reports/{token}")
        assert shared.status_code == 200
        assert shared.json()["keyword"] == "分享测试"

        revoked = client.delete(
            f"/api/v1/reports/share-job/shares/{share_payload['id']}"
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/v1/shared/reports/{token}").status_code == 404
