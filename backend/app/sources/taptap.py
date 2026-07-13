from __future__ import annotations

import asyncio
import difflib
import random
from urllib.parse import quote

from playwright.async_api import Page

from ..config import Settings
from .base import (
    AwaitingSourceSelection,
    CancelCallback,
    CollectedApp,
    CollectedContent,
    CollectionResult,
    ProgressCallback,
    SourcePaused,
)
from .browser import BilibiliBrowserManager
from .parsers import parse_taptap_app_html, parse_taptap_reviews_html, parse_taptap_search_html

REVIEW_LIMITS = {"light": 100, "standard": 200, "deep": 500}


class TapTapVisibleSource:
    def __init__(self, settings: Settings, manager: BilibiliBrowserManager) -> None:
        self.settings = settings
        self.manager = manager

    async def _check_page(self, page: Page) -> None:
        title = await page.title()
        body = (await page.locator("body").inner_text(timeout=10_000))[:5000]
        signals = (title + " " + body).casefold()
        if any(
            marker in signals
            for marker in ("安全验证", "验证码", "captcha", "滑动验证", "访问过于频繁")
        ):
            await self.manager.adopt_page("taptap", page, risk_detected=True)
            raise SourcePaused("TapTap 触发验证，请在页面子窗口完成处理后点击重试")

    async def collect(
        self,
        keyword: str,
        depth: str,
        selected_app_id: str | None,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
        *,
        selected_app_url: str | None = None,
    ) -> CollectionResult:
        review_limit = REVIEW_LIMITS.get(depth, REVIEW_LIMITS["standard"])
        context = await self.manager.connect(open_login=False, platform="taptap")
        page = await context.new_page()
        keep_page = False
        try:
            await progress("匹配 TapTap 应用", 91, f"搜索“{keyword}”")
            if selected_app_id:
                seed = CollectedApp(
                    external_id=selected_app_id,
                    title=keyword,
                    url=selected_app_url or f"https://www.taptap.cn/app/{selected_app_id}",
                )
            else:
                candidates: list[CollectedApp] = []
                for search_url in (
                    f"https://www.taptap.cn/search/{quote(keyword)}",
                    f"https://www.taptap.cn/search?kw={quote(keyword)}",
                ):
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                    await self._check_page(page)
                    await page.wait_for_timeout(1_200)
                    candidates = parse_taptap_search_html(await page.content())
                    if candidates:
                        break
                if not candidates:
                    return CollectionResult(
                        warnings=["TapTap 网页搜索未返回应用，请在新任务中填写 TapTap 应用地址"],
                        metrics={"taptap": {"available": False, "review_count": 0}},
                    )
                scored = sorted(
                    [
                        (
                            difflib.SequenceMatcher(
                                None,
                                keyword.casefold().replace(" ", ""),
                                candidate.title.casefold().replace(" ", ""),
                            ).ratio(),
                            candidate,
                        )
                        for candidate in candidates
                    ],
                    key=lambda item: item[0],
                    reverse=True,
                )
                top_score, seed = scored[0]
                gap = top_score - scored[1][0] if len(scored) > 1 else top_score
                exact = seed.title.casefold().replace(" ", "") == keyword.casefold().replace(
                    " ", ""
                )
                if not exact and not (top_score >= 0.78 and gap >= 0.15):
                    raise AwaitingSourceSelection(
                        [
                            {
                                "id": candidate.external_id,
                                "title": candidate.title,
                                "url": candidate.url,
                                "cover_url": candidate.cover_url,
                                "match_score": round(score, 4),
                            }
                            for score, candidate in scored[:6]
                        ]
                    )

            await page.goto(seed.url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            await page.wait_for_timeout(900)
            app = parse_taptap_app_html(await page.content(), seed)
            await progress("采集 TapTap 评价", 94, f"{app.title} · 目标 {review_limit} 条")
            await page.goto(
                f"https://www.taptap.cn/app/{app.external_id}/review",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            await self._check_page(page)
            unique: dict[str, CollectedContent] = {}
            stable = 0
            for _ in range(max(20, min(160, review_limit // 6 + 20))):
                if await is_cancelled():
                    break
                before = len(unique)
                for review in parse_taptap_reviews_html(await page.content(), app.external_id):
                    unique[review.external_id] = review
                if len(unique) >= review_limit:
                    break
                next_button = page.locator(".app-reviews__next").first
                clicked = False
                if await next_button.count():
                    try:
                        await next_button.click(timeout=3_000)
                        await page.wait_for_timeout(1_600)
                        clicked = True
                    except Exception:
                        pass
                if not clicked:
                    await page.mouse.wheel(0, 1300)
                    await asyncio.sleep(random.uniform(0.6, 1.0))
                stable = stable + 1 if len(unique) == before else 0
                if stable >= 6:
                    break
            warnings = []
            if not unique:
                await self.manager.adopt_page("taptap", page)
                keep_page = True
                raise SourcePaused("TapTap 应用已匹配，但评价列表未能识别，已保留页面供检查")
            if len(unique) < review_limit:
                warnings.append(f"TapTap 目标 {review_limit} 条，实际采集 {len(unique)} 条可见评价")
            self.manager.clear_risk("taptap")
            return CollectionResult(
                apps=[app],
                contents=list(unique.values())[:review_limit],
                warnings=warnings,
                metrics={
                    "taptap": {
                        "available": True,
                        "target_reviews": review_limit,
                        "review_count": min(len(unique), review_limit),
                    }
                },
            )
        except SourcePaused:
            keep_page = True
            raise
        finally:
            if not keep_page and not page.is_closed():
                await page.close()
