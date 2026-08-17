---
name: fetch-eurostat-data
description: Find relevant Eurostat datasets and fetch official Eurostat data for data questions about EU countries, regions, indicators, time series, population, economy, energy, trade, labor, prices, environment, agriculture, transport, and other Eurostat topics. Use when Codex needs to search the Eurostat database, inspect dataset dimensions and codes, call the Eurostat dissemination API, parse JSON-stat data, compare countries or periods, cite dataset codes, or answer a question using fresh Eurostat statistics.
---

# Fetch Eurostat Data

## Workflow

Use Eurostat as the authoritative source when the user asks for European official statistics or explicitly asks for Eurostat data.

1. Reuse compatible structured Eurostat rows already present in the conversation. Do not search, inspect, or fetch the same data again.
2. Identify the requested statistical concept, geography, time range, unit, and comparison grain. Separate details discoverable from Eurostat from preferences only the user can choose. For a relationship between two measures with no geography or period, default to a cross-sectional comparison of the individual countries shared by both datasets in their latest common year. Exclude supranational aggregates, state this reversible assumption, and do not pause to ask for geography or time.
3. Perform bounded discovery before asking a clarification question. If the user supplied an exact dataset code, inspect it directly without a catalogue search. Otherwise run at most one catalogue search per requested measure and inspect the best credible candidate for each measure; inspect a second candidate only when the first is genuinely ambiguous. Dimension inspection is metadata-first: the helper reads SDMX structure, codelists, and available-position constraints without requesting observations, then uses a one-period Statistics API inspection only as a compatibility fallback. Pass requested region, unit, product, and indicator labels as dimension matches so codes outside the samples are discovered rather than guessed. Do not fetch observations for competing interpretations.
4. After discovery, continue when one candidate clearly matches. State and proceed with a reasonable reversible assumption when the remaining ambiguity is minor. Ask one focused question when candidates represent materially different concepts, units, populations, or geographic grains.
5. Ground clarification questions in the discovery: name the search performed, candidate dataset titles and codes, the relevant differences, and a recommended option when one is a better match.
6. After the measure is resolved, fetch a bounded slice with `scripts/eurostat_api.py fetch <dataset_code> --param dim=value --last-time-period N`. Always include an explicit time selection or `last_time_period`; the host rejects unbounded time queries and data cubes above its configured cell and response-size limits.
7. Answer from the returned data. Name the dataset code, filters, units, geography, and latest period used. Show the relevant observations in a Markdown table as part of the user-facing response.
8. When a visualization is requested or a clean multi-period trend materially improves the answer, choose it from the analytical relationship and the validated row shape. Read `references/chart-selection.md` for the chart matrix and guardrails. Do not automatically chart single-period, matrix, or high-dimensional tables. Reuse loaded rows for chart-only follow-ups instead of fetching again.
9. In hosts that expose `publish_result`, every successful fetch receives a result ID. One successful fetch can be published automatically. After multiple successful fetches, publish the supporting result ID. To re-chart reusable conversation rows, publish `context` with a chart. To pair two measures, publish both result IDs with shared join keys and optional chart settings. Previous conversation data is reasoning context, not a result to republish unless the user asks to reuse or re-chart it.

Prefer the smallest query that answers the question. Always filter high-cardinality dimensions such as `geo`, `time`, `unit`, `freq`, `sex`, `age`, `nace_r2`, `indic_*`, `siec`, `currency`, or `coicop` before fetching broad data.

Use at most two catalogue searches total per request and at most one per requested measure. Do not repeat identical tool calls or reformulate a search after its result contains a credible dataset. If the bounded searches do not identify a credible dataset, stop and ask the user to choose from the closest candidates. After a zero-row fetch or invalid filter, correct the filters using the inspected dimension codes instead of restarting dataset search.

## Quick Start

Run from the skill directory or pass the absolute script path:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan --match Germany --match France
python3 scripts/eurostat_api.py fetch demo_pjan --param geo=DE --param sex=T --param age=TOTAL --last-time-period 5
```

The script uses only the Python standard library. It emits JSON for `search` and `dimensions`, and CSV for `fetch` by default.

## Dataset Selection

Search results are only candidates. Choose datasets by matching:

- title and dataset code;
- unit and frequency;
- available dimensions and dimension labels;
- whether the table is country-level, regional, annual, quarterly, monthly, or detailed by category.

If several datasets fit, inspect dimensions for each before fetching. If a question needs a concept definition, read `references/eurostat-api.md`.

### Multi-measure relationship questions

For questions asking for the relationship between two measures:

1. Decompose the request into two independently measurable concepts. Decide whether wording such
   as “X in Y” means a share, amount, rate, or intensity from context and units.
2. Search once for each concept. Search for the statistical family and denominator, not only the
   user's literal wording. Eurostat table titles often name a family such as fuels, products,
   activities, or indicators while the requested numerator is a dimension category inside it.
   For a requested “share of X in Y”, include terms for *share*, the parent category of X, and Y.
3. Review the complete bounded candidate list. Do not reject a credible family table because its
   title omits the requested category. Inspect it with the requested numerator, denominator, unit,
   geography, and aggregate labels as dimension matches. Use at most two inspections per measure.
4. Resolve both measures to one observation per intended join key. Apply the same individual
   geographies and the same explicit period to both fetches, exclude aggregate geographies from a
   country-level comparison, and use the latest common year when no period was requested.
5. Fetch each resolved measure once, then publish the two result IDs joined on the shared keys.
   Use a scatter plot for two numeric measures and describe association rather than causation.

The complete path is bounded to two searches, four inspections, two fetches, and one publication.
If that budget cannot resolve both measures, ask one focused clarification question instead of
starting another discovery loop.

Dimension samples are intentionally bounded. Use repeatable `--match` terms (or the
`inspect_dimensions.matches` tool argument) to search complete category lists for requested labels,
including misspellings and diacritics. For generic solar electricity generation, use solar
photovoltaic when no aggregate solar-electricity category exists, state that assumption, and do not
substitute solar thermal.

## Fetching Rules

Use the Eurostat Statistics API endpoint:

`https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset_code}`

Inspect dataset structure without observations through Eurostat's SDMX metadata endpoints. The
helper requests the dataset dataflow with referenced structure and codelists, plus its Data
Constraint containing available positions. This path must be attempted before the Statistics API
fallback so a large observation cube cannot block dimension-code discovery.

Pass filters as repeated query parameters. Use dynamic time filters when appropriate:

- `--last-time-period 1` for the latest available observation;
- `--last-time-period 5` for recent trend comparisons;
- `--time 2020 --time 2021` for exact periods.

If the API returns too much data, narrow filters and retry. If an exact dataset cannot be found, explain the search terms tried and offer the closest candidates rather than inventing values.

The runtime limits in `agent_limits.json` are authoritative for the web agent. Treat a rejected cell estimate, response-size limit, or missing time bound as a request to narrow the existing query, not to restart dataset discovery.

## Answering

Include enough provenance for the user to reproduce the result:

- Eurostat dataset code and title when available;
- applied filters, especially units and geographies;
- latest extraction date if present in API metadata;
- any data gaps or flags returned by Eurostat.

Render every dataset code in user-facing prose as a Markdown link to its Eurostat Data Browser
page. Use this exact pattern:

`[demo_pjan](https://ec.europa.eu/eurostat/databrowser/view/demo_pjan/default/table?lang=en)`

Replace `demo_pjan` in both the label and URL with the actual dataset code. Apply this to selected
datasets, candidate datasets in clarification questions, and source notes. Do not link dimension or
category codes as though they were datasets.

When the host does not render structured observations, include a compact Markdown table of the
relevant returned rows. Prefer user-friendly columns such as geography, period, unit, indicator,
category, value, and status/flag when present. Keep the table bounded to the rows needed to answer
the question. In hosts that expose `publish_result` and render its structured rows, do not duplicate
observation values in a Markdown table or transcribe values from truncated model-visible tool
output; the published structured result is the authoritative table.

When an answer uses values from multiple datasets, preserve and show one bounded table for every
dataset used. Let the host render the source tables when it supports structured or expandable
content. Otherwise put each Markdown table in its own section, label it with the dataset code and
title, and do not substitute only a joined or last-fetched table for the underlying source tables.

Do not treat Eurostat values as versioned historical database snapshots. Eurostat states that the database contains the latest dataset versions.

## Resources

- `scripts/eurostat_api.py`: Search Eurostat dataset metadata, inspect JSON-stat dimensions, and fetch flattened observations.
- `references/eurostat-api.md`: Endpoint notes, parameter patterns, and troubleshooting.
- `references/chart-selection.md`: Supported analytical purposes, chart choices, modifications, and validation guardrails.
