"""局域网 LoRA 清单解析测试。"""

import json
import unittest
from dataclasses import replace

from ..models import LoraSelection, PluginSettings
from ..services.lora_catalog import (
    LoraCatalogError,
    LoraCatalogService,
    LoraRecord,
)


class LoraCatalogParserTests(unittest.TestCase):
    """验证 ComfyUI、JSON、文本和目录格式。"""

    def test_parses_comfyui_object_info(self) -> None:
        payload = {
            "LoraLoader": {
                "input": {
                    "required": {
                        "lora_name": [
                            ["characters/denia.safetensors", "styles/anime.pt"]
                        ]
                    }
                }
            },
            "CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [["model.safetensors"]]}}
            },
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(
            [record.name for record in records],
            ["characters/denia.safetensors", "styles/anime.pt"],
        )

    def test_object_info_reads_only_explicit_lora_input_choices(self) -> None:
        payload = {
            "HybridModelAndLoraLoader": {
                "input": {
                    "required": {
                        "lora_name": [["styles/quality.safetensors"]],
                        "unet_name": [["diffusion_models/anima-unet.safetensors"]],
                        "ckpt_name": [["checkpoints/anima-full.safetensors"]],
                    }
                }
            },
            "MisleadingLoraCheckpointNode": {
                "input": {
                    "required": {"model_name": [["checkpoints/not-a-lora.safetensors"]]}
                }
            },
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(
            [record.name for record in records], ["styles/quality.safetensors"]
        )

    def test_checkpoint_only_object_info_does_not_fall_back_to_json_text(self) -> None:
        payload = {
            "CheckpointLoaderSimple": {
                "input": {
                    "required": {"ckpt_name": [["checkpoints/anima.safetensors"]]}
                }
            }
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(records, ())

    def test_parses_metadata_json(self) -> None:
        payload = {
            "loras": [
                {
                    "name": "denia.safetensors",
                    "trigger_words": ["denia (wuthering waves)"],
                    "description": "character",
                }
            ]
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(records[0].trigger_words, ("denia (wuthering waves)",))

    def test_parses_text_catalog(self) -> None:
        records = LoraCatalogService.parse_catalog(
            b"style.safetensors|style trigger, vivid|anime style\n"
        )

        self.assertEqual(records[0].name, "style.safetensors")
        self.assertEqual(records[0].trigger_words, ("style trigger", "vivid"))

    def test_parses_public_directory_html(self) -> None:
        html = b'<a href="denia.safetensors">denia</a><a href="note.txt">note</a>'

        records = LoraCatalogService.parse_catalog(html, "text/html")

        self.assertEqual([record.name for record in records], ["denia.safetensors"])

    def test_parses_lora_manager_payload(self) -> None:
        payload = {
            "items": [
                {
                    "model_name": "Denia Character",
                    "file_name": "Denia_Wuwa",
                    "file_path": "E:/Comfy/models/loras/characters/Denia_Wuwa.safetensors",
                    "folder": "characters",
                    "base_model": "Anima",
                    "preview_url": "/api/lm/previews?path=denia.jpeg",
                    "sha256": "abc123",
                    "tags": ["character", "wuthering waves"],
                    "favorite": True,
                    "civitai": {"trainedWords": ["denia (wuthering waves)"]},
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 100,
            "total_pages": 1,
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(records[0].name, "characters/Denia_Wuwa")
        self.assertEqual(records[0].model_name, "Denia Character")
        self.assertEqual(records[0].base_model, "Anima")
        self.assertEqual(records[0].trigger_words, ("denia (wuthering waves)",))
        self.assertTrue(records[0].favorite)

    def test_manager_payload_requires_lora_directory_or_type_evidence(self) -> None:
        payload = {
            "items": [
                {
                    "file_name": "valid-by-type.safetensors",
                    "sub_type": "DoRA",
                },
                {
                    "file_name": "valid-by-directory.safetensors",
                    "file_path": "/models/loras/styles/valid-by-directory.safetensors",
                },
                {
                    "file_name": "unet.safetensors",
                    "model_type": "UNET",
                    "file_path": "/models/loras/wrong/unet.safetensors",
                },
                {
                    "file_name": "checkpoint.safetensors",
                    "model_type": "Checkpoint",
                    "file_path": "/models/checkpoints/checkpoint.safetensors",
                },
                {
                    "file_name": "ambiguous.safetensors",
                    "folder": "misc",
                },
            ]
        }

        records = LoraCatalogService.parse_catalog(
            json.dumps(payload).encode(), "application/json"
        )

        self.assertEqual(
            [record.name for record in records],
            ["valid-by-directory", "valid-by-type"],
        )

    def test_merges_manager_metadata_onto_actual_comfy_name(self) -> None:
        actual = LoraCatalogService.parse_catalog(
            json.dumps(
                {
                    "LoraLoader": {
                        "input": {
                            "required": {
                                "lora_name": [["characters/Denia_Wuwa.safetensors"]]
                            }
                        }
                    }
                }
            ).encode(),
            "application/json",
        )
        manager = LoraCatalogService.parse_catalog(
            json.dumps(
                {
                    "items": [
                        {
                            "file_name": "Denia_Wuwa",
                            "folder": "characters",
                            "sub_type": "lora",
                            "model_name": "Denia Character",
                            "base_model": "Anima",
                            "civitai": {"trainedWords": ["denia"]},
                        }
                    ]
                }
            ).encode(),
            "application/json",
        )

        records = LoraCatalogService._merge_catalogs(actual, manager)

        self.assertEqual(records[0].name, "characters/Denia_Wuwa.safetensors")
        self.assertEqual(records[0].model_name, "Denia Character")
        self.assertEqual(records[0].trigger_words, ("denia",))

    def test_manager_only_deleted_record_is_not_exposed(self) -> None:
        actual = (LoraRecord("still-present.safetensors"),)
        manager = (
            LoraRecord("still-present", model_name="Current"),
            LoraRecord("deleted-denia", model_name="Deleted stale cache"),
        )

        records = LoraCatalogService._merge_catalogs(actual, manager)

        self.assertEqual(
            [record.name for record in records], ["still-present.safetensors"]
        )

    def test_manager_page_url_is_normalized_to_api_root(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "comfyui_url": "http://192.168.1.50:8188",
                "lora_manager_url": "http://192.168.1.50:8188/loras",
            }
        )

        self.assertEqual(
            LoraCatalogService._resolve_manager_url(settings),
            "http://192.168.1.50:8188/api/lm/loras",
        )


class StrictLoraRefreshTests(unittest.IsolatedAsyncioTestCase):
    class Catalog(LoraCatalogService):
        def __init__(self):
            super().__init__(
                PluginSettings.from_mapping(
                    {"comfyui_url": "http://192.168.1.50:8188"}
                )
            )
            self.scan_forces = []

        async def _scan_manager(self, *, force=False):
            self.scan_forces.append(force)

        async def _fetch_manager_records(self):
            return (
                LoraRecord("present", model_name="Present"),
                LoraRecord("deleted-denia", model_name="Stale"),
            )

        async def _fetch(self, _url, **_kwargs):
            payload = {
                "LoraLoader": {
                    "input": {"required": {"lora_name": [["present.safetensors"]]}}
                }
            }
            return json.dumps(payload).encode(), "application/json"

    async def test_every_operation_bypasses_cache_and_forces_scan(self) -> None:
        service = self.Catalog()

        first = await service.refresh_for_operation()
        second = await service.refresh_for_operation()

        self.assertEqual(service.scan_forces, [True, True])
        self.assertEqual([record.name for record in first], ["present.safetensors"])
        self.assertEqual([record.name for record in second], ["present.safetensors"])

    async def test_scan_failure_blocks_object_info_fallback(self) -> None:
        service = self.Catalog()

        async def fail_scan(*, force=False):
            raise LoraCatalogError("scan failed")

        service._scan_manager = fail_scan
        with self.assertRaises(LoraCatalogError) as raised:
            await service.refresh_for_operation()
        self.assertIn("强制刷新失败", raised.exception.user_message)

    async def test_manager_rows_cannot_replace_empty_comfy_lora_choices(self) -> None:
        service = self.Catalog()

        async def checkpoint_only(_url, **_kwargs):
            payload = {
                "CheckpointLoaderSimple": {
                    "input": {
                        "required": {"ckpt_name": [["anima-checkpoint.safetensors"]]}
                    }
                }
            }
            return json.dumps(payload).encode(), "application/json"

        service._fetch = checkpoint_only
        with self.assertRaises(LoraCatalogError) as raised:
            await service.refresh_for_operation()

        self.assertIn("实际可加载 LoRA 清单为空", raised.exception.user_message)

    async def test_semantic_overlay_enriches_but_cannot_change_file_set(self) -> None:
        service = self.Catalog()
        service.set_record_overlay(
            lambda records: tuple(
                replace(record, aliases=("语义别名",)) for record in records
            )
        )
        records = await service.refresh_for_operation()
        self.assertEqual(records[0].aliases, ("语义别名",))
        self.assertEqual([record.name for record in records], ["present.safetensors"])

        service.set_record_overlay(
            lambda records: (*records, LoraRecord("deleted-denia.safetensors"))
        )
        safe_records = await service.refresh_for_operation()
        self.assertEqual(
            [record.name for record in safe_records], ["present.safetensors"]
        )
        self.assertIn("语义索引暂不可用", service._last_warning)


class CivitaiIdentityTests(unittest.IsolatedAsyncioTestCase):
    """验证 Civitai 角色、作品和别名的逻辑归档与安全消歧。"""

    @staticmethod
    def _denia_record() -> LoraRecord:
        return LoraCatalogService._record_from_manager_item(
            {
                "model_name": r"denia \(wuthering waves\) 达妮娅（鸣潮 ）(新增anima)",
                "file_name": "black deniav1-2",
                "sub_type": "lora",
                "tags": ["character"],
                "from_civitai": True,
            }
        )

    @staticmethod
    def _sunna_record() -> LoraRecord:
        return LoraCatalogService._record_from_manager_item(
            {
                "model_name": "Character > Sunna (Zenless Zone Zero)",
                "file_name": "Sunna-Zenless_anima-base1_v1-1",
                "sub_type": "lora",
                "tags": ["character"],
                "civitai": {
                    "trainedWords": [
                        "sunna (zenless zone zero)",
                        "sunna (afternoon tea break) (zenless zone zero)",
                    ]
                },
            }
        )

    @staticmethod
    def _remielle_record() -> LoraRecord:
        return LoraCatalogService._record_from_manager_item(
            {
                "model_name": "拉米尔|绝区零 remielle dan|zenless zone zero",
                "file_name": "remielle_dan-000028",
                "sub_type": "lora",
                "tags": [
                    "character",
                    "remielle dan",
                    "zenless zone zero",
                    "拉米尔",
                    "绝区零",
                ],
                "civitai": {"trainedWords": ["remielle dan", "mouth mask"]},
                "from_civitai": True,
            }
        )

    def test_denia_bilingual_identity_and_work_are_extracted(self) -> None:
        record = self._denia_record()

        self.assertEqual(record.category, "character")
        self.assertIn("denia", record.character_name.casefold())
        self.assertIn("达妮娅", record.character_name)
        self.assertEqual(record.source_work, "鸣潮 / Wuthering Waves")
        self.assertTrue(record.from_civitai)
        self.assertGreaterEqual(
            LoraCatalogService._search_score(record, "鸣潮达妮娅"),
            90,
        )

    def test_sunna_variant_is_not_misclassified_as_source_work(self) -> None:
        record = self._sunna_record()

        self.assertEqual(record.character_name, "Sunna")
        self.assertEqual(record.source_work, "绝区零 / Zenless Zone Zero")
        self.assertIn("afternoon tea break", record.aliases)
        self.assertNotIn("afternoon tea break", record.source_work.casefold())

    def test_remielle_chinese_and_english_names_are_searchable(self) -> None:
        record = self._remielle_record()

        self.assertIn("拉米尔", record.character_name)
        self.assertIn("remielle dan", record.character_name.casefold())
        self.assertNotIn("mouth mask", record.character_name.casefold())
        self.assertIn("mouth mask", record.trigger_words)
        self.assertEqual(record.source_work, "绝区零 / Zenless Zone Zero")
        for query in ("拉米尔", "remielle", "绝区零 拉米尔"):
            self.assertEqual(
                LoraCatalogService.search_records((record,), query),
                (record,),
            )

    def test_character_title_can_infer_category_without_manual_tag(self) -> None:
        record = LoraCatalogService._record_from_manager_item(
            {
                "model_name": "Character > Sunna (Zenless Zone Zero)",
                "file_name": "sunna-v1",
                "sub_type": "lora",
            }
        )

        self.assertEqual(record.category, "character")

    def test_custom_alias_rules_accept_unique_basename(self) -> None:
        settings = PluginSettings.from_mapping(
            {"lora_alias_rules": ["black deniav1-2=达妮娅,denia,鸣潮达妮娅"]}
        )
        service = LoraCatalogService(settings)
        records = service._apply_alias_rules(
            (LoraRecord("characters/black deniav1-2.safetensors"),)
        )

        self.assertIn("达妮娅", records[0].aliases)
        self.assertIn("鸣潮达妮娅", records[0].aliases)

    def test_archive_summary_groups_categories_and_works(self) -> None:
        records = (
            self._denia_record(),
            self._sunna_record(),
            LoraRecord("style", category="artist_style"),
        )

        archive = LoraCatalogService.archive_summary(records)

        self.assertEqual(archive["categories"]["character"], 2)
        self.assertEqual(archive["categories"]["artist_style"], 1)
        self.assertEqual(archive["civitai_enriched"], 2)
        self.assertEqual(archive["identified_characters"], 2)
        self.assertEqual(
            {item["name"] for item in archive["works"]},
            {
                "鸣潮 / Wuthering Waves",
                "绝区零 / Zenless Zone Zero",
            },
        )

    async def test_unique_alias_resolves_to_exact_loadable_file(self) -> None:
        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return (CivitaiIdentityTests._denia_record(),)

        service = Catalog(PluginSettings.from_mapping({}))

        resolved = await service.resolve_selections(
            (LoraSelection("鸣潮 达妮娅", 0.9),),
            strict=True,
        )

        self.assertEqual(resolved[0].name, "black deniav1-2")
        self.assertEqual(resolved[0].strength, 0.9)

    async def test_multiple_character_variants_refuse_fuzzy_guess(self) -> None:
        records = (
            LoraRecord(
                "denia-outfit-a",
                category="character",
                aliases=("达妮娅", "denia"),
                character_name="达妮娅 / Denia",
                source_work="鸣潮 / Wuthering Waves",
            ),
            LoraRecord(
                "denia-outfit-b",
                category="character",
                aliases=("达妮娅", "denia"),
                character_name="达妮娅 / Denia",
                source_work="鸣潮 / Wuthering Waves",
            ),
        )

        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return records

        service = Catalog(PluginSettings.from_mapping({}))

        with self.assertRaises(LoraCatalogError) as raised:
            await service.resolve_selections(
                (LoraSelection("达妮娅", 1.0),),
                strict=True,
            )
        self.assertIn("多个文件", raised.exception.user_message)

    async def test_duplicate_basenames_require_full_path(self) -> None:
        records = (
            LoraRecord("characters/a/denia.safetensors"),
            LoraRecord("characters/b/denia.safetensors"),
        )

        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return records

        service = Catalog(PluginSettings.from_mapping({}))
        with self.assertRaises(LoraCatalogError) as raised:
            await service.resolve_selections(
                (LoraSelection("denia", 0.8),),
                strict=True,
            )
        self.assertIn("包含文件夹", raised.exception.user_message)

        resolved, record_map = await service.resolve_selections_with_records(
            (LoraSelection("characters/b/denia", 0.8),),
            strict=True,
        )
        self.assertEqual(resolved[0].name, "characters/b/denia")
        self.assertEqual(
            record_map["characters/b/denia"].name,
            "characters/b/denia.safetensors",
        )

    async def test_manager_full_path_collision_blocks_legacy_runtime_name(self) -> None:
        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return (LoraRecord("denia.safetensors"),)

        service = Catalog(PluginSettings.from_mapping({}))
        service._manager_items_by_name = {
            "characters/a/denia": {},
            "characters/b/denia": {},
        }

        for requested, strict in (
            ("denia", True),
            ("denia", False),
            ("characters/a/denia", True),
        ):
            with self.subTest(requested=requested, strict=strict):
                with self.assertRaises(LoraCatalogError) as raised:
                    await service.resolve_selections(
                        (LoraSelection(requested, 0.8),),
                        strict=strict,
                    )
                self.assertIn("包含文件夹", raised.exception.user_message)


class FunctionalLoraCategoryTests(unittest.TestCase):
    def test_metadata_signals_cover_functional_category_hierarchy(self) -> None:
        cases = (
            ("fast.safetensors", ("sampling helper", "few step"), "speed_sampling"),
            (
                "anima-highres.safetensors",
                ("quality enhancement", "aesthetic boost"),
                "quality_enhancement",
            ),
            (
                "skin.safetensors",
                ("skin detail", "detail repair"),
                "detail_restoration",
            ),
            (
                "pose.safetensors",
                ("dynamic pose", "composition"),
                "composition_pose",
            ),
            (
                "light.safetensors",
                ("lighting", "color grading"),
                "lighting_color",
            ),
            (
                "anima-photo-background.safetensors",
                ("scenery", "photo background"),
                "background_environment",
            ),
            (
                "outfit.safetensors",
                ("outfit", "costume"),
                "clothing_concept",
            ),
        )

        for file_name, tags, expected in cases:
            with self.subTest(category=expected):
                self.assertEqual(
                    LoraCatalogService._infer_category(
                        file_name=file_name,
                        model_name="",
                        tags=tags,
                        trigger_words=(),
                    ),
                    expected,
                )

    def test_character_evidence_takes_priority_over_outfit_trigger(self) -> None:
        category = LoraCatalogService._infer_category(
            file_name="hero.safetensors",
            model_name="Hero Character",
            tags=("character",),
            trigger_words=("hero", "special outfit"),
        )

        self.assertEqual(category, "character")

    def test_explicit_function_name_overrides_generic_style_tag(self) -> None:
        cases = (
            (
                "AestheticQualityModifiers_Masterpieces-v5.safetensors",
                ("aesthetic", "styles"),
                "quality_enhancement",
            ),
            (
                "real skin.baka.v1.safetensors",
                ("style",),
                "detail_restoration",
            ),
            (
                "anima3-photo-background-v3.safetensors",
                ("anime", "scenery", "background"),
                "background_environment",
            ),
        )

        for file_name, tags, expected in cases:
            with self.subTest(file_name=file_name):
                self.assertEqual(
                    LoraCatalogService._infer_category(
                        file_name=file_name,
                        model_name="",
                        tags=tags,
                        trigger_words=(),
                    ),
                    expected,
                )

    def test_archive_summary_keeps_functional_categories_out_of_unknown(self) -> None:
        records = tuple(
            LoraRecord(f"{category}.safetensors", category=category)
            for category in (
                "speed_sampling",
                "quality_enhancement",
                "detail_restoration",
                "composition_pose",
                "lighting_color",
                "background_environment",
                "clothing_concept",
            )
        )

        summary = LoraCatalogService.archive_summary(records)

        for record in records:
            self.assertEqual(summary["categories"][record.category], 1)
        self.assertEqual(summary["categories"]["unknown"], 0)


class FunctionalPresetCategoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_style_and_functional_stack_remains_artist_style_preset(self) -> None:
        records = (
            LoraRecord("style", category="artist_style"),
            LoraRecord("quality", category="quality_enhancement"),
            LoraRecord("details", category="detail_restoration"),
            LoraRecord("lighting", category="lighting_color"),
            LoraRecord("background", category="background_environment"),
        )

        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return records

        service = Catalog(PluginSettings.from_mapping({}))
        selections = tuple(LoraSelection(record.name, 0.5) for record in records)

        self.assertEqual(
            await service.infer_preset_category(selections),
            "artist_style",
        )

    async def test_character_mixed_with_functional_stack_is_mixed_preset(self) -> None:
        records = (
            LoraRecord("character", category="character"),
            LoraRecord("quality", category="quality_enhancement"),
        )

        class Catalog(LoraCatalogService):
            async def _get_records(self, *_args, **_kwargs):
                return records

        service = Catalog(PluginSettings.from_mapping({}))
        selections = tuple(LoraSelection(record.name, 0.5) for record in records)

        self.assertEqual(await service.infer_preset_category(selections), "mixed")


if __name__ == "__main__":
    unittest.main()
