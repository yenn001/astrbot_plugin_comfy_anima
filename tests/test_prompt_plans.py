"""Tests for persistent, execution-neutral prompt plans."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ..services.prompt_plans import (
    BUILTIN_PROMPT_PLANS,
    MAX_CUSTOM_PLANS,
    PROMPT_PLAN_SCHEMA,
    PromptPlanAmbiguousError,
    PromptPlanConflictError,
    PromptPlanLimitError,
    PromptPlanNotFoundError,
    PromptPlanStorageError,
    PromptPlanStore,
    PromptPlanValidationError,
)


class PromptPlanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "nested" / "prompt_plans_v1.json"
        self.store = PromptPlanStore(self.path)

    def _save(self, name: str = "风格2（凛然）", **overrides: object) -> dict:
        payload = {
            "name": name,
            "positive_prompt": "1girl, solo, standing. A woman waits beside a window.",
            "negative_prompt": "lowres, blurry",
            "pipeline": "rtx",
            "layers": {
                "identity": ["1girl", "solo"],
                "relation": "A woman waits beside a window.",
            },
            "locked_layers": ["identity", "camera"],
            "source": "prompt_lab",
        }
        payload.update(overrides)
        return self.store.save_plan(**payload)

    def test_lists_five_complete_read_only_examples_without_creating_file(self) -> None:
        plans = self.store.list_plans()

        self.assertEqual([item["plan_id"] for item in plans], [
            "EX-001", "EX-002", "EX-003", "EX-004", "EX-005"
        ])
        self.assertFalse(self.path.exists())
        self.assertTrue(all(item["builtin"] for item in plans))
        required = {
            "plan_id", "name", "positive_prompt", "negative_prompt",
            "pipeline", "layers", "locked_layers", "source", "builtin",
            "created_at", "updated_at",
        }
        for plan in plans:
            self.assertEqual(set(plan), required)
            self.assertRegex(plan["positive_prompt"], r"\. [A-Z].+\.$")

    def test_builtin_results_are_defensive_copies(self) -> None:
        first = self.store.resolve_plan("EX-001")
        first["name"] = "tampered"
        first["layers"]["identity"].append("extra")

        fresh = self.store.resolve_plan("EX-001")
        self.assertEqual(fresh["name"], "雨夜霓虹肖像")
        self.assertNotIn("extra", fresh["layers"]["identity"])
        self.assertEqual(BUILTIN_PROMPT_PLANS[0]["name"], "雨夜霓虹肖像")

    def test_save_is_persistent_and_uses_short_random_id(self) -> None:
        plan = self._save()

        self.assertRegex(plan["plan_id"], r"^P-[0-9A-F]{6}$")
        self.assertFalse(plan["builtin"])
        self.assertEqual(plan["pipeline"], "rtx")
        self.assertEqual(plan["locked_layers"], ["identity", "camera"])
        self.assertTrue(self.path.exists())
        reloaded = PromptPlanStore(self.path).resolve_plan(plan["plan_id"].lower())
        self.assertEqual(reloaded, plan)

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["schema"], PROMPT_PLAN_SCHEMA)
        self.assertEqual(list(raw["plans"]), [plan["plan_id"]])
        self.assertNotIn("EX-001", raw["plans"])

    def test_resolves_full_name_and_unique_trailing_annotation_alias(self) -> None:
        plan = self._save()

        self.assertEqual(self.store.resolve_plan("风格2（凛然）")["plan_id"], plan["plan_id"])
        self.assertEqual(self.store.resolve_plan(" 风格2 ")["plan_id"], plan["plan_id"])

    def test_alias_can_remove_multiple_supported_trailing_annotations(self) -> None:
        plan = self._save("风格1011 [夜景]（推荐）")

        self.assertEqual(self.store.resolve_plan("风格1011")["plan_id"], plan["plan_id"])

    def test_ambiguous_short_alias_fails_closed(self) -> None:
        first = self._save("风格9（暖色）")
        second = self._save("风格9（冷色）")

        with self.assertRaisesRegex(PromptPlanAmbiguousError, "ambiguous"):
            self.store.resolve_plan("风格9")
        self.assertEqual(self.store.resolve_plan(first["plan_id"])["name"], "风格9（暖色）")
        self.assertEqual(self.store.resolve_plan(second["plan_id"])["name"], "风格9（冷色）")

    def test_missing_plan_raises_specific_error(self) -> None:
        with self.assertRaises(PromptPlanNotFoundError):
            self.store.resolve_plan("does-not-exist")

    def test_builtin_cannot_be_deleted_or_overwritten(self) -> None:
        with self.assertRaisesRegex(PromptPlanConflictError, "cannot be deleted"):
            self.store.delete_plan("EX-001")
        with self.assertRaisesRegex(PromptPlanConflictError, "cannot be overwritten"):
            self._save("雨夜霓虹肖像", overwrite=True)

    def test_custom_name_requires_explicit_overwrite_and_preserves_identity(self) -> None:
        first = self._save("我的方案")
        with self.assertRaises(PromptPlanConflictError):
            self._save("我的方案")

        updated = self._save(
            "我的方案",
            positive_prompt="1boy, solo. A man stands in sunlight.",
            overwrite=True,
        )
        self.assertEqual(updated["plan_id"], first["plan_id"])
        self.assertEqual(updated["created_at"], first["created_at"])
        self.assertEqual(updated["positive_prompt"], "1boy, solo. A man stands in sunlight.")

    def test_delete_custom_plan_persists(self) -> None:
        plan = self._save()

        removed = self.store.delete_plan("风格2")
        self.assertEqual(removed["plan_id"], plan["plan_id"])
        with self.assertRaises(PromptPlanNotFoundError):
            PromptPlanStore(self.path).resolve_plan(plan["plan_id"])

    def test_list_can_redact_prompts_and_filter(self) -> None:
        plan = self._save("私有夜景")

        listed = self.store.list_plans(keyword="私有", include_prompts=False)
        self.assertEqual([item["plan_id"] for item in listed], [plan["plan_id"]])
        self.assertNotIn("positive_prompt", listed[0])
        self.assertNotIn("negative_prompt", listed[0])
        self.assertNotIn("layers", listed[0])

    def test_validation_rejects_empty_prompt_and_non_json_layers(self) -> None:
        with self.assertRaises(PromptPlanValidationError):
            self._save(positive_prompt="")
        with self.assertRaises(PromptPlanValidationError):
            self._save(name="bad\x00name")
        with self.assertRaises(PromptPlanValidationError):
            self._save(layers={"identity": {object()}})

    def test_corrupt_state_fails_loudly_instead_of_hiding_plans(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")

        with self.assertRaisesRegex(PromptPlanStorageError, "cannot read"):
            self.store.list_plans()

    def test_state_cannot_inject_builtin_or_unknown_fields(self) -> None:
        plan = self._save()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["plans"][plan["plan_id"]]["builtin"] = True
        raw["plans"][plan["plan_id"]]["extra"] = "bad"
        self.path.write_text(json.dumps(raw), encoding="utf-8")

        with self.assertRaises(PromptPlanStorageError):
            self.store.list_plans()

    def test_atomic_replace_failure_preserves_previous_file_and_removes_temp(self) -> None:
        first = self._save("first")
        before = self.path.read_bytes()

        with mock.patch(
            "astrbot_plugin_comfy_anima.services.prompt_plans.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaises(PromptPlanStorageError):
                self._save("second")

        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(self.store.resolve_plan(first["plan_id"])["name"], "first")

    def test_custom_limit_is_enforced_without_rewriting_state(self) -> None:
        with mock.patch(
            "astrbot_plugin_comfy_anima.services.prompt_plans.MAX_CUSTOM_PLANS",
            2,
        ):
            self._save("one")
            self._save("two")
            before = self.path.read_bytes()
            with self.assertRaises(PromptPlanLimitError):
                self._save("three")
            self.assertEqual(self.path.read_bytes(), before)

    def test_declared_capacity_is_128(self) -> None:
        self.assertEqual(MAX_CUSTOM_PLANS, 128)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
