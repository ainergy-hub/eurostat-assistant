from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.e2b_agent import run_eurostat_agent
from app.main import _agent_config


class _Files:
    def __init__(self) -> None:
        self.writes: dict[str, str] = {}

    def write(self, path: str, content: str) -> None:
        self.writes[path] = content


class _Commands:
    def __init__(self, files: _Files) -> None:
        self.files = files

    def run(self, *_args, **_kwargs):
        assert "/home/user/eurostat_agent/agent_limits.json" in self.files.writes
        limits = json.loads(self.files.writes["/home/user/eurostat_agent/agent_limits.json"])
        assert limits["max_estimated_cells"] == 50_000
        return type(
            "Result",
            (),
            {
                "stdout": json.dumps(
                    {
                        "answer": "Ready.",
                        "result": None,
                        "tool_calls": 0,
                        "tool_call_details": [],
                    }
                ),
                "stderr": "",
            },
        )()


class _Sandbox:
    def __init__(self) -> None:
        self.files = _Files()
        self.commands = _Commands(self.files)


class E2BAgentTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"E2B_API_KEY": "test-e2b", "OPENROUTER_API_KEY": "test-openrouter"},
    )
    @patch("app.e2b_agent.Sandbox.create")
    def test_sandbox_bundle_includes_authoritative_limits(self, create_mock) -> None:
        create_mock.return_value = _Sandbox()

        result = run_eurostat_agent(
            "Test the bundle.",
            [],
            "",
            _agent_config(),
        )

        self.assertEqual(result.answer, "Ready.")


if __name__ == "__main__":
    unittest.main()
