import { expect, test } from "@playwright/test";

test("the assembled application starts without browser errors", async ({ page }) => {
  const browserErrors = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      browserErrors.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    browserErrors.push(`page: ${error.message}`);
  });

  await page.route("https://cdn.jsdelivr.net/**", (route) =>
    route.fulfill({
      body: "",
      contentType: "application/javascript",
      status: 200,
    }),
  );

  const response = await page.goto("/");
  expect(response?.ok()).toBe(true);
  await page.waitForLoadState("networkidle");

  await expect(
    page.getByRole("heading", { name: "Explore Eurostat data." }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Investigation query" }),
  ).toBeVisible();
  const sidebarBox = await page
    .getByRole("complementary", { name: "Investigations" })
    .boundingBox();
  expect(sidebarBox).not.toBeNull();
  expect(sidebarBox.width).toBe(320);
  const historyTitleLayout = await page.locator(".chat-select-copy strong").evaluate((title) => ({
    whiteSpace: getComputedStyle(title).whiteSpace,
    width: title.getBoundingClientRect().width,
  }));
  expect(historyTitleLayout.whiteSpace).toBe("nowrap");
  expect(historyTitleLayout.width).toBeGreaterThan(250);
  const historyRowLayout = await page.locator(".chat-list-item").evaluate((row) => ({
    height: row.getBoundingClientRect().height,
    gap: getComputedStyle(row.parentElement).rowGap,
  }));
  expect(historyRowLayout.height).toBe(40);
  expect(historyRowLayout.gap).toBe("2px");
  expect(await page.locator(".chat-select").getAttribute("title")).toBeNull();
  await expect(page.locator(".chat-select-copy small")).toHaveCount(0);
  await expect(page.getByText("Agent ready", { exact: true })).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});

test("settings opens as a minimal full-page overlay and closes from its top bar", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "Open development settings" }).click();
  await expect(page).toHaveURL(/\/settings\/development$/);
  await expect(page.getByRole("complementary", { name: "Investigations" })).not.toBeVisible();

  const settingsOverlay = page.getByRole("dialog", { name: "Development settings" });
  await expect(settingsOverlay).toBeVisible();
  await expect(settingsOverlay.getByRole("button")).toHaveCount(1);
  await expect(settingsOverlay.getByRole("button", { name: "Close settings" })).toBeFocused();

  const overlayBox = await settingsOverlay.boundingBox();
  expect(overlayBox).not.toBeNull();
  expect(overlayBox.x).toBe(0);
  expect(overlayBox.y).toBe(0);
  expect(overlayBox.width).toBe(page.viewportSize().width);
  expect(overlayBox.height).toBe(page.viewportSize().height);

  await settingsOverlay.getByRole("button", { name: "Close settings" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Explore Eurostat data." })).toBeVisible();
});
