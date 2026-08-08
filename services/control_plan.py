"""Typed, bounded control plans for Anima LLLite workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


CONTROL_ORDER: Final[tuple[str, ...]] = ("pose", "depth", "lineart", "reference")
FIDELITY_VALUES: Final[frozenset[str]] = frozenset({"strict", "balanced", "loose"})
CONTENT_VALUES: Final[frozenset[str]] = frozenset({"preserve", "balanced", "free"})
PIPELINE_VALUES: Final[frozenset[str]] = frozenset({"base", "rtx", "iterative"})


class ControlPlanError(ValueError):
    """Raised when a request cannot become a deterministic control plan."""


@dataclass(frozen=True, slots=True)
class ControlChannel:
    mode: str
    source_index: int = 1
    strength: float | None = None
    start_percent: float | None = None
    end_percent: float | None = None
    resize_policy: str = "fit"
    reference_scope: str = "appearance"

    def __post_init__(self) -> None:
        if self.mode not in CONTROL_ORDER:
            raise ControlPlanError(f"unsupported control mode: {self.mode}")
        if self.source_index not in {1, 2}:
            raise ControlPlanError("control source_index must be 1 or 2")
        if self.strength is not None and not 0.0 <= self.strength <= 10.0:
            raise ControlPlanError("control strength must be between 0 and 10")
        start = 0.0 if self.start_percent is None else self.start_percent
        end = 1.0 if self.end_percent is None else self.end_percent
        if not 0.0 <= start <= end <= 1.0:
            raise ControlPlanError("control window must satisfy 0 <= start <= end <= 1")
        if self.resize_policy not in {"fit", "crop", "stretch"}:
            raise ControlPlanError("control resize_policy must be fit, crop or stretch")
        if self.mode != "reference" and self.reference_scope != "appearance":
            raise ControlPlanError("reference_scope only applies to reference control")
        if self.reference_scope not in {"appearance", "style", "color"}:
            raise ControlPlanError("reference_scope must be appearance, style or color")


@dataclass(frozen=True, slots=True)
class ControlPlan:
    channels: tuple[ControlChannel, ...]
    fidelity: str = "balanced"
    content_mode: str = "balanced"
    pipeline: str = "rtx"

    def __post_init__(self) -> None:
        if not self.channels:
            raise ControlPlanError("control plan requires at least one channel")
        if len(self.channels) > len(CONTROL_ORDER):
            raise ControlPlanError("control plan supports at most four channels")
        modes = tuple(channel.mode for channel in self.channels)
        if len(set(modes)) != len(modes):
            raise ControlPlanError("control mode may only appear once")
        if self.fidelity not in FIDELITY_VALUES:
            raise ControlPlanError("fidelity must be strict, balanced or loose")
        if self.content_mode not in CONTENT_VALUES:
            raise ControlPlanError("content_mode must be preserve, balanced or free")
        if self.pipeline not in PIPELINE_VALUES:
            raise ControlPlanError("pipeline must be base, rtx or iterative")

    @property
    def modes(self) -> tuple[str, ...]:
        selected = {channel.mode for channel in self.channels}
        return tuple(mode for mode in CONTROL_ORDER if mode in selected)

    @classmethod
    def from_modes(
        cls,
        modes: tuple[str, ...] | list[str],
        *,
        fidelity: str = "balanced",
        content_mode: str = "balanced",
        pipeline: str = "rtx",
    ) -> "ControlPlan":
        selected = {str(mode or "").strip().casefold() for mode in modes}
        return cls(
            channels=tuple(ControlChannel(mode) for mode in CONTROL_ORDER if mode in selected),
            fidelity=fidelity,
            content_mode=content_mode,
            pipeline=pipeline,
        )


__all__ = [
    "CONTENT_VALUES",
    "CONTROL_ORDER",
    "FIDELITY_VALUES",
    "PIPELINE_VALUES",
    "ControlChannel",
    "ControlPlan",
    "ControlPlanError",
]
