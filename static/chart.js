const VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json";
const NUMBER_FORMAT = ",.1~f";

const BASE_LAYOUT = Object.freeze({
  width: 920,
  lineHeight: 350,
  verticalBarHeight: 350,
  horizontalBarMinHeight: 350,
  horizontalBarRowHeight: 32,
  horizontalBarMaxLabelWidth: 340,
});

const FALLBACK_THEME = Object.freeze({
  series: ["#ff4f00", "#25764c", "#545c78", "#a66b1f", "#7b557c", "#357a78"],
  grid: "#e5e5e0",
  axis: "#a8a8a0",
  text: "#6b6b65",
  pointOutline: "#fbfbf6",
  surface: "#fbfbf6",
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function uniqueValues(rows, field) {
  return [...new Set(rows.map((row) => String(row[field] ?? "")))];
}

function sortDimensionValues(values) {
  return [...values].sort((left, right) => {
    const numeric = Number(left) - Number(right);
    return Number.isNaN(numeric) ? left.localeCompare(right) : numeric;
  });
}

function fieldLabel(field) {
  return String(field ?? "").replaceAll("_", " ");
}

function fieldTitle(spec, axis) {
  return spec[`${axis}_label`] || fieldLabel(spec[axis]);
}

function cssVariable(name, fallback) {
  if (typeof document === "undefined" || typeof getComputedStyle === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function chartTheme() {
  return {
    series: FALLBACK_THEME.series.map((color, index) =>
      cssVariable(`--chart-series-${index + 1}`, color),
    ),
    grid: cssVariable("--chart-grid", FALLBACK_THEME.grid),
    axis: cssVariable("--chart-axis", FALLBACK_THEME.axis),
    text: cssVariable("--chart-text", FALLBACK_THEME.text),
    pointOutline: cssVariable("--chart-point-outline", FALLBACK_THEME.pointOutline),
    surface: cssVariable("--color-surface", FALLBACK_THEME.surface),
  };
}

function numericRowsForSpec(rows, spec) {
  return rows
    .filter(
      (row) =>
        Number.isFinite(Number(row[spec.y])) &&
        (spec.type !== "scatter" || Number.isFinite(Number(row[spec.x]))),
    )
    .map((row) => ({
      ...row,
      [spec.y]: Number(row[spec.y]),
      ...(spec.type === "scatter" ? { [spec.x]: Number(row[spec.x]) } : {}),
    }));
}

export function resolveBarOrientation(spec, rows) {
  if (spec.orientation === "horizontal" || spec.orientation === "vertical") {
    return spec.orientation;
  }
  const labels = uniqueValues(rows, spec.x);
  const longestLabel = Math.max(0, ...labels.map((label) => label.length));
  return labels.length > 6 || longestLabel > 12 ? "horizontal" : "vertical";
}

export function normalizeChartSpec(spec, rows) {
  if (!spec || spec.type === "none") return spec;
  return {
    ...spec,
    orientation: spec.type === "bar" ? resolveBarOrientation(spec, rows) : undefined,
  };
}

export function horizontalBarLayout(rows, spec) {
  const labels = uniqueValues(rows, spec.x);
  const longestLabel = Math.max(0, ...labels.map((label) => label.length));
  const labelWidth = Math.min(
    BASE_LAYOUT.horizontalBarMaxLabelWidth,
    Math.max(150, longestLabel * 6.6 + 24),
  );
  return {
    width: BASE_LAYOUT.width,
    height: Math.max(
      BASE_LAYOUT.horizontalBarMinHeight,
      rows.length * BASE_LAYOUT.horizontalBarRowHeight + 64,
    ),
    margin: { top: 18, right: 34, bottom: 46, left: labelWidth },
  };
}

export function sortComparisonRows(rows, spec) {
  return [...rows].sort((left, right) => {
    const valueDifference = Number(right[spec.y]) - Number(left[spec.y]);
    if (valueDifference) return valueDifference;
    return String(left[spec.x] ?? "").localeCompare(String(right[spec.x] ?? ""));
  });
}

function colorEncoding(spec, rows, theme) {
  if (!spec.series || !rows.some((row) => row[spec.series] !== undefined)) {
    return { value: theme.series[0] };
  }
  const seriesValues = uniqueValues(rows, spec.series);
  return {
    field: spec.series,
    type: "nominal",
    scale: { range: theme.series },
    legend:
      seriesValues.length > 1
        ? {
            title: fieldLabel(spec.series),
            orient: "bottom",
            direction: "horizontal",
            symbolType: spec.type === "line" ? "stroke" : "circle",
          }
        : null,
  };
}

function tooltipFields(spec, { includeLabel = false } = {}) {
  const fields = [];
  if (includeLabel && spec.label) {
    fields.push({ field: spec.label, type: "nominal", title: fieldLabel(spec.label) });
  }
  if (spec.series && spec.series !== spec.label) {
    fields.push({ field: spec.series, type: "nominal", title: fieldLabel(spec.series) });
  }
  fields.push(
    {
      field: spec.x,
      type: spec.type === "scatter" ? "quantitative" : "ordinal",
      title: fieldTitle(spec, "x"),
      ...(spec.type === "scatter" ? { format: NUMBER_FORMAT } : {}),
    },
    {
      field: spec.y,
      type: "quantitative",
      title: fieldTitle(spec, "y"),
      format: NUMBER_FORMAT,
    },
  );
  return fields;
}

function baseConfig(theme) {
  const monoFont = "IBM Plex Mono, SFMono-Regular, Menlo, Consolas, monospace";
  return {
    background: null,
    view: { stroke: null },
    axis: {
      domainColor: theme.axis,
      gridColor: theme.grid,
      gridOpacity: 1,
      labelColor: theme.text,
      labelFont: monoFont,
      labelFontSize: 11,
      labelPadding: 8,
      tickColor: theme.axis,
      tickSize: 4,
      titleColor: theme.text,
      titleFont: monoFont,
      titleFontSize: 11,
      titleFontWeight: 400,
      titlePadding: 14,
    },
    legend: {
      labelColor: theme.text,
      labelFont: monoFont,
      labelFontSize: 11,
      symbolStrokeWidth: 3,
      titleColor: theme.text,
      titleFont: monoFont,
      titleFontSize: 11,
      titleFontWeight: 500,
    },
  };
}

function lineSpec(rows, spec, theme) {
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  return {
    height: BASE_LAYOUT.lineHeight,
    mark: {
      type: "line",
      point: {
        filled: true,
        size: 72,
        stroke: theme.pointOutline,
        strokeWidth: 2,
      },
      strokeCap: "square",
      strokeJoin: "miter",
      strokeWidth: 2.5,
    },
    encoding: {
      x: {
        field: spec.x,
        type: "ordinal",
        sort: xValues,
        axis: {
          title: fieldTitle(spec, "x"),
          grid: false,
          labelAngle: 0,
          labelOverlap: "parity",
        },
      },
      y: {
        field: spec.y,
        type: "quantitative",
        scale: { zero: false, nice: true },
        axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
      },
      color: colorEncoding(spec, rows, theme),
      tooltip: tooltipFields(spec),
    },
  };
}

function verticalBarSpec(rows, spec, theme) {
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  const encoding = {
    x: {
      field: spec.x,
      type: "nominal",
      sort: xValues,
      axis: {
        title: fieldTitle(spec, "x"),
        grid: false,
        labelAngle: 0,
        labelOverlap: "parity",
      },
    },
    y: {
      field: spec.y,
      type: "quantitative",
      scale: { zero: true, nice: true },
      axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec),
  };
  if (spec.series) encoding.xOffset = { field: spec.series };
  return {
    height: BASE_LAYOUT.verticalBarHeight,
    mark: { type: "bar", cornerRadiusEnd: 1 },
    encoding,
  };
}

function horizontalBarSpec(rows, spec, theme) {
  const encoding = {
    y: {
      field: spec.x,
      type: "nominal",
      sort: { field: spec.y, op: "sum", order: "descending" },
      axis: {
        title: fieldTitle(spec, "x"),
        grid: false,
        labelLimit: BASE_LAYOUT.horizontalBarMaxLabelWidth,
      },
    },
    x: {
      field: spec.y,
      type: "quantitative",
      scale: { zero: true, nice: true },
      axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec),
  };
  if (spec.series) encoding.yOffset = { field: spec.series };
  return {
    height: horizontalBarLayout(rows, spec).height,
    mark: { type: "bar", cornerRadiusEnd: 1 },
    encoding,
  };
}

function scatterSpec(rows, spec, theme) {
  return {
    height: 390,
    mark: {
      type: "point",
      filled: true,
      size: 96,
      stroke: theme.pointOutline,
      strokeWidth: 1.5,
    },
    encoding: {
      x: {
        field: spec.x,
        type: "quantitative",
        scale: { zero: false, nice: true },
        axis: { title: fieldTitle(spec, "x"), grid: true, tickCount: 5 },
      },
      y: {
        field: spec.y,
        type: "quantitative",
        scale: { zero: false, nice: true },
        axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
      },
      color: colorEncoding(spec, rows, theme),
      tooltip: tooltipFields(spec, { includeLabel: true }),
    },
  };
}

export function buildVegaLiteSpec(rows, chartSpec, theme = FALLBACK_THEME) {
  const spec = normalizeChartSpec(chartSpec, rows);
  if (!spec || spec.type === "none") return null;
  const cleanRows = numericRowsForSpec(rows, spec);
  if (!cleanRows.length) return null;
  const chartRows =
    spec.type === "bar" && spec.orientation === "horizontal"
      ? sortComparisonRows(cleanRows, spec)
      : cleanRows;

  const chart =
    spec.type === "line"
      ? lineSpec(chartRows, spec, theme)
      : spec.type === "scatter"
        ? scatterSpec(chartRows, spec, theme)
        : spec.orientation === "horizontal"
          ? horizontalBarSpec(chartRows, spec, theme)
          : verticalBarSpec(chartRows, spec, theme);

  return {
    $schema: VEGA_LITE_SCHEMA,
    description: spec.title || "Eurostat data chart",
    data: { values: chartRows },
    width: "container",
    autosize: { type: "fit", contains: "padding", resize: true },
    ...chart,
    config: baseConfig(theme),
  };
}

export async function renderVegaLiteChart(container, rows, chartSpec, embed = globalThis.vegaEmbed) {
  const loading = element("p", "chart-loading", "Rendering chart…");
  loading.setAttribute("role", "status");
  container.appendChild(loading);

  try {
    if (typeof embed !== "function") throw new Error("Vega-Embed did not load.");
    const spec = buildVegaLiteSpec(rows, chartSpec, chartTheme());
    if (!spec) throw new Error("The chart has no valid numeric observations.");
    const result = await embed(container, spec, {
      actions: false,
      defaultStyle: true,
      mode: "vega-lite",
      renderer: "svg",
      tooltip: {
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "light",
      },
    });
    if (!container.isConnected) {
      result.finalize();
      return null;
    }
    container.vegaFinalize = result.finalize;
    return result;
  } catch (error) {
    container.replaceChildren(
      element(
        "p",
        "chart-error",
        "The chart could not be rendered. The observations remain available in the table below.",
      ),
    );
    console.error("Unable to render Vega-Lite chart.", error);
    return null;
  } finally {
    loading.remove();
  }
}

export function finalizeChartViews(root) {
  root.querySelectorAll(".chart-view").forEach((view) => {
    if (typeof view.vegaFinalize === "function") view.vegaFinalize();
  });
}

export function createChartSection(result) {
  if (!result.chart || result.chart.type === "none" || !result.rows.length) return null;
  const spec = normalizeChartSpec(result.chart, result.rows);
  const rows = numericRowsForSpec(result.rows, spec);
  if (!rows.length) return null;

  const section = element("section", "result-section");
  const heading = element("div", "section-heading");
  const copy = element("div");
  const sectionTitle =
    spec.type === "line" ? "Trend" : spec.type === "scatter" ? "Relationship" : "Comparison";
  copy.appendChild(element("h2", "", sectionTitle));
  copy.appendChild(element("p", "", "Hover or focus a mark to inspect an observation"));
  heading.appendChild(copy);
  section.appendChild(heading);

  const wrap = element(
    "div",
    `chart-wrap chart-${spec.type} chart-${spec.orientation || "standard"}`,
  );
  const view = element("div", "chart-view");
  view.setAttribute("role", "img");
  view.setAttribute("aria-label", spec.title || "Eurostat data chart");
  wrap.appendChild(view);
  section.appendChild(wrap);
  void renderVegaLiteChart(view, rows, spec);
  return section;
}
