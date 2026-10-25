from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.local_agent import (
    AgentCancelledError,
    AgentConfig,
    AgentError,
    _child_environment,
    run_eurostat_agent,
)
from app.sandbox_agent import EVENT_PREFIX


class LocalAgentTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
    def test_local_process_returns_result_and_streams_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_path = Path(temporary_directory) / "runner.py"
            runner_path.write_text(
                textwrap.dedent(
                    f"""
                    import json
                    import sys

                    request = json.loads(open(sys.argv[1], encoding="utf-8").read())
                    print({EVENT_PREFIX!r} + json.dumps({{"type": "tool_call", "query": request["query"]}}))
                    print(json.dumps({{
                        "answer": "Ready.",
                        "confidence": "high",
                        "result": None,
                        "tool_calls": 0,
                        "tool_call_details": [],
                    }}))
                    """
                ),
                encoding="utf-8",
            )
            events: list[dict[str, str]] = []

            result = run_eurostat_agent(
                "Test the runner.",
                [],
                "",
                AgentConfig(model="test/model", runner_path=runner_path),
                on_event=events.append,
            )

        self.assertEqual(result.answer, "Ready.")
        self.assertEqual(result.confidence, "high")
        self.assertEqual(events, [{"type": "tool_call", "query": "Test the runner."}])

    @patch.dict(
        os.environ,
        {
            "APP_PASSWORD": "must-not-leak",
            "DATABASE_URL": "must-not-leak",
        },
        clear=True,
    )
    def test_child_environment_only_forwards_allow_listed_values(self) -> None:
        environment = _child_environment(
            "test-openrouter",
            stream_events=True,
            catalog_cache=Path("/tmp/test-cache.tsv"),
        )

        self.assertEqual(environment["OPENROUTER_API_KEY"], "test-openrouter")
        self.assertEqual(environment["STREAM_TOOL_EVENTS"], "1")
        self.assertNotIn("APP_PASSWORD", environment)
        self.assertNotIn("DATABASE_URL", environment)

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
    def test_local_process_is_stopped_at_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_path = Path(temporary_directory) / "runner.py"
            runner_path.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")

            with self.assertRaisesRegex(AgentError, "exceeded the 0.05-second timeout"):
                run_eurostat_agent(
                    "Test the timeout.",
                    [],
                    "",
                    AgentConfig(
                        model="test/model",
                        runner_path=runner_path,
                        timeout_seconds=0.05,
                    ),
                )

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
    def test_cancellation_stops_the_child_process(self) -> None:
        cancel_event = threading.Event()
        processes: list[subprocess.Popen[str]] = []
        start_process = subprocess.Popen

        def start_then_cancel(*args, **kwargs):
            process = start_process(*args, **kwargs)
            processes.append(process)
            cancel_event.set()
            return process

        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_path = Path(temporary_directory) / "runner.py"
            runner_path.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")

            started_at = time.monotonic()
            with (
                patch("app.local_agent.subprocess.Popen", side_effect=start_then_cancel),
                self.assertRaises(AgentCancelledError),
            ):
                run_eurostat_agent(
                    "Test cancellation.",
                    [],
                    "",
                    AgentConfig(model="test/model", runner_path=runner_path, timeout_seconds=10),
                    cancel_event=cancel_event,
                )

        self.assertLess(time.monotonic() - started_at, 5)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"})
    def test_cancellation_while_waiting_for_a_slot_gives_up_without_starting(self) -> None:
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        cancel_event = threading.Event()
        threading.Timer(0.1, cancel_event.set).start()

        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_path = Path(temporary_directory) / "runner.py"
            runner_path.write_text("", encoding="utf-8")

            with (
                patch("app.local_agent._AGENT_SLOTS", slots),
                patch("app.local_agent.subprocess.Popen") as start_process,
                self.assertRaises(AgentCancelledError),
            ):
                run_eurostat_agent(
                    "Test cancellation.",
                    [],
                    "",
                    AgentConfig(model="test/model", runner_path=runner_path, timeout_seconds=10),
                    cancel_event=cancel_event,
                )

        start_process.assert_not_called()
        # The busy slot still belongs to its holder.
        self.assertFalse(slots.acquire(blocking=False))
        slots.release()


if __name__ == "__main__":
    unittest.main()
