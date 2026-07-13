from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.security import (
    SESSION_COOKIE,
    LoginThrottle,
    SessionAccessMiddleware,
    SessionSigner,
)


def test_session_signer_rejects_tampering_and_expiry() -> None:
    signer = SessionSigner("secret", ttl_seconds=60)
    token = signer.issue("operator", now=100)
    assert signer.verify(token, now=120) == "operator"
    assert signer.verify(token + "x", now=120) is None
    assert signer.verify(token, now=160) is None


def test_session_middleware_returns_json_without_basic_auth_challenge() -> None:
    protected = FastAPI()
    signer = SessionSigner("secret")

    @protected.get("/api/private")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    protected.add_middleware(
        SessionAccessMiddleware,
        signer=signer,
        allowed_origins={"http://testserver"},
    )
    client = TestClient(protected)
    denied = client.get("/api/private")
    assert denied.status_code == 401
    assert "www-authenticate" not in denied.headers
    client.cookies.set(SESSION_COOKIE, signer.issue("operator"))
    assert client.get("/api/private").json() == {"ok": True}


def test_login_throttle_limits_repeated_failures() -> None:
    throttle = LoginThrottle(max_attempts=2, window_seconds=60)
    throttle.fail("client", now=10)
    assert not throttle.is_blocked("client", now=11)
    throttle.fail("client", now=12)
    assert throttle.is_blocked("client", now=13)
    assert not throttle.is_blocked("client", now=80)


def test_server_mode_refuses_to_start_without_access_password(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
        Settings(deployment_mode="server", data_dir=tmp_path, _env_file=None)
