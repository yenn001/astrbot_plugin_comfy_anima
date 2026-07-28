"""插件配置模型兼容性测试。"""

import json
import unittest
from pathlib import Path

from ..constants import PLUGIN_VERSION
from ..models import PluginSettings
from ..services.config_profiles import ENVIRONMENT_FIELDS


class PluginSettingsTests(unittest.TestCase):
    """验证 AstrBot 支持的列表配置可转换为内部映射。"""

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
        self.assertTrue(settings.auto_reload_after_style_save)
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

        self.assertEqual(PLUGIN_VERSION, "1.9.4")
        self.assertEqual(metadata_version, PLUGIN_VERSION)
        self.assertIn(f"v{PLUGIN_VERSION}", readme_head)
        self.assertIn(f"## [{PLUGIN_VERSION}] - 2026-07-28", changelog)


if __name__ == "__main__":
    unittest.main()
