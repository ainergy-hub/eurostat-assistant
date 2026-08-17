export const PENDING_STAGES = [
  "Inspecting dataset dimensions",
  "Fetching a bounded data slice",
  "Checking units and observation flags",
  "Preparing the answer and visualisation",
];

export function createInFlightState(chatId) {
  return {
    chatId,
    phase: "running",
    label: PENDING_STAGES[0],
    stageIndex: 0,
    hasToolActivity: false,
    purpose: "",
    toolCalls: [],
    toolCallTotal: null,
  };
}

export function hasPendingForChat(request, chatId) {
  return request?.chatId === chatId && request.phase === "running";
}

export function advancePendingStage(request) {
  if (!request || request.phase !== "running" || request.hasToolActivity) {
    return request?.label || "";
  }
  request.stageIndex = Math.min(request.stageIndex + 1, PENDING_STAGES.length - 1);
  request.label = PENDING_STAGES[request.stageIndex];
  return request.label;
}

export function setInFlightLabel(request, label) {
  if (!request || request.phase !== "running") return;
  request.hasToolActivity = true;
  request.label = label;
}

export function updateInFlightToolCall(request, detail) {
  if (!request || !detail) return [];
  const purpose = typeof detail.reason === "string" ? detail.reason.trim() : "";
  if (purpose) request.purpose = purpose;
  const existingIndex = request.toolCalls.findIndex((item) => item.id === detail.id);
  if (existingIndex >= 0) {
    request.toolCalls[existingIndex] = {
      ...request.toolCalls[existingIndex],
      ...detail,
    };
  } else {
    request.toolCalls.push(detail);
  }
  request.toolCalls.sort((left, right) => left.index - right.index);
  request.hasToolActivity = true;
  return request.toolCalls;
}

export function completeInFlightState(request, details, total) {
  if (!request) return;
  request.phase = "completed";
  if (Array.isArray(details) && details.length) {
    request.toolCalls = [...details].sort((left, right) => left.index - right.index);
  }
  request.toolCallTotal = Number.isInteger(total) ? total : request.toolCalls.length;
}

export function failInFlightState(request) {
  if (request) request.phase = "error";
}
