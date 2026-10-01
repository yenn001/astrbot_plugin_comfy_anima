"""Focused regression tests for backend audit fixes OP-01..OP-08/OP-20.

These tests use lightweight AstrBot stubs and exercise the same helper
patterns as the existing ``test_main_compat`` suite.
"""

from __future__ import annotations

import asyncio
import importlib
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from ..models import GeneratedImagePaths
from ..services.comfy_client import ComfyClient
from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import (
    LoraIdentityBinding,
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
)
from ..services.lora_visuals import LoraVisualService
from ..services.task_store import TaskStore


from ._stubs import install_astrbot_stubs


install_astrbot_stubs()
main = importlib.import_module("astrbot_plugin_comfy_anima.main")


class Op01GenerationSlotReleasedBeforeDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_does_not_hold_generation_slot(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._temp_dir = Path(tempfile.mkdtemp())
        semaphore = asyncio.Semaphore(1)
        download_started = asyncio.Event()
        release_download = asyncio.Event()

        class Client:
            @staticmethod
            async def submit(_workflow):
                return "prompt-id"

            @staticmethod
            async def wait_for_images(_prompt_id, _preferred):
                return (object(),)

            @staticmethod
            async def download_image_with_sha(_reference, job_dir):
                download_started.set()
                await release_download.wait()
                path = job_dir / "result.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"image")
                return path, "abc"

        plugin._client = Client()
        plugin._generation_slot = lambda: semaphore
        paths = GeneratedImagePaths()
        job = main.GenerationJob("u", "preview", time.monotonic())
        task = asyncio.create_task(
            plugin._submit_wait_download(
                job,
                {"workflow": True},
                ["out"],
                paths,
                active_state="generating",
            )
        )
        await asyncio.wait_for(download_started.wait(), timeout=1.0)
        # The slot must be free while the download is still in progress.
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.2)
        finally:
            semaphore.release()
            release_download.set()
            await task
        self.assertEqual(paths[0].name, "result.png")
        self.assertEqual(paths.output_sha256s[str(paths[0])], "abc")


class Op02TaskStoreAsyncWritesTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_write_wrappers_persist_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(
                Path(directory) / "task-events.sqlite3",
                max_events=500,
                cleanup_interval=1000,
            )
            try:
                run_id = await store.create_task_async(
                    "audit", requested_by="tester", total_items=1
                )
                await store.start_task_async(run_id, total_items=1)
                await store.append_event_async(
                    run_id, "run", "async write", event_code="audit_async"
                )
                await store.finish_task_async(
                    run_id, "succeeded", completed_items=1, failed_items=0
                )
                task = store.get_task(run_id)
                self.assertIsNotNone(task)
                self.assertEqual(task["status"], "succeeded")
            finally:
                store.close()


class Op03ComfyClientSessionLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_first_get_creates_one_session(self) -> None:
        class FakeSession:
            instances = 0

            def __init__(self, *args, **kwargs):
                type(self).instances += 1
                self.closed = False

            async def close(self):
                self.closed = True

        settings = main.PluginSettings.from_mapping(
            {
                "comfyui_url": "http://127.0.0.1:8188",
                "request_timeout": 10,
            }
        )
        with mock.patch(
            "astrbot_plugin_comfy_anima.services.comfy_client.aiohttp.ClientSession",
            FakeSession,
        ):
            client = ComfyClient(settings)
            try:
                sessions = await asyncio.gather(
                    *(client._get_session() for _ in range(10))
                )
                self.assertEqual(FakeSession.instances, 1)
                self.assertEqual(len({id(session) for session in sessions}), 1)
            finally:
                await client.close()
        self.assertTrue(sessions[0].closed)


class Op04ShaReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_wait_download_stores_downloaded_sha(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._temp_dir = Path(tempfile.mkdtemp())
        plugin._generation_slots = asyncio.Semaphore(1)

        class Client:
            @staticmethod
            async def submit(_workflow):
                return "prompt-id"

            @staticmethod
            async def wait_for_images(_prompt_id, _preferred):
                return (object(),)

            @staticmethod
            async def download_image_with_sha(_reference, job_dir):
                path = job_dir / "result.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"image")
                return path, "deadbeef"

        plugin._client = Client()
        paths = GeneratedImagePaths()
        job = main.GenerationJob("u", "preview", time.monotonic())
        await plugin._submit_wait_download(
            job,
            {"workflow": True},
            ["out"],
            paths,
            active_state="generating",
        )
        self.assertEqual(paths.output_sha256s[str(paths[0])], "deadbeef")


class Op05GpuNameCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_gpu_name_is_cached_within_ttl(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._gpu_name_cache = None
        calls = []

        class Client:
            @staticmethod
            async def gpu_name():
                calls.append(1)
                return "Test GPU"

        plugin._client = Client()
        first = await plugin._safe_gpu_name()
        second = await plugin._safe_gpu_name()
        self.assertEqual(first, "Test GPU")
        self.assertEqual(second, "Test GPU")
        self.assertEqual(len(calls), 1)


class Op06PersistConfigThreadedTests(unittest.IsolatedAsyncioTestCase):
    async def test_persist_config_transaction_returns_true_after_write(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            calls = []
            config_path_value = str(config_path)

            class Config:
                config_path = config_path_value

                def __init__(self):
                    self._data = {}

                def __getitem__(self, key):
                    return self._data[key]

                def __setitem__(self, key, value):
                    self._data[key] = value

                def get(self, key, default=None):
                    return self._data.get(key, default)

                def __contains__(self, key):
                    return key in self._data

                def save_config(self):
                    calls.append(1)
                    config_path.write_text(
                        __import__("json").dumps(self._data),
                        encoding="utf-8",
                    )

            plugin.config = Config()
            result = await plugin._persist_config_updates({"unet_model_name": "x"})
            self.assertTrue(result)
            self.assertEqual(calls, [1])


class Op07SemanticLookupTests(unittest.IsolatedAsyncioTestCase):
    def _index(self) -> LoraSemanticIndex:
        record = LoraRecord(
            name="characters/denia.safetensors",
            sha256="a" * 64,
            category="character",
        )
        entry = SemanticEntry(
            identity_key=semantic_identity_key(record.name, record.sha256),
            canonical_name=record.name,
            sha256=record.sha256,
            analysis_status="searchable",
            category=(SemanticFact("character", "manual"),),
            aliases=(SemanticFact("达妮娅", "manual"),),
            identity_bindings=(
                LoraIdentityBinding(
                    character_canonical="denia_(wuthering_waves)",
                    copyright_canonical="wuthering_waves",
                    activation_terms=("达妮娅",),
                ),
            ),
        )
        return LoraSemanticIndex(entries={entry.identity_key: entry})

    async def test_requested_subject_hint_uses_alias_lookup(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index()
        hint = plugin._requested_subject_hint("画 达妮娅 穿裙子")
        self.assertEqual(hint, "达妮娅")

    def test_requested_subject_hint_parses_named_character_phrases(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index()
        self.assertEqual(
            plugin._requested_subject_hint(
                "风格001-29b 角色是Remielle Dan（Zenless Zone Zero）"
            ),
            "Remielle Dan",
        )
        self.assertEqual(
            plugin._requested_subject_hint(
                "风格001-29b 角色是来自Zenless Zone Zero的Remielle Dan"
            ),
            "Remielle Dan",
        )
        self.assertEqual(
            plugin._requested_subject_hint("画图 角色是Remielle Dan --llm"),
            "Remielle Dan",
        )
        self.assertEqual(
            plugin._requested_subject_hint(
                "/重绘 角色是elaina_(majo_no_tabitabi) --llm"
            ),
            "elaina",
        )

    async def test_subject_binding_gate_can_soft_degrade_to_tag_flow(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._runtime_semantic_index = lambda: self._index()
        plan = types.SimpleNamespace(
            identity_required=True,
            requested_subject="陌生角色",
        )
        self.assertIsNone(
            plugin._resolve_subject_binding_gate(
                plan,
                subject_probe_available=False,
            )
        )

    async def test_subject_binding_gate_uses_canonical_lookup(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index()
        plan = types.SimpleNamespace(
            identity_required=True,
            requested_subject="达妮娅",
        )
        binding = plugin._resolve_subject_binding_gate(
            plan,
            subject_probe_available=True,
        )
        self.assertEqual(binding.canonical, "denia_(wuthering_waves)")


class Op08LoraVisualDirectoryIndexTests(unittest.TestCase):
    def test_build_manifest_enumerates_each_parent_directory_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "loras"
            root.mkdir()
            parent = root / "characters"
            parent.mkdir()
            model1 = parent / "a.safetensors"
            model2 = parent / "b.safetensors"
            model1.write_bytes(b"a")
            model2.write_bytes(b"b")
            service = LoraVisualService((root,), Path(directory) / "cache")
            try:
                records = [
                    LoraRecord(
                        name="characters/a.safetensors",
                        file_path=str(model1),
                        category="unknown",
                    ),
                    LoraRecord(
                        name="characters/b.safetensors",
                        file_path=str(model2),
                        category="unknown",
                    ),
                ]
                seen_files: list[bool] = []
                original_find = service._find_companion

                def wrapped_find(model_path, *, files=None):
                    seen_files.append(files is not None)
                    return original_find(model_path, files=files)

                with mock.patch.object(service, "_find_companion", wrapped_find):
                    manifest = service.build_manifest(records)
                self.assertEqual(manifest.total, 2)
                self.assertEqual(seen_files, [True, True])
            finally:
                service.close(wait=True)


class Op20FullEnvironmentProfileTests(unittest.TestCase):
    def test_legacy_profile_uses_full_environment_snapshot(self) -> None:
        plugin = object.__new__(main.ComfyAnimaPlugin)
        plugin.settings = main.PluginSettings.from_mapping(
            {
                "workflow_dir": "custom_workflows",
                "unet_model_name": "legacy.safetensors",
            }
        )
        plugin.config = {
            "workflow_dir": "custom_workflows",
            "unet_model_name": "legacy.safetensors",
            "upscale_workflow_file": "custom_upscale.json",
        }
        saved = {}

        class Profiles:
            @staticmethod
            def list_profiles():
                return []

            @staticmethod
            def save_profile(name, payload):
                saved[name] = payload

        plugin._config_profiles = Profiles()
        plugin._ensure_builtin_environment_profiles()
        legacy = saved["Anima Legacy"]
        self.assertGreater(len(legacy), 14)
        self.assertEqual(legacy["model_family"], "anima_legacy_28l")
        self.assertEqual(legacy["upscale_workflow_file"], "custom_upscale.json")
        self.assertEqual(legacy["workflow_dir"], "custom_workflows")


if __name__ == "__main__":
    unittest.main()
