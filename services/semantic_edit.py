"""Deterministic semantic-edit constraints for whole-image redraw jobs.

The LLM still writes the final Anima prompt, but this module owns the small set of
facts that must not be left to model goodwill: explicit requested concepts, source
outfit terms that a replacement must remove, and an edit-magnitude estimate used
for img2img strength selection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_SPACE_RE = re.compile(r"[\s_\-]+")
_WEIGHT_RE = re.compile(r"^\((.*?):\s*[0-9.]+\)$")


def _normalized(value: str) -> str:
    value = value.casefold().replace("’", "'")
    value = re.sub(r"[^a-z0-9<>:.'\s_-]+", " ", value)
    return _SPACE_RE.sub(" ", value).strip()


def _contains(text: str, phrase: str) -> bool:
    haystack = f" {_normalized(text)} "
    needle = _normalized(phrase)
    return bool(needle) and f" {needle} " in haystack


@dataclass(frozen=True)
class RequiredConcept:
    """One user-requested visual fact with accepted English renderings."""

    code: str
    label: str
    aliases: tuple[str, ...]

    def present_in(self, prompt: str) -> bool:
        return any(_contains(prompt, alias) for alias in self.aliases)


@dataclass(frozen=True)
class SemanticEditContract:
    """Machine-checkable invariants for one whole-image semantic redraw."""

    required_positive: tuple[RequiredConcept, ...] = ()
    removed_source_terms: tuple[str, ...] = ()
    preserved_source_terms: tuple[str, ...] = ()
    magnitude: str = "unknown"

    @property
    def required_negative_terms(self) -> tuple[str, ...]:
        return self.removed_source_terms

    @property
    def suppressed_prompt_terms(self) -> tuple[str, ...]:
        return self.removed_source_terms

    def validate(self, positive_prompt: str) -> tuple[str, ...]:
        return validate_semantic_prompt(
            positive_prompt,
            required_groups=tuple(
                (concept.code, concept.aliases) for concept in self.required_positive
            ),
            forbidden_terms=self.removed_source_terms,
            preserved_terms=self.preserved_source_terms,
        )

    def repair_instruction(self, issues: tuple[str, ...]) -> str:
        required = "; ".join(
            f"{concept.label} (use one of: {', '.join(concept.aliases)})"
            for concept in self.required_positive
        ) or "none"
        removed = ", ".join(self.removed_source_terms) or "none"
        preserved = ", ".join(self.preserved_source_terms) or "none"
        return (
            "The previous candidate failed the semantic edit contract. Return a new "
            "single <pic> tag only. Required final concepts: "
            + required
            + ". Source outfit terms that must not remain in positive prompt: "
            + removed
            + ". Source pose/composition terms that must remain: "
            + preserved
            + ". Put reliable mutually exclusive source outfit terms in negative. "
            "Do not remove identity, face, hair, eye, pose or composition facts unless "
            "the user explicitly requested that change. Failure codes: "
            + ", ".join(issues)
            + "."
        )


_CONCEPT_RULES: tuple[tuple[re.Pattern[str], RequiredConcept], ...] = (
    (
        re.compile(r"(?:透明|透视|薄透|半透明|see[- ]?through|sheer).{0,8}(?:内衣|内裤|胸罩|文胸|lingerie|underwear|bra)", re.I),
        RequiredConcept(
            "transparent_underwear",
            "transparent/sheer underwear",
            (
                "transparent underwear",
                "sheer underwear",
                "see-through underwear",
                "transparent lingerie",
                "sheer lingerie",
                "see-through lingerie",
                "transparent bra",
                "sheer bra",
            ),
        ),
    ),
    (
        re.compile(r"(?:白丝|白色?丝袜|白色?大腿袜|白色?长筒袜|white thigh[- ]?high|white stocking)", re.I),
        RequiredConcept(
            "white_thighhighs",
            "white thigh-high stockings",
            (
                "white thighhighs",
                "white thigh highs",
                "white thigh-highs",
                "white thigh-high stockings",
                "white thigh high stockings",
                "white stockings",
            ),
        ),
    ),
    (
        re.compile(r"(?:三点式|比基尼|bikini)", re.I),
        RequiredConcept(
            "bikini",
            "bikini",
            ("bikini", "two-piece swimsuit", "string bikini"),
        ),
    ),
    (
        re.compile(r"(?:红色?|红)(?:晚礼服|礼服|连衣裙|裙子)|red (?:evening )?(?:dress|gown)", re.I),
        RequiredConcept(
            "red_dress",
            "red dress",
            ("red dress", "red evening dress", "red evening gown", "red gown"),
        ),
    ),
    (
        re.compile(r"(?:校服|制服|school uniform)", re.I),
        RequiredConcept(
            "school_uniform",
            "school uniform",
            ("school uniform", "student uniform"),
        ),
    ),
)


_OUTFIT_KEYWORDS = (
    "dress",
    "gown",
    "uniform",
    "shirt",
    "blouse",
    "sweater",
    "jacket",
    "coat",
    "hoodie",
    "skirt",
    "shorts",
    "pants",
    "trousers",
    "swimsuit",
    "bikini",
    "underwear",
    "lingerie",
    "bra",
    "panties",
    "stockings",
    "thighhighs",
    "thigh highs",
    "socks",
    "boots",
    "shoes",
    "sleeves",
    "necktie",
    "ribbon",
    "apron",
)
_GENERIC_OUTFIT_TERMS = {
    "clothes",
    "clothing",
    "outfit",
    "fashion",
    "bare shoulders",
    "cleavage",
}

_PRESERVE_KEYWORDS = (
    "solo",
    "1girl",
    "1boy",
    "full body",
    "upper body",
    "cowboy shot",
    "close up",
    "portrait",
    "sitting",
    "standing",
    "kneeling",
    "lying",
    "squatting",
    "crossed legs",
    "looking at viewer",
    "from above",
    "from below",
    "from side",
    "front view",
    "side view",
    "back view",
)


def _source_outfit_terms(source_positive_tags: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in str(source_positive_tags or "").split(","):
        term = raw.strip(" .\n\t")
        weighted = _WEIGHT_RE.match(term)
        if weighted:
            term = weighted.group(1).strip()
        normalized = _normalized(term)
        if not normalized or normalized in _GENERIC_OUTFIT_TERMS:
            continue
        if len(normalized) > 80 or normalized.startswith("<lora:"):
            continue
        if any(keyword in normalized for keyword in _OUTFIT_KEYWORDS):
            terms.append(normalized)
    return tuple(dict.fromkeys(terms[:10]))


def _source_preserve_terms(source_positive_tags: str, requirement: str) -> tuple[str, ...]:
    if not re.search(r"(?:构图|姿势|动作|镜头).{0,8}(?:不变|保持|保留|沿用)", requirement, re.I):
        return ()
    terms: list[str] = []
    for raw in str(source_positive_tags or "").split(","):
        normalized = _normalized(raw.strip(" .\n\t"))
        if normalized in _PRESERVE_KEYWORDS:
            terms.append(normalized)
    return tuple(dict.fromkeys(terms[:8]))


def _is_outfit_replacement(requirement: str) -> bool:
    return bool(
        re.search(
            r"(?:衣服|服装|裙子|裙装|泳装|泳衣|校服|制服|外套|上衣|内衣|内裤|胸罩|"
            r"dress|outfit|clothes|uniform|swimsuit).{0,24}"
            r"(?:换成|改成|改为|替换成|换掉|脱掉|去掉|删除|移除)|"
            r"(?:把|将).{0,18}(?:衣服|服装|裙子|泳装|泳衣|校服|制服|外套|上衣)"
            r".{0,16}(?:换成|改成|改为|替换成|换掉|脱掉|去掉|删除|移除)",
            requirement,
            re.I,
        )
    )


def classify_edit_magnitude(requirement: str) -> str:
    text = str(requirement or "")
    if _is_outfit_replacement(text) or re.search(
        r"(?:背景|场景|动作|姿势|构图|镜头|发型|角色|人物).{0,20}"
        r"(?:换成|改成|改为|替换|删除|移除)|"
        r"(?:透明内衣|三点式|比基尼|全裸|裸体|重新画|完全重画)",
        text,
        re.I,
    ):
        return "major"
    if re.search(
        r"(?:加上|增加|添加|穿上|戴上|去掉|删除|移除).{0,24}"
        r"(?:袜|鞋|靴|帽|眼镜|饰品|道具|耳环|项链|手套|stocking|sock|accessory)",
        text,
        re.I,
    ):
        return "moderate"
    if re.search(r"(?:颜色|色调|光线|表情|细节|纹理|材质|轻微|稍微)", text, re.I):
        return "minor"
    return "unknown"


def build_semantic_edit_contract(
    requirement: str,
    source_positive_tags: str,
) -> SemanticEditContract:
    concepts = tuple(
        concept for pattern, concept in _CONCEPT_RULES if pattern.search(requirement)
    )
    removed = list(
        _source_outfit_terms(source_positive_tags)
        if _is_outfit_replacement(requirement)
        else ()
    )
    if any(concept.code == "white_thighhighs" for concept in concepts):
        source_normalized = {_normalized(item) for item in source_positive_tags.split(",")}
        if "bare legs" in source_normalized:
            removed.append("bare legs")
    return SemanticEditContract(
        required_positive=tuple(dict.fromkeys(concepts)),
        removed_source_terms=tuple(dict.fromkeys(removed)),
        preserved_source_terms=_source_preserve_terms(
            source_positive_tags,
            requirement,
        ),
        magnitude=classify_edit_magnitude(requirement),
    )


def semantic_redraw_parameters(
    requirement: str,
    mode: str,
    *,
    explicit_denoise: float | None,
    explicit_steps: int | None,
) -> tuple[float, int | None, str]:
    """Choose enough edit strength while keeping explicit user values authoritative."""

    normalized_mode = str(mode or "balanced").casefold()
    base = {"preserve": 0.32, "balanced": 0.55, "free": 0.78}.get(
        normalized_mode,
        0.55,
    )
    magnitude = classify_edit_magnitude(requirement)
    floors = {
        "major": 0.64,
        "moderate": 0.48,
        "minor": 0.40,
        "unknown": base,
    }
    denoise = explicit_denoise if explicit_denoise is not None else max(base, floors[magnitude])
    if explicit_steps is not None:
        steps = explicit_steps
    else:
        steps = {"major": 16, "moderate": 14, "minor": 12}.get(magnitude)
    return denoise, steps, magnitude


def validate_semantic_prompt(
    positive_prompt: str,
    *,
    required_groups: tuple[tuple[str, tuple[str, ...]], ...] = (),
    forbidden_terms: tuple[str, ...] = (),
    preserved_terms: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Validate the final post-LoRA positive prompt against edit invariants."""

    issues: list[str] = []
    for code, aliases in required_groups:
        if not any(_contains(positive_prompt, alias) for alias in aliases):
            issues.append(f"missing:{code}")
    for term in forbidden_terms:
        if _contains(positive_prompt, term):
            issues.append("retained_source_outfit")
    for term in preserved_terms:
        if not _contains(positive_prompt, term):
            issues.append("missing_preserved_composition")
    return tuple(dict.fromkeys(issues))
