"""Tests for the deterministic, side-effect-free Prompt Lab planner."""

from __future__ import annotations

import unittest

from ..services.prompt_composer import PromptComposer
from ..services.prompt_lab import (
    MAX_ASSETS_PER_POOL,
    PromptLab,
    PromptLabAsset,
    PromptLabError,
    confirm_prompt_candidate,
    generate_prompt_candidates,
)


def _all_visual_pools() -> dict[str, list[object]]:
    return {
        "character": [
            {"id": "alice", "tags": ["1girl", "alice_(wonderland)"]},
            {"id": "roxy", "tags": ["1girl", "roxy_migurdia"]},
        ],
        "outfit": ["white dress", "black jacket"],
        "pose": ["standing", "sitting"],
        "background": ["beach", "library"],
        "artist": ["artist:alpha", "artist:beta"],
    }


class PromptLabDeterminismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lab = PromptLab()

    def test_same_seed_and_inputs_return_identical_batch(self) -> None:
        kwargs = {
            "seed": 104729,
            "count": 6,
            "base_layers": {"camera": "from below"},
            "asset_pools": _all_visual_pools(),
        }

        first = self.lab.generate_candidates(**kwargs)
        second = self.lab.generate_candidates(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(len(first.candidates), 6)

    def test_string_seed_is_stable_and_kept_distinct_from_integer_seed(self) -> None:
        text_seed = self.lab.generate(seed="42", count=2, asset_pools=_all_visual_pools())
        same = self.lab.generate(seed="42", count=2, asset_pools=_all_visual_pools())
        integer_seed = self.lab.generate(seed=42, count=2, asset_pools=_all_visual_pools())

        self.assertEqual(text_seed, same)
        self.assertNotEqual(text_seed.seed_value, integer_seed.seed_value)

    def test_candidate_count_is_strictly_bounded_from_one_to_six(self) -> None:
        self.assertEqual(
            len(self.lab.generate(seed=1, count=1).candidates),
            1,
        )
        self.assertEqual(
            len(self.lab.generate(seed=1, count=6).candidates),
            6,
        )
        for invalid in (0, 7, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(PromptLabError):
                self.lab.generate(seed=1, count=invalid)  # type: ignore[arg-type]

    def test_small_variation_space_is_reported_without_changing_count(self) -> None:
        batch = self.lab.generate(seed=9, count=4, locked_layers=("identity",))

        self.assertEqual(len(batch.candidates), 4)
        self.assertTrue(
            any("variation space has 1" in warning for warning in batch.warnings)
        )


class PromptLabAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lab = PromptLab()

    def test_all_five_visual_asset_types_are_sampled(self) -> None:
        batch = self.lab.generate(
            seed=123,
            count=3,
            asset_pools=_all_visual_pools(),
        )

        self.assertEqual(
            batch.enabled_asset_types,
            ("character", "outfit", "pose", "background", "artist"),
        )
        for candidate in batch.candidates:
            self.assertEqual(len(candidate.selected_assets), 5)
            self.assertTrue(candidate.layers.identity)
            self.assertTrue(candidate.layers.clothing)
            self.assertTrue(candidate.layers.pose)
            self.assertTrue(candidate.layers.background)
            self.assertTrue(candidate.layers.style)

    def test_alias_pool_names_are_normalized(self) -> None:
        batch = self.lab.generate(
            seed=11,
            count=1,
            asset_pools={
                "characters": ["heroine"],
                "costumes": ["summer dress"],
                "environment": ["garden"],
                "artists": ["artist:example"],
            },
        )
        layers = batch.candidates[0].layers

        self.assertEqual(layers.identity, ("heroine",))
        self.assertEqual(layers.clothing, ("summer dress",))
        self.assertEqual(layers.background, ("garden",))
        self.assertEqual(layers.style, ("artist:example",))

    def test_enabled_asset_types_can_select_only_part_of_the_pools(self) -> None:
        batch = self.lab.generate(
            seed=7,
            count=1,
            base_layers={"identity": "base heroine", "style": "base style"},
            asset_pools={
                "character": ["new heroine"],
                "artist": ["new style"],
            },
            enabled_asset_types=("character",),
        )
        candidate = batch.candidates[0]

        self.assertEqual(candidate.layers.identity, ("new heroine",))
        self.assertEqual(candidate.layers.style, ("base style",))
        self.assertEqual(candidate.selected_assets[0][0], "identity")

    def test_mapping_asset_can_add_visual_phrase_relation_and_lora(self) -> None:
        batch = self.lab.generate(
            seed=4,
            count=1,
            asset_pools={
                "artist": [
                    {
                        "id": "warm-film",
                        "tags": ["cinematic lighting"],
                        "visual_phrases": ["warm rim light across her face"],
                        "relation": "She watches the sunset beside the sea.",
                        "lora_tags": ["<lora:warm-film:0.45>"],
                    }
                ]
            },
        )
        candidate = batch.candidates[0]

        self.assertEqual(candidate.layers.style, ("cinematic lighting",))
        self.assertEqual(candidate.layers.lora, ("<lora:warm-film:0.45>",))
        self.assertEqual(
            candidate.visual_phrases,
            ("warm rim light across her face",),
        )
        self.assertEqual(
            candidate.layers.relation,
            "She watches the sunset beside the sea.",
        )

    def test_advanced_relation_and_lora_pools_are_supported(self) -> None:
        batch = self.lab.generate(
            seed=8,
            count=1,
            asset_pools={
                "scene": ["She reads quietly beside a rain-streaked window."],
                "loras": ["<lora:detail:0.30>"],
            },
        )
        candidate = batch.candidates[0]

        self.assertEqual(
            candidate.layers.relation,
            "She reads quietly beside a rain-streaked window.",
        )
        self.assertEqual(candidate.layers.lora, ("<lora:detail:0.30>",))
        self.assertEqual(
            {layer for layer, _asset_id in candidate.selected_assets},
            {"relation", "lora"},
        )

    def test_prompt_lab_asset_instances_are_accepted(self) -> None:
        asset = PromptLabAsset(
            asset_id="hand-authored",
            label="Hand authored",
            tags=("kneeling",),
        )
        batch = self.lab.generate(
            seed=3,
            count=1,
            asset_pools={"pose": [asset]},
        )

        self.assertEqual(batch.candidates[0].layers.pose, ("kneeling",))
        self.assertEqual(
            batch.candidates[0].selected_assets,
            (("pose", "hand-authored"),),
        )


class PromptLabLockAndValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lab = PromptLab()

    def test_locked_layer_preserves_base_and_ignores_its_pool(self) -> None:
        batch = self.lab.generate(
            seed=5,
            count=2,
            base_layers={"identity": "locked heroine"},
            asset_pools={"character": ["other heroine", "third heroine"]},
            locked_layers=("character",),
        )

        self.assertEqual(batch.locked_layers, ("identity",))
        self.assertTrue(any("locked layer: identity" in item for item in batch.warnings))
        for candidate in batch.candidates:
            self.assertEqual(candidate.layers.identity, ("locked heroine",))
            self.assertEqual(candidate.selected_assets, ())

    def test_unlocked_layer_is_replaced_by_a_pool_choice(self) -> None:
        batch = self.lab.generate(
            seed=5,
            count=1,
            base_layers={"clothing": "base uniform"},
            asset_pools={"outfit": ["evening dress"]},
        )

        self.assertEqual(batch.candidates[0].layers.clothing, ("evening dress",))
        self.assertNotIn("base uniform", batch.candidates[0].layers.clothing)

    def test_exact_duplicates_are_removed_across_layers(self) -> None:
        batch = self.lab.generate(
            seed=6,
            count=1,
            base_layers={"identity": ["1girl", "blue hair"]},
            asset_pools={
                "outfit": [{"id": "dress", "tags": ["blue hair", "white dress"]}]
            },
        )
        candidate = batch.candidates[0]

        self.assertEqual(candidate.layers.identity, ("1girl", "blue hair"))
        self.assertEqual(candidate.layers.clothing, ("white dress",))
        self.assertIn("blue hair", candidate.duplicates_removed)

    def test_sampled_conflict_loses_to_a_locked_layer(self) -> None:
        batch = self.lab.generate(
            seed=12,
            count=1,
            base_layers={"background": "night"},
            asset_pools={"camera": ["day"]},
            locked_layers=("background",),
        )
        candidate = batch.candidates[0]

        self.assertEqual(candidate.layers.background, ("night",))
        self.assertEqual(candidate.layers.camera, ())
        self.assertEqual(candidate.discarded_terms, ("day",))
        self.assertTrue(candidate.conflicts_resolved)

    def test_conflicting_base_facts_are_rejected(self) -> None:
        with self.assertRaisesRegex(PromptLabError, "base layers contain conflicts"):
            self.lab.generate(
                seed=1,
                base_layers={"background": ["day", "night"]},
            )

    def test_invalid_lora_control_is_rejected(self) -> None:
        with self.assertRaisesRegex(PromptLabError, "invalid LoRA"):
            self.lab.generate(
                seed=1,
                asset_pools={"lora": ["not-a-lora-control"]},
            )

    def test_asset_pool_capacity_is_bounded(self) -> None:
        with self.assertRaisesRegex(PromptLabError, "exceeds"):
            self.lab.generate(
                seed=1,
                asset_pools={
                    "pose": [f"pose {index}" for index in range(MAX_ASSETS_PER_POOL + 1)]
                },
            )

    def test_term_and_negative_lengths_are_bounded(self) -> None:
        with self.assertRaisesRegex(PromptLabError, "characters"):
            self.lab.generate(
                seed=1,
                asset_pools={"pose": ["x" * 513]},
            )
        with self.assertRaisesRegex(PromptLabError, "negative_prompt"):
            self.lab.generate(seed=1, negative_prompt="x" * 8193)

    def test_duplicate_asset_id_with_different_content_is_rejected(self) -> None:
        with self.assertRaisesRegex(PromptLabError, "reuses id"):
            self.lab.generate(
                seed=1,
                asset_pools={
                    "pose": [
                        {"id": "same", "tags": "standing"},
                        {"id": "same", "tags": "sitting"},
                    ]
                },
            )


class PromptLabConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lab = PromptLab()

    def test_confirm_returns_strict_prompt_composer_arguments(self) -> None:
        batch = self.lab.generate(
            seed=99,
            count=2,
            base_layers={
                "identity": ["1girl", "roxy_migurdia"],
                "camera": "full body",
                "relation": "She watches the sparks above the moonlit sea.",
                "lora": "<lora:roxy:0.80>",
            },
            asset_pools={"outfit": ["white bikini", "blue dress"]},
            locked_layers=("identity", "camera", "relation", "lora"),
            negative_prompt="lowres",
            visual_phrases=("soft amber light",),
        )
        draft = self.lab.confirm_candidate(batch, 1)
        kwargs = draft.to_composer_kwargs()

        self.assertEqual(
            set(kwargs),
            {
                "positive_prompt",
                "negative_prompt",
                "hard_tags",
                "visual_phrases",
                "scene_sentence",
                "anchors",
                "source",
            },
        )
        self.assertIn(("roxy_migurdia", "character"), draft.anchors)
        self.assertIn(("<lora:roxy:0.80>", "lora"), draft.anchors)
        self.assertTrue(set(draft.hard_tags) & {"white bikini", "blue dress"})

        composed = PromptComposer("off").compose(**kwargs)
        self.assertIn("<lora:roxy:0.80>", composed.layers.lora_tags)
        self.assertIn("roxy_migurdia", composed.layers.hard_tags)
        self.assertEqual(composed.layers.scene_sentence, draft.scene_sentence)
        self.assertEqual(composed.negative_prompt, "lowres")

    def test_candidate_can_be_selected_by_id_or_numeric_text(self) -> None:
        batch = self.lab.generate(
            seed=15,
            count=2,
            asset_pools={"pose": ["standing", "sitting"]},
        )
        by_id = self.lab.confirm(batch, batch.candidates[1].candidate_id)
        by_number = self.lab.confirm(batch, "2")

        self.assertEqual(by_id, by_number)
        with self.assertRaises(PromptLabError):
            self.lab.confirm(batch, 3)

    def test_convenience_functions_are_side_effect_free_round_trip(self) -> None:
        batch = generate_prompt_candidates(
            seed="workbench",
            count=1,
            asset_pools={"background": ["workshop"]},
        )
        draft = confirm_prompt_candidate(batch, 1)

        self.assertEqual(draft.source, "prompt_lab")
        self.assertEqual(draft.hard_tags, ("workshop",))
        self.assertEqual(draft.positive_prompt, "")


if __name__ == "__main__":
    unittest.main()
