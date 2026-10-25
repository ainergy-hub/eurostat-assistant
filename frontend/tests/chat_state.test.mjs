import assert from "node:assert/strict";

import {
  CHAT_LOG_SCHEMA_VERSION,
  CHAT_TITLE_MAX_LENGTH,
  HISTORY_MESSAGE_LIMIT,
  SUMMARY_LIMIT,
  buildChatLog,
  buildContextSummary,
  latestDataResult,
  latestUnansweredFailure,
  recentHistory,
  shortChatTitle,
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

const longAnswer = `${"a".repeat(HISTORY_MESSAGE_LIMIT - 2)}😀${"b".repeat(50)}`;
const [truncatedAnswer] = recentHistory([{ role: "assistant", content: longAnswer }]);
assert.ok(truncatedAnswer.content.length <= HISTORY_MESSAGE_LIMIT);
assert.ok(truncatedAnswer.content.endsWith("a…"));
assert.equal(
  recentHistory([{ role: "assistant", content: "a".repeat(HISTORY_MESSAGE_LIMIT) }])[0].content
    .length,
  HISTORY_MESSAGE_LIMIT,
);
assert.equal(latestDataResult(messages).dataset.code, "demo_pjan");
assert.equal(latestDataResult([{ role: "user", content: "No chart yet" }]), null);

const failedRequest = latestUnansweredFailure({
  messages: [
    { role: "assistant", content: "Earlier answer", createdAt: "2026-07-26T10:00:00.000Z" },
    { role: "user", content: "Try this", createdAt: "2026-07-26T10:01:00.000Z" },
  ],
  events: [
    { type: "request_error", message: "Unavailable", createdAt: "2026-07-26T10:01:02.000Z" },
  ],
});
assert.equal(failedRequest.message, "Unavailable");
assert.equal(failedRequest.prompt, "Try this");
assert.equal(failedRequest.priorMessages.length, 1);
assert.equal(
  latestUnansweredFailure({
    messages: [{ role: "user", content: "Newer", createdAt: "2026-07-26T10:02:00.000Z" }],
    events: [
      { type: "request_error", message: "Older", createdAt: "2026-07-26T10:01:00.000Z" },
    ],
  }),
  null,
);
assert.equal(
  latestUnansweredFailure({
    messages: [{ role: "assistant", content: "Completed" }],
    events: [{ type: "request_error", createdAt: "2026-07-26T10:01:00.000Z" }],
  }),
  null,
);

const summary = buildContextSummary(messages);
assert.match(summary, /Question 0/);
assert.match(summary, /demo_pjan/);
assert.match(summary, /geo=DE/);
assert.ok(summary.length <= SUMMARY_LIMIT);

assert.equal(buildContextSummary(messages.slice(0, 6)), "");
assert.equal(
  titleFromPrompt("Compare Germany and France population over the latest ten years please"),
  "Compare Germany and France population…",
);
assert.equal(titleFromPrompt("  Germany   annual inflation  "), "Germany annual inflation");
assert.equal(shortChatTitle("Population, employment, wages, inflation, and productivity"), "Population, employment, wages…");
assert.equal(shortChatTitle("x".repeat(80)), `${"x".repeat(39)}…`);
assert.equal(shortChatTitle(""), "Untitled investigation");
assert.ok(titleFromPrompt("Compare population and inflation across every EU member state").length <= CHAT_TITLE_MAX_LENGTH);

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
        confidence: "high",
        model: "openai/gpt-5.6-luna-pro",
        durationMs: 1250,
        toolCalls: 1,
        toolCallDetails: [
          {
            id: "call-1",
            name: "fetch_data",
            reason: "Retrieve the requested population observations.",
            status: "completed",
            result_preview: '{"geo":"DE","value":1}',
          },
        ],
        result: {
          dataset: { code: "demo_pjan" },
          rows: [{ geo: "DE", value: 1 }],
          source_tables: [
            {
              dataset: { code: "demo_pjan" },
              rows: [{ geo: "DE", value: 1 }],
            },
            {
              dataset: { code: "nama_10_pc" },
              rows: [{ geo: "DE", value: 2 }],
            },
          ],
        },
      },
    ],
    events: [
      {
        type: "request_error",
        message: "Example failure",
        model: "openai/gpt-5.6-luna-pro",
      },
    ],
  },
  { exportedAt, appVersion: "0.2.0" },
);
assert.equal(log.schemaVersion, CHAT_LOG_SCHEMA_VERSION);
assert.equal(log.exportedAt, exportedAt);
assert.equal(log.app.version, "0.2.0");
assert.equal(log.investigation.turnCount, 1);
assert.equal(log.investigation.messageCount, 2);
assert.equal(log.investigation.messages[1].model, "openai/gpt-5.6-luna-pro");
assert.equal(log.investigation.messages[1].confidence, "high");
assert.equal(log.investigation.messages[1].toolCallDetails[0].name, "fetch_data");
assert.equal(
  log.investigation.messages[1].toolCallDetails[0].reason,
  "Retrieve the requested population observations.",
);
assert.equal("result_preview" in log.investigation.messages[1].toolCallDetails[0], false);
assert.equal("rows" in log.investigation.messages[1].result, false);
assert.equal(log.investigation.messages[1].result.rowCount, 1);
assert.equal(log.investigation.messages[1].result.dataset.code, "demo_pjan");
assert.equal(log.investigation.messages[1].result.source_tables[0].rowCount, 1);
assert.equal("rows" in log.investigation.messages[1].result.source_tables[0], false);
assert.equal(log.investigation.events[0].type, "request_error");
assert.equal(log.investigation.events[0].model, "openai/gpt-5.6-luna-pro");

console.log("chat state tests passed");
