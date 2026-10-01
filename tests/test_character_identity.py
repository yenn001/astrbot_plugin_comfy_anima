from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ..services.character_identity import (
    character_identity_lookup_candidates,
    resolve_character_identity,
    resolve_user_adjacent_character_alias,
)
from ..services.danbooru_index import DanbooruTagIndex


class CharacterIdentityResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.index = DanbooruTagIndex(Path(self.directory.name) / "tags.sqlite3")
        payload = {
            "source": "unit fixture",
            "license": "fixture-only",
            "revision": "characters-r1",
            "tags": [
                {
                    "tag": "toki_(blue_archive)",
                    "category": "character",
                    "aliases": ["asuma_toki"],
                    "count": 10652,
                },
                {
                    "tag": "toki_(bunny)_(blue_archive)",
                    "category": "character",
                    "aliases": ["asuma_toki_(bunny)"],
                    "count": 5539,
                },
                {
                    "tag": "rio_(blue_archive)",
                    "category": "character",
                    "aliases": ["tsukatsuki_rio"],
                    "count": 12095,
                },
                {
                    "tag": "jinhsi_(wuthering_waves)",
                    "category": "character",
                    "aliases": ["jinxi_(wuthering_waves)"],
                    "count": 8300,
                },
                {
                    "tag": "firefly_(honkai:_star_rail)",
                    "category": "character",
                    "aliases": [],
                    "count": 28000,
                },
                {
                    "tag": "hatsune_miku",
                    "category": "character",
                    "aliases": ["miku_hatsune"],
                    "count": 180000,
                },
                {
                    "tag": "remielle_dan",
                    "category": "character",
                    "aliases": [],
                    "count": 1600,
                },
                {
                    "tag": "remielle_dan_(past)",
                    "category": "character",
                    "aliases": [],
                    "count": 300,
                },
                {
                    "tag": "remielle_dan_(dreamland_fest)",
                    "category": "character",
                    "aliases": [],
                    "count": 200,
                },
                {
                    "tag": "vocaloid",
                    "category": "copyright",
                    "aliases": [],
                    "count": 900000,
                },
                {
                    "tag": "blue_archive",
                    "category": "copyright",
                    "aliases": [],
                    "count": 500000,
                },
                {
                    "tag": "honkai:_star_rail",
                    "category": "copyright",
                    "aliases": [],
                    "count": 250000,
                },
                {
                    "tag": "genshin_impact",
                    "category": "copyright",
                    "aliases": [],
                    "count": 500000,
                },
                {
                    "tag": "zenless_zone_zero",
                    "category": "copyright",
                    "aliases": [],
                    "count": 500000,
                },
                {
                    "tag": "toki_style",
                    "category": "artist",
                    "aliases": ["wrong_category_toki"],
                    "count": 99999,
                },
            ],
        }
        self.index.import_bytes(json.dumps(payload).encode(), content_type="json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_provider_canonical_variant_resolves_unique_base_alias(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="碧蓝档案里的飞鸟马时",
            canonical_tag="asuma_toki_(blue_archive)",
        )

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "alias_without_work")
        self.assertEqual(result.match_type, "alias")

    def test_costume_variant_does_not_collapse_to_base_character(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="碧蓝档案兔女郎飞鸟马时",
            canonical_tag="asuma_toki_(bunny)_(blue_archive)",
        )

        self.assertTrue(result.verified)
        self.assertEqual(
            result.canonical_tag,
            "toki_(bunny)_(blue_archive)",
        )
        self.assertEqual(result.match_variant, "alias_without_work")

    def test_wrong_work_cannot_borrow_an_alias_from_another_work(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="错误作品的飞鸟马时",
            canonical_tag="asuma_toki_(wrong_work)",
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)

    def test_ascii_user_alias_can_resolve_before_provider_call(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="飞鸟马时/Asuma Toki",
            work_hints=("blue_archive",),
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "user_ascii_exact")

    def test_provider_identity_candidates_are_batch_exact_checked(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="蔚蓝档案飞鸟马时",
            canonical_tag="asuma_toki_(blue_archive)",
            identity_candidates=("asuma_toki", "toki"),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")

    def test_qualifierless_character_keeps_copyright_exact_work_separate(
        self,
    ) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Hatsune Miku",
            identity_candidates=("hatsune_miku",),
            work_hints=("vocaloid",),
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "hatsune_miku")
        self.assertEqual(result.confirmed_work, "vocaloid")
        self.assertEqual(result.match_variant, "provider_candidate_exact")

    def test_qualifierless_base_wins_over_same_identity_event_variants(
        self,
    ) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Remielle Dan",
            canonical_tag="remielle_dan",
            identity_candidates=(
                "remielle_dan",
                "remielle_dan_(past)",
                "remielle_dan_(dreamland_fest)",
            ),
            work_hints=("zenless_zone_zero",),
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "remielle_dan")
        self.assertEqual(result.confirmed_work, "zenless_zone_zero")
        self.assertEqual(
            result.match_variant,
            "same_identity_variant_base_exact",
        )
        self.assertEqual(result.candidate_count, 3)

    def test_explicit_qualifierless_event_variant_remains_selectable(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Remielle Dan past",
            canonical_tag="remielle_dan_(past)",
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "remielle_dan_(past)")

    def test_qualifierless_character_rejects_unverified_work_hint(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Hatsune Miku",
            identity_candidates=("hatsune_miku",),
            work_hints=("not_a_real_work",),
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.confirmed_work, "")

    def test_qualifierless_character_rejects_multiple_exact_work_hints(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Hatsune Miku",
            canonical_tag="hatsune_miku",
            work_hints=("vocaloid", "blue_archive"),
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.match_variant, "copyright_exact_conflict")
        self.assertEqual(
            set(result.conflicting_works),
            {"vocaloid", "blue_archive"},
        )

    def test_explicit_wrong_qualifier_cannot_fall_back_to_bare_character(
        self,
    ) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="hatsune_miku",
            canonical_tag="hatsune_miku_(blue_archive)",
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)

    def test_conflicting_exact_candidates_fail_closed(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="碧蓝档案角色",
            identity_candidates=("asuma_toki", "tsukatsuki_rio"),
            work_hints=("blue_archive",),
        )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(
            set(result.candidates),
            {"toki_(blue_archive)", "rio_(blue_archive)"},
        )

    def test_character_category_filter_ignores_same_named_artist(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Toki from Blue Archive",
            identity_candidates=("toki",),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")

    def test_global_ambiguous_alias_cannot_reenter_through_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            index.import_bytes(
                json.dumps(
                    {
                        "tags": [
                            {
                                "tag": "hero_(fixture_work)",
                                "category": "character",
                                "aliases": ["shared_identity"],
                                "count": 100,
                            },
                            {
                                "tag": "fixture_artist",
                                "category": "artist",
                                "aliases": ["shared_identity"],
                                "count": 200,
                            },
                            {
                                "tag": "fixture_work",
                                "category": "copyright",
                                "count": 300,
                            },
                        ]
                    }
                ).encode(),
                content_type="json",
            )

            result = resolve_character_identity(
                index,
                target_query="shared identity",
                identity_candidates=("shared_identity",),
                work_hints=("fixture_work",),
                allow_discovery=True,
            )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.match_variant, "global_alias_ambiguous")
        self.assertIn("hero_(fixture_work)", result.candidates)

    def test_wrong_category_canonical_cannot_be_reinterpreted_as_character(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            index.import_bytes(
                json.dumps(
                    {
                        "tags": [
                            {"tag": "shared", "category": "general", "count": 300},
                            {
                                "tag": "hero_(fixture_work)",
                                "category": "character",
                                "aliases": ["shared"],
                                "count": 100,
                            },
                            {
                                "tag": "fixture_work",
                                "category": "copyright",
                                "count": 300,
                            },
                        ]
                    }
                ).encode(),
                content_type="json",
            )

            result = resolve_character_identity(
                index,
                target_query="shared",
                identity_candidates=("shared",),
                work_hints=("fixture_work",),
                allow_discovery=True,
            )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.match_variant, "canonical_category_mismatch")

    def test_user_adjacent_alias_selects_base_identity_without_lora(self) -> None:
        result = resolve_user_adjacent_character_alias(
            self.index,
            alias="toki",
            canonical_candidates=(),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "user_adjacent_alias_unique_base")

    def test_user_adjacent_alias_binds_prompt_exact_to_same_base(self) -> None:
        result = resolve_user_adjacent_character_alias(
            self.index,
            alias="toki",
            canonical_candidates=("toki_(blue_archive)",),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "user_adjacent_alias_prompt_exact")

    def test_user_adjacent_alias_rejects_variant_when_base_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            payload = {
                "tags": [
                    {
                        "tag": "toki_(bunny)_(blue_archive)",
                        "category": "character",
                        "count": 5000,
                    },
                    {
                        "tag": "blue_archive",
                        "category": "copyright",
                    },
                ]
            }
            index.import_bytes(json.dumps(payload).encode(), content_type="json")
            result = resolve_user_adjacent_character_alias(
                index,
                alias="toki",
                work_hints=("blue_archive",),
            )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)

    def test_user_adjacent_alias_filters_prompt_roots_by_confirmed_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            index.import_bytes(
                json.dumps(
                    {
                        "tags": [
                            {
                                "tag": "toki_(work_a)",
                                "category": "character",
                            },
                            {
                                "tag": "toki_(work_b)",
                                "category": "character",
                            },
                            {"tag": "work_a", "category": "copyright"},
                            {"tag": "work_b", "category": "copyright"},
                        ]
                    }
                ).encode(),
                content_type="json",
            )
            result = resolve_user_adjacent_character_alias(
                index,
                alias="toki",
                canonical_candidates=("toki_(work_a)", "toki_(work_b)"),
                work_hints=("work_a",),
            )

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "toki_(work_a)")
        self.assertEqual(result.match_variant, "user_adjacent_alias_prompt_exact")

    def test_user_adjacent_alias_rejects_different_prompt_exact_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            index.import_bytes(
                json.dumps(
                    {
                        "tags": [
                            {
                                "tag": "toki_(blue_archive)",
                                "category": "character",
                            },
                            {
                                "tag": "toki_(bunny)_(blue_archive)",
                                "category": "character",
                            },
                            {
                                "tag": "hatsune_miku_(vocaloid)",
                                "category": "character",
                            },
                        ]
                    }
                ).encode(),
                content_type="json",
            )
            result = resolve_user_adjacent_character_alias(
                index,
                alias="toki",
                canonical_candidates=("hatsune_miku_(vocaloid)",),
            )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(
            result.match_variant,
            "user_adjacent_alias_prompt_conflict",
        )
        self.assertEqual(
            set(result.candidates),
            {"toki_(blue_archive)", "hatsune_miku_(vocaloid)"},
        )

    def test_prefix_discovery_collapses_one_identity_not_first_fuzzy_variant(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Toki from Blue Archive",
            identity_candidates=("toki",),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "provider_candidate_work_qualified")

    def test_punctuation_discovery_must_be_unique_and_exact_confirmed(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="崩坏星穹铁道流萤",
            canonical_tag="firefly_(honkai_star_rail)",
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "firefly_(honkai:_star_rail)")

    def test_short_identity_uses_only_safe_ascii_work_alias_for_exact_candidate(
        self,
    ) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="《BlueArchive》的调月莉音",
            identity_candidates=("Rio",),
            work_hints=("Blue Archive", "碧蓝档案", "蔚蓝档案"),
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "rio_(blue_archive)")
        self.assertEqual(
            result.match_variant,
            "provider_candidate_work_qualified",
        )

    def test_escaped_parentheses_remain_exact(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="鸣潮今汐",
            canonical_tag=r"jinhsi_\(wuthering_waves\)",
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "jinhsi_(wuthering_waves)")

    def test_punctuated_work_builds_safe_qualified_candidate(self) -> None:
        candidates = character_identity_lookup_candidates(
            target_query="Viola",
            identity_candidates=("Viola",),
            work_hints=("BanG Dream!",),
        )

        self.assertIn("viola_(bang_dream!)", candidates)

    def test_provider_candidate_uses_exact_normalized_work_hint(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="崩坏星穹铁道流萤",
            identity_candidates=("firefly",),
            work_hints=("honkai_star_rail",),
            allow_discovery=False,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "firefly_(honkai:_star_rail)")
        self.assertEqual(result.match_variant, "provider_candidate_work_qualified")

    def test_conflicting_exact_copyright_evidence_fails_closed(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="流萤",
            canonical_tag="firefly_(honkai_star_rail)",
            identity_candidates=("firefly",),
            work_hints=("genshin_impact",),
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.match_variant, "copyright_exact_conflict")
        self.assertEqual(
            set(result.conflicting_works),
            {"honkai:_star_rail", "genshin_impact"},
        )
        self.assertEqual(result.candidates, ())

    def test_fuzzy_copyright_spelling_does_not_authorize_rewrite(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="流萤",
            canonical_tag="firefly_(honkai_star)",
            work_hints=("honkai_star",),
            allow_discovery=False,
        )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)

    def test_punctuation_collapsed_copyright_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            payload = {
                "tags": [
                    {
                        "tag": "firefly_(honkai:_star_rail)",
                        "category": "character",
                    },
                    {
                        "tag": "honkai:_star_rail",
                        "category": "copyright",
                    },
                    {
                        "tag": "honkai-star-rail",
                        "category": "copyright",
                    },
                ]
            }
            index.import_bytes(json.dumps(payload).encode(), content_type="json")

            result = resolve_character_identity(
                index,
                target_query="流萤",
                canonical_tag="firefly_(honkai_star_rail)",
                allow_discovery=False,
            )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)

    def test_cross_category_work_alias_cannot_bypass_global_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = DanbooruTagIndex(Path(directory) / "tags.sqlite3")
            index.import_bytes(
                json.dumps(
                    {
                        "tags": [
                            {
                                "tag": "hero_(foo_bar)",
                                "category": "character",
                            },
                            {
                                "tag": "foo_bar",
                                "category": "copyright",
                                "aliases": ["foo-bar"],
                            },
                            {
                                "tag": "foo_artist",
                                "category": "artist",
                                "aliases": ["foo-bar"],
                            },
                        ]
                    }
                ).encode(),
                content_type="json",
            )

            result = resolve_character_identity(
                index,
                target_query="hero from foo-bar",
                canonical_tag="hero_(foo-bar)",
                identity_candidates=("hero",),
                work_hints=("foo-bar",),
                allow_discovery=False,
            )

        self.assertFalse(result.verified)
        self.assertFalse(result.ambiguous)


if __name__ == "__main__":
    unittest.main()
