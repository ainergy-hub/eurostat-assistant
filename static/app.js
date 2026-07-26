import {
  buildChatLog,
  buildContextSummary,
  latestDataResult,
  recentHistory,
  titleFromPrompt,
} from "./chat_state.js";
import { createChartSection } from "./chart.js";
import { eurostatDatasetUrl, renderMarkdown } from "./markdown.js";

const PAGE_SIZE = 12;
const MAX_CHATS = 30;
const STORAGE_KEY = "eurostat-lens-chats-v1";
const APP_VERSION = "0.2.0";

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
const downloadChatLogButton = document.querySelector("#download-chat-log");

let state = loadState();
let inFlightChatId = null;
let currentToolCalls = [];

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
  const summary = [`${details.length} total`, `${completed} completed`];
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

    const meta = element("div", "tool-call-meta");
    meta.append(
      element("span", "", `ID ${detail.id}`),
      element("span", "", toolDuration(detail)),
    );
    item.appendChild(meta);

    const argumentsBlock = element("div");
    argumentsBlock.appendChild(element("h3", "", "Arguments"));
    const argumentsCode = element("pre");
    argumentsCode.textContent = JSON.stringify(detail.arguments || {}, null, 2);
    argumentsBlock.appendChild(argumentsCode);
    item.appendChild(argumentsBlock);

    if (detail.result_preview) {
      const resultBlock = element("div");
      resultBlock.appendChild(element("h3", "", "Result preview"));
      resultBlock.appendChild(element("p", "tool-call-result", detail.result_preview));
      item.appendChild(resultBlock);
    }
    toolCallDetails.appendChild(item);
  }
}

function updateToolActivity(detail) {
  const existingIndex = currentToolCalls.findIndex((item) => item.id === detail.id);
  if (existingIndex >= 0) {
    currentToolCalls[existingIndex] = { ...currentToolCalls[existingIndex], ...detail };
  } else {
    currentToolCalls.push(detail);
  }
  currentToolCalls.sort((left, right) => left.index - right.index);
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
  toolActivity.hidden = false;
  toolActivity.className = "tool-activity running";
  toolActivityCount.textContent = "0";
  toolActivityStatus.textContent = "Starting agent";
  renderToolCallDetails();
}

function finishToolActivity(details, total) {
  if (Array.isArray(details) && details.length) currentToolCalls = details;
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

function failToolActivity() {
  toolActivity.hidden = false;
  toolActivity.className = "tool-activity error";
  toolActivityStatus.textContent = "Agent request failed · Select for details";
  renderToolCallDetails();
}

function syncToolActivity(record) {
  if (inFlightChatId) return;
  const latestWithDetails = [...record.messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.toolCallDetails?.length);
  if (!latestWithDetails) {
    currentToolCalls = [];
    toolActivity.hidden = true;
    renderToolCallDetails();
    return;
  }
  finishToolActivity(latestWithDetails.toolCallDetails, latestWithDetails.toolCalls);
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
    messages: [],
    events: [],
  };
}

function loadState() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (stored?.chats?.length) {
      const chats = stored.chats
        .filter((item) => item && typeof item.id === "string" && Array.isArray(item.messages))
        .map((item) => ({
          ...item,
          events: Array.isArray(item.events) ? item.events : [],
        }))
        .slice(0, MAX_CHATS);
      const activeChatId = chats.some((item) => item.id === stored.activeChatId)
        ? stored.activeChatId
        : chats[0]?.id;
      if (chats.length && activeChatId) return { chats, activeChatId };
    }
  } catch {
    // A malformed browser cache should never prevent the app from starting.
  }
  const firstChat = newChatRecord();
  return { chats: [firstChat], activeChatId: firstChat.id };
}

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    return true;
  } catch {
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
    const turnCount = Math.ceil(record.messages.length / 2);
    text.append(
      element("strong", "", record.title),
      element(
        "small",
        "",
        `${turnCount} turn${turnCount === 1 ? "" : "s"} · ${formatChatDate(record.updatedAt)}`,
      ),
    );
    select.appendChild(text);
    select.addEventListener("click", () => selectChat(record.id));

    const remove = element("button", "chat-delete", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Delete ${record.title}`);
    remove.addEventListener("click", () => deleteChat(record.id));
    row.append(select, remove);
    chatList.appendChild(row);
  }
}

function selectChat(id) {
  if (!state.chats.some((item) => item.id === id)) return;
  state.activeChatId = id;
  saveState();
  renderWorkspace();
  closeSidebar();
}

function createChat() {
  const current = activeChat();
  if (current && current.messages.length === 0) {
    promptInput.focus();
    closeSidebar();
    return;
  }
  if (state.chats.length >= MAX_CHATS) {
    window.alert("This proof of concept keeps up to 30 investigations. Delete one before starting another.");
    return;
  }
  const record = newChatRecord();
  state.chats.push(record);
  state.activeChatId = record.id;
  saveState();
  renderWorkspace();
  closeSidebar();
  promptInput.focus();
}

function deleteChat(id) {
  if (id === inFlightChatId) {
    window.alert("Wait for this investigation to finish before deleting it.");
    return;
  }
  const record = state.chats.find((item) => item.id === id);
  if (!record || !window.confirm(`Delete “${record.title}” from this device?`)) return;
  state.chats = state.chats.filter((item) => item.id !== id);
  if (!state.chats.length) state.chats.push(newChatRecord());
  if (state.activeChatId === id) state.activeChatId = state.chats[0].id;
  saveState();
  renderWorkspace();
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

function addPending() {
  const pending = pendingTemplate.content.firstElementChild.cloneNode(true);
  chat.appendChild(pending);
  const label = pending.querySelector(".progress-label");
  const stages = [
    "Inspecting dataset dimensions",
    "Fetching a bounded data slice",
    "Checking units and observation flags",
    "Preparing the answer and visualisation",
  ];
  let stage = 0;
  const timer = window.setInterval(() => {
    label.textContent = stages[Math.min(stage, stages.length - 1)];
    stage += 1;
  }, 2600);
  pending.scrollIntoView({ behavior: "smooth", block: "center" });
  return { pending, timer, label };
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

function createTableSection(result) {
  const section = element("section", "result-section");
  const heading = element("div", "section-heading");
  const headingCopy = element("div");
  headingCopy.appendChild(element("h2", "", "Observations"));
  headingCopy.appendChild(
    element("p", "", `${result.rows.length} rows returned by the bounded query`),
  );
  heading.appendChild(headingCopy);
  section.appendChild(heading);

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

function createProvenance(result) {
  const section = element("section", "provenance");
  const sources = result.sources?.length ? result.sources : [result.dataset || {}];
  section.appendChild(element("h2", "", sources.length > 1 ? "Sources" : "Source"));
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
      const queryLink = element("a", "", "Open filtered API query ↗");
      queryLink.href = dataset.source_url;
      queryLink.target = "_blank";
      queryLink.rel = "noopener noreferrer";
      grid.appendChild(sourceItem(`API query${suffix}`, queryLink));
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
    response.appendChild(createTableSection(result));
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
  syncToolActivity(record);
  renderChatList();
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
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
  record.messages.push({
    role: "user",
    content: message,
    createdAt: requestStartedAt.toISOString(),
  });
  record.updatedAt = requestStartedAt.toISOString();
  inFlightChatId = record.id;
  saveState();
  hero.hidden = true;
  addQuestion(message);
  currentChatTitle.textContent = record.title;
  downloadChatLogButton.disabled = false;
  renderChatList();
  promptInput.value = "";
  sendButton.disabled = true;
  const { pending, timer, label } = addPending();
  startToolActivity();

  try {
    const data = await streamChat(
      { message, history, summary, context_result: contextResult },
      (streamEvent) => {
        if (streamEvent.type !== "tool_call" || !streamEvent.call) return;
        updateToolActivity(streamEvent.call);
        if (streamEvent.phase === "started") {
          label.textContent = `Running ${readableToolName(streamEvent.call.name)}`;
        } else if (streamEvent.call.status === "error") {
          label.textContent = `${readableToolName(streamEvent.call.name)} reported an error`;
        } else {
          label.textContent = `${readableToolName(streamEvent.call.name)} completed`;
        }
      },
    );
    pending.remove();
    finishToolActivity(data.tool_call_details, data.tool_calls);
    const target = state.chats.find((item) => item.id === record.id);
    if (target) {
      target.messages.push({
        role: "assistant",
        content: data.answer,
        createdAt: new Date().toISOString(),
        durationMs: Date.now() - requestStartedAt.getTime(),
        result: data.result,
        toolCalls: data.tool_calls,
        toolCallDetails: data.tool_call_details,
      });
      target.updatedAt = new Date().toISOString();
      const saved = saveState();
      if (state.activeChatId === target.id) {
        addResponse(
          data.answer,
          data.result,
          data.tool_calls,
          data.tool_call_details || [],
        );
        const updatedSummary = buildContextSummary(target.messages);
        contextStatus.hidden = !updatedSummary;
        contextStatus.title = updatedSummary
          ? "Older turns are represented by a bounded extractive summary to reduce model input."
          : "";
        if (!saved) {
          addError("The answer is available, but this browser could not persist the latest chat data.");
        }
      }
      renderChatList();
    }
  } catch (error) {
    pending.remove();
    failToolActivity();
    const target = state.chats.find((item) => item.id === record.id);
    if (target) {
      target.events ??= [];
      target.events.push({
        type: "request_error",
        createdAt: new Date().toISOString(),
        durationMs: Date.now() - requestStartedAt.getTime(),
        message: error instanceof Error ? error.message : String(error),
      });
      target.updatedAt = new Date().toISOString();
      saveState();
    }
    if (state.activeChatId === record.id) addError(error.message);
  } finally {
    window.clearInterval(timer);
    inFlightChatId = null;
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

newChatButton.addEventListener("click", createChat);
downloadChatLogButton.addEventListener("click", downloadCurrentChatLog);
menuButton.addEventListener("click", openSidebar);
sidebarClose.addEventListener("click", closeSidebar);
sidebarBackdrop.addEventListener("click", closeSidebar);
toolActivity.addEventListener("click", () => openToolCallDialog());
toolCallDialogClose.addEventListener("click", () => toolCallDialog.close());
toolCallDialog.addEventListener("click", (event) => {
  if (event.target === toolCallDialog) toolCallDialog.close();
});
window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_KEY) return;
  state = loadState();
  renderWorkspace();
});

renderWorkspace();
checkHealth();
