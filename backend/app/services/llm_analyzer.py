from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings
from ..models import ContentItem
from .privacy import sanitize_text

SENTIMENTS = {"positive", "neutral", "negative"}
TOPIC_IDS = {
    "performance",
    "fairness",
    "anti_abuse",
    "time_cost",
    "monetization",
    "experience",
    "visual_audio",
    "rust_identity",
    "community",
}
PROMPT_VERSION = "game-opinion-gpt56-v3"

BatchProgress = Callable[[int, int], Awaitable[None]]


@dataclass(slots=True)
class LLMLabel:
    sentiment: str
    confidence: float
    topics: list[str]


@dataclass(slots=True)
class LLMAnalysisResult:
    labels: dict[int, LLMLabel] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    unique_input_count: int = 0
    batch_count: int = 0


class LLMRequestError(RuntimeError):
    pass


class LLMAnalyzer:
    """OpenAI-compatible, evidence-bound analysis for enhanced reports."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = (settings.openai_base_url or "").rstrip("/")
        self.api_key = settings.openai_api_key_value
        self.model = settings.openai_model or ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        *,
        system: str,
        user: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "temperature": 0.1,
                        "max_tokens": self.settings.llm_max_output_tokens,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {
                                "role": "user",
                                "content": "Return json for this request:\n"
                                + json.dumps(user, ensure_ascii=False),
                            },
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("LLM content is not text")
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                parsed = json.loads(cleaned)
                if not isinstance(parsed, dict):
                    raise ValueError("LLM JSON root must be an object")
                usage = payload.get("usage") or {}
                return parsed, {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                }
            except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 < self.settings.llm_max_retries:
                    await asyncio.sleep(min(8.0, 1.5 * (2**attempt)))
        assert last_error is not None
        detail = (
            f"HTTP {last_error.response.status_code}"
            if isinstance(last_error, httpx.HTTPStatusError)
            else type(last_error).__name__
        )
        raise LLMRequestError(detail) from last_error

    @staticmethod
    def _normalized_text(text: str) -> str:
        return re.sub(r"\s+", " ", sanitize_text(text)).strip().casefold()

    @staticmethod
    def _normalize_report(
        payload: dict[str, Any], evidence_ids: set[int]
    ) -> dict[str, Any]:
        summary = str(payload.get("executive_summary") or "").strip()
        if not summary:
            raise ValueError("AI report summary invalid")

        def normalize_insights(key: str) -> list[dict[str, Any]]:
            source = payload.get(key)
            if not isinstance(source, list):
                raise ValueError(f"AI report {key} invalid")
            rows: list[dict[str, Any]] = []
            for entry in source[:5]:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                detail = str(entry.get("detail") or "").strip()
                if not title or not detail:
                    continue
                raw_ids = entry.get("evidence_ids")
                ids = []
                if isinstance(raw_ids, list):
                    for value in raw_ids:
                        try:
                            item_id = int(value)
                        except (TypeError, ValueError):
                            continue
                        if item_id in evidence_ids and item_id not in ids:
                            ids.append(item_id)
                rows.append({"title": title, "detail": detail, "evidence_ids": ids[:8]})
            if not rows:
                raise ValueError(f"AI report {key} empty")
            return rows

        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            raise ValueError("AI report actions invalid")
        actions: list[dict[str, str]] = []
        for entry in raw_actions[:6]:
            if not isinstance(entry, dict):
                continue
            priority = str(entry.get("priority") or "").upper()
            title = str(entry.get("title") or "").strip()
            rationale = str(entry.get("rationale") or "").strip()
            action = str(entry.get("action") or "").strip()
            if priority not in {"P0", "P1", "P2"} or not all(
                (title, rationale, action)
            ):
                continue
            actions.append(
                {
                    "priority": priority,
                    "title": title,
                    "rationale": rationale,
                    "action": action,
                }
            )
        if not actions:
            raise ValueError("AI report actions empty")

        raw_caveats = payload.get("caveats")
        if not isinstance(raw_caveats, list):
            raise ValueError("AI report caveats invalid")
        caveats = [str(value).strip() for value in raw_caveats if str(value).strip()][:8]
        return {
            "executive_summary": summary,
            "findings": normalize_insights("findings"),
            "risks": normalize_insights("risks"),
            "actions": actions,
            "caveats": caveats,
        }

    async def classify(
        self,
        items: list[ContentItem],
        keyword: str,
        progress: BatchProgress | None = None,
    ) -> LLMAnalysisResult:
        result = LLMAnalysisResult()
        if not self.configured:
            result.warnings.append("GPT-5.6 未配置，增强分析已回退本地模型")
            return result

        duplicate_groups: dict[str, list[ContentItem]] = {}
        for item in items:
            normalized = self._normalized_text(item.text)
            if normalized:
                duplicate_groups.setdefault(normalized, []).append(item)
        representatives = [group[0] for group in duplicate_groups.values()]
        result.unique_input_count = len(representatives)
        batches = [
            representatives[index : index + self.settings.llm_batch_size]
            for index in range(0, len(representatives), self.settings.llm_batch_size)
        ]
        result.batch_count = len(batches)
        semaphore = asyncio.Semaphore(self.settings.llm_concurrency)
        progress_lock = asyncio.Lock()
        completed = 0

        system = (
            "You are a strict sentiment annotator for Chinese game discussion. Judge only the "
            "attitude toward the target game or its player experience. Use positive for explicit "
            "praise, support, or anticipation; negative for explicit complaints, rejection, "
            "sarcasm, or risk feedback; neutral for questions, factual or support replies, "
            "marketing, emoji-only jokes, unclear context, and balanced mixed opinions. Interpret "
            "negation and resolved issues instead of matching isolated words. Topic definitions: "
            "performance=device compatibility, FPS, heat, crashes, latency; fairness=new-player or "
            "solo progression and matchmaking fairness; anti_abuse=cheats, illegal teaming, reports, "
            "bans; time_cost=grind, offline raids, base loss, wipes, continuous-online pressure; "
            "monetization=payments, skins, passes, inheritance; experience=controls, aiming/shooting, "
            "building mechanics or UI interaction only; visual_audio=graphics, art, sound; "
            "rust_identity=Rust fidelity, porting or product differences; community=team, social or "
            "community environment. Never use experience as a catch-all for launch anticipation, "
            "marketing, generic praise/complaints, raids, or time cost. Use other when no defined "
            "topic applies. Input rows are [id,text,kind,scope]. Return JSON "
            "only as {\"rows\":[[id,\"sentiment\",confidence,[\"topic\"]]]}. Include every input "
            "id exactly once. Confidence is 0 to 1. Do not add fields or explanations."
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=15),
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=max(4, self.settings.llm_concurrency + 1)),
        ) as client:

            async def run_batch(batch: list[ContentItem]) -> tuple[dict[int, LLMLabel], list[str], dict[str, int]]:
                nonlocal completed
                expected = {item.id for item in batch}
                warnings: list[str] = []
                parsed_labels: dict[int, LLMLabel] = {}
                usage = {"prompt_tokens": 0, "completion_tokens": 0}
                try:
                    async with semaphore:
                        payload, usage = await self._post_json(
                            client,
                            system=system,
                            user={
                                "keyword": keyword,
                                "prompt_version": PROMPT_VERSION,
                                "items": [
                                    [
                                        item.id,
                                        sanitize_text(item.text)[:600],
                                        item.kind,
                                        item.source_scope,
                                    ]
                                    for item in batch
                                ],
                            },
                        )
                    rows = payload.get("rows")
                    if not isinstance(rows, list):
                        raise ValueError("rows missing")
                    for row in rows:
                        if not isinstance(row, list) or len(row) < 4:
                            continue
                        try:
                            item_id = int(row[0])
                            confidence = max(0.0, min(1.0, float(row[2])))
                        except (TypeError, ValueError):
                            continue
                        sentiment = str(row[1]).casefold()
                        if item_id not in expected or sentiment not in SENTIMENTS:
                            continue
                        if confidence < self.settings.llm_confidence_threshold:
                            sentiment = "neutral"
                        raw_topics = row[3] if isinstance(row[3], list) else []
                        topics = list(
                            dict.fromkeys(
                                str(topic).casefold()
                                for topic in raw_topics
                                if str(topic).casefold() in TOPIC_IDS
                            )
                        )[:4]
                        parsed_labels[item_id] = LLMLabel(sentiment, round(confidence, 4), topics)
                    missing = expected - parsed_labels.keys()
                    if missing:
                        warnings.append(f"GPT-5.6 批次缺少 {len(missing)} 条结果，已使用本地回退")
                except LLMRequestError as exc:
                    warnings.append(f"GPT-5.6 批次失败，已使用本地回退：{exc}")
                except Exception as exc:
                    warnings.append(f"GPT-5.6 批次失败，已使用本地回退：{type(exc).__name__}")
                finally:
                    async with progress_lock:
                        completed += len(batch)
                        if progress:
                            await progress(completed, len(representatives))
                return parsed_labels, warnings, usage

            batch_results = await asyncio.gather(*(run_batch(batch) for batch in batches))

        representative_labels: dict[int, LLMLabel] = {}
        for labels, warnings, usage in batch_results:
            representative_labels.update(labels)
            result.warnings.extend(warnings)
            result.prompt_tokens += usage["prompt_tokens"]
            result.completion_tokens += usage["completion_tokens"]

        for group in duplicate_groups.values():
            label = representative_labels.get(group[0].id)
            if label:
                for item in group:
                    result.labels[item.id] = label
        result.warnings = list(dict.fromkeys(result.warnings))
        return result

    async def generate_report(
        self,
        *,
        keyword: str,
        metrics: dict[str, Any],
        topics: list[dict[str, Any]],
        keywords: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        data_quality: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, dict[str, int]]:
        if not self.configured:
            return None, "GPT-5.6 未配置，未生成 AI 深度研判", {}
        system = (
            "You are a senior game product opinion analyst. Write the report in Simplified Chinese. "
            "Use only the supplied metrics and evidence; never invent facts or numbers. Distinguish "
            "sentiment share, within-sample risk ranking, and statistical probability. Put incomplete "
            "sampling limits in caveats. Return JSON only with: executive_summary string; findings and "
            "risks arrays of 2-5 objects containing title, detail, evidence_ids; actions array of 3-6 "
            "objects containing priority (P0/P1/P2), title, rationale, action; caveats string array."
        )
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=15),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                parsed, usage = await self._post_json(
                    client,
                    system=system,
                    user={
                        "keyword": keyword,
                        "prompt_version": PROMPT_VERSION,
                        "metrics": metrics,
                        "topics": topics[:10],
                        "keywords": keywords[:20],
                        "evidence": evidence[:60],
                        "data_quality": data_quality,
                    },
                )
            normalized = self._normalize_report(
                parsed,
                {
                    int(item["id"])
                    for item in evidence
                    if isinstance(item, dict) and str(item.get("id", "")).isdigit()
                },
            )
            normalized["model"] = self.model
            normalized["prompt_version"] = PROMPT_VERSION
            return normalized, None, usage
        except LLMRequestError as exc:
            return None, f"GPT-5.6 深度研判失败，已保留结构化分析：{exc}", {}
        except Exception as exc:
            return None, f"GPT-5.6 深度研判失败，已保留结构化分析：{type(exc).__name__}", {}
