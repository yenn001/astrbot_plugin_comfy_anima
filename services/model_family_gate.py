"""Unified model-family gate for LoRA selection at submission time.

The gate delegates every eligibility decision to
:func:`assess_lora_compatibility`, so native 2.9B assets load on the 2.9B
target and legacy assets stay loader-bound to the Legacy target. A selection
with no catalog record fails closed.
"""

from __future__ import annotations

from typing import Any

from .lora_compatibility import assess_lora_compatibility


class ModelFamilyGateError(RuntimeError):
    """Raised when a selected LoRA is not eligible for the active family."""


class ModelFamilyGate:
    """Verify one LoRA selection against the active target family."""

    def __init__(self, *, target_family: str, patch_verified: bool = False) -> None:
        self._target_family = str(target_family or "").strip().casefold()
        self._patch_verified = bool(patch_verified)

    @property
    def target_family(self) -> str:
        return self._target_family

    def evaluate(self, selection_name: str, record: Any) -> bool:
        """Gate one LoRA selection.

        An absent record is a metadata gap: without a catalog record there is
        no declared family or compatibility mode, so the selection is refused
        instead of being loaded blind.
        """

        if record is None:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: asset metadata missing for "
                f"{selection_name}"
            )
        decision = assess_lora_compatibility(
            record,
            self._target_family,
            patch_verified=self._patch_verified,
        )
        if not decision.eligible:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: {selection_name} "
                f"({decision.reason})"
            )
        return True


def gate_lora_selection(
    selection_name: str,
    record: Any,
    *,
    target_family: str,
    patch_verified: bool,
) -> bool:
    """Compatibility wrapper over the unified gate."""

    return ModelFamilyGate(
        target_family=target_family,
        patch_verified=patch_verified,
    ).evaluate(selection_name, record)


__all__ = [
    "ModelFamilyGate",
    "ModelFamilyGateError",
    "gate_lora_selection",
]