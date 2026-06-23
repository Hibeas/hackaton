"""Auth register/login tests (SQLite fallback when DATABASE_URL unset)."""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from auth_service import login_user, register_user  # noqa: E402
from user_store import UserStore  # noqa: E402


class AuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._prev_db_url = os.environ.pop("DATABASE_URL", None)
        self.store = UserStore(db_path=os.path.join(self._tmpdir.name, "auth.db"))
        import auth_service
        import user_store as user_store_module

        self._prev_store = user_store_module.user_store
        user_store_module.user_store = self.store
        auth_service.user_store = self.store

    def tearDown(self) -> None:
        import user_store as user_store_module

        user_store_module.user_store = self._prev_store
        if self._prev_db_url is not None:
            os.environ["DATABASE_URL"] = self._prev_db_url
        self._tmpdir.cleanup()

    def test_register_and_login(self) -> None:
        registered = register_user(
            email="ops@port-ai.test",
            password="secret123",
            phone_e164="+48728538889",
            full_name="Port Operator",
        )
        self.assertIn("access_token", registered)
        self.assertEqual(registered["user"]["email"], "ops@port-ai.test")

        session = login_user(email="ops@port-ai.test", password="secret123")
        self.assertIn("access_token", session)
        self.assertEqual(session["user"]["full_name"], "Port Operator")

    def test_duplicate_email_rejected(self) -> None:
        register_user(email="dup@test.pl", password="secret123", phone_e164="+48728538889")
        with self.assertRaises(ValueError) as ctx:
            register_user(email="dup@test.pl", password="secret456", phone_e164="+48728538888")
        self.assertEqual(str(ctx.exception), "email_taken")

    def test_invalid_credentials(self) -> None:
        register_user(email="user@test.pl", password="secret123", phone_e164="+48728538889")
        with self.assertRaises(ValueError) as ctx:
            login_user(email="user@test.pl", password="wrong-pass")
        self.assertEqual(str(ctx.exception), "invalid_credentials")


if __name__ == "__main__":
    unittest.main()
