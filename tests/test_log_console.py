"""Tests for the plugin-only redacted WebUI log buffer."""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

from ..services.log_console import PluginLogConsole, redact_log_text
from ..services.task_store import TaskStore


class LogRedactionTests(unittest.TestCase):
    def test_common_credentials_are_redacted(self) -> None:
        text = (
            'api_key=plain-secret api_token=token-secret '
            'password: "two words secret" '
            'Authorization: Bearer abc.def.ghi '
            'https://user:pass@example.test/path?token=query-secret '
            'sk-exampleSecretKey123456'
        )
        redacted = redact_log_text(text)
        for secret in (
            "plain-secret",
            "token-secret",
            "two words secret",
            "abc.def.ghi",
            "user",
            "query-secret",
            "exampleSecretKey123456",
        ):
            self.assertNotIn(secret, redacted)
        self.assertNotIn("user:pass@", redacted)
        self.assertIn("api_key=***", redacted)
        self.assertIn("Authorization: ***", redacted)

    def test_quoted_json_secret_is_redacted(self) -> None:
        redacted = redact_log_text('{"api_key":"jsonSecret123", "model":"ok"}')
        self.assertNotIn("jsonSecret123", redacted)
        self.assertIn('"model":"ok"', redacted)


class PluginLogConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.plugin_dir = Path(self.temp_dir.name)
        self.source = self.plugin_dir / "services" / "worker.py"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("# test", encoding="utf-8")
        self.logger = logging.getLogger(f"comfy-anima-test-{id(self)}")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.console = PluginLogConsole(self.plugin_dir, capacity=100)
        self.assertTrue(self.console.attach(self.logger))

    def tearDown(self) -> None:
        self.console.close()
        self.logger.handlers.clear()
        self.temp_dir.cleanup()

    def _record(self, message: str, *, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            self.logger.name,
            level,
            str(self.source),
            42,
            message,
            (),
            None,
            func="run",
        )

    def test_captures_plugin_records_and_ignores_unrelated_sources(self) -> None:
        self.console.emit(self._record("LoRA refresh complete"))
        unrelated = logging.LogRecord(
            self.logger.name,
            logging.ERROR,
            str(self.plugin_dir.parent / "other.py"),
            5,
            "unrelated error",
            (),
            None,
        )
        self.console.emit(unrelated)
        snapshot = self.console.snapshot()
        self.assertEqual(snapshot["buffer_size"], 1)
        entry = snapshot["entries"][0]
        self.assertEqual(entry["category"], "lora")
        self.assertEqual(entry["source"], "services/worker.py")
        self.assertEqual(entry["line"], 42)

    def test_external_record_cannot_spoof_the_plugin_marker(self) -> None:
        spoofed = logging.LogRecord(
            self.logger.name,
            logging.ERROR,
            str(self.plugin_dir.parent / "other.py"),
            5,
            "[astrbot_plugin_comfy_anima] api_token=must-not-enter",
            (),
            None,
        )
        self.console.emit(spoofed)
        self.assertEqual(self.console.snapshot()["buffer_size"], 0)

    def test_cursor_limit_counts_and_clear(self) -> None:
        for index in range(6):
            level = logging.ERROR if index == 5 else logging.INFO
            self.console.emit(self._record(f"message {index}", level=level))
        first = self.console.snapshot(after_id=0, limit=3)
        self.assertTrue(first["truncated"])
        self.assertEqual([item["id"] for item in first["entries"]], [4, 5, 6])
        self.assertEqual(first["counts"]["INFO"], 5)
        self.assertEqual(first["counts"]["ERROR"], 1)

        self.console.emit(self._record("message 6", level=logging.WARNING))
        incremental = self.console.snapshot(after_id=first["cursor"], limit=10)
        self.assertEqual(len(incremental["entries"]), 1)
        self.assertEqual(incremental["entries"][0]["level"], "WARNING")

        cleared = self.console.clear_buffer()
        self.assertEqual(cleared["removed"], 7)
        empty = self.console.snapshot(after_id=0)
        self.assertEqual(empty["buffer_size"], 0)
        self.assertEqual(empty["cursor"], 7)
        self.assertEqual(empty["clear_generation"], 1)
        second_clear = self.console.clear_buffer()
        self.assertEqual(second_clear["removed"], 0)
        self.assertEqual(second_clear["clear_generation"], 2)

    def test_eviction_gap_is_reported(self) -> None:
        for index in range(150):
            self.console.emit(self._record(f"message {index}"))
        snapshot = self.console.snapshot(after_id=1, limit=100)
        self.assertTrue(snapshot["gap"])
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["missed"], 49)
        self.assertEqual(snapshot["oldest_id"], 51)

    def test_exception_traceback_is_redacted(self) -> None:
        try:
            raise ValueError("api_token=traceback-secret")
        except ValueError:
            record = logging.LogRecord(
                self.logger.name,
                logging.ERROR,
                str(self.source),
                55,
                "operation failed",
                (),
                sys.exc_info(),
                func="run",
            )
        self.console.emit(record)
        message = self.console.snapshot()["entries"][0]["message"]
        self.assertIn("ValueError", message)
        self.assertNotIn("traceback-secret", message)

    def test_attach_replaces_a_stale_plugin_console_handler(self) -> None:
        replacement = PluginLogConsole(self.plugin_dir, capacity=100)
        try:
            self.assertTrue(replacement.attach(self.logger))
            marked = [
                handler
                for handler in self.logger.handlers
                if getattr(handler, PluginLogConsole._handler_marker, False)
            ]
            self.assertEqual(marked, [replacement])
        finally:
            replacement.close()

    def test_persistent_store_restores_logs_after_console_reload(self) -> None:
        database_path = self.plugin_dir / "task-events.sqlite3"
        first_store = TaskStore(database_path, cleanup_interval=1000)
        first = PluginLogConsole(
            self.plugin_dir,
            capacity=100,
            persistent_store=first_store,
        )
        first.emit(self._record("persistent LoRA event"))
        first.close()
        first_store.close()

        second_store = TaskStore(database_path, cleanup_interval=1000)
        second = PluginLogConsole(
            self.plugin_dir,
            capacity=100,
            persistent_store=second_store,
        )
        try:
            snapshot = second.snapshot(after_id=0)
            self.assertEqual(snapshot["buffer_size"], 1)
            self.assertEqual(snapshot["entries"][0]["message"], "persistent LoRA event")
            second.clear_buffer()
        finally:
            second.close()
            second_store.close()

        third_store = TaskStore(database_path, cleanup_interval=1000)
        third = PluginLogConsole(
            self.plugin_dir,
            capacity=100,
            persistent_store=third_store,
        )
        try:
            self.assertEqual(third.snapshot()["buffer_size"], 0)
        finally:
            third.close()
            third_store.close()

    def test_task_event_mirror_is_visible_without_console_reload(self) -> None:
        store = TaskStore(
            self.plugin_dir / "live-task-events.sqlite3",
            cleanup_interval=1000,
        )
        console = PluginLogConsole(
            self.plugin_dir,
            capacity=100,
            persistent_store=store,
        )
        try:
            run_id = store.create_task("lora_semantic_analysis", total_items=1)
            initial = console.snapshot(after_id=0)
            self.assertTrue(
                any("事件=task_created" in entry["message"] for entry in initial["entries"])
            )
            cursor = initial["cursor"]
            store.append_event(
                run_id,
                "metadata",
                "LoRA detail package is complete.",
                item_name="character-a.safetensors",
                event_code="metadata_fetch_completed",
            )
            incremental = console.snapshot(after_id=cursor)
            self.assertEqual(len(incremental["entries"]), 1)
            entry = incremental["entries"][0]
            self.assertEqual(entry["category"], "lora")
            self.assertEqual(entry["source"], "task/lora_semantic_analysis")
            self.assertIn("LoRA=character-a.safetensors", entry["message"])
            self.assertIn("事件=metadata_fetch_completed", entry["message"])
        finally:
            console.close()
            store.close()


if __name__ == "__main__":
    unittest.main()
