import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.main import app, browser
from backend.app.models import Job, Report, ReportShare


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
