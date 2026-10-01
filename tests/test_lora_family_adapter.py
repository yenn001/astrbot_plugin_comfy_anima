"""Model-family LoRA selection and declarative native character bypass tests."""

import unittest

from ..models import LoraSelection
from ..services.lora_catalog import LoraRecord
from ..services.lora_compatibility import ANIMA_29B_FAMILY
from ..services.lora_family_adapter import (
    adapt_lora_selections_for_target,
    is_29b_model_family,
)


class LoraFamilyAdapterTests(unittest.TestCase):
    """验证根据底模自动切换 LoRA 变体与内生免挂逻辑。"""

    def test_detect_29b_model_family(self) -> None:
        self.assertTrue(is_29b_model_family("anima_29b_40l"))
        self.assertTrue(is_29b_model_family("", "workflow/anima_29b_base_api.json"))
        self.assertTrue(is_29b_model_family("", "Anima-2.9B-preview-v1.safetensors"))
        self.assertTrue(is_29b_model_family("", "checkpoints/my_model_40l.safetensors"))

        self.assertFalse(is_29b_model_family("anima_legacy_28l"))
        self.assertFalse(is_29b_model_family("", "workflow/anima_base_api.json"))
        self.assertFalse(is_29b_model_family("", "Anima-Pencil-XL.safetensors"))

    def test_adapt_upgrade_to_29b_on_29b_target(self) -> None:
        base_record = LoraRecord(
            name="characters/denia.safetensors",
            companion_variant="characters/denia_29b.safetensors",
            character_name="达妮娅",
            trigger_words=("denia",),
        )
        variant_record = LoraRecord(
            name="characters/denia_29b.safetensors",
            companion_variant="characters/denia.safetensors",
            character_name="达妮娅",
            trigger_words=("denia",),
            compatible_model_families=(ANIMA_29B_FAMILY,),
            compatibility_mode="native_29b",
        )
        records = {
            "characters/denia": base_record,
            "characters/denia_29b": variant_record,
        }

        # 用户/LLM 原本选了原版 denia
        selections = (LoraSelection("characters/denia", 0.8),)

        # 在 2.9B 底模下执行适配
        adapted, bypassed, logs = adapt_lora_selections_for_target(
            selections,
            target_family="anima_29b_40l",
            records_by_name=records,
        )

        self.assertEqual(len(adapted), 1)
        self.assertEqual(adapted[0].name, "characters/denia_29b")
        self.assertEqual(adapted[0].strength, 0.8)
        self.assertEqual(len(bypassed), 0)
        self.assertTrue(any("2.9B" in log and "切换为专属变体" in log for log in logs))

    def test_adapt_downgrade_to_base_on_legacy_target(self) -> None:
        base_record = LoraRecord(
            name="characters/denia.safetensors",
            companion_variant="characters/denia_29b.safetensors",
            character_name="达妮娅",
        )
        variant_record = LoraRecord(
            name="characters/denia_29b.safetensors",
            companion_variant="characters/denia.safetensors",
            character_name="达妮娅",
        )
        records = {
            "characters/denia": base_record,
            "characters/denia_29b": variant_record,
        }

        # 用户/LLM 选了 29b 版本
        selections = (LoraSelection("characters/denia_29b", 0.7),)

        # 在常规底模下执行适配
        adapted, bypassed, logs = adapt_lora_selections_for_target(
            selections,
            target_family="anima_legacy_28l",
            records_by_name=records,
        )

        self.assertEqual(len(adapted), 1)
        self.assertEqual(adapted[0].name, "characters/denia")
        self.assertEqual(adapted[0].strength, 0.7)
        self.assertEqual(len(bypassed), 0)
        self.assertTrue(any("常规模型" in log and "回退为原版" in log for log in logs))

    def test_strip_legacy_lora_without_29b_variant_on_29b_target(self) -> None:
        # anima-000040 是旧 28 层 LoRA，无 29b 变体，也未声明 29B
        legacy_record = LoraRecord(
            name="anima-000040.safetensors",
            character_name="达妮娅",
            trigger_words=("denia",),
        )
        records = {"anima-000040": legacy_record}
        selections = (LoraSelection("anima-000040", 0.9),)

        adapted, bypassed, logs = adapt_lora_selections_for_target(
            selections,
            target_family="anima_29b_40l",
            records_by_name=records,
        )

        # 在 2.9B 底模下，非 29b 变体且未声明 29B 的旧 LoRA 必须被自动剥离拦截
        self.assertEqual(len(adapted), 0)
        self.assertTrue(any("自动拦截并剥离非 2.9B 架构的旧 LoRA" in log for log in logs))

    def test_native_character_bypass_on_29b_target(self) -> None:
        # 达妮娅声明在 2.9B 底模下已原生支持
        denia_record = LoraRecord(
            name="characters/denia.safetensors",
            character_name="达妮娅",
            trigger_words=("denia", "blue ribbon"),
            native_in_families=(ANIMA_29B_FAMILY,),
        )
        records = {"characters/denia": denia_record}
        selections = (LoraSelection("characters/denia", 0.8),)

        # 在 2.9B 底模下适配：应自动免挂 LoRA
        adapted, bypassed, logs = adapt_lora_selections_for_target(
            selections,
            target_family="anima_29b_40l",
            records_by_name=records,
        )

        # 待挂载 LoRA 列表应为空（免挂）
        self.assertEqual(len(adapted), 0)
        # bypassed 列表包含达妮娅，用于提取 Prompt Tag
        self.assertEqual(len(bypassed), 1)
        self.assertEqual(bypassed[0].name, "characters/denia.safetensors")
        self.assertTrue(any("原生内生角色" in log and "免挂 LoRA" in log for log in logs))

        # 在常规底模下适配：依然正常挂载 LoRA
        adapted_legacy, bypassed_legacy, _ = adapt_lora_selections_for_target(
            selections,
            target_family="anima_legacy_28l",
            records_by_name=records,
        )
        self.assertEqual(len(adapted_legacy), 1)
        self.assertEqual(len(bypassed_legacy), 0)
