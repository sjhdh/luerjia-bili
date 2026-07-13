from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.main import app, runner
from backend.app.models import Job, OfficialAccount
from backend.app.sources.base import (
    CollectedOfficialAccount,
    CollectedVideo,
    CollectionResult,
)
from backend.app.sources.bilibili import EXPAND_REPLIES, BilibiliVisibleSource


class _MissingCommentRoot:
    async def count(self) -> int:
        return 0


class _Locator:
    @property
    def first(self) -> _MissingCommentRoot:
        return _MissingCommentRoot()


class _Mouse:
    async def wheel(self, _x: int, _y: int) -> None:
        return None


class _StalledCommentPage:
    def __init__(self) -> None:
        self.mouse = _Mouse()
        self.comment_reads = 0

    def locator(self, _selector: str) -> _Locator:
        return _Locator()

    async def evaluate(self, script: str) -> Any:
        if script == EXPAND_REPLIES:
            return 1
        if script.startswith("window.scrollTo"):
            return None
        self.comment_reads += 1
        return []

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


async def test_exhaustive_comments_stop_when_expand_controls_make_no_progress() -> None:
    source = object.__new__(BilibiliVisibleSource)
    page = _StalledCommentPage()

    rows, complete = await source._collect_comments(
        page,  # type: ignore[arg-type]
        CollectedVideo(
            external_id="BV-stalled",
            title="stalled comments",
            url="https://www.bilibili.com/video/BV-stalled",
            replies=100,
        ),
        quota=None,
        is_cancelled=_not_cancelled,
        exhaustive=True,
    )

    assert rows == []
    assert complete is False
    assert page.comment_reads == 20


async def _not_cancelled() -> bool:
    return False


async def test_first_official_checkpoint_treats_unflushed_count_as_zero() -> None:
    job_id = f"checkpoint-{uuid.uuid4()}"
    with TestClient(app):
        async with SessionLocal() as session:
            session.add(Job(id=job_id, keyword="失控进化", collection_metrics={}))
            await session.commit()

        await runner._persist_result(
            job_id,
            CollectionResult(
                official_account=CollectedOfficialAccount(
                    mid="3546785396034301",
                    title="失控进化",
                    url="https://space.bilibili.com/3546785396034301",
                    collected_video_count=1,
                )
            ),
        )

        async with SessionLocal() as session:
            account = await session.scalar(
                select(OfficialAccount).where(OfficialAccount.job_id == job_id)
            )

    assert account is not None
    assert account.collected_video_count == 1
