"""构建 3.1.440：绘图流程的"卫生"修复回归。

1. 绘图链中间工具轮次不再逐轮投递正文（AstrBot respond 阶段对空链直接跳过）；
   非绘图会话（intent=False）必须保持原样放行，否则会静音正常聊天。
2. 家族映射（legacy 名 → 专属变体名）后必须去重，否则同一 LoRA 被写两次、权重叠加。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs
from ..models import LoraSelection
from ..services.lora_family_adapter import adapt_lora_selections_for_target


class IntermediateDrawTextSuppressionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, *, trace, suppress=False):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = SimpleNamespace(suppress_intermediate_draw_text=suppress)
        plugin._director = SimpleNamespace()
        plugin._natural_draw_enabled = lambda: True
        plugin._chat_draw_terminal_guard_enabled = lambda: True
        plugin._chat_draw_terminal_trace = lambda event: trace
        plugin._set_chat_draw_terminal_trace = lambda event, value: None
        return plugin

    def _event(self, chain):
        result = SimpleNamespace(chain=list(chain))
        return SimpleNamespace(get_result=lambda: result), result

    def test_suppress_drops_plain_keeps_other_components(self) -> None:
        from .. import main as main_module

        Comp = main_module.Comp
        result = SimpleNamespace(
            chain=[Comp.Plain("一"), Comp.Image(), Comp.Plain("二")]
        )
        self.main.ComfyAnimaPlugin._suppress_intermediate_draw_text(result)
        self.assertEqual(len(result.chain), 1)
        self.assertNotIsInstance(result.chain[0], Comp.Plain)

    async def test_draw_intent_suppresses_intermediate_text_when_enabled(self) -> None:
        from .. import main as main_module

        Comp = main_module.Comp
        plugin = self._plugin(trace={"intent": True}, suppress=True)
        event, result = self._event([Comp.Plain("这就给你看～")])
        await plugin._render_llm_picture_tags_impl(event)
        self.assertEqual(result.chain, [])

    async def test_draw_intent_keeps_text_by_default(self) -> None:
        """默认关闭：保持既有设计约定——中间轮台词照常放行。"""
        from .. import main as main_module

        Comp = main_module.Comp
        plugin = self._plugin(trace={"intent": True}, suppress=False)
        event, result = self._event([Comp.Plain("行，马上穿给你看。")])
        await plugin._render_llm_picture_tags_impl(event)
        self.assertEqual(result.chain[0].text, "行，马上穿给你看。")

    async def test_non_draw_intent_keeps_text(self) -> None:
        """非绘图会话（intent=False）即使开关开启也不得被静音。"""
        from .. import main as main_module

        Comp = main_module.Comp
        plugin = self._plugin(trace={"intent": False}, suppress=True)
        event, result = self._event([Comp.Plain("普通聊天回复")])
        await plugin._render_llm_picture_tags_impl(event)
        texts = [
            str(component.text)
            for component in result.chain
            if isinstance(component, Comp.Plain)
        ]
        self.assertEqual(texts, ["普通聊天回复"])


class FamilyAdapterDedupTests(unittest.TestCase):
    def _record(self, *, companion="29B/anima-000040_29b"):
        return SimpleNamespace(
            name="anima-000040",
            character_name="",
            native_in_families=(),
            compatible_model_families=(),
            compatibility_mode="unknown",
            companion_variant=companion,
        )

    def test_variant_mapping_dedupes_collision(self) -> None:
        """legacy 名被提升后与栈内已有变体名撞名 → 只保留一条。"""
        selections = (
            LoraSelection(name="anima-000040", strength=0.9),
            LoraSelection(name="29B/anima-000040_29b", strength=0.9),
        )
        adapted, _bypassed, logs = adapt_lora_selections_for_target(
            selections,
            "anima_29b_40l",
            {"anima-000040": self._record()},
        )
        self.assertEqual(len(adapted), 1)
        self.assertEqual(adapted[0].name.casefold(), "29b/anima-000040_29b")
        self.assertTrue(any("切换为专属变体" in line for line in logs))

    def test_no_collision_preserves_variant_mapping(self) -> None:
        adapted, _bypassed, _logs = adapt_lora_selections_for_target(
            (LoraSelection(name="anima-000040", strength=0.8),),
            "anima_29b_40l",
            {"anima-000040": self._record()},
        )
        self.assertEqual(len(adapted), 1)
        self.assertEqual(adapted[0].name.casefold(), "29b/anima-000040_29b")

    def test_distinct_loras_are_preserved(self) -> None:
        selections = (
            LoraSelection(name="a", strength=0.5),
            LoraSelection(name="b", strength=0.6),
        )
        adapted, _bypassed, _logs = adapt_lora_selections_for_target(
            selections,
            "anima_legacy_28l",
            {},
        )
        self.assertEqual([s.name for s in adapted], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
