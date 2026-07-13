import time

from fastapi.testclient import TestClient

from backend.app.main import app


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
