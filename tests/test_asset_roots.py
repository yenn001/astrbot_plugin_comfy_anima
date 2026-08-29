from __future__ import annotations

import unittest

from ..models import PluginSettings
from ..services.config_profiles import ConfigProfileValidationError, validate_environment_settings
from ..services.lora_catalog import LoraCatalogService, LoraRecord


class AssetRootTests(unittest.TestCase):
    def test_29b_asset_names_are_scoped(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
                "unet_model_root": "2.9Bunet",
                "clip_model_root": "2.9Bclip",
                "vae_model_root": "2.9Bvae",
            }
        )
        self.assertEqual(settings.resolve_asset_name("unet"), "2.9Bunet/Anima-2.9B-preview-v1.safetensors")

    def test_asset_roots_reject_escape(self) -> None:
        base = {
            "comfyui_url": "http://127.0.0.1:8188",
            "workflow_file": "workflow/anima_api.json",
            "reverse_workflow_file": "workflow/anima_reverse_tagger_api.json",
            "workflow_dir": "workflow",
            "unet_catalog_url": "",
            "unet_loader_node_id": "429",
            "unet_model_input_name": "unet_name",
            "unet_model_name": "model.safetensors",
            "lora_catalog_url": "",
            "lora_manager_url": "",
            "lora_loader_node_id": "462",
            "prompt_node_id": "210",
            "negative_node_id": "13",
            "primary_seed_node_id": "8",
            "secondary_seed_node_id": "262",
            "resolution_node_id": "437",
            "sampler_node_ids": ["8"],
            "output_node_ids": ["285", "20"],
            "upscale_output_node_id": "285",
            "default_width": 832,
            "default_height": 1216,
        }
        for value in ("../escape", "/absolute", "C:/absolute", "a//b"):
            with self.subTest(value=value), self.assertRaises(ConfigProfileValidationError):
                validate_environment_settings({**base, "lora_model_root": value}, require_all=False)

    def test_lora_catalog_filter_is_branch_local(self) -> None:
        settings = PluginSettings.from_mapping({"lora_model_root": "2.9BLora"})
        service = LoraCatalogService(settings)
        records = service._filter_model_root(
            (
                LoraRecord(name="legacy/style.safetensors", file_path="models/loras/legacy/style.safetensors"),
                LoraRecord(name="characters/denia.safetensors", file_path="models/loras/2.9BLora/characters/denia.safetensors"),
            )
        )
        self.assertEqual([record.name for record in records], ["characters/denia.safetensors"])


if __name__ == "__main__":
    unittest.main()
