// Shared rules for the tool activity panel and its details dialog. A failed
// tool call only turns the panel red when the whole agent request failed; if
// the agent still produced an answer, the failure is reported as a note.

const DETAILS_HINT = "Select for details";

function countByStatus(calls, status) {
  return calls.filter((call) => call.status === status).length;
}

export function toolActivityTone(phase) {
  if (phase === "error") return "error";
  if (phase === "completed") return "success";
  return "running";
}

export function toolActivityStatusText(calls = [], phase, total) {
  if (phase === "error") return `Agent request failed · ${DETAILS_HINT}`;

  const failed = countByStatus(calls, "error");
  if (phase === "completed") {
    const callTotal = Number.isInteger(total) ? total : calls.length;
    return failed
      ? `${callTotal} calls · ${failed} failed · ${DETAILS_HINT}`
      : `${calls.length} completed · ${DETAILS_HINT}`;
  }

  const running = countByStatus(calls, "running");
  if (running) return `${running} running · ${DETAILS_HINT}`;
  if (calls.length) return `Agent is preparing the answer · ${DETAILS_HINT}`;
  return "Starting agent";
}

export function toolCallSummaryText(calls = [], phase) {
  if (!calls.length) return "No tool calls yet.";
  const completed = countByStatus(calls, "completed");
  const failed = countByStatus(calls, "error");
  const running = countByStatus(calls, "running");
  const summary = [`${completed} of ${calls.length} complete`];
  if (running) summary.push(`${running} running`);
  if (failed) {
    summary.push(
      phase === "completed" ? `${failed} failed (answer still generated)` : `${failed} failed`,
    );
  }
  return summary.join(" · ");
}
