import { expect, test } from "@playwright/test";

const baseURL = process.env.LIVE_BASE_URL;
const username = process.env.LIVE_USERNAME;
const password = process.env.LIVE_PASSWORD;

test("live private deployment serves the workbench and QR login", async ({ browser }, testInfo) => {
  test.skip(!baseURL || !username || !password, "Live deployment credentials are not configured");

  const context = await browser.newContext({
    httpCredentials: { username: username!, password: password! },
    viewport: testInfo.project.use.viewport,
  });
  const page = await context.newPage();
  try {
    const response = await page.goto(baseURL!, { waitUntil: "networkidle" });
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "舆情任务" })).toBeVisible();
    await expect(page.getByText("服务器私有工作台")).toBeVisible();

    if (process.env.LIVE_GENERATE_QR === "true") {
      await page.getByRole("button", { name: /生成二维码|刷新二维码/ }).click();
      await expect(page.getByAltText("B站登录二维码")).toBeVisible();
    }

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
    await page.screenshot({ path: testInfo.outputPath("live-workbench.png"), fullPage: true });
  } finally {
    await context.close();
  }
});
