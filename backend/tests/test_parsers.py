from datetime import datetime, timezone
from pathlib import Path

from backend.app.sources.base import CollectedApp, CollectedVideo
from backend.app.sources.parsers import (
    parse_bilibili_search_html,
    parse_bilibili_space_html,
    parse_bilibili_video_html,
    parse_taptap_app_html,
    parse_taptap_reviews_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_bilibili_search_parser_extracts_visible_cards() -> None:
    rows = parse_bilibili_search_html((FIXTURES / "bilibili_search.html").read_text("utf-8"))
    assert [row.external_id for row in rows] == ["BV1TEST001", "BV1TEST002"]
    assert rows[0].views == 123_000
    assert rows[0].cover_url == "https://i0.hdslb.com/test-cover.jpg"


def test_bilibili_detail_parser_prefers_page_structured_metadata() -> None:
    seed = CollectedVideo(
        external_id="BV1DETAIL01",
        title="占位",
        url="https://www.bilibili.com/video/BV1DETAIL01",
    )
    row = parse_bilibili_video_html(
        (FIXTURES / "bilibili_video.html").read_text("utf-8"), seed
    )
    assert row.title == "失控进化官号实机演示"
    assert row.views == 234_567
    assert row.replies == 789
    assert row.danmakus == 456
    assert row.published_at is not None
    assert row.raw_meta["metadata_source"] == "initial_state"


def test_bilibili_space_parser_extracts_official_videos_and_dates() -> None:
    account, rows = parse_bilibili_space_html(
        (FIXTURES / "bilibili_space.html").read_text("utf-8"),
        "3546785396034301",
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    assert account.title == "失控进化官方"
    assert [row.external_id for row in rows] == ["BV1OFFICIAL1", "BV1OFFICIAL2"]
    assert all(row.source_scope == "bilibili_official" for row in rows)
    assert rows[0].published_at == datetime(2026, 7, 10, tzinfo=timezone.utc)


def test_taptap_parser_extracts_rating_tags_and_reviews() -> None:
    html = (FIXTURES / "taptap.html").read_text("utf-8")
    app = parse_taptap_app_html(
        html,
        CollectedApp(external_id="123", title="占位", url="https://www.taptap.cn/app/123"),
    )
    reviews = parse_taptap_reviews_html(html, "123")
    assert app.title == "测试游戏"
    assert app.score == 8.6
    assert app.rating_count == 12_000
    assert app.tags[0] == {"name": "画面优秀", "count": 120}
    assert [review.rating for review in reviews] == [5, 1]
