"""Deterministic fail-closed gate for projected character LoRA views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .character_lora_projection import CharacterLoraPresetView

_RANK = {"ready": 0, "needs_review": 1, "missing_asset": 2, "revision_changed": 3, "ambiguous": 4, "conflict": 5}


@dataclass(frozen=True)
class CharacterLoraGateResult:
    eligible: bool
    health: str
    views: tuple[CharacterLoraPresetView, ...]
    warnings: tuple[str, ...] = ()


def _worst(states: Iterable[str]) -> str:
    return max(states, key=lambda state: _RANK.get(state, 5), default="ready")


def gate_character_lora_views(views: Iterable[CharacterLoraPresetView], *, current_asset_revision: str = "") -> CharacterLoraGateResult:
    ordered = tuple(sorted(tuple(views), key=lambda row: (row.authority_kind, row.identity_ref, row.variant_id, row.asset_key)))
    if not ordered:
        return CharacterLoraGateResult(False, "missing_asset", (), ("no_character_lora_view",))
    warnings: list[str] = []
    kinds = {row.authority_kind for row in ordered}
    if len(kinds) > 1 or "conflict" in kinds:
        warnings.append("public_private_authority_conflict")
    if len({row.identity_ref for row in ordered}) != len(ordered):
        warnings.append("duplicate_identity_ref")
    revisions = {row.asset_revision for row in ordered if row.asset_revision}
    if len(revisions) > 1 or (current_asset_revision and any(row.asset_revision != current_asset_revision for row in ordered)):
        warnings.append("asset_revision_mismatch")
    by_name: dict[str, set[str]] = {}
    by_sha: dict[str, set[str]] = {}
    for row in ordered:
        if row.asset_key:
            by_name.setdefault(row.asset_key, set()).add(row.asset_revision)
        if row.asset_revision:
            by_sha.setdefault(row.asset_revision, set()).add(row.asset_key)
    if any(len(revs) > 1 for revs in by_name.values()):
        warnings.append("same_name_multiple_assets")
    if any(len(names) > 1 for names in by_sha.values()):
        warnings.append("duplicate_sha")
    groups: dict[str, list[CharacterLoraPresetView]] = {}
    for row in ordered:
        groups.setdefault(row.character_canonical or row.identity_ref, []).append(row)
    for rows in groups.values():
        if sum(row.default_for_identity for row in rows) != 1:
            warnings.append("default_variant_not_unique")
        if len(rows) > 1 and any(not row.activation_terms for row in rows):
            warnings.append("activation_required_for_variant")
    warnings.extend(warning for row in ordered for warning in row.warnings)
    warnings = list(dict.fromkeys(warnings))
    states = [row.health for row in ordered]
    if any(item in warnings for item in ("public_private_authority_conflict", "same_name_multiple_assets", "duplicate_sha")):
        states.append("conflict")
    if any(item in warnings for item in ("duplicate_identity_ref", "default_variant_not_unique", "activation_required_for_variant")):
        states.append("ambiguous")
    if "asset_revision_mismatch" in warnings:
        states.append("revision_changed")
    health = _worst(states)
    return CharacterLoraGateResult(health == "ready", health, ordered, tuple(warnings))


__all__ = ["CharacterLoraGateResult", "gate_character_lora_views"]
