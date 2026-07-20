"""Semantic whole-image redraw invariants."""

import unittest

from ..services.semantic_edit import (
    build_semantic_edit_contract,
    classify_edit_magnitude,
    semantic_redraw_parameters,
)


class SemanticEditContractTests(unittest.TestCase):
    def test_outfit_replacement_requires_targets_and_removes_source_outfit(self) -> None:
        contract = build_semantic_edit_contract(
            "把泳装换成三点式，然后再加白丝大腿袜，构图不变",
            "1girl, blue one-piece swimsuit, bare legs, sitting, full body, beach",
        )

        self.assertEqual(contract.magnitude, "major")
        self.assertEqual(
            {item.code for item in contract.required_positive},
            {"bikini", "white_thighhighs"},
        )
        self.assertIn("blue one piece swimsuit", contract.removed_source_terms)
        self.assertIn("bare legs", contract.removed_source_terms)
        self.assertIn("sitting", contract.preserved_source_terms)
        self.assertIn("full body", contract.preserved_source_terms)
        self.assertEqual(
            contract.validate(
                "1girl, string bikini, white thigh-high stockings, sitting, full body, beach"
            ),
            (),
        )
        self.assertIn(
            "retained_source_outfit",
            contract.validate(
                "1girl, blue one-piece swimsuit, string bikini, white thighhighs, sitting, full body"
            ),
        )
        self.assertIn(
            "missing:white_thighhighs",
            contract.validate("1girl, string bikini, sitting, full body"),
        )
        self.assertIn(
            "missing_preserved_composition",
            contract.validate("1girl, string bikini, white thighhighs"),
        )

    def test_major_floor_applies_but_explicit_values_win(self) -> None:
        self.assertEqual(
            semantic_redraw_parameters(
                "把泳装换成三点式",
                "preserve",
                explicit_denoise=None,
                explicit_steps=None,
            ),
            (0.64, 16, "major"),
        )
        self.assertEqual(
            semantic_redraw_parameters(
                "把泳装换成三点式",
                "preserve",
                explicit_denoise=0.38,
                explicit_steps=9,
            ),
            (0.38, 9, "major"),
        )

    def test_magnitude_levels(self) -> None:
        self.assertEqual(classify_edit_magnitude("加上一双白色靴子"), "moderate")
        self.assertEqual(classify_edit_magnitude("稍微调整一下颜色和细节"), "minor")
        self.assertEqual(classify_edit_magnitude("画得更好看"), "unknown")


if __name__ == "__main__":
    unittest.main()
