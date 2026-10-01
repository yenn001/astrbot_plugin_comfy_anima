"""Tests for the 2.1.306 Stage 1 drawing state machine and orchestrator."""

from __future__ import annotations

import pytest

from ..services.drawing_orchestrator import (
    FOLLOW_UP_NOTICE_MARKER,
    DrawingOrchestrator,
    detect_follow_up_draw_requests,
    extract_follow_up_lines,
)
from ..services.drawing_state_machine import (
    DrawingPhase,
    DrawingRunRegistry,
    DrawingRunState,
    DrawingStateError,
    DuplicateSubmissionError,
)


class FakeEvent:
    def __init__(self, session_id: str = "s1", sender_id: str = "u1") -> None:
        self.session_id = session_id
        self.sender_id = sender_id

    def get_session_id(self) -> str:
        return self.session_id

    def get_sender_id(self) -> str:
        return self.sender_id


def test_state_machine_allowed_lifecycle() -> None:
    state = DrawingRunState(ownership_key="k")
    state.allocate_run_id(lambda: "run-1")
    state.transition(DrawingPhase.SUBMITTING)
    state.transition(DrawingPhase.RUNNING)
    state.transition(DrawingPhase.COMPLETED)
    state.transition(DrawingPhase.DELIVERY)
    assert state.run_id == "run-1"
    assert state.is_terminal


def test_state_machine_rejects_illegal_transition() -> None:
    state = DrawingRunState(ownership_key="k")
    with pytest.raises(DrawingStateError):
        state.transition(DrawingPhase.DELIVERY)


def test_state_machine_terminal_is_immutable() -> None:
    state = DrawingRunState(ownership_key="k")
    state.transition(DrawingPhase.QUEUED)
    state.transition(DrawingPhase.FAILED)
    for target in DrawingPhase:
        if target == state.phase:
            continue
        with pytest.raises(DrawingStateError):
            state.transition(target)


def test_state_machine_cancel_only_before_completion() -> None:
    queued = DrawingRunState(ownership_key="q")
    queued.request_cancel()
    assert queued.phase == DrawingPhase.CANCELLED

    running = DrawingRunState(ownership_key="r")
    running.transition(DrawingPhase.SUBMITTING)
    running.transition(DrawingPhase.RUNNING)
    running.request_cancel()
    assert running.phase == DrawingPhase.CANCELLED

    delivered = DrawingRunState(ownership_key="d")
    delivered.transition(DrawingPhase.SUBMITTING)
    delivered.transition(DrawingPhase.RUNNING)
    delivered.transition(DrawingPhase.COMPLETED)
    delivered.transition(DrawingPhase.DELIVERY)
    delivered.request_cancel()
    assert delivered.phase == DrawingPhase.DELIVERY


def test_run_id_allocated_exactly_once() -> None:
    calls: list[str] = []

    def factory() -> str:
        calls.append("f")
        return "run-x"

    state = DrawingRunState(ownership_key="k")
    assert state.allocate_run_id(factory) == "run-x"
    assert state.allocate_run_id(factory) == "run-x"
    assert calls == ["f"]


def test_registry_one_state_per_event_and_session_isolation() -> None:
    registry = DrawingRunRegistry()
    first = FakeEvent("s1", "u1")
    same = registry.claim(first)
    assert registry.claim(first) is same
    assert len(registry) == 1

    other_session = FakeEvent("s2", "u1")
    assert registry.claim(other_session) is not same
    assert len(registry) == 2

    other_sender = FakeEvent("s2", "u2")
    assert registry.claim(other_sender) is not same
    assert len(registry) == 3

    registry.forget(first)
    assert registry.get(first) is None


def test_orchestrator_duplicate_submission_rejected() -> None:
    orchestrator = DrawingOrchestrator(run_id_factory=lambda: "run-1")
    event = FakeEvent()
    state = orchestrator.begin_submission(event)
    assert state.run_id == "run-1"
    assert state.submission_count == 1
    assert state.phase == DrawingPhase.SUBMITTING
    with pytest.raises(DuplicateSubmissionError):
        orchestrator.begin_submission(event)


def test_orchestrator_terminal_blocks_submission() -> None:
    orchestrator = DrawingOrchestrator(run_id_factory=lambda: "run-1")
    event = FakeEvent()
    state = orchestrator.begin_submission(event)
    state.transition(DrawingPhase.FAILED)
    with pytest.raises(DuplicateSubmissionError):
        orchestrator.begin_submission(event)
    assert orchestrator.legacy_submission_allowed(event) is False


def test_orchestrator_run_id_allocation_idempotent_before_submission() -> None:
    orchestrator = DrawingOrchestrator(run_id_factory=lambda: "run-a")
    event = FakeEvent()
    assert orchestrator.allocate_run_id(event) == "run-a"
    assert orchestrator.allocate_run_id(event) == "run-a"
    state = orchestrator.begin_submission(event)
    assert state.run_id == "run-a"


def test_orchestrator_phase_markers_ignore_run_id_mismatch() -> None:
    orchestrator = DrawingOrchestrator(run_id_factory=lambda: "run-a")
    event = FakeEvent()
    orchestrator.begin_submission(event)
    orchestrator.mark_running(event, "run-other")
    assert orchestrator.state(event).phase == DrawingPhase.SUBMITTING
    orchestrator.mark_running(event, "run-a")
    orchestrator.mark_completed(event, "run-a")
    orchestrator.mark_delivered(event, "run-a")
    assert orchestrator.state(event).phase == DrawingPhase.DELIVERY


def test_orchestrator_forget_releases_event() -> None:
    orchestrator = DrawingOrchestrator()
    event = FakeEvent()
    orchestrator.begin_submission(event)
    orchestrator.forget(event)
    assert orchestrator.state(event) is None
    # A new submission for a forgotten event is allowed again.
    orchestrator.begin_submission(event)
    assert orchestrator.state(event).submission_count == 1


def test_follow_up_lines_extraction() -> None:
    prompt = (
        f"{FOLLOW_UP_NOTICE_MARKER}\n"
        "1. 我想看你在干嘛\n"
        "2. 画一张达妮娅自拍\n"
        "3. 检查一下日志看看怎么回事"
    )
    assert extract_follow_up_lines(prompt) == [
        "我想看你在干嘛",
        "画一张达妮娅自拍",
        "检查一下日志看看怎么回事",
    ]
    assert extract_follow_up_lines("普通消息，没有 notice") == []


def test_follow_up_detection_drawing_and_debug() -> None:
    prompt = (
        f"{FOLLOW_UP_NOTICE_MARKER}\n"
        "1. 画一张达妮娅自拍\n"
        "2. 检查一下日志看看怎么回事"
    )
    detections, has_debug = detect_follow_up_draw_requests(prompt)
    assert has_debug is True
    assert [item.text for item in detections] == ["画一张达妮娅自拍"]
    assert detections[0].visual_delivery is True
    assert detections[0].source == "follow_up_notice"


def test_umo_drawing_session_markers() -> None:
    orchestrator = DrawingOrchestrator()
    umo = "Bot:FriendMessage:719397082"
    assert orchestrator.is_umo_drawing(umo) is False
    orchestrator.begin_umo_drawing(umo)
    assert orchestrator.is_umo_drawing(umo) is True
    orchestrator.end_umo_drawing(umo)
    assert orchestrator.is_umo_drawing(umo) is False


def test_any_umo_drawing_flag() -> None:
    orchestrator = DrawingOrchestrator()
    assert orchestrator.has_any_umo_drawing() is False
    orchestrator.begin_umo_drawing("other-session")
    assert orchestrator.has_any_umo_drawing() is True
    orchestrator.clear()
    assert orchestrator.has_any_umo_drawing() is False


def test_nested_umo_drawing_begin_end_keeps_outer_session() -> None:
    orchestrator = DrawingOrchestrator()
    umo = "Bot:FriendMessage:719397082"
    orchestrator.begin_umo_drawing(umo)
    # A non-drawing filter probe enters and leaves the same keys.
    orchestrator.begin_umo_drawing(umo)
    orchestrator.end_umo_drawing(umo)
    assert orchestrator.is_umo_drawing(umo) is True
    orchestrator.end_umo_drawing(umo)
    assert orchestrator.is_umo_drawing(umo) is False


def test_follow_up_detection_no_drawing() -> None:
    prompt = f"{FOLLOW_UP_NOTICE_MARKER}\n1. 我想看你在干嘛"
    detections, has_debug = detect_follow_up_draw_requests(prompt)
    assert detections == []
    assert has_debug is True
