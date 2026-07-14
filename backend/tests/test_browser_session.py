from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.app.sources.browser import BilibiliBrowserManager


def test_platform_browser_profiles_are_isolated(tmp_path: Path) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    assert manager._profile_dir("bilibili") == tmp_path / "browser-profile"
    assert manager._profile_dir("taptap") == tmp_path / "taptap-browser-profile"
    assert manager._profile_dir("bilibili") != manager._profile_dir("taptap")


async def test_unstarted_platform_sessions_do_not_claim_authentication(tmp_path: Path) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    assert await manager.session_state("bilibili") == (False, False)
    assert await manager.session_state("taptap") == (False, False)


async def test_new_browser_context_uses_the_active_proxy(tmp_path: Path, monkeypatch) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    captured: dict[str, object] = {}
    fake_context = object()

    class FakeChromium:
        async def launch_persistent_context(self, **kwargs):
            captured.update(kwargs)
            return fake_context

    class FakeRuntime:
        chromium = FakeChromium()

    async def runtime():
        return FakeRuntime()

    async def active_proxy(_platform):
        return "http://192.0.2.30:8080"

    monkeypatch.setattr(manager, "_runtime", runtime)
    monkeypatch.setattr(manager.proxy, "ensure_active", active_proxy)
    context = await manager.connect(platform="bilibili")
    assert context is fake_context
    assert captured["proxy"] == {"server": "http://192.0.2.30:8080"}


async def test_taptap_risk_can_rotate_an_auto_proxy_once(
    tmp_path: Path, monkeypatch
) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    manager.proxy._state.mode = "auto"
    manager.proxy._state.auto_rotate_on_risk = True
    manager.proxy._state.risk_rotation_limit = 2
    manager._sessions["taptap"].risk_detected = True
    closed: list[str] = []

    async def rotate() -> dict[str, object]:
        return {
            "active_proxy": "http://192.0.2.31:8080",
            "platform_scope": "taptap",
        }

    async def close_platform(platform: str) -> None:
        closed.append(platform)

    monkeypatch.setattr(manager.proxy, "rotate", rotate)
    monkeypatch.setattr(manager, "close_platform", close_platform)

    assert await manager.recover_taptap_risk(0) == "http://192.0.2.31:8080"
    assert closed == ["taptap"]
    assert await manager.recover_taptap_risk(2) is None


async def test_taptap_route_timeout_can_rotate_without_a_risk_page(
    tmp_path: Path, monkeypatch
) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    manager.proxy._state.mode = "auto"
    manager.proxy._state.auto_rotate_on_risk = True
    manager.proxy._state.risk_rotation_limit = 1
    manager._sessions["taptap"].risk_detected = False

    async def rotate() -> dict[str, object]:
        return {
            "active_proxy": "http://192.0.2.32:8080",
            "platform_scope": "taptap",
        }

    async def close_platform(_platform: str) -> None:
        return None

    monkeypatch.setattr(manager.proxy, "rotate", rotate)
    monkeypatch.setattr(manager, "close_platform", close_platform)

    assert await manager.recover_taptap_risk(
        0, route_failure=True
    ) == "http://192.0.2.32:8080"


async def test_existing_risk_page_is_not_replaced_when_workspace_reopens(
    tmp_path: Path, monkeypatch
) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    calls = {"goto": 0, "front": 0}

    class FakePage:
        url = "https://captcha.example.test/verify"

        def is_closed(self) -> bool:
            return False

        async def goto(self, *_args, **_kwargs) -> None:
            calls["goto"] += 1

        async def bring_to_front(self) -> None:
            calls["front"] += 1

    class FakeContext:
        pages: list[object] = []

    page = FakePage()
    manager._sessions["taptap"].workspace_page = page  # type: ignore[assignment]
    manager._sessions["taptap"].risk_detected = True

    async def connect(*_args, **_kwargs):
        return FakeContext()

    monkeypatch.setattr(manager, "connect", connect)
    await manager.start_login("taptap")
    assert calls == {"goto": 0, "front": 1}
    assert manager._sessions["taptap"].risk_detected is True
