from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .agent_config import EVENT_PREFIX


DEFAULT_TIMEOUT_SECONDS = 180


GENERIC_AGENT_ERROR = "The agent request failed. Try again."
AGENT_BUSY_MESSAGE = "The assistant is busy with other questions. Try again in a minute."


class AgentError(RuntimeError):
    """Raised when the local agent process cannot complete the request.

    The exception text is for server logs and may contain tracebacks or upstream error
    bodies. Only ``public_message`` is safe to return to clients.
    """

    def __init__(self, message: str, public_message: str = GENERIC_AGENT_ERROR) -> None:
        super().__init__(message)
        self.public_message = public_message


class AgentCancelledError(AgentError):
    """Raised when the caller cancelled the request, for example after a client disconnect."""


@dataclass(frozen=True)
class AgentConfig:
    model: str
    runner_path: Path
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class AgentResult:
    answer: str
    confidence: str
    result: dict[str, Any] | None
    tool_calls: int
    tool_call_details: list[dict[str, Any]]
    stdout: str


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _non_negative_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


_AGENT_CONCURRENCY = _positive_int_env("LOCAL_AGENT_CONCURRENCY", 2)
_AGENT_SLOTS = threading.BoundedSemaphore(_AGENT_CONCURRENCY)
# Running plus waiting requests. Requests beyond this are rejected rather than queued.
_AGENT_REQUESTS = threading.BoundedSemaphore(
    _AGENT_CONCURRENCY + _non_negative_int_env("LOCAL_AGENT_QUEUE_LIMIT", 4)
)


def try_admit_agent_request() -> bool:
    """Reserve a running or waiting place without blocking.

    Every successful call must be paired with exactly one ``release_agent_request()``.
    """
    return _AGENT_REQUESTS.acquire(blocking=False)


def release_agent_request() -> None:
    _AGENT_REQUESTS.release()


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AgentCancelledError("Local agent request was cancelled.")


def _acquire_agent_slot(timeout_seconds: float, cancel_event: threading.Event | None) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        _raise_if_cancelled(cancel_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            message = "Local agent capacity is busy. Try the request again shortly."
            raise AgentError(message, message)
        if _AGENT_SLOTS.acquire(timeout=min(0.25, remaining)):
            if cancel_event is None or not cancel_event.is_set():
                return
            # Cancelled while waiting: hand the slot back and raise on the next pass.
            _AGENT_SLOTS.release()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise AgentError(f"Missing {name}. Add it to your environment before starting the app.")
    return value


def _child_environment(
    openrouter_api_key: str,
    stream_events: bool,
    catalog_cache: Path,
) -> dict[str, str]:
    environment = {
        "OPENROUTER_API_KEY": openrouter_api_key,
        "STREAM_TOOL_EVENTS": "1" if stream_events else "0",
        "EUROSTAT_CATALOG_CACHE": str(catalog_cache),
        "PYTHONIOENCODING": "utf-8",
    }
    for name in (
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "SYSTEMROOT",
    ):
        value = os.getenv(name)
        if value:
            environment[name] = value
    return environment


def _read_stream(
    stream: TextIO,
    collected: list[str],
    lines: queue.Queue[str | None] | None = None,
) -> None:
    try:
        for line in stream:
            collected.append(line)
            if lines is not None:
                lines.put(line)
    finally:
        if lines is not None:
            lines.put(None)
        stream.close()


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()


def _publish_event(line: str, on_event: Callable[[dict[str, Any]], None] | None) -> None:
    if not on_event or not line.startswith(EVENT_PREFIX):
        return
    try:
        event = json.loads(line.removeprefix(EVENT_PREFIX))
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return
    try:
        on_event(event)
    except Exception:
        # UI telemetry must never interrupt the data investigation.
        return


def _run_process(
    payload: dict[str, Any],
    config: AgentConfig,
    openrouter_api_key: str,
    on_event: Callable[[dict[str, Any]], None] | None,
    cancel_event: threading.Event | None = None,
) -> str:
    with tempfile.TemporaryDirectory(prefix="eurostat-agent-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        request_path = temporary_path / "request.json"
        request_path.write_text(json.dumps(payload), encoding="utf-8")

        try:
            process = subprocess.Popen(
                [sys.executable, str(config.runner_path), str(request_path)],
                cwd=config.runner_path.parent,
                env=_child_environment(
                    openrouter_api_key,
                    stream_events=on_event is not None,
                    catalog_cache=temporary_path / "eurostat_toc.tsv",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            raise AgentError(f"Could not start the local agent process: {exc}") from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        stdout_lines: queue.Queue[str | None] = queue.Queue()
        stdout_reader = threading.Thread(
            target=_read_stream,
            args=(process.stdout, stdout_parts, stdout_lines),
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=_read_stream,
            args=(process.stderr, stderr_parts),
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()

        deadline = time.monotonic() + config.timeout_seconds
        stdout_complete = False
        try:
            while not stdout_complete:
                # A cancelled request leaves the loop here; the finally block stops the child.
                _raise_if_cancelled(cancel_event)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, config.timeout_seconds)
                try:
                    line = stdout_lines.get(timeout=min(0.25, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    stdout_complete = True
                else:
                    _publish_event(line, on_event)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, config.timeout_seconds)
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            _stop_process(process)
            raise AgentError(
                f"Local agent exceeded the {config.timeout_seconds:g}-second timeout.",
                "The agent took too long to answer. Try a narrower question.",
            ) from exc
        finally:
            if process.poll() is None:
                _stop_process(process)
            stdout_reader.join(timeout=1)
            stderr_reader.join(timeout=1)

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts).strip()
        if return_code != 0:
            detail = stderr or stdout[:1000] or f"exit status {return_code}"
            raise AgentError(f"Local agent process failed: {detail}")
        if stderr:
            raise AgentError(f"Local agent reported an error: {stderr}")
        return stdout


def run_eurostat_agent(
    query: str,
    history: list[dict[str, str]],
    summary: str,
    config: AgentConfig,
    context_result: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> AgentResult:
    openrouter_api_key = _require_env("OPENROUTER_API_KEY")
    if not config.runner_path.is_file():
        raise AgentError(f"Required agent runner is missing: {config.runner_path}")
    if config.timeout_seconds <= 0:
        raise AgentError("Local agent timeout must be greater than zero.")

    payload = {
        "query": query,
        "history": history,
        "summary": summary,
        "context_result": context_result,
        "model": config.model,
    }

    _acquire_agent_slot(config.timeout_seconds, cancel_event)
    try:
        stdout = _run_process(payload, config, openrouter_api_key, on_event, cancel_event)
    finally:
        _AGENT_SLOTS.release()

    result_output = "\n".join(
        line for line in stdout.splitlines() if not line.startswith(EVENT_PREFIX)
    ).strip()
    try:
        data = json.loads(result_output)
    except json.JSONDecodeError as exc:
        raise AgentError(f"Local agent returned non-JSON output: {stdout[:1000]}") from exc
    if not isinstance(data, dict):
        raise AgentError("Local agent returned an invalid response.")

    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise AgentError("Local agent did not return an answer.")

    confidence = str(data.get("confidence", "medium")).strip().lower()
    if confidence not in {"low", "medium", "high"}:
        raise AgentError("Local agent returned an invalid confidence level.")

    structured_result = data.get("result")
    if structured_result is not None and not isinstance(structured_result, dict):
        raise AgentError("Local agent returned an invalid structured result.")

    tool_calls = data.get("tool_calls", 0)
    if not isinstance(tool_calls, int) or isinstance(tool_calls, bool) or tool_calls < 0:
        raise AgentError("Local agent returned an invalid tool-call count.")

    tool_call_details = data.get("tool_call_details", [])
    if not isinstance(tool_call_details, list):
        raise AgentError("Local agent returned invalid tool-call details.")

    return AgentResult(
        answer=answer,
        confidence=confidence,
        result=structured_result,
        tool_calls=tool_calls,
        tool_call_details=tool_call_details,
        stdout=stdout,
    )
