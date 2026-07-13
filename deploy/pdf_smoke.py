from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import Job, JobStatus, Report
from backend.app.security import SessionSigner
from backend.app.services.exporter import build_pdf


def smoke_report(job_id: str) -> dict[str, object]:
    distribution = [
        {"name": "positive", "label": "正面", "count": 72, "percentage": 72},
        {"name": "neutral", "label": "中性", "count": 12, "percentage": 12},
        {"name": "negative", "label": "负面", "count": 16, "percentage": 16},
    ]
    samples = {
        "positive": [
            {
                "id": 1,
                "platform": "taptap",
                "kind": "review",
                "author": "匿名用户 #A001",
                "text": "玩法有趣，整体体验稳定。",
                "rating": 5,
                "likes": 18,
                "confidence": 1.0,
            }
        ],
        "neutral": [
            {
                "id": 2,
                "platform": "bilibili",
                "kind": "comment",
                "author": "匿名用户 #B002",
                "text": "内容不错，后续优化值得关注。",
                "rating": None,
                "likes": 8,
                "confidence": 0.82,
            }
        ],
        "negative": [
            {
                "id": 3,
                "platform": "bilibili",
                "kind": "comment",
                "author": "匿名用户 #C003",
                "text": "偶尔掉帧，希望尽快改善。",
                "rating": None,
                "likes": 12,
                "confidence": 0.91,
            }
        ],
    }
    return {
        "id": job_id,
        "keyword": "部署冒烟验证",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "partial": False,
        "warnings": [],
        "hero": {"cover_url": None, "subtitle": "服务器 PDF 导出链路验证"},
        "metrics": {
            "video_count": 1,
            "selected_video_count": 1,
            "comment_count": 60,
            "danmaku_count": 40,
            "review_count": 100,
            "taptap_score": 8.6,
            "overall_positive": 72,
            "overall_neutral": 12,
            "overall_negative": 16,
        },
        "sentiment": {
            "overall": {"total": 200, "items": distribution},
            "bilibili": {"total": 100, "items": distribution},
            "taptap": {"total": 100, "items": distribution},
        },
        "rating_distribution": [
            {"star": 5, "count": 52, "percentage": 52},
            {"star": 4, "count": 20, "percentage": 20},
            {"star": 3, "count": 12, "percentage": 12},
            {"star": 2, "count": 9, "percentage": 9},
            {"star": 1, "count": 7, "percentage": 7},
        ],
        "timeline": [
            {"date": "2026-07-11", "positive": 20, "neutral": 4, "negative": 6, "total": 30},
            {"date": "2026-07-12", "positive": 24, "neutral": 4, "negative": 5, "total": 33},
            {"date": "2026-07-13", "positive": 28, "neutral": 4, "negative": 5, "total": 37},
        ],
        "keywords": [
            {"word": "玩法", "count": 42, "negative_ratio": 0.12},
            {"word": "优化", "count": 31, "negative_ratio": 0.55},
            {"word": "画面", "count": 24, "negative_ratio": 0.18},
        ],
        "tags": [{"name": "玩法设计", "count": 42}, {"name": "运行稳定性", "count": 31}],
        "topics": [
            {
                "id": 1,
                "name": "性能优化",
                "keywords": ["优化", "掉帧"],
                "size": 31,
                "negative_ratio": 55,
                "risk_score": 4.2,
                "samples": ["偶尔掉帧"],
            }
        ],
        "samples": samples,
        "videos": [
            {
                "id": "BVSMOKE",
                "title": "部署验证视频",
                "url": "https://www.bilibili.com",
                "cover_url": None,
                "creator": "匿名创作者",
                "views": 120000,
                "likes": 6800,
                "coins": 900,
                "favorites": 1200,
                "replies": 600,
                "danmakus": 400,
                "selection_score": 0.86,
                "selected": True,
                "score_components": {},
            }
        ],
        "source_app": {
            "id": "smoke",
            "title": "部署验证",
            "url": "https://www.taptap.cn",
            "score": 8.6,
            "rating_count": 100,
        },
        "model_quality": {
            "sample_size": 100,
            "accuracy": 0.84,
            "macro_f1": 0.81,
            "confusion": [[68, 3, 1], [4, 6, 2], [2, 4, 10]],
            "model": "lxyuan/distilbert-base-multilingual-cased-sentiments-student",
            "revision": "cf991100d706c13c0a080c097134c05b7f436c45",
        },
        "summary": {
            "overview": "部署验证报告已成功渲染。",
            "positives": ["核心页面可访问"],
            "risks": ["持续观察资源占用"],
            "recommendations": ["定期执行导出冒烟检查"],
            "enhanced": False,
        },
        "methodology": {
            "bilibili": "可见网页低频采集",
            "taptap": "公开网页评价",
            "combined": "平台等权平均",
        },
    }


async def main() -> None:
    settings = get_settings()
    job_id = f"pdf-smoke-{uuid.uuid4().hex[:12]}"
    session_cookie = None
    if settings.admin_password_value:
        session_cookie = SessionSigner(
            settings.session_secret_value,
            ttl_seconds=settings.session_ttl_hours * 60 * 60,
        ).issue(settings.admin_username)
    async with SessionLocal() as session:
        session.add(
            Job(
                id=job_id,
                keyword="部署冒烟验证",
                status=JobStatus.COMPLETED.value,
                stage="报告已完成",
                progress=100,
            )
        )
        session.add(Report(job_id=job_id, payload=smoke_report(job_id)))
        await session.commit()
    try:
        content = await build_pdf(
            job_id,
            settings.pdf_base_url or f"http://127.0.0.1:{settings.port}",
            session_cookie=session_cookie,
            executable_path=settings.browser_executable_path,
        )
        print(f"PDF smoke output: header={content[:4]!r}, bytes={len(content)}")
        if not content.startswith(b"%PDF") or len(content) < 10_000:
            raise SystemExit("PDF smoke output is invalid")
    finally:
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                await session.delete(job)
                await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
