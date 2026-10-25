from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from typing import Any

try:
    from .agent_config import (
        CATALOG_CACHE,
        EUROSTAT_HELPER,
        EVENT_PREFIX,
        MAX_ESTIMATED_CELLS,
        MAX_EVENT_PREVIEW_CHARS,
        MAX_RESULT_ROWS,
        MAX_TIME_PERIODS,
        MAX_TOOL_CHARS,
        MIN_CATALOG_RESULTS,
        TOOLS,
    )
except ImportError:  # Support direct execution by sandbox_agent.py.
    from agent_config import (
        CATALOG_CACHE,
        EUROSTAT_HELPER,
        EVENT_PREFIX,
        MAX_ESTIMATED_CELLS,
        MAX_EVENT_PREVIEW_CHARS,
        MAX_RESULT_ROWS,
        MAX_TIME_PERIODS,
        MAX_TOOL_CHARS,
        MIN_CATALOG_RESULTS,
        TOOLS,
    )

_TOOL_DIMENSION_CATALOGS: dict[str, dict[str, dict[str, Any]]] = {}


def run_helper(args: list[str]) -> str:
    completed = subprocess.run(
        [sys.executable, str(EUROSTAT_HELPER), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = completed.stdout
    if completed.returncode != 0:
        output = f"ERROR:\n{completed.stderr or completed.stdout}"
    return output


def call_tool(name: str, raw_arguments: str) -> str:
    try:
        args = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid JSON arguments: {exc}"

    if name == "search_eurostat":
        requested_limit = int(args.get("limit", MIN_CATALOG_RESULTS))
        return run_helper(
            [
                "search",
                str(args["query"]),
                "--limit",
                str(max(MIN_CATALOG_RESULTS, min(requested_limit, 20))),
                "--cache-file",
                str(CATALOG_CACHE),
            ]
        )

    if name == "inspect_dimensions":
        command = ["dimensions", str(args["dataset"])]
        for match in args.get("matches", []) or []:
            command.extend(["--match", str(match)])
        output = run_helper(command)
        catalog = _dimension_catalog(output)
        if catalog:
            _TOOL_DIMENSION_CATALOGS[str(args["dataset"])] = catalog
        return output

    if name == "fetch_eurostat":
        dataset = str(args["dataset"])
        catalog = _TOOL_DIMENSION_CATALOGS.get(dataset)
        if not catalog:
            inspection_output = run_helper(["dimensions", dataset])
            catalog = _dimension_catalog(inspection_output)
            if not catalog:
                return (
                    "ERROR: Could not inspect dataset dimensions before fetching. "
                    "Retry inspect_dimensions for the dataset."
                )
            _TOOL_DIMENSION_CATALOGS[dataset] = catalog
        validation_error = validate_fetch_arguments(args, {dataset: catalog})
        if validation_error:
            return validation_error
        command = [
            "fetch",
            dataset,
            "--output",
            "json",
            "--max-rows",
            str(MAX_RESULT_ROWS),
        ]
        for param in args.get("params", []) or []:
            command.extend(["--param", str(param)])
        if args.get("last_time_period"):
            command.extend(["--last-time-period", str(args["last_time_period"])])
        for time_value in args.get("time", []) or []:
            command.extend(["--time", str(time_value)])
        return run_helper(command)

    if name == "publish_result":
        return json.dumps(
            {
                "accepted": True,
                "message": "Publication request recorded. Compatibility will be validated by the host.",
            }
        )

    return f"Unknown tool: {name}"


def tool_content_for_model(output: str) -> str:
    if len(output) <= MAX_TOOL_CHARS:
        return output
    return output[:MAX_TOOL_CHARS] + "\n\n[tool output truncated for the model]"


def emit_event(event: dict[str, Any]) -> None:
    if os.getenv("STREAM_TOOL_EVENTS") != "1":
        return
    print(f"{EVENT_PREFIX}{json.dumps(event, ensure_ascii=False)}", flush=True)


def tool_output_preview(output: str) -> str:
    compact = " ".join(output.split())
    if len(compact) <= MAX_EVENT_PREVIEW_CHARS:
        return compact
    return f"{compact[: MAX_EVENT_PREVIEW_CHARS - 1].rstrip()}…"


def text_content(value: Any) -> str:
    """Normalize text-only content variants returned by OpenRouter providers."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(text_content(part) for part in value)
    if not isinstance(value, dict):
        return ""

    part_type = str(value.get("type") or "").lower()
    if part_type in {"reasoning", "thinking", "tool_call", "tool_use"}:
        return ""
    for key in ("text", "output_text", "content", "value"):
        if key in value:
            return text_content(value[key])
    return ""


def legacy_tool_calls(value: Any, id_prefix: str = "legacy") -> list[dict[str, Any]]:
    """Normalize the XML-like tool syntax emitted by some OpenRouter providers."""
    content = text_content(value).replace("\\_", "_")
    blocks = re.findall(r"<tool_call>(.*?)</tool_call>", content, flags=re.DOTALL | re.IGNORECASE)
    if not blocks:
        return []
    allowed = {tool["function"]["name"] for tool in TOOLS}
    calls: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        name_match = re.match(r"\s*([a-zA-Z][a-zA-Z0-9_]*)", block)
        if not name_match or name_match.group(1) not in allowed:
            return []
        arguments: dict[str, Any] = {}
        pairs = re.findall(
            r"<arg_key>\s*(.*?)\s*</arg_key>\s*"
            r"<arg_value>\s*(.*?)\s*</arg_value>",
            block,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for raw_key, raw_value in pairs:
            key = re.sub(r"\s+", "", raw_key)
            if not key:
                return []
            value = raw_value.strip()
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = value
            arguments[key] = decoded
        calls.append(
            {
                "id": f"{id_prefix}-{index}",
                "type": "function",
                "function": {
                    "name": name_match.group(1),
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )
    return calls


def contains_tool_markup(value: Any) -> bool:
    content = text_content(value).replace("\\_", "_").casefold()
    return "<tool_call" in content or "<arg_key" in content or "<arg_value" in content


def tool_arguments(value: Any) -> tuple[str, dict[str, Any]]:
    """Return arguments in both provider-facing JSON and host-facing mapping forms."""
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False), value
    raw = value if isinstance(value, str) else "{}"
    try:
        decoded = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return raw, {"raw": raw}
    if isinstance(decoded, dict):
        return raw, decoded
    return raw, {"raw": raw}


def _call_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


def tool_call_reason(
    name: str,
    arguments: dict[str, Any],
    provided_reason: Any = None,
) -> str:
    if isinstance(provided_reason, str):
        reason = " ".join(provided_reason.split())
        if reason:
            return reason if len(reason) <= 180 else f"{reason[:179].rstrip()}…"

    dataset = str(arguments.get("dataset") or "the selected dataset")
    if name == "search_eurostat":
        query = " ".join(str(arguments.get("query") or "the requested measure").split())
        return f"Find candidate Eurostat datasets for “{query[:100]}”."
    if name == "inspect_dimensions":
        return f"Check {dataset} dimensions and valid filter codes before fetching values."
    if name == "fetch_eurostat":
        return f"Retrieve the filtered observations needed from {dataset}."
    if name == "publish_result":
        result_ids = arguments.get("result_ids")
        selected = ", ".join(str(value) for value in result_ids or []) or "the requested data"
        if isinstance(result_ids, list) and len(result_ids) == 2:
            return f"Pair and publish {selected} as the data supporting this answer."
        return f"Publish {selected} as the data supporting this answer."
    return f"Run {name.replace('_', ' ')} to support the answer."


def _dimension_catalog(output: str) -> dict[str, dict[str, Any]] | None:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list):
        return None
    catalog: dict[str, dict[str, Any]] = {}
    for dimension in dimensions:
        if not isinstance(dimension, dict) or not isinstance(dimension.get("id"), str):
            continue
        samples = dimension.get("sample_categories")
        if not isinstance(samples, list):
            samples = []
        codes = [
            str(item["code"])
            for item in samples
            if isinstance(item, dict) and item.get("code") is not None
        ]
        size = dimension.get("size")
        catalog[dimension["id"]] = {
            "codes": codes,
            "size": size if isinstance(size, int) else len(codes),
            "complete": isinstance(size, int) and size <= len(codes),
        }
    return catalog


def validate_fetch_arguments(
    arguments: dict[str, Any],
    dimension_catalogs: dict[str, dict[str, dict[str, Any]]],
) -> str | None:
    dataset = str(arguments.get("dataset") or "")
    catalog = dimension_catalogs.get(dataset)
    if not catalog:
        return None

    invalid: list[str] = []
    selected_values: dict[str, set[str]] = {}
    for raw_param in arguments.get("params", []) or []:
        key, separator, raw_values = str(raw_param).partition("=")
        if not separator or not key or not raw_values:
            invalid.append(f"{raw_param!r} is not in key=value form")
            continue
        dimension = catalog.get(key)
        if not dimension:
            invalid.append(f"{key!r} is not a dimension in {dataset}")
            continue
        selected_values.setdefault(key, set()).update(
            part for part in raw_values.split(",") if part
        )
        if not dimension["complete"]:
            continue
        allowed = dimension["codes"]
        for value in (part for part in raw_values.split(",") if part):
            if value in allowed:
                continue
            suggestions = difflib.get_close_matches(value, allowed, n=3, cutoff=0.45)
            hint = f"; closest valid codes: {', '.join(suggestions)}" if suggestions else ""
            invalid.append(f"{key}={value} is invalid{hint}")
    if not invalid:
        explicit_times = {
            str(value) for value in arguments.get("time", []) or [] if str(value)
        }
        explicit_times.update(selected_values.get("time", set()))
        if len(explicit_times) > MAX_TIME_PERIODS:
            return f"ERROR: At most {MAX_TIME_PERIODS} explicit time periods may be requested."
        raw_last_time_period = arguments.get("last_time_period")
        try:
            last_time_period = (
                int(raw_last_time_period) if raw_last_time_period is not None else None
            )
        except (TypeError, ValueError):
            return "ERROR: last_time_period must be an integer."
        if isinstance(raw_last_time_period, bool) or (
            last_time_period is not None and not 1 <= last_time_period <= MAX_TIME_PERIODS
        ):
            return (
                f"ERROR: last_time_period must be between 1 and {MAX_TIME_PERIODS}."
            )
        if explicit_times and last_time_period is not None:
            return (
                "ERROR: Explicit time values and last_time_period are mutually exclusive. "
                "Choose exact time values or the latest N periods, not both."
            )
        if not explicit_times and last_time_period is None:
            return (
                f"ERROR: A bounded time filter is required for {dataset}. Pass time values or "
                "last_time_period before fetching."
            )

        estimate = 1
        for dimension_id, dimension in catalog.items():
            if dimension_id == "time":
                selected_count = len(explicit_times) or last_time_period
            elif dimension_id in selected_values:
                selected_count = len(selected_values[dimension_id])
            else:
                selected_count = int(dimension.get("size") or 0)
            estimate *= max(0, selected_count)
            if estimate > MAX_ESTIMATED_CELLS:
                return (
                    f"ERROR: Filtered query for {dataset} is too broad ({estimate} estimated "
                    f"cells; limit {MAX_ESTIMATED_CELLS}). Narrow the dimension filters."
                )
        if "time" not in catalog:
            estimate *= len(explicit_times) or last_time_period
        if estimate > MAX_ESTIMATED_CELLS:
            return (
                f"ERROR: Filtered query for {dataset} is too broad ({estimate} estimated cells; "
                f"limit {MAX_ESTIMATED_CELLS}). Narrow the dimension filters."
            )
        return None
    return (
        f"ERROR: Invalid filters for {dataset}: {'; '.join(invalid)}. "
        "Use codes returned by inspect_dimensions and retry the fetch without another search."
    )


def _zero_row_error(arguments: dict[str, Any]) -> str:
    dataset = str(arguments.get("dataset") or "the dataset")
    return (
        f"ERROR: The filtered query for {dataset} returned zero observations. Re-check the "
        "dimension codes and time selection from inspect_dimensions; adjust the filters without "
        "repeating the catalogue search."
    )
