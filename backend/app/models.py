from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_LOGIN = "awaiting_login"
    COLLECTING = "collecting"
    AWAITING_TAPTAP_SELECTION = "awaiting_taptap_selection"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING,
    JobStatus.AWAITING_LOGIN,
    JobStatus.COLLECTING,
    JobStatus.AWAITING_TAPTAP_SELECTION,
    JobStatus.ANALYZING,
    JobStatus.RENDERING,
}
TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    keyword: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.PENDING.value, index=True)
    stage: Mapped[str] = mapped_column(String(80), default="等待开始")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    analysis_mode: Mapped[str] = mapped_column(String(20), default="local")
    time_range: Mapped[str] = mapped_column(String(20), default="90d")
    depth: Mapped[str] = mapped_column(String(20), default="standard")
    taptap_app_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    taptap_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    videos: Mapped[list[Video]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    contents: Mapped[list[ContentItem]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    source_apps: Mapped[list[SourceApp]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    report: Mapped[Report | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (Index("uq_video_job_external", "job_id", "external_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator: Mapped[str | None] = mapped_column(String(160), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    coins: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    danmakus: Mapped[int] = mapped_column(Integer, default=0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    selection_score: Mapped[float] = mapped_column(Float, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job: Mapped[Job] = relationship(back_populates="videos")
    contents: Mapped[list[ContentItem]] = relationship(back_populates="video")


class SourceApp(Base):
    __tablename__ = "source_apps"
    __table_args__ = (Index("uq_app_job_external", "job_id", "external_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    url: Mapped[str] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job: Mapped[Job] = relationship(back_populates="source_apps")


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (
        Index("uq_content_job_platform_external", "job_id", "platform", "external_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    author_hash: Mapped[str] = mapped_column(String(32), default="匿名用户")
    text: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="contents")
    video: Mapped[Video | None] = relationship(back_populates="contents")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="report")
