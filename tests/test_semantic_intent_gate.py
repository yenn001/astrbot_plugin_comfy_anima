"""End-to-end semantic IntentJudge gate tests for Sol evidence.

Q10: ordinary chat must be no_draw.
Q11: visual-intent message must pass the gate and pre-create a draw bundle.
Q15: single-character draw phrase must not be treated as multi-character.
SceneBridge: must not run without a draw_now gate result.
"""

import importlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ._stubs import install_astrbot_stubs, make_gate_payload


class _Event:
    def __init__(self, message):
        self.message_str = message
        self._extras = {}

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value


def _fake_judge(decision):
    class Judge:
        async def judge(self, message, bot_reply, context=""):
            return types.SimpleNamespace(
                decision=decision,
                confidence=0.9,
                backend_used="test",
                reason="test",
                latency_ms=0.0,
                trace={},
            )

    return Judge()


class SemanticIntentGateTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _plugin(decision):
        plugin = object.__new__(SemanticIntentGateTests.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True,
            director_primary=True,
            enable_scene_extraction=True,
            intent_router_gate_mode="on",
        )
        plugin._event_has_explicit_command_route = lambda _event: False
        plugin._build_intent_judge_service = lambda: _fake_judge(decision)
        plugin._gate_decision = decision
        plugin._event_drawing_keys = lambda _event: ("key",)
        plugin._get_drawing_orchestrator = lambda: types.SimpleNamespace(
            begin_umo_drawing=lambda _key: None,
            end_umo_drawing=lambda _key: None,
            has_any_umo_drawing=lambda: False,
            legacy_submission_allowed=lambda _event: True,
        )
        plugin._ledger = SemanticsStubLedger()
        plugin._response_ledger = lambda _event: plugin._ledger
        plugin._cleanup_tasks = set()
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: True
        )
        return plugin

    async def _run(self, plugin, message):
        event = _Event(message)
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            make_gate_payload(self.main, plugin._gate_decision, message),
        )
        replies = [reply async for reply in plugin._natural_language_draw_impl(event)]
        return event, replies

    async def test_q10_ordinary_no_draw_does_not_have_bundle(self):
        plugin = self._plugin(self.main.NO_DRAW)
        event, replies = await self._run(plugin, "你在干嘛")
        self.assertEqual(replies, [])
        self.assertIsNone(plugin._ledger.envelope())

    async def test_q11_visual_intent_draw_now_precreates_bundle(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        event, replies = await self._run(plugin, "我想看你在干嘛")
        self.assertEqual(replies, [])
        envelope = plugin._ledger.envelope()
        if envelope is not None:
            self.assertIsNotNone(envelope.draw_bundle)

    async def test_q15_single_draw_phrase_not_multi_clarify(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        event, replies = await self._run(plugin, "想看JK娅娅（画出来）")
        self.assertNotIn("同框还是", " ".join(str(item) for item in replies))

    async def test_intent_router_gate_runs_real_judge_once(self):
        plugin = self._plugin(self.main.DRAW_NOW)

        class FakeLedger:
            def start(self, **kwargs):
                return "test-decision"

            def result(self, decision_id, result):
                return "test-hash"

            def verify(self, decision_id, expected):
                return True

        plugin._intent_decision_ledger = FakeLedger()
        event = _Event("我想看你在干嘛")
        await plugin.intent_router_gate(event, None)
        gate = event.get_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result"
        )
        self.assertEqual(gate["decision"], self.main.DRAW_NOW)
        self.assertEqual(gate["status"], "judged")
        self.assertEqual(gate["decision_id"], "test-decision")
        self.assertEqual(gate["result_hash"], "test-hash")
        await plugin.intent_router_gate(event, None)
        self.assertEqual(gate["once"], True)

    async def test_producer_payload_and_helper_integrate_in_order(self):
        from ..services.intent_decision_ledger import IntentDecisionLedger

        with tempfile.TemporaryDirectory() as tmp:
            plugin = self._plugin(self.main.DRAW_NOW)
            plugin._intent_decision_ledger = IntentDecisionLedger(
                Path(tmp) / "intent_judge_decisions_v1.jsonl",
                public_version=self.main.PLUGIN_VERSION,
                internal_target_version=self.main.INTERNAL_BUILD_ID,
            )
            plugin._build_intent_judge_service = lambda: _fake_judge(
                self.main.DRAW_NOW
            )
            event = _Event("我想看你在干嘛")

            async def stub_context(event, recent_limit=8, memory_limit=5):
                return {
                    "recent_messages": (),
                    "persona_name": "",
                    "memories": (),
                    "sources": ("stub",),
                }

            with mock.patch.object(
                self.main,
                "scene_context_from_event",
                new=stub_context,
            ):
                await plugin.intent_router_gate(event, None)
            payload = event.get_extra(
                "astrbot_plugin_comfy_anima:intent_router_gate_result"
            )
            self.assertEqual(payload["decision"], self.main.DRAW_NOW)
            self.assertEqual(
                plugin._event_intent_gate_result(event).get("decision"),
                self.main.DRAW_NOW,
            )
            other = _Event("在吗")
            other.set_extra(
                "astrbot_plugin_comfy_anima:intent_router_gate_result",
                payload,
            )
            self.assertEqual(plugin._event_intent_gate_result(other), {})
            tampered = dict(payload)
            tampered["internal_target_version"] = "3.1.399"
            event.set_extra(
                "astrbot_plugin_comfy_anima:intent_router_gate_result",
                tampered,
            )
            self.assertEqual(plugin._event_intent_gate_result(event), {})

    async def test_q11_scene_bridge_submits_real_run_job_with_gate(self):
        from ..services.scene_bridge import SceneBridgeResult, SceneFacts

        plugin = self._plugin(self.main.DRAW_NOW)
        plugin.settings = types.SimpleNamespace(
            scene_extraction=True,
            scene_context_window=8,
            scene_extraction_max_memories=5,
            show_chat_generation_details=False,
        )
        plugin._get_drawing_orchestrator = lambda: types.SimpleNamespace(
            legacy_submission_allowed=lambda _event: True,
        )

        class FakeBridge:
            async def decide(self, message, bot, **kwargs):
                return SceneBridgeResult(
                    action="draw",
                    scene=SceneFacts(
                        location="bedroom",
                        action="lying in bed",
                        clothing="black pantyhose",
                        confidence=0.9,
                    ),
                    reason="confident_scene",
                )

        plugin._build_scene_bridge = lambda _event: FakeBridge()
        plugin._extract_resolution_request = lambda _text: (512, 512)
        plugin._requested_subject_hint = lambda _text: ""
        plugin._subject_character_preset = lambda _subject: None
        plugin._access_error = lambda *_args, **_kwargs: None
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        captured = {}

        async def run_job(event, options):
            captured["options"] = options
            return ["/tmp/scene.png"], 42, options.prompt, "", "base"

        plugin._run_job = run_job
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            make_gate_payload(self.main, self.main.DRAW_NOW, "我想看你在干嘛"),
        )
        async def stub_context(event, recent_limit=8, memory_limit=5):
            return {
                "recent_messages": ("我刚躺下",),
                "persona_name": "达妮娅",
                "memories": (),
                "sources": ("stub",),
            }

        with mock.patch.object(
            self.main,
            "scene_context_from_event",
            new=stub_context,
        ):
            handled = await plugin._try_scene_bridge_draw(
                event,
                types.SimpleNamespace(chain=[]),
                "我刚躺下",
            )
        self.assertTrue(handled)
        self.assertEqual(captured["options"].llm_prompt_source, "scene_bridge")
        self.assertIn("bedroom", captured["options"].prompt)

    async def test_missing_ledger_fails_closed(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        plugin._intent_decision_ledger = None
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            {
                "status": "judged",
                "decision": self.main.DRAW_NOW,
                "decision_id": "test-decision",
                "result_hash": "test-hash",
            },
        )
        self.assertEqual(plugin._event_intent_gate_result(event), {})

    async def test_invalid_gate_payload_is_rejected(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            {"decision": self.main.DRAW_NOW},
        )
        self.assertEqual(plugin._event_intent_gate_result(event), {})

    async def test_forged_gate_hash_is_rejected(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: False
        )
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            {
                "status": "judged",
                "decision": self.main.DRAW_NOW,
                "decision_id": "forged",
                "result_hash": "forged",
            },
        )
        self.assertEqual(plugin._event_intent_gate_result(event), {})

    async def test_forged_gate_hash_never_reaches_run_job(self):
        from ..services.scene_bridge import SceneBridgeResult, SceneFacts

        plugin = self._plugin(self.main.DRAW_NOW)
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: False
        )
        plugin.settings = types.SimpleNamespace(
            scene_extraction=True,
            scene_context_window=8,
            scene_extraction_max_memories=5,
            show_chat_generation_details=False,
        )
        plugin._get_drawing_orchestrator = lambda: types.SimpleNamespace(
            legacy_submission_allowed=lambda _event: True,
        )

        class FakeBridge:
            async def decide(self, message, bot, **kwargs):
                return SceneBridgeResult(
                    action="draw",
                    scene=SceneFacts(location="room", confidence=0.9),
                )

        plugin._build_scene_bridge = lambda _event: FakeBridge()
        plugin._extract_resolution_request = lambda _text: (512, 512)
        plugin._requested_subject_hint = lambda _text: ""
        plugin._subject_character_preset = lambda _subject: None
        plugin._access_error = lambda *_args, **_kwargs: None
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        plugin._run_job = types.SimpleNamespace(__call__=None)
        call_count = {"n": 0}

        async def run_job(event, options):
            call_count["n"] += 1
            return ["/tmp/x.png"], 1, options.prompt, "", "base"

        plugin._run_job = run_job
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            {
                "status": "judged",
                "decision": self.main.DRAW_NOW,
                "decision_id": "forged",
                "result_hash": "forged",
            },
        )

        async def stub_context(event, recent_limit=8, memory_limit=5):
            return {
                "recent_messages": (),
                "persona_name": "",
                "memories": (),
                "sources": ("stub",),
            }

        with mock.patch.object(
            self.main,
            "scene_context_from_event",
            new=stub_context,
        ):
            handled = await plugin._try_scene_bridge_draw(
                event,
                types.SimpleNamespace(chain=[]),
                "场景",
            )
        self.assertFalse(handled)
        self.assertEqual(call_count["n"], 0)

    async def test_scene_bridge_rejects_missing_gate(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        plugin.settings = types.SimpleNamespace(
            enable_scene_extraction=True,
        )
        event = _Event("我想看你在干嘛")
        self.assertFalse(
            await plugin._try_scene_bridge_draw(event, types.SimpleNamespace(chain=[]), "场景")
        )

    async def test_scene_bridge_rejects_no_draw_gate(self):
        plugin = self._plugin(self.main.DRAW_NOW)
        plugin.settings = types.SimpleNamespace(
            enable_scene_extraction=True,
        )
        event = _Event("我想看你在干嘛")
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            {
                "status": "judged",
                "decision": self.main.NO_DRAW,
                "decision_id": "test-decision",
                "result_hash": "test-hash",
            },
        )
        self.assertFalse(
            await plugin._try_scene_bridge_draw(event, types.SimpleNamespace(chain=[]), "场景")
        )


class SemanticsStubLedger:
    def ensure_envelope(self, allocate_run_id=lambda: "run"):
        self._envelope_obj = types.SimpleNamespace(
            draw_bundle=None,
            image_bundle=None,
            store_bundle=None,
        )
        return self._envelope_obj

    def new_bundle(self, kind, bundle_run_id=None):
        self._envelope_obj.draw_bundle = types.SimpleNamespace(
            bundle_id="b", kind=kind
        )
        return self._envelope_obj.draw_bundle

    def envelope(self):
        return getattr(self, "_envelope_obj", None)


if __name__ == "__main__":
    unittest.main()
