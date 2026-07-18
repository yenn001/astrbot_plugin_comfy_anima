"""Resolve direct and replied AstrBot images into bounded local files."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

try:  # AstrBot is not installed in the standalone unit-test environment.
    import astrbot.api.message_components as Comp
except ImportError:  # pragma: no cover - exercised by import compatibility tests
    Comp = None  # type: ignore[assignment]

from ..models import PluginSettings


class IncomingImageError(ValueError):
    pass


class IncomingImageService:
    def __init__(self, settings: PluginSettings, temp_dir: Path):
        self._settings = settings
        self._temp_dir = temp_dir

    @staticmethod
    def _message_chain(event: Any) -> list[Any]:
        getter = getattr(event, "get_messages", None)
        if callable(getter):
            try:
                result = getter()
                if isinstance(result, list):
                    return result
            except Exception:
                pass
        message_obj = getattr(event, "message_obj", None)
        result = getattr(message_obj, "message", None)
        return result if isinstance(result, list) else []

    @classmethod
    def _direct_images(cls, event: Any) -> list[Any]:
        image_type = getattr(Comp, "Image", None)
        if image_type is None:
            return []
        return [item for item in cls._message_chain(event) if isinstance(item, image_type)]

    @classmethod
    def _quoted_images(cls, event: Any) -> list[Any]:
        """Read aiocqhttp/NapCat Reply.chain on AstrBot versions without helpers."""
        image_type = getattr(Comp, "Image", None)
        reply_type = getattr(Comp, "Reply", None)
        if image_type is None or reply_type is None:
            return []
        result: list[Any] = []
        for item in cls._message_chain(event):
            if not isinstance(item, reply_type):
                continue
            chain = getattr(item, "chain", None)
            if not isinstance(chain, list):
                continue
            result.extend(component for component in chain if isinstance(component, image_type))
        return result

    @staticmethod
    async def _quoted_refs(event: Any) -> list[str]:
        try:
            from astrbot.core.utils.quoted_message_parser import (
                extract_quoted_message_images,
            )

            result = await extract_quoted_message_images(event)
            return [str(item) for item in result if str(item).strip()]
        except (ImportError, AttributeError):
            return []
        except Exception:
            return []

    async def _materialize_component(self, component: Any) -> Path:
        try:
            value = await component.convert_to_file_path()
        except Exception as exc:
            raise IncomingImageError("无法读取 QQ 图片，请重新发送原图") from exc
        return Path(value).expanduser().resolve(strict=True)

    async def _copy_and_validate(self, source: Path) -> Path:
        size = source.stat().st_size
        limit = self._settings.max_input_image_size_mb * 1024 * 1024
        if size <= 0 or size > limit:
            raise IncomingImageError(
                f"输入图片必须小于 {self._settings.max_input_image_size_mb}MB"
            )

        def inspect() -> tuple[str, int, int]:
            try:
                with Image.open(source) as image:
                    image.verify()
                with Image.open(source) as image:
                    image_format = str(image.format or "").upper()
                    width, height = image.size
            except (UnidentifiedImageError, OSError) as exc:
                raise IncomingImageError("输入文件不是有效图片") from exc
            if image_format not in {"PNG", "JPEG", "WEBP"}:
                raise IncomingImageError("只支持 PNG、JPEG 和 WebP 图片")
            if width <= 0 or height <= 0:
                raise IncomingImageError("图片尺寸无效")
            if width * height > self._settings.max_input_image_pixels:
                raise IncomingImageError(
                    f"图片像素总量不能超过 {self._settings.max_input_image_pixels}"
                )
            return image_format, width, height

        image_format, _, _ = await asyncio.to_thread(inspect)
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[image_format]
        target_dir = self._temp_dir / "incoming"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{uuid.uuid4().hex}{suffix}"
        await asyncio.to_thread(shutil.copyfile, source, target)
        return target

    async def collect_one(self, event: Any) -> Path:
        direct = self._direct_images(event)
        if len(direct) > 1:
            raise IncomingImageError("一次只能处理一张图片")
        quoted = self._quoted_images(event)
        if len(quoted) > 1:
            raise IncomingImageError("引用消息中有多张图片，请单独引用一张")
        refs = [] if quoted else await self._quoted_refs(event)
        if len(refs) > 1:
            raise IncomingImageError("引用消息中有多张图片，请单独引用一张")
        if direct and (quoted or refs):
            raise IncomingImageError("不能同时发送新图片和引用图片，请只保留一种来源")
        if direct:
            return await self._copy_and_validate(
                await self._materialize_component(direct[0])
            )
        if quoted:
            return await self._copy_and_validate(
                await self._materialize_component(quoted[0])
            )

        if refs:
            image_type = getattr(Comp, "Image", None)
            if image_type is None:
                raise IncomingImageError("当前 AstrBot 版本无法读取引用图片")
            return await self._copy_and_validate(
                await self._materialize_component(image_type(file=refs[0]))
            )
        raise IncomingImageError("请发送一张图片，或回复图片后再使用该指令")

    async def has_any(self, event: Any) -> bool:
        """Return whether the event carries any direct or quoted image source."""

        if self._direct_images(event) or self._quoted_images(event):
            return True
        return bool(await self._quoted_refs(event))


__all__ = ["IncomingImageError", "IncomingImageService"]
