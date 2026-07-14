from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..services.ranking import parse_human_count
from .base import CollectedApp, CollectedContent, CollectedOfficialAccount, CollectedVideo

BILI_BASE = "https://www.bilibili.com"
TAPTAP_BASE = "https://www.taptap.cn"


def _text(node: Tag | None) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _meta(soup: BeautifulSoup, key: str) -> str | None:
    node = soup.select_one(f'meta[property="{key}"], meta[name="{key}"]')
    if not node:
        return None
    content = node.get("content")
    return str(content) if content is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _assigned_json(html: str, marker: str) -> dict[str, Any]:
    start = html.find(marker)
    if start < 0:
        return {}
    start = html.find("{", start + len(marker))
    if start < 0:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(html[start:])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.string or node.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if isinstance(row, dict) and (
                row.get("@type") == "VideoObject" or row.get("uploadDate")
            ):
                return row
    return {}


def _interaction_counts(value: Any) -> dict[str, int]:
    rows = value if isinstance(value, list) else [value]
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("interactionType") or row.get("@type") or "").casefold()
        count = parse_human_count(str(row.get("userInteractionCount") or 0))
        if "watch" in kind or "view" in kind:
            result["views"] = count
        elif "like" in kind:
            result["likes"] = count
        elif "comment" in kind:
            result["replies"] = count
    return result


def _visible_datetime(value: str, now: datetime | None = None) -> datetime | None:
    current = now or datetime.now(timezone.utc)
    normalized = " ".join(value.strip().split())
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", normalized)
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    match = re.search(r"(?<!\d)(\d{1,2})[-/.月](\d{1,2})(?:日)?(?!\d)", normalized)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        for year in range(current.year, current.year - 5, -1):
            try:
                parsed = datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                continue
            if parsed <= current + timedelta(days=2):
                return parsed
        return None
    relative = re.search(r"(\d+)\s*(分钟|小时|天|周|个月|月)前", normalized)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        days = amount if unit == "天" else amount * 7 if unit == "周" else amount * 30 if unit in {"个月", "月"} else 0
        return current - (timedelta(days=days) if days else timedelta(hours=amount if unit == "小时" else 0, minutes=amount if unit == "分钟" else 0))
    if "昨天" in normalized:
        return current - timedelta(days=1)
    return None


def parse_bilibili_search_html(html: str, limit: int = 30) -> list[CollectedVideo]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[CollectedVideo] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/video/BV"]'):
        href = str(link.get("href") or "")
        match = re.search(r"/video/(BV[\w]+)", href)
        if not match or match.group(1) in seen:
            continue
        bvid = match.group(1)
        card: Tag = link
        for parent in link.parents:
            if not isinstance(parent, Tag):
                continue
            if parent.select_one("h3, .bili-video-card__info--tit, .bili-video-card__title"):
                card = parent
                break
        title_node = card.select_one(
            "h3, .bili-video-card__info--tit, .bili-video-card__title a, [title]"
        )
        title = str((title_node.get("title") if title_node else None) or _text(title_node) or link.get("title") or _text(link))
        if not title:
            continue
        text = _text(card)
        counts = re.findall(r"(?:播放|观看|弹幕|评论)?\s*([\d.]+\s*[万亿]?)", text)
        views = parse_human_count(counts[0]) if counts else 0
        danmakus = parse_human_count(counts[1]) if len(counts) > 1 else 0
        image = card.select_one("img")
        cover = None
        if image:
            cover = str(image.get("src") or image.get("data-src") or "") or None
            if cover and cover.startswith("//"):
                cover = "https:" + cover
        creator = _text(card.select_one(".bili-video-card__info--author, .up-name, [class*=author]")) or None
        results.append(
            CollectedVideo(
                external_id=bvid,
                title=title,
                url=urljoin(BILI_BASE, href),
                cover_url=cover,
                creator=creator,
                views=views,
                danmakus=danmakus,
                raw_meta={"search_text": text[:500]},
            )
        )
        seen.add(bvid)
        if len(results) >= limit:
            break
    return results


def parse_bilibili_video_html(html: str, seed: CollectedVideo) -> CollectedVideo:
    soup = BeautifulSoup(html, "html.parser")
    state = _assigned_json(html, "window.__INITIAL_STATE__")
    video_data = state.get("videoData") or state.get("videoInfo") or {}
    if not isinstance(video_data, dict):
        video_data = {}
    stat_value = video_data.get("stat")
    stat: dict[str, Any] = stat_value if isinstance(stat_value, dict) else {}
    owner_value = video_data.get("owner")
    owner: dict[str, Any] = owner_value if isinstance(owner_value, dict) else {}
    ld = _json_ld(soup)
    ld_counts = _interaction_counts(ld.get("interactionStatistic"))
    title = str(video_data.get("title") or ld.get("name") or _meta(soup, "og:title") or _text(soup.select_one("h1")) or seed.title)
    thumbnail = ld.get("thumbnailUrl")
    if isinstance(thumbnail, list):
        thumbnail = thumbnail[0] if thumbnail else None
    cover = str(video_data.get("pic") or thumbnail or _meta(soup, "og:image") or seed.cover_url or "") or None
    description = str(video_data.get("desc") or ld.get("description") or _meta(soup, "og:description") or "")
    published = (
        _parse_datetime(video_data.get("pubdate"))
        or _parse_datetime(video_data.get("ctime"))
        or _parse_datetime(ld.get("uploadDate"))
        or _parse_datetime(_meta(soup, "article:published_time"))
        or _parse_datetime(_meta(soup, "datePublished"))
        or _parse_datetime(_meta(soup, "og:pubdate"))
        or seed.published_at
    )
    body = _text(soup)

    def count_after(labels: str, fallback: int = 0) -> int:
        match = re.search(rf"(?:{labels})\s*[:：]?\s*([\d.]+\s*[万亿]?)", body)
        return parse_human_count(match.group(1)) if match else fallback

    return CollectedVideo(
        external_id=seed.external_id,
        title=title,
        url=seed.url,
        cover_url=cover,
        creator=str(owner.get("name") or seed.creator or "") or None,
        published_at=published,
        views=int(stat.get("view") or ld_counts.get("views") or count_after("播放|观看", seed.views)),
        likes=int(stat.get("like") or ld_counts.get("likes") or count_after("点赞|赞", seed.likes)),
        coins=int(stat.get("coin") or count_after("投币", seed.coins)),
        favorites=int(stat.get("favorite") or count_after("收藏", seed.favorites)),
        replies=int(stat.get("reply") or ld_counts.get("replies") or count_after("评论", seed.replies)),
        danmakus=int(stat.get("danmaku") or count_after("弹幕", seed.danmakus)),
        description=description,
        source_scope=seed.source_scope,
        official_mid=seed.official_mid,
        raw_meta={
            **seed.raw_meta,
            "description": description[:1000],
            "metadata_source": "initial_state" if video_data else "json_ld" if ld else "visible_text",
        },
    )


def parse_bilibili_space_html(
    html: str,
    mid: str,
    *,
    now: datetime | None = None,
) -> tuple[CollectedOfficialAccount, list[CollectedVideo]]:
    soup = BeautifulSoup(html, "html.parser")
    state = _assigned_json(html, "window.__INITIAL_STATE__")
    owner = state.get("spaceInfo") or state.get("upData") or state.get("userInfo") or {}
    if not isinstance(owner, dict):
        owner = {}
    meta_title = _meta(soup, "og:title") or _text(soup.select_one("h1")) or f"B站用户 {mid}"
    title = str(owner.get("name") or re.split(r"的个人空间|个人主页|[-_]", meta_title)[0]).strip()
    avatar = str(owner.get("face") or _meta(soup, "og:image") or "") or None
    account = CollectedOfficialAccount(
        mid=mid,
        title=title,
        url=f"https://space.bilibili.com/{mid}",
        avatar_url=avatar,
    )
    videos: list[CollectedVideo] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/video/BV"]'):
        href = str(link.get("href") or "")
        match = re.search(r"/video/(BV[\w]+)", href)
        if not match or match.group(1) in seen:
            continue
        bvid = match.group(1)
        card: Tag = link
        for parent in link.parents:
            if not isinstance(parent, Tag):
                continue
            if parent.select_one(".bili-video-card__title"):
                card = parent
                break
        if card is link:
            for parent in link.parents:
                if not isinstance(parent, Tag):
                    continue
                classes = {str(value) for value in (parent.get("class") or [])}
                if classes & {"bili-video-card", "video-card", "small-item"}:
                    card = parent
                    break
        title_node = card.select_one(
            ".bili-video-card__title a, h3, [class*=title] a, [title]"
        )
        video_title = str((title_node.get("title") if title_node else None) or _text(title_node) or link.get("title") or _text(link)).strip()
        if not video_title:
            continue
        image = card.select_one("img")
        cover = str(image.get("src") or image.get("data-src") or "") if image else ""
        if cover.startswith("//"):
            cover = "https:" + cover
        text = _text(card)
        published = _visible_datetime(text, now)
        counts = re.findall(r"([\d.]+\s*[万亿]?)", text)
        videos.append(
            CollectedVideo(
                external_id=bvid,
                title=video_title,
                url=urljoin(BILI_BASE, href),
                cover_url=cover or None,
                creator=title,
                published_at=published,
                views=parse_human_count(counts[0]) if counts else 0,
                source_scope="bilibili_official",
                official_mid=mid,
                raw_meta={"space_card_text": text[:500]},
            )
        )
        seen.add(bvid)
    account.collected_video_count = len(videos)
    return account, videos


def parse_taptap_search_html(html: str, limit: int = 8) -> list[CollectedApp]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[CollectedApp] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/app/"]'):
        href = str(link.get("href") or "")
        if any(part in href for part in ("/topic", "/review", "/strategy", "/game-event")):
            continue
        if link.find_parent(class_=re.compile(r"layout-header")):
            continue
        match = re.search(r"/app/(\d+)", href)
        if not match or match.group(1) in seen:
            continue
        app_id = match.group(1)
        card = (
            link.find_parent(attrs={"itemprop": "MobileApplication"})
            or link.find_parent(class_=re.compile(r"^search-list-item-app(?:-box)?$"))
            or link.find_parent(["article", "li"])
            or link
        )
        title_meta = card.select_one('meta[itemprop="name"][content]')
        title_node = card.select_one(
            '[itemprop="name"]:not(meta), .text-with-tags .text, '
            ".text-wrapper .tap-text, h2, h3, [class*=title]"
        )
        title = (
            (str(title_meta.get("content") or "") if title_meta else "")
            or _text(title_node)
            or str(link.get("title") or "")
            or _text(link)
        )
        if not title:
            continue
        image = card.select_one("img")
        cover = str(image.get("src") or image.get("data-src") or "") if image else None
        score_node = card.select_one(".tap-rating__number, [class*=rating__number]")
        score_match = re.search(r"(10|[0-9](?:\.[0-9])?)", _text(score_node))
        results.append(
            CollectedApp(
                external_id=app_id,
                title=title,
                url=f"{TAPTAP_BASE}/app/{app_id}",
                cover_url=cover,
                score=float(score_match.group(1)) if score_match else None,
            )
        )
        seen.add(app_id)
        if len(results) >= limit:
            break
    return results


def parse_taptap_app_html(html: str, seed: CollectedApp) -> CollectedApp:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("h1")) or _meta(soup, "og:title") or seed.title
    title = re.sub(r"\s+-\s+(?:安卓|iOS|游戏评价|官方).*?(?:TapTap)?$", "", title).strip()
    cover = _meta(soup, "og:image") or seed.cover_url
    body = _text(soup)
    score_node = soup.select_one(
        ".app-info-board__score, .app-info-board__rating, "
        ".app-reviews__score-wrap, [class*=score-wrap], [class*=score-value]"
    )
    score_match = re.search(
        r"(10|[0-9](?:\.[0-9])?)",
        _text(score_node),
    ) or re.search(r"(?:评分|TapTap)\s*(10|[0-9](?:\.[0-9])?)", body)
    score = float(score_match.group(1)) if score_match else seed.score
    rating_node = soup.select_one(".app-review__header-count, [class*=review-count]")
    rating_match = (
        re.search(r"([\d.]+\s*[万亿]?)\s*(?:个|条)?", _text(rating_node))
        if rating_node
        else None
    ) or re.search(r"([\d.]+\s*[万亿]?)\s*(?:个|条)?(?:评价|评分)", body)
    rating_count = parse_human_count(rating_match.group(1)) if rating_match else 0
    tags: list[dict[str, int | str]] = []
    for node in soup.select("[class*=tag]")[:30]:
        text = _text(node)
        match = re.match(r"(.+?)\s*(\d+)$", text)
        if match and len(match.group(1)) <= 20:
            tags.append({"name": match.group(1).strip(), "count": int(match.group(2))})
    return CollectedApp(
        external_id=seed.external_id,
        title=title,
        url=seed.url,
        cover_url=cover,
        score=score,
        rating_count=rating_count,
        tags=tags,
    )


def parse_taptap_reviews_html(html: str, app_id: str) -> list[CollectedContent]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select(
        '[data-e2e="review-item"], [data-review-id], article.review-item, div.review-item, div.ReviewItem'
    )
    results: list[CollectedContent] = []
    seen: set[str] = set()
    for index, card in enumerate(candidates):
        content_node = card.select_one(
            ".review-item__contents, [class*=review-content], [class*=ReviewContent], [class*=content-text], p"
        )
        text = _text(content_node)
        if len(text) < 2:
            continue
        review_link = card.select_one('a[href*="/review/"]')
        review_match = re.search(r"/review/(\d+)", str(review_link.get("href") or "")) if review_link else None
        external_id = str(
            card.get("data-review-id")
            or card.get("data-id")
            or (review_match.group(1) if review_match else f"{app_id}-{index}")
        )
        if external_id in seen:
            continue
        rating = None
        rating_node = card.select_one("[aria-label*=星], [aria-label*=分], [class*=star]")
        rating_text = str(rating_node.get("aria-label") or _text(rating_node)) if rating_node else ""
        rating_match = re.search(r"([1-5])", rating_text)
        if rating_match:
            rating = int(rating_match.group(1))
        if rating is None:
            highlight = card.select_one(".review-rate__highlight")
            style = str(highlight.get("style") or "") if highlight else ""
            width = re.search(r"width\s*:\s*([\d.]+)px", style)
            if width:
                rating = max(1, min(5, round(float(width.group(1)) / 18)))
        author = _text(
            card.select_one(".review-item__author-name, [class*=user-name], [class*=author], [class*=UserName]")
        ) or None
        like_text = _text(card.select_one(".review-vote-up, [class*=like], [class*=vote-up]"))
        results.append(
            CollectedContent(
                external_id=external_id,
                platform="taptap",
                kind="review",
                text=text,
                author=author,
                source_scope="taptap",
                rating=rating,
                likes=parse_human_count(like_text),
            )
        )
        seen.add(external_id)
    return results
