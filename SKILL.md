---
name: fetch-eurostat-data
description: Find relevant Eurostat datasets and fetch official Eurostat data for data questions about EU countries, regions, indicators, time series, population, economy, energy, trade, labor, prices, environment, agriculture, transport, and other Eurostat topics. Use when Codex needs to search the Eurostat database, inspect dataset dimensions and codes, call the Eurostat dissemination API, parse JSON-stat data, compare countries or periods, cite dataset codes, or answer a question using fresh Eurostat statistics.
---

# Fetch Eurostat Data

## Workflow

Use Eurostat as the authoritative source when the user asks for European official statistics or explicitly asks for Eurostat data.

1. Clarify the statistical concept, geography, time range, and unit before using tools if the ambiguity could change the answer. Broad concepts such as "innovation" require the user to choose a proxy such as patents, R&D expenditure, researchers, or an innovation-survey indicator.
2. Reuse compatible structured Eurostat rows already present in the conversation. Do not search, inspect, or fetch the same data again.
3. If the user supplied an exact dataset code, inspect it directly. Otherwise search for candidate datasets with `scripts/eurostat_api.py search "<topic>"`.
4. Inspect the most promising dataset with `scripts/eurostat_api.py dimensions <dataset_code>`.
5. Fetch a bounded slice with `scripts/eurostat_api.py fetch <dataset_code> --param dim=value --last-time-period N`.
6. Answer from the returned data. Name the dataset code, filters, units, geography, and latest period used. Show the relevant observations in a Markdown table as part of the user-facing response.

Prefer the smallest query that answers the question. Always filter high-cardinality dimensions such as `geo`, `time`, `unit`, `freq`, `sex`, `age`, `nace_r2`, `indic_*`, `siec`, `currency`, or `coicop` before fetching broad data.

Use at most two catalogue searches per requested measure. Do not repeat identical tool calls. If two searches do not identify a credible dataset, stop and ask the user to choose from the closest candidates. After a zero-row fetch or invalid filter, correct the filters using the inspected dimension codes instead of restarting dataset search.

## Quick Start

Run from the skill directory or pass the absolute script path:

```bash
python3 scripts/eurostat_api.py search "population by age country"
python3 scripts/eurostat_api.py dimensions demo_pjan
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

## Fetching Rules

Use the Eurostat Statistics API endpoint:

`https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset_code}`

Pass filters as repeated query parameters. Use dynamic time filters when appropriate:

- `--last-time-period 1` for the latest available observation;
- `--last-time-period 5` for recent trend comparisons;
- `--time 2020 --time 2021` for exact periods.

If the API returns too much data, narrow filters and retry. If an exact dataset cannot be found, explain the search terms tried and offer the closest candidates rather than inventing values.

## Answering

Include enough provenance for the user to reproduce the result:

- Eurostat dataset code and title when available;
- applied filters, especially units and geographies;
- latest extraction date if present in API metadata;
- any data gaps or flags returned by Eurostat.

Also include a compact Markdown table of the relevant returned observations. Prefer user-friendly columns such as geography, period, unit, indicator, category, value, and status/flag when present. Keep the table bounded to the rows needed to answer the question; if the result is too large, show the most relevant rows and explain how it was limited.

Do not treat Eurostat values as versioned historical database snapshots. Eurostat states that the database contains the latest dataset versions.

## Resources

- `scripts/eurostat_api.py`: Search Eurostat dataset metadata, inspect JSON-stat dimensions, and fetch flattened observations.
- `references/eurostat-api.md`: Endpoint notes, parameter patterns, and troubleshooting.
