from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings
from backend.app.services.proxy import (
    ProxyCheck,
    ProxyConfigurationError,
    ProxyManager,
    ProxyUnavailableError,
    target_status_available,
)


def check(proxy: str, reachable: bool = True, latency: int = 42) -> ProxyCheck:
    return ProxyCheck(
        proxy=proxy,
        reachable=reachable,
        latency_ms=latency if reachable else None,
        exit_ip="203.0.113.8" if reachable else None,
        message="代理出口可用" if reachable else "代理不可用",
        checked_at="2026-07-13T12:00:00+00:00",
        targets={"bilibili": reachable, "taptap": reachable},
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


def test_target_probe_rejects_method_and_block_pages() -> None:
    assert target_status_available(200) is True
    assert target_status_available(302) is True
    assert target_status_available(405) is False
    assert target_status_available(429) is False


async def test_manual_proxy_is_checked_and_persisted(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, _env_file=None)
    manager = ProxyManager(settings)

    async def proxy_check(server: str, **_kwargs) -> ProxyCheck:
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
    assert state["target_results"] == {"bilibili": True, "taptap": True}
    assert settings.proxy_settings_path.exists()

    reloaded = ProxyManager(settings).state()
    assert reloaded["mode"] == "manual"
    assert reloaded["active_proxy"] == "http://192.0.2.10:8080"


async def test_auto_proxy_selects_a_reachable_pool_candidate(tmp_path: Path, monkeypatch) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def pool_candidates(
        _protocol: str, _country: str, _count: int, **_kwargs
    ) -> list[tuple[str, str]]:
        return [("http://192.0.2.11:8080", "scdn"), ("http://192.0.2.12:8080", "scdn")]

    async def proxy_check(server: str, **_kwargs) -> ProxyCheck:
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


async def test_pool_selection_isolates_a_malformed_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def pool_candidates(
        _protocol: str, _country: str, _count: int, **_kwargs
    ) -> list[tuple[str, str]]:
        return [("socks5://192.0.2.21:1080", "scdn"), ("socks5://192.0.2.22:1080", "scdn")]

    async def proxy_check(server: str, **_kwargs) -> ProxyCheck:
        if server.endswith("21:1080"):
            raise RuntimeError("malformed SOCKS reply")
        return check(server)

    monkeypatch.setattr(manager, "_pool_candidates", pool_candidates)
    monkeypatch.setattr(manager, "_check_proxy", proxy_check)
    selected = await manager._select_pool_proxy(
        "socks5",
        "CN",
        2,
        None,
        pool_provider="scdn",
        allow_tls_interception=False,
        platform_scope="taptap",
        zdopen_app_id="",
        zdopen_akey="",
    )

    assert selected.proxy == "socks5://192.0.2.22:1080"
    assert selected.reachable is True


async def test_direct_route_can_be_checked_without_a_proxy_address(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def direct_check() -> ProxyCheck:
        return check("DIRECT")

    monkeypatch.setattr(manager, "_check_direct", direct_check)
    configured = await manager.configure(
        mode="direct",
        protocol="https",
        country_code="CN",
        pool_size=5,
        manual_proxy="",
    )
    result = await manager.test()
    assert configured["active_proxy"] is None
    assert result.proxy == "DIRECT"
    assert result.targets == {"bilibili": True, "taptap": True}


async def test_socks4_port_is_not_treated_as_a_verified_login_route(tmp_path: Path) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))
    result = await manager._check_proxy("socks4://192.0.2.50:1080")
    assert result.reachable is False
    assert "TLS" in result.message


async def test_tls_interception_requires_explicit_compatibility(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"ip": "203.0.113.40"}

    class FakeClient:
        def __init__(self, *, verify: bool = True, **_kwargs) -> None:
            self.verify = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, _url, **_kwargs):
            if self.verify:
                raise httpx.ConnectError("certificate verify failed")
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    strict = await manager._check_proxy(
        "http://192.0.2.60:8080",
        allow_tls_interception=False,
        platform_scope="taptap",
    )
    compatible = await manager._check_proxy(
        "http://192.0.2.60:8080",
        allow_tls_interception=True,
        platform_scope="taptap",
    )

    assert strict.reachable is False
    assert compatible.reachable is True
    assert compatible.tls_intercepted is True
    assert "显式兼容" in compatible.message


async def test_zdopen_json_provider_uses_documented_filters(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))
    observed: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "code": "10001",
                "msg": "获取成功",
                "data": {
                    "count": 1,
                    "proxy_list": [
                        {
                            "ip": "203.0.113.61",
                            "port": 1080,
                            "protocol": "socks5",
                            "level": "高匿",
                        }
                    ],
                },
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url, *, params):
            observed["url"] = url
            observed["params"] = params
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    candidates = await manager._zdopen_candidates(
        "socks5", "CN", 5, "1234567890", "8a17ca305f683620"
    )

    assert candidates == [("socks5://203.0.113.61:1080", "zdopen")]
    assert observed["url"] == "http://www.zdopen.com/FreeProxy/Get/"
    params = observed["params"]
    assert isinstance(params, dict)
    assert params["api"] == "1234567890"
    assert params["protocol_type"] == 3
    assert params["dalu"] == 1
    assert params["return_type"] == 3


async def test_smart_pool_falls_back_to_scdn_when_zdopen_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def zdopen(*_args, **_kwargs) -> list[tuple[str, str]]:
        raise ProxyUnavailableError("ZDOpen 暂不可用")

    async def scdn(*_args, **_kwargs) -> list[tuple[str, str]]:
        return [("http://192.0.2.62:8080", "scdn")]

    monkeypatch.setattr(manager, "_zdopen_candidates", zdopen)
    monkeypatch.setattr(manager, "_scdn_candidates", scdn)
    candidates = await manager._pool_candidates(
        "https",
        "CN",
        5,
        pool_provider="smart",
        zdopen_app_id="1234567890",
        zdopen_akey="8a17ca305f683620",
    )

    assert candidates == [("http://192.0.2.62:8080", "scdn")]


async def test_proxy_state_never_returns_zdopen_akey(tmp_path: Path, monkeypatch) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))

    async def direct_check() -> ProxyCheck:
        return check("DIRECT")

    monkeypatch.setattr(manager, "_check_direct", direct_check)
    state = await manager.configure(
        mode="direct",
        protocol="https",
        country_code="CN",
        pool_size=5,
        manual_proxy="",
        zdopen_app_id="1234567890",
        zdopen_akey="8a17ca305f683620",
    )

    assert state["zdopen_configured"] is True
    assert "zdopen_akey" not in state


async def test_taptap_only_proxy_keeps_bilibili_on_direct_route(tmp_path: Path) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))
    manager._state.mode = "manual"
    manager._state.platform_scope = "taptap"
    manager._state.active_proxy = "http://192.0.2.70:8080"

    assert await manager.ensure_active("bilibili") is None
    assert await manager.ensure_active("taptap") == "http://192.0.2.70:8080"


def test_https_compatibility_only_applies_to_a_detected_intercepting_proxy(
    tmp_path: Path,
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))
    manager._state.mode = "auto"
    manager._state.platform_scope = "taptap"
    manager._state.allow_tls_interception = True

    assert manager.ignore_https_errors("taptap") is False
    manager._state.tls_intercepted = True
    assert manager.ignore_https_errors("taptap") is True
    assert manager.ignore_https_errors("bilibili") is False


async def test_pool_prefers_strict_tls_and_cools_down_failed_nodes(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ProxyManager(Settings(data_dir=tmp_path, _env_file=None))
    checks: list[str] = []

    async def pool_candidates(*_args, **_kwargs) -> list[tuple[str, str]]:
        return [
            ("http://192.0.2.80:8080", "scdn"),
            ("http://192.0.2.81:8080", "scdn"),
            ("http://192.0.2.82:8080", "scdn"),
        ]

    async def proxy_check(server: str, **_kwargs) -> ProxyCheck:
        checks.append(server)
        result = check(server, reachable=not server.endswith("82:8080"), latency=10)
        if server.endswith("80:8080"):
            result.tls_intercepted = True
        return result

    monkeypatch.setattr(manager, "_pool_candidates", pool_candidates)
    monkeypatch.setattr(manager, "_check_proxy", proxy_check)
    selected = await manager._select_pool_proxy(
        "https",
        "CN",
        2,
        None,
        pool_provider="scdn",
        allow_tls_interception=True,
        platform_scope="taptap",
        zdopen_app_id="",
        zdopen_akey="",
    )

    assert selected.proxy == "http://192.0.2.81:8080"
    assert "http://192.0.2.82:8080" in checks
    assert any(key[0].endswith("82:8080") for key in manager._rejected_until)
