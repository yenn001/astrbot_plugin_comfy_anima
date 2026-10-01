"""Atomic config write-back fault injection tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ..services.atomic_config import (
    AtomicConfigWriteError,
    atomic_write_json,
)


class AtomicConfigTests(unittest.TestCase):
    def test_atomic_write_replaces_complete_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            atomic_write_json(path, {"a": 1, "b": [1, 2]})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"a": 1, "b": [1, 2]},
            )
            atomic_write_json(path, {"c": 3})
            self.assertEqual(json.loads(path.read_text()), {"c": 3})

    def test_directory_fsync_failure_after_replace_does_not_fork(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"old": True}), encoding="utf-8")
            with mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.open",
                return_value=123,
            ), mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.close",
                return_value=None,
            ), mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.fsync",
                side_effect=[None, OSError("dir fsync failed")],
            ):
                atomic_write_json(path, {"new": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"new": True},
            )

    def test_os_replace_failure_keeps_previous_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"old": True}), encoding="utf-8")
            with mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.replace",
                side_effect=OSError("replace denied"),
            ):
                with self.assertRaises(AtomicConfigWriteError):
                    atomic_write_json(path, {"new": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"old": True},
            )


if __name__ == "__main__":
    unittest.main()