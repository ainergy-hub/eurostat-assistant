import {
  developmentLimitRows,
  loadSelectedModel,
  readableSettingName,
  saveSelectedModel,
} from "./development_settings.js?v=20260801-2";

const modelSelect = document.querySelector("#model-select");
const modelDescription = document.querySelector("#model-description");
const modelSaveStatus = document.querySelector("#settings-save-status");
const activeModelSummary = document.querySelector("#active-model-summary");
const toolCountSummary = document.querySelector("#tool-count-summary");
const developmentToolCatalog = document.querySelector("#development-tool-catalog");
const runtimeList = document.querySelector("#runtime-list");
const developmentAppVersion = document.querySelector("#development-app-version");

let developmentSettings = null;
let selectedModel = "";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function selectedModelOption() {
  return developmentSettings?.models?.find((model) => model.id === selectedModel) || null;
}

function syncModelDescription() {
  const option = selectedModelOption();
  modelDescription.textContent = option?.description || "No model description is available.";
  activeModelSummary.textContent = option?.label || selectedModel || "Unavailable";
}

function renderDevelopmentSettings(settings) {
  developmentSettings = settings;
  selectedModel = loadSelectedModel(settings.models, settings.default_model);

  modelSelect.replaceChildren();
  for (const model of settings.models) {
    const option = element("option", "", model.label);
    option.value = model.id;
    option.selected = model.id === selectedModel;
    modelSelect.appendChild(option);
  }
  modelSelect.disabled = settings.models.length < 2;
  syncModelDescription();

  developmentToolCatalog.replaceChildren();
  for (const [index, tool] of settings.tools.entries()) {
    const item = element("article", "development-tool");
    const heading = element("div", "development-tool-heading");
    heading.append(
      element("span", "development-tool-number", String(index + 1).padStart(2, "0")),
      element("strong", "", readableSettingName(tool.name)),
      element("code", "", tool.name),
    );
    item.append(
      heading,
      element("p", "", tool.description),
      element("span", "development-tool-limit", `Up to ${tool.per_request_limit} calls per request`),
    );
    developmentToolCatalog.appendChild(item);
  }
  toolCountSummary.textContent = String(settings.tools.length);

  const runtimeLabels = {
    model_gateway: "Model gateway",
    title_model: "Chat title model",
    data_source: "Data source",
    history: "Chat history",
  };
  runtimeList.replaceChildren();
  for (const [key, value] of Object.entries(settings.runtime)) {
    const row = element("div");
    row.append(
      element("dt", "", runtimeLabels[key] || readableSettingName(key)),
      element("dd", "", value),
    );
    runtimeList.appendChild(row);
  }
  for (const limit of developmentLimitRows(settings.limits)) {
    const row = element("div");
    row.append(
      element("dt", "", limit.label),
      element("dd", "", limit.value),
    );
    runtimeList.appendChild(row);
  }
  developmentAppVersion.textContent = `v${settings.app_version}`;
}

export async function loadDevelopmentSettings() {
  try {
    const response = await fetch("/api/settings/development", { cache: "no-store" });
    if (!response.ok) throw new Error("Development settings are unavailable.");
    renderDevelopmentSettings(await response.json());
  } catch (error) {
    modelSelect.disabled = true;
    modelDescription.textContent = error instanceof Error ? error.message : String(error);
    activeModelSummary.textContent = "Unavailable";
    toolCountSummary.textContent = "—";
    developmentToolCatalog.replaceChildren(
      element("p", "settings-loading settings-error", "Could not load tool descriptions."),
    );
  }
}

export function selectedModelForRequest() {
  return selectedModel;
}

export function bindDevelopmentSettings() {
  modelSelect.addEventListener("change", () => {
    selectedModel = modelSelect.value;
    syncModelDescription();
    const saved = saveSelectedModel(selectedModel, developmentSettings?.models || []);
    modelSaveStatus.textContent = saved
      ? "Saved for new questions"
      : "Browser storage is unavailable";
    modelSaveStatus.className = `settings-save-status ${saved ? "saved" : "error"}`;
  });
}
