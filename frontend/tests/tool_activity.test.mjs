import assert from "node:assert/strict";

import {
  toolActivityStatusText,
  toolActivityTone,
  toolCallSummaryText,
} from "../static/tool_activity.js";

const recovered = [
  { id: "call-1", status: "completed" },
  { id: "call-2", status: "error" },
  { id: "call-3", status: "completed" },
];

// A failed call only turns the panel red when the request itself failed.
assert.equal(toolActivityTone("running"), "running");
assert.equal(toolActivityTone("completed"), "success");
assert.equal(toolActivityTone("error"), "error");

assert.equal(
  toolActivityStatusText(recovered, "completed", 3),
  "3 calls · 1 failed · Select for details",
);
assert.equal(
  toolActivityStatusText(recovered.filter((call) => call.status === "completed"), "completed"),
  "2 completed · Select for details",
);
assert.equal(
  toolActivityStatusText(recovered, "error"),
  "Agent request failed · Select for details",
);

// While the agent is still working, failures do not change the status text.
assert.equal(toolActivityStatusText([], "running"), "Starting agent");
assert.equal(
  toolActivityStatusText([...recovered, { id: "call-4", status: "running" }], "running"),
  "1 running · Select for details",
);
assert.equal(
  toolActivityStatusText(recovered, "running"),
  "Agent is preparing the answer · Select for details",
);

assert.equal(toolCallSummaryText([], "completed"), "No tool calls yet.");
assert.equal(
  toolCallSummaryText(recovered, "completed"),
  "2 of 3 complete · 1 failed (answer still generated)",
);
assert.equal(toolCallSummaryText(recovered, "error"), "2 of 3 complete · 1 failed");
assert.equal(
  toolCallSummaryText([...recovered, { id: "call-4", status: "running" }], "running"),
  "2 of 4 complete · 1 running · 1 failed",
);
