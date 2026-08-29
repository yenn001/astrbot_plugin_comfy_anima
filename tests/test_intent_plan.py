"""Deterministic IntentPlan and read-only ToolSet snapshot tests."""

import sys
import types
import unittest
from unittest import mock

from ..services.chat_intent_classifier import (
    INTENT_CLARIFY,
    INTENT_DRAW_NEW,
    INTENT_EDIT_LAST_IMAGE,
    PROBE_DANBOORU,
    PROBE_LORA,
    PROBE_LORA_PRESETS,
    PROBE_PREVIOUS_IMAGE,
    PROBE_PROMPT_PLAN,
    PROBE_SUBJECT,
    build_intent_plan,
)
from ..services.toolset_snapshot import (
    restrict_toolset_non_mutating,
    snapshot_tool_names,
)


class IntentPlanTests(unittest.TestCase):
    def test_plain_draw_has_only_optional_probes(self) -> None:
        plan = build_intent_plan("画一张夏日海边")
        self.assertEqual(plan.intent, INTENT_DRAW_NEW)
        self.assertEqual(plan.required_probes, ())
        self.assertIn(PROBE_DANBOORU, plan.optional_probes)
        self.assertIn(PROBE_LORA, plan.optional_probes)

    def test_named_subject_requires_subject_resolution(self) -> None:
        plan = build_intent_plan(
            "画一张 kei 的女仆自拍",
            requested_subject="kei_(blue_archive)",
        )
        self.assertIn(PROBE_SUBJECT, plan.required_probes)
        self.assertEqual(plan.requested_subject, "kei_(blue_archive)")
        self.assertFalse(plan.identity_required)

    def test_identity_required_forces_subject_probe(self) -> None:
        plan = build_intent_plan("画一张原创角色", identity_required=True)
        self.assertIn(PROBE_SUBJECT, plan.required_probes)
        self.assertTrue(plan.identity_required)

    def test_preset_combo_requires_preset_probe(self) -> None:
        plan = build_intent_plan("风格006 达妮娅组合")
        self.assertIn(PROBE_LORA_PRESETS, plan.required_probes)
        self.assertIn(PROBE_LORA, plan.optional_probes)
        self.assertIn(PROBE_DANBOORU, plan.optional_probes)

    def test_prompt_plan_mention_requires_plan_probe(self) -> None:
        plan = build_intent_plan("按管理员保存的预设方案生成")
        self.assertIn(PROBE_PROMPT_PLAN, plan.required_probes)

    def test_edit_last_requires_previous_image_probe(self) -> None:
        plan = build_intent_plan("重画上一张")
        self.assertEqual(plan.intent, INTENT_EDIT_LAST_IMAGE)
        self.assertIn(PROBE_PREVIOUS_IMAGE, plan.required_probes)

    def test_same_input_gives_same_plan(self) -> None:
        first = build_intent_plan("风格006 达妮娅组合")
        second = build_intent_plan("风格006 达妮娅组合")
        self.assertEqual(first, second)

    def test_continuation_without_recipe_stays_clarify(self) -> None:
        plan = build_intent_plan("继续", has_recipe=False)
        self.assertEqual(plan.intent, INTENT_CLARIFY)
        self.assertEqual(plan.required_probes, ())
        self.assertEqual(plan.optional_probes, ())


class ToolSetSnapshotTests(unittest.TestCase):
    def test_snapshot_returns_ordered_names(self) -> None:
        tool_set = types.SimpleNamespace(
            tools=[
                types.SimpleNamespace(name="safe_a"),
                types.SimpleNamespace(name="delivery"),
                types.SimpleNamespace(name="safe_b"),
            ]
        )
        self.assertEqual(
            snapshot_tool_names(tool_set), ("safe_a", "delivery", "safe_b")
        )

    def test_restrict_builds_new_toolset_and_preserves_input(self) -> None:
        class FakeToolSet:
            def __init__(self, tools):
                self.tools = list(tools)

        module = types.ModuleType("astrbot.core.agent.tool")
        module.ToolSet = FakeToolSet
        with mock.patch.dict(
            sys.modules, {"astrbot.core.agent.tool": module}
        ):
            original = [
                types.SimpleNamespace(name="safe_a"),
                types.SimpleNamespace(name="delivery"),
            ]
            tool_set = types.SimpleNamespace(tools=original)
            self.assertEqual(
                snapshot_tool_names(
                    restrict_toolset_non_mutating(tool_set, {"safe_a"})
                ),
                ("safe_a",),
            )
            self.assertEqual(
                snapshot_tool_names(tool_set), ("safe_a", "delivery")
            )

    def test_empty_allowed_subset_returns_none(self) -> None:
        tool_set = types.SimpleNamespace(
            tools=[types.SimpleNamespace(name="delivery")]
        )
        self.assertIsNone(restrict_toolset_non_mutating(tool_set, {"nothing"}))


if __name__ == "__main__":
    unittest.main()
