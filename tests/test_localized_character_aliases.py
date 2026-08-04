from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ..services.danbooru_index import DanbooruTagIndex
from ..services.localized_character_aliases import (
    LocalizedAliasEntry,
    LocalizedCharacterAliasIndex,
    normalize_localized_alias,
    parse_autocomplete_csv,
    split_localized_character_query,
)


class LocalizedCharacterAliasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.index = DanbooruTagIndex(Path(self.directory.name) / "tags.sqlite3")
        payload = {
            "source": "unit fixture",
            "license": "fixture-only",
            "revision": "localized-r1",
            "tags": [
                {
                    "tag": "phoebe_(wuthering_waves)",
                    "category": "character",
                    "aliases": [],
                    "count": 3100,
                },
                {
                    "tag": "phoebe_(pokemon)",
                    "category": "character",
                    "aliases": [],
                    "count": 250,
                },
                {
                    "tag": "wuthering_waves",
                    "category": "copyright",
                    "aliases": [],
                    "count": 12000,
                },
                {
                    "tag": "pokemon",
                    "category": "copyright",
                    "aliases": [],
                    "count": 900000,
                },
                {
                    "tag": "kei_(blue_archive)",
                    "category": "character",
                    "aliases": [],
                    "count": 2148,
                },
                {
                    "tag": "blue_archive",
                    "category": "copyright",
                    "aliases": [],
                    "count": 371555,
                },
                {
                    "tag": "hatsune_miku",
                    "category": "character",
                    "aliases": [],
                    "count": 180000,
                },
                {
                    "tag": "vocaloid",
                    "category": "copyright",
                    "aliases": [],
                    "count": 900000,
                },
            ],
        }
        self.index.import_bytes(json.dumps(payload).encode(), content_type="json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_phoebe_with_wuthering_waves_resolves_exact(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        result = aliases.resolve_character("菲比", "鸣潮", self.index)

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "phoebe_(wuthering_waves)")
        self.assertEqual(result.confirmed_work, "wuthering_waves")
        self.assertEqual(result.match_type, "localized_alias_exact")

    def test_phoebe_without_work_fails_closed(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        result = aliases.resolve_character("菲比", "", self.index)

        self.assertFalse(result.verified)
        self.assertTrue(result.ambiguous)
        self.assertTrue(result.work_required)

    def test_wrong_work_cannot_select_wuthering_waves_character(self) -> None:
        aliases = LocalizedCharacterAliasIndex(
            (
                LocalizedAliasEntry(
                    alias="宝可梦",
                    canonical_tag="pokemon",
                    category="copyright",
                ),
            )
        )

        result = aliases.resolve_character("菲比", "宝可梦", self.index)

        self.assertFalse(result.verified)
        self.assertEqual(result.match_type, "localized_work_conflict")

    def test_missing_character_canonical_is_rejected(self) -> None:
        aliases = LocalizedCharacterAliasIndex(
            (
                LocalizedAliasEntry(
                    alias="新角色",
                    canonical_tag="missing_(wuthering_waves)",
                    category="character",
                    work="wuthering_waves",
                ),
            )
        )

        result = aliases.resolve_character("新角色", "鸣潮", self.index)

        self.assertFalse(result.verified)
        self.assertEqual(result.match_type, "localized_canonical_unverified")

    def test_query_split_and_nfkc_normalization(self) -> None:
        self.assertEqual(
            split_localized_character_query("《鸣潮》的菲比"),
            ("菲比", "鸣潮"),
        )
        self.assertEqual(
            split_localized_character_query("菲比（鸣潮）"),
            ("菲比", "鸣潮"),
        )
        self.assertEqual(normalize_localized_alias(" Ｗｕ－Ｗａ "), "wuwa")

    def test_parenthetical_ascii_alias_is_not_misread_as_work(self) -> None:
        self.index.import_bytes(
            json.dumps(
                {
                    "tags": [
                        {
                            "tag": "toki_(blue_archive)",
                            "category": "character",
                            "aliases": ["toki"],
                        },
                        {
                            "tag": "blue_archive",
                            "category": "copyright",
                        },
                    ]
                }
            ).encode(),
            content_type="json",
        )

        result = LocalizedCharacterAliasIndex().search(
            "飞鸟马时（toki）",
            index=self.index,
            category="character",
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].verified)
        self.assertEqual(result[0].canonical_tag, "toki_(blue_archive)")
        self.assertEqual(
            result[0].match_type,
            "localized_adjacent_ascii_alias_exact",
        )

    def test_autocomplete_csv_supports_one_to_many_aliases(self) -> None:
        entries = parse_autocomplete_csv(
            "tag,category,count,alias\n"
            'phoebe_(wuthering_waves),4,3000,"菲比,菲碧"\n'
            'phoebe_(pokemon),4,250,"菲比"\n'
            'wuthering_waves,3,12000,"鸣潮,鳴潮"\n',
            source="fixture",
            license_name="fixture-only",
            revision="r1",
        )
        aliases = LocalizedCharacterAliasIndex(entries)

        no_work = aliases.resolve_character("菲比", "", self.index)
        with_work = aliases.resolve_character("菲比", "鸣潮", self.index)

        self.assertTrue(no_work.ambiguous)
        self.assertEqual(no_work.candidate_count, 2)
        self.assertTrue(with_work.verified)
        self.assertEqual(with_work.canonical_tag, "phoebe_(wuthering_waves)")

    def test_search_returns_verified_canonical_for_full_localized_query(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        results = aliases.search(
            "《鸣潮》的菲比",
            index=self.index,
            category="character",
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].verified)
        self.assertEqual(results[0].canonical_tag, "phoebe_(wuthering_waves)")

    def test_ascii_character_with_camelcase_work_resolves_exact(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        results = aliases.search(
            "《BlueArchive》Kei",
            index=self.index,
            category="character",
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].verified)
        self.assertEqual(results[0].canonical_tag, "kei_(blue_archive)")
        self.assertEqual(
            results[0].match_type,
            "localized_work_ascii_character_exact",
        )

    def test_qualifierless_character_uses_curated_work_as_separate_evidence(
        self,
    ) -> None:
        aliases = LocalizedCharacterAliasIndex()

        result = aliases.resolve_character("初音未来", "VOCALOID", self.index)

        self.assertTrue(result.verified)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.canonical_tag, "hatsune_miku")
        self.assertEqual(result.confirmed_work, "vocaloid")
        self.assertEqual(result.candidates[0].work, "vocaloid")

    def test_qualifierless_character_rejects_wrong_exact_work(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        result = aliases.resolve_character("初音未来", "Blue Archive", self.index)

        self.assertFalse(result.verified)
        self.assertEqual(result.match_type, "localized_work_conflict")

    def test_ascii_qualifierless_canonical_requires_exact_copyright(self) -> None:
        aliases = LocalizedCharacterAliasIndex()

        valid = aliases.resolve_character("hatsune_miku", "vocaloid", self.index)
        invalid = aliases.resolve_character(
            "hatsune_miku",
            "not_a_real_work",
            self.index,
        )

        self.assertTrue(valid.verified)
        self.assertEqual(valid.canonical_tag, "hatsune_miku")
        self.assertEqual(valid.confirmed_work, "vocaloid")
        self.assertFalse(invalid.verified)


if __name__ == "__main__":
    unittest.main()
