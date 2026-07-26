from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from e2b import Sandbox

from .sandbox_agent import EVENT_PREFIX


SANDBOX_DIR = "/home/user/eurostat_agent"


class AgentError(RuntimeError):
    """Raised when the sandboxed agent cannot complete the request."""


@dataclass(frozen=True)
class AgentConfig:
    model: str
    skill_path: Path
    chart_reference_path: Path
    helper_path: Path
    sandbox_agent_path: Path


@dataclass(frozen=True)
class AgentResult:
    answer: str
    result: dict[str, Any] | None
    tool_calls: int
    tool_call_details: list[dict[str, Any]]
    stdout: str


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise AgentError(f"Missing {name}. Add it to your environment before starting the app.")
    return value


def _command_text(result: Any, attr: str) -> str:
    value = getattr(result, attr, "")
    if value is None:
        return ""
    return str(value)


def run_eurostat_agent(
    query: str,
    history: list[dict[str, str]],
    summary: str,
    config: AgentConfig,
    context_result: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> AgentResult:
    _require_env("E2B_API_KEY")
    openrouter_api_key = _require_env("OPENROUTER_API_KEY")

    for path in (
        config.skill_path,
        config.chart_reference_path,
        config.helper_path,
        config.sandbox_agent_path,
    ):
        if not path.exists():
            raise AgentError(f"Required file is missing: {path}")

    payload = {
        "query": query,
        "history": history,
        "summary": summary,
        "context_result": context_result,
        "model": config.model,
    }
    def handle_stdout(data: Any) -> None:
        line = getattr(data, "line", None)
        text = str(line if line is not None else data)
        if not on_event:
            return
        for candidate in text.splitlines():
            if not candidate.startswith(EVENT_PREFIX):
                continue
            try:
                event = json.loads(candidate.removeprefix(EVENT_PREFIX))
            except json.JSONDecodeError:
                continue
            try:
                on_event(event)
            except Exception:
                # UI telemetry must never interrupt the data investigation.
                continue

    try:
        sandbox = Sandbox.create(timeout=180)
        sandbox.files.write(f"{SANDBOX_DIR}/SKILL.md", config.skill_path.read_text())
        sandbox.files.write(
            f"{SANDBOX_DIR}/chart-selection.md",
            config.chart_reference_path.read_text(),
        )
        sandbox.files.write(f"{SANDBOX_DIR}/eurostat_api.py", config.helper_path.read_text())
        sandbox.files.write(f"{SANDBOX_DIR}/sandbox_agent.py", config.sandbox_agent_path.read_text())
        sandbox.files.write(f"{SANDBOX_DIR}/request.json", json.dumps(payload))

        result = sandbox.commands.run(
            f"python3 {SANDBOX_DIR}/sandbox_agent.py {SANDBOX_DIR}/request.json",
            cwd=SANDBOX_DIR,
            envs={
                "OPENROUTER_API_KEY": openrouter_api_key,
                "STREAM_TOOL_EVENTS": "1" if on_event else "0",
            },
            on_stdout=handle_stdout if on_event else None,
            timeout=180,
        )
    except Exception as exc:  # E2B exposes several transport/runtime exceptions.
        raise AgentError(f"E2B sandbox run failed: {exc}") from exc

    stdout = _command_text(result, "stdout")
    stderr = _command_text(result, "stderr")
    if stderr.strip():
        raise AgentError(f"Sandbox agent reported an error: {stderr.strip()}")

    result_output = "\n".join(
        line for line in stdout.splitlines() if not line.startswith(EVENT_PREFIX)
    ).strip()
    try:
        data = json.loads(result_output)
    except json.JSONDecodeError as exc:
        raise AgentError(f"Sandbox returned non-JSON output: {stdout[:1000]}") from exc

    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise AgentError("Sandbox agent did not return an answer.")

    structured_result = data.get("result")
    if structured_result is not None and not isinstance(structured_result, dict):
        raise AgentError("Sandbox agent returned an invalid structured result.")

    tool_calls = data.get("tool_calls", 0)
    if not isinstance(tool_calls, int) or isinstance(tool_calls, bool) or tool_calls < 0:
        raise AgentError("Sandbox agent returned an invalid tool-call count.")

    tool_call_details = data.get("tool_call_details", [])
    if not isinstance(tool_call_details, list):
        raise AgentError("Sandbox agent returned invalid tool-call details.")

    return AgentResult(
        answer=answer,
        result=structured_result,
        tool_calls=tool_calls,
        tool_call_details=tool_call_details,
        stdout=stdout,
    )
