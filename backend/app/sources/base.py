from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ProgressCallback = Callable[[str, int, str], Awaitable[None]]
CancelCallback = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class CollectedVideo:
    external_id: str
    title: str
    url: str
    cover_url: str | None = None
    creator: str | None = None
    published_at: datetime | None = None
    views: int = 0
    likes: int = 0
    coins: int = 0
    favorites: int = 0
    replies: int = 0
    danmakus: int = 0
    description: str = ""
    raw_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectedContent:
    external_id: str
    platform: str
    kind: str
    text: str
    author: str | None = None
    video_external_id: str | None = None
    rating: int | None = None
    likes: int = 0
    published_at: datetime | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectedApp:
    external_id: str
    title: str
    url: str
    cover_url: str | None = None
    score: float | None = None
    rating_count: int = 0
    tags: list[dict[str, Any]] = field(default_factory=list)
    raw_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectionResult:
    videos: list[CollectedVideo] = field(default_factory=list)
    contents: list[CollectedContent] = field(default_factory=list)
    apps: list[CollectedApp] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SourcePaused(RuntimeError):
    pass


class AwaitingSourceSelection(RuntimeError):
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        super().__init__("需要确认 TapTap 应用")
        self.candidates = candidates
