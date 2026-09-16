from __future__ import annotations

import base64
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app.main import app


class AirtableResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FeedbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
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

    @patch("app.main.urlopen")
    def test_creates_a_feedback_record_without_generating_an_attachment(self, urlopen_mock) -> None:
        urlopen_mock.return_value = AirtableResponse({"id": "recFeedback"})

        response = self.client.post(
            "/api/feedback",
            json={
                "category": "Bug report",
                "feedback": "The chart labels overlap.",
                "rating": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        urlopen_mock.assert_called_once()
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.airtable.com/v0/appTestBase/tblTestTable",
        )
        self.assertEqual(
            json.loads(request.data),
            {
                "fields": {
                    "Category": "Bug report",
                    "Feedback": "The chart labels overlap.",
                    "Rating": 2,
                }
            },
        )
        self.assertEqual(request.headers["Authorization"], "Bearer secret-airtable-token")

    @patch("app.main.urlopen")
    def test_uploads_the_existing_chat_log_to_the_created_record(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = [
            AirtableResponse({"id": "recFeedback"}),
            AirtableResponse({"id": "attChatLog"}),
        ]
        chat_log = {
            "schemaVersion": 2,
            "app": {"name": "Eurostat Assistant", "version": "0.3.0"},
            "exportedAt": "2026-09-13T12:00:00.000Z",
            "investigation": {"id": "chat-1", "messages": []},
        }

        response = self.client.post(
            "/api/feedback",
            json={
                "category": "Response quality",
                "feedback": "The answer used the wrong year.",
                "rating": 1,
                "email": "reader@example.eu",
                "chat_log": chat_log,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "chat_log_attached": True})
        self.assertEqual(urlopen_mock.call_count, 2)
        record_request = urlopen_mock.call_args_list[0].args[0]
        self.assertEqual(
            json.loads(record_request.data)["fields"]["email"],
            "reader@example.eu",
        )
        attachment_request = urlopen_mock.call_args_list[1].args[0]
        self.assertEqual(
            attachment_request.full_url,
            "https://content.airtable.com/v0/appTestBase/recFeedback/"
            "Chat%20log%20attachment/uploadAttachment",
        )
        attachment = json.loads(attachment_request.data)
        self.assertEqual(attachment["contentType"], "application/json")
        self.assertEqual(attachment["filename"], "eurostat-assistant-chat-log.json")
        self.assertEqual(json.loads(base64.b64decode(attachment["file"])), chat_log)

    @patch("app.main.urlopen")
    def test_reports_partial_success_when_the_attachment_upload_fails(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = [
            AirtableResponse({"id": "recFeedback"}),
            HTTPError(
                "https://content.airtable.com/v0/appTestBase/recFeedback/attachment/uploadAttachment",
                500,
                "attachment upload failed",
                {},
                None,
            ),
        ]

        with self.assertLogs("app.main", level="WARNING"):
            response = self.client.post(
                "/api/feedback",
                json={
                    "category": "Response quality",
                    "feedback": "The answer used the wrong year.",
                    "rating": 1,
                    "chat_log": {
                        "schemaVersion": 2,
                        "app": {"name": "Eurostat Assistant"},
                        "exportedAt": "2026-09-13T12:00:00.000Z",
                        "investigation": {"id": "chat-1", "messages": []},
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "chat_log_attached": False})
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_rejects_invalid_values_before_contacting_airtable(self) -> None:
        cases = [
            {"category": "Compliment", "feedback": "Hello", "rating": 3},
            {"category": "General feedback", "feedback": "Hello", "rating": 0},
            {"category": "General feedback", "feedback": "Hello", "rating": 6},
            {"category": "General feedback", "feedback": " ", "rating": 3},
            {"category": "General feedback", "feedback": "x" * 5_001, "rating": 3},
            {
                "category": "General feedback",
                "feedback": "Hello",
                "rating": 3,
                "email": "not-an-email",
            },
            {
                "category": "General feedback",
                "feedback": "Hello",
                "rating": 3,
                "chat_log": {"messages": []},
            },
        ]

        with patch("app.main.urlopen") as urlopen_mock:
            for payload in cases:
                with self.subTest(payload=payload):
                    response = self.client.post("/api/feedback", json=payload)
                    self.assertEqual(response.status_code, 422)
            urlopen_mock.assert_not_called()

    def test_reports_missing_configuration_without_naming_secrets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(
                "/api/feedback",
                json={
                    "category": "General feedback",
                    "feedback": "A useful note.",
                    "rating": 4,
                },
            )
            status = self.client.get("/api/auth/status")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Feedback storage is not configured."})
        self.assertNotIn("AIRTABLE", response.text)
        self.assertFalse(status.json()["feedback_configured"])

    @patch("app.main.urlopen")
    def test_hides_airtable_error_details_and_credentials(self, urlopen_mock) -> None:
        urlopen_mock.side_effect = HTTPError(
            "https://api.airtable.com/v0/appTestBase/tblTestTable",
            401,
            "secret-airtable-token was rejected",
            {},
            None,
        )

        response = self.client.post(
            "/api/feedback",
            json={
                "category": "Feature request",
                "feedback": "Add CSV downloads.",
                "rating": 4,
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "Feedback could not be saved. Try again."},
        )
        self.assertNotIn("secret-airtable-token", response.text)


if __name__ == "__main__":
    unittest.main()
