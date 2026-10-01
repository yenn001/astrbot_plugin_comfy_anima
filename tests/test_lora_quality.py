"""Deterministic, redacted semantic quality gates for representative LoRAs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from ..services.lora_catalog import LoraRecord
from ..services.lora_detail import FileStatus, LoraDetailV2, MetadataHealth
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lora_semantic_goldens.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _detail(payload: dict[str, Any]) -> LoraDetailV2:
    raw = dict(payload)
    raw["trigger_words"] = tuple(raw.get("trigger_words", ()))
    raw["tags"] = tuple(raw.get("tags", ()))
    raw["aliases"] = tuple(raw.get("aliases", ()))
    raw["file_status"] = FileStatus(**raw.get("file_status", {}))
    raw["metadata_health"] = MetadataHealth(**raw.get("metadata_health", {}))
    return LoraDetailV2(**raw)


def _record(detail: LoraDetailV2) -> LoraRecord:
    return LoraRecord(
        name=detail.name,
        trigger_words=detail.trigger_words,
        description=detail.version_description or detail.model_description,
        model_name=detail.model_name,
        base_model=detail.base_model,
        folder=detail.folder,
        tags=detail.tags,
        favorite=detail.file_status.favorite,
        sha256=detail.file_status.sha256,
        category=detail.category,
        aliases=detail.aliases,
        character_name=detail.character_name,
        source_work=detail.source_work,
        from_civitai=detail.file_status.from_civitai,
    )


def _facts(values: Any) -> tuple[SemanticFact, ...]:
    return tuple(SemanticFact.from_dict(item) for item in values or ())


def _entry(detail: LoraDetailV2, semantic: dict[str, Any]) -> SemanticEntry:
    return SemanticEntry(
        identity_key=semantic_identity_key(detail.name, detail.file_status.sha256),
        canonical_name=detail.name,
        sha256=detail.file_status.sha256,
        analysis_status=semantic["analysis_status"],
        category=_facts(semantic.get("category")),
        character_names=_facts(semantic.get("character_names")),
        source_works=_facts(semantic.get("source_works")),
        artist_style_names=_facts(semantic.get("artist_style_names")),
        aliases=_facts(semantic.get("aliases")),
    )


class LoraSemanticGoldenQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _load_fixture()
        cls.cases = cls.fixture["cases"]
        cls.details = {case["id"]: _detail(case["detail"]) for case in cls.cases}
        cls.records = tuple(_record(cls.details[case["id"]]) for case in cls.cases)
        cls.names_by_id = {
            case["id"]: cls.details[case["id"]].name for case in cls.cases
        }
        entries = {
            entry.identity_key: entry
            for case in cls.cases
            for entry in (_entry(cls.details[case["id"]], case["semantic"]),)
        }
        removed = cls.fixture["removed_semantic"]
        removed_detail = LoraDetailV2(
            asset_id="asset-retired-001",
            name=removed["name"],
            file_name=removed["name"].rsplit("/", 1)[-1],
            file_status=FileStatus(
                sha256=removed["sha256"],
                loadable=False,
            ),
        )
        removed_entry = _entry(removed_detail, removed)
        entries[removed_entry.identity_key] = removed_entry
        cls.removed_entry_key = removed_entry.identity_key
        cls.index = LoraSemanticIndex(entries=entries)

    def test_fixture_is_redacted_and_contains_no_external_location(self) -> None:
        raw = FIXTURE_PATH.read_text(encoding="utf-8")

        self.assertNotRegex(raw, r"(?i)https?://|file://|sk-[a-z0-9_-]{8,}")
        self.assertNotRegex(raw, r"(?i)[a-z]:[\\/]|/(?:home|root|astrbot|comfyui)/")
        self.assertNotRegex(raw, r"(?i)api[_-]?key|authorization|bearer\s+")

    def test_lora_detail_payloads_are_deterministic_and_bounded(self) -> None:
        for case_id, detail in self.details.items():
            with self.subTest(case=case_id):
                first = detail.to_llm_payload()
                second = _detail(
                    next(case["detail"] for case in self.cases if case["id"] == case_id)
                ).to_llm_payload()
                self.assertEqual(first, second)
                self.assertEqual(first["schema_version"], 2)
                self.assertEqual(first["asset_id"], detail.asset_id)
                self.assertEqual(first["trigger_words"], list(detail.trigger_words))
                serialized = json.dumps(first, ensure_ascii=False)
                self.assertNotRegex(serialized, r"(?i)https?://|[a-z]:[\\/]")

    def test_semantic_overlay_preserves_every_trigger_word_exactly(self) -> None:
        overlaid = self.index.apply_overlays(self.records)

        self.assertEqual(len(overlaid), len(self.records))
        for before, after in zip(self.records, overlaid):
            with self.subTest(lora=before.name):
                self.assertEqual(after.trigger_words, before.trigger_words)
                self.assertEqual(
                    list(after.trigger_words),
                    list(
                        self.details[
                            next(
                                case_id
                                for case_id, name in self.names_by_id.items()
                                if name == before.name
                            )
                        ].trigger_words
                    ),
                )

    def test_expected_character_work_and_style_overlays_are_applied(self) -> None:
        by_name = {
            record.name: record for record in self.index.apply_overlays(self.records)
        }

        denia = by_name[self.names_by_id["denia_wuwa"]]
        self.assertEqual(denia.category, "character")
        self.assertIn("达妮娅", denia.character_name)
        self.assertIn("鸣潮", denia.source_work)

        remielle = by_name[self.names_by_id["remielle_zzz"]]
        self.assertIn("拉米尔", remielle.character_name)
        self.assertIn("绝区零", remielle.source_work)

        cure = by_name[self.names_by_id["cure_arcana_shadow"]]
        self.assertIn("Cure Arcana Shadow", cure.character_name)
        self.assertIn("光之美少女", cure.source_work)

        style = by_name[self.names_by_id["photo_background_style"]]
        self.assertEqual(style.category, "artist_style")
        self.assertIn("写真背景", style.aliases)

    def test_functional_category_goldens_remain_distinct_and_searchable(self) -> None:
        expected = {
            "speed_sampling_helper": ("speed_sampling", "采样加速"),
            "quality_enhancer": ("quality_enhancement", "画质增强"),
            "detail_restorer": ("detail_restoration", "细节修复"),
            "composition_pose_helper": ("composition_pose", "构图姿势"),
            "lighting_color_helper": ("lighting_color", "光影色彩"),
            "clothing_concept_helper": ("clothing_concept", "服装概念"),
        }
        by_name = {
            record.name: record for record in self.index.apply_overlays(self.records)
        }

        for case_id, (category, alias) in expected.items():
            with self.subTest(category=category):
                record = by_name[self.names_by_id[case_id]]
                self.assertEqual(record.category, category)
                self.assertIn(alias, record.aliases)
                result = self.index.search(self.records, alias, limit=30)
                self.assertEqual(result.selected_name, record.name)

    def test_unique_chinese_english_and_work_alias_queries_hit_expected_lora(
        self,
    ) -> None:
        for query in self.fixture["unique_queries"]:
            with self.subTest(query=query["query"]):
                result = self.index.search(self.records, query["query"], limit=20)
                self.assertFalse(result.ambiguous)
                self.assertEqual(
                    result.selected_name,
                    self.names_by_id[query["expected_id"]],
                )

    def test_shared_work_and_duplicate_alias_queries_never_auto_select(self) -> None:
        for query in self.fixture["ambiguous_queries"]:
            with self.subTest(query=query["query"]):
                result = self.index.search(self.records, query["query"], limit=20)
                candidate_names = {candidate.name for candidate in result.candidates}
                expected_names = {
                    self.names_by_id[case_id] for case_id in query["expected_ids"]
                }
                self.assertTrue(result.ambiguous)
                self.assertEqual(result.selected_name, "")
                self.assertTrue(expected_names.issubset(candidate_names))

    def test_sparse_case_stays_unclassified_until_review(self) -> None:
        sparse_name = self.names_by_id["sparse_unknown"]
        before = next(record for record in self.records if record.name == sparse_name)
        after = self.index.apply_overlay(before)

        self.assertIs(after, before)
        self.assertEqual(after.category, "unknown")
        self.assertEqual(after.aliases, ())
        result = self.index.search(self.records, "mystery_epoch24")
        self.assertEqual(result.selected_name, sparse_name)

    def test_old_unloadable_semantic_record_never_reappears(self) -> None:
        self.index.sync_presence(self.records)

        removed_entry = self.index.entries[self.removed_entry_key]
        self.assertFalse(removed_entry.present)
        overlaid = self.index.apply_overlays(self.records)
        self.assertEqual(
            {record.name for record in overlaid},
            {record.name for record in self.records},
        )
        result = self.index.search(self.records, "不可加载旧角色")
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.selected_name, "")


if __name__ == "__main__":
    unittest.main()
