import { toolCallSummaryText } from "./tool_activity.js?v=20261022-1";

const toolCallDialogSummary = document.querySelector("#tool-call-dialog-summary");
const toolCallDetails = document.querySelector("#tool-call-details");

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function readableToolName(name) {
  return String(name || "Unknown tool")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function toolDuration(detail) {
  if (!Number.isInteger(detail?.duration_ms)) return "In progress";
  if (detail.duration_ms < 1000) return `${detail.duration_ms} ms`;
  return `${(detail.duration_ms / 1000).toFixed(2)} s`;
}

export function renderToolCallDetails(details = [], phase = "completed") {
  toolCallDetails.replaceChildren();
  toolCallDialogSummary.textContent = toolCallSummaryText(details, phase);

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
