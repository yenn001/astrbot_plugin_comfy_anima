"""Tests for the persistent task/event and runtime-log store."""

from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..services.task_store import TaskStore, TaskStoreError


class TaskStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "task-events.sqlite3"
        self.store = TaskStore(
            self.database_path,
            retention_days=30,
            max_tasks=100,
            max_events=500,
            max_runtime_logs=500,
            cleanup_interval=1000,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_wal_and_task_lifecycle_persist_across_reopen(self) -> None:
        self.assertEqual(self.store.journal_mode, "wal")
        base = time.time()
        run_id = self.store.create_task(
            "lora_archive",
            mode="selected",
            requested_by="admin",
            total_items=2,
            metadata={"names": ["character-a.safetensors"]},
            timestamp=base,
        )
        started = self.store.start_task(run_id, timestamp=base + 1)
        self.assertEqual(started["status"], "running")
        heartbeat = self.store.heartbeat(
            run_id,
            completed_items=1,
            failed_items=0,
            timestamp=base + 2,
        )
        self.assertEqual(heartbeat["completed_items"], 1)
        finished = self.store.finish_task(
            run_id,
            "succeeded",
            completed_items=2,
            result={"updated_names": ["character-a.safetensors"]},
            timestamp=base + 3,
        )
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["result"]["updated_names"], ["character-a.safetensors"])

        self.store.close()
        self.store = TaskStore(self.database_path, cleanup_interval=1000)
        restored = self.store.get_task(run_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored["status"], "succeeded")
        self.assertEqual(restored["ended_at"], base + 3)

    def test_events_are_incremental_and_sensitive_payloads_are_omitted(self) -> None:
        run_id = self.store.create_task(
            "lora_archive",
            metadata={
                "api_key": "top-secret",
                "system_prompt": "full private system prompt",
            },
        )
        first = self.store.append_event(
            run_id,
            "metadata",
            "Authorization: Bearer token-value; fetched metadata",
            details={
                "prompt": "raw prompt must not persist",
                "response": {"content": "complete response must not persist"},
                "password": "password-value",
                "safe_count": 3,
            },
        )
        second = self.store.append_event(run_id, "llm", "batch finished")
        initial = self.store.read_events(run_id=run_id, after_seq=first - 1, limit=1)
        self.assertEqual(initial["cursor"], first)
        self.assertEqual(len(initial["entries"]), 1)
        incremental = self.store.read_events(
            run_id=run_id,
            after_seq=initial["cursor"],
        )
        self.assertEqual(incremental["cursor"], second)
        self.assertEqual(incremental["entries"][0]["message"], "batch finished")

        event = initial["entries"][0]
        serialized = str(event)
        for secret in (
            "token-value",
            "raw prompt must not persist",
            "complete response must not persist",
            "password-value",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(event["details"]["prompt"]["omitted"], True)
        self.assertEqual(event["details"]["response"]["omitted"], True)
        self.assertEqual(event["details"]["password"], "***")
        task = self.store.get_task(run_id)
        self.assertEqual(task["metadata"]["api_key"], "***")
        self.assertTrue(task["metadata"]["system_prompt"]["omitted"])

    def test_recent_tasks_filters_and_restart_interrupts_running_only(self) -> None:
        base = time.time()
        running = self.store.create_task("lora_archive", status="running", timestamp=base)
        queued = self.store.create_task("metadata_fetch", status="queued", timestamp=base + 1)
        complete = self.store.create_task("lora_archive", status="running", timestamp=base + 2)
        self.store.finish_task(complete, "succeeded", timestamp=base + 3)

        recent = self.store.recent_tasks(task_type="lora_archive")
        self.assertEqual([item["run_id"] for item in recent], [complete, running])
        self.store.close()
        self.store = TaskStore(self.database_path, cleanup_interval=1000)
        self.assertEqual(self.store.get_task(running)["status"], "interrupted")
        self.assertEqual(
            self.store.get_task(running)["error_code"],
            "plugin_restarted",
        )
        self.assertEqual(self.store.get_task(queued)["status"], "queued")
        self.assertEqual(self.store.get_task(complete)["status"], "succeeded")
        interrupted = self.store.recent_tasks(statuses=["interrupted"])
        self.assertEqual([item["run_id"] for item in interrupted], [running])

    def test_runtime_logs_persist_incrementally_and_redact_secrets(self) -> None:
        base = time.time()
        first = self.store.append_runtime_log(
            "WARN",
            "lora",
            "services/lora_archiver.py",
            42,
            "api_token=hidden-value metadata request failed",
            run_id="run-1",
            timestamp=base,
        )
        second = self.store.append_runtime_log(
            "ERROR",
            "llm",
            "main.py",
            2200,
            "LLM request timed out",
            run_id="run-1",
            timestamp=base + 1,
        )
        page = self.store.read_runtime_logs(run_id="run-1", limit=1)
        self.assertEqual(page["cursor"], first)
        self.assertEqual(page["entries"][0]["level"], "WARNING")
        self.assertNotIn("hidden-value", page["entries"][0]["message"])
        remaining = self.store.read_runtime_logs(
            run_id="run-1", after_seq=page["cursor"]
        )
        self.assertEqual(remaining["cursor"], second)
        self.assertEqual(remaining["entries"][0]["category"], "llm")

        self.store.close()
        self.store = TaskStore(self.database_path, cleanup_interval=1000)
        restored = self.store.read_runtime_logs(run_id="run-1")
        self.assertEqual(len(restored["entries"]), 2)

    def test_capacity_and_retention_cleanup(self) -> None:
        self.store.close()
        self.store = TaskStore(
            self.database_path,
            retention_days=1,
            max_tasks=2,
            max_events=3,
            max_runtime_logs=3,
            cleanup_interval=1000,
        )
        old_task = self.store.create_task("old", status="running", timestamp=1)
        self.store.append_event(old_task, "start", "old", timestamp=1)
        self.store.finish_task(old_task, "succeeded", timestamp=2)
        for index in range(4):
            run_id = self.store.create_task("new", status="running", timestamp=100 + index)
            self.store.append_event(run_id, "batch", f"event {index}", timestamp=100 + index)
            self.store.finish_task(run_id, "succeeded", timestamp=100 + index)
            self.store.append_runtime_log(
                "INFO", "plugin", "test", index, f"log {index}", timestamp=100 + index
            )
        removed = self.store.cleanup(now=1000 + 86400)
        self.assertGreaterEqual(removed["tasks"], 3)
        self.assertLessEqual(len(self.store.recent_tasks(limit=100)), 2)
        self.assertLessEqual(len(self.store.read_events(limit=100)["entries"]), 3)
        self.assertLessEqual(len(self.store.read_runtime_logs(limit=100)["entries"]), 3)

    def test_thread_safe_event_and_log_appends(self) -> None:
        run_id = self.store.create_task("parallel", status="running")

        def write(index: int) -> tuple[int, int]:
            event_seq = self.store.append_event(
                run_id, "parallel", f"event {index}", item_name=str(index)
            )
            log_seq = self.store.append_runtime_log(
                "INFO", "plugin", "test", index, f"log {index}", run_id=run_id
            )
            return event_seq, log_seq

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(100)))
        self.assertEqual(len({item[0] for item in results}), 100)
        self.assertEqual(len({item[1] for item in results}), 100)
        parallel_events = [
            event
            for event in self.store.read_events(run_id=run_id, limit=200)["entries"]
            if event["phase"] == "parallel"
        ]
        self.assertEqual(len(parallel_events), 100)
        explicit_logs = [
            entry
            for entry in self.store.read_runtime_logs(run_id=run_id, limit=500)["entries"]
            if entry["source"] == "test"
        ]
        self.assertEqual(len(explicit_logs), 100)

    def test_task_lifecycle_and_stage_events_mirror_to_persistent_console(self) -> None:
        run_id = self.store.create_task(
            "lora_semantic_analysis",
            total_items=1,
            metadata={"prompt": "must never be persisted"},
        )
        self.store.start_task(run_id, total_items=1)
        self.store.append_event(
            run_id,
            "metadata",
            "LoRA 资料包已就绪（健康状态：complete）。",
            item_name="character-a.safetensors",
            batch_index=1,
            batch_total=1,
            event_code="metadata_fetch_completed",
            duration_ms=245,
        )
        for _ in range(2):
            self.store.append_event(
                run_id,
                "heartbeat",
                "Waiting for the semantic-analysis provider.",
                item_name="character-a.safetensors",
                batch_index=1,
                batch_total=1,
                event_code="provider_heartbeat",
            )
        self.store.finish_task(
            run_id,
            "failed",
            completed_items=0,
            failed_items=1,
            error_code="provider_error",
            error_summary="Provider did not return a valid response.",
        )

        events = self.store.read_events(run_id=run_id, limit=100)["entries"]
        codes = [event["event_code"] for event in events]
        for expected in (
            "task_created",
            "task_starting",
            "task_started",
            "metadata_fetch_completed",
            "task_finishing",
            "task_finished",
        ):
            self.assertIn(expected, codes)

        logs = self.store.read_runtime_logs(run_id=run_id, limit=100)["entries"]
        messages = [entry["message"] for entry in logs]
        self.assertTrue(all(entry["category"] == "lora" for entry in logs))
        self.assertTrue(all(entry["source"] == "task/lora_semantic_analysis" for entry in logs))
        self.assertTrue(any("LoRA=character-a.safetensors" in message for message in messages))
        self.assertTrue(any("耗时=245ms" in message for message in messages))
        self.assertTrue(any("状态=failed" in message for message in messages))
        self.assertTrue(any("Provider did not return" in message for message in messages))
        self.assertEqual(
            sum("事件=provider_heartbeat" in message for message in messages),
            1,
        )
        self.assertNotIn("must never be persisted", str(events) + str(logs))

    def test_recent_runtime_logs_and_clear_survive_reopen(self) -> None:
        for index in range(5):
            self.store.append_runtime_log(
                "INFO", "plugin", "test", index, f"log {index}", timestamp=index + 1
            )
        recent = self.store.recent_runtime_logs(limit=3)
        self.assertEqual([item["message"] for item in recent], ["log 2", "log 3", "log 4"])
        self.assertEqual(self.store.clear_runtime_logs(), 5)
        self.store.close()
        self.store = TaskStore(self.database_path, cleanup_interval=1000)
        self.assertEqual(self.store.recent_runtime_logs(limit=10), [])

    def test_unknown_task_and_invalid_terminal_state_fail_closed(self) -> None:
        with self.assertRaises(TaskStoreError):
            self.store.append_event("missing", "start", "message")
        run_id = self.store.create_task("test")
        with self.assertRaises(ValueError):
            self.store.finish_task(run_id, "running")


if __name__ == "__main__":
    unittest.main()
