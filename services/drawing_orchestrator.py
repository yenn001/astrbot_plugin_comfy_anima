"""Stage 1 unified drawing orchestrator for ComfyAnima 2.1.306.

The orchestrator is the single owner of per-event drawing execution facts:

- exactly one state per AstrBot event;
- exactly one submission per event (duplicate submissions raise);
- one run id allocated idempotently and passed to the task store;
- terminal phases are immutable, so legacy hooks can only observe.

It also owns follow-up notice detection: during an active agent run AstrBot
injects new user messages as ``[SYSTEM NOTICE] User sent follow-up messages
while tool execution was in progress.`` blocks merged into the next LLM
request. Those messages never produce a fresh ``on_llm_request``, so the
orchestrator scans the merged prompt to keep drawing intents inside the
controlled chain.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .chat_intent_classifier import (
    INTENT_DEBUG_ONLY,
    ChatIntentDecision,
    classify_chat_intent,
)
from .drawing_state_machine import (
    DrawingPhase,
    DrawingRunRegistry,
    DrawingRunState,
    DuplicateSubmissionError,
)

FOLLOW_UP_NOTICE_MARKER = (
    "[SYSTEM NOTICE] User sent follow-up messages while tool execution "
    "was in progress."
)

# Blueprint 3.4: drawing requests expose only drawing tools. Competing delivery
# tools and host-execution tools are rejected at the request stage (allowlist
# replacement) and observed again at execution time (fail-closed trace).
BLOCKED_EXECUTION_TOOL_NAMES = frozenset(
    {
        "send_message_to_user",
        "comfy_anima_generate_for_companion",
        "pc_generate_photo",
        "pc_send_current_media",
        "astrbot_execute_shell",
        "astrbot_shell_session",
        "astrbot_execute_python",
        "astrbot_file_read_tool",
        "astrbot_file_write_tool",
        "astrbot_file_edit_tool",
        "astrbot_grep_tool",
    }
)

_FOLLOW_UP_LINE_RE = re.compile(
    r"^\s*\d+\s*[.)]\s*(?P<text>.+?)\s*$",
    flags=re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class FollowUpDrawDetection:
    """A drawing intent found inside one follow-up notice block."""

    text: str
    intent: str
    visual_delivery: bool
    confidence: float
    source: str


def extract_follow_up_lines(prompt: str) -> list[str]:
    """Extract the numbered follow-up lines from a merged LLM prompt.

    AstrBot 4.27.4 merges pending follow-up tickets into the active run's
    next request with ``FOLLOW_UP_NOTICE_TEMPLATE``; the numbered lines are
    the exact user messages. Returns [] when no notice block is present.
    """

    source = str(prompt or "")
    marker_index = source.find(FOLLOW_UP_NOTICE_MARKER)
    if marker_index < 0:
        return []
    tail = source[marker_index + len(FOLLOW_UP_NOTICE_MARKER) :]
    return [
        match.group("text").strip()
        for match in _FOLLOW_UP_LINE_RE.finditer(tail)
        if match.group("text").strip()
    ]


def detect_follow_up_draw_requests(
    prompt: str,
    *,
    has_recipe: bool = False,
    strict: bool = False,
) -> tuple[list[FollowUpDrawDetection], bool]:
    """Classify follow-up lines and return drawing detections.

    The second return value is True when a debug/log query appears among the
    follow-up lines. Debug intent always outranks drawing in the deterministic
    classifier; callers use the flag to fail closed without touching ComfyUI.
    """

    detections: list[FollowUpDrawDetection] = []
    has_debug_query = False
    for line in extract_follow_up_lines(prompt):
        decision: ChatIntentDecision = classify_chat_intent(
            line,
            has_recipe=has_recipe,
            strict=strict,
        )
        if decision.intent == INTENT_DEBUG_ONLY:
            has_debug_query = True
        if decision.visual_delivery:
            detections.append(
                FollowUpDrawDetection(
                    text=line,
                    intent=decision.intent,
                    visual_delivery=True,
                    confidence=decision.confidence,
                    source="follow_up_notice",
                )
            )
    return detections, has_debug_query


class DrawingOrchestrator:
    """Per-event drawing execution owner for Stage 1."""

    def __init__(
        self,
        *,
        registry: Optional[DrawingRunRegistry] = None,
        run_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.registry = registry or DrawingRunRegistry()
        self.run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)

    # -- ownership ---------------------------------------------------------

    def claim(self, event: Any) -> DrawingRunState:
        return self.registry.claim(event)

    def state(self, event: Any) -> Optional[DrawingRunState]:
        return self.registry.get(event)

    def forget(self, event: Any) -> None:
        self.registry.forget(event)

    def clear(self) -> None:
        self.registry.clear()

    # -- UMO-level active drawing sessions (Stage 2) -----------------------

    def begin_umo_drawing(self, umo: str) -> None:
        self.registry.begin_umo_drawing(umo)

    def end_umo_drawing(self, umo: str) -> None:
        self.registry.end_umo_drawing(umo)

    def is_umo_drawing(self, umo: str) -> bool:
        return self.registry.is_umo_drawing(umo)

    def has_any_umo_drawing(self) -> bool:
        return self.registry.has_any_umo_drawing()

    # -- submission --------------------------------------------------------

    def allocate_run_id(self, event: Any) -> str:
        """Allocate the single run id for an event (idempotent)."""

        state = self.claim(event)
        return state.allocate_run_id(self.run_id_factory)

    def begin_submission(
        self,
        event: Any,
        *,
        detail: str = "",
    ) -> DrawingRunState:
        """Move the event's run into SUBMITTING exactly once.

        Raises DuplicateSubmissionError when any submission for this event
        already exists. This is the single choke point that makes legacy
        re-entry unable to create a second run.
        """

        state = self.claim(event)
        if state.submission_count > 0:
            raise DuplicateSubmissionError(
                f"event {state.ownership_key} already submitted "
                f"(run_id={state.run_id or 'pending'}, "
                f"phase={state.phase.value})"
            )
        if state.is_terminal:
            raise DuplicateSubmissionError(
                f"event {state.ownership_key} is terminal "
                f"(phase={state.phase.value}); submission refused"
            )
        state.submission_count += 1
        state.allocate_run_id(self.run_id_factory)
        state.transition(DrawingPhase.SUBMITTING, detail=detail)
        return state

    # -- phase transitions -------------------------------------------------

    def mark_running(self, event: Any, run_id: str) -> None:
        state = self.state(event)
        if state is None or not run_id:
            return
        if state.run_id and state.run_id != run_id:
            return
        if state.phase == DrawingPhase.SUBMITTING:
            state.transition(DrawingPhase.RUNNING)

    def mark_completed(self, event: Any, run_id: str) -> None:
        state = self.state(event)
        if state is None or not run_id:
            return
        if state.run_id and state.run_id != run_id:
            return
        if state.phase in {DrawingPhase.SUBMITTING, DrawingPhase.RUNNING}:
            state.transition(DrawingPhase.COMPLETED)

    def mark_delivered(self, event: Any, run_id: str) -> None:
        state = self.state(event)
        if state is None or not run_id:
            return
        if state.run_id and state.run_id != run_id:
            return
        if state.phase in {
            DrawingPhase.SUBMITTING,
            DrawingPhase.RUNNING,
            DrawingPhase.COMPLETED,
        }:
            state.transition(DrawingPhase.DELIVERY)

    def mark_failed(self, event: Any, run_id: str, *, detail: str = "") -> None:
        state = self.state(event)
        if state is None or not run_id:
            return
        if state.run_id and state.run_id != run_id:
            return
        if not state.is_terminal:
            state.transition(DrawingPhase.FAILED, detail=detail)

    def request_cancel(self, event: Any) -> None:
        state = self.state(event)
        if state is not None:
            state.request_cancel()

    # -- legacy hook mutex -------------------------------------------------

    def legacy_submission_allowed(self, event: Any) -> bool:
        """Return whether an old hook may still create a submission.

        Old ``on_decorating_result`` / ``on_agent_done`` handlers must call
        this before any repair or picture-terminal handling. Once the event's
        run is terminal, they may only observe.
        """

        state = self.state(event)
        if state is None:
            return True
        return not state.is_terminal

    # -- diagnostics -------------------------------------------------------

    def snapshot(self, event: Any) -> dict[str, Any]:
        state = self.state(event)
        if state is None:
            return {"claimed": False}
        return {
            "claimed": True,
            "ownership_key": state.ownership_key,
            "phase": state.phase.value,
            "run_id": state.run_id,
            "submission_count": state.submission_count,
            "cancel_requested": state.cancel_requested,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "detail": state.detail,
        }

    @staticmethod
    def bounded_event_snapshot(event: Any) -> dict[str, Any]:
        """Small stable event facts for diagnostics (never raw prompts)."""

        session_id = ""
        sender_id = ""
        for attribute, getter_name in (
            ("session_id", "get_session_id"),
            ("sender_id", "get_sender_id"),
        ):
            getter = getattr(event, getter_name, None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:
                    value = getattr(event, attribute, "")
            else:
                value = getattr(event, attribute, "")
            if attribute == "session_id":
                session_id = str(value or "")
            else:
                sender_id = str(value or "")
        return {
            "session_id": session_id,
            "sender_id": sender_id,
            "wall_time": time.time(),
        }
