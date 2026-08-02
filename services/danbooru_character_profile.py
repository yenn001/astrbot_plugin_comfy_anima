"""Evidence-backed stable appearance profiles for exact Danbooru characters.

The local tag index proves *who* a character is, but it does not associate the
character with general appearance tags.  This module derives a very small
profile from public, safe-rated Danbooru post metadata returned by the trusted
ComfyUI Danbooru Gallery endpoint.  Raw posts are never persisted.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Mapping, Sequence

from .danbooru_index import normalize_tag


PROFILE_SCHEMA = "astrbot-comfy-anima-character-profile"
PROFILE_VERSION = 2
DEFAULT_PROFILE_TTL_SECONDS = 7 * 24 * 60 * 60
MIN_PROFILE_SAMPLES = 12
MIN_PROFILE_SUPPORT = 0.65
MAX_PROFILE_TAGS = 10
MAX_PROFILE_RECORDS = 2048
MIN_EXCLUSIVE_SLOT_COVERAGE = 0.25
MIN_ADDITIVE_SLOT_COVERAGE = 0.50

_HAIR_COLOURS = frozenset(
    {
        "aqua_hair",
        "black_hair",
        "blonde_hair",
        "blue_hair",
        "brown_hair",
        "green_hair",
        "grey_hair",
        "multicolored_hair",
        "orange_hair",
        "pink_hair",
        "purple_hair",
        "red_hair",
        "silver_hair",
        "two-tone_hair",
        "white_hair",
    }
)
_EYE_COLOURS = frozenset(
    {
        "aqua_eyes",
        "black_eyes",
        "blue_eyes",
        "brown_eyes",
        "green_eyes",
        "grey_eyes",
        "orange_eyes",
        "pink_eyes",
        "purple_eyes",
        "red_eyes",
        "white_eyes",
        "yellow_eyes",
    }
)
_HAIR_LENGTHS = frozenset(
    {
        "very_long_hair",
        "long_hair",
        "medium_hair",
        "short_hair",
    }
)
_HAIR_STYLES = frozenset(
    {
        "bob_cut",
        "braid",
        "double_bun",
        "drill_hair",
        "hair_bun",
        "high_ponytail",
        "hime_cut",
        "low_ponytail",
        "one_side_up",
        "ponytail",
        "short_twintails",
        "side_braid",
        "side_ponytail",
        "single_braid",
        "single_side_bun",
        "twin_braids",
        "twintails",
    }
)
_HAIR_ORNAMENTS = frozenset(
    {
        "hair_bow",
        "hair_flower",
        "hair_ornament",
        "hair_pin",
        "hair_ribbon",
        "hairband",
        "hairclip",
        "x_hair_ornament",
    }
)
_FACIAL_OR_BODY_MARKS = frozenset(
    {
        "ahoge",
        "dark_skin",
        "eyepatch",
        "facial_mark",
        "fang",
        "freckles",
        "glasses",
        "halo",
        "heterochromia",
        "mole",
        "mole_under_eye",
        "mole_under_mouth",
        "scar",
        "tan",
        "tattoo",
    }
)
_SPECIES_OR_UNIQUE_PARTS = frozenset(
    {
        "animal_ears",
        "cat_ears",
        "demon_horns",
        "elf",
        "fox_ears",
        "horns",
        "pointy_ears",
        "rabbit_ears",
        "tail",
        "wings",
    }
)
_BODY_SHAPES = frozenset({"petite", "slender", "tall", "short_stature"})
_DEFAULT_VARIANT_TAGS = frozenset(
    {
        "alternate_hair_color",
        "alternate_hairstyle",
        "cosplay",
        "genderbend",
        "palette_swap",
    }
)


def _prompt_form(tag: str) -> str:
    return normalize_tag(tag).replace("_", " ")


_ALLOWED_PROFILE_TAGS = frozenset(
    _prompt_form(tag)
    for tag in (
        _HAIR_COLOURS
        | _EYE_COLOURS
        | _HAIR_LENGTHS
        | _HAIR_STYLES
        | _HAIR_ORNAMENTS
        | _FACIAL_OR_BODY_MARKS
        | _SPECIES_OR_UNIQUE_PARTS
        | _BODY_SHAPES
    )
)
_CANONICAL_TAG_RE = re.compile(r"[a-z0-9_().!'&+:/\-]{1,160}")


@dataclass(frozen=True)
class CharacterAppearanceProfile:
    canonical_tag: str
    appearance_tags: tuple[str, ...]
    support: tuple[tuple[str, float], ...]
    sample_count: int
    fetched_at: float
    source: str = "danbooru_gallery"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["appearance_tags"] = list(self.appearance_tags)
        payload["support"] = [list(item) for item in self.support]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CharacterAppearanceProfile":
        canonical = normalize_tag(str(payload.get("canonical_tag") or ""))
        raw_tags = payload.get("appearance_tags")
        raw_support = payload.get("support")
        source = str(payload.get("source") or "").strip()
        if (
            not canonical
            or not _CANONICAL_TAG_RE.fullmatch(canonical)
            or source != "danbooru_gallery"
            or not isinstance(raw_tags, list)
            or not isinstance(raw_support, list)
        ):
            raise ValueError("invalid character profile")
        tags = tuple(
            str(item or "").strip()
            for item in raw_tags[:MAX_PROFILE_TAGS]
            if str(item or "").strip()
        )
        if (
            len(tags) < 2
            or len(tags) != len(raw_tags)
            or len(set(tags)) != len(tags)
            or any(tag not in _ALLOWED_PROFILE_TAGS for tag in tags)
        ):
            raise ValueError("invalid character profile")
        support_items: list[tuple[str, float]] = []
        for item in raw_support[:MAX_PROFILE_TAGS]:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("invalid character profile")
            tag = str(item[0] or "").strip()
            try:
                ratio = float(item[1])
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid character profile") from exc
            if (
                tag not in _ALLOWED_PROFILE_TAGS
                or not math.isfinite(ratio)
                or not MIN_PROFILE_SUPPORT <= ratio <= 1.0
            ):
                raise ValueError("invalid character profile")
            support_items.append((tag, ratio))
        fetched_at = float(payload.get("fetched_at") or 0.0)
        sample_count = int(payload.get("sample_count") or 0)
        if (
            tuple(tag for tag, _ratio in support_items) != tags
            or len(support_items) != len(raw_support)
            or not math.isfinite(fetched_at)
            or fetched_at <= 0.0
            or fetched_at > time.time() + 300.0
            or not MIN_PROFILE_SAMPLES <= sample_count <= 1000
        ):
            raise ValueError("invalid character profile")
        return cls(
            canonical_tag=canonical,
            appearance_tags=tags,
            support=tuple(support_items),
            sample_count=sample_count,
            fetched_at=fetched_at,
            source=source,
        )


def _flag_is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _slot_supported(
    counts: Mapping[str, int],
    valid_posts: Sequence[set[str]],
    candidates: frozenset[str],
    sample_count: int,
    minimum_support: float,
    *,
    minimum_coverage: float,
    limit: int = 1,
    specificity: Mapping[str, int] | None = None,
) -> tuple[tuple[str, float], ...]:
    slot_total = sum(1 for tags in valid_posts if tags & candidates)
    if slot_total <= 0 or slot_total / sample_count < minimum_coverage:
        return ()
    specificity = specificity or {}
    ranked = sorted(
        (
            (tag, count / slot_total)
            for tag, count in counts.items()
            if tag in candidates and count / slot_total >= minimum_support
        ),
        key=lambda item: (-specificity.get(item[0], 0), -item[1], item[0]),
    )
    return tuple(ranked[: max(1, limit)])


def build_character_appearance_profile(
    canonical_tag: str,
    posts: Sequence[Mapping[str, Any]],
    *,
    minimum_samples: int = MIN_PROFILE_SAMPLES,
    minimum_support: float = MIN_PROFILE_SUPPORT,
    maximum_tags: int = MAX_PROFILE_TAGS,
    fetched_at: float | None = None,
) -> CharacterAppearanceProfile | None:
    """Aggregate a bounded stable-appearance profile from verified safe posts."""

    canonical = normalize_tag(canonical_tag)
    if not canonical:
        return None
    minimum_samples = max(MIN_PROFILE_SAMPLES, int(minimum_samples))
    minimum_support = min(0.95, max(0.5, float(minimum_support)))
    maximum_tags = min(MAX_PROFILE_TAGS, max(1, int(maximum_tags)))
    valid_posts: list[set[str]] = []
    seen_post_ids: set[int] = set()
    for post in posts:
        if not isinstance(post, Mapping):
            continue
        rating = str(post.get("rating") or "").strip().casefold()
        if rating != "g" or any(
            _flag_is_true(post.get(field))
            for field in ("is_deleted", "is_pending", "is_flagged", "is_banned")
        ):
            continue
        try:
            post_id = int(post.get("id"))
        except (TypeError, ValueError):
            continue
        if post_id <= 0 or post_id in seen_post_ids:
            continue
        character_tags = {
            normalize_tag(item)
            for item in str(post.get("tag_string_character") or "").split()
            if normalize_tag(item)
        }
        if character_tags != {canonical}:
            continue
        general_tags = {
            normalize_tag(item)
            for item in str(post.get("tag_string_general") or "").split()
            if normalize_tag(item)
        }
        if "solo" not in general_tags:
            continue
        if general_tags & _DEFAULT_VARIANT_TAGS:
            continue
        seen_post_ids.add(post_id)
        valid_posts.append(general_tags)
    sample_count = len(valid_posts)
    if sample_count < minimum_samples:
        return None
    counts: dict[str, int] = {}
    for tags in valid_posts:
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1

    slot_specs = (
        (_HAIR_COLOURS, MIN_EXCLUSIVE_SLOT_COVERAGE, 1, {}),
        (_EYE_COLOURS, MIN_EXCLUSIVE_SLOT_COVERAGE, 1, {}),
        (_HAIR_LENGTHS, MIN_EXCLUSIVE_SLOT_COVERAGE, 1, {}),
        (
            _HAIR_STYLES,
            MIN_ADDITIVE_SLOT_COVERAGE,
            2,
            {
                "single_side_bun": 4,
                "double_bun": 4,
                "one_side_up": 3,
                "hair_bun": 2,
                "side_ponytail": 2,
                "ponytail": 1,
                "braid": 1,
            },
        ),
        (
            _HAIR_ORNAMENTS,
            MIN_ADDITIVE_SLOT_COVERAGE,
            2,
            {
                "x_hair_ornament": 4,
                "hairclip": 3,
                "hair_pin": 3,
                "hair_flower": 3,
                "hair_bow": 2,
                "hair_ribbon": 2,
                "hair_ornament": 1,
            },
        ),
        (
            _FACIAL_OR_BODY_MARKS,
            MIN_ADDITIVE_SLOT_COVERAGE,
            2,
            {
                "mole_under_mouth": 4,
                "mole_under_eye": 4,
                "facial_mark": 3,
                "mole": 1,
            },
        ),
        (_SPECIES_OR_UNIQUE_PARTS, MIN_ADDITIVE_SLOT_COVERAGE, 2, {}),
        (_BODY_SHAPES, MIN_ADDITIVE_SLOT_COVERAGE, 1, {}),
    )
    selected: list[tuple[str, float]] = []
    for group, coverage, limit, specificity in slot_specs:
        for candidate in _slot_supported(
            counts,
            valid_posts,
            group,
            sample_count,
            minimum_support,
            minimum_coverage=coverage,
            limit=limit,
            specificity=specificity,
        ):
            if candidate[0] in {item[0] for item in selected}:
                continue
            selected.append(candidate)
            if len(selected) >= maximum_tags:
                break
        if len(selected) >= maximum_tags:
            break
    if len(selected) < 2:
        return None
    prompt_support = tuple((_prompt_form(tag), ratio) for tag, ratio in selected)
    return CharacterAppearanceProfile(
        canonical_tag=canonical,
        appearance_tags=tuple(tag for tag, _ratio in prompt_support),
        support=prompt_support,
        sample_count=sample_count,
        fetched_at=time.time() if fetched_at is None else float(fetched_at),
    )


class CharacterAppearanceProfileStore:
    """Small atomic cache containing aggregates only, never raw post metadata."""

    def __init__(
        self,
        path: str | Path,
        *,
        ttl_seconds: int = DEFAULT_PROFILE_TTL_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(3600, int(ttl_seconds))
        self._lock = threading.RLock()

    def get(self, canonical_tag: str) -> CharacterAppearanceProfile | None:
        canonical = normalize_tag(canonical_tag)
        if not canonical:
            return None
        with self._lock:
            state = self._load()
            raw = state["profiles"].get(canonical)
            if not isinstance(raw, Mapping):
                return None
            try:
                profile = CharacterAppearanceProfile.from_dict(raw)
            except (TypeError, ValueError):
                return None
            if profile.canonical_tag != canonical:
                return None
            age = time.time() - profile.fetched_at
            if age < -300.0 or age > self.ttl_seconds:
                return None
            return profile

    def put(self, profile: CharacterAppearanceProfile) -> None:
        with self._lock:
            state = self._load()
            profiles = state["profiles"]
            profiles[profile.canonical_tag] = profile.as_dict()
            if len(profiles) > MAX_PROFILE_RECORDS:
                ordered = sorted(
                    profiles.items(),
                    key=lambda item: float(item[1].get("fetched_at") or 0.0),
                    reverse=True,
                )[:MAX_PROFILE_RECORDS]
                state["profiles"] = dict(ordered)
            self._save(state)

    def _load(self) -> dict[str, Any]:
        empty = {
            "schema": PROFILE_SCHEMA,
            "version": PROFILE_VERSION,
            "profiles": {},
        }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return empty
        if (
            not isinstance(raw, Mapping)
            or raw.get("schema") != PROFILE_SCHEMA
            or int(raw.get("version") or 0) != PROFILE_VERSION
            or not isinstance(raw.get("profiles"), Mapping)
        ):
            return empty
        return {
            "schema": PROFILE_SCHEMA,
            "version": PROFILE_VERSION,
            "profiles": dict(raw["profiles"]),
        }

    def _save(self, state: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write(payload)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
