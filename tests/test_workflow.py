"""
AstrBot Comfy Anima 插件 v1.1.0

功能描述：
- 测试工作流参数替换和指令解析

作者: Yen
版本: 1.1.0
日期: 2026-07-14
"""

import unittest
from pathlib import Path

from ..core.workflow import ImageWorkflowBuilder, WorkflowBuilder, parse_generation_options
from ..models import GenerationOptions, LoraSelection, PluginSettings


class WorkflowBuilderTests(unittest.TestCase):
    """工作流构造测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        plugin_dir = Path(__file__).resolve().parents[1]
        cls.settings = PluginSettings.from_mapping(
            {"workflow_file": "workflow/anima_api.json"}
        )
        cls.builder = WorkflowBuilder(
            cls.settings.resolve_workflow_path(plugin_dir), cls.settings
        )

    def test_build_replaces_dynamic_inputs(self) -> None:
        """动态参数应正确写入对应节点。"""
        options = GenerationOptions(
            prompt="1girl, white hair",
            negative_prompt="bad hands",
            seed=123,
            width=1024,
            height=1536,
            steps=24,
            cfg=4.5,
        )
        workflow, seed, preferred = self.builder.build(options)
        self.assertEqual(seed, 123)
        self.assertEqual(workflow["210"]["inputs"]["positive"], options.prompt)
        self.assertIn("bad hands", workflow["13"]["inputs"]["positive"])
        self.assertEqual(workflow["8"]["inputs"]["noise_seed"], 123)
        self.assertEqual(workflow["262"]["inputs"]["seed"], 123)
        self.assertEqual(workflow["437"]["inputs"]["width"], 1024)
        self.assertEqual(workflow["437"]["inputs"]["height"], 1536)
        self.assertEqual(workflow["8"]["inputs"]["steps"], 24)
        self.assertEqual(workflow["8"]["inputs"]["cfg"], 4.5)
        self.assertEqual(preferred[0], "285")

    def test_no_upscale_removes_final_output(self) -> None:
        """禁用放大时应移除最终放大输出节点。"""
        workflow, _, preferred = self.builder.build(
            GenerationOptions(prompt="test", seed=1, enable_upscale=False)
        )
        self.assertNotIn("285", workflow)
        self.assertNotIn("285", preferred)
        self.assertIn("20", preferred)

    def test_dynamic_lora_is_injected_into_anima_node(self) -> None:
        """单次动态 LoRA 应写入工作流节点 462。"""
        workflow, _, _ = self.builder.build(
            GenerationOptions(
                prompt="1girl, portrait",
                seed=1,
                dynamic_loras=(LoraSelection("characters/test", 0.75),),
            )
        )

        node_inputs = workflow["462"]["inputs"]
        self.assertIn("<lora:characters/test:0.75>", node_inputs["text"])
        self.assertTrue(
            any(
                record.get("name") == "characters/test"
                for record in node_inputs["loras"]["__value__"]
            )
        )

    def test_replace_injection_removes_template_style_stack(self) -> None:
        """新风格栈应替换节点 462 原有 LoRA，角色 LoRA 在其后追加。"""
        selections = (
            LoraSelection("styles/selected", 0.65),
            LoraSelection("characters/hero", 0.8),
        )

        workflow, _, _ = self.builder.build(
            GenerationOptions(
                prompt="1girl, portrait",
                seed=1,
                dynamic_loras=selections,
                lora_injection_mode="replace",
            )
        )

        inputs = workflow["462"]["inputs"]
        records = inputs["loras"]["__value__"]
        self.assertEqual(
            [record["name"] for record in records],
            ["styles/selected", "characters/hero"],
        )
        self.assertEqual(
            inputs["text"],
            "<lora:styles/selected:0.65>, <lora:characters/hero:0.8>",
        )

    def test_default_resolution_is_832_by_1216(self) -> None:
        """未指定分辨率时应使用 Anima 竖图默认值。"""
        workflow, _, _ = self.builder.build(
            GenerationOptions(prompt="1girl, portrait", seed=1)
        )

        resolution = workflow["437"]["inputs"]
        self.assertEqual(resolution["width"], 832)
        self.assertEqual(resolution["height"], 1216)

    def test_selected_unet_model_overrides_node_429(self) -> None:
        """Anima 模型必须写入 UNETLoader，而不是 checkpoint 节点。"""
        plugin_dir = Path(__file__).resolve().parents[1]
        settings = PluginSettings.from_mapping(
            {
                "workflow_file": "workflow/anima_api.json",
                "unet_model_name": "miaomiaoHarem_anima13.safetensors",
            }
        )
        builder = WorkflowBuilder(
            settings.resolve_workflow_path(plugin_dir),
            settings,
        )
        workflow, _, _ = builder.build(
            GenerationOptions(prompt="1girl, portrait", seed=1)
        )
        self.assertEqual(
            workflow["429"]["class_type"],
            "UNETLoader",
        )
        self.assertEqual(
            workflow["429"]["inputs"]["unet_name"],
            "miaomiaoHarem_anima13.safetensors",
        )


class AnimaV2WorkflowTests(unittest.TestCase):
    """Validate isolated Anima V2 and standalone RTX workflow profiles."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin_dir = Path(__file__).resolve().parents[1]

    def test_anima_v2_bindings_do_not_use_legacy_node_ids(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "workflow_file": "workflow/anima_v2_api.json",
                "unet_model_name": "replacement-anima.safetensors",
                "sampler_steps_override": 12,
                "enable_upscale": True,
            }
        )
        builder = WorkflowBuilder(
            settings.resolve_workflow_path(self.plugin_dir),
            settings,
        )
        workflow, seed, preferred = builder.build(
            GenerationOptions(
                prompt="1girl, black hair",
                negative_prompt="school uniform",
                seed=99,
                width=896,
                height=1152,
                dynamic_loras=(LoraSelection("characters/hero", 0.8),),
                lora_injection_mode="replace",
            )
        )
        self.assertEqual(builder.profile.profile_id, "anima_v2")
        self.assertEqual(seed, 99)
        self.assertEqual(workflow["11"]["inputs"]["text"], "1girl, black hair")
        self.assertIn("school uniform", workflow["12"]["inputs"]["text"])
        self.assertEqual(workflow["19"]["inputs"]["seed"], 99)
        self.assertEqual(workflow["19"]["inputs"]["steps"], 12)
        self.assertEqual(workflow["28"]["inputs"]["width"], 896)
        self.assertEqual(workflow["28"]["inputs"]["height"], 1152)
        self.assertEqual(
            workflow["44"]["inputs"]["unet_name"],
            "replacement-anima.safetensors",
        )
        self.assertEqual(
            workflow["462"]["inputs"]["loras"]["__value__"][0]["name"],
            "characters/hero",
        )
        self.assertEqual(workflow["462"]["inputs"]["clip"], ["45", 0])
        self.assertEqual(workflow["462"]["inputs"]["model"], ["44", 0])
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["462", 1])
        self.assertNotIn("66", workflow)
        self.assertNotIn("88", workflow)
        self.assertEqual(preferred, ["458"])
        self.assertNotIn("210", workflow)

    def test_anima_v2_can_return_base_image_without_rtx(self) -> None:
        settings = PluginSettings.from_mapping(
            {"workflow_file": "workflow/anima_v2_api.json"}
        )
        builder = WorkflowBuilder(
            settings.resolve_workflow_path(self.plugin_dir),
            settings,
        )
        workflow, _, preferred = builder.build(
            GenerationOptions(prompt="1girl", seed=1, enable_upscale=False)
        )
        self.assertEqual(preferred, ["88"])
        self.assertNotIn("552", workflow)
        self.assertNotIn("458", workflow)

    def test_standalone_rtx_workflow_writes_uploaded_input(self) -> None:
        settings = PluginSettings.from_mapping({"rtx_scale": 3.0})
        builder = ImageWorkflowBuilder(
            settings.resolve_upscale_workflow_path(self.plugin_dir),
            settings,
        )
        workflow, preferred = builder.build(
            "astrbot_comfy_anima/input.webp",
            quality="HIGH",
        )
        self.assertEqual(
            workflow["1"]["inputs"]["image"],
            "astrbot_comfy_anima/input.webp",
        )
        self.assertEqual(workflow["552"]["inputs"]["resize_type.scale"], 3.0)
        self.assertEqual(workflow["552"]["inputs"]["quality"], "HIGH")
        self.assertEqual(preferred, ["458"])


class CommandParserTests(unittest.TestCase):
    """绘图指令参数解析测试。"""

    def test_parse_full_command(self) -> None:
        """解析提示词及所有常用覆盖参数。"""
        result = parse_generation_options(
            '1girl white hair --negative "bad hands, text" '
            "--seed 42 --size 832x1216 --steps 25 --cfg 4.5 --no-upscale"
        )
        self.assertEqual(result.prompt, "1girl white hair")
        self.assertEqual(result.negative_prompt, "bad hands, text")
        self.assertEqual(result.seed, 42)
        self.assertEqual((result.width, result.height), (832, 1216))
        self.assertEqual(result.steps, 25)
        self.assertEqual(result.cfg, 4.5)
        self.assertFalse(result.enable_upscale)

    def test_empty_prompt_is_rejected(self) -> None:
        """不允许只有选项而没有提示词。"""
        with self.assertRaises(ValueError):
            parse_generation_options("--seed 1")


if __name__ == "__main__":
    unittest.main()
