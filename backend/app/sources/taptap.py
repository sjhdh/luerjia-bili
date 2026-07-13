from __future__ import annotations

import asyncio
import difflib
import random
from urllib.parse import quote

from playwright.async_api import async_playwright

from ..config import Settings
from .base import (
    AwaitingSourceSelection,
    CancelCallback,
    CollectedApp,
    CollectionResult,
    ProgressCallback,
)
from .parsers import parse_taptap_app_html, parse_taptap_reviews_html, parse_taptap_search_html

REVIEW_LIMITS = {"light": 100, "standard": 200, "deep": 500}


class TapTapVisibleSource:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def collect(
        self,
        keyword: str,
        depth: str,
        selected_app_id: str | None,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> CollectionResult:
        review_limit = REVIEW_LIMITS.get(depth, REVIEW_LIMITS["standard"])
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                executable_path=self.settings.browser_executable_path,
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="zh-CN"
            )
            page = await context.new_page()
            try:
                await progress("匹配 TapTap 应用", 83, f"搜索“{keyword}”")
                candidates: list[CollectedApp] = []
                if selected_app_id:
                    seed = CollectedApp(
                        external_id=selected_app_id,
                        title=keyword,
                        url=f"https://www.taptap.cn/app/{selected_app_id}",
                    )
                else:
                    search_urls = [
                        f"https://www.taptap.cn/search/{quote(keyword)}",
                        f"https://www.taptap.cn/search?kw={quote(keyword)}",
                    ]
                    for search_url in search_urls:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                        await page.wait_for_timeout(900)
                        candidates = parse_taptap_search_html(await page.content())
                        if candidates:
                            break
                    if not candidates:
                        return CollectionResult(warnings=["TapTap 未找到匹配应用"])
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
                    exact = seed.title.casefold().replace(" ", "") == keyword.casefold().replace(" ", "")
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
                await page.wait_for_timeout(700)
                app = parse_taptap_app_html(await page.content(), seed)
                await progress("采集 TapTap 评价", 87, f"{app.title} · 目标 {review_limit} 条")
                await page.goto(
                    f"https://www.taptap.cn/app/{app.external_id}/review",
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                unique = {}
                for _ in range(max(12, min(70, review_limit // 8))):
                    if await is_cancelled():
                        break
                    for review in parse_taptap_reviews_html(
                        await page.content(), app.external_id
                    ):
                        unique[review.external_id] = review
                    if len(unique) >= review_limit:
                        break
                    await page.mouse.wheel(0, 1200)
                    await asyncio.sleep(random.uniform(0.7, 1.2))
                warnings = []
                if not unique:
                    warnings.append("TapTap 应用已匹配，但未识别到可见评价")
                return CollectionResult(
                    apps=[app], contents=list(unique.values())[:review_limit], warnings=warnings
                )
            finally:
                await context.close()
                await browser.close()
