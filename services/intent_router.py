"""Independent ordinary-chat intent routing contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


INTENT_VALUES = frozenset(
    {"draw_new", "edit_last_image", "query_only", "debug_only", "clarify"}
)


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    visual_delivery: bool
    needs_previous_image: bool
    confidence: float
    rationale: str = ""
    source: str = "router"


class IntentRouterError(ValueError):
    """Raised when the independent router does not return its contract."""


def _json_object(text: str) -> Mapping[str, Any]:
    source = str(text or "").strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.I | re.S)
    try:
        value = json.loads(source)
    except (TypeError, ValueError) as exc:
        raise IntentRouterError("intent router returned invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise IntentRouterError("intent router result must be an object")
    return value


def parse_intent_decision(text: str) -> IntentDecision:
    value = _json_object(text)
    intent = str(value.get("intent") or "").strip().casefold()
    if intent not in INTENT_VALUES:
        raise IntentRouterError(f"unsupported intent: {intent or '<empty>'}")
    visual_delivery = value.get("visual_delivery")
    if not isinstance(visual_delivery, bool):
        raise IntentRouterError("visual_delivery must be boolean")
    previous = value.get("needs_previous_image", False)
    if not isinstance(previous, bool):
        raise IntentRouterError("needs_previous_image must be boolean")
    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise IntentRouterError("confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise IntentRouterError("confidence must be between 0 and 1")
    rationale = str(value.get("rationale") or "").strip()[:240]
    return IntentDecision(
        intent=intent,
        visual_delivery=visual_delivery,
        needs_previous_image=previous,
        confidence=confidence,
        rationale=rationale,
    )


def apply_confidence_gate(
    decision: IntentDecision,
    *,
    min_confidence: float,
) -> IntentDecision:
    """Downgrade a low-confidence router decision to clarify.

    Drawing has an asymmetric cost: a wrong picture wastes a GPU job and
    breaks the character identity, while asking the user costs one reply.
    """

    threshold = max(0.0, min(1.0, float(min_confidence or 0.7)))
    if decision.confidence >= threshold:
        return decision
    return IntentDecision(
        intent="clarify",
        visual_delivery=False,
        needs_previous_image=decision.needs_previous_image,
        confidence=decision.confidence,
        rationale=(
            f"router confidence {decision.confidence:.2f} is below "
            f"threshold {threshold:.2f}"
        ),
        source="router-confidence-gate",
    )


def build_intent_router_prompts(*, message: str, tool_names: list[str], evidence: list[Mapping[str, Any]]) -> tuple[str, str]:
    system = (
        "You are the independent ComfyAnima intent router. You are not the drawing director, "
        "not the image reverse model, and never submit tools. Return one JSON object only with "
        "intent (draw_new|edit_last_image|query_only|debug_only|clarify), visual_delivery (boolean), "
        "needs_previous_image (boolean), confidence (0..1), and optional rationale. "
        "If the latest user message asks about logs, errors, status, or why something failed, "
        "ALWAYS return intent=debug_only and visual_delivery=false. Never draw to compensate "
        "for a previous failure. Classify the user's latest message, using tool evidence "
        "only as context."
    )
    user = json.dumps(
        {
            "latest_user_message": str(message or "").strip(),
            "completed_asset_tools": list(tool_names),
            "bounded_tool_evidence": list(evidence)[-6:],
        },
        ensure_ascii=False,
    )
    return system, user
