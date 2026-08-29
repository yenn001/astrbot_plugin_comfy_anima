"""Double-manifest merge tests for saved LoRA stacks."""

import unittest

from ..services.preset_manifest import (
    PresetManifestError,
    merge_preset_manifests,
)


class PresetManifestMergeTests(unittest.TestCase):
    def test_recipe_only_entries_survive(self) -> None:
        merged = merge_preset_manifests(
            recipe_entries=[{"name": "denia_lorav4", "weight": 0.9}],
            preset_entries=[],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].name, "denia_lorav4")
        self.assertEqual(merged[0].weight, 0.9)
        self.assertEqual(merged[0].source, "recipe")

    def test_preset_conflict_fails_closed(self) -> None:
        with self.assertRaises(PresetManifestError):
            merge_preset_manifests(
                recipe_entries=[{"name": "denia_lorav4", "weight": 0.9}],
                preset_entries=[{"name": "denia_lorav4", "weight": 0.4}],
            )

    def test_no_saved_style_weight_is_dropped(self) -> None:
        merged = merge_preset_manifests(
            recipe_entries=[
                {"name": "denia_lorav4", "weight": 0.9},
                {"name": "(画质)anima-highres-aesthetic-boost", "weight": 0.4},
                {"name": "(美感细节)anima-rl-v0.1", "weight": 0.45},
            ],
            preset_entries=[
                {"name": "(画质)anima-highres-aesthetic-boost", "weight": 0.4},
                {"name": "(美感细节)anima-rl-v0.1", "weight": 0.45},
            ],
        )
        names = [slot.name for slot in merged]
        self.assertIn("denia_lorav4", names)
        self.assertIn("(画质)anima-highres-aesthetic-boost", names)
        self.assertIn("(美感细节)anima-rl-v0.1", names)
        self.assertEqual(len(names), 3)
        self.assertEqual(len({slot.name for slot in merged}), 3)

    def test_duplicate_normalized_name_fails_closed(self) -> None:
        with self.assertRaises(PresetManifestError):
            merge_preset_manifests(
                recipe_entries=[{"name": "denia_lorav4", "weight": 0.9}],
                preset_entries=[{"name": "DENIA_LORAV4", "weight": 0.5}],
            )

    def test_duplicate_preset_entry_fails_loud(self) -> None:
        with self.assertRaises(PresetManifestError):
            merge_preset_manifests(
                recipe_entries=[],
                preset_entries=[
                    {"name": "denia_lorav4", "weight": 0.5},
                    {"name": "denia_lorav4", "weight": 0.7},
                ],
            )

    def test_unsupported_entry_fails_loud(self) -> None:
        with self.assertRaises(PresetManifestError):
            merge_preset_manifests(recipe_entries=["plain string"], preset_entries=[])


if __name__ == "__main__":
    unittest.main()
