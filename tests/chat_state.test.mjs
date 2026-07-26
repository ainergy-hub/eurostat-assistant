import assert from "node:assert/strict";

import {
  SUMMARY_LIMIT,
  buildContextSummary,
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
        }
      : undefined,
}));

const history = recentHistory(messages);
assert.equal(history.length, 6);
assert.equal(history[0].content, "Question 4");
assert.deepEqual(Object.keys(history[0]), ["role", "content"]);

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

console.log("chat state tests passed");
