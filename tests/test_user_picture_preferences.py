"""Tests for per-user picture preference persistence."""

import tempfile
import unittest
from pathlib import Path

from ..services.user_picture_preferences import (
    UserPicturePreferencesError,
    UserPicturePreferencesStore,
)


class UserPicturePreferencesStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "user_picture_preferences_v1.json"
        self.store = UserPicturePreferencesStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_use_clear_round_trip(self) -> None:
        saved = self.store.save_preference(
            "user-1",
            {"preset": "风格006", "pose": "portrait"},
            timestamp=100.0,
        )
        self.assertEqual(saved["user_id"], "user-1")
        self.assertEqual(self.store.get_preference("user-1")["preset"], "风格006")

        self.assertTrue(self.store.clear_preference("user-1"))
        self.assertIsNone(self.store.get_preference("user-1"))
        self.assertFalse(self.store.clear_preference("user-1"))

    def test_store_persists_across_reopen(self) -> None:
        self.store.save_preference(
            "user-2",
            {"clothing": "兔女郎装"},
            timestamp=200.0,
        )
        self.store = UserPicturePreferencesStore(self.path)
        self.assertEqual(
            self.store.get_preference("user-2")["clothing"],
            "兔女郎装",
        )

    def test_ttl_expires_preference(self) -> None:
        self.store.save_preference("user-3", {"preset": "风格001"}, timestamp=100.0)
        self.assertIsNotNone(self.store.get_preference("user-3", timestamp=150.0))
        expired = UserPicturePreferencesStore(self.path, ttl_seconds=30)
        self.assertIsNone(expired.get_preference("user-3", timestamp=200.0))

    def test_invalid_json_fails_loud(self) -> None:
        self.path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(UserPicturePreferencesError):
            UserPicturePreferencesStore(self.path)

    def test_clear_all_removes_everything(self) -> None:
        self.store.save_preference("a", {"preset": "one"})
        self.store.save_preference("b", {"preset": "two"})
        self.assertEqual(self.store.clear_all(), 2)
        self.assertEqual(self.store.all_preferences(), {})


if __name__ == "__main__":
    unittest.main()
