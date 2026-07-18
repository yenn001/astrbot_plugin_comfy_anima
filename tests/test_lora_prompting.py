"""Runtime LoRA stack and evidence-backed trigger-word tests."""

import unittest

from ..models import LoraSelection
from ..services.lora_catalog import LoraRecord
from ..services.lora_presets import LoraPreset
from ..services.lora_prompting import (
    build_lora_trigger_plan,
    merge_runtime_lora_selections,
)


class RuntimeLoraMergeTests(unittest.TestCase):
    def test_style_preset_weight_cannot_be_overridden(self) -> None:
        preset = LoraPreset(
            name="风格001",
            category="artist_style",
            selections=(LoraSelection("styles/ink", 0.5),),
        )

        plan = merge_runtime_lora_selections(
            (preset,),
            (LoraSelection("styles/ink", 1.2),),
        )

        self.assertEqual(plan.selections, (LoraSelection("styles/ink", 0.5),))
        self.assertEqual(plan.ignored_locked_overrides, ("styles/ink",))

    def test_character_preset_weight_can_be_explicitly_adjusted(self) -> None:
        preset = LoraPreset(
            name="角色达妮娅",
            category="character",
            selections=(LoraSelection("characters/denia", 0.8),),
        )

        plan = merge_runtime_lora_selections(
            (preset,),
            (LoraSelection("characters/denia", 0.55),),
        )

        self.assertEqual(
            plan.selections,
            (LoraSelection("characters/denia", 0.55),),
        )
        self.assertEqual(plan.ignored_locked_overrides, ())


class RuntimeLoraTriggerTests(unittest.TestCase):
    def test_style_gets_all_triggers_but_character_gets_identity_only(self) -> None:
        selections = (
            LoraSelection("styles/base", 0.5),
            LoraSelection("characters/denia", 0.8),
        )
        records = {
            "styles/base": LoraRecord(
                "styles/base.safetensors",
                category="quality_enhancement",
                trigger_words=("masterpiece", "very aesthetic"),
            ),
            "characters/denia": LoraRecord(
                "characters/denia.safetensors",
                category="character",
                trigger_words=("denia_wuwa", "black coat", "silver hair"),
                character_name="Denia",
                aliases=("达妮娅", "denia"),
            ),
        }

        plan = build_lora_trigger_plan(
            prompt="1girl, casual hoodie, black coat",
            negative_prompt="black coat",
            selections=selections,
            records_by_name=records,
        )

        self.assertEqual(
            plan.prompt,
            "1girl, casual hoodie, masterpiece, very aesthetic, denia_wuwa",
        )
        self.assertNotIn("black coat", plan.prompt)
        self.assertNotIn("silver hair", plan.prompt)
        self.assertTrue(any("removed positive" in item for item in plan.skipped))

    def test_manual_preset_triggers_are_authoritative_for_members(self) -> None:
        preset = LoraPreset(
            name="风格001",
            category="artist_style",
            selections=(LoraSelection("styles/base", 0.5),),
            trigger_words="hand tuned style",
        )

        plan = build_lora_trigger_plan(
            prompt="1girl",
            negative_prompt="",
            selections=preset.selections,
            records_by_name={
                "styles/base": LoraRecord(
                    "styles/base",
                    category="artist_style",
                    trigger_words=("manager trigger", "second trigger"),
                )
            },
            presets=(preset,),
        )

        self.assertEqual(plan.prompt, "1girl, hand tuned style")
        self.assertNotIn("manager trigger", plan.prompt)

    def test_semantic_rewrite_suppresses_manual_and_metadata_triggers(self) -> None:
        preset = LoraPreset(
            name="legacy mix",
            category="artist_style",
            selections=(LoraSelection("styles/base", 0.5),),
            trigger_words="denia_wuwa, hand tuned style",
        )

        plan = build_lora_trigger_plan(
            prompt="1girl",
            negative_prompt="",
            selections=preset.selections,
            records_by_name={
                "styles/base": LoraRecord(
                    "styles/base",
                    category="artist_style",
                    trigger_words=("denia_wuwa", "manager style"),
                )
            },
            presets=(preset,),
            suppressed_terms=("denia_wuwa",),
        )

        self.assertEqual(plan.prompt, "1girl, hand tuned style")
        self.assertNotIn("denia_wuwa", plan.prompt)
        self.assertTrue(any("suppressed" in item for item in plan.skipped))

    def test_existing_trigger_is_not_duplicated(self) -> None:
        plan = build_lora_trigger_plan(
            prompt="1girl, masterpiece",
            negative_prompt="",
            selections=(LoraSelection("quality", 0.5),),
            records_by_name={
                "quality": LoraRecord(
                    "quality",
                    category="quality_enhancement",
                    trigger_words=("masterpiece", "very aesthetic"),
                )
            },
        )

        self.assertEqual(plan.prompt, "1girl, masterpiece, very aesthetic")

    def test_unclassified_or_unreliable_character_trigger_is_skipped(self) -> None:
        selections = (
            LoraSelection("unknown", 0.5),
            LoraSelection("character", 0.8),
        )
        plan = build_lora_trigger_plan(
            prompt="1girl",
            negative_prompt="",
            selections=selections,
            records_by_name={
                "unknown": LoraRecord(
                    "unknown",
                    category="unknown",
                    trigger_words=("mystery token",),
                ),
                "character": LoraRecord(
                    "character",
                    category="character",
                    trigger_words=("school uniform", "blue eyes"),
                    character_name="Hero",
                ),
            },
        )

        self.assertEqual(plan.prompt, "1girl")
        self.assertEqual(len(plan.skipped), 2)

    def test_character_alias_cannot_circularly_prove_outfit_as_identity(self) -> None:
        plan = build_lora_trigger_plan(
            prompt="1girl",
            negative_prompt="",
            selections=(LoraSelection("character", 0.8),),
            records_by_name={
                "character": LoraRecord(
                    "character",
                    category="character",
                    trigger_words=("black coat",),
                    aliases=("black coat",),
                    character_name="Denia",
                )
            },
        )

        self.assertEqual(plan.prompt, "1girl")
        self.assertIn("no reliable character identity", plan.skipped[0])

    def test_civitai_markdown_parentheses_are_restored_before_injection(self) -> None:
        plan = build_lora_trigger_plan(
            prompt="1girl",
            negative_prompt="",
            selections=(LoraSelection("character", 0.8),),
            records_by_name={
                "character": LoraRecord(
                    "character",
                    category="character",
                    trigger_words=(r"jett \(precure\)", "school uniform"),
                    character_name="jett / Jett",
                )
            },
        )

        self.assertEqual(plan.added, ("jett (precure)",))
        self.assertEqual(plan.prompt, "1girl, jett (precure)")


if __name__ == "__main__":
    unittest.main()
