from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class AppLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.password_patch = patch.dict(os.environ, {"APP_PASSWORD": "test-app-password"})
        self.password_patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.password_patch.stop()

    def test_chat_api_requires_an_unlocked_session(self) -> None:
        status = self.client.get("/api/auth/status")

        self.assertEqual(
            status.json(),
            {"lock_enabled": True, "authenticated": False},
        )
        self.assertEqual(
            self.client.post("/api/chat", json={"message": "hello"}).status_code,
            401,
        )

    def test_health_check_is_public_when_app_is_locked(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-openrouter"}, clear=True):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(response.json()["agent_ready"])

    def test_development_page_is_available_for_direct_navigation(self) -> None:
        response = self.client.get("/settings/development")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Settings / Development", response.text)

    def test_development_metadata_requires_unlock_and_describes_models_and_tools(self) -> None:
        self.assertEqual(self.client.get("/api/settings/development").status_code, 401)
        self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )

        response = self.client.get("/api/settings/development")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn(data["default_model"], [model["id"] for model in data["models"]])
        self.assertIn("moonshotai/kimi-k2-thinking", [model["id"] for model in data["models"]])
        self.assertIn("fetch_eurostat", [tool["name"] for tool in data["tools"]])
        self.assertIn("publish_result", [tool["name"] for tool in data["tools"]])
        self.assertEqual(len(data["tools"]), 4)
        self.assertEqual(data["limits"]["estimated_cells"], 50_000)
        self.assertEqual(data["limits"]["eurostat_response_bytes"], 8_000_000)
        self.assertNotIn("agent_runtime", data["runtime"])
        self.assertEqual(data["runtime"]["history"], "This browser (IndexedDB)")

    def test_unknown_model_is_rejected_before_starting_an_agent(self) -> None:
        self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )

        response = self.client.post(
            "/api/chat",
            json={"message": "hello", "model": "unknown/not-enabled"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not enabled", response.json()["detail"])

    def test_wrong_password_is_rejected(self) -> None:
        response = self.client.post(
            "/api/auth/unlock",
            json={"password": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("set-cookie", response.headers)

    def test_unlock_sets_http_only_cookie_and_lock_clears_it(self) -> None:
        unlock = self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )

        self.assertEqual(unlock.status_code, 200)
        self.assertIn("HttpOnly", unlock.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/health").status_code, 200)

        lock = self.client.post("/api/auth/lock")

        self.assertEqual(lock.status_code, 200)
        self.assertEqual(
            self.client.post("/api/chat", json={"message": "hello"}).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
