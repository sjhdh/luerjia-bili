import { expect, test } from "@playwright/test";

const baseURL = process.env.LIVE_BASE_URL;
const username = process.env.LIVE_USERNAME;
const password = process.env.LIVE_PASSWORD;

test("live private deployment serves the workbench and embedded login", async ({ browser }, testInfo) => {
  test.skip(!baseURL || !username || !password, "Live deployment credentials are not configured");

  const context = await browser.newContext({ viewport: testInfo.project.use.viewport });
  const page = await context.newPage();
  try {
    const response = await page.goto(baseURL!, { waitUntil: "networkidle" });
    expect(response?.status()).toBe(200);
    await page.getByLabel("账号").fill(username!);
    await page.getByLabel("密码").fill(password!);
    await page.getByRole("button", { name: "登录" }).click();
    await expect(page.getByRole("heading", { name: "分析任务" })).toBeVisible();

    if (process.env.LIVE_GENERATE_QR === "true") {
      await page.getByTitle("打开 B站 页面子窗口").click();
      await expect(page.getByRole("dialog", { name: "bilibili 页面子窗口" })).toBeVisible();
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
