# Chart selection

Choose the chart from the analytical relationship and the validated row shape. Prefer
`type=auto` with a `purpose` unless the user explicitly names a compatible chart.

| Purpose | Use | Required row shape |
|---|---|---|
| `trend` | line; area only for totals or accumulation | ordered period, numeric measure |
| `comparison` | bar for a few categories; dot for many categories | category, numeric measure |
| `relationship` | scatter for two numeric measures; heatmap for two categorical dimensions and a numeric intensity | compatible fields |
| `distribution` | histogram for one numeric measure; box plot for grouped distributions | repeated numeric observations |
| `composition` | stacked bar; normalized bar for percentage shares; stacked area for composition over time | category/period, series, numeric measure |
| `change` | line for several periods | ordered period, numeric measure |

After the relevant rows exist, call `configure_chart` to select or modify the chart. Use only fields
present in the loaded rows. Common modifications are `orientation`, `sort`, `top_n`, `stack`,
`trendline`, `labels`, `scale`, `zero_baseline`, `series`, `size`, and `label`.

Apply these guardrails:

- Keep line and area data unique at the period-plus-series grain.
- Use at most 12 visible series.
- Use a scatter plot only when both axes are numeric.
- Use a heatmap only when `x` and `y` are distinct dimensions and `color` is numeric.
- Use `stack=normalize` only for shares or composition questions.
- Keep bars on a zero baseline.
- Request a log scale only for strictly positive values.
- Add a linear trendline only to a scatter plot.
- Prefer hover labels; use always-visible labels only when the chart remains readable.
- Do not automatically request pie, donut, radar, dual-axis, or geographic charts.
