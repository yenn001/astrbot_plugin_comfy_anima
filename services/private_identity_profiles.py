"""Read-only private/OC profile adapter for the U1 character-LoRA projection.

The U1 track deliberately does not introduce a persistence layer.  Callers may
adapt an existing private profile object or mapping to this immutable view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PrivateIdentityProfile:
    profile_id: str
    display_name: str
    aliases: tuple[str, ...]
    lora_name: str
    lora_sha256: str
    activation_terms: tuple[str, ...]
    identity_tags: tuple[str, ...] = ()
    default_appearance_tags: tuple[str, ...] = ()
    optional_component_tags: tuple[str, ...] = ()
    variant_id: str = "default"
    variant_display_name: str = ""
    default_for_character: bool = True
    enabled: bool = True
    lora_strength_override: float | None = None
    compatible_model_families: tuple[str, ...] = ()
    compatibility_mode: str = "unknown"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PrivateIdentityProfile":
        def values(name: str) -> tuple[str, ...]:
            raw = payload.get(name, ())
            if isinstance(raw, str):
                raw = (raw,)
            if not isinstance(raw, (list, tuple, set)):
                return ()
            return tuple(str(item) for item in raw)

        return cls(
            profile_id=str(payload.get("profile_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            aliases=values("aliases"),
            lora_name=str(payload.get("lora_name") or ""),
            lora_sha256=str(payload.get("lora_sha256") or ""),
            activation_terms=values("activation_terms"),
            identity_tags=values("identity_tags"),
            default_appearance_tags=values("default_appearance_tags"),
            optional_component_tags=values("optional_component_tags"),
            variant_id=str(payload.get("variant_id") or "default"),
            variant_display_name=str(payload.get("variant_display_name") or ""),
            default_for_character=bool(payload.get("default_for_character", True)),
            enabled=bool(payload.get("enabled", True)),
            lora_strength_override=payload.get("lora_strength_override"),
            compatible_model_families=values("compatible_model_families"),
            compatibility_mode=str(payload.get("compatibility_mode") or "unknown"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "lora_name": self.lora_name,
            "lora_sha256": self.lora_sha256,
            "activation_terms": list(self.activation_terms),
            "identity_tags": list(self.identity_tags),
            "default_appearance_tags": list(self.default_appearance_tags),
            "optional_component_tags": list(self.optional_component_tags),
            "variant_id": self.variant_id,
            "variant_display_name": self.variant_display_name,
            "default_for_character": self.default_for_character,
            "enabled": self.enabled,
            "lora_strength_override": self.lora_strength_override,
            "compatible_model_families": list(self.compatible_model_families),
            "compatibility_mode": self.compatibility_mode,
        }


__all__ = ["PrivateIdentityProfile"]
