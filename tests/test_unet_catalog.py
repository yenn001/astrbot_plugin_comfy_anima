"""ComfyUI UNETLoader 实时模型清单测试。"""

import unittest

from ..models import PluginSettings
from ..services.unet_catalog import (
    UnetCatalogError,
    UnetCatalogService,
    UnetModelEntry,
)


class UnetCatalogTests(unittest.TestCase):
    def test_defaults_to_comfyui_unet_object_info(self) -> None:
        settings = PluginSettings.from_mapping(
            {"comfyui_url": "http://192.168.1.50:8188"}
        )
        service = UnetCatalogService(settings)
        self.assertEqual(
            service._url,
            "http://192.168.1.50:8188/object_info/UNETLoader",
        )

    def test_parses_and_deduplicates_unet_names(self) -> None:
        payload = {
            "UNETLoader": {
                "input": {
                    "required": {
                        "unet_name": [
                            [
                                "anima-a.safetensors",
                                "anima-b.safetensors",
                                "ANIMA-A.safetensors",
                            ]
                        ]
                    }
                }
            }
        }
        self.assertEqual(
            UnetCatalogService.parse_payload(payload),
            ("anima-a.safetensors", "anima-b.safetensors"),
        )

    def test_resolves_one_based_index_and_exact_name(self) -> None:
        entries = (
            UnetModelEntry(1, "anima-a.safetensors"),
            UnetModelEntry(2, "folder/anima-b.safetensors"),
        )
        self.assertEqual(UnetCatalogService.resolve("2", entries), entries[1])
        self.assertEqual(
            UnetCatalogService.resolve("FOLDER/ANIMA-B.SAFETENSORS", entries),
            entries[1],
        )
        with self.assertRaises(UnetCatalogError):
            UnetCatalogService.resolve("3", entries)

    def test_listing_marks_current_model(self) -> None:
        entries = (
            UnetModelEntry(1, "anima-a.safetensors"),
            UnetModelEntry(2, "anima-b.safetensors"),
        )
        text = UnetCatalogService.format_listing(entries, "anima-b.safetensors")
        self.assertIn("2. anima-b.safetensors ✅ 当前", text)

    def test_rejects_public_or_credentialed_catalog_url(self) -> None:
        for url in (
            "https://example.com/object_info/UNETLoader",
            "http://user:pass@192.168.1.50:8188/object_info/UNETLoader",
        ):
            with self.subTest(url=url), self.assertRaises(UnetCatalogError):
                UnetCatalogService(
                    PluginSettings.from_mapping({"unet_catalog_url": url})
                )


if __name__ == "__main__":
    unittest.main()
