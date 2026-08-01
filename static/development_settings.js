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
