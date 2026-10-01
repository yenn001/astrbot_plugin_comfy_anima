"""307 prompt field migration tests (legacy is rollback source only)."""

import unittest

from ..models import (
    PluginSettings,
    migrate_legacy_auto_draw_prompt,
)

_LEGACY_WITH_PROTOCOL = (
    "<图像生成要求>\n输出 <pic prompt=\"...\">，不要输出 JSON。\n"
)


class PromptMigrationTests(unittest.TestCase):
    def test_legacy_field_is_not_copied_into_new_fields(self) -> None:
        migrated = migrate_legacy_auto_draw_prompt(
            {"auto_draw_system_prompt": _LEGACY_WITH_PROTOCOL}
        )
        self.assertEqual(migrated["auto_draw_system_prompt"], _LEGACY_WITH_PROTOCOL)
        self.assertEqual(migrated["chat_roleplay_draw_prompt"], "")
        self.assertEqual(migrated["director_creative_preference"], "")

    def test_existing_new_fields_are_preserved(self) -> None:
        migrated = migrate_legacy_auto_draw_prompt(
            {
                "auto_draw_system_prompt": _LEGACY_WITH_PROTOCOL,
                "chat_roleplay_draw_prompt": "roleplay tone",
                "director_creative_preference": "painterly style",
            }
        )
        self.assertEqual(migrated["chat_roleplay_draw_prompt"], "roleplay tone")
        self.assertEqual(
            migrated["director_creative_preference"], "painterly style"
        )

    def test_from_mapping_parses_new_fields(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "chat_roleplay_draw_prompt": "  roleplay tone  ",
                "director_creative_preference": "  painterly style  ",
            }
        )
        self.assertEqual(settings.chat_roleplay_draw_prompt, "roleplay tone")
        self.assertEqual(
            settings.director_creative_preference, "painterly style"
        )
        self.assertEqual(settings.auto_draw_system_prompt, "")

    def test_migrated_prompt_has_no_protocol_literals(self) -> None:
        migrated = migrate_legacy_auto_draw_prompt(
            {"auto_draw_system_prompt": _LEGACY_WITH_PROTOCOL}
        )
        for field in ("chat_roleplay_draw_prompt", "director_creative_preference"):
            self.assertNotIn("<pic", migrated[field])
            self.assertNotIn("emit_anima_plan_v1", migrated[field])
            self.assertNotIn("JSON", migrated[field])

    def test_chat_and_director_prompt_are_not_identical(self) -> None:
        # Model-level default is empty for both; role-specific defaults are
        # resolved later by PromptCatalog from different prompt files. The
        # migration must never force both fields to the same legacy value.
        migrated = migrate_legacy_auto_draw_prompt(
            {"auto_draw_system_prompt": _LEGACY_WITH_PROTOCOL}
        )
        self.assertEqual(migrated["chat_roleplay_draw_prompt"], "")
        self.assertEqual(migrated["director_creative_preference"], "")


if __name__ == "__main__":
    unittest.main()
