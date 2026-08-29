"""Deterministic decode and validation for the ordinary-chat picture terminal.

The conversation model must end a drawing request with exactly one ``<pic>``
block.  This module performs a single HTML unescape and rejects everything
ambiguous: double escapes, multiple terminals, bare prompts, unknown LoRA
attributes and simultaneous pic/edit blocks.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional


class PictureTerminalError(ValueError):
    """Raised when model output is not an acceptable picture terminal."""


@dataclass(frozen=True)
class PictureTerminal:
    normalized_text: str
    pic_count: int
    edit_count: int
    lora_tags: tuple[str, ...]

    def is_valid_single_pic(self) -> bool:
        return self.pic_count == 1 and self.edit_count == 0


_PIC_OPEN_RE = re.compile(r"<pic\b[^>]*>", flags=re.IGNORECASE)
_PIC_CLOSE_RE = re.compile(r"</pic\s*>", flags=re.IGNORECASE)
_EDIT_RE = re.compile(r"<edit\b[^>]*>.*?</edit\s*>", flags=re.IGNORECASE | re.DOTALL)
_LORA_TAG_RE = re.compile(r"<lora:([^>]+)>", flags=re.IGNORECASE)
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", flags=re.IGNORECASE | re.DOTALL)
_ESCAPE_TOKEN_RE = re.compile(r"&(?:lt|gt|quot|#60|#62|#34);", flags=re.IGNORECASE)
_RESIDUAL_ESCAPE_RE = re.compile(r"&(?:lt|gt|quot);", flags=re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_-]*\s*)?", flags=re.IGNORECASE)

LORA_ALLOWED_ATTRIBUTES = frozenset({"name", "weight"})


def normalize_picture_terminal_text(raw: Any) -> str:
    """Return normalized text after one deterministic decode pass."""

    text = str(raw or "")
    text = _THINK_BLOCK_RE.sub(" ", text)
    text = _CODE_FENCE_RE.sub(" ", text)
    text = text.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "")
    text = text.replace("＜", "<").replace("＞", ">")
    text = text.replace("〈", "<").replace("〉", ">")
    if _ESCAPE_TOKEN_RE.search(text):
        text = html.unescape(text)
    return text.strip()


def validate_lora_tag(
    inner: str,
    *,
    known_names: Optional[Iterable[str]] = None,
) -> None:
    """Validate a single ``<lora:...>`` body against the attribute whitelist."""

    attributes = [part.strip() for part in inner.split(",") if part.strip()]
    if not attributes:
        raise PictureTerminalError("lora tag is empty")
    parsed: dict[str, str] = {}
    if len(attributes) == 1 and "=" not in attributes[0]:
        # Canonical AstrBot form: <lora:name:weight>
        name, separator, weight = attributes[0].partition(":")
        if not separator or not name.strip():
            raise PictureTerminalError("lora tag is missing a name")
        parsed = {"name": name.strip(), "weight": weight.strip()}
    else:
        for attribute in attributes:
            key, separator, value = attribute.partition(":")
            key = key.strip().casefold()
            value = value.strip()
            if not separator or key not in LORA_ALLOWED_ATTRIBUTES:
                raise PictureTerminalError(f"非法 LoRA 属性: {attribute!r}")
            parsed[key] = value
    name = parsed.get("name", "").strip()
    if not name:
        raise PictureTerminalError("lora tag is missing a name")
    if "weight" in parsed and parsed["weight"]:
        try:
            weight = float(parsed["weight"])
        except ValueError as exc:
            raise PictureTerminalError("lora weight is not numeric") from exc
        if not 0 < weight <= 1.5:
            raise PictureTerminalError("lora weight is out of range")
    if known_names is not None:
        allowed = {str(item or "").strip() for item in known_names}
        if allowed and name not in allowed:
            raise PictureTerminalError(f"lora name is not in the catalog: {name!r}")


def parse_picture_terminal(raw: Any, *, known_lora_names: Optional[Iterable[str]] = None) -> PictureTerminal:
    """Decode and validate a picture terminal without executing anything."""

    text = normalize_picture_terminal_text(raw)
    if _RESIDUAL_ESCAPE_RE.search(text):
        raise PictureTerminalError("双重转义，拒绝执行")

    pic_opens = len(_PIC_OPEN_RE.findall(text))
    pic_closes = len(_PIC_CLOSE_RE.findall(text))
    edit_count = len(_EDIT_RE.findall(text))
    lora_tags = tuple(_LORA_TAG_RE.findall(text))

    for lora_tag in lora_tags:
        validate_lora_tag(lora_tag, known_names=known_lora_names)

    if pic_opens == 0 and edit_count == 0:
        raise PictureTerminalError("只有裸 prompt，没有合法终端标签")
    if pic_closes > 1:
        raise PictureTerminalError("pic 闭合标签多余一个")
    if pic_opens != 1:
        raise PictureTerminalError(f"pic 标签必须恰好一个，实际 {pic_opens} 个")
    if edit_count:
        raise PictureTerminalError("pic 与 edit 不能同时出现")
    return PictureTerminal(
        normalized_text=text,
        pic_count=pic_opens,
        edit_count=edit_count,
        lora_tags=lora_tags,
    )


def is_valid_single_pic(raw: Any, *, known_lora_names: Optional[Iterable[str]] = None) -> bool:
    """Convenience boolean used by the terminal guard."""

    try:
        return parse_picture_terminal(raw, known_lora_names=known_lora_names).is_valid_single_pic()
    except PictureTerminalError:
        return False
