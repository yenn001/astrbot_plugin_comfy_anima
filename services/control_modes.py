"""Normalize explicit and natural-language reference-control modes.

This module deliberately contains no AstrBot or ComfyUI dependencies.  Command
parsers can use :func:`parse_explicit_control_modes`, while message routers can
use :func:`extract_natural_control_modes` and make their own decision about
whether a source image is actually present.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final


CONTROL_MODES: Final[tuple[str, ...]] = (
    "pose",
    "depth",
    "lineart",
    "reference",
)

_MODE_ALIASES: Final[dict[str, str]] = {
    "p": "pose",
    "pose": "pose",
    "openpose": "pose",
    "dwpose": "pose",
    "姿势": "pose",
    "姿态": "pose",
    "骨架": "pose",
    "d": "depth",
    "depth": "depth",
    "深度": "depth",
    "深度图": "depth",
    "构图": "depth",
    "空间": "depth",
    "l": "lineart",
    "line": "lineart",
    "lineart": "lineart",
    "line art": "lineart",
    "线稿": "lineart",
    "线描": "lineart",
    "草图": "lineart",
    "r": "reference",
    "ref": "reference",
    "reference": "reference",
    "ipadapter": "reference",
    "ip-adapter": "reference",
    "参考": "reference",
    "参考图": "reference",
}

_EXPLICIT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[\s,，;+|/、]+")

# A natural-language feature only becomes a control mode when it is near a
# reference/control verb.  This prevents bare phrases such as "构图漂亮一些"
# and "给衣服上色" from unexpectedly consuming an attached image.
_CONTROL_CUE = (
    r"(?:只|仅)?(?:按|按照|照着|参考|参照|沿用|保留|保持|锁定|固定|控制|"
    r"跟随|提取|复用|套用|使用|用)"
)

# Reference is deliberately stricter than the geometric modes.  Generic
# phrases such as ``用风格001画`` name a saved LoRA preset; they do not ask to
# copy the source image's appearance.  A style/colour reference therefore
# needs an explicit image anchor, while identity/material references retain a
# bounded source-preservation verb.
_REFERENCE_CUE = r"(?:参考|参照|沿用|保留|保持|锁定|固定|跟随|提取|复用)"
_REFERENCE_IMAGE = r"(?:这张图|这幅图|该图|原图|底图|参考图|图片|图中|画面中)"
_REFERENCE_STYLE = r"(?:画风|风格|配色|色彩)"
_REFERENCE_APPEARANCE = (
    r"(?:人物(?:的)?外观|角色(?:的)?外观|长相|脸部|脸型|五官|"
    r"服装(?:的)?质感|材质|质感)"
)
_REFERENCE_GAP = r"[^，,。；;！？!?\n]{0,10}"
_REFERENCE_POSSESSIVE = r"(?:的|之|里|中的?|内的?)?"

_FEATURE_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "pose": (
        re.compile(r"\b(?:openpose|dwpose|pose)(?:\s*(?:mode|control|模式|控制))?\b", re.I),
        re.compile(
            rf"{_CONTROL_CUE}.{{0,14}}(?:姿势|姿态|动作|骨架|人体姿态|站姿|坐姿|手势)",
            re.I,
        ),
        re.compile(
            r"(?:姿势|姿态|动作|骨架|人体姿态|站姿|坐姿|手势).{0,10}"
            r"(?:参考|参照|沿用|保留|保持|锁定|固定|控制|跟随)",
            re.I,
        ),
    ),
    "depth": (
        re.compile(
            r"\bdepth(?!\s+of\s+field)(?:\s*(?:map|mode|control))?\b",
            re.I,
        ),
        re.compile(r"(?:深度图|depth)\s*(?:模式|控制|参考)", re.I),
        re.compile(
            rf"{_CONTROL_CUE}.{{0,14}}(?:构图|深度图|空间结构|空间关系|前后关系|"
            r"透视(?:关系|布局)?|物体布局|画面布局|轮廓布局)",
            re.I,
        ),
        re.compile(
            r"(?:构图|深度图|空间结构|空间关系|前后关系|透视(?:关系|布局)?|"
            r"物体布局|画面布局|轮廓布局).{0,10}"
            r"(?:参考|参照|沿用|保留|保持|锁定|固定|控制|跟随)",
            re.I,
        ),
    ),
    "lineart": (
        re.compile(r"\bline\s*-?\s*art(?:\s*(?:mode|control))?\b", re.I),
        re.compile(r"(?:线稿|线描|草图|轮廓线)\s*(?:模式|控制|参考)", re.I),
        re.compile(r"(?:按|按照|照着|参考|沿用).{0,12}(?:线稿|线描|草图|轮廓线).{0,8}上色", re.I),
        re.compile(r"(?:给|把|将).{0,10}(?:线稿|线描|草图).{0,8}(?:上色|着色|完成上色)", re.I),
        re.compile(
            rf"{_CONTROL_CUE}.{{0,14}}(?:线稿|线描|草图|轮廓线)",
            re.I,
        ),
    ),
    "reference": (
        re.compile(r"\b(?:reference|ref|ip\s*-?\s*adapter)(?:\s*(?:mode|control))?\b", re.I),
        re.compile(r"(?:reference|参考)\s*(?:模式|控制)", re.I),
        re.compile(
            rf"(?:{_REFERENCE_CUE}|(?:套用|使用|用).{{0,6}})"
            rf"{_REFERENCE_GAP}{_REFERENCE_IMAGE}{_REFERENCE_POSSESSIVE}"
            rf"(?:{_REFERENCE_STYLE}|{_REFERENCE_APPEARANCE})",
            re.I,
        ),
        re.compile(
            rf"(?:{_REFERENCE_STYLE}|{_REFERENCE_APPEARANCE})"
            rf"{_REFERENCE_GAP}{_REFERENCE_CUE}{_REFERENCE_GAP}"
            rf"{_REFERENCE_IMAGE}",
            re.I,
        ),
        re.compile(
            rf"{_REFERENCE_CUE}{_REFERENCE_GAP}{_REFERENCE_APPEARANCE}",
            re.I,
        ),
        re.compile(
            rf"{_REFERENCE_APPEARANCE}{_REFERENCE_GAP}{_REFERENCE_CUE}",
            re.I,
        ),
    ),
}

_COMMAND_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[/／]?\s*(?:底图控制|控制画图|反推画图)\s*[:：]?\s*",
    re.I,
)
_COMMAND_LOCK_CUE = r"(?:不变|保持不变|保持|保留|锁定|固定|沿用|参考|参照)"
_COMMAND_SCOPED_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "pose": (
        re.compile(
            rf"(?:姿势|姿态|动作|骨架|人体姿态|站姿|坐姿|手势)"
            rf".{{0,10}}{_COMMAND_LOCK_CUE}",
            re.I,
        ),
        re.compile(
            rf"{_COMMAND_LOCK_CUE}.{{0,10}}"
            r"(?:姿势|姿态|动作|骨架|人体姿态|站姿|坐姿|手势)",
            re.I,
        ),
    ),
    "depth": (
        re.compile(
            rf"(?:构图|深度图|空间结构|空间关系|前后关系|透视(?:关系|布局)?|"
            rf"物体布局|画面布局|轮廓布局).{{0,10}}{_COMMAND_LOCK_CUE}",
            re.I,
        ),
        re.compile(
            rf"{_COMMAND_LOCK_CUE}.{{0,10}}(?:构图|深度图|空间结构|空间关系|"
            r"前后关系|透视(?:关系|布局)?|物体布局|画面布局|轮廓布局)",
            re.I,
        ),
    ),
    "lineart": (
        re.compile(
            r"(?:线稿|线描|草图|轮廓线).{0,10}(?:上色|着色|完成上色|保持|保留|参考|参照)",
            re.I,
        ),
        re.compile(
            r"(?:按|按照|照着|参考|参照|沿用|保持|保留).{0,10}"
            r"(?:线稿|线描|草图|轮廓线)",
            re.I,
        ),
    ),
}

_NEGATION_PREFIX = (
    r"(?:不要|不用|无需|不需要|不必|别|取消|关闭|禁用|不使用|不参考|"
    r"不沿用|不保留|不保持|不锁定|不固定)"
)
_NEGATION_FEATURES: Final[dict[str, str]] = {
    "pose": r"(?:姿势|姿态|动作|骨架|人体姿态|站姿|坐姿|手势|openpose|dwpose|pose)",
    "depth": r"(?:构图|深度图|空间结构|空间关系|前后关系|透视(?:关系|布局)?|物体布局|画面布局|depth)",
    "lineart": r"(?:线稿|线描|草图|轮廓线|line\s*-?\s*art|lineart)",
    "reference": r"(?:画风|风格|配色|色彩|人物外观|角色外观|长相|脸部|脸型|五官|材质|质感|reference|ref|ip\s*-?\s*adapter)",
}

_ONLY_CLAUSE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:只|仅)(?:需|要)?(?:参考|参照|沿用|保留|保持|锁定|固定|控制|使用|用)"
    r"(?P<body>[^，,。；;！？!?\n]{1,48})",
    re.I,
)


class ControlModeError(ValueError):
    """Raised when an explicit control-mode value is empty or unsupported."""


def normalize_control_mode(value: object) -> str:
    """Return one canonical control mode from a short, English or Chinese alias."""

    normalized = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    mode = _MODE_ALIASES.get(normalized)
    if mode is None:
        raise ControlModeError(
            f"未知底图控制模式：{value!s}；仅支持 p/pose、d/depth、"
            "l/lineart、r/reference"
        )
    return mode


def parse_explicit_control_modes(values: str | Iterable[object]) -> tuple[str, ...]:
    """Parse one or more explicit values and de-duplicate them in input order.

    A string may use whitespace, commas, ``+``, ``|``, slash or Chinese list
    separators.  Iterables are useful to merge repeated command options, e.g.
    ``("p", "p d")`` from ``--m p --m p d``.
    """

    raw_values: Iterable[object]
    if isinstance(values, str):
        raw_values = (values,)
    else:
        raw_values = values

    result: list[str] = []
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        # Preserve the useful two-word alias before splitting general lists.
        compact = re.sub(r"\s+", " ", text.casefold())
        pieces = (
            [compact]
            if compact in _MODE_ALIASES
            else [item for item in _EXPLICIT_SPLIT_RE.split(text) if item]
        )
        for piece in pieces:
            mode = normalize_control_mode(piece)
            if mode not in result:
                result.append(mode)

    if not result:
        raise ControlModeError(
            "底图控制模式不能为空；请使用 p、d、l、r 或对应完整名称"
        )
    return tuple(result)


def _mentioned_modes(text: str) -> set[str]:
    """Find feature names inside an already control-scoped short clause."""

    result: set[str] = set()
    aliases = {
        "pose": r"(?:姿势|姿态|动作|骨架|站姿|坐姿|手势|openpose|dwpose|\bpose\b)",
        "depth": r"(?:构图|深度图|空间结构|空间关系|前后关系|透视|布局|\bdepth\b)",
        "lineart": r"(?:线稿|线描|草图|轮廓线|line\s*-?\s*art|\blineart\b)",
        "reference": r"(?:画风|风格|配色|色彩|人物外观|角色外观|长相|脸部|五官|材质|质感|\breference\b|\bref\b|ip\s*-?\s*adapter)",
    }
    for mode, pattern in aliases.items():
        if re.search(pattern, text, re.I):
            result.add(mode)
    return result


def _is_negated(message: str, mode: str) -> bool:
    feature = _NEGATION_FEATURES[mode]
    patterns = (
        rf"{_NEGATION_PREFIX}.{{0,8}}{feature}",
        rf"{feature}\s*(?:不要|不用|取消|关闭|禁用|不参考|不保留|不保持|重新设计|自由发挥)",
    )
    return any(re.search(pattern, message, re.I) for pattern in patterns)


def extract_natural_control_modes(message: object) -> tuple[str, ...]:
    """Extract contextual pose/depth/lineart/reference requests.

    The return order is the stable canonical order in :data:`CONTROL_MODES`.
    This function only interprets text; callers must still require exactly one
    valid source image before starting a control-generation workflow.
    """

    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not text:
        return ()

    selected = {
        mode
        for mode, patterns in _FEATURE_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }

    # "只参考/只保留 ..." is a hard upper bound.  It prevents a later mention
    # such as "构图重新设计" from being accidentally added as another control.
    only_modes: set[str] = set()
    for match in _ONLY_CLAUSE_RE.finditer(text):
        only_modes.update(_mentioned_modes(match.group("body")))
    if only_modes:
        selected.intersection_update(only_modes)

    for mode in tuple(selected):
        if _is_negated(text, mode):
            selected.discard(mode)

    return tuple(mode for mode in CONTROL_MODES if mode in selected)


def extract_command_control_modes(message: object) -> tuple[str, ...]:
    """Infer modes inside an explicit control/reverse-draw command.

    Command scope permits concise locks such as ``构图和姿势不变`` without
    broadening the ordinary natural-language router, where the same wording
    may belong to a semantic redraw.  Reference still uses the strict,
    source-image-aware rules from :func:`extract_natural_control_modes`.
    """

    text = re.sub(r"\s+", " ", str(message or "").strip())
    text = _COMMAND_PREFIX_RE.sub("", text, count=1)
    if not text:
        return ()

    selected = set(extract_natural_control_modes(text))
    for mode, patterns in _COMMAND_SCOPED_PATTERNS.items():
        if any(pattern.search(text) for pattern in patterns):
            selected.add(mode)
    for mode in tuple(selected):
        if _is_negated(text, mode):
            selected.discard(mode)
    return tuple(mode for mode in CONTROL_MODES if mode in selected)


def looks_like_control_request(message: object) -> bool:
    """Return whether contextual natural language selects any control mode."""

    return bool(extract_natural_control_modes(message))


__all__ = [
    "CONTROL_MODES",
    "ControlModeError",
    "extract_command_control_modes",
    "extract_natural_control_modes",
    "looks_like_control_request",
    "normalize_control_mode",
    "parse_explicit_control_modes",
]
