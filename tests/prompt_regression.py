from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

from app.sandbox_agent import call_tool, openrouter_chat, run


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "tests" / "prompt_scenarios"
CASSETTE_DIR = ROOT / "tests" / "prompt_cassettes"
SCHEMA_VERSION = 1
TOOL_MARKUP = re.compile(r"<(?:tool_call|arg_key|arg_value)\b", re.IGNORECASE)


class ScenarioFailure(AssertionError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioFailure(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ScenarioFailure(f"{path}: top-level value must be an object")
    return value


def load_scenario(path: Path) -> dict[str, Any]:
    scenario = _read_json(path)
    if scenario.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioFailure(f"{path}: schema_version must be {SCHEMA_VERSION}")
    scenario_id = scenario.get("id")
    turns = scenario.get("turns")
    if not isinstance(scenario_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", scenario_id):
        raise ScenarioFailure(f"{path}: id must contain lowercase letters, digits, '_' or '-'")
    if path.stem != scenario_id:
        raise ScenarioFailure(f"{path}: filename must match scenario id {scenario_id!r}")
    if not isinstance(turns, list) or not turns:
        raise ScenarioFailure(f"{path}: turns must be a non-empty array")
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict) or not isinstance(turn.get("prompt"), str):
            raise ScenarioFailure(f"{path}: turn {index} requires a string prompt")
        if not isinstance(turn.get("expect", {}), dict):
            raise ScenarioFailure(f"{path}: turn {index} expect must be an object")
    tags = scenario.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ScenarioFailure(f"{path}: tags must be an array of strings")
    return scenario


def load_cassette(path: Path, scenario_id: str, turn_count: int) -> dict[str, Any]:
    cassette = _read_json(path)
    if cassette.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioFailure(f"{path}: schema_version must be {SCHEMA_VERSION}")
    if cassette.get("scenario_id") != scenario_id:
        raise ScenarioFailure(f"{path}: scenario_id must be {scenario_id!r}")
    turns = cassette.get("turns")
    if not isinstance(turns, list) or len(turns) != turn_count:
        raise ScenarioFailure(f"{path}: expected {turn_count} recorded turns")
    return cassette


def _sanitize_model_value(value: Any) -> Any:
    if isinstance(value, list):
        cleaned = []
        for item in value:
            if isinstance(item, dict) and str(item.get("type") or "").casefold() in {
                "reasoning",
                "thinking",
            }:
                continue
            cleaned.append(_sanitize_model_value(item))
        return cleaned
    if not isinstance(value, dict):
        return value
    return {
        key: _sanitize_model_value(item)
        for key, item in value.items()
        if key not in {"reasoning", "reasoning_details", "system_fingerprint"}
    }


class RecordingChat:
    def __init__(self) -> None:
        self.responses: list[dict[str, Any]] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, Any]],
        available_tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        response = openrouter_chat(model, messages, available_tools)
        sanitized = _sanitize_model_value(response)
        self.responses.append(sanitized)
        return response


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, name: str, raw_arguments: str) -> str:
        output = call_tool(name, raw_arguments)
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"raw": raw_arguments}
        self.calls.append({"name": name, "arguments": arguments, "output": output})
        return output


class ReplayChat:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = copy.deepcopy(responses)
        self.index = 0

    def __call__(
        self,
        _model: str,
        _messages: list[dict[str, Any]],
        _available_tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.index >= len(self.responses):
            raise ScenarioFailure("cassette exhausted before the model returned a final answer")
        response = copy.deepcopy(self.responses[self.index])
        self.index += 1
        return response

    def assert_consumed(self) -> None:
        if self.index != len(self.responses):
            raise ScenarioFailure(
                f"cassette contains {len(self.responses) - self.index} unused model response(s)"
            )


class ReplayTools:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = copy.deepcopy(calls)
        self.index = 0

    def __call__(self, name: str, raw_arguments: str) -> str:
        if self.index >= len(self.calls):
            raise ScenarioFailure(f"unexpected tool call {name}")
        expected = self.calls[self.index]
        self.index += 1
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"raw": raw_arguments}
        if expected.get("name") != name or expected.get("arguments") != arguments:
            raise ScenarioFailure(
                "unexpected tool call "
                f"{name}({arguments!r}); expected "
                f"{expected.get('name')}({expected.get('arguments')!r})"
            )
        output = expected.get("output")
        if isinstance(output, (dict, list)):
            return json.dumps(output, ensure_ascii=False)
        if isinstance(output, str):
            return output
        raise ScenarioFailure(f"recorded output for {name} must be JSON or a string")

    def assert_consumed(self) -> None:
        if self.index != len(self.calls):
            raise ScenarioFailure(f"cassette contains {len(self.calls) - self.index} unused tool call(s)")


def _model_name() -> str:
    model = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENAI_MODEL") or "openai/gpt-4.1-mini"
    return model if "/" in model else f"openai/{model}"


def _row_matches(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(row.get(key) == value for key, value in expected.items())


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ScenarioFailure(f"{label}: expected {expected!r}, got {actual!r}")


def _assert_row_count(rows: list[dict[str, Any]], expected: Any) -> None:
    if isinstance(expected, int):
        _assert_equal(len(rows), expected, "row_count")
        return
    if not isinstance(expected, dict):
        raise ScenarioFailure("row_count must be an integer or an object with min/max")
    if "min" in expected and len(rows) < int(expected["min"]):
        raise ScenarioFailure(f"row_count: expected at least {expected['min']}, got {len(rows)}")
    if "max" in expected and len(rows) > int(expected["max"]):
        raise ScenarioFailure(f"row_count: expected at most {expected['max']}, got {len(rows)}")


def _matching_numeric_rows(
    rows: list[dict[str, Any]],
    condition: dict[str, Any],
) -> list[dict[str, Any]]:
    where = condition.get("where", {})
    if not isinstance(where, dict):
        raise ScenarioFailure("numeric.where must be an object")
    return [row for row in rows if _row_matches(row, where)]


def _assert_numeric(rows: list[dict[str, Any]], condition: dict[str, Any]) -> None:
    field = condition.get("field", "value")
    operation = condition.get("op")
    matching = _matching_numeric_rows(rows, condition)
    values = [
        float(row[field])
        for row in matching
        if field in row and isinstance(row[field], (int, float)) and not isinstance(row[field], bool)
    ]
    if not values:
        raise ScenarioFailure(f"numeric assertion found no values for field {field!r}")
    if operation == "any_nonzero" and not any(value != 0 for value in values):
        raise ScenarioFailure(f"numeric {field}: expected at least one non-zero value")
    elif operation == "all_nonzero" and not all(value != 0 for value in values):
        raise ScenarioFailure(f"numeric {field}: expected every value to be non-zero")
    elif operation == "min" and min(values) < float(condition["value"]):
        raise ScenarioFailure(
            f"numeric {field}: expected minimum >= {condition['value']}, got {min(values)}"
        )
    elif operation == "max" and max(values) > float(condition["value"]):
        raise ScenarioFailure(
            f"numeric {field}: expected maximum <= {condition['value']}, got {max(values)}"
        )
    elif operation not in {"any_nonzero", "all_nonzero", "min", "max"}:
        raise ScenarioFailure(f"unsupported numeric operation {operation!r}")


def assert_turn(
    response: dict[str, Any],
    expected: dict[str, Any],
    *,
    forbid_tool_markup: bool = True,
    forbid_duplicate_tools: bool = True,
) -> None:
    supported = {
        "result",
        "dataset",
        "forbidden_datasets",
        "filters",
        "row_count",
        "required_rows",
        "row_unique_by",
        "numeric",
        "chart",
        "tools",
        "no_tool_errors",
        "answer_contains",
        "answer_not_contains",
        "answer_regex",
        "warnings_contain",
        "provenance",
    }
    unknown = set(expected) - supported
    if unknown:
        raise ScenarioFailure(f"unsupported assertions: {', '.join(sorted(unknown))}")

    answer = str(response.get("answer") or "")
    if forbid_tool_markup and TOOL_MARKUP.search(answer.replace("\\_", "_")):
        raise ScenarioFailure("answer contains raw tool-call markup")
    for value in expected.get("answer_contains", []):
        if str(value).casefold() not in answer.casefold():
            raise ScenarioFailure(f"answer must contain {value!r}")
    for value in expected.get("answer_not_contains", []):
        if str(value).casefold() in answer.casefold():
            raise ScenarioFailure(f"answer must not contain {value!r}")
    if "answer_regex" in expected and not re.search(str(expected["answer_regex"]), answer, re.I):
        raise ScenarioFailure(f"answer does not match /{expected['answer_regex']}/")

    details = response.get("tool_call_details") or []
    tool_names = [detail.get("name") for detail in details]
    if "tools" in expected:
        _assert_equal(tool_names, expected["tools"], "tools")
    if expected.get("no_tool_errors") and any(detail.get("status") == "error" for detail in details):
        raise ScenarioFailure("one or more tool calls failed")
    if forbid_duplicate_tools:
        seen: set[str] = set()
        for detail in details:
            fingerprint = json.dumps(
                [detail.get("name"), detail.get("arguments")],
                sort_keys=True,
                ensure_ascii=False,
            )
            if fingerprint in seen:
                raise ScenarioFailure(f"duplicate tool call recorded for {detail.get('name')}")
            seen.add(fingerprint)

    result = response.get("result")
    result_expectation = expected.get("result")
    if result_expectation == "null":
        if result is not None:
            raise ScenarioFailure(
                f"result: expected null, got dataset {(result.get('dataset') or {}).get('code')!r}"
            )
        return
    if result_expectation == "present" and not isinstance(result, dict):
        raise ScenarioFailure("result: expected a structured result")
    if not isinstance(result, dict):
        if set(expected) & {
            "dataset",
            "filters",
            "row_count",
            "required_rows",
            "numeric",
            "chart",
            "provenance",
        }:
            raise ScenarioFailure("structured-result assertions require result: present")
        return

    dataset = result.get("dataset") or {}
    if "dataset" in expected:
        _assert_equal(dataset.get("code"), expected["dataset"], "dataset")
    forbidden = set(expected.get("forbidden_datasets", []))
    source_codes = {
        str(item.get("code"))
        for item in ([dataset] + list(result.get("sources") or []))
        if isinstance(item, dict) and item.get("code")
    }
    overlap = forbidden & source_codes
    if overlap:
        raise ScenarioFailure(f"forbidden dataset(s) published: {', '.join(sorted(overlap))}")
    for key, values in expected.get("filters", {}).items():
        _assert_equal((result.get("filters") or {}).get(key), values, f"filter {key}")

    rows = result.get("rows") or []
    if "row_count" in expected:
        _assert_row_count(rows, expected["row_count"])
    for required in expected.get("required_rows", []):
        if not any(_row_matches(row, required) for row in rows):
            raise ScenarioFailure(f"required row not found: {required!r}")
    unique_fields = expected.get("row_unique_by")
    if unique_fields:
        keys = [tuple(row.get(field) for field in unique_fields) for row in rows]
        if len(keys) != len(set(keys)):
            raise ScenarioFailure(f"rows are not unique by {unique_fields!r}")
    for condition in expected.get("numeric", []):
        _assert_numeric(rows, condition)

    if "chart" in expected:
        chart = result.get("chart") or {}
        for key, value in expected["chart"].items():
            _assert_equal(chart.get(key), value, f"chart.{key}")
    warnings = " ".join(str(item) for item in result.get("warnings") or [])
    for value in expected.get("warnings_contain", []):
        if str(value).casefold() not in warnings.casefold():
            raise ScenarioFailure(f"warnings must contain {value!r}")
    if expected.get("provenance"):
        if not dataset.get("code") or not dataset.get("source_url"):
            raise ScenarioFailure("result is missing dataset provenance")
        if not isinstance(result.get("filters"), dict):
            raise ScenarioFailure("result is missing applied filters")


def _initial_messages(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    history = scenario.get("initial_history", [])
    if not isinstance(history, list):
        raise ScenarioFailure("initial_history must be an array")
    return copy.deepcopy(history)


def execute_scenario(
    scenario: dict[str, Any],
    *,
    mode: str,
    cassette: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    messages = _initial_messages(scenario)
    context_result = copy.deepcopy(scenario.get("initial_context_result"))
    responses: list[dict[str, Any]] = []
    recorded_turns: list[dict[str, Any]] = []
    global_expect = scenario.get("global_expect", {})
    if not isinstance(global_expect, dict):
        raise ScenarioFailure("global_expect must be an object")

    for index, turn in enumerate(scenario["turns"]):
        if mode == "replay":
            assert cassette is not None
            recorded = cassette["turns"][index]
            replay_chat = ReplayChat(recorded.get("chat_responses", []))
            replay_tools = ReplayTools(recorded.get("tool_calls", []))
            chat_client: Callable[..., dict[str, Any]] = replay_chat
            tool_executor: Callable[[str, str], str] = replay_tools
        elif mode == "record":
            recording_chat = RecordingChat()
            recording_tools = RecordingTools()
            chat_client = recording_chat
            tool_executor = recording_tools
        elif mode == "live":
            chat_client = openrouter_chat
            tool_executor = call_tool
        else:
            raise ScenarioFailure(f"unsupported execution mode {mode!r}")

        prompt = turn["prompt"]
        payload = {
            "query": prompt,
            "history": [
                {"role": item["role"], "content": item["content"]}
                for item in messages[-6:]
                if item.get("role") in {"user", "assistant"} and item.get("content")
            ],
            "summary": "",
            "context_result": context_result,
            "model": _model_name(),
        }
        response = run(payload, chat_client=chat_client, tool_executor=tool_executor)
        if mode == "replay":
            replay_chat.assert_consumed()
            replay_tools.assert_consumed()
        elif mode == "record":
            recorded_turns.append(
                {
                    "chat_responses": recording_chat.responses,
                    "tool_calls": recording_tools.calls,
                }
            )

        try:
            assert_turn(
                response,
                turn.get("expect", {}),
                forbid_tool_markup=global_expect.get("forbid_tool_markup", True),
                forbid_duplicate_tools=global_expect.get("forbid_duplicate_tools", True),
            )
        except ScenarioFailure as exc:
            raise ScenarioFailure(
                f"turn {index + 1} ({prompt!r}): {exc}\n"
                f"rerun: uv run python -m tests.prompt_regression {mode} {scenario['id']}"
            ) from exc

        messages.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response["answer"], "result": response.get("result")},
            ]
        )
        result = response.get("result")
        if isinstance(result, dict) and result.get("rows"):
            context_result = result
        responses.append(response)

    recorded_cassette = (
        {
            "schema_version": SCHEMA_VERSION,
            "scenario_id": scenario["id"],
            "turns": recorded_turns,
        }
        if mode == "record"
        else None
    )
    return responses, recorded_cassette


def _scenario_paths(scenario_id: str | None, tag: str | None) -> list[Path]:
    paths = sorted(SCENARIO_DIR.glob("*.json"))
    if scenario_id:
        paths = [path for path in paths if path.stem == scenario_id]
        if not paths:
            raise ScenarioFailure(f"unknown scenario {scenario_id!r}")
    if tag:
        paths = [path for path in paths if tag in load_scenario(path).get("tags", [])]
        if not paths:
            raise ScenarioFailure(f"no scenarios have tag {tag!r}")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Eurostat Lens prompt regression scenarios.")
    parser.add_argument("mode", choices=["replay", "live", "record"])
    parser.add_argument("scenario_id", nargs="?")
    parser.add_argument("--tag")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Allow record mode to replace an existing cassette.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.update and args.mode != "record":
        print("--update is only valid with record mode", file=sys.stderr)
        return 2
    try:
        paths = _scenario_paths(args.scenario_id, args.tag)
    except ScenarioFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    failures = 0
    for path in paths:
        try:
            scenario = load_scenario(path)
            cassette_path = CASSETTE_DIR / f"{scenario['id']}.json"
            if args.mode == "replay":
                cassette = load_cassette(cassette_path, scenario["id"], len(scenario["turns"]))
                execute_scenario(scenario, mode="replay", cassette=cassette)
            elif args.mode == "live":
                execute_scenario(scenario, mode="live")
            else:
                if cassette_path.exists() and not args.update:
                    raise ScenarioFailure(
                        f"{cassette_path} already exists; pass --update to replace it"
                    )
                _, recorded = execute_scenario(scenario, mode="record")
                assert recorded is not None
                CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
                cassette_path.write_text(
                    json.dumps(recorded, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            print(f"PASS {scenario['id']}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {path.stem}: {exc}", file=sys.stderr)
    if failures:
        print(f"{failures} prompt scenario(s) failed", file=sys.stderr)
        return 1
    print(f"{len(paths)} prompt scenario(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
