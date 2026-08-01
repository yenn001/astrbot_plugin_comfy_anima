"""Tests for fail-closed single-character semantic replacement."""

import json
import unittest
from dataclasses import replace

from ..services.character_swap import (
    CharacterSwapError,
    CharacterSwapPlanner,
    CharacterSwapRequest,
    SWAP_MODE_TARGET_OUTFIT,
    _is_deterministic_outfit_term,
    fit_canvas_to_aspect_ratio,
    normalize_semantic_identity_payload,
    parse_character_swap_request,
    parse_natural_character_swap,
    parse_text_character_change_request,
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
        self.assertIsNone(parse_natural_character_swap("把泳装换成三点式"))
        self.assertIsNone(
            parse_natural_character_swap("把角色泳装换成三点式，加一条白丝大腿袜")
        )

    def test_natural_character_and_outfit_edit_are_kept_separate(self) -> None:
        request = parse_natural_character_swap(
            "把达妮娅换成米浴并穿红色礼服，构图和背景保持不变"
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.source_query, "达妮娅")
        self.assertEqual(request.target_query, "米浴")
        self.assertIn("穿红色礼服", request.edit_requirement)
        self.assertIn("构图和背景保持不变", request.edit_requirement)

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

    def test_required_character_lora_directive_is_not_treated_as_visual_edit(
        self,
    ) -> None:
        request = parse_text_character_change_request(
            "shifty \\(nikke\\), 1girl, blue hair, gym uniform, white thighhighs，"
            "把角色换成目标角色：《BlueArchive》的凯伊（kei），请使用Lora。"
        )

        self.assertEqual(request.target_query, "《BlueArchive》的凯伊(kei)")
        self.assertEqual(request.edit_requirement, "")
        self.assertTrue(request.use_target_lora)
        self.assertTrue(request.require_target_lora)

        natural = parse_natural_character_swap(
            "把图中的角色换成《BlueArchive》的凯伊，请务必使用角色 LoRA"
        )
        self.assertIsNotNone(natural)
        assert natural is not None
        self.assertEqual(natural.edit_requirement, "")
        self.assertTrue(natural.require_target_lora)

        command = parse_character_swap_request(
            "Shifty -> 《BlueArchive》的凯伊（kei），请使用Lora | "
            "shifty_(nikke), 1girl, gym uniform, white thighhighs"
        )
        self.assertEqual(command.target_query, "《BlueArchive》的凯伊(kei)")
        self.assertTrue(command.require_target_lora)

        style_phrase = parse_text_character_change_request(
            "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，使用LoRA风格001"
        )
        self.assertFalse(style_phrase.require_target_lora)
        self.assertEqual(style_phrase.edit_requirement, "使用LoRA风格001")
        spaced_style_phrase = parse_text_character_change_request(
            "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，使用 LoRA 风格001"
        )
        self.assertFalse(spaced_style_phrase.require_target_lora)

        for optional in (
            "可以使用角色 LoRA",
            "有的话使用角色 LoRA",
            "不建议使用角色 LoRA",
        ):
            with self.subTest(optional=optional):
                optional_request = parse_text_character_change_request(
                    "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，"
                    + optional
                )
                self.assertFalse(optional_request.require_target_lora)

        for negated in (
            "不要强制使用角色 LoRA",
            "不想使用角色 LoRA",
            "不一定要使用角色 LoRA",
            "别强制使用角色 LoRA",
        ):
            with self.subTest(negated=negated):
                negated_request = parse_text_character_change_request(
                    "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，"
                    + negated
                )
                self.assertFalse(negated_request.use_target_lora)
                self.assertFalse(negated_request.require_target_lora)

        conflict = parse_text_character_change_request(
            "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，"
            "请使用角色 LoRA，不要使用角色 LoRA"
        )
        self.assertFalse(conflict.use_target_lora)
        self.assertTrue(conflict.require_target_lora)

        reverse_conflict = parse_text_character_change_request(
            "shifty_(nikke), 1girl, gym uniform，把角色换成凯伊，"
            "不要使用角色 LoRA，请使用角色 LoRA"
        )
        self.assertFalse(reverse_conflict.use_target_lora)
        self.assertTrue(reverse_conflict.require_target_lora)

        leading = parse_text_character_change_request(
            "请使用角色 LoRA，shifty_(nikke), 1girl, gym uniform，"
            "把角色换成凯伊"
        )
        self.assertTrue(leading.require_target_lora)
        self.assertNotIn("LoRA", leading.tags)

    def test_text_character_change_parser_keeps_tags_and_edit_separate(self) -> None:
        request = parse_text_character_change_request(
            "1girl, roxy migurdia, blue hair, twin braids, school uniform, "
            "standing, looking at viewer，把角色换成甘雨，穿JK制服",
            preset="风格GZC",
            pipeline="rtx",
            prompt_expansion_mode="ultra",
            steps=20,
        )

        self.assertEqual(request.source_query, "")
        self.assertEqual(request.target_query, "甘雨")
        self.assertIn("roxy migurdia", request.tags)
        self.assertNotIn("把角色换成", request.tags)
        self.assertEqual(request.edit_requirement, "穿JK制服")
        self.assertEqual(request.preset, "风格GZC")
        self.assertEqual(request.pipeline, "rtx")
        self.assertEqual(request.prompt_expansion_mode, "ultra")
        self.assertEqual(request.steps, 20)

    def test_text_character_change_parser_forwards_generation_swap_options(
        self,
    ) -> None:
        request = parse_text_character_change_request(
            "1girl, silver hair, long hair, beach，"
            "把角色替换为目标角色鸣潮今汐",
            preset="风格007",
            mode=SWAP_MODE_TARGET_OUTFIT,
            target_lora_strength=0.7,
            preview=True,
            use_target_lora=False,
            width=512,
            height=768,
            negative_prompt="old identity",
            pipeline="rtx",
            prompt_expansion_mode="ultra",
            seed=42,
            steps=18,
            cfg=4.5,
            enable_upscale=True,
            denoise=0.35,
        )

        self.assertEqual(request.target_query, "鸣潮今汐")
        self.assertEqual(request.preset, "风格007")
        self.assertEqual(request.mode, SWAP_MODE_TARGET_OUTFIT)
        self.assertEqual(request.target_lora_strength, 0.7)
        self.assertTrue(request.preview)
        self.assertFalse(request.use_target_lora)
        self.assertEqual((request.width, request.height), (512, 768))
        self.assertEqual(request.negative_prompt, "old identity")
        self.assertEqual(request.pipeline, "rtx")
        self.assertEqual(request.prompt_expansion_mode, "ultra")
        self.assertEqual(request.seed, 42)
        self.assertEqual(request.steps, 18)
        self.assertEqual(request.cfg, 4.5)
        self.assertTrue(request.enable_upscale)
        self.assertEqual(request.denoise, 0.35)

    def test_text_character_change_parser_consumes_trailing_no_lora_phrase(
        self,
    ) -> None:
        request = parse_text_character_change_request(
            "1girl, roxy, blue hair, school uniform，把角色换成甘雨，"
            "换成白裙，无需使用角色 LoRA"
        )

        self.assertEqual(request.target_query, "甘雨")
        self.assertEqual(request.edit_requirement, "换成白裙")
        self.assertFalse(request.use_target_lora)
        self.assertNotIn("LoRA", request.edit_requirement)

    def test_target_role_and_confidence_override_are_normalized(self) -> None:
        request = parse_character_swap_request(
            "Denia -> 目标角色鸣潮的今汐 置信度满足0.5即可 | "
            "1girl, denia_wuwa, black hair, standing"
        )

        self.assertEqual(request.target_query, "鸣潮的今汐")
        self.assertEqual(
            request.ignored_control_directives,
            ("confidence_override",),
        )

    def test_text_character_change_parser_keeps_original_character_traits(self) -> None:
        request = parse_text_character_change_request(
            "1girl, blue hair, purple eyes, standing，把原角色换成"
            "原创角色：黑色长发、金色眼睛、精灵耳、左眼下有美人痣，其他保持不变"
        )

        self.assertIn("原创角色", request.target_query)
        self.assertIn("黑色长发", request.target_query)
        self.assertIn("美人痣", request.target_query)
        self.assertEqual(request.edit_requirement, "其他保持不变")

    def test_text_character_change_parser_requires_source_tags(self) -> None:
        with self.assertRaises(CharacterSwapError) as raised:
            parse_text_character_change_request("把角色换成甘雨")
        self.assertEqual(raised.exception.code, "text_character_change_tags_missing")

    def test_original_semantic_payload_requires_coherent_appearance(self) -> None:
        tags, confidence, ignored = normalize_semantic_identity_payload(
            {
                "canonical_identity_tag": "original character",
                "appearance_tags": [
                    "long black hair",
                    "golden eyes",
                    "elf ears",
                    "beauty mark under left eye",
                ],
                "confidence": 0.95,
            },
            allow_original=True,
        )

        self.assertEqual(tags[0], "original character")
        self.assertEqual(confidence, 0.95)
        self.assertEqual(ignored, 0)

        with self.assertRaises(CharacterSwapError) as raised:
            normalize_semantic_identity_payload(
                {
                    "canonical_identity_tag": "original character",
                    "appearance_tags": ["long black hair", "golden eyes"],
                    "confidence": 0.95,
                },
                allow_original=True,
            )
        self.assertEqual(
            raised.exception.code,
            "semantic_original_appearance_missing",
        )

    def test_known_character_rejects_more_than_four_appearance_candidates(
        self,
    ) -> None:
        with self.assertRaises(CharacterSwapError) as raised:
            normalize_semantic_identity_payload(
                {
                    "canonical_identity_tag": "jinhsi_(wuthering_waves)",
                    "appearance_tags": [
                        "long white hair",
                        "red eyes",
                        "dragon horns",
                        "pale skin",
                        "beauty mark under left eye",
                    ],
                    "confidence": 0.95,
                }
            )

        self.assertEqual(
            raised.exception.code,
            "semantic_target_appearance_excessive",
        )

    def test_unqualified_character_canonical_is_discovery_only(self) -> None:
        tags, confidence, ignored = normalize_semantic_identity_payload(
            {
                "canonical_identity_tag": "hatsune_miku",
                "identity_candidates": ["hatsune_miku"],
                "work_hints": ["vocaloid"],
                "appearance_tags": [],
                "confidence": 0.99,
            }
        )

        self.assertEqual(tags, ("hatsune_miku",))
        self.assertEqual(confidence, 0.99)
        self.assertEqual(ignored, 0)

    def test_generic_unqualified_anchors_remain_rejected(self) -> None:
        for anchor in ("blue_hair", "1girl", "school_uniform", "masterpiece"):
            with self.subTest(anchor=anchor):
                with self.assertRaises(CharacterSwapError) as raised:
                    normalize_semantic_identity_payload(
                        {
                            "canonical_identity_tag": anchor,
                            "appearance_tags": [],
                            "confidence": 0.99,
                        }
                    )
                self.assertEqual(
                    raised.exception.code,
                    "semantic_target_identity_anchor",
                )

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

    def _semantic_preparation(
        self,
        request: CharacterSwapRequest,
        target_tags: tuple[str, ...],
    ):
        return self.planner.prepare(
            request,
            positive_prompt=(
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=target_tags,
        )

    def _semantic_classification(
        self,
        preparation,
        *,
        confidence: float,
        appearance_ids: tuple[int, ...] = (),
    ):
        payload = _classification_payload(
            len(preparation.tags),
            source_identity_ids=[1, 2],
            outfit_ids=[3],
            pose_action_ids=[4],
            scene_lighting_ids=[5],
            style_quality_ids=[0, 6],
            target_appearance_trigger_ids=list(appearance_ids),
            confidence=confidence,
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

    def test_character_change_removes_extended_identity_but_keeps_expression(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest("", "Kallen Kaslana"),
            positive_prompt=(
                "1girl, roxy_migurdia_(mushoku_tensei), blue hair, twin braids, "
                "ahoge, blue eyes, petite, small breasts, beauty mark under left eye, "
                "school uniform, standing, looking at viewer, open mouth, beach, "
                "masterpiece"
            ),
            negative_prompt="",
            records=self.records,
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=list(range(1, 9)),
                    outfit_ids=[9],
                    pose_action_ids=[10, 11, 12],
                    scene_lighting_ids=[13],
                    style_quality_ids=[0, 14],
                    target_appearance_trigger_ids=[1],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )
        plan = self.planner.finalize(preparation, classification)

        for removed in (
            "roxy_migurdia_(mushoku_tensei)",
            "blue hair",
            "twin braids",
            "ahoge",
            "blue eyes",
            "petite",
            "small breasts",
            "beauty mark under left eye",
        ):
            self.assertNotIn(removed, plan.prompt)
        for preserved in (
            "school uniform",
            "standing",
            "looking at viewer",
            "open mouth",
            "beach",
        ):
            self.assertIn(preserved, plan.prompt)

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

    def test_required_target_lora_never_falls_back_to_semantic_tags(self) -> None:
        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.prepare(
                CharacterSwapRequest(
                    "Denia",
                    "Missing Character",
                    require_target_lora=True,
                ),
                positive_prompt="1girl, denia_wuwa, black hair, standing",
                negative_prompt="",
                records=self.records,
                fallback_target_tags=("missing_character_(work)",),
            )

        self.assertEqual(raised.exception.code, "required_target_lora_missing")

        with self.assertRaises(CharacterSwapError) as conflict:
            self.planner.prepare(
                CharacterSwapRequest(
                    "Denia",
                    "Kallen Kaslana",
                    use_target_lora=False,
                    require_target_lora=True,
                ),
                positive_prompt="1girl, denia_wuwa, black hair, standing",
                negative_prompt="",
                records=self.records,
            )
        self.assertEqual(
            conflict.exception.code,
            "conflicting_target_lora_directives",
        )

    def test_uncertain_white_thighhighs_is_safely_preserved_as_outfit(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "Shifty",
                "Kallen Kaslana",
                require_target_lora=True,
            ),
            positive_prompt=(
                "shifty_(nikke), 1girl, blue eyes, blue hair, buruma, "
                "gym uniform, white thighhighs, solo"
            ),
            negative_prompt="",
            records=self.records,
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[0, 2, 3],
                    outfit_ids=[4, 5],
                    style_quality_ids=[1, 7],
                    uncertain_ids=[6],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertIn("white thighhighs", plan.prompt)
        self.assertEqual(plan.promoted_uncertain_outfit_count, 1)
        self.assertIs(plan.target_record, self.kallen)
        self.assertIn(
            "characters/kallen.safetensors",
            [selection.name for selection in plan.loras],
        )

    def test_required_kei_lora_preserves_escaped_identity_trigger(self) -> None:
        kei = _record(
            "characters/kei_student_blue_archive_anima-base-v1_0_lokr_f8-000012_fp32.safetensors",
            "Kei/凯伊",
            "KEI-SHA",
            triggers=(r"kei \(student\) \(blue archive\)",),
            aliases=("kei", "凯伊"),
            source_work="Blue Archive/碧蓝档案/蔚蓝档案",
        )
        kei_entry = _semantic_entry(kei, "kei student blue archive")
        wrong_kei = _record(
            "characters/kei_wrong_game.safetensors",
            "Kei/凯伊",
            "WRONG-KEI-SHA",
            triggers=(r"kei \(wrong game\)",),
            aliases=("kei", "凯伊"),
            source_work="Wrong Game",
        )
        wrong_entry = _semantic_entry(wrong_kei, "kei wrong game")
        planner = CharacterSwapPlanner(
            LoraSemanticIndex(
                entries={
                    kei_entry.identity_key: kei_entry,
                    wrong_entry.identity_key: wrong_entry,
                },
            )
        )
        preparation = planner.prepare(
            CharacterSwapRequest(
                "Shifty",
                "《BlueArchive》的凯伊(kei)",
                require_target_lora=True,
            ),
            positive_prompt=(
                "shifty_(nikke), 1girl, blue hair, gym uniform, "
                "white thighhighs, solo"
            ),
            negative_prompt="",
            records=(*self.records, kei, wrong_kei),
        )
        classification = planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[0, 2],
                    outfit_ids=[3, 4],
                    style_quality_ids=[1, 5],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = planner.finalize(preparation, classification)

        self.assertIs(plan.target_record, kei)
        self.assertIn(r"kei \(student\) \(blue archive\)", plan.prompt)
        self.assertNotIn("kei (student) (blue archive)", plan.prompt)
        self.assertNotIn("blue hair", plan.prompt)
        self.assertLess(
            plan.prompt.index(r"kei \(student\) \(blue archive\)"),
            plan.prompt.index("gym uniform"),
        )

        with self.assertRaises(CharacterSwapError) as wrong_work:
            planner.prepare(
                CharacterSwapRequest(
                    "Shifty",
                    "《Fate》的凯伊(kei)",
                    require_target_lora=True,
                ),
                positive_prompt="shifty_(nikke), 1girl, gym uniform, solo",
                negative_prompt="",
                records=(*self.records, kei, wrong_kei),
            )
        self.assertEqual(
            wrong_work.exception.code,
            "required_target_lora_missing",
        )
        for wrong_query in ("Fate的凯伊(kei)", "Fate里的凯伊"):
            with self.subTest(wrong_query=wrong_query):
                with self.assertRaises(CharacterSwapError) as wrong_plain_work:
                    planner.prepare(
                        CharacterSwapRequest(
                            "Shifty",
                            wrong_query,
                            require_target_lora=True,
                        ),
                        positive_prompt=(
                            "shifty_(nikke), 1girl, gym uniform, solo"
                        ),
                        negative_prompt="",
                        records=(*self.records, kei, wrong_kei),
                    )
                self.assertEqual(
                    wrong_plain_work.exception.code,
                    "required_target_lora_missing",
                )

    def test_uncertain_bra_does_not_collide_with_twin_braids(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest("Denia", "Kallen Kaslana"),
            positive_prompt=(
                "denia_wuwa, 1girl, twin braids, bra, standing, solo"
            ),
            negative_prompt="",
            records=self.records,
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[0],
                    style_quality_ids=[1, 5],
                    pose_action_ids=[4],
                    uncertain_ids=[2, 3],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("twin braids", plan.prompt)
        self.assertIn("bra", plan.prompt)
        self.assertEqual(plan.promoted_uncertain_count, 1)
        self.assertEqual(plan.promoted_uncertain_outfit_count, 1)

    def test_deterministic_outfit_repair_rejects_composite_identity_and_pose(self) -> None:
        for term in (
            "black hair ribbon",
            "blue hair with red ribbon",
            "ribbon braid",
            "looking under skirt",
            "dress blowing in wind",
        ):
            with self.subTest(term=term):
                self.assertFalse(_is_deterministic_outfit_term(term))

        for term in (
            "white_thighhighs",
            "gym uniform",
            "black bra",
            "white shirt",
        ):
            with self.subTest(term=term):
                self.assertTrue(_is_deterministic_outfit_term(term))

    def test_slash_alias_is_not_an_explicit_lora_file_and_can_fallback(self) -> None:
        request = parse_character_swap_request(
            "Denia -> 目标角色《鸣潮》的今汐/今夕 | "
            "1girl, denia_wuwa, black hair, standing"
        )
        preparation = self.planner.prepare(
            request,
            positive_prompt=request.tags,
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "jinhsi_(wuthering_waves)",
                "white hair",
                "red eyes",
            ),
        )

        self.assertEqual(request.target_query, "《鸣潮》的今汐/今夕")
        self.assertIsNone(preparation.target_record)
        self.assertEqual(
            preparation.target_trigger_words[0],
            "jinhsi_(wuthering_waves)",
        )

    def test_target_role_with_safetensors_suffix_remains_strict(self) -> None:
        request = parse_character_swap_request(
            "Denia -> 目标角色characters/missing.safetensors | "
            "1girl, denia_wuwa, black hair, standing"
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.prepare(
                request,
                positive_prompt=request.tags,
                negative_prompt="",
                records=self.records,
                fallback_target_tags=("missing_character_(work)",),
            )

        self.assertEqual(raised.exception.code, "character_not_found")

    def test_explicit_lora_prefix_resolves_exact_character_file(self) -> None:
        resolved = resolve_character_record(
            self.records,
            "lora:characters/kallen.safetensors",
            LoraSemanticIndex.empty(),
        )

        self.assertIs(resolved, self.kallen)

    def test_danbooru_exact_identity_allows_point85_classification(self) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "鸣潮的今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            (
                "jinhsi_(wuthering_waves)",
                "white hair",
                "red eyes",
            ),
        )

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.85,
                appearance_ids=(1, 2),
            ),
        )

        self.assertIn(r"jinhsi_\(wuthering_waves\)", plan.prompt)
        self.assertNotIn("white hair", plan.prompt)
        self.assertNotIn("red eyes", plan.prompt)

    def test_danbooru_exact_unqualified_identity_survives_final_validation(
        self,
    ) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Shifty",
                "初音未来",
                semantic_identity_confidence=0.99,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            ("hatsune_miku",),
        )

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.85,
                appearance_ids=(),
            ),
        )

        self.assertIn("hatsune_miku", plan.prompt)

    def test_danbooru_profile_pins_appearance_and_places_identity_after_subject(
        self,
    ) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "Blue Archive Rio",
                semantic_identity_confidence=1.0,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
                semantic_appearance_source="danbooru_gallery",
                semantic_appearance_count=4,
                semantic_appearance_sample_count=100,
            ),
            (
                "rio_(blue_archive)",
                "black hair",
                "red eyes",
                "long hair",
                "halo",
            ),
        )

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.85,
                appearance_ids=(),
            ),
        )

        terms = tuple(item.strip() for item in plan.prompt.split(","))
        self.assertEqual(terms[:6], (
            "1girl",
            r"rio_\(blue_archive\)",
            "black hair",
            "red eyes",
            "long hair",
            "halo",
        ))
        self.assertNotIn("denia_wuwa", plan.prompt)
        self.assertEqual(plan.prompt.count("black hair"), 1)

    def test_danbooru_profile_ignores_classifier_outfit_mislabel(self) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "Blue Archive Rio",
                semantic_identity_confidence=1.0,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
                semantic_appearance_source="danbooru_gallery",
                semantic_appearance_count=4,
                semantic_appearance_sample_count=100,
            ),
            (
                "rio_(blue_archive)",
                "black hair",
                "red eyes",
                "long hair",
                "halo",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    outfit_ids=[3],
                    pose_action_ids=[4],
                    scene_lighting_ids=[5],
                    style_quality_ids=[0, 6],
                    target_default_outfit_trigger_ids=[1],
                    confidence=0.85,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertIn("black hair", plan.prompt)
        self.assertIn(r"rio_\(blue_archive\)", plan.prompt)

    def test_rio_dense_prompt_contract_removes_source_and_reinforces_target(
        self,
    ) -> None:
        request = CharacterSwapRequest(
            "",
            "Blue Archive Rio",
            semantic_identity_confidence=1.0,
            semantic_identity_index_verified=True,
            semantic_identity_anchor_source="danbooru_exact",
            semantic_appearance_source="danbooru_gallery",
            semantic_appearance_count=4,
            semantic_appearance_sample_count=100,
        )
        preparation = self.planner.prepare(
            request,
            positive_prompt=(
                "masterpiece, 1girl, solo, silver hair, white hair, twin tails, "
                "profile, rainbow reflection in hair, beach"
            ),
            negative_prompt="black_hair, red_eyes, low quality",
            records=self.records,
            fallback_target_tags=(
                "rio_(blue_archive)",
                "black hair",
                "red eyes",
                "long hair",
                "halo",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[3, 4, 5],
                    composition_ids=[6],
                    scene_lighting_ids=[7, 8],
                    style_quality_ids=[0, 1, 2],
                    confidence=0.9,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("silver hair", plan.prompt)
        self.assertNotIn("white hair", plan.prompt)
        self.assertNotIn("twin tails", plan.prompt)
        self.assertIn("rainbow reflection in hair", plan.prompt)
        self.assertIn("beach", plan.prompt)
        self.assertNotIn("black_hair", plan.negative_prompt)
        self.assertNotIn("red_eyes", plan.negative_prompt)
        self.assertIn("low quality", plan.negative_prompt)
        self.assertIn(
            "1girl, solo, rio_\\(blue_archive\\), black hair, red eyes, long hair, halo",
            plan.prompt,
        )

    def test_high_provider_confidence_allows_point82_classification_without_index(
        self,
    ) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "鸣潮的今汐",
                semantic_identity_confidence=0.92,
                semantic_identity_index_verified=False,
                semantic_identity_anchor_source="provider_qualified",
            ),
            ("jinhsi_(wuthering_waves)", "white hair"),
        )

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.82,
                appearance_ids=(1,),
            ),
        )

        self.assertIn("jinhsi_(wuthering_waves)", plan.prompt)
        self.assertNotIn("white hair", plan.prompt)

    def test_guarded_provider_confidence_still_requires_point90_classification(
        self,
    ) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "鸣潮的今汐",
                semantic_identity_confidence=0.85,
                semantic_identity_index_verified=False,
                semantic_identity_anchor_source="provider_qualified",
            ),
            ("jinhsi_(wuthering_waves)", "white hair"),
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.finalize(
                preparation,
                self._semantic_classification(
                    preparation,
                    confidence=0.89,
                ),
            )
        self.assertEqual(raised.exception.code, "low_classification_confidence")
        self.assertEqual(raised.exception.details["minimum_confidence"], 0.9)

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.90,
            ),
        )
        self.assertIn("jinhsi_(wuthering_waves)", plan.prompt)

    def test_known_character_appearance_requires_point92_classification(self) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "鸣潮的今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_anchor_source="provider_qualified",
            ),
            (
                "jinhsi_(wuthering_waves)",
                "long white hair",
                "red eyes",
                "dragon horns",
            ),
        )

        guarded = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.91,
                appearance_ids=(1, 2, 3),
            ),
        )
        trusted = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.92,
                appearance_ids=(1, 2, 3),
            ),
        )

        for tag in ("long white hair", "red eyes", "dragon horns"):
            self.assertNotIn(tag, guarded.prompt)
            self.assertIn(tag, trusted.prompt)

    def test_exact_shared_long_hair_is_reauthorized_at_high_confidence(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "",
                "鸣潮今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            positive_prompt=(
                "1girl, source_character_(source_work), long hair, "
                "school uniform, standing, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "jinhsi_(wuthering_waves)",
                "long hair",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    outfit_ids=[3],
                    pose_action_ids=[4],
                    scene_lighting_ids=[5],
                    style_quality_ids=[0, 6],
                    target_appearance_trigger_ids=[1],
                    confidence=0.96,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("source_character_(source_work)", plan.prompt)
        self.assertIn(r"jinhsi_\(wuthering_waves\)", plan.prompt)
        self.assertEqual(plan.prompt.count("long hair"), 1)
        self.assertEqual(plan.reauthorized_appearance_terms, ("long hair",))

    def test_target_candidate_long_silver_hair_reauthorizes_shared_fragment(
        self,
    ) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "",
                "鸣潮今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            positive_prompt=(
                "1girl, source_character_(source_work), silver hair, "
                "school uniform, standing, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "jinhsi_(wuthering_waves)",
                "long silver hair",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    outfit_ids=[3],
                    pose_action_ids=[4],
                    scene_lighting_ids=[5],
                    style_quality_ids=[0, 6],
                    target_appearance_trigger_ids=[1],
                    confidence=0.96,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn(", silver hair,", f", {plan.prompt},")
        self.assertIn("long silver hair", plan.prompt)
        self.assertEqual(
            plan.reauthorized_appearance_terms,
            ("long silver hair",),
        )

    def test_non_target_candidate_fragment_leak_is_still_rejected(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "",
                "鸣潮今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            positive_prompt=(
                "1girl, source_character_(source_work), silver hair, "
                "long silver hair, school uniform, standing, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "jinhsi_(wuthering_waves)",
                "red eyes",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    outfit_ids=[4],
                    pose_action_ids=[5],
                    scene_lighting_ids=[6],
                    style_quality_ids=[0, 3, 7],
                    target_appearance_trigger_ids=[1],
                    confidence=0.96,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.finalize(preparation, classification)
        self.assertEqual(raised.exception.code, "source_identity_leak")

    def test_weighted_or_composite_shared_appearance_is_not_reauthorized(
        self,
    ) -> None:
        source_terms = (
            "(long hair:1.2)",
            "(silver hair, long hair:1.1)",
        )
        for source_term in source_terms:
            with self.subTest(source_term=source_term):
                preparation = self.planner.prepare(
                    CharacterSwapRequest(
                        "",
                        "鸣潮今汐",
                        semantic_identity_confidence=0.95,
                        semantic_identity_index_verified=True,
                        semantic_identity_anchor_source="danbooru_exact",
                    ),
                    positive_prompt=(
                        f"1girl, source_character_(source_work), {source_term}, "
                        "school uniform, standing, beach, masterpiece"
                    ),
                    negative_prompt="",
                    records=self.records,
                    fallback_target_tags=(
                        "jinhsi_(wuthering_waves)",
                        source_term,
                    ),
                )
                classification = self.planner.parse_classification(
                    json.dumps(
                        _classification_payload(
                            len(preparation.tags),
                            source_identity_ids=[1, 2],
                            outfit_ids=[3],
                            pose_action_ids=[4],
                            scene_lighting_ids=[5],
                            style_quality_ids=[0, 6],
                            target_appearance_trigger_ids=[1],
                            confidence=0.96,
                        )
                    ),
                    tag_count=len(preparation.tags),
                    target_trigger_count=len(preparation.target_trigger_words),
                )

                with self.assertRaises(CharacterSwapError) as raised:
                    self.planner.finalize(preparation, classification)
                self.assertEqual(raised.exception.code, "source_identity_leak")

    def test_uncertain_atomic_appearance_is_cleaned_with_source_profile(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest("Denia", "Kallen Kaslana"),
            positive_prompt=(
                "<lora:characters/denia:1.0>, 1girl, denia_wuwa, long hair, "
                "school uniform, standing, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1],
                    outfit_ids=[3],
                    pose_action_ids=[4],
                    scene_lighting_ids=[5],
                    style_quality_ids=[0, 6],
                    uncertain_ids=[2],
                    target_appearance_trigger_ids=[1],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("long hair", plan.prompt)
        self.assertEqual(plan.promoted_uncertain_count, 1)

    def test_two_uncertain_atomic_traits_form_a_bounded_source_profile(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "",
                "鸣潮今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            positive_prompt=(
                "1girl, silver hair, blue eyes, school uniform, standing, "
                "beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=("jinhsi_(wuthering_waves)",),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    outfit_ids=[3],
                    pose_action_ids=[4],
                    scene_lighting_ids=[5],
                    style_quality_ids=[0, 6],
                    uncertain_ids=[1, 2],
                    confidence=0.96,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        plan = self.planner.finalize(preparation, classification)

        self.assertNotIn("silver hair", plan.prompt)
        self.assertNotIn("blue eyes", plan.prompt)
        self.assertEqual(plan.promoted_uncertain_count, 2)

    def test_single_uncertain_atomic_trait_without_anchor_still_fails_closed(
        self,
    ) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "",
                "鸣潮今汐",
                semantic_identity_confidence=0.95,
                semantic_identity_index_verified=True,
                semantic_identity_anchor_source="danbooru_exact",
            ),
            positive_prompt=(
                "1girl, silver hair, school uniform, standing, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=("jinhsi_(wuthering_waves)",),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    outfit_ids=[2],
                    pose_action_ids=[3],
                    scene_lighting_ids=[4],
                    style_quality_ids=[0, 5],
                    uncertain_ids=[1],
                    confidence=0.96,
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.finalize(preparation, classification)
        self.assertEqual(raised.exception.code, "uncertain_tags")

    def test_non_atomic_uncertain_terms_are_never_auto_promoted(self) -> None:
        terms = (
            "hair ornament",
            "closed eyes",
            "eye-level view",
            "warm ink style",
        )
        for term in terms:
            with self.subTest(term=term):
                preparation = self.planner.prepare(
                    CharacterSwapRequest("Denia", "Kallen Kaslana"),
                    positive_prompt=(
                        "<lora:characters/denia:1.0>, 1girl, denia_wuwa, "
                        f"{term}, school uniform, standing, beach, masterpiece"
                    ),
                    negative_prompt="",
                    records=self.records,
                )
                classification = self.planner.parse_classification(
                    json.dumps(
                        _classification_payload(
                            len(preparation.tags),
                            source_identity_ids=[1],
                            outfit_ids=[3],
                            pose_action_ids=[4],
                            scene_lighting_ids=[5],
                            style_quality_ids=[0, 6],
                            uncertain_ids=[2],
                            target_appearance_trigger_ids=[1],
                        )
                    ),
                    tag_count=len(preparation.tags),
                    target_trigger_count=len(preparation.target_trigger_words),
                )

                with self.assertRaises(CharacterSwapError) as raised:
                    self.planner.finalize(preparation, classification)
                self.assertEqual(raised.exception.code, "uncertain_tags")

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

    def test_no_character_lora_ignores_duplicate_target_lora_files(self) -> None:
        rice_a = _record(
            "characters/rice_shower_a.safetensors",
            "米浴",
            "rice-a",
            triggers=("rice_shower_(umamusume)",),
            source_work="赛马娘",
        )
        rice_b = _record(
            "characters/rice_shower_b.safetensors",
            "米浴",
            "rice-b",
            triggers=("rice_shower_(umamusume)",),
            source_work="赛马娘",
        )
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "Denia",
                "米浴",
                use_target_lora=False,
            ),
            positive_prompt="1girl, denia_wuwa, black hair, standing",
            negative_prompt="",
            records=(*self.records, rice_a, rice_b),
            fallback_target_tags=("rice_shower_(umamusume)", "brown hair"),
        )

        self.assertIsNone(preparation.target_record)
        self.assertIn(preparation.target_metadata_record, (rice_a, rice_b))
        self.assertEqual(preparation.target_trigger_words, ("rice_shower_(umamusume)",))

    def test_optional_target_lora_uses_semantic_fallback_for_same_character_variants(
        self,
    ) -> None:
        rice_a = _record(
            "characters/rice_shower_a.safetensors",
            "米浴",
            "rice-a",
            triggers=("rice_shower_(umamusume)",),
            source_work="赛马娘",
        )
        rice_b = _record(
            "characters/rice_shower_b.safetensors",
            "米浴",
            "rice-b",
            triggers=("rice_shower_(umamusume)",),
            source_work="赛马娘",
        )

        preparation = self.planner.prepare(
            CharacterSwapRequest("Denia", "米浴"),
            positive_prompt="1girl, denia_wuwa, black hair, standing",
            negative_prompt="",
            records=(*self.records, rice_a, rice_b),
            fallback_target_tags=(
                "rice_shower_(umamusume)",
                "brown hair",
                "purple eyes",
                "horse ears",
            ),
        )

        self.assertIsNone(preparation.target_record)
        self.assertIsNone(preparation.target_metadata_record)
        self.assertEqual(
            preparation.target_trigger_words,
            (
                "rice_shower_(umamusume)",
                "brown hair",
                "purple eyes",
                "horse ears",
            ),
        )

    def test_optional_target_lora_keeps_cross_identity_alias_ambiguous(self) -> None:
        first = _record(
            "characters/alex_game_a.safetensors",
            "Alex A",
            "alex-a",
            triggers=("alex_a_(game_a)",),
            source_work="Game A",
        )
        second = _record(
            "characters/alex_game_b.safetensors",
            "Alex B",
            "alex-b",
            triggers=("alex_b_(game_b)",),
            source_work="Game B",
        )
        first_entry = _semantic_entry(first, "阿历克斯")
        second_entry = _semantic_entry(second, "阿历克斯")
        planner = CharacterSwapPlanner(
            LoraSemanticIndex(
                entries={
                    first_entry.identity_key: first_entry,
                    second_entry.identity_key: second_entry,
                }
            )
        )

        with self.assertRaises(CharacterSwapError) as raised:
            planner.prepare(
                CharacterSwapRequest("Denia", "阿历克斯"),
                positive_prompt="1girl, denia_wuwa, black hair, standing",
                negative_prompt="",
                records=(*self.records, first, second),
                fallback_target_tags=("alex_a_(game_a)", "black hair"),
            )

        self.assertEqual(raised.exception.code, "ambiguous_character")

    def test_no_character_lora_keeps_cross_identity_alias_ambiguous(self) -> None:
        first = _record(
            "characters/alex_game_a.safetensors",
            "Alex A",
            "alex-a",
            triggers=("alex_a_(game_a)",),
            source_work="Game A",
        )
        second = _record(
            "characters/alex_game_b.safetensors",
            "Alex B",
            "alex-b",
            triggers=("alex_b_(game_b)",),
            source_work="Game B",
        )
        first_entry = _semantic_entry(first, "阿历克斯")
        second_entry = _semantic_entry(second, "阿历克斯")
        planner = CharacterSwapPlanner(
            LoraSemanticIndex(
                entries={
                    first_entry.identity_key: first_entry,
                    second_entry.identity_key: second_entry,
                }
            )
        )

        with self.assertRaises(CharacterSwapError) as raised:
            planner.prepare(
                CharacterSwapRequest(
                    "Denia",
                    "阿历克斯",
                    use_target_lora=False,
                ),
                positive_prompt="1girl, denia_wuwa, black hair, standing",
                negative_prompt="",
                records=(*self.records, first, second),
                fallback_target_tags=("alex_a_(game_a)",),
            )

        self.assertEqual(raised.exception.code, "ambiguous_character")

    def test_qualified_character_name_survives_finalize(self) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "Denia",
                "Hat Kid",
                use_target_lora=False,
            ),
            positive_prompt="1girl, denia_wuwa, black hair, standing, masterpiece",
            negative_prompt="",
            records=self.records,
            fallback_target_tags=("hat_kid_(a_hat_in_time)", "brown hair"),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    pose_action_ids=[3],
                    style_quality_ids=[0, 4],
                    target_appearance_trigger_ids=[1],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )
        plan = self.planner.finalize(
            preparation,
            classification,
        )

        self.assertIn("hat_kid_(a_hat_in_time)", plan.prompt)
        self.assertNotIn("characters/kallen", [item.name for item in plan.loras])

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

    def test_original_character_uses_stable_appearance_without_target_lora(
        self,
    ) -> None:
        preparation = self.planner.prepare(
            CharacterSwapRequest(
                "Denia",
                "原创角色：银色长发、金色眼睛、精灵耳、左眼下美人痣",
            ),
            positive_prompt=(
                "1girl, denia_wuwa, black hair, school uniform, standing, "
                "looking at viewer, open mouth, beach, masterpiece"
            ),
            negative_prompt="",
            records=self.records,
            fallback_target_tags=(
                "original character",
                "long silver hair",
                "golden eyes",
                "elf ears",
                "beauty mark under left eye",
            ),
        )
        classification = self.planner.parse_classification(
            json.dumps(
                _classification_payload(
                    len(preparation.tags),
                    source_identity_ids=[1, 2],
                    outfit_ids=[3],
                    pose_action_ids=[4, 5, 6],
                    scene_lighting_ids=[7],
                    style_quality_ids=[0, 8],
                    target_appearance_trigger_ids=[1, 2, 3, 4],
                )
            ),
            tag_count=len(preparation.tags),
            target_trigger_count=len(preparation.target_trigger_words),
        )
        plan = self.planner.finalize(preparation, classification)

        self.assertIsNone(plan.target_record)
        for tag in (
            "original character",
            "long silver hair",
            "golden eyes",
            "elf ears",
            "beauty mark under left eye",
        ):
            self.assertIn(tag, plan.prompt)
        self.assertNotIn("denia_wuwa", plan.prompt)
        for preserved in (
            "school uniform",
            "standing",
            "looking at viewer",
            "open mouth",
            "beach",
        ):
            self.assertIn(preserved, plan.prompt)
        self.assertEqual(plan.loras, ())

    def test_original_character_requires_three_classifier_verified_traits(
        self,
    ) -> None:
        preparation = self._semantic_preparation(
            CharacterSwapRequest(
                "Denia",
                "原创角色：银色长发、金色眼睛、精灵耳、左眼下美人痣",
                semantic_identity_confidence=0.95,
                semantic_identity_anchor_source="original_profile",
            ),
            (
                "original character",
                "long silver hair",
                "golden eyes",
                "elf ears",
                "beauty mark under left eye",
            ),
        )

        with self.assertRaises(CharacterSwapError) as raised:
            self.planner.finalize(
                preparation,
                self._semantic_classification(
                    preparation,
                    confidence=0.95,
                    appearance_ids=(1, 2),
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "semantic_original_appearance_unverified",
        )

        plan = self.planner.finalize(
            preparation,
            self._semantic_classification(
                preparation,
                confidence=0.95,
                appearance_ids=(1, 2, 3),
            ),
        )
        for tag in ("long silver hair", "golden eyes", "elf ears"):
            self.assertIn(tag, plan.prompt)
        self.assertNotIn("beauty mark under left eye", plan.prompt)

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
