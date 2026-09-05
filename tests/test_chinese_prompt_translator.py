"""Chinese prompt translator service and direct-draw integration tests."""

import importlib
import unittest
from types import SimpleNamespace

from ..services.chinese_prompt_translator import ChinesePromptTranslator
from ._stubs import install_astrbot_stubs


class ChinesePromptTranslatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a1_dictionary_translation(self) -> None:
        translator = ChinesePromptTranslator()
        result = await translator.translate("穿JK制服和黑丝")
        self.assertEqual(result.source, "a1")
        self.assertIn("wearing school uniform, pleated skirt and black pantyhose", result.translated)
        self.assertNotIn("JK制服", result.translated)

    async def test_a1_partial_translation_keeps_unknown_chinese(self) -> None:
        translator = ChinesePromptTranslator()
        result = await translator.translate("达妮娅自拍")
        self.assertEqual(result.source, "a1")
        self.assertIn("达妮娅", result.translated)
        self.assertIn("selfie", result.translated)
        self.assertIn("looking at viewer", result.translated)
        self.assertTrue(any("partial" in item for item in result.trace))

    async def test_a2_embed_rerank_selects_best_tag(self) -> None:
        vectors = {
            "黑丝": [1.0, 0.0, 0.0],
            "black pantyhose": [1.0, 0.0, 0.0],
            "maid outfit": [0.0, 1.0, 0.0],
            "school uniform": [0.0, 0.0, 1.0],
        }

        def embed_fn(texts):
            return [vectors[text] for text in texts]

        def rerank_fn(_query, docs):
            return [0.9 if doc == "black pantyhose" else 0.2 for doc in docs]

        translator = ChinesePromptTranslator(
            tag_library=("black pantyhose", "maid outfit", "school uniform"),
            embed_fn=embed_fn,
            rerank_fn=rerank_fn,
            a2_margin_threshold=0.1,
        )
        result = await translator.translate("黑丝")
        self.assertEqual(result.source, "a2")
        self.assertEqual(result.translated, "black pantyhose")
        self.assertGreaterEqual(result.confidence, 0.9)

    async def test_a2_margin_below_threshold_falls_through(self) -> None:
        vectors = {
            "神秘服装": [1.0, 0.0],
            "mysterious outfit": [0.9, 0.1],
            "dark outfit": [0.85, 0.15],
        }

        def embed_fn(texts):
            return [vectors[text] for text in texts]

        def rerank_fn(_query, _docs):
            return [0.6, 0.55]

        translator = ChinesePromptTranslator(
            tag_library=("mysterious outfit", "dark outfit"),
            embed_fn=embed_fn,
            rerank_fn=rerank_fn,
            a2_margin_threshold=0.1,
        )
        result = await translator.translate("神秘服装")
        self.assertEqual(result.source, "none")
        self.assertEqual(result.translated, "神秘服装")
        self.assertTrue(any("below threshold" in item for item in result.trace))

    async def test_b_llm_fallback(self) -> None:
        async def llm_fn(prompt, system_prompt, temperature):
            self.assertEqual(prompt, "神秘氛围")
            self.assertIn("English", system_prompt)
            self.assertIsInstance(temperature, float)
            return "mysterious atmosphere"

        translator = ChinesePromptTranslator(llm_fn=llm_fn)
        result = await translator.translate("神秘氛围")
        self.assertEqual(result.source, "b")
        self.assertEqual(result.translated, "mysterious atmosphere")
        self.assertTrue(any(item.startswith("b:") for item in result.trace))

    async def test_none_fallback_returns_original(self) -> None:
        translator = ChinesePromptTranslator()
        result = await translator.translate("神秘氛围")
        self.assertEqual(result.source, "none")
        self.assertEqual(result.translated, "神秘氛围")
        self.assertEqual(result.confidence, 0.0)


class DirectDrawChineseTranslationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_direct_draw_replaces_chinese_fragment_and_keeps_subject(self) -> None:
        class FakePlugin:
            settings = SimpleNamespace(enable_chinese_prompt_translation=True)
            _lora_presets = SimpleNamespace(list_presets=lambda: ())
            _director = None

            def _requested_subject_hint(self, prompt: str) -> str:
                return "达妮娅" if "达妮娅" in prompt else ""

            def _build_chinese_translator(self, event):
                return ChinesePromptTranslator()

        plugin = FakePlugin()
        plugin._chinese_translation_exclusions = (
            self.main.ComfyAnimaPlugin._chinese_translation_exclusions.__get__(
                plugin,
                self.main.ComfyAnimaPlugin,
            )
        )
        translated, results = (
            await self.main.ComfyAnimaPlugin._translate_direct_draw_chinese(
                plugin,
                object(),
                "角色是达妮娅，穿JK制服和黑丝",
            )
        )
        self.assertIn("达妮娅", translated)
        self.assertIn("角色是", translated)
        self.assertNotIn("JK制服", translated)
        self.assertIn("school uniform, pleated skirt", translated)
        self.assertIn("black pantyhose", translated)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "a1")

    async def test_direct_draw_replaces_selfie_without_losing_character(self) -> None:
        class FakePlugin:
            settings = SimpleNamespace(enable_chinese_prompt_translation=True)
            _lora_presets = SimpleNamespace(list_presets=lambda: ())
            _director = None

            def _requested_subject_hint(self, prompt: str) -> str:
                return "达妮娅" if "达妮娅" in prompt else ""

            def _build_chinese_translator(self, event):
                return ChinesePromptTranslator()

        plugin = FakePlugin()
        plugin._chinese_translation_exclusions = (
            self.main.ComfyAnimaPlugin._chinese_translation_exclusions.__get__(
                plugin,
                self.main.ComfyAnimaPlugin,
            )
        )
        translated, results = (
            await self.main.ComfyAnimaPlugin._translate_direct_draw_chinese(
                plugin,
                object(),
                "风格HH1 达妮娅自拍",
            )
        )
        self.assertIn("达妮娅", translated)
        self.assertIn("selfie", translated)
        self.assertIn("looking at viewer", translated)
        self.assertNotIn("自拍", translated)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "a1")


if __name__ == "__main__":
    unittest.main()
