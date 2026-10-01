"""Non-persistent character-LoRA identity projection for U1.0.0+1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..core.lora import canonical_lora_name
from .lora_catalog import LoraRecord
from .lora_semantic import LoraIdentityBinding, semantic_source_fingerprint
from .private_identity_profiles import PrivateIdentityProfile

HEALTH_STATES = (
    "ready", "needs_review", "missing_asset", "revision_changed", "ambiguous", "conflict"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_ACTIVATION = re.compile(
    r"<lora\s*:|https?://|[\\/]|(?:^|\s)[+-]?\d+(?:\.\d+)?(?:\s|$)|(?:[:=]\s*)[+-]?\d+(?:\.\d+)?(?:\s|$)|\.(?:safetensors|ckpt|pt|bin)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CharacterLoraPresetView:
    authority_kind: str
    identity_ref: str
    display_name: str
    aliases: tuple[str, ...]
    asset_key: str
    lora_name: str
    asset_revision: str
    metadata_revision: str
    character_canonical: str = ""
    copyright_canonical: str = ""
    variant_id: str = "default"
    variant_display_name: str = ""
    activation_terms: tuple[str, ...] = ()
    stable_identity_tags: tuple[str, ...] = ()
    default_appearance_tags: tuple[str, ...] = ()
    optional_component_tags: tuple[str, ...] = ()
    strength_override: float | None = None
    effective_strength: float = 0.65
    strength_source: str = "global"
    default_for_identity: bool = True
    enabled: bool = True
    health: str = "needs_review"
    warnings: tuple[str, ...] = ()
    compatible_model_families: tuple[str, ...] = ()
    compatibility_mode: str = "unknown"


def _metadata_revision(record: LoraRecord, source: Any) -> str:
    payload = {
        "record": {
            "name": record.name,
            "description": record.description,
            "model_name": record.model_name,
            "base_model": record.base_model,
            "trigger_words": tuple(record.trigger_words),
            "tags": tuple(record.tags),
            "aliases": tuple(record.aliases),
            "character_name": record.character_name,
            "source_work": record.source_work,
            "category": record.category,
            "source_fingerprint": semantic_source_fingerprint(record),
        },
        "source": source,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clean_terms(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _strength(command: float | None, profile: float | None, global_value: float) -> tuple[float, str]:
    value, source = (
        (command, "command") if command is not None else
        (profile, "profile") if profile is not None else
        (global_value, "global")
    )
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(global_value), "global"
    if not 0.0 <= number <= 2.0:
        return float(global_value), "global"
    return number, source


def _health(record: LoraRecord, expected_revision: str, warnings: list[str]) -> str:
    digest = str(record.sha256 or "").strip().casefold()
    if not _SHA_RE.fullmatch(digest):
        warnings.append("asset_sha_unavailable")
        return "missing_asset"
    expected = str(expected_revision or "").strip().casefold()
    if not _SHA_RE.fullmatch(expected):
        warnings.append("identity_revision_unbound")
        return "needs_review"
    if expected != digest:
        warnings.append("asset_revision_mismatch")
        return "revision_changed"
    return "ready"


def _view(
    record: LoraRecord,
    *,
    authority_kind: str,
    identity_ref: str,
    display_name: str,
    aliases: Iterable[Any],
    expected_revision: str,
    metadata_source: Any,
    character: str = "",
    work: str = "",
    variant_id: str = "default",
    variant_display_name: str = "",
    activation_terms: Iterable[Any] = (),
    stable_tags: Iterable[Any] = (),
    default_tags: Iterable[Any] = (),
    optional_tags: Iterable[Any] = (),
    default_for_identity: bool = True,
    strength_override: float | None = None,
    command_strength: float | None = None,
    global_strength: float = 0.65,
    enabled: bool = True,
    compatible_model_families: Iterable[Any] = (),
    compatibility_mode: str = "unknown",
) -> CharacterLoraPresetView:
    warnings: list[str] = []
    terms = _clean_terms(activation_terms)
    if any(_FORBIDDEN_ACTIVATION.search(term) for term in terms):
        warnings.append("forbidden_activation_term")
    health = _health(record, expected_revision, warnings)
    if "forbidden_activation_term" in warnings:
        health = "conflict"
    effective, source = _strength(command_strength, strength_override, global_strength)
    return CharacterLoraPresetView(
        authority_kind=authority_kind,
        identity_ref=identity_ref,
        display_name=str(display_name or identity_ref),
        aliases=_clean_terms(aliases),
        asset_key=canonical_lora_name(record.name),
        lora_name=record.name,
        asset_revision=str(record.sha256 or "").strip().casefold(),
        metadata_revision=_metadata_revision(record, metadata_source),
        character_canonical=character,
        copyright_canonical=work,
        variant_id=variant_id or "default",
        variant_display_name=variant_display_name,
        activation_terms=terms,
        stable_identity_tags=_clean_terms(stable_tags),
        default_appearance_tags=_clean_terms(default_tags),
        optional_component_tags=_clean_terms(optional_tags),
        strength_override=strength_override,
        effective_strength=effective,
        strength_source=source,
        default_for_identity=bool(default_for_identity),
        enabled=bool(enabled) and health == "ready",
        health=health,
        warnings=tuple(warnings),
        compatible_model_families=_clean_terms(compatible_model_families),
        compatibility_mode=str(compatibility_mode or "unknown").strip().casefold(),
    )


def build_character_lora_views(
    record: LoraRecord,
    *,
    public_bindings: Iterable[LoraIdentityBinding] = (),
    private_profile: PrivateIdentityProfile | None = None,
    command_strength: float | None = None,
    global_strength: float = 0.65,
) -> tuple[CharacterLoraPresetView, ...]:
    """Project current public/private authority without persistence or inference."""
    bindings = tuple(public_bindings)
    if bindings and private_profile is not None:
        return (_view(record, authority_kind="conflict", identity_ref="conflict:authority", display_name="authority conflict", aliases=(), expected_revision="", metadata_source={"bindings": [b.to_dict() for b in bindings], "profile": private_profile.to_dict()}, enabled=False),)
    if private_profile is not None:
        return (_view(record, authority_kind="local_profile", identity_ref=f"private:{private_profile.profile_id}", display_name=private_profile.display_name, aliases=private_profile.aliases, expected_revision=private_profile.lora_sha256, metadata_source=private_profile.to_dict(), variant_id=private_profile.variant_id, variant_display_name=private_profile.variant_display_name, activation_terms=private_profile.activation_terms, stable_tags=private_profile.identity_tags, default_tags=private_profile.default_appearance_tags, optional_tags=private_profile.optional_component_tags, default_for_identity=private_profile.default_for_character, strength_override=private_profile.lora_strength_override, command_strength=command_strength, global_strength=global_strength, enabled=private_profile.enabled, compatible_model_families=private_profile.compatible_model_families, compatibility_mode=private_profile.compatibility_mode),)
    views: list[CharacterLoraPresetView] = []
    for binding in bindings:
        views.append(_view(record, authority_kind="public_binding", identity_ref=f"public:{binding.character_canonical}:{binding.variant_id}", display_name=binding.variant_display_name or binding.character_canonical, aliases=binding.variant_aliases, expected_revision=binding.verified_revision, metadata_source=binding.to_dict(), character=binding.character_canonical, work=binding.copyright_canonical, variant_id=binding.variant_id, variant_display_name=binding.variant_display_name, activation_terms=binding.activation_terms, stable_tags=binding.stable_identity_tags, default_tags=binding.default_appearance_tags, optional_tags=binding.optional_component_tags, default_for_identity=binding.default_for_character, command_strength=command_strength, global_strength=global_strength, compatible_model_families=binding.compatible_model_families, compatibility_mode=binding.compatibility_mode))
    if len(views) > 1:
        normalized_groups = [tuple(term.casefold() for term in view.activation_terms) for view in views]
        if any(not terms for terms in normalized_groups):
            views = [dataclass_replace(view, health="needs_review", enabled=False, warnings=tuple(dict.fromkeys((*view.warnings, "activation_required_for_variant")))) for view in views]
        if len(set(normalized_groups)) != len(normalized_groups):
            views = [dataclass_replace(view, health="ambiguous", enabled=False, warnings=tuple(dict.fromkeys((*view.warnings, "duplicate_activation_group")))) for view in views]
    return tuple(views)


def dataclass_replace(view: CharacterLoraPresetView, **changes: Any) -> CharacterLoraPresetView:
    values = view.__dict__.copy()
    values.update(changes)
    return CharacterLoraPresetView(**values)


__all__ = ["CharacterLoraPresetView", "HEALTH_STATES", "build_character_lora_views"]
