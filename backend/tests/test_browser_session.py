from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from backend.app.config import Settings
from backend.app.sources.browser import QR_IMAGE_SELECTOR, BilibiliBrowserManager


def test_bilibili_login_fixture_matches_qr_contract() -> None:
    fixture = Path(__file__).parent / "fixtures" / "bilibili_login.html"
    soup = BeautifulSoup(fixture.read_text(encoding="utf-8"), "html.parser")
    qr_image = soup.select_one(QR_IMAGE_SELECTOR)
    assert qr_image is not None
    assert str(qr_image.get("src", "")).startswith("data:image/png")


def test_qr_image_expires_without_exposing_browser_cookies(tmp_path: Path) -> None:
    manager = BilibiliBrowserManager(Settings(data_dir=tmp_path, _env_file=None))
    manager._qr_png = b"png"
    manager._qr_expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert manager.qr_image() == b"png"

    manager._qr_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert manager.qr_image() is None
