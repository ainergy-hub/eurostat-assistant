import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVegaLiteSpec,
  horizontalBarLayout,
  normalizeChartSpec,
  resolveBarOrientation,
  sortComparisonRows,
} from "../static/chart.js";

const rows = [
  { product: "Food and live animals", value: 15 },
  { product: "Machinery and transport equipment", value: 80 },
  { product: "Mineral fuels, lubricants and related materials", value: 45 },
];
const barSpec = { type: "bar", x: "product", y: "value" };

test("explicit chart orientation wins over the readability heuristic", () => {
  assert.equal(resolveBarOrientation({ ...barSpec, orientation: "vertical" }, rows), "vertical");
});

test("long category labels default to horizontal bars for legacy results", () => {
  assert.equal(resolveBarOrientation(barSpec, rows), "horizontal");
  assert.equal(normalizeChartSpec(barSpec, rows).orientation, "horizontal");
});

test("short, sparse comparisons can retain vertical bars", () => {
  const shortRows = [
    { product: "France", value: 68 },
    { product: "Germany", value: 84 },
  ];
  assert.equal(resolveBarOrientation(barSpec, shortRows), "vertical");
});

test("scatter specifications pass through without a bar orientation", () => {
  const scatter = normalizeChartSpec(
    {
      type: "scatter",
      x: "population",
      y: "gdp",
      x_label: "Population (millions)",
      y_label: "GDP per capita (PPS)",
      series: "geo",
      label: "geo_label",
    },
    [{ population: 10, gdp: 20, geo: "DE" }],
  );
  assert.equal(scatter.type, "scatter");
  assert.equal(scatter.x, "population");
  assert.equal(scatter.y, "gdp");
  assert.equal(scatter.x_label, "Population (millions)");
  assert.equal(scatter.label, "geo_label");
  assert.equal(scatter.orientation, undefined);
});

test("horizontal comparisons are ordered by value and sized by row count", () => {
  const manyRows = Array.from({ length: 20 }, (_, index) => ({
    product: `Category ${index}`,
    value: index,
  }));
  assert.deepEqual(
    sortComparisonRows(rows, barSpec).map((row) => row.value),
    [80, 45, 15],
  );
  assert.ok(horizontalBarLayout(rows, barSpec).margin.left >= 150);
  assert.ok(horizontalBarLayout(manyRows, barSpec).height > 350);
});

test("line charts translate the public chart contract into Vega-Lite", () => {
  const spec = buildVegaLiteSpec(
    [
      { time_label: "2024", value: "12.5", geo_label: "France" },
      { time_label: "2023", value: 10, geo_label: "France" },
    ],
    {
      type: "line",
      x: "time_label",
      y: "value",
      series: "geo_label",
      title: "Population",
    },
  );

  assert.equal(spec.$schema, "https://vega.github.io/schema/vega-lite/v6.json");
  assert.equal(spec.mark.type, "line");
  assert.deepEqual(spec.encoding.x.sort, ["2023", "2024"]);
  assert.equal(spec.encoding.y.scale.zero, false);
  assert.equal(spec.encoding.color.field, "geo_label");
  assert.equal(spec.data.values[0].value, 12.5);
});

test("horizontal bars swap the categorical and quantitative axes", () => {
  const spec = buildVegaLiteSpec(rows, { ...barSpec, orientation: "horizontal" });

  assert.equal(spec.mark.type, "bar");
  assert.equal(spec.encoding.y.field, "product");
  assert.equal(spec.encoding.x.field, "value");
  assert.equal(spec.encoding.y.sort.order, "descending");
  assert.deepEqual(
    spec.data.values.map((row) => row.value),
    [80, 45, 15],
  );
});

test("scatter plots use quantitative axes and include point labels in tooltips", () => {
  const spec = buildVegaLiteSpec(
    [{ population: 84.4, gdp: 46.2, geo: "DE", geo_label: "Germany" }],
    {
      type: "scatter",
      x: "population",
      y: "gdp",
      series: "geo",
      label: "geo_label",
      x_label: "Population (millions)",
      y_label: "GDP per capita",
    },
  );

  assert.equal(spec.mark.type, "point");
  assert.equal(spec.encoding.x.type, "quantitative");
  assert.equal(spec.encoding.y.type, "quantitative");
  assert.equal(spec.encoding.tooltip[0].field, "geo_label");
  assert.equal(spec.encoding.x.axis.title, "Population (millions)");
});
