"""Tests for the LLM-backed logical LoRA archive."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ..services.lora_archiver import LoraArchiveError, LoraArchiveService
from ..services.lora_catalog import LoraRecord


def _record(name: str, **kwargs) -> LoraRecord:
    defaults = {
        "model_name": "Character > Denia (Wuthering Waves)",
        "description": "Denia character model. Use for the named character.",
        "trigger_words": ("denia (wuthering waves)", "black coat"),
        "tags": ("character", "wuthering waves"),
        "aliases": ("denia", "达妮娅"),
        "character_name": "Denia / 达妮娅",
        "source_work": "Wuthering Waves / 鸣潮",
        "from_civitai": True,
        "sha256": "abc123",
    }
    defaults.update(kwargs)
    return LoraRecord(name=name, **defaults)


def _classification(record: LoraRecord, *, category: str = "character") -> dict:
    if category == "character":
        character_names = ["Denia"]
        artist_style_names = []
        evidence = ["Character > Denia (Wuthering Waves)"]
        confidence = "high"
        uncertainty = ""
    elif category == "artist_style":
        character_names = []
        artist_style_names = ["warm ink style"]
        evidence = ["warm ink style"]
        confidence = "high"
        uncertainty = ""
    else:
        character_names = []
        artist_style_names = []
        evidence = []
        confidence = "low"
        uncertainty = "insufficient metadata"
    return {
        "name": record.name,
        "category": category,
        "display_name": record.model_name,
        "character_names": character_names,
        "source_works": ["Wuthering Waves"] if category == "character" else [],
        "artist_style_names": artist_style_names,
        "aliases": list(record.aliases),
        "summary": record.description,
        "evidence": evidence,
        "confidence": confidence,
        "uncertainty": uncertainty,
    }


def _response(*items: dict) -> str:
    return json.dumps({"items": list(items)}, ensure_ascii=False)


class FingerprintAndSelectionTests(unittest.TestCase):
    def test_catalog_fingerprint_is_order_and_set_order_stable(self) -> None:
        first = _record("characters/denia.safetensors")
        second = _record(
            "styles/ink.safetensors",
            model_name="warm ink style",
            description="artist style",
            trigger_words=("warm ink", "paper texture"),
            tags=("style", "artist"),
            aliases=(),
            character_name="",
            source_work="",
            sha256="def456",
        )
        reordered_second = replace(
            second,
            trigger_words=tuple(reversed(second.trigger_words)),
            tags=tuple(reversed(second.tags)),
        )

        self.assertEqual(
            LoraArchiveService.catalog_fingerprint((first, second)),
            LoraArchiveService.catalog_fingerprint((reordered_second, first)),
        )
        self.assertNotEqual(
            LoraArchiveService.catalog_fingerprint((first, second)),
            LoraArchiveService.catalog_fingerprint(
                (first, replace(second, description="changed description"))
            ),
        )

    def test_selects_all_single_and_multiple_without_fuzzy_guess(self) -> None:
        records = (
            _record("characters/denia.safetensors"),
            _record("styles/ink.safetensors", model_name="warm ink style"),
        )

        self.assertEqual(LoraArchiveService.select_records(records), records)
        self.assertEqual(
            [item.name for item in LoraArchiveService.select_records(records, ["denia"])],
            ["characters/denia.safetensors"],
        )
        self.assertEqual(
            [
                item.name
                for item in LoraArchiveService.select_records(
                    records, ["styles/ink", "characters/denia"]
                )
            ],
            ["styles/ink.safetensors", "characters/denia.safetensors"],
        )

    def test_ambiguous_basename_is_rejected(self) -> None:
        records = (_record("a/denia.safetensors"), _record("b/denia.safetensors"))
        with self.assertRaises(LoraArchiveError):
            LoraArchiveService.select_records(records, ["denia"])


class PromptAndParserTests(unittest.TestCase):
    def test_prompt_contains_complete_civitai_material(self) -> None:
        long_description = "description-" + ("detail " * 1500)
        record = _record(
            "characters/denia.safetensors",
            description=long_description,
            file_path="E:/ComfyUI/models/loras/characters/denia.safetensors",
        )

        prompt = LoraArchiveService.build_prompt((record,))

        self.assertIn(long_description, prompt.user_prompt)
        self.assertIn("denia (wuthering waves)", prompt.user_prompt)
        self.assertIn("black coat", prompt.user_prompt)
        self.assertIn("Wuthering Waves / 鸣潮", prompt.user_prompt)
        self.assertIn("Civitai", prompt.system_prompt)

    def test_parser_accepts_grounded_strict_json_and_preserves_order(self) -> None:
        denia = _record("characters/denia.safetensors")
        style = _record(
            "styles/ink.safetensors",
            model_name="warm ink style",
            description="warm ink style for paper texture",
            trigger_words=("warm ink",),
            tags=("style",),
            aliases=(),
            character_name="",
            source_work="",
        )
        output = _response(
            _classification(style, category="artist_style"),
            _classification(denia),
        )

        parsed = LoraArchiveService.parse_response(output, (denia, style))

        self.assertEqual([item["name"] for item in parsed], [denia.name, style.name])
        self.assertEqual(parsed[1]["category"], "artist_style")

    def test_parser_rejects_unknown_category_and_invented_evidence(self) -> None:
        record = _record("characters/denia.safetensors")
        item = _classification(record)
        item["category"] = "concept"
        with self.assertRaises(LoraArchiveError):
            LoraArchiveService.parse_response(_response(item), (record,))

        item = _classification(record)
        item["evidence"] = ["invented fact not in metadata"]
        with self.assertRaises(LoraArchiveError):
            LoraArchiveService.parse_response(_response(item), (record,))

    def test_parser_requires_uncertain_result_to_be_unclassified(self) -> None:
        record = _record("characters/denia.safetensors")
        item = _classification(record)
        item["confidence"] = "low"
        with self.assertRaises(LoraArchiveError):
            LoraArchiveService.parse_response(_response(item), (record,))


class ArchivePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.index_path = Path(self.temp_dir.name) / "lora_archive.json"
        self.service = LoraArchiveService(self.index_path)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_selected_archive_keeps_pending_then_full_completion_clears_change(self) -> None:
        denia = _record("characters/denia.safetensors")
        style = _record(
            "styles/ink.safetensors",
            model_name="warm ink style",
            description="warm ink style for paper texture",
            trigger_words=("warm ink",),
            tags=("style",),
            aliases=(),
            character_name="",
            source_work="",
            sha256="stylehash",
        )

        async def callback(_system: str, user: str) -> str:
            payload = json.loads(user[user.index("{") :])
            items = []
            for raw in payload["records"]:
                record = denia if raw["name"] == denia.name else style
                category = "character" if record is denia else "artist_style"
                items.append(_classification(record, category=category))
            return _response(*items)

        first = await self.service.archive_with_llm(
            (denia, style), callback, selected_names=[denia.name]
        )
        self.assertTrue(first.status.changed)
        self.assertEqual(first.status.added, (style.name,))

        second = await self.service.archive_with_llm(
            (denia, style), callback, selected_names=[style.name]
        )
        self.assertFalse(second.status.changed)
        self.assertEqual(len(self.service.list_entries()), 2)

    async def test_manual_override_survives_rearchive(self) -> None:
        record = _record("characters/denia.safetensors")

        async def callback(_system: str, _user: str) -> str:
            return _response(_classification(record))

        await self.service.archive_with_llm((record,), callback)
        self.service.set_manual_override(
            record.name,
            {"category": "mixed", "artist_style_names": ["manual style"]},
        )
        await self.service.archive_with_llm((record,), callback)

        entry = self.service.list_entries()[0]
        self.assertEqual(entry["classification"]["category"], "character")
        self.assertEqual(entry["manual_override"]["category"], "mixed")
        self.assertEqual(entry["effective"]["category"], "mixed")
        self.assertEqual(entry["effective"]["artist_style_names"], ["manual style"])

    async def test_sync_catalog_presence_acknowledges_deletion_without_llm(self) -> None:
        denia = _record("characters/denia.safetensors")
        style = _record(
            "styles/ink.safetensors",
            model_name="warm ink style",
            description="warm ink style",
            trigger_words=("warm ink",),
            tags=("style",),
            aliases=(),
            character_name="",
            source_work="",
            sha256="stylehash",
        )

        async def callback(_system: str, user: str) -> str:
            payload = json.loads(user[user.index("{") :])
            by_name = {denia.name: denia, style.name: style}
            return _response(
                *[
                    _classification(
                        by_name[item["name"]],
                        category=(
                            "character" if item["name"] == denia.name else "artist_style"
                        ),
                    )
                    for item in payload["records"]
                ]
            )

        await self.service.archive_with_llm((denia, style), callback)
        before = self.service.catalog_status((denia,))
        self.assertEqual(before.removed, (style.name,))

        after = self.service.sync_catalog_presence((denia,))

        self.assertFalse(after.changed)
        self.assertEqual(after.removed, ())
        self.assertEqual([entry["name"] for entry in self.service.list_entries()], [denia.name])
        all_entries = self.service.list_entries(present_only=False)
        removed_entry = next(entry for entry in all_entries if entry["name"] == style.name)
        self.assertFalse(removed_entry["present"])

    async def test_batching_and_unchanged_skip(self) -> None:
        records = tuple(_record(f"characters/denia-{index}.safetensors") for index in range(3))
        calls = 0

        async def callback(_system: str, user: str) -> str:
            nonlocal calls
            calls += 1
            payload = json.loads(user[user.index("{") :])
            by_name = {record.name: record for record in records}
            return _response(
                *[_classification(by_name[item["name"]]) for item in payload["records"]]
            )

        result = await self.service.archive_with_llm(
            records, callback, batch_size=2
        )
        self.assertEqual(result.batch_count, 2)
        self.assertEqual(calls, 2)

        skipped = await self.service.archive_with_llm(
            records, callback, skip_when_unchanged=True
        )
        self.assertTrue(skipped.skipped)
        self.assertEqual(calls, 2)

    async def test_archive_from_catalog_refreshes_and_enriches_first(self) -> None:
        base = _record(
            "characters/denia.safetensors",
            description="",
            file_path="E:/loras/denia.safetensors",
        )

        class Catalog:
            def __init__(self):
                self.refreshed = 0
                self.enriched = 0

            async def refresh_for_operation(self):
                self.refreshed += 1
                return (base,)

            async def _enrich_manager_detail(self, record):
                self.enriched += 1
                return replace(record, description="full Civitai version description")

        catalog = Catalog()

        async def callback(_system: str, user: str) -> str:
            self.assertIn("full Civitai version description", user)
            enriched = replace(base, description="full Civitai version description")
            return _response(_classification(enriched))

        result = await self.service.archive_from_catalog(catalog, callback)

        self.assertFalse(result.skipped)
        self.assertEqual(catalog.refreshed, 1)
        self.assertEqual(catalog.enriched, 1)
        self.assertFalse(result.status.changed)

        skipped = await self.service.archive_from_catalog(
            catalog, callback, skip_when_unchanged=True
        )
        self.assertTrue(skipped.skipped)
        self.assertEqual(catalog.refreshed, 2)
        self.assertEqual(catalog.enriched, 1)

    async def test_custom_archive_prompt_file_is_used(self) -> None:
        prompt_path = Path(self.temp_dir.name) / "archive_prompt.txt"
        prompt_path.write_text("CUSTOM ARCHIVE RULES", encoding="utf-8")
        service = LoraArchiveService(self.index_path, prompt_path)
        record = _record("characters/denia.safetensors")
        seen_system_prompts: list[str] = []

        async def callback(system_prompt: str, _user_prompt: str) -> str:
            seen_system_prompts.append(system_prompt)
            return _response(_classification(record))

        await service.archive_with_llm((record,), callback)

        self.assertEqual(seen_system_prompts, ["CUSTOM ARCHIVE RULES"])


if __name__ == "__main__":
    unittest.main()
