"""构建 3.1.441：WebUI 配置面对接（P1–P3）回归。

核心不变量：**设置表单里渲染的每个字段都必须可保存**。此前有 4 个字段
（Bot 回复意图续画）只渲染在白名单之外，保存被静默丢弃。

另外覆盖 BOT 角色绑定在保存期的合法性校验（fail loud，与运行期 fail-soft 相对）。
"""

import importlib
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs
from ..services.lora_presets import LoraPresetRegistry

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

CHARACTER_PRESET = {
    "__template_key": "character_combo",
    "name": "\u8fbe\u59ae\u5a05",
    "loras": ["29B/anima-000040_29b=0.9"],
    "identity_anchor": "denia_(wuthering_waves)",
    "required_trigger_terms": ["denia_(wuthering_waves)"],
    "enabled": True,
}
BARE_PRESET = {
    "__template_key": "character_combo",
    "name": "\u88f8\u89d2\u8272",
    "loras": ["bare=0.5"],
    "enabled": True,
}


def _settings_form_field_names() -> set[str]:
    html = (PLUGIN_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    marker = html.find('id="settings-form"')
    start = html.rfind("<form", 0, marker)
    end = html.find("</form>", start)
    return set(re.findall(r'name="([a-z][a-z0-9_]*)"', html[start:end]))


class SettingsSurfaceTests(unittest.TestCase):
    """表单字段必须全部可保存（对应审计 A 类归零）。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_every_rendered_field_is_saveable(self) -> None:
        form_fields = _settings_form_field_names()
        self.assertTrue(form_fields, "设置表单没有解析到任何字段")
        editable = set(self.main.WEB_UI_EDITABLE_FIELDS)
        legacy = set(self.main.WEB_UI_LEGACY_FIELDS)
        orphan = sorted(form_fields - editable - legacy)
        self.assertEqual(
            orphan,
            [],
            "以下字段渲染在设置表单里但不在保存白名单，保存会被静默丢弃："
            + ", ".join(orphan),
        )

    def test_reply_draw_fields_are_saveable(self) -> None:
        """P1：本次修复的四个 Bot 回复字段。"""
        editable = set(self.main.WEB_UI_EDITABLE_FIELDS)
        for key in (
            "enable_bot_reply_draw",
            "bot_reply_draw_cooldown_seconds",
            "bot_reply_intent_backend",
            "bot_reply_draw_delivery_phrases",
        ):
            self.assertIn(key, editable)

    def test_new_binding_fields_are_saveable(self) -> None:
        """P2：绑定与静默开关。"""
        editable = set(self.main.WEB_UI_EDITABLE_FIELDS)
        for key in (
            "enable_bot_character_binding",
            "bot_character_preset",
            "bot_character_preset_scopes",
            "suppress_intermediate_draw_text",
        ):
            self.assertIn(key, editable)

    def test_p3_fields_are_saveable(self) -> None:
        """P3：意图判定与提示词定制。"""
        editable = set(self.main.WEB_UI_EDITABLE_FIELDS)
        for key in (
            "chat_roleplay_draw_prompt",
            "director_extra_instruction",
            "director_creative_preference",
            "intent_judge_positive_anchors",
            "intent_judge_negative_anchors",
            "intent_judge_fallback",
            "intent_judge_online_temperature",
            "intent_router_min_confidence",
            "enable_local_intent_router",
        ):
            self.assertIn(key, editable)

    def test_assets_copies_match(self) -> None:
        """pages/control/ 必须与 web/ 真源保持一致（同一份 app.js）。"""
        for name in ("app.js", "app.css", "theme.js"):
            self.assertEqual(
                (PLUGIN_ROOT / "web" / name).read_bytes(),
                (PLUGIN_ROOT / "pages" / "control" / name).read_bytes(),
                f"{name} 未同步：请运行 scripts/sync_web_assets.py",
            )


class CharacterBindingSaveValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_presets = LoraPresetRegistry(
            [CHARACTER_PRESET, BARE_PRESET], max_loras=8
        )
        return plugin

    def test_valid_binding_accepted(self) -> None:
        plugin = self._plugin()
        plugin._validate_web_ui_character_binding(
            {"bot_character_preset": "\u8fbe\u59ae\u5a05"},
            {"bot_character_preset"},
        )

    def test_unknown_preset_rejected(self) -> None:
        plugin = self._plugin()
        with self.assertRaises(self.main.WebUiActionError) as ctx:
            plugin._validate_web_ui_character_binding(
                {"bot_character_preset": "\u4e0d\u5b58\u5728"},
                {"bot_character_preset"},
            )
        # 报错必须列出可用项，便于改错
        self.assertIn("\u8fbe\u59ae\u5a05", str(ctx.exception))

    def test_non_contract_preset_rejected(self) -> None:
        plugin = self._plugin()
        with self.assertRaises(self.main.WebUiActionError):
            plugin._validate_web_ui_character_binding(
                {"bot_character_preset": "\u88f8\u89d2\u8272"},
                {"bot_character_preset"},
            )

    def test_invalid_scope_value_rejected(self) -> None:
        plugin = self._plugin()
        with self.assertRaises(self.main.WebUiActionError):
            plugin._validate_web_ui_character_binding(
                {"bot_character_preset_scopes": {"Bot": "\u4e0d\u5b58\u5728"}},
                {"bot_character_preset_scopes"},
            )

    def test_untouched_binding_not_validated(self) -> None:
        """未提交绑定时不得因历史值报错。"""
        plugin = self._plugin()
        plugin._validate_web_ui_character_binding(
            {"bot_character_preset": "\u4e0d\u5b58\u5728"},
            {"comfyui_url"},
        )


if __name__ == "__main__":
    unittest.main()
