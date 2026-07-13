from __future__ import annotations

import asyncio
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx
import jieba
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, silhouette_score

from ..config import Settings
from ..models import ContentItem, Job, SourceApp, Video
from .privacy import sanitize_text

SENTIMENTS = ("positive", "neutral", "negative")
SENTIMENT_CN = {"positive": "正面", "neutral": "中性", "negative": "负面"}
POSITIVE_WORDS = {"好玩", "优秀", "喜欢", "流畅", "惊喜", "推荐", "良心", "期待", "不错", "有趣"}
NEGATIVE_WORDS = {"垃圾", "失望", "卡顿", "掉帧", "外挂", "举报", "氪金", "发热", "闪退", "恶心", "无聊"}
STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "也", "都", "就", "和", "在", "有", "不", "这", "那",
    "一个", "没有", "什么", "还是", "但是", "游戏", "视频", "感觉", "真的", "可以", "就是", "比较", "非常",
}


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
            predictions.append((mapped, round(float(best["score"]), 6)))
        return predictions

    @staticmethod
    def _lexical_predict(text: str) -> tuple[str, float]:
        positive = sum(word in text for word in POSITIVE_WORDS)
        negative = sum(word in text for word in NEGATIVE_WORDS)
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
    return {"total": comments["total"] + danmakus["total"], "items": items, "weighted": True}


def _extract_keywords(items: list[ContentItem], limit: int = 25) -> list[dict[str, Any]]:
    tokens: list[str] = []
    negative_counts: Counter[str] = Counter()
    for item in items:
        words = [
            word.strip().casefold()
            for word in jieba.lcut(item.text)
            if len(word.strip()) >= 2 and word.strip().casefold() not in STOPWORDS
        ]
        tokens.extend(words)
        if item.sentiment == "negative":
            negative_counts.update(words)
    counts = Counter(tokens)
    return [
        {
            "word": word,
            "count": count,
            "negative_ratio": round(negative_counts[word] / count, 3) if count else 0,
        }
        for word, count in counts.most_common(limit)
    ]


def _extract_topics(items: list[ContentItem]) -> list[dict[str, Any]]:
    usable = [item for item in items if len(item.text) >= 4]
    if len(usable) < 12:
        return []
    texts = [item.text for item in usable]
    vectorizer = TfidfVectorizer(
        tokenizer=jieba.lcut,
        token_pattern=None,
        stop_words=list(STOPWORDS),
        max_features=2500,
        min_df=2,
        max_df=0.92,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return []
    max_k = min(8, len(usable) - 1)
    candidate_ks = range(3, max_k + 1) if max_k >= 3 else [2]
    best_model: MiniBatchKMeans | None = None
    best_score = -1.0
    sample_size = min(500, matrix.shape[0])
    for k in candidate_ks:
        model = MiniBatchKMeans(n_clusters=k, random_state=42, n_init="auto", batch_size=128)
        labels = model.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(matrix, labels, sample_size=sample_size, random_state=42)
        if score > best_score:
            best_score, best_model = score, model
    if best_model is None:
        return []
    labels = best_model.labels_
    terms = np.asarray(vectorizer.get_feature_names_out())
    topics = []
    for cluster_id in range(best_model.n_clusters):
        indices = np.where(labels == cluster_id)[0].tolist()
        if not indices:
            continue
        top_indices = best_model.cluster_centers_[cluster_id].argsort()[-6:][::-1]
        keywords = [str(term) for term in terms[top_indices] if len(str(term)) >= 2]
        cluster_items = [usable[index] for index in indices]
        negative_count = sum(item.sentiment == "negative" for item in cluster_items)
        negative_ratio = negative_count / len(cluster_items)
        engagement = sum(math.log1p(item.likes) for item in cluster_items) / len(cluster_items)
        risk_score = negative_ratio * math.log1p(len(cluster_items)) * (1 + engagement)
        representatives = sorted(
            cluster_items,
            key=lambda item: ((item.confidence or 0) + math.log1p(item.likes) * 0.05),
            reverse=True,
        )[:3]
        topics.append(
            {
                "id": cluster_id,
                "name": " / ".join(keywords[:3]) or f"议题 {cluster_id + 1}",
                "keywords": keywords,
                "size": len(cluster_items),
                "negative_ratio": round(negative_ratio * 100, 1),
                "risk_score": round(risk_score, 3),
                "samples": [item.text[:180] for item in representatives],
            }
        )
    return sorted(topics, key=lambda topic: topic["risk_score"], reverse=True)


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


async def _enhance_summary(
    settings: Settings, keyword: str, metrics: dict[str, Any], topics: list[dict[str, Any]], samples: list[ContentItem]
) -> tuple[dict[str, Any] | None, str | None]:
    if not (settings.openai_base_url and settings.openai_api_key and settings.openai_model):
        return None, "LLM 增强未配置，已使用本地总结"
    evidence = [sanitize_text(item.text)[:300] for item in samples[:24]]
    prompt = {
        "keyword": keyword,
        "metrics": metrics,
        "topics": [{key: topic[key] for key in ("name", "size", "negative_ratio", "keywords")} for topic in topics[:6]],
        "evidence": evidence,
        "instruction": "仅依据给定统计与证据输出 JSON，字段为 overview、positives、risks、recommendations；每个字段为中文字符串或字符串数组，不得编造数字。",
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                settings.openai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "你是严谨的中文舆情分析员，只能引用输入证据。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            required = {"overview", "positives", "risks", "recommendations"}
            if not required.issubset(parsed):
                raise ValueError("LLM JSON 缺少字段")
            return parsed, None
    except Exception as exc:
        return None, f"LLM 增强失败，已使用本地总结：{type(exc).__name__}"


def _local_summary(keyword: str, overall: dict[str, Any], topics: list[dict[str, Any]]) -> dict[str, Any]:
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
) -> tuple[dict[str, Any], list[str]]:
    engine = SentimentEngine(settings)
    predictions = await engine.predict([item.text for item in items])
    model_predictions: dict[int, str] = {}
    for item, (sentiment, confidence) in zip(items, predictions, strict=True):
        model_predictions[item.id] = sentiment
        if item.platform == "taptap" and item.rating:
            sentiment = "positive" if item.rating >= 4 else "neutral" if item.rating == 3 else "negative"
            confidence = 1.0
        item.sentiment = sentiment
        item.confidence = confidence

    comments = [item for item in items if item.platform == "bilibili" and item.kind == "comment"]
    danmakus = [item for item in items if item.platform == "bilibili" and item.kind == "danmaku"]
    reviews = [item for item in items if item.platform == "taptap"]
    bili_distribution = _blend_bilibili(_distribution(comments), _distribution(danmakus))
    taptap_distribution = _distribution(reviews)
    available = [entry for entry in (bili_distribution, taptap_distribution) if entry["total"]]
    overall_items = []
    for index, key in enumerate(SENTIMENTS):
        percentage = sum(entry["items"][index]["percentage"] for entry in available) / max(1, len(available))
        overall_items.append(
            {"name": key, "label": SENTIMENT_CN[key], "percentage": round(percentage, 1), "count": sum(entry["items"][index]["count"] for entry in available)}
        )
    overall = {"total": sum(entry["total"] for entry in available), "items": overall_items, "platform_equal_weight": True}
    keywords = _extract_keywords(items)
    topics = _extract_topics(items)
    metrics = {
        "video_count": len(videos),
        "selected_video_count": sum(bool(video.selected) for video in videos),
        "comment_count": len(comments),
        "danmaku_count": len(danmakus),
        "review_count": len(reviews),
        "taptap_score": apps[0].score if apps else None,
        "overall_positive": overall_items[0]["percentage"],
        "overall_neutral": overall_items[1]["percentage"],
        "overall_negative": overall_items[2]["percentage"],
    }
    quality = _model_quality(reviews, model_predictions)
    summary = _local_summary(job.keyword, overall, topics)
    warnings: list[str] = [engine.warning] if engine.warning else []
    if job.analysis_mode == "enhanced":
        enhanced, warning = await _enhance_summary(
            settings,
            job.keyword,
            metrics,
            topics,
            sorted(items, key=lambda item: item.likes, reverse=True),
        )
        if enhanced:
            summary = {**enhanced, "enhanced": True}
        if warning:
            warnings.append(warning)

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
                "author": item.author_hash,
                "text": item.text[:900],
                "rating": item.rating,
                "likes": item.likes,
                "confidence": item.confidence,
            }
            for item in candidates[:5]
        ]

    selected_videos = sorted(videos, key=lambda video: video.selection_score, reverse=True)
    cover_url = apps[0].cover_url if apps and apps[0].cover_url else next((video.cover_url for video in selected_videos if video.cover_url), None)
    payload = {
        "id": job.id,
        "keyword": job.keyword,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "partial": bool(job.partial),
        "warnings": list(dict.fromkeys((job.warnings or []) + warnings)),
        "hero": {"cover_url": cover_url, "subtitle": "B站视频评论、可见弹幕与 TapTap 玩家评价联合分析"},
        "metrics": metrics,
        "sentiment": {"overall": overall, "bilibili": bili_distribution, "taptap": taptap_distribution},
        "rating_distribution": [
            {"star": star, "count": rating_counts[star], "percentage": round(rating_counts[star] / rating_total * 100, 1) if rating_total else 0}
            for star in range(5, 0, -1)
        ],
        "timeline": _timeline(items),
        "keywords": keywords,
        "tags": (apps[0].tags or []) if apps else [],
        "topics": topics,
        "samples": samples,
        "videos": [
            {
                "id": video.external_id,
                "title": video.title,
                "url": video.url,
                "cover_url": video.cover_url,
                "creator": video.creator,
                "views": video.views,
                "likes": video.likes,
                "coins": video.coins,
                "favorites": video.favorites,
                "replies": video.replies,
                "danmakus": video.danmakus,
                "selection_score": round(video.selection_score, 4),
                "selected": video.selected,
                "score_components": (video.raw_meta or {}).get("score_components", {}),
            }
            for video in selected_videos
        ],
        "source_app": {
            "id": apps[0].external_id,
            "title": apps[0].title,
            "url": apps[0].url,
            "score": apps[0].score,
            "rating_count": apps[0].rating_count,
        } if apps else None,
        "model_quality": {**quality, "model": settings.local_model_id, "revision": settings.local_model_revision},
        "summary": summary,
        "methodology": {
            "bilibili": "登录用户可见网页低频采集；评论 80%、可见弹幕 20% 加权",
            "taptap": "公开网页评价；4-5星正面、3星中性、1-2星负面",
            "combined": "平台等权平均；不使用隐藏 API，不绕过验证码或风控",
        },
    }
    return payload, warnings
