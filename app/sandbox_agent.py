from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
EUROSTAT_HELPER = ROOT / "eurostat_api.py"
SKILL = ROOT / "SKILL.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOOL_CHARS = 14000


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_eurostat",
            "description": "Search Eurostat table-of-contents metadata for candidate datasets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_dimensions",
            "description": "Inspect dimensions and sample categories for a Eurostat dataset code.",
            "parameters": {
                "type": "object",
                "properties": {"dataset": {"type": "string"}},
                "required": ["dataset"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_eurostat",
            "description": "Fetch a bounded Eurostat data slice as flattened JSON rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Dimension filter in key=value form, for example geo=DE or sex=T.",
                        },
                    },
                    "last_time_period": {"type": "integer", "minimum": 1, "maximum": 20},
                    "time": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["dataset"],
                "additionalProperties": False,
            },
        },
    },
]


def run_helper(args: list[str]) -> str:
    completed = subprocess.run(
        ["python3", str(EUROSTAT_HELPER), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = completed.stdout
    if completed.returncode != 0:
        output = f"ERROR:\n{completed.stderr or completed.stdout}"
    if len(output) > MAX_TOOL_CHARS:
        return output[:MAX_TOOL_CHARS] + "\n\n[truncated]"
    return output


def call_tool(name: str, raw_arguments: str) -> str:
    try:
        args = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid JSON arguments: {exc}"

    if name == "search_eurostat":
        return run_helper(["search", str(args["query"]), "--limit", str(args.get("limit", 12))])

    if name == "inspect_dimensions":
        return run_helper(["dimensions", str(args["dataset"])])

    if name == "fetch_eurostat":
        command = ["fetch", str(args["dataset"]), "--output", "json"]
        for param in args.get("params", []) or []:
            command.extend(["--param", str(param)])
        if args.get("last_time_period"):
            command.extend(["--last-time-period", str(args["last_time_period"])])
        for time_value in args.get("time", []) or []:
            command.extend(["--time", str(time_value)])
        return run_helper(command)

    return f"Unknown tool: {name}"


def openrouter_chat(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps({"model": model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"}).encode()
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Eurostat E2B Chat",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail[:1000]}") from exc


def build_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    skill_text = SKILL.read_text()
    system = f"""
You are a Eurostat data agent running inside an E2B sandbox.

Follow this local skill exactly:

{skill_text}

Use the tools to search, inspect, and fetch Eurostat data. Prefer small bounded queries. Your final answer must be concise, cite the dataset code and filters used, mention the latest period used when relevant, and include a compact Markdown table of the observations that support the answer.
""".strip()

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for item in payload.get("history", [])[-8:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": payload["query"]})
    return messages


def run(payload: dict[str, Any]) -> str:
    model = payload.get("model") or "openai/gpt-4.1-mini"
    messages = build_messages(payload)

    for _ in range(8):
        response = openrouter_chat(model, messages)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content", "").strip()

        messages.append(message)
        for tool_call in tool_calls:
            function = tool_call["function"]
            tool_output = call_tool(function["name"], function.get("arguments", "{}"))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_output,
                }
            )

    return "I could not complete the Eurostat lookup within the tool-call limit. Please narrow the question."


def main() -> None:
    payload = json.loads(Path(sys.argv[1]).read_text())
    answer = run(payload)
    print(json.dumps({"answer": answer}, ensure_ascii=False))


if __name__ == "__main__":
    main()
