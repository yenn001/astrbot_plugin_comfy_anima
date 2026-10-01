"""Preview permission control for prompt and manifest previews.

Preview content is sensitive: only the admin or an explicitly whitelisted
user can see full prompt/manifest payloads. Other users get a sanitized
summary that never contains prompt text or LoRA weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PreviewDecision:
    allowed: bool
    reason: str = ""


def preview_request_allowed(
    *,
    is_admin: bool,
    user_id: str,
    config: Mapping[str, Any] | None = None,
) -> PreviewDecision:
    """Return whether a user may request a full preview."""

    if bool(is_admin):
        return PreviewDecision(True, "admin")
    config = config or {}
    whitelist = config.get("preview_whitelist_users", ())
    if isinstance(whitelist, str):
        whitelist = (whitelist,)
    allowed_ids = {str(value).strip() for value in whitelist if str(value).strip()}
    if str(user_id or "").strip() in allowed_ids:
        return PreviewDecision(True, "whitelist")
    return PreviewDecision(False, "not allowed")


def sanitize_preview_payload(payload: Any) -> dict[str, Any]:
    """Return only safe summary fields; never the raw prompt text."""

    if not isinstance(payload, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key in ("preset_name", "prompt_id", "version", "status", "count"):
        value = payload.get(key)
        if value is not None:
            safe[str(key)] = value
    return safe


__all__ = [
    "PreviewDecision",
    "preview_request_allowed",
    "sanitize_preview_payload",
]
