from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ..services.danbooru_index import DanbooruTagIndex
from ..services.localized_character_aliases import (
    LocalizedCharacterAliasIndex,
    parse_autocomplete_csv,
)
from ..services.lora_catalog import LoraRecord
from ..services.lora_identity_evidence import (
    build_lora_identity_discovery,
    resolve_lora_character_canonicals,
)
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
    semantic_source_fingerprint,
)


class LoraIdentityEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.index = DanbooruTagIndex(Path(self.directory.name) / "tags.sqlite3")
        self.index.import_bytes(
            json.dumps(
                {
                    "revision": "identity-r1",
                    "tags": [
                        {"tag": "new_hero_(new_work)", "category": "character"},
                        {"tag": "new_work", "category": "copyright"},
                        {"tag": "eimi_(blue_archive)", "category": "character"},
                        {"tag": "himari_(blue_archive)", "category": "character"},
                        {"tag": "rio_(blue_archive)", "category": "character"},
                        {"tag": "toki_(blue_archive)", "category": "character"},
                        {"tag": "blue_archive", "category": "copyright"},
                        {"tag": "alpha_(shared_work)", "category": "character"},
                        {"tag": "beta_(shared_work)", "category": "character"},
                        {"tag": "shared_work", "category": "copyright"},
                        {"tag": "hatsune_miku", "category": "character"},
                        {"tag": "vocaloid", "category": "copyright"},
                        {
                            "tag": "scathach_(fate/grand_order)",
                            "category": "character",
                        },
                        {"tag": "fate/grand_order", "category": "copyright"},
                        {"tag": "arknights", "category": "copyright"},
                        {
                            "tag": "future_role_(future_series)",
                            "category": "character",
                        },
                        {"tag": "future_series", "category": "copyright"},
                    ],
                },
                ensure_ascii=False,
            ).encode(),
            content_type="json",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    @staticmethod
    def _record(**updates: object) -> LoraRecord:
        values: dict[str, object] = {
            "name": "characters/future.safetensors",
            "sha256": "ab" * 32,
            "category": "unknown",
        }
        values.update(updates)
        record = LoraRecord(**values)
        return replace(record, source_fingerprint=semantic_source_fingerprint(record))

    @staticmethod
    def _semantic_index(
        record: LoraRecord,
        *,
        character_names: tuple[str, ...],
        source_works: tuple[str, ...],
        aliases: tuple[str, ...] = (),
        fingerprint: str | None = None,
    ) -> LoraSemanticIndex:
        entry = SemanticEntry(
            identity_key=semantic_identity_key(record.name, record.sha256),
            canonical_name=record.name,
            sha256=record.sha256,
            analysis_status="searchable",
            category=(SemanticFact("character", "manual"),),
            character_names=tuple(
                SemanticFact(value, "manual") for value in character_names
            ),
            source_works=tuple(
                SemanticFact(value, "observed") for value in source_works
            ),
            aliases=tuple(SemanticFact(value, "manual") for value in aliases),
            source_fingerprint=(
                record.source_fingerprint if fingerprint is None else fingerprint
            ),
            analysis_confidence=1.0,
        )
        return LoraSemanticIndex(entries={entry.identity_key: entry})

    def test_future_localized_query_uses_fresh_semantic_pair_then_exact(self) -> None:
        record = self._record(source_work="新作品")
        semantic = self._semantic_index(
            record,
            character_names=("新角色", "new_hero"),
            source_works=("new_work",),
            aliases=("新角色",),
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=semantic,
            tag_index=self.index,
            query="新角色",
        )

        self.assertEqual(result, ("new_hero_(new_work)",))

    def test_stale_semantic_fingerprint_cannot_authorize_future_character(self) -> None:
        record = self._record()
        semantic = self._semantic_index(
            record,
            character_names=("new_hero",),
            source_works=("new_work",),
            aliases=("新角色",),
            fingerprint="stale-fingerprint",
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=semantic,
            tag_index=self.index,
            query="新角色",
        )

        self.assertEqual(result, ())

    def test_four_in_one_record_keeps_every_exact_character(self) -> None:
        record = self._record(
            category="character",
            character_name="Eimi / Himari / Rio / Toki",
            source_work="Blue Archive",
            trigger_words=(
                "eimi (blue archive)",
                "himari (blue archive)",
                "rio (blue archive)",
                "toki (blue archive)",
            ),
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
        )

        self.assertEqual(
            set(result),
            {
                "eimi_(blue_archive)",
                "himari_(blue_archive)",
                "rio_(blue_archive)",
                "toki_(blue_archive)",
            },
        )

    def test_ambiguous_localized_alias_never_becomes_exact_authority(self) -> None:
        aliases = LocalizedCharacterAliasIndex(
            parse_autocomplete_csv(
                "tag,category,count,alias\n"
                'alpha_(shared_work),4,100,"同名角色"\n'
                'beta_(shared_work),4,90,"同名角色"\n'
                'shared_work,3,1000,"共同作品"\n',
                source="fixture",
                license_name="fixture-only",
                revision="r1",
            )
        )
        record = self._record(
            category="character",
            character_name="同名角色",
            source_work="共同作品",
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
            localized_index=aliases,
        )

        self.assertEqual(result, ())

    def test_qualifierless_character_keeps_separate_exact_work_evidence(self) -> None:
        record = self._record(
            category="character",
            character_name="Hatsune Miku",
            source_work="Vocaloid",
            trigger_words=("hatsune_miku",),
        )

        discovery = build_lora_identity_discovery(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
        )
        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
        )

        self.assertEqual(discovery.canonical_works, ("vocaloid",))
        self.assertEqual(result, ("hatsune_miku",))

    def test_wrong_work_rejects_qualified_character(self) -> None:
        record = self._record(
            category="character",
            character_name="Scathach",
            source_work="Arknights",
            trigger_words=(r"scathach \(fate/grand_order\)",),
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
        )

        self.assertEqual(result, ())

    def test_slash_work_title_is_preserved_before_split_hints(self) -> None:
        record = self._record(
            category="character",
            character_name="Scathach",
            source_work="Fate/Grand Order",
            trigger_words=(r"scathach \(fate/grand_order\)",),
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
        )

        self.assertEqual(result, ("scathach_(fate/grand_order)",))

    def test_new_localized_csv_entry_works_without_code_change(self) -> None:
        aliases = LocalizedCharacterAliasIndex(
            parse_autocomplete_csv(
                "tag,category,count,alias\n"
                'future_role_(future_series),4,100,"未来角色"\n'
                'future_series,3,1000,"未来作品"\n',
                source="administrator-csv",
                license_name="operator-supplied",
                revision="future-r1",
            )
        )
        record = self._record(
            category="character",
            character_name="未来角色",
            source_work="未来作品",
        )

        result = resolve_lora_character_canonicals(
            record,
            semantic_index=LoraSemanticIndex.empty(),
            tag_index=self.index,
            localized_index=aliases,
        )

        self.assertEqual(result, ("future_role_(future_series)",))
