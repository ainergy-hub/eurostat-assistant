from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch

import anyio
from fastapi.testclient import TestClient

from app.local_agent import AGENT_BUSY_MESSAGE, AgentCancelledError, AgentError, AgentResult
from app.main import ChatRequest, app, chat_stream


AGENT_RESULT = AgentResult(
    answer="Ready.",
    confidence="high",
    result=None,
    tool_calls=0,
    tool_call_details=[],
    stdout="",
)


def stream_events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


class AgentAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {"OPENROUTER_MODEL_OPTIONS": "test/default-model"},
            clear=True,
        )
        self.environment.start()
        # One running or waiting place, so a second concurrent request must be rejected.
        self.requests = threading.BoundedSemaphore(1)
        self.requests_patch = patch("app.local_agent._AGENT_REQUESTS", self.requests)
        self.requests_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.requests_patch.stop()
        self.environment.stop()

    def assert_place_released(self) -> None:
        self.assertTrue(self.requests.acquire(blocking=False))
        self.requests.release()

    def test_full_capacity_rejects_both_endpoints_before_starting_work(self) -> None:
        self.requests.acquire()
        try:
            with patch("app.main.run_eurostat_agent") as run_agent:
                chat = self.client.post("/api/chat", json={"message": "hello"})
                stream = self.client.post("/api/chat/stream", json={"message": "hello"})
        finally:
            self.requests.release()

        for response in (chat, stream):
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()["detail"], AGENT_BUSY_MESSAGE)
        run_agent.assert_not_called()

    def test_place_is_released_after_completion(self) -> None:
        with patch("app.main.run_eurostat_agent", return_value=AGENT_RESULT):
            chat = self.client.post("/api/chat", json={"message": "hello"})
            self.assert_place_released()
            stream = self.client.post("/api/chat/stream", json={"message": "hello"})
            self.assert_place_released()

        self.assertEqual(chat.status_code, 200)
        self.assertEqual(stream_events(stream)[-1]["type"], "result")

    def test_place_is_released_after_errors(self) -> None:
        for error in (AgentError("internal detail"), RuntimeError("unexpected")):
            with (
                patch("app.main.run_eurostat_agent", side_effect=error),
                self.assertLogs("app.main", level="ERROR"),
            ):
                stream = self.client.post("/api/chat/stream", json={"message": "hello"})
            self.assertEqual(stream_events(stream)[-1]["type"], "error")
            self.assert_place_released()

        with (
            patch("app.main.run_eurostat_agent", side_effect=AgentError("internal detail")),
            self.assertLogs("app.main", level="ERROR"),
        ):
            chat = self.client.post("/api/chat", json={"message": "hello"})
        self.assertEqual(chat.status_code, 502)
        self.assert_place_released()

        with (
            patch("app.main.run_eurostat_agent", side_effect=RuntimeError("unexpected")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post("/api/chat", json={"message": "hello"})
        self.assert_place_released()

    def test_stream_disconnect_cancels_the_agent_and_releases_its_place(self) -> None:
        for disconnect_before_first_event in (False, True):
            with self.subTest(disconnect_before_first_event=disconnect_before_first_event):
                self.assert_disconnect_cancels_agent(disconnect_before_first_event)

    def assert_disconnect_cancels_agent(self, disconnect_before_first_event: bool) -> None:
        agent_stopped = threading.Event()
        cancel_seen: list[bool] = []

        def wait_for_cancel(*args, on_event, cancel_event: threading.Event, **kwargs):
            try:
                on_event({"type": "status", "phase": "working"})
                cancel_seen.append(cancel_event.wait(timeout=5))
                raise AgentCancelledError("cancelled")
            finally:
                agent_stopped.set()

        async def disconnect() -> None:
            body_sent = anyio.Event()

            async def receive():
                if not disconnect_before_first_event:
                    await body_sent.wait()
                    # Let the stream block while waiting for the next agent event.
                    await anyio.sleep(0.1)
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body":
                    body_sent.set()

            with anyio.fail_after(5):
                response = await chat_stream(ChatRequest(message="hello"))
                await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)

        with patch("app.main.run_eurostat_agent", side_effect=wait_for_cancel):
            anyio.run(disconnect)
            self.assertTrue(agent_stopped.wait(timeout=5))

        self.assertEqual(cancel_seen, [True])
        self.assert_place_released()


if __name__ == "__main__":
    unittest.main()
