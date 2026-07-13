from __future__ import annotations

import asyncio
import hashlib
import random
import re
from collections.abc import Awaitable, Callable
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
    CollectedOfficialAccount,
    CollectedVideo,
    CollectionResult,
    ProgressCallback,
    SourcePaused,
)
from .browser import BilibiliBrowserManager
from .parsers import (
    parse_bilibili_search_html,
    parse_bilibili_space_html,
    parse_bilibili_video_html,
)

DEPTHS = {
    "light": {"candidates": 10, "selected": 5, "comments": 250, "danmakus": 100},
    "standard": {"candidates": 30, "selected": 10, "comments": 1000, "danmakus": 500},
    "deep": {"candidates": 50, "selected": 20, "comments": 3000, "danmakus": 1500},
}

PersistCallback = Callable[[CollectionResult], Awaitable[None]]

COMMENT_EXTRACTOR = r"""
() => {
  const deepRoots = [document];
  const roots = [];
  const seenRoots = new Set();
  while (deepRoots.length) {
    const root = deepRoots.pop();
    if (!root || seenRoots.has(root)) continue;
    seenRoots.add(root);
    roots.push(root);
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) deepRoots.push(el.shadowRoot);
    }
  }
  const candidates = [];
    for (const root of roots) {
    for (const selector of [
      'bili-comment-renderer',
      'bili-comment-reply-renderer',
      '[data-rpid]',
      '.reply-item',
      '.sub-reply-item',
      '[class*="comment-item"]'
    ]) {
      for (const el of root.querySelectorAll(selector)) candidates.push(el);
    }
  }
  const out = [];
  const ids = new Set();
  const find = (el, selector) => el.shadowRoot?.querySelector(selector) || el.querySelector(selector);
  const attr = (el, names) => {
    for (const name of names) {
      const value = el.getAttribute?.(name) || el.dataset?.[name];
      if (value) return String(value);
    }
    return '';
  };
  for (const el of candidates) {
    const tag = el.tagName.toLowerCase();
    const cls = String(el.className || '');
    const data = el.__data || {};
    const id = String(data.rpid_str || data.rpid || attr(el, ['data-rpid', 'rpid', 'reply-id', 'data-id', 'id']) || '');
    const textEl = find(el, 'bili-rich-text, [class*="reply-content"], [class*="message"], [class*="content"], [id*="content"]');
    const text = String(data.content?.message || textEl?.shadowRoot?.textContent || textEl?.innerText || textEl?.textContent || '').trim();
    if (text.length < 2 || text.length > 20000) continue;
    const authorEl = find(el, 'bili-comment-user-info, [class*="user-name"], [class*="member"], [class*="author"]');
    const likeEl = find(el, '[class*="like"], [class*="vote"]');
    const timeEl = find(el, 'time, [class*="time"], [class*="date"]');
    const parentEl = el.closest?.('bili-comment-thread-renderer, [data-root-rpid]');
    const parentId = String(data.parent_str || data.parent || data.root_str || data.root || attr(parentEl || {}, ['data-root-rpid', 'data-rpid', 'rpid', 'data-id']) || '');
    const depth = tag.includes('reply-renderer') || /sub-reply/.test(cls) ? 1 : 0;
    const key = id || `${parentId}:${text.slice(0, 160)}`;
    if (ids.has(key)) continue;
    ids.add(key);
    out.push({
      id,
      parentId: depth ? parentId : '',
      depth,
      text,
      author: String(data.member?.uname || authorEl?.shadowRoot?.textContent || authorEl?.innerText || authorEl?.textContent || '').trim().split('\n')[0],
      likes: String(data.like ?? likeEl?.shadowRoot?.textContent ?? likeEl?.innerText ?? likeEl?.textContent ?? '').trim(),
      publishedAt: String(data.ctime || timeEl?.getAttribute?.('datetime') || timeEl?.innerText || '').trim(),
    });
  }
  return out;
}
"""

EXPAND_REPLIES = r"""
() => {
  const roots = [document];
  const seen = new Set();
  const clicked = new Set();
  let count = 0;
  while (roots.length) {
    const root = roots.pop();
    if (!root || seen.has(root)) continue;
    seen.add(root);
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (count >= 24) continue;
      const text = (el.innerText || '').trim();
      if (text.length > 30 || !/(展开|查看|更多|下一页).*(回复|评论)|^(展开|查看更多回复)$/.test(text)) continue;
      if (clicked.has(text) || el.disabled) continue;
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      clicked.add(text);
      el.click();
      count += 1;
    }
  }
  return count;
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
  return [...new Set(values)].slice(0, 10000);
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
        text = (await page.locator("body").inner_text(timeout=10_000))[:5000]
        signals = (title + " " + text).casefold()
        risk_signals = ("-352", "风控", "安全验证", "完成验证", "验证码", "captcha", "滑动验证")
        if any(signal in signals for signal in risk_signals):
            await self.manager.adopt_page("bilibili", page, risk_detected=True)
            raise SourcePaused("B站触发验证或风控，请在页面子窗口完成验证后点击重试")
        if "视频去哪了呢" in text or "请求被拦截" in text or "412" in title:
            await self.manager.adopt_page("bilibili", page, risk_detected=True)
            raise SourcePaused("B站拒绝了当前页面请求，请在页面子窗口确认登录或完成验证")

    async def collect(
        self,
        keyword: str,
        time_range: str,
        depth: str,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
        *,
        official_mid: str | None = None,
        include_discovery: bool = True,
        persist: PersistCallback | None = None,
        resume_comment_counts: dict[str, int] | None = None,
    ) -> CollectionResult:
        running, authenticated = await self.manager.session_state("bilibili")
        if not running or not authenticated:
            raise SourcePaused("请先在 B站页面子窗口完成登录")
        context = await self.manager.connect(open_login=False, platform="bilibili")
        page = await context.new_page()
        keep_page = False
        combined = CollectionResult(metrics={"bilibili": {}})
        official_ids: set[str] = set()
        try:
            if official_mid:
                official = await self._collect_official(
                    page,
                    official_mid,
                    time_range,
                    depth,
                    progress,
                    is_cancelled,
                    persist,
                    resume_comment_counts or {},
                )
                combined.official_account = official.official_account
                combined.videos.extend(official.videos)
                combined.contents.extend(official.contents)
                combined.warnings.extend(official.warnings)
                combined.metrics["bilibili"]["official"] = official.metrics.get("official", {})
                official_ids = {video.external_id for video in official.videos}

            if include_discovery and not await is_cancelled():
                discovery = await self._collect_discovery(
                    page,
                    keyword,
                    time_range,
                    depth,
                    progress,
                    is_cancelled,
                    exclude_ids=official_ids,
                )
                combined.videos.extend(discovery.videos)
                combined.contents.extend(discovery.contents)
                combined.warnings.extend(discovery.warnings)
                combined.metrics["bilibili"]["discovery"] = discovery.metrics.get(
                    "discovery", {}
                )

            unique_videos: dict[str, CollectedVideo] = {}
            for video in combined.videos:
                current = unique_videos.get(video.external_id)
                if current is None or video.source_scope == "bilibili_official":
                    unique_videos[video.external_id] = video
            combined.videos = list(unique_videos.values())
            unique_content: dict[tuple[str, str], CollectedContent] = {}
            for item in combined.contents:
                unique_content[(item.platform, item.external_id)] = item
            combined.contents = list(unique_content.values())
            combined.warnings = list(dict.fromkeys(combined.warnings))

            new_comment_count = sum(item.kind == "comment" for item in combined.contents)
            resumed_comment_count = sum(
                resume_comment_counts.get(video.external_id, 0)
                for video in combined.videos
                if video.source_scope == "bilibili_official"
            )
            comment_count = new_comment_count + resumed_comment_count
            metadata_known = any(
                (video.raw_meta or {}).get("metadata_source") in {"initial_state", "json_ld"}
                for video in combined.videos
            )
            combined.metrics["bilibili"].update(
                {
                    "comment_count": comment_count,
                    "sample_count": len(combined.contents),
                    "metadata_known": metadata_known,
                }
            )
            if combined.videos and not metadata_known:
                await self.manager.adopt_page("bilibili", page)
                keep_page = True
                raise SourcePaused("B站详情指标与发布时间未能识别，已保留页面供检查")
            if any(video.replies > 0 for video in combined.videos) and comment_count == 0:
                await self.manager.adopt_page("bilibili", page)
                keep_page = True
                raise SourcePaused("B站页面显示存在评论，但评论区未能识别，已保留页面供检查")
            self.manager.clear_risk("bilibili")
            return combined
        except SourcePaused:
            keep_page = True
            raise
        finally:
            if not keep_page and not page.is_closed():
                if self.manager.is_workspace_page("bilibili", page):
                    await self.manager.adopt_page("bilibili", context.pages[0])
                await page.close()

    async def _collect_official(
        self,
        page: Page,
        mid: str,
        time_range: str,
        depth: str,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
        persist: PersistCallback | None,
        resume_comment_counts: dict[str, int],
    ) -> CollectionResult:
        await progress("读取 B站官号", 3, f"正在读取官号 MID {mid}")
        seeds: dict[str, CollectedVideo] = {}
        account: CollectedOfficialAccount | None = None
        page_number = 1
        unchanged_pages = 0
        await page.goto(
            f"https://space.bilibili.com/{mid}/upload/video",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        while page_number <= 1000 and not await is_cancelled():
            await self._check_page(page)
            for _ in range(6):
                await page.mouse.wheel(0, 1000)
                await page.wait_for_timeout(350)
            page_account, page_videos = parse_bilibili_space_html(await page.content(), mid)
            account = account or page_account
            before = len(seeds)
            for video in page_videos:
                seeds.setdefault(video.external_id, video)
            unchanged_pages = unchanged_pages + 1 if len(seeds) == before else 0
            await progress(
                "读取 B站官号",
                min(16, 3 + page_number),
                f"已发现 {len(seeds)} 个官号视频",
            )
            if unchanged_pages >= 2 or not page_videos:
                break
            next_number = page_number + 1
            next_button = None
            numbered = page.locator("button.vui_pagenation--btn-num")
            for button_index in range(await numbered.count()):
                candidate = numbered.nth(button_index)
                if (await candidate.inner_text()).strip() == str(next_number):
                    next_button = candidate
                    break
            if next_button is None:
                side_buttons = page.locator("button.vui_pagenation--btn-side")
                if await side_buttons.count():
                    candidate = side_buttons.last
                    if not await candidate.is_disabled():
                        next_button = candidate
            if next_button is None:
                break
            previous_first = page_videos[0].external_id
            await next_button.click(timeout=5_000)
            try:
                await page.wait_for_function(
                    "([selector, previous]) => { const link = document.querySelector(selector); return link && !link.href.includes(previous); }",
                    arg=['a[href*="/video/BV"]', previous_first],
                    timeout=8_000,
                )
            except Exception:
                await page.wait_for_timeout(1_200)
            page_number += 1
            await self._delay()
        if not seeds or account is None:
            await self.manager.adopt_page("bilibili", page)
            raise SourcePaused("未能识别官号视频列表，请在页面子窗口确认页面状态")

        range_days = {"7d": 7, "30d": 30, "90d": 90, "180d": 180}.get(time_range)
        cutoff = datetime.now(timezone.utc) - timedelta(days=range_days) if range_days else None
        eligible_seeds = [
            seed
            for seed in seeds.values()
            if cutoff is None or seed.published_at is None or seed.published_at >= cutoff
        ]
        detailed: list[CollectedVideo] = []
        comments: list[CollectedContent] = []
        per_video_metrics: list[dict[str, Any]] = []
        for index, seed in enumerate(eligible_seeds):
            if await is_cancelled():
                break
            await progress(
                "采集官号视频",
                17 + int(index / max(1, len(eligible_seeds)) * 36),
                f"官号视频 {index + 1}/{len(eligible_seeds)}",
            )
            await page.goto(seed.url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            video = parse_bilibili_video_html(await page.content(), seed)
            video.source_scope = "bilibili_official"
            video.official_mid = mid
            video.raw_meta["selected"] = True
            video.raw_meta["provenance"] = ["official"]
            if cutoff and video.published_at and video.published_at < cutoff:
                continue
            detailed.append(video)
            resumed_count = resume_comment_counts.get(video.external_id)
            resumed_complete = resumed_count is not None and (
                video.replies <= 0 or resumed_count >= video.replies
            )
            if resumed_complete:
                video_comments: list[CollectedContent] = []
                collected_count = resumed_count or 0
                complete = True
            else:
                video_comments, complete = await self._collect_comments(
                    page,
                    video,
                    quota=None,
                    is_cancelled=is_cancelled,
                    exhaustive=True,
                )
                collected_count = len(video_comments)
            comments.extend(video_comments)
            metric = {
                "video_id": video.external_id,
                "expected_comments": video.replies,
                "collected_comments": collected_count,
                "complete": complete,
                "resumed": resumed_complete,
            }
            per_video_metrics.append(metric)
            if persist:
                await persist(
                    CollectionResult(
                        videos=[video],
                        contents=video_comments,
                        official_account=CollectedOfficialAccount(
                            mid=account.mid,
                            title=account.title,
                            url=account.url,
                            avatar_url=account.avatar_url,
                            expected_video_count=None,
                            collected_video_count=len(detailed),
                        ),
                        metrics={"official_checkpoint": metric},
                    )
                )
            await self._delay()

        account.expected_video_count = len(detailed)
        account.collected_video_count = len(detailed)
        complete_count = sum(bool(row["complete"]) for row in per_video_metrics)
        warnings = []
        if complete_count < len(per_video_metrics):
            warnings.append(
                f"官号评论完整采集 {complete_count}/{len(per_video_metrics)} 个视频，未完成视频可重试续采"
            )
        return CollectionResult(
            videos=detailed,
            contents=comments,
            official_account=account,
            metrics={
                "official": {
                    "expected_videos": len(detailed),
                    "collected_videos": len(detailed),
                    "expected_comments": sum(video.replies for video in detailed),
                    "collected_comments": sum(
                        int(row["collected_comments"]) for row in per_video_metrics
                    ),
                    "complete_videos": complete_count,
                    "videos": per_video_metrics,
                }
            },
            warnings=warnings,
        )

    async def _collect_discovery(
        self,
        page: Page,
        keyword: str,
        time_range: str,
        depth: str,
        progress: ProgressCallback,
        is_cancelled: CancelCallback,
        *,
        exclude_ids: set[str],
    ) -> CollectionResult:
        config = DEPTHS.get(depth, DEPTHS["standard"])
        await progress("搜索 B站相关视频", 54, f"正在搜索“{keyword}”")
        await page.goto(
            f"https://search.bilibili.com/all?keyword={quote(keyword)}",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await self._check_page(page)
        for _ in range(8):
            if await is_cancelled():
                return CollectionResult(warnings=["任务已取消"])
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(500)
        candidates = [
            video
            for video in parse_bilibili_search_html(
                await page.content(), limit=int(config["candidates"]) + len(exclude_ids)
            )
            if video.external_id not in exclude_ids
        ][: int(config["candidates"])]
        if not candidates:
            if exclude_ids:
                return CollectionResult(
                    metrics={"discovery": {"candidate_count": 0, "deduplicated": len(exclude_ids)}}
                )
            raise SourcePaused("未能从 B站可见搜索结果中识别视频，请在页面子窗口检查")

        detailed: list[CollectedVideo] = []
        for index, candidate in enumerate(candidates):
            if await is_cancelled():
                break
            await progress(
                "读取相关视频指标",
                56 + int(index / max(1, len(candidates)) * 12),
                f"相关视频 {index + 1}/{len(candidates)}",
            )
            await page.goto(candidate.url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            video = parse_bilibili_video_html(await page.content(), candidate)
            video.source_scope = "bilibili_discovery"
            video.raw_meta["provenance"] = ["discovery"]
            detailed.append(video)
            await self._delay()

        warnings: list[str] = []
        range_days = {"7d": 7, "30d": 30, "90d": 90, "180d": 180}.get(time_range)
        if range_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=range_days)
            unknown_count = sum(video.published_at is None for video in detailed)
            detailed = [
                video
                for video in detailed
                if video.published_at is None or video.published_at >= cutoff
            ]
            if unknown_count:
                warnings.append(f"{unknown_count} 个相关视频发布时间无法识别，已保留参与排名")
        if not detailed:
            return CollectionResult(
                warnings=["所选时间范围内没有相关视频"],
                metrics={"discovery": {"candidate_count": len(candidates), "selected_count": 0}},
            )

        ranked = rank_videos([asdict(video) for video in detailed], keyword)
        selected_rows = ranked[: int(config["selected"])]
        selected_ids = {str(item["external_id"]) for item in selected_rows}
        quotas = allocate_comment_quotas(selected_rows, int(config["comments"]))
        contents: list[CollectedContent] = []
        for index, row in enumerate(selected_rows):
            if await is_cancelled():
                break
            video = CollectedVideo(
                **{key: row[key] for key in CollectedVideo.__dataclass_fields__}
            )
            video.raw_meta["selection_score"] = row["selection_score"]
            video.raw_meta["relevance_score"] = row["relevance_score"]
            video.raw_meta["score_components"] = row["score_components"]
            video.raw_meta["selected"] = True
            await page.goto(video.url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            quota = quotas.get(video.external_id, 30)
            await progress(
                "采集相关视频评论",
                69 + int(index / max(1, len(selected_rows)) * 14),
                f"{video.title[:24]} · 目标 {quota} 条",
            )
            rows, _ = await self._collect_comments(
                page, video, quota, is_cancelled, exhaustive=False
            )
            contents.extend(rows)
            await self._delay()

        selected_videos = [video for video in detailed if video.external_id in selected_ids]
        per_video_danmaku = max(1, int(config["danmakus"]) // max(1, len(selected_videos)))
        for index, video in enumerate(selected_videos):
            if await is_cancelled():
                break
            await progress(
                "采集可见弹幕",
                83 + int(index / max(1, len(selected_videos)) * 7),
                f"{video.title[:24]} · 弹幕列表",
            )
            await page.goto(video.url, wait_until="domcontentloaded", timeout=45_000)
            await self._check_page(page)
            try:
                contents.extend(
                    await self._collect_danmakus(
                        page, video, per_video_danmaku, is_cancelled
                    )
                )
            except Exception as exc:
                warnings.append(f"{video.external_id} 弹幕列表未读取：{type(exc).__name__}")

        all_videos: list[CollectedVideo] = []
        for row in ranked:
            video = CollectedVideo(
                **{key: row[key] for key in CollectedVideo.__dataclass_fields__}
            )
            video.raw_meta["selection_score"] = row["selection_score"]
            video.raw_meta["relevance_score"] = row["relevance_score"]
            video.raw_meta["score_components"] = row["score_components"]
            video.raw_meta["selected"] = video.external_id in selected_ids
            all_videos.append(video)
        return CollectionResult(
            videos=all_videos,
            contents=contents,
            warnings=warnings,
            metrics={
                "discovery": {
                    "candidate_count": len(candidates),
                    "selected_count": len(selected_videos),
                    "comment_count": sum(item.kind == "comment" for item in contents),
                    "danmaku_count": sum(item.kind == "danmaku" for item in contents),
                    "deduplicated": len(exclude_ids),
                }
            },
        )

    async def _collect_comments(
        self,
        page: Page,
        video: CollectedVideo,
        quota: int | None,
        is_cancelled: CancelCallback,
        exhaustive: bool,
    ) -> tuple[list[CollectedContent], bool]:
        unique: dict[str, CollectedContent] = {}
        comment_root = page.locator("bili-comments, #commentapp, [class*=comment-container]").first
        if await comment_root.count():
            try:
                await comment_root.scroll_into_view_if_needed(timeout=4_000)
            except Exception:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        else:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
        await page.wait_for_timeout(1_200)

        modes = [("all", 1.0)] if exhaustive else [("hot", 0.6), ("new", 0.4)]
        stable = 0
        for mode, share in modes:
            stable = 0
            if mode == "new":
                newest = page.get_by_text("最新", exact=True)
                if await newest.count():
                    try:
                        await newest.first.click(timeout=3_000)
                        await page.wait_for_timeout(800)
                    except Exception:
                        pass
            target = None if quota is None else max(1, int(quota * share))
            start_count = len(unique)
            iterations = 0
            while iterations < (10_000 if exhaustive else max(8, min(80, (target or 1) // 10 + 8))):
                if await is_cancelled():
                    break
                before = len(unique)
                raw_items: list[dict[str, Any]] = await page.evaluate(COMMENT_EXTRACTOR)
                for raw in raw_items:
                    comment_text = str(raw.get("text") or "").strip()
                    if len(comment_text) < 2:
                        continue
                    external_id = str(raw.get("id") or "")
                    if not external_id:
                        external_id = hashlib.sha1(
                            f"{video.external_id}:{raw.get('parentId')}:{raw.get('author')}:{comment_text}".encode()
                        ).hexdigest()[:24]
                    unique[external_id] = CollectedContent(
                        external_id=external_id,
                        platform="bilibili",
                        kind="comment",
                        text=comment_text,
                        author=str(raw.get("author") or "") or None,
                        video_external_id=video.external_id,
                        source_scope=video.source_scope,
                        parent_external_id=str(raw.get("parentId") or "") or None,
                        reply_depth=int(raw.get("depth") or 0),
                        likes=self._parse_count(str(raw.get("likes") or "")),
                        published_at=self._parse_comment_time(str(raw.get("publishedAt") or "")),
                        raw_meta={"order": mode},
                    )
                expanded = int(await page.evaluate(EXPAND_REPLIES))
                if expanded:
                    await page.wait_for_timeout(500)
                stable = stable + 1 if len(unique) == before and expanded == 0 else 0
                expected = video.replies if exhaustive and video.replies > 0 else None
                if expected and len(unique) >= expected:
                    break
                if target and (len(unique) - start_count >= target or (quota and len(unique) >= quota)):
                    break
                if stable >= (10 if exhaustive else 5):
                    break
                await page.mouse.wheel(0, 1050)
                await page.wait_for_timeout(550)
                iterations += 1
        rows = list(unique.values()) if quota is None else list(unique.values())[:quota]
        complete = video.replies <= 0 or len(rows) >= video.replies
        return rows, complete

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
                await trigger.first.click(timeout=3_000)
                await page.wait_for_timeout(600)
            except Exception:
                pass
        values: list[str] = []
        seen: set[str] = set()
        for _ in range(max(4, min(40, quota // 15 + 4))):
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
                    f"{video.external_id}:danmaku:{index}:{text}".encode()
                ).hexdigest()[:24],
                platform="bilibili",
                kind="danmaku",
                text=text,
                video_external_id=video.external_id,
                source_scope=video.source_scope,
            )
            for index, text in enumerate(values[:quota])
        ]

    @staticmethod
    def _parse_count(value: str) -> int:
        from ..services.ranking import parse_human_count

        return parse_human_count(value)

    @staticmethod
    def _parse_comment_time(value: str) -> datetime | None:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.isdigit():
            try:
                return datetime.fromtimestamp(int(normalized), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", normalized)
        if match:
            year, month, day = (int(value) for value in match.groups())
            return datetime(year, month, day, tzinfo=timezone.utc)
        return None
