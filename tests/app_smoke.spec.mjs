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
