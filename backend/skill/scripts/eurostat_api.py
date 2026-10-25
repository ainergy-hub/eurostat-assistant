#!/usr/bin/env python3
"""Small Eurostat Statistics API helper for Codex skills.

Commands:
  search "query terms"
  dimensions DATASET
  fetch DATASET --param geo=DE --last-time-period 5
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


BASE = "https://ec.europa.eu/eurostat/api/dissemination"
TOC_URL = f"{BASE}/catalogue/toc/txt?lang=en"
DATA_URL = f"{BASE}/statistics/1.0/data"
SDMX_DATAFLOW_URL = f"{BASE}/sdmx/2.1/dataflow"
SDMX_CONSTRAINT_URL = f"{BASE}/sdmx/3.0/structure/dataconstraint"
LIMITS_PATH = Path(__file__).resolve().parent / "agent_limits.json"
if not LIMITS_PATH.exists():
    LIMITS_PATH = Path(__file__).resolve().parent.parent / "agent_limits.json"
LIMITS = json.loads(LIMITS_PATH.read_text(encoding="utf-8"))
MAX_RESPONSE_BYTES = int(LIMITS["max_eurostat_response_bytes"])
MAX_ESTIMATED_CELLS = int(LIMITS["max_estimated_cells"])
MAX_TIME_PERIODS = int(LIMITS["max_time_periods"])
SEARCH_STOP_WORDS = {
    "a",
    "across",
    "all",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "per",
    "the",
    "to",
    "total",
    "with",
}
SEARCH_MODIFIER_WORDS = {
    "annual",
    "capita",
    "country",
    "inhabitant",
    "level",
    "million",
    "monthly",
    "quarterly",
    "region",
}
DIMENSION_MATCH_TOKEN_ALIASES = {
    "manufactured": "manufacture",
    "manufacturer": "manufacture",
    "manufacturers": "manufacture",
    "manufacturing": "manufacture",
}
DIMENSION_MATCH_QUERY_EXPANSIONS = {
    "agriculture": "crop animal production hunting",
    "agricultural": "crop animal production hunting",
}


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "codex-eurostat-skill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            content_length = response.headers.get("Content-Length")
            try:
                declared_bytes = int(content_length) if content_length else None
            except ValueError:
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > MAX_RESPONSE_BYTES:
                raise SystemExit(
                    "Eurostat response is too large "
                    f"({declared_bytes} bytes; limit {MAX_RESPONSE_BYTES}). Narrow the filters."
                )
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise SystemExit(
                    "Eurostat response exceeded the "
                    f"{MAX_RESPONSE_BYTES}-byte limit. Narrow the filters."
                )
            return body.decode("utf-8-sig")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} for {url}\n{detail[:1000]}") from exc


def get_json(url: str) -> dict[str, Any]:
    return json.loads(get_text(url))


def parse_toc(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(reader, None)
    if not header:
        return rows
    normalized = [h.strip().lower().replace(" ", "_") for h in header]
    for raw in reader:
        if not raw or len(raw) < 2:
            continue
        item = {normalized[i]: raw[i].strip() for i in range(min(len(normalized), len(raw)))}
        code = item.get("code") or item.get("dataset_code") or item.get("data_code") or ""
        title = (item.get("title") or item.get("label") or item.get("description") or "").strip()
        if code and title:
            rows.append(
                {
                    "code": code,
                    "title": title,
                    "type": item.get("type", ""),
                    "last_update": item.get("last_update_of_data", item.get("last_update", "")),
                    "data_start": item.get("data_start", ""),
                    "data_end": item.get("data_end", ""),
                }
            )
    return rows


def _stem_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(value: str) -> list[str]:
    return [
        _stem_token(token)
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in SEARCH_STOP_WORDS
    ]


def rank_catalog(
    rows: list[dict[str, str]],
    query: str,
    limit: int,
) -> list[dict[str, str]]:
    query_terms = _tokens(query)
    if not query_terms:
        return []
    query_set = set(query_terms)
    core_query_set = query_set - SEARCH_MODIFIER_WORDS
    normalized_query = re.sub(r"[^a-z0-9]+", "_", query.casefold()).strip("_")
    human_population_query = "population" in query_set and not {
        "animal",
        "livestock",
        "bovine",
        "pig",
        "goat",
    }.intersection(query_set)
    seen: set[str] = set()
    matches: list[tuple[float, float, dict[str, str]]] = []
    for row in rows:
        if row["code"] in seen or row["type"] not in {"dataset", "table"}:
            continue
        seen.add(row["code"])

        code = row["code"].casefold()
        code_terms = set(_tokens(code))
        title_terms = set(_tokens(row["title"]))
        matched = query_set & (code_terms | title_terms)
        matched_core = core_query_set.intersection(matched)
        minimum_core_matches = 2 if len(core_query_set) >= 3 else 1
        if not matched or (
            core_query_set and len(matched_core) < minimum_core_matches
        ):
            continue

        coverage = len(matched) / len(query_set)
        score = sum(
            4.0 if term in code_terms else 2.0
            for term in matched
        )
        score += coverage * 4
        if normalized_query == code:
            score += 100
        normalized_title = " ".join(_tokens(row["title"]))
        normalized_terms = " ".join(query_terms)
        if normalized_terms and normalized_terms in normalized_title:
            score += 8
        end_match = re.match(r"(\d{4})", row.get("data_end", ""))
        if end_match:
            end_year = int(end_match.group(1))
            if end_year >= 2024:
                score += 3
            elif end_year < 2020:
                score -= 2
        if "per capita" in query.casefold():
            title = row["title"].casefold()
            if any(term in title for term in ("country", "national level")):
                score += 2
            if any(term in title for term in ("metropolitan region", "nuts 3")):
                score -= 2
        if row["type"] == "dataset":
            score += 0.25
        if human_population_query:
            title = row["title"].casefold()
            if row["code"].startswith("demo"):
                score += 3
            elif row["code"].startswith("proj"):
                score += 1
            elif row["code"].startswith("cens"):
                score += 0.5
            if "demographic" in title:
                score += 2
            if any(word in title for word in ("animal", "bovine", "pig", "goat", "hens", "livestock")):
                score -= 2
        matches.append((score, coverage, row))

    matches.sort(key=lambda item: (-item[0], -item[1], item[2]["code"]))
    return [row for _, _, row in matches[:limit]]


def _catalog_text(cache_file: str | None) -> str:
    cache_path = Path(cache_file) if cache_file else None
    if cache_path and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    text = get_text(TOC_URL)
    if cache_path:
        cache_path.write_text(text, encoding="utf-8")
    return text


def search_catalog(query: str, limit: int, cache_file: str | None = None) -> None:
    rows = parse_toc(_catalog_text(cache_file))
    print(json.dumps(rank_catalog(rows, query, limit), indent=2, ensure_ascii=False))


def build_url(dataset: str, params: list[tuple[str, str]]) -> str:
    query = [("format", "JSON"), ("lang", "en"), *params]
    return f"{DATA_URL}/{urllib.parse.quote(dataset)}?{urllib.parse.urlencode(query)}"


def build_sdmx_dataflow_url(dataset: str) -> str:
    """Return a structure-only request including the dataset's referenced codelists."""
    code = urllib.parse.quote(dataset.upper())
    query = urllib.parse.urlencode(
        {
            "references": "descendants",
            "detail": "referencepartial",
            "compress": "false",
        }
    )
    return f"{SDMX_DATAFLOW_URL}/ESTAT/{code}/1.0?{query}"


def build_sdmx_constraint_url(dataset: str) -> str:
    """Return the dataset constraint containing positions used by observations."""
    code = urllib.parse.quote(dataset.upper())
    return f"{SDMX_CONSTRAINT_URL}/ESTAT/{code}/1.0?compress=false"


def parse_param(values: list[str]) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected --param key=value, got {value!r}")
        key, raw = value.split("=", 1)
        for part in raw.split(","):
            if part:
                params.append((key, part))
    return params


def categories(dataset: dict[str, Any], dim_id: str) -> list[dict[str, Any]]:
    dim = dataset.get("dimension", {}).get(dim_id, {})
    category = dim.get("category", {})
    indexes = category.get("index", {})
    labels = category.get("label", {})
    if isinstance(indexes, list):
        ordered = sorted(enumerate(indexes), key=lambda item: item[0])
        return [{"code": code, "label": labels.get(code, code), "index": i} for i, code in ordered]
    ordered = sorted(indexes.items(), key=lambda item: item[1])
    return [{"code": code, "label": labels.get(code, code), "index": idx} for code, idx in ordered]


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    tokens = re.findall(r"[a-z0-9]+", without_marks)
    return " ".join(DIMENSION_MATCH_TOKEN_ALIASES.get(token, token) for token in tokens)


def match_dimension_categories(
    data: dict[str, Any],
    queries: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Find bounded label/code matches across every complete dataset dimension."""
    dimensions = []
    for dim_id in data.get("id", []):
        dimensions.append({"id": dim_id, "categories": categories(data, dim_id)})
    return match_catalog_categories(dimensions, queries, limit)


def match_catalog_categories(
    dimensions: list[dict[str, Any]],
    queries: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Find bounded matches in a normalized dimension/category catalog."""
    results: list[dict[str, Any]] = []
    for raw_query in queries:
        query = raw_query.strip()
        expanded_query = DIMENSION_MATCH_QUERY_EXPANSIONS.get(query.casefold(), query)
        normalized_query = _search_text(expanded_query)
        if not normalized_query:
            continue
        query_tokens = set(normalized_query.split())
        candidates: list[tuple[float, str, str, str]] = []
        for dimension in dimensions:
            dim_id = str(dimension.get("id") or "")
            for item in dimension.get("categories", []):
                code = str(item["code"])
                label = str(item["label"])
                normalized_code = _search_text(code)
                normalized_label = _search_text(label)
                label_tokens = set(normalized_label.split())
                overlap = len(query_tokens & label_tokens) / max(1, len(query_tokens))
                similarity = difflib.SequenceMatcher(
                    None,
                    normalized_query,
                    normalized_label,
                ).ratio()
                contains = normalized_query in normalized_label or normalized_label in normalized_query
                score = max(
                    1.0 if normalized_query == normalized_code else 0.0,
                    0.96 if normalized_query == normalized_label else 0.0,
                    0.88 if contains else 0.0,
                    overlap * 0.72 + similarity * 0.28,
                )
                if score >= 0.44:
                    candidates.append((score, str(dim_id), code, label))
        candidates.sort(key=lambda item: (-item[0], item[1], item[3], item[2]))
        results.append(
            {
                "query": query,
                "categories": [
                    {
                        "dimension": dim_id,
                        "code": code,
                        "label": label,
                    }
                    for _, dim_id, code, label in candidates[:limit]
                ],
            }
        )
    return results


def _xml_local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _xml_name(element: ET.Element) -> str | None:
    names = [child for child in element if _xml_local_name(child) == "Name"]
    for child in names:
        language = child.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "")
        if language.casefold() == "en" and child.text:
            return child.text.strip()
    for child in names:
        if child.text:
            return child.text.strip()
    return None


def _reference_id(element: ET.Element, container_name: str) -> str | None:
    for container in element.iter():
        if _xml_local_name(container) != container_name:
            continue
        for descendant in container.iter():
            if _xml_local_name(descendant) == "Ref" and descendant.attrib.get("id"):
                return str(descendant.attrib["id"])
    return None


def _parse_constraint_positions(xml_text: str) -> dict[str, set[str]]:
    root = ET.fromstring(xml_text)
    positions: dict[str, set[str]] = {}
    for key_value in root.iter():
        if _xml_local_name(key_value) != "KeyValue":
            continue
        dimension_id = key_value.attrib.get("id")
        if not dimension_id:
            continue
        values = {
            str(value.text).strip()
            for value in key_value.iter()
            if _xml_local_name(value) == "Value" and value.text and value.text.strip()
        }
        if values:
            positions.setdefault(str(dimension_id).casefold(), set()).update(values)
    return positions


def parse_sdmx_dimensions(
    dataflow_xml: str,
    constraint_xml: str,
    dataset: str,
) -> dict[str, Any]:
    """Parse structure-only SDMX responses into the inspector's normalized catalog."""
    root = ET.fromstring(dataflow_xml)
    constraints = _parse_constraint_positions(constraint_xml)

    concept_labels: dict[str, str] = {}
    codelists: dict[str, list[dict[str, Any]]] = {}
    dataflow_label: str | None = None
    requested_code = dataset.casefold()

    for element in root.iter():
        local_name = _xml_local_name(element)
        element_id = str(element.attrib.get("id") or "")
        if local_name == "Dataflow" and element_id.casefold() == requested_code:
            dataflow_label = _xml_name(element)
        elif local_name == "Concept" and element_id:
            concept_labels[element_id.casefold()] = _xml_name(element) or element_id
        elif local_name == "Codelist" and element_id:
            items: list[dict[str, Any]] = []
            for code in element.iter():
                if _xml_local_name(code) != "Code" or not code.attrib.get("id"):
                    continue
                code_id = str(code.attrib["id"])
                items.append(
                    {
                        "code": code_id,
                        "label": _xml_name(code) or code_id,
                        "index": len(items),
                    }
                )
            codelists[element_id.casefold()] = items

    dimensions: list[dict[str, Any]] = []
    for dimension_list in root.iter():
        if _xml_local_name(dimension_list) != "DimensionList":
            continue
        for dimension in dimension_list:
            dimension_kind = _xml_local_name(dimension)
            if dimension_kind not in {
                "Dimension",
                "MeasureDimension",
                "TimeDimension",
            }:
                continue
            sdmx_dimension_id = str(dimension.attrib.get("id") or "")
            if not sdmx_dimension_id:
                continue
            dimension_id = (
                "time"
                if dimension_kind == "TimeDimension"
                or sdmx_dimension_id.casefold() == "time_period"
                else sdmx_dimension_id
            )
            concept_id = _reference_id(dimension, "ConceptIdentity")
            codelist_id = _reference_id(dimension, "Enumeration")
            catalog = list(codelists.get(str(codelist_id).casefold(), []))
            available = constraints.get(sdmx_dimension_id.casefold(), set())
            if not available:
                available = constraints.get(dimension_id.casefold(), set())
            if available:
                by_code = {str(item["code"]): item for item in catalog}
                ordered_codes = [
                    str(item["code"]) for item in catalog if str(item["code"]) in available
                ]
                ordered_codes.extend(sorted(available - set(ordered_codes)))
                catalog = [
                    {
                        "code": code,
                        "label": str(by_code.get(code, {}).get("label") or code),
                        "index": index,
                    }
                    for index, code in enumerate(ordered_codes)
                ]
            if not catalog:
                raise ValueError(
                    f"SDMX metadata did not provide categories for dimension {dimension_id}."
                )
            try:
                position = int(dimension.attrib.get("position", len(dimensions) + 1))
            except ValueError:
                position = len(dimensions) + 1
            dimensions.append(
                {
                    "id": dimension_id,
                    "label": concept_labels.get(str(concept_id).casefold(), dimension_id),
                    "position": position,
                    "categories": catalog,
                }
            )
        if dimensions:
            break

    if not dimensions:
        raise ValueError("SDMX metadata did not contain a dimension list.")
    dimensions.sort(key=lambda item: int(item["position"]))
    return {
        "dataset": dataset,
        "label": dataflow_label,
        "updated": None,
        "inspection_source": "sdmx",
        "dimensions": dimensions,
    }


def inspect_sdmx_dimensions(dataset: str) -> dict[str, Any]:
    dataflow_xml = get_text(build_sdmx_dataflow_url(dataset))
    constraint_xml = get_text(build_sdmx_constraint_url(dataset))
    return parse_sdmx_dimensions(dataflow_xml, constraint_xml, dataset)


def inspect_statistics_dimensions(dataset: str) -> dict[str, Any]:
    data = get_json(build_url(dataset, [("lastTimePeriod", "1")]))
    normalized_dimensions = []
    for dim_id, size in zip(data.get("id", []), data.get("size", [])):
        normalized_dimensions.append(
            {
                "id": dim_id,
                "label": data.get("dimension", {}).get(dim_id, {}).get("label", dim_id),
                "position": len(normalized_dimensions) + 1,
                "categories": categories(data, dim_id),
                "reported_size": size,
            }
        )
    return {
        "dataset": dataset,
        "label": data.get("label"),
        "updated": data.get("updated"),
        "inspection_source": "statistics_fallback",
        "dimensions": normalized_dimensions,
    }


def dimensions(dataset: str, matches: list[str] | None = None) -> None:
    try:
        catalog = inspect_sdmx_dimensions(dataset)
    except (ET.ParseError, OSError, SystemExit, ValueError) as metadata_error:
        try:
            catalog = inspect_statistics_dimensions(dataset)
        except (OSError, SystemExit, ValueError) as fallback_error:
            raise SystemExit(
                "Could not inspect Eurostat dataset dimensions. "
                f"SDMX metadata failed: {metadata_error}. "
                f"Statistics API fallback failed: {fallback_error}."
            ) from fallback_error

    result = {
        "dataset": dataset,
        "label": catalog.get("label"),
        "updated": catalog.get("updated"),
        "inspection_source": catalog.get("inspection_source"),
        "dimensions": [],
    }
    normalized_dimensions = catalog.get("dimensions", [])
    for dimension in normalized_dimensions:
        cats = dimension.get("categories", [])
        result["dimensions"].append(
            {
                "id": dimension["id"],
                "label": dimension.get("label", dimension["id"]),
                "size": dimension.get("reported_size", len(cats)),
                "sample_categories": cats[:30],
            }
        )
    if matches:
        result["matches"] = match_catalog_categories(normalized_dimensions, matches)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def coords_from_index(index: int, sizes: list[int]) -> list[int]:
    coords = [0] * len(sizes)
    for pos in range(len(sizes) - 1, -1, -1):
        size = sizes[pos]
        coords[pos] = index % size
        index //= size
    return coords


def flatten(data: dict[str, Any]) -> list[dict[str, Any]]:
    ids = data.get("id", [])
    sizes = data.get("size", [])
    category_by_dim = {dim_id: categories(data, dim_id) for dim_id in ids}
    code_by_pos = {
        dim_id: {item["index"]: (item["code"], item["label"]) for item in items}
        for dim_id, items in category_by_dim.items()
    }
    values = data.get("value", [])
    statuses = data.get("status", {})
    if isinstance(values, dict):
        iterator = ((int(k), v) for k, v in values.items())
    else:
        iterator = ((i, v) for i, v in enumerate(values))

    rows = []
    for flat_index, value in iterator:
        if value is None:
            continue
        coords = coords_from_index(flat_index, sizes)
        row: dict[str, Any] = {"value": value}
        for dim_id, coord in zip(ids, coords):
            code, label = code_by_pos[dim_id].get(coord, (str(coord), str(coord)))
            row[dim_id] = code
            row[f"{dim_id}_label"] = label
        if isinstance(statuses, dict) and str(flat_index) in statuses:
            row["status"] = statuses[str(flat_index)]
        elif isinstance(statuses, list) and flat_index < len(statuses) and statuses[flat_index]:
            row["status"] = statuses[flat_index]
        rows.append(row)
    return rows


def estimated_cell_count(data: dict[str, Any]) -> int:
    """Return the dense JSON-stat cube size before allocating flattened rows."""
    estimate = 1
    sizes = data.get("size", [])
    if not isinstance(sizes, list):
        raise SystemExit("Eurostat returned an invalid dimension-size list.")
    for raw_size in sizes:
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
            raise SystemExit("Eurostat returned an invalid dimension size.")
        estimate *= raw_size
        if estimate > MAX_ESTIMATED_CELLS:
            raise SystemExit(
                "Filtered Eurostat query is too broad "
                f"({estimate} estimated cells; limit {MAX_ESTIMATED_CELLS}). "
                "Narrow the dimension or time filters."
            )
    return estimate


def fetch(args: argparse.Namespace) -> None:
    params = parse_param(args.param)
    if args.last_time_period is not None:
        if not 1 <= args.last_time_period <= MAX_TIME_PERIODS:
            raise SystemExit(
                f"--last-time-period must be between 1 and {MAX_TIME_PERIODS}."
            )
        params.append(("lastTimePeriod", str(args.last_time_period)))
    for time_value in args.time:
        params.append(("time", time_value))
    requested_times = {value for key, value in params if key == "time"}
    if requested_times and args.last_time_period is not None:
        raise SystemExit(
            "Explicit time values and --last-time-period are mutually exclusive. "
            "Choose --time/--param time=... or --last-time-period, not both."
        )
    if not requested_times and args.last_time_period is None:
        raise SystemExit(
            "A bounded time filter is required. Pass --time or --last-time-period."
        )
    if len(requested_times) > MAX_TIME_PERIODS:
        raise SystemExit(
            f"At most {MAX_TIME_PERIODS} explicit time periods may be requested."
        )
    data = get_json(build_url(args.dataset, params))
    estimated_cells = estimated_cell_count(data)
    rows = flatten(data)
    total_rows = len(rows)
    truncated = bool(args.max_rows and total_rows > args.max_rows)
    if args.max_rows:
        rows = rows[: args.max_rows]
    if args.output == "json":
        print(
            json.dumps(
                {
                    "metadata": {
                        "label": data.get("label"),
                        "updated": data.get("updated"),
                        "total_rows": total_rows,
                        "returned_rows": len(rows),
                        "truncated": truncated,
                        "estimated_cells": estimated_cells,
                    },
                    "rows": rows,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and fetch Eurostat Statistics API data.")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search Eurostat table-of-contents metadata.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument(
        "--cache-file",
        help="Optional catalogue cache file, useful when several searches run in one investigation.",
    )

    dims = sub.add_parser("dimensions", help="Inspect dataset dimensions with one recent period.")
    dims.add_argument("dataset")
    dims.add_argument(
        "--match",
        action="append",
        default=[],
        help=(
            "Find matching category labels or codes across complete dimensions. "
            "Repeat for multiple requested labels."
        ),
    )

    fetch_parser = sub.add_parser("fetch", help="Fetch and flatten a filtered dataset slice.")
    fetch_parser.add_argument("dataset")
    fetch_parser.add_argument("--param", action="append", default=[], help="Dimension filter as key=value or key=a,b.")
    fetch_parser.add_argument("--last-time-period", type=int)
    fetch_parser.add_argument("--time", action="append", default=[])
    fetch_parser.add_argument("--output", choices=["csv", "json"], default="csv")
    fetch_parser.add_argument(
        "--max-rows",
        type=int,
        default=500,
        help="Maximum observations to emit after flattening (default: 500).",
    )

    args = parser.parse_args()
    if args.command == "search":
        search_catalog(args.query, args.limit, args.cache_file)
    elif args.command == "dimensions":
        dimensions(args.dataset, args.match)
    elif args.command == "fetch":
        fetch(args)


if __name__ == "__main__":
    main()
