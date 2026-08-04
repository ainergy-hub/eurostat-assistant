import { eurostatDatasetUrl } from "./markdown.js";

const PAGE_SIZE = 12;
const apiQueryPanel = document.querySelector("#api-query-panel");
const apiQueryPanelTitle = document.querySelector("#api-query-panel-title");
const apiQueryPanelBody = document.querySelector("#api-query-panel-body");

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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

export function createTableSections(result) {
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

export function createProvenance(result) {
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

export function toolCallLabel(toolCalls) {
  if (!Number.isInteger(toolCalls) || toolCalls < 0) return "";
  return `${toolCalls} tool ${toolCalls === 1 ? "call" : "calls"}`;
}

export function responseDatasetCodes(result, details) {
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
