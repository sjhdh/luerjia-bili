from __future__ import annotations

import asyncio
import math
import re
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import jieba
import jieba.posseg as pseg
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

from ..config import Settings
from ..models import ContentItem, Job, OfficialAccount, SourceApp, Video
from .llm_analyzer import PROMPT_VERSION, LLMAnalyzer
from .privacy import sanitize_text

SENTIMENTS = ("positive", "neutral", "negative")
SENTIMENT_CN = {"positive": "正面", "neutral": "中性", "negative": "负面"}
POSITIVE_WORDS = {
    "好玩", "优秀", "喜欢", "流畅", "惊喜", "推荐", "良心", "期待", "不错", "有趣", "支持",
    "跟手", "还原", "上头", "爱了", "真香", "满意", "舒服", "进步", "稳定",
}
NEGATIVE_WORDS = {
    "垃圾", "失望", "卡顿", "掉帧", "外挂", "举报", "氪金", "发热", "闪退", "恶心", "无聊",
    "劝退", "误判", "封号", "红温", "退游", "卸载", "一坨", "半成品", "崩溃", "霸凌",
    "不公平", "不友好", "受罪", "折磨", "玩不了", "火不了", "吐了",
}
STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "也", "都", "就", "和", "在", "有", "不", "这", "那",
    "一个", "没有", "什么", "还是", "但是", "游戏", "视频", "感觉", "真的", "可以", "就是", "比较", "非常",
    "这个", "那个", "一下", "时候", "然后", "还有", "怎么", "为什么", "因为", "如果", "我们", "他们", "自己",
    "现在", "直接", "不能", "不是", "不会", "知道", "觉得", "进行", "能够", "已经", "需要", "里面", "东西",
    "不了", "只能", "只要", "可能", "应该", "也许", "希望", "建议", "问题", "请问", "求问", "有人", "有没有",
    "大家", "朋友", "兄弟", "大佬", "世界", "这里", "这样", "这么", "有点", "进去", "出来", "对面", "明白",
    "回复", "评论", "弹幕", "多少", "体验",
    "官方", "玩家", "手机", "模式", "测试", "上线", "失控", "进化", "rust", "doge", "吃瓜", "大哭", "笑哭",
    "星星", "思考", "打call", "链接", "隐藏", "三连", "第一", "哈哈", "哈哈哈", "666", "啊啊", "一点",
}

TOPIC_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "performance",
        "label": "性能与设备适配",
        "keywords": ("性能", "优化", "掉帧", "卡顿", "发热", "闪退", "黑屏", "帧率", "配置", "机型", "内存", "设备不支持", "旧包体", "服务器", "延迟", "ping"),
    },
    {
        "id": "fairness",
        "label": "新手发育与匹配公平",
        "keywords": ("新手", "萌新", "匹配", "单排", "独狼", "小团体", "以多打少", "以大欺小", "服霸", "发育", "公平"),
    },
    {
        "id": "anti_abuse",
        "label": "外挂、组队与处罚",
        "keywords": ("外挂", "开挂", "透视", "锁头", "自瞄", "非法组队", "反作弊", "封禁", "封号", "误判", "举报", "申诉", "判罚", "处罚"),
    },
    {
        "id": "time_cost",
        "label": "时间成本与硬核门槛",
        "keywords": ("时间成本", "在线", "全天", "社畜", "七天", "7天", "偷家", "拆家", "抄家", "守家", "下线", "进度", "档期", "肝", "劝退"),
    },
    {
        "id": "monetization",
        "label": "商业化、皮肤与继承",
        "keywords": ("氪金", "充值", "付费", "皮肤", "商城", "抽卡", "战令", "月卡", "继承", "豪宅", "跑车"),
    },
    {
        "id": "experience",
        "label": "操作、建造与交互",
        "keywords": ("手感", "操作", "建造", "交互", "射击", "移动", "按键", "搓玻璃", "一键盖家", "领地柜", "科技UI", "建造UI", "电力UI"),
    },
    {
        "id": "visual_audio",
        "label": "画质、音效与表现",
        "keywords": ("画质", "画面", "音效", "建模", "光影", "美术", "贴图", "黑夜", "亮度", "特效"),
    },
    {
        "id": "rust_identity",
        "label": "Rust 还原与产品差异",
        "keywords": ("rust", "还原", "端游", "国服", "正版", "复刻", "移植", "原创", "差异", "soc"),
    },
    {
        "id": "community",
        "label": "社交与社区环境",
        "keywords": ("队友", "社交", "骂人", "压力", "霸凌", "游戏环境", "组队", "搭子", "世界麦", "公屏", "保护费", "小队"),
    },
)

TOPIC_BY_ID = {topic["id"]: topic for topic in TOPIC_DEFINITIONS}
DOMAIN_PHRASES = tuple(
    dict.fromkeys(
        keyword.casefold()
        for topic in TOPIC_DEFINITIONS
        for keyword in topic["keywords"]
        if len(keyword) >= 2
    )
)
BRACKET_EMOJI = re.compile(r"\[[^\]]{1,30}\]")
LINK_MARKER = re.compile(r"\[链接已隐藏\]|https?://\S+", re.IGNORECASE)

AnalysisProgress = Callable[[int, str], Awaitable[None]]
CancellationCheck = Callable[[], Awaitable[bool]]


class AnalysisCancelled(RuntimeError):
    pass


class SentimentEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline: Any | None = None
        self._load_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self.settings.local_model_id

    @property
    def warning(self) -> str | None:
        return self._load_error

    async def predict(self, texts: list[str]) -> list[tuple[str, float]]:
        if not texts:
            return []
        if self.settings.lightweight_analysis:
            return [self._lexical_predict(text) for text in texts]
        async with self._lock:
            if self._pipeline is None and self._load_error is None:
                try:
                    self._pipeline = await asyncio.to_thread(self._load_pipeline)
                except Exception as exc:
                    self._load_error = f"本地模型加载失败，已使用词典降级：{type(exc).__name__}"
        if self._pipeline is None:
            return [self._lexical_predict(text) for text in texts]
        try:
            return await asyncio.to_thread(self._predict_pipeline, texts)
        except Exception as exc:
            self._load_error = f"本地模型推理失败，已使用词典降级：{type(exc).__name__}"
            return [self._lexical_predict(text) for text in texts]

    def _load_pipeline(self) -> Any:
        from transformers import pipeline

        return pipeline(
            "text-classification",
            model=self.settings.local_model_id,
            revision=self.settings.local_model_revision,
            tokenizer=self.settings.local_model_id,
            top_k=None,
            device=-1,
        )

    def _predict_pipeline(self, texts: list[str]) -> list[tuple[str, float]]:
        pipeline_instance = self._pipeline
        assert pipeline_instance is not None
        outputs = pipeline_instance(
            texts,
            batch_size=self.settings.model_batch_size,
            truncation=True,
            max_length=256,
        )
        predictions: list[tuple[str, float]] = []
        for output in outputs:
            rows = output if isinstance(output, list) else [output]
            best = max(rows, key=lambda item: float(item["score"]))
            label = str(best["label"]).casefold()
            mapped = next((item for item in SENTIMENTS if item in label), None)
            if mapped is None:
                label_id = label.replace("label_", "")
                mapped = {"0": "negative", "1": "neutral", "2": "positive"}.get(label_id, "neutral")
            predictions.append(self._calibrate(texts[len(predictions)], mapped, float(best["score"])))
        return predictions

    @staticmethod
    def _calibrate(text: str, label: str, confidence: float) -> tuple[str, float]:
        content = LINK_MARKER.sub(" ", BRACKET_EMOJI.sub(" ", text)).strip()
        positive = sum(word in content for word in POSITIVE_WORDS)
        negative = sum(word in content for word in NEGATIVE_WORDS)
        factual = bool(
            re.search(r"(先帮您同步|配置要求|排查一下|请确认|客户端与测试包|公告|预下载)", content)
        )
        question_only = bool(re.search(r"[?？]", content)) and not positive and not negative
        ambiguous_short = len(re.sub(r"\W+", "", content)) <= 5 and not positive and not negative
        if factual or question_only or ambiguous_short or (positive and negative):
            return "neutral", round(max(0.52, 1 - confidence * 0.35), 6)
        if confidence < 0.58:
            return "neutral", round(max(0.52, confidence), 6)
        if label == "negative" and not negative and confidence < 0.74:
            return "neutral", round(max(0.52, confidence), 6)
        if label == "positive" and not positive and confidence < 0.62:
            return "neutral", round(max(0.52, confidence), 6)
        return label, round(confidence, 6)

    @staticmethod
    def _lexical_predict(text: str) -> tuple[str, float]:
        content = LINK_MARKER.sub(" ", BRACKET_EMOJI.sub(" ", text)).strip()
        positive = sum(word in content for word in POSITIVE_WORDS)
        negative = sum(word in content for word in NEGATIVE_WORDS)
        if len(re.sub(r"\W+", "", content)) <= 5 or (
            re.search(r"[?？]", content) and not positive and not negative
        ):
            return "neutral", 0.64
        if positive > negative:
            return "positive", min(0.9, 0.58 + 0.08 * (positive - negative))
        if negative > positive:
            return "negative", min(0.9, 0.58 + 0.08 * (negative - positive))
        return "neutral", 0.52


def _distribution(items: list[ContentItem]) -> dict[str, Any]:
    counts = Counter(item.sentiment or "neutral" for item in items)
    total = sum(counts.values())
    return {
        "total": total,
        "available": total > 0,
        "items": [
            {
                "name": key,
                "label": SENTIMENT_CN[key],
                "count": counts[key],
                "percentage": round(counts[key] / total * 100, 1) if total else 0,
            }
            for key in SENTIMENTS
        ],
    }


def _blend_bilibili(comments: dict[str, Any], danmakus: dict[str, Any]) -> dict[str, Any]:
    if not comments["total"]:
        return danmakus
    if not danmakus["total"]:
        return comments
    items = []
    for index, key in enumerate(SENTIMENTS):
        percentage = comments["items"][index]["percentage"] * 0.8 + danmakus["items"][index]["percentage"] * 0.2
        items.append(
            {
                "name": key,
                "label": SENTIMENT_CN[key],
                "count": comments["items"][index]["count"] + danmakus["items"][index]["count"],
                "percentage": round(percentage, 1),
            }
        )
    return {
        "total": comments["total"] + danmakus["total"],
        "available": True,
        "items": items,
        "weighted": True,
    }


def _clean_analysis_text(text: str) -> str:
    return re.sub(r"\s+", " ", LINK_MARKER.sub(" ", BRACKET_EMOJI.sub(" ", text))).strip()


def _keyword_exclusions(keyword: str) -> set[str]:
    values = {keyword.casefold().replace(" ", "")}
    values.update(token.casefold() for token in jieba.lcut(keyword) if len(token.strip()) >= 2)
    return values


def _extract_keywords(
    items: list[ContentItem], keyword: str = "", limit: int = 25
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    negative_counts: Counter[str] = Counter()
    phrase_terms = set(DOMAIN_PHRASES)
    exclusions = STOPWORDS | _keyword_exclusions(keyword)
    for item in items:
        content = _clean_analysis_text(item.text).casefold()
        if not content:
            continue
        terms = {phrase for phrase in DOMAIN_PHRASES if phrase in content}
        for token in pseg.cut(content):
            word = token.word.strip().casefold()
            flag = token.flag.casefold()
            if (
                len(word) < 2
                or len(word) > 12
                or word in exclusions
                or word.isdigit()
                or re.fullmatch(r"[a-z]", word)
                or not (flag.startswith(("n", "v", "a")) or flag == "eng")
            ):
                continue
            terms.add(word)
        for term in terms:
            counts[term] += 1
            if item.sentiment == "negative":
                negative_counts[term] += 1

    ranked = sorted(
        counts,
        key=lambda term: (counts[term] * (1.2 if term in phrase_terms else 1.0), len(term)),
        reverse=True,
    )
    selected: list[str] = []
    for term in ranked:
        if counts[term] < 2:
            continue
        if any(
            term != chosen
            and term in chosen
            and counts[term] <= counts[chosen] * 1.2
            for chosen in selected
        ):
            continue
        selected.append(term)
        if len(selected) >= limit:
            break
    return [
        {
            "word": word,
            "count": counts[word],
            "negative_ratio": round(negative_counts[word] / counts[word], 3),
        }
        for word in selected
    ]


def _rule_topic_assignments(items: list[ContentItem]) -> dict[int, list[str]]:
    assignments: dict[int, list[str]] = {}
    for item in items:
        content = _clean_analysis_text(item.text).casefold()
        matched = [
            str(topic["id"])
            for topic in TOPIC_DEFINITIONS
            if any(str(keyword).casefold() in content for keyword in topic["keywords"])
        ]
        assignments[item.id] = matched
    return assignments


def _extract_topics(
    items: list[ContentItem], assignments: dict[int, list[str]] | None = None
) -> list[dict[str, Any]]:
    if not items:
        return []
    resolved = assignments or _rule_topic_assignments(items)
    grouped: dict[str, list[ContentItem]] = {str(topic["id"]): [] for topic in TOPIC_DEFINITIONS}
    for item in items:
        for topic_id in resolved.get(item.id, []):
            if topic_id in grouped:
                grouped[topic_id].append(item)

    minimum_mentions = max(3, math.ceil(len(items) * 0.002))
    eligible = {key: value for key, value in grouped.items() if len(value) >= minimum_mentions}
    if not eligible:
        return []
    max_mentions = max(len(value) for value in eligible.values())
    weighted_negative = {
        topic_id: sum(
            1 + math.log2(max(0, item.likes) + 1)
            for item in topic_items
            if item.sentiment == "negative"
        )
        for topic_id, topic_items in eligible.items()
    }
    max_impact = max(weighted_negative.values(), default=1.0) or 1.0
    topics: list[dict[str, Any]] = []
    for topic_id, topic_items in eligible.items():
        definition = TOPIC_BY_ID[topic_id]
        negative_items = [item for item in topic_items if item.sentiment == "negative"]
        negative_ratio = len(negative_items) / len(topic_items)
        risk_score = (
            negative_ratio * 50
            + weighted_negative[topic_id] / max_impact * 35
            + len(topic_items) / max_mentions * 15
        )
        keyword_counts = Counter(
            str(keyword)
            for item in topic_items
            for keyword in definition["keywords"]
            if str(keyword).casefold() in _clean_analysis_text(item.text).casefold()
        )
        representatives = sorted(
            negative_items or topic_items,
            key=lambda item: (math.log2(max(0, item.likes) + 1), item.confidence or 0),
            reverse=True,
        )[:3]
        topics.append(
            {
                "id": topic_id,
                "name": definition["label"],
                "keywords": [word for word, _count in keyword_counts.most_common(6)]
                or list(definition["keywords"][:4]),
                "size": len(topic_items),
                "negative_ratio": round(negative_ratio * 100, 1),
                "risk_score": round(min(100.0, risk_score), 1),
                "samples": [item.text[:240] for item in representatives],
                "weighted_negative": round(weighted_negative[topic_id], 2),
            }
        )
    return sorted(topics, key=lambda topic: (topic["risk_score"], topic["size"]), reverse=True)


def _timeline(items: list[ContentItem]) -> list[dict[str, Any]]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    fallback_day = datetime.now(timezone.utc).date().isoformat()
    for item in items:
        day = item.published_at.date().isoformat() if item.published_at else fallback_day
        buckets[day][item.sentiment or "neutral"] += 1
    rows = []
    for day in sorted(buckets)[-30:]:
        counter = buckets[day]
        rows.append({"date": day, **{key: counter[key] for key in SENTIMENTS}, "total": sum(counter.values())})
    return rows


def _model_quality(items: list[ContentItem], model_predictions: dict[int, str]) -> dict[str, Any]:
    rated = [item for item in items if item.platform == "taptap" and item.rating is not None]
    if not rated:
        return {"sample_size": 0, "accuracy": None, "macro_f1": None, "confusion": []}
    truth = []
    for item in rated:
        rating = item.rating
        assert rating is not None
        truth.append("positive" if rating >= 4 else "neutral" if rating == 3 else "negative")
    predicted = [model_predictions.get(item.id, item.sentiment or "neutral") for item in rated]
    matrix = confusion_matrix(truth, predicted, labels=list(SENTIMENTS)).tolist()
    return {
        "sample_size": len(rated),
        "accuracy": round(float(accuracy_score(truth, predicted)), 4),
        "macro_f1": round(float(f1_score(truth, predicted, labels=list(SENTIMENTS), average="macro", zero_division=0)), 4),
        "labels": list(SENTIMENTS),
        "confusion": matrix,
    }


def _local_summary(keyword: str, overall: dict[str, Any], topics: list[dict[str, Any]]) -> dict[str, Any]:
    if not overall["total"]:
        return {
            "overview": f"“{keyword}”当前来源没有足够样本，未计算情感比例。",
            "positives": [],
            "risks": ["样本不足，结论不可用"],
            "recommendations": ["检查登录状态、来源地址与采集完整度后重试"],
        }
    percentages = {item["name"]: item["percentage"] for item in overall["items"]}
    risks = [topic["name"] for topic in topics[:3] if topic["negative_ratio"] >= 35]
    positives = [topic["name"] for topic in reversed(topics) if topic["negative_ratio"] < 35][:3]
    return {
        "overview": f"“{keyword}”样本整体正面 {percentages.get('positive', 0):.1f}%，中性 {percentages.get('neutral', 0):.1f}%，负面 {percentages.get('negative', 0):.1f}%。",
        "positives": positives or ["正面样本较分散，建议结合代表性评价人工复核"],
        "risks": risks or ["当前未识别到高度集中的负面议题"],
        "recommendations": [
            "优先复核高风险议题中的高互动样本",
            "手动重跑任务以比较不同时间窗口的变化",
            "对模型低置信度和反讽表达保留人工判断",
        ],
    }


async def analyze_job(
    settings: Settings,
    job: Job,
    videos: list[Video],
    apps: list[SourceApp],
    items: list[ContentItem],
    official_account: OfficialAccount | None = None,
    analysis_progress: AnalysisProgress | None = None,
    is_cancelled: CancellationCheck | None = None,
) -> tuple[dict[str, Any], list[str]]:
    engine = SentimentEngine(settings)
    predictions = await engine.predict([item.text for item in items])
    model_predictions: dict[int, str] = {}
    for item, (sentiment, confidence) in zip(items, predictions, strict=True):
        model_predictions[item.id] = sentiment
        item.sentiment = sentiment
        item.confidence = confidence
    evaluated_predictions = dict(model_predictions)

    warnings: list[str] = [engine.warning] if engine.warning else []
    topic_assignments = _rule_topic_assignments(items)
    llm_engine: LLMAnalyzer | None = None
    llm_result = None
    analysis_meta: dict[str, Any] = {
        "mode": job.analysis_mode,
        "sentiment_source": "local_model_calibrated",
        "local_model": settings.local_model_id,
        "local_model_revision": settings.local_model_revision,
    }
    if job.analysis_mode == "enhanced":
        llm_engine = LLMAnalyzer(settings)

        async def report_batch_progress(done: int, total: int) -> None:
            if is_cancelled and await is_cancelled():
                raise AnalysisCancelled("analysis cancelled")
            if analysis_progress:
                percentage = 92 + round(done / max(1, total) * 4)
                await analysis_progress(percentage, f"GPT-5.6 正在复核文本 {done}/{total}")

        llm_result = await llm_engine.classify(
            items,
            keyword=job.keyword,
            progress=report_batch_progress,
        )
        warnings.extend(llm_result.warnings)
        agreement = 0
        for item in items:
            label = llm_result.labels.get(item.id)
            if not label:
                continue
            agreement += model_predictions.get(item.id) == label.sentiment
            evaluated_predictions[item.id] = label.sentiment
            item.sentiment = label.sentiment
            item.confidence = label.confidence
            # An empty semantic topic is meaningful: it clears false-positive
            # keyword matches made by the deterministic fallback.
            topic_assignments[item.id] = label.topics
            item.raw_meta = {
                **(item.raw_meta or {}),
                "analysis": {
                    "source": "llm",
                    "model": llm_engine.model,
                    "prompt_version": PROMPT_VERSION,
                    "topics": topic_assignments.get(item.id, []),
                },
            }
        covered = len(llm_result.labels)
        coverage = covered / max(1, len(items))
        if covered < len(items):
            warnings.append(
                f"GPT-5.6 覆盖 {covered}/{len(items)} 条，其余使用校准后的本地模型"
            )
        analysis_meta.update(
            {
                "sentiment_source": "gpt-5.6_with_local_fallback",
                "llm_model": llm_engine.model,
                "prompt_version": PROMPT_VERSION,
                "llm_coverage": round(coverage, 4),
                "llm_covered_count": covered,
                "llm_unique_input_count": llm_result.unique_input_count,
                "llm_batch_count": llm_result.batch_count,
                "local_llm_agreement": round(agreement / max(1, covered), 4),
                "prompt_tokens": llm_result.prompt_tokens,
                "completion_tokens": llm_result.completion_tokens,
            }
        )

    for item in items:
        if item.platform == "taptap" and item.rating:
            item.sentiment = (
                "positive" if item.rating >= 4 else "neutral" if item.rating == 3 else "negative"
            )
            item.confidence = 1.0
            item.raw_meta = {
                **(item.raw_meta or {}),
                "analysis": {
                    **dict((item.raw_meta or {}).get("analysis") or {}),
                    "sentiment_source": "rating",
                },
            }

    comments = [
        item for item in items if item.platform == "bilibili" and item.kind == "comment"
    ]
    danmakus = [
        item for item in items if item.platform == "bilibili" and item.kind == "danmaku"
    ]
    reviews = [item for item in items if item.platform == "taptap"]
    official_items = [item for item in items if item.source_scope == "bilibili_official"]
    discovery_items = [item for item in items if item.source_scope == "bilibili_discovery"]
    taptap_items = [item for item in items if item.source_scope == "taptap"]
    official_videos = [video for video in videos if video.source_scope == "bilibili_official"]
    discovery_videos = [video for video in videos if video.source_scope == "bilibili_discovery"]

    def bili_section_distribution(section_items: list[ContentItem]) -> dict[str, Any]:
        return _blend_bilibili(
            _distribution([item for item in section_items if item.kind == "comment"]),
            _distribution([item for item in section_items if item.kind == "danmaku"]),
        )

    official_distribution = bili_section_distribution(official_items)
    discovery_distribution = bili_section_distribution(discovery_items)
    bili_overall_distribution = _blend_bilibili(
        _distribution(comments), _distribution(danmakus)
    )
    taptap_distribution = _distribution(reviews)
    available = [
        entry
        for entry in (bili_overall_distribution, taptap_distribution)
        if entry["total"]
    ]
    overall_items = []
    for index, key in enumerate(SENTIMENTS):
        percentage = sum(entry["items"][index]["percentage"] for entry in available) / max(1, len(available))
        overall_items.append(
            {"name": key, "label": SENTIMENT_CN[key], "percentage": round(percentage, 1), "count": sum(entry["items"][index]["count"] for entry in available)}
        )
    overall = {
        "total": sum(entry["total"] for entry in available),
        "available": bool(available),
        "items": overall_items,
        "platform_equal_weight": True,
    }
    keywords = _extract_keywords(items, job.keyword)
    topics = _extract_topics(items, topic_assignments)
    metrics = {
        "video_count": len(videos),
        "selected_video_count": sum(bool(video.selected) for video in videos),
        "official_video_count": len(official_videos),
        "discovery_video_count": len(discovery_videos),
        "official_comment_count": sum(item.kind == "comment" for item in official_items),
        "discovery_comment_count": sum(item.kind == "comment" for item in discovery_items),
        "comment_count": len(comments),
        "danmaku_count": len(danmakus),
        "review_count": len(reviews),
        "taptap_score": apps[0].score if apps else None,
        "overall_positive": overall_items[0]["percentage"],
        "overall_neutral": overall_items[1]["percentage"],
        "overall_negative": overall_items[2]["percentage"],
    }
    quality = _model_quality(reviews, evaluated_predictions)
    summary = _local_summary(job.keyword, overall, topics)

    rating_counts = Counter(item.rating for item in reviews if item.rating)
    rating_total = sum(rating_counts.values())
    samples = {}
    for sentiment in SENTIMENTS:
        candidates = [item for item in items if item.sentiment == sentiment]
        candidates.sort(key=lambda item: ((item.confidence or 0) + math.log1p(item.likes) * 0.05), reverse=True)
        samples[sentiment] = [
            {
                "id": item.id,
                "platform": item.platform,
                "kind": item.kind,
                "source_scope": item.source_scope,
                "author": item.author_hash,
                "text": item.text[:900],
                "rating": item.rating,
                "likes": item.likes,
                "confidence": item.confidence,
            }
            for item in candidates[:5]
        ]

    selected_videos = sorted(
        videos,
        key=lambda video: (
            video.source_scope == "bilibili_official",
            video.published_at or datetime.min.replace(tzinfo=timezone.utc),
            video.selection_score,
        ),
        reverse=True,
    )
    cover_url = (
        apps[0].cover_url
        if apps and apps[0].cover_url
        else official_account.avatar_url
        if official_account and official_account.avatar_url
        else next((video.cover_url for video in selected_videos if video.cover_url), None)
    )

    def section_samples(section_items: list[ContentItem]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for sentiment in SENTIMENTS:
            candidates = [item for item in section_items if item.sentiment == sentiment]
            candidates.sort(
                key=lambda item: (item.confidence or 0) + math.log1p(item.likes) * 0.05,
                reverse=True,
            )
            result[sentiment] = [
                {
                    "id": item.id,
                    "platform": item.platform,
                    "kind": item.kind,
                    "source_scope": item.source_scope,
                    "author": item.author_hash,
                    "text": item.text[:900],
                    "rating": item.rating,
                    "likes": item.likes,
                    "confidence": item.confidence,
                    "reply_depth": item.reply_depth or 0,
                }
                for item in candidates[:5]
            ]
        return result

    def video_rows(section_videos: list[Video]) -> list[dict[str, Any]]:
        return [
            {
                "id": video.external_id,
                "title": video.title,
                "url": video.url,
                "cover_url": video.cover_url,
                "creator": video.creator,
                "published_at": video.published_at.isoformat() if video.published_at else None,
                "views": video.views,
                "likes": video.likes,
                "coins": video.coins,
                "favorites": video.favorites,
                "replies": video.replies,
                "danmakus": video.danmakus,
                "selection_score": round(video.selection_score, 4),
                "selected": video.selected,
                "source_scope": video.source_scope,
                "score_components": (video.raw_meta or {}).get("score_components", {}),
            }
            for video in section_videos
        ]

    def section_payload(
        key: str,
        label: str,
        section_items: list[ContentItem],
        distribution: dict[str, Any],
        section_videos: list[Video] | None = None,
    ) -> dict[str, Any]:
        section_topics = _extract_topics(section_items, topic_assignments)
        return {
            "key": key,
            "label": label,
            "available": bool(section_items),
            "metrics": {
                "sample_count": len(section_items),
                "comment_count": sum(item.kind == "comment" for item in section_items),
                "nested_reply_count": sum((item.reply_depth or 0) > 0 for item in section_items),
                "danmaku_count": sum(item.kind == "danmaku" for item in section_items),
                "review_count": sum(item.kind == "review" for item in section_items),
                "video_count": len(section_videos or []),
            },
            "sentiment": distribution,
            "timeline": _timeline(section_items),
            "keywords": _extract_keywords(section_items, job.keyword),
            "topics": section_topics,
            "samples": section_samples(section_items),
            "videos": video_rows(section_videos or []),
            "summary": _local_summary(f"{job.keyword} · {label}", distribution, section_topics),
        }

    sections = {
        "bilibili_official": section_payload(
            "bilibili_official",
            "B站官号",
            official_items,
            official_distribution,
            official_videos,
        ),
        "bilibili_discovery": section_payload(
            "bilibili_discovery",
            "B站相关视频",
            discovery_items,
            discovery_distribution,
            discovery_videos,
        ),
        "taptap": section_payload(
            "taptap",
            "TapTap 玩家评价",
            taptap_items,
            taptap_distribution,
        ),
    }
    sections["taptap"].update(
        {
            "rating_distribution": [
                {
                    "star": star,
                    "count": rating_counts[star],
                    "percentage": round(rating_counts[star] / rating_total * 100, 1)
                    if rating_total
                    else 0,
                }
                for star in range(5, 0, -1)
            ],
            "tags": (apps[0].tags or []) if apps else [],
        }
    )

    requested = {
        "bilibili_official": bool(job.official_mid),
        "bilibili_discovery": bool(job.include_discovery),
        "taptap": bool(job.include_taptap),
    }
    source_available = {key: bool(value["available"]) for key, value in sections.items()}
    empty_sources = [
        key for key, was_requested in requested.items() if was_requested and not source_available[key]
    ]
    if empty_sources:
        warnings.append("以下来源没有有效样本：" + "、".join(empty_sources))
    data_quality = {
        "valid": bool(items) and not empty_sources and not job.partial,
        "sample_count": len(items),
        "requested_sources": requested,
        "available_sources": source_available,
        "empty_sources": empty_sources,
        "collection": job.collection_metrics or {},
    }
    ai_analysis: dict[str, Any] | None = None
    if job.analysis_mode == "enhanced" and llm_engine is not None:
        if is_cancelled and await is_cancelled():
            raise AnalysisCancelled("analysis cancelled")
        if analysis_progress:
            await analysis_progress(97, "GPT-5.6 正在生成深度研判")
        evidence_candidates: list[ContentItem] = []
        seen_evidence: set[int] = set()
        for sentiment in SENTIMENTS:
            candidates = sorted(
                (item for item in items if item.sentiment == sentiment),
                key=lambda item: (math.log2(max(0, item.likes) + 1), item.confidence or 0),
                reverse=True,
            )[:16]
            for item in candidates:
                if item.id not in seen_evidence:
                    seen_evidence.add(item.id)
                    evidence_candidates.append(item)
        for topic in topics[:8]:
            topic_id = str(topic["id"])
            candidates = sorted(
                (item for item in items if topic_id in topic_assignments.get(item.id, [])),
                key=lambda item: (item.sentiment == "negative", math.log2(max(0, item.likes) + 1)),
                reverse=True,
            )[:3]
            for item in candidates:
                if item.id not in seen_evidence:
                    seen_evidence.add(item.id)
                    evidence_candidates.append(item)
        report_metrics = {
            **metrics,
            "sections": {
                key: {
                    "sample_count": value["metrics"]["sample_count"],
                    "sentiment": value["sentiment"]["items"],
                }
                for key, value in sections.items()
            },
        }
        report_evidence = [
                {
                    "id": item.id,
                    "text": sanitize_text(item.text)[:420],
                    "sentiment": item.sentiment,
                    "confidence": item.confidence,
                    "likes": item.likes,
                    "source_scope": item.source_scope,
                    "topics": topic_assignments.get(item.id, []),
                }
                for item in evidence_candidates[:60]
            ]
        ai_analysis, ai_warning, report_usage = await llm_engine.generate_report(
            keyword=job.keyword,
            metrics=report_metrics,
            topics=topics,
            keywords=keywords,
            evidence=report_evidence,
            data_quality=data_quality,
        )
        if report_usage:
            analysis_meta["prompt_tokens"] = int(analysis_meta.get("prompt_tokens", 0)) + int(
                report_usage.get("prompt_tokens", 0)
            )
            analysis_meta["completion_tokens"] = int(
                analysis_meta.get("completion_tokens", 0)
            ) + int(report_usage.get("completion_tokens", 0))
        if ai_warning:
            warnings.append(ai_warning)
        if ai_analysis:
            ai_analysis["evidence"] = report_evidence
            finding_titles = [
                str(row.get("title"))
                for row in ai_analysis.get("findings", [])
                if isinstance(row, dict) and row.get("title")
            ]
            risk_titles = [
                str(row.get("title"))
                for row in ai_analysis.get("risks", [])
                if isinstance(row, dict) and row.get("title")
            ]
            actions = [
                str(row.get("action"))
                for row in ai_analysis.get("actions", [])
                if isinstance(row, dict) and row.get("action")
            ]
            summary = {
                "overview": ai_analysis["executive_summary"],
                "positives": finding_titles[:3] or summary["positives"],
                "risks": risk_titles[:3] or summary["risks"],
                "recommendations": actions[:3] or summary["recommendations"],
                "enhanced": True,
            }
            analysis_meta["report_generated"] = True
        else:
            analysis_meta["report_generated"] = False
    payload = {
        "id": job.id,
        "keyword": job.keyword,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "partial": bool(job.partial),
        "warnings": list(dict.fromkeys((job.warnings or []) + warnings)),
        "hero": {
            "cover_url": cover_url,
            "subtitle": "B站官号、相关视频与 TapTap 玩家评价分区联合分析",
        },
        "metrics": metrics,
        "sentiment": {
            "overall": overall,
            "bilibili": bili_overall_distribution,
            "bilibili_official": official_distribution,
            "bilibili_discovery": discovery_distribution,
            "taptap": taptap_distribution,
        },
        "sections": sections,
        "rating_distribution": [
            {"star": star, "count": rating_counts[star], "percentage": round(rating_counts[star] / rating_total * 100, 1) if rating_total else 0}
            for star in range(5, 0, -1)
        ],
        "timeline": _timeline(items),
        "keywords": keywords,
        "tags": (apps[0].tags or []) if apps else [],
        "topics": topics,
        "analysis": analysis_meta,
        "ai_analysis": ai_analysis,
        "samples": samples,
        "videos": video_rows(selected_videos),
        "official_account": {
            "mid": official_account.mid,
            "title": official_account.title,
            "url": official_account.url,
            "avatar_url": official_account.avatar_url,
            "expected_video_count": official_account.expected_video_count,
            "collected_video_count": official_account.collected_video_count,
        }
        if official_account
        else None,
        "source_app": {
            "id": apps[0].external_id,
            "title": apps[0].title,
            "url": apps[0].url,
            "score": apps[0].score,
            "rating_count": apps[0].rating_count,
        } if apps else None,
        "model_quality": {
            **quality,
            **analysis_meta,
            "model": llm_engine.model
            if llm_engine and analysis_meta.get("llm_covered_count")
            else settings.local_model_id,
            "revision": PROMPT_VERSION
            if llm_engine and analysis_meta.get("llm_covered_count")
            else settings.local_model_revision,
        },
        "summary": summary,
        "data_quality": data_quality,
        "methodology": {
            "bilibili_official": "官号时间范围内视频穷尽分页；顶层评论与楼中楼完整性逐视频核对",
            "bilibili_discovery": "关键词相关视频按互动权重采样；与官号 BVID 去重后分析",
            "bilibili": "登录用户可见网页低频采集；评论 80%、可见弹幕 20% 加权",
            "taptap": "公开网页评价；4-5星正面、3星中性、1-2星负面",
            "analysis": "增强模式由 GPT-5.6 全量分批标注，确定性代码聚合固定业务议题与风险分；失败批次回退校准后的本地模型"
            if job.analysis_mode == "enhanced"
            else "校准后的本地三分类模型；低置信度、纯表情、事实回复与无主导混合表达归为中性",
            "combined": "平台等权平均；风险分用于样本内运营排序，不等同于真实用户负面概率；不绕过验证码或风控",
        },
    }
    return payload, warnings
