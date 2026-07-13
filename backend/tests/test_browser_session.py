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

    async def active_proxy():
        return "http://192.0.2.30:8080"

    monkeypatch.setattr(manager, "_runtime", runtime)
    monkeypatch.setattr(manager.proxy, "ensure_active", active_proxy)
    context = await manager.connect(platform="bilibili")
    assert context is fake_context
    assert captured["proxy"] == {"server": "http://192.0.2.30:8080"}
