from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.local_agent import GENERIC_AGENT_ERROR, AgentError
from app.main import app


INTERNAL_DETAIL = (
    'Local agent process failed: Traceback (most recent call last):\n'
    '  File "/app/app/sandbox_agent.py", line 131, in main\n'
    "urllib.error.HTTPError: HTTP Error 402: upstream body"
)


class AgentErrorResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"OPENROUTER_MODEL_OPTIONS": "test/default-model"},
            clear=True,
        )
        self.environment.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.environment.stop()

    def test_chat_returns_generic_message_and_logs_detail(self) -> None:
        with (
            patch("app.main.run_eurostat_agent", side_effect=AgentError(INTERNAL_DETAIL)),
            self.assertLogs("app.main", level="ERROR") as logs,
        ):
            response = self.client.post("/api/chat", json={"message": "hello"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], GENERIC_AGENT_ERROR)
        self.assertIn("sandbox_agent.py", "\n".join(logs.output))

    def test_stream_returns_generic_message(self) -> None:
        with (
            patch("app.main.run_eurostat_agent", side_effect=AgentError(INTERNAL_DETAIL)),
            self.assertLogs("app.main", level="ERROR"),
        ):
            response = self.client.post("/api/chat/stream", json={"message": "hello"})

        events = [json.loads(line) for line in response.text.splitlines() if line]
        self.assertEqual(events[-1], {"type": "error", "message": GENERIC_AGENT_ERROR})
        self.assertNotIn("Traceback", response.text)

    def test_public_message_is_preserved_when_provided(self) -> None:
        error = AgentError("internal detail", "Local agent capacity is busy.")
        with (
            patch("app.main.run_eurostat_agent", side_effect=error),
            self.assertLogs("app.main", level="ERROR"),
        ):
            response = self.client.post("/api/chat", json={"message": "hello"})

        self.assertEqual(response.json()["detail"], "Local agent capacity is busy.")


if __name__ == "__main__":
    unittest.main()
