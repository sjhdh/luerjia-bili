from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from ..config import Settings

QR_IMAGE_SELECTOR = ".login-scan__qrcode img"


class BilibiliBrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._login_lock = asyncio.Lock()
        self._login_page: Page | None = None
        self._qr_png: bytes | None = None
        self._qr_expires_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._context is not None

    async def connect(self, open_login: bool = True) -> BrowserContext:
        async with self._lock:
            if self._context is None:
                self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
                self._playwright = await async_playwright().start()
                launch_args = ["--disable-dev-shm-usage"] if self.settings.deployment_mode == "server" else []
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.settings.browser_profile_dir),
                    headless=self.settings.browser_headless,
                    executable_path=self.settings.browser_executable_path,
                    slow_mo=self.settings.browser_slow_mo_ms,
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    args=launch_args,
                )
            context = self._context
        if open_login:
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            if "bilibili.com" not in page.url:
                await page.goto("https://www.bilibili.com/", wait_until="domcontentloaded")
            await page.bring_to_front()
        return context

    async def session_state(self) -> tuple[bool, bool]:
        if self._context is None:
            return False, False
        try:
            cookies = await self._context.cookies("https://www.bilibili.com/")
        except Exception:
            return True, False
        names = {cookie["name"] for cookie in cookies}
        authenticated = "SESSDATA" in names
        if authenticated:
            self._qr_png = None
            self._qr_expires_at = None
        return True, authenticated

    async def start_qr_login(self) -> None:
        async with self._login_lock:
            context = await self.connect(open_login=False)
            _, authenticated = await self.session_state()
            if authenticated:
                return

            if self._login_page is None or self._login_page.is_closed():
                blank_pages = [page for page in context.pages if page.url in {"", "about:blank"}]
                self._login_page = blank_pages[0] if blank_pages else await context.new_page()
            page = self._login_page
            await page.goto(
                "https://passport.bilibili.com/login",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            qr_image = page.locator(QR_IMAGE_SELECTOR).first
            await qr_image.wait_for(state="visible", timeout=15_000)
            self._qr_png = await qr_image.screenshot(type="png")
            self._qr_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=self.settings.qr_login_ttl_seconds
            )

    def qr_state(self) -> tuple[bool, datetime | None]:
        if self._qr_png is None or self._qr_expires_at is None:
            return False, None
        if datetime.now(timezone.utc) >= self._qr_expires_at:
            self._qr_png = None
            return False, self._qr_expires_at
        return True, self._qr_expires_at

    def qr_image(self) -> bytes | None:
        ready, _ = self.qr_state()
        return self._qr_png if ready else None

    async def close(self) -> None:
        async with self._lock:
            if self._login_page is not None and not self._login_page.is_closed():
                await self._login_page.close()
                self._login_page = None
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._qr_png = None
            self._qr_expires_at = None

    async def clear_profile(self) -> None:
        await self.close()
        profile = self.settings.browser_profile_dir.resolve()
        data_dir = self.settings.data_dir.resolve()
        if profile.parent != data_dir:
            raise RuntimeError("浏览器资料目录不在应用数据目录内")
        if profile.exists():
            shutil.rmtree(profile)


browser_manager: BilibiliBrowserManager | None = None


def init_browser_manager(settings: Settings) -> BilibiliBrowserManager:
    global browser_manager
    if browser_manager is None:
        browser_manager = BilibiliBrowserManager(settings)
    return browser_manager
