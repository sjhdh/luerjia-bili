from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.security import SharedAccessMiddleware, basic_authorization_is_valid


def authorization(username: str, password: str) -> bytes:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}".encode()


def test_shared_access_credentials_use_exact_constant_time_comparison() -> None:
    assert basic_authorization_is_valid(authorization("operator", "secret"), "operator", "secret")
    assert not basic_authorization_is_valid(
        authorization("operator", "wrong"), "operator", "secret"
    )
    assert not basic_authorization_is_valid(b"Bearer token", "operator", "secret")
    assert not basic_authorization_is_valid(b"Basic malformed", "operator", "secret")


def test_shared_access_middleware_challenges_and_accepts_browser_auth() -> None:
    protected = FastAPI()

    @protected.get("/")
    async def index() -> dict[str, bool]:
        return {"ok": True}

    protected.add_middleware(
        SharedAccessMiddleware,
        username="operator",
        password="secret",
    )
    client = TestClient(protected)
    denied = client.get("/")
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"].startswith("Basic")
    assert client.get("/", auth=("operator", "secret")).json() == {"ok": True}


def test_server_mode_refuses_to_start_without_access_password(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
        Settings(deployment_mode="server", data_dir=tmp_path, _env_file=None)
