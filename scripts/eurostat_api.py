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
from pathlib import Path
from typing import Any


BASE = "https://ec.europa.eu/eurostat/api/dissemination"
TOC_URL = f"{BASE}/catalogue/toc/txt?lang=en"
DATA_URL = f"{BASE}/statistics/1.0/data"
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


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "codex-eurostat-skill/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read().decode("utf-8-sig")
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
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def match_dimension_categories(
    data: dict[str, Any],
    queries: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Find bounded label/code matches across every complete dataset dimension."""
    results: list[dict[str, Any]] = []
    for raw_query in queries:
        query = raw_query.strip()
        normalized_query = _search_text(query)
        if not normalized_query:
            continue
        query_tokens = set(normalized_query.split())
        candidates: list[tuple[float, str, str, str]] = []
        for dim_id in data.get("id", []):
            for item in categories(data, dim_id):
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


def dimensions(dataset: str, matches: list[str] | None = None) -> None:
    data = get_json(build_url(dataset, [("lastTimePeriod", "1")]))
    result = {
        "dataset": dataset,
        "label": data.get("label"),
        "updated": data.get("updated"),
        "dimensions": [],
    }
    for dim_id, size in zip(data.get("id", []), data.get("size", [])):
        cats = categories(data, dim_id)
        result["dimensions"].append(
            {
                "id": dim_id,
                "label": data.get("dimension", {}).get(dim_id, {}).get("label", dim_id),
                "size": size,
                "sample_categories": cats[:30],
            }
        )
    if matches:
        result["matches"] = match_dimension_categories(data, matches)
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


def fetch(args: argparse.Namespace) -> None:
    params = parse_param(args.param)
    if args.last_time_period:
        params.append(("lastTimePeriod", str(args.last_time_period)))
    for time_value in args.time:
        params.append(("time", time_value))
    data = get_json(build_url(args.dataset, params))
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
