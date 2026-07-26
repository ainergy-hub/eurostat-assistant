export const RECENT_MESSAGE_LIMIT = 6;
export const SUMMARY_LIMIT = 2400;

export function titleFromPrompt(prompt) {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  return cleaned.length > 42 ? `${cleaned.slice(0, 41).trimEnd()}…` : cleaned;
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

export function recentHistory(messages) {
  return messages
    .slice(-RECENT_MESSAGE_LIMIT)
    .map(({ role, content }) => ({ role, content }));
}
