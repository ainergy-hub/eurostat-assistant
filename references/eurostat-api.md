# Eurostat API Notes

## Current Endpoints

Primary Statistics API:

`https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset_code}`

Metadata-first dimension inspection:

`https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/dataflow/ESTAT/{DATASET}/1.0?references=descendants&detail=referencepartial&compress=false`

Available dimension positions:

`https://ec.europa.eu/eurostat/api/dissemination/sdmx/3.0/structure/dataconstraint/ESTAT/{DATASET}/1.0?compress=false`

Dataset metadata / table of contents:

`https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt?lang=en`

Useful documentation:

- Eurostat Statistics API introduction: `https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction`
- Eurostat Statistics API getting started: `https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started/api`
- Eurostat detailed Statistics API guidelines: `https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-detailed-guidelines/api-statistics`
- Eurostat Query Builder: `https://ec.europa.eu/eurostat/web/query-builder`

The Statistics API returns JSON-stat 2.0. It is public and does not require an API key.

## Query Parameters

Common parameters:

- `format=JSON`
- `lang=en`
- `lastTimePeriod=N`
- `time=YYYY` or repeated `time` values
- dimension filters such as `geo=DE`, `unit=PC`, `freq=A`, `sex=T`, `age=TOTAL`

Use repeated parameters for multiple values of the same dimension. Example:

`...?format=JSON&lang=en&geo=DE&geo=FR&lastTimePeriod=3`

Dimension names are dataset-specific. Inspect dimensions before assuming filters.

## JSON-stat Parsing

The response usually contains:

- `id`: ordered dimension ids;
- `size`: cardinality for each dimension;
- `dimension.<id>.category.index`: code-to-position mapping;
- `dimension.<id>.category.label`: code-to-label mapping;
- `value`: dense list or sparse object keyed by flat observation index;
- `status`: optional observation flags.

Flatten by converting each flat index into one coordinate per dimension using row-major JSON-stat order.

## Practical Heuristics

Search broadly first, then inspect. Eurostat dataset names can use domain-specific abbreviations.

Prefer dynamic recent-period queries for current-answer prompts. Use exact `time` filters for historical questions.

For country comparisons, use ISO-like Eurostat `geo` codes (`DE`, `FR`, `IT`, `EU27_2020`). Regional data uses NUTS codes and may require `geoLevel` or exact region codes.

For large dimensions, fetch only the requested unit/category/time/geography. Broad unfiltered requests may fail or be too large to parse usefully.

Dimension inspection must not depend on an observation request. Read the SDMX dataflow, DSD,
referenced codelists, and Data Constraint first. Use the one-period Statistics API inspector only
when structural metadata is unavailable or malformed. A failure of a broad observation request
does not imply that dataset metadata is inaccessible.

If a query returns no observations, inspect dimension labels and try alternative unit or indicator codes before concluding no data exists.
