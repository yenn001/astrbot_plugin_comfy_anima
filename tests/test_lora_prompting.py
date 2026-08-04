"""Runtime LoRA stack and evidence-backed trigger-word tests."""

import unittest

from ..core.lora import LoraWorkflowError
from ..models import LoraSelection
from ..services.lora_catalog import LoraRecord
from ..services.lora_presets import LoraPreset
from ..services.lora_prompting import (
    build_lora_trigger_plan,
    choose_character_identity_trigger,
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
    def test_verified_character_override_reclassifies_mislabeled_style_record(self) -> None:
        record = LoraRecord(
            "style/disguised.safetensors",
            category="artist_style",
            trigger_words=(r"toki \(blue archive\)", "masterpiece", "white bodysuit"),
        )

        plan = build_lora_trigger_plan(
            prompt="1girl, selfie",
            negative_prompt="",
            selections=(LoraSelection(record.name, 0.8),),
            records_by_name={"style/disguised": record},
            verified_character_triggers={record.name: r"toki \(blue archive\)"},
        )

        self.assertEqual(plan.added, (r"toki_\(blue_archive\)",))
        self.assertIn(r"toki_\(blue_archive\)", plan.prompt)
        self.assertNotIn("masterpiece", plan.prompt)
        self.assertNotIn("white bodysuit", plan.prompt)

    def test_verified_character_trigger_has_one_escape_layer_only(self) -> None:
        record = LoraRecord(
            "characters/rio.safetensors",
            category="character",
            character_name="Rio",
            trigger_words=(r"rio \\\\(blue archive\\\\)", "black bodysuit"),
        )
        free_form = r"1girl, custom\namespace, (portrait emphasis:1.2)"

        plan = build_lora_trigger_plan(
            prompt=free_form,
            negative_prompt="",
            selections=(LoraSelection(record.name, 0.8),),
            records_by_name={"characters/rio": record},
            verified_character_triggers={record.name: r"rio \(blue archive\)"},
        )

        self.assertEqual(plan.added, (r"rio_\(blue_archive\)",))
        self.assertEqual(plan.prompt.count(r"rio_\(blue_archive\)"), 1)
        self.assertNotIn(r"rio_\\(blue_archive\\)", plan.prompt)
        self.assertTrue(plan.prompt.startswith(free_form))

    def test_identity_trigger_matches_spaced_name_to_underscore_tag(self) -> None:
        record = LoraRecord(
            "characters/kallen.safetensors",
            category="character",
            character_name="Kallen Kaslana",
            trigger_words=("kallen_kaslana", "white hair"),
        )

        self.assertEqual(
            choose_character_identity_trigger(record),
            "kallen_kaslana",
        )

    def test_single_character_without_trained_words_uses_identity_anchor(self) -> None:
        record = LoraRecord(
            "characters/viola.safetensors",
            category="character",
            character_name="Viola / 薇欧拉 / 薇欧拉-梦限大Mewtype",
            trigger_words=(),
        )

        self.assertEqual(choose_character_identity_trigger(record), "")
        plan = build_lora_trigger_plan(
            prompt=r"1girl, viola_\(bang_dream!\), maid, selfie",
            negative_prompt="",
            selections=(LoraSelection(record.name, 0.65),),
            records_by_name={"characters/viola": record},
            verified_character_triggers={record.name: "viola"},
        )
        self.assertIn(r"viola_\(bang_dream!\)", plan.prompt)

    def test_multi_character_without_trained_words_has_no_identity_anchor(self) -> None:
        record = LoraRecord(
            "characters/multi.safetensors",
            category="character",
            character_name="Viola / Rio",
            trigger_words=(),
        )

        self.assertEqual(choose_character_identity_trigger(record), "")

    def test_multi_character_trained_words_require_query_specific_identity(self) -> None:
        record = LoraRecord(
            "characters/baarmed_4in1_v1.safetensors",
            category="character",
            character_name="Himari / Eimi / Rio / Toki",
            trigger_words=(
                r"himari \(armed\) \(blue archive\), white bodysuit",
                r"eimi \(armed\) \(blue archive\), black sports bra",
                r"rio \(armed\) \(blue archive\), black bodysuit, skin tight",
                r"toki \(armed\) \(blue archive\), hooded jacket",
            ),
        )

        self.assertEqual(choose_character_identity_trigger(record), "")
        self.assertEqual(
            choose_character_identity_trigger(record, ("rio",)),
            "rio (armed) (blue archive)",
        )

    def test_verified_override_selects_one_identity_from_multi_character_lora(self) -> None:
        record = LoraRecord(
            "characters/baarmed_4in1_v1.safetensors",
            category="character",
            character_name="Himari / Eimi / Rio / Toki",
            trigger_words=(
                r"himari \(armed\) \(blue archive\), white bodysuit",
                r"eimi \(armed\) \(blue archive\), black sports bra",
                r"rio \(armed\) \(blue archive\), black bodysuit",
                r"toki \(armed\) \(blue archive\), hooded jacket",
            ),
        )

        plan = build_lora_trigger_plan(
            prompt="1girl, solo",
            negative_prompt="",
            selections=(LoraSelection("characters/baarmed_4in1_v1", 0.8),),
            records_by_name={"characters/baarmed_4in1_v1": record},
            verified_character_triggers={
                "characters/baarmed_4in1_v1": "toki (armed) (blue archive)"
            },
        )

        self.assertEqual(
            plan.added,
            (r"toki_\(armed\)_\(blue_archive\)",),
        )
        self.assertIn(r"toki_\(armed\)_\(blue_archive\)", plan.prompt)
        self.assertNotIn("himari", plan.prompt)
        self.assertNotIn("eimi", plan.prompt)
        self.assertNotIn("rio", plan.prompt)
        self.assertFalse(any("no reliable" in item for item in plan.skipped))

    def test_invalid_verified_character_override_fails_closed(self) -> None:
        record = LoraRecord(
            "characters/rio.safetensors",
            category="character",
            character_name="Rio",
            trigger_words=(r"rio \(blue archive\)", "black bodysuit"),
        )

        with self.assertRaises(LoraWorkflowError):
            build_lora_trigger_plan(
                prompt="1girl, solo",
                negative_prompt="",
                selections=(LoraSelection("characters/rio", 0.8),),
                records_by_name={"characters/rio": record},
                verified_character_triggers={
                    "characters/rio": "black bodysuit"
                },
            )

    def test_character_record_in_style_preset_stays_identity_only(self) -> None:
        preset = LoraPreset(
            name="misclassified style",
            category="artist_style",
            selections=(LoraSelection("characters/rio", 0.8),),
        )
        for category, character_name in (
            ("character", ""),
            ("artist_style", "Rio"),
        ):
            with self.subTest(category=category, character_name=character_name):
                record = LoraRecord(
                    "characters/rio.safetensors",
                    category=category,
                    character_name=character_name,
                    trigger_words=(
                        r"rio \(blue archive\)",
                        "black dress",
                        "red eyes",
                    ),
                )

                plan = build_lora_trigger_plan(
                    prompt="1girl, solo",
                    negative_prompt="",
                    selections=preset.selections,
                    records_by_name={"characters/rio": record},
                    presets=(preset,),
                )

                self.assertEqual(plan.added, ("rio (blue archive)",))
                self.assertNotIn("black dress", plan.prompt)
                self.assertNotIn("red eyes", plan.prompt)

    def test_character_trigger_plan_splits_compound_civitai_trained_word(self) -> None:
        record = LoraRecord(
            "characters/rio.safetensors",
            category="character",
            character_name="Rio",
            trigger_words=(
                r"rio \(blue archive\), black bodysuit, skin tight",
            ),
        )
        plan = build_lora_trigger_plan(
            prompt="1girl, solo",
            negative_prompt="",
            selections=(LoraSelection("characters/rio", 0.7),),
            records_by_name={"characters/rio": record},
        )

        self.assertEqual(plan.added, ("rio (blue archive)",))

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

    def test_manual_preset_triggers_supplement_latest_manager_metadata(self) -> None:
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

        self.assertEqual(
            plan.prompt,
            "1girl, hand tuned style, manager trigger, second trigger",
        )

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

        self.assertEqual(plan.prompt, "1girl, hand tuned style, manager style")
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

    def test_preset_and_manager_triggers_stay_before_scene_sentence(self) -> None:
        preset = LoraPreset(
            name="style preset",
            category="artist_style",
            selections=(LoraSelection("styles/manual", 0.5),),
            trigger_words="hand tuned ink",
        )
        selections = (
            *preset.selections,
            LoraSelection("styles/manager", 0.6),
        )
        records = {
            "styles/manual": LoraRecord(
                "styles/manual",
                category="artist_style",
                trigger_words=("latest manager trigger",),
            ),
            "styles/manager": LoraRecord(
                "styles/manager",
                category="artist_style",
                trigger_words=("paper texture", "warm palette"),
            ),
        }

        plan = build_lora_trigger_plan(
            prompt=(
                "<lora:styles/manual:0.5>, <lora:styles/manager:0.6>, "
                "1girl, beach. A girl stands beside the sea at sunset."
            ),
            negative_prompt="",
            selections=selections,
            records_by_name=records,
            presets=(preset,),
        )

        self.assertEqual(
            plan.prompt,
            "<lora:styles/manual:0.5>, <lora:styles/manager:0.6>, 1girl, "
            "beach, hand tuned ink, latest manager trigger, paper texture, warm palette. "
            "A girl stands beside the sea at sunset.",
        )
        self.assertEqual(
            plan.added,
            (
                "hand tuned ink",
                "latest manager trigger",
                "paper texture",
                "warm palette",
            ),
        )
        self.assertTrue(plan.prompt.endswith("A girl stands beside the sea at sunset."))

    def test_outfit_conflict_filter_only_rewrites_hybrid_tag_block(self) -> None:
        plan = build_lora_trigger_plan(
            prompt=(
                "<lora:characters/denia:0.8>, 1girl, school uniform, "
                "(casual hoodie:1.2). A girl stands in the rain and looks at the viewer."
            ),
            negative_prompt="school uniform",
            selections=(LoraSelection("characters/denia", 0.8),),
            records_by_name={
                "characters/denia": LoraRecord(
                    "characters/denia",
                    category="character",
                    trigger_words=("denia_wuwa", "school uniform"),
                    character_name="Denia",
                )
            },
        )

        self.assertEqual(
            plan.prompt,
            "<lora:characters/denia:0.8>, 1girl, (casual hoodie:1.2), "
            "denia_wuwa. A girl stands in the rain and looks at the viewer.",
        )
        self.assertNotIn("school uniform", plan.prompt)
        self.assertIn("(casual hoodie:1.2)", plan.prompt)
        self.assertTrue(
            plan.prompt.endswith("A girl stands in the rain and looks at the viewer.")
        )


if __name__ == "__main__":
    unittest.main()
