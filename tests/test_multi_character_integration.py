"""Main-plugin integration tests for MultiCharacterJudge-driven natural draw."""

import importlib
import types
import unittest

from ..services.lora_presets import (
    LoraPreset,
    PRESET_CATEGORY_CHARACTER,
)
from ._stubs import install_astrbot_stubs


class _StubEvent:
    def __init__(self, message_str: str) -> None:
        self.message_str = message_str
        self.replies: list[str] = []

    def plain_result(self, text: str) -> str:
        self.replies.append(text)
        return text


async def _collect(handler):
    return [reply async for reply in handler]


class MultiCharacterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _preset(name, anchor):
        return LoraPreset(
            name=name,
            category=PRESET_CATEGORY_CHARACTER,
            selections=(),
            identity_anchor=anchor,
            required_trigger_terms=(anchor,),
            contract_enabled=True,
        )

    def _plugin(self, presets):
        registry = types.SimpleNamespace(
            list_presets=lambda category: tuple(presets)
            if category == PRESET_CATEGORY_CHARACTER
            else ()
        )
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_presets = registry
        plugin._subject_character_preset = self.main.ComfyAnimaPlugin._subject_character_preset.__get__(
            plugin,
            self.main.ComfyAnimaPlugin,
        )
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        plugin._initialization_error = ""
        plugin._extract_resolution_request = lambda message: (512, 512)
        plugin._access_error = lambda *args, **kwargs: None
        plugin._schedule_cleanup = lambda paths: None
        plugin._make_image_result = lambda *args, **kwargs: "image-result"
        return plugin

    def test_detects_two_character_names_in_message_order(self) -> None:
        plugin = self._plugin(
            [
                self._preset("达妮娅", "denia_(wuthering_waves)"),
                self._preset("调月莉音", "tsukiyo_(blue_archive)"),
            ]
        )
        self.assertEqual(
            plugin._detect_multi_character_names("达妮娅 cos 调月莉音 画出来"),
            ("达妮娅", "调月莉音"),
        )

    def test_visual_intent_phrase_is_not_split_as_second_character(self) -> None:
        plugin = self._plugin([self._preset("娅娅", "denia_(wuthering_waves)")])
        names = plugin._detect_multi_character_names("想看JK娅娅（画出来）")
        self.assertEqual(len(names), 1)
        self.assertIn("娅娅", names)

    async def test_cosplay_submits_only_anchor_preset_and_cosplay_tag(self) -> None:
        anchor = self._preset("达妮娅", "denia_(wuthering_waves)")
        target = self._preset("调月莉音", "tsukiyo_(blue_archive)")
        plugin = self._plugin([anchor, target])
        captured = {}

        async def run_job(event, options):
            captured["options"] = options
            return ["path.png"], 1, options.prompt, "", "base"

        plugin._run_job = run_job
        replies = await _collect(
            plugin._handle_multi_character_draw(
                _StubEvent("达妮娅 cos 调月莉音 画出来"),
                "达妮娅 cos 调月莉音 画出来",
                ("达妮娅", "调月莉音"),
            )
        )
        self.assertEqual(replies[-1], "image-result")
        self.assertEqual(captured["options"].lora_preset, "达妮娅")
        self.assertIn("tsukiyo_(blue_archive)_(cosplay)", captured["options"].prompt)
        self.assertNotIn("tsukiyo_(blue_archive), ", captured["options"].prompt)

    async def test_dual_submits_both_presets_and_both_identity_terms(self) -> None:
        first = self._preset("达妮娅", "denia_(wuthering_waves)")
        second = self._preset("调月莉音", "tsukiyo_(blue_archive)")
        plugin = self._plugin([first, second])
        captured = {}

        async def run_job(event, options):
            captured["options"] = options
            return ["path.png"], 2, options.prompt, "", "base"

        plugin._run_job = run_job
        replies = await _collect(
            plugin._handle_multi_character_draw(
                _StubEvent("达妮娅和调月莉音同框 画出来"),
                "达妮娅和调月莉音同框 画出来",
                ("达妮娅", "调月莉音"),
            )
        )
        self.assertEqual(replies[-1], "image-result")
        self.assertEqual(
            captured["options"].lora_preset,
            "达妮娅,调月莉音",
        )
        self.assertIn("denia_(wuthering_waves)", captured["options"].prompt)
        self.assertIn("tsukiyo_(blue_archive)", captured["options"].prompt)

    async def test_clarify_sends_question_and_does_not_submit(self) -> None:
        plugin = self._plugin(
            [
                self._preset("达妮娅", "denia_(wuthering_waves)"),
                self._preset("调月莉音", "tsukiyo_(blue_archive)"),
            ]
        )
        plugin._run_job = lambda *args, **kwargs: self.fail("must not submit")
        event = _StubEvent("达妮娅和调月莉音")
        replies = await _collect(
            plugin._handle_multi_character_draw(
                event,
                "达妮娅和调月莉音",
                ("达妮娅", "调月莉音"),
            )
        )
        self.assertEqual(len(replies), 1)
        self.assertIn("同框", replies[0])


if __name__ == "__main__":
    unittest.main()
