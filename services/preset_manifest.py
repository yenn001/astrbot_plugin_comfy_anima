"""Preset manifest and submission-time invariant gates for ordinary-chat drawing.

The manifest is the single authoritative snapshot of "what the user asked to
draw".  Before a workflow reaches ``workflow_payload_ready`` the plugin
rebuilds the manifest from the *actual* final prompt, negative pool and LoRA
stack and asserts that it still matches the snapshot.  Any mismatch stops the
job instead of silently drawing the wrong character or dropping the preset
negative pool.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


class PresetManifestError(ValueError):
    """Raised when the final workflow no longer matches the preset manifest."""


@dataclass(frozen=True)
class LoraManifestEntry:
    """One canonical LoRA selection that must survive into the final workflow."""

    name: str
    weight: float
    model_family: str = ""

    def normalized(self) -> tuple[str, float, str]:
        """Return a hash-stable normalized tuple."""

        return (
            str(self.name or "").strip().casefold(),
            round(float(self.weight), 6),
            str(self.model_family or "").strip().casefold(),
        )


def _normalize_terms(value: Any) -> tuple[str, ...]:
    """Split and normalize comma/newline separated prompt terms."""

    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        parts: list[str] = []
        for item in value:
            parts.extend(str(item or "").split(","))
    else:
        parts = str(value or "").split(",")
    return tuple(
        dict.fromkeys(
            term.strip()
            for part in parts
            if (term := part.strip())
        )
    )


def _normalize_lora_entries(value: Any) -> tuple[LoraManifestEntry, ...]:
    if not value:
        return ()
    if isinstance(value, LoraManifestEntry):
        return (value,)
    if isinstance(value, Mapping):
        value = (value,)
    entries: list[LoraManifestEntry] = []
    for item in value or ():
        if isinstance(item, LoraManifestEntry):
            entries.append(item)
            continue
        if isinstance(item, Mapping):
            try:
                weight = float(item.get("weight") or 0.0)
            except (TypeError, ValueError) as exc:
                raise PresetManifestError(
                    f"LoRA manifest weight is not numeric: {item.get('weight')!r}"
                ) from exc
            entries.append(
                LoraManifestEntry(
                    name=str(item.get("name") or "").strip(),
                    weight=weight,
                    model_family=str(item.get("model_family") or "").strip(),
                )
            )
            continue
        raise PresetManifestError(f"unsupported LoRA manifest entry: {item!r}")
    return tuple(entries)


@dataclass(frozen=True)
class PresetManifest:
    """Authoritative picture recipe snapshot."""

    preset_name: str = ""
    positive_terms: tuple[str, ...] = ()
    negative_terms: tuple[str, ...] = ()
    lora_entries: tuple[LoraManifestEntry, ...] = ()
    model_family: str = ""
    identity_anchor: str = ""
    required_triggers: tuple[str, ...] = ()
    manifest_hash: str = ""

    @classmethod
    def build(
        cls,
        *,
        preset_name: Any = "",
        positive_terms: Any = (),
        negative_terms: Any = (),
        lora_entries: Any = (),
        model_family: Any = "",
        identity_anchor: Any = "",
        required_triggers: Any = (),
    ) -> "PresetManifest":
        """Build a normalized manifest and its stable hash."""

        normalized_positive = _normalize_terms(positive_terms)
        normalized_negative = _normalize_terms(negative_terms)
        normalized_lora = _normalize_lora_entries(lora_entries)
        normalized_triggers = _normalize_terms(required_triggers)
        manifest = cls(
            preset_name=str(preset_name or "").strip(),
            positive_terms=normalized_positive,
            negative_terms=normalized_negative,
            lora_entries=normalized_lora,
            model_family=str(model_family or "").strip().casefold(),
            identity_anchor=str(identity_anchor or "").strip(),
            required_triggers=normalized_triggers,
        )
        object.__setattr__(manifest, "manifest_hash", manifest._compute_hash())
        return manifest

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PresetManifest":
        """Rebuild a manifest from a stored/JSON mapping."""

        return cls.build(
            preset_name=value.get("preset_name", ""),
            positive_terms=value.get("positive_terms", ()),
            negative_terms=value.get("negative_terms", ()),
            lora_entries=value.get("lora_entries", ()),
            model_family=value.get("model_family", ""),
            identity_anchor=value.get("identity_anchor", ""),
            required_triggers=value.get("required_triggers", ()),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "preset_name": self.preset_name,
            "positive_terms": list(self.positive_terms),
            "negative_terms": list(self.negative_terms),
            "lora_entries": [
                {
                    "name": entry.name,
                    "weight": entry.weight,
                    "model_family": entry.model_family,
                }
                for entry in self.lora_entries
            ],
            "model_family": self.model_family,
            "identity_anchor": self.identity_anchor,
            "required_triggers": list(self.required_triggers),
        }

    def _compute_hash(self) -> str:
        payload = json.dumps(
            self._payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-safe mapping including the hash."""

        return {**self._payload(), "manifest_hash": self.manifest_hash}

    def matches(self, other: "PresetManifest") -> bool:
        """Compare the canonical payload, not the caller-supplied hash."""

        return self._payload() == other._payload()

    def requires_negative_pool(self) -> bool:
        """Return whether the manifest declares a non-empty negative pool."""

        return bool(self.negative_terms)

    def lora_keys(self) -> tuple[tuple[str, float, str], ...]:
        """Return normalized LoRA keys in stable order."""

        return tuple(entry.normalized() for entry in self.lora_entries)


def assert_manifests_equal(
    expected: PresetManifest,
    actual: PresetManifest,
    *,
    reason: str = "",
) -> None:
    """Raise when the final workflow manifest diverges from the intent snapshot."""

    if expected.matches(actual):
        return
    differences: list[str] = []
    if expected.preset_name != actual.preset_name:
        differences.append(
            f"preset_name expected={expected.preset_name!r} actual={actual.preset_name!r}"
        )
    if expected.positive_terms != actual.positive_terms:
        differences.append("positive_terms differ")
    if expected.negative_terms != actual.negative_terms:
        differences.append(
            f"negative_terms differ expected_len={len(expected.negative_terms)} "
            f"actual_len={len(actual.negative_terms)}"
        )
    if expected.lora_keys() != actual.lora_keys():
        differences.append(
            f"lora stack differs expected={expected.lora_keys()!r} "
            f"actual={actual.lora_keys()!r}"
        )
    if expected.model_family != actual.model_family:
        differences.append(
            f"model_family expected={expected.model_family!r} actual={actual.model_family!r}"
        )
    if expected.identity_anchor != actual.identity_anchor:
        differences.append("identity_anchor differs")
    if expected.required_triggers != actual.required_triggers:
        differences.append("required_triggers differ")
    suffix = f": {reason}" if reason else ""
    raise PresetManifestError(
        "最终 prompt 与预设清单不一致，已停止生成"
        + ("；" + "；".join(differences) if differences else "")
        + suffix
    )


def assert_preset_invariants(
    expected: PresetManifest,
    actual: PresetManifest,
    *,
    reason: str = "",
) -> None:
    """Assert the drawing-affecting subset that must survive final compilation.

    The positive prompt legitimately grows (trigger words, Danbooru
    non-character enrichment), so it is not compared verbatim here.  The
    negative pool, LoRA stack and identity anchor are invariants: dropping any
    of them changes who or what gets drawn.
    """

    failures: list[str] = []
    if expected.requires_negative_pool():
        if not actual.negative_terms:
            failures.append("preset negative pool was dropped to empty")
        else:
            missing = [
                term
                for term in expected.negative_terms
                if term not in actual.negative_terms
            ]
            if missing:
                failures.append(f"missing negative terms: {missing[:6]!r}")
    expected_lora = expected.lora_keys()
    if expected_lora:
        actual_lora = actual.lora_keys()
        missing_lora = [key for key in expected_lora if key not in actual_lora]
        if missing_lora:
            failures.append(f"missing LoRA stack entries: {missing_lora!r}")
    if expected.model_family and actual.model_family:
        if expected.model_family != actual.model_family:
            failures.append(
                f"model family expected={expected.model_family!r} "
                f"actual={actual.model_family!r}"
            )
    if expected.identity_anchor:
        joined_positive = " ".join(actual.positive_terms).casefold()
        if expected.identity_anchor.casefold() not in joined_positive:
            failures.append(
                f"identity anchor {expected.identity_anchor!r} is missing from final prompt"
            )
    if failures:
        suffix = f": {reason}" if reason else ""
        raise PresetManifestError(
            "最终 workflow 与预设清单不变量不一致，已停止生成；"
            + "；".join(failures)
            + suffix
        )


def lora_entries_from_names(
    names: Iterable[str],
    *,
    default_weight: float = 0.0,
    model_family: str = "",
) -> tuple[LoraManifestEntry, ...]:
    """Build manifest entries from plain LoRA names."""

    return tuple(
        LoraManifestEntry(
            name=str(name or "").strip(),
            weight=float(default_weight),
            model_family=str(model_family or "").strip(),
        )
        for name in names
        if str(name or "").strip()
    )


def manifest_from_success(
    *,
    preset_name: str,
    prompt: str,
    negative_prompt: str,
    lora_entries: Sequence[LoraManifestEntry] | Any,
    model_family: str,
    identity_anchor: str = "",
    required_triggers: Iterable[str] = (),
) -> PresetManifest:
    """Convenience builder used by the session recipe commit path."""

    return PresetManifest.build(
        preset_name=preset_name,
        positive_terms=prompt,
        negative_terms=negative_prompt,
        lora_entries=lora_entries,
        model_family=model_family,
        identity_anchor=identity_anchor,
        required_triggers=required_triggers,
    )


@dataclass(frozen=True)
class ManifestSlot:
    """One merged LoRA slot with its provenance classification."""

    name: str
    weight: float
    trigger: str = ""
    model_family: str = ""
    source: str = field(default="recipe")
    preset_index: int = -1

    def normalized_key(self) -> tuple[str, str]:
        return (
            str(self.name or "").strip().casefold(),
            str(self.model_family or "").strip().casefold(),
        )


@dataclass(frozen=True)
class ManifestMergeResult:
    """Explained double-manifest merge outcome."""

    effective_manifest: PresetManifest
    slots: tuple[ManifestSlot, ...]
    merge_trace: tuple[str, ...]
    conflicts: int
    source_revision: str = ""

    @property
    def merge_trace_text(self) -> str:
        return "\n".join(self.merge_trace)


def merge_preset_manifests_with_trace(
    recipe_entries: Any,
    preset_entries: Any,
    *,
    preset_name: str = "",
    positive_terms: Any = (),
    negative_terms: Any = (),
) -> ManifestMergeResult:
    """Merge two manifests and produce an auditable effective manifest.

    Same-name slots are resolved with preset authority and every override is
    recorded in ``merge_trace``; no slot is silently dropped.
    """

    recipe = _normalize_lora_entries(recipe_entries)
    preset = _normalize_lora_entries(preset_entries)
    preset_by_key: dict[tuple[str, str], LoraManifestEntry] = {}
    preset_order: list[tuple[str, str]] = []
    trace: list[str] = []
    conflicts = 0
    for entry in preset:
        key = (entry.name.strip().casefold(), entry.model_family.strip().casefold())
        if key in preset_by_key:
            conflicts += 1
            raise PresetManifestError(f"preset declares duplicate LoRA: {entry.name}")
        preset_by_key[key] = entry
        preset_order.append(key)

    merged: dict[tuple[str, str], ManifestSlot] = {}
    order: list[tuple[str, str]] = []
    for key in preset_order:
        entry = preset_by_key[key]
        merged[key] = ManifestSlot(
            name=entry.name,
            weight=entry.weight,
            trigger="",
            model_family=entry.model_family,
            source="preset",
            preset_index=0,
        )
        order.append(key)
        trace.append(f"slot:{entry.name}|source:preset|weight:{entry.weight}")
    for entry in recipe:
        key = (entry.name.strip().casefold(), entry.model_family.strip().casefold())
        if key in merged:
            existing = merged[key]
            if abs(existing.weight - entry.weight) > 1e-6:
                conflict = (
                    f"slot conflict:{entry.name}|preset_weight:{existing.weight}"
                    f"|recipe_weight:{entry.weight}"
                )
                trace.append(conflict)
                raise PresetManifestError(
                    f"会话配方与预设权重冲突，已停止生成：{conflict}"
                )
            trace.append(
                f"slot:{entry.name}|source:preset|weight:{existing.weight}|"
                "recipe_weight_identical"
            )
            continue
        merged[key] = ManifestSlot(
            name=entry.name,
            weight=entry.weight,
            trigger="",
            model_family=entry.model_family,
            source="recipe",
            preset_index=-1,
        )
        order.append(key)
        trace.append(f"slot:{entry.name}|source:recipe|weight:{entry.weight}")
    slots = tuple(merged[key] for key in order)
    effective_manifest = PresetManifest.build(
        preset_name=preset_name or "merged_preset",
        positive_terms=positive_terms,
        negative_terms=negative_terms,
        lora_entries=[
            LoraManifestEntry(
                name=slot.name,
                weight=slot.weight,
                model_family=slot.model_family,
            )
            for slot in slots
        ],
    )
    return ManifestMergeResult(
        effective_manifest=effective_manifest,
        slots=slots,
        merge_trace=tuple(trace),
        conflicts=conflicts,
    )


def merge_preset_manifests(
    recipe_entries: Any,
    preset_entries: Any,
) -> tuple[ManifestSlot, ...]:
    """Merge with the audited fail-closed implementation.

    Same-name weight conflicts raise instead of silently overriding.
    """

    result = merge_preset_manifests_with_trace(recipe_entries, preset_entries)
    return result.slots
