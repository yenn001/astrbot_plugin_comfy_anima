from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ..core.workflow import (
    ControlWorkflowBuilder,
    GenerationOptions,
    Img2ImgWorkflowBuilder,
    InpaintWorkflowBuilder,
    WorkflowBuilder,
    WorkflowError,
)
from ..models import PluginSettings
from ..services.config_profiles import ConfigProfileService, ENVIRONMENT_FIELDS
from ..services.anima_29b_contract import Anima29BContract, legacy_block_mapping


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "workflow"


class Anima29BProfileTests(unittest.TestCase):
    def test_documented_28_to_40_layer_mapping_is_complete(self) -> None:
        mapping = legacy_block_mapping()
        self.assertEqual(len(mapping), 28)
        self.assertEqual(sum(len(value) for value in mapping.values()), 40)
        self.assertEqual(mapping[0], (0,))
        self.assertEqual(mapping[1], (1, 2))
        self.assertEqual(mapping[27], (39,))
        self.assertEqual(Anima29BContract().verification_status, "needs_review")

    def test_29b_workflow_family_is_independent_and_declares_contract(self) -> None:
        for stem in ("base", "rtx", "iterative", "inpaint_crop", "lanpaint", "control", "img2img"):
            workflow = WORKFLOW_DIR / f"anima_29b_{stem}_api.json"
            manifest = WORKFLOW_DIR / "manifests" / workflow.name
            self.assertTrue(workflow.is_file(), workflow)
            self.assertTrue(manifest.is_file(), manifest)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["workflow_file"], workflow.name)
            self.assertTrue(payload["profile_id"].startswith("anima_29b_"))
            self.assertEqual(payload["model_contract"]["model_family"], "anima_29b_40l")
            if stem == "control":
                self.assertEqual(payload["model_contract"]["verification_status"], "unsupported")
                self.assertFalse(payload["model_contract"]["activation_required"])
            else:
                self.assertEqual(payload["model_contract"]["verification_status"], "verified")

        legacy = json.loads((WORKFLOW_DIR / "anima_base_api.json").read_text(encoding="utf-8"))
        upgraded = json.loads((WORKFLOW_DIR / "anima_29b_base_api.json").read_text(encoding="utf-8"))
        self.assertNotEqual(legacy["44"]["inputs"]["unet_name"], upgraded["44"]["inputs"]["unet_name"])
        self.assertEqual(legacy["45"]["inputs"]["clip_name"], upgraded["45"]["inputs"]["clip_name"])

    def test_builder_applies_29b_model_trio_without_mutating_template(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "workflow_file": "workflow/anima_29b_base_api.json",
                "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                "clip_model_name": "qwen_3_06b_base.safetensors",
                "vae_model_name": "qwen_image_vae.safetensors",
                "model_profile_id": "anima_29b",
                "model_family": "anima_29b_40l",
                "lora_patch_required": True,
                "lora_patch_node_type": "ComfyUI-Anima-2.9B",
                "lora_patch_contract_id": "anima29b-runtime-patch:unverified",
            }
        )
        path = ROOT / "workflow" / "anima_29b_base_api.json"
        builder = WorkflowBuilder(path, settings)
        workflow, _seed, _outputs = builder.build(GenerationOptions(prompt="1girl"))
        self.assertEqual(workflow["44"]["inputs"]["unet_name"], settings.unet_model_name)
        self.assertEqual(workflow["45"]["inputs"]["clip_name"], settings.clip_model_name)
        self.assertEqual(workflow["15"]["inputs"]["vae_name"], settings.vae_model_name)
        template = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(template["44"]["inputs"]["unet_name"], settings.unet_model_name)

    def test_all_profile_bound_builders_receive_the_29b_model_trio(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "workflow_file": "workflow/anima_29b_rtx_api.json",
                "base_workflow_file": "workflow/anima_29b_base_api.json",
                "rtx_generation_workflow_file": "workflow/anima_29b_rtx_api.json",
                "iterative_workflow_file": "workflow/anima_29b_iterative_api.json",
                "inpaint_crop_workflow_file": "workflow/anima_29b_inpaint_crop_api.json",
                "lanpaint_workflow_file": "workflow/anima_29b_lanpaint_api.json",
                "control_workflow_file": "workflow/anima_29b_control_api.json",
                "img2img_workflow_file": "workflow/anima_29b_img2img_api.json",
                "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                "clip_model_name": "qwen_3_06b_base.safetensors",
                "vae_model_name": "qwen_image_vae.safetensors",
                "model_profile_id": "anima_29b",
                "model_family": "anima_29b_40l",
                "lora_patch_required": True,
                "lora_patch_contract_id": "anima29b-runtime-patch:detect-unet-blocks-28-to-40@2de99f23e31ccf75d1a0f3d04c16ac5cfcd320e6",
            }
        )
        options = GenerationOptions(prompt="1girl", seed=17, pipeline="base")
        for stem in ("base", "rtx", "iterative"):
            builder = WorkflowBuilder(
                WORKFLOW_DIR / f"anima_29b_{stem}_api.json", settings
            )
            workflow, _seed, _outputs = builder.build(options)
            self.assertEqual(workflow["44"]["inputs"]["unet_name"], settings.unet_model_name)
            self.assertEqual(workflow["45"]["inputs"]["clip_name"], settings.clip_model_name)
            self.assertEqual(workflow["15"]["inputs"]["vae_name"], settings.vae_model_name)

        for stem in ("inpaint_crop", "lanpaint"):
            builder = InpaintWorkflowBuilder(
                WORKFLOW_DIR / f"anima_29b_{stem}_api.json", settings
            )
            workflow, _seed, _outputs = builder.build("source.png", "mask.png", options)
            self.assertEqual(workflow["44"]["inputs"]["unet_name"], settings.unet_model_name)
            self.assertEqual(workflow["45"]["inputs"]["clip_name"], settings.clip_model_name)
            self.assertEqual(workflow["15"]["inputs"]["vae_name"], settings.vae_model_name)

        with self.assertRaisesRegex(WorkflowError, "2.9B-compatible"):
            ControlWorkflowBuilder(WORKFLOW_DIR / "anima_29b_control_api.json", settings)

        img2img = Img2ImgWorkflowBuilder(WORKFLOW_DIR / "anima_29b_img2img_api.json", settings)
        workflow, _seed, _outputs = img2img.build("source.png", options)
        self.assertEqual(workflow["44"]["inputs"]["unet_name"], settings.unet_model_name)
        self.assertEqual(workflow["45"]["inputs"]["clip_name"], settings.clip_model_name)
        self.assertEqual(workflow["15"]["inputs"]["vae_name"], settings.vae_model_name)

    def test_unverified_29b_patch_blocks_legacy_lora_submission(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "workflow_file": "workflow/anima_29b_base_api.json",
                "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                "lora_patch_required": True,
                "lora_patch_contract_id": "anima29b-runtime-patch:unverified",
            }
        )
        builder = WorkflowBuilder(ROOT / "workflow" / "anima_29b_base_api.json", settings)
        with self.assertRaisesRegex(WorkflowError, "patch contract"):
            builder.build(
                GenerationOptions(
                    prompt="1girl",
                    dynamic_loras=(self._lora("characters/hero", 0.7),),
                )
            )

    def test_needs_review_manifest_blocks_normal_contract_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow_dir = Path(directory) / "workflow"
            manifest_dir = workflow_dir / "manifests"
            manifest_dir.mkdir(parents=True)
            source_workflow = ROOT / "workflow" / "anima_29b_base_api.json"
            source_manifest = ROOT / "workflow" / "manifests" / source_workflow.name
            target_workflow = workflow_dir / source_workflow.name
            target_manifest = manifest_dir / source_manifest.name
            shutil.copy2(source_workflow, target_workflow)
            payload = json.loads(source_manifest.read_text(encoding="utf-8"))
            payload["model_contract"]["verification_status"] = "needs_review"
            target_manifest.write_text(json.dumps(payload), encoding="utf-8")
            settings = PluginSettings.from_mapping(
                {
                    "workflow_file": "workflow/anima_29b_base_api.json",
                    "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                    "lora_patch_required": True,
                    "lora_patch_contract_id": "anima29b-runtime-patch:detect-unet-blocks-28-to-40@2de99f23e31ccf75d1a0f3d04c16ac5cfcd320e6",
                }
            )
            builder = WorkflowBuilder(target_workflow, settings)
            with self.assertRaisesRegex(WorkflowError, "not verified"):
                builder.build(
                    GenerationOptions(
                        prompt="1girl",
                        dynamic_loras=(self._lora("characters/hero", 0.7),),
                    )
                )

    @staticmethod
    def _lora(name: str, strength: float):
        from ..models import LoraSelection

        return LoraSelection(name=name, strength=strength)

    def test_profile_service_accepts_v4_fields_and_preserves_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigProfileService(Path(directory) / "profiles.json")
            config = {
                "comfyui_url": "http://127.0.0.1:8188",
                "model_profile_id": "anima_29b",
                "model_family": "anima_29b_40l",
                "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                "clip_model_name": "qwen_3_06b_base.safetensors",
                "vae_model_name": "qwen_image_vae.safetensors",
                "lora_patch_required": True,
                "lora_patch_node_type": "ComfyUI-Anima-2.9B",
                "lora_patch_contract_id": "anima29b-runtime-patch:unverified",
                "api_token": "secret",
            }
            profile = service.save_profile("Anima 2.9B", config)
            self.assertEqual(set(profile["settings"]), ENVIRONMENT_FIELDS)
            raw = (Path(directory) / "profiles.json").read_text(encoding="utf-8")
            self.assertNotIn("secret", raw)
            self.assertEqual(profile["settings"]["model_family"], "anima_29b_40l")


if __name__ == "__main__":
    unittest.main()
