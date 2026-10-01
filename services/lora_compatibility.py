"""Model-family compatibility gates for Anima LoRA assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEGACY_FAMILY = "anima_legacy_28l"
ANIMA_29B_FAMILY = "anima_29b_40l"
COMPATIBILITY_MODES = frozenset(
    {"unknown", "legacy_only", "native_29b", "legacy_projection"}
)


@dataclass(frozen=True)
class LoraCompatibility:
    eligible: bool
    mode: str
    reason: str


def assess_lora_compatibility(
    record: Any,
    target_family: str,
    *,
    patch_verified: bool = False,
) -> LoraCompatibility:
    """Require explicit family metadata before using a LoRA on 2.9B."""
    families = tuple(
        str(item).strip().casefold()
        for item in getattr(record, "compatible_model_families", ()) or ()
        if str(item).strip()
    )
    mode = str(
        getattr(record, "compatibility_mode", "unknown") or "unknown"
    ).strip().casefold()
    if mode not in COMPATIBILITY_MODES:
        return LoraCompatibility(False, "unknown", "invalid_compatibility_mode")
    if target_family == LEGACY_FAMILY:
        if ANIMA_29B_FAMILY in families and LEGACY_FAMILY not in families:
            return LoraCompatibility(False, mode, "anima_29b_only_asset")
        if mode == "native_29b":
            return LoraCompatibility(False, mode, "anima_29b_only_asset")
        return LoraCompatibility(True, mode, "legacy_profile")
    if target_family != ANIMA_29B_FAMILY:
        return LoraCompatibility(False, mode, "unsupported_target_model_family")
    if mode == "native_29b" and ANIMA_29B_FAMILY in families:
        return LoraCompatibility(True, mode, "native_29b_asset")
    if mode == "legacy_projection" and LEGACY_FAMILY in families and patch_verified:
        return LoraCompatibility(True, mode, "verified_legacy_projection")
    if not families:
        return LoraCompatibility(False, "unknown", "asset_family_not_declared")
    return LoraCompatibility(False, mode, "asset_not_compatible_with_2.9b")


__all__ = [
    "ANIMA_29B_FAMILY",
    "COMPATIBILITY_MODES",
    "LEGACY_FAMILY",
    "LoraCompatibility",
    "assess_lora_compatibility",
]
