import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import app, browser


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


def test_qr_login_api_never_returns_cookie_material(monkeypatch) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)

    async def start_qr_login() -> None:
        return None

    async def session_state() -> tuple[bool, bool]:
        return True, False

    monkeypatch.setattr(browser, "start_qr_login", start_qr_login)
    monkeypatch.setattr(browser, "session_state", session_state)
    monkeypatch.setattr(browser, "qr_state", lambda: (True, expires_at))
    monkeypatch.setattr(browser, "qr_image", lambda: b"\x89PNG\r\n\x1a\nfixture")

    client = TestClient(app)
    response = client.post("/api/v1/bilibili/qr-login")
    assert response.status_code == 200
    payload = response.json()
    assert payload["qr_ready"] is True
    assert "cookie" not in str(payload).casefold()
    assert "sessdata" not in str(payload).casefold()

    image = client.get("/api/v1/bilibili/qr-code.png")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"].startswith("no-store")
