"""插件配置模型兼容性测试。"""

import json
import unittest
from pathlib import Path

from ..constants import PLUGIN_VERSION
from ..models import (
    PluginSettings,
    migrate_legacy_consolidated_config,
)
from ..services.config_profiles import ENVIRONMENT_FIELDS


class PluginSettingsTests(unittest.TestCase):
    """验证 AstrBot 支持的列表配置可转换为内部映射。"""

    def test_legacy_director_reference_default_is_migrated(self) -> None:
        settings = PluginSettings.from_mapping(
            {"director_reference_file": "prompts/director_reference.txt"}
        )
        self.assertEqual(
            settings.director_reference_file,
            "prompts/director_creative_default.txt",
        )

    def test_group_levels_accept_schema_list_format(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "group_block_levels": [
                    "123456=full",
                    "654321:none",
                    "invalid",
                    "999=unknown",
                ]
            }
        )

        self.assertEqual(
            settings.group_block_levels,
            {"123456": "full", "654321": "none"},
        )

    def test_chat_picture_terminal_guard_cannot_be_disabled_independently(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "enable_llm_pic_trigger": True,
                "enable_chat_draw_terminal_guard": False,
            }
        )

        self.assertTrue(settings.enable_chat_draw_terminal_guard)

    def test_group_levels_remain_backward_compatible_with_mapping(self) -> None:
        settings = PluginSettings.from_mapping(
            {"group_block_levels": {"123456": "LITE"}}
        )

        self.assertEqual(settings.group_block_levels, {"123456": "lite"})

    def test_lora_manager_defaults_to_comfyui_integration(self) -> None:
        settings = PluginSettings.from_mapping({})

        self.assertTrue(settings.enable_lora_manager)
        self.assertTrue(settings.lora_manager_scan_on_refresh)
        self.assertEqual(settings.lora_manager_page_size, 100)
        self.assertFalse(settings.auto_reload_after_style_save)
        self.assertTrue(settings.enable_unet_switch)
        self.assertEqual(settings.unet_loader_node_id, "429")
        self.assertEqual(settings.unet_model_input_name, "unet_name")

    def test_anima_defaults_include_style_001_and_portrait_resolution(self) -> None:
        settings = PluginSettings.from_mapping({})

        self.assertEqual(settings.default_style_preset, "风格001")
        self.assertEqual((settings.default_width, settings.default_height), (832, 1216))
        self.assertTrue(settings.lora_presets)
        self.assertEqual(settings.lora_presets[0]["name"], "风格001")
        self.assertEqual(
            settings.lora_presets[0]["__template_key"],
            "artist_style_combo",
        )

    def test_lora_alias_rules_remain_a_string_list(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "lora_alias_rules": [
                    "black deniav1-2=达妮娅,denia",
                    "remielle_dan-000028=拉米尔,remielle",
                ]
            }
        )

        self.assertEqual(
            settings.lora_alias_rules,
            [
                "black deniav1-2=达妮娅,denia",
                "remielle_dan-000028=拉米尔,remielle",
            ],
        )

    def test_reverse_json_controls_default_on_and_parse_boolean_strings(self) -> None:
        defaults = PluginSettings.from_mapping({})
        disabled = PluginSettings.from_mapping(
            {
                "enable_reverse_json_formatter": "false",
                "enable_reverse_json_repair_retry": "0",
            }
        )

        self.assertTrue(defaults.enable_reverse_json_formatter)
        self.assertTrue(defaults.enable_reverse_json_repair_retry)
        self.assertFalse(disabled.enable_reverse_json_formatter)
        self.assertFalse(disabled.enable_reverse_json_repair_retry)

    def test_reverse_workflow_schema_defaults_match_safe_runtime_defaults(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        settings = PluginSettings.from_mapping({})
        fields = {
            "enable_workflow_reverse",
            "reverse_backend",
            "reverse_workflow_file",
            "reverse_workflow_timeout",
            "reverse_tagger_model",
            "reverse_general_threshold",
            "reverse_character_threshold",
            "reverse_categories",
            "reverse_session_method",
        }

        for field_name in fields:
            self.assertEqual(schema[field_name]["default"], getattr(settings, field_name))
        self.assertTrue(settings.enable_workflow_reverse)
        self.assertEqual(settings.reverse_backend, "workflow")

    def test_danbooru_auto_update_defaults_off_and_clamps_interval(self) -> None:
        defaults = PluginSettings.from_mapping({})
        low = PluginSettings.from_mapping(
            {
                "danbooru_auto_update_enabled": "true",
                "danbooru_auto_update_interval_hours": 1,
            }
        )
        high = PluginSettings.from_mapping(
            {"danbooru_auto_update_interval_hours": 99999}
        )

        self.assertFalse(defaults.danbooru_auto_update_enabled)
        self.assertEqual(defaults.danbooru_auto_update_interval_hours, 168)
        self.assertTrue(low.danbooru_auto_update_enabled)
        self.assertEqual(low.danbooru_auto_update_interval_hours, 24)
        self.assertEqual(high.danbooru_auto_update_interval_hours, 2160)

    def test_per_user_image_queue_defaults_and_clamps(self) -> None:
        defaults = PluginSettings.from_mapping({})
        disabled = PluginSettings.from_mapping({"max_queued_jobs_per_user": -5})
        high = PluginSettings.from_mapping({"max_queued_jobs_per_user": 999})

        self.assertEqual(defaults.max_queued_jobs_per_user, 3)
        self.assertEqual(disabled.max_queued_jobs_per_user, 0)
        self.assertEqual(high.max_queued_jobs_per_user, 10)

    def test_v170_global_capabilities_have_safe_defaults(self) -> None:
        settings = PluginSettings.from_mapping({})

        self.assertTrue(settings.enable_prompt_asset_library)
        self.assertFalse(settings.prompt_asset_remote_import_enabled)
        self.assertEqual(settings.prompt_asset_max_download_mb, 16)
        self.assertTrue(settings.enable_prompt_lab)
        self.assertEqual(settings.prompt_lab_batch_capacity, 32)
        self.assertEqual(settings.prompt_lab_ttl_seconds, 1800)
        self.assertTrue(settings.enable_lora_visual_gallery)
        self.assertEqual(settings.lora_visual_roots, [])
        self.assertEqual(settings.lora_visual_cache_mb, 256)
        self.assertEqual(settings.lora_visual_warmup_workers, 2)
        self.assertEqual(settings.lora_visual_preview_max_mb, 4)
        self.assertEqual(settings.lora_visual_thumbnail_size, 512)

    def test_v170_global_capabilities_preserve_valid_existing_values(self) -> None:
        raw_config = {
            "comfyui_url": "http://192.168.10.88:8188",
            "enable_prompt_asset_library": False,
            "prompt_asset_remote_import_enabled": True,
            "prompt_asset_max_download_mb": 12,
            "enable_prompt_lab": False,
            "prompt_lab_batch_capacity": 64,
            "prompt_lab_ttl_seconds": 7200,
            "enable_lora_visual_gallery": False,
            "lora_visual_roots": ["/models/loras", " /archive/loras "],
            "lora_visual_cache_mb": 2048,
            "lora_visual_warmup_workers": 4,
            "lora_visual_preview_max_mb": 16,
            "lora_visual_thumbnail_size": 768,
        }

        settings = PluginSettings.from_mapping(raw_config)

        self.assertFalse(settings.enable_prompt_asset_library)
        self.assertTrue(settings.prompt_asset_remote_import_enabled)
        self.assertEqual(settings.prompt_asset_max_download_mb, 12)
        self.assertFalse(settings.enable_prompt_lab)
        self.assertEqual(settings.prompt_lab_batch_capacity, 64)
        self.assertEqual(settings.prompt_lab_ttl_seconds, 7200)
        self.assertFalse(settings.enable_lora_visual_gallery)
        self.assertEqual(
            settings.lora_visual_roots,
            ["/models/loras", "/archive/loras"],
        )
        self.assertEqual(settings.lora_visual_cache_mb, 2048)
        self.assertEqual(settings.lora_visual_warmup_workers, 4)
        self.assertEqual(settings.lora_visual_preview_max_mb, 16)
        self.assertEqual(settings.lora_visual_thumbnail_size, 768)
        self.assertEqual(raw_config["lora_visual_roots"][1], " /archive/loras ")

    def test_v170_global_capability_ranges_are_clamped(self) -> None:
        low = PluginSettings.from_mapping(
            {
                "prompt_asset_max_download_mb": 0,
                "prompt_lab_batch_capacity": -1,
                "prompt_lab_ttl_seconds": 1,
                "lora_visual_cache_mb": -1,
                "lora_visual_warmup_workers": 0,
                "lora_visual_preview_max_mb": 0,
                "lora_visual_thumbnail_size": 1,
            }
        )
        high = PluginSettings.from_mapping(
            {
                "prompt_asset_max_download_mb": 999,
                "prompt_lab_batch_capacity": 999,
                "prompt_lab_ttl_seconds": 999_999,
                "lora_visual_cache_mb": 99_999,
                "lora_visual_warmup_workers": 99,
                "lora_visual_preview_max_mb": 999,
                "lora_visual_thumbnail_size": 9999,
            }
        )

        self.assertEqual(low.prompt_asset_max_download_mb, 1)
        self.assertEqual(low.prompt_lab_batch_capacity, 4)
        self.assertEqual(low.prompt_lab_ttl_seconds, 60)
        self.assertEqual(low.lora_visual_cache_mb, 0)
        self.assertEqual(low.lora_visual_warmup_workers, 1)
        self.assertEqual(low.lora_visual_preview_max_mb, 1)
        self.assertEqual(low.lora_visual_thumbnail_size, 128)
        self.assertEqual(high.prompt_asset_max_download_mb, 16)
        self.assertEqual(high.prompt_lab_batch_capacity, 128)
        self.assertEqual(high.prompt_lab_ttl_seconds, 86400)
        self.assertEqual(high.lora_visual_cache_mb, 8192)
        self.assertEqual(high.lora_visual_warmup_workers, 4)
        self.assertEqual(high.lora_visual_preview_max_mb, 32)
        self.assertEqual(high.lora_visual_thumbnail_size, 1024)

    def test_v170_schema_defaults_match_runtime_defaults(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        settings = PluginSettings.from_mapping({})
        field_names = {
            "enable_prompt_asset_library",
            "prompt_asset_remote_import_enabled",
            "prompt_asset_max_download_mb",
            "enable_prompt_lab",
            "prompt_lab_batch_capacity",
            "prompt_lab_ttl_seconds",
            "enable_lora_visual_gallery",
            "lora_visual_roots",
            "lora_visual_cache_mb",
            "lora_visual_warmup_workers",
            "lora_visual_preview_max_mb",
            "lora_visual_thumbnail_size",
            "show_chat_generation_details",
        }

        for field_name in field_names:
            self.assertIn(field_name, schema)
            self.assertEqual(
                schema[field_name]["default"],
                getattr(settings, field_name),
            )
        self.assertEqual(schema["prompt_asset_max_download_mb"]["min"], 1)
        self.assertEqual(schema["prompt_asset_max_download_mb"]["max"], 16)

    def test_v170_global_capabilities_do_not_enter_environment_profiles(self) -> None:
        global_fields = {
            "enable_prompt_asset_library",
            "prompt_asset_remote_import_enabled",
            "prompt_asset_max_download_mb",
            "enable_prompt_lab",
            "prompt_lab_batch_capacity",
            "prompt_lab_ttl_seconds",
            "enable_lora_visual_gallery",
            "lora_visual_roots",
            "lora_visual_cache_mb",
            "lora_visual_warmup_workers",
            "lora_visual_preview_max_mb",
            "lora_visual_thumbnail_size",
        }

        self.assertTrue(global_fields.isdisjoint(ENVIRONMENT_FIELDS))

    def test_blueprint_g8_config_fields_have_sensible_defaults(self) -> None:
        settings = PluginSettings.from_mapping({})
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        fields = {
            "draw_pipeline_mode": "auto",
            "intent_router_gate_mode": "on",
            "enable_visual_task_intent": True,
            "enable_user_picture_preferences": False,
            "user_picture_preferences_ttl": 0,
            "router_timeout_before_agent": 0.0,
            "enable_scene_extraction": True,
            "scene_extraction_model": "",
            "scene_context_window": 8,
            "scene_extraction_max_memories": 5,
            "natural_draw_mode": "full",
            "character_purity_mode": "smart",
            "scene_extraction": True,
            "chinese_prompt_translation": True,
            "workflow_positive_node_overrides": [],
            "workflow_negative_node_overrides": [],
        }
        for field_name, expected in fields.items():
            with self.subTest(field=field_name):
                self.assertIn(field_name, schema)
                self.assertEqual(getattr(settings, field_name), expected)
                self.assertEqual(schema[field_name]["default"], expected)

    def test_blueprint_g8_fields_are_backward_compatible_and_clamped(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "draw_pipeline_mode": "unknown",
                "intent_router_gate_mode": "enabled",
                "enable_visual_task_intent": "false",
                "enable_user_picture_preferences": "true",
                "user_picture_preferences_ttl": -10,
                "router_timeout_before_agent": 999,
                "enable_scene_extraction": "true",
                "scene_context_window": 999,
                "scene_extraction_max_memories": -2,
            }
        )
        self.assertEqual(settings.draw_pipeline_mode, "auto")
        self.assertEqual(settings.intent_router_gate_mode, "on")
        self.assertFalse(settings.enable_visual_task_intent)
        self.assertTrue(settings.enable_user_picture_preferences)
        self.assertEqual(settings.user_picture_preferences_ttl, 0)
        self.assertEqual(settings.router_timeout_before_agent, 120.0)
        self.assertTrue(settings.enable_scene_extraction)
        self.assertEqual(settings.scene_context_window, 32)
        self.assertEqual(settings.scene_extraction_max_memories, 0)

    def test_config_consolidation_migrates_legacy_flags(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "enable_natural_draw": False,
                "enable_scene_extraction": False,
                "enable_chinese_prompt_translation": False,
            }
        )
        self.assertEqual(settings.natural_draw_mode, "full")
        self.assertTrue(settings.scene_extraction)
        self.assertTrue(settings.chinese_prompt_translation)
        with_specified = PluginSettings.from_mapping(
            {
                "natural_draw_mode": "photo_only",
                "character_purity_mode": "strict",
            }
        )
        self.assertEqual(with_specified.natural_draw_mode, "photo_only")
        self.assertEqual(with_specified.character_purity_mode, "strict")

    def test_consolidated_config_migration_write_back(self) -> None:
        migrated = migrate_legacy_consolidated_config(
            {
                "enable_natural_draw": True,
                "enable_llm_pic_trigger": False,
                "enable_scene_extraction": False,
                "enable_chinese_prompt_translation": False,
            }
        )
        self.assertEqual(migrated["natural_draw_mode"], "photo_only")
        self.assertFalse(migrated["scene_extraction"])
        self.assertFalse(migrated["chinese_prompt_translation"])
        self.assertEqual(migrated["character_purity_mode"], "smart")
        self.assertEqual(migrated["intent_judge_backend"], "auto")
        self.assertEqual(migrated["intent_router_gate_mode"], "on")
        roundtrip = PluginSettings.from_mapping(migrated)
        self.assertEqual(roundtrip.natural_draw_mode, "photo_only")
        self.assertFalse(roundtrip.scene_extraction)
        self.assertFalse(roundtrip.chinese_prompt_translation)

    def test_invalid_migration_version_is_normalized_to_zero(self) -> None:
        migrated = migrate_legacy_consolidated_config(
            {
                "config_migration_version": "not-an-int",
                "enable_natural_draw": False,
            }
        )
        self.assertEqual(migrated["config_migration_version"], 2)
        self.assertEqual(migrated["natural_draw_mode"], "off")

    def test_migration_four_legacy_combinations(self) -> None:
        cases = (
            ({"enable_natural_draw": False}, "off"),
            ({"enable_natural_draw": None}, "full"),
            (
                {"enable_natural_draw": True, "enable_llm_pic_trigger": False},
                "photo_only",
            ),
            (
                {"enable_natural_draw": True, "enable_llm_pic_trigger": True},
                "full",
            ),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                migrated = migrate_legacy_consolidated_config(raw)
                self.assertEqual(migrated["natural_draw_mode"], expected)
                self.assertEqual(migrated["config_migration_version"], 2)

    def test_natural_draw_mode_presence_beats_legacy_flags(self) -> None:
        migrated = migrate_legacy_consolidated_config(
            {
                "natural_draw_mode": "photo_only",
                "enable_natural_draw": False,
            }
        )
        self.assertEqual(migrated["natural_draw_mode"], "photo_only")

    def test_version_two_missing_utc_is_stamped(self) -> None:
        migrated = migrate_legacy_consolidated_config(
            {
                "natural_draw_mode": "full",
                "config_migration_version": 2,
                "config_migrated_utc": "",
            }
        )
        self.assertTrue(migrated["config_migrated_utc"])

    def test_migration_version_two_is_idempotent(self) -> None:
        base = {
            "natural_draw_mode": "photo_only",
            "enable_natural_draw": False,
            "config_migration_version": 2,
            "config_migrated_utc": "2026-08-31T00:00:00Z",
        }
        merged = migrate_legacy_consolidated_config(base)
        self.assertEqual(merged, base)

    def test_legacy_schema_fields_are_invisible_and_readonly(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        for field in (
            "enable_natural_draw",
            "enable_llm_pic_trigger",
            "director_primary",
            "enable_scene_extraction",
            "enable_chinese_prompt_translation",
        ):
            with self.subTest(field=field):
                self.assertTrue(schema[field]["deprecated"])
                self.assertTrue(schema[field]["readonly"])
                self.assertTrue(schema[field]["invisible"])

    def test_release_version_is_synchronized(self) -> None:
        plugin_dir = Path(__file__).resolve().parents[1]
        metadata_lines = (plugin_dir / "metadata.yaml").read_text(
            encoding="utf-8"
        ).splitlines()
        metadata_version = next(
            line.split(":", 1)[1].strip()
            for line in metadata_lines
            if line.startswith("version:")
        )
        readme_head = "\n".join(
            (plugin_dir / "README.md").read_text(encoding="utf-8").splitlines()[:5]
        )
        changelog = (plugin_dir / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(PLUGIN_VERSION, "2.4.1")
        self.assertEqual(metadata_version, PLUGIN_VERSION)
        self.assertIn(f"v{PLUGIN_VERSION}", readme_head)
        self.assertIn(f"## [{PLUGIN_VERSION}] - 2026-08-30", changelog)


if __name__ == "__main__":
    unittest.main()
