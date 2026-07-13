from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from playwright.async_api import Page

from ..config import Settings
from ..services.ranking import allocate_comment_quotas, rank_videos
from .base import (
    CancelCallback,
    CollectedContent,
    CollectedVideo,
    CollectionResult,
    ProgressCallback,
    SourcePaused,
)
from .browser import BilibiliBrowserManager
from .parsers import parse_bilibili_search_html, parse_bilibili_video_html

DEPTHS = {
    "light": {"candidates": 10, "selected": 5, "comments": 250, "danmakus": 100},
    "standard": {"candidates": 30, "selected": 10, "comments": 1000, "danmakus": 500},
    "deep": {"candidates": 50, "selected": 20, "comments": 3000, "danmakus": 1500},
}

COMMENT_EXTRACTOR = r"""
() => {
  const roots = [document];
  const candidates = [];
  const seenRoots = new Set();
  while (roots.length) {
    const root = roots.pop();
    if (!root || seenRoots.has(root)) continue;
    seenRoots.add(root);
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      const cls = String(el.className || '');
      const isReply = el.hasAttribute('data-rpid') || /reply-item|comment-item|reply-wrap/.test(cls);
      if (isReply) candidates.push(el);
    }
  }
  const out = [];
  const ids = new Set();
  for (const el of candidates) {
    const id = el.getAttribute('data-rpid') || el.dataset?.id || '';
    const textEl = el.querySelector('[class*="reply-content"], [class*="message"], [class*="content"], bili-rich-text');
    const text = (textEl?.innerText || '').trim();
    if (text.length < 2) continue;
    const authorEl = el.querySelector('[class*="user-name"], [class*="member"], [class*="author"]');
    const likeEl = el.querySelector('[class*="like"]');
    const key = id || text.slice(0, 120);
    if (ids.has(key)) continue;
    ids.add(key);
    out.push({
      id,
      text,
      author: (authorEl?.innerText || '').trim(),
      likes: (likeEl?.innerText || '').trim(),
    });
  }
  return out.slice(0, 5000);
}
"""

DANMAKU_EXTRACTOR = r"""
() => {
  const roots = [document];
  const values = [];
  const seen = new Set();
  while (roots.length) {
    const root = roots.pop();
    if (!root || seen.has(root)) continue;
    seen.add(root);
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      const cls = String(el.className || '');
      if (/danmaku-info-row|dm-row|danmaku-item/.test(cls)) {
        const text = (el.innerText || '').trim().split('\n')[0];
        if (text.length > 1) values.push(text);
      }
    }
  }
  return [...new Set(values)].slice(0, 5000);
}
"""


class BilibiliVisibleSource:
    def __init__(self, settings: Settings, manager: BilibiliBrowserManager) -> None:
        self.settings = settings
        self.manager = manager

    async def _delay(self) -> None:
        await asyncio.sleep(
            random.uniform(
                self.settings.crawl_min_delay_seconds,
                self.settings.crawl_max_delay_seconds,
            )
        )

    async def _check_page(self, page: Page) -> None:
        title = await page.title()
        text = (await page.locator("body").inner_text(timeout=10_000))[:4000]
        signals = (title + " " + text).casefold()
        risk_signals = ("-352", "风控", "安全验证", "完成验证", "验证码", "captcha")
        if any(signal in signals for signal in risk_signals):
            raise SourcePaused("B站触发验证或风控，请在登录窗口中处理后重试")

    async def collect(
        self,
        keyword: str,
        time_range: str,
        depth: str,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> CollectionResult:
        running, authenticated = await self.manager.session_state()
        if not running or not authenticated:
            raise SourcePaused("请先点击“连接 B站”并在浏览器窗口中完成登录")
        config = DEPTHS.get(depth, DEPTHS["standard"])
        context = await self.manager.connect(open_login=False)
        page = await context.new_page()
        warnings: list[str] = []
        try:
            await progress("搜索 B站视频", 5, f"正在搜索“{keyword}”")
            search_url = f"https://search.bilibili.com/all?keyword={quote(keyword)}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            for _ in range(8):
                if await is_cancelled():
                    return CollectionResult(warnings=["任务已取消"])
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(500)
            candidates = parse_bilibili_search_html(
                await page.content(), limit=int(config["candidates"])
            )
            if not candidates:
                raise SourcePaused("未能从 B站可见搜索结果中识别视频，请稍后重试")

            detailed: list[CollectedVideo] = []
            for index, candidate in enumerate(candidates):
                if await is_cancelled():
                    return CollectionResult(warnings=["任务已取消"])
                await progress(
                    "读取视频指标",
                    8 + int(index / max(1, len(candidates)) * 22),
                    f"读取视频 {index + 1}/{len(candidates)}",
                )
                await page.goto(candidate.url, wait_until="domcontentloaded", timeout=45_000)
                await self._check_page(page)
                detailed.append(parse_bilibili_video_html(await page.content(), candidate))
                await self._delay()

            range_days = {"7d": 7, "30d": 30, "90d": 90, "180d": 180}.get(time_range)
            if range_days:
                cutoff = datetime.now(timezone.utc) - timedelta(days=range_days)
                known_dates = [video for video in detailed if video.published_at is not None]
                if known_dates:
                    unknown_count = sum(video.published_at is None for video in detailed)
                    detailed = [
                        video
                        for video in detailed
                        if video.published_at is None or video.published_at >= cutoff
                    ]
                    if unknown_count:
                        warnings.append(f"{unknown_count} 个视频发布时间无法识别，已保留参与排名")
                else:
                    warnings.append("视频发布时间未能从可见页面识别，时间范围未用于过滤")
            if not detailed:
                raise SourcePaused("所选时间范围内没有可分析的视频")

            ranked_dicts = rank_videos([asdict(video) for video in detailed], keyword)
            selected_dicts = ranked_dicts[: int(config["selected"])]
            selected_ids = {str(item["external_id"]) for item in selected_dicts}
            quotas = allocate_comment_quotas(selected_dicts, int(config["comments"]))
            selected: list[CollectedVideo] = []
            contents: list[CollectedContent] = []

            for index, video_data in enumerate(selected_dicts):
                if await is_cancelled():
                    return CollectionResult(videos=selected, contents=contents, warnings=["任务已取消"])
                video = CollectedVideo(
                    **{key: video_data[key] for key in CollectedVideo.__dataclass_fields__}
                )
                video.raw_meta["selection_score"] = video_data["selection_score"]
                video.raw_meta["relevance_score"] = video_data["relevance_score"]
                video.raw_meta["score_components"] = video_data["score_components"]
                selected.append(video)
                await page.goto(video.url, wait_until="domcontentloaded", timeout=45_000)
                await self._check_page(page)
                quota = quotas.get(video.external_id, 30)
                await progress(
                    "采集 B站评论",
                    32 + int(index / max(1, len(selected_dicts)) * 38),
                    f"{video.title[:24]} · 目标 {quota} 条",
                )
                comments = await self._collect_comments(page, video, quota, is_cancelled)
                contents.extend(comments)
                await self._delay()

            per_video_danmaku = max(1, int(config["danmakus"]) // max(1, len(selected)))
            for index, video in enumerate(selected):
                if await is_cancelled():
                    break
                await progress(
                    "采集可见弹幕",
                    70 + int(index / max(1, len(selected)) * 12),
                    f"{video.title[:24]} · 弹幕列表",
                )
                await page.goto(video.url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    danmakus = await self._collect_danmakus(
                        page, video, per_video_danmaku, is_cancelled
                    )
                    contents.extend(danmakus)
                except Exception as exc:
                    warnings.append(f"{video.external_id} 弹幕列表未读取：{type(exc).__name__}")
                await self._delay()

            all_videos: list[CollectedVideo] = []
            for item in ranked_dicts:
                video = CollectedVideo(
                    **{key: item[key] for key in CollectedVideo.__dataclass_fields__}
                )
                video.raw_meta["selection_score"] = item["selection_score"]
                video.raw_meta["relevance_score"] = item["relevance_score"]
                video.raw_meta["score_components"] = item["score_components"]
                video.raw_meta["selected"] = video.external_id in selected_ids
                all_videos.append(video)
            return CollectionResult(videos=all_videos, contents=contents, warnings=warnings)
        finally:
            await page.close()

    async def _collect_comments(
        self,
        page: Page,
        video: CollectedVideo,
        quota: int,
        is_cancelled: CancelCallback,
    ) -> list[CollectedContent]:
        unique: dict[str, CollectedContent] = {}
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.65)")
        await page.wait_for_timeout(1200)
        modes = [("hot", 0.6), ("new", 0.4)]
        for mode, share in modes:
            if mode == "new":
                newest = page.get_by_text("最新", exact=True)
                if await newest.count():
                    try:
                        await newest.nth(0).click(timeout=3000)
                        await page.wait_for_timeout(800)
                    except Exception:
                        pass
            target = max(1, int(quota * share))
            start_count = len(unique)
            for _ in range(max(6, min(45, target // 12 + 4))):
                if await is_cancelled():
                    break
                raw_items: list[dict[str, Any]] = await page.evaluate(COMMENT_EXTRACTOR)
                for raw in raw_items:
                    text = str(raw.get("text") or "").strip()
                    if len(text) < 2:
                        continue
                    external_id = str(raw.get("id") or "")
                    if not external_id:
                        external_id = hashlib.sha1(
                            f"{video.external_id}:{raw.get('author')}:{text}".encode("utf-8")
                        ).hexdigest()[:24]
                    unique[external_id] = CollectedContent(
                        external_id=external_id,
                        platform="bilibili",
                        kind="comment",
                        text=text,
                        author=str(raw.get("author") or "") or None,
                        video_external_id=video.external_id,
                        likes=self._parse_count(str(raw.get("likes") or "")),
                        raw_meta={"order": mode},
                    )
                if len(unique) - start_count >= target or len(unique) >= quota:
                    break
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(600)
        return list(unique.values())[:quota]

    async def _collect_danmakus(
        self,
        page: Page,
        video: CollectedVideo,
        quota: int,
        is_cancelled: CancelCallback,
    ) -> list[CollectedContent]:
        trigger = page.get_by_text("弹幕列表", exact=True)
        if await trigger.count():
            try:
                await trigger.nth(0).click(timeout=3000)
                await page.wait_for_timeout(600)
            except Exception:
                pass
        values: list[str] = []
        seen: set[str] = set()
        for _ in range(max(4, min(30, quota // 15 + 3))):
            if await is_cancelled():
                break
            batch: list[str] = await page.evaluate(DANMAKU_EXTRACTOR)
            for text in batch:
                normalized = text.strip()
                if normalized and normalized not in seen:
                    values.append(normalized)
                    seen.add(normalized)
            if len(values) >= quota:
                break
            await page.mouse.wheel(0, 650)
            await page.wait_for_timeout(350)
        return [
            CollectedContent(
                external_id=hashlib.sha1(
                    f"{video.external_id}:danmaku:{index}:{text}".encode("utf-8")
                ).hexdigest()[:24],
                platform="bilibili",
                kind="danmaku",
                text=text,
                video_external_id=video.external_id,
            )
            for index, text in enumerate(values[:quota])
        ]

    @staticmethod
    def _parse_count(value: str) -> int:
        from ..services.ranking import parse_human_count

        return parse_human_count(value)
