import { defineConfig } from "@playwright/test";

const port = 8765;
const channel = process.env.PLAYWRIGHT_CHANNEL;

export default defineConfig({
  testDir: "./tests",
  testMatch: "app_smoke.spec.mjs",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    ...(channel ? { channel } : {}),
  },
  webServer: {
    command: [
      "env -u APP_PASSWORD",
      "OPENROUTER_API_KEY=smoke-test-key",
      "OPENROUTER_MODEL_OPTIONS=test/default-model",
      "AIRTABLE_ACCESS_TOKEN=test-airtable-token",
      "AIRTABLE_BASE_ID=appTestBase",
      "AIRTABLE_TABLE_ID=tblTestTable",
      "uv run uvicorn app.main:app",
      `--host 127.0.0.1 --port ${port}`,
    ].join(" "),
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
