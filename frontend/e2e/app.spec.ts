import { expect, test } from "@playwright/test";
import { demoReport } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/bilibili/session", async (route) => {
    await route.fulfill({ json: { running: true, authenticated: true, login_method: "window", qr_ready: false, qr_expires_at: null, message: "B站登录态可用" } });
  });
  await page.route("**/api/v1/jobs", async (route) => {
    await route.fulfill({ json: [{ id: "demo", keyword: "失控进化", status: "completed", stage: "报告已完成", progress: 100, message: "报告已生成", analysis_mode: "local", time_range: "90d", depth: "standard", taptap_app_id: "733908", taptap_candidates: [], warnings: [], partial: false, cancel_requested: false, created_at: "2026-07-13T04:00:00Z", updated_at: "2026-07-13T04:30:00Z", finished_at: "2026-07-13T04:30:00Z" }] });
  });
  await page.route("**/api/v1/reports/demo", async (route) => {
    await route.fulfill({ json: demoReport });
  });
});

test("workbench is usable without authentication", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "舆情任务" })).toBeVisible();
  await expect(page.getByText("B站已连接")).toBeVisible();
  await expect(page.getByRole("button", { name: "开始分析" })).toBeDisabled();
  await page.getByPlaceholder("输入游戏、产品或事件名称").fill("失控进化");
  await expect(page.getByRole("button", { name: "开始分析" })).toBeEnabled();
});

test("server workbench presents a refreshable Bilibili QR login", async ({ page }, testInfo) => {
  await page.unroute("**/api/v1/bilibili/session");
  await page.route("**/api/v1/bilibili/session", async (route) => {
    await route.fulfill({ json: { running: false, authenticated: false, login_method: "qr", qr_ready: false, qr_expires_at: null, message: "尚未生成登录二维码" } });
  });
  await page.route("**/api/v1/bilibili/qr-login", async (route) => {
    await route.fulfill({ json: { running: true, authenticated: false, login_method: "qr", qr_ready: true, qr_expires_at: new Date(Date.now() + 120_000).toISOString(), message: "登录二维码已生成" } });
  });
  await page.route("**/api/v1/bilibili/qr-code.png**", async (route) => {
    await route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64") });
  });

  await page.goto("/");
  await expect(page.getByText("服务器私有工作台")).toBeVisible();
  await page.getByRole("button", { name: "生成二维码" }).click();
  await expect(page.getByRole("heading", { name: "使用哔哩哔哩客户端扫码" })).toBeVisible();
  await expect(page.getByAltText("B站登录二维码")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新生成" })).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("qr-login.png"), fullPage: true });
});

test("report renders every evidence section without horizontal overflow", async ({ page }, testInfo) => {
  await page.goto("/reports/demo");
  await expect(page.getByRole("heading", { name: "《失控进化》舆情分析" })).toBeVisible();
  for (const heading of ["星级评分分布", "舆情占比", "高频讨论词 TOP 15", "核心风险议题", "重点视频互动", "模型质量", "舆情总结", "合规与方法说明"]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
  await page.screenshot({ path: testInfo.outputPath("report.png"), fullPage: true });
});
