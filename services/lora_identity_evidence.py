"""Shared LoRA character/work discovery with exact-only authorization.

Fresh LoRA metadata and semantic facts may discover multilingual candidates, but
only the local Danbooru Character/Copyright index can authorize an identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .character_swap import (
    character_identity_trigger_candidates,
    character_lookup_hints_for_query,
)
from .danbooru_index import DanbooruTagIndex, normalize_tag
from .localized_character_aliases import (
    LocalizedCharacterAliasIndex,
    canonical_work_for_character,
    contains_localized_text,
)
from .lora_catalog import LoraRecord
from .lora_semantic import LoraSemanticIndex


@dataclass(frozen=True)
class LoraIdentityDiscovery:
    character_candidates: tuple[str, ...] = ()
    canonical_works: tuple[str, ...] = ()
    raw_names: tuple[str, ...] = ()
    raw_works: tuple[str, ...] = ()
    semantic_hint_count: int = 0
    localized_candidate_count: int = 0


def _split_names(value: str, limit: int = 24) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"\s*(?:/|／|\||;|；|,|，)\s*", str(value or ""))
            if 1 <= len(item.strip()) <= 80
        )
    )[:limit]


def _split_works(value: str, limit: int = 24) -> tuple[str, ...]:
    source = unicodedata.normalize("NFKC", str(value or "")).strip()
    primary = tuple(
        item.strip()
        for item in re.split(r"\s*(?:\||;|；|,|，)\s*", source)
        if 1 <= len(item.strip()) <= 120
    )
    slash_hints = tuple(
        part.strip()
        for item in primary
        for part in re.split(r"\s*[/／]\s*", item)
        if part.strip() and part.strip() != item and len(part.strip()) <= 120
    )
    return tuple(dict.fromkeys((*primary, *slash_hints)))[:limit]


def _qualified_parts(value: str) -> tuple[str, str]:
    normalized = normalize_tag(value)
    match = re.fullmatch(r"(.+)_\(([^()]+)\)", normalized)
    return (match.group(1), match.group(2)) if match else ("", "")


def _verified_work_canonicals(
    values: tuple[str, ...],
    *,
    tag_index: DanbooruTagIndex,
    localized_index: LocalizedCharacterAliasIndex | None,
) -> tuple[str, ...]:
    candidates: list[str] = []
    for value in values[:24]:
        if localized_index is not None:
            candidates.extend(localized_index.resolve_work(value, tag_index))
        normalized = normalize_tag(value)
        if normalized:
            candidates.append(normalized)
    unique = tuple(dict.fromkeys(candidates))[:48]
    lookups = tag_index.lookup_many(unique, "copyright") if unique else ()
    return tuple(
        dict.fromkeys(
            canonical
            for lookup in lookups
            if lookup.verified
            and (canonical := normalize_tag(lookup.canonical_tag or lookup.tag))
        )
    )


def build_lora_identity_discovery(
    record: LoraRecord,
    *,
    semantic_index: LoraSemanticIndex,
    tag_index: DanbooruTagIndex,
    localized_index: LocalizedCharacterAliasIndex | None = None,
    query: str = "",
) -> LoraIdentityDiscovery:
    """Build bounded multilingual candidates without authorizing metadata itself."""

    raw_names = _split_names(record.character_name)
    raw_works = _split_works(record.source_work)
    identity_hints: list[str] = []
    work_hints: list[str] = list(raw_works)
    for probe in tuple(dict.fromkeys((query, *raw_names)))[:24]:
        if not str(probe or "").strip():
            continue
        names, works = character_lookup_hints_for_query(
            (record,),
            probe,
            semantic_index,
        )
        identity_hints.extend(names)
        work_hints.extend(works)
    canonical_works = _verified_work_canonicals(
        tuple(dict.fromkeys(work_hints))[:48],
        tag_index=tag_index,
        localized_index=localized_index,
    )

    localized_canonicals: list[str] = []
    if localized_index is not None:
        work_probes = tuple(dict.fromkeys((*raw_works, *canonical_works))) or ("",)
        for name in raw_names:
            if not contains_localized_text(name):
                continue
            for work in work_probes[:24]:
                resolved = localized_index.resolve_character(name, work, tag_index)
                if resolved.verified and resolved.canonical_tag:
                    localized_canonicals.append(normalize_tag(resolved.canonical_tag))

    candidates: list[str] = [*localized_canonicals]
    discovery_names = tuple(
        dict.fromkeys(
            (
                *raw_names,
                *identity_hints,
                *character_identity_trigger_candidates(record),
            )
        )
    )[:72]
    for name in discovery_names:
        normalized = normalize_tag(name)
        if not normalized:
            continue
        candidates.append(normalized)
        _base, existing_work = _qualified_parts(normalized)
        if existing_work:
            continue
        if normalized.isascii() and re.search(r"[a-z]", normalized):
            candidates.extend(f"{normalized}_({work})" for work in canonical_works)
    return LoraIdentityDiscovery(
        character_candidates=tuple(dict.fromkeys(candidates))[:128],
        canonical_works=canonical_works,
        raw_names=raw_names,
        raw_works=raw_works,
        semantic_hint_count=len(tuple(dict.fromkeys(identity_hints))),
        localized_candidate_count=len(tuple(dict.fromkeys(localized_canonicals))),
    )


def resolve_lora_character_canonicals(
    record: LoraRecord,
    *,
    semantic_index: LoraSemanticIndex,
    tag_index: DanbooruTagIndex,
    localized_index: LocalizedCharacterAliasIndex | None = None,
    query: str = "",
) -> tuple[str, ...]:
    discovery = build_lora_identity_discovery(
        record,
        semantic_index=semantic_index,
        tag_index=tag_index,
        localized_index=localized_index,
        query=query,
    )
    lookups = tag_index.lookup_many(discovery.character_candidates, "character")
    verified: list[str] = []
    for lookup in lookups:
        if not lookup.verified:
            continue
        canonical = normalize_tag(lookup.canonical_tag or lookup.tag)
        work = canonical_work_for_character(canonical)
        if work and discovery.canonical_works and work not in discovery.canonical_works:
            continue
        if canonical:
            verified.append(canonical)
    return tuple(dict.fromkeys(verified))


__all__ = [
    "LoraIdentityDiscovery",
    "build_lora_identity_discovery",
    "resolve_lora_character_canonicals",
]
