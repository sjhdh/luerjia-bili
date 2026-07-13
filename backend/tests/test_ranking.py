from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.ranking import (
    RANKING_WEIGHTS,
    allocate_comment_quotas,
    parse_human_count,
    rank_videos,
)


def test_ranking_weights_sum_to_one() -> None:
    assert sum(RANKING_WEIGHTS.values()) == pytest.approx(1.0)


def test_human_counts() -> None:
    assert parse_human_count("12.3万") == 123_000
    assert parse_human_count("1.2亿") == 120_000_000
    assert parse_human_count("456") == 456


def test_rank_videos_prioritizes_relevance_and_engagement() -> None:
    now = datetime.now(timezone.utc)
    rows = [
        {
            "external_id": "a",
            "title": "目标游戏正式上线",
            "views": 200_000,
            "likes": 15_000,
            "coins": 4_000,
            "favorites": 3_000,
            "replies": 2_000,
            "danmakus": 5_000,
            "published_at": now,
        },
        {
            "external_id": "b",
            "title": "无关内容",
            "views": 5_000,
            "likes": 30,
            "coins": 2,
            "favorites": 1,
            "replies": 5,
            "danmakus": 3,
            "published_at": now - timedelta(days=400),
        },
    ]
    assert rank_videos(rows, "目标游戏")[0]["external_id"] == "a"


def test_comment_quota_respects_total_and_bounds() -> None:
    videos = [{"external_id": str(index), "selection_score": index + 1} for index in range(10)]
    quotas = allocate_comment_quotas(videos, 1000)
    assert sum(quotas.values()) == 1000
    assert all(30 <= value <= 200 for value in quotas.values())
