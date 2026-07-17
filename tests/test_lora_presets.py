"""LoRA 组合预设注册、配置序列化与命令参数测试。"""

import asyncio
import importlib
import types
import unittest
from pathlib import Path

from ..core.workflow import WorkflowError, parse_generation_options
from ..models import GenerationJob, GenerationOptions, LoraSelection
from ..services.lora_catalog import LoraRecord
from ..services.lora_presets import (
    PRESET_CATEGORY_ARTIST_STYLE,
    PRESET_CATEGORY_MIXED,
    LoraPresetError,
    LoraPresetRegistry,
    deduplicate_selections,
    parse_lora_entries,
)
from .test_main_compat import _install_astrbot_stubs


def _selection(name: str, strength: float = 0.8) -> tuple[LoraSelection, ...]:
    return (LoraSelection(name, strength),)


class LoraPresetRegistryTests(unittest.TestCase):
    """验证预设命名、分类、选择和持久化行为。"""

    def test_numeric_names_are_normalized_by_category(self) -> None:
        registry = LoraPresetRegistry([])

        character = registry.save(
            name="1",
            category="角色",
            selections=_selection("characters/denia"),
        )
        style = registry.save(
            name="02",
            category="画师",
            selections=_selection("styles/soft-light"),
        )
        mixed = registry.save(
            name="3",
            category="混合",
            selections=_selection("mix/cinematic"),
        )

        self.assertEqual(character.name, "角色1")
        self.assertEqual(style.name, "风格02")
        self.assertEqual(mixed.name, "组合3")

    def test_custom_name_is_preserved(self) -> None:
        registry = LoraPresetRegistry([])

        preset = registry.save(
            name="雨夜霁3光",
            category="artist_style",
            selections=_selection("styles/neon-rain", 0.65),
        )

        self.assertEqual(preset.name, "雨夜霁3光")
        self.assertEqual(preset.category, PRESET_CATEGORY_ARTIST_STYLE)

    def test_numeric_name_from_template_list_is_normalized(self) -> None:
        registry = LoraPresetRegistry(
            [
                {
                    "__template_key": "character_combo",
                    "name": "007",
                    "loras": ["characters/denia=0.8"],
                    "enabled": True,
                }
            ]
        )

        self.assertEqual(registry.presets[0].name, "角色007")
        self.assertEqual(registry.to_config()[0]["name"], "角色007")

    def test_template_list_round_trip_preserves_all_fields(self) -> None:
        raw_config = [
            {
                "__template_key": "character_combo",
                "name": "角色1",
                "loras": [
                    "characters/denia.safetensors=0.8",
                    "characters/eyes=0.45",
                ],
                "trigger_words": "denia, silver hair",
                "description": "默认角色组合",
                "enabled": True,
            },
            {
                "__template_key": "artist_style_combo",
                "name": "风格1",
                "loras": ["styles/ink=0.7"],
                "trigger_words": "ink wash",
                "description": "水墨画风",
                "enabled": False,
            },
        ]

        first = LoraPresetRegistry(raw_config)
        serialized = first.to_config()
        second = LoraPresetRegistry(serialized)

        self.assertEqual(second.to_config(), serialized)
        self.assertEqual(second.presets[0].selections[0].name, "characters/denia")
        self.assertFalse(second.presets[1].enabled)

    def test_list_filters_by_category_keyword_and_enabled_state(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="角色1",
            category="character",
            selections=_selection("characters/denia"),
            trigger_words="silver hair",
        )
        registry.save(
            name="柔光风格",
            category="style",
            selections=_selection("styles/soft-light"),
            description="portrait lighting",
        )
        registry.save(
            name="禁用组合",
            category="mixed",
            selections=_selection("mixed/disabled"),
            enabled=False,
        )

        styles = registry.list_presets(category="画师")
        keyword = registry.list_presets(keyword="silver")
        all_items = registry.list_presets(enabled_only=False)

        self.assertEqual([item.name for item in styles], ["柔光风格"])
        self.assertEqual([item.name for item in keyword], ["角色1"])
        self.assertEqual(len(all_items), 3)

    def test_resolve_accepts_one_based_index_and_case_insensitive_name(self) -> None:
        registry = LoraPresetRegistry([])
        first = registry.save(
            name="角色1",
            category="character",
            selections=_selection("characters/denia"),
        )
        second = registry.save(
            name="Night Style",
            category="style",
            selections=_selection("styles/night"),
        )

        self.assertIs(registry.resolve("1"), first)
        self.assertIs(registry.resolve("night style"), second)
        with self.assertRaises(LoraPresetError):
            registry.resolve("99")

    def test_filtered_display_keeps_global_index_used_by_resolve(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="角色1",
            category="character",
            selections=_selection("characters/denia"),
        )
        style = registry.save(
            name="风格1",
            category="style",
            selections=_selection("styles/ink"),
        )
        registry.save(
            name="组合1",
            category="mixed",
            selections=_selection("mixed/cinematic"),
        )

        filtered = registry.format_for_llm(category="style")

        self.assertIn("- 2. 风格1", filtered)
        self.assertIs(registry.resolve("2"), style)

    def test_natural_language_style_mention_uses_exact_saved_name(self) -> None:
        registry = LoraPresetRegistry([])
        shorter = registry.save(
            name="风格001",
            category="style",
            selections=_selection("styles/one"),
        )
        longer = registry.save(
            name="风格0012",
            category="style",
            selections=_selection("styles/twelve"),
        )

        self.assertIs(registry.find_mentioned_style("用风格001画猫娘"), shorter)
        self.assertIs(registry.find_mentioned_style("风格0012画猫娘"), longer)
        self.assertIsNone(registry.find_mentioned_style("画一张猫娘"))

    def test_trailing_style_note_can_be_omitted_when_resolving(self) -> None:
        registry = LoraPresetRegistry([])
        annotated = registry.save(
            name="风格2（凛然）",
            category="style",
            selections=_selection("styles/dignified"),
        )

        self.assertIs(registry.resolve("风格2"), annotated)
        self.assertIs(registry.resolve("风格 02"), annotated)
        self.assertIs(
            registry.find_mentioned_style("请用风格2画达妮娅"),
            annotated,
        )

    def test_ambiguous_omitted_note_requires_full_style_name(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格2（凛然）",
            category="style",
            selections=_selection("styles/dignified"),
        )
        registry.save(
            name="风格2（柔和）",
            category="style",
            selections=_selection("styles/soft"),
        )

        with self.assertRaisesRegex(LoraPresetError, "对应多个预设"):
            registry.resolve("风格2")
        self.assertIsNone(registry.find_mentioned_style("用风格2画图"))

    def test_save_overwrites_same_name_case_insensitively(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="Night Style",
            category="style",
            selections=_selection("styles/old", 0.5),
        )

        updated = registry.save(
            name="night style",
            category="mixed",
            selections=_selection("styles/new", 1.1),
            trigger_words="new trigger",
        )

        self.assertEqual(len(registry.presets), 1)
        self.assertIs(registry.presets[0], updated)
        self.assertEqual(updated.category, PRESET_CATEGORY_MIXED)
        self.assertEqual(updated.selections, _selection("styles/new", 1.1))
        self.assertEqual(updated.trigger_words, "new trigger")

    def test_delete_accepts_name_and_index(self) -> None:
        registry = LoraPresetRegistry([])
        first = registry.save(
            name="角色1",
            category="character",
            selections=_selection("characters/one"),
        )
        registry.save(
            name="风格1",
            category="style",
            selections=_selection("styles/one"),
        )

        self.assertIs(registry.delete("角色1"), first)
        self.assertEqual(registry.delete("1").name, "风格1")
        self.assertEqual(registry.presets, ())

    def test_disabled_preset_can_still_be_deleted(self) -> None:
        registry = LoraPresetRegistry(
            [
                {
                    "__template_key": "artist_style_combo",
                    "name": "禁用风格",
                    "loras": ["styles/disabled=0.8"],
                    "enabled": False,
                }
            ]
        )

        with self.assertRaisesRegex(LoraPresetError, "已禁用"):
            registry.resolve("1")
        deleted = registry.delete("1")

        self.assertEqual(deleted.name, "禁用风格")
        self.assertEqual(registry.presets, ())


class LoraPresetParsingTests(unittest.TestCase):
    """验证 LoRA 串解析、去重和安全限制。"""

    def test_deduplicate_normalizes_name_and_last_weight_wins(self) -> None:
        result = deduplicate_selections(
            (
                LoraSelection(r"Characters\Denia.safetensors", 0.5),
                LoraSelection("characters/denia", 0.9),
                LoraSelection("styles/ink.pt", 0.7),
            )
        )

        self.assertEqual(
            result,
            (
                LoraSelection("characters/denia", 0.9),
                LoraSelection("styles/ink", 0.7),
            ),
        )

    def test_parse_accepts_tags_and_name_weight_entries(self) -> None:
        result = parse_lora_entries(
            [
                "<lora:characters/denia:0.8>, <lora:styles/ink:0.6>",
                "details/eyes.safetensors=0.35",
            ],
            max_loras=3,
        )

        self.assertEqual(
            result,
            (
                LoraSelection("characters/denia", 0.8),
                LoraSelection("styles/ink", 0.6),
                LoraSelection("details/eyes", 0.35),
            ),
        )

    def test_parse_rejects_weight_outside_zero_to_two(self) -> None:
        for weight in ("-0.01", "2.01"):
            with self.subTest(weight=weight), self.assertRaises(LoraPresetError):
                parse_lora_entries([f"styles/ink={weight}"], max_loras=1)

    def test_parse_and_save_reject_non_finite_weights(self) -> None:
        for weight in ("nan", "inf", "-inf"):
            with self.subTest(source="parse", weight=weight):
                with self.assertRaises(LoraPresetError):
                    parse_lora_entries([f"styles/ink={weight}"], max_loras=1)

            with self.subTest(source="save", weight=weight):
                registry = LoraPresetRegistry([])
                with self.assertRaises(LoraPresetError):
                    registry.save(
                        name="invalid",
                        category="style",
                        selections=(LoraSelection("styles/ink", float(weight)),),
                    )

    def test_parse_rejects_partially_invalid_tag_strings(self) -> None:
        invalid_entries = (
            "<lora:styles/ink:0.8>, unexpected text",
            "<lora:styles/ink:0.8>, <lora:broken:not-a-number>",
        )
        for entry in invalid_entries:
            with self.subTest(entry=entry), self.assertRaises(LoraPresetError):
                parse_lora_entries([entry], max_loras=2)

    def test_parse_and_save_enforce_max_lora_count(self) -> None:
        with self.assertRaises(LoraPresetError):
            parse_lora_entries(["a=0.5", "b=0.6"], max_loras=1)

        registry = LoraPresetRegistry([], max_loras=1)
        with self.assertRaises(LoraPresetError):
            registry.save(
                name="too-many",
                category="mixed",
                selections=(LoraSelection("a", 0.5), LoraSelection("b", 0.6)),
            )


class PresetCommandParserTests(unittest.TestCase):
    """验证 `/anima draw` 和中文直接绘图的预设参数。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_parse_generation_options_accepts_preset_and_alias(self) -> None:
        result = parse_generation_options(
            '1girl, rainy street --preset "风格 1" --seed 42'
        )
        alias = parse_generation_options("portrait --lora-preset 自定义组合")

        self.assertEqual(result.prompt, "1girl, rainy street")
        self.assertEqual(result.lora_preset, "风格 1")
        self.assertEqual(result.seed, 42)
        self.assertEqual(alias.lora_preset, "自定义组合")

    def test_extract_preset_option_removes_quoted_option(self) -> None:
        extractor = self.main.ComfyAnimaPlugin._extract_preset_option

        prompt, preset = extractor(
            '1girl, white hair --preset "雨夜 霁3光" , cinematic lighting'
        )

        self.assertEqual(prompt, "1girl, white hair , cinematic lighting")
        self.assertEqual(preset, "雨夜 霁3光")

    def test_extract_preset_option_accepts_alias_at_start(self) -> None:
        extractor = self.main.ComfyAnimaPlugin._extract_preset_option

        prompt, preset = extractor("--lora-preset 风格1 1girl, portrait")

        self.assertEqual(prompt, "1girl, portrait")
        self.assertEqual(preset, "风格1")

    def test_extract_preset_option_rejects_missing_or_duplicate_value(self) -> None:
        extractor = self.main.ComfyAnimaPlugin._extract_preset_option

        with self.assertRaises(ValueError):
            extractor("1girl --preset")
        with self.assertRaises(ValueError):
            extractor("1girl --preset 风格1 --lora-preset 角色1")

    def test_resolution_helpers_parse_natural_language_and_size_option(self) -> None:
        plugin_class = self.main.ComfyAnimaPlugin

        self.assertEqual(
            plugin_class._extract_resolution_request("帮我画一张猫娘，分辨率 832×1216"),
            (832, 1216),
        )
        self.assertEqual(
            plugin_class._extract_resolution_request("帮我画一张猫娘"),
            (None, None),
        )
        cleaned, width, height = plugin_class._extract_size_option(
            '1girl, portrait --size "1024x1536"'
        )
        self.assertEqual(cleaned, "1girl, portrait")
        self.assertEqual((width, height), (1024, 1536))

    def test_resolution_helpers_reject_invalid_or_duplicate_size(self) -> None:
        plugin_class = self.main.ComfyAnimaPlugin

        with self.assertRaises(ValueError):
            plugin_class._extract_resolution_request("分辨率 100x1216")
        with self.assertRaises(ValueError):
            plugin_class._extract_size_option("1girl --size")
        with self.assertRaises(ValueError):
            plugin_class._extract_size_option("1girl --size 832x1216 --size 1024x1536")


class _CapturingWorkflowBuilder:
    """捕获 `_execute_job` 最终交给工作流的参数。"""

    def __init__(self) -> None:
        self.options = None

    def build(self, options):
        self.options = options
        return {"captured": True}, 123456, ["output"]


class _FakeComfyClient:
    """不访问网络的最小 ComfyUI 客户端。"""

    def __init__(self) -> None:
        self.submitted_workflow = None

    async def submit(self, workflow):
        self.submitted_workflow = workflow
        return "prompt-id"

    async def wait_for_images(self, _prompt_id, _preferred_nodes):
        return []

    async def cancel(self, _prompt_id):
        return None


class _RecordingLoraCatalog:
    """Record each source group resolved against the same fresh catalog."""

    def __init__(self) -> None:
        self.groups = []
        self.strict_values = []

    async def resolve_selections(self, selections, *, strict):
        self.groups.append(tuple(selections))
        self.strict_values.append(strict)
        return tuple(selections)

    async def resolve_selections_with_records(self, selections, *, strict):
        resolved = await self.resolve_selections(selections, strict=strict)
        records = {
            selection.name.casefold(): LoraRecord(selection.name)
            for selection in resolved
        }
        return resolved, records


class ExecuteJobPresetTests(unittest.IsolatedAsyncioTestCase):
    """验证预设在实际生成执行路径中的合并与报错行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _make_plugin(
        self,
        registry: LoraPresetRegistry,
        *,
        max_total: int = 8,
        catalog=None,
        default_style_preset: str = "",
    ):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_prompt_llm=False,
            max_dynamic_loras=8,
            max_total_dynamic_loras=max_total,
            strict_lora_validation=catalog is not None,
            max_prompt_length=2000,
            default_style_preset=default_style_preset,
        )
        plugin._generation_slots = asyncio.Semaphore(1)
        plugin._workflow_builder = _CapturingWorkflowBuilder()
        plugin._client = _FakeComfyClient()
        plugin._lora_presets = registry
        plugin._lora_catalog = catalog

        async def refresh_lora_manager(_action):
            return 1

        plugin._refresh_lora_manager_before = refresh_lora_manager
        plugin._temp_dir = Path(".")
        plugin._director = None
        plugin._director_error = None
        return plugin

    @staticmethod
    def _job() -> GenerationJob:
        return GenerationJob(user_id="tester", prompt_preview="test", created_at=0.0)

    async def test_execute_job_locks_saved_style_weights_across_sources(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格1",
            category="style",
            selections=(
                LoraSelection("shared/model", 0.2),
                LoraSelection("preset/only", 0.3),
            ),
            trigger_words="preset trigger, vivid colors",
        )
        catalog = _RecordingLoraCatalog()
        plugin = self._make_plugin(registry, catalog=catalog)
        options = GenerationOptions(
            prompt=(
                "<lora:shared/model.safetensors:0.9>, "
                "<lora:prompt/only:0.8>, 1girl, portrait"
            ),
            negative_prompt="bad hands, preset trigger",
            use_prompt_llm=False,
            lora_preset="风格1",
            dynamic_loras=(
                LoraSelection("SHARED\\MODEL", 0.6),
                LoraSelection("command/only", 0.7),
            ),
        )

        result = await plugin._execute_job(self._job(), options, object())
        built = plugin._workflow_builder.options

        expected_loras = (
            LoraSelection("shared/model", 0.2),
            LoraSelection("preset/only", 0.3),
            LoraSelection("command/only", 0.7),
            LoraSelection("prompt/only", 0.8),
        )
        self.assertEqual(built.dynamic_loras, expected_loras)
        self.assertEqual(
            catalog.groups,
            [
                (
                    LoraSelection("shared/model", 0.2),
                    LoraSelection("preset/only", 0.3),
                ),
                (
                    LoraSelection("SHARED\\MODEL", 0.6),
                    LoraSelection("command/only", 0.7),
                ),
                (
                    LoraSelection("shared/model", 0.9),
                    LoraSelection("prompt/only", 0.8),
                ),
            ],
        )
        self.assertTrue(all(catalog.strict_values))
        self.assertEqual(
            built.prompt,
            "1girl, portrait, vivid colors",
        )
        self.assertEqual(built.negative_prompt, "bad hands, preset trigger")
        self.assertNotIn("<lora:", built.prompt)
        self.assertEqual(result[2], built.prompt)
        self.assertEqual(built.lora_injection_mode, "replace")

    async def test_character_preset_appends_after_default_style(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格001",
            category="style",
            selections=(
                LoraSelection("style/base-a", 0.5),
                LoraSelection("style/base-b", 0.4),
            ),
            trigger_words="style trigger",
        )
        registry.save(
            name="角色001",
            category="character",
            selections=(LoraSelection("characters/hero", 0.8),),
            trigger_words="hero trigger",
        )
        catalog = _RecordingLoraCatalog()
        plugin = self._make_plugin(
            registry,
            catalog=catalog,
            default_style_preset="风格001",
        )
        options = GenerationOptions(
            prompt="<lora:details/accessory:0.35>, 1girl, portrait",
            negative_prompt="bad hands",
            use_prompt_llm=False,
            lora_preset="角色001",
        )

        await plugin._execute_job(self._job(), options, object())
        built = plugin._workflow_builder.options

        self.assertEqual(
            built.dynamic_loras,
            (
                LoraSelection("style/base-a", 0.5),
                LoraSelection("style/base-b", 0.4),
                LoraSelection("characters/hero", 0.8),
                LoraSelection("details/accessory", 0.35),
            ),
        )
        self.assertEqual(built.lora_injection_mode, "replace")
        self.assertEqual(
            built.prompt,
            "1girl, portrait, style trigger, hero trigger",
        )
        self.assertEqual(built.negative_prompt, "bad hands")

    async def test_default_style_is_used_when_no_style_is_requested(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格001",
            category="style",
            selections=(LoraSelection("style/default", 0.55),),
        )
        plugin = self._make_plugin(
            registry,
            catalog=_RecordingLoraCatalog(),
            default_style_preset="风格001",
        )

        await plugin._execute_job(
            self._job(),
            GenerationOptions(
                prompt="1girl, portrait",
                use_prompt_llm=False,
            ),
            object(),
        )
        built = plugin._workflow_builder.options

        self.assertEqual(
            built.dynamic_loras,
            (LoraSelection("style/default", 0.55),),
        )
        self.assertEqual(built.lora_injection_mode, "replace")

    async def test_explicit_style_overrides_default_style(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格001",
            category="style",
            selections=(LoraSelection("style/default", 0.5),),
        )
        registry.save(
            name="风格002",
            category="style",
            selections=(LoraSelection("style/selected", 0.75),),
        )
        plugin = self._make_plugin(
            registry,
            catalog=_RecordingLoraCatalog(),
            default_style_preset="风格001",
        )

        await plugin._execute_job(
            self._job(),
            GenerationOptions(
                prompt="<lora:characters/hero:0.8>, 1girl",
                use_prompt_llm=False,
                lora_preset="风格002",
            ),
            object(),
        )
        built = plugin._workflow_builder.options

        self.assertEqual(
            built.dynamic_loras,
            (
                LoraSelection("style/selected", 0.75),
                LoraSelection("characters/hero", 0.8),
            ),
        )
        self.assertNotIn(
            "style/default",
            {selection.name for selection in built.dynamic_loras},
        )
        self.assertEqual(built.lora_injection_mode, "replace")

    async def test_expanded_saved_style_replaces_default_without_duplication(
        self,
    ) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="风格001",
            category="style",
            selections=(LoraSelection("style/default", 0.5),),
        )
        registry.save(
            name="风格002",
            category="style",
            selections=(
                LoraSelection("style/second-a", 0.6),
                LoraSelection("style/second-b", 0.7),
            ),
        )
        plugin = self._make_plugin(
            registry,
            catalog=_RecordingLoraCatalog(),
            default_style_preset="风格001",
        )

        await plugin._execute_job(
            self._job(),
            GenerationOptions(
                prompt=("<lora:style/second-a:0.6>, <lora:style/second-b:0.7>, 1girl"),
                use_prompt_llm=False,
            ),
            object(),
        )
        built = plugin._workflow_builder.options

        self.assertEqual(
            built.dynamic_loras,
            (
                LoraSelection("style/second-a", 0.6),
                LoraSelection("style/second-b", 0.7),
            ),
        )
        self.assertEqual(built.lora_injection_mode, "replace")

    async def test_execute_job_rejects_total_lora_count_over_limit(self) -> None:
        registry = LoraPresetRegistry([])
        registry.save(
            name="组合1",
            category="mixed",
            selections=(LoraSelection("preset/a", 0.5), LoraSelection("preset/b", 0.5)),
        )
        plugin = self._make_plugin(registry, max_total=3)
        options = GenerationOptions(
            prompt="<lora:prompt/d:0.8>, 1girl",
            use_prompt_llm=False,
            lora_preset="组合1",
            dynamic_loras=(LoraSelection("command/c", 0.7),),
        )

        with self.assertRaisesRegex(WorkflowError, "合计最多允许 3 个"):
            await plugin._execute_job(self._job(), options, object())

        self.assertIsNone(plugin._workflow_builder.options)
        self.assertIsNone(plugin._client.submitted_workflow)

    async def test_execute_job_rejects_unknown_preset(self) -> None:
        plugin = self._make_plugin(LoraPresetRegistry([]))
        options = GenerationOptions(
            prompt="1girl, portrait",
            use_prompt_llm=False,
            lora_preset="不存在的组合",
        )

        with self.assertRaisesRegex(WorkflowError, "找不到 LoRA 组合"):
            await plugin._execute_job(self._job(), options, object())

        self.assertIsNone(plugin._workflow_builder.options)
        self.assertIsNone(plugin._client.submitted_workflow)

    async def test_execute_job_rejects_unavailable_default_style(self) -> None:
        plugin = self._make_plugin(
            LoraPresetRegistry([]),
            default_style_preset="风格001",
        )
        options = GenerationOptions(
            prompt="1girl, portrait",
            use_prompt_llm=False,
        )

        with self.assertRaisesRegex(WorkflowError, "默认风格预设.*不可用"):
            await plugin._execute_job(self._job(), options, object())

        self.assertIsNone(plugin._workflow_builder.options)
        self.assertIsNone(plugin._client.submitted_workflow)

    async def test_execute_job_rejects_disabled_default_style(self) -> None:
        registry = LoraPresetRegistry(
            [
                {
                    "__template_key": "artist_style_combo",
                    "name": "风格001",
                    "loras": ["style/default=0.5"],
                    "enabled": False,
                }
            ]
        )
        plugin = self._make_plugin(
            registry,
            default_style_preset="风格001",
        )

        with self.assertRaisesRegex(WorkflowError, "默认风格预设.*不可用"):
            await plugin._execute_job(
                self._job(),
                GenerationOptions(prompt="1girl", use_prompt_llm=False),
                object(),
            )

        self.assertIsNone(plugin._workflow_builder.options)
        self.assertIsNone(plugin._client.submitted_workflow)


class ConfigPersistenceTests(unittest.TestCase):
    """验证配置保存失败时不留下内存脏数据。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_persist_config_restores_previous_value_when_save_fails(self) -> None:
        class FailingConfig(dict):
            def save_config(self):
                raise RuntimeError("disk unavailable")

        config = FailingConfig(lora_presets=[{"name": "old"}])
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.config = config

        result = plugin._persist_config("lora_presets", [{"name": "new"}])

        self.assertFalse(result)
        self.assertEqual(config["lora_presets"], [{"name": "old"}])


if __name__ == "__main__":
    unittest.main()
