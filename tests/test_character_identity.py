from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ..services.character_identity import resolve_character_identity
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

    def test_prefix_discovery_collapses_one_identity_not_first_fuzzy_variant(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="Toki from Blue Archive",
            identity_candidates=("toki",),
            work_hints=("blue_archive",),
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "toki_(blue_archive)")
        self.assertEqual(result.match_variant, "local_discovery_unique_identity")

    def test_escaped_parentheses_remain_exact(self) -> None:
        result = resolve_character_identity(
            self.index,
            target_query="鸣潮今汐",
            canonical_tag=r"jinhsi_\(wuthering_waves\)",
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "jinhsi_(wuthering_waves)")


if __name__ == "__main__":
    unittest.main()
