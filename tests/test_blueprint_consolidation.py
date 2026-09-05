"""Blueprint consolidation (G1-G10) focused tests.

Kept in one file so the G-series acceptance cases are easy to review.  Service
unit tests live in their dedicated files; this file adds the main-module
integration cases that require AstrBot stubs.
"""

from __future__ import annotations

import importlib
import tempfile
import types
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs, make_gate_payload


def _install_stubs() -> None:
    install_astrbot_stubs()


class BlueprintConsolidationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        from ..services.chat_intent_classifier import (
            INTENT_CLARIFY,
            classify_chat_intent,
        )
        from ..services.task_store import (
            ALLOWED_EVENT_CODES,
            BLUEPRINT_EVENT_CODES,
        )
        from ..services.user_picture_preferences import UserPicturePreferencesStore

        cls.INTENT_CLARIFY = INTENT_CLARIFY
        cls.classify_chat_intent = classify_chat_intent
        cls.ALLOWED_EVENT_CODES = ALLOWED_EVENT_CODES
        cls.BLUEPRINT_EVENT_CODES = BLUEPRINT_EVENT_CODES
        cls.UserPicturePreferencesStore = UserPicturePreferencesStore

    @staticmethod
    def _event(message: str):
        class Event:
            message_str = message

            def __init__(self) -> None:
                self.extras: dict[str, object] = {}

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        return Event()

    def _plugin_for_inject(self):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_llm_pic_trigger=True,
            director_primary=False,
            enable_session_recipe_continuity=False,
            interaction_mode="smart",
            enable_visual_task_intent=True,
            chat_roleplay_draw_prompt="",
        )
        plugin._access_error = lambda *_args, **_kwargs: None
        plugin._internal_llm_events = set()
        plugin._chat_draw_terminal_states = {}
        plugin._director = None
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: True
        )
        return plugin

    async def test_g1_gate_runs_once_and_stores_extra(self) -> None:
        plugin = self._plugin_for_inject()
        plugin.settings.intent_router_gate_mode = "on"
        event = self._event("画一张达妮娅")
        req = types.SimpleNamespace()

        await plugin.intent_router_gate(event, req)
        await plugin.intent_router_gate(event, req)

        self.assertTrue(event.extras[self.main._INTENT_ROUTER_GATE_DONE_KEY])
        self.assertEqual(
            event.extras[self.main._INTENT_ROUTER_GATE_EXTRA_KEY]["once"],
            True,
        )

    async def test_g1_gate_is_noop_when_off(self) -> None:
        plugin = self._plugin_for_inject()
        plugin.settings.intent_router_gate_mode = "off"
        event = self._event("画一张达妮娅")

        await plugin.intent_router_gate(event, types.SimpleNamespace())

        self.assertNotIn(self.main._INTENT_ROUTER_GATE_DONE_KEY, event.extras)

    async def test_g4_draw_intent_disables_streaming(self) -> None:
        plugin = self._plugin_for_inject()
        event = self._event("角色预设，达妮娅在厨房做饭的样子")
        event.set_extra(
            self.main._INTENT_ROUTER_GATE_EXTRA_KEY,
            make_gate_payload(
                self.main,
                self.main.DRAW_NOW,
                "角色预设，达妮娅在厨房做饭的样子",
            ),
        )
        request = types.SimpleNamespace(system_prompt="base", func_tool=None)

        await plugin.inject_auto_draw_prompt(event, request)

        self.assertIs(event.extras["enable_streaming"], False)

    async def test_g7_no_recipe_continuation_clarifies(self) -> None:
        decision = self.__class__.classify_chat_intent(
            "现在发给我",
            has_recipe=False,
        )
        self.assertEqual(decision.intent, self.INTENT_CLARIFY)

    def test_g6_event_codes_are_present(self) -> None:
        expected = {
            "intent_router_gate_start",
            "intent_router_gate_result",
            "visual_task_intent_promoted",
            "user_picture_preference_saved",
            "scene_extracted",
            "roleplay_text_blocked",
            "draw_terminal_forced",
            "director_instruction_generated",
        }
        self.assertTrue(expected.issubset(self.BLUEPRINT_EVENT_CODES))
        self.assertTrue(expected.issubset(self.ALLOWED_EVENT_CODES))

    def test_g3_main_wiring_saves_and_uses_preference(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin._user_picture_preferences = self.UserPicturePreferencesStore(
                Path(temp_dir) / "user_picture_preferences_v1.json"
            )

            class Event:
                @staticmethod
                def get_sender_id():
                    return "user-9"

            record = plugin._save_user_picture_preference(
                Event(),
                {"preset": "风格001"},
            )
            self.assertIsNotNone(record)
            self.assertEqual(
                plugin._user_picture_preference(Event())["preset"],
                "风格001",
            )

    async def test_g7_roleplay_text_blocked_fails_closed(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_llm_pic_trigger=True,
            director_primary=False,
        )
        plugin._director = None
        plugin._drawing_orchestrator = self.main.DrawingOrchestrator()
        plugin._chat_draw_terminal_states = {}
        plugin._clear_lora_operation_snapshot = lambda _event: None

        event = self._event("普通聊天")
        event.extras[self.main._CHAT_DRAW_TERMINAL_EXTRA_KEY] = {
            "blocked": True,
            "blocked_message": "❌ 绘图请求已停止且不会提交 ComfyUI",
            "intent": True,
            "called": False,
        }
        run_context = types.SimpleNamespace(
            messages=[{"role": "assistant", "content": "原本角色台词"}]
        )
        response = types.SimpleNamespace(
            completion_text="原本角色台词",
            reasoning_content="hidden",
            reasoning_signature="signature",
        )

        await plugin.enforce_chat_draw_terminal(event, run_context, response)

        self.assertNotIn("<pic", response.completion_text)
        self.assertIn("ComfyUI", response.completion_text)
        self.assertIn("不会提交", run_context.messages[-1]["content"])

    def test_g9_intent_judge_off_backend_is_accepted_by_settings(self) -> None:
        from ..models import PluginSettings

        settings = PluginSettings.from_mapping({"intent_judge_backend": "off"})
        self.assertEqual(settings.intent_judge_backend, "off")


if __name__ == "__main__":
    unittest.main()
