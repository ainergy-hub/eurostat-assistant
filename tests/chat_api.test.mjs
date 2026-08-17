import assert from "node:assert/strict";
import test from "node:test";

import { generateChatTitle } from "../static/chat_api.js";


test("requests a chat title from the independent title endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        title: "German Population Trends",
        model: "openai/gpt-5.4-nano",
      }),
    };
  };

  try {
    const response = await generateChatTitle("How has Germany's population changed?");

    assert.equal(response.title, "German Population Trends");
    assert.equal(request.url, "/api/chat/title");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), {
      message: "How has Germany's population changed?",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reports an expired title-workflow session", async () => {
  const originalFetch = globalThis.fetch;
  let unauthorizedMessage = "";
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    json: async () => ({ detail: "App is locked." }),
  });

  try {
    await assert.rejects(
      generateChatTitle("Population", {
        onUnauthorized: (message) => {
          unauthorizedMessage = message;
        },
      }),
      /App is locked/,
    );
    assert.match(unauthorizedMessage, /session expired/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
