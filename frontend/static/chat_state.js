export const RECENT_MESSAGE_LIMIT = 6;
export const SUMMARY_LIMIT = 2400;
export const HISTORY_MESSAGE_LIMIT = 20000;
export const CHAT_LOG_SCHEMA_VERSION = 2;
export const CHAT_TITLE_MAX_LENGTH = 40;
export const CHAT_TITLE_MAX_WORDS = 6;

export function shortChatTitle(value) {
  const cleaned = String(value || "").replace(/\s+/g, " ").trim();
  if (!cleaned) return "Untitled investigation";

  const words = cleaned.split(" ");
  const selected = [];
  for (const word of words) {
    if (selected.length >= CHAT_TITLE_MAX_WORDS) break;
    const candidate = [...selected, word].join(" ");
    if (candidate.length > CHAT_TITLE_MAX_LENGTH - 1) break;
    selected.push(word);
  }

  if (!selected.length) {
    return `${cleaned.slice(0, CHAT_TITLE_MAX_LENGTH - 1).trimEnd()}…`;
  }

  const title = selected.join(" ");
  const shortened = selected.length < words.length || title.length < cleaned.length;
  return shortened ? `${title.replace(/[.,;:!?]+$/, "")}…` : title;
}

export function titleFromPrompt(prompt) {
  return shortChatTitle(prompt);
}

function compactText(value, length) {
  const cleaned = String(value || "")
    .replace(/\|.*\|/g, " ")
    .replace(/[*_`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > length ? `${cleaned.slice(0, length - 1).trimEnd()}…` : cleaned;
}

export function buildContextSummary(messages) {
  const olderMessages = messages.slice(0, Math.max(0, messages.length - RECENT_MESSAGE_LIMIT));
  if (!olderMessages.length) return "";

  const entries = [];
  for (const message of olderMessages) {
    if (message.role === "user") {
      entries.push(`Question: ${compactText(message.content, 180)}`);
      continue;
    }
    const dataset = message.result?.dataset;
    const provenance = dataset
      ? ` Dataset ${dataset.code}; filters ${Object.entries(message.result.filters || {})
          .map(([key, values]) => `${key}=${values.join(",")}`)
          .join("; ")}.`
      : "";
    entries.push(`Finding: ${compactText(message.content, 260)}${provenance}`);
  }

  const selected = [];
  let used = 0;
  for (const entry of entries.reverse()) {
    if (used + entry.length + 1 > SUMMARY_LIMIT - 80) break;
    selected.unshift(entry);
    used += entry.length + 1;
  }
  return `Earlier investigation summary:\n${selected.join("\n")}`.slice(0, SUMMARY_LIMIT);
}

function historyContent(content) {
  const text = String(content || "");
  if (text.length <= HISTORY_MESSAGE_LIMIT) return text;
  // Drop a dangling high surrogate so the truncated text stays valid UTF-16.
  return `${text.slice(0, HISTORY_MESSAGE_LIMIT - 1).replace(/[\uD800-\uDBFF]$/, "")}…`;
}

export function recentHistory(messages) {
  return messages
    .slice(-RECENT_MESSAGE_LIMIT)
    .map(({ role, content }) => ({ role, content: historyContent(content) }));
}

export function latestDataResult(messages) {
  return [...messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.result?.rows?.length)
    ?.result ?? null;
}

export function latestUnansweredFailure(record) {
  const messages = Array.isArray(record?.messages) ? record.messages : [];
  const lastMessage = messages.at(-1);
  if (lastMessage?.role !== "user") return null;
  const questionTime = Date.parse(lastMessage.createdAt || "");
  const failure = [...(record?.events || [])]
    .reverse()
    .find((event) => event.type === "request_error");
  if (!failure) return null;
  const failureTime = Date.parse(failure.createdAt || "");
  if (!Number.isFinite(questionTime) || !Number.isFinite(failureTime)) return null;
  return failureTime >= questionTime
    ? {
        message: failure.message,
        prompt: lastMessage.content,
        priorMessages: messages.slice(0, -1),
      }
    : null;
}

function diagnosticToolCallDetails(details) {
  if (!Array.isArray(details)) return details;
  return details.map(({ result_preview: _resultPreview, ...detail }) => detail);
}

function diagnosticResult(result) {
  if (!result || typeof result !== "object") return result;
  const { rows, source_tables: sourceTables, ...metadata } = result;
  return {
    ...metadata,
    ...(Array.isArray(sourceTables)
      ? {
          source_tables: sourceTables.map(({ rows: sourceRows, ...table }) => ({
            ...table,
            ...(Array.isArray(sourceRows) ? { rowCount: sourceRows.length } : {}),
          })),
        }
      : {}),
    ...(Array.isArray(rows) ? { rowCount: rows.length } : {}),
  };
}

export function buildChatLog(
  record,
  {
    exportedAt = new Date().toISOString(),
    appVersion = "unknown",
  } = {},
) {
  const messages = Array.isArray(record?.messages) ? record.messages : [];
  const events = Array.isArray(record?.events) ? record.events : [];
  const summary = buildContextSummary(messages);

  return {
    schemaVersion: CHAT_LOG_SCHEMA_VERSION,
    app: {
      name: "Eurostat Assistant",
      version: appVersion,
    },
    exportedAt,
    privacyNotice:
      "Generated locally from this browser. Observation rows and tool result previews are excluded; review chat text before sharing.",
    investigation: {
      id: record?.id || null,
      title: record?.title || "Untitled investigation",
      createdAt: record?.createdAt || null,
      updatedAt: record?.updatedAt || null,
      messageCount: messages.length,
      turnCount: messages.filter((message) => message.role === "user").length,
      context: {
        recentMessageLimit: RECENT_MESSAGE_LIMIT,
        olderContextCompacted: Boolean(summary),
        compactSummary: summary || null,
      },
      messages: messages.map((message, index) => ({
        index: index + 1,
        role: message.role,
        createdAt: message.createdAt || null,
        content: message.content,
        ...(message.model === undefined ? {} : { model: message.model }),
        ...(message.confidence === undefined ? {} : { confidence: message.confidence }),
        ...(message.durationMs === undefined ? {} : { durationMs: message.durationMs }),
        ...(message.toolCalls === undefined ? {} : { toolCalls: message.toolCalls }),
        ...(message.toolCallDetails === undefined
          ? {}
          : { toolCallDetails: diagnosticToolCallDetails(message.toolCallDetails) }),
        ...(message.result === undefined ? {} : { result: diagnosticResult(message.result) }),
      })),
      events,
    },
  };
}

// Leave room below the 4 MB API limit for the next prompt and model selection.
export function shouldSuggestNewChat(messages) {
  if (messages.filter((message) => message.role === "user").length >= 10) return true;
  const context = {
    history: recentHistory(messages),
    summary: buildContextSummary(messages),
    context_result: latestDataResult(messages),
  };
  return new TextEncoder().encode(JSON.stringify(context)).byteLength >= 3_000_000;
}
