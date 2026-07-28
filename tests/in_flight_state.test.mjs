import assert from "node:assert/strict";

import {
  advancePendingStage,
  completeInFlightState,
  createInFlightState,
  failInFlightState,
  hasPendingForChat,
  setInFlightLabel,
  updateInFlightToolCall,
} from "../static/in_flight_state.js";

const request = createInFlightState("population-chat");
assert.equal(hasPendingForChat(request, "population-chat"), true);
assert.equal(hasPendingForChat(request, "inflation-chat"), false);

const firstLabel = request.label;
assert.notEqual(advancePendingStage(request), firstLabel);

updateInFlightToolCall(request, {
  id: "call-2",
  index: 2,
  name: "fetch_data",
  reason: "Retrieve the requested observations.",
  status: "running",
});
updateInFlightToolCall(request, {
  id: "call-1",
  index: 1,
  name: "inspect_dimensions",
  status: "completed",
});
updateInFlightToolCall(request, {
  id: "call-2",
  index: 2,
  name: "fetch_data",
  status: "completed",
});
setInFlightLabel(request, "Fetch Data completed");

// Live state continues changing while another chat is selected and is still
// available when the running chat is rendered again.
assert.equal(hasPendingForChat(request, "inflation-chat"), false);
assert.equal(hasPendingForChat(request, "population-chat"), true);
assert.deepEqual(request.toolCalls.map((call) => call.id), ["call-1", "call-2"]);
assert.equal(request.toolCalls[1].status, "completed");
assert.equal(request.purpose, "Retrieve the requested observations.");
assert.equal(request.label, "Fetch Data completed");
assert.equal(advancePendingStage(request), "Fetch Data completed");

completeInFlightState(request, request.toolCalls, 2);
assert.equal(hasPendingForChat(request, "population-chat"), false);
assert.equal(request.phase, "completed");
assert.equal(request.toolCallTotal, 2);

const failedRequest = createInFlightState("failed-chat");
failInFlightState(failedRequest);
assert.equal(failedRequest.phase, "error");
assert.equal(hasPendingForChat(failedRequest, "failed-chat"), false);

console.log("in-flight state tests passed");
