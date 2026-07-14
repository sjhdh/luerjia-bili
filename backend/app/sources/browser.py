from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from ..config import Settings
from ..services.proxy import (
    ProxyCheck,
    ProxyManager,
    ProxyMode,
    ProxyPlatformScope,
    ProxyPoolProvider,
    ProxyProtocol,
    ProxyUnavailableError,
)

PlatformName = Literal["bilibili", "taptap"]
LOGIN_URLS: dict[PlatformName, str] = {
    "bilibili": "https://passport.bilibili.com/login",
    "taptap": "https://www.taptap.cn/",
}


@dataclass(slots=True)
class PlatformBrowser:
    context: BrowserContext | None = None
    workspace_page: Page | None = None
    risk_detected: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BilibiliBrowserManager:
    """Owns isolated persistent browser profiles and an embeddable page viewport."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proxy = ProxyManager(settings)
        self._playwright: Playwright | None = None
        self._start_lock = asyncio.Lock()
        self._sessions: dict[PlatformName, PlatformBrowser] = {
            "bilibili": PlatformBrowser(),
            "taptap": PlatformBrowser(),
        }

    @property
    def running(self) -> bool:
        return self._sessions["bilibili"].context is not None

    def _profile_dir(self, platform: PlatformName) -> Path:
        return (
            self.settings.browser_profile_dir
            if platform == "bilibili"
            else self.settings.taptap_browser_profile_dir
        )

    async def _runtime(self) -> Playwright:
        async with self._start_lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            return self._playwright

    async def connect(
        self,
        open_login: bool = False,
        platform: PlatformName = "bilibili",
    ) -> BrowserContext:
        session = self._sessions[platform]
        async with session.lock:
            if session.context is None:
                runtime = await self._runtime()
                proxy_server = await self.proxy.ensure_active(platform)
                profile = self._profile_dir(platform)
                profile.mkdir(parents=True, exist_ok=True)
                launch_args = (
                    ["--disable-dev-shm-usage", "--disable-gpu"]
                    if self.settings.deployment_mode == "server"
                    else []
                )
                session.context = await runtime.chromium.launch_persistent_context(
                    user_data_dir=str(profile),
                    headless=self.settings.browser_headless,
                    executable_path=self.settings.browser_executable_path,
                    slow_mo=self.settings.browser_slow_mo_ms,
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    args=launch_args,
                    proxy={"server": proxy_server} if proxy_server else None,
                    ignore_https_errors=self.proxy.ignore_https_errors(platform),
                )
            context = session.context
        if open_login:
            await self.start_login(platform)
        return context

    async def start_login(self, platform: PlatformName = "bilibili") -> None:
        context = await self.connect(open_login=False, platform=platform)
        session = self._sessions[platform]
        async with session.lock:
            page = session.workspace_page
            should_navigate = False
            if page is None or page.is_closed():
                blank = [item for item in context.pages if item.url in {"", "about:blank"}]
                page = blank[0] if blank else await context.new_page()
                session.workspace_page = page
                should_navigate = True
            else:
                hostname = (urlsplit(page.url).hostname or "").casefold()
                expected_host = "bilibili.com" if platform == "bilibili" else "taptap.cn"
                on_platform = hostname == expected_host or hostname.endswith(f".{expected_host}")
                should_navigate = not session.risk_detected and not on_platform
            if should_navigate:
                session.risk_detected = False
                await page.goto(LOGIN_URLS[platform], wait_until="domcontentloaded", timeout=45_000)
            if platform == "taptap" and should_navigate:
                await page.wait_for_timeout(1_000)
                account_trigger = page.locator(".user-avatar-with-menu").first
                if await account_trigger.count():
                    try:
                        await account_trigger.click(timeout=3_000)
                        await page.wait_for_timeout(600)
                    except Exception:
                        pass
                login = page.get_by_text("登录", exact=True)
                if await login.count():
                    try:
                        await login.first.click(timeout=3_000)
                        await page.wait_for_timeout(700)
                    except Exception:
                        pass
            await page.bring_to_front()

    async def start_qr_login(self) -> None:
        await self.start_login("bilibili")

    async def session_state(
        self, platform: PlatformName = "bilibili"
    ) -> tuple[bool, bool]:
        session = self._sessions[platform]
        context = session.context
        if context is None:
            return False, False
        try:
            base_url = (
                "https://www.bilibili.com/"
                if platform == "bilibili"
                else "https://www.taptap.cn/"
            )
            cookies = await context.cookies(base_url)
        except Exception:
            return True, False
        names = {str(cookie["name"]).casefold() for cookie in cookies}
        if platform == "bilibili":
            authenticated = "sessdata" in names
        else:
            authenticated = any(
                name in {"tap_sess", "taptap_token", "sessionid", "web_session"}
                or ("token" in name and name not in {"csrf_token", "x-csrf-token"})
                for name in names
            )
            page = session.workspace_page
            if not authenticated and page and not page.is_closed() and "taptap.cn" in page.url:
                try:
                    authenticated = bool(
                        await page.locator(
                            ".user-avatar-with-menu img:not(.unlogin-img), "
                            '.user-avatar-with-menu a[href*="/user/"]'
                        ).count()
                    )
                except Exception:
                    pass
        return True, authenticated

    async def workspace_state(self, platform: PlatformName) -> dict[str, object]:
        running, authenticated = await self.session_state(platform)
        session = self._sessions[platform]
        page = session.workspace_page
        if page is not None and page.is_closed():
            page = None
            session.workspace_page = None
        return {
            "platform": platform,
            "running": running,
            "authenticated": authenticated,
            "workspace_ready": page is not None,
            "current_url": page.url if page else None,
            "page_title": await page.title() if page else None,
            "risk_detected": session.risk_detected,
        }

    async def adopt_page(
        self,
        platform: PlatformName,
        page: Page,
        *,
        risk_detected: bool = False,
    ) -> None:
        session = self._sessions[platform]
        session.workspace_page = page
        session.risk_detected = risk_detected

    def is_workspace_page(self, platform: PlatformName, page: Page) -> bool:
        return self._sessions[platform].workspace_page is page and not page.is_closed()

    def clear_risk(self, platform: PlatformName) -> None:
        self._sessions[platform].risk_detected = False

    async def capture_frame(self, platform: PlatformName) -> bytes:
        session = self._sessions[platform]
        page = session.workspace_page
        if page is None or page.is_closed():
            await self.start_login(platform)
            page = self._sessions[platform].workspace_page
        assert page is not None
        async with session.lock:
            return await page.screenshot(type="jpeg", quality=75)

    async def browser_input(
        self,
        platform: PlatformName,
        event_type: str,
        *,
        x: float | None = None,
        y: float | None = None,
        action: str | None = None,
        delta_y: float | None = None,
        key: str | None = None,
        text: str | None = None,
    ) -> None:
        session = self._sessions[platform]
        page = session.workspace_page
        if page is None or page.is_closed():
            raise RuntimeError("页面子窗口尚未打开")
        async with session.lock:
            px = max(0, min(1439, round((x or 0) * 1440)))
            py = max(0, min(899, round((y or 0) * 900)))
            if event_type == "click":
                await page.mouse.click(px, py)
            elif event_type == "pointer":
                if action == "down":
                    await page.mouse.move(px, py)
                    await page.mouse.down()
                elif action == "move":
                    await page.mouse.move(px, py)
                elif action == "up":
                    await page.mouse.move(px, py)
                    await page.mouse.up()
            elif event_type == "wheel":
                await page.mouse.wheel(0, float(delta_y or 0))
            elif event_type == "key" and key:
                await page.keyboard.press(key)
            elif event_type == "text" and text is not None:
                await page.keyboard.insert_text(text)
            elif event_type == "reload":
                await page.reload(wait_until="domcontentloaded", timeout=45_000)
            elif event_type == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=45_000)
            elif event_type == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=45_000)

    async def close_platform(self, platform: PlatformName) -> None:
        session = self._sessions[platform]
        async with session.lock:
            if session.context is not None:
                await session.context.close()
            session.context = None
            session.workspace_page = None
            session.risk_detected = False

    async def close(self) -> None:
        for platform in ("bilibili", "taptap"):
            await self.close_platform(platform)
        async with self._start_lock:
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    def proxy_state(self) -> dict[str, object]:
        return self.proxy.state()

    async def configure_proxy(
        self,
        *,
        mode: ProxyMode,
        protocol: ProxyProtocol,
        country_code: str,
        pool_size: int,
        manual_proxy: str,
        pool_provider: ProxyPoolProvider,
        platform_scope: ProxyPlatformScope,
        allow_tls_interception: bool,
        auto_rotate_on_risk: bool,
        risk_rotation_limit: int,
        zdopen_app_id: str,
        zdopen_akey: str,
    ) -> dict[str, object]:
        state = await self.proxy.configure(
            mode=mode,
            protocol=protocol,
            country_code=country_code,
            pool_size=pool_size,
            manual_proxy=manual_proxy,
            pool_provider=pool_provider,
            platform_scope=platform_scope,
            allow_tls_interception=allow_tls_interception,
            auto_rotate_on_risk=auto_rotate_on_risk,
            risk_rotation_limit=risk_rotation_limit,
            zdopen_app_id=zdopen_app_id,
            zdopen_akey=zdopen_akey,
        )
        for platform in ("bilibili", "taptap"):
            await self.close_platform(platform)
        return state

    async def rotate_proxy(self) -> dict[str, object]:
        state = await self.proxy.rotate()
        for platform in ("bilibili", "taptap"):
            await self.close_platform(platform)
        return state

    async def test_proxy(
        self,
        value: str | None = None,
        protocol: ProxyProtocol | None = None,
        *,
        allow_tls_interception: bool | None = None,
        platform_scope: ProxyPlatformScope | None = None,
    ) -> ProxyCheck:
        return await self.proxy.test(
            value,
            protocol,
            allow_tls_interception=allow_tls_interception,
            platform_scope=platform_scope,
        )

    async def recover_taptap_risk(self, attempt: int) -> str | None:
        session = self._sessions["taptap"]
        enabled, limit = self.proxy.risk_rotation_policy()
        state = self.proxy.state()
        if (
            not session.risk_detected
            or not enabled
            or attempt >= limit
            or state["mode"] != "auto"
        ):
            return None
        try:
            next_state = await self.proxy.rotate()
        except ProxyUnavailableError:
            return None
        await self.close_platform("taptap")
        if next_state.get("platform_scope") == "all":
            await self.close_platform("bilibili")
        return str(next_state.get("active_proxy") or "") or None

    async def clear_profile(self, platform: PlatformName = "bilibili") -> None:
        await self.close_platform(platform)
        profile = self._profile_dir(platform).resolve()
        data_dir = self.settings.data_dir.resolve()
        if profile.parent != data_dir:
            raise RuntimeError("浏览器资料目录不在应用数据目录内")
        if profile.exists():
            shutil.rmtree(profile)

    def qr_state(self) -> tuple[bool, None]:
        return False, None

    def qr_image(self) -> None:
        return None


browser_manager: BilibiliBrowserManager | None = None


def init_browser_manager(settings: Settings) -> BilibiliBrowserManager:
    global browser_manager
    if browser_manager is None:
        browser_manager = BilibiliBrowserManager(settings)
    return browser_manager
