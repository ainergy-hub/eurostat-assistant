const VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json";
const NUMBER_FORMAT = ",.1~f";

const BASE_LAYOUT = Object.freeze({
  width: 920,
  lineHeight: 350,
  distributionHeight: 370,
  relationshipHeight: 390,
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

function numericFieldsForSpec(spec) {
  if (spec.type === "histogram") return [spec.x];
  if (spec.type === "heatmap") return [spec.color];
  if (spec.type === "scatter") return [spec.x, spec.y, spec.size].filter(Boolean);
  return [spec.y].filter(Boolean);
}

function numericRowsForSpec(rows, spec) {
  const numericFields = numericFieldsForSpec(spec);
  return rows
    .filter((row) => numericFields.every((field) => Number.isFinite(Number(row[field]))))
    .map((row) => {
      const normalized = { ...row };
      for (const field of numericFields) normalized[field] = Number(row[field]);
      return normalized;
    });
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
    purpose: spec.purpose || chartPurpose(spec.type, spec.stack),
    stack: spec.stack || "none",
    sort: spec.sort || "natural",
    trendline: spec.trendline || "none",
    labels: spec.labels || "hover",
    scale: spec.scale || "linear",
    zero_baseline: spec.zero_baseline ?? "auto",
    orientation:
      spec.type === "bar" || spec.type === "dot"
        ? resolveBarOrientation(spec, rows)
        : undefined,
  };
}

function chartPurpose(type, stack = "none") {
  if (type === "line") return "trend";
  if (type === "area") return stack === "none" ? "trend" : "composition";
  if (type === "bar") return stack === "none" ? "comparison" : "composition";
  if (type === "dot") return "comparison";
  if (type === "scatter" || type === "heatmap") return "relationship";
  if (type === "histogram" || type === "boxplot") return "distribution";
  return "comparison";
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

function comparisonOrder(spec, fallback = "descending") {
  if (spec.sort === "ascending") return "ascending";
  if (spec.sort === "descending") return "descending";
  return fallback;
}

function limitChartRows(rows, spec) {
  if (!Number.isInteger(spec.top_n) || spec.top_n < 1) return rows;
  if (!["bar", "dot", "heatmap"].includes(spec.type)) return rows;
  const valueField = spec.type === "heatmap" ? spec.color : spec.y;
  const totals = new Map();
  for (const row of rows) {
    const key = String(row[spec.x] ?? "");
    totals.set(key, (totals.get(key) || 0) + Number(row[valueField] || 0));
  }
  const direction = comparisonOrder(spec);
  const selected = [...totals]
    .sort((left, right) =>
      direction === "ascending" ? left[1] - right[1] : right[1] - left[1],
    )
    .slice(0, spec.top_n)
    .map(([key]) => key);
  const allowed = new Set(selected);
  return rows.filter((row) => allowed.has(String(row[spec.x] ?? "")));
}

function quantitativeScale(spec, defaultZero = false) {
  if (spec.scale === "log") return { type: "log", zero: false, nice: true };
  const zero = spec.zero_baseline === "auto" ? defaultZero : Boolean(spec.zero_baseline);
  return { type: "linear", zero, nice: true };
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

function chartWithLabels(height, mark, encoding, spec, options = {}) {
  if (spec.labels !== "always") return { height, mark, encoding };
  const horizontal = options.orientation === "horizontal";
  const labelField = options.labelField || spec.y;
  const textEncoding = {
    ...encoding,
    text: {
      field: labelField,
      type: options.labelType || "quantitative",
      ...(options.labelType === "nominal" ? {} : { format: NUMBER_FORMAT }),
    },
  };
  delete textEncoding.size;
  return {
    height,
    layer: [
      { mark, encoding },
      {
        mark: {
          type: "text",
          align: horizontal ? "left" : "center",
          baseline: horizontal ? "middle" : "bottom",
          dx: horizontal ? 6 : 0,
          dy: horizontal ? 0 : -7,
          fontSize: 10,
        },
        encoding: textEncoding,
      },
    ],
  };
}

function lineSpec(rows, spec, theme) {
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  return chartWithLabels(
    BASE_LAYOUT.lineHeight,
    {
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
    {
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
        scale: quantitativeScale(spec, false),
        axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
      },
      color: colorEncoding(spec, rows, theme),
      tooltip: tooltipFields(spec),
    },
    spec,
  );
}

function verticalBarSpec(rows, spec, theme) {
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  const stacked = spec.stack === "stacked" || spec.stack === "normalize";
  const encoding = {
    x: {
      field: spec.x,
      type: "nominal",
      sort:
        spec.sort === "natural"
          ? xValues
          : { field: spec.y, op: "sum", order: comparisonOrder(spec) },
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
      stack: stacked ? (spec.stack === "normalize" ? "normalize" : "zero") : null,
      scale: quantitativeScale(spec, true),
      axis: {
        title: fieldTitle(spec, "y"),
        grid: true,
        tickCount: 5,
        ...(spec.stack === "normalize" ? { format: ".0%" } : {}),
      },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec),
  };
  if (spec.series && !stacked) encoding.xOffset = { field: spec.series };
  return chartWithLabels(
    BASE_LAYOUT.verticalBarHeight,
    { type: "bar", cornerRadiusEnd: 1 },
    encoding,
    spec,
  );
}

function horizontalBarSpec(rows, spec, theme) {
  const stacked = spec.stack === "stacked" || spec.stack === "normalize";
  const encoding = {
    y: {
      field: spec.x,
      type: "nominal",
      sort: {
        field: spec.y,
        op: "sum",
        order: comparisonOrder(spec),
      },
      axis: {
        title: fieldTitle(spec, "x"),
        grid: false,
        labelLimit: BASE_LAYOUT.horizontalBarMaxLabelWidth,
      },
    },
    x: {
      field: spec.y,
      type: "quantitative",
      stack: stacked ? (spec.stack === "normalize" ? "normalize" : "zero") : null,
      scale: quantitativeScale(spec, true),
      axis: {
        title: fieldTitle(spec, "y"),
        grid: true,
        tickCount: 5,
        ...(spec.stack === "normalize" ? { format: ".0%" } : {}),
      },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec),
  };
  if (spec.series && !stacked) encoding.yOffset = { field: spec.series };
  return chartWithLabels(
    horizontalBarLayout(rows, spec).height,
    { type: "bar", cornerRadiusEnd: 1 },
    encoding,
    spec,
    { orientation: "horizontal" },
  );
}

function scatterSpec(rows, spec, theme) {
  const encoding = {
    x: {
      field: spec.x,
      type: "quantitative",
      scale: quantitativeScale(spec, false),
      axis: { title: fieldTitle(spec, "x"), grid: true, tickCount: 5 },
    },
    y: {
      field: spec.y,
      type: "quantitative",
      scale: quantitativeScale(spec, false),
      axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec, { includeLabel: true }),
  };
  if (spec.size) {
    encoding.size = {
      field: spec.size,
      type: "quantitative",
      scale: { range: [60, 520] },
      legend: { title: fieldLabel(spec.size), orient: "bottom" },
    };
  }
  const pointLayer = {
    mark: {
      type: "point",
      filled: true,
      size: 96,
      stroke: theme.pointOutline,
      strokeWidth: 1.5,
    },
    encoding,
  };
  const layers = [];
  if (spec.trendline === "linear") {
    layers.push({
      transform: [
        {
          regression: spec.y,
          on: spec.x,
          ...(spec.series ? { groupby: [spec.series] } : {}),
        },
      ],
      mark: { type: "line", strokeWidth: 2, opacity: 0.8 },
      encoding: {
        x: encoding.x,
        y: encoding.y,
        color: encoding.color,
      },
    });
  }
  layers.push(pointLayer);
  if (spec.labels === "always") {
    layers.push({
      mark: { type: "text", dy: -10, fontSize: 10 },
      encoding: {
        x: encoding.x,
        y: encoding.y,
        color: encoding.color,
        text: spec.label
          ? { field: spec.label, type: "nominal" }
          : { field: spec.y, type: "quantitative", format: NUMBER_FORMAT },
      },
    });
  }
  return {
    height: BASE_LAYOUT.relationshipHeight,
    ...(layers.length === 1 ? pointLayer : { layer: layers }),
  };
}

function areaSpec(rows, spec, theme) {
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  const stack =
    spec.stack === "normalize" ? "normalize" : spec.stack === "stacked" ? "zero" : null;
  return {
    height: BASE_LAYOUT.lineHeight,
    mark: { type: "area", opacity: spec.series ? 0.72 : 0.5, line: true },
    encoding: {
      x: {
        field: spec.x,
        type: "ordinal",
        sort: xValues,
        axis: { title: fieldTitle(spec, "x"), grid: false, labelAngle: 0 },
      },
      y: {
        field: spec.y,
        type: "quantitative",
        stack,
        scale: quantitativeScale(spec, stack !== null),
        axis: {
          title: fieldTitle(spec, "y"),
          grid: true,
          tickCount: 5,
          ...(spec.stack === "normalize" ? { format: ".0%" } : {}),
        },
      },
      color: colorEncoding(spec, rows, theme),
      tooltip: tooltipFields(spec),
    },
  };
}

function dotSpec(rows, spec, theme) {
  const horizontal = spec.orientation !== "vertical";
  const category = {
    field: spec.x,
    type: "nominal",
    sort:
      spec.sort === "natural"
        ? sortDimensionValues(uniqueValues(rows, spec.x))
        : { field: spec.y, op: "sum", order: comparisonOrder(spec) },
    axis: {
      title: fieldTitle(spec, "x"),
      grid: false,
      labelLimit: BASE_LAYOUT.horizontalBarMaxLabelWidth,
    },
  };
  const value = {
    field: spec.y,
    type: "quantitative",
    scale: quantitativeScale(spec, false),
    axis: { title: fieldTitle(spec, "y"), grid: true, tickCount: 5 },
  };
  const encoding = {
    x: horizontal ? value : category,
    y: horizontal ? category : value,
    color: colorEncoding(spec, rows, theme),
    tooltip: tooltipFields(spec),
  };
  if (spec.series) {
    encoding[horizontal ? "yOffset" : "xOffset"] = { field: spec.series };
  }
  return chartWithLabels(
    horizontal ? horizontalBarLayout(rows, spec).height : BASE_LAYOUT.verticalBarHeight,
    {
      type: "point",
      filled: true,
      size: 105,
      stroke: theme.pointOutline,
      strokeWidth: 1.5,
    },
    encoding,
    spec,
    { orientation: horizontal ? "horizontal" : "vertical" },
  );
}

function heatmapSpec(rows, spec) {
  return {
    height: Math.max(300, uniqueValues(rows, spec.y).length * 30 + 80),
    mark: { type: "rect", cornerRadius: 1 },
    encoding: {
      x: {
        field: spec.x,
        type: "ordinal",
        sort: sortDimensionValues(uniqueValues(rows, spec.x)),
        axis: { title: fieldTitle(spec, "x"), grid: false, labelAngle: 0 },
      },
      y: {
        field: spec.y,
        type: "nominal",
        sort: sortDimensionValues(uniqueValues(rows, spec.y)),
        axis: { title: fieldTitle(spec, "y"), grid: false },
      },
      color: {
        field: spec.color,
        type: "quantitative",
        scale: spec.scale === "log" ? { type: "log" } : { type: "linear" },
        legend: { title: fieldLabel(spec.color), orient: "bottom" },
      },
      tooltip: [
        { field: spec.x, type: "ordinal", title: fieldTitle(spec, "x") },
        { field: spec.y, type: "nominal", title: fieldTitle(spec, "y") },
        {
          field: spec.color,
          type: "quantitative",
          title: fieldLabel(spec.color),
          format: NUMBER_FORMAT,
        },
      ],
    },
  };
}

function histogramSpec(spec, theme) {
  return {
    height: BASE_LAYOUT.distributionHeight,
    mark: { type: "bar", color: theme.series[0], cornerRadiusEnd: 1 },
    encoding: {
      x: {
        field: spec.x,
        type: "quantitative",
        bin: { maxbins: 20 },
        scale: quantitativeScale(spec, false),
        axis: { title: fieldTitle(spec, "x"), grid: false },
      },
      y: {
        aggregate: "count",
        type: "quantitative",
        scale: { zero: true, nice: true },
        axis: { title: "Observations", grid: true, tickMinStep: 1 },
      },
      tooltip: [
        { field: spec.x, type: "quantitative", bin: true, title: fieldTitle(spec, "x") },
        { aggregate: "count", type: "quantitative", title: "Observations" },
      ],
    },
  };
}

function boxplotSpec(rows, spec, theme) {
  const encoding = {
    y: {
      field: spec.y,
      type: "quantitative",
      scale: quantitativeScale(spec, false),
      axis: { title: fieldTitle(spec, "y"), grid: true },
    },
    color: colorEncoding(spec, rows, theme),
    tooltip: [
      ...(spec.x
        ? [{ field: spec.x, type: "nominal", title: fieldTitle(spec, "x") }]
        : []),
      { field: spec.y, type: "quantitative", title: fieldTitle(spec, "y") },
    ],
  };
  if (spec.x) {
    encoding.x = {
      field: spec.x,
      type: "nominal",
      sort: sortDimensionValues(uniqueValues(rows, spec.x)),
      axis: { title: fieldTitle(spec, "x"), grid: false, labelAngle: 0 },
    };
  }
  return {
    height: BASE_LAYOUT.distributionHeight,
    mark: { type: "boxplot", extent: "min-max", size: 28 },
    encoding,
  };
}

export function buildVegaLiteSpec(rows, chartSpec, theme = FALLBACK_THEME) {
  const spec = normalizeChartSpec(chartSpec, rows);
  if (!spec || spec.type === "none") return null;
  const renderers = {
    line: lineSpec,
    area: areaSpec,
    bar: (chartRows, resolved, colors) =>
      resolved.orientation === "horizontal"
        ? horizontalBarSpec(chartRows, resolved, colors)
        : verticalBarSpec(chartRows, resolved, colors),
    dot: dotSpec,
    scatter: scatterSpec,
    heatmap: heatmapSpec,
    histogram: (_chartRows, resolved, colors) => histogramSpec(resolved, colors),
    boxplot: boxplotSpec,
  };
  if (!renderers[spec.type]) return null;
  const cleanRows = numericRowsForSpec(rows, spec);
  if (!cleanRows.length) return null;
  let chartRows = limitChartRows(cleanRows, spec);
  if (["bar", "dot"].includes(spec.type) && spec.orientation === "horizontal") {
    chartRows = sortComparisonRows(chartRows, spec);
    if (spec.sort === "ascending") chartRows.reverse();
  }
  const chart = renderers[spec.type](chartRows, spec, theme);

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
  const sectionTitle = {
    trend: "Trend",
    comparison: "Comparison",
    relationship: "Relationship",
    distribution: "Distribution",
    composition: "Composition",
    change: "Change",
  }[spec.purpose] || "Chart";
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
