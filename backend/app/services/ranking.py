from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

RANKING_WEIGHTS = {
    "relevance": 0.32,
    "views": 0.24,
    "replies": 0.12,
    "danmakus": 0.08,
    "like_rate": 0.08,
    "coin_rate": 0.06,
    "favorite_rate": 0.05,
    "recency": 0.05,
}


def parse_human_count(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = value.strip().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([万亿]?)", text)
    if not match:
        return 0
    amount = float(match.group(1))
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return int(amount * multiplier)


def keyword_relevance(keyword: str, title: str, description: str = "") -> float:
    needle = re.sub(r"\s+", "", keyword.casefold())
    title_norm = re.sub(r"\s+", "", title.casefold())
    description_norm = re.sub(r"\s+", "", description.casefold())
    if not needle:
        return 0.0
    if title_norm == needle:
        return 1.0
    if needle in title_norm:
        return 0.92
    if needle in description_norm:
        return 0.68
    chars = set(needle)
    overlap = len(chars & set(title_norm)) / max(1, len(chars))
    return round(min(0.65, overlap * 0.65), 4)


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [0.5 if high else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def rank_videos(videos: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    if not videos:
        return []
    log_views = _minmax([math.log1p(int(video.get("views", 0))) for video in videos])
    log_replies = _minmax([math.log1p(int(video.get("replies", 0))) for video in videos])
    log_danmakus = _minmax([math.log1p(int(video.get("danmakus", 0))) for video in videos])
    like_rates = _minmax(
        [int(video.get("likes", 0)) / max(1, int(video.get("views", 0))) for video in videos]
    )
    coin_rates = _minmax(
        [int(video.get("coins", 0)) / max(1, int(video.get("views", 0))) for video in videos]
    )
    favorite_rates = _minmax(
        [
            int(video.get("favorites", 0)) / max(1, int(video.get("views", 0)))
            for video in videos
        ]
    )
    now = datetime.now(timezone.utc)
    ranked: list[dict[str, Any]] = []
    for index, video in enumerate(videos):
        published = video.get("published_at")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None
        age_days = max(0, (now - published).days) if isinstance(published, datetime) else 365
        relevance = keyword_relevance(keyword, str(video.get("title", "")), str(video.get("description", "")))
        recency = math.exp(-age_days / 180)
        components = {
            "relevance": relevance,
            "views": log_views[index],
            "replies": log_replies[index],
            "danmakus": log_danmakus[index],
            "like_rate": like_rates[index],
            "coin_rate": coin_rates[index],
            "favorite_rate": favorite_rates[index],
            "recency": recency,
        }
        score = sum(components[key] * RANKING_WEIGHTS[key] for key in RANKING_WEIGHTS)
        ranked.append({**video, "relevance_score": relevance, "selection_score": round(score, 6), "score_components": components})
    return sorted(ranked, key=lambda item: item["selection_score"], reverse=True)


def allocate_comment_quotas(
    videos: list[dict[str, Any]], total: int, minimum: int = 30, maximum: int = 200
) -> dict[str, int]:
    if not videos:
        return {}
    feasible_total = min(total, maximum * len(videos))
    quotas = {str(video["external_id"]): min(minimum, maximum) for video in videos}
    remaining = max(0, feasible_total - sum(quotas.values()))
    scores = [max(0.001, float(video.get("selection_score", 0))) for video in videos]
    score_total = sum(scores)
    while remaining > 0:
        changed = False
        for video, score in zip(videos, scores, strict=True):
            key = str(video["external_id"])
            if quotas[key] >= maximum:
                continue
            addition = max(1, round(remaining * score / score_total))
            addition = min(addition, maximum - quotas[key], remaining)
            quotas[key] += addition
            remaining -= addition
            changed = True
            if remaining <= 0:
                break
        if not changed:
            break
    return quotas
