"""Tests for fail-closed single-character semantic replacement."""

import json
import unittest
from dataclasses import replace

from ..services.character_swap import (
    CharacterSwapError,
    CharacterSwapPlanner,
    CharacterSwapRequest,
    SWAP_MODE_TARGET_OUTFIT,
    fit_canvas_to_aspect_ratio,
    parse_character_swap_request,
    parse_natural_character_swap,
    resolve_character_record,
)
from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
    semantic_source_fingerprint,
)


def _record(
    name: str,
    character_name: str,
    sha256: str,
    *,
    category: str = "character",
    triggers=(),
    model_name: str = "",
) -> LoraRecord:
    record = LoraRecord(
        name=name,
        sha256=sha256,
        category=category,
        character_name=character_name,
        trigger_words=tuple(triggers),
        model_name=model_name or f"{character_name} LoRA",
    )
    return replace(record, source_fingerprint=semantic_source_fingerprint(record))


def _semantic_entry(record: LoraRecord, alias: str, *, fingerprint=None):
    return SemanticEntry(
        identity_key=semantic_identity_key(record.name, record.sha256),
        canonical_name=record.name,
        sha256=record.sha256,
        analysis_status="searchable",
        category=(SemanticFact("character", "manual"),),
        character_names=(SemanticFact(record.character_name, "manual"),),
        aliases=(SemanticFact(alias, "manual"),),
        source_fingerprint=(
            record.source_fingerprint if fingerprint is None else fingerprint
        ),
        analysis_confidence=1.0,
    )


def _classification_payload(tag_count: int, **updates):
    payload = {
        "source_identity_ids": [],
        "outfit_ids": [],
        "pose_action_ids": [],
        "composition_ids": [],
        "scene_lighting_ids": [],
        "style_quality_ids": list(range(tag_count)),
        "uncertain_ids": [],
        "target_identity_trigger_id": 0,
        "target_appearance_trigger_ids": [],
        "target_default_outfit_trigger_ids": [],
        "subject_count": 1,
        "confidence": 0.96,
    }
    payload.update(updates)
    return payload


class CharacterSwapRequestTests(unittest.TestCase):
    def test_parses_tag_mode_and_bounded_options(self) -> None:
        request = parse_character_swap_request(
            '达妮娅 -> 卡莲 --weight 0.7 --preset "风格2（凛然）" '
            '--size 832x1216 --preview | 1girl, school uniform'
        )

        self.assertEqual(request.source_query, "达妮娅")
        self.assertEqual(request.target_query, "卡莲")
        self.assertEqual(request.target_lora_strength, 0.7)
        self.assertEqual(request.preset, "风格2（凛然）")
        self.assertEqual((request.width, request.height), (832, 1216))
        self.assertTrue(request.preview)
        self.assertIn("school uniform", request.tags)

    def test_rejects_unsafe_weight(self) -> None:
        with self.assertRaisesRegex(CharacterSwapError, "0.55"):
            parse_character_swap_request("A -> B --weight 1.2")

    def test_natural_language_parser_is_explicit(self) -> None:
        request = parse_natural_character_swap(
            "把引用图片里的达妮娅换成卡莲，衣服、姿势和背景保持不变"
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.source_query, "达妮娅")
        self.assertEqual(request.target_query, "卡莲")
        self.assertIsNone(parse_natural_character_swap("帮我画一个卡莲"))
        self.assertIsNone(parse_natural_character_swap("把画面背景换成夜晚"))

    def test_canvas_preserves_ratio_near_one_megapixel(self) -> None:
        width, height = fit_canvas_to_aspect_ratio(4000, 2000)
        self.assertEqual(width % 64, 0)
        self.assertEqual(height % 64, 0)
        self.assertAlmostEqual(width / height, 2.0, delta=0.15)
        self.assertLessEqual(width * height, 1_300_000)


class CharacterResolverTests(unittest.TestCase):
    def test_manual_fresh_alias_resolves_target(self) -> None:
        kallen = _record(
            "characters/kallen.safetensors",
            "Kallen Kaslana",
            "bb22cc33",
            triggers=("kallen_kaslana", "white hair"),
        )
        entry = _semantic_entry(kallen, "卡莲")
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        self.assertIs(resolve_character_record((kallen,), "卡莲", index), kallen)

    def test_stale_alias_is_rejected(self) -> None:
        kallen = _record(
            "characters/kallen.safetensors",
            "Kallen Kaslana",
            "bb22cc33",
            triggers=("kallen_kaslana",),
        )
        entry = _semantic_entry(kallen, "卡莲", fingerprint="old-fingerprint")
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        with self.assertRaisesRegex(CharacterSwapError, "未在最新"):
            resolve_character_record((kallen,), "卡莲", index)

    def test_shared_character_name_is_ambiguous(self) -> None:
        first = _record("a/kallen.safetensors", "Kallen", "aa11aa11")
        second = _record("b/variant-two.safetensors", "Kallen", "bb22bb22")

        with self.assertRaisesRegex(CharacterSwapError, "多个 LoRA"):
            resolve_character_record(
                (first, second),
                "Kallen",
                LoraSemanticIndex.empty(),
            )

        self.assertIs(
            resolve_character_record(
                (first, second),
                "a/kallen.safetensors",
                LoraSemanticIndex.empty(),
            ),
            first,
        )


class CharacterSwapPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.denia = _record(
            "characters/denia.safetensors",
            "Denia",
            "aa11bb22",
            triggers=("denia_wuwa", "black hair", "school uniform"),
        )
        self.kallen = _record(
            "characters/kallen.safetensors",
            "Kallen Kaslana",
            "cc33dd44",
            triggers=("kallen_kaslana", "white hair", "battle suit"),
        )
        self.style = _record(
            "styles/warm-ink.safetensors",
            "",
            "ee55ff66",
            category="artist_style",
            triggers=("warm ink style",),
            model_name="Warm Ink",
        )
        self.planner = CharacterSwapPlanner(LoraSemanticIndex.empty())
        self.records = (self.denia, self.kallen, self.style)

    def _prepare(self, *, mode="keep-outfit", prompt=None, negative=""):
        return self.planner.prepare(
            CharacterSwapRequest(
                source_query="Denia",
                target_query="Kallen Kaslana",
                mode=mode,
            ),
            positive_prompt=prompt
            or (
                "<lora:characters/denia:1.0>, "
                "<lora:styles/warm-ink:0.4>, "
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "from side, rainy street, warm light, masterpiece"
            ),
            negative_prompt=negative,
            records=self.records,
        )

    def _classification(self, preparation, **updates):
        # Default tag layout from _prepare:
        # 0 subject, 1-2 source identity, 3 outfit, 4 action, 5 composition,
        # 6-7 scene/lighting, 8 style/quality.
        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[1, 2],
            outfit_ids=[3],
            pose_action_ids=[4],
            composition_ids=[5],
            scene_lighting_ids=[6, 7],
            style_quality_ids=[0, 8],
            **updates,
        )
        return self.planner.parse_classification(
            json.dumps(payload),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

    def test_keep_outfit_replaces_only_identity_and_character_lora(self) -> None:
        preparation = self._prepare(
            negative="kallen_kaslana, white hair, low quality"
        )
        plan = self.planner.finalize(
            preparation,
            self._classification(
                preparation,
                target_appearance_trigger_ids=[1],
            ),
        )

        self.assertNotIn("denia_wuwa", plan.prompt)
        self.assertNotIn("black hair", plan.prompt)
        self.assertIn("school uniform", plan.prompt)
        self.assertIn("standing", plan.prompt)
        self.assertIn("rainy street", plan.prompt)
        self.assertIn("kallen_kaslana", plan.prompt)
        self.assertNotIn("kallen_kaslana", plan.negative_prompt)
        self.assertNotIn("white hair", plan.negative_prompt)
        self.assertEqual(
            [(item.name, item.strength) for item in plan.loras],
            [
                ("styles/warm-ink.safetensors", 0.4),
                ("characters/kallen.safetensors", 0.65),
            ],
        )
        self.assertTrue(plan.suppress_default_style)

    def test_target_outfit_requires_and_uses_metadata_terms(self) -> None:
        preparation = self._prepare(mode=SWAP_MODE_TARGET_OUTFIT)
        classification = self._classification(
            preparation,
            target_default_outfit_trigger_ids=[2],
        )
        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("school uniform", plan.prompt)
        self.assertIn("battle suit", plan.prompt)

    def test_target_outfit_fails_when_metadata_cannot_identify_outfit(self) -> None:
        preparation = self._prepare(mode=SWAP_MODE_TARGET_OUTFIT)
        with self.assertRaisesRegex(CharacterSwapError, "元数据不足"):
            self.planner.finalize(
                preparation,
                self._classification(preparation),
            )

    def test_multiple_character_loras_are_rejected(self) -> None:
        third = _record(
            "characters/third.safetensors",
            "Third",
            "11223344",
            triggers=("third_identity",),
        )
        with self.assertRaisesRegex(CharacterSwapError, "多个不同角色 LoRA"):
            self.planner.prepare(
                CharacterSwapRequest("Denia", "Kallen Kaslana"),
                positive_prompt=(
                    "<lora:characters/denia:1>, <lora:characters/third:1>, "
                    "1girl, denia_wuwa"
                ),
                negative_prompt="",
                records=(*self.records, third),
            )

    def test_malformed_and_duplicate_lora_tags_are_rejected(self) -> None:
        with self.assertRaisesRegex(CharacterSwapError, "残缺或非法"):
            self._prepare(
                prompt="<lora:characters/denia:not-a-number>, 1girl, denia_wuwa"
            )
        with self.assertRaisesRegex(CharacterSwapError, "重复指定"):
            self._prepare(
                prompt=(
                    "<lora:characters/denia:0.8>, "
                    "<lora:characters/denia.safetensors:0.7>, "
                    "1girl, denia_wuwa"
                )
            )

    def test_low_confidence_and_uncertain_tags_fail_closed(self) -> None:
        preparation = self._prepare()
        with self.assertRaisesRegex(CharacterSwapError, "置信度"):
            self.planner.finalize(
                preparation,
                self._classification(preparation, confidence=0.5),
            )

        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[1, 2],
            outfit_ids=[3],
            pose_action_ids=[4],
            composition_ids=[5],
            scene_lighting_ids=[6, 7],
            style_quality_ids=[0],
            uncertain_ids=[8],
        )
        uncertain = self.planner.parse_classification(
            json.dumps(payload),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )
        with self.assertRaisesRegex(CharacterSwapError, "无法可靠区分"):
            self.planner.finalize(preparation, uncertain)

    def test_classification_rejects_duplicate_or_missing_ids(self) -> None:
        preparation = self._prepare()
        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[0],
            outfit_ids=[0],
            style_quality_ids=list(range(1, len(preparation.tags))),
        )
        with self.assertRaisesRegex(CharacterSwapError, "重复 Tag ID"):
            self.planner.parse_classification(
                json.dumps(payload),
                tag_count=len(preparation.tags),
                target_trigger_count=len(preparation.target_trigger_words),
            )

    def test_obvious_outfit_cannot_be_deleted_as_source_identity(self) -> None:
        preparation = self._prepare()
        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[1, 2, 3],
            outfit_ids=[],
            pose_action_ids=[4],
            composition_ids=[5],
            scene_lighting_ids=[6, 7],
            style_quality_ids=[0, 8],
        )
        classification = self.planner.parse_classification(
            json.dumps(payload),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        with self.assertRaisesRegex(CharacterSwapError, "明显衣装"):
            self.planner.finalize(preparation, classification)

    def test_obvious_multi_subject_prompt_is_rejected(self) -> None:
        with self.assertRaisesRegex(CharacterSwapError, "单角色"):
            self._prepare(prompt="2girls, denia_wuwa, school uniform")


if __name__ == "__main__":
    unittest.main()
