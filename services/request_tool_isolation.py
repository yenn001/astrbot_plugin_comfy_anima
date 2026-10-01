"""Request-local isolation for tools that can bypass picture delivery.

The input ToolSet is never mutated. The isolated result is a NEW ToolSet;
when isolation cannot prove success the function returns ``None`` and the
caller must block the request.
"""

from collections.abc import Iterable
from typing import Any

from .toolset_snapshot import (
    restrict_toolset_non_mutating,
    snapshot_tool_names,
)

COMPETING_DELIVERY_TOOL_NAMES = frozenset(
    {
        "comfy_anima_generate_for_companion",
        "pc_generate_photo",
        "pc_send_current_media",
        "send_message_to_user",
    }
)


def isolate_picture_delivery_tools(
    tool_set: Any,
    *,
    additional_blocked_names: Iterable[str] = (),
    allowed_names: Iterable[str] | None = None,
) -> Any | None:
    """Return a new non-mutated ToolSet limited to the allow-list.

    ``allowed_names`` is the runtime inventory allow-list and is the only
    production path. Without it the function falls back to denylist removal
    for compatibility tests and never mutates the input.
    """

    if tool_set is None:
        return None
    blocked_names = {
        str(name or "").strip()
        for name in (*COMPETING_DELIVERY_TOOL_NAMES, *additional_blocked_names)
        if str(name or "").strip()
    }
    current_names = snapshot_tool_names(tool_set)
    if not current_names:
        return None
    if allowed_names is not None:
        allowed = {
            str(name or "").strip()
            for name in allowed_names
            if str(name or "").strip()
        }
        allowed_names_tuple = tuple(
            name for name in current_names if name in allowed and name not in blocked_names
        )
    else:
        allowed_names_tuple = tuple(
            name for name in current_names if name not in blocked_names
        )
    if not allowed_names_tuple:
        return None
    return restrict_toolset_non_mutating(tool_set, allowed_names_tuple)


__all__ = [
    "COMPETING_DELIVERY_TOOL_NAMES",
    "isolate_picture_delivery_tools",
]
