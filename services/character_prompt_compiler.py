"""Deterministic character validation and correction for LLM-generated prompts."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable, Sequence

from .character_swap import (
    FEATURE_BODY_SHAPE,
    FEATURE_EAR_SHAPE,
    FEATURE_EYE_COLOR,
    FEATURE_HAIR_COLOR,
    FEATURE_HAIR_ORNAMENT,
    FEATURE_HAIR_STYLE,
    FEATURE_UNIQUE_BODY_PARTS,
    _character_feature_categories_for_term,
    _dedupe_prompt_terms,
    _prompt_term_key,
    _split_prompt_terms,
    _target_identity_insert_index,
)
from .danbooru_index import escape_prompt_tag, normalize_tag


class CharacterPromptCompileError(ValueError):
    """A named-character LLM prompt cannot be verified safely."""

    def __init__(
        self,
        user_message: str,
        *,
        code: str = "character_prompt_invalid",
        details: dict[str, object] | None = None,
    ) -> None:
        self.user_message = user_message
        self.code = code
        self.details = dict(details or {})
        super().__init__(user_message)


@dataclass(frozen=True)
class CharacterPromptEvidence:
    """One exact-confirmed character and its bounded appearance evidence."""

    query: str
    canonical_tag: str
    appearance_terms: tuple[str, ...] = ()
    appearance_source: str = ""
    match_variant: str = ""
    query_count: int = 0
    candidate_count: int = 0
    confirmed_work: str = ""


@dataclass(frozen=True)
class CharacterPromptCompilation:
    """A corrected prompt plus privacy-safe diagnostics."""

    prompt: str
    negative_prompt: str
    canonical_tags: tuple[str, ...] = ()
    removed_terms: tuple[str, ...] = ()
    added_terms: tuple[str, ...] = ()
    dropped_relation_terms: tuple[str, ...] = ()
    override_categories: tuple[str, ...] = ()
    appearance_sources: tuple[str, ...] = ()


_FEATURE_ORDER = (
    FEATURE_HAIR_STYLE,
    FEATURE_HAIR_COLOR,
    FEATURE_HAIR_ORNAMENT,
    FEATURE_EYE_COLOR,
    FEATURE_UNIQUE_BODY_PARTS,
    FEATURE_BODY_SHAPE,
    FEATURE_EAR_SHAPE,
)


def _normalized_words(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace(r"\(", "(").replace(r"\)", ")")
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\bhaired\b", "hair", text)
    return re.sub(r"\s+", " ", text).strip()


def appearance_override_categories(value: str) -> tuple[str, ...]:
    """Return physical slots the user explicitly requested to customize."""

    text = _normalized_words(value)
    categories: set[str] = set()
    if re.search(
        r"\b(?:hair|hairstyle|bangs|ponytail|twintails?|braids?|hair bun)\b|"
        r"头发|发型|刘海|马尾|双马尾|辫子|盘发|呆毛|短发|长发|中长发",
        text,
    ):
        categories.add(FEATURE_HAIR_STYLE)
    if re.search(
        r"\b(?:black|blonde|brown|red|blue|green|purple|pink|white|silver|"
        r"grey|gray|orange|yellow|aqua|teal|cyan|golden|multicolored|gradient)"
        r"\s+hair\b|发色|黑发|白发|银发|灰发|金发|棕发|红发|蓝发|绿发|"
        r"紫发|粉发|橙发|渐变发|彩发|"
        r"(?:黑|白|银|灰|金|棕|红|蓝|绿|紫|粉|橙)色(?:头发|短发|长发)",
        text,
    ):
        categories.add(FEATURE_HAIR_COLOR)
    if re.search(
        r"\b(?:hair ornament|hairclip|hair ribbon|hair bow|hair flower|"
        r"hair pin|hairband|headband)\b|发饰|发夹|发带|头饰",
        text,
    ):
        categories.add(FEATURE_HAIR_ORNAMENT)
    if re.search(
        r"\b(?:eyes?|heterochromia|pupils?)\b|眼睛|眼色|瞳色|异色瞳|瞳孔",
        text,
    ):
        categories.add(FEATURE_EYE_COLOR)
    if re.search(
        r"\b(?:halo|horns?|tails?|wings?|fangs?|freckles|mole|beauty mark|"
        r"scar|tattoo|angel|demon|elf|vampire)\b|光环|角|尾巴|翅膀|獠牙|"
        r"雀斑|痣|泪痣|伤疤|纹身|天使|恶魔|精灵|吸血鬼",
        text,
    ):
        categories.add(FEATURE_UNIQUE_BODY_PARTS)
    if re.search(
        r"\b(?:petite|slender|slim|curvy|muscular|tall|short stature|"
        r"small breasts|medium breasts|large breasts|huge breasts|wide hips|"
        r"narrow waist|pear shaped|hourglass)\b|体型|身材|娇小|高挑|纤细|"
        r"丰满|肌肉|贫乳|小胸|巨乳|大胸|宽臀|细腰|梨形|沙漏",
        text,
    ):
        categories.add(FEATURE_BODY_SHAPE)
    if re.search(
        r"\b(?:animal|cat|fox|wolf|dog|horse|rabbit|bunny|elf|pointed) ears\b|"
        r"耳型|兽耳|猫耳|狐耳|狼耳|犬耳|马耳|兔耳|精灵耳|尖耳",
        text,
    ):
        categories.add(FEATURE_EAR_SHAPE)
    return tuple(category for category in _FEATURE_ORDER if category in categories)


def _work_qualifier(canonical: str) -> str:
    value = normalize_tag(canonical)
    match = re.search(r"_\(([^()]+)\)$", value)
    return normalize_tag(match.group(1)) if match else ""


def _contains_removed_fragment(term: str, removed: Sequence[str]) -> bool:
    container = f" {_normalized_words(term)} "
    if "." not in term and len(container.split()) < 8:
        return False
    for value in removed:
        fragment = _normalized_words(value)
        if len(fragment) < 3:
            continue
        if f" {fragment} " in container:
            return True
    return False


def _appearance_map(values: Iterable[str]) -> dict[str, tuple[str, ...]]:
    collected: dict[str, list[str]] = {category: [] for category in _FEATURE_ORDER}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        for category in _character_feature_categories_for_term(text):
            if category in collected:
                collected[category].append(text)
    return {
        category: _dedupe_prompt_terms(terms)
        for category, terms in collected.items()
        if terms
    }


def _explicit_costume_accessory(term: str, user_request: str) -> bool:
    """Protect deterministic costume props that merely resemble body features."""

    request = _normalized_words(user_request)
    if not re.search(
        r"\b(?:playboy bunny|bunny girl|rabbit girl)\b|兔女郎|兔娘",
        request,
    ):
        return False
    value = _normalized_words(term)
    return bool(
        re.fullmatch(
            r"(?:rabbit|bunny|animal) ear (?:hairband|headband)|"
            r"fake (?:rabbit|bunny|animal) ears",
            value,
        )
    )


def split_character_validation_terms(value: str) -> tuple[str, ...]:
    """Expose the prompt splitter used by character validation and correction."""

    return _split_prompt_terms(value)


def compile_character_prompt(
    prompt: str,
    negative_prompt: str,
    evidences: Sequence[CharacterPromptEvidence],
    *,
    prompt_character_terms: Sequence[tuple[str, str]] = (),
    prompt_copyright_terms: Sequence[tuple[str, str]] = (),
    user_request: str = "",
) -> CharacterPromptCompilation:
    """Canonicalize exact characters and remove unsupported LLM appearance guesses."""

    verified = tuple(
        evidence
        for evidence in evidences
        if normalize_tag(evidence.canonical_tag)
    )
    if not verified:
        return CharacterPromptCompilation(
            prompt=str(prompt or "").strip(" ,"),
            negative_prompt=str(negative_prompt or "").strip(" ,"),
        )

    canonical_by_key = {
        _prompt_term_key(evidence.canonical_tag): normalize_tag(evidence.canonical_tag)
        for evidence in verified
    }
    allowed_keys = frozenset(canonical_by_key)
    canonical_tags = tuple(dict.fromkeys(canonical_by_key.values()))
    expected_works = frozenset(
        work
        for evidence in verified
        for value in (
            _work_qualifier(evidence.canonical_tag),
            normalize_tag(evidence.confirmed_work),
        )
        if (work := normalize_tag(value))
    )
    character_by_source = {
        _prompt_term_key(source): normalize_tag(canonical)
        for source, canonical in prompt_character_terms
        if _prompt_term_key(source) and normalize_tag(canonical)
    }
    copyright_by_source = {
        _prompt_term_key(source): normalize_tag(canonical)
        for source, canonical in prompt_copyright_terms
        if _prompt_term_key(source) and normalize_tag(canonical)
    }
    override_categories = appearance_override_categories(user_request)
    override_set = frozenset(override_categories)
    trusted_appearance = (
        _dedupe_prompt_terms(verified[0].appearance_terms)
        if len(verified) == 1
        else ()
    )
    trusted_by_category = _appearance_map(trusted_appearance)
    trusted_keys = {
        _prompt_term_key(term)
        for term in trusted_appearance
        if _prompt_term_key(term)
    }

    kept: list[str] = []
    removed: list[str] = []
    for term in _split_prompt_terms(prompt):
        key = _prompt_term_key(term)
        if not key:
            continue
        exact_character = character_by_source.get(key, "")
        if exact_character:
            if _prompt_term_key(exact_character) not in allowed_keys:
                removed.append(term)
            continue
        exact_copyright = copyright_by_source.get(key, "")
        if exact_copyright:
            if normalize_tag(exact_copyright) not in expected_works:
                removed.append(term)
                continue
            kept.append(escape_prompt_tag(exact_copyright))
            continue

        categories = _character_feature_categories_for_term(term)
        if len(verified) == 1 and categories:
            if _explicit_costume_accessory(term, user_request):
                kept.append(term)
                continue
            if any(category in override_set for category in categories):
                kept.append(term)
                continue
            if key in trusted_keys:
                kept.append(term)
                continue
            # Exact identity is authoritative. Unsupported physical details are
            # deleted rather than inherited from model memory or another role.
            removed.append(term)
            continue
        kept.append(term)

    dropped_relation: list[str] = []
    if removed:
        corrected: list[str] = []
        for term in kept:
            if _contains_removed_fragment(term, removed):
                dropped_relation.append(term)
            else:
                corrected.append(term)
        kept = corrected

    additions = [escape_prompt_tag(canonical) for canonical in canonical_tags]
    if len(verified) == 1:
        for category in _FEATURE_ORDER:
            if category in override_set:
                continue
            additions.extend(trusted_by_category.get(category, ()))
    additions = list(_dedupe_prompt_terms(additions))
    existing_keys = {_prompt_term_key(term) for term in kept}
    inserted = [term for term in additions if _prompt_term_key(term) not in existing_keys]
    insert_at = _target_identity_insert_index(kept)
    final_terms = _dedupe_prompt_terms((*kept[:insert_at], *inserted, *kept[insert_at:]))

    protected_negative_keys = {
        *allowed_keys,
        *({_prompt_term_key(term) for term in trusted_appearance}),
    }
    protected_negative_categories = frozenset(
        (*trusted_by_category.keys(), *override_categories)
    )
    final_negative = _dedupe_prompt_terms(
        term
        for term in _split_prompt_terms(negative_prompt)
        if (
            _prompt_term_key(term) not in protected_negative_keys
            and not (
                len(verified) == 1
                and protected_negative_categories.intersection(
                    _character_feature_categories_for_term(term)
                )
            )
        )
    )
    return CharacterPromptCompilation(
        prompt=", ".join(final_terms),
        negative_prompt=", ".join(final_negative),
        canonical_tags=canonical_tags,
        removed_terms=_dedupe_prompt_terms(removed),
        added_terms=tuple(inserted),
        dropped_relation_terms=_dedupe_prompt_terms(dropped_relation),
        override_categories=override_categories,
        appearance_sources=tuple(
            dict.fromkeys(
                evidence.appearance_source
                for evidence in verified
                if evidence.appearance_source
            )
        ),
    )
