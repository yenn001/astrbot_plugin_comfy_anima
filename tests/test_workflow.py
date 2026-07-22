"""
AstrBot Comfy Anima 插件 v1.2.0

功能描述：
- 测试工作流参数替换和指令解析

作者: Yen
版本: 1.2.0
日期: 2026-07-14
"""

import json
import unittest
from pathlib import Path

from ..core.workflow import (
    ControlWorkflowBuilder,
    ImageWorkflowBuilder,
    InpaintWorkflowBuilder,
    WorkflowBuilder,
    parse_generation_options,
)
from ..models import GenerationOptions, LoraSelection, PluginSettings


class WorkflowTemplateTopologyTests(unittest.TestCase):
    """Guard the model, CLIP, LoRA, prompt, and RTX edges in shipped workflows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_dir = Path(__file__).resolve().parents[1] / "workflow"

    def _load(self, filename: str) -> dict:
        with (self.workflow_dir / filename).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_legacy_anima_routes_every_text_encoder_through_lora_clip(self) -> None:
        workflow = self._load("anima_api.json")
        text_encoders = {
            node_id: node
            for node_id, node in workflow.items()
            if node.get("class_type") == "CLIPTextEncode"
        }

        self.assertEqual(
            set(text_encoders),
            {"6", "7", "336", "339", "341", "343"},
        )
        for node_id, node in text_encoders.items():
            with self.subTest(node_id=node_id):
                self.assertEqual(node["inputs"]["clip"], ["462", 1])

        self.assertEqual(workflow["462"]["inputs"]["model"], ["429", 0])
        self.assertEqual(workflow["462"]["inputs"]["clip"], ["4", 0])
        self.assertEqual(workflow["8"]["inputs"]["model"], ["462", 0])

    def test_legacy_trigger_toggle_is_inert_and_has_no_stale_fallback(self) -> None:
        workflow = self._load("anima_api.json")
        inputs = workflow["431"]["inputs"]

        self.assertFalse(inputs["default_active"])
        self.assertEqual(inputs["toggle_trigger_words"]["__value__"], [])
        self.assertEqual(inputs["orinalMessage"], "")
        self.assertEqual(inputs["trigger_words"], "")
        self.assertNotEqual(inputs["trigger_words"], ["462", 2])

    def test_anima_v2_lora_model_clip_and_rtx_edges_are_complete(self) -> None:
        workflow = self._load("anima_v2_api.json")

        self.assertEqual(workflow["462"]["inputs"]["model"], ["44", 0])
        self.assertEqual(workflow["462"]["inputs"]["clip"], ["45", 0])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["462", 0])
        self.assertEqual(workflow["11"]["inputs"]["clip"], ["462", 1])
        self.assertEqual(workflow["12"]["inputs"]["clip"], ["462", 1])
        self.assertEqual(workflow["8"]["inputs"]["samples"], ["19", 0])
        self.assertEqual(workflow["552"]["inputs"]["images"], ["8", 0])
        self.assertEqual(workflow["458"]["inputs"]["images"], ["552", 0])

        for node in workflow.values():
            self.assertNotIn(["462", 2], node.get("inputs", {}).values())

    def test_standalone_rtx_workflow_remains_image_only(self) -> None:
        workflow = self._load("rtx_upscale_api.json")

        self.assertEqual(set(workflow), {"1", "552", "458"})
        self.assertEqual(workflow["1"]["class_type"], "LoadImage")
        self.assertEqual(
            workflow["552"]["class_type"],
            "RTXVideoSuperResolution",
        )
        self.assertEqual(workflow["552"]["inputs"]["images"], ["1", 0])
        self.assertEqual(workflow["458"]["class_type"], "SaveImage")
        self.assertEqual(workflow["458"]["inputs"]["images"], ["552", 0])
        self.assertFalse(
            any("lora" in node.get("class_type", "").lower() for node in workflow.values())
        )
        self.assertFalse(
            any(
                key in {"model", "clip", "loras"}
                for node in workflow.values()
                for key in node.get("inputs", {})
            )
        )


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

    def test_explicit_replace_clears_template_with_empty_dynamic_stack(self) -> None:
        """纯 Tags 换角即使没有动态 LoRA，也必须清空模板静态栈。"""

        template_inputs = self.builder._template["462"]["inputs"]
        self.assertTrue(template_inputs["loras"]["__value__"])
        self.assertTrue(template_inputs["text"])

        workflow, _, _ = self.builder.build(
            GenerationOptions(
                prompt="1girl, rice_shower_(umamusume)",
                seed=1,
                dynamic_loras=(),
                lora_injection_mode="replace",
                character_swap_forbid_character_loras=True,
            )
        )

        inputs = workflow["462"]["inputs"]
        self.assertEqual(inputs["loras"]["__value__"], [])
        self.assertEqual(inputs["text"], "")
        self.assertTrue(template_inputs["loras"]["__value__"])

    def test_empty_dynamic_stack_preserves_template_without_explicit_replace(self) -> None:
        """普通生图的历史模板行为不因安全清栈支持而改变。"""

        template_inputs = self.builder._template["462"]["inputs"]
        workflow, _, _ = self.builder.build(
            GenerationOptions(prompt="1girl, portrait", seed=1)
        )
        inputs = workflow["462"]["inputs"]

        self.assertEqual(inputs["loras"], template_inputs["loras"])
        self.assertEqual(inputs["text"], template_inputs["text"])

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

    def test_anima_v2_enables_rtx_by_default(self) -> None:
        settings = PluginSettings.from_mapping(
            {"workflow_file": "workflow/anima_v2_api.json"}
        )
        builder = WorkflowBuilder(
            settings.resolve_workflow_path(self.plugin_dir),
            settings,
        )

        workflow, _, preferred = builder.build(
            GenerationOptions(prompt="1girl", seed=1, width=512, height=512)
        )

        self.assertEqual(preferred, ["458"])
        self.assertNotIn("88", workflow)
        self.assertEqual(workflow["28"]["inputs"]["width"], 512)
        self.assertEqual(workflow["28"]["inputs"]["height"], 512)
        self.assertEqual(workflow["552"]["inputs"]["images"], ["8", 0])
        self.assertEqual(workflow["458"]["inputs"]["images"], ["552", 0])

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

    def test_pipeline_inpaint_mode_and_denoise_are_parsed(self) -> None:
        result = parse_generation_options(
            "red evening dress --pipeline iterative --mode lanpaint --denoise 0.42"
        )
        self.assertEqual(result.pipeline, "iterative")
        self.assertEqual(result.inpaint_mode, "lanpaint")
        self.assertEqual(result.denoise, 0.42)

    def test_semantic_redraw_mode_uses_separate_parser_context(self) -> None:
        result = parse_generation_options(
            "把衣服换成红裙 --mode preserve --pipeline base",
            mode_context="semantic_redraw",
        )
        self.assertEqual(result.semantic_redraw_mode, "preserve")
        self.assertEqual(result.inpaint_mode, "")
        self.assertEqual(result.pipeline, "base")
        with self.assertRaisesRegex(ValueError, "preserve"):
            parse_generation_options(
                "重新画一张 --mode quick",
                mode_context="semantic_redraw",
            )


class DedicatedPipelineWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin_dir = Path(__file__).resolve().parents[1]

    def test_base_rtx_and_iterative_pipelines_have_separate_outputs(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "iterative_scale": 1.6,
                "iterative_steps": 4,
                "iterative_denoise": 0.3,
            }
        )
        base = WorkflowBuilder(
            settings.resolve_pipeline_workflow_path(self.plugin_dir, "base"),
            settings,
        )
        base_workflow, _, base_nodes = base.build(
            GenerationOptions(prompt="1girl", width=512, height=512)
        )
        self.assertEqual(base_nodes, ["88"])
        self.assertNotIn("552", base_workflow)

        rtx = WorkflowBuilder(
            settings.resolve_pipeline_workflow_path(self.plugin_dir, "rtx"),
            settings,
        )
        rtx_workflow, _, rtx_nodes = rtx.build(
            GenerationOptions(prompt="1girl", width=512, height=512)
        )
        self.assertEqual(rtx_nodes, ["458"])
        self.assertEqual(rtx_workflow["552"]["inputs"]["images"], ["8", 0])

        iterative = WorkflowBuilder(
            settings.resolve_pipeline_workflow_path(self.plugin_dir, "iterative"),
            settings,
        )
        iterative_workflow, _, iterative_nodes = iterative.build(
            GenerationOptions(prompt="1girl", denoise=0.48)
        )
        self.assertEqual(iterative_nodes, ["103"])
        self.assertEqual(iterative_workflow["101"]["inputs"]["upscale_factor"], 1.6)
        self.assertEqual(iterative_workflow["101"]["inputs"]["steps"], 4)
        self.assertEqual(iterative_workflow["100"]["inputs"]["denoise"], 0.48)
        self.assertEqual(iterative_workflow["19"]["inputs"]["denoise"], 1.0)

    def test_quick_and_lanpaint_receive_source_mask_prompt_and_lora(self) -> None:
        settings = PluginSettings.from_mapping({})
        for mode, expected_node in (("quick", "26"), ("lanpaint", "25")):
            builder = InpaintWorkflowBuilder(
                settings.resolve_inpaint_workflow_path(self.plugin_dir, mode),
                settings,
            )
            workflow, seed, preferred = builder.build(
                "incoming/source.png",
                "incoming/mask.png",
                GenerationOptions(
                    prompt="red evening dress",
                    negative_prompt="school uniform",
                    seed=77,
                    denoise=0.6,
                    dynamic_loras=(LoraSelection("characters/hero", 0.7),),
                    lora_injection_mode="replace",
                ),
            )
            self.assertEqual(seed, 77)
            self.assertEqual(preferred, [expected_node])
            self.assertEqual(workflow["1"]["inputs"]["image"], "incoming/source.png")
            self.assertEqual(workflow["2"]["inputs"]["image"], "incoming/mask.png")
            self.assertEqual(workflow["11"]["inputs"]["text"], "red evening dress")
            self.assertIn("school uniform", workflow["12"]["inputs"]["text"])
            self.assertEqual(
                workflow["462"]["inputs"]["loras"]["__value__"][0]["name"],
                "characters/hero",
            )

    def test_control_builder_chains_selected_modes_and_prunes_the_rest(self) -> None:
        settings = PluginSettings.from_mapping({"default_generation_pipeline": "rtx"})
        builder = ControlWorkflowBuilder(
            self.plugin_dir / "workflow" / "anima_control_api.json",
            settings,
        )
        workflow, seed, preferred = builder.build_control(
            "incoming/control.png",
            GenerationOptions(
                prompt="1girl, running",
                seed=77,
                width=512,
                height=512,
                pipeline="rtx",
                control_modes=("pose", "depth"),
                dynamic_loras=(LoraSelection("characters/hero", 0.7),),
                lora_injection_mode="replace",
            ),
        )
        self.assertEqual(seed, 77)
        self.assertEqual(preferred, ["458"])
        self.assertEqual(workflow["500"]["inputs"]["image"], "incoming/control.png")
        self.assertEqual(workflow["501"]["inputs"]["width"], 512)
        self.assertEqual(workflow["501"]["inputs"]["height"], 512)
        self.assertEqual(workflow["511"]["inputs"]["model"], ["462", 0])
        self.assertEqual(workflow["521"]["inputs"]["model"], ["511", 0])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["521", 0])
        self.assertNotIn("530", workflow)
        self.assertNotIn("531", workflow)
        self.assertNotIn("540", workflow)
        self.assertNotIn("88", workflow)
        self.assertNotIn("100", workflow)
        self.assertEqual(
            workflow["462"]["inputs"]["loras"]["__value__"][0]["name"],
            "characters/hero",
        )

    def test_control_builder_supports_reference_and_iterative_output(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "iterative_scale": 1.6,
                "iterative_steps": 4,
                "iterative_denoise": 0.31,
            }
        )
        builder = ControlWorkflowBuilder(
            self.plugin_dir / "workflow" / "anima_control_api.json",
            settings,
        )
        workflow, _, preferred = builder.build_control(
            "incoming/reference.png",
            GenerationOptions(
                prompt="1girl",
                pipeline="iterative",
                control_modes=("reference",),
            ),
        )
        self.assertEqual(preferred, ["103"])
        self.assertEqual(workflow["540"]["inputs"]["image"], ["501", 0])
        self.assertEqual(workflow["19"]["inputs"]["model"], ["540", 0])
        self.assertEqual(workflow["100"]["inputs"]["model"], ["540", 0])
        self.assertEqual(workflow["101"]["inputs"]["upscale_factor"], 1.6)
        self.assertEqual(workflow["101"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["100"]["inputs"]["denoise"], 0.31)
        self.assertNotIn("510", workflow)
        self.assertNotIn("520", workflow)
        self.assertNotIn("530", workflow)

    def test_generation_short_aliases_and_control_modes_are_parsed(self) -> None:
        result = parse_generation_options(
            "1girl --p r --m p d --sz 512x512 --st 8 --c 5 --pr 风格2",
            mode_context="generation",
        )
        self.assertEqual(result.pipeline, "rtx")
        self.assertEqual(result.control_modes, ("pose", "depth"))
        self.assertEqual((result.width, result.height), (512, 512))
        self.assertEqual(result.steps, 8)
        self.assertEqual(result.cfg, 5.0)
        self.assertEqual(result.lora_preset, "风格2")

    def test_generation_llm_and_raw_switches_are_explicit(self) -> None:
        optimized = parse_generation_options(
            "蓝发少女在海边看烟花 --llm",
            mode_context="generation",
        )
        short_optimized = parse_generation_options(
            "蓝发少女在海边看烟花 --l",
            mode_context="generation",
        )
        raw = parse_generation_options(
            "1girl, blue hair --raw",
            mode_context="generation",
        )

        self.assertTrue(optimized.use_prompt_llm)
        self.assertTrue(short_optimized.use_prompt_llm)
        self.assertFalse(raw.use_prompt_llm)


if __name__ == "__main__":
    unittest.main()
