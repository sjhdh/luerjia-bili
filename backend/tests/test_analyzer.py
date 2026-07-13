from backend.app.config import get_settings
from backend.app.models import ContentItem, Job, SourceApp, Video
from backend.app.services.analyzer import analyze_job


async def test_analyzer_builds_complete_report_with_rating_calibration() -> None:
    job = Job(id="job-test", keyword="测试游戏", analysis_mode="local")
    video = Video(
        id=1,
        job_id=job.id,
        external_id="BV1TEST",
        title="测试游戏实况",
        url="https://www.bilibili.com/video/BV1TEST",
        selected=True,
        selection_score=0.88,
    )
    app = SourceApp(
        id=1,
        job_id=job.id,
        external_id="123",
        title="测试游戏",
        url="https://www.taptap.cn/app/123",
        score=8.6,
        rating_count=1000,
        tags=[{"name": "画面优秀", "count": 20}],
    )
    positive = ["画面优秀玩法有趣值得推荐" for _ in range(8)]
    negative = ["掉帧发热卡顿体验失望" for _ in range(8)]
    items = []
    for index, text in enumerate(positive + negative, start=1):
        items.append(
            ContentItem(
                id=index,
                job_id=job.id,
                platform="taptap" if index <= 4 else "bilibili",
                kind="review" if index <= 4 else "comment",
                external_id=str(index),
                author_hash=f"匿名用户 #{index:04d}",
                text=text,
                rating=5 if index <= 2 else 1 if index <= 4 else None,
                likes=index,
            )
        )
    payload, warnings = await analyze_job(get_settings(), job, [video], [app], items)
    assert payload["metrics"]["video_count"] == 1
    assert payload["metrics"]["review_count"] == 4
    assert payload["model_quality"]["sample_size"] == 4
    assert payload["keywords"]
    assert payload["summary"]["overview"]
    assert not warnings
