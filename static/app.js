import {
  buildChatLog,
  buildContextSummary,
  latestDataResult,
  recentHistory,
  titleFromPrompt,
} from "./chat_state.js";
import {
  ChatHistoryStore,
  requestPersistentStorage,
} from "./chat_store.js";
import {
  advancePendingStage,
  completeInFlightState,
  createInFlightState,
  failInFlightState,
  hasPendingForChat,
  setInFlightLabel,
  updateInFlightToolCall,
} from "./in_flight_state.js";
import { createChartSection, finalizeChartViews } from "./chart.js?v=20260731-1";
import { eurostatDatasetUrl, renderMarkdown } from "./markdown.js";

const PAGE_SIZE = 12;
const APP_VERSION = "0.3.0";

const appLayout = document.querySelector("#app-layout");
const appLock = document.querySelector("#app-lock");
const appLockForm = document.querySelector("#app-lock-form");
const appLockPassword = document.querySelector("#app-lock-password");
const appLockError = document.querySelector("#app-lock-error");
const appUnlockButton = document.querySelector("#app-unlock-button");
const lockAppButton = document.querySelector("#lock-app");
const chat = document.querySelector("#chat");
const composer = document.querySelector("#composer");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send");
const statusBadge = document.querySelector("#status");
const statusWrap = document.querySelector(".status-wrap");
const pendingTemplate = document.querySelector("#pending-template");
const hero = document.querySelector("#hero");
const chatList = document.querySelector("#chat-list");
const chatCount = document.querySelector("#chat-count");
const newChatButton = document.querySelector("#new-chat");
const currentChatTitle = document.querySelector("#current-chat-title");
const contextStatus = document.querySelector("#context-status");
const sidebar = document.querySelector("#sidebar");
const sidebarBackdrop = document.querySelector("#sidebar-backdrop");
const menuButton = document.querySelector("#menu-button");
const sidebarClose = document.querySelector("#sidebar-close");
const toolActivity = document.querySelector("#tool-activity");
const toolActivityCount = document.querySelector("#tool-activity-count");
const toolActivityStatus = document.querySelector("#tool-activity-status");
const toolCallDialog = document.querySelector("#tool-call-dialog");
const toolCallDialogClose = document.querySelector("#tool-call-dialog-close");
const toolCallDialogSummary = document.querySelector("#tool-call-dialog-summary");
const toolCallDetails = document.querySelector("#tool-call-details");
const apiQueryPanel = document.querySelector("#api-query-panel");
const apiQueryPanelTitle = document.querySelector("#api-query-panel-title");
const apiQueryPanelClose = document.querySelector("#api-query-panel-close");
const apiQueryPanelBody = document.querySelector("#api-query-panel-body");
const downloadChatLogButton = document.querySelector("#download-chat-log");
const themeToggleButton = document.querySelector("#theme-toggle");
const notification = document.querySelector("#notification");
const notificationMessage = document.querySelector("#notification-message");
const notificationDismiss = document.querySelector("#notification-dismiss");
const themeApi = globalThis.EurostatTheme;

let state = { chats: [], activeChatId: null };
let historyStore = null;
let historyNotice = "";
let inFlightChatId = null;
let inFlightState = null;
let currentToolCalls = [];
let lockEnabled = false;
let notificationTimer = null;

function syncThemeToggle() {
  const isDark = document.documentElement.dataset.theme === themeApi.DARK;
  const nextTheme = isDark ? "light" : "dark";
  themeToggleButton.querySelector(".theme-toggle-label").textContent = `${nextTheme[0].toUpperCase()}${nextTheme.slice(1)} mode`;
  themeToggleButton.dataset.nextTheme = nextTheme;
  themeToggleButton.setAttribute("aria-label", `Use ${nextTheme} mode`);
  themeToggleButton.title = `Use ${nextTheme} mode`;
}

function showAppLock(message = "") {
  appLayout.inert = true;
  appLayout.hidden = true;
  appLock.hidden = false;
  document.body.classList.remove("app-unlocked");
  appLockError.textContent = message;
  appLockError.hidden = !message;
  appLockPassword.value = "";
  window.setTimeout(() => appLockPassword.focus(), 0);
}

function showApp() {
  appLayout.inert = false;
  appLayout.hidden = false;
  appLock.hidden = true;
  document.body.classList.add("app-unlocked");
  lockAppButton.hidden = !lockEnabled;
  promptInput.focus();
}

async function checkAuth() {
  try {
    const response = await fetch("/api/auth/status", { cache: "no-store" });
    if (!response.ok) throw new Error("The app could not check the lock status.");
    const data = await response.json();
    lockEnabled = Boolean(data.lock_enabled);
    if (!data.authenticated) {
      showAppLock();
      return false;
    }
    showApp();
    return true;
  } catch {
    showAppLock("The backend is unavailable. Start the app and try again.");
    return false;
  }
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function readableToolName(name) {
  return String(name || "Unknown tool")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function toolDuration(detail) {
  if (!Number.isInteger(detail?.duration_ms)) return "In progress";
  if (detail.duration_ms < 1000) return `${detail.duration_ms} ms`;
  return `${(detail.duration_ms / 1000).toFixed(2)} s`;
}

function renderToolCallDetails(details = currentToolCalls) {
  toolCallDetails.replaceChildren();
  const completed = details.filter((detail) => detail.status === "completed").length;
  const failed = details.filter((detail) => detail.status === "error").length;
  const running = details.filter((detail) => detail.status === "running").length;
  const summary = [`${completed} of ${details.length} complete`];
  if (running) summary.push(`${running} running`);
  if (failed) summary.push(`${failed} failed`);
  toolCallDialogSummary.textContent = details.length ? summary.join(" · ") : "No tool calls yet.";

  for (const detail of details) {
    const item = element("li", "tool-call-detail");
    const heading = element("div", "tool-call-detail-heading");
    heading.appendChild(
      element("strong", "", `${detail.index}. ${readableToolName(detail.name)}`),
    );
    heading.appendChild(
      element("span", `tool-call-state ${detail.status}`, detail.status),
    );
    item.appendChild(heading);

    const trace = element("div", "tool-call-trace");
    trace.append(
      element("span", "tool-call-trace-label", "Purpose"),
      element(
        "p",
        "tool-call-reason",
        detail.reason || "Support the answer with verified Eurostat data.",
      ),
    );
    item.appendChild(trace);

    const meta = element("div", "tool-call-meta");
    meta.appendChild(element("span", "", toolDuration(detail)));
    item.appendChild(meta);

    const technical = element("details", "tool-call-technical");
    technical.appendChild(element("summary", "", "Technical details"));
    const technicalBody = element("div", "tool-call-technical-body");
    technicalBody.appendChild(element("span", "tool-call-id", `ID ${detail.id}`));

    const argumentsBlock = element("section");
    argumentsBlock.appendChild(element("h3", "", "Arguments"));
    const argumentsCode = element("pre");
    argumentsCode.textContent = JSON.stringify(detail.arguments || {}, null, 2);
    argumentsBlock.appendChild(argumentsCode);
    technicalBody.appendChild(argumentsBlock);

    if (detail.result_preview) {
      const resultBlock = element("section");
      resultBlock.appendChild(element("h3", "", "Result preview"));
      resultBlock.appendChild(element("p", "tool-call-result", detail.result_preview));
      technicalBody.appendChild(resultBlock);
    }
    technical.appendChild(technicalBody);
    item.appendChild(technical);
    toolCallDetails.appendChild(item);
  }
}

function updateToolActivity(detail) {
  const calls = updateInFlightToolCall(inFlightState, detail);
  if (state.activeChatId !== inFlightChatId) return;
  currentToolCalls = calls;
  const running = currentToolCalls.filter((item) => item.status === "running").length;
  const failed = currentToolCalls.filter((item) => item.status === "error").length;
  toolActivity.hidden = false;
  toolActivityCount.textContent = String(currentToolCalls.length);
  toolActivity.className = `tool-activity${running ? " running" : failed ? " error" : ""}`;
  toolActivityStatus.textContent = running
    ? `${running} running · Select for details`
    : failed
      ? `${failed} failed · Select for details`
      : `${currentToolCalls.length} completed · Select for details`;
  renderToolCallDetails();
}

function startToolActivity() {
  currentToolCalls = [];
  if (inFlightState) inFlightState.toolCalls = currentToolCalls;
  if (state.activeChatId !== inFlightChatId) return;
  toolActivity.hidden = false;
  toolActivity.className = "tool-activity running";
  toolActivityCount.textContent = "0";
  toolActivityStatus.textContent = "Starting agent";
  renderToolCallDetails();
}

function renderFinishedToolActivity(details, total) {
  currentToolCalls = Array.isArray(details) ? details : [];
  toolActivity.hidden = false;
  toolActivity.className = "tool-activity";
  toolActivityCount.textContent = String(
    Number.isInteger(total) ? total : currentToolCalls.length,
  );
  const failed = currentToolCalls.filter((item) => item.status === "error").length;
  if (failed) toolActivity.classList.add("error");
  toolActivityStatus.textContent = failed
    ? `${failed} failed · Select for details`
    : `${currentToolCalls.length} completed · Select for details`;
  renderToolCallDetails();
}

function finishToolActivity(details, total) {
  completeInFlightState(inFlightState, details, total);
  if (state.activeChatId !== inFlightChatId) return;
  renderFinishedToolActivity(inFlightState?.toolCalls, total);
}

function failToolActivity() {
  failInFlightState(inFlightState);
  if (state.activeChatId !== inFlightChatId) return;
  toolActivity.hidden = false;
  toolActivity.className = "tool-activity error";
  toolActivityStatus.textContent = "Agent request failed · Select for details";
  renderToolCallDetails();
}

function syncToolActivity(record) {
  if (record.id === inFlightChatId && inFlightState) {
    currentToolCalls = inFlightState.toolCalls;
    if (inFlightState.phase === "error") {
      toolActivity.hidden = false;
      toolActivity.className = "tool-activity error";
      toolActivityCount.textContent = String(currentToolCalls.length);
      toolActivityStatus.textContent = "Agent request failed · Select for details";
      renderToolCallDetails();
      return;
    }
    if (inFlightState.phase === "completed") {
      toolActivity.hidden = false;
      toolActivity.className = "tool-activity";
      toolActivityCount.textContent = String(
        inFlightState.toolCallTotal ?? currentToolCalls.length,
      );
      const failed = currentToolCalls.filter((item) => item.status === "error").length;
      if (failed) toolActivity.classList.add("error");
      toolActivityStatus.textContent = failed
        ? `${failed} failed · Select for details`
        : `${currentToolCalls.length} completed · Select for details`;
      renderToolCallDetails();
      return;
    }

    const running = currentToolCalls.filter((item) => item.status === "running").length;
    const failed = currentToolCalls.filter((item) => item.status === "error").length;
    toolActivity.hidden = false;
    toolActivity.className = `tool-activity running${failed ? " error" : ""}`;
    toolActivityCount.textContent = String(currentToolCalls.length);
    toolActivityStatus.textContent = running
      ? `${running} running · Select for details`
      : currentToolCalls.length
        ? "Agent is preparing the answer · Select for details"
        : "Starting agent";
    renderToolCallDetails();
    return;
  }

  const latestWithDetails = [...record.messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.toolCallDetails?.length);
  if (!latestWithDetails) {
    currentToolCalls = [];
    toolActivity.hidden = true;
    renderToolCallDetails();
    return;
  }
  renderFinishedToolActivity(
    latestWithDetails.toolCallDetails,
    latestWithDetails.toolCalls,
  );
}

function openToolCallDialog(details = currentToolCalls) {
  renderToolCallDetails(details);
  toolCallDialog.showModal();
}

async function streamChat(payload, onEvent) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      showAppLock("Your app session expired. Enter the password again.");
    }
    throw new Error(data.detail || "The agent request failed.");
  }
  if (!response.body) throw new Error("The browser could not read the live agent response.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      onEvent(event);
      if (event.type === "error") throw new Error(event.message || "The agent request failed.");
      if (event.type === "result") result = event.data;
    }
    if (done) break;
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    onEvent(event);
    if (event.type === "error") throw new Error(event.message || "The agent request failed.");
    if (event.type === "result") result = event.data;
  }
  if (!result) throw new Error("The agent stream ended before returning an answer.");
  return result;
}

function createId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function newChatRecord() {
  const now = new Date().toISOString();
  return {
    id: createId(),
    title: "New investigation",
    createdAt: now,
    updatedAt: now,
    messageCount: 0,
    turnCount: 0,
    eventCount: 0,
    messages: [],
    events: [],
    loaded: true,
  };
}

function applyMetadata(record, metadata) {
  if (!record || !metadata) return;
  record.title = metadata.title;
  record.createdAt = metadata.createdAt;
  record.updatedAt = metadata.updatedAt;
  record.messageCount = metadata.messageCount;
  record.turnCount = metadata.turnCount;
  record.eventCount = metadata.eventCount;
}

function unloadedRecord(record) {
  return {
    ...record,
    messages: [],
    events: [],
    loaded: false,
  };
}

async function initializeHistory() {
  const fallbackChat = newChatRecord();
  try {
    historyStore = new ChatHistoryStore();
    const initialState = await historyStore.initialize(fallbackChat);
    state = {
      chats: initialState.chats,
      activeChatId: initialState.activeChatId,
    };
    if (initialState.migratedCount) {
      const count = initialState.migratedCount;
      historyNotice = `Moved ${count} saved investigation${count === 1 ? "" : "s"} into scalable device storage.`;
    }
    void requestPersistentStorage();
  } catch {
    historyStore = null;
    state = { chats: [fallbackChat], activeChatId: fallbackChat.id };
    historyNotice =
      "Device history is unavailable in this browser. New investigations will last only until this page is closed.";
  }
}

async function persistMessage(record, message) {
  if (!historyStore) return false;
  try {
    const metadata = await historyStore.appendMessage(record.id, message, {
      title: record.title,
      updatedAt: record.updatedAt,
    });
    applyMetadata(record, metadata);
    return true;
  } catch {
    showNotification("This browser could not save the latest message to device history.");
    return false;
  }
}

async function persistEvent(record, event) {
  if (!historyStore) return false;
  try {
    const metadata = await historyStore.appendEvent(record.id, event, {
      updatedAt: record.updatedAt,
    });
    applyMetadata(record, metadata);
    return true;
  } catch {
    showNotification("This browser could not save the latest diagnostic event.");
    return false;
  }
}

function activeChat() {
  return state.chats.find((item) => item.id === state.activeChatId);
}

function formatChatDate(value) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function openSidebar() {
  document.body.classList.add("sidebar-open");
}

function closeSidebar() {
  document.body.classList.remove("sidebar-open");
}

function hideNotification() {
  window.clearTimeout(notificationTimer);
  notificationTimer = null;
  notification.hidden = true;
}

function showNotification(message) {
  window.clearTimeout(notificationTimer);
  notificationMessage.textContent = message;
  notification.hidden = false;
  notificationTimer = window.setTimeout(hideNotification, 6000);
}

function renderChatList() {
  chatList.replaceChildren();
  const sorted = [...state.chats].sort(
    (left, right) => new Date(right.updatedAt) - new Date(left.updatedAt),
  );
  chatCount.textContent = String(sorted.length);

  for (const record of sorted) {
    const row = element("div", `chat-list-item${record.id === state.activeChatId ? " active" : ""}`);
    const select = element("button", "chat-select");
    select.type = "button";
    select.setAttribute("aria-current", record.id === state.activeChatId ? "page" : "false");
    const text = element("span", "chat-select-copy");
    const turnCount = Number.isInteger(record.turnCount)
      ? record.turnCount
      : record.messages.filter((message) => message.role === "user").length;
    text.append(
      element("strong", "", record.title),
      element(
        "small",
        "",
        `${turnCount} turn${turnCount === 1 ? "" : "s"} · ${formatChatDate(record.updatedAt)}`,
      ),
    );
    select.appendChild(text);
    select.addEventListener("click", () => {
      void selectChat(record.id);
    });

    const remove = element("button", "chat-delete", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Delete ${record.title}`);
    remove.addEventListener("click", () => {
      void deleteChat(record.id);
    });
    row.append(select, remove);
    chatList.appendChild(row);
  }
}

async function selectChat(id) {
  const record = state.chats.find((item) => item.id === id);
  const previous = activeChat();
  if (!record) return;
  if (id === state.activeChatId) {
    closeSidebar();
    return;
  }

  try {
    const loaded = record.loaded || !historyStore
      ? record
      : await historyStore.loadChat(id);
    if (!loaded) throw new Error("The saved investigation could not be found.");
    if (historyStore) await historyStore.setActiveChat(id);
    const index = state.chats.findIndex((item) => item.id === id);
    state.chats[index] = loaded;
    if (historyStore && previous && previous.id !== inFlightChatId) {
      const previousIndex = state.chats.findIndex((item) => item.id === previous.id);
      if (previousIndex >= 0) state.chats[previousIndex] = unloadedRecord(previous);
    }
    state.activeChatId = id;
    renderWorkspace();
    closeSidebar();
  } catch {
    showNotification("This browser could not open that saved investigation.");
  }
}

async function createChat() {
  const current = activeChat();
  if (current && (current.messageCount ?? current.messages.length) === 0) {
    promptInput.focus();
    closeSidebar();
    return;
  }

  const record = newChatRecord();
  try {
    if (historyStore) await historyStore.createChat(record, true);
  } catch {
    showNotification(
      "This browser could not add the investigation to device history. It will remain available until the page is closed.",
    );
  }
  if (historyStore && current && current.id !== inFlightChatId) {
    const currentIndex = state.chats.findIndex((item) => item.id === current.id);
    if (currentIndex >= 0) state.chats[currentIndex] = unloadedRecord(current);
  }
  state.chats.push(record);
  state.activeChatId = record.id;
  renderWorkspace();
  closeSidebar();
  promptInput.focus();
}

async function deleteChat(id) {
  if (id === inFlightChatId) {
    window.alert("Wait for this investigation to finish before deleting it.");
    return;
  }
  const record = state.chats.find((item) => item.id === id);
  if (!record || !window.confirm(`Delete “${record.title}” from this device?`)) return;

  try {
    if (historyStore) await historyStore.deleteChat(id);
  } catch {
    showNotification("This browser could not delete that investigation.");
    return;
  }

  state.chats = state.chats.filter((item) => item.id !== id);
  if (!state.chats.length) {
    const replacement = newChatRecord();
    try {
      if (historyStore) await historyStore.createChat(replacement, true);
    } catch {
      showNotification(
        "Device history could not save the replacement investigation.",
      );
    }
    state.chats.push(replacement);
    state.activeChatId = replacement.id;
    renderWorkspace();
    return;
  }

  if (state.activeChatId !== id) {
    renderChatList();
    return;
  }

  const next = state.chats[0];
  try {
    const loaded = next.loaded || !historyStore
      ? next
      : await historyStore.loadChat(next.id);
    if (!loaded) throw new Error("The next investigation could not be found.");
    if (historyStore) await historyStore.setActiveChat(loaded.id);
    state.chats[0] = loaded;
    state.activeChatId = loaded.id;
    renderWorkspace();
  } catch {
    showNotification("This browser could not open the next saved investigation.");
  }
}

function filenamePart(value) {
  const cleaned = String(value || "investigation")
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLocaleLowerCase();
  return (cleaned || "investigation").slice(0, 60);
}

function downloadCurrentChatLog() {
  const record = activeChat();
  if (!record?.messages.length) return;

  const exportedAt = new Date().toISOString();
  const log = buildChatLog(record, { exportedAt, appVersion: APP_VERSION });
  const blob = new Blob([`${JSON.stringify(log, null, 2)}\n`], {
    type: "application/json;charset=utf-8",
  });
  const link = document.createElement("a");
  const date = exportedAt.slice(0, 10);
  link.href = URL.createObjectURL(blob);
  link.download = `eurostat-lens-${filenamePart(record.title)}-${date}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 0);
}

function addQuestion(content) {
  const article = element("article", "question", content);
  chat.appendChild(article);
  return article;
}

function addPending(labelText) {
  const pending = pendingTemplate.content.firstElementChild.cloneNode(true);
  chat.appendChild(pending);
  const label = pending.querySelector(".progress-label");
  label.textContent = labelText || "Finding candidate datasets";
  pending.scrollIntoView({ behavior: "smooth", block: "center" });
  return pending;
}

function syncPendingLabel() {
  if (!hasPendingForChat(inFlightState, state.activeChatId)) return;
  const pending = chat.querySelector(".pending-response");
  if (!pending) return;
  const label = pending.querySelector(".progress-label");
  if (label) label.textContent = inFlightState.label;
  const purpose = pending.querySelector(".progress-purpose");
  const purposeText = pending.querySelector(".progress-purpose-text");
  const currentPurpose =
    typeof inFlightState.purpose === "string" ? inFlightState.purpose.trim() : "";
  if (purpose && purposeText) {
    purposeText.textContent = currentPurpose;
    purpose.hidden = !currentPurpose;
  }
}

function addError(message) {
  const response = element("article", "response error-card");
  response.appendChild(element("div", "response-kicker", "Could not complete the request"));
  const answer = element("div", "answer");
  answer.appendChild(
    element(
      "p",
      "",
      message || "The Eurostat agent did not return a result. Check the app configuration and try again.",
    ),
  );
  response.appendChild(answer);
  chat.appendChild(response);
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
  }
  return String(value);
}

function compareValues(a, b) {
  const left = typeof a === "number" ? a : String(a ?? "").toLocaleLowerCase();
  const right = typeof b === "number" ? b : String(b ?? "").toLocaleLowerCase();
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function createTableSection(result, label = "Data") {
  const section = element("details", "result-section result-details");
  const summary = element("summary", "result-summary");
  summary.append(
    element("span", "", label),
    element(
      "span",
      "result-summary-meta",
      `${result.rows.length} row${result.rows.length === 1 ? "" : "s"}`,
    ),
  );
  section.appendChild(summary);

  const tools = element("div", "table-tools");
  const search = element("input", "table-search");
  search.type = "search";
  search.placeholder = "Filter returned observations";
  search.setAttribute("aria-label", "Filter table rows");
  const download = element("button", "secondary-button", "Download CSV ↓");
  download.type = "button";
  tools.append(search, download);
  section.appendChild(tools);

  const tableScroll = element("div", "table-scroll");
  const table = element("table");
  const thead = element("thead");
  const headerRow = element("tr");
  const tbody = element("tbody");
  const columns = result.columns?.length
    ? result.columns
    : Object.keys(result.rows[0] || {}).map((key) => ({ key, label: key }));
  let sortKey = columns.find((column) => column.key.includes("time"))?.key || columns[0]?.key;
  let sortDirection = "asc";
  let page = 0;
  let query = "";

  for (const column of columns) {
    const th = element("th");
    if (column.key === "value") th.classList.add("numeric");
    const button = element("button", "", column.label);
    button.type = "button";
    button.addEventListener("click", () => {
      if (sortKey === column.key) {
        sortDirection = sortDirection === "asc" ? "desc" : "asc";
      } else {
        sortKey = column.key;
        sortDirection = "asc";
      }
      page = 0;
      renderRows();
    });
    th.appendChild(button);
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.append(thead, tbody);
  tableScroll.appendChild(table);
  section.appendChild(tableScroll);

  const pagination = element("div", "pagination");
  const pageLabel = element("span");
  const previous = element("button", "", "←");
  previous.type = "button";
  previous.setAttribute("aria-label", "Previous table page");
  const next = element("button", "", "→");
  next.type = "button";
  next.setAttribute("aria-label", "Next table page");
  pagination.append(previous, pageLabel, next);
  section.appendChild(pagination);

  function filteredRows() {
    const matching = result.rows.filter((row) =>
      columns.some((column) =>
        String(row[column.key] ?? "")
          .toLocaleLowerCase()
          .includes(query),
      ),
    );
    return matching.sort((a, b) => {
      const comparison = compareValues(a[sortKey], b[sortKey]);
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }

  function renderRows() {
    const rows = filteredRows();
    const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    page = Math.min(page, pageCount - 1);
    tbody.replaceChildren();
    for (const row of rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
      const tr = element("tr");
      for (const column of columns) {
        const td = element("td", column.key === "value" ? "numeric" : "", displayValue(row[column.key]));
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    if (!rows.length) {
      const tr = element("tr");
      const td = element("td", "", "No rows match this filter.");
      td.colSpan = columns.length;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    pageLabel.textContent = `Page ${page + 1} of ${pageCount}`;
    previous.disabled = page === 0;
    next.disabled = page >= pageCount - 1;
  }

  search.addEventListener("input", () => {
    query = search.value.trim().toLocaleLowerCase();
    page = 0;
    renderRows();
  });
  previous.addEventListener("click", () => {
    page -= 1;
    renderRows();
  });
  next.addEventListener("click", () => {
    page += 1;
    renderRows();
  });
  download.addEventListener("click", () => downloadCsv(result, columns));
  renderRows();
  return section;
}

function createTableSections(result) {
  const sourceTables = (result.source_tables || []).filter((table) => table?.rows?.length);
  if (sourceTables.length < 2) return [createTableSection(result)];

  const sections = [];
  const sourceCodes = new Set(sourceTables.map((table) => table.dataset?.code).filter(Boolean));
  if (!sourceCodes.has(result.dataset?.code)) {
    sections.push(createTableSection(result, "Combined data"));
  }
  for (const table of sourceTables) {
    const code = table.dataset?.code || "Eurostat dataset";
    const section = createTableSection(table, `Dataset ${code}`);
    if (table.dataset?.title) section.title = table.dataset.title;
    sections.push(section);
  }
  return sections;
}

function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(result, columns) {
  const lines = [
    columns.map((column) => csvCell(column.label)).join(","),
    ...result.rows.map((row) => columns.map((column) => csvCell(row[column.key])).join(",")),
  ];
  const blob = new Blob([`\ufeff${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  const code = result.dataset?.code || "eurostat";
  link.href = URL.createObjectURL(blob);
  link.download = `${code}-observations.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function sourceTableForDataset(result, dataset) {
  const sourceTable = (result.source_tables || []).find(
    (table) => table.dataset?.code === dataset.code,
  );
  if (sourceTable) return sourceTable;
  return result.dataset?.code === dataset.code ? result : null;
}

function openApiQueryPanel(dataset, table) {
  apiQueryPanelTitle.textContent = dataset.title || dataset.code || "Query results";
  apiQueryPanelBody.replaceChildren();

  const overview = element("section", "api-query-overview");
  const codeRow = element("div", "api-query-code-row");
  codeRow.append(
    element("span", "source-label", "Dataset"),
    element("code", "api-query-code", dataset.code || "Not reported"),
  );
  overview.appendChild(codeRow);

  if (dataset.source_url) {
    const request = element("div", "api-query-request");
    request.append(
      element("span", "source-label", "Filtered API request"),
      element("code", "api-query-url", dataset.source_url),
    );
    overview.appendChild(request);
  }

  const chips = element("div", "api-query-filters");
  chips.appendChild(element("span", "source-label", "Applied filters"));
  const chipList = element("div", "filter-chips");
  Object.entries(table?.filters || {}).forEach(([key, values]) => {
    for (const value of values) {
      chipList.appendChild(element("span", "filter-chip", `${key}=${value}`));
    }
  });
  if (!chipList.childElementCount) {
    chipList.appendChild(element("span", "source-value", "No filters reported"));
  }
  chips.appendChild(chipList);
  overview.appendChild(chips);
  apiQueryPanelBody.appendChild(overview);

  if (table?.rows?.length) {
    const tableSection = createTableSection(table, "Returned observations");
    tableSection.classList.add("api-query-table");
    tableSection.open = true;
    apiQueryPanelBody.appendChild(tableSection);
  } else {
    apiQueryPanelBody.appendChild(
      element(
        "p",
        "api-query-empty",
        "The stored answer does not contain rows for this source. Run the query again to load them.",
      ),
    );
  }

  apiQueryPanel.showModal();
}

function createProvenance(result) {
  const section = element("details", "provenance result-details");
  const sources = result.sources?.length ? result.sources : [result.dataset || {}];
  const summary = element("summary", "result-summary");
  summary.append(
    element("span", "", sources.length > 1 ? "Sources" : "Source"),
    element(
      "span",
      "result-summary-meta",
      `${sources.length} dataset${sources.length === 1 ? "" : "s"}`,
    ),
  );
  section.appendChild(summary);
  const grid = element("div", "source-grid");

  function sourceItem(label, valueNode) {
    const item = element("div", "source-item");
    item.appendChild(element("span", "source-label", label));
    if (valueNode instanceof Node) {
      valueNode.classList.add("source-value");
      item.appendChild(valueNode);
    } else {
      item.appendChild(element("span", "source-value", valueNode || "—"));
    }
    return item;
  }

  sources.forEach((dataset, index) => {
    const sourceLink = element("a", "", `${dataset.code || "Dataset"} ↗`);
    sourceLink.href = eurostatDatasetUrl(dataset.code) || dataset.source_url;
    sourceLink.target = "_blank";
    sourceLink.rel = "noopener noreferrer";
    const suffix = sources.length > 1 ? ` ${index + 1}` : "";
    grid.appendChild(sourceItem(`Eurostat dataset${suffix}`, sourceLink));
    grid.appendChild(sourceItem(`Title${suffix}`, dataset.title));
    grid.appendChild(sourceItem(`Updated${suffix}`, dataset.updated || "Not reported"));
    if (dataset.source_url) {
      const queryButton = element("button", "source-query-button", "View query results →");
      queryButton.type = "button";
      queryButton.setAttribute(
        "aria-label",
        `View API query results for ${dataset.code || "this dataset"}`,
      );
      queryButton.addEventListener("click", () => {
        openApiQueryPanel(dataset, sourceTableForDataset(result, dataset));
      });
      grid.appendChild(sourceItem(`API query${suffix}`, queryButton));
    }
  });

  const chips = element("div", "filter-chips");
  Object.entries(result.filters || {}).forEach(([key, values]) => {
    for (const value of values) chips.appendChild(element("span", "filter-chip", `${key}=${value}`));
  });
  grid.appendChild(sourceItem("Applied filters", chips));
  section.appendChild(grid);
  return section;
}

function toolCallLabel(toolCalls) {
  if (!Number.isInteger(toolCalls) || toolCalls < 0) return "";
  return `${toolCalls} tool ${toolCalls === 1 ? "call" : "calls"}`;
}

function responseDatasetCodes(result, details) {
  const codes = new Set();
  const sources = result?.sources?.length ? result.sources : [result?.dataset];
  for (const source of sources) {
    if (source?.code && !source.code.includes("__")) codes.add(source.code);
  }
  for (const detail of details || []) {
    for (const key of ["dataset", "x_dataset", "y_dataset"]) {
      const code = detail?.arguments?.[key];
      if (typeof code === "string" && code) codes.add(code);
    }
  }
  return [...codes];
}

function addResponse(answerText, result, toolCalls, details = [], shouldScroll = true) {
  const response = element("article", "response");
  const kicker = element("div", "response-kicker");
  kicker.appendChild(element("span", "", "Eurostat agent"));
  const callLabel = toolCallLabel(toolCalls);
  if (callLabel) {
    if (details.length) {
      const callButton = element("button", "tool-call-count", callLabel);
      callButton.type = "button";
      callButton.addEventListener("click", () => openToolCallDialog(details));
      kicker.appendChild(callButton);
    } else {
      kicker.appendChild(element("span", "tool-call-count", callLabel));
    }
  }
  response.appendChild(kicker);
  const answer = element("div", "answer");
  renderMarkdown(answer, answerText, {
    datasetCodes: responseDatasetCodes(result, details),
  });
  response.appendChild(answer);

  if (result?.rows?.length) {
    const chartSection = createChartSection(result);
    if (chartSection) response.appendChild(chartSection);
    response.append(...createTableSections(result));
    if (result.warnings?.length) {
      response.appendChild(element("p", "warning", result.warnings.join(" ")));
    }
    response.appendChild(createProvenance(result));
  }
  chat.appendChild(response);
  if (shouldScroll) response.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderWorkspace() {
  const record = activeChat();
  if (!record) return;
  finalizeChartViews(chat);
  chat.replaceChildren();
  hero.hidden = record.messages.length > 0;
  currentChatTitle.textContent = record.title;
  downloadChatLogButton.disabled = record.messages.length === 0;
  downloadChatLogButton.setAttribute(
    "aria-label",
    record.messages.length
      ? `Download log for ${record.title}`
      : "Download log (available after the first message)",
  );
  const summary = buildContextSummary(record.messages);
  contextStatus.hidden = !summary;
  contextStatus.title = summary
    ? "Older turns are represented by a bounded extractive summary to reduce model input."
    : "";

  for (const message of record.messages) {
    if (message.role === "user") {
      addQuestion(message.content);
    } else {
      addResponse(
        message.content,
        message.result,
        message.toolCalls,
        message.toolCallDetails || [],
        false,
      );
    }
  }
  if (hasPendingForChat(inFlightState, record.id)) {
    addPending(inFlightState.label);
  }
  syncToolActivity(record);
  renderChatList();
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    if (response.status === 401) {
      showAppLock("Your app session expired. Enter the password again.");
      return;
    }
    const data = await response.json();
    if (data.agent_ready) {
      statusBadge.textContent = "Agent ready";
      statusWrap.className = "status-wrap ready";
      return;
    }
    statusBadge.textContent = "Setup required";
    statusWrap.className = "status-wrap error";
  } catch {
    statusBadge.textContent = "Backend offline";
    statusWrap.className = "status-wrap error";
  }
}

appLockForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = appLockPassword.value;
  if (!password) return;

  appUnlockButton.disabled = true;
  appLockError.hidden = true;
  try {
    const response = await fetch("/api/auth/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "The app could not be unlocked.");
    lockEnabled = Boolean(data.lock_enabled);
    showApp();
    renderWorkspace();
    if (historyNotice) {
      showNotification(historyNotice);
      historyNotice = "";
    }
    await checkHealth();
  } catch (error) {
    showAppLock(error instanceof Error ? error.message : "The app could not be unlocked.");
  } finally {
    appUnlockButton.disabled = false;
  }
});

lockAppButton.addEventListener("click", async () => {
  try {
    await fetch("/api/auth/lock", { method: "POST" });
  } finally {
    showAppLock();
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = promptInput.value.trim();
  const record = activeChat();
  if (!message || !record || inFlightChatId) return;

  const priorMessages = [...record.messages];
  const summary = buildContextSummary(priorMessages);
  const history = recentHistory(priorMessages);
  const contextResult = latestDataResult(priorMessages);
  if (!record.messages.length) record.title = titleFromPrompt(message);
  const requestStartedAt = new Date();
  const userMessage = {
    role: "user",
    content: message,
    createdAt: requestStartedAt.toISOString(),
  };
  record.messages.push(userMessage);
  record.updatedAt = requestStartedAt.toISOString();
  record.messageCount = record.messages.length;
  record.turnCount = (record.turnCount || 0) + 1;
  inFlightChatId = record.id;
  inFlightState = createInFlightState(record.id);
  await persistMessage(record, userMessage);
  if (state.activeChatId === record.id) {
    hero.hidden = true;
    addQuestion(message);
    currentChatTitle.textContent = record.title;
    downloadChatLogButton.disabled = false;
    addPending(inFlightState.label);
  }
  renderChatList();
  promptInput.value = "";
  sendButton.disabled = true;
  const timer = window.setInterval(() => {
    advancePendingStage(inFlightState);
    syncPendingLabel();
  }, 2600);
  startToolActivity();

  try {
    const data = await streamChat(
      { message, history, summary, context_result: contextResult },
      (streamEvent) => {
        if (streamEvent.type !== "tool_call" || !streamEvent.call) return;
        updateToolActivity(streamEvent.call);
        if (streamEvent.phase === "started") {
          setInFlightLabel(
            inFlightState,
            `Running ${readableToolName(streamEvent.call.name)}`,
          );
        } else if (streamEvent.call.status === "error") {
          setInFlightLabel(
            inFlightState,
            `${readableToolName(streamEvent.call.name)} reported an error`,
          );
        } else {
          setInFlightLabel(
            inFlightState,
            `${readableToolName(streamEvent.call.name)} completed`,
          );
        }
        syncPendingLabel();
      },
    );
    finishToolActivity(data.tool_call_details, data.tool_calls);
    const target = state.chats.find((item) => item.id === record.id);
    if (target) {
      const assistantMessage = {
        role: "assistant",
        content: data.answer,
        createdAt: new Date().toISOString(),
        durationMs: Date.now() - requestStartedAt.getTime(),
        result: data.result,
        toolCalls: data.tool_calls,
        toolCallDetails: data.tool_call_details,
      };
      target.messages.push(assistantMessage);
      target.updatedAt = new Date().toISOString();
      target.messageCount = target.messages.length;
      const saved = await persistMessage(target, assistantMessage);
      if (state.activeChatId === target.id) {
        renderWorkspace();
        chat.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "start" });
        if (!saved && historyStore) {
          addError("The answer is available, but this browser could not persist the latest chat data.");
        }
      }
      renderChatList();
    }
  } catch (error) {
    failToolActivity();
    const target = state.chats.find((item) => item.id === record.id);
    if (target) {
      target.events ??= [];
      const diagnosticEvent = {
        type: "request_error",
        createdAt: new Date().toISOString(),
        durationMs: Date.now() - requestStartedAt.getTime(),
        message: error instanceof Error ? error.message : String(error),
      };
      target.events.push(diagnosticEvent);
      target.updatedAt = new Date().toISOString();
      target.eventCount = target.events.length;
      await persistEvent(target, diagnosticEvent);
    }
    if (state.activeChatId === record.id) {
      renderWorkspace();
      addError(error.message);
    }
  } finally {
    window.clearInterval(timer);
    inFlightChatId = null;
    if (historyStore && state.activeChatId !== record.id) {
      const completedIndex = state.chats.findIndex((item) => item.id === record.id);
      if (completedIndex >= 0) {
        state.chats[completedIndex] = unloadedRecord(state.chats[completedIndex]);
      }
    }
    inFlightState = null;
    sendButton.disabled = false;
    promptInput.focus();
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    promptInput.value = button.dataset.prompt;
    composer.requestSubmit();
  });
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

newChatButton.addEventListener("click", () => {
  void createChat();
});
themeToggleButton.addEventListener("click", () => {
  themeApi.toggleTheme();
  syncThemeToggle();
  renderWorkspace();
});
downloadChatLogButton.addEventListener("click", downloadCurrentChatLog);
notificationDismiss.addEventListener("click", hideNotification);
menuButton.addEventListener("click", openSidebar);
sidebarClose.addEventListener("click", closeSidebar);
sidebarBackdrop.addEventListener("click", closeSidebar);
toolActivity.addEventListener("click", () => openToolCallDialog());
toolCallDialogClose.addEventListener("click", () => toolCallDialog.close());
toolCallDialog.addEventListener("click", (event) => {
  if (event.target === toolCallDialog) toolCallDialog.close();
});
apiQueryPanelClose.addEventListener("click", () => apiQueryPanel.close());
apiQueryPanel.addEventListener("click", (event) => {
  if (event.target !== apiQueryPanel) return;
  const bounds = apiQueryPanel.getBoundingClientRect();
  const outsidePanel =
    event.clientX < bounds.left ||
    event.clientX > bounds.right ||
    event.clientY < bounds.top ||
    event.clientY > bounds.bottom;
  if (outsidePanel) apiQueryPanel.close();
});
window.addEventListener("storage", (event) => {
  if (event.key !== themeApi.STORAGE_KEY) return;
  themeApi.applyTheme(themeApi.loadTheme() || themeApi.systemTheme());
  syncThemeToggle();
  renderWorkspace();
});

async function initializeApp() {
  syncThemeToggle();
  await initializeHistory();
  if (await checkAuth()) {
    renderWorkspace();
    if (historyNotice) {
      showNotification(historyNotice);
      historyNotice = "";
    }
    await checkHealth();
  }
}

initializeApp();
