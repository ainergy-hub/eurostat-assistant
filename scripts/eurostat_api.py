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
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


BASE = "https://ec.europa.eu/eurostat/api/dissemination"
TOC_URL = f"{BASE}/catalogue/toc/txt?lang=en"
DATA_URL = f"{BASE}/statistics/1.0/data"


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


def search_catalog(query: str, limit: int) -> None:
    terms = [term.casefold() for term in query.split() if term.strip()]
    human_population_query = "population" in terms and not {"animal", "livestock", "bovine", "pig", "goat"}.intersection(terms)
    seen: set[str] = set()
    matches = []
    for row in parse_toc(get_text(TOC_URL)):
        if row["code"] in seen or row["type"] not in {"dataset", "table"}:
            continue
        seen.add(row["code"])
        haystack = f"{row['code']} {row['title']}".casefold()
        score = sum(3 if term in row["code"].casefold() else 1 for term in terms if term in haystack)
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
        if score:
            matches.append((score, row))
    matches.sort(key=lambda pair: (-pair[0], pair[1]["code"]))
    print(json.dumps([row for _, row in matches[:limit]], indent=2, ensure_ascii=False))


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


def dimensions(dataset: str) -> None:
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
    if args.output == "json":
        print(json.dumps({"metadata": {"label": data.get("label"), "updated": data.get("updated")}, "rows": rows}, indent=2, ensure_ascii=False))
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
    search.add_argument("--limit", type=int, default=12)

    dims = sub.add_parser("dimensions", help="Inspect dataset dimensions with one recent period.")
    dims.add_argument("dataset")

    fetch_parser = sub.add_parser("fetch", help="Fetch and flatten a filtered dataset slice.")
    fetch_parser.add_argument("dataset")
    fetch_parser.add_argument("--param", action="append", default=[], help="Dimension filter as key=value or key=a,b.")
    fetch_parser.add_argument("--last-time-period", type=int)
    fetch_parser.add_argument("--time", action="append", default=[])
    fetch_parser.add_argument("--output", choices=["csv", "json"], default="csv")

    args = parser.parse_args()
    if args.command == "search":
        search_catalog(args.query, args.limit)
    elif args.command == "dimensions":
        dimensions(args.dataset)
    elif args.command == "fetch":
        fetch(args)


if __name__ == "__main__":
    main()
