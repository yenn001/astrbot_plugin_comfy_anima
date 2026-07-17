"""Tests for bounded direct and replied image collection."""

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ..models import PluginSettings
from ..services.image_input import IncomingImageError, IncomingImageService


class _ImageComponent:
    def __init__(self, file: str):
        self.file = file

    async def convert_to_file_path(self) -> str:
        return self.file


class _ReplyComponent:
    def __init__(self, chain):
        self.chain = chain


class _Event:
    def __init__(self, messages):
        self._messages = messages

    def get_messages(self):
        return self._messages


class IncomingImageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.png"
        Image.new("RGB", (32, 24), "orange").save(self.source)
        self.service = IncomingImageService(
            PluginSettings.from_mapping(
                {"max_input_image_size_mb": 1, "max_input_image_pixels": 10_000}
            ),
            self.root / "plugin-temp",
        )
        self.components = types.SimpleNamespace(
            Image=_ImageComponent,
            Reply=_ReplyComponent,
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_direct_image_is_copied_to_plugin_temp(self) -> None:
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            result = await self.service.collect_one(
                _Event([_ImageComponent(str(self.source))])
            )
        self.assertTrue(result.is_file())
        self.assertNotEqual(result, self.source)
        self.assertEqual(result.suffix, ".png")

    async def test_aiocqhttp_reply_chain_is_supported_without_helper(self) -> None:
        reply = _ReplyComponent([_ImageComponent(str(self.source))])
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            result = await self.service.collect_one(_Event([reply]))
        self.assertTrue(result.is_file())

    async def test_multiple_reply_images_are_rejected(self) -> None:
        reply = _ReplyComponent(
            [
                _ImageComponent(str(self.source)),
                _ImageComponent(str(self.source)),
            ]
        )
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            with self.assertRaises(IncomingImageError):
                await self.service.collect_one(_Event([reply]))

    async def test_pixel_limit_is_enforced_after_image_verification(self) -> None:
        service = IncomingImageService(
            PluginSettings.from_mapping({"max_input_image_pixels": 1_000_000}),
            self.root / "small-limit",
        )
        # PluginSettings clamps the configured minimum to one million pixels.
        oversized = self.root / "oversized.png"
        Image.new("RGB", (1100, 1000), "black").save(oversized)
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            with self.assertRaises(IncomingImageError):
                await service.collect_one(_Event([_ImageComponent(str(oversized))]))


if __name__ == "__main__":
    unittest.main()
