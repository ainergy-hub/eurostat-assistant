from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import (
    MAX_CHAT_LOG_BYTES,
    MAX_HISTORY_MESSAGE_CHARACTERS,
    MAX_REQUEST_BODY_BYTES,
    MAX_RESULT_FIELDS,
    MAX_RESULT_ROWS,
    MAX_RESULT_SOURCES,
    MAX_RESULT_TEXT_CHARACTERS,
    MAX_RESULT_WARNINGS,
    MAX_SOURCE_URL_CHARACTERS,
    ChatRequest,
    ChatResponse,
    app,
)
from app.sandbox_agent import response_result


def fetch_record(index: int, row_count: int = MAX_RESULT_ROWS) -> dict:
    dataset = f"nrg_dataset_{index}"
    rows = [
        {
            "value": 1234.5 + row,
            "freq": "A",
            "freq_label": "Annual",
            "nrg_bal": "GIC",
            "nrg_bal_label": "Gross inland consumption of energy products and services",
            "siec": "TOTAL",
            "siec_label": "Total of all energy products",
            "unit": "KTOE",
            "unit_label": "Thousand tonnes of oil equivalent",
            "geo": f"G{row % 40:02d}",
            "geo_label": f"Geography {row % 40} (NUTS 2024 boundaries)",
            "time": str(2000 + row // 40),
            "time_label": str(2000 + row // 40),
            "status": "p",
        }
        for row in range(row_count)
    ]
    return {
        "result_id": f"fetch-{index}",
        "arguments": {
            "dataset": dataset,
            "params": ["freq=A", "nrg_bal=GIC", "siec=TOTAL", "unit=KTOE"],
            "last_time_period": 20,
        },
        "output": {
            "metadata": {
                "label": "Complete energy balances by product and balance item",
                "updated": "2026-07-25T11:00:00+0200",
                "total_rows": row_count + 100,
                "returned_rows": row_count,
                "truncated": True,
            },
            "rows": rows,
        },
    }


def largest_agent_result() -> dict:
    """The widest result the agent can publish: one table per allowed fetch, each at the row cap."""
    records = [fetch_record(index) for index in range(MAX_RESULT_SOURCES)]
    result = response_result(
        records[-1],
        None,
        fetch_records=records,
        selected_result_id=records[-1]["result_id"],
    )
    assert result is not None
    return result


def realistic_request() -> dict:
    long_answer = "Germany consumed the most energy in the selected years. " * 200
    return {
        "message": "How does that compare with France?",
        "summary": "Earlier investigation summary:\nQuestion: Energy use in Germany",
        "history": [
            {"role": "user", "content": "Show energy use in Germany."},
            {"role": "assistant", "content": long_answer},
            {"role": "user", "content": "Add the European Union."},
            {"role": "assistant", "content": long_answer},
            {"role": "user", "content": "Use the last 20 years."},
            {"role": "assistant", "content": long_answer},
        ],
        "context_result": largest_agent_result(),
    }


class ChatRequestLimitTests(unittest.TestCase):
    def test_largest_agent_result_round_trips_as_follow_up_context(self) -> None:
        result = largest_agent_result()
        response = ChatResponse(answer="Energy balance.", result=result)
        payload = response.model_dump(mode="json")["result"]
        request = ChatRequest(message="Continue.", context_result=payload)

        assert request.context_result is not None
        self.assertEqual(len(request.context_result.source_tables), MAX_RESULT_SOURCES)
        self.assertEqual(len(request.context_result.rows), MAX_RESULT_ROWS)
        self.assertEqual(request.context_result.rows[0]["value"], 1234.5)
        self.assertEqual(request.context_result.model_dump(mode="json"), payload)

    def test_realistic_request_fits_the_body_limit(self) -> None:
        payload = realistic_request()
        ChatRequest.model_validate(payload)
        self.assertLess(len(json.dumps(payload).encode("utf-8")), MAX_REQUEST_BODY_BYTES)

    def test_rejects_oversized_history_message(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(
                message="Continue.",
                history=[
                    {"role": "assistant", "content": "x" * (MAX_HISTORY_MESSAGE_CHARACTERS + 1)}
                ],
            )
        ChatRequest(
            message="Continue.",
            history=[{"role": "assistant", "content": "x" * MAX_HISTORY_MESSAGE_CHARACTERS}],
        )

    def test_rejects_oversized_context_result_pieces(self) -> None:
        base = largest_agent_result()
        long_text = "x" * (MAX_RESULT_TEXT_CHARACTERS + 1)
        table = base["source_tables"][0]
        column = {"key": "geo", "label": "Geography"}
        oversized = {
            "columns": lambda result: result.update(columns=[column] * (MAX_RESULT_FIELDS + 1)),
            "sources": lambda result: result.update(
                sources=[result["dataset"]] * (MAX_RESULT_SOURCES + 1)
            ),
            "source_tables": lambda result: result.update(
                source_tables=[table] * (MAX_RESULT_SOURCES + 1)
            ),
            "filter keys": lambda result: result.update(
                filters={f"dim{index}": ["A"] for index in range(MAX_RESULT_FIELDS + 1)}
            ),
            "filter value": lambda result: result.update(filters={"geo": [long_text]}),
            "warnings": lambda result: result.update(
                warnings=["Truncated."] * (MAX_RESULT_WARNINGS + 1)
            ),
            "warning text": lambda result: result.update(warnings=[long_text]),
            "rows": lambda result: result.update(rows=result["rows"] * 2),
            "row fields": lambda result: result["rows"][0].update(
                {f"field{index}": 1 for index in range(MAX_RESULT_FIELDS + 1)}
            ),
            "cell text": lambda result: result["rows"][0].update(geo_label=long_text),
            "nested cell": lambda result: result["rows"][0].update(geo={"nested": ["DE"]}),
            "dataset title": lambda result: result["dataset"].update(title=long_text),
            "source url": lambda result: result["dataset"].update(
                source_url="x" * (MAX_SOURCE_URL_CHARACTERS + 1)
            ),
            "column label": lambda result: result["columns"][0].update(label=long_text),
            "chart title": lambda result: result["chart"].update(title=long_text),
            "source table rows": lambda result: result["source_tables"][0].update(
                rows=table["rows"] * 2
            ),
            "source table warnings": lambda result: result["source_tables"][0].update(
                warnings=["Truncated."] * (MAX_RESULT_WARNINGS + 1)
            ),
        }
        for name, mutate in oversized.items():
            with self.subTest(name):
                result = json.loads(json.dumps(base))
                mutate(result)
                with self.assertRaises(ValidationError):
                    ChatRequest(message="Continue.", context_result=result)


class RequestBodyLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "OPENROUTER_MODEL_OPTIONS": "test/model",
                "AIRTABLE_ACCESS_TOKEN": "secret-airtable-token",
                "AIRTABLE_BASE_ID": "appTestBase",
                "AIRTABLE_TABLE_ID": "tblTestTable",
            },
            clear=True,
        )
        self.environment.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.environment.stop()

    def test_rejects_declared_oversized_body(self) -> None:
        body = b"{" + b" " * MAX_REQUEST_BODY_BYTES + b"}"
        response = self.client.post(
            "/api/chat/stream",
            content=body,
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "Request body is too large.")

    def test_rejects_streamed_oversized_body_without_content_length(self) -> None:
        def chunks():
            yield b'{"message": "'
            for _ in range(MAX_REQUEST_BODY_BYTES // 100_000 + 1):
                yield b"x" * 100_000
            yield b'"}'

        response = self.client.post(
            "/api/chat",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)

    def test_oversized_history_message_returns_validation_error(self) -> None:
        response = self.client.post(
            "/api/chat/stream",
            json={
                "message": "Continue.",
                "history": [{"role": "assistant", "content": "x" * 1_000_000}],
            },
        )

        self.assertEqual(response.status_code, 422)

    @patch("app.main.run_eurostat_agent")
    def test_realistic_follow_up_request_is_accepted(self, agent_mock) -> None:
        payload = realistic_request()
        agent_mock.return_value = SimpleNamespace(
            answer="France consumed less.",
            confidence="high",
            result=payload["context_result"],
            tool_calls=0,
            tool_call_details=[],
        )

        response = self.client.post("/api/chat", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "France consumed less.")
        self.assertEqual(len(agent_mock.call_args.args[1]), 6)

    @patch("app.main.urlopen")
    def test_feedback_accepts_chat_log_at_its_own_limit(self, urlopen_mock) -> None:
        class AirtableResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"id": "recFeedback"}).encode("utf-8")

        urlopen_mock.return_value = AirtableResponse()
        chat_log = {
            "schemaVersion": 2,
            "app": {"name": "Eurostat Assistant", "version": "test"},
            "exportedAt": "2026-07-26T10:00:00.000Z",
            "investigation": {"messages": [{"content": "x" * (MAX_CHAT_LOG_BYTES - 500)}]},
        }

        response = self.client.post(
            "/api/feedback",
            json={
                "category": "Bug report",
                "feedback": "x" * 5_000,
                "rating": 2,
                "chat_log": chat_log,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["chat_log_attached"])


if __name__ == "__main__":
    unittest.main()
