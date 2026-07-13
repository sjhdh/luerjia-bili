from __future__ import annotations

import httpx
import pytest

from backend.app.config import Settings
from backend.app.models import ContentItem, Job
from backend.app.services.analyzer import (
    AnalysisCancelled,
    SentimentEngine,
    _extract_keywords,
    _extract_topics,
    _rule_topic_assignments,
    analyze_job,
)
from backend.app.services.llm_analyzer import (
    LLMAnalysisResult,
    LLMAnalyzer,
    LLMLabel,
    LLMRequestError,
)


def item(item_id: int, text: str, *, sentiment: str = "neutral", likes: int = 0) -> ContentItem:
    return ContentItem(
        id=item_id,
        job_id="quality-job",
        platform="bilibili",
        kind="comment",
        source_scope="bilibili_official",
        external_id=str(item_id),
        author_hash=f"匿名用户 #{item_id:04d}",
        text=text,
        sentiment=sentiment,
        confidence=0.8,
        likes=likes,
    )


def test_local_calibration_keeps_ambiguous_and_factual_text_neutral() -> None:
    assert SentimentEngine._calibrate("[doge]", "positive", 0.99)[0] == "neutral"
    assert SentimentEngine._calibrate("这个游戏会很肝吗？", "negative", 0.82)[0] == "neutral"
    assert SentimentEngine._calibrate("挺好玩但是掉帧严重", "negative", 0.91)[0] == "neutral"
    assert SentimentEngine._calibrate("掉帧发热，已经卸载", "negative", 0.91)[0] == "negative"
    assert SentimentEngine._calibrate("太好了，真的很喜欢", "positive", 0.91)[0] == "positive"


def test_keywords_remove_chat_noise_and_keep_domain_signals() -> None:
    rows = [
        item(1, "这个游戏为什么不能玩[doge]"),
        item(2, "优化太差，手机疯狂掉帧发热", sentiment="negative"),
        item(3, "掉帧卡顿，低端机完全玩不了", sentiment="negative"),
        item(4, "外挂和非法组队一直没人处理", sentiment="negative"),
        item(5, "下线就被抄家，时间成本太高", sentiment="negative"),
        item(6, "优化后帧率稳定多了", sentiment="positive"),
        item(7, "有没有朋友知道这个问题，希望官方回复一下"),
        item(8, "弹幕只能这样建议，进去体验不了"),
    ]
    words = {row["word"] for row in _extract_keywords(rows, "失控进化")}
    assert {"优化", "掉帧"}.issubset(words)
    assert not {
        "这个",
        "为什么",
        "不能",
        "doge",
        "有没有",
        "朋友",
        "问题",
        "希望",
        "回复",
        "弹幕",
        "只能",
        "建议",
        "进去",
        "体验",
        "不了",
    }.intersection(words)


def test_business_topics_are_stable_and_risk_ranked() -> None:
    rows = [
        item(1, "掉帧卡顿发热，手机根本玩不了", sentiment="negative", likes=80),
        item(2, "优化很差，帧率不稳定", sentiment="negative", likes=30),
        item(3, "优化后已经很流畅", sentiment="positive", likes=4),
        item(4, "外挂透视和非法组队必须处罚", sentiment="negative", likes=50),
        item(5, "下线就被抄家，社畜没时间守家", sentiment="negative", likes=60),
        item(6, "Rust 还原度不错", sentiment="positive", likes=3),
        item(7, "每天必须全天在线守家，实在太肝", sentiment="negative", likes=25),
        item(8, "七天一个档期，上班族没有时间发育", sentiment="negative", likes=15),
    ]
    topics = _extract_topics(rows, _rule_topic_assignments(rows))
    names = {topic["name"] for topic in topics}
    assert "性能与设备适配" in names
    assert "时间成本与硬核门槛" in names
    assert all("doge" not in topic["name"].casefold() for topic in topics)
    assert topics[0]["risk_score"] >= topics[-1]["risk_score"]


async def test_llm_batches_are_validated_deduplicated_and_confidence_calibrated(
    monkeypatch,
) -> None:
    settings = Settings(
        data_dir="data/test-llm-quality",
        openai_base_url="https://example.test/v1",
        openai_api_key="secret",
        openai_model="gpt-5.6",
        llm_batch_size=20,
        _env_file=None,
    )
    analyzer = LLMAnalyzer(settings)
    rows = [
        item(1, "太好了，终于上线"),
        item(2, "太好了，终于上线"),
        item(3, "大技霸这一块[doge]"),
    ]
    observed_ids: list[int] = []

    async def post_json(_client, *, system, user):
        assert "every input id exactly once" in system
        observed_ids.extend(row[0] for row in user["items"])
        return {
            "rows": [
                [1, "positive", 0.96, ["community"]],
                [3, "positive", 0.55, ["experience", "other"]],
            ]
        }, {"prompt_tokens": 100, "completion_tokens": 20}

    monkeypatch.setattr(analyzer, "_post_json", post_json)
    result = await analyzer.classify(rows, keyword="失控进化")
    assert observed_ids == [1, 3]
    assert result.unique_input_count == 2
    assert result.labels[1].sentiment == "positive"
    assert result.labels[2].sentiment == "positive"
    assert result.labels[3].sentiment == "neutral"
    assert result.labels[3].topics == ["experience"]


async def test_llm_empty_topics_clear_local_keyword_false_positives(monkeypatch) -> None:
    settings = Settings(
        data_dir="data/test-llm-topic-clear",
        lightweight_analysis=True,
        openai_base_url="https://example.test/v1",
        openai_api_key="secret",
        openai_model="gpt-5.6",
        _env_file=None,
    )
    rows = [item(index, "官方说明里提到掉帧一词") for index in range(1, 4)]

    async def classify(_self, items, keyword, progress=None):
        return LLMAnalysisResult(
            labels={
                row.id: LLMLabel("neutral", 0.92, [])
                for row in items
            },
            unique_input_count=1,
            batch_count=1,
        )

    async def report(_self, **_kwargs):
        return None, None, {}

    monkeypatch.setattr(LLMAnalyzer, "classify", classify)
    monkeypatch.setattr(LLMAnalyzer, "generate_report", report)
    payload, _warnings = await analyze_job(
        settings,
        Job(
            id="topic-clear-job",
            keyword="失控进化",
            status="analyzing",
            analysis_mode="enhanced",
            include_discovery=True,
            include_taptap=False,
        ),
        [],
        [],
        rows,
    )

    assert payload["topics"] == []
    assert payload["sections"]["bilibili_official"]["topics"] == []


def test_ai_report_schema_is_normalized_and_evidence_is_bounded() -> None:
    normalized = LLMAnalyzer._normalize_report(
        {
            "executive_summary": "  结论  ",
            "findings": [
                {
                    "title": "发现",
                    "detail": "内容",
                    "evidence_ids": [1, "2", 999, "bad", 1],
                }
            ],
            "risks": [{"title": "风险", "detail": "内容", "evidence_ids": [2]}],
            "actions": [
                {
                    "priority": "p0",
                    "title": "处理",
                    "rationale": "原因",
                    "action": "动作",
                },
                {"priority": "urgent", "title": "丢弃", "rationale": "x", "action": "y"},
            ],
            "caveats": [" 样本限制 ", ""],
        },
        {1, 2},
    )

    assert normalized["executive_summary"] == "结论"
    assert normalized["findings"][0]["evidence_ids"] == [1, 2]
    assert normalized["actions"] == [
        {"priority": "P0", "title": "处理", "rationale": "原因", "action": "动作"}
    ]
    assert normalized["caveats"] == ["样本限制"]


async def test_llm_request_error_exposes_status_without_response_body() -> None:
    settings = Settings(
        data_dir="data/test-llm-error",
        openai_base_url="https://example.test/v1",
        openai_api_key="secret",
        openai_model="gpt-5.6",
        llm_max_retries=1,
        _env_file=None,
    )
    analyzer = LLMAnalyzer(settings)

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            request=request,
            json={"error": {"message": "sensitive upstream detail"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(LLMRequestError, match=r"^HTTP 401$") as captured:
            await analyzer._post_json(client, system="system", user={"items": []})

    assert "sensitive" not in str(captured.value)


async def test_enhanced_analysis_stops_after_cancellation_check(monkeypatch) -> None:
    settings = Settings(
        data_dir="data/test-llm-cancel",
        lightweight_analysis=True,
        openai_base_url="https://example.test/v1",
        openai_api_key="secret",
        openai_model="gpt-5.6",
        _env_file=None,
    )

    async def classify(_self, items, keyword, progress=None):
        assert progress is not None
        await progress(1, len(items))
        raise AssertionError("cancellation should interrupt progress")

    async def cancelled() -> bool:
        return True

    monkeypatch.setattr(LLMAnalyzer, "classify", classify)
    with pytest.raises(AnalysisCancelled):
        await analyze_job(
            settings,
            Job(
                id="cancel-analysis-job",
                keyword="失控进化",
                status="analyzing",
                analysis_mode="enhanced",
                include_discovery=True,
                include_taptap=False,
            ),
            [],
            [],
            [item(1, "优化后已经很流畅")],
            is_cancelled=cancelled,
        )


async def test_taptap_quality_scores_the_active_llm_before_rating_override(
    monkeypatch,
) -> None:
    settings = Settings(
        data_dir="data/test-llm-taptap-quality",
        lightweight_analysis=True,
        openai_base_url="https://example.test/v1",
        openai_api_key="secret",
        openai_model="gpt-5.6",
        _env_file=None,
    )
    reviews = [
        ContentItem(
            id=index,
            job_id="taptap-quality-job",
            platform="taptap",
            kind="review",
            source_scope="taptap",
            external_id=str(index),
            author_hash=f"匿名用户 #{index:04d}",
            text=text,
            rating=rating,
            likes=0,
        )
        for index, (text, rating) in enumerate(
            [("样本甲", 5), ("样本乙", 3), ("样本丙", 1)],
            start=1,
        )
    ]

    async def classify(_self, items, keyword, progress=None):
        labels = ["positive", "neutral", "negative"]
        return LLMAnalysisResult(
            labels={
                row.id: LLMLabel(labels[index], 0.95, [])
                for index, row in enumerate(items)
            },
            unique_input_count=3,
            batch_count=1,
        )

    async def report(_self, **_kwargs):
        return None, None, {}

    monkeypatch.setattr(LLMAnalyzer, "classify", classify)
    monkeypatch.setattr(LLMAnalyzer, "generate_report", report)
    payload, _warnings = await analyze_job(
        settings,
        Job(
            id="taptap-quality-job",
            keyword="失控进化",
            status="analyzing",
            analysis_mode="enhanced",
            include_discovery=False,
            include_taptap=True,
        ),
        [],
        [],
        reviews,
    )

    assert payload["model_quality"]["sample_size"] == 3
    assert payload["model_quality"]["accuracy"] == 1.0
    assert payload["model_quality"]["macro_f1"] == 1.0
