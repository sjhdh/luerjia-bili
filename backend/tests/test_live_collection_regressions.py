from __future__ import annotations

import uuid
from typing import Any

import pytest
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


class _CollectionPage:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class _CollectionContext:
    def __init__(self) -> None:
        self.page = _CollectionPage()
        self.pages = [self.page]

    async def new_page(self) -> _CollectionPage:
        return self.page


class _CollectionManager:
    def __init__(self) -> None:
        self.context = _CollectionContext()

    async def session_state(self, _platform: str) -> tuple[bool, bool]:
        return True, True

    async def connect(self, **_kwargs: Any) -> _CollectionContext:
        return self.context

    def is_workspace_page(self, _platform: str, _page: _CollectionPage) -> bool:
        return False

    def clear_risk(self, _platform: str) -> None:
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


async def _ignore_progress(_stage: str, _progress: int, _message: str) -> None:
    return None


async def test_official_phase_is_checkpointed_before_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _CollectionManager()
    source = BilibiliVisibleSource(object(), manager)  # type: ignore[arg-type]
    persisted: list[CollectionResult] = []

    async def collect_official(*_args: Any, **_kwargs: Any) -> CollectionResult:
        return CollectionResult(
            official_account=CollectedOfficialAccount(
                mid="3546785396034301",
                title="失控进化",
                url="https://space.bilibili.com/3546785396034301",
                expected_video_count=1,
                collected_video_count=1,
            ),
            videos=[
                CollectedVideo(
                    external_id="BV-official",
                    title="official",
                    url="https://www.bilibili.com/video/BV-official",
                    raw_meta={"metadata_source": "initial_state"},
                )
            ],
            metrics={
                "official": {
                    "expected_videos": 1,
                    "collected_videos": 1,
                    "expected_comments": 0,
                    "collected_comments": 0,
                    "complete_videos": 1,
                    "videos": [],
                }
            },
        )

    async def fail_discovery(*_args: Any, **_kwargs: Any) -> CollectionResult:
        raise ValueError("could not convert string to float: '...'")

    async def persist(result: CollectionResult) -> None:
        persisted.append(result)

    monkeypatch.setattr(source, "_collect_official", collect_official)
    monkeypatch.setattr(source, "_collect_discovery", fail_discovery)

    with pytest.raises(ValueError, match="float"):
        await source.collect(
            keyword="失控进化",
            time_range="90d",
            depth="standard",
            progress=_ignore_progress,
            is_cancelled=_not_cancelled,
            official_mid="3546785396034301",
            include_discovery=True,
            persist=persist,
        )

    assert len(persisted) == 1
    assert persisted[0].metrics["official_phase_complete"] is True
    assert persisted[0].metrics["bilibili"]["official"]["collected_videos"] == 1


async def test_completed_official_phase_is_skipped_and_still_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _CollectionManager()
    source = BilibiliVisibleSource(object(), manager)  # type: ignore[arg-type]
    excluded: set[str] = set()

    async def unexpected_official(*_args: Any, **_kwargs: Any) -> CollectionResult:
        raise AssertionError("completed official phase should not run again")

    async def collect_discovery(
        *_args: Any, exclude_ids: set[str], **_kwargs: Any
    ) -> CollectionResult:
        excluded.update(exclude_ids)
        return CollectionResult()

    monkeypatch.setattr(source, "_collect_official", unexpected_official)
    monkeypatch.setattr(source, "_collect_discovery", collect_discovery)

    await source.collect(
        keyword="失控进化",
        time_range="90d",
        depth="standard",
        progress=_ignore_progress,
        is_cancelled=_not_cancelled,
        official_mid="3546785396034301",
        include_discovery=True,
        official_phase_complete=True,
        existing_official_ids={"BV-official"},
    )

    assert excluded == {"BV-official"}


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
