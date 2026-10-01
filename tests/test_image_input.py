"""Tests for bounded direct and replied image collection."""

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    async def test_direct_and_quoted_sources_are_rejected_as_ambiguous(self) -> None:
        reply = _ReplyComponent([_ImageComponent(str(self.source))])
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            with self.assertRaisesRegex(IncomingImageError, "同时"):
                await self.service.collect_one(
                    _Event([_ImageComponent(str(self.source)), reply])
                )

    async def test_direct_and_helper_quoted_ref_are_also_ambiguous(self) -> None:
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ), patch.object(
            self.service,
            "_quoted_refs",
            AsyncMock(return_value=[str(self.source)]),
        ):
            with self.assertRaisesRegex(IncomingImageError, "同时"):
                await self.service.collect_one(
                    _Event([_ImageComponent(str(self.source))])
                )

    async def test_collect_many_orders_reply_before_direct_attachment(self) -> None:
        direct_source = self.root / "direct.png"
        Image.new("RGB", (32, 24), "blue").save(direct_source)
        reply = _ReplyComponent([_ImageComponent(str(self.source))])
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            results = await self.service.collect_many(
                _Event([_ImageComponent(str(direct_source)), reply])
            )

        self.assertEqual(len(results), 2)
        with Image.open(results[0]) as first, Image.open(results[1]) as second:
            self.assertEqual(first.getpixel((0, 0)), (255, 165, 0))
            self.assertEqual(second.getpixel((0, 0)), (0, 0, 255))

    async def test_collect_many_sha_deduplicates_reply_and_direct_copy(self) -> None:
        reply = _ReplyComponent([_ImageComponent(str(self.source))])
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            results = await self.service.collect_up_to_two(
                _Event([reply, _ImageComponent(str(self.source))])
            )

        self.assertEqual(len(results), 1)

    async def test_collect_many_rejects_more_than_two_direct_images(self) -> None:
        second = self.root / "second.png"
        third = self.root / "third.png"
        Image.new("RGB", (32, 24), "blue").save(second)
        Image.new("RGB", (32, 24), "green").save(third)
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            with self.assertRaisesRegex(IncomingImageError, "最多"):
                await self.service.collect_many(
                    _Event(
                        [
                            _ImageComponent(str(self.source)),
                            _ImageComponent(str(second)),
                            _ImageComponent(str(third)),
                        ]
                    )
                )

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

    async def test_reply_source_plus_direct_mask_builds_inpaint_pair(self) -> None:
        mask = self.root / "mask.png"
        Image.new("RGB", (32, 24), "black").save(mask)
        with Image.open(mask) as image:
            image.putpixel((5, 5), (255, 255, 255))
            image.save(mask)
        reply = _ReplyComponent([_ImageComponent(str(self.source))])
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            pair = await self.service.collect_inpaint_pair(
                _Event([reply, _ImageComponent(str(mask))])
            )
        self.assertEqual((pair.width, pair.height), (32, 24))
        self.assertEqual(pair.mask_source, "explicit_image")
        self.assertTrue(pair.source.is_file())
        self.assertTrue(pair.mask.is_file())

    async def test_two_direct_images_use_source_then_mask_order(self) -> None:
        mask = self.root / "direct-mask.png"
        Image.new("RGB", (32, 24), "white").save(mask)
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            pair = await self.service.collect_inpaint_pair(
                _Event(
                    [
                        _ImageComponent(str(self.source)),
                        _ImageComponent(str(mask)),
                    ]
                )
            )
        self.assertEqual(pair.mask_source, "explicit_image")

    async def test_inpaint_rejects_mismatched_or_empty_mask(self) -> None:
        mismatched = self.root / "mismatched.png"
        Image.new("RGB", (16, 16), "white").save(mismatched)
        empty = self.root / "empty-mask.png"
        Image.new("RGB", (32, 24), "black").save(empty)
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            with self.assertRaisesRegex(IncomingImageError, "尺寸"):
                await self.service.collect_inpaint_pair(
                    _Event(
                        [
                            _ImageComponent(str(self.source)),
                            _ImageComponent(str(mismatched)),
                        ]
                    )
                )
            with self.assertRaisesRegex(IncomingImageError, "遮罩为空"):
                await self.service.collect_inpaint_pair(
                    _Event(
                        [
                            _ImageComponent(str(self.source)),
                            _ImageComponent(str(empty)),
                        ]
                    )
                )

    async def test_single_transparent_png_uses_alpha_mask(self) -> None:
        rgba = self.root / "alpha-source.png"
        image = Image.new("RGBA", (32, 24), (255, 128, 0, 255))
        image.putpixel((4, 4), (255, 128, 0, 0))
        image.save(rgba)
        with patch(
            "astrbot_plugin_comfy_anima.services.image_input.Comp",
            self.components,
        ):
            pair = await self.service.collect_inpaint_pair(
                _Event([_ImageComponent(str(rgba))])
            )
        self.assertEqual(pair.mask_source, "source_alpha")
        with Image.open(pair.mask) as mask:
            self.assertEqual(mask.getpixel((4, 4)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
