"""Anima 动态 LoRA 标签与工作流注入测试。"""

import unittest

from ..core.lora import extract_lora_selections, inject_loras
from ..models import LoraSelection


class LoraWorkflowTests(unittest.TestCase):
    """验证提示词清理与 LoraManager 节点更新。"""

    def test_extracts_loras_and_keeps_english_prompt(self) -> None:
        cleaned, selections = extract_lora_selections(
            "<lora:角色/black denia.safetensors:0.88>, 1girl, portrait",
            max_loras=3,
        )

        self.assertEqual(cleaned, "1girl, portrait")
        self.assertEqual(selections[0].name, "角色/black denia")
        self.assertEqual(selections[0].strength, 0.88)

    def test_rejects_excessive_lora_count(self) -> None:
        with self.assertRaises(ValueError):
            extract_lora_selections("<lora:a:0.5>, <lora:b:0.5>", max_loras=1)

    def test_append_preserves_base_lora_and_adds_dynamic_lora(self) -> None:
        workflow = {
            "462": {
                "inputs": {
                    "text": "<lora:base:0.5>",
                    "loras": {
                        "__value__": [
                            {
                                "name": "base",
                                "strength": 0.5,
                                "clipStrength": 0.5,
                                "active": True,
                            }
                        ]
                    },
                }
            }
        }

        inject_loras(
            workflow,
            "462",
            (LoraSelection("character", 0.8),),
            mode="append",
        )

        records = workflow["462"]["inputs"]["loras"]["__value__"]
        self.assertEqual([record["name"] for record in records], ["base", "character"])
        self.assertIn("<lora:character:0.8>", workflow["462"]["inputs"]["text"])

    def test_replace_removes_base_loras(self) -> None:
        workflow = {
            "462": {
                "inputs": {
                    "text": "<lora:base:0.5>",
                    "loras": {"__value__": [{"name": "base"}]},
                }
            }
        }

        inject_loras(
            workflow,
            "462",
            (LoraSelection("new", 1.0),),
            mode="replace",
        )

        records = workflow["462"]["inputs"]["loras"]["__value__"]
        self.assertEqual([record["name"] for record in records], ["new"])
        self.assertEqual(workflow["462"]["inputs"]["text"], "<lora:new:1>")


if __name__ == "__main__":
    unittest.main()
