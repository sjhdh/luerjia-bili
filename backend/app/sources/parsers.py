from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..services.ranking import parse_human_count
from .base import CollectedApp, CollectedContent, CollectedVideo

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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
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
        card = link.find_parent(["article", "div", "li"]) or link
        title_node = card.select_one("h3, .bili-video-card__info--tit, [title]")
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
    title = _meta(soup, "og:title") or _text(soup.select_one("h1")) or seed.title
    cover = _meta(soup, "og:image") or seed.cover_url
    description = _meta(soup, "og:description") or ""
    published = (
        _parse_datetime(_meta(soup, "article:published_time"))
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
        creator=seed.creator,
        published_at=published,
        views=count_after("播放|观看", seed.views),
        likes=count_after("点赞|赞", seed.likes),
        coins=count_after("投币", seed.coins),
        favorites=count_after("收藏", seed.favorites),
        replies=count_after("评论", seed.replies),
        danmakus=count_after("弹幕", seed.danmakus),
        description=description,
        raw_meta={**seed.raw_meta, "description": description[:1000]},
    )


def parse_taptap_search_html(html: str, limit: int = 8) -> list[CollectedApp]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[CollectedApp] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/app/"]'):
        href = str(link.get("href") or "")
        match = re.search(r"/app/(\d+)", href)
        if not match or match.group(1) in seen:
            continue
        app_id = match.group(1)
        card = link.find_parent(["article", "div", "li"]) or link
        title_node = card.select_one("h2, h3, [class*=title]")
        title = _text(title_node) or str(link.get("title") or "") or _text(link)
        if not title:
            continue
        image = card.select_one("img")
        cover = str(image.get("src") or image.get("data-src") or "") if image else None
        results.append(
            CollectedApp(
                external_id=app_id,
                title=title,
                url=urljoin(TAPTAP_BASE, href),
                cover_url=cover,
            )
        )
        seen.add(app_id)
        if len(results) >= limit:
            break
    return results


def parse_taptap_app_html(html: str, seed: CollectedApp) -> CollectedApp:
    soup = BeautifulSoup(html, "html.parser")
    title = _meta(soup, "og:title") or _text(soup.select_one("h1")) or seed.title
    cover = _meta(soup, "og:image") or seed.cover_url
    body = _text(soup)
    score_match = re.search(r"(?:评分|TapTap)\s*([0-9](?:\.[0-9])?)", body)
    score = float(score_match.group(1)) if score_match else seed.score
    rating_match = re.search(r"([\d.]+\s*[万亿]?)\s*(?:条)?(?:评价|评分)", body)
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
        '[data-e2e="review-item"], [data-review-id], article[class*=review], div[class*=review-item], div[class*=ReviewItem]'
    )
    results: list[CollectedContent] = []
    seen: set[str] = set()
    for index, card in enumerate(candidates):
        content_node = card.select_one("[class*=content], [class*=text], p")
        text = _text(content_node)
        if len(text) < 2:
            continue
        external_id = str(card.get("data-review-id") or card.get("data-id") or f"{app_id}-{index}")
        if external_id in seen:
            continue
        rating = None
        rating_node = card.select_one("[aria-label*=星], [aria-label*=分], [class*=star]")
        rating_text = str(rating_node.get("aria-label") or _text(rating_node)) if rating_node else ""
        rating_match = re.search(r"([1-5])", rating_text)
        if rating_match:
            rating = int(rating_match.group(1))
        author = _text(card.select_one("[class*=user-name], [class*=author], [class*=UserName]")) or None
        like_text = _text(card.select_one("[class*=like], [class*=up]"))
        results.append(
            CollectedContent(
                external_id=external_id,
                platform="taptap",
                kind="review",
                text=text,
                author=author,
                rating=rating,
                likes=parse_human_count(like_text),
            )
        )
        seen.add(external_id)
    return results
