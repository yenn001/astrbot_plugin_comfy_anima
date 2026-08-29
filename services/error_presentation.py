"""User-facing error presentation rules for 307 immersive delivery.

Presentations never fake a delivery, never leak provider ids or run ids, and
always say clearly that no image was submitted when that is the case.
"""

from __future__ import annotations

import re

_FALLBACK = "绘画没有完成，先停下来检查一下。"

_PRESENTATIONS: dict[str, str] = {
    "invalid_terminal_repair": "分镜没有返回可提交的绘图结果，本次没有生成图片。",
    "invalid_json": "分镜返回的内容不是合法绘图结构，本次没有生成图片。",
    "missing_positive_tags": "分镜缺少画面主体描述，本次没有生成图片。",
    "prompt_plan_lookup_failed": "没有找到对应的预设方案，本次没有生成图片。",
    "prompt_composition_failed": "画面组成校验失败，本次没有生成图片。",
    "lora_identity_binding_failed": "角色身份绑定未通过校验，本次没有生成图片。",
    "preset_manifest_mismatch": "风格预设与生成清单不一致，本次没有生成图片。",
    "provider_failed": "绘图模型暂时不可用，本次没有生成图片。",
    "delivery_unknown": "图片发送状态暂时无法确认，请不要认为已经送到。",
}

_SUCCESS_CLAIM_MARKERS = (
    "已发给你",
    "已经发给你",
    "发给你了",
    "照片来了",
    "图片来了",
    "生成完成",
    "已生成",
)

_INTERNAL_LEAK_PATTERN = re.compile(
    r"run[_-]?id\s*[=:]\s*[0-9a-fA-F-]{8,}"
    r"|provider[_-]?id\s*[=:]\s*[\w.-]+"
    r"|provider\s*[=:]\s*[\w./-]+"
    r"|task[_-]?id\s*[=:]\s*[0-9a-fA-F-]{8,}",
    flags=re.IGNORECASE,
)


def present_error(code: str, detail: str = "") -> str:
    """Map one internal error code to a safe user-facing message."""

    text = _PRESENTATIONS.get(str(code or "").strip(), _FALLBACK)
    if str(detail or "").strip():
        text = f"{text} {str(detail).strip()}"
    return _sanitize(text)


def _sanitize(text: str) -> str:
    cleaned = str(text or _FALLBACK).strip()
    cleaned = _INTERNAL_LEAK_PATTERN.sub("[内部信息已隐藏]", cleaned)
    for marker in _SUCCESS_CLAIM_MARKERS:
        if marker in cleaned:
            cleaned = cleaned.replace(marker, "交付状态未确认")
    return cleaned


__all__ = ["present_error"]
