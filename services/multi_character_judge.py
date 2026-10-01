"""Deterministic multi-character request judge.

Decides whether a request is dual-character, cosplay, ambiguous or blocked,
and builds the corresponding CharacterAuthority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .character_authority import CharacterAuthority, normalize_character_key

DUAL_DECISION = "dual_contract"
COSPLAY_DECISION = "cosplay_contract"
CLARIFY_DECISION = "clarify"
SINGLE_DECISION = "single"
BLOCKED_DECISION = "blocked"

_DUAL_RE = re.compile(
    r"(?:同框|双人|一起|两个角色|两个人|和(.+?)站在一起|跟(.+?)一起)",
    flags=re.IGNORECASE,
)
_COSPLAY_RE = re.compile(
    r"(?:cos|cosplay|穿(.+?)(?:的|那套|同款)?(?:衣服|造型|服装)|"
    r"扮演(.+?)|装扮成(.+?)|打扮成(.+?)|仿(.+?)|还原(.+?))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class MultiCharacterDecision:
    decision: str
    authority: CharacterAuthority
    characters: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "authority": self.authority.to_dict(),
            "characters": list(self.characters),
            "reason": self.reason,
        }


class MultiCharacterJudge:
    """Classify N>=2 character requests with explicit/ambiguous separation."""

    def __init__(
        self,
        known_characters: Iterable[str] = (),
        cosplay_tag_resolver: Any | None = None,
    ) -> None:
        self._known = {
            normalize_character_key(value): value for value in known_characters
        }
        self._cosplay_tag_resolver = cosplay_tag_resolver

    def judge(
        self,
        text: str,
        *,
        detected_characters: tuple[str, ...] = (),
    ) -> MultiCharacterDecision:
        source = str(text or "")
        characters = tuple(
            dict.fromkeys(str(value).strip() for value in detected_characters if value)
        )
        if len(characters) < 2:
            anchor = characters[0] if characters else ""
            return MultiCharacterDecision(
                decision=SINGLE_DECISION,
                authority=CharacterAuthority(identity_anchor=anchor),
                characters=characters,
                reason="single_character",
            )
        if len(characters) >= 3:
            return MultiCharacterDecision(
                decision=BLOCKED_DECISION,
                authority=CharacterAuthority(identity_anchor=characters[0]),
                characters=characters,
                reason="three_or_more_requires_confirmation",
            )
        cosplay_match = _COSPLAY_RE.search(source)
        if cosplay_match:
            target = next(
                (group for group in cosplay_match.groups() if group),
                "",
            )
            if not target and len(characters) > 1:
                target = characters[1]
            if target:
                anchor = characters[0]
                if self._cosplay_tag_resolver is not None:
                    resolved = self._cosplay_tag_resolver(target)
                else:
                    resolved = f"{target}_(cosplay)"
                return MultiCharacterDecision(
                    decision=COSPLAY_DECISION,
                    authority=CharacterAuthority(
                        identity_anchor=anchor,
                        cosplay_source=resolved,
                    ),
                    characters=(anchor, resolved),
                    reason="cosplay_contract",
                )
        if _DUAL_RE.search(source):
            return MultiCharacterDecision(
                decision=DUAL_DECISION,
                authority=CharacterAuthority(
                    identity_anchor=characters[0],
                    allowed_extra_characters=characters[1:],
                ),
                characters=characters,
                reason="explicit_dual",
            )
        return MultiCharacterDecision(
            decision=CLARIFY_DECISION,
            authority=CharacterAuthority(identity_anchor=characters[0]),
            characters=characters,
            reason="ambiguous_a_and_b",
        )


__all__ = [
    "BLOCKED_DECISION",
    "CLARIFY_DECISION",
    "COSPLAY_DECISION",
    "DUAL_DECISION",
    "SINGLE_DECISION",
    "MultiCharacterDecision",
    "MultiCharacterJudge",
]
