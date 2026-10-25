from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import (
    MAX_UNLOCK_FAILURES_GLOBAL,
    MAX_UNLOCK_FAILURES_PER_CLIENT,
    UNLOCK_WINDOW_SECONDS,
    _model_name,
    _title_model_name,
    app,
    unlock_throttle,
)


class AppLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.password_patch = patch.dict(
            os.environ,
            {
                "APP_PASSWORD": "test-app-password",
                "OPENROUTER_MODEL_OPTIONS": "test/default-model,test/alternate-model",
                "AIRTABLE_ACCESS_TOKEN": "test-airtable-token",
                "AIRTABLE_BASE_ID": "appTestBase",
                "AIRTABLE_TABLE_ID": "tblTestTable",
            },
        )
        self.password_patch.start()
        unlock_throttle.reset()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.password_patch.stop()
        unlock_throttle.reset()

    def test_chat_api_requires_an_unlocked_session(self) -> None:
        status = self.client.get("/api/auth/status")

        self.assertEqual(
            status.json(),
            {
                "lock_enabled": True,
                "authenticated": False,
                "feedback_configured": True,
            },
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
        self.assertEqual(
            [model["id"] for model in data["models"]],
            ["test/default-model", "test/alternate-model"],
        )
        self.assertIn("fetch_eurostat", [tool["name"] for tool in data["tools"]])
        self.assertIn("publish_result", [tool["name"] for tool in data["tools"]])
        self.assertEqual(len(data["tools"]), 4)
        self.assertEqual(data["limits"]["estimated_cells"], 50_000)
        self.assertEqual(data["limits"]["eurostat_response_bytes"], 8_000_000)
        self.assertNotIn("agent_runtime", data["runtime"])
        self.assertEqual(data["runtime"]["history"], "This browser (IndexedDB)")
        self.assertEqual(data["runtime"]["title_model"], "openai/gpt-5.4-nano")

    def test_default_model_is_the_first_configured_option(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODEL_OPTIONS": "test/first-model,test/second-model"},
            clear=True,
        ):
            self.assertEqual(_model_name(), "test/first-model")

    def test_missing_model_options_are_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_MODEL_OPTIONS"):
                _model_name()

    def test_title_model_has_a_separate_config(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_TITLE_MODEL": "test/fast-title-model"},
            clear=True,
        ):
            self.assertEqual(_title_model_name(), "test/fast-title-model")

    def test_invalid_title_model_is_rejected(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_TITLE_MODEL": "not a model"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_TITLE_MODEL"):
                _title_model_name()

    def test_title_api_requires_an_unlocked_session(self) -> None:
        response = self.client.post("/api/chat/title", json={"message": "Population"})

        self.assertEqual(response.status_code, 401)

    @patch("app.main.generate_chat_title", return_value="European Population Trends")
    def test_title_api_uses_the_dedicated_model(self, generate_title_mock) -> None:
        self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )

        response = self.client.post(
            "/api/chat/title",
            json={"message": "How has European population changed?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "title": "European Population Trends",
                "model": "openai/gpt-5.4-nano",
            },
        )
        generate_title_mock.assert_called_once_with(
            "How has European population changed?",
            "openai/gpt-5.4-nano",
        )

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

    def test_lock_revokes_the_session_on_the_server(self) -> None:
        self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )
        token = self.client.cookies.get("eurostat_lens_session")
        self.assertEqual(self.client.get("/api/settings/development").status_code, 200)

        self.client.post("/api/auth/lock")

        with TestClient(app, cookies={"eurostat_lens_session": token}) as replay:
            self.assertEqual(replay.get("/api/settings/development").status_code, 401)
            self.assertFalse(replay.get("/api/auth/status").json()["authenticated"])

    def test_changing_the_password_invalidates_existing_sessions(self) -> None:
        self.client.post(
            "/api/auth/unlock",
            json={"password": "test-app-password"},
        )
        self.assertEqual(self.client.get("/api/settings/development").status_code, 200)

        with patch.dict(os.environ, {"APP_PASSWORD": "rotated-app-password"}):
            self.assertEqual(self.client.get("/api/settings/development").status_code, 401)


class UnlockThrottleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, {"APP_PASSWORD": "test-app-password"})
        self.env_patch.start()
        self.now = 1_000.0
        self.clock_patch = patch.object(unlock_throttle, "clock", lambda: self.now)
        self.clock_patch.start()
        unlock_throttle.reset()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.clock_patch.stop()
        self.env_patch.stop()
        unlock_throttle.reset()

    def unlock(self, password: str, client: TestClient | None = None):
        return (client or self.client).post("/api/auth/unlock", json={"password": password})

    def fail_until_limit(self) -> None:
        for _ in range(MAX_UNLOCK_FAILURES_PER_CLIENT):
            self.assertEqual(self.unlock("wrong").status_code, 401)

    def test_client_is_locked_out_after_repeated_failures(self) -> None:
        self.fail_until_limit()

        response = self.unlock("wrong")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], str(UNLOCK_WINDOW_SECONDS))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Too many unlock attempts", response.json()["detail"])
        self.assertIn("15 minutes", response.json()["detail"])

    def test_correct_password_is_rejected_while_locked_out(self) -> None:
        self.fail_until_limit()
        self.now += 60

        response = self.unlock("test-app-password")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], str(UNLOCK_WINDOW_SECONDS - 60))
        self.assertNotIn("set-cookie", response.headers)

    def test_successful_unlock_resets_the_client_counter(self) -> None:
        for _ in range(MAX_UNLOCK_FAILURES_PER_CLIENT - 1):
            self.assertEqual(self.unlock("wrong").status_code, 401)
        self.assertEqual(self.unlock("test-app-password").status_code, 200)

        self.fail_until_limit()
        self.assertEqual(self.unlock("wrong").status_code, 429)

    def test_lockout_expires_after_the_window(self) -> None:
        self.fail_until_limit()
        self.now += UNLOCK_WINDOW_SECONDS - 1
        self.assertEqual(self.unlock("test-app-password").status_code, 429)

        self.now += 1

        self.assertEqual(self.unlock("wrong").status_code, 401)
        self.assertEqual(self.unlock("test-app-password").status_code, 200)

    def test_lockout_is_per_client(self) -> None:
        self.fail_until_limit()

        with TestClient(app, client=("203.0.113.7", 50000)) as other:
            self.assertEqual(self.unlock("test-app-password", other).status_code, 200)

    def test_global_cap_applies_across_clients(self) -> None:
        for index in range(MAX_UNLOCK_FAILURES_GLOBAL):
            _, retry_after = unlock_throttle.acquire(f"198.51.100.{index}")
            self.assertIsNone(retry_after)

        response = self.unlock("test-app-password")

        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)

    def test_expired_clients_are_pruned(self) -> None:
        for index in range(10):
            unlock_throttle.acquire(f"198.51.100.{index}")
        self.now += UNLOCK_WINDOW_SECONDS

        unlock_throttle.acquire("203.0.113.7")

        self.assertEqual(list(unlock_throttle._clients), ["203.0.113.7"])


if __name__ == "__main__":
    unittest.main()


class StartupLockConfigurationTests(unittest.TestCase):
    def test_refuses_to_start_without_password(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_PASSWORD is not set"):
                with TestClient(app):
                    pass

    def test_starts_unlocked_with_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {"APP_ALLOW_UNLOCKED": "true"}, clear=True):
            with TestClient(app) as client:
                self.assertFalse(client.get("/api/auth/status").json()["lock_enabled"])

    def test_starts_with_password(self) -> None:
        with patch.dict(os.environ, {"APP_PASSWORD": "test-app-password"}, clear=True):
            with TestClient(app) as client:
                self.assertTrue(client.get("/api/auth/status").json()["lock_enabled"])
