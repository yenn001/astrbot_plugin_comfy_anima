"""Character authority and purity primitives for image prompts.

The authority is the single allowed-character set that travels through
intent, Director, character compiler and final workflow submission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class CharacterAuthority:
    identity_anchor: str
    allowed_extra_characters: tuple[str, ...] = ()
    cosplay_source: str = ""
    forbid_other_characters: bool = True

    def allowed_canonicals(self) -> tuple[str, ...]:
        values = [self.identity_anchor, *self.allowed_extra_characters]
        if self.cosplay_source:
            values.append(self.cosplay_source)
        return tuple(dict.fromkeys(value for value in values if value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_anchor": self.identity_anchor,
            "allowed_extra_characters": list(self.allowed_extra_characters),
            "cosplay_source": self.cosplay_source,
            "forbid_other_characters": self.forbid_other_characters,
        }


def normalize_character_key(value: str) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", " ", text).strip(" ,()")


def split_character_declarations(text: str) -> tuple[str, ...]:
    """Return explicit A/B character names from simple declarations."""
    source = str(text or "")
    parts = re.split(
        r"(?:和|与|、|,|，|跟)(?![^(]*\))",
        source,
    )
    return tuple(part.strip() for part in parts if part.strip())


@dataclass(frozen=True)
class PurityResult:
    prompt: str
    removed_characters: tuple[str, ...]
    blocked: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "removed_characters": list(self.removed_characters),
            "blocked": self.blocked,
            "reason": self.reason,
        }


class CharacterPurityFilter:
    """Remove unexpected character canonicals from the final prompt."""

    def __init__(
        self,
        forbidden_canonicals: Iterable[str] = (),
    ) -> None:
        self._forbidden = tuple(
            (normalize_character_key(value), str(value).strip())
            for value in forbidden_canonicals
        )

    def purify(
        self,
        prompt: str,
        authority: CharacterAuthority,
    ) -> PurityResult:
        if not authority.forbid_other_characters:
            return PurityResult(
                prompt=str(prompt or ""),
                removed_characters=(),
                reason="purity_disabled",
            )
        allowed = {
            normalize_character_key(value)
            for value in authority.allowed_canonicals()
        }
        if authority.cosplay_source:
            cosplay_base = re.sub(
                r"_\(cosplay\)$",
                "",
                authority.cosplay_source,
                flags=re.IGNORECASE,
            )
            allowed.add(normalize_character_key(cosplay_base))
        source = str(prompt or "")
        removed: list[str] = []
        for normalized, canonical in self._forbidden:
            if normalized in allowed:
                continue
            for candidate in self._match_candidates(canonical):
                pattern = rf"\s*,?\s*{re.escape(candidate)}\s*,?\s*"
                if re.search(pattern, source, flags=re.IGNORECASE):
                    source = re.sub(pattern, " ", source, flags=re.IGNORECASE)
                    removed.append(canonical)
        blocked = bool(self._forbidden and not removed and _count_unknown_characters(source) > len(allowed))
        return PurityResult(
            prompt=re.sub(r"\s+", " ", source).strip(" ,"),
            removed_characters=tuple(dict.fromkeys(removed)),
            blocked=blocked,
            reason="unexpected_characters_blocked" if blocked else "ok",
        )

    @staticmethod
    def _match_candidates(canonical: str) -> tuple[str, ...]:
        value = str(canonical or "").strip()
        if not value:
            return ()
        candidates = [value]
        if value.count(" ") == 1:
            left, right = value.split(" ", 1)
            candidates.extend([left, right])
        return tuple(dict.fromkeys(candidates))


def _count_unknown_characters(prompt: str) -> int:
    # Character tags are approximated by parenthesised Danbooru canonicals.
    return len(
        re.findall(
            r"\([a-z0-9_ ()-]*(?:\([a-z0-9_ -]+\))?\)",
            str(prompt or "").casefold(),
        )
    )


__all__ = [
    "CharacterAuthority",
    "CharacterPurityFilter",
    "PurityResult",
    "normalize_character_key",
    "split_character_declarations",
]
