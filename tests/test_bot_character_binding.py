"""BOT 绑定角色预设组合（构建 3.1.439）回归测试。

覆盖：
1. 绑定角色预设经 ``_resolve_job_presets`` 进入预设栈（无显式预设时补位）；
2. 显式风格 + 绑定角色 = 双组合叠加；
3. 显式已含角色预设时不重复注入；
4. 适用性闸门：显式点名其它角色 / 换角任务 → 绑定让位；
5. 非法绑定（非角色类 / 无契约）→ 拒绝套用；
6. 作用域覆盖优先于全局默认；
7. 配置字段经 from_mapping 正确装载。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs
from ..services.lora_presets import (
    PRESET_CATEGORY_ARTIST_STYLE,
    PRESET_CATEGORY_CHARACTER,
    LoraPresetRegistry,
)

ANCHOR = "denia_(wuthering_waves)"
BINDING_NAME = "\u8fbe\u59ae\u5a05"          # 达妮娅
STYLE_NAME = "\u98ce\u683c001"               # 风格001

CHARACTER_PRESET = {
    "__template_key": "character_combo",
    "name": BINDING_NAME,
    "loras": ["29B/anima-000040_29b=0.9"],
    "aliases": ["denia"],
    "character_canonical": "denia",
    "identity_anchor": ANCHOR,
    "required_trigger_terms": [ANCHOR],
    "positive_tags": ["Quick Use"],
    "enabled": True,
}

STYLE_PRESET = {
    "__template_key": "artist_style_combo",
    "name": STYLE_NAME,
    "loras": ["style_lora=0.6"],
    "enabled": True,
}

# 非契约角色预设：有角色类但没有身份锚点/触发词 → 不得作绑定源
BARE_CHARACTER_PRESET = {
    "__template_key": "character_combo",
    "name": "裸角色",
    "loras": ["bare=0.5"],
    "enabled": True,
}


class _Event:
    def __init__(self, *, umo="Bot:FriendMessage:719397082", session="752633354",
                 sender="719397082", self_id="2131906245"):
        self.unified_msg_origin = umo
        self._session = session
        self._sender = sender
        self._self_id = self_id

    def get_session_id(self):
        return self._session

    def get_sender_id(self):
        return self._sender

    def get_self_id(self):
        return self._self_id


class BotCharacterBindingTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, *, enabled=True, global_preset=BINDING_NAME, scopes=None,
                extra_presets=()):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = SimpleNamespace(
            enable_bot_character_binding=enabled,
            bot_character_preset=global_preset,
            bot_character_preset_scopes=dict(scopes or {}),
            model_family="anima_legacy_28l",
            default_style_preset="",
            max_preset_loras=8,
        )
        plugin._lora_presets = LoraPresetRegistry(
            [CHARACTER_PRESET, STYLE_PRESET, BARE_CHARACTER_PRESET, *extra_presets],
            max_loras=8,
        )
        plugin._semantic_index = None
        return plugin

    # ---- 解析层 -------------------------------------------------------

    async def test_disabled_switch_returns_empty(self) -> None:
        plugin = self._plugin(enabled=False)
        self.assertEqual(plugin._bound_character_preset_name(_Event()), "")

    async def test_valid_binding_resolves(self) -> None:
        plugin = self._plugin()
        self.assertEqual(
            plugin._bound_character_preset_name(_Event()), BINDING_NAME
        )

    async def test_scope_override_beats_global(self) -> None:
        plugin = self._plugin(
            global_preset="",
            scopes={"Bot:FriendMessage:719397082": BINDING_NAME},
        )
        event = _Event(umo="Bot:FriendMessage:719397082")
        self.assertEqual(plugin._bound_character_preset_name(event), BINDING_NAME)
        # 未命中的作用域 → 回落到全局（此处为空）
        self.assertEqual(
            plugin._bound_character_preset_name(_Event(umo="Bot:GroupMessage:1")),
            "",
        )

    async def test_explicit_other_character_wins(self) -> None:
        plugin = self._plugin()
        options = SimpleNamespace(prompt="\u89d2\u8272\u662f\u521d\u97f3", 
                                  llm_character_user_request="")
        self.assertEqual(
            plugin._bound_character_preset_name(_Event(), options), ""
        )

    async def test_character_swap_task_wins(self) -> None:
        plugin = self._plugin()
        options = SimpleNamespace(
            prompt="keep scene",
            llm_character_user_request="",
            character_swap_target_lora="other_character",
        )
        self.assertEqual(
            plugin._bound_character_preset_name(_Event(), options), ""
        )

    async def test_bare_character_preset_rejected(self) -> None:
        plugin = self._plugin(global_preset="\u88f8\u89d2\u8272")
        self.assertEqual(plugin._bound_character_preset_name(_Event()), "")

    async def test_unknown_preset_rejected(self) -> None:
        plugin = self._plugin(global_preset="\u4e0d\u5b58\u5728\u7684\u9884\u8bbe")
        self.assertEqual(plugin._bound_character_preset_name(_Event()), "")

    # ---- 应用层 -------------------------------------------------------

    def test_bound_preset_fills_when_nothing_explicit(self) -> None:
        plugin = self._plugin()
        presets, replace = plugin._resolve_job_presets(
            "", (), bound_character=BINDING_NAME
        )
        names = {preset.name for preset in presets}
        self.assertIn(BINDING_NAME, names)
        self.assertIsInstance(replace, bool)

    def test_bound_preset_stacks_with_explicit_style(self) -> None:
        """显式风格 + 绑定角色 = 双组合叠加。"""
        plugin = self._plugin()
        presets, _ = plugin._resolve_job_presets(
            STYLE_NAME, (), bound_character=BINDING_NAME
        )
        names = [preset.name for preset in presets]
        self.assertIn(STYLE_NAME, names)
        self.assertIn(BINDING_NAME, names)
        categories = {preset.category for preset in presets}
        self.assertIn(PRESET_CATEGORY_ARTIST_STYLE, categories)
        self.assertIn(PRESET_CATEGORY_CHARACTER, categories)

    def test_explicit_character_not_duplicated(self) -> None:
        plugin = self._plugin()
        presets, _ = plugin._resolve_job_presets(
            BINDING_NAME, (), bound_character=BINDING_NAME
        )
        names = [preset.name for preset in presets]
        self.assertEqual(names.count(BINDING_NAME), 1)

    def test_no_binding_keeps_legacy_behaviour(self) -> None:
        """bound_character 为空时行为与基线一致（回归保护）。"""
        plugin = self._plugin()
        presets, replace = plugin._resolve_job_presets("", ())
        self.assertEqual(presets, ())
        self.assertFalse(replace)

    # ---- 配置装载 -----------------------------------------------------

    def test_settings_from_mapping_loads_binding(self) -> None:
        settings = self.main.PluginSettings.from_mapping(
            {
                "enable_bot_character_binding": True,
                "bot_character_preset": BINDING_NAME,
                "bot_character_preset_scopes": {"Bot": BINDING_NAME, "": "x"},
            }
        )
        self.assertTrue(settings.enable_bot_character_binding)
        self.assertEqual(settings.bot_character_preset, BINDING_NAME)
        # 空键被清洗
        self.assertEqual(settings.bot_character_preset_scopes, {"Bot": BINDING_NAME})

    def test_settings_default_binding_disabled(self) -> None:
        settings = self.main.PluginSettings.from_mapping({})
        self.assertFalse(settings.enable_bot_character_binding)
        self.assertEqual(settings.bot_character_preset, "")
        self.assertEqual(settings.bot_character_preset_scopes, {})


if __name__ == "__main__":
    unittest.main()
