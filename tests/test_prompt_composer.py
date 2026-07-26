"""Tests for deterministic three-layer prompt composition."""

from __future__ import annotations

import concurrent.futures
import unittest

from ..services.prompt_composer import (
    PromptComposer,
    PromptDiagnosticsStore,
    insert_tags_before_scene_sentence,
    split_hybrid_prompt,
)


class HybridPromptSplitTests(unittest.TestCase):
    def test_lora_version_and_decimal_weight_are_not_sentence_boundaries(self) -> None:
        tag_block, scene = split_hybrid_prompt(
            "<lora:styles/anima.v1.2:0.50>, version 2.1, 1girl, beach. "
            "She stands in shallow water while holding a sparkler."
        )

        self.assertEqual(
            tag_block,
            "<lora:styles/anima.v1.2:0.50>, version 2.1, 1girl, beach",
        )
        self.assertEqual(
            scene,
            "She stands in shallow water while holding a sparkler.",
        )

    def test_legacy_comma_only_scene_is_detected_at_its_real_start(self) -> None:
        tag_block, scene = split_hybrid_prompt(
            "1girl, beach, night, soft lighting, she squats in the shallow "
            "water while holding a sparkler in one hand"
        )

        self.assertEqual(tag_block, "1girl, beach, night, soft lighting")
        self.assertTrue(scene.startswith("she squats"))

    def test_pure_natural_language_is_not_mislabelled_as_tags(self) -> None:
        prose = "A girl stands on the beach while holding a sparkler at night."
        self.assertEqual(split_hybrid_prompt(prose), ("", prose))

    def test_apostrophe_inside_danbooru_tag_does_not_consume_later_tags(self) -> None:
        result = PromptComposer("off").compose(
            "1girl, worm's eye view, beach. "
            "She looks upward while standing beneath a bright summer sky."
        )

        self.assertIn("worm's eye view", result.layers.hard_tags)
        self.assertIn("beach", result.layers.hard_tags)

    def test_insert_tags_keeps_scene_sentence_last(self) -> None:
        result = insert_tags_before_scene_sentence(
            "1girl, beach. She watches the waves under moonlight.",
            ("blue hair", "beach"),
        )

        self.assertEqual(
            result,
            "1girl, beach, blue hair. She watches the waves under moonlight.",
        )

    def test_insert_lora_tag_also_moves_it_ahead_of_ordinary_tags(self) -> None:
        result = insert_tags_before_scene_sentence(
            "1girl, beach. She watches the waves under moonlight.",
            "<lora:style.v1.2:0.35>",
        )

        self.assertTrue(result.startswith("<lora:style.v1.2:0.35>, 1girl, beach."))


class PromptCompositionTests(unittest.TestCase):
    def test_loras_are_preserved_verbatim_and_moved_to_the_front(self) -> None:
        result = PromptComposer("off").compose(
            "1girl, <lora:characters/hero.v2:0.65>, beach. "
            "She looks across the moonlit water while holding a lantern."
        )

        self.assertTrue(
            result.positive_prompt.startswith(
                "<lora:characters/hero.v2:0.65>, 1girl, beach."
            )
        )
        self.assertEqual(
            result.layers.lora_tags,
            ("<lora:characters/hero.v2:0.65>",),
        )

    def test_exact_duplicate_ordinary_tags_are_removed_across_layers(self) -> None:
        result = PromptComposer("off").compose(
            "1girl, blue hair, blue hair",
            hard_tags=("blue hair", "green eyes"),
            visual_phrases=("blue hair", "soft amber light across her face"),
        )

        self.assertEqual(result.layers.hard_tags, ("1girl", "blue hair", "green eyes"))
        self.assertNotIn("blue hair", result.layers.visual_phrases)
        self.assertGreaterEqual(
            result.diagnostics.duplicates_removed.count("blue hair"), 2
        )

    def test_conflicting_input_facts_are_reported_but_preserved(self) -> None:
        result = PromptComposer("off").compose("1girl, day, night, outdoors")

        self.assertIn("day", result.layers.hard_tags)
        self.assertIn("night", result.layers.hard_tags)
        self.assertTrue(
            any(item.startswith("time:") for item in result.diagnostics.conflicts)
        )
        self.assertEqual(result.diagnostics.discarded_tags, ())

    def test_later_generated_mutual_exclusive_tag_is_conservatively_dropped(
        self,
    ) -> None:
        result = PromptComposer("off").compose(
            "1girl, night, outdoors",
            hard_tags=("day", "indoors", "blue eyes"),
        )

        self.assertNotIn("day", result.layers.hard_tags)
        self.assertNotIn("indoors", result.layers.hard_tags)
        self.assertIn("blue eyes", result.layers.hard_tags)
        self.assertEqual(result.diagnostics.discarded_tags, ("day", "indoors"))

    def test_anchor_dictionary_and_tuple_forms_are_supported(self) -> None:
        result = PromptComposer("off").compose(
            "portrait",
            anchors=(
                {"value": "night", "category": "time_of_day"},
                ("looking at viewer", "view_direction"),
            ),
            hard_tags=("day", "looking away"),
        )

        self.assertEqual(
            result.diagnostics.anchors,
            (("night", "time"), ("looking at viewer", "gaze")),
        )
        self.assertIn("night", result.layers.hard_tags)
        self.assertNotIn("day", result.layers.hard_tags)
        self.assertNotIn("looking away", result.layers.hard_tags)

    def test_existing_input_scene_wins_over_a_later_generated_scene(self) -> None:
        result = PromptComposer("off").compose(
            "1girl, beach. She stands beside the water while holding a lantern.",
            scene_sentence="She sits inside a train while reading a book.",
        )

        self.assertIn("stands beside the water", result.layers.scene_sentence)
        self.assertTrue(
            any(item.startswith("scene:") for item in result.diagnostics.conflicts)
        )
        self.assertIn(
            "She sits inside a train while reading a book.",
            result.diagnostics.discarded_tags,
        )


class AdaptiveNegativeTests(unittest.TestCase):
    def test_off_does_not_add_any_negative_tags(self) -> None:
        result = PromptComposer("off").compose("1girl, holding flower, full body")
        self.assertEqual(result.negative_prompt, "")
        self.assertEqual(result.diagnostics.adaptive_negative_added, ())

    def test_conservative_adds_only_risk_specific_terms(self) -> None:
        result = PromptComposer("conservative").compose(
            "1girl, holding flower, full body, from below"
        )

        self.assertIn("bad hands", result.negative_prompt)
        self.assertIn("bad feet", result.negative_prompt)
        self.assertIn("bad perspective", result.negative_prompt)
        self.assertNotIn("worst quality", result.negative_prompt)

    def test_standard_adds_baseline_and_deduplicates_existing_negative(self) -> None:
        result = PromptComposer("standard").compose(
            "1girl, holding flower",
            "lowres, lowres, extra fingers",
        )

        self.assertEqual(result.negative_prompt.count("lowres"), 1)
        self.assertEqual(result.negative_prompt.count("extra fingers"), 1)
        self.assertIn("bad anatomy", result.negative_prompt)


class PromptValidationTests(unittest.TestCase):
    def test_report_mode_records_unknown_tags_without_rewriting_them(self) -> None:
        result = PromptComposer(
            "off",
            tag_index={"1girl": True, "blue_hair": True},
            validation_mode="report",
        ).compose("1girl, invented character token, blue hair")

        self.assertEqual(result.diagnostics.unknown_tags, ("invented character token",))
        self.assertIn("invented character token", result.positive_prompt)

    def test_strict_mode_rejects_unknown_tags(self) -> None:
        composer = PromptComposer(
            "off",
            tag_index={"1girl": True},
            validation_mode="strict",
        )
        with self.assertRaisesRegex(ValueError, "unknown prompt tags"):
            composer.compose("1girl, invented_token")

    def test_lookup_object_uses_verified_flag_instead_of_object_truthiness(
        self,
    ) -> None:
        class LookupResult:
            def __init__(self, verified: bool):
                self.verified = verified

        class Index:
            def lookup(self, value: str) -> LookupResult:
                return LookupResult(value == "1girl")

        result = PromptComposer(
            "off",
            tag_index=Index(),
            validation_mode="report",
        ).compose("1girl, made_up_tag")

        self.assertEqual(result.diagnostics.unknown_tags, ("made_up_tag",))

    def test_unavailable_index_degrades_without_marking_every_tag_unknown(self) -> None:
        class UnavailableIndex:
            @staticmethod
            def status() -> dict[str, object]:
                return {"ready": False, "error": "missing"}

            def lookup(self, _value: str) -> object:
                raise AssertionError(
                    "lookup must not run while the index is unavailable"
                )

        result = PromptComposer(
            "off",
            tag_index=UnavailableIndex(),
            validation_mode="report",
        ).compose("1girl, custom trigger word")

        self.assertEqual(result.diagnostics.unknown_tags, ())
        self.assertEqual(result.diagnostics.validation_warnings, ())

    def test_guarded_only_blocks_explicit_identity_anchors(self) -> None:
        composer = PromptComposer(
            "off",
            tag_index={"1girl": True, "portrait": True},
            validation_mode="guarded",
        )

        report_only = composer.compose("1girl, custom trigger word")
        self.assertIn("custom trigger word", report_only.positive_prompt)
        with self.assertRaisesRegex(ValueError, "guarded identity"):
            composer.compose(
                "1girl, portrait",
                anchors=(("invented heroine", "character"),),
            )


class DiagnosticsStoreTests(unittest.TestCase):
    def test_passed_empty_store_is_used_and_content_is_private_by_default(self) -> None:
        store = PromptDiagnosticsStore(max_items=2)
        composer = PromptComposer("off", diagnostics_store=store)

        result = composer.compose("1girl, portrait", source="command")
        stored = store.get(result.diagnostic_id)

        self.assertIs(composer.diagnostics_store, store)
        self.assertIsNotNone(stored)
        self.assertIsNot(stored, result.diagnostics)
        self.assertEqual(stored.anchor_count, 0)
        self.assertEqual(stored.unknown_tags, ())
        self.assertEqual(result.diagnostics.positive_prompt, "")
        self.assertEqual(result.diagnostics.negative_prompt, "")

    def test_default_history_redacts_individual_prompt_terms_but_keeps_counts(
        self,
    ) -> None:
        store = PromptDiagnosticsStore(max_items=2)
        composer = PromptComposer("off", diagnostics_store=store)

        result = composer.compose(
            "1girl, blue hair, blue hair, day, night",
            hard_tags=("night", "invented private garment"),
        )
        stored = store.get(result.diagnostic_id)

        self.assertIsNotNone(stored)
        self.assertGreater(stored.duplicates_removed_count, 0)
        self.assertGreater(stored.conflict_count, 0)
        self.assertEqual(stored.duplicates_removed, ())
        self.assertEqual(stored.conflicts, ())
        self.assertEqual(stored.discarded_tags, ())
        self.assertNotIn(
            "invented private garment",
            str(stored.to_dict()),
        )

    def test_store_is_bounded_and_lists_newest_first(self) -> None:
        store = PromptDiagnosticsStore(max_items=2)
        composer = PromptComposer("off", diagnostics_store=store)
        first = composer.compose("1girl")
        second = composer.compose("1boy")
        third = composer.compose("landscape")

        self.assertEqual(len(store), 2)
        self.assertIsNone(store.get(first.diagnostic_id))
        self.assertEqual(
            tuple(item.diagnostic_id for item in store.list()),
            (third.diagnostic_id, second.diagnostic_id),
        )

    def test_store_remains_bounded_under_concurrent_writes(self) -> None:
        store = PromptDiagnosticsStore(max_items=16)
        composer = PromptComposer("off", diagnostics_store=store)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = tuple(
                executor.map(
                    lambda index: composer.compose(f"1girl, portrait {index}"),
                    range(100),
                )
            )

        self.assertEqual(len(results), 100)
        self.assertEqual(len({item.diagnostic_id for item in results}), 100)
        self.assertEqual(len(store), 16)


if __name__ == "__main__":
    unittest.main()
