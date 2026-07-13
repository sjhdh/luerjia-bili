from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from ..config import Settings
from ..database import SessionLocal
from ..models import ContentItem, Job, JobStatus, Report, SourceApp, Video
from ..sources.base import AwaitingSourceSelection, CollectionResult, SourcePaused
from ..sources.bilibili import BilibiliVisibleSource
from ..sources.browser import BilibiliBrowserManager
from ..sources.taptap import TapTapVisibleSource
from .analyzer import analyze_job
from .privacy import anonymize_author, sanitize_text


class JobRunner:
    def __init__(self, settings: Settings, browser_manager: BilibiliBrowserManager) -> None:
        self.settings = settings
        self.browser_manager = browser_manager
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker: asyncio.Task[None] | None = None
        self._queued: set[str] = set()

    async def start(self) -> None:
        await self._recover_jobs()
        await self.cleanup_retention()
        self.worker = asyncio.create_task(self._work_loop(), name="sentiment-job-runner")

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None

    async def enqueue(self, job_id: str) -> None:
        if job_id not in self._queued:
            self._queued.add(job_id)
            await self.queue.put(job_id)

    async def _work_loop(self) -> None:
        while True:
            job_id = await self.queue.get()
            self._queued.discard(job_id)
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._set_status(
                    job_id,
                    JobStatus.FAILED,
                    "任务失败",
                    100,
                    f"{type(exc).__name__}: {exc}",
                    finished=True,
                )
            finally:
                self.queue.task_done()

    async def _recover_jobs(self) -> None:
        interrupted = [
            JobStatus.COLLECTING.value,
            JobStatus.ANALYZING.value,
            JobStatus.RENDERING.value,
        ]
        async with SessionLocal() as session:
            await session.execute(
                update(Job)
                .where(Job.status.in_(interrupted))
                .values(
                    status=JobStatus.FAILED.value,
                    stage="应用重启",
                    message="任务在应用重启时中断，可点击重试",
                    progress=100,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            pending = list(
                (await session.scalars(select(Job.id).where(Job.status == JobStatus.PENDING.value))).all()
            )
            await session.commit()
        for job_id in pending:
            await self.enqueue(job_id)

    async def cleanup_retention(self) -> None:
        now = datetime.now(timezone.utc)
        raw_before = now - timedelta(days=self.settings.raw_retention_days)
        report_before = now - timedelta(days=self.settings.report_retention_days)
        async with SessionLocal() as session:
            await session.execute(delete(ContentItem).where(ContentItem.created_at < raw_before))
            await session.execute(delete(Report).where(Report.created_at < report_before))
            await session.commit()

    async def _run_job(self, job_id: str) -> None:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job or job.cancel_requested:
                return
            existing_videos = await session.scalar(
                select(func.count(Video.id)).where(Video.job_id == job_id)
            )

        if not existing_videos:
            await self._set_status(job_id, JobStatus.COLLECTING, "搜索 B站视频", 2, "准备采集")
            try:
                bili_result = await BilibiliVisibleSource(
                    self.settings, self.browser_manager
                ).collect(
                    keyword=job.keyword,
                    time_range=job.time_range,
                    depth=job.depth,
                    progress=lambda stage, progress, message: self._progress(job_id, stage, progress, message),
                    is_cancelled=lambda: self._is_cancelled(job_id),
                )
            except SourcePaused as exc:
                await self._set_status(
                    job_id,
                    JobStatus.AWAITING_LOGIN,
                    "等待人工处理",
                    0,
                    str(exc),
                )
                return
            await self._persist_result(job_id, bili_result)

        if await self._is_cancelled(job_id):
            await self._set_status(job_id, JobStatus.CANCELLED, "已取消", 100, "任务已取消", finished=True)
            return

        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            existing_apps = await session.scalar(
                select(func.count(SourceApp.id)).where(SourceApp.job_id == job_id)
            )
        if not existing_apps:
            try:
                tap_result = await TapTapVisibleSource(self.settings).collect(
                    keyword=job.keyword,
                    depth=job.depth,
                    selected_app_id=job.taptap_app_id,
                    progress=lambda stage, progress, message: self._progress(job_id, stage, progress, message),
                    is_cancelled=lambda: self._is_cancelled(job_id),
                )
                await self._persist_result(job_id, tap_result)
            except AwaitingSourceSelection as exc:
                async with SessionLocal() as session:
                    current = await session.get(Job, job_id)
                    if current:
                        current.status = JobStatus.AWAITING_TAPTAP_SELECTION.value
                        current.stage = "选择 TapTap 应用"
                        current.progress = 83
                        current.message = "自动匹配不够确定，请选择正确的 TapTap 应用"
                        current.taptap_candidates = exc.candidates
                        await session.commit()
                return
            except Exception as exc:
                await self._add_warning(job_id, f"TapTap 采集失败：{type(exc).__name__}")

        await self._set_status(job_id, JobStatus.ANALYZING, "运行舆情模型", 92, "正在分类情感与聚类议题")
        async with SessionLocal() as session:
            query_result = await session.execute(
                select(Job)
                .where(Job.id == job_id)
                .options(
                    selectinload(Job.videos),
                    selectinload(Job.contents),
                    selectinload(Job.source_apps),
                    selectinload(Job.report),
                )
            )
            current = query_result.scalar_one()
            current.partial = not bool(current.source_apps) or not bool(current.videos)
            payload, analysis_warnings = await analyze_job(
                self.settings,
                current,
                current.videos,
                current.source_apps,
                current.contents,
            )
            if analysis_warnings:
                current.warnings = list(dict.fromkeys(current.warnings + analysis_warnings))
                payload["warnings"] = current.warnings
            await session.flush()
            if current.report:
                current.report.payload = payload
            else:
                current.report = Report(job_id=current.id, payload=payload)
            current.status = JobStatus.RENDERING.value
            current.stage = "生成报告"
            current.progress = 98
            current.message = "正在整理图表与导出数据"
            await session.commit()

        await self._set_status(
            job_id,
            JobStatus.PARTIAL if current.partial else JobStatus.COMPLETED,
            "报告已完成",
            100,
            "报告已生成，可查看并导出",
            finished=True,
        )

    async def _persist_result(self, job_id: str, result: CollectionResult) -> None:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            if result.warnings:
                job.warnings = list(dict.fromkeys(job.warnings + result.warnings))
            video_map: dict[str, Video] = {}
            for source_video in result.videos:
                existing = await session.scalar(
                    select(Video).where(
                        Video.job_id == job_id,
                        Video.external_id == source_video.external_id,
                    )
                )
                video = existing or Video(
                    job_id=job_id,
                    external_id=source_video.external_id,
                    title=source_video.title,
                    url=source_video.url,
                )
                video.title = source_video.title
                video.url = source_video.url
                video.cover_url = source_video.cover_url
                video.creator = source_video.creator
                video.published_at = source_video.published_at
                video.views = source_video.views
                video.likes = source_video.likes
                video.coins = source_video.coins
                video.favorites = source_video.favorites
                video.replies = source_video.replies
                video.danmakus = source_video.danmakus
                video.relevance_score = float(source_video.raw_meta.get("relevance_score", 0))
                video.selection_score = float(source_video.raw_meta.get("selection_score", 0))
                video.selected = bool(source_video.raw_meta.get("selected", False))
                video.raw_meta = source_video.raw_meta
                session.add(video)
                await session.flush()
                video_map[source_video.external_id] = video
            for source_app in result.apps:
                app = await session.scalar(
                    select(SourceApp).where(
                        SourceApp.job_id == job_id,
                        SourceApp.external_id == source_app.external_id,
                    )
                ) or SourceApp(
                    job_id=job_id,
                    external_id=source_app.external_id,
                    title=source_app.title,
                    url=source_app.url,
                )
                app.title = source_app.title
                app.url = source_app.url
                app.cover_url = source_app.cover_url
                app.score = source_app.score
                app.rating_count = source_app.rating_count
                app.tags = source_app.tags
                app.raw_meta = source_app.raw_meta
                session.add(app)
            for source_content in result.contents:
                text = sanitize_text(source_content.text)
                if len(text) < 2:
                    continue
                exists = await session.scalar(
                    select(ContentItem.id).where(
                        ContentItem.job_id == job_id,
                        ContentItem.platform == source_content.platform,
                        ContentItem.external_id == source_content.external_id,
                    )
                )
                if exists:
                    continue
                linked_video: Video | None = video_map.get(
                    source_content.video_external_id or ""
                )
                if linked_video is None and source_content.video_external_id:
                    linked_video = await session.scalar(
                        select(Video).where(
                            Video.job_id == job_id,
                            Video.external_id == source_content.video_external_id,
                        )
                    )
                session.add(
                    ContentItem(
                        job_id=job_id,
                        video_id=linked_video.id if linked_video else None,
                        platform=source_content.platform,
                        kind=source_content.kind,
                        external_id=source_content.external_id,
                        author_hash=anonymize_author(source_content.author, job_id),
                        text=text,
                        rating=source_content.rating,
                        likes=source_content.likes,
                        published_at=source_content.published_at,
                        raw_meta=source_content.raw_meta,
                    )
                )
            await session.commit()

    async def _progress(self, job_id: str, stage: str, progress: int, message: str) -> None:
        await self._set_status(job_id, JobStatus.COLLECTING, stage, progress, message)

    async def _set_status(
        self,
        job_id: str,
        status: JobStatus,
        stage: str,
        progress: int,
        message: str,
        finished: bool = False,
    ) -> None:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            job.status = status.value
            job.stage = stage
            job.progress = progress
            job.message = message
            job.finished_at = datetime.now(timezone.utc) if finished else None
            await session.commit()

    async def _add_warning(self, job_id: str, warning: str) -> None:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job:
                job.warnings = list(dict.fromkeys(job.warnings + [warning]))
                job.partial = True
                await session.commit()

    async def _is_cancelled(self, job_id: str) -> bool:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            return not job or job.cancel_requested


job_runner: JobRunner | None = None


def init_job_runner(settings: Settings, browser_manager: BilibiliBrowserManager) -> JobRunner:
    global job_runner
    if job_runner is None:
        job_runner = JobRunner(settings, browser_manager)
    return job_runner
