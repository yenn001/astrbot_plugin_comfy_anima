"""Deterministic local Danbooru character identity resolution.

Provider output is discovery data, never identity authority.  This module expands
only bounded prompt-safe variants, accepts only verified character exact/unique
alias lookups, and checks the work qualifier before returning a canonical tag.
Prefix/keyword results are used only to collapse variants of one proven identity;
they are exact-confirmed again before authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Sequence
import unicodedata

from .danbooru_index import DanbooruTagIndex, TagCandidate, TagLookup, normalize_tag


_QUALIFIER_RE = re.compile(r"_\(([^()]*)\)")
_TRAILING_QUALIFIER_RE = re.compile(r"_\(([^()]*)\)$")
_ASCII_LOOKUP_RE = re.compile(r"[A-Za-z][A-Za-z0-9_ .()!'&+:/-]{0,79}")
_SAFE_LOOKUP_RE = re.compile(r"[a-z0-9_().!'&+:/-]{1,80}")


@dataclass(frozen=True)
class CharacterIdentityResolution:
    canonical_tag: str = ""
    verified: bool = False
    ambiguous: bool = False
    match_variant: str = "none"
    match_type: str = "none"
    query_count: int = 0
    candidate_count: int = 0
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class _LookupSpec:
    value: str
    variant: str
    expected_work: str = ""


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_tag(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _qualifiers(value: str) -> tuple[str, ...]:
    return tuple(
        item
        for raw in _QUALIFIER_RE.findall(normalize_tag(value))
        if (item := normalize_tag(raw))
    )


def _work_qualifier(value: str) -> str:
    qualifiers = _qualifiers(value)
    return qualifiers[-1] if qualifiers else ""


def _strip_last_qualifier(value: str) -> tuple[str, str]:
    normalized = normalize_tag(value)
    match = _TRAILING_QUALIFIER_RE.search(normalized)
    if match is None:
        return normalized, ""
    stripped = normalized[: match.start()].rstrip("_")
    return stripped, normalize_tag(match.group(1))


def _identity_root(value: str) -> str:
    """Collapse costume variants while retaining the final work qualifier."""

    normalized = normalize_tag(value)
    qualifiers = _qualifiers(normalized)
    if not qualifiers:
        return normalized
    base = _QUALIFIER_RE.sub("", normalized).rstrip("_")
    return f"{base}_({qualifiers[-1]})"


def _safe_lookup_value(value: Any) -> str:
    normalized = normalize_tag(str(value or ""))
    if not normalized or not _SAFE_LOOKUP_RE.fullmatch(normalized):
        return ""
    return normalized


def _ascii_query_segments(value: str) -> tuple[str, ...]:
    segments: list[str] = []
    for raw in re.split(r"[/|、；;\n]+", unicodedata.normalize("NFKC", value)):
        # Parentheses may be the meaningful Danbooru work qualifier in an
        # explicit value such as ``viola (bang_dream!)``.  Strip only wrapper
        # punctuation here; ``normalize_tag`` will canonicalize the qualifier.
        stripped = raw.strip(" ，,:：[]{}<>\"'")
        if not stripped or not stripped.isascii() or not _ASCII_LOOKUP_RE.fullmatch(stripped):
            continue
        safe = _safe_lookup_value(stripped)
        if safe:
            segments.append(safe)
    return _dedupe(segments)


def character_identity_lookup_candidates(
    *,
    target_query: str,
    canonical_tag: str = "",
    identity_candidates: Sequence[str] = (),
    work_hints: Sequence[str] = (),
) -> tuple[str, ...]:
    """Expose the bounded exact candidates for optional Gallery verification.

    The Gallery remains a discovery/evidence source.  Callers must require an
    exact Character-category response for these already-safe candidates and
    must still reject cross-identity ambiguity.
    """

    return tuple(
        dict.fromkeys(
            spec.value
            for spec in _lookup_specs(
                target_query,
                canonical_tag,
                identity_candidates,
                work_hints,
            )
        )
    )


def _lookup_specs(
    target_query: str,
    canonical_tag: str,
    identity_candidates: Sequence[str],
    work_hints: Sequence[str],
) -> tuple[_LookupSpec, ...]:
    specs: list[_LookupSpec] = []
    global_works = _dedupe(work_hints)
    safe_global_works = tuple(
        work for raw in global_works if (work := _safe_lookup_value(raw))
    )[:4]

    def add(value: str, variant: str, expected_work: str = "") -> None:
        safe = _safe_lookup_value(value)
        work = _safe_lookup_value(expected_work)
        if not safe:
            return
        specs.append(_LookupSpec(safe, variant, work))

    canonical = _safe_lookup_value(canonical_tag)
    if canonical:
        add(canonical, "canonical_exact", _work_qualifier(canonical))
        stripped, work = _strip_last_qualifier(canonical)
        if stripped and work:
            add(stripped, "alias_without_work", work)

    for candidate in identity_candidates[:8]:
        safe = _safe_lookup_value(candidate)
        if not safe:
            continue
        expected_work = _work_qualifier(safe) or (
            safe_global_works[0] if len(safe_global_works) == 1 else ""
        )
        add(safe, "provider_candidate_exact", expected_work)
        stripped, stripped_work = _strip_last_qualifier(safe)
        if stripped and stripped_work:
            add(stripped, "provider_candidate_alias_without_work", stripped_work)
        elif "_(" not in safe:
            # A short alias such as ``rio`` is not exact when costume variants
            # also exist. Copyright evidence may construct bounded Character
            # candidates, but every result is still exact-checked below.
            for work in safe_global_works:
                add(
                    f"{safe}_({work})",
                    "provider_candidate_work_qualified",
                    work,
                )

    for segment in _ascii_query_segments(target_query):
        add(
            segment,
            "user_ascii_exact",
            safe_global_works[0] if len(safe_global_works) == 1 else "",
        )
        if "_(" not in segment:
            for work in safe_global_works:
                add(
                    f"{segment}_({work})",
                    "user_ascii_work_qualified",
                    work,
                )

    deduped: list[_LookupSpec] = []
    seen: set[tuple[str, str]] = set()
    for spec in specs:
        key = (normalize_tag(spec.value), normalize_tag(spec.expected_work))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return tuple(deduped[:24])


def _work_matches(canonical_tag: str, expected_work: str) -> bool:
    expected = normalize_tag(expected_work)
    if not expected:
        return True
    return _work_qualifier(canonical_tag) == expected


def _verified_hit(lookup: TagLookup, expected_work: str) -> bool:
    return bool(
        lookup.found
        and lookup.verified
        and str(lookup.category or "").casefold() == "character"
        and _work_matches(lookup.canonical_tag or lookup.tag, expected_work)
    )


def _lookup_many(
    index: DanbooruTagIndex,
    values: Sequence[str],
) -> tuple[TagLookup, ...]:
    batch = getattr(index, "lookup_many", None)
    if callable(batch):
        return tuple(batch(values, "character"))
    lookup = getattr(index, "lookup")
    return tuple(lookup(value, "character") for value in values)


def _candidate_canonical(candidate: TagCandidate) -> str:
    return normalize_tag(candidate.canonical_tag or candidate.tag)


def resolve_character_identity(
    index: DanbooruTagIndex,
    *,
    target_query: str,
    canonical_tag: str = "",
    identity_candidates: Sequence[str] = (),
    work_hints: Sequence[str] = (),
    allow_discovery: bool = True,
) -> CharacterIdentityResolution:
    """Resolve one character using local verified evidence only."""

    specs = _lookup_specs(
        target_query,
        canonical_tag,
        identity_candidates,
        work_hints,
    )
    if not specs:
        return CharacterIdentityResolution()

    lookups = _lookup_many(index, [spec.value for spec in specs])
    exact_hits: list[tuple[_LookupSpec, TagLookup, str]] = []
    for spec, lookup in zip(specs, lookups):
        if not _verified_hit(lookup, spec.expected_work):
            continue
        canonical = normalize_tag(lookup.canonical_tag or lookup.tag)
        exact_hits.append((spec, lookup, canonical))

    unique_exact = tuple(dict.fromkeys(hit[2] for hit in exact_hits))
    if len(unique_exact) == 1:
        selected = next(hit for hit in exact_hits if hit[2] == unique_exact[0])
        return CharacterIdentityResolution(
            canonical_tag=unique_exact[0],
            verified=True,
            match_variant=selected[0].variant,
            match_type=str(getattr(selected[1], "match_type", "") or "exact"),
            query_count=len(specs),
            candidate_count=1,
            candidates=unique_exact,
        )
    if len(unique_exact) > 1:
        return CharacterIdentityResolution(
            ambiguous=True,
            match_variant="exact_conflict",
            query_count=len(specs),
            candidate_count=len(unique_exact),
            candidates=unique_exact[:8],
        )
    if not allow_discovery:
        return CharacterIdentityResolution(query_count=len(specs))

    discovered: dict[str, TagCandidate] = {}
    for spec in specs[:12]:
        # Work-qualified full tags are poor discovery seeds; their safe stripped
        # alias is already present as a separate spec.
        if "_(" in spec.value:
            continue
        for mode in ("prefix", "keyword"):
            for candidate in index.search(
                spec.value,
                mode=mode,
                category="character",
                limit=12,
            ):
                canonical = _candidate_canonical(candidate)
                if not canonical or not _work_matches(canonical, spec.expected_work):
                    continue
                discovered.setdefault(canonical, candidate)

    if not discovered:
        return CharacterIdentityResolution(query_count=len(specs))

    # Discovery results are hints.  Re-run exact on every canonical before they
    # participate in deterministic grouping.
    verified = _lookup_many(index, tuple(discovered))
    verified_tags = tuple(
        normalize_tag(item.canonical_tag or item.tag)
        for item in verified
        if _verified_hit(item, "")
    )
    roots: dict[str, list[str]] = {}
    for tag in dict.fromkeys(verified_tags):
        roots.setdefault(_identity_root(tag), []).append(tag)
    if len(roots) != 1:
        candidates = tuple(dict.fromkeys(verified_tags))[:8]
        return CharacterIdentityResolution(
            ambiguous=len(roots) > 1,
            match_variant="discovery_ambiguous" if len(roots) > 1 else "none",
            query_count=len(specs),
            candidate_count=len(candidates),
            candidates=candidates,
        )

    root, variants = next(iter(roots.items()))
    canonical = root if root in variants else min(
        variants,
        key=lambda item: (len(_qualifiers(item)), -int(discovered[item].count), item),
    )
    final_lookup = index.lookup(canonical, "character")
    if not _verified_hit(final_lookup, _work_qualifier(canonical)):
        return CharacterIdentityResolution(
            query_count=len(specs),
            candidate_count=len(verified_tags),
        )
    return CharacterIdentityResolution(
        canonical_tag=normalize_tag(final_lookup.canonical_tag or final_lookup.tag),
        verified=True,
        match_variant="local_discovery_unique_identity",
        match_type=str(getattr(final_lookup, "match_type", "") or "canonical"),
        query_count=len(specs),
        candidate_count=len(verified_tags),
        candidates=tuple(dict.fromkeys(verified_tags))[:8],
    )


__all__ = [
    "CharacterIdentityResolution",
    "character_identity_lookup_candidates",
    "resolve_character_identity",
]
