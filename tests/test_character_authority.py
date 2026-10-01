"""Character authority, purity and multi-character judge tests."""

import unittest

from ..services.character_authority import (
    CharacterAuthority,
    CharacterPurityFilter,
)
from ..services.multi_character_judge import (
    BLOCKED_DECISION,
    CLARIFY_DECISION,
    COSPLAY_DECISION,
    DUAL_DECISION,
    SINGLE_DECISION,
    MultiCharacterJudge,
)


class CharacterAuthorityTests(unittest.TestCase):
    def test_allowed_canonicals_excludes_empty(self) -> None:
        authority = CharacterAuthority(
            "denia_(wuthering_waves)",
            allowed_extra_characters=("", "shiroko_(blue_archive)"),
        )
        self.assertEqual(
            authority.allowed_canonicals(),
            ("denia_(wuthering_waves)", "shiroko_(blue_archive)"),
        )

    def test_to_dict_roundtrip_fields(self) -> None:
        authority = CharacterAuthority(
            "denia_(wuthering_waves)",
            cosplay_source="tsukiyo_(cosplay)",
        )
        payload = authority.to_dict()
        self.assertEqual(payload["cosplay_source"], "tsukiyo_(cosplay)")


class CharacterPurityFilterTests(unittest.TestCase):
    def test_forbidden_character_is_removed(self) -> None:
        authority = CharacterAuthority("denia_(wuthering_waves)")
        filt = CharacterPurityFilter(("tsukiyo_(blue_archive)",))
        result = filt.purify(
            "denia_(wuthering_waves), tsukiyo_(blue_archive), 1girl",
            authority,
        )
        self.assertNotIn("tsukiyo", result.prompt)
        self.assertEqual(result.removed_characters, ("tsukiyo_(blue_archive)",))

    def test_cosplay_source_is_not_removed(self) -> None:
        authority = CharacterAuthority(
            "denia_(wuthering_waves)",
            cosplay_source="tsukiyo_(blue_archive)_(cosplay)",
        )
        filt = CharacterPurityFilter(("tsukiyo_(blue_archive)",))
        result = filt.purify(
            "denia_(wuthering_waves), tsukiyo_(blue_archive)_(cosplay)",
            authority,
        )
        self.assertIn("cosplay", result.prompt)
        self.assertEqual(result.removed_characters, ())


class MultiCharacterJudgeTests(unittest.TestCase):
    def test_single_character_is_single(self) -> None:
        judge = MultiCharacterJudge()
        decision = judge.judge(
            "画达妮娅",
            detected_characters=("达妮娅",),
        )
        self.assertEqual(decision.decision, SINGLE_DECISION)

    def test_explicit_dual_opens_dual_contract(self) -> None:
        judge = MultiCharacterJudge()
        decision = judge.judge(
            "达妮娅和调月莉音同框",
            detected_characters=("达妮娅", "调月莉音"),
        )
        self.assertEqual(decision.decision, DUAL_DECISION)
        self.assertEqual(
            decision.authority.allowed_extra_characters,
            ("调月莉音",),
        )

    def test_ambiguous_a_and_b_clarifies(self) -> None:
        judge = MultiCharacterJudge()
        decision = judge.judge(
            "达妮娅和调月莉音",
            detected_characters=("达妮娅", "调月莉音"),
        )
        self.assertEqual(decision.decision, CLARIFY_DECISION)

    def test_cosplay_opens_cosplay_contract(self) -> None:
        judge = MultiCharacterJudge()
        decision = judge.judge(
            "达妮娅 cos 调月莉音",
            detected_characters=("达妮娅", "调月莉音"),
        )
        self.assertEqual(decision.decision, COSPLAY_DECISION)
        self.assertEqual(decision.authority.identity_anchor, "达妮娅")
        self.assertIn("cosplay", decision.authority.cosplay_source)

    def test_three_characters_are_blocked_until_confirmed(self) -> None:
        judge = MultiCharacterJudge()
        decision = judge.judge(
            "三个人同框",
            detected_characters=("A", "B", "C"),
        )
        self.assertEqual(decision.decision, BLOCKED_DECISION)


if __name__ == "__main__":
    unittest.main()
