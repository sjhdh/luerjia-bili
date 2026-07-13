from __future__ import annotations

import csv
import io

from playwright.async_api import HttpCredentials, async_playwright

from ..models import ContentItem


def build_csv(items: list[ContentItem]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["平台", "类型", "匿名作者", "内容", "评分", "点赞", "情感", "置信度", "发布时间"]
    )
    for item in items:
        writer.writerow(
            [
                item.platform,
                item.kind,
                item.author_hash,
                item.text,
                item.rating or "",
                item.likes,
                item.sentiment or "",
                item.confidence if item.confidence is not None else "",
                item.published_at.isoformat() if item.published_at else "",
            ]
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


async def build_pdf(
    report_id: str,
    base_url: str,
    http_credentials: HttpCredentials | None = None,
    executable_path: str | None = None,
) -> bytes:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
        )
        page = await browser.new_page(
            viewport={"width": 1440, "height": 900},
            http_credentials=http_credentials,
        )
        try:
            response = await page.goto(
                f"{base_url.rstrip('/')}/reports/{report_id}?print=1",
                wait_until="networkidle",
                timeout=60_000,
            )
            if response is None or not response.ok:
                status = response.status if response is not None else "no response"
                raise RuntimeError(f"Report page returned {status}")
            await page.locator(".report-page").wait_for(state="visible", timeout=30_000)
            await page.locator(".chart-root svg").first.wait_for(state="visible", timeout=30_000)
            await page.evaluate("document.fonts.ready")
            await page.emulate_media(media="print")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
            )
        finally:
            await browser.close()
