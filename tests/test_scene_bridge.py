"""Scene Bridge tests: visual intent gate, thresholds, JSON parsing."""

import importlib
from pathlib import Path
import types
import unittest

from ..services.scene_bridge import (
    SceneBridge,
    SceneBridgeResult,
    SceneFacts,
    has_visual_intent,
    scene_context_from_event,
)
from ._stubs import (
    Plain as _Plain,
    install_astrbot_stubs,
    make_gate_payload,
)


def _scene_json(confidence, location="bedroom"):
    return (
        '{"location":"'
        + location
        + '","action":"lying on bed","clothing":"pajamas",'
        + '"pose":"side lying","emotion":"sleepy","confidence":'
        + str(confidence)
        + "}"
    )


class VisualIntentTests(unittest.TestCase):
    def test_plain_question_has_no_visual_intent(self) -> None:
        self.assertFalse(has_visual_intent("你在干嘛"))

    def test_want_to_see_has_visual_intent(self) -> None:
        self.assertTrue(has_visual_intent("我想看你在干嘛"))
        self.assertTrue(has_visual_intent("你在干嘛呢让我看看"))


class SceneContextFromEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_available_context_and_traces_sources(self) -> None:
        async def get_memories():
            return [{"content": "她喜欢海边"}, "上次在厨房"]

        event = types.SimpleNamespace(
            get_recent_messages=lambda: ["你好", "达妮娅在卧室"],
            persona_name="达妮娅",
            get_memories=get_memories,
        )
        context = await scene_context_from_event(
            event,
            recent_limit=8,
            memory_limit=5,
        )
        self.assertEqual(context["recent_messages"], ("你好", "达妮娅在卧室"))
        self.assertEqual(context["persona_name"], "达妮娅")
        self.assertEqual(context["memories"], ("她喜欢海边", "上次在厨房"))
        self.assertEqual(context["sources"]["recent_messages"], "get_recent_messages")
        self.assertEqual(context["sources"]["persona_name"], "event.persona_name")
        self.assertEqual(context["sources"]["memories"], "get_memories")

    async def test_falls_back_gracefully_when_apis_are_missing(self) -> None:
        context = await scene_context_from_event(types.SimpleNamespace())
        self.assertEqual(context["recent_messages"], ())
        self.assertEqual(context["persona_name"], "")
        self.assertEqual(context["memories"], ())
        self.assertEqual(
            context["sources"],
            {
                "recent_messages": "fallback_empty",
                "persona_name": "fallback_empty",
                "memories": "fallback_empty",
            },
        )

    async def test_broken_api_falls_back_without_raising(self) -> None:
        def broken():
            raise RuntimeError("api unavailable")

        event = types.SimpleNamespace(get_recent_messages=broken)
        context = await scene_context_from_event(event)
        self.assertEqual(context["recent_messages"], ())
        self.assertEqual(context["sources"]["recent_messages"], "fallback_empty")


class SceneBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def _bridge(self, raw, filter_fn=None):
        async def llm(prompt, system, temperature):
            return raw

        return SceneBridge(llm, filter_fn=filter_fn)

    async def test_plain_question_skips_without_calling_llm(self) -> None:
        calls = []

        async def llm(prompt, system, temperature):
            calls.append(prompt)
            return "{}"

        bridge = SceneBridge(llm)
        result = await bridge.decide("你在干嘛", "我在床上")
        self.assertEqual(result.action, "skip")
        self.assertEqual(calls, [])

    async def test_confident_scene_draws(self) -> None:
        bridge = await self._bridge(_scene_json(0.9))
        result = await bridge.decide(
            "我想看你在干嘛",
            "我刚躺下",
            recent_messages=("我洗完澡了", "现在躺着"),
        )
        self.assertEqual(result.action, "draw")
        self.assertEqual(result.scene.location, "bedroom")

    async def test_medium_confidence_asks(self) -> None:
        bridge = await self._bridge(_scene_json(0.5))
        result = await bridge.decide("我想看你在干嘛", "我在床上")
        self.assertEqual(result.action, "ask")

    async def test_low_confidence_skips(self) -> None:
        bridge = await self._bridge(_scene_json(0.2, location="unknown"))
        result = await bridge.decide("我想看你在干嘛", "不知道")
        self.assertEqual(result.action, "skip")

    async def test_invalid_json_asks(self) -> None:
        bridge = await self._bridge("not json")
        result = await bridge.decide("我想看你在干嘛", "我在床上")
        self.assertEqual(result.action, "ask")
        self.assertIn("invalid_scene_json", result.reason)

    async def test_filter_fn_selects_context(self) -> None:
        async def filter_fn(query, messages):
            return (len(messages) - 1,)

        bridge = await self._bridge(_scene_json(0.9), filter_fn)
        result = await bridge.decide(
            "我想看你在干嘛",
            "床上",
            recent_messages=("旧消息", "刚洗完澡躺沙发"),
        )
        self.assertEqual(result.action, "draw")
        self.assertEqual(result.trace["context_messages"], 1)


class SceneBridgeMainIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, bridge_result):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_scene_extraction=True,
            scene_context_window=8,
            scene_extraction_max_memories=5,
            show_chat_generation_details=False,
        )
        plugin._director = object()
        plugin._get_drawing_orchestrator = lambda: types.SimpleNamespace(
            legacy_submission_allowed=lambda event: True
        )

        async def decide(*args, **kwargs):
            return bridge_result

        plugin._build_scene_bridge = lambda event: types.SimpleNamespace(
            decide=decide
        )
        plugin._subject_character_preset = lambda subject: None
        plugin._requested_subject_hint = lambda message: ""
        plugin._extract_resolution_request = lambda message: (512, 512)
        plugin._access_error = lambda *args, **kwargs: None
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        plugin._schedule_cleanup = lambda paths: None
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: True
        )

        async def run_job(event, options):
            self.assertEqual(options.prompt, "bedroom, lying on bed")
            self.assertEqual(options.lora_preset, "")
            self.assertEqual(options.llm_prompt_source, "scene_bridge")
            return [Path("generated.png")], 123, options.prompt, "", "base"

        plugin._run_job = run_job
        return plugin

    @staticmethod
    def _event(message):
        draw_now = SceneBridgeMainIntegrationTests.main.DRAW_NOW

        class Event:
            message_str = message

            def __init__(self):
                self._extras = {
                    "astrbot_plugin_comfy_anima:intent_router_gate_result": make_gate_payload(
                        SceneBridgeMainIntegrationTests.main,
                        draw_now,
                        message,
                    )
                }

            def get_extra(self, key, default=None):
                return self._extras.get(key, default)

            def set_extra(self, key, value):
                self._extras[key] = value

        return Event()

    async def test_draw_action_submits_generation_and_appends_image(self) -> None:
        scene = SceneFacts(location="bedroom", action="lying on bed")
        plugin = self._plugin(
            SceneBridgeResult(action="draw", scene=scene, reason="confident_scene")
        )
        result = types.SimpleNamespace(chain=[_Plain("我刚躺下")])
        event = self._event("我想看你在干嘛")
        handled = await plugin._try_scene_bridge_draw(event, result, "我刚躺下")
        self.assertTrue(handled)
        self.assertIn(("image", "generated.png"), result.chain)

    async def test_ask_action_appends_one_clarify_and_returns(self) -> None:
        plugin = self._plugin(
            SceneBridgeResult(action="ask", scene=None, reason="scene_needs_confirmation")
        )
        result = types.SimpleNamespace(chain=[_Plain("我在床上")])
        event = self._event("我想看你在干嘛")
        handled = await plugin._try_scene_bridge_draw(event, result, "我在床上")
        self.assertTrue(handled)
        self.assertTrue(
            any(
                isinstance(component, _Plain)
                and "场景还不够明确" in component.text
                for component in result.chain
            )
        )

    async def test_skip_action_does_nothing(self) -> None:
        plugin = self._plugin(
            SceneBridgeResult(action="skip", scene=None, reason="scene_too_weak")
        )
        result = types.SimpleNamespace(chain=[_Plain("不知道")])
        event = types.SimpleNamespace(message_str="我想看你在干嘛")
        handled = await plugin._try_scene_bridge_draw(event, result, "不知道")
        self.assertFalse(handled)
        self.assertEqual(len(result.chain), 1)


if __name__ == "__main__":
    unittest.main()
