from pathlib import Path

from backend.app.sources.base import CollectedApp
from backend.app.sources.parsers import (
    parse_bilibili_search_html,
    parse_taptap_app_html,
    parse_taptap_reviews_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_bilibili_search_parser_extracts_visible_cards() -> None:
    rows = parse_bilibili_search_html((FIXTURES / "bilibili_search.html").read_text("utf-8"))
    assert [row.external_id for row in rows] == ["BV1TEST001", "BV1TEST002"]
    assert rows[0].views == 123_000
    assert rows[0].cover_url == "https://i0.hdslb.com/test-cover.jpg"


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
