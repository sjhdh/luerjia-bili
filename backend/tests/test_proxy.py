from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.services.proxy import (
    ProxyCheck,
    ProxyConfigurationError,
    ProxyManager,
)


def check(proxy: str, reachable: bool = True, latency: int = 42) -> ProxyCheck:
    return ProxyCheck(
        proxy=proxy,
        reachable=reachable,
        latency_ms=latency if reachable else None,
        exit_ip="203.0.113.8" if reachable else None,
        message="代理出口可用" if reachable else "代理不可用",
        checked_at="2026-07-13T12:00:00+00:00",
    )


def test_proxy_address_normalization_is_strict() -> None:
    assert ProxyManager.normalize_proxy("192.0.2.10:8080", "https") == "http://192.0.2.10:8080"
    assert ProxyManager.normalize_proxy("socks5://proxy.example:1080", "http") == "socks5://proxy.example:1080"
    with pytest.raises(ProxyConfigurationError, match="账号密码"):
        ProxyManager.normalize_proxy("http://user:secret@proxy.example:8080", "http")
    with pytest.raises(ProxyConfigurationError, match="路径"):
        ProxyManager.normalize_proxy("http://proxy.example:8080/path", "http")
    with pytest.raises(ProxyConfigurationError, match="端口"):
        ProxyManager.normalize_proxy("http://proxy.example:99999", "http")


async def test_manual_proxy_is_checked_and_persisted(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, _env_file=None)
    manager = ProxyManager(settings)

    async def proxy_check(server: str) -> ProxyCheck:
        return check(server)

    monkeypatch.setattr(manager, "_check_proxy", proxy_check)
    state = await manager.configure(
        mode="manual",
        protocol="https",
        country_code="cn",
        pool_size=3,
        manual_proxy="192.0.2.10:8080",
    )
    assert state["active_proxy"] == "http://192.0.2.10:8080"
    assert state["active_source"] == "manual"
    assert state["exit_ip"] == "203.0.113.8"
    assert settings.proxy_settings_path.exists()

    reloaded = ProxyManager(settings).state()
    assert reloaded["mode"] == "manual"
    assert reloaded["active_proxy"] == "http://192.0.2.10:8080"


async def test_auto_proxy_selects_a_reachable_pool_candidate(tmp_path: Path, monkeypatch) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def pool_candidates(_protocol: str, _country: str, _count: int) -> list[str]:
        return ["http://192.0.2.11:8080", "http://192.0.2.12:8080"]

    async def proxy_check(server: str) -> ProxyCheck:
        return check(server, reachable=server.endswith("12:8080"))

    monkeypatch.setattr(manager, "_pool_candidates", pool_candidates)
    monkeypatch.setattr(manager, "_check_proxy", proxy_check)
    state = await manager.configure(
        mode="auto",
        protocol="https",
        country_code="CN",
        pool_size=2,
        manual_proxy="",
    )
    assert state["active_proxy"] == "http://192.0.2.12:8080"
    assert state["active_source"] == "pool"
    assert await manager.ensure_active() == "http://192.0.2.12:8080"
