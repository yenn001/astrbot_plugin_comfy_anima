"""Read-only ToolSet snapshot helpers for deterministic intent plans.

These helpers never mutate the input ToolSet; they build a new ToolSet (or
return ``None`` when the allowed subset is empty) so runtime isolation stays
request-local.
"""

from __future__ import annotations

from typing import Any, Iterable


def snapshot_tool_names(tool_set: Any) -> tuple[str, ...]:
    """Return the ordered tool names of a ToolSet without touching it."""

    getter = getattr(tool_set, "names", None)
    if callable(getter):
        try:
            return tuple(str(name) for name in getter())
        except Exception:
            pass
    tools = getattr(tool_set, "tools", None)
    if isinstance(tools, (list, tuple)):
        return tuple(
            str(getattr(tool, "name", "") or "") for tool in tools
        )
    return ()


def restrict_toolset_non_mutating(
    tool_set: Any,
    allowed_names: Iterable[str],
) -> Any | None:
    """Return a NEW ToolSet limited to ``allowed_names``; never mutate input."""

    allowed = {str(name).strip() for name in allowed_names if str(name).strip()}
    tools = getattr(tool_set, "tools", None)
    if not isinstance(tools, (list, tuple)) or not allowed:
        return None
    kept = [
        tool
        for tool in tools
        if str(getattr(tool, "name", "") or "") in allowed
    ]
    if not kept:
        return None
    try:
        from astrbot.core.agent.tool import ToolSet

        return ToolSet(kept)
    except Exception:
        return None


__all__ = ["restrict_toolset_non_mutating", "snapshot_tool_names"]
