from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


try:
    from .agent_config import (
        EVENT_PREFIX,
        MAX_ESTIMATED_CELLS,
        MAX_EVENT_PREVIEW_CHARS,
        MAX_TOOL_CALLS,
        MAX_TOOL_ROUNDS,
        TOOL_CALL_LIMITS,
        TOOLS,
    )
except ImportError:  # Support direct execution by local_agent.py.
    from agent_config import (
        EVENT_PREFIX,
        MAX_ESTIMATED_CELLS,
        MAX_EVENT_PREVIEW_CHARS,
        MAX_TOOL_CALLS,
        MAX_TOOL_ROUNDS,
        TOOL_CALL_LIMITS,
        TOOLS,
    )

try:
    from .agent_tools import (
        _call_fingerprint,
        _dimension_catalog,
        _zero_row_error,
        call_tool,
        contains_tool_markup,
        emit_event,
        legacy_tool_calls,
        text_content,
        tool_arguments,
        tool_call_reason,
        tool_content_for_model,
        tool_output_preview,
        validate_fetch_arguments,
    )
except ImportError:  # Support direct execution by local_agent.py.
    from agent_tools import (
        _call_fingerprint,
        _dimension_catalog,
        _zero_row_error,
        call_tool,
        contains_tool_markup,
        emit_event,
        legacy_tool_calls,
        text_content,
        tool_arguments,
        tool_call_reason,
        tool_content_for_model,
        tool_output_preview,
        validate_fetch_arguments,
    )


try:
    from .agent_results import (
        _paired_chart_choice,
        _validated_chart_choice,
        build_scatter_result,
        build_source_tables,
        build_structured_result,
        response_result,
        reuse_context_result,
    )
except ImportError:  # Support direct execution by local_agent.py.
    from agent_results import (
        _paired_chart_choice,
        _validated_chart_choice,
        build_scatter_result,
        build_source_tables,
        build_structured_result,
        response_result,
        reuse_context_result,
    )


try:
    from .agent_model import build_messages, openrouter_chat
except ImportError:  # Support direct execution by local_agent.py.
    from agent_model import build_messages, openrouter_chat


def run(
    payload: dict[str, Any],
    chat_client: Any = None,
    tool_executor: Any = None,
) -> dict[str, Any]:
    model = payload["model"]
    context_result = payload.get("context_result")
    messages = build_messages(payload)
    chat = chat_client or openrouter_chat
    execute_tool = tool_executor or call_tool
    last_fetch: dict[str, Any] | None = None
    fetch_records: list[dict[str, Any]] = []
    composed_result: dict[str, Any] | None = None
    chart_choice: dict[str, Any] | None = None
    selected_result_id: str | None = None
    tool_call_count = 0
    tool_call_details: list[dict[str, Any]] = []
    tool_counts: dict[str, int] = {}
    executed_outputs: dict[str, str] = {}
    dimension_catalogs: dict[str, dict[str, dict[str, Any]]] = {}
    force_final = False

    for _ in range(MAX_TOOL_ROUNDS):
        response = chat(model, messages, [] if force_final else None)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            tool_calls = legacy_tool_calls(message.get("content"), f"legacy-{tool_call_count + 1}")
            if tool_calls:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                }
            elif contains_tool_markup(message.get("content")):
                return {
                    "answer": (
                        "I could not safely interpret the model's tool request. "
                        "Please try the request again."
                    ),
                    "result": None,
                    "tool_calls": tool_call_count,
                    "tool_call_details": tool_call_details,
                }
        if not tool_calls:
            answer = text_content(message.get("content")).strip()
            return {
                "answer": answer or "I could not complete the Eurostat request.",
                "result": response_result(
                    last_fetch,
                    context_result,
                    chart_choice,
                    composed_result,
                    fetch_records,
                    selected_result_id,
                ),
                "tool_calls": tool_call_count,
                "tool_call_details": tool_call_details,
            }

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call["function"]
            raw_arguments, parsed_arguments = tool_arguments(function.get("arguments", "{}"))
            provided_reason = parsed_arguments.pop("reason", None)
            if provided_reason is not None:
                raw_arguments = json.dumps(parsed_arguments, ensure_ascii=False)
            function["arguments"] = raw_arguments
            function_name = str(function.get("name") or "unknown_tool")
            fingerprint = _call_fingerprint(function_name, parsed_arguments)

            if function_name != "publish_result" and fingerprint in executed_outputs:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": (
                            "Identical call already executed; reused the previous result without a "
                            f"new tool invocation.\n\n{tool_content_for_model(executed_outputs[fingerprint])}"
                        ),
                    }
                )
                continue

            call_limit = TOOL_CALL_LIMITS.get(function_name)
            if tool_call_count >= MAX_TOOL_CALLS or (
                call_limit is not None and tool_counts.get(function_name, 0) >= call_limit
            ):
                if tool_call_count >= MAX_TOOL_CALLS:
                    limit_message = (
                        f"ERROR: Total tool budget exhausted after {MAX_TOOL_CALLS} unique calls."
                    )
                else:
                    limit_message = (
                        f"ERROR: {function_name} budget exhausted after {call_limit} unique calls. "
                        "Stop retrying this tool and answer with the available evidence or ask the "
                        "user to choose a measure."
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": limit_message,
                    }
                )
                force_final = True
                continue

            tool_call_count += 1
            tool_counts[function_name] = tool_counts.get(function_name, 0) + 1

            detail = {
                "id": str(tool_call.get("id") or f"tool-call-{tool_call_count}"),
                "index": tool_call_count,
                "name": function_name,
                "reason": tool_call_reason(function_name, parsed_arguments, provided_reason),
                "arguments": parsed_arguments,
                "status": "running",
                "duration_ms": None,
                "result_preview": "",
            }
            emit_event({"type": "tool_call", "phase": "started", "call": detail})
            started_at = time.perf_counter()
            validation_error = (
                validate_fetch_arguments(parsed_arguments, dimension_catalogs)
                if function_name == "fetch_eurostat"
                else None
            )
            if validation_error:
                tool_output = validation_error
            elif function_name == "publish_result":
                requested_ids = parsed_arguments.get("result_ids")
                requested_ids = (
                    [str(result_id) for result_id in requested_ids]
                    if isinstance(requested_ids, list)
                    else []
                )
                requested_chart = parsed_arguments.get("chart")
                context_rows = (
                    context_result.get("rows")
                    if isinstance(context_result, dict)
                    else None
                )
                if len(requested_ids) == 2:
                    publication_choice = {
                        key: value
                        for key, value in parsed_arguments.items()
                        if key not in {"chart", "reason"}
                    }
                    candidate_result = build_scatter_result(fetch_records, publication_choice)
                    candidate_chart = None
                    if candidate_result and isinstance(requested_chart, dict):
                        paired_chart_choice = _paired_chart_choice(
                            candidate_result,
                            requested_chart,
                        )
                        candidate_chart = _validated_chart_choice(
                            candidate_result["rows"],
                            candidate_result["dataset"]["title"],
                            paired_chart_choice,
                        )
                    if candidate_result and (requested_chart is None or candidate_chart):
                        composed_result = candidate_result
                        chart_choice = candidate_chart
                        selected_result_id = None
                        tool_output = json.dumps(
                            {
                                "accepted": True,
                                "result_ids": requested_ids,
                                "matched_rows": len(candidate_result["rows"]),
                                "chart_type": (candidate_chart or candidate_result["chart"])["type"],
                                "message": "Paired result is selected for publication.",
                            }
                        )
                    else:
                        tool_output = (
                            "ERROR: Could not publish the paired result. Confirm both result IDs, "
                            "join keys, one observation per key, and compatible chart fields."
                        )
                elif len(requested_ids) == 1:
                    requested_result_id = requested_ids[0]
                    selected_fetch = next(
                        (
                            record
                            for record in fetch_records
                            if record.get("result_id") == requested_result_id
                        ),
                        None,
                    )
                    valid_context = (
                        requested_result_id == "context"
                        and isinstance(context_rows, list)
                        and bool(context_rows)
                    )
                    if selected_fetch:
                        candidate_result = build_structured_result(selected_fetch)
                    elif valid_context:
                        candidate_result = reuse_context_result(context_result)
                    else:
                        candidate_result = None
                    candidate_chart = None
                    if candidate_result and isinstance(requested_chart, dict):
                        candidate_chart = _validated_chart_choice(
                            candidate_result["rows"],
                            candidate_result["dataset"]["title"],
                            requested_chart,
                        )
                    if candidate_result and (requested_chart is None or candidate_chart):
                        selected_result_id = requested_result_id
                        chart_choice = candidate_chart
                        composed_result = None
                        tool_output = json.dumps(
                            {
                                "accepted": True,
                                "result_ids": requested_ids,
                                "chart_type": (
                                    candidate_chart or candidate_result["chart"]
                                )["type"],
                                "message": "Result is selected for publication.",
                            }
                        )
                    else:
                        available_ids = [
                            str(record.get("result_id"))
                            for record in fetch_records
                            if record.get("result_id")
                        ]
                        if isinstance(context_rows, list) and context_rows:
                            available_ids.append("context")
                        tool_output = (
                            "ERROR: Could not publish the requested result or chart. "
                            f"Available result IDs: {', '.join(available_ids) or 'none'}."
                        )
                else:
                    tool_output = (
                        "ERROR: publish_result requires one result ID, or two result IDs for a "
                        "paired relationship result."
                    )
            else:
                try:
                    tool_output = execute_tool(function_name, raw_arguments)
                except Exception as exc:
                    tool_output = f"ERROR: {function_name} failed safely: {exc}"

            parsed_output: dict[str, Any] | None = None
            if function_name == "fetch_eurostat" and not tool_output.startswith("ERROR:"):
                try:
                    candidate_output = json.loads(tool_output)
                except json.JSONDecodeError:
                    candidate_output = None
                if isinstance(candidate_output, dict):
                    parsed_output = candidate_output
                    rows = parsed_output.get("rows")
                    if isinstance(rows, list) and not rows:
                        tool_output = _zero_row_error(parsed_arguments)
                        parsed_output = None
                    elif isinstance(rows, list):
                        result_id = f"fetch-{len(fetch_records) + 1}"
                        parsed_output = {"result_id": result_id, **parsed_output}
                        tool_output = json.dumps(parsed_output, ensure_ascii=False)

            detail["duration_ms"] = max(0, round((time.perf_counter() - started_at) * 1000))
            detail["status"] = (
                "error"
                if tool_output.startswith(("ERROR:", "Invalid JSON arguments:", "Unknown tool:"))
                else "completed"
            )
            detail["result_preview"] = tool_output_preview(tool_output)
            executed_outputs[fingerprint] = tool_output
            tool_call_details.append(detail)
            emit_event({"type": "tool_call", "phase": "completed", "call": detail})
            if function_name == "inspect_dimensions" and not tool_output.startswith("ERROR:"):
                catalog = _dimension_catalog(tool_output)
                dataset = str(parsed_arguments.get("dataset") or "")
                if catalog and dataset:
                    dimension_catalogs[dataset] = catalog
            if function_name == "fetch_eurostat" and parsed_output is not None:
                last_fetch = {
                    "result_id": parsed_output["result_id"],
                    "arguments": parsed_arguments,
                    "output": parsed_output,
                }
                fetch_records.append(last_fetch)
                composed_result = None
                chart_choice = None
                selected_result_id = None
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_content_for_model(tool_output),
                }
            )
        if tool_call_count >= MAX_TOOL_CALLS:
            force_final = True

    return {
        "answer": (
            f"I could not complete the Eurostat lookup within {MAX_TOOL_ROUNDS} "
            "model/tool rounds. Please narrow the question."
        ),
        "result": response_result(
            last_fetch,
            context_result,
            chart_choice,
            composed_result,
            fetch_records,
            selected_result_id,
        ),
        "tool_calls": tool_call_count,
        "tool_call_details": tool_call_details,
    }


def main() -> None:
    payload = json.loads(Path(sys.argv[1]).read_text())
    response = run(payload)
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
