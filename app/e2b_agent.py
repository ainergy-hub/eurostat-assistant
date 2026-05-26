from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from e2b import Sandbox


SANDBOX_DIR = "/home/user/eurostat_agent"


class AgentError(RuntimeError):
    """Raised when the sandboxed agent cannot complete the request."""


@dataclass(frozen=True)
class AgentConfig:
    model: str
    skill_path: Path
    helper_path: Path
    sandbox_agent_path: Path


@dataclass(frozen=True)
class AgentResult:
    answer: str
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


def run_eurostat_agent(query: str, history: list[dict[str, str]], config: AgentConfig) -> AgentResult:
    _require_env("E2B_API_KEY")
    openrouter_api_key = _require_env("OPENROUTER_API_KEY")

    for path in (config.skill_path, config.helper_path, config.sandbox_agent_path):
        if not path.exists():
            raise AgentError(f"Required file is missing: {path}")

    payload = {
        "query": query,
        "history": history,
        "model": config.model,
    }

    try:
        sandbox = Sandbox.create(timeout=180)
        sandbox.files.write(f"{SANDBOX_DIR}/SKILL.md", config.skill_path.read_text())
        sandbox.files.write(f"{SANDBOX_DIR}/eurostat_api.py", config.helper_path.read_text())
        sandbox.files.write(f"{SANDBOX_DIR}/sandbox_agent.py", config.sandbox_agent_path.read_text())
        sandbox.files.write(f"{SANDBOX_DIR}/request.json", json.dumps(payload))

        result = sandbox.commands.run(
            f"python3 {SANDBOX_DIR}/sandbox_agent.py {SANDBOX_DIR}/request.json",
            cwd=SANDBOX_DIR,
            envs={"OPENROUTER_API_KEY": openrouter_api_key},
            timeout=180,
        )
    except Exception as exc:  # E2B exposes several transport/runtime exceptions.
        raise AgentError(f"E2B sandbox run failed: {exc}") from exc

    stdout = _command_text(result, "stdout")
    stderr = _command_text(result, "stderr")
    if stderr.strip():
        raise AgentError(f"Sandbox agent reported an error: {stderr.strip()}")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AgentError(f"Sandbox returned non-JSON output: {stdout[:1000]}") from exc

    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise AgentError("Sandbox agent did not return an answer.")

    return AgentResult(answer=answer, stdout=stdout)
