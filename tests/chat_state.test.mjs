import assert from "node:assert/strict";

import {
  CHAT_LOG_SCHEMA_VERSION,
  SUMMARY_LIMIT,
  buildChatLog,
  buildContextSummary,
  latestDataResult,
  recentHistory,
  titleFromPrompt,
} from "../static/chat_state.js";

const messages = Array.from({ length: 10 }, (_, index) => ({
  role: index % 2 === 0 ? "user" : "assistant",
  content: index % 2 === 0 ? `Question ${index}` : `Finding ${index}`,
  result:
    index === 1
      ? {
          dataset: { code: "demo_pjan" },
          filters: { geo: ["DE"], age: ["TOTAL"] },
          rows: [{ geo: "DE", value: 1 }],
        }
      : undefined,
}));

const history = recentHistory(messages);
assert.equal(history.length, 6);
assert.equal(history[0].content, "Question 4");
assert.deepEqual(Object.keys(history[0]), ["role", "content"]);
assert.equal(latestDataResult(messages).dataset.code, "demo_pjan");
assert.equal(latestDataResult([{ role: "user", content: "No chart yet" }]), null);

const summary = buildContextSummary(messages);
assert.match(summary, /Question 0/);
assert.match(summary, /demo_pjan/);
assert.match(summary, /geo=DE/);
assert.ok(summary.length <= SUMMARY_LIMIT);

assert.equal(buildContextSummary(messages.slice(0, 6)), "");
assert.equal(
  titleFromPrompt("Compare Germany and France population over the latest ten years please"),
  "Compare Germany and France population ove…",
);

const exportedAt = "2026-07-26T12:00:00.000Z";
const log = buildChatLog(
  {
    id: "chat-123",
    title: "Population comparison",
    createdAt: "2026-07-26T11:00:00.000Z",
    updatedAt: "2026-07-26T11:01:00.000Z",
    messages: [
      { role: "user", content: "Compare population", createdAt: "2026-07-26T11:00:00.000Z" },
      {
        role: "assistant",
        content: "Population changed.",
        durationMs: 1250,
        toolCalls: 1,
        toolCallDetails: [
          {
            id: "call-1",
            name: "fetch_data",
            status: "completed",
            result_preview: '{"geo":"DE","value":1}',
          },
        ],
        result: { dataset: { code: "demo_pjan" }, rows: [{ geo: "DE", value: 1 }] },
      },
    ],
    events: [{ type: "request_error", message: "Example failure" }],
  },
  { exportedAt, appVersion: "0.2.0" },
);
assert.equal(log.schemaVersion, CHAT_LOG_SCHEMA_VERSION);
assert.equal(log.exportedAt, exportedAt);
assert.equal(log.app.version, "0.2.0");
assert.equal(log.investigation.turnCount, 1);
assert.equal(log.investigation.messageCount, 2);
assert.equal(log.investigation.messages[1].toolCallDetails[0].name, "fetch_data");
assert.equal("result_preview" in log.investigation.messages[1].toolCallDetails[0], false);
assert.equal("rows" in log.investigation.messages[1].result, false);
assert.equal(log.investigation.messages[1].result.rowCount, 1);
assert.equal(log.investigation.messages[1].result.dataset.code, "demo_pjan");
assert.equal(log.investigation.events[0].type, "request_error");

console.log("chat state tests passed");
