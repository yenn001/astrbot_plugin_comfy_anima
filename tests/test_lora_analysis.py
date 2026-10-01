"""Tests for resilient per-item LoRA semantic analysis."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ..services.lora_analysis import (
    LoraAnalysisError,
    LoraAnalysisPipeline,
)
from ..services.lora_detail import (
    FileStatus,
    LoraDetailV2,
    MetadataHealth,
)
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
)
from ..services.task_store import TaskStore


def _detail(name: str, digest: str, *, character: str = "") -> LoraDetailV2:
    file_name = name.rsplit("/", 1)[-1]
    return LoraDetailV2(
        asset_id=f"sha256:{digest}",
        name=name,
        file_name=file_name,
        folder=name.rsplit("/", 1)[0] if "/" in name else "",
        model_name="Denia from Wuthering Waves" if "denia" in name else "Warm Ink",
        version_name="v1",
        base_model="Anima Base 1.0",
        model_description=(
            "Denia is a character from Wuthering Waves."
            if "denia" in name
            else "A warm ink illustration style by Example Artist."
        ),
        version_description="Training version notes.",
        trigger_words=("denia_wuwa",) if "denia" in name else ("warm ink",),
        tags=("Wuthering Waves", "character") if "denia" in name else ("style", "ink"),
        category="character" if "denia" in name else "artist_style",
        aliases=("local-derived",),
        character_name=character,
        source_work="Wuthering Waves" if "denia" in name else "",
        file_status=FileStatus(
            loadable=True,
            sha256=digest,
            from_civitai=True,
        ),
        metadata_health=MetadataHealth(
            status="complete",
            available_sources=(
                "fresh_record",
                "manager_list",
                "manager_metadata",
                "model_description",
            ),
        ),
    )


def _character_response(detail: LoraDetailV2, *, confidence: float = 0.94) -> str:
    return json.dumps(
        {
            "asset_id": detail.asset_id,
            "lora_name": detail.name,
            "category": "character",
            "character_names": ["Denia", "达妮娅"],
            "source_works": ["Wuthering Waves", "鸣潮"],
            "artist_style_names": [],
            "aliases": ["达妮娅", "Denia Wuwa"],
            "summary": "《鸣潮》角色达妮娅的角色 LoRA。",
            "confidence": confidence,
            "evidence": [
                {
                    "source": "descriptions.model",
                    "quote": "Denia is a character from Wuthering Waves.",
                },
                {"source": "trigger_words[0]", "quote": "denia_wuwa"},
            ],
        },
        ensure_ascii=False,
    )


def _style_response(detail: LoraDetailV2) -> str:
    return json.dumps(
        {
            "asset_id": detail.asset_id,
            "lora_name": detail.name,
            "category": "artist_style",
            "character_names": [],
            "source_works": [],
            "artist_style_names": ["Example Artist", "暖墨风格"],
            "aliases": ["暖墨", "warm ink"],
            "summary": "Example Artist 的暖色墨绘风格 LoRA。",
            "confidence": "high",
            "evidence": [{"source": "descriptions.model"}],
        },
        ensure_ascii=False,
    )


class LoraSemanticPromptContractTests(unittest.TestCase):
    def test_runtime_prompt_covers_functional_categories_and_output_duties(
        self,
    ) -> None:
        prompt = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "lora_semantic_analysis.txt"
        ).read_text(encoding="utf-8")

        for category in (
            "speed_sampling",
            "quality_enhancement",
            "detail_restoration",
            "composition_pose",
            "lighting_color",
            "background_environment",
            "clothing_concept",
        ):
            self.assertIn(category, prompt)
        self.assertIn("功能型类别不要求填写 character_names", prompt)
        self.assertIn("功能型 LoRA 至少提供一个能说明用途的可搜索名称", prompt)
        self.assertIn("summary 必须说明它控制什么", prompt)
        self.assertIn("角色 LoRA 带有服装触发词时仍优先归为 character", prompt)


class LoraAnalysisPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = TaskStore(self.root / "tasks.sqlite3", cleanup_interval=1000)
        self.index = LoraSemanticIndex.empty()
        self.index_path = self.root / "lora-semantic-v2.json"
        self.pipeline = LoraAnalysisPipeline(
            self.index,
            self.index_path,
            self.store,
            heartbeat_interval=0.05,
        )

    async def asyncTearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    async def test_think_and_fenced_json_are_cleaned_and_saved_immediately(
        self,
    ) -> None:
        detail = _detail("characters/denia.safetensors", "a" * 64)

        async def callback(_system: str, _user: str) -> str:
            return (
                "<think>private reasoning</think>\n```json\n"
                + _character_response(detail)
                + "\n```"
            )

        result = await self.pipeline.run(
            (detail,), callback, requested_by="admin", run_id="rich-run"
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(result.items[0].summary, "《鸣潮》角色达妮娅的角色 LoRA。")
        self.assertEqual(result.items[0].character_names, ("Denia", "达妮娅"))
        self.assertEqual(result.items[0].source_works, ("Wuthering Waves", "鸣潮"))
        self.assertIn("descriptions.model", result.items[0].evidence[0])
        restored = LoraSemanticIndex.load(self.index_path)
        entry = restored.entries[semantic_identity_key(detail.name, "a" * 64)]
        self.assertEqual(entry.analysis_status, "searchable")
        self.assertIn("达妮娅", entry.effective_values("character_names"))
        self.assertTrue(
            all(
                fact.source == "llm_inferred"
                for fact in entry.character_names
                if fact.value in {"Denia", "达妮娅"}
            )
        )
        self.assertTrue(entry.source_fingerprint)
        self.assertEqual(entry.analysis_summary, "《鸣潮》角色达妮娅的角色 LoRA。")
        self.assertEqual(entry.analysis_confidence, 0.94)

        task = self.store.get_task("rich-run")
        self.assertEqual(task["status"], "succeeded")
        events = self.store.read_events(run_id="rich-run")["entries"]
        self.assertIn("item_saved", [event["event_code"] for event in events])
        persisted_text = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("private reasoning", persisted_text)
        self.assertNotIn("Denia is a character from Wuthering Waves", persisted_text)

    async def test_precreated_queued_task_is_reused_by_background_pipeline(
        self,
    ) -> None:
        detail = _detail("characters/denia.safetensors", "9" * 64)
        self.store.create_task(
            "lora_semantic_analysis",
            run_id="queued-run",
            status="queued",
            total_items=1,
        )

        async def callback(_system: str, _user: str) -> str:
            return _character_response(detail)

        result = await self.pipeline.run((detail,), callback, run_id="queued-run")

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(self.store.get_task("queued-run")["status"], "succeeded")

    async def test_invalid_first_response_is_repaired_with_error_feedback(self) -> None:
        detail = _detail("characters/denia.safetensors", "b" * 64)
        prompts: list[str] = []

        async def callback(_system: str, user_prompt: str) -> str:
            prompts.append(user_prompt)
            if len(prompts) == 1:
                return json.dumps(
                    {
                        "category": "character",
                        "character_names": [],
                        "summary": "missing the required identity",
                        "confidence": 0.9,
                        "evidence": [{"source": "descriptions.model"}],
                    }
                )
            return _character_response(detail)

        result = await self.pipeline.run((detail,), callback, run_id="repair-run")

        self.assertTrue(result.items[0].success)
        self.assertEqual(result.items[0].attempts, 2)
        self.assertIn("missing_character", prompts[1])
        events = self.store.read_events(run_id="repair-run")["entries"]
        self.assertEqual(
            [
                event["attempt"]
                for event in events
                if event["event_code"] == "repair_requested"
            ],
            [2],
        )

    def test_functional_category_response_is_accepted_without_identity_names(
        self,
    ) -> None:
        detail = replace(
            _detail("quality/highres.safetensors", "8" * 64),
            model_name="Anima High Resolution Quality Boost",
            model_description="A quality enhancement LoRA for high-resolution output.",
            trigger_words=("highres quality",),
            tags=("quality enhancement", "highres"),
            category="quality_enhancement",
            character_name="",
            source_work="",
        )
        response = json.dumps(
            {
                "asset_id": detail.asset_id,
                "lora_name": detail.name,
                "category": "quality_enhancement",
                "character_names": [],
                "source_works": [],
                "artist_style_names": [],
                "aliases": ["画质增强"],
                "summary": "用于提升高分辨率输出质量的功能型 LoRA。",
                "confidence": 0.92,
                "evidence": [
                    {
                        "source": "descriptions.model",
                        "quote": "quality enhancement LoRA",
                    }
                ],
            },
            ensure_ascii=False,
        )

        proposal = self.pipeline.parse_response(response, detail)

        self.assertEqual(proposal.category, "quality_enhancement")
        self.assertEqual(proposal.character_names, ())
        self.assertEqual(proposal.artist_style_names, ())

    async def test_one_bad_item_does_not_rollback_successful_items(self) -> None:
        good = _detail("characters/denia.safetensors", "c" * 64)
        bad = _detail("styles/bad.safetensors", "d" * 64)
        attempts = {good.name: 0, bad.name: 0}

        async def callback(_system: str, user_prompt: str) -> str:
            if good.name in user_prompt:
                attempts[good.name] += 1
                return _character_response(good)
            attempts[bad.name] += 1
            return "not json and never valid"

        result = await self.pipeline.run((good, bad), callback, run_id="partial-run")

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(attempts[good.name], 1)
        self.assertEqual(attempts[bad.name], 3)
        restored = LoraSemanticIndex.load(self.index_path)
        self.assertIsNotNone(
            restored.entries.get(semantic_identity_key(good.name, "c" * 64))
        )
        failed_entry = restored.entries.get(semantic_identity_key(bad.name, "d" * 64))
        self.assertIsNotNone(failed_entry)
        self.assertEqual(failed_entry.analysis_status, "failed")
        self.assertEqual(failed_entry.error, "invalid_json")
        task = self.store.get_task("partial-run")
        self.assertEqual(task["completed_items"], 1)
        self.assertEqual(task["failed_items"], 1)

    async def test_existing_observed_derived_and_manual_facts_survive_reanalysis(
        self,
    ) -> None:
        detail = _detail(
            "characters/denia.safetensors", "e" * 64, character="Local Denia"
        )
        key = semantic_identity_key(detail.name, "e" * 64)
        previous = SemanticEntry(
            identity_key=key,
            canonical_name=detail.name,
            sha256="e" * 64,
            analysis_status="searchable",
            category=(SemanticFact("character", "observed"),),
            character_names=(
                SemanticFact("Observed Denia", "observed"),
                SemanticFact("Old LLM Name", "llm_inferred"),
                SemanticFact("Manual Denia", "manual"),
            ),
            source_works=(SemanticFact("Observed Work", "derived"),),
            aliases=(SemanticFact("manual-short", "manual"),),
        )
        self.index.upsert(previous)

        async def callback(_system: str, _user: str) -> str:
            return _character_response(detail)

        await self.pipeline.run((detail,), callback, run_id="preserve-run")
        entry = self.index.entries[key]
        sources_and_names = {
            (fact.source, fact.value) for fact in entry.character_names
        }
        self.assertIn(("observed", "Observed Denia"), sources_and_names)
        self.assertIn(("manual", "Manual Denia"), sources_and_names)
        self.assertIn(("derived", "Local Denia"), sources_and_names)
        self.assertIn(("llm_inferred", "达妮娅"), sources_and_names)
        self.assertNotIn(("llm_inferred", "Old LLM Name"), sources_and_names)
        self.assertEqual(entry.effective_values("character_names"), ("Manual Denia",))

    async def test_selected_names_are_exact_and_only_selected_item_is_called(
        self,
    ) -> None:
        character = _detail("characters/denia.safetensors", "f" * 64)
        style = _detail("styles/warm-ink.safetensors", "1" * 64)
        calls: list[str] = []

        async def callback(_system: str, user_prompt: str) -> str:
            calls.append(user_prompt)
            return _style_response(style)

        result = await self.pipeline.run(
            (character, style),
            callback,
            selected_names=(style.name,),
            run_id="selected-run",
        )

        self.assertEqual(result.updated_names, (style.name,))
        self.assertEqual(len(calls), 1)
        self.assertNotIn(character.name, calls[0])

        with self.assertRaises(LoraAnalysisError):
            await self.pipeline.run(
                (character, style),
                callback,
                selected_names=("warm-ink.safetensors",),
            )

    async def test_low_confidence_result_requires_review(self) -> None:
        detail = _detail("characters/denia.safetensors", "2" * 64)

        async def callback(_system: str, _user: str) -> str:
            return _character_response(detail, confidence=0.45)

        result = await self.pipeline.run((detail,), callback, run_id="review-run")

        self.assertEqual(result.items[0].analysis_status, "review_needed")
        entry = self.index.entries[semantic_identity_key(detail.name, "2" * 64)]
        self.assertFalse(entry.overlay_valid)

    async def test_mapping_response_and_trailing_comma_are_tolerated(self) -> None:
        detail = _detail("styles/warm-ink.safetensors", "3" * 64)
        mapping = json.loads(_style_response(detail))

        parsed = self.pipeline.parse_response(mapping, detail)
        self.assertEqual(parsed.category, "artist_style")
        self.assertEqual(parsed.confidence, 0.9)

        text = "```json\n" + _style_response(detail)[:-1] + ",}\n```"
        parsed_trailing = self.pipeline.parse_response(text, detail)
        self.assertEqual(parsed_trailing.aliases, ("暖墨", "warm ink"))


if __name__ == "__main__":
    unittest.main()
