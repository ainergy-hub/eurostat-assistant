export const MODEL_STORAGE_KEY = "eurostat-lens-model-v1";

function availableModelIds(models = []) {
  return new Set(models.map((model) => model?.id).filter(Boolean));
}

export function loadSelectedModel(models, fallback, storage = globalThis.localStorage) {
  const available = availableModelIds(models);
  try {
    const saved = storage?.getItem(MODEL_STORAGE_KEY);
    if (saved && available.has(saved)) return saved;
  } catch {
    // A blocked storage API should not prevent the settings page from loading.
  }
  return available.has(fallback) ? fallback : models[0]?.id || "";
}

export function saveSelectedModel(model, models, storage = globalThis.localStorage) {
  if (!availableModelIds(models).has(model)) return false;
  try {
    storage?.setItem(MODEL_STORAGE_KEY, model);
  } catch {
    return false;
  }
  return true;
}

export function readableSettingName(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function developmentLimitRows(limits = {}) {
  const number = (value) => Number(value || 0).toLocaleString("en-US");
  const megabytes = Number(limits.eurostat_response_bytes || 0) / 1_000_000;
  return [
    {
      label: "Agent budget",
      value: `${number(limits.tool_calls)} tool calls · ${number(limits.result_rows)} result rows`,
    },
    {
      label: "Eurostat query guard",
      value: `${number(limits.estimated_cells)} estimated cells · ${number(limits.time_periods)} time periods`,
    },
    {
      label: "Eurostat response cap",
      value: `${number(megabytes)} MB per response`,
    },
    {
      label: "Conversation context",
      value: `${number(limits.recent_messages)} recent messages · ${number(limits.summary_characters)} summary characters`,
    },
  ];
}
