from __future__ import annotations

import asyncio
import shutil

from playwright.async_api import BrowserContext, Playwright, async_playwright

from ..config import Settings


class BilibiliBrowserManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._context is not None

    async def connect(self, open_login: bool = True) -> BrowserContext:
        async with self._lock:
            if self._context is None:
                self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.settings.browser_profile_dir),
                    headless=self.settings.browser_headless,
                    slow_mo=self.settings.browser_slow_mo_ms,
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
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
        return True, "SESSDATA" in names

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

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
