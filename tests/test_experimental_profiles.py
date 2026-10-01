"""Tests for the opt-in experimental ComfyUI capability registry."""

import unittest

from ..services.experimental_profiles import (
    EXPERIMENTAL_PROFILES,
    evaluate_experimental_profile,
    inspect_experimental_profiles,
    list_experimental_profiles,
)


def _object_info(*node_types: str, schedulers: tuple[str, ...] = ()) -> dict:
    payload = {node_type: {} for node_type in node_types}
    if schedulers:
        payload.setdefault("FLS_SamplerV4", {})["input"] = {
            "required": {"scheduler": [list(schedulers), {}]}
        }
    return payload


class ExperimentalProfileTests(unittest.TestCase):
    def test_registry_is_read_only_and_has_expected_contracts(self) -> None:
        self.assertEqual(
            tuple(EXPERIMENTAL_PROFILES),
            ("artist_mixer", "quality_stack", "layer_replay"),
        )
        with self.assertRaises(TypeError):
            EXPERIMENTAL_PROFILES["new_profile"] = list_experimental_profiles()[0]

        quality = EXPERIMENTAL_PROFILES["quality_stack"]
        self.assertEqual(
            quality.required_node_types,
            ("AnimaBoosterLoader", "FLS_SamplerV4", "AnimaTeaCache"),
        )
        self.assertNotIn("RES4LYF", quality.required_node_types)

    def test_artist_mixer_requires_all_three_real_node_types(self) -> None:
        result = evaluate_experimental_profile(
            "artist_mixer",
            _object_info("AnimaArtistPack", "AnimaArtistCrossAttn"),
            workflow_available=True,
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_nodes"], ["AnimaArtistOptions"])

    def test_complete_nodes_and_reviewed_workflow_are_ready(self) -> None:
        result = evaluate_experimental_profile(
            "artist_mixer",
            _object_info(
                "AnimaArtistPack",
                "AnimaArtistOptions",
                "AnimaArtistCrossAttn",
            ),
            workflow_available=True,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["missing_nodes"], [])

    def test_nodes_alone_never_activate_profile_without_workflow(self) -> None:
        result = evaluate_experimental_profile(
            "layer_replay",
            _object_info("AnimaLayerReplayPatcher"),
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_nodes"], [])
        self.assertTrue(
            any("activation is blocked" in note for note in result["notes"])
        )

    def test_beta57_is_optional_and_reported_when_available(self) -> None:
        result = evaluate_experimental_profile(
            "quality_stack",
            _object_info(
                "AnimaBoosterLoader",
                "FLS_SamplerV4",
                "AnimaTeaCache",
                schedulers=("simple", "beta57"),
            ),
            workflow_available=True,
        )
        self.assertTrue(result["ready"])
        self.assertTrue(any("beta57 is advertised" in note for note in result["notes"]))

    def test_missing_beta57_does_not_make_quality_stack_unready(self) -> None:
        result = evaluate_experimental_profile(
            "quality_stack",
            _object_info(
                "AnimaBoosterLoader",
                "FLS_SamplerV4",
                "AnimaTeaCache",
                schedulers=("beta", "ddim_uniform"),
            ),
            workflow_available=True,
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["missing_nodes"], [])
        self.assertTrue(
            any("does not gate readiness" in note for note in result["notes"])
        )

    def test_free_form_beta57_text_is_not_mistaken_for_enum_support(self) -> None:
        object_info = _object_info(
            "AnimaBoosterLoader",
            "FLS_SamplerV4",
            "AnimaTeaCache",
        )
        object_info["UnrelatedNode"] = {"description": "mentions beta57"}
        result = evaluate_experimental_profile(
            "quality_stack",
            object_info,
            workflow_available=True,
        )
        self.assertTrue(result["ready"])
        self.assertTrue(
            any("could not be verified" in note for note in result["notes"])
        )

    def test_invalid_object_info_is_safe_and_reports_missing_nodes(self) -> None:
        result = evaluate_experimental_profile(
            "layer_replay",
            ["AnimaLayerReplayPatcher"],
            workflow_available=True,
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["missing_nodes"], ["AnimaLayerReplayPatcher"])

    def test_batch_inspection_defaults_to_blocked_and_accepts_per_profile_gate(
        self,
    ) -> None:
        object_info = _object_info(
            "AnimaArtistPack",
            "AnimaArtistOptions",
            "AnimaArtistCrossAttn",
            "AnimaBoosterLoader",
            "FLS_SamplerV4",
            "AnimaTeaCache",
            "AnimaLayerReplayPatcher",
        )
        blocked = inspect_experimental_profiles(object_info)
        self.assertTrue(all(not result["ready"] for result in blocked))

        selective = inspect_experimental_profiles(
            object_info,
            workflow_availability={"layer_replay": True},
        )
        by_id = {result["id"]: result for result in selective}
        self.assertTrue(by_id["layer_replay"]["ready"])
        self.assertFalse(by_id["artist_mixer"]["ready"])
        self.assertFalse(by_id["quality_stack"]["ready"])


if __name__ == "__main__":
    unittest.main()
