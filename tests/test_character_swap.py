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
    aliases=(),
    source_work: str = "",
) -> LoraRecord:
    record = LoraRecord(
        name=name,
        sha256=sha256,
        category=category,
        character_name=character_name,
        trigger_words=tuple(triggers),
        model_name=model_name or f"{character_name} LoRA",
        aliases=tuple(aliases),
        source_work=source_work,
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

    def test_no_character_lora_is_parsed_from_command_and_natural_language(self) -> None:
        command = parse_character_swap_request(
            "达妮娅 -> 米浴 --no-character-lora | 1girl, denia_wuwa"
        )
        self.assertFalse(command.use_target_lora)

        natural_command = parse_character_swap_request(
            "达妮娅 -> 赛马娘的米浴，无需使用角色LoRA"
        )
        self.assertEqual(natural_command.target_query, "赛马娘的米浴")
        self.assertFalse(natural_command.use_target_lora)

        natural = parse_natural_character_swap(
            "把角色换成赛马娘的米浴，无需使用角色LoRA"
        )
        self.assertIsNotNone(natural)
        assert natural is not None
        self.assertEqual(natural.source_query, "")
        self.assertEqual(natural.target_query, "赛马娘的米浴")
        self.assertFalse(natural.use_target_lora)

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

    def test_work_possessive_phrase_resolves_and_typo_only_suggests(self) -> None:
        rice = _record(
            "characters/rice_shower.safetensors",
            "米浴",
            "rice1234",
            aliases=("Rice Shower",),
            source_work="赛马娘",
        )
        index = LoraSemanticIndex.empty()

        self.assertIs(
            resolve_character_record((rice,), "赛马娘的米浴", index),
            rice,
        )
        with self.assertRaises(CharacterSwapError) as raised:
            resolve_character_record((rice,), "赛马娘的米欲", index)
        self.assertEqual(raised.exception.code, "character_suggestion")
        self.assertIn("米浴", raised.exception.user_message)

    def test_unproven_record_alias_and_work_title_cannot_authorize_swap(self) -> None:
        kiki = _record(
            "characters/character_full_name.safetensors",
            "Character Full Name",
            "kiki1234",
            aliases=("kiki",),
            source_work="Example Work",
        )
        for query in ("kiki", "Example Work"):
            with self.subTest(query=query):
                with self.assertRaises(CharacterSwapError) as raised:
                    resolve_character_record(
                        (kiki,),
                        query,
                        LoraSemanticIndex.empty(),
                    )
                self.assertEqual(raised.exception.code, "character_not_found")

    def test_semantic_alias_combines_with_work_title(self) -> None:
        kiki = _record(
            "characters/character_full_name.safetensors",
            "Character Full Name",
            "kiki1234",
            source_work="Example Work",
        )
        entry = SemanticEntry(
            identity_key=semantic_identity_key(kiki.name, kiki.sha256),
            canonical_name=kiki.name,
            sha256=kiki.sha256,
            analysis_status="searchable",
            category=(SemanticFact("character", "manual"),),
            character_names=(SemanticFact(kiki.character_name, "manual"),),
            source_works=(SemanticFact("Example Work", "manual"),),
            aliases=(SemanticFact("kiki", "manual"),),
            source_fingerprint=kiki.source_fingerprint,
            analysis_confidence=1.0,
        )
        index = LoraSemanticIndex(entries={entry.identity_key: entry})

        self.assertIs(
            resolve_character_record((kiki,), "Example Work的kiki", index),
            kiki,
        )

    def test_legacy_observed_alias_cannot_authorize_swap(self) -> None:
        record = _record(
            "characters/character_full_name.safetensors",
            "Character Full Name",
            "observed1234",
        )
        entry = SemanticEntry(
            identity_key=semantic_identity_key(record.name, record.sha256),
            canonical_name=record.name,
            sha256=record.sha256,
            analysis_status="searchable",
            category=(SemanticFact("character", "manual"),),
            character_names=(SemanticFact(record.character_name, "manual"),),
            aliases=(SemanticFact("legacy-trained-word", "observed"),),
            source_fingerprint=record.source_fingerprint,
            analysis_confidence=1.0,
        )
        with self.assertRaises(CharacterSwapError) as raised:
            resolve_character_record(
                (record,),
                "legacy-trained-word",
                LoraSemanticIndex(entries={entry.identity_key: entry}),
            )
        self.assertEqual(raised.exception.code, "character_not_found")


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

    def test_missing_target_lora_uses_semantic_tags_without_character_lora(self) -> None:
        request = CharacterSwapRequest("Denia", "赛马娘的米浴")
        preparation = self.planner.prepare(
            request,
            positive_prompt=(
                "<lora:characters/denia:1.0>, <lora:styles/warm-ink:0.4>, "
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "from side, rainy street, warm light, masterpiece"
            ),
            negative_prompt="rice shower (umamusume), brown hair, low quality",
            records=self.records,
            fallback_target_tags=(
                "rice shower (umamusume)",
                "brown hair",
                "purple eyes",
                "horse ears",
            ),
        )
        plan = self.planner.finalize(
            preparation,
            self._classification(
                preparation,
                target_appearance_trigger_ids=[1, 2, 3],
            ),
        )

        self.assertIsNone(plan.target_record)
        self.assertIn("rice shower (umamusume)", plan.prompt)
        self.assertIn("brown hair", plan.prompt)
        self.assertIn("school uniform", plan.prompt)
        self.assertNotIn("denia_wuwa", plan.prompt)
        self.assertEqual(
            [(item.name, item.strength) for item in plan.loras],
            [("styles/warm-ink.safetensors", 0.4)],
        )
        self.assertNotIn("rice shower", plan.negative_prompt)

    def test_explicit_no_character_lora_skips_existing_target_lora(self) -> None:
        request = CharacterSwapRequest(
            "Denia",
            "Kallen Kaslana",
            use_target_lora=False,
        )
        preparation = self.planner.prepare(
            request,
            positive_prompt=(
                "<lora:characters/denia:1.0>, <lora:styles/warm-ink:0.4>, "
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "from side, rainy street, warm light, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
        )
        plan = self.planner.finalize(
            preparation,
            self._classification(
                preparation,
                target_appearance_trigger_ids=[1],
            ),
        )

        self.assertIsNone(plan.target_record)
        self.assertIs(preparation.target_metadata_record, self.kallen)
        self.assertIn("kallen_kaslana", plan.prompt)
        self.assertIn("white hair", plan.prompt)
        self.assertEqual(
            [(item.name, item.strength) for item in plan.loras],
            [("styles/warm-ink.safetensors", 0.4)],
        )

    def test_stale_category_cannot_hide_character_lora(self) -> None:
        hidden_character = _record(
            "legacy/hidden-character.safetensors",
            "Hidden Character",
            "aa55aa55",
            category="artist_style",
            triggers=("hidden_character",),
        )
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "Hidden Character",
                "Unknown Target",
                use_target_lora=False,
            ),
            positive_prompt=(
                "<lora:legacy/hidden-character:0.8>, 1girl, hidden_character, "
                "school uniform, standing, rainy street, masterpiece"
            ),
            negative_prompt="",
            records=(*self.records, hidden_character),
            fallback_target_tags=("unknown_target", "silver hair"),
        )

        self.assertEqual(
            [item.name for item in preparation.removed_character_loras],
            ["legacy/hidden-character"],
        )
        self.assertNotIn(
            "legacy/hidden-character.safetensors",
            [item.name for item in preparation.preserved_loras],
        )

    def test_no_character_lora_keeps_typo_suggestion_fail_closed(self) -> None:
        rice = _record(
            "characters/rice_shower.safetensors",
            "米浴",
            "rice1234",
            triggers=("rice_shower_(umamusume)", "brown hair"),
            source_work="赛马娘",
        )
        planner = CharacterSwapPlanner(LoraSemanticIndex.empty())
        with self.assertRaises(CharacterSwapError) as raised:
            planner.prepare(
                CharacterSwapRequest(
                    "Denia",
                    "赛马娘的米欲",
                    use_target_lora=False,
                ),
                positive_prompt="1girl, denia_wuwa, black hair",
                negative_prompt="",
                records=(*self.records, rice),
                fallback_target_tags=("rice_shower_(umamusume)",),
            )
        self.assertEqual(raised.exception.code, "character_suggestion")

    def test_semantic_fallback_injects_only_identity_and_appearance(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest("Denia", "Unknown Hero", use_target_lora=False),
            positive_prompt=(
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "from side, rainy street, warm light, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "unknown_hero_(example_work)",
                "white hair",
                "battle suit",
                "jumping",
                "best quality",
            ),
        )
        classification = self._classification(
            preparation,
            target_appearance_trigger_ids=[1],
            target_default_outfit_trigger_ids=[2],
        )
        plan = self.planner.finalize(preparation, classification)

        self.assertIn("unknown_hero_(example_work)", plan.prompt)
        self.assertIn("white hair", plan.prompt)
        self.assertIn("school uniform", plan.prompt)
        self.assertNotIn("battle suit", plan.prompt)
        self.assertNotIn("jumping", plan.prompt)
        self.assertEqual(plan.prompt.count("best quality"), 0)

    def test_missing_explicit_target_file_never_uses_semantic_fallback(self) -> None:
        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.prepare(
                CharacterSwapRequest("Denia", "characters/missing.safetensors"),
                positive_prompt="1girl, denia_wuwa, black hair",
                negative_prompt="",
                records=self.records,
                fallback_target_tags=("missing character",),
            )
        self.assertEqual(raised.exception.code, "character_not_found")

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

    def test_weighted_group_cannot_hide_source_identity(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest("Denia", "Kallen Kaslana"),
            positive_prompt=(
                "1girl, denia_wuwa, (denia_wuwa, black hair:1.2), "
                "school uniform, standing, rainy street, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
        )
        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[1],
            outfit_ids=[3],
            pose_action_ids=[4],
            scene_lighting_ids=[5],
            style_quality_ids=[0, 2, 6],
        )
        classification = self.planner.parse_classification(
            json.dumps(payload),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.finalize(preparation, classification)
        self.assertEqual(
            raised.exception.code,
            "source_identity_group_misclassified",
        )

    def test_weighted_negative_group_with_target_identity_is_removed(self) -> None:
        preparation = self._prepare(
            negative="(kallen_kaslana, low quality:1.2), bad hands"
        )
        plan = self.planner.finalize(
            preparation,
            self._classification(preparation),
        )

        self.assertNotIn("kallen_kaslana", plan.negative_prompt)
        self.assertEqual(plan.negative_prompt, "bad hands")


if __name__ == "__main__":
    unittest.main()
