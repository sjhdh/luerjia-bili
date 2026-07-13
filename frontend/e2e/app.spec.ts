import { expect, test } from "@playwright/test";
import { demoReport } from "./fixtures";

const platformState = (platform: "bilibili" | "taptap", authenticated = true) => ({ platform, running: true, authenticated, login_method: "window", qr_ready: false, qr_expires_at: null, message: authenticated ? "登录态可用" : "尚未登录", workspace_ready: true, current_url: platform === "bilibili" ? "https://passport.bilibili.com/login" : "https://www.taptap.cn", page_title: `${platform} 登录`, risk_detected: false });
const directProxy = { mode: "direct", protocol: "https", country_code: "CN", pool_size: 5, manual_proxy: "", active_proxy: null, active_source: "direct", exit_ip: null, latency_ms: null, last_checked_at: null, last_error: null, pool_api: "https://proxy.scdn.io/api/get_proxy.php" };
const autoProxy = { ...directProxy, mode: "auto", active_proxy: "http://192.0.2.20:8080", active_source: "pool", exit_ip: "203.0.113.20", latency_ms: 85, last_checked_at: "2026-07-13T12:00:00+00:00" };

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({ json: { authenticated: true, username: "operator" } }));
  await page.route("**/api/v1/platforms/bilibili/session", (route) => route.fulfill({ json: platformState("bilibili") }));
  await page.route("**/api/v1/platforms/taptap/session", (route) => route.fulfill({ json: platformState("taptap") }));
  await page.route("**/api/v1/proxy", (route) => route.fulfill({ json: route.request().method() === "PUT" ? autoProxy : directProxy }));
  await page.route("**/api/v1/proxy/rotate", (route) => route.fulfill({ json: autoProxy }));
  await page.route("**/api/v1/proxy/test", (route) => route.fulfill({ json: { proxy: autoProxy.active_proxy, reachable: true, latency_ms: 85, exit_ip: autoProxy.exit_ip, message: "代理出口可用", checked_at: autoProxy.last_checked_at } }));
  await page.route("**/api/v1/jobs", async (route) => {
    await route.fulfill({ json: [{ id: "demo", keyword: "失控进化", status: "completed", stage: "报告已完成", progress: 100, message: "报告已生成", analysis_mode: "local", time_range: "90d", depth: "standard", official_bilibili_url: "https://space.bilibili.com/3546785396034301", official_mid: "3546785396034301", include_discovery: true, include_taptap: true, taptap_app_id: "733908", taptap_app_url: "https://www.taptap.cn/app/733908", taptap_candidates: [], collection_metrics: {}, warnings: [], partial: false, cancel_requested: false, created_at: "2026-07-13T04:00:00Z", updated_at: "2026-07-13T04:30:00Z", finished_at: "2026-07-13T04:30:00Z" }] });
  });
  await page.route("**/api/v1/reports/demo", (route) => route.fulfill({ json: demoReport }));
});

test("unauthenticated operators see the application login page", async ({ page }, testInfo) => {
  await page.unroute("**/api/v1/auth/session");
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({ json: { authenticated: false, username: null } }));
  await page.route("**/api/v1/auth/login", (route) => route.fulfill({ json: { authenticated: true, username: "operator" } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "登录工作台" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("login.png"), fullPage: true });
  await page.getByLabel("密码").fill("test-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "舆情任务台" })).toBeVisible();
});

test("workbench exposes official, discovery, and TapTap inputs", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "舆情任务台" })).toBeVisible();
  await expect(page.getByText("B站已连接")).toBeVisible();
  await expect(page.getByText("TapTap已连接")).toBeVisible();
  await expect(page.getByRole("button", { name: "开始采集与分析" })).toBeDisabled();
  await page.getByPlaceholder("输入游戏、产品或事件").fill("失控进化");
  await page.getByPlaceholder("https://space.bilibili.com/3546785396034301").fill("https://space.bilibili.com/3546785396034301");
  await expect(page.getByRole("button", { name: "开始采集与分析" })).toBeEnabled();
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("workbench.png"), fullPage: true });
});

test("network route settings switch to the automatic proxy pool", async ({ page }, testInfo) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "网络路由" })).toBeVisible();
  await expect(page.getByText("服务器直连", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "自动代理池" }).click();
  await page.getByLabel("候选数量").fill("3");
  await page.getByRole("button", { name: "保存并切换" }).click();
  await expect(page.getByText("自动代理池已生效", { exact: false })).toBeVisible();
  await expect(page.getByText("203.0.113.20", { exact: true })).toBeVisible();
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("network-route.png"), fullPage: true });
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

test("partial report uses a real cover and accurate collection status", async ({ page }) => {
  const cover = "https://i0.hdslb.com/bfs/archive/real-video-cover.jpg";
  await page.unroute("**/api/v1/reports/demo");
  await page.route("**/api/v1/reports/demo", (route) => route.fulfill({
    json: {
      ...demoReport,
      partial: true,
      hero: { ...demoReport.hero, cover_url: "//www.bilibili.com/favicon.ico" },
      metrics: { ...demoReport.metrics, discovery_video_count: 21 },
      videos: demoReport.videos.map((video, index) => ({ ...video, cover_url: index === 0 ? cover : null })),
      data_quality: {
        valid: false,
        sample_count: 1646,
        requested_sources: { bilibili_official: true, bilibili_discovery: true, taptap: false },
        available_sources: { bilibili_official: true, bilibili_discovery: true, taptap: false },
        empty_sources: [],
        collection: {}
      }
    }
  }));

  await page.goto("/reports/demo");
  await expect(page.getByText("部分采集未完整", { exact: true })).toBeVisible();
  await expect(page.getByText("相关视频 10 个", { exact: true })).toBeVisible();
  await expect(page.getByAltText("失控进化")).toHaveAttribute("src", cover);
});

test("report remains contained when resized from desktop to mobile", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/reports/demo");
  await expect(page.getByRole("heading", { name: "跨平台情感占比" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));

  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
});

test("report creates an anonymous read-only share link", async ({ page }) => {
  await page.route("**/api/v1/reports/demo/shares", (route) => route.fulfill({ status: 201, json: { id: "share-1", url: "https://example.test/share/opaque-token", expires_at: "2026-07-20T04:00:00Z" } }));
  await page.goto("/reports/demo");
  await page.getByRole("button", { name: "分享" }).click();
  await expect(page.getByRole("dialog", { name: "报告分享" })).toBeVisible();
  await expect(page.locator(".share-value input")).toHaveValue("https://example.test/share/opaque-token");
});
