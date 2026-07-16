"""Tests for the versioned semantic LoRA overlay."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import (
    LoraSemanticError,
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
    semantic_source_fingerprint,
)


def _record(name: str, **kwargs) -> LoraRecord:
    defaults = {
        "sha256": "abc12345",
        "model_name": "Raw model title",
        "category": "unknown",
        "aliases": (),
        "trigger_words": (),
        "tags": (),
    }
    defaults.update(kwargs)
    return LoraRecord(name=name, **defaults)


def _fact(value: str, source: str = "llm_inferred") -> SemanticFact:
    return SemanticFact(
        value=value, source=source, evidence=("fixture",), confidence=0.9
    )


def _entry(record: LoraRecord, **kwargs) -> SemanticEntry:
    defaults = {
        "identity_key": semantic_identity_key(record.name, record.sha256),
        "canonical_name": record.name,
        "sha256": record.sha256,
        "analysis_status": "searchable",
        "category": (_fact("character"),),
        "character_names": (_fact("Denia"),),
        "source_works": (_fact("Wuthering Waves"),),
        "aliases": (_fact("达妮娅"), _fact("丹瑾")),
    }
    defaults.update(kwargs)
    return SemanticEntry(**defaults)


class SemanticIdentityTests(unittest.TestCase):
    def test_identity_prefers_sha256_and_falls_back_to_canonical_name(self) -> None:
        self.assertEqual(
            semantic_identity_key("Characters/Denia.safetensors", "AA11BB22"),
            "sha256:aa11bb22",
        )
        self.assertEqual(
            semantic_identity_key("Characters\\Denia.safetensors"),
            "name:characters/denia",
        )

    def test_fact_rejects_unknown_provenance_and_invalid_confidence(self) -> None:
        with self.assertRaises(LoraSemanticError):
            SemanticFact("Denia", "guessed")
        with self.assertRaises(LoraSemanticError):
            SemanticFact("Denia", "manual", confidence=1.1)

    def test_entry_rejects_identity_mismatch_and_unknown_status(self) -> None:
        with self.assertRaises(LoraSemanticError):
            SemanticEntry(
                identity_key="name:wrong",
                canonical_name="denia.safetensors",
            )
        with self.assertRaises(LoraSemanticError):
            SemanticEntry(
                identity_key="name:denia",
                canonical_name="denia.safetensors",
                analysis_status="done",
            )


class SemanticSerializationTests(unittest.TestCase):
    def test_version_two_round_trip_preserves_provenance(self) -> None:
        record = _record("characters/denia.safetensors")
        entry = _entry(
            record,
            aliases=(
                _fact("Denia", "observed"),
                _fact("达妮娅", "derived"),
                _fact("丹瑾", "manual"),
            ),
        )
        original = LoraSemanticIndex(entries={entry.identity_key: entry})

        restored = LoraSemanticIndex.from_payload(original.to_dict())

        facts = restored.entries[entry.identity_key].aliases
        self.assertEqual(
            [fact.source for fact in facts], ["observed", "derived", "manual"]
        )

    def test_load_missing_file_returns_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = LoraSemanticIndex.load(Path(directory) / "missing.json")
        self.assertEqual(index.entries, {})

    def test_invalid_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "semantic.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(LoraSemanticError):
                LoraSemanticIndex.load(path)


class LegacyArchiveMigrationTests(unittest.TestCase):
    def test_migrates_legacy_archive_with_llm_and_manual_provenance(self) -> None:
        legacy = {
            "schema_version": 1,
            "updated_at": "2026-07-16T01:00:00+00:00",
            "entries": {
                "characters/denia": {
                    "name": "characters/denia.safetensors",
                    "present": True,
                    "catalog_source_fingerprint": "source-v1",
                    "source": {
                        "sha256": "ABC12345",
                        "existing_category": "character",
                        "existing_aliases": ["Denia"],
                        "existing_character_name": "Denia",
                        "existing_source_work": "Wuthering Waves / 鸣潮",
                    },
                    "classification": {
                        "category": "character",
                        "character_names": ["Denia"],
                        "source_works": ["Wuthering Waves"],
                        "artist_style_names": [],
                        "aliases": ["Denia"],
                        "evidence": ["Denia character model"],
                        "confidence": "high",
                    },
                    "manual_override": {"aliases": ["达妮娅", "丹瑾"]},
                    "classified_at": "2026-07-16T00:00:00+00:00",
                }
            },
        }

        index = LoraSemanticIndex.from_payload(legacy)
        entry = index.entries["sha256:abc12345"]

        self.assertEqual(entry.analysis_status, "searchable")
        self.assertEqual(entry.source_fingerprint, "source-v1")
        self.assertIn("observed", {fact.source for fact in entry.character_names})
        self.assertIn("llm_inferred", {fact.source for fact in entry.character_names})
        self.assertEqual(entry.effective_values("aliases"), ("丹瑾", "达妮娅"))

    def test_migrates_low_confidence_and_removed_entries_to_safe_statuses(self) -> None:
        legacy = {
            "schema_version": 1,
            "entries": {
                "unknown": {
                    "name": "unknown.safetensors",
                    "present": True,
                    "source": {},
                    "classification": {
                        "category": "unclassified",
                        "confidence": "low",
                    },
                },
                "removed": {
                    "name": "removed.safetensors",
                    "present": False,
                    "source": {},
                    "classification": {"category": "character"},
                },
            },
        }

        index = LoraSemanticIndex.from_payload(legacy)

        self.assertEqual(index.entries["name:unknown"].analysis_status, "review_needed")
        self.assertEqual(index.entries["name:removed"].analysis_status, "stale")

    def test_loads_legacy_file_without_rewriting_it(self) -> None:
        payload = {"schema_version": 1, "entries": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lora_archive.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes()
            LoraSemanticIndex.load(path)
            after = path.read_bytes()
        self.assertEqual(after, before)

    def test_legacy_functional_category_is_preserved_during_migration(self) -> None:
        legacy = {
            "schema_version": 1,
            "entries": {
                "quality": {
                    "name": "quality/highres.safetensors",
                    "present": True,
                    "source": {
                        "sha256": "abc99999",
                        "existing_category": "quality_enhancement",
                    },
                    "classification": {
                        "category": "quality_enhancement",
                        "confidence": "high",
                        "evidence": ["quality enhancement"],
                    },
                }
            },
        }

        index = LoraSemanticIndex.from_payload(legacy)
        entry = index.entries["sha256:abc99999"]

        self.assertEqual(entry.analysis_status, "searchable")
        self.assertEqual(entry.effective_category, "quality_enhancement")


class SemanticOverlayTests(unittest.TestCase):
    def test_frozen_source_fingerprint_survives_semantic_overlay(self) -> None:
        raw = _record("characters/denia.safetensors")
        fingerprint = semantic_source_fingerprint(raw)
        frozen = replace(raw, source_fingerprint=fingerprint)
        entry = _entry(
            frozen,
            aliases=(_fact("达妮娅"),),
        )
        overlaid = LoraSemanticIndex(entries={entry.identity_key: entry}).apply_overlay(
            frozen
        )

        self.assertIn("达妮娅", overlaid.aliases)
        self.assertEqual(semantic_source_fingerprint(overlaid), fingerprint)

    def test_sha_identity_survives_file_rename_and_applies_overlay(self) -> None:
        archived = _record("old/denia.safetensors")
        entry = _entry(archived)
        fresh = _record(
            "renamed/denia-v2.safetensors",
            aliases=("local alias",),
            trigger_words=("denia_wuwa",),
        )
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        overlaid = index.apply_overlay(fresh)

        self.assertEqual(overlaid.category, "character")
        self.assertEqual(overlaid.character_name, "Denia")
        self.assertEqual(overlaid.source_work, "Wuthering Waves")
        self.assertIn("local alias", overlaid.aliases)
        self.assertIn("达妮娅", overlaid.aliases)

    def test_name_fallback_applies_to_hashless_legacy_entry(self) -> None:
        fresh = _record("characters/denia.safetensors", sha256="")
        entry = _entry(
            fresh,
            identity_key="name:characters/denia",
            sha256="",
        )
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        self.assertEqual(index.apply_overlay(fresh).character_name, "Denia")

    def test_stale_failed_and_unreviewed_entries_do_not_overlay(self) -> None:
        record = _record("characters/denia.safetensors")
        for status in (
            "stale",
            "failed",
            "metadata_ready",
            "analyzing",
            "review_needed",
        ):
            with self.subTest(status=status):
                entry = _entry(record, analysis_status=status)
                index = LoraSemanticIndex(entries={entry.identity_key: entry})
                self.assertIs(index.apply_overlay(record), record)

    def test_manual_review_entry_is_allowed_and_manual_values_override_llm(
        self,
    ) -> None:
        record = _record("characters/denia.safetensors")
        entry = _entry(
            record,
            analysis_status="review_needed",
            character_names=(
                _fact("Wrong Name", "llm_inferred"),
                _fact("丹瑾", "manual"),
            ),
            aliases=(
                _fact("wrong", "llm_inferred"),
                _fact("达妮娅", "manual"),
            ),
        )
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        overlaid = index.apply_overlay(record)

        self.assertEqual(overlaid.character_name, "丹瑾")
        self.assertIn("达妮娅", overlaid.aliases)
        self.assertNotIn("wrong", overlaid.aliases)

    def test_hash_mismatch_does_not_apply_wrong_overlay(self) -> None:
        archived = _record("characters/denia.safetensors", sha256="abc12345")
        fresh = _record("characters/denia.safetensors", sha256="def67890")
        entry = _entry(archived)
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        self.assertIs(index.apply_overlay(fresh), fresh)


class SemanticSearchTests(unittest.TestCase):
    def test_search_matches_manual_alias_and_returns_safe_unique_candidate(
        self,
    ) -> None:
        denia = _record("characters/denia.safetensors")
        style = _record("styles/warm-ink.safetensors", sha256="def67890")
        denia_entry = _entry(
            denia,
            aliases=(_fact("达妮娅", "manual"), _fact("丹瑾", "manual")),
        )
        style_entry = SemanticEntry(
            identity_key=semantic_identity_key(style.name, style.sha256),
            canonical_name=style.name,
            sha256=style.sha256,
            analysis_status="searchable",
            category=(_fact("artist_style"),),
            artist_style_names=(_fact("暖墨风格"),),
            aliases=(_fact("warm ink"),),
        )
        index = LoraSemanticIndex(
            entries={
                denia_entry.identity_key: denia_entry,
                style_entry.identity_key: style_entry,
            }
        )

        result = index.search((denia, style), "达妮娅")

        self.assertFalse(result.ambiguous)
        self.assertEqual(result.selected_name, denia.name)
        self.assertEqual(result.candidates[0].score, 100)

    def test_duplicate_character_alias_is_reported_as_ambiguous(self) -> None:
        first = _record("a/denia.safetensors", sha256="aaa11111")
        second = _record("b/denia.safetensors", sha256="bbb22222")
        first_entry = _entry(first, aliases=(_fact("达妮娅", "manual"),))
        second_entry = _entry(second, aliases=(_fact("达妮娅", "manual"),))
        index = LoraSemanticIndex(
            entries={
                first_entry.identity_key: first_entry,
                second_entry.identity_key: second_entry,
            }
        )

        result = index.search((first, second), "达妮娅")

        self.assertTrue(result.ambiguous)
        self.assertEqual(result.selected_name, "")
        self.assertEqual([item.score for item in result.candidates], [100, 100])

    def test_duplicate_basename_is_not_auto_selected(self) -> None:
        first = _record("a/denia.safetensors", sha256="aaa11111")
        second = _record("b/denia.safetensors", sha256="bbb22222")

        result = LoraSemanticIndex.empty().search((first, second), "denia")

        self.assertTrue(result.ambiguous)
        self.assertEqual(result.selected_name, "")

    def test_exact_full_canonical_name_beats_alias_collision(self) -> None:
        first = _record("a/denia.safetensors", sha256="aaa11111", aliases=("target",))
        second = _record("b/target.safetensors", sha256="bbb22222")

        result = LoraSemanticIndex.empty().search((first, second), "b/target")

        self.assertEqual(result.selected_name, second.name)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.candidates[0].score, 120)


class SemanticPersistenceV2Tests(unittest.TestCase):
    def test_atomic_save_reload_and_presence_sync(self) -> None:
        record = _record("characters/denia.safetensors")
        entry = _entry(record, aliases=(_fact("达妮娅", "manual"),))
        index = LoraSemanticIndex.empty()
        index.upsert(entry)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lora_semantic_v2.json"
            index.save(path)
            restored = LoraSemanticIndex.load(path)
        self.assertEqual(
            restored.entry_for(record).effective_values("aliases"), ("达妮娅",)
        )
        restored.sync_presence(())
        self.assertFalse(restored.entries[entry.identity_key].present)


if __name__ == "__main__":
    unittest.main()
