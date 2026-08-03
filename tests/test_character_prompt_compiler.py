"""Tests for deterministic correction of LLM-generated character prompts."""

import unittest

from ..services.character_prompt_compiler import (
    CharacterPromptEvidence,
    appearance_override_categories,
    compile_character_prompt,
)
from ..services.character_swap import (
    FEATURE_EYE_COLOR,
    FEATURE_HAIR_COLOR,
    FEATURE_HAIR_STYLE,
)


class CharacterPromptCompilerTests(unittest.TestCase):
    def test_canonicalizes_firefly_and_removes_wrong_identity_traits(self) -> None:
        result = compile_character_prompt(
            (
                "1girl, solo, firefly (honkai star rail), long grey hair, "
                "blue eyes, school uniform, classroom"
            ),
            "firefly (honkai star rail), green eyes",
            (
                CharacterPromptEvidence(
                    query="《崩坏：星穹铁道》的流萤",
                    canonical_tag="firefly_(honkai:_star_rail)",
                    appearance_terms=("silver hair", "blue eyes", "long hair"),
                    appearance_source="danbooru_gallery",
                ),
            ),
            prompt_character_terms=(
                ("firefly (honkai star rail)", "firefly_(honkai:_star_rail)"),
            ),
            user_request="画《崩坏：星穹铁道》的流萤穿校服",
        )

        self.assertIn(r"firefly_\(honkai:_star_rail\)", result.prompt)
        self.assertIn("silver hair", result.prompt)
        self.assertIn("blue eyes", result.prompt)
        self.assertNotIn("long grey hair", result.prompt)
        self.assertNotIn("firefly (honkai star rail)", result.prompt)
        self.assertNotIn("green eyes", result.negative_prompt)

    def test_rio_prompt_drops_untrusted_hair_and_eye_guesses(self) -> None:
        result = compile_character_prompt(
            "1girl, solo, rio, white hair, blue eyes, twin braids, stage",
            "",
            (
                CharacterPromptEvidence(
                    query="碧蓝档案的调月莉音",
                    canonical_tag="rio_(blue_archive)",
                    appearance_terms=("black hair", "red eyes", "long hair", "halo"),
                    appearance_source="danbooru_gallery",
                ),
            ),
            prompt_character_terms=(("rio", "rio_(blue_archive)"),),
            user_request="画碧蓝档案的调月莉音在舞台上",
        )

        self.assertIn(r"rio_\(blue_archive\)", result.prompt)
        self.assertIn("black hair", result.prompt)
        self.assertIn("red eyes", result.prompt)
        self.assertNotIn("white hair", result.prompt)
        self.assertNotIn("blue eyes", result.prompt)
        self.assertNotIn("twin braids", result.prompt)

    def test_explicit_user_appearance_override_is_preserved(self) -> None:
        result = compile_character_prompt(
            "1girl, rio (blue archive), white hair, short hair, blue eyes, beach",
            "",
            (
                CharacterPromptEvidence(
                    query="调月莉音",
                    canonical_tag="rio_(blue_archive)",
                    appearance_terms=("black hair", "long hair", "red eyes"),
                ),
            ),
            prompt_character_terms=(("rio (blue archive)", "rio_(blue_archive)"),),
            user_request="把调月莉音改成白色短发和蓝色眼睛",
        )

        self.assertIn("white hair", result.prompt)
        self.assertIn("short hair", result.prompt)
        self.assertIn("blue eyes", result.prompt)
        self.assertNotIn("black hair", result.prompt)
        self.assertNotIn("long hair", result.prompt)
        self.assertNotIn("red eyes", result.prompt)
        self.assertEqual(
            set(result.override_categories),
            {FEATURE_HAIR_STYLE, FEATURE_HAIR_COLOR, FEATURE_EYE_COLOR},
        )

    def test_bunny_costume_hairband_is_not_deleted_as_character_appearance(self) -> None:
        result = compile_character_prompt(
            (
                "1girl, toki, playboy bunny, rabbit ear hairband, "
                "fake rabbit ears, rabbit ears, selfie"
            ),
            "",
            (CharacterPromptEvidence("toki", "toki_(blue_archive)"),),
            prompt_character_terms=(("toki", "toki_(blue_archive)"),),
            user_request="画兔女郎飞鸟马时（toki）自拍",
        )

        self.assertIn("rabbit ear hairband", result.prompt)
        self.assertIn("fake rabbit ears", result.prompt)
        self.assertNotIn(", rabbit ears,", f", {result.prompt},")

    def test_removes_wrong_copyright_and_keeps_verified_work(self) -> None:
        result = compile_character_prompt(
            "1girl, rio, nikke, blue archive, city",
            "",
            (CharacterPromptEvidence("rio", "rio_(blue_archive)"),),
            prompt_character_terms=(("rio", "rio_(blue_archive)"),),
            prompt_copyright_terms=(
                ("nikke", "nikke"),
                ("blue archive", "blue_archive"),
            ),
        )

        self.assertNotIn("nikke", result.prompt)
        self.assertIn("blue_archive", result.prompt)

    def test_drops_relation_sentence_that_repeats_removed_trait(self) -> None:
        result = compile_character_prompt(
            (
                "1girl, rio, white hair, beach, "
                "A white-haired girl stands beside the sea."
            ),
            "",
            (
                CharacterPromptEvidence(
                    "rio",
                    "rio_(blue_archive)",
                    appearance_terms=("black hair",),
                ),
            ),
            prompt_character_terms=(("rio", "rio_(blue_archive)"),),
        )

        self.assertNotIn("white-haired", result.prompt)
        self.assertIn("beach", result.prompt)

    def test_multiple_characters_only_canonicalizes_identity(self) -> None:
        result = compile_character_prompt(
            "2girls, rio, toki, black hair, white hair, classroom",
            "",
            (
                CharacterPromptEvidence("rio", "rio_(blue_archive)"),
                CharacterPromptEvidence("toki", "toki_(blue_archive)"),
            ),
            prompt_character_terms=(
                ("rio", "rio_(blue_archive)"),
                ("toki", "toki_(blue_archive)"),
            ),
        )

        self.assertIn(r"rio_\(blue_archive\)", result.prompt)
        self.assertIn(r"toki_\(blue_archive\)", result.prompt)
        self.assertIn("black hair", result.prompt)
        self.assertIn("white hair", result.prompt)

    def test_no_verified_character_leaves_prompt_unchanged(self) -> None:
        result = compile_character_prompt(
            "1girl, original character, green hair",
            "bad hands",
            (),
            user_request="画一个原创角色",
        )

        self.assertEqual(result.prompt, "1girl, original character, green hair")
        self.assertEqual(result.negative_prompt, "bad hands")

    def test_chinese_override_detection(self) -> None:
        categories = appearance_override_categories("改成白发双马尾和蓝色眼睛")

        self.assertEqual(
            set(categories),
            {FEATURE_HAIR_STYLE, FEATURE_HAIR_COLOR, FEATURE_EYE_COLOR},
        )


if __name__ == "__main__":
    unittest.main()
