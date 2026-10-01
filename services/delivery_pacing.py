"""Deterministic delivery pacing for immersive image replies.

No wall-clock guessing: all thresholds come from configuration or monotonic
history records supplied by the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .chat_intent_classifier import (
    INTENT_DRAW_NEW,
    INTENT_EDIT_LAST_IMAGE,
    IntentPlan,
)


@dataclass(frozen=True)
class PacingDecision:
    allow: bool
    max_images: int
    cooldown_seconds: float
    follow_up: bool
    reason: str = ""


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def decide_delivery_pacing(
    plan: IntentPlan,
    *,
    config: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None = None,
    now: float = 0.0,
) -> PacingDecision:
    """Return the deterministic pacing decision for one visual delivery."""

    config = config or {}
    history = history or {}
    max_images = _as_int(config.get("max_auto_images_per_reply"), 1, 1, 4)
    cooldown_seconds = max(
        0.0, _as_float(config.get("delivery_cooldown_seconds"), 8.0)
    )

    if plan.intent not in {INTENT_DRAW_NEW, INTENT_EDIT_LAST_IMAGE}:
        return PacingDecision(
            allow=False,
            max_images=max_images,
            cooldown_seconds=cooldown_seconds,
            follow_up=False,
            reason="intent does not allow visual delivery",
        )

    last_delivery_at = _as_float(history.get("last_delivery_at"), 0.0)
    in_flight = int(history.get("in_flight") or 0)
    if in_flight > 0:
        return PacingDecision(
            allow=False,
            max_images=max_images,
            cooldown_seconds=cooldown_seconds,
            follow_up=False,
            reason="previous delivery still in flight",
        )
    if now and last_delivery_at and now - last_delivery_at < cooldown_seconds:
        return PacingDecision(
            allow=False,
            max_images=max_images,
            cooldown_seconds=cooldown_seconds,
            follow_up=False,
            reason="delivery cooldown not elapsed",
        )

    follow_up = bool(history.get("pending_follow_up"))
    return PacingDecision(
        allow=True,
        max_images=max_images,
        cooldown_seconds=cooldown_seconds,
        follow_up=follow_up,
        reason="pacing allows visual delivery",
    )


def build_follow_up_text(history: Mapping[str, Any] | None = None) -> str:
    """Return a neutral follow-up line; never claims delivery succeeded."""

    history = history or {}
    pending = str(history.get("pending_follow_up") or "").strip()
    return pending or ""


__all__ = ["PacingDecision", "build_follow_up_text", "decide_delivery_pacing"]
