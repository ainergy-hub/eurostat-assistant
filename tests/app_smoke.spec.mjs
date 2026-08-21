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
    page.getByRole("heading", { name: "Explore Eurostat Data." }),
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
  const sidebarFooterLayout = await page.locator(".sidebar-foot").evaluate((footer) => {
    const sidebar = footer.closest(".sidebar");
    const footerBox = footer.getBoundingClientRect();
    const sidebarBox = sidebar.getBoundingClientRect();
    return {
      bottomGap: sidebarBox.bottom - footerBox.bottom,
      height: footerBox.height,
    };
  });
  expect(sidebarFooterLayout.bottomGap).toBe(16);
  expect(sidebarFooterLayout.height).toBeLessThan(60);
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
  await expect(page.getByRole("heading", { name: "Explore Eurostat Data." })).toBeVisible();
});

test("the top info button opens accessible app information", async ({ page }) => {
  await page.goto("/");

  const infoButton = page.getByRole("button", { name: "About this app" });
  await expect(infoButton).toBeVisible();
  await infoButton.click();

  const aboutDialog = page.getByRole("dialog", { name: "About this app" });
  await expect(aboutDialog).toBeVisible();
  await expect(aboutDialog.getByText("Official Eurostat dissemination datasets")).toBeVisible();
  await expect(aboutDialog.getByText("0.3.0", { exact: true })).toBeVisible();
  await expect(aboutDialog.getByRole("heading", { name: "Tips" })).toBeVisible();
  await expect(
    aboutDialog.getByText(
      "Start a new chat for each new investigation instead of continuing in the same thread.",
    ),
  ).toBeVisible();
  await expect(
    aboutDialog.getByText(
      "If the agent fails to complete a response, select Retry to run the question again.",
    ),
  ).toBeVisible();

  await aboutDialog.getByRole("button", { name: "Close app information" }).click();
  await expect(aboutDialog).not.toBeVisible();
  await expect(infoButton).toBeFocused();
});

test("shows a subtle title loader before the parallel AI title completes", async ({ page }) => {
  let releaseTitle;
  const titleGate = new Promise((resolve) => {
    releaseTitle = resolve;
  });
  await page.route("**/api/chat/title", async (route) => {
    await titleGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        title: "German Population Trends",
        model: "openai/gpt-5.4-nano",
      }),
    });
  });
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${JSON.stringify({
        type: "result",
        data: {
          answer: "Population increased.",
          confidence: "high",
          model: "test/model",
          result: null,
          tool_calls: 0,
          tool_call_details: [],
        },
      })}\n`,
    }),
  );
  await page.goto("/");

  await page.getByRole("textbox", { name: "Investigation query" }).fill(
    "How has Germany's population changed?",
  );
  await page.getByRole("button", { name: /Ask/ }).click();

  await expect(page.locator("#current-chat-title.title-loading")).toHaveAttribute(
    "aria-label",
    "Generating chat title",
  );
  await expect(page.locator(".chat-select-copy .title-loader")).toBeVisible();
  await expect(page.locator(".chat-select-copy .title-loader > span")).toHaveCount(3);
  const confidence = page.getByLabel("Answer confidence: high");
  const retry = page.getByRole("button", { name: "Retry this question" });
  await expect(confidence).toHaveText("Confidence: High");
  await expect(retry).toBeVisible();
  const confidenceBox = await confidence.boundingBox();
  const retryBox = await retry.boundingBox();
  expect(confidenceBox).not.toBeNull();
  expect(retryBox).not.toBeNull();
  expect(confidenceBox.x).toBeLessThan(retryBox.x);
  const confidenceStyle = await confidence.evaluate((node) => ({
    backgroundColor: getComputedStyle(node).backgroundColor,
    borderStyle: getComputedStyle(node).borderStyle,
  }));
  expect(confidenceStyle.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(confidenceStyle.borderStyle).toBe("none");
  await expect(page.getByText("How has Germany's population changed?", { exact: true })).toHaveCount(1);

  releaseTitle();
  await expect(page.locator("#current-chat-title")).toHaveText("German Population Trends");
  await expect(page.locator(".chat-select-copy strong")).toHaveText("German Population Trends");
  await expect(page.locator(".title-loading")).toHaveCount(0);
});
