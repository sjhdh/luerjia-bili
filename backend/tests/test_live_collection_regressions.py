from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.main import app, runner
from backend.app.models import ContentItem, Job, OfficialAccount
from backend.app.sources.base import (
    CollectedContent,
    CollectedOfficialAccount,
    CollectedVideo,
    CollectionResult,
)
from backend.app.sources.bilibili import (
    COMMENT_EXTRACTOR,
    DANMAKU_EXTRACTOR,
    EXPAND_REPLIES,
    BilibiliVisibleSource,
)
from backend.app.sources.taptap import (
    TapTapNavigationError,
    TapTapVisibleSource,
)


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


def test_bilibili_extractors_cover_current_shadow_dom_contract() -> None:
    assert "querySelector('#contents')" in COMMENT_EXTRACTOR
    assert "'data-id'" in COMMENT_EXTRACTOR
    assert "'data-id', 'id'" not in COMMENT_EXTRACTOR
    assert "点击查看" in EXPAND_REPLIES
    assert "下一页" in EXPAND_REPLIES
    assert ".dm-info-row .dm-info-dm" in DANMAKU_EXTRACTOR
    assert "getAttribute?.('title')" in DANMAKU_EXTRACTOR


class _DanmakuLocator:
    def __init__(self, page: _DanmakuPage, kind: str) -> None:
        self.page = page
        self.kind = kind

    @property
    def first(self) -> _DanmakuLocator:
        return self

    async def count(self) -> int:
        return 1

    async def click(self, **_kwargs: Any) -> None:
        self.page.trigger_clicked = True

    async def wait_for(self, **_kwargs: Any) -> None:
        return None

    async def hover(self, **_kwargs: Any) -> None:
        self.page.scroll_hovered = True


class _DanmakuPage:
    def __init__(self) -> None:
        self.mouse = _Mouse()
        self.trigger_clicked = False
        self.scroll_hovered = False
        self.reads = 0

    def locator(self, selector: str) -> _DanmakuLocator:
        kind = "trigger" if "collapse-wrap-folded" in selector else "row"
        if "long-list-wrap" in selector:
            kind = "scroll"
        return _DanmakuLocator(self, kind)

    async def evaluate(self, script: str) -> list[dict[str, str]]:
        assert script == DANMAKU_EXTRACTOR
        self.reads += 1
        return [
            {"id": "0", "text": "真实弹幕"},
            {"id": "1", "text": "重复文字"},
            {"id": "2", "text": "重复文字"},
        ]

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


async def test_danmaku_collection_uses_visible_row_ids_and_preserves_duplicates() -> None:
    source = object.__new__(BilibiliVisibleSource)
    page = _DanmakuPage()
    rows = await source._collect_danmakus(
        page,  # type: ignore[arg-type]
        CollectedVideo(
            external_id="BV-danmaku",
            title="danmaku",
            url="https://www.bilibili.com/video/BV-danmaku",
        ),
        3,
        _not_cancelled,
    )

    assert page.trigger_clicked is True
    assert [row.text for row in rows] == ["真实弹幕", "重复文字", "重复文字"]
    assert len({row.external_id for row in rows}) == 3


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


async def test_incomplete_official_phase_remains_resumable(
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
            ),
            videos=[
                CollectedVideo(
                    external_id="BV-partial",
                    title="partial",
                    url="https://www.bilibili.com/video/BV-partial",
                    raw_meta={"metadata_source": "initial_state"},
                )
            ],
            metrics={
                "official": {
                    "collected_videos": 1,
                    "complete_videos": 0,
                    "videos": [
                        {
                            "video_id": "BV-partial",
                            "expected_comments": 10,
                            "collected_comments": 5,
                            "complete": False,
                        }
                    ],
                }
            },
        )

    async def collect_discovery(*_args: Any, **_kwargs: Any) -> CollectionResult:
        return CollectionResult()

    async def persist(result: CollectionResult) -> None:
        persisted.append(result)

    monkeypatch.setattr(source, "_collect_official", collect_official)
    monkeypatch.setattr(source, "_collect_discovery", collect_discovery)
    await source.collect(
        keyword="失控进化",
        time_range="7d",
        depth="light",
        progress=_ignore_progress,
        is_cancelled=_not_cancelled,
        official_mid="3546785396034301",
        include_discovery=True,
        persist=persist,
    )

    assert persisted[0].metrics["official_phase_complete"] is False


class _TapBody:
    async def wait_for(self, **_kwargs: Any) -> None:
        return None


class _TapResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _TapNavigationPage:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.goto_kwargs: dict[str, Any] = {}

    async def goto(self, _url: str, **kwargs: Any) -> _TapResponse:
        self.goto_kwargs = kwargs
        return _TapResponse(self.status)

    async def wait_for_load_state(self, *_args: Any, **_kwargs: Any) -> None:
        raise PlaywrightTimeoutError("third-party resource remained pending")

    def locator(self, selector: str) -> _TapBody:
        assert selector == "body"
        return _TapBody()


async def test_taptap_navigation_accepts_committed_page_when_dom_wait_stalls() -> None:
    source = object.__new__(TapTapVisibleSource)
    page = _TapNavigationPage()

    await source._navigate(
        page,  # type: ignore[arg-type]
        "https://www.taptap.cn/app/733908",
        "打开 TapTap 应用页",
    )

    assert page.goto_kwargs["wait_until"] == "commit"
    assert page.goto_kwargs["timeout"] == 30_000


async def test_taptap_navigation_reports_rejected_http_status() -> None:
    source = object.__new__(TapTapVisibleSource)
    page = _TapNavigationPage(status=405)

    with pytest.raises(TapTapNavigationError, match="HTTP 405") as error:
        await source._navigate(
            page,  # type: ignore[arg-type]
            "https://www.taptap.cn/app/733908",
            "打开 TapTap 应用页",
        )

    assert error.value.retryable is False


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
            session.add(
                Job(
                    id=job_id,
                    keyword="失控进化",
                    status="completed",
                    collection_metrics={},
                )
            )
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


async def test_official_checkpoint_metrics_use_persisted_union_count() -> None:
    job_id = f"checkpoint-union-{uuid.uuid4()}"
    video = CollectedVideo(
        external_id="BV-union",
        title="union",
        url="https://www.bilibili.com/video/BV-union",
        replies=2,
        source_scope="bilibili_official",
    )
    with TestClient(app):
        async with SessionLocal() as session:
            session.add(
                Job(
                    id=job_id,
                    keyword="失控进化",
                    status="completed",
                    collection_metrics={},
                )
            )
            await session.commit()

        await runner._persist_result(
            job_id,
            CollectionResult(
                videos=[video],
                contents=[
                    CollectedContent(
                        external_id="reply-1",
                        platform="bilibili",
                        kind="comment",
                        text="第一条评论",
                        video_external_id=video.external_id,
                        source_scope="bilibili_official",
                    )
                ],
            ),
        )
        await runner._persist_result(
            job_id,
            CollectionResult(
                videos=[video],
                contents=[
                    CollectedContent(
                        external_id="reply-2",
                        platform="bilibili",
                        kind="comment",
                        text="第二条评论",
                        video_external_id=video.external_id,
                        source_scope="bilibili_official",
                    )
                ],
                warnings=["官号评论完整采集 0/1 个视频，未完成视频可重试续采"],
                metrics={
                    "official_checkpoint": {
                        "video_id": video.external_id,
                        "expected_comments": 2,
                        "collected_comments": 1,
                        "complete": False,
                    },
                    "bilibili": {
                        "official": {
                            "collected_videos": 1,
                            "complete_videos": 0,
                            "collected_comments": 1,
                            "videos": [
                                {
                                    "video_id": video.external_id,
                                    "expected_comments": 2,
                                    "collected_comments": 1,
                                    "complete": False,
                                }
                            ],
                        }
                    },
                },
            ),
        )
        async with SessionLocal() as session:
            stored = await session.get(Job, job_id)

    assert stored is not None
    checkpoint = stored.collection_metrics["official_checkpoint"]
    assert checkpoint["collected_comments"] == 2
    assert checkpoint["complete"] is True
    assert stored.collection_metrics["bilibili"]["official"]["complete_videos"] == 1
    assert stored.warnings == []


async def test_taptap_platform_is_canonicalized_to_taptap_scope() -> None:
    job_id = f"taptap-scope-{uuid.uuid4()}"
    with TestClient(app):
        async with SessionLocal() as session:
            session.add(
                Job(
                    id=job_id,
                    keyword="失控进化",
                    status="completed",
                    collection_metrics={},
                )
            )
            await session.commit()

        await runner._persist_result(
            job_id,
            CollectionResult(
                contents=[
                    CollectedContent(
                        external_id="tap-review",
                        platform="taptap",
                        kind="review",
                        text="评价正文",
                    )
                ]
            ),
        )
        async with SessionLocal() as session:
            item = await session.scalar(
                select(ContentItem).where(ContentItem.job_id == job_id)
            )

    assert item is not None
    assert item.source_scope == "taptap"
