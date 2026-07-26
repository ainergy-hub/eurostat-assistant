const SVG_NS = "http://www.w3.org/2000/svg";
const COLORS = ["#ff4f00", "#25764c", "#545c78", "#a66b1f", "#7b557c", "#357a78"];
const NUMBER_FORMAT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

const BASE_LAYOUT = Object.freeze({
  width: 920,
  lineHeight: 350,
  verticalBarHeight: 350,
  horizontalBarMinHeight: 350,
  horizontalBarRowHeight: 32,
  horizontalBarMaxLabelWidth: 340,
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function addText(svg, text, x, y, attributes = {}) {
  const node = svgElement("text", {
    x,
    y,
    fill: "#6b6b65",
    "font-size": 11,
    "font-family": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    ...attributes,
  });
  node.textContent = text;
  svg.appendChild(node);
  return node;
}

function fittedLabel(label, availableWidth) {
  const maximumCharacters = Math.max(12, Math.floor(availableWidth / 6.6));
  if (label.length <= maximumCharacters) return label;
  return `${label.slice(0, maximumCharacters - 1).trimEnd()}…`;
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

function numericRowsForSpec(rows, spec) {
  return rows.filter((row) => Number.isFinite(Number(row[spec.y])));
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

function numericDomain(values, includeZero) {
  const observedMin = Math.min(...values);
  const observedMax = Math.max(...values);
  const min = includeZero ? Math.min(0, observedMin) : observedMin > 0 ? observedMin * 0.96 : observedMin;
  const max = includeZero ? Math.max(0, observedMax) : observedMax;
  return { min, max, range: max - min || Math.max(Math.abs(max), 1) };
}

function paddedNumericDomain(values) {
  const observedMin = Math.min(...values);
  const observedMax = Math.max(...values);
  const observedRange = observedMax - observedMin;
  const padding = (observedRange || Math.max(Math.abs(observedMax), 1)) * 0.06;
  const min = observedMin - padding;
  const max = observedMax + padding;
  return { min, max, range: max - min };
}

function createTooltip(wrap) {
  const tooltip = element("div", "chart-tooltip");
  tooltip.hidden = true;
  wrap.appendChild(tooltip);

  function show(event, title, detail) {
    tooltip.replaceChildren(
      element("strong", "", title),
      document.createElement("br"),
      document.createTextNode(detail),
    );
    tooltip.hidden = false;
    const bounds = wrap.getBoundingClientRect();
    tooltip.style.left = `${event.clientX - bounds.left + wrap.scrollLeft}px`;
    tooltip.style.top = `${event.clientY - bounds.top + wrap.scrollTop}px`;
  }

  return {
    show,
    hide() {
      tooltip.hidden = true;
    },
  };
}

function bindMarkTooltip(mark, tooltip, wrap, title, detail) {
  mark.addEventListener("pointerenter", (event) => tooltip.show(event, title, detail));
  mark.addEventListener("pointerleave", tooltip.hide);
  mark.addEventListener("focus", (event) => {
    const markBounds = event.target.getBoundingClientRect();
    const wrapBounds = wrap.getBoundingClientRect();
    tooltip.show(
      {
        clientX: markBounds.left + markBounds.width / 2,
        clientY: Math.max(markBounds.top, wrapBounds.top + 24),
      },
      title,
      detail,
    );
  });
  mark.addEventListener("blur", tooltip.hide);
}

function addLegend(section, seriesValues) {
  if (seriesValues.length <= 1) return;
  const legend = element("div", "chart-legend");
  seriesValues.forEach((seriesName, index) => {
    const item = element("span", "legend-item");
    const swatch = element("span", "legend-swatch");
    swatch.style.background = COLORS[index % COLORS.length];
    item.append(swatch, document.createTextNode(seriesName));
    legend.appendChild(item);
  });
  section.appendChild(legend);
}

function renderLineChart({ svg, wrap, tooltip, rows, spec, section }) {
  const width = BASE_LAYOUT.width;
  const height = BASE_LAYOUT.lineHeight;
  const margin = { top: 18, right: 24, bottom: 58, left: 68 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  const domain = numericDomain(rows.map((row) => Number(row[spec.y])), false);
  const xPoint = (value) =>
    margin.left +
    (xValues.length === 1
      ? plotWidth / 2
      : (xValues.indexOf(String(value)) / (xValues.length - 1)) * plotWidth);
  const yPoint = (value) =>
    margin.top + plotHeight - ((Number(value) - domain.min) / domain.range) * plotHeight;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  for (let index = 0; index <= 4; index += 1) {
    const value = domain.min + (domain.range * index) / 4;
    const y = yPoint(value);
    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: y,
        y2: y,
        stroke: "#e5e5e0",
        "stroke-width": 1,
      }),
    );
    addText(svg, NUMBER_FORMAT.format(value), margin.left - 10, y + 4, { "text-anchor": "end" });
  }

  const tickStep = Math.max(1, Math.ceil(xValues.length / 8));
  xValues.forEach((value, index) => {
    if (index % tickStep !== 0 && index !== xValues.length - 1) return;
    addText(svg, value, xPoint(value), height - margin.bottom + 24, { "text-anchor": "middle" });
  });
  svg.appendChild(
    svgElement("line", {
      x1: margin.left,
      x2: width - margin.right,
      y1: margin.top + plotHeight,
      y2: margin.top + plotHeight,
      stroke: "#a8a8a0",
    }),
  );

  const seriesField = spec.series;
  const seriesValues = seriesField ? uniqueValues(rows, seriesField) : ["Value"];
  seriesValues.forEach((seriesName, seriesIndex) => {
    const seriesRows = rows
      .filter((row) => !seriesField || String(row[seriesField] ?? "Series") === seriesName)
      .sort((left, right) => xValues.indexOf(String(left[spec.x])) - xValues.indexOf(String(right[spec.x])));
    const color = COLORS[seriesIndex % COLORS.length];
    const path = seriesRows
      .map((row, index) => `${index ? "L" : "M"} ${xPoint(row[spec.x])} ${yPoint(row[spec.y])}`)
      .join(" ");
    svg.appendChild(
      svgElement("path", {
        d: path,
        fill: "none",
        stroke: color,
        "stroke-width": 2.5,
        "stroke-linecap": "square",
        "stroke-linejoin": "miter",
      }),
    );
    seriesRows.forEach((row) => {
      const point = svgElement("circle", {
        cx: xPoint(row[spec.x]),
        cy: yPoint(row[spec.y]),
        r: 4,
        fill: color,
        stroke: "#fbfbf6",
        "stroke-width": 2,
        tabindex: 0,
        "aria-label": `${seriesName}, ${row[spec.x]}, ${NUMBER_FORMAT.format(Number(row[spec.y]))}`,
      });
      bindMarkTooltip(
        point,
        tooltip,
        wrap,
        seriesName,
        `${row[spec.x]} · ${NUMBER_FORMAT.format(Number(row[spec.y]))}`,
      );
      svg.appendChild(point);
    });
  });
  addLegend(section, seriesValues);
}

function renderVerticalBarChart({ svg, wrap, tooltip, rows, spec }) {
  const width = BASE_LAYOUT.width;
  const height = BASE_LAYOUT.verticalBarHeight;
  const margin = { top: 18, right: 24, bottom: 58, left: 68 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xValues = sortDimensionValues(uniqueValues(rows, spec.x));
  const domain = numericDomain(rows.map((row) => Number(row[spec.y])), true);
  const band = plotWidth / Math.max(xValues.length, 1);
  const xPoint = (value) => margin.left + (xValues.indexOf(String(value)) + 0.5) * band;
  const yPoint = (value) =>
    margin.top + plotHeight - ((Number(value) - domain.min) / domain.range) * plotHeight;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  for (let index = 0; index <= 4; index += 1) {
    const value = domain.min + (domain.range * index) / 4;
    const y = yPoint(value);
    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: y,
        y2: y,
        stroke: "#e5e5e0",
        "stroke-width": 1,
      }),
    );
    addText(svg, NUMBER_FORMAT.format(value), margin.left - 10, y + 4, { "text-anchor": "end" });
  }
  const tickStep = Math.max(1, Math.ceil(xValues.length / 8));
  xValues.forEach((value, index) => {
    if (index % tickStep !== 0 && index !== xValues.length - 1) return;
    addText(svg, value, xPoint(value), height - margin.bottom + 24, { "text-anchor": "middle" });
  });

  const zero = yPoint(0);
  svg.appendChild(
    svgElement("line", {
      x1: margin.left,
      x2: width - margin.right,
      y1: zero,
      y2: zero,
      stroke: "#a8a8a0",
    }),
  );
  const barWidth = Math.max(8, Math.min(62, band * 0.62));
  rows.forEach((row) => {
    const value = Number(row[spec.y]);
    const valueY = yPoint(value);
    const label = String(row[spec.x] ?? "");
    const bar = svgElement("rect", {
      x: xPoint(label) - barWidth / 2,
      y: Math.min(valueY, zero),
      width: barWidth,
      height: Math.max(1, Math.abs(zero - valueY)),
      fill: COLORS[0],
      tabindex: 0,
      "aria-label": `${label}, ${NUMBER_FORMAT.format(value)}`,
    });
    bindMarkTooltip(bar, tooltip, wrap, label, NUMBER_FORMAT.format(value));
    svg.appendChild(bar);
  });
}

function renderHorizontalBarChart({ svg, wrap, tooltip, rows, spec }) {
  const sortedRows = sortComparisonRows(rows, spec);
  const layout = horizontalBarLayout(sortedRows, spec);
  const { width, height, margin } = layout;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const domain = numericDomain(sortedRows.map((row) => Number(row[spec.y])), true);
  const xPoint = (value) => margin.left + ((Number(value) - domain.min) / domain.range) * plotWidth;
  const band = plotHeight / Math.max(sortedRows.length, 1);
  const barHeight = Math.min(22, band * 0.68);

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  for (let index = 0; index <= 4; index += 1) {
    const value = domain.min + (domain.range * index) / 4;
    const x = xPoint(value);
    svg.appendChild(
      svgElement("line", {
        x1: x,
        x2: x,
        y1: margin.top,
        y2: height - margin.bottom,
        stroke: "#e5e5e0",
        "stroke-width": 1,
      }),
    );
    addText(svg, NUMBER_FORMAT.format(value), x, height - margin.bottom + 24, { "text-anchor": "middle" });
  }

  const zero = xPoint(0);
  svg.appendChild(
    svgElement("line", {
      x1: zero,
      x2: zero,
      y1: margin.top,
      y2: height - margin.bottom,
      stroke: "#a8a8a0",
    }),
  );

  sortedRows.forEach((row, index) => {
    const value = Number(row[spec.y]);
    const valueX = xPoint(value);
    const centerY = margin.top + (index + 0.5) * band;
    const label = String(row[spec.x] ?? "");
    const labelNode = addText(
      svg,
      fittedLabel(label, margin.left - 28),
      margin.left - 12,
      centerY + 4,
      { "text-anchor": "end" },
    );
    labelNode.appendChild(svgElement("title"));
    labelNode.lastChild.textContent = label;
    const bar = svgElement("rect", {
      x: Math.min(valueX, zero),
      y: centerY - barHeight / 2,
      width: Math.max(1, Math.abs(valueX - zero)),
      height: barHeight,
      fill: COLORS[0],
      tabindex: 0,
      "aria-label": `${label}, ${NUMBER_FORMAT.format(value)}`,
    });
    bindMarkTooltip(bar, tooltip, wrap, label, NUMBER_FORMAT.format(value));
    svg.appendChild(bar);
  });
}

function renderScatterChart({ svg, wrap, tooltip, rows, spec, section }) {
  const width = BASE_LAYOUT.width;
  const height = 390;
  const margin = { top: 24, right: 32, bottom: 62, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xDomain = paddedNumericDomain(rows.map((row) => Number(row[spec.x])));
  const yDomain = paddedNumericDomain(rows.map((row) => Number(row[spec.y])));
  const xPoint = (value) => margin.left + ((Number(value) - xDomain.min) / xDomain.range) * plotWidth;
  const yPoint = (value) =>
    margin.top + plotHeight - ((Number(value) - yDomain.min) / yDomain.range) * plotHeight;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  for (let index = 0; index <= 4; index += 1) {
    const xValue = xDomain.min + (xDomain.range * index) / 4;
    const x = xPoint(xValue);
    svg.appendChild(
      svgElement("line", {
        x1: x,
        x2: x,
        y1: margin.top,
        y2: height - margin.bottom,
        stroke: "#e5e5e0",
        "stroke-width": 1,
      }),
    );
    addText(svg, NUMBER_FORMAT.format(xValue), x, height - margin.bottom + 25, {
      "text-anchor": "middle",
    });

    const yValue = yDomain.min + (yDomain.range * index) / 4;
    const y = yPoint(yValue);
    svg.appendChild(
      svgElement("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: y,
        y2: y,
        stroke: "#e5e5e0",
        "stroke-width": 1,
      }),
    );
    addText(svg, NUMBER_FORMAT.format(yValue), margin.left - 10, y + 4, {
      "text-anchor": "end",
    });
  }

  const xLabel = fieldLabel(spec.x);
  const yLabel = fieldLabel(spec.y);
  addText(svg, xLabel, margin.left + plotWidth / 2, height - 9, { "text-anchor": "middle" });
  addText(svg, yLabel, 16, margin.top + plotHeight / 2, {
    "text-anchor": "middle",
    transform: `rotate(-90 16 ${margin.top + plotHeight / 2})`,
  });

  const seriesField = spec.series;
  const seriesValues = seriesField ? uniqueValues(rows, seriesField) : ["Observations"];
  rows.forEach((row) => {
    const seriesName = seriesField ? String(row[seriesField] ?? "Series") : "Observation";
    const seriesIndex = Math.max(0, seriesValues.indexOf(seriesName));
    const xValue = Number(row[spec.x]);
    const yValue = Number(row[spec.y]);
    const point = svgElement("circle", {
      cx: xPoint(xValue),
      cy: yPoint(yValue),
      r: 5,
      fill: COLORS[seriesIndex % COLORS.length],
      stroke: "#fbfbf6",
      "stroke-width": 1.5,
      tabindex: 0,
      "aria-label": `${seriesName}, ${xLabel} ${NUMBER_FORMAT.format(xValue)}, ${yLabel} ${NUMBER_FORMAT.format(yValue)}`,
    });
    bindMarkTooltip(
      point,
      tooltip,
      wrap,
      seriesName,
      `${xLabel}: ${NUMBER_FORMAT.format(xValue)} · ${yLabel}: ${NUMBER_FORMAT.format(yValue)}`,
    );
    svg.appendChild(point);
  });
  addLegend(section, seriesValues);
}

const RENDERERS = Object.freeze({
  line: renderLineChart,
  "bar:horizontal": renderHorizontalBarChart,
  "bar:vertical": renderVerticalBarChart,
  scatter: renderScatterChart,
});

export function createChartSection(result) {
  if (!result.chart || result.chart.type === "none" || !result.rows.length) return null;
  const spec = normalizeChartSpec(result.chart, result.rows);
  const rows = numericRowsForSpec(result.rows, spec);
  if (!rows.length) return null;

  const section = element("section", "result-section");
  const heading = element("div", "section-heading");
  const copy = element("div");
  const sectionTitle = spec.type === "line" ? "Trend" : spec.type === "scatter" ? "Relationship" : "Comparison";
  copy.appendChild(element("h2", "", sectionTitle));
  copy.appendChild(element("p", "", "Hover or focus a mark to inspect an observation"));
  heading.appendChild(copy);
  section.appendChild(heading);

  const wrap = element("div", `chart-wrap chart-${spec.type} chart-${spec.orientation || "standard"}`);
  const svg = svgElement("svg", {
    role: "img",
    "aria-label": spec.title || "Eurostat data chart",
  });
  wrap.appendChild(svg);
  const tooltip = createTooltip(wrap);
  section.appendChild(wrap);

  const rendererKey = spec.type === "bar" ? `${spec.type}:${spec.orientation}` : spec.type;
  const renderer = RENDERERS[rendererKey];
  if (!renderer) return null;
  renderer({ svg, wrap, tooltip, rows, spec, section });
  return section;
}
