"""Tests for secret-free, named ComfyUI environment profiles."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ..services.config_profiles import (
    ENVIRONMENT_FIELDS,
    ConfigProfileApplyError,
    ConfigProfileConflictError,
    ConfigProfileNotFoundError,
    ConfigProfileService,
    ConfigProfileStorageError,
    ConfigProfileValidationError,
)


def _config(ip: str = "192.168.1.50") -> dict[str, Any]:
    return {
        "comfyui_url": f"http://{ip}:8188",
        "workflow_file": "workflow/anima_api.json",
        "workflow_dir": "workflow",
        "unet_catalog_url": f"http://{ip}:8188/object_info/UNETLoader",
        "unet_loader_node_id": "429",
        "unet_model_input_name": "unet_name",
        "unet_model_name": "anima-v1.safetensors",
        "lora_catalog_url": f"http://{ip}:8188/object_info",
        "lora_manager_url": f"http://{ip}:8188/loras",
        "lora_loader_node_id": "462",
        "prompt_node_id": "210",
        "negative_node_id": "13",
        "primary_seed_node_id": "8",
        "secondary_seed_node_id": "262",
        "resolution_node_id": "437",
        "sampler_node_ids": ["8"],
        "output_node_ids": ["285", "20"],
        "upscale_output_node_id": "285",
        "default_width": 832,
        "default_height": 1216,
        # These values must never enter or be modified by a normal profile.
        "api_token": "comfy-secret",
        "web_ui_username": "yen",
        "web_ui_password": "web-secret",
        "prompt_llm_provider_id": "openai-custom-1",
        "prompt_llm_api_key": "director-secret",
        "auto_draw_system_prompt": "private director prompt",
        "global_lock": True,
    }


class _SavingConfig(dict[str, Any]):
    def __init__(self, *args: Any, fail: bool = False, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.fail = fail
        self.saved = 0

    def save_config(self) -> None:
        self.saved += 1
        if self.fail:
            raise RuntimeError("disk unavailable")


class ConfigProfileServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.storage_path = Path(self.temporary_directory.name) / "config_profiles.json"
        self.service = ConfigProfileService(self.storage_path)

    def test_save_and_export_include_only_allowlisted_environment_fields(self) -> None:
        profile = self.service.save_profile("主工作站 192.168.1.50", _config())

        self.assertEqual(set(profile["settings"]), ENVIRONMENT_FIELDS)
        self.assertEqual(
            profile["settings"]["comfyui_url"],
            "http://192.168.1.50:8188",
        )
        raw_file = self.storage_path.read_text(encoding="utf-8")
        export = json.dumps(
            self.service.export_profile("主工作站 192.168.1.50"),
            ensure_ascii=False,
        )
        for secret in (
            "comfy-secret",
            "web-secret",
            "director-secret",
            "private director prompt",
        ):
            self.assertNotIn(secret, raw_file)
            self.assertNotIn(secret, export)
        self.assertNotIn("api_token", raw_file)
        self.assertNotIn("prompt_llm_provider_id", raw_file)

    def test_create_list_overwrite_and_casefold_conflict(self) -> None:
        first = self.service.save_profile("Studio", _config(), activate=True)
        self.assertTrue(first["active"])

        with self.assertRaises(ConfigProfileConflictError):
            self.service.save_profile("studio", _config("192.168.1.51"))

        updated = self.service.save_profile(
            "studio",
            _config("192.168.1.51"),
            overwrite=True,
        )
        self.assertEqual(updated["created_at"], first["created_at"])
        self.assertEqual(updated["name"], "studio")
        self.assertEqual(len(self.service.list_profiles()), 1)
        self.assertTrue(self.service.list_profiles()[0]["active"])

    def test_profile_name_is_unicode_friendly_but_path_safe(self) -> None:
        saved = self.service.save_profile("日常绘图・34号", _config())
        self.assertEqual(saved["name"], "日常绘图・34号")

        for invalid in ("", "..", "../escape", "bad\\name", "bad:name", "a\nname"):
            with self.subTest(name=invalid):
                with self.assertRaises(ConfigProfileValidationError):
                    self.service.save_profile(invalid, _config())

    def test_switch_applies_environment_and_preserves_global_and_secrets(self) -> None:
        self.service.save_profile("34号", _config("192.168.1.50"))
        current = _SavingConfig(_config("192.168.1.60"))
        current["api_token"] = "current-comfy-secret"
        current["web_ui_password"] = "current-web-secret"
        current["prompt_llm_provider_id"] = "current-director"
        current["global_lock"] = False

        switched = self.service.switch_profile("34号", current)

        self.assertTrue(switched["active"])
        self.assertEqual(current["comfyui_url"], "http://192.168.1.50:8188")
        self.assertEqual(current["lora_manager_url"], "http://192.168.1.50:8188/loras")
        self.assertEqual(current["unet_model_name"], "anima-v1.safetensors")
        self.assertEqual(current["api_token"], "current-comfy-secret")
        self.assertEqual(current["web_ui_password"], "current-web-secret")
        self.assertEqual(current["prompt_llm_provider_id"], "current-director")
        self.assertFalse(current["global_lock"])
        self.assertEqual(current.saved, 1)
        self.assertTrue(self.service.get_profile("34号")["active"])

    def test_switch_accepts_plugin_persist_updates_callback(self) -> None:
        self.service.save_profile("34号", _config("192.168.1.50"))
        current = _config("192.168.1.60")
        calls: list[dict[str, Any]] = []

        def persist_updates(updates: dict[str, Any]) -> bool:
            calls.append(updates)
            current.update(updates)
            return True

        self.service.activate_profile(
            "34号",
            current,
            persist_updates=persist_updates,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]), ENVIRONMENT_FIELDS)
        self.assertEqual(current["comfyui_url"], "http://192.168.1.50:8188")

    def test_failed_plugin_save_rolls_back_without_marking_active(self) -> None:
        self.service.save_profile("34号", _config("192.168.1.50"))
        current = _SavingConfig(_config("192.168.1.60"), fail=True)
        previous = dict(current)

        with self.assertRaises(ConfigProfileApplyError):
            self.service.activate_profile("34号", current)

        self.assertEqual(dict(current), previous)
        self.assertFalse(self.service.get_profile("34号")["active"])

    def test_active_marker_write_failure_rolls_configuration_back(self) -> None:
        self.service.save_profile("34号", _config("192.168.1.50"))
        current = _SavingConfig(_config("192.168.1.60"))
        previous = dict(current)

        with mock.patch.object(
            self.service,
            "_write_state",
            side_effect=ConfigProfileStorageError("read-only"),
        ):
            with self.assertRaises(ConfigProfileApplyError):
                self.service.activate_profile("34号", current)

        self.assertEqual(dict(current), previous)
        self.assertEqual(current.saved, 2)

    def test_import_rejects_unknown_or_sensitive_settings(self) -> None:
        exported = {
            "schema": "astrbot-comfy-anima-environment-profile",
            "version": 1,
            "profile": {
                "name": "malicious",
                "created_at": "2026-07-15T00:00:00Z",
                "updated_at": "2026-07-15T00:00:00Z",
                "settings": {
                    **{
                        key: value
                        for key, value in self.service.save_profile(
                            "safe",
                            _config(),
                        )["settings"].items()
                    },
                    "web_ui_password": "smuggled-secret",
                },
            },
        }

        with self.assertRaises(ConfigProfileValidationError):
            self.service.import_profile(exported)
        self.assertNotIn("smuggled-secret", self.storage_path.read_text("utf-8"))

    def test_url_credentials_and_query_tokens_are_rejected(self) -> None:
        for url in (
            "http://user:password@192.168.1.50:8188",
            "http://192.168.1.50:8188?token=secret",
            "ftp://192.168.1.50:8188",
        ):
            config = _config()
            config["comfyui_url"] = url
            with self.subTest(url=url):
                with self.assertRaises(ConfigProfileValidationError):
                    self.service.save_profile(url.split(":", 1)[0], config)

    def test_delete_clears_active_profile(self) -> None:
        self.service.save_profile("34号", _config(), activate=True)

        deleted = self.service.delete_profile("34号")

        self.assertTrue(deleted["active"])
        self.assertEqual(self.service.list_profiles(), [])
        with self.assertRaises(ConfigProfileNotFoundError):
            self.service.get_profile("34号")

    def test_json_write_is_atomic_and_leaves_no_temporary_file(self) -> None:
        self.service.save_profile("34号", _config())

        parsed = json.loads(self.storage_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["schema"], "astrbot-comfy-anima-environment-profile")
        temporary_files = list(self.storage_path.parent.glob(".*.tmp"))
        self.assertEqual(temporary_files, [])

    def test_corrupted_store_is_not_silently_overwritten(self) -> None:
        self.storage_path.write_text("{not-json", encoding="utf-8")

        with self.assertRaises(ConfigProfileStorageError):
            self.service.save_profile("34号", _config())

        self.assertEqual(self.storage_path.read_text("utf-8"), "{not-json")


if __name__ == "__main__":
    unittest.main()
