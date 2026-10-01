"""Deterministic three-state asset probe classification.

An asset probe is a tool the main LLM may call while preparing a drawing
terminal. ``MISS`` is a definitive negative answer (nothing found) and never
seals the terminal; ``FATAL`` is an infrastructure/permission/content failure
and always seals it.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Mapping, Optional


class AssetProbeResult(str, Enum):
    EVIDENCE_OK = "evidence_ok"
    MISS = "miss"
    FATAL = "fatal"


_FAILURE_MARKERS = (
    "lora manager is unavailable",
    "lora manager refresh failed",
    "lora preset query unavailable",
    "stop this lora drawing request",
    "do not select any lora",
    "error: tool ",
    "the tool returned no content",
)

_MISS_MARKERS = (
    "prompt_plan_lookup_failed",
    "no matching saved lora presets were found",
)


def classify_asset_probe(
    tool_name: str,
    tool_args: Optional[Mapping[str, Any]],
    tool_result: Any,
    text: str,
) -> AssetProbeResult:
    """Map one asset tool result to evidence-ok, miss or fatal."""

    if bool(
        getattr(tool_result, "isError", False)
        or getattr(tool_result, "is_error", False)
    ):
        return AssetProbeResult.FATAL

    source = str(text or "").strip()
    if not source:
        return AssetProbeResult.FATAL

    try:
        payload = json.loads(source)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = None

    name = str(tool_name or "").strip()
    args = dict(tool_args) if isinstance(tool_args, Mapping) else {}
    lowered = source.casefold()

    if isinstance(payload, Mapping) and "ok" in payload:
        if not bool(payload.get("ok")):
            code = str(payload.get("code") or "").strip().casefold()
            message = str(payload.get("message") or "").strip().casefold()
            if "prompt_plan_lookup_failed" in code or "prompt plan not found" in message:
                return AssetProbeResult.MISS
            if "no matching saved lora presets were found" in lowered:
                return AssetProbeResult.MISS
            return AssetProbeResult.FATAL
        if name == "list_anima_prompt_plans":
            try:
                count = int(payload.get("count") or 0)
            except (TypeError, ValueError):
                return AssetProbeResult.FATAL
            if count <= 0:
                return AssetProbeResult.MISS

    if any(marker in lowered for marker in _FAILURE_MARKERS):
        return AssetProbeResult.FATAL

    if any(marker in lowered for marker in _MISS_MARKERS):
        return AssetProbeResult.MISS

    if name == "list_anima_lora_presets" and (
        "no matching saved lora presets were found" in lowered
    ):
        return AssetProbeResult.MISS

    if name == "list_anima_prompt_plans" and str(
        args.get("keyword") or ""
    ).strip() and '"plans":[]' in lowered.replace(" ", ""):
        return AssetProbeResult.MISS

    return AssetProbeResult.EVIDENCE_OK


__all__ = ["AssetProbeResult", "classify_asset_probe"]
