"""Stage 1 call-chain state machine for ComfyAnima 2.1.306.

A drawing run belongs to exactly one AstrBot event and moves through a strict
phase sequence. Terminal phases are immutable: once a run reaches delivery,
failed or cancelled, no hook may submit again and no state may be re-opened.

Blueprint references:
- Section 3.3 (hard invariants: one orchestrator per event)
- Section 10 (new/old path mutex)
- Section 11 (cancel / reload / terminate state machine)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class DrawingPhase(str, Enum):
    QUEUED = "queued"
    SUBMITTING = "submitting"
    RUNNING = "running"
    COMPLETED = "completed"
    DELIVERY = "delivery"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DrawingStateError(RuntimeError):
    """Raised when a drawing run attempts an illegal phase transition."""


class DuplicateSubmissionError(DrawingStateError):
    """Raised when a second submission is attempted for one event."""


_ALLOWED_TRANSITIONS: dict[DrawingPhase, frozenset[DrawingPhase]] = {
    DrawingPhase.QUEUED: frozenset(
        {
            DrawingPhase.SUBMITTING,
            DrawingPhase.CANCELLED,
            DrawingPhase.FAILED,
        }
    ),
    DrawingPhase.SUBMITTING: frozenset(
        {
            DrawingPhase.RUNNING,
            DrawingPhase.CANCELLED,
            DrawingPhase.FAILED,
        }
    ),
    DrawingPhase.RUNNING: frozenset(
        {
            DrawingPhase.COMPLETED,
            DrawingPhase.CANCELLED,
            DrawingPhase.FAILED,
        }
    ),
    DrawingPhase.COMPLETED: frozenset(
        {
            DrawingPhase.DELIVERY,
            DrawingPhase.FAILED,
        }
    ),
    DrawingPhase.DELIVERY: frozenset(),
    DrawingPhase.CANCELLED: frozenset(),
    DrawingPhase.FAILED: frozenset(),
}

_TERMINAL_PHASES = frozenset(
    {
        DrawingPhase.DELIVERY,
        DrawingPhase.CANCELLED,
        DrawingPhase.FAILED,
    }
)

_CANCELLABLE_PHASES = frozenset(
    {
        DrawingPhase.QUEUED,
        DrawingPhase.SUBMITTING,
        DrawingPhase.RUNNING,
    }
)


def default_event_ownership_key(event: Any) -> str:
    """Build a stable ownership key for one live AstrBot event.

    ``id(event)`` matches the legacy per-event trace keys already used by the
    plugin. It is only valid while the event object is alive, which is exactly
    the lifetime the registry tracks. Session and sender are included so a
    recycled id cannot collide across sessions.
    """

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
    return f"{id(event)}:{session_id}:{sender_id}"


@dataclass(slots=True)
class DrawingRunState:
    """One event-scoped drawing run."""

    ownership_key: str
    phase: DrawingPhase = DrawingPhase.QUEUED
    run_id: str = ""
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    cancel_requested: bool = False
    submission_count: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        self.created_at = time.monotonic()
        self.updated_at = self.created_at

    @property
    def is_terminal(self) -> bool:
        return self.phase in _TERMINAL_PHASES

    @property
    def has_run_id(self) -> bool:
        return bool(self.run_id)

    def allocate_run_id(
        self,
        factory: Optional[Callable[[], str]] = None,
    ) -> str:
        """Allocate the run id exactly once for this event."""

        if not self.run_id:
            generator = factory or (lambda: uuid.uuid4().hex)
            self.run_id = str(generator() or "").strip() or uuid.uuid4().hex
        return self.run_id

    def transition(
        self,
        target: DrawingPhase,
        *,
        detail: str = "",
    ) -> None:
        if self.phase == target:
            return
        if target not in _ALLOWED_TRANSITIONS.get(self.phase, frozenset()):
            raise DrawingStateError(
                f"illegal drawing run transition: {self.phase.value} -> {target.value}"
            )
        self.phase = target
        self.updated_at = time.monotonic()
        if detail:
            self.detail = str(detail)[:200]

    def request_cancel(self) -> None:
        """Apply the blueprint cancel semantics for the current phase."""

        if self.phase not in _CANCELLABLE_PHASES:
            return
        self.cancel_requested = True
        self.transition(DrawingPhase.CANCELLED, detail="user requested cancel")


class DrawingRunRegistry:
    """Process-local registry enforcing one orchestrator per event.

    The plugin runs inside one AstrBot process and all hook handlers execute on
    the same event loop, so a plain dict with a small monotonic prune is
    sufficient; no cross-thread lock is required.
    """

    def __init__(self, *, capacity: int = 512) -> None:
        self._runs: dict[str, DrawingRunState] = {}
        self._umo_drawing_sessions: dict[str, int] = {}
        self._capacity = max(16, int(capacity))

    def __len__(self) -> int:
        return len(self._runs)

    # -- UMO-level active drawing sessions (Stage 2) -----------------------

    def begin_umo_drawing(self, umo: str) -> None:
        key = str(umo or "").strip()
        if not key:
            return
        # Reference counting: the filter handler also probes non-drawing
        # messages with the same event keys, so nested begin/end must not
        # clear a session owned by an outer drawing run.
        self._umo_drawing_sessions[key] = self._umo_drawing_sessions.get(key, 0) + 1
        self._prune_umo_locked()

    def end_umo_drawing(self, umo: str) -> None:
        key = str(umo or "").strip()
        count = self._umo_drawing_sessions.get(key, 0)
        if count <= 1:
            self._umo_drawing_sessions.pop(key, None)
        else:
            self._umo_drawing_sessions[key] = count - 1

    def is_umo_drawing(self, umo: str) -> bool:
        return self._umo_drawing_sessions.get(str(umo or "").strip(), 0) > 0

    def has_any_umo_drawing(self) -> bool:
        return bool(self._umo_drawing_sessions)

    def _prune_umo_locked(self) -> None:
        if len(self._umo_drawing_sessions) <= self._capacity:
            return
        # Remove the oldest entries (dict preserves insertion order).
        overflow = len(self._umo_drawing_sessions) - self._capacity
        for key in list(self._umo_drawing_sessions)[:overflow]:
            self._umo_drawing_sessions.pop(key, None)

    # -- event runs --------------------------------------------------------

    def _prune_locked(self) -> None:
        if len(self._runs) <= self._capacity:
            return
        stale = sorted(
            self._runs.items(),
            key=lambda item: item[1].updated_at,
        )
        for key, _state in stale[: len(self._runs) - self._capacity]:
            self._runs.pop(key, None)

    def claim(
        self,
        event: Any,
        *,
        key: Optional[str] = None,
    ) -> DrawingRunState:
        """Return the single state for an event, creating it on first use."""

        ownership_key = key or default_event_ownership_key(event)
        existing = self._runs.get(ownership_key)
        if existing is not None:
            return existing
        self._prune_locked()
        state = DrawingRunState(ownership_key=ownership_key)
        self._runs[ownership_key] = state
        return state

    def get(
        self,
        event: Any,
        *,
        key: Optional[str] = None,
    ) -> Optional[DrawingRunState]:
        ownership_key = key or default_event_ownership_key(event)
        return self._runs.get(ownership_key)

    def forget(self, event: Any, *, key: Optional[str] = None) -> None:
        ownership_key = key or default_event_ownership_key(event)
        self._runs.pop(ownership_key, None)

    def clear(self) -> None:
        self._runs.clear()
        self._umo_drawing_sessions.clear()

    def states(self) -> list[DrawingRunState]:
        return list(self._runs.values())
