"""Deterministic identity binding for explicitly named subjects.

One user-requested subject must resolve to exactly one verified canonical
before generation. Multiple verified canonicals are a hard error, never a
random pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class IdentityBindingError(RuntimeError):
    """Raised when a named subject cannot bind to exactly one canonical."""


@dataclass(frozen=True)
class IdentityBinding:
    subject: str
    canonical: str
    work: str = ""
    activation_terms: tuple[str, ...] = ()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _canonical_candidates(
    subject: str,
    evidence: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized = _clean(subject)
    matches: list[dict[str, Any]] = []
    for item in evidence:
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            continue
        names = [
            str(item.get("name") or ""),
            str(item.get("alias") or ""),
            *[
                str(term)
                for term in (item.get("activation_terms") or ())
                if term is not None
            ],
        ]
        cleaned_names = {_clean(name) for name in names if name.strip()}
        if normalized in cleaned_names:
            matches.append(
                {
                    "canonical": canonical,
                    "work": str(item.get("work") or "").strip(),
                    "activation_terms": tuple(
                        str(term)
                        for term in (item.get("activation_terms") or ())
                        if term is not None
                    ),
                }
            )
    return matches


def resolve_requested_subject_binding(
    subject: str,
    *,
    evidence: Sequence[Mapping[str, Any]],
    allowed_canonicals: Sequence[str] = (),
) -> IdentityBinding:
    """Resolve one named subject to one verified canonical or fail closed."""

    if not str(subject or "").strip():
        raise IdentityBindingError("subject is empty")
    allowed = {str(value).strip() for value in allowed_canonicals if str(value).strip()}
    candidates = _canonical_candidates(subject, evidence)
    if allowed:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["canonical"] in allowed
        ]
    unique = {candidate["canonical"] for candidate in candidates}
    if not unique:
        raise IdentityBindingError(f"no verified binding for subject: {subject!r}")
    if len(unique) > 1:
        raise IdentityBindingError(
            "multiple verified canonicals for subject "
            f"{subject!r}: {', '.join(sorted(unique))}"
        )
    candidate = candidates[0]
    return IdentityBinding(
        subject=str(subject).strip(),
        canonical=candidate["canonical"],
        work=candidate["work"],
        activation_terms=candidate["activation_terms"],
    )


def identity_required_for_subject(subject: str) -> bool:
    """Return whether a named subject must resolve before generation."""

    return bool(str(subject or "").strip())


__all__ = [
    "IdentityBinding",
    "IdentityBindingError",
    "identity_required_for_subject",
    "resolve_requested_subject_binding",
]
