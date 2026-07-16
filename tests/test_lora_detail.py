"""Tests for the safe LoRA v2 detail aggregation layer."""

from datetime import datetime, timedelta, timezone
import json
import unittest

from ..services.lora_catalog import LoraRecord
from ..services.lora_detail import LoraDetailAggregator


class LoraDetailAggregatorTests(unittest.TestCase):
    @staticmethod
    def _record(**overrides) -> LoraRecord:
        values = {
            "name": "characters/denia.safetensors",
            "trigger_words": ("denia",),
            "description": "legacy description",
            "model_name": "Denia fallback",
            "base_model": "Anima",
            "folder": "characters",
            "file_path": "E:/ComfyUI/models/loras/characters/denia.safetensors",
            "preview_url": "https://example.test/preview.jpg?token=secret",
            "tags": ("character",),
            "favorite": True,
            "sha256": "a" * 64,
            "source": "lora-manager+comfyui",
            "category": "character",
            "aliases": ("达妮娅",),
            "character_name": "Denia",
            "source_work": "Wuthering Waves",
            "from_civitai": True,
        }
        values.update(overrides)
        return LoraRecord(**values)

    @staticmethod
    def _list_item() -> dict:
        return {
            "file_name": "denia.safetensors",
            "file_path": "/mnt/models/loras/characters/denia.safetensors",
            "folder": "characters",
            "model_name": "Denia Character",
            "base_model": "Anima Base 1.0",
            "sha256": "a" * 64,
            "file_size": 123456,
            "modified": "2026-07-15T10:00:00Z",
            "tags": ["game character"],
            "auto_tags": ["female"],
            "favorite": True,
            "exclude": False,
            "usage_count": 12,
            "usage_tips": '{"strength_min":0.55,"strength_max":0.8}',
            "sub_type": "lora",
            "update_available": True,
            "version_count": 3,
            "license_flags": 7,
            "from_civitai": True,
            "preview_url": "https://cdn.test/preview.webp?token=download-secret",
            "civitai": {
                "id": 456,
                "modelId": 123,
                "name": "v2.0",
                "trainedWords": ["denia_wuwa"],
            },
        }

    @staticmethod
    def _metadata() -> dict:
        return {
            "id": 456,
            "modelId": 123,
            "name": "v2.0",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-02-01T00:00:00Z",
            "publishedAt": "2026-01-03T00:00:00Z",
            "trainedWords": ["denia_wuwa", "black denia"],
            "baseModel": "Anima Base 1.0",
            "description": "<p>Version training notes and settings.</p>",
            "creator": {
                "username": "artist-user",
                "name": "Artist User",
                "url": "https://civitai.com/user/artist-user?token=private",
            },
            "model": {
                "name": "Denia from Wuthering Waves",
                "type": "LORA",
                "description": "<p>Model-level character identity.</p>",
                "tags": ["Wuthering Waves", "Denia"],
                "allowNoCredit": False,
                "allowCommercialUse": ["Image"],
                "allowDerivatives": True,
                "allowDifferentLicense": False,
            },
            "images": [
                {
                    "url": "https://image.test/a.webp?token=private",
                    "width": 832,
                    "height": 1216,
                    "nsfwLevel": 1,
                    "meta": {
                        "prompt": "denia_wuwa, cinematic portrait",
                        "negativePrompt": "low quality",
                        "seed": 42,
                        "steps": 30,
                        "sampler": "Euler a",
                        "cfgScale": 6.5,
                        "workflow": {"secret": "must not pass"},
                        "downloadUrl": "https://bad.test/file?token=secret",
                    },
                }
            ],
            "customImages": [
                {
                    "url": "file:///mnt/private/example.png",
                    "width": 1024,
                    "height": 1024,
                    "metadata": {"clip_skip": 2, "api_key": "secret"},
                }
            ],
        }

    def test_aggregates_rich_sources_without_losing_dual_descriptions(self) -> None:
        detail = LoraDetailAggregator.aggregate(
            self._record(),
            manager_list=self._list_item(),
            manager_metadata={"success": True, "metadata": self._metadata()},
            model_description={
                "success": True,
                "description": "Local model description supplement.",
            },
            usage_tips={
                "success": True,
                "usage_tips": '{"strength":0.7,"clipStrength":0.8}',
            },
            checked_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        )

        self.assertEqual(detail.asset_id, f"sha256:{'a' * 64}")
        self.assertEqual(detail.name, "characters/denia.safetensors")
        self.assertIn("Local model description supplement", detail.model_description)
        self.assertIn("Model-level character identity", detail.model_description)
        self.assertEqual(detail.version_description, "Version training notes and settings.")
        self.assertEqual(detail.model_name, "Denia from Wuthering Waves")
        self.assertEqual(detail.version_name, "v2.0")
        self.assertEqual(
            detail.trigger_words, ("denia", "denia_wuwa", "black denia")
        )
        self.assertEqual(
            detail.tags,
            ("character", "game character", "female", "Wuthering Waves", "Denia"),
        )
        self.assertEqual(detail.creator.username, "artist-user")
        self.assertEqual(detail.creator.profile_url, "https://civitai.com/user/artist-user")
        self.assertFalse(detail.license.allow_no_credit)
        self.assertEqual(detail.license.allow_commercial_use, ("Image",))
        self.assertEqual(detail.usage_tips_dict(), {"strength": 0.7, "clip_strength": 0.8})
        self.assertEqual(detail.version_status.model_id, "123")
        self.assertTrue(detail.version_status.update_available)
        self.assertEqual(detail.file_status.file_size, 123456)
        self.assertEqual(detail.metadata_health.status, "complete")

        first_image = detail.images[0]
        self.assertEqual(first_image.url, "https://image.test/a.webp")
        self.assertEqual(
            first_image.parameter_dict(),
            {
                "positive_prompt": "denia_wuwa, cinematic portrait",
                "negative_prompt": "low quality",
                "seed": 42,
                "steps": 30,
                "sampler": "Euler a",
                "cfg_scale": 6.5,
            },
        )
        self.assertEqual(detail.images[1].url, "")
        self.assertEqual(detail.images[1].parameter_dict(), {"clip_skip": 2})

        provenance = detail.provenance_dict()
        self.assertEqual(
            provenance["model_description"],
            ("model_description", "manager_metadata"),
        )
        self.assertIn("fresh_record", provenance["trigger_words"])
        self.assertIn("manager_metadata", provenance["trigger_words"])

    def test_llm_payload_is_bounded_and_excludes_sensitive_technical_data(self) -> None:
        metadata = self._metadata()
        metadata["model"]["description"] = (
            "Installed at E:\\ComfyUI\\models\\loras and key sk-abcdefghijklmnop. "
            + "x" * 100
        )
        detail = LoraDetailAggregator.aggregate(
            self._record(),
            manager_list=self._list_item(),
            manager_metadata={"metadata": metadata},
            model_description="/mnt/private/models/denia.safetensors",
        )

        payload = detail.to_llm_payload(
            max_images=1, max_description_chars=80, max_prompt_chars=20
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("E:\\ComfyUI", serialized)
        self.assertNotIn("/mnt/private", serialized)
        self.assertNotIn("sk-abcdefghijklmnop", serialized)
        self.assertNotIn("token=", serialized)
        self.assertNotIn("workflow", serialized)
        self.assertNotIn("downloadUrl", serialized)
        self.assertNotIn('"sha256":', serialized)
        self.assertEqual(len(payload["example_images"]), 1)
        self.assertTrue(
            len(payload["example_images"][0]["generation_parameters"]["positive_prompt"])
            <= 21
        )

    def test_health_distinguishes_missing_partial_error_and_stale(self) -> None:
        record = self._record()
        missing = LoraDetailAggregator.aggregate(record)
        self.assertEqual(missing.metadata_health.status, "missing")

        partial = LoraDetailAggregator.aggregate(
            record, manager_list=self._list_item()
        )
        self.assertEqual(partial.metadata_health.status, "partial")
        self.assertIn("manager_metadata", partial.metadata_health.missing_sources)

        errored = LoraDetailAggregator.aggregate(
            record,
            manager_list=self._list_item(),
            manager_metadata={"success": False, "error": "timeout"},
        )
        self.assertEqual(errored.metadata_health.status, "error")
        self.assertEqual(errored.metadata_health.error_sources, ("manager_metadata",))

        now = datetime(2026, 7, 16, tzinfo=timezone.utc)
        stale = LoraDetailAggregator.aggregate(
            record,
            manager_list=self._list_item(),
            manager_metadata={"metadata": self._metadata()},
            model_description={"description": "description"},
            checked_at=now,
            source_fetched_at={"manager_metadata": now - timedelta(days=2)},
            stale_after_seconds=3600,
        )
        self.assertEqual(stale.metadata_health.status, "stale")
        self.assertEqual(stale.metadata_health.stale_sources, ("manager_metadata",))

    def test_selects_matching_item_from_full_list_response(self) -> None:
        other = dict(self._list_item())
        other.update(
            {
                "file_name": "other.safetensors",
                "sha256": "b" * 64,
                "model_name": "Wrong model",
            }
        )
        response = {"success": True, "items": [other, self._list_item()]}

        detail = LoraDetailAggregator.aggregate(
            self._record(), manager_list=response
        )

        self.assertEqual(detail.model_name, "Denia Character")
        self.assertEqual(detail.file_status.sha256, "a" * 64)

    def test_absolute_record_path_is_reduced_to_file_name(self) -> None:
        detail = LoraDetailAggregator.aggregate(
            self._record(
                name="E:/Private/ComfyUI/models/loras/secret/denia.safetensors",
                folder="E:/Private/ComfyUI/models/loras/secret",
                sha256="",
            )
        )

        self.assertEqual(detail.name, "denia.safetensors")
        self.assertEqual(detail.folder, "")
        self.assertEqual(detail.file_name, "denia.safetensors")
        self.assertTrue(detail.asset_id.startswith("catalog:"))

    def test_manager_display_name_without_extension_cannot_replace_live_identity(self) -> None:
        item = self._list_item()
        item["file_name"] = "denia"
        item["folder"] = ""

        detail = LoraDetailAggregator.aggregate(
            self._record(),
            manager_list=item,
        )

        self.assertEqual(detail.name, "characters/denia.safetensors")
        self.assertEqual(detail.file_name, "denia.safetensors")

    def test_invalid_usage_tips_and_unknown_fields_are_ignored(self) -> None:
        detail = LoraDetailAggregator.aggregate(
            self._record(),
            manager_list=self._list_item(),
            usage_tips={
                "usage_tips": json.dumps(
                    {
                        "strength_min": 0.4,
                        "custom_private_path": "/mnt/private/file",
                        "authorization": "Bearer secret",
                        "notes": "Use at 0.6",
                    }
                )
            },
        )

        self.assertEqual(
            detail.usage_tips_dict(),
            {"strength_min": 0.4, "notes": "Use at 0.6"},
        )


if __name__ == "__main__":
    unittest.main()
