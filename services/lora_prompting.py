"""Deterministic runtime LoRA merging and trigger-word planning."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..core.lora import canonical_lora_name
from ..models import LoraSelection
from .lora_catalog import FUNCTIONAL_LORA_CATEGORIES, LoraRecord
from .lora_presets import (
    LoraPreset,
    PRESET_CATEGORY_ARTIST_STYLE,
    PRESET_CATEGORY_CHARACTER,
    PRESET_CATEGORY_MIXED,
    deduplicate_selections,
)


_TRIGGER_SPLIT_RE = re.compile(r"\s*(?:,,|[,，;；\n\r]+)\s*")
_PROMPT_TERM_SPLIT_RE = re.compile(r"\s*(?:,,|[,，;；\n\r]+)\s*")
_WEIGHT_SUFFIX_RE = re.compile(r":\s*[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*$")
_METADATA_ESCAPE_RE = re.compile(r"\\([()\[\]{},])")
_GENERIC_CHARACTER_TRIGGERS = frozenset(
    {
        "1girl",
        "1boy",
        "solo",
        "character",
        "anime character",
        "masterpiece",
        "best quality",
        "high quality",
        "very aesthetic",
    }
)
_APPEARANCE_OR_OUTFIT_MARKERS = (
    "hair",
    "eyes",
    "eye",
    "dress",
    "uniform",
    "outfit",
    "clothes",
    "clothing",
    "shirt",
    "skirt",
    "coat",
    "jacket",
    "pants",
    "boots",
    "shoes",
    "gloves",
    "hat",
    "armor",
    "weapon",
    "swimsuit",
    "bikini",
    "lingerie",
    "发色",
    "头发",
    "眼睛",
    "服装",
    "衣服",
    "制服",
    "裙",
    "外套",
    "鞋",
    "武器",
)


@dataclass(frozen=True)
class LoraMergePlan:
    """The authoritative runtime stack plus ignored locked overrides."""

    selections: tuple[LoraSelection, ...]
    ignored_locked_overrides: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoraTriggerPlan:
    """A prompt with evidence-backed trigger words and an audit trail."""

    prompt: str
    added: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def _canonical_key(value: str) -> str:
    return canonical_lora_name(value).casefold()


def _term_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = text.strip("()[]{}<>‘’“”\"' ")
    text = _WEIGHT_SUFFIX_RE.sub("", text)
    return re.sub(r"[^0-9a-z@_\u3400-\u9fff]+", "", text)


def _split_trigger_text(value: str) -> tuple[str, ...]:
    return tuple(
        token.strip()
        for token in _TRIGGER_SPLIT_RE.split(str(value or ""))
        if token.strip()
    )


def _clean_metadata_trigger(value: str) -> str:
    """Restore punctuation escaped by Civitai/Markdown serialization."""

    return _METADATA_ESCAPE_RE.sub(r"\1", str(value or "").strip())


def _prompt_term_keys(value: str) -> set[str]:
    return {
        key
        for token in _PROMPT_TERM_SPLIT_RE.split(str(value or ""))
        if (key := _term_key(token))
    }


def _validate_groups(groups: Iterable[Iterable[LoraSelection]]) -> None:
    for group in groups:
        deduplicate_selections(tuple(group))


def merge_runtime_lora_selections(
    presets: tuple[LoraPreset, ...],
    *requested_groups: Iterable[LoraSelection],
) -> LoraMergePlan:
    """Merge LoRAs while keeping saved style/mixed preset weights immutable.

    Character presets remain adjustable by an explicit command or LLM choice.
    Later explicit groups win for every non-locked LoRA.
    """

    _validate_groups(
        (
            *(preset.selections for preset in presets),
            *requested_groups,
        )
    )
    ordered: list[str] = []
    values: dict[str, LoraSelection] = {}
    locked: set[str] = set()
    ignored: list[str] = []

    for preset in presets:
        preset_locks_weights = preset.category in {
            PRESET_CATEGORY_ARTIST_STYLE,
            PRESET_CATEGORY_MIXED,
        }
        for selection in preset.selections:
            normalized = deduplicate_selections((selection,))[0]
            key = _canonical_key(normalized.name)
            if key not in values:
                ordered.append(key)
                values[key] = normalized
            elif key not in locked:
                values[key] = normalized
            if preset_locks_weights:
                locked.add(key)

    for group in requested_groups:
        for selection in deduplicate_selections(tuple(group)):
            key = _canonical_key(selection.name)
            if key in locked:
                if values[key].strength != selection.strength:
                    ignored.append(selection.name)
                continue
            if key not in values:
                ordered.append(key)
            values[key] = selection

    return LoraMergePlan(
        selections=tuple(values[key] for key in ordered),
        ignored_locked_overrides=tuple(dict.fromkeys(ignored)),
    )


def _identity_terms(record: LoraRecord) -> tuple[str, ...]:
    values: list[str] = []
    # Do not use aliases here.  Catalog aliases may themselves contain every
    # trained word (including clothes), which would circularly "prove" an
    # outfit tag to be a character identity trigger.
    for raw in (record.character_name,):
        for part in re.split(r"\s*(?:/|\||；|;|,|，)\s*", str(raw or "")):
            key = _term_key(part)
            if len(key) >= 3 and key not in values:
                values.append(key)
    return tuple(values)


def is_character_identity_trigger_candidate(trigger: str) -> bool:
    folded = unicodedata.normalize("NFKC", trigger).casefold()
    key = _term_key(trigger)
    if not key or folded.strip() in _GENERIC_CHARACTER_TRIGGERS:
        return False
    if any(marker in folded for marker in _APPEARANCE_OR_OUTFIT_MARKERS):
        return False
    return True


def choose_character_identity_trigger(record: LoraRecord) -> str:
    candidates = tuple(
        cleaned
        for trigger in record.trigger_words
        if (cleaned := _clean_metadata_trigger(trigger))
    )
    identities = _identity_terms(record)
    for trigger in candidates:
        trigger_key = _term_key(trigger)
        if is_character_identity_trigger_candidate(trigger) and any(
            identity in trigger_key or trigger_key in identity
            for identity in identities
        ):
            return trigger
    return ""


def build_lora_trigger_plan(
    *,
    prompt: str,
    negative_prompt: str,
    selections: tuple[LoraSelection, ...],
    records_by_name: Mapping[str, LoraRecord],
    presets: tuple[LoraPreset, ...] = (),
    suppressed_terms: Iterable[str] = (),
) -> LoraTriggerPlan:
    """Append only explicit, role-appropriate trigger words.

    Style and functional LoRAs receive every metadata trigger.  Character
    LoRAs receive one reliable identity trigger only, so default clothes and
    appearance tags cannot defeat an explicit outfit change.  A preset's
    manually saved trigger string is authoritative for all of its members.
    """

    prompt_text = str(prompt or "").strip(" ,")
    existing = _prompt_term_keys(prompt_text)
    negative = _prompt_term_keys(negative_prompt)
    suppressed = {
        key for value in suppressed_terms if (key := _term_key(str(value or "")))
    }
    added: list[str] = []
    skipped: list[str] = []
    manual_member_keys: set[str] = set()
    preset_roles: dict[str, str] = {}
    manual_triggers: list[tuple[str, str]] = []

    def append_trigger(trigger: str, source: str) -> None:
        value = trigger.strip(" ,")
        key = _term_key(value)
        if not value or not key:
            return
        if key in suppressed:
            skipped.append(f"{source}: trigger suppressed by semantic rewrite: {value}")
            return
        if key in negative:
            skipped.append(f"{source}: trigger conflicts with negative prompt: {value}")
            return
        if key in existing:
            return
        existing.add(key)
        added.append(value)

    for preset in presets:
        for selection in preset.selections:
            key = _canonical_key(selection.name)
            resolved_record = records_by_name.get(key)
            resolved_key = (
                _canonical_key(resolved_record.name) if resolved_record is not None else key
            )
            current = preset_roles.get(key)
            if current != PRESET_CATEGORY_ARTIST_STYLE:
                preset_roles[key] = preset.category
            current = preset_roles.get(resolved_key)
            if current != PRESET_CATEGORY_ARTIST_STYLE:
                preset_roles[resolved_key] = preset.category
        manual = _split_trigger_text(preset.trigger_words)
        if not manual:
            continue
        for selection in preset.selections:
            key = _canonical_key(selection.name)
            manual_member_keys.add(key)
            resolved_record = records_by_name.get(key)
            if resolved_record is not None:
                manual_member_keys.add(_canonical_key(resolved_record.name))
        for trigger in manual:
            manual_triggers.append((trigger, f"preset {preset.name}"))

    conflicting_character_terms: set[str] = set()
    for selection in selections:
        key = _canonical_key(selection.name)
        record = records_by_name.get(key)
        if record is None:
            continue
        role = preset_roles.get(key) or record.category
        is_character_role = role in {PRESET_CATEGORY_CHARACTER, "character"} or (
            role in {PRESET_CATEGORY_MIXED, "mixed"} and bool(record.character_name)
        )
        if not is_character_role:
            continue
        identity_trigger_key = _term_key(choose_character_identity_trigger(record))
        for raw_trigger in record.trigger_words:
            trigger = _clean_metadata_trigger(raw_trigger)
            trigger_key = _term_key(trigger)
            if (
                trigger_key
                and trigger_key != identity_trigger_key
                and trigger_key in negative
            ):
                conflicting_character_terms.add(trigger_key)

    if conflicting_character_terms:
        kept_terms: list[str] = []
        for term in _PROMPT_TERM_SPLIT_RE.split(prompt_text):
            value = term.strip()
            if not value:
                continue
            if _term_key(value) in conflicting_character_terms:
                skipped.append(
                    f"removed positive character metadata term conflicting with negative: {value}"
                )
                continue
            kept_terms.append(value)
        prompt_text = ", ".join(kept_terms)
        existing = _prompt_term_keys(prompt_text)

    for trigger, source in manual_triggers:
        append_trigger(trigger, source)

    for selection in selections:
        key = _canonical_key(selection.name)
        if key in manual_member_keys:
            continue
        record = records_by_name.get(key)
        if record is None:
            skipped.append(f"{selection.name}: no fresh metadata record")
            continue
        triggers = tuple(
            cleaned
            for trigger in record.trigger_words
            if (cleaned := _clean_metadata_trigger(trigger))
        )
        if not triggers:
            skipped.append(f"{selection.name}: no metadata trigger words")
            continue

        role = preset_roles.get(key) or record.category
        if role == PRESET_CATEGORY_ARTIST_STYLE or role in FUNCTIONAL_LORA_CATEGORIES:
            for trigger in triggers:
                append_trigger(trigger, selection.name)
            continue
        if role == PRESET_CATEGORY_CHARACTER or role == "character":
            trigger = choose_character_identity_trigger(record)
            if trigger:
                append_trigger(trigger, selection.name)
            else:
                skipped.append(
                    f"{selection.name}: no reliable character identity trigger"
                )
            continue
        if role == PRESET_CATEGORY_MIXED or role == "mixed":
            if record.character_name:
                trigger = choose_character_identity_trigger(record)
                if trigger:
                    append_trigger(trigger, selection.name)
                else:
                    skipped.append(
                        f"{selection.name}: mixed LoRA has no reliable identity trigger"
                    )
            else:
                for trigger in triggers:
                    append_trigger(trigger, selection.name)
            continue
        skipped.append(f"{selection.name}: unclassified trigger words not auto-applied")

    combined = ", ".join(part for part in (prompt_text, *added) if part)
    return LoraTriggerPlan(
        prompt=combined,
        added=tuple(added),
        skipped=tuple(skipped),
    )


__all__ = [
    "LoraMergePlan",
    "LoraTriggerPlan",
    "build_lora_trigger_plan",
    "choose_character_identity_trigger",
    "is_character_identity_trigger_candidate",
    "merge_runtime_lora_selections",
]
