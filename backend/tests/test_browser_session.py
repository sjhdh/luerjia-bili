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
