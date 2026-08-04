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
  await expect(page.getByText("Agent ready", { exact: true })).toBeVisible();
  expect(browserErrors).toEqual([]);
});
