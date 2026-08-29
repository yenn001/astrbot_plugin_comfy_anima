"""Pure validation for reviewed character-LoRA records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .lora_catalog import LoraRecord


_SHA = re.compile(r"^[0-9a-f]{64}$")
_VARIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_FORBIDDEN = re.compile(r"<lora\s*:|https?://|[\\/]|\.(?:safetensors|ckpt|pt|bin)$", re.I)


@dataclass(frozen=True)
class CharacterLoraValidation:
    valid: bool
    health: str
    normalized: dict[str, Any]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _terms(value: Any, *, limit: int = 48) -> tuple[str, ...]:
    if isinstance(value, str):
        value = re.split(r"[\n,;，；]+", value)
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:limit]


def validate_character_lora_payload(
    payload: Mapping[str, Any],
    records: Iterable[LoraRecord],
    *,
    existing: Iterable[Mapping[str, Any]] = (),
) -> CharacterLoraValidation:
    """Validate public/private role data without persistence or inference."""
    by_name = {record.name: record for record in records}
    errors: list[str] = []
    warnings: list[str] = []
    authority = str(payload.get("authority") or "public").strip().casefold()
    if authority not in {"public", "private"}:
        errors.append("invalid_authority")
    lora_name = str(payload.get("lora_name") or "").strip()
    record = by_name.get(lora_name)
    if record is None:
        errors.append("missing_asset")
    elif not _SHA.fullmatch(str(record.sha256 or "").strip().casefold()):
        errors.append("missing_asset")
    identity = str(payload.get("character_canonical") or payload.get("display_name") or "").strip()
    if not identity:
        errors.append("missing_identity")
    variant_id = str(payload.get("variant_id") or "default").strip() or "default"
    if not _VARIANT.fullmatch(variant_id):
        errors.append("invalid_variant")
    activation_terms = _terms(payload.get("activation_terms"))
    if any(_FORBIDDEN.search(term) for term in activation_terms):
        errors.append("forbidden_activation_term")
    if any(len(term) > 240 for term in activation_terms):
        errors.append("activation_too_long")
    strength = payload.get("strength_override")
    if strength not in (None, ""):
        try:
            strength = float(strength)
            if not 0.0 <= strength <= 2.0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("invalid_strength")
    else:
        strength = None
    raw_families = payload.get("compatible_model_families", ())
    if isinstance(raw_families, str):
        raw_families = re.split(r"[\n,;，；]+", raw_families)
    if not isinstance(raw_families, (list, tuple, set)):
        raw_families = ()
    compatible_model_families = tuple(
        dict.fromkeys(str(item).strip().casefold() for item in raw_families if str(item).strip())
    )[:8]
    compatibility_mode = str(payload.get("compatibility_mode") or "unknown").strip().casefold()
    if compatibility_mode not in {"unknown", "legacy_only", "native_29b", "legacy_projection"}:
        errors.append("invalid_compatibility_mode")
    normalized = {
        "authority": authority,
        "lora_name": lora_name,
        "lora_sha256": str(record.sha256 or "").strip().casefold() if record else "",
        "character_canonical": identity,
        "copyright_canonical": str(payload.get("copyright_canonical") or "").strip(),
        "display_name": str(payload.get("display_name") or identity).strip(),
        "aliases": _terms(payload.get("aliases")),
        "variant_id": variant_id,
        "variant_display_name": str(payload.get("variant_display_name") or "").strip(),
        "default_for_character": bool(payload.get("default_for_character", True)),
        "activation_terms": activation_terms,
        "stable_identity_tags": _terms(payload.get("stable_identity_tags")),
        "default_appearance_tags": _terms(payload.get("default_appearance_tags")),
        "optional_component_tags": _terms(payload.get("optional_component_tags")),
        "strength_override": strength,
        "enabled": bool(payload.get("enabled", True)),
        "evidence": _terms(payload.get("evidence")),
        "compatible_model_families": compatible_model_families,
        "compatibility_mode": compatibility_mode,
    }
    sibling_rows = [item for item in existing if str(item.get("character_canonical") or item.get("display_name") or "").strip() == identity]
    candidates = [*sibling_rows, normalized]
    defaults = [item for item in candidates if bool(item.get("default_for_character", True))]
    if len(defaults) != 1:
        errors.append("default_variant_not_unique")
    if len(candidates) > 1 and any(not _terms(item.get("activation_terms")) for item in candidates):
        errors.append("activation_required_for_variant")
    groups = [tuple(term.casefold() for term in _terms(item.get("activation_terms"))) for item in candidates]
    if len(groups) != len(set(groups)) and len(candidates) > 1:
        errors.append("duplicate_activation_group")
    health = "ready" if not errors else "conflict" if any(error in errors for error in ("forbidden_activation_term", "missing_asset")) else "needs_review"
    return CharacterLoraValidation(not errors, health, normalized, tuple(dict.fromkeys(errors)), tuple(warnings))


__all__ = ["CharacterLoraValidation", "validate_character_lora_payload"]
