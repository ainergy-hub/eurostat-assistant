from __future__ import annotations

import json
import math
import re
import urllib.parse
from typing import Any

try:
    from .agent_config import CHART_PURPOSES, CHART_TYPES
except ImportError:  # Support direct execution by sandbox_agent.py.
    from agent_config import CHART_PURPOSES, CHART_TYPES


def _filters_from_arguments(arguments: dict[str, Any]) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    for raw in arguments.get("params", []) or []:
        key, separator, value = str(raw).partition("=")
        if not separator or not key or not value:
            continue
        filters.setdefault(key, []).extend(part for part in value.split(",") if part)
    if arguments.get("last_time_period"):
        filters["lastTimePeriod"] = [str(arguments["last_time_period"])]
    if arguments.get("time"):
        filters["time"] = [str(value) for value in arguments["time"]]
    return filters


def _source_url(dataset: str, filters: dict[str, list[str]]) -> str:
    query: list[tuple[str, str]] = [("format", "JSON"), ("lang", "en")]
    for key, values in filters.items():
        query.extend((key, value) for value in values)
    return (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        f"{urllib.parse.quote(dataset)}?{urllib.parse.urlencode(query)}"
    )


def _column_label(field: str) -> str:
    labels = {
        "freq_label": "Frequency",
        "geo_label": "Geography",
        "time_label": "Period",
        "value": "Value",
        "status": "Status",
    }
    return labels.get(field, field.removesuffix("_label").replace("_", " ").title())


def _visible_columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return []
    available = list(rows[0])
    fields: list[str] = []
    for field in available:
        if field.endswith("_label"):
            continue
        label_field = f"{field}_label"
        chosen = label_field if label_field in available else field
        if chosen not in fields:
            fields.append(chosen)
    # Keep the measure and its observation flag at the end.
    fields = [field for field in fields if field not in {"value", "status"}]
    if "value" in available:
        fields.append("value")
    if "status" in available:
        fields.append("status")
    return [{"key": field, "label": _column_label(field)} for field in fields]


def _unique_values(rows: list[dict[str, Any]], field: str) -> list[Any]:
    seen: list[Any] = []
    for row in rows:
        value = row.get(field)
        if value is not None and value not in seen:
            seen.append(value)
    return seen


def _chart_intent(rows: list[dict[str, Any]], title: str) -> dict[str, Any]:
    if not rows or not any(isinstance(row.get("value"), (int, float)) for row in rows):
        return {"type": "none"}

    time_field = _time_field(rows)
    time_values = _unique_values(rows, time_field) if time_field else []
    dimension_fields = _dimension_fields(rows, exclude={time_field} if time_field else set())
    preferred_series = _preferred_dimension(dimension_fields)

    if time_field and len(time_values) > 1:
        unit_values = _unique_values(rows, "unit_label")
        y_label = str(unit_values[0]) if len(unit_values) == 1 else "Value"
        choice = {
            "purpose": "trend",
            "type": "line",
            "x": time_field,
            "y": "value",
            "series": preferred_series,
            "x_label": _column_label(time_field),
            "y_label": y_label,
        }
        return _validated_chart_choice(rows, title, choice) or {"type": "none"}
    return {"type": "none"}


def _available_fields(rows: list[dict[str, Any]]) -> set[str]:
    return {field for row in rows for field in row}


def _time_field(rows: list[dict[str, Any]]) -> str | None:
    fields = _available_fields(rows)
    if "time_label" in fields:
        return "time_label"
    if "time" in fields:
        return "time"
    return None


def _dimension_fields(
    rows: list[dict[str, Any]],
    exclude: set[str] | None = None,
) -> list[str]:
    excluded = exclude or set()
    fields = _available_fields(rows)
    candidates = [
        field
        for field in fields
        if field not in excluded
        and len(_unique_values(rows, field)) > 1
        and (field.endswith("_label") or not _numeric_field(rows, field))
    ]
    return sorted(candidates)


def _preferred_dimension(fields: list[str]) -> str | None:
    for field in ("geo_label", "indic_label", "product_label", "unit_label"):
        if field in fields:
            return field
    return fields[0] if fields else None


def _numeric_field(rows: list[dict[str, Any]], field: str) -> bool:
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not values:
        return False
    try:
        return all(not isinstance(value, bool) and math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def _numeric_fields(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(field for field in _available_fields(rows) if _numeric_field(rows, field))


def _measure_field(rows: list[dict[str, Any]]) -> str | None:
    numeric = _numeric_fields(rows)
    if "value" in numeric:
        return "value"
    non_time = [field for field in numeric if field != "time"]
    return non_time[0] if non_time else (numeric[0] if numeric else None)


def _resolve_chart_type(
    rows: list[dict[str, Any]],
    choice: dict[str, Any],
) -> str | None:
    requested = choice.get("type")
    if requested in CHART_TYPES:
        return str(requested)
    if requested not in {None, "auto"}:
        return None

    purpose = choice.get("purpose")
    if purpose in {"trend", "change"}:
        return "line"
    if purpose == "comparison":
        category = choice.get("x")
        if not isinstance(category, str) or category not in _available_fields(rows):
            category = _preferred_dimension(
                _dimension_fields(
                    rows,
                    exclude={_time_field(rows)} if _time_field(rows) else set(),
                )
            )
        if category:
            return "dot" if len(_unique_values(rows, category)) > 12 else "bar"
        return "bar"
    if purpose == "relationship":
        x_field = choice.get("x")
        y_field = choice.get("y")
        color_field = choice.get("color")
        if (
            isinstance(x_field, str)
            and isinstance(y_field, str)
            and _numeric_field(rows, x_field)
            and _numeric_field(rows, y_field)
        ):
            return "scatter"
        if (
            isinstance(x_field, str)
            and isinstance(y_field, str)
            and isinstance(color_field, str)
            and _numeric_field(rows, color_field)
        ):
            return "heatmap"
        return "scatter"
    if purpose == "distribution":
        return "boxplot" if choice.get("x") and choice.get("y") else "histogram"
    if purpose == "composition":
        return "area" if choice.get("x") == _time_field(rows) else "bar"
    return None


def _default_chart_fields(
    rows: list[dict[str, Any]],
    chart_type: str,
    choice: dict[str, Any],
) -> dict[str, Any]:
    fields = _available_fields(rows)
    time_field = _time_field(rows)
    measure = _measure_field(rows)
    dimensions = _dimension_fields(rows, exclude={time_field} if time_field else set())
    category = _preferred_dimension(dimensions)
    result = dict(choice)

    if chart_type in {"line", "area"}:
        result["x"] = result.get("x") if result.get("x") in fields else time_field or category
        result["y"] = result.get("y") if result.get("y") in fields else measure
    elif chart_type in {"bar", "dot"}:
        result["x"] = result.get("x") if result.get("x") in fields else category or time_field
        result["y"] = result.get("y") if result.get("y") in fields else measure
    elif chart_type == "scatter":
        numeric = _numeric_fields(rows)
        result["y"] = result.get("y") if result.get("y") in fields else measure
        x_candidates = [field for field in numeric if field != result.get("y")]
        result["x"] = (
            result.get("x")
            if result.get("x") in fields
            else ("time" if "time" in x_candidates else (x_candidates[0] if x_candidates else None))
        )
    elif chart_type == "heatmap":
        all_dimensions = _dimension_fields(rows)
        result["x"] = (
            result.get("x")
            if result.get("x") in fields
            else time_field or (all_dimensions[0] if all_dimensions else None)
        )
        y_candidates = [field for field in all_dimensions if field != result.get("x")]
        result["y"] = (
            result.get("y") if result.get("y") in fields else (y_candidates[0] if y_candidates else None)
        )
        result["color"] = (
            result.get("color") if result.get("color") in fields else measure
        )
    elif chart_type == "histogram":
        result["x"] = result.get("x") if result.get("x") in fields else measure
        result["y"] = None
    elif chart_type == "boxplot":
        result["x"] = result.get("x") if result.get("x") in fields else category
        result["y"] = result.get("y") if result.get("y") in fields else measure

    if chart_type in {"line", "area", "bar", "dot", "boxplot"}:
        series = result.get("series")
        if series not in fields:
            series_candidates = [
                field for field in dimensions if field not in {result.get("x"), result.get("y")}
            ]
            result["series"] = _preferred_dimension(series_candidates)
    return result


def _valid_line_grain(rows: list[dict[str, Any]], x_field: str, series: str | None) -> bool:
    keys: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (row.get(x_field), row.get(series) if series else None)
        if key in keys:
            return False
        keys.add(key)
    return True


def _validated_chart_choice(
    rows: list[dict[str, Any]],
    title: str,
    choice: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not choice or not rows:
        return None
    chart_type = _resolve_chart_type(rows, choice)
    if chart_type not in CHART_TYPES:
        return None
    resolved = _default_chart_fields(rows, chart_type, choice)
    fields = _available_fields(rows)
    x_field = resolved.get("x")
    y_field = resolved.get("y")
    color_field = resolved.get("color")

    if chart_type == "histogram":
        if not isinstance(x_field, str) or x_field not in fields or not _numeric_field(rows, x_field):
            return None
    elif chart_type == "heatmap":
        if (
            not isinstance(x_field, str)
            or not isinstance(y_field, str)
            or not isinstance(color_field, str)
            or x_field not in fields
            or y_field not in fields
            or x_field == y_field
            or not _numeric_field(rows, color_field)
            or len(_unique_values(rows, x_field)) * len(_unique_values(rows, y_field)) > 500
        ):
            return None
    elif chart_type == "boxplot":
        if not isinstance(y_field, str) or not _numeric_field(rows, y_field):
            return None
        if x_field is not None and (not isinstance(x_field, str) or x_field not in fields):
            return None
    elif not isinstance(x_field, str) or not isinstance(y_field, str):
        return None
    elif x_field not in fields or y_field not in fields or not _numeric_field(rows, y_field):
        return None
    if chart_type == "scatter" and (x_field == y_field or not _numeric_field(rows, x_field)):
        return None
    series = resolved.get("series")
    if (
        not isinstance(series, str)
        or series not in fields
        or series in {x_field, y_field, color_field}
        or len(_unique_values(rows, series)) < 2
        or len(_unique_values(rows, series)) > 12
    ):
        series = None
    if chart_type in {"line", "area"} and not _valid_line_grain(rows, x_field, series):
        return None
    label = resolved.get("label")
    if not isinstance(label, str) or label not in fields:
        label = None
    size = resolved.get("size")
    if (
        chart_type != "scatter"
        or not isinstance(size, str)
        or size not in fields
        or not _numeric_field(rows, size)
    ):
        size = None
    orientation = resolved.get("orientation")
    if chart_type not in {"bar", "dot"} or orientation not in {"horizontal", "vertical"}:
        orientation = None
    stack = resolved.get("stack")
    if stack not in {"none", "stacked", "normalize"}:
        stack = "none"
    if chart_type not in {"bar", "area"} or not series:
        stack = "none"
    elif resolved.get("purpose") == "composition" and stack == "none":
        stack = "stacked"
    sort = resolved.get("sort")
    if sort not in {"natural", "ascending", "descending"}:
        sort = "natural"
    top_n = resolved.get("top_n")
    if (
        not isinstance(top_n, int)
        or isinstance(top_n, bool)
        or not 1 <= top_n <= 50
        or chart_type not in {"bar", "dot", "heatmap"}
    ):
        top_n = None
    trendline = resolved.get("trendline")
    if chart_type != "scatter" or trendline != "linear":
        trendline = "none"
    labels = (
        "always"
        if chart_type in {"line", "bar", "dot", "scatter"}
        and resolved.get("labels") == "always"
        else "hover"
    )
    scale = "log" if resolved.get("scale") == "log" else "linear"
    numeric_axis_fields = [
        field
        for field in (x_field if chart_type in {"scatter", "histogram"} else None, y_field, color_field)
        if isinstance(field, str) and _numeric_field(rows, field)
    ]
    if scale == "log" and any(
        float(row[field]) <= 0
        for field in numeric_axis_fields
        for row in rows
        if row.get(field) is not None
    ):
        scale = "linear"
    zero_baseline = resolved.get("zero_baseline")
    if zero_baseline == "zero":
        zero_baseline = True
    elif zero_baseline == "free":
        zero_baseline = False
    if zero_baseline not in {True, False, "auto"}:
        zero_baseline = "auto"
    if chart_type == "bar":
        zero_baseline = True
    if scale == "log":
        zero_baseline = False
    purpose = resolved.get("purpose")
    if purpose not in CHART_PURPOSES:
        purpose = {
            "line": "trend",
            "area": "composition" if stack != "none" else "trend",
            "bar": "composition" if stack != "none" else "comparison",
            "dot": "comparison",
            "scatter": "relationship",
            "heatmap": "relationship",
            "histogram": "distribution",
            "boxplot": "distribution",
        }[chart_type]

    intent: dict[str, Any] = {
        "type": chart_type,
        "purpose": purpose,
        "x": x_field,
        "y": y_field,
        "color": color_field if chart_type == "heatmap" else None,
        "size": size,
        "series": series,
        "label": label,
        "title": str(resolved.get("title") or title)[:160],
        "stack": stack,
        "sort": sort,
        "top_n": top_n,
        "trendline": trendline,
        "labels": labels,
        "scale": scale,
        "zero_baseline": zero_baseline,
    }
    if orientation:
        intent["orientation"] = orientation
    for axis in ("x", "y"):
        axis_label = resolved.get(f"{axis}_label")
        if isinstance(axis_label, str) and axis_label.strip():
            intent[f"{axis}_label"] = axis_label.strip()[:80]
    return intent


def _field_name(label: str, fallback: str) -> str:
    field = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not field or field[0].isdigit():
        return fallback
    return field[:64]


def _matching_fetch(
    fetch_records: list[dict[str, Any]],
    dataset_code: str,
) -> dict[str, Any] | None:
    return next(
        (
            record
            for record in reversed(fetch_records)
            if str((record.get("arguments") or {}).get("dataset")) == dataset_code
        ),
        None,
    )


def _unique_row_index(
    rows: list[dict[str, Any]],
    join_on: list[str],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], set[tuple[Any, ...]]]:
    index: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates: set[tuple[Any, ...]] = set()
    for row in rows:
        key = tuple(row.get(field) for field in join_on)
        if any(value is None for value in key):
            continue
        if key in index:
            duplicates.add(key)
            continue
        index[key] = row
    for key in duplicates:
        index.pop(key, None)
    return index, duplicates


def _aggregate_geography_code(row: dict[str, Any]) -> str | None:
    code = str(row.get("geo") or "").strip()
    label = str(row.get("geo_label") or "").casefold()
    aggregate_labels = (
        "european union",
        "euro area",
        "european economic area",
        "european free trade association",
    )
    if any(marker in label for marker in aggregate_labels) or re.match(r"^(?:EU|EA)\d", code):
        return code or str(row.get("geo_label") or "aggregate")
    return None


def build_scatter_result(
    fetch_records: list[dict[str, Any]],
    choice: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not choice:
        return None
    result_ids = choice.get("result_ids")
    if isinstance(result_ids, list) and len(result_ids) == 2:
        x_record = next(
            (record for record in fetch_records if record.get("result_id") == result_ids[0]),
            None,
        )
        y_record = next(
            (record for record in fetch_records if record.get("result_id") == result_ids[1]),
            None,
        )
        x_dataset = str(((x_record or {}).get("arguments") or {}).get("dataset") or "")
        y_dataset = str(((y_record or {}).get("arguments") or {}).get("dataset") or "")
    else:
        x_dataset = str(choice.get("x_dataset") or "")
        y_dataset = str(choice.get("y_dataset") or "")
        x_record = _matching_fetch(fetch_records, x_dataset)
        y_record = _matching_fetch(fetch_records, y_dataset)
    join_on = choice.get("join_on")
    if not x_dataset or not y_dataset or x_dataset == y_dataset:
        return None
    if (
        not isinstance(join_on, list)
        or not join_on
        or not all(isinstance(field, str) and field for field in join_on)
    ):
        return None

    if not x_record or not y_record:
        return None
    x_output = x_record.get("output") or {}
    y_output = y_record.get("output") or {}
    x_rows = x_output.get("rows")
    y_rows = y_output.get("rows")
    if not isinstance(x_rows, list) or not isinstance(y_rows, list) or not x_rows or not y_rows:
        return None
    if any(field not in x_rows[0] or field not in y_rows[0] for field in join_on):
        return None

    aggregate_geo_codes: set[str] = set()
    if "geo" in join_on:
        for row in [*x_rows, *y_rows]:
            aggregate_code = _aggregate_geography_code(row)
            if aggregate_code:
                aggregate_geo_codes.add(aggregate_code)
        x_rows = [row for row in x_rows if not _aggregate_geography_code(row)]
        y_rows = [row for row in y_rows if not _aggregate_geography_code(row)]
        if not x_rows or not y_rows:
            return None

    x_index, x_duplicates = _unique_row_index(x_rows, join_on)
    y_index, y_duplicates = _unique_row_index(y_rows, join_on)
    shared_keys = sorted(
        x_index.keys() & y_index.keys(),
        key=lambda key: tuple(str(value) for value in key),
    )
    x_label = str(choice.get("x_label") or x_dataset).strip()
    y_label = str(choice.get("y_label") or y_dataset).strip()
    x_field = _field_name(x_label, "x_value")
    y_field = _field_name(y_label, "y_value")
    if y_field == x_field:
        x_field = "x_value"
        y_field = "y_value"

    label_field = choice.get("label")
    if not isinstance(label_field, str) or not label_field:
        label_field = next(
            (
                f"{field}_label"
                for field in join_on
                if f"{field}_label" in x_rows[0] or f"{field}_label" in y_rows[0]
            ),
            join_on[0],
        )

    paired_rows: list[dict[str, Any]] = []
    for key in shared_keys:
        x_row = x_index[key]
        y_row = y_index[key]
        if not _numeric_field([x_row], "value") or not _numeric_field([y_row], "value"):
            continue
        row: dict[str, Any] = {}
        for field, value in zip(join_on, key):
            row[field] = value
            display_field = f"{field}_label"
            display_value = x_row.get(display_field, y_row.get(display_field))
            if display_value is not None:
                row[display_field] = display_value
        if label_field not in row:
            label_value = x_row.get(label_field, y_row.get(label_field))
            if label_value is not None:
                row[label_field] = label_value
        row[x_field] = x_row["value"]
        row[y_field] = y_row["value"]
        if "time" not in join_on:
            if x_row.get("time_label") is not None:
                row["x_period"] = x_row["time_label"]
            if y_row.get("time_label") is not None:
                row["y_period"] = y_row["time_label"]
        if x_row.get("status"):
            row["x_status"] = x_row["status"]
        if y_row.get("status"):
            row["y_status"] = y_row["status"]
        paired_rows.append(row)

    if len(paired_rows) < 2:
        return None

    x_metadata = x_output.get("metadata") or {}
    y_metadata = y_output.get("metadata") or {}
    x_filters = _filters_from_arguments(x_record["arguments"])
    y_filters = _filters_from_arguments(y_record["arguments"])
    sources = [
        {
            "code": x_dataset,
            "title": str(x_metadata.get("label") or x_dataset),
            "updated": x_metadata.get("updated"),
            "source_url": _source_url(x_dataset, x_filters),
        },
        {
            "code": y_dataset,
            "title": str(y_metadata.get("label") or y_dataset),
            "updated": y_metadata.get("updated"),
            "source_url": _source_url(y_dataset, y_filters),
        },
    ]
    title = str(choice.get("title") or f"{x_label} vs {y_label}").strip()
    warnings: list[str] = []
    if aggregate_geo_codes:
        warnings.append(
            f"{len(aggregate_geo_codes)} aggregate geographies were omitted from the "
            "country-level relationship."
        )
    unmatched = (len(x_index) - len(shared_keys)) + (len(y_index) - len(shared_keys))
    ambiguous = len(x_duplicates) + len(y_duplicates)
    if unmatched:
        warnings.append(f"{unmatched} observations had no matching pair and were omitted.")
    if ambiguous:
        warnings.append(
            f"{ambiguous} join keys were not unique and were omitted; filter each measure to one "
            "observation per join key."
        )

    visible_join_fields = [
        f"{field}_label" if f"{field}_label" in paired_rows[0] else field for field in join_on
    ]
    columns = [{"key": field, "label": _column_label(field)} for field in visible_join_fields]
    columns.extend(
        [
            {"key": x_field, "label": x_label},
            {"key": y_field, "label": y_label},
        ]
    )
    for field, label in (
        ("x_period", f"{x_label} period"),
        ("y_period", f"{y_label} period"),
        ("x_status", f"{x_label} status"),
        ("y_status", f"{y_label} status"),
    ):
        if any(field in row for row in paired_rows):
            columns.append({"key": field, "label": label})

    combined_filters = {
        f"{x_dataset}.{key}": values for key, values in x_filters.items()
    } | {
        f"{y_dataset}.{key}": values for key, values in y_filters.items()
    }
    updated_values = [source["updated"] for source in sources if source["updated"]]
    return {
        "dataset": {
            "code": f"{x_dataset}__{y_dataset}",
            "title": title,
            "updated": max(updated_values) if updated_values else None,
            "source_url": sources[0]["source_url"],
        },
        "sources": sources,
        "filters": combined_filters,
        "columns": columns,
        "rows": paired_rows,
        "chart": {
            "type": "scatter",
            "purpose": "relationship",
            "x": x_field,
            "y": y_field,
            "x_label": x_label,
            "y_label": y_label,
            "series": None,
            "label": label_field if label_field in paired_rows[0] else None,
            "title": title,
            "stack": "none",
            "sort": "natural",
            "top_n": None,
            "trendline": "none",
            "labels": "hover",
            "scale": "linear",
            "zero_baseline": "auto",
        },
        "warnings": warnings,
    }


def _paired_chart_choice(
    candidate_result: dict[str, Any],
    requested_chart: dict[str, Any],
) -> dict[str, Any]:
    """Apply safe style overrides without losing the paired measure axes."""
    base_chart = candidate_result["chart"]
    choice = {**base_chart, **requested_chart}
    choice["type"] = "scatter"
    choice["purpose"] = "relationship"

    base_axes = {base_chart.get("x"), base_chart.get("y")}
    requested_axes = {requested_chart.get("x"), requested_chart.get("y")}
    if (
        None in base_axes
        or len(base_axes) != 2
        or requested_axes != base_axes
    ):
        choice["x"] = base_chart.get("x")
        choice["y"] = base_chart.get("y")
    return choice


def build_structured_result(
    fetch_record: dict[str, Any] | None,
    chart_choice: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not fetch_record:
        return None
    output = fetch_record.get("output")
    if not isinstance(output, dict):
        return None
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None

    arguments = fetch_record["arguments"]
    dataset_code = str(arguments["dataset"])
    metadata = output.get("metadata") or {}
    title = str(metadata.get("label") or dataset_code)
    filters = _filters_from_arguments(arguments)
    warnings: list[str] = []
    if metadata.get("truncated"):
        warnings.append(
            f"Showing {metadata.get('returned_rows', len(rows))} of "
            f"{metadata.get('total_rows', len(rows))} returned observations."
        )

    chart = _validated_chart_choice(rows, title, chart_choice) or _chart_intent(rows, title)
    return {
        "dataset": {
            "code": dataset_code,
            "title": title,
            "updated": metadata.get("updated"),
            "source_url": _source_url(dataset_code, filters),
        },
        "filters": filters,
        "columns": _visible_columns(rows),
        "rows": rows,
        "chart": chart,
        "warnings": warnings,
    }


def build_source_tables(fetch_records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not fetch_records:
        return []

    records_by_dataset: dict[str, dict[str, Any]] = {}
    for record in fetch_records:
        dataset_code = str((record.get("arguments") or {}).get("dataset") or "")
        if dataset_code:
            records_by_dataset[dataset_code] = record
    if len(records_by_dataset) < 2:
        return []

    tables: list[dict[str, Any]] = []
    for record in records_by_dataset.values():
        result = build_structured_result(record)
        if not result:
            continue
        tables.append(
            {
                "dataset": result["dataset"],
                "filters": result["filters"],
                "columns": result["columns"],
                "rows": result["rows"],
                "warnings": result["warnings"],
            }
        )
    return tables


def reuse_context_result(
    context_result: dict[str, Any] | None,
    chart_choice: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(context_result, dict):
        return None
    rows = context_result.get("rows")
    if not isinstance(rows, list) or not rows:
        return None

    result = json.loads(json.dumps(context_result))
    if chart_choice:
        dataset = result.get("dataset") or {}
        title = str(dataset.get("title") or dataset.get("code") or "Eurostat data")
        chart = _validated_chart_choice(rows, title, chart_choice)
        if chart:
            result["chart"] = chart
    return result


def response_result(
    fetch_record: dict[str, Any] | None,
    context_result: dict[str, Any] | None,
    chart_choice: dict[str, Any] | None = None,
    composed_result: dict[str, Any] | None = None,
    fetch_records: list[dict[str, Any]] | None = None,
    selected_result_id: str | None = None,
) -> dict[str, Any] | None:
    records = fetch_records or ([fetch_record] if fetch_record else [])
    if composed_result:
        result = reuse_context_result(composed_result, chart_choice)
    elif selected_result_id == "context":
        result = reuse_context_result(context_result, chart_choice)
    else:
        selected_fetch = (
            next(
                (
                    record
                    for record in records
                    if str(record.get("result_id") or "") == selected_result_id
                ),
                None,
            )
            if selected_result_id
            else None
        )
        if selected_fetch:
            result = build_structured_result(selected_fetch, chart_choice)
        elif selected_result_id is None and len(records) == 1:
            result = build_structured_result(records[0], chart_choice)
        else:
            result = None

    source_tables = build_source_tables(records)
    if result and source_tables:
        result["source_tables"] = source_tables
        result["sources"] = [table["dataset"] for table in source_tables]
    return result

