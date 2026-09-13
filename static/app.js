import {
  buildChatLog,
  buildContextSummary,
  latestDataResult,
  latestUnansweredFailure,
  recentHistory,
  shortChatTitle,
  titleFromPrompt,
} from "./chat_state.js?v=20260816-2";
import {
  ChatHistoryStore,
  requestPersistentStorage,
} from "./chat_store.js?v=20260816-1";
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
import { renderMarkdown } from "./markdown.js";
import {
  bindDevelopmentSettings,
  loadDevelopmentSettings,
  selectedModelForRequest,
} from "./development_view.js?v=20260816-1";
import { generateChatTitle, streamChat } from "./chat_api.js?v=20260816-1";
import { readableToolName, renderToolCallDetails as renderToolTrace } from "./tool_trace.js";
import {
  createProvenance,
  createTableSections,
  responseDatasetCodes,
  toolCallLabel,
} from "./result_view.js";

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
const topbar = document.querySelector(".topbar");
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
const apiQueryPanel = document.querySelector("#api-query-panel");
const apiQueryPanelClose = document.querySelector("#api-query-panel-close");
const downloadChatLogButton = document.querySelector("#download-chat-log");
const themeToggleButton = document.querySelector("#theme-toggle");
const notification = document.querySelector("#notification");
const notificationMessage = document.querySelector("#notification-message");
const notificationDismiss = document.querySelector("#notification-dismiss");
const developmentLink = document.querySelector("#development-link");
const infoButton = document.querySelector("#info-button");
const aboutDialog = document.querySelector("#about-dialog");
const aboutDialogClose = document.querySelector("#about-dialog-close");
const aboutAppVersion = document.querySelector("#about-app-version");
const feedbackButton = document.querySelector("#feedback-button");
const feedbackDialog = document.querySelector("#feedback-dialog");
const feedbackDialogClose = document.querySelector("#feedback-dialog-close");
const feedbackForm = document.querySelector("#feedback-form");
const feedbackCategory = document.querySelector("#feedback-category");
const feedbackText = document.querySelector("#feedback-text");
const feedbackEmail = document.querySelector("#feedback-email");
const feedbackChatLog = document.querySelector("#feedback-chat-log");
const feedbackStatus = document.querySelector("#feedback-status");
const feedbackSubmit = document.querySelector("#feedback-submit");
const feedbackCancel = document.querySelector("#feedback-cancel");
const developmentPage = document.querySelector("#development-page");
const settingsCloseButton = document.querySelector("#settings-close");
const chatViews = document.querySelectorAll("[data-chat-view]");
const themeApi = globalThis.EurostatTheme;

let state = { chats: [], activeChatId: null };
let historyStore = null;
let historyNotice = "";
let inFlightChatId = null;
let inFlightState = null;
let currentToolCalls = [];
let lockEnabled = false;
let notificationTimer = null;
let pendingRetryContext = null;

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

function renderChatTitle(node, record, { compact = false } = {}) {
  node.classList.toggle("title-loading", Boolean(record?.titlePending));
  if (!record?.titlePending) {
    node.removeAttribute("aria-label");
    node.textContent = compact ? shortChatTitle(record?.title) : record?.title || "New investigation";
    return;
  }
  node.setAttribute("aria-label", "Generating chat title");
  const loader = element("span", "title-loader");
  loader.setAttribute("aria-hidden", "true");
  loader.append(element("span"), element("span"), element("span"));
  node.replaceChildren(
    element("span", "sr-only", "Generating chat title"),
    loader,
  );
}

function recordTitleLabel(record) {
  return record?.titlePending ? "current chat" : record?.title || "current chat";
}


function showDevelopmentPage({ updateHistory = true } = {}) {
  appLayout.classList.add("settings-view");
  document.body.classList.add("settings-open");
  sidebar.inert = true;
  topbar.inert = true;
  chatViews.forEach((view) => { view.hidden = true; });
  developmentPage.hidden = false;
  developmentLink.classList.add("active");
  developmentLink.setAttribute("aria-current", "page");
  developmentLink.hidden = true;
  currentChatTitle.classList.remove("title-loading");
  currentChatTitle.removeAttribute("aria-label");
  currentChatTitle.textContent = "Development";
  contextStatus.hidden = true;
  downloadChatLogButton.hidden = true;
  downloadChatLogButton.disabled = true;
  downloadChatLogButton.title = "Return to a chat to download its log";
  downloadChatLogButton.setAttribute("aria-label", "Download log unavailable in settings");
  closeSidebar();
  if (updateHistory && window.location.pathname !== "/settings/development") {
    window.history.pushState({ view: "development" }, "", "/settings/development");
  }
  developmentPage.scrollTo({ top: 0, behavior: "smooth" });
  window.setTimeout(() => settingsCloseButton.focus(), 0);
}

function showChatPage({ updateHistory = true } = {}) {
  appLayout.classList.remove("settings-view");
  document.body.classList.remove("settings-open");
  sidebar.inert = false;
  topbar.inert = false;
  developmentPage.hidden = true;
  chatViews.forEach((view) => { view.hidden = false; });
  developmentLink.classList.remove("active");
  developmentLink.removeAttribute("aria-current");
  developmentLink.hidden = false;
  downloadChatLogButton.hidden = false;
  renderWorkspace();
  closeSidebar();
  if (updateHistory && window.location.pathname !== "/") {
    window.history.pushState({ view: "chat" }, "", "/");
  }
}

function syncPageFromLocation() {
  if (window.location.pathname === "/settings/development") {
    showDevelopmentPage({ updateHistory: false });
  } else {
    showChatPage({ updateHistory: false });
  }
}

function renderToolCallDetails(details = currentToolCalls) {
  renderToolTrace(details);
}

function deactivateToolActivity() {
  currentToolCalls = [];
  toolActivity.hidden = false;
  toolActivity.disabled = true;
  toolActivity.className = "tool-activity inactive";
  toolActivityCount.textContent = "0";
  toolActivityStatus.textContent = "No calls for this chat";
  renderToolCallDetails();
}

function updateToolActivity(detail) {
  const calls = updateInFlightToolCall(inFlightState, detail);
  if (state.activeChatId !== inFlightChatId) return;
  currentToolCalls = calls;
  const running = currentToolCalls.filter((item) => item.status === "running").length;
  const failed = currentToolCalls.filter((item) => item.status === "error").length;
  toolActivity.hidden = false;
  toolActivity.disabled = false;
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
  toolActivity.disabled = false;
  toolActivity.className = "tool-activity running";
  toolActivityCount.textContent = "0";
  toolActivityStatus.textContent = "Starting agent";
  renderToolCallDetails();
}

function renderFinishedToolActivity(details, total) {
  currentToolCalls = Array.isArray(details) ? details : [];
  const callTotal = Number.isInteger(total) ? total : currentToolCalls.length;
  if (callTotal === 0 && currentToolCalls.length === 0) {
    deactivateToolActivity();
    return;
  }
  toolActivity.hidden = false;
  toolActivity.disabled = false;
  toolActivity.className = "tool-activity";
  toolActivityCount.textContent = String(callTotal);
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
  toolActivity.disabled = false;
  toolActivity.className = "tool-activity error";
  toolActivityStatus.textContent = "Agent request failed · Select for details";
  renderToolCallDetails();
}

function syncToolActivity(record) {
  if (record.id === inFlightChatId && inFlightState) {
    currentToolCalls = inFlightState.toolCalls;
    if (inFlightState.phase === "error") {
      toolActivity.hidden = false;
      toolActivity.disabled = false;
      toolActivity.className = "tool-activity error";
      toolActivityCount.textContent = String(currentToolCalls.length);
      toolActivityStatus.textContent = "Agent request failed · Select for details";
      renderToolCallDetails();
      return;
    }
    if (inFlightState.phase === "completed") {
      renderFinishedToolActivity(currentToolCalls, inFlightState.toolCallTotal);
      return;
    }

    const running = currentToolCalls.filter((item) => item.status === "running").length;
    const failed = currentToolCalls.filter((item) => item.status === "error").length;
    toolActivity.hidden = false;
    toolActivity.disabled = false;
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
    deactivateToolActivity();
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

async function applyGeneratedTitle(chatId, generatedTitle) {
  const record = state.chats.find((item) => item.id === chatId);
  if (!record || typeof generatedTitle !== "string" || !generatedTitle.trim()) return;
  record.title = shortChatTitle(generatedTitle);
  record.titlePending = false;
  if (historyStore) {
    try {
      const metadata = await historyStore.updateChat(chatId, { title: record.title });
      applyMetadata(record, metadata);
    } catch {
      // The next message persistence attempt can still save the in-memory title.
    }
  }
  if (state.activeChatId === chatId && developmentPage.hidden) {
    renderChatTitle(currentChatTitle, record);
  }
  renderChatList();
}

async function generateAndApplyChatTitle(chatId, message) {
  try {
    const data = await generateChatTitle(message, { onUnauthorized: showAppLock });
    await applyGeneratedTitle(chatId, data.title);
  } catch {
    await applyGeneratedTitle(chatId, titleFromPrompt(message));
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
    const title = element("strong");
    renderChatTitle(title, record, { compact: true });
    text.append(title);
    select.appendChild(text);
    select.addEventListener("click", () => {
      void selectChat(record.id);
    });

    const remove = element("button", "chat-delete", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Delete ${recordTitleLabel(record)}`);
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
    showChatPage();
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
    showChatPage();
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
  link.download = `eurostat-assistant-${filenamePart(record.title)}-${date}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 0);
}

function openFeedbackDialog() {
  closeSidebar();
  if (feedbackStatus.dataset.state === "success") {
    feedbackStatus.hidden = true;
    feedbackStatus.textContent = "";
    delete feedbackStatus.dataset.state;
  }
  feedbackDialog.showModal();
  window.setTimeout(() => feedbackCategory.focus(), 0);
}

function closeFeedbackDialog() {
  if (!feedbackSubmit.disabled) feedbackDialog.close();
}

async function submitFeedback(event) {
  event.preventDefault();
  if (!feedbackForm.reportValidity()) return;

  feedbackSubmit.disabled = true;
  feedbackCancel.disabled = true;
  feedbackDialogClose.disabled = true;
  feedbackSubmit.textContent = "Sending…";
  feedbackStatus.hidden = true;
  feedbackStatus.textContent = "";
  delete feedbackStatus.dataset.state;

  const rating = feedbackForm.elements.rating.value;
  const payload = {
    category: feedbackCategory.value,
    feedback: feedbackText.value,
    rating: Number(rating),
  };
  if (feedbackEmail.value.trim()) payload.email = feedbackEmail.value.trim();
  if (feedbackChatLog.checked) {
    payload.chat_log = buildChatLog(activeChat(), {
      exportedAt: new Date().toISOString(),
      appVersion: APP_VERSION,
    });
  }

  try {
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "Feedback could not be saved. Try again.");
    }
    feedbackForm.reset();
    feedbackStatus.textContent = "Thanks. Your feedback was sent.";
    feedbackStatus.dataset.state = "success";
    feedbackStatus.hidden = false;
    feedbackSubmit.textContent = "Send feedback";
  } catch (error) {
    feedbackStatus.textContent =
      error instanceof Error ? error.message : "Feedback could not be saved. Try again.";
    feedbackStatus.dataset.state = "error";
    feedbackStatus.hidden = false;
    feedbackSubmit.textContent = "Retry";
  } finally {
    feedbackSubmit.disabled = false;
    feedbackCancel.disabled = false;
    feedbackDialogClose.disabled = false;
  }
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

function retryPrompt(message, priorMessages = []) {
  const prompt = String(message || "").trim();
  if (!prompt || inFlightChatId) return;
  pendingRetryContext = { prompt, priorMessages: [...priorMessages] };
  promptInput.value = prompt;
  composer.requestSubmit();
}

function appendResponseActions(response, prompt, priorMessages = [], confidence = "") {
  const normalizedConfidence = ["low", "medium", "high"].includes(
    String(confidence || "").toLowerCase(),
  )
    ? String(confidence).toLowerCase()
    : "";
  const canRetry = Boolean(String(prompt || "").trim());
  if (!canRetry && !normalizedConfidence) return;
  const actions = element("div", "response-actions");
  if (normalizedConfidence) {
    const label = element(
      "span",
      `confidence-level confidence-${normalizedConfidence}`,
      `Confidence: ${normalizedConfidence[0].toUpperCase()}${normalizedConfidence.slice(1)}`,
    );
    label.setAttribute("aria-label", `Answer confidence: ${normalizedConfidence}`);
    actions.appendChild(label);
  }
  if (canRetry) {
    const retryButton = element("button", "retry-button");
    retryButton.type = "button";
    retryButton.setAttribute("aria-label", "Retry this question");
    retryButton.append(
      element("span", "retry-icon", "↻"),
      element("span", "", "Retry"),
    );
    retryButton.addEventListener("click", () => retryPrompt(prompt, priorMessages));
    actions.appendChild(retryButton);
  }
  response.appendChild(actions);
}

function addError(message, prompt, priorMessages = [], shouldScroll = true) {
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
  appendResponseActions(response, prompt, priorMessages);
  chat.appendChild(response);
  if (shouldScroll) response.scrollIntoView({ behavior: "smooth", block: "start" });
}


function addResponse(
  answerText,
  result,
  toolCalls,
  details = [],
  retryMessage = "",
  retryContext = [],
  confidence = "",
  shouldScroll = true,
) {
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
  appendResponseActions(response, retryMessage, retryContext, confidence);
  chat.appendChild(response);
  if (shouldScroll) response.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderWorkspace() {
  const record = activeChat();
  if (!record) return;
  finalizeChartViews(chat);
  chat.replaceChildren();
  hero.hidden = record.messages.length > 0;
  renderChatTitle(currentChatTitle, record);
  downloadChatLogButton.disabled = record.messages.length === 0;
  downloadChatLogButton.setAttribute(
    "aria-label",
    record.messages.length
      ? `Download log for ${recordTitleLabel(record)}`
      : "Download log (available after the first message)",
  );
  downloadChatLogButton.title = record.messages.length
    ? `Download log for ${recordTitleLabel(record)}`
    : "Download log available after the first message";
  const summary = buildContextSummary(record.messages);
  contextStatus.hidden = !summary;
  contextStatus.title = summary
    ? "Older turns are represented by a bounded extractive summary to reduce model input."
    : "";

  let latestQuestion = "";
  let latestQuestionContext = [];
  for (const [index, message] of record.messages.entries()) {
    if (message.role === "user") {
      latestQuestion = message.content;
      latestQuestionContext = record.messages.slice(0, index);
      addQuestion(message.content);
    } else {
      addResponse(
        message.content,
        message.result,
        message.toolCalls,
        message.toolCallDetails || [],
        latestQuestion,
        latestQuestionContext,
        message.confidence,
        false,
      );
    }
  }
  const failure = latestUnansweredFailure(record);
  if (failure) addError(failure.message, failure.prompt, failure.priorMessages, false);
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
      statusBadge.textContent = "";
      statusWrap.className = "status-wrap";
      statusWrap.hidden = true;
      return;
    }
    statusBadge.textContent = "Setup required";
    statusWrap.className = "status-wrap error";
    statusWrap.hidden = false;
  } catch {
    statusBadge.textContent = "Backend offline";
    statusWrap.className = "status-wrap error";
    statusWrap.hidden = false;
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
    await loadDevelopmentSettings();
    renderWorkspace();
    syncPageFromLocation();
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

  const retryContext = pendingRetryContext?.prompt === message ? pendingRetryContext : null;
  pendingRetryContext = null;
  const priorMessages = retryContext
    ? [...retryContext.priorMessages]
    : [...record.messages];
  const summary = buildContextSummary(priorMessages);
  const history = recentHistory(priorMessages);
  const contextResult = latestDataResult(priorMessages);
  const shouldGenerateTitle = record.messages.length === 0;
  if (shouldGenerateTitle) record.titlePending = true;
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
    renderChatTitle(currentChatTitle, record);
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
  const requestModel = selectedModelForRequest();
  if (shouldGenerateTitle) {
    void generateAndApplyChatTitle(record.id, message);
  }

  try {
    const data = await streamChat(
      {
        message,
        history,
        summary,
        context_result: contextResult,
        ...(requestModel ? { model: requestModel } : {}),
      },
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
      { onUnauthorized: showAppLock },
    );
    finishToolActivity(data.tool_call_details, data.tool_calls);
    const target = state.chats.find((item) => item.id === record.id);
    if (target) {
      const assistantMessage = {
        role: "assistant",
        content: data.answer,
        confidence: data.confidence,
        createdAt: new Date().toISOString(),
        ...(data.model || requestModel ? { model: data.model || requestModel } : {}),
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
        ...(requestModel ? { model: requestModel } : {}),
      };
      target.events.push(diagnosticEvent);
      target.updatedAt = new Date().toISOString();
      target.eventCount = target.events.length;
      await persistEvent(target, diagnosticEvent);
    }
    if (state.activeChatId === record.id) {
      renderWorkspace();
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
  if (!developmentPage.hidden) showChatPage();
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
developmentLink.addEventListener("click", () => showDevelopmentPage());
infoButton.addEventListener("click", () => aboutDialog.showModal());
aboutDialogClose.addEventListener("click", () => aboutDialog.close());
aboutDialog.addEventListener("click", (event) => {
  if (event.target === aboutDialog) aboutDialog.close();
});
feedbackButton.addEventListener("click", openFeedbackDialog);
feedbackDialogClose.addEventListener("click", closeFeedbackDialog);
feedbackCancel.addEventListener("click", closeFeedbackDialog);
feedbackForm.addEventListener("submit", submitFeedback);
feedbackDialog.addEventListener("click", (event) => {
  if (event.target === feedbackDialog) closeFeedbackDialog();
});
feedbackDialog.addEventListener("close", () => feedbackButton.focus());
settingsCloseButton.addEventListener("click", () => {
  showChatPage();
  developmentLink.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || developmentPage.hidden) return;
  showChatPage();
  developmentLink.focus();
});
window.addEventListener("popstate", syncPageFromLocation);
window.addEventListener("storage", (event) => {
  if (event.key !== themeApi.STORAGE_KEY) return;
  themeApi.applyTheme(themeApi.loadTheme() || themeApi.systemTheme());
  syncThemeToggle();
  renderWorkspace();
});

async function initializeApp() {
  aboutAppVersion.textContent = APP_VERSION;
  bindDevelopmentSettings();
  syncThemeToggle();
  await initializeHistory();
  if (await checkAuth()) {
    await loadDevelopmentSettings();
    renderWorkspace();
    syncPageFromLocation();
    if (historyNotice) {
      showNotification(historyNotice);
      historyNotice = "";
    }
    await checkHealth();
  }
}

initializeApp();
