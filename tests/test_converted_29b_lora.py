"""测试 _29b 转换版 LoRA 的识别、元数据/触发词继承及提示词生成联动。"""

import unittest

from ..core.lora import canonical_lora_name
from ..models import LoraSelection
from ..services.lora_catalog import LoraCatalogService, LoraRecord
from ..services.lora_compatibility import ANIMA_29B_FAMILY, assess_lora_compatibility
from ..services.lora_prompting import build_lora_trigger_plan


class Converted29BLoraTests(unittest.TestCase):
    """验证 _29b 衍生 LoRA 的命名识别与元数据继承。"""

    def test_derive_base_lora_name_variants(self) -> None:
        derive = LoraCatalogService._derive_base_lora_name

        self.assertEqual(derive("denia_29b.safetensors"), "denia")
        self.assertEqual(derive("denia-29b.safetensors"), "denia")
        self.assertEqual(derive("characters/denia_29B.safetensors"), "characters/denia")
        self.assertEqual(derive("styles/watercolor_29b_40l.safetensors"), "styles/watercolor")
        self.assertEqual(derive("concept_40l.safetensors"), "concept")

        # 非 29b 衍生文件名应返回 None
        self.assertIsNone(derive("denia.safetensors"))
        self.assertIsNone(derive("29b.safetensors"))
        self.assertIsNone(derive("characters/29b"))

    def test_inherit_metadata_and_triggers_same_directory(self) -> None:
        base_record = LoraRecord(
            name="characters/miku.safetensors",
            trigger_words=("hatsune miku", "twintails", "aqua hair"),
            character_name="初音未来 / Hatsune Miku",
            source_work="Vocaloid",
            category="character",
            description="Official Miku LoRA",
            model_name="Miku SDXL",
            preview_url="http://127.0.0.1/preview_miku.png",
            tags=("vocaloid", "singer"),
            aliases=("初音", "miku"),
        )
        # 经过转换的 29b 衍生文件，Manager 只有空白元数据
        derived_record = LoraRecord(
            name="characters/miku_29b.safetensors",
            trigger_words=(),
            character_name="",
            source_work="",
            category="unknown",
            description="",
            model_name="",
            preview_url="",
            tags=(),
            aliases=(),
        )

        inherited = LoraCatalogService._inherit_converted_29b_metadata(
            (base_record, derived_record)
        )
        self.assertEqual(len(inherited), 2)
        miku_29b = inherited[1]

        # 触发词和角色信息应完全继承
        self.assertEqual(miku_29b.trigger_words, ("hatsune miku", "twintails", "aqua hair"))
        self.assertEqual(miku_29b.character_name, "初音未来 / Hatsune Miku")
        self.assertEqual(miku_29b.source_work, "Vocaloid")
        self.assertEqual(miku_29b.category, "character")
        self.assertEqual(miku_29b.description, "Official Miku LoRA")
        self.assertEqual(miku_29b.model_name, "Miku SDXL")
        self.assertEqual(miku_29b.preview_url, "http://127.0.0.1/preview_miku.png")
        self.assertIn("vocaloid", miku_29b.tags)
        self.assertIn("初音", miku_29b.aliases)

        # 必须标记 2.9B 模型家族和 native_29b 兼容模式
        self.assertIn(ANIMA_29B_FAMILY, miku_29b.compatible_model_families)
        self.assertEqual(miku_29b.compatibility_mode, "native_29b")

        # 验证兼容性评估通过
        compat = assess_lora_compatibility(miku_29b, ANIMA_29B_FAMILY)
        self.assertTrue(compat.eligible)
        self.assertEqual(compat.mode, "native_29b")

    def test_cross_directory_fallback_by_basename(self) -> None:
        # 原版在根目录，29b 转换版在 converted_29b 子目录
        base_record = LoraRecord(
            name="artoria.safetensors",
            trigger_words=("artoria pendragon", "ahoge"),
            character_name="阿尔托莉雅",
            category="character",
        )
        derived_record = LoraRecord(
            name="converted_29b/artoria_29b.safetensors",
            trigger_words=(),
        )

        inherited = LoraCatalogService._inherit_converted_29b_metadata(
            (base_record, derived_record)
        )
        artoria_29b = inherited[1]
        self.assertEqual(artoria_29b.trigger_words, ("artoria pendragon", "ahoge"))
        self.assertEqual(artoria_29b.character_name, "阿尔托莉雅")
        self.assertIn(ANIMA_29B_FAMILY, artoria_29b.compatible_model_families)

    def test_merge_triggers_if_derived_has_triggers(self) -> None:
        base_record = LoraRecord(
            name="rin.safetensors",
            trigger_words=("tohsaka rin", "twin tails"),
            character_name="远坂凛",
            category="character",
        )
        derived_record = LoraRecord(
            name="rin_29b.safetensors",
            trigger_words=("extra_tag", "twin tails"),
        )

        inherited = LoraCatalogService._inherit_converted_29b_metadata(
            (base_record, derived_record)
        )
        rin_29b = inherited[1]
        # 去重且 base 触发词优先保留
        self.assertEqual(rin_29b.trigger_words, ("tohsaka rin", "twin tails", "extra_tag"))

    def test_standalone_29b_without_base_is_safe(self) -> None:
        # 没有原版 LoRA，单存 29b 文件
        derived_record = LoraRecord(
            name="unknown_char_29b.safetensors",
            trigger_words=("some_tag",),
        )
        inherited = LoraCatalogService._inherit_converted_29b_metadata((derived_record,))
        res = inherited[0]
        self.assertEqual(res.trigger_words, ("some_tag",))
        self.assertIn(ANIMA_29B_FAMILY, res.compatible_model_families)
        self.assertEqual(res.compatibility_mode, "native_29b")

    def test_prompt_planning_with_inherited_29b_triggers(self) -> None:
        base_record = LoraRecord(
            name="denia.safetensors",
            trigger_words=("denia", "blue ribbon"),
            character_name="denia",
            category="character",
        )
        derived_record = LoraRecord(
            name="denia_29b.safetensors",
            trigger_words=(),
            character_name="",
            category="unknown",
        )

        records = LoraCatalogService._inherit_converted_29b_metadata(
            (base_record, derived_record)
        )
        record_map = {
            canonical_lora_name(r.name).casefold(): r for r in records
        }

        # 用户提示词中使用 <lora:denia_29b:0.8>
        prompt = "1girl, solo, smile <lora:denia_29b:0.8>"
        plan = build_lora_trigger_plan(
            prompt=prompt,
            negative_prompt="",
            selections=(LoraSelection("denia_29b", 0.8),),
            records_by_name=record_map,
        )

        # 触发词应当根据继承来的角色身份自动生成并注入
        self.assertIn("denia", plan.added)
        self.assertIn("denia", plan.prompt)
