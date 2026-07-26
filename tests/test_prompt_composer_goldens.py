"""Golden regression coverage for real Prompt Composer v2 prompt shapes."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from ..services.prompt_composer import PromptComposer, split_hybrid_prompt


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prompt_composer_goldens.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _compose(case: dict[str, Any]):
    composer = PromptComposer(**case["composer"])
    return composer.compose(**case["input"])


def _expected_positive(expected: dict[str, Any]) -> str:
    prefix = ", ".join(
        (
            *expected["lora_tags"],
            *expected["hard_tags"],
            *expected["visual_phrases"],
        )
    )
    scene = expected["scene_sentence"]
    if prefix and scene:
        return f"{prefix}. {scene}"
    return prefix or scene


class PromptComposerGoldenRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = _load_fixture()
        if fixture["schema_version"] != 1:
            raise AssertionError("unsupported prompt-composer golden schema")
        cls.cases = fixture["cases"]

    def test_fixture_is_local_redacted_and_has_unique_case_ids(self) -> None:
        raw = FIXTURE_PATH.read_text(encoding="utf-8")
        case_ids = [case["id"] for case in self.cases]

        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertNotRegex(raw, r"(?i)https?://|file://|sk-[a-z0-9_-]{8,}")
        self.assertNotRegex(raw, r"(?i)[a-z]:[\\/]|/(?:home|root|astrbot|comfyui)/")
        self.assertNotRegex(raw, r"(?i)api[_-]?key|authorization|bearer\s+")

    def test_golden_layers_and_final_prompt_are_exact(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = _compose(case)
                expected = case["expected"]

                self.assertEqual(result.layers.lora_tags, tuple(expected["lora_tags"]))
                self.assertEqual(result.layers.hard_tags, tuple(expected["hard_tags"]))
                self.assertEqual(
                    result.layers.visual_phrases,
                    tuple(expected["visual_phrases"]),
                )
                self.assertEqual(
                    result.layers.scene_sentence,
                    expected["scene_sentence"],
                )
                self.assertEqual(result.positive_prompt, _expected_positive(expected))
                self.assertEqual(result.negative_prompt, expected["negative_prompt"])
                self.assertEqual(
                    result.diagnostics.adaptive_negative_added,
                    tuple(expected["adaptive_negative_added"]),
                )

    def test_three_layer_cases_keep_hard_visual_and_scene_order(self) -> None:
        for case in self.cases:
            expected = case["expected"]
            if not expected.get("assert_three_layers"):
                continue
            with self.subTest(case=case["id"]):
                result = _compose(case)
                hard_layer = ", ".join((*expected["lora_tags"], *expected["hard_tags"]))
                visual_layer = ", ".join(expected["visual_phrases"])
                scene = expected["scene_sentence"]

                self.assertTrue(hard_layer)
                self.assertTrue(visual_layer)
                self.assertTrue(scene)
                self.assertLess(
                    result.positive_prompt.index(hard_layer),
                    result.positive_prompt.index(visual_layer),
                )
                self.assertLess(
                    result.positive_prompt.index(visual_layer),
                    result.positive_prompt.index(scene),
                )

    def test_scene_sentence_is_neither_duplicated_nor_extended(self) -> None:
        for case in self.cases:
            expected = case["expected"]
            if not expected.get("assert_single_scene"):
                continue
            with self.subTest(case=case["id"]):
                result = _compose(case)
                tag_block, scene = split_hybrid_prompt(result.positive_prompt)

                self.assertTrue(tag_block)
                self.assertEqual(scene, expected["scene_sentence"])
                self.assertEqual(result.positive_prompt.count(scene), 1)
                self.assertNotIn(". ", scene.rstrip("."))

    def test_masked_edit_and_raw_tags_do_not_gain_a_whole_image_sentence(self) -> None:
        for case in self.cases:
            expected = case["expected"]
            if not expected.get("assert_no_scene"):
                continue
            with self.subTest(case=case["id"]):
                result = _compose(case)
                _, scene = split_hybrid_prompt(result.positive_prompt)

                self.assertEqual(result.layers.scene_sentence, "")
                self.assertEqual(scene, "")

    def test_conservative_negatives_are_only_the_fixture_risks(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = _compose(case)
                expected = case["expected"]
                final_terms = tuple(
                    item.strip()
                    for item in result.negative_prompt.split(",")
                    if item.strip()
                )

                for forbidden in expected["forbidden_negative_tags"]:
                    self.assertNotIn(forbidden, final_terms)
                self.assertEqual(
                    result.diagnostics.adaptive_negative_added,
                    tuple(expected["adaptive_negative_added"]),
                )

    def test_custom_outfit_negative_is_preserved_without_generic_padding(self) -> None:
        case = next(
            item for item in self.cases if item["id"] == "custom_outfit_change_negative"
        )
        result = _compose(case)

        self.assertEqual(
            result.negative_prompt,
            case["input"]["negative_prompt"],
        )
        self.assertEqual(result.diagnostics.adaptive_negative_added, ())

    def test_raw_direct_tags_and_negative_are_unchanged(self) -> None:
        case = next(
            item for item in self.cases if item["expected"].get("assert_raw_unchanged")
        )
        result = _compose(case)

        self.assertEqual(result.positive_prompt, case["input"]["positive_prompt"])
        self.assertEqual(result.negative_prompt, case["input"]["negative_prompt"])

    def test_diagnostics_do_not_store_prompt_content_by_default(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                result = _compose(case)

                self.assertEqual(result.diagnostics.positive_prompt, "")
                self.assertEqual(result.diagnostics.negative_prompt, "")
                self.assertNotIn(
                    case["input"]["positive_prompt"],
                    json.dumps(result.diagnostics.to_dict(), ensure_ascii=False),
                )


if __name__ == "__main__":
    unittest.main()
