"""Regression tests for the dedicated Anima img2img workflow."""

import json
import unittest
from pathlib import Path

from ..core.workflow import (
    ControlWorkflowBuilder,
    Img2ImgWorkflowBuilder,
    WorkflowError,
)
from ..core.workflow_registry import WorkflowRegistry, WorkflowRegistryError
from ..models import GenerationOptions, LoraSelection, PluginSettings


class Img2ImgWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin_dir = Path(__file__).resolve().parents[1]
        cls.workflow_path = cls.plugin_dir / "workflow" / "anima_img2img_api.json"
        cls.manifest_path = (
            cls.plugin_dir / "workflow" / "manifests" / "anima_img2img_api.json"
        )
        cls.settings = PluginSettings.from_mapping(
            {
                "default_generation_pipeline": "base",
                "unet_model_name": "models/anima-selected.safetensors",
                "rtx_scale": 1.75,
                "rtx_quality": "HIGH",
                "iterative_scale": 1.4,
                "iterative_steps": 4,
                "iterative_denoise": 0.3,
            }
        )
        cls.builder = Img2ImgWorkflowBuilder(cls.workflow_path, cls.settings)

    def test_manifest_and_fixed_pixel_latent_topology(self) -> None:
        workflow = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["profile_id"], "anima_img2img")
        self.assertEqual(manifest["task_type"], "img2img")
        self.assertEqual(
            manifest["bindings"]["positive_prompt"],
            {"node_id": "11", "input": "text"},
        )
        self.assertEqual(
            manifest["bindings"]["negative_prompt"],
            {"node_id": "12", "input": "text"},
        )
        self.assertEqual(workflow["500"]["class_type"], "LoadImage")
        self.assertEqual(workflow["501"]["class_type"], "ImageScale")
        self.assertEqual(workflow["502"]["class_type"], "VAEEncode")
        self.assertEqual(workflow["501"]["inputs"]["image"], ["500", 0])
        self.assertEqual(workflow["502"]["inputs"]["pixels"], ["501", 0])
        self.assertEqual(workflow["502"]["inputs"]["vae"], ["15", 0])
        self.assertEqual(workflow["19"]["inputs"]["latent_image"], ["502", 0])
        self.assertEqual(workflow["19"]["inputs"]["positive"], ["11", 0])
        self.assertEqual(workflow["19"]["inputs"]["negative"], ["12", 0])
        self.assertFalse(
            any(
                node.get("class_type") == "EmptyLatentImage"
                for node in workflow.values()
            )
        )

    def test_builder_writes_all_dynamic_generation_inputs(self) -> None:
        options = GenerationOptions(
            prompt="1girl, red dress, standing in rain",
            negative_prompt="blue dress, school uniform",
            seed=987654,
            width=512,
            height=640,
            steps=16,
            cfg=4.25,
            denoise=0.42,
            pipeline="base",
            dynamic_loras=(LoraSelection("characters/example", 0.73),),
            lora_injection_mode="replace",
        )

        workflow, seed, preferred = self.builder.build(
            "astrbot/input/source.png", options
        )

        self.assertEqual(seed, 987654)
        self.assertEqual(preferred, ["88"])
        self.assertEqual(workflow["500"]["inputs"]["image"], "astrbot/input/source.png")
        self.assertEqual(workflow["501"]["inputs"]["width"], 512)
        self.assertEqual(workflow["501"]["inputs"]["height"], 640)
        self.assertEqual(workflow["11"]["inputs"]["text"], options.prompt)
        self.assertIn(options.negative_prompt, workflow["12"]["inputs"]["text"])
        self.assertEqual(workflow["44"]["inputs"]["unet_name"], self.settings.unet_model_name)
        self.assertEqual(workflow["19"]["inputs"]["seed"], 987654)
        self.assertEqual(workflow["19"]["inputs"]["steps"], 16)
        self.assertEqual(workflow["19"]["inputs"]["cfg"], 4.25)
        self.assertEqual(workflow["19"]["inputs"]["denoise"], 0.42)
        self.assertEqual(workflow["19"]["inputs"]["latent_image"], ["502", 0])
        self.assertEqual(
            workflow["462"]["inputs"]["loras"]["__value__"][0]["name"],
            "characters/example",
        )
        self.assertNotIn("458", workflow)
        self.assertNotIn("552", workflow)
        self.assertNotIn("103", workflow)

    def test_rtx_pipeline_has_only_rtx_final_output(self) -> None:
        workflow, seed, preferred = self.builder.build_img2img(
            "source.png",
            GenerationOptions(prompt="portrait", seed=11, pipeline="rtx"),
        )

        self.assertEqual(seed, 11)
        self.assertEqual(preferred, ["458"])
        self.assertIn("458", workflow)
        self.assertIn("552", workflow)
        self.assertNotIn("88", workflow)
        self.assertNotIn("103", workflow)
        self.assertEqual(workflow["552"]["inputs"]["images"], ["8", 0])
        self.assertEqual(
            workflow["552"]["inputs"]["resize_type.scale"],
            self.settings.rtx_scale,
        )
        self.assertEqual(
            workflow["552"]["inputs"]["quality"], self.settings.rtx_quality
        )

    def test_iterative_pipeline_keeps_prompt_model_and_seed_connections(self) -> None:
        workflow, seed, preferred = self.builder.build(
            "source.png",
            GenerationOptions(
                prompt="portrait, evening dress",
                seed=22,
                steps=14,
                cfg=4.0,
                denoise=0.38,
                pipeline="iterative",
            ),
        )

        self.assertEqual(seed, 22)
        self.assertEqual(preferred, ["103"])
        self.assertNotIn("88", workflow)
        self.assertNotIn("458", workflow)
        self.assertNotIn("552", workflow)
        self.assertEqual(workflow["100"]["inputs"]["model"], ["462", 0])
        self.assertEqual(workflow["100"]["inputs"]["positive"], ["11", 0])
        self.assertEqual(workflow["100"]["inputs"]["negative"], ["12", 0])
        self.assertEqual(workflow["100"]["inputs"]["seed"], 22)
        self.assertEqual(workflow["100"]["inputs"]["steps"], 14)
        self.assertEqual(workflow["100"]["inputs"]["cfg"], 4.0)
        self.assertEqual(workflow["19"]["inputs"]["denoise"], 0.38)
        self.assertEqual(
            workflow["100"]["inputs"]["denoise"],
            self.settings.iterative_denoise,
        )
        self.assertEqual(
            workflow["101"]["inputs"]["upscale_factor"],
            self.settings.iterative_scale,
        )
        self.assertEqual(
            workflow["101"]["inputs"]["steps"], self.settings.iterative_steps
        )

    def test_source_image_is_required_and_template_is_immutable(self) -> None:
        original = self.builder._template["500"]["inputs"]["image"]
        with self.assertRaises(WorkflowError):
            self.builder.build("  ", GenerationOptions(prompt="portrait"))

        workflow, _, _ = self.builder.build(
            "request.png", GenerationOptions(prompt="portrait", pipeline="base")
        )
        self.assertEqual(workflow["500"]["inputs"]["image"], "request.png")
        self.assertEqual(self.builder._template["500"]["inputs"]["image"], original)

    def test_unknown_pipeline_is_rejected(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "does not support pipeline"):
            self.builder.build(
                "source.png",
                GenerationOptions(prompt="portrait", pipeline="unknown"),
            )

    def test_registry_describes_img2img_but_cannot_select_it_as_default(self) -> None:
        registry = WorkflowRegistry(self.workflow_path.parent, self.settings)
        descriptor = next(
            item
            for item in registry.describe()
            if item.profile_id == "anima_img2img"
        )

        self.assertEqual(descriptor.task_type, "img2img")
        self.assertFalse(descriptor.selectable)
        self.assertIn("cannot be selected", descriptor.error)
        with self.assertRaisesRegex(WorkflowRegistryError, "cannot be selected"):
            registry.select(descriptor.entry.index)


class ControlFidelityPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        plugin_dir = Path(__file__).resolve().parents[1]
        cls.settings = PluginSettings.from_mapping(
            {"default_generation_pipeline": "base"}
        )
        cls.builder = ControlWorkflowBuilder(
            plugin_dir / "workflow" / "anima_control_api.json",
            cls.settings,
        )

    def _build(self, modes: tuple[str, ...]) -> dict:
        workflow, _, preferred = self.builder.build_control(
            "source.png",
            GenerationOptions(
                prompt="portrait",
                seed=1,
                width=512,
                height=512,
                pipeline="base",
                control_modes=modes,
            ),
        )
        self.assertEqual(preferred, ["88"])
        return workflow

    def test_one_and_two_controls_keep_full_declared_strength(self) -> None:
        single = self._build(("pose",))
        dual = self._build(("pose", "depth"))

        self.assertEqual(single["511"]["inputs"]["strength"], 0.9)
        self.assertEqual(dual["511"]["inputs"]["strength"], 0.9)
        self.assertEqual(dual["521"]["inputs"]["strength"], 0.82)
        self.assertEqual(dual["511"]["inputs"]["end_percent"], 0.9)
        self.assertEqual(dual["521"]["inputs"]["end_percent"], 0.85)

    def test_three_and_four_controls_use_conservative_fidelity_decay(self) -> None:
        triple = self._build(("pose", "depth", "lineart"))
        all_modes = self._build(("pose", "depth", "lineart", "reference"))

        self.assertEqual(triple["511"]["inputs"]["strength"], 0.765)
        self.assertEqual(triple["521"]["inputs"]["strength"], 0.697)
        self.assertEqual(triple["531"]["inputs"]["strength"], 0.782)
        self.assertEqual(all_modes["511"]["inputs"]["strength"], 0.675)
        self.assertEqual(all_modes["521"]["inputs"]["strength"], 0.615)
        self.assertEqual(all_modes["531"]["inputs"]["strength"], 0.69)
        self.assertEqual(all_modes["540"]["inputs"]["strength"], 0.54)

    def test_reference_uses_stronger_longer_manifest_guidance(self) -> None:
        workflow = self._build(("reference",))

        self.assertEqual(workflow["540"]["inputs"]["strength"], 0.72)
        self.assertEqual(workflow["540"]["inputs"]["end_percent"], 0.9)


if __name__ == "__main__":
    unittest.main()
