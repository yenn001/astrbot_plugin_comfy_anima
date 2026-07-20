"""Regression tests for the prompt-sensitive Quick Crop inpaint workflow."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ..core.workflow import InpaintWorkflowBuilder
from ..models import GenerationOptions, PluginSettings


class QuickPromptWorkflowTests(unittest.TestCase):
    """Keep Quick mode cropped, mask-bound, and directly text-conditioned."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin_dir = Path(__file__).resolve().parents[1]
        cls.workflow_path = cls.plugin_dir / "workflow" / "anima_inpaint_crop_api.json"
        cls.manifest_path = (
            cls.plugin_dir
            / "workflow"
            / "manifests"
            / "anima_inpaint_crop_api.json"
        )
        cls.workflow = json.loads(cls.workflow_path.read_text(encoding="utf-8"))
        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def test_profile_identity_and_output_remain_backward_compatible(self) -> None:
        self.assertEqual(self.manifest["profile_id"], "anima_inpaint_crop")
        self.assertEqual(
            self.manifest["workflow_file"], "anima_inpaint_crop_api.json"
        )
        self.assertEqual(self.manifest["default_output_variant"], "quick")
        self.assertEqual(
            self.manifest["output_variants"]["quick"]["preferred_node_ids"],
            ["26"],
        )

    def test_crop_image_and_mask_reach_lanpaint_fast_sampler(self) -> None:
        workflow = self.workflow

        self.assertEqual(workflow["21"]["class_type"], "InpaintCropImproved")
        self.assertEqual(workflow["21"]["inputs"]["image"], ["1", 0])
        self.assertEqual(workflow["21"]["inputs"]["mask"], ["3", 0])

        self.assertEqual(workflow["20"]["class_type"], "VAEEncode")
        self.assertEqual(workflow["20"]["inputs"]["pixels"], ["21", 1])
        self.assertEqual(workflow["22"]["class_type"], "SetLatentNoiseMask")
        self.assertEqual(workflow["22"]["inputs"]["samples"], ["20", 0])
        self.assertEqual(workflow["22"]["inputs"]["mask"], ["21", 2])

        sampler = workflow["23"]
        self.assertEqual(sampler["class_type"], "LanPaint_KSampler")
        self.assertEqual(sampler["inputs"]["latent_image"], ["22", 0])
        self.assertEqual(sampler["inputs"]["model"], ["462", 0])
        self.assertEqual(sampler["inputs"]["steps"], 12)
        self.assertEqual(sampler["inputs"]["LanPaint_NumSteps"], 2)
        self.assertEqual(sampler["inputs"]["denoise"], 1.0)

        self.assertEqual(workflow["25"]["class_type"], "InpaintStitchImproved")
        self.assertEqual(workflow["25"]["inputs"]["stitcher"], ["21", 0])
        self.assertEqual(workflow["25"]["inputs"]["inpainted_image"], ["24", 0])
        self.assertEqual(workflow["26"]["inputs"]["images"], ["25", 0])

    def test_positive_and_negative_prompts_bind_directly_to_sampler(self) -> None:
        bindings = self.manifest["bindings"]
        self.assertEqual(
            bindings["positive_prompt"], {"node_id": "11", "input": "text"}
        )
        self.assertEqual(
            bindings["negative_prompt"], {"node_id": "12", "input": "text"}
        )
        self.assertEqual(self.workflow["23"]["inputs"]["positive"], ["11", 0])
        self.assertEqual(self.workflow["23"]["inputs"]["negative"], ["12", 0])
        self.assertFalse(
            any(
                node.get("class_type") == "InpaintModelConditioning"
                for node in self.workflow.values()
            )
        )

    def test_builder_writes_prompt_and_runtime_sampler_overrides(self) -> None:
        settings = PluginSettings.from_mapping(
            {"inpaint_crop_workflow_file": "workflow/anima_inpaint_crop_api.json"}
        )
        builder = InpaintWorkflowBuilder(self.workflow_path, settings)
        workflow, seed, preferred = builder.build(
            "uploaded-source.png",
            "uploaded-mask.png",
            GenerationOptions(
                prompt="white evening dress, gold embroidery",
                negative_prompt="swimsuit",
                seed=314159,
                steps=10,
                cfg=4.25,
                denoise=0.9,
            ),
        )

        self.assertEqual(builder.profile.profile_id, "anima_inpaint_crop")
        self.assertEqual(seed, 314159)
        self.assertEqual(preferred, ["26"])
        self.assertEqual(workflow["1"]["inputs"]["image"], "uploaded-source.png")
        self.assertEqual(workflow["2"]["inputs"]["image"], "uploaded-mask.png")
        self.assertEqual(
            workflow["11"]["inputs"]["text"],
            "white evening dress, gold embroidery",
        )
        self.assertIn("swimsuit", workflow["12"]["inputs"]["text"])
        self.assertEqual(workflow["23"]["inputs"]["positive"], ["11", 0])
        self.assertEqual(workflow["23"]["inputs"]["steps"], 10)
        self.assertEqual(workflow["23"]["inputs"]["cfg"], 4.25)
        self.assertEqual(workflow["23"]["inputs"]["denoise"], 0.9)


if __name__ == "__main__":
    unittest.main()
