"""Unified model-family gate for LoRA selection at submission time.

2.4.0 defers every 2.9B executable path: native/projected 2.9B assets are
rejected on every target and a 2.9B target is rejected outright.
"""

from __future__ import annotations

from typing import Any

from .lora_compatibility import (
    ANIMA_29B_FAMILY,
    LEGACY_FAMILY,
    assess_lora_compatibility,
)

RESTRICTED_FAMILY = ANIMA_29B_FAMILY


class ModelFamilyGateError(RuntimeError):
    """Raised when a selected LoRA is not eligible for the active family."""


class ModelFamilyGate:
    """Unified model-family gate with a 2.9B deferred-scope invariant."""

    def __init__(self, *, target_family: str, patch_verified: bool = False) -> None:
        self._target_family = str(target_family or "").strip().casefold()
        self._patch_verified = bool(patch_verified)

    @property
    def target_family(self) -> str:
        return self._target_family

    @property
    def restricted_29b(self) -> bool:
        return self._target_family == RESTRICTED_FAMILY

    def evaluate(self, selection_name: str, record: Any) -> bool:
        """Gate one LoRA.

        2.9B assets and 2.9B targets are deferred. A Legacy target treats
        an unclassified manager asset as legacy_only, because 2.9B assets
        must explicitly declare their family; unknown cannot silently become
        2.9B.
        """

        if record is None:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: asset metadata missing for "
                f"{selection_name}"
            )
        families = {
            str(item).strip().casefold()
            for item in getattr(record, "compatible_model_families", ()) or ()
            if str(item).strip()
        }
        mode = str(
            getattr(record, "compatibility_mode", "unknown") or "unknown"
        ).strip().casefold()
        if ANIMA_29B_FAMILY in families or mode in {
            "native_29b",
            "legacy_projection",
        }:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: 2.9B asset is deferred in 2.4.0 "
                f"({selection_name})"
            )
        if self.restricted_29b:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: 2.9B target family is deferred "
                f"in 2.4.0 ({selection_name})"
            )
        if mode == "unknown" or not families:
            if self._target_family == LEGACY_FAMILY:
                return True
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: unknown asset family for "
                f"{selection_name}"
            )
        decision = assess_lora_compatibility(
            record,
            self._target_family,
            patch_verified=self._patch_verified,
        )
        if not decision.eligible:
            raise ModelFamilyGateError(
                f"LoRA compatibility rejected: {selection_name} ({decision.reason})"
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
    "RESTRICTED_FAMILY",
    "gate_lora_selection",
]
