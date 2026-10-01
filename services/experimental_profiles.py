"""Read-only capability registry for opt-in experimental ComfyUI profiles.

The registry deliberately contains capability requirements only.  It does not
bundle, copy, or synthesize workflow JSON.  A profile is therefore never ready
unless the caller explicitly confirms that a separately reviewed workflow is
available for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class ExperimentalProfile:
    """Immutable description of one optional ComfyUI capability."""

    profile_id: str
    label: str
    required_node_types: tuple[str, ...]
    description: str
    checks_beta57: bool = False


_PROFILE_DEFINITIONS = {
    "artist_mixer": ExperimentalProfile(
        profile_id="artist_mixer",
        label="Artist Mixer",
        required_node_types=(
            "AnimaArtistPack",
            "AnimaArtistOptions",
            "AnimaArtistCrossAttn",
        ),
        description="Cross-attention mixing of multiple explicitly selected artists.",
    ),
    "quality_stack": ExperimentalProfile(
        profile_id="quality_stack",
        label="Quality Stack",
        required_node_types=(
            "AnimaBoosterLoader",
            "FLS_SamplerV4",
            "AnimaTeaCache",
        ),
        description="Optional Anima Booster, FLS sampler, and TeaCache quality stack.",
        checks_beta57=True,
    ),
    "layer_replay": ExperimentalProfile(
        profile_id="layer_replay",
        label="Layer Replay",
        required_node_types=("AnimaLayerReplayPatcher",),
        description="Layer-replay acceleration with a possible quality trade-off.",
    ),
}


# MappingProxyType plus frozen dataclasses/tuples prevents runtime mutation of
# capability contracts.  Activation state belongs to callers, not the registry.
EXPERIMENTAL_PROFILES: Mapping[str, ExperimentalProfile] = MappingProxyType(
    _PROFILE_DEFINITIONS
)


def get_experimental_profile(profile_id: str) -> ExperimentalProfile:
    """Return one immutable profile definition.

    A ``KeyError`` is intentional: callers must only activate known capability
    identifiers and should not silently accept an arbitrary workflow name.
    """

    return EXPERIMENTAL_PROFILES[str(profile_id or "").strip()]


def list_experimental_profiles() -> tuple[ExperimentalProfile, ...]:
    """Return the registry in its stable declaration order."""

    return tuple(EXPERIMENTAL_PROFILES.values())


def _registered_node_types(object_info: Any) -> set[str]:
    if not isinstance(object_info, Mapping):
        return set()
    return {
        str(node_type)
        for node_type, definition in object_info.items()
        if isinstance(node_type, str) and isinstance(definition, Mapping)
    }


def _scheduler_choices(object_info: Any) -> tuple[str, ...]:
    """Read only explicit ComfyUI ``scheduler`` choice enumerations.

    RES4LYF does not expose a dependable node class whose presence proves that
    ``beta57`` can be selected.  The observable contract is the enum advertised
    by a sampler node, so free-form text and unrelated values are ignored.
    """

    if not isinstance(object_info, Mapping):
        return ()

    values: list[str] = []
    seen: set[str] = set()
    for definition in object_info.values():
        if not isinstance(definition, Mapping):
            continue
        inputs = definition.get("input")
        if not isinstance(inputs, Mapping):
            continue
        for section_name in ("required", "optional"):
            section = inputs.get(section_name)
            if not isinstance(section, Mapping):
                continue
            field = section.get("scheduler")
            if not isinstance(field, (list, tuple)) or not field:
                continue
            choices = field[0]
            if not isinstance(choices, (list, tuple, set, frozenset)):
                continue
            for choice in choices:
                value = str(choice).strip()
                key = value.casefold()
                if value and key not in seen:
                    seen.add(key)
                    values.append(value)
    return tuple(values)


def evaluate_experimental_profile(
    profile_id: str,
    object_info: Any,
    *,
    workflow_available: bool = False,
) -> dict[str, Any]:
    """Evaluate one profile against a live ComfyUI ``object_info`` payload.

    Node compatibility alone is insufficient.  ``workflow_available`` must be
    explicitly true because this module intentionally ships no experimental
    workflow and must not activate a capability by guessing node wiring.
    """

    profile = get_experimental_profile(profile_id)
    registered = _registered_node_types(object_info)
    missing_nodes = [
        node_type
        for node_type in profile.required_node_types
        if node_type not in registered
    ]
    notes = [profile.description]

    if missing_nodes:
        notes.append(
            "Missing required ComfyUI node types: " + ", ".join(missing_nodes) + "."
        )
    else:
        notes.append("All required ComfyUI node types are registered.")

    if not workflow_available:
        notes.append(
            "No reviewed workflow is available for this profile; activation is blocked."
        )
    else:
        notes.append(
            "A separately reviewed workflow was declared available by the caller."
        )

    if profile.checks_beta57:
        schedulers = _scheduler_choices(object_info)
        if any(value.casefold() == "beta57" for value in schedulers):
            notes.append("Optional scheduler check: beta57 is advertised by ComfyUI.")
        elif schedulers:
            notes.append(
                "Optional scheduler check: beta57 is not advertised; use a supported "
                "scheduler or install/repair its provider. This does not gate readiness."
            )
        else:
            notes.append(
                "Optional scheduler check: no scheduler enum was advertised, so beta57 "
                "could not be verified. This does not gate readiness."
            )
        notes.append(
            "RES4LYF is not treated as a required node type; only the optional beta57 "
            "scheduler enum is inspected."
        )

    return {
        "id": profile.profile_id,
        "label": profile.label,
        "ready": bool(workflow_available and not missing_nodes),
        "required_nodes": list(profile.required_node_types),
        "missing_nodes": missing_nodes,
        "notes": notes,
    }


def inspect_experimental_profiles(
    object_info: Any,
    *,
    workflow_availability: Mapping[str, bool] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Evaluate every registered profile without mutating registry state."""

    availability = workflow_availability or {}
    return tuple(
        evaluate_experimental_profile(
            profile.profile_id,
            object_info,
            workflow_available=bool(availability.get(profile.profile_id, False)),
        )
        for profile in EXPERIMENTAL_PROFILES.values()
    )


__all__ = [
    "EXPERIMENTAL_PROFILES",
    "ExperimentalProfile",
    "evaluate_experimental_profile",
    "get_experimental_profile",
    "inspect_experimental_profiles",
    "list_experimental_profiles",
]
