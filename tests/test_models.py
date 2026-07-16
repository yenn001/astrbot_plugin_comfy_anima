"""插件配置模型兼容性测试。"""

import unittest

from ..models import PluginSettings


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


if __name__ == "__main__":
    unittest.main()
