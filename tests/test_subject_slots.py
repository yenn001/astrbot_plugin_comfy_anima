from __future__ import annotations

import unittest

from ..services.subject_slots import (
    ObservedSubject,
    SubjectSelectionError,
    analyze_prompt_subject_selection,
    select_observed_subject,
)


class SubjectSlotSelectionTests(unittest.TestCase):
    def test_hair_color_selector_protects_other_subject_color(self) -> None:
        result = analyze_prompt_subject_selection(
            ("2girls", "yellow hair", "red hair", "school uniform"),
            "把黄色头发的角色",
        )

        self.assertTrue(result.multi_subject)
        self.assertEqual(result.subject_count, 2)
        self.assertEqual(result.basis, "unique_hair_color")
        self.assertEqual(result.matched_terms, ("yellow hair",))
        self.assertEqual(result.protected_terms, ("red hair",))

    def test_same_feature_requires_natural_direction_fallback(self) -> None:
        with self.assertRaises(SubjectSelectionError) as raised:
            analyze_prompt_subject_selection(
                ("2girls", "yellow hair", "school uniform"),
                "黄色头发的角色",
            )

        self.assertEqual(raised.exception.code, "source_selector_ambiguous")

        result = analyze_prompt_subject_selection(
            ("2girls", "yellow hair", "left", "right"),
            "左边的黄色头发角色",
        )
        self.assertEqual(result.basis, "natural_direction_fallback")
        self.assertTrue(result.direction_used)
        self.assertIn("left", result.matched_terms)

    def test_unique_gender_is_recognized_without_short_option(self) -> None:
        result = analyze_prompt_subject_selection(
            ("1girl", "1boy", "outdoors"),
            "把男生换成目标角色",
        )

        self.assertEqual(result.basis, "unique_gender")
        self.assertEqual(result.subject_count, 2)

    def test_reverse_observation_matches_chinese_selector_to_english_tag(self) -> None:
        selected, result = select_observed_subject(
            (
                ObservedSubject(
                    appearance_tags=("yellow hair",),
                    outfit_tags=("white dress",),
                    position="left",
                ),
                ObservedSubject(
                    appearance_tags=("red hair",),
                    outfit_tags=("school uniform",),
                    position="right",
                ),
            ),
            "黄色头发的角色",
        )

        self.assertEqual(selected, 0)
        self.assertEqual(result.matched_terms, ("yellow hair",))
        self.assertIn("red hair", result.protected_terms)


if __name__ == "__main__":
    unittest.main()
