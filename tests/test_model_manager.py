"""Safe LoRA and UNET deletion service tests."""

from __future__ import annotations

import unittest
from typing import Any

from ..models import PluginSettings
from ..services.lora_catalog import LoraRecord
from ..services.model_manager import ModelManagerError, ModelManagerService
from ..services.unet_catalog import UnetModelEntry


class _FakeLoraCatalog:
    def __init__(self, events: list[str], records: tuple[LoraRecord, ...]):
        self.events = events
        self.records = records

    async def refresh_for_operation(self) -> tuple[LoraRecord, ...]:
        self.events.append("lora-refresh")
        return self.records


class _FakeUnetCatalog:
    def __init__(self, events: list[str], names: tuple[str, ...]):
        self.events = events
        self.names = names

    async def list_models(self) -> tuple[UnetModelEntry, ...]:
        self.events.append("comfy-unet-refresh")
        return tuple(
            UnetModelEntry(index=index, name=name)
            for index, name in enumerate(self.names, start=1)
        )


class _FakeModelManager(ModelManagerService):
    def __init__(
        self,
        *,
        events: list[str],
        lora_records: tuple[LoraRecord, ...] = (),
        unet_names: tuple[str, ...] = (),
        manager_items: list[dict[str, Any]] | None = None,
        current_unet: str = "",
        preset_reference_resolver=None,
        preset_removal_callback=None,
    ) -> None:
        settings = PluginSettings.from_mapping(
            {
                "comfyui_url": "http://192.168.1.50:8188",
                "unet_model_name": current_unet,
            }
        )
        self.events = events
        self.manager_items = list(manager_items or [])
        self.delete_payloads: list[dict[str, Any]] = []
        self.delete_success = True
        super().__init__(
            settings,
            _FakeLoraCatalog(events, lora_records),
            _FakeUnetCatalog(events, unet_names),
            preset_reference_resolver=preset_reference_resolver,
            preset_removal_callback=preset_removal_callback,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        del timeout
        self.events.append(f"{method}:{path}")
        if path.endswith("/scan"):
            return {"success": True}
        if path.endswith("/list"):
            self.assert_list_params(params)
            return {
                "items": self.manager_items,
                "total_pages": 1,
            }
        if path.endswith("/delete"):
            self.delete_payloads.append(dict(payload or {}))
            return {"success": self.delete_success, "deleted": ["hidden"]}
        raise AssertionError(f"Unexpected endpoint: {method} {path}")

    @staticmethod
    def assert_list_params(params: dict[str, Any] | None) -> None:
        if not params or params.get("page") != 1 or params.get("page_size") != 100:
            raise AssertionError(f"Unexpected list params: {params}")


def _lora(name: str = "characters/denia") -> LoraRecord:
    return LoraRecord(
        name=name,
        file_path="E:/ComfyUI/models/loras/characters/denia.safetensors",
        source="LoRA Manager",
    )


def _unet_item(
    name: str = "anima-v1.safetensors",
    *,
    sub_type: str = "diffusion_model",
    file_path: str = "/ComfyUI/models/diffusion_models/anima-v1.safetensors",
) -> dict[str, Any]:
    return {
        "file_name": name,
        "file_path": file_path,
        "sub_type": sub_type,
    }


class LoraDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_only_after_mandatory_refresh_and_returns_no_path(
        self,
    ) -> None:
        events: list[str] = []
        service = _FakeModelManager(events=events, lora_records=(_lora(),))

        result = await service.delete_lora(
            "characters/denia",
            "characters/denia",
        )

        self.assertEqual(events, ["lora-refresh", "POST:/api/lm/loras/delete"])
        self.assertEqual(
            service.delete_payloads,
            [{"file_path": ("E:/ComfyUI/models/loras/characters/denia.safetensors")}],
        )
        self.assertTrue(result.deleted)
        self.assertEqual(result.exact_name, "characters/denia")
        self.assertNotIn("path", result.as_dict())
        self.assertNotIn("file_path", result.as_dict())
        self.assertNotIn("ComfyUI", repr(result))

    async def test_refreshes_before_rejecting_confirmation_mismatch(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(events=events, lora_records=(_lora(),))

        with self.assertRaisesRegex(ModelManagerError, "确认名称"):
            await service.delete_lora("characters/denia", "denia")

        self.assertEqual(events, ["lora-refresh"])
        self.assertEqual(service.delete_payloads, [])

    async def test_rejects_unsafe_manager_path(self) -> None:
        events: list[str] = []
        unsafe = LoraRecord(
            name="denia",
            file_path="../models/loras/denia.safetensors",
        )
        service = _FakeModelManager(events=events, lora_records=(unsafe,))

        with self.assertRaisesRegex(ModelManagerError, "绝对路径"):
            await service.delete_lora("denia", "denia")

        self.assertEqual(events, ["lora-refresh"])

    async def test_does_not_fuzzy_match_a_lora_basename(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(events=events, lora_records=(_lora(),))

        with self.assertRaisesRegex(ModelManagerError, "精确名称"):
            await service.delete_lora("denia", "denia")

        self.assertEqual(events, ["lora-refresh"])

    async def test_blocks_referenced_preset_without_explicit_cleanup(self) -> None:
        events: list[str] = []

        async def references(_name: str) -> tuple[str, ...]:
            events.append("preset-check")
            return ("风格001", "角色达妮娅")

        service = _FakeModelManager(
            events=events,
            lora_records=(_lora(),),
            preset_reference_resolver=references,
        )

        with self.assertRaisesRegex(ModelManagerError, "2 个预设"):
            await service.delete_lora("characters/denia", "characters/denia")

        self.assertEqual(events, ["lora-refresh", "preset-check"])

    async def test_explicit_cleanup_must_remove_all_references(self) -> None:
        events: list[str] = []
        referenced = True

        async def references(_name: str) -> tuple[str, ...]:
            events.append("preset-check")
            return ("风格001",) if referenced else ()

        async def remove(_name: str) -> int:
            nonlocal referenced
            events.append("preset-remove")
            referenced = False
            return 1

        service = _FakeModelManager(
            events=events,
            lora_records=(_lora(),),
            preset_reference_resolver=references,
            preset_removal_callback=remove,
        )

        result = await service.delete_lora(
            "characters/denia",
            "characters/denia",
            remove_from_presets=True,
        )

        self.assertEqual(
            events,
            [
                "lora-refresh",
                "preset-check",
                "preset-remove",
                "preset-check",
                "POST:/api/lm/loras/delete",
            ],
        )
        self.assertTrue(result.removed_from_presets)
        self.assertEqual(result.preset_cleanup_count, 1)

    async def test_incomplete_preset_cleanup_still_blocks_delete(self) -> None:
        events: list[str] = []

        async def references(_name: str) -> tuple[str, ...]:
            events.append("preset-check")
            return ("风格001",)

        async def remove(_name: str) -> int:
            events.append("preset-remove")
            return 1

        service = _FakeModelManager(
            events=events,
            lora_records=(_lora(),),
            preset_reference_resolver=references,
            preset_removal_callback=remove,
        )

        with self.assertRaisesRegex(ModelManagerError, "清理不完整"):
            await service.delete_lora(
                "characters/denia",
                "characters/denia",
                remove_from_presets=True,
            )

        self.assertNotIn("POST:/api/lm/loras/delete", events)

    async def test_manager_must_explicitly_confirm_success(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(events=events, lora_records=(_lora(),))
        service.delete_success = False

        with self.assertRaisesRegex(ModelManagerError, "未确认删除成功"):
            await service.delete_lora("characters/denia", "characters/denia")


class UnetDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_diffusion_models_and_deletes_exact_fresh_match(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[
                _unet_item(
                    "checkpoint.safetensors",
                    sub_type="checkpoint",
                    file_path="/ComfyUI/models/checkpoints/checkpoint.safetensors",
                ),
                _unet_item(),
            ],
        )

        result = await service.delete_unet(
            "anima-v1.safetensors",
            "anima-v1.safetensors",
        )

        self.assertEqual(
            events,
            [
                "GET:/api/lm/checkpoints/scan",
                "GET:/api/lm/checkpoints/list",
                "comfy-unet-refresh",
                "POST:/api/lm/checkpoints/delete",
            ],
        )
        self.assertEqual(
            service.delete_payloads,
            [{"file_path": ("/ComfyUI/models/diffusion_models/anima-v1.safetensors")}],
        )
        self.assertEqual(result.model_type, "unet")
        self.assertNotIn("path", result.as_dict())
        self.assertNotIn("ComfyUI", repr(result))

    async def test_refuses_to_delete_current_unet_after_refresh(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[_unet_item()],
            current_unet="anima-v1.safetensors",
        )

        with self.assertRaisesRegex(ModelManagerError, "当前正在使用"):
            await service.delete_unet(
                "anima-v1.safetensors",
                "anima-v1.safetensors",
            )

        self.assertEqual(
            events,
            [
                "GET:/api/lm/checkpoints/scan",
                "GET:/api/lm/checkpoints/list",
                "comfy-unet-refresh",
            ],
        )

    async def test_rejects_checkpoint_row_even_if_filename_matches(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[_unet_item(sub_type="checkpoint")],
        )

        with self.assertRaisesRegex(ModelManagerError, "Manager 清单"):
            await service.delete_unet(
                "anima-v1.safetensors",
                "anima-v1.safetensors",
            )

    async def test_rejects_unet_path_traversal(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[
                _unet_item(
                    file_path="/ComfyUI/models/diffusion_models/../anima-v1.safetensors"
                )
            ],
        )

        with self.assertRaisesRegex(ModelManagerError, "路径不安全"):
            await service.delete_unet(
                "anima-v1.safetensors",
                "anima-v1.safetensors",
            )

    async def test_rejects_manager_path_with_different_basename(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[
                {
                    "file_name": "anima-v1.safetensors",
                    "file_path": (
                        "/ComfyUI/models/diffusion_models/another-model.safetensors"
                    ),
                    "sub_type": "diffusion_model",
                }
            ],
        )

        with self.assertRaisesRegex(ModelManagerError, "路径与所选模型"):
            await service.delete_unet(
                "anima-v1.safetensors",
                "anima-v1.safetensors",
            )

    async def test_rejects_ambiguous_manager_rows(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[
                _unet_item(),
                _unet_item(
                    file_path=(
                        "/ComfyUI/secondary/diffusion_models/anima-v1.safetensors"
                    )
                ),
            ],
        )

        with self.assertRaisesRegex(ModelManagerError, "重名 UNET"):
            await service.delete_unet(
                "anima-v1.safetensors",
                "anima-v1.safetensors",
            )

    async def test_refreshes_before_confirmation_mismatch(self) -> None:
        events: list[str] = []
        service = _FakeModelManager(
            events=events,
            unet_names=("anima-v1.safetensors",),
            manager_items=[_unet_item()],
        )

        with self.assertRaisesRegex(ModelManagerError, "确认名称"):
            await service.delete_unet("anima-v1.safetensors", "wrong")

        self.assertEqual(
            events,
            [
                "GET:/api/lm/checkpoints/scan",
                "GET:/api/lm/checkpoints/list",
                "comfy-unet-refresh",
            ],
        )


class ModelManagerConfigurationTests(unittest.TestCase):
    def test_rejects_public_or_credentialed_manager_origin(self) -> None:
        invalid_urls = (
            "https://example.com",
            "http://user:pass@192.168.1.50:8188",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ModelManagerError):
                settings = PluginSettings.from_mapping(
                    {"comfyui_url": url, "lora_manager_url": url}
                )
                ModelManagerService(
                    settings,
                    _FakeLoraCatalog([], ()),
                    _FakeUnetCatalog([], ()),
                )


if __name__ == "__main__":
    unittest.main()
