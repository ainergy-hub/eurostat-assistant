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
  const inactiveToolActivity = page.getByRole("button", { name: /Tool calls/ });
  await expect(inactiveToolActivity).toBeVisible();
  await expect(inactiveToolActivity).toBeDisabled();
  await expect(inactiveToolActivity).toContainText("No calls for this chat");
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
  expect(sidebarFooterLayout.height).toBeLessThan(100);
  expect(await page.locator(".chat-select").getAttribute("title")).toBeNull();
  await expect(page.locator(".chat-select-copy small")).toHaveCount(0);
  await expect(page.getByText("Agent ready", { exact: true })).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});

test("feedback remains available during a rolling backend update", async ({ page }) => {
  await page.route("**/api/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ lock_enabled: false, authenticated: true }),
    }),
  );

  await page.goto("/");

  await expect(page.getByRole("button", { name: "Send feedback" })).toBeVisible();
});

test("feedback stays hidden when Airtable is not configured", async ({ page }) => {
  await page.route("**/api/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        lock_enabled: false,
        authenticated: true,
        feedback_configured: false,
      }),
    }),
  );

  await page.goto("/");

  await expect(page.locator("#feedback-button")).toBeHidden();
});

test("tool activity stays in place while its state changes", async ({ page }) => {
  const toolCall = {
    id: "call-1",
    index: 0,
    name: "search_eurostat_datasets",
    status: "completed",
    reason: "Find the population dataset.",
    arguments: { query: "population" },
    result_preview: "Found demo_pjan.",
    duration_ms: 12,
  };
  await page.route("**/api/chat/title", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ title: "Population lookup", model: "test/model" }),
    }),
  );
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: [
        JSON.stringify({ type: "tool_call", phase: "completed", call: toolCall }),
        JSON.stringify({
          type: "result",
          data: {
            answer: "Population data found.",
            confidence: "high",
            model: "test/model",
            result: null,
            tool_calls: 1,
            tool_call_details: [toolCall],
          },
        }),
        "",
      ].join("\n"),
    }),
  );
  await page.goto("/");

  const activity = page.getByRole("button", { name: /Tool calls/ });
  const historyRow = page.locator(".chat-list-item");
  const before = {
    activity: await activity.boundingBox(),
    history: await historyRow.boundingBox(),
  };
  expect(before.activity?.height).toBe(64);
  await expect(activity).toBeDisabled();

  await page.getByRole("textbox", { name: "Investigation query" }).fill("Find population data");
  await page.getByRole("button", { name: /Ask/ }).click();

  await expect(activity).toBeEnabled();
  await expect(activity).toContainText("1 completed");
  const after = {
    activity: await activity.boundingBox(),
    history: await historyRow.boundingBox(),
  };
  expect(after.activity?.height).toBe(before.activity?.height);
  expect(after.history?.y).toBe(before.history?.y);
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

test("feedback opens, closes, validates, and sends no chat log by default", async ({ page }) => {
  let submittedPayload = null;
  await page.route("**/api/feedback", async (route) => {
    submittedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.goto("/");

  const openButton = page.getByRole("button", { name: "Send feedback" });
  await openButton.click();
  const dialog = page.getByRole("dialog", { name: "Send feedback" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("1 star", { exact: true })).toBeFocused();
  await expect(dialog.getByRole("group", { name: "How useful do you find the app?" })).toBeVisible();
  await expect(dialog.locator("#feedback-chat-log")).not.toBeChecked();
  await expect(dialog.getByText("New investigation", { exact: true })).toBeVisible();

  await dialog.getByRole("button", { name: "Send feedback" }).click();
  expect(submittedPayload).toBeNull();

  await dialog.getByLabel("Category").selectOption("Bug report");
  await dialog.getByRole("textbox", { name: /Feedback/ }).fill("The chart labels overlap.");
  await dialog.getByRole("textbox", { name: /Email/ }).fill("reader@example.eu");
  await dialog.getByLabel("2 stars", { exact: true }).check();
  await dialog.getByRole("button", { name: "Send feedback" }).click();

  await expect(dialog.getByText("Thanks. Your feedback was sent.")).toBeVisible();
  expect(submittedPayload).toEqual({
    category: "Bug report",
    feedback: "The chart labels overlap.",
    rating: 2,
    email: "reader@example.eu",
  });

  await dialog.getByRole("button", { name: "Close feedback form" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(openButton).toBeFocused();

  await openButton.click();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

test("failed feedback keeps every value and retries", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/feedback", async (route) => {
    attempts += 1;
    await route.fulfill({
      status: attempts === 1 ? 502 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        attempts === 1
          ? { detail: "Feedback could not be saved. Try again." }
          : { ok: true },
      ),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Send feedback" }).click();
  const dialog = page.getByRole("dialog", { name: "Send feedback" });
  await dialog.getByLabel("Category").selectOption("Feature request");
  await dialog.getByRole("textbox", { name: /Feedback/ }).fill("Add a CSV export.");
  await dialog.getByRole("textbox", { name: /Email/ }).fill("maintainer@example.eu");
  await dialog.getByLabel("4 stars", { exact: true }).check();
  await dialog.locator("#feedback-chat-log").check();

  await dialog.getByRole("button", { name: "Send feedback" }).click();
  await expect(dialog.getByText("Feedback could not be saved. Try again.")).toBeVisible();
  await expect(dialog.getByLabel("Category")).toHaveValue("Feature request");
  await expect(dialog.getByRole("textbox", { name: /Feedback/ })).toHaveValue("Add a CSV export.");
  await expect(dialog.getByRole("textbox", { name: /Email/ })).toHaveValue(
    "maintainer@example.eu",
  );
  await expect(dialog.getByLabel("4 stars", { exact: true })).toBeChecked();
  await expect(dialog.locator("#feedback-chat-log")).toBeChecked();

  await dialog.getByRole("button", { name: "Retry" }).click();
  await expect(dialog.getByText("Thanks. Your feedback was sent.")).toBeVisible();
  expect(attempts).toBe(2);
});

test("opted-in feedback uses the downloadable chat log", async ({ page }) => {
  await page.addInitScript(() => {
    const NativeDate = Date;
    const fixed = "2026-09-13T12:00:00.000Z";
    globalThis.Date = class extends NativeDate {
      constructor(...args) {
        super(...(args.length ? args : [fixed]));
      }

      static now() {
        return NativeDate.parse(fixed);
      }
    };
  });
  let submittedPayload = null;
  await page.route("**/api/chat/title", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ title: "Population lookup", model: "test/model" }),
    }),
  );
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${JSON.stringify({
        type: "result",
        data: {
          answer: "Population data found.",
          confidence: "high",
          model: "test/model",
          result: null,
          tool_calls: 0,
          tool_call_details: [],
        },
      })}\n`,
    }),
  );
  await page.route("**/api/feedback", async (route) => {
    submittedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, chat_log_attached: false }),
    });
  });
  await page.goto("/");
  await page.getByRole("textbox", { name: "Investigation query" }).fill("Find population data");
  await page.getByRole("button", { name: /Ask/ }).click();
  await expect(page.getByText("Population data found.")).toBeVisible();
  await expect(page.locator("#current-chat-title")).toHaveText("Population lookup");

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download log/ }).click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const downloadedLog = JSON.parse(Buffer.concat(chunks).toString("utf8"));

  await page.getByRole("button", { name: "Send feedback" }).click();
  const dialog = page.getByRole("dialog", { name: "Send feedback" });
  await dialog.getByLabel("Category").selectOption("Response quality");
  await dialog.getByRole("textbox", { name: /Feedback/ }).fill("The answer needs more context.");
  await dialog.getByLabel("3 stars", { exact: true }).check();
  await dialog.locator("#feedback-chat-log").check();
  await expect(dialog.getByText("Population lookup", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Send feedback" }).click();

  await expect(
    dialog.getByText("Your feedback was sent, but the chat log could not be attached."),
  ).toBeVisible();
  expect(submittedPayload.chat_log).toEqual(downloadedLog);
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

test("csv export neutralises formula-like cells", async ({ page }) => {
  await page.route("**/api/chat/title", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ title: "Regions", model: "test/model" }),
    }),
  );
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: [
        JSON.stringify({
          type: "result",
          data: {
            answer: "Two regions found.",
            confidence: "high",
            model: "test/model",
            result: {
              dataset: { code: "demo_r", title: "Regions", source_url: "https://ec.europa.eu/x" },
              filters: {},
              columns: [
                { key: "geo_label", label: "Geography" },
                { key: "value", label: "Value" },
              ],
              rows: [
                { geo_label: '=HYPERLINK("http://evil/","x")', value: -1.5 },
                { geo_label: "Germany", value: 2 },
              ],
              chart: { type: "none" },
            },
            tool_calls: 0,
            tool_call_details: [],
          },
        }),
        "",
      ].join("\n"),
    }),
  );
  await page.goto("/");
  await page.getByRole("textbox", { name: "Investigation query" }).fill("Regions");
  await page.getByRole("button", { name: /Ask/ }).click();
  await page.locator("summary", { hasText: "2 rows" }).click();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Download CSV/ }).click(),
  ]);
  const stream = await download.createReadStream();
  let csv = "";
  for await (const chunk of stream) csv += chunk;

  expect(download.suggestedFilename()).toBe("demo_r-observations.csv");
  expect(csv.replace(/^﻿/, "").split("\n")).toEqual([
    `"Geography","Value"`,
    `"'=HYPERLINK(""http://evil/"",""x"")","-1.5"`,
    `"Germany","2"`,
  ]);
});
