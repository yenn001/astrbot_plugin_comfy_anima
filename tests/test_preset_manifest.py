"""Tests for preset manifest construction and submission gates."""

import unittest

from ..services.preset_manifest import (
    PresetManifest,
    PresetManifestError,
    assert_manifests_equal,
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


if __name__ == "__main__":
    unittest.main()
