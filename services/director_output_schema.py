"""Built-in validator for the Director's structured output contract.

The model text never owns this schema. Unknown fields are rejected, asset
fields must reference verified probe evidence, and a failed validation stops
workflow compilation.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_SCHEMA_VERSION = "1.0"
_ALLOWED_PIPELINES = {"base", "rtx", "iterative"}
_ALLOWED_KEYS = {
    "positive_tags",
    "negative_tags",
    "pipeline",
    "characters",
    "lora_stack",
    "preset",
    "identity_binding",
}
_FORBIDDEN_IN_TEXT = ("<pic", "emit_anima_plan_v1")


class DirectorOutputSchemaError(ValueError):
    """Raised when a Director structured payload violates the built-in schema."""


def _require_string(payload: Mapping[str, Any], key: str, *, max_length: int) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise DirectorOutputSchemaError(f"{key} must be a string")
    if len(value) > max_length:
        raise DirectorOutputSchemaError(f"{key} exceeds {max_length} characters")
    return value


def validate_emit_anima_plan(
    payload: Any,
    *,
    allowed_lora_names: Sequence[str] = (),
    allowed_character_canonicals: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate and normalize one emit_anima_plan_v1 payload."""

    if not isinstance(payload, Mapping):
        raise DirectorOutputSchemaError("payload must be a JSON object")
    unknown = sorted(set(payload) - _ALLOWED_KEYS)
    if unknown:
        raise DirectorOutputSchemaError(f"unknown fields: {', '.join(unknown)}")

    positive = _require_string(payload, "positive_tags", max_length=8000)
    if not positive.strip():
        raise DirectorOutputSchemaError("positive_tags is required")
    lowered = positive.casefold()
    for forbidden in _FORBIDDEN_IN_TEXT:
        if forbidden in lowered:
            raise DirectorOutputSchemaError(f"positive_tags contains {forbidden!r}")

    negative = _require_string(payload, "negative_tags", max_length=2000)

    pipeline = _require_string(payload, "pipeline", max_length=32).strip().casefold()
    if pipeline not in _ALLOWED_PIPELINES:
        raise DirectorOutputSchemaError(
            f"pipeline must be one of {sorted(_ALLOWED_PIPELINES)}"
        )

    raw_characters = payload.get("characters", ())
    if raw_characters is None:
        raw_characters = ()
    if not isinstance(raw_characters, (list, tuple)):
        raise DirectorOutputSchemaError("characters must be an array")
    characters: list[dict[str, str]] = []
    allowed_canonicals = {str(value).strip() for value in allowed_character_canonicals if str(value).strip()}
    for index, raw in enumerate(raw_characters):
        if isinstance(raw, str):
            query = raw.strip()
            canonical = ""
            work = ""
        elif isinstance(raw, Mapping):
            query = str(raw.get("query") or "").strip()
            canonical = str(raw.get("canonical") or "").strip()
            work = str(raw.get("work") or "").strip()
        else:
            raise DirectorOutputSchemaError(f"characters[{index}] must be an object")
        if not query:
            raise DirectorOutputSchemaError(f"characters[{index}].query is required")
        if canonical and allowed_canonicals and canonical not in allowed_canonicals:
            raise DirectorOutputSchemaError(
                f"characters[{index}].canonical is not verified evidence"
            )
        characters.append(
            {"query": query, "canonical": canonical, "work": work}
        )

    raw_lora = payload.get("lora_stack", ())
    if raw_lora is None:
        raw_lora = ()
    if not isinstance(raw_lora, (list, tuple)):
        raise DirectorOutputSchemaError("lora_stack must be an array")
    lora_stack: list[dict[str, object]] = []
    allowed_loras = {str(value).strip() for value in allowed_lora_names if str(value).strip()}
    for index, raw in enumerate(raw_lora):
        if not isinstance(raw, Mapping):
            raise DirectorOutputSchemaError(f"lora_stack[{index}] must be an object")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise DirectorOutputSchemaError(f"lora_stack[{index}].name is required")
        if allowed_loras and name not in allowed_loras:
            raise DirectorOutputSchemaError(
                f"lora_stack[{index}].name is not verified evidence"
            )
        try:
            weight = float(raw.get("weight", 0))
        except (TypeError, ValueError) as exc:
            raise DirectorOutputSchemaError(
                f"lora_stack[{index}].weight must be numeric"
            ) from exc
        if not 0 <= weight <= 2:
            raise DirectorOutputSchemaError(
                f"lora_stack[{index}].weight must be between 0 and 2"
            )
        lora_stack.append({"name": name, "weight": weight})

    raw_preset = payload.get("preset")
    preset: dict[str, str] | None = None
    if raw_preset is not None:
        if not isinstance(raw_preset, Mapping):
            raise DirectorOutputSchemaError("preset must be an object")
        preset = {
            "name": str(raw_preset.get("name") or "").strip(),
            "manifest_hash": str(raw_preset.get("manifest_hash") or "").strip(),
        }
        if not preset["name"]:
            raise DirectorOutputSchemaError("preset.name is required")

    raw_binding = payload.get("identity_binding")
    identity_binding: dict[str, str] | None = None
    if raw_binding is not None:
        if not isinstance(raw_binding, Mapping):
            raise DirectorOutputSchemaError("identity_binding must be an object")
        identity_binding = {
            "character_canonical": str(
                raw_binding.get("character_canonical") or ""
            ).strip(),
            "copyright_canonical": str(
                raw_binding.get("copyright_canonical") or ""
            ).strip(),
            "activation_terms": str(
                raw_binding.get("activation_terms") or ""
            ).strip(),
        }

    return {
        "schema_version": _SCHEMA_VERSION,
        "positive_tags": positive.strip(),
        "negative_tags": negative.strip(),
        "pipeline": pipeline,
        "characters": tuple(characters),
        "lora_stack": tuple(lora_stack),
        "preset": preset,
        "identity_binding": identity_binding,
    }


__all__ = [
    "DirectorOutputSchemaError",
    "validate_emit_anima_plan",
]
