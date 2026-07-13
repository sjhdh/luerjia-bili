import { expect, test } from "@playwright/test";
import { demoReport } from "./fixtures";

const platformState = (platform: "bilibili" | "taptap", authenticated = true) => ({ platform, running: true, authenticated, login_method: "window", qr_ready: false, qr_expires_at: null, message: authenticated ? "登录态可用" : "尚未登录", workspace_ready: true, current_url: platform === "bilibili" ? "https://passport.bilibili.com/login" : "https://www.taptap.cn", page_title: `${platform} 登录`, risk_detected: false });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({ json: { authenticated: true, username: "operator" } }));
  await page.route("**/api/v1/platforms/bilibili/session", (route) => route.fulfill({ json: platformState("bilibili") }));
  await page.route("**/api/v1/platforms/taptap/session", (route) => route.fulfill({ json: platformState("taptap") }));
  await page.route("**/api/v1/jobs", async (route) => {
    await route.fulfill({ json: [{ id: "demo", keyword: "失控进化", status: "completed", stage: "报告已完成", progress: 100, message: "报告已生成", analysis_mode: "local", time_range: "90d", depth: "standard", official_bilibili_url: "https://space.bilibili.com/3546785396034301", official_mid: "3546785396034301", include_discovery: true, include_taptap: true, taptap_app_id: "733908", taptap_app_url: "https://www.taptap.cn/app/733908", taptap_candidates: [], collection_metrics: {}, warnings: [], partial: false, cancel_requested: false, created_at: "2026-07-13T04:00:00Z", updated_at: "2026-07-13T04:30:00Z", finished_at: "2026-07-13T04:30:00Z" }] });
  });
  await page.route("**/api/v1/reports/demo", (route) => route.fulfill({ json: demoReport }));
});

test("unauthenticated operators see the application login page", async ({ page }) => {
  await page.unroute("**/api/v1/auth/session");
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({ json: { authenticated: false, username: null } }));
  await page.route("**/api/v1/auth/login", (route) => route.fulfill({ json: { authenticated: true, username: "operator" } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "登录工作台" })).toBeVisible();
  await page.getByLabel("密码").fill("test-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "分析任务" })).toBeVisible();
});

test("workbench exposes official, discovery, and TapTap inputs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "分析任务" })).toBeVisible();
  await expect(page.getByText("B站已连接")).toBeVisible();
  await expect(page.getByText("TapTap已连接")).toBeVisible();
  await expect(page.getByRole("button", { name: "开始分析" })).toBeDisabled();
  await page.getByPlaceholder("游戏、产品或事件名称").fill("失控进化");
  await page.getByPlaceholder("https://space.bilibili.com/3546785396034301").fill("https://space.bilibili.com/3546785396034301");
  await expect(page.getByRole("button", { name: "开始分析" })).toBeEnabled();
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
});

test("Bilibili login is rendered in an interactive page subwindow", async ({ page }, testInfo) => {
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  await page.route("**/api/v1/platforms/bilibili/workspace", (route) => route.fulfill({ json: platformState("bilibili", false) }));
  await page.route("**/api/v1/platforms/bilibili/frame.jpg**", (route) => route.fulfill({ contentType: "image/png", body: png }));
  await page.route("**/api/v1/platforms/bilibili/input", (route) => route.fulfill({ json: platformState("bilibili", false) }));
  await page.goto("/");
  await page.getByTitle("打开 B站 页面子窗口").click();
  await expect(page.getByRole("dialog", { name: "bilibili 页面子窗口" })).toBeVisible();
  await expect(page.getByAltText("bilibili 交互页面")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("embedded-login.png"), fullPage: true });
});

test("report separates source blocks and remains horizontally contained", async ({ page }, testInfo) => {
  await page.goto("/reports/demo");
  await expect(page.getByRole("heading", { name: "《失控进化》舆情分析" })).toBeVisible();
  for (const heading of ["跨平台情感占比", "B站官号", "B站相关视频", "TapTap 玩家评价", "模型质量", "合规与方法说明"]) {
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
  await page.screenshot({ path: testInfo.outputPath("report.png"), fullPage: true });
});

test("report creates an anonymous read-only share link", async ({ page }) => {
  await page.route("**/api/v1/reports/demo/shares", (route) => route.fulfill({ status: 201, json: { id: "share-1", url: "https://example.test/share/opaque-token", expires_at: "2026-07-20T04:00:00Z" } }));
  await page.goto("/reports/demo");
  await page.getByRole("button", { name: "分享" }).click();
  await expect(page.getByRole("dialog", { name: "报告分享" })).toBeVisible();
  await expect(page.locator(".share-value input")).toHaveValue("https://example.test/share/opaque-token");
});
