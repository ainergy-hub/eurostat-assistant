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
        self.assertEqual(self.client.get("/api/health").status_code, 401)

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
        self.assertEqual(self.client.get("/api/health").status_code, 401)


if __name__ == "__main__":
    unittest.main()
