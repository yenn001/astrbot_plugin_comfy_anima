"""Intent decision ledger and gate persistence tests (Stage 1)."""

import hashlib
import importlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ._stubs import install_astrbot_stubs


class IntentDecisionLedgerTests(unittest.TestCase):
    def test_append_start_and_result_share_decision_id(self) -> None:
        from ..services.intent_decision_ledger import IntentDecisionLedger

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent_judge_decisions_v1.jsonl"
            ledger = IntentDecisionLedger(
                path,
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            decision_id = ledger.start(
                user_message="我想看你在干嘛",
                user_id_hash="user-hash",
                context_hash="ctx-hash",
                context_source="scene_context",
            )
            result_hash = ledger.result(
                decision_id,
                types.SimpleNamespace(
                    decision="draw_now",
                    confidence=0.9,
                    backend_used="local",
                    reason="test",
                    latency_ms=1.0,
                ),
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            second = json.loads(lines[1])
            self.assertEqual(first["event"], "intent_judge_start")
            self.assertEqual(second["event"], "intent_judge_result")
            self.assertEqual(first["decision_id"], decision_id)
            self.assertEqual(second["decision_id"], decision_id)
            self.assertEqual(first["public_version"], "2.4.1")
            self.assertEqual(second["internal_target_version"], "3.1.400")
            self.assertEqual(second["decision"], "draw_now")
            self.assertEqual(first["context_source"], "scene_context")
            self.assertTrue(second["hash"])
            self.assertEqual(second["hash"], result_hash)
            expected = {
                "decision_id": decision_id,
                "result_hash": result_hash,
                "decision": "draw_now",
                "confidence": 0.9,
                "backend_used": "local",
                "reason": "test",
                "latency_ms": 1.0,
                "trace": {},
                "user_message_hash": hashlib.sha256(
                    "我想看你在干嘛".encode("utf-8")
                ).hexdigest(),
                "user_id_hash": "user-hash",
                "context_hash": "ctx-hash",
                "context_source": "scene_context",
                "public_version": "2.4.1",
                "internal_target_version": "3.1.400",
            }
            self.assertTrue(ledger.verify(decision_id, expected))
            bad_decision = dict(expected)
            bad_decision["decision"] = "no_draw"
            self.assertFalse(ledger.verify(decision_id, bad_decision))
            bad_confidence = dict(expected)
            bad_confidence["confidence"] = 0.1
            self.assertFalse(ledger.verify(decision_id, bad_confidence))

    def test_result_after_ledger_restart_is_allowed(self) -> None:
        from ..services.intent_decision_ledger import IntentDecisionLedger

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent_judge_decisions_v1.jsonl"
            ledger1 = IntentDecisionLedger(
                path,
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            decision_id = ledger1.start(
                user_message="x",
                user_id_hash="u",
                context_hash="ctx",
            )
            ledger2 = IntentDecisionLedger(
                path,
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            result_hash = ledger2.result(
                decision_id,
                types.SimpleNamespace(
                    decision="draw_now",
                    confidence=0.8,
                    backend_used="local",
                    reason="restart",
                    latency_ms=0.0,
                    trace={},
                ),
            )
            self.assertTrue(result_hash)

    def test_second_result_for_same_decision_is_rejected(self) -> None:
        from ..services.intent_decision_ledger import (
            IntentDecisionLedger,
            IntentDecisionLedgerError,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ledger = IntentDecisionLedger(
                Path(tmp) / "intent_judge_decisions_v1.jsonl",
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            decision_id = ledger.start(
                user_message="x",
                user_id_hash="u",
                context_hash="ctx",
            )
            ledger.result(
                decision_id,
                types.SimpleNamespace(
                    decision="draw_now",
                    confidence=0.8,
                    backend_used="local",
                    reason="a",
                    latency_ms=0.0,
                    trace={},
                ),
            )
            with self.assertRaises(IntentDecisionLedgerError):
                ledger.result(
                    decision_id,
                    types.SimpleNamespace(
                        decision="no_draw",
                        confidence=0.0,
                        backend_used="local",
                        reason="b",
                        latency_ms=0.0,
                        trace={},
                    ),
                )

    def test_exact_duplicate_result_line_marks_ledger_corrupt_and_blocks_writes(self) -> None:
        from ..services.intent_decision_ledger import (
            IntentDecisionLedger,
            IntentDecisionLedgerError,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent_judge_decisions_v1.jsonl"
            ledger = IntentDecisionLedger(
                path,
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            decision_id = ledger.start(
                user_message="x",
                user_id_hash="u",
                context_hash="ctx",
            )
            result_hash = ledger.result(
                decision_id,
                types.SimpleNamespace(
                    decision="draw_now",
                    confidence=0.8,
                    backend_used="local",
                    reason="a",
                    latency_ms=0.0,
                    trace={},
                ),
            )
            result_line = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["event"] == "intent_judge_result"
            ][0]
            with path.open("a", encoding="utf-8") as handle:
                handle.write(result_line + "\n")

            ledger2 = IntentDecisionLedger(
                path,
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            expected = {
                "decision_id": decision_id,
                "result_hash": result_hash,
                "decision": "draw_now",
                "confidence": 0.8,
                "backend_used": "local",
                "reason": "a",
                "latency_ms": 0.0,
                "trace": {},
                "user_message_hash": hashlib.sha256("x".encode()).hexdigest(),
                "user_id_hash": "u",
                "context_hash": "ctx",
                "context_source": "",
                "public_version": "2.4.1",
                "internal_target_version": "3.1.400",
            }
            self.assertFalse(ledger2.verify(decision_id, expected))
            with self.assertRaises(IntentDecisionLedgerError):
                ledger2.start(user_message="y", user_id_hash="u", context_hash="c2")

    def test_result_without_start_is_rejected(self) -> None:
        from ..services.intent_decision_ledger import (
            IntentDecisionLedger,
            IntentDecisionLedgerError,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ledger = IntentDecisionLedger(
                Path(tmp) / "intent_judge_decisions_v1.jsonl",
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            with self.assertRaises(IntentDecisionLedgerError):
                ledger.result(
                    "missing",
                    types.SimpleNamespace(decision="draw_now"),
                )


class IntentRouterGateLedgerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_gate_writes_ledger_and_decision_id_to_extra(self) -> None:
        from ..services.intent_decision_ledger import IntentDecisionLedger

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            intent_router_gate_mode="on",
            scene_context_window=8,
            scene_extraction_max_memories=5,
        )

        draw_now = self.main.DRAW_NOW

        class Judge:
            async def judge(self, message, bot_reply, context=""):
                return types.SimpleNamespace(
                    decision=draw_now,
                    confidence=0.88,
                    backend_used="test",
                    reason="test",
                    latency_ms=2.0,
                    trace={},
                )

        plugin._build_intent_judge_service = lambda: Judge()

        class Event:
            message_str = "我想看你在干嘛"

            def __init__(self):
                self._extras = {}

            def get_extra(self, key, default=None):
                return self._extras.get(key, default)

            def set_extra(self, key, value):
                self._extras[key] = value

        with tempfile.TemporaryDirectory() as tmp:
            ledger = IntentDecisionLedger(
                Path(tmp) / "intent_judge_decisions_v1.jsonl",
                public_version="2.4.1",
                internal_target_version="3.1.400",
            )
            plugin._intent_decision_ledger = ledger
            event = Event()
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
            lines = ledger.path.read_text(encoding="utf-8").splitlines()
            payload = event.get_extra(
                "astrbot_plugin_comfy_anima:intent_router_gate_result"
            )
        self.assertEqual(len(lines), 2)
        self.assertEqual(payload["decision"], self.main.DRAW_NOW)
        self.assertTrue(payload["decision_id"])
        self.assertTrue(payload["result_hash"])
        self.assertEqual(json.loads(lines[0])["decision_id"], payload["decision_id"])
        self.assertEqual(json.loads(lines[1])["hash"], payload["result_hash"])

    async def _run_gate_with_ledger(self, ledger):
        draw_now = self.main.DRAW_NOW

        class Judge:
            async def judge(self, message, bot_reply, context=""):
                return types.SimpleNamespace(
                    decision=draw_now,
                    confidence=0.88,
                    backend_used="test",
                    reason="test",
                    latency_ms=2.0,
                    trace={},
                )

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            intent_router_gate_mode="on",
            scene_context_window=8,
            scene_extraction_max_memories=5,
        )
        plugin._build_intent_judge_service = lambda: Judge()
        plugin._intent_decision_ledger = ledger

        class Event:
            message_str = "我想看你在干嘛"

            def __init__(self):
                self._extras = {}

            def get_extra(self, key, default=None):
                return self._extras.get(key, default)

            def set_extra(self, key, value):
                self._extras[key] = value

        event = Event()

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
        return event.get_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result"
        )

    async def test_gate_fails_closed_when_ledger_start_fails(self) -> None:
        class FailingStart:
            def start(self, **kwargs):
                raise RuntimeError("disk full")

        payload = await self._run_gate_with_ledger(FailingStart())
        self.assertEqual(payload["decision"], self.main.NO_DRAW)
        self.assertIn("ledger_start_failed", payload["status"])

    async def test_gate_fails_closed_when_ledger_result_fails(self) -> None:
        class FailingResult:
            def start(self, **kwargs):
                return "decision-1"

            def result(self, decision_id, result):
                raise RuntimeError("disk full")

        payload = await self._run_gate_with_ledger(FailingResult())
        self.assertEqual(payload["decision"], self.main.NO_DRAW)
        self.assertIn("ledger_result_failed", payload["status"])


if __name__ == "__main__":
    unittest.main()
