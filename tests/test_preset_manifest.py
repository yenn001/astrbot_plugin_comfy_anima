"""Tests for preset manifest construction and submission gates."""

import unittest

from ..services.preset_manifest import (
    LoraManifestEntry,
    PresetManifest,
    PresetManifestError,
    assert_manifests_equal,
    assert_preset_invariants,
)


def _manifest(negative: tuple[str, ...]) -> PresetManifest:
    return PresetManifest.build(
        preset_name="达妮娅预设",
        positive_terms=("daniya_(wuwa)", "smile", "outdoors"),
        negative_terms=negative,
        lora_entries=(
            {"name": "daniya.safetensors", "weight": 0.8, "model_family": "legacy-28-layer"},
        ),
        model_family="legacy-28-layer",
        identity_anchor="daniya_(wuwa)",
        required_triggers=("daniya",),
    )


class PresetManifestTests(unittest.TestCase):
    def test_runtime_family_filename_matches_family_neutral_preset_name(self) -> None:
        expected = PresetManifest.build(
            lora_entries=[{"name": "anima-000040", "weight": 0.9}]
        )
        actual = PresetManifest.build(
            lora_entries=[
                {"name": "29B/anima-000040_29b.safetensors", "weight": 0.9}
            ]
        )
        self.assertEqual(expected.lora_keys(), actual.lora_keys())
        assert_preset_invariants(expected, actual)
    def test_stable_hash(self) -> None:
        first = _manifest(("lowres", "bad anatomy"))
        second = _manifest(("lowres", "bad anatomy"))
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        self.assertTrue(first.matches(second))

    def test_matches_ignores_stored_hash(self) -> None:
        first = _manifest(("lowres",))
        second = _manifest(("lowres",))
        object.__setattr__(second, "manifest_hash", "forged")
        self.assertTrue(first.matches(second))

    def test_negative_pool_mismatch_blocks(self) -> None:
        expected = _manifest(("lowres", "bad anatomy"))
        actual = _manifest(())
        with self.assertRaises(PresetManifestError):
            assert_manifests_equal(expected, actual)

    def test_lora_stack_mismatch_blocks(self) -> None:
        expected = _manifest(("lowres",))
        actual = PresetManifest.build(
            preset_name="达妮娅预设",
            positive_terms=("daniya_(wuwa)", "smile", "outdoors"),
            negative_terms=("lowres",),
            lora_entries=(),
            model_family="legacy-28-layer",
            identity_anchor="daniya_(wuwa)",
            required_triggers=("daniya",),
        )
        with self.assertRaises(PresetManifestError):
            assert_manifests_equal(expected, actual)

    def test_model_family_mismatch_blocks(self) -> None:
        expected = _manifest(("lowres",))
        actual = _manifest(("lowres",))
        object.__setattr__(actual, "model_family", "2.9B-40-layer")
        with self.assertRaises(PresetManifestError):
            assert_manifests_equal(expected, actual)

    def test_requires_negative_pool(self) -> None:
        self.assertTrue(_manifest(("lowres",)).requires_negative_pool())
        self.assertFalse(_manifest(()).requires_negative_pool())



class RecipeWeightDriftGateTests(unittest.TestCase):
    """3.1.436：闸门 LoRA 存在性按 (name, family) 匹配，权重漂移仅警告。"""

    def _manifest(self, weights):
        entries = tuple(
            LoraManifestEntry(name=name, weight=weight)
            for name, weight in weights
        )
        return PresetManifest.build(
            preset_name="conversation_pic",
            lora_entries=entries,
        )

    def test_weight_drift_no_longer_fails_gate(self) -> None:
        expected = self._manifest([("real skin.baka.v1-000010", 0.25)])
        actual = self._manifest([("real skin.baka.v1-000010", 0.66)])
        assert_preset_invariants(expected, actual)  # 不 raise 即通过

    def test_missing_entry_still_fails(self) -> None:
        expected = self._manifest([("real skin.baka.v1-000010", 0.25)])
        actual = self._manifest([])
        with self.assertRaises(PresetManifestError) as ctx:
            assert_preset_invariants(expected, actual)
        self.assertIn("missing LoRA stack entries", str(ctx.exception))

    def test_same_name_different_family_still_fails(self) -> None:
        expected = PresetManifest.build(
            preset_name="p",
            lora_entries=(LoraManifestEntry(name="denia", weight=0.8),),
        )
        actual = PresetManifest.build(
            preset_name="p",
            lora_entries=(
                LoraManifestEntry(
                    name="denia", weight=0.8, model_family="anima_legacy_28l"
                ),
            ),
        )
        with self.assertRaises(PresetManifestError):
            assert_preset_invariants(expected, actual)

    def test_family_agnostic_match_across_suffixes(self) -> None:
        expected = self._manifest([("anima-000040", 0.8)])
        actual = PresetManifest.build(
            preset_name="p",
            lora_entries=(
                LoraManifestEntry(name="29B/anima-000040_29b", weight=0.8),
            ),
        )
        assert_preset_invariants(expected, actual)



if __name__ == "__main__":
    unittest.main()
