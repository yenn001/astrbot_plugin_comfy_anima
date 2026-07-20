"""Fail-closed single-character semantic replacement for Anima prompts.

This module deliberately does not perform image editing.  It rewrites a
single-subject prompt, replaces exactly one character LoRA, and preserves the
remaining outfit, pose, composition, scene and style terms unless the caller
explicitly requests the target character's metadata-backed default outfit.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence

from ..core.command_aliases import (
    CONTEXT_CHARACTER_SWAP,
    normalize_command_aliases,
)
from ..core.lora import LoraWorkflowError, canonical_lora_name, extract_lora_selections
from ..models import LoraIdentityExpectation, LoraSelection
from .lora_catalog import LoraRecord
from .lora_prompting import (
    choose_character_identity_trigger,
    is_character_identity_trigger_candidate,
)
from .lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    semantic_source_fingerprint,
)


SWAP_MODE_KEEP_OUTFIT = "keep-outfit"
SWAP_MODE_TARGET_OUTFIT = "target-outfit"
SWAP_MODES = frozenset({SWAP_MODE_KEEP_OUTFIT, SWAP_MODE_TARGET_OUTFIT})

_CLASSIFICATION_FIELDS = (
    "source_identity_ids",
    "outfit_ids",
    "pose_action_ids",
    "composition_ids",
    "scene_lighting_ids",
    "style_quality_ids",
    "uncertain_ids",
)
_MULTI_SUBJECT_KEYS = frozenset(
    {
        "multiplepeople",
        "multiplegirls",
        "multipleboys",
        "group",
        "crowd",
        "twogirls",
        "twoboys",
        "couple",
        "duo",
        "trio",
    }
)
_SPLIT_NAME_RE = re.compile(r"\s*(?:/|\||；|;|，|,)\s*")
_WEIGHT_SUFFIX_RE = re.compile(r":\s*[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*$")
_STRICT_LORA_TAG_RE = re.compile(
    r"<lora:([^<>:]+):([+-]?(?:\d+(?:\.\d+)?|\.\d+))>",
    re.IGNORECASE,
)
_GENERIC_NON_IDENTITY_KEYS = frozenset(
    {
        "1girl",
        "1boy",
        "solo",
        "masterpiece",
        "bestquality",
        "highquality",
        "veryaesthetic",
    }
)
_OBVIOUS_OUTFIT_MARKERS = (
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
    "suit",
    "costume",
    "attire",
    "robe",
    "kimono",
    "swimsuit",
    "bikini",
    "lingerie",
    "服装",
    "衣服",
    "制服",
    "裙",
    "外套",
    "鞋",
    "手套",
    "帽",
    "盔甲",
)
_APPEARANCE_MARKERS = (
    "hair",
    "eyes",
    "eye",
    "skin",
    "face",
    "facial",
    "freckles",
    "scar",
    "tattoo",
    "marking",
    "ears",
    "horns",
    "wings",
    "tail",
    "fangs",
    "species",
    "发",
    "头发",
    "眼",
    "皮肤",
    "脸",
    "雀斑",
    "伤疤",
    "纹身",
    "耳",
    "角",
    "翅",
    "尾",
)
_NON_CHARACTER_REQUEST_MARKERS = (
    "背景",
    "场景",
    "天空",
    "光线",
    "灯光",
    "构图",
    "镜头",
    "姿势",
    "动作",
    "表情",
    "衣服",
    "服装",
    "颜色",
    "风格",
    "画风",
    "泳装",
    "比基尼",
    "三点式",
    "内衣",
    "丝袜",
    "白丝",
    "黑丝",
    "袜",
    "礼服",
    "制服",
    "裙",
    "外套",
    "上衣",
    "裤",
    "鞋",
    "配饰",
)
_GENERIC_SOURCE_QUERY_KEYS = frozenset(
    {
        "角色",
        "人物",
        "主角",
        "原角色",
        "原人物",
        "当前角色",
        "当前人物",
        "这个角色",
        "这个人物",
        "那个角色",
        "那个人物",
        "图中角色",
        "图中人物",
        "图片中角色",
        "图片中人物",
        "画面中角色",
        "画面中人物",
        "她",
        "他",
        "ta",
    }
)
_NO_CHARACTER_LORA_RE = re.compile(
    r"(?:无需|不用|不要|别用|禁用|禁止(?:使用)?|"
    r"不(?:需要|使用|加载|添加|挂载))"
    r"(?:再)?(?:使用|加载|添加|挂载)?\s*"
    r"(?:任何\s*)?(?:目标\s*)?(?:角色\s*)?lo[-\s]?ra",
    re.IGNORECASE,
)


class CharacterSwapError(RuntimeError):
    """A semantic replacement could not be proven safe."""

    def __init__(
        self,
        user_message: str,
        *,
        code: str = "character_swap_error",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.user_message = user_message
        self.code = code
        self.details = dict(details or {})
        super().__init__(user_message)


@dataclass(frozen=True)
class CharacterSwapRequest:
    source_query: str
    target_query: str
    tags: str = ""
    mode: str = SWAP_MODE_KEEP_OUTFIT
    target_lora_strength: float = 0.65
    preset: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    negative_prompt: str = ""
    preview: bool = False
    use_target_lora: bool = True
    edit_requirement: str = ""

    @property
    def source_kind(self) -> str:
        return "tags" if self.tags.strip() else "image"


@dataclass(frozen=True)
class CharacterSwapClassification:
    source_identity_ids: tuple[int, ...]
    outfit_ids: tuple[int, ...]
    pose_action_ids: tuple[int, ...]
    composition_ids: tuple[int, ...]
    scene_lighting_ids: tuple[int, ...]
    style_quality_ids: tuple[int, ...]
    uncertain_ids: tuple[int, ...]
    target_identity_trigger_id: Optional[int]
    target_appearance_trigger_ids: tuple[int, ...]
    target_default_outfit_trigger_ids: tuple[int, ...]
    subject_count: int
    confidence: float


@dataclass(frozen=True)
class CharacterSwapPreparation:
    request: CharacterSwapRequest
    tags: tuple[str, ...]
    negative_prompt: str
    target_record: Optional[LoraRecord]
    target_metadata_record: Optional[LoraRecord]
    source_record: Optional[LoraRecord]
    preserved_loras: tuple[LoraSelection, ...]
    preserved_lora_records: tuple[LoraRecord, ...]
    removed_character_loras: tuple[LoraSelection, ...]
    deterministic_target_trigger: str
    target_trigger_words: tuple[str, ...]
    source_identity_hints: tuple[str, ...]
    target_identity_hints: tuple[str, ...]


@dataclass(frozen=True)
class CharacterSwapPlan:
    prompt: str
    negative_prompt: str
    loras: tuple[LoraSelection, ...]
    expectations: tuple[LoraIdentityExpectation, ...]
    target_record: Optional[LoraRecord]
    source_record: Optional[LoraRecord]
    target_identity_trigger: str
    removed_terms: tuple[str, ...]
    kept_terms: tuple[str, ...]
    added_terms: tuple[str, ...]
    suppressed_terms: tuple[str, ...]
    suppress_default_style: bool

    def preview_text(self) -> str:
        removed = "、".join(self.removed_terms[:12]) or "无"
        added = "、".join(self.added_terms[:12]) or "无"
        return (
            "语义换角预览（未提交 ComfyUI）\n"
            f"目标身份来源：{self.target_record.name if self.target_record else '纯语义 Tags（未使用角色 LoRA）'}\n"
            f"保留 Tags：{len(self.kept_terms)} 项\n"
            f"移除身份：{removed}\n"
            f"新增身份：{added}\n"
            "说明：这是整图语义重绘，不是像素级或局部替换。"
        )


def _clean_text(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _identity_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = _WEIGHT_SUFFIX_RE.sub("", text)
    return re.sub(r"[^0-9a-z@_\u3400-\u9fff]+", "", text)


def _is_generic_source_query(value: Any) -> bool:
    return _identity_key(value) in _GENERIC_SOURCE_QUERY_KEYS


def _is_meaningful_identity_key(value: str) -> bool:
    if re.search(r"[\u3400-\u9fff]", value):
        return len(value) >= 2
    return len(value) >= 3


def _contains_identity_fragment(container: str, fragment: str) -> bool:
    return bool(
        container
        and fragment
        and _is_meaningful_identity_key(fragment)
        and fragment in container
    )


def _strip_no_character_lora_suffix(value: str) -> tuple[str, bool]:
    """Remove a trailing natural-language no-LoRA directive from a target."""

    normalized = unicodedata.normalize("NFKC", str(value or ""))
    match = _NO_CHARACTER_LORA_RE.search(normalized)
    if match is None:
        return normalized, False
    target = normalized[: match.start()].rstrip(" \t，,。；;、:-")
    return target, True


def _canonical_key(value: Any) -> str:
    return canonical_lora_name(str(value or "")).casefold()


def _basename_key(value: Any) -> str:
    return PurePosixPath(_canonical_key(value)).name


def _dedupe_text(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = _identity_key(text)
        if text and key and key not in seen:
            seen.add(key)
            result.append(text)
    return tuple(result)


def _split_names(value: Any) -> tuple[str, ...]:
    return _dedupe_text(_SPLIT_NAME_RE.split(_clean_text(value)))


def _split_prompt_terms(prompt: str) -> tuple[str, ...]:
    """Split top-level prompt terms without damaging weighted groups."""

    result: list[str] = []
    buffer: list[str] = []
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for character in str(prompt or ""):
        if character in pairs:
            depth += 1
        elif character in closing and depth > 0:
            depth -= 1
        if depth == 0 and character in {",", "，", ";", "；", "\n", "\r"}:
            value = "".join(buffer).strip(" ,")
            if value:
                result.append(value)
            buffer = []
            continue
        buffer.append(character)
    value = "".join(buffer).strip(" ,")
    if value:
        result.append(value)
    return tuple(result)


def _prompt_term_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = text.strip("()[]{}<>‘’“”\"' ")
    return _identity_key(text)


def _is_character_record(record: LoraRecord) -> bool:
    category = str(record.category or "").strip().casefold()
    # Character identity evidence is authoritative even if an older archive or
    # manual edit left the broad category stale. Failing closed here prevents
    # a misclassified character LoRA from surviving a semantic replacement.
    return category == "character" or bool(str(record.character_name or "").strip())


def _entry_is_fresh(entry: Optional[SemanticEntry], record: LoraRecord) -> bool:
    if entry is None or not entry.overlay_valid:
        return False
    if not entry.source_fingerprint:
        return entry.has_manual_facts
    return (
        entry.source_fingerprint.casefold()
        == semantic_source_fingerprint(record).casefold()
    )


def _trusted_identity_values(
    record: LoraRecord,
    semantic_index: LoraSemanticIndex,
) -> tuple[str, ...]:
    values: list[str] = []
    canonical = canonical_lora_name(record.name)
    basename = PurePosixPath(canonical).name
    values.extend((canonical, basename))
    record_names = _split_names(record.character_name)
    values.extend(record_names)
    record_works = _split_names(record.source_work)
    # A work title is contextual evidence, not a character identity. Likewise,
    # LoraRecord.aliases mixes filenames, titles, tags and trained words without
    # provenance, so neither may independently authorize an automatic swap.
    for name in record_names:
        for work in record_works:
            values.extend((f"{work} {name}", f"{name} {work}"))

    entry = semantic_index.entry_for(record)
    if _entry_is_fresh(entry, record):
        assert entry is not None
        names = tuple(
            fact.value
            for fact in entry.effective_facts("character_names")
            if fact.source in {"manual", "observed"}
            or (
                fact.confidence >= 0.85
                and entry.analysis_confidence >= 0.85
            )
        )
        aliases = tuple(
            fact.value
            for fact in entry.effective_facts("aliases")
            if fact.source == "manual"
            or (
                fact.source == "llm_inferred"
                and
                fact.confidence >= 0.9
                and entry.analysis_confidence >= 0.85
            )
        )
        works = tuple(
            fact.value
            for fact in entry.effective_facts("source_works")
            if fact.source in {"manual", "observed"}
            or fact.confidence >= 0.9
        )
        values.extend(names)
        values.extend(aliases)
        trusted_names = _dedupe_text((*names, *aliases)) or record_names
        for name in trusted_names:
            for work in works:
                values.extend((f"{work} {name}", f"{name} {work}"))
    return _dedupe_text(values)


def _query_identity_keys(value: str) -> tuple[str, ...]:
    """Build conservative Chinese-natural-language variants for exact/fuzzy lookup."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    variants = [text]
    stripped = re.sub(
        r"(?:这个|那个|一位|一个)?(?:角色|人物|角色名)$",
        "",
        text,
    ).strip()
    variants.append(stripped)
    variants.append(
        re.sub(r"(?:里面|里边|当中|之中|中)?的", " ", stripped).strip()
    )
    return tuple(
        dict.fromkeys(key for item in variants if (key := _identity_key(item)))
    )


def _bounded_edit_distance(left: str, right: str, limit: int = 1) -> int:
    """Return a small Levenshtein distance, stopping once it exceeds ``limit``."""

    if left == right:
        return 0
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        row_min = current[0]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
            row_min = min(row_min, current[-1])
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _same_lora(left: LoraRecord, right: LoraRecord) -> bool:
    left_hash = str(left.sha256 or "").strip().casefold()
    right_hash = str(right.sha256 or "").strip().casefold()
    if left_hash and right_hash:
        return left_hash == right_hash
    return _canonical_key(left.name) == _canonical_key(right.name)


def resolve_character_record(
    records: Sequence[LoraRecord],
    query: str,
    semantic_index: LoraSemanticIndex,
    *,
    role_label: str = "目标",
) -> LoraRecord:
    """Resolve a character only from exact, provenance-aware identity evidence."""

    raw_query = unicodedata.normalize("NFKC", str(query or "")).strip().replace(
        "\\", "/"
    )
    explicit_path = "/" in raw_query
    explicit_file = bool(
        re.search(r"\.(?:safetensors|ckpt|pt|bin)$", raw_query, re.IGNORECASE)
    )
    query_keys = _query_identity_keys(
        canonical_lora_name(raw_query) if explicit_file else raw_query
    )
    if not query_keys:
        raise CharacterSwapError(
            f"{role_label}角色不能为空",
            code="empty_character_query",
        )
    matches: list[tuple[int, LoraRecord, str]] = []
    for record in records:
        if not _is_character_record(record):
            continue
        canonical = canonical_lora_name(record.name)
        basename = PurePosixPath(canonical).name
        if explicit_path:
            candidates: list[tuple[int, str]] = [(120, canonical)]
        elif explicit_file:
            candidates = [(115, basename)]
        else:
            # A bare word may be a character name as well as a basename.  Keep
            # both at the same rank so another character variant makes the
            # request ambiguous instead of silently preferring one filename.
            candidates = [(100, canonical), (100, basename)]
        candidates.extend(
            (100, value)
            for value in _trusted_identity_values(record, semantic_index)
        )
        best_score = 0
        best_value = ""
        for score, value in candidates:
            key = _identity_key(value)
            if key and key in query_keys and score > best_score:
                best_score = score
                best_value = value
        if best_score:
            matches.append((best_score, record, best_value))

    if not matches and not explicit_path and not explicit_file:
        fuzzy_matches: list[tuple[int, LoraRecord, str]] = []
        for record in records:
            if not _is_character_record(record):
                continue
            best_distance = 2
            best_value = ""
            for value in _trusted_identity_values(record, semantic_index):
                candidate_key = _identity_key(value)
                if len(candidate_key) < 2:
                    continue
                for query_key in query_keys:
                    distance = _bounded_edit_distance(query_key, candidate_key, 1)
                    if distance < best_distance:
                        best_distance = distance
                        best_value = value
            if best_distance == 1:
                fuzzy_matches.append((80, record, best_value))
        fuzzy_unique = {
            (str(item[1].sha256 or "").casefold(), _canonical_key(item[1].name))
            for item in fuzzy_matches
        }
        if len(fuzzy_unique) == 1:
            suggested = fuzzy_matches[0][1]
            suggested_name = (
                _split_names(suggested.character_name)[0]
                if _split_names(suggested.character_name)
                else suggested.name
            )
            raise CharacterSwapError(
                f"没有精确找到{role_label}角色“{query}”；疑似“{suggested_name}”。"
                "为避免换错角色，请使用建议名称重新发送",
                code="character_suggestion",
                details={"suggested_lora": suggested.name},
            )
        matches = fuzzy_matches

    if not matches:
        raise CharacterSwapError(
            f"未在最新 LoRA 清单中找到可唯一确认的{role_label}角色“{query}”",
            code="character_not_found",
        )
    highest = max(score for score, _record, _value in matches)
    finalists = [item for item in matches if item[0] == highest]
    unique = {
        (str(item[1].sha256 or "").casefold(), _canonical_key(item[1].name))
        for item in finalists
    }
    if len(unique) != 1:
        names = "、".join(item[1].name for item in finalists[:5])
        raise CharacterSwapError(
            f"{role_label}角色“{query}”命中多个 LoRA：{names}；请使用完整精确文件名",
            code="ambiguous_character",
            details={"candidate_count": len(unique)},
        )
    return finalists[0][1]


def _resolve_prompt_lora(
    selection: LoraSelection,
    records: Sequence[LoraRecord],
) -> LoraRecord:
    key = _canonical_key(selection.name)
    exact = [record for record in records if _canonical_key(record.name) == key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise CharacterSwapError(
            f"LoRA 完整名称出现冲突：{selection.name}",
            code="ambiguous_prompt_lora",
        )
    basename = _basename_key(selection.name)
    fallback = [
        record for record in records if _basename_key(record.name) == basename
    ]
    if len(fallback) == 1:
        return fallback[0]
    if not fallback:
        raise CharacterSwapError(
            f"提示词中的 LoRA 已不存在或当前不可加载：{selection.name}",
            code="prompt_lora_missing",
        )
    raise CharacterSwapError(
        f"LoRA 简称“{selection.name}”存在多个同名文件，请改用完整路径",
        code="ambiguous_prompt_lora",
    )


def _extract_prompt_loras_strict(
    prompt: str,
    *,
    max_loras: int,
) -> tuple[str, tuple[LoraSelection, ...]]:
    """Reject malformed or duplicate runtime tags before the legacy parser."""

    source = str(prompt or "")
    without_valid = _STRICT_LORA_TAG_RE.sub("", source)
    if re.search(r"<\s*lora\b", without_valid, re.IGNORECASE):
        raise CharacterSwapError(
            "提示词含有残缺或非法的 <lora:名称:权重> 标签",
            code="invalid_prompt_lora",
        )
    seen: set[str] = set()
    for match in _STRICT_LORA_TAG_RE.finditer(source):
        key = _canonical_key(match.group(1))
        if key in seen:
            raise CharacterSwapError(
                f"提示词重复指定了同一个 LoRA：{match.group(1).strip()}",
                code="duplicate_prompt_lora",
            )
        seen.add(key)
    try:
        return extract_lora_selections(source, max_loras=max_loras)
    except LoraWorkflowError as exc:
        raise CharacterSwapError(
            str(exc),
            code="invalid_prompt_lora",
        ) from exc


def _reject_obvious_multi_subject(tags: Sequence[str]) -> None:
    keys = {_prompt_term_key(tag) for tag in tags}
    if keys & _MULTI_SUBJECT_KEYS:
        raise CharacterSwapError(
            "首版语义换角只支持单角色，检测到多人或群像 Tags",
            code="multiple_subjects",
        )
    for key in keys:
        match = re.fullmatch(r"(\d+)(girls?|boys?|people|persons?)", key)
        if match and int(match.group(1)) != 1:
            raise CharacterSwapError(
                "首版语义换角只支持单角色，检测到多人数量 Tag",
                code="multiple_subjects",
            )
    if {"1girl", "1boy"}.issubset(keys):
        raise CharacterSwapError(
            "同时检测到 1girl 与 1boy，无法安全绑定唯一角色",
            code="multiple_subjects",
        )


def _target_trigger_candidates(record: LoraRecord) -> tuple[str, ...]:
    return _dedupe_text(record.trigger_words)


def _expectation(record: LoraRecord) -> LoraIdentityExpectation:
    return LoraIdentityExpectation(
        name=record.name,
        sha256=str(record.sha256 or "").strip().casefold(),
        source_fingerprint=semantic_source_fingerprint(record),
    )


class CharacterSwapPlanner:
    """Prepare and deterministically finalize one semantic character swap."""

    def __init__(self, semantic_index: LoraSemanticIndex) -> None:
        self._semantic_index = semantic_index

    def prepare(
        self,
        request: CharacterSwapRequest,
        *,
        positive_prompt: str,
        negative_prompt: str,
        records: Sequence[LoraRecord],
        replace_source_style: bool = False,
        fallback_target_tags: Sequence[str] = (),
    ) -> CharacterSwapPreparation:
        if request.mode not in SWAP_MODES:
            raise CharacterSwapError(
                "换角模式只支持 keep-outfit 或 target-outfit",
                code="unsupported_swap_mode",
            )
        if (
            request.source_query.strip()
            and _identity_key(request.source_query) == _identity_key(request.target_query)
        ):
            raise CharacterSwapError(
                "原角色与目标角色名称相同，已停止无效换角",
                code="same_character",
            )
        target_metadata: Optional[LoraRecord] = None
        explicit_target = "/" in request.target_query.replace("\\", "/") or bool(
            re.search(
                r"\.(?:safetensors|ckpt|pt|bin)$",
                request.target_query,
                re.IGNORECASE,
            )
        )
        try:
            target_metadata = resolve_character_record(
                records,
                request.target_query,
                self._semantic_index,
                role_label="目标",
            )
        except CharacterSwapError as exc:
            # Suggestions and ambiguity are never bypassed by pure-Tags mode.
            # Only a true miss may use separately validated semantic candidates.
            if (
                exc.code != "character_not_found"
                or explicit_target
                or not fallback_target_tags
            ):
                raise
        target = target_metadata if request.use_target_lora else None
        if (
            (target is None or not request.use_target_lora)
            and request.mode == SWAP_MODE_TARGET_OUTFIT
        ):
            raise CharacterSwapError(
                "未加载目标角色 LoRA 时只支持 keep-outfit，不能自动替换为目标默认服装",
                code="semantic_target_outfit_unsupported",
            )
        source: Optional[LoraRecord] = None
        if request.source_query.strip():
            try:
                source = resolve_character_record(
                    records,
                    request.source_query,
                    self._semantic_index,
                    role_label="原",
                )
            except CharacterSwapError as exc:
                # A source character may be represented only by prompt tags.
                # Missing is tolerable; ambiguity is not.
                if exc.code != "character_not_found":
                    raise
        if (
            source is not None
            and target_metadata is not None
            and _same_lora(source, target_metadata)
        ):
            raise CharacterSwapError(
                "原角色与目标角色解析为同一个 LoRA，已停止无效换角",
                code="same_character",
            )

        clean_prompt, parsed_loras = _extract_prompt_loras_strict(
            positive_prompt,
            max_loras=max(1, len(records)),
        )

        resolved_pairs = tuple(
            (selection, _resolve_prompt_lora(selection, records))
            for selection in parsed_loras
        )
        character_pairs = tuple(
            pair for pair in resolved_pairs if _is_character_record(pair[1])
        )
        distinct_character_keys = {
            _canonical_key(record.name) for _selection, record in character_pairs
        }
        if len(distinct_character_keys) > 1:
            raise CharacterSwapError(
                "提示词中含有多个不同角色 LoRA，无法安全确定要替换哪一个",
                code="multiple_character_loras",
        )
        if character_pairs:
            prompt_source = character_pairs[0][1]
            if target_metadata is not None and _same_lora(
                prompt_source,
                target_metadata,
            ):
                raise CharacterSwapError(
                    "提示词已经使用目标角色 LoRA，无法确认原角色身份",
                    code="target_already_present",
                )
            if source is not None and not _same_lora(source, prompt_source):
                raise CharacterSwapError(
                    "指定的原角色与提示词中的角色 LoRA 不一致",
                    code="source_character_mismatch",
                )
            source = prompt_source

        preserved_selections: list[LoraSelection] = []
        preserved_records: list[LoraRecord] = []
        removed_character_loras: list[LoraSelection] = []
        for selection, record in resolved_pairs:
            if _is_character_record(record):
                removed_character_loras.append(selection)
                continue
            if replace_source_style and str(record.category or "") in {
                "artist_style",
                "mixed",
            }:
                continue
            preserved_selections.append(
                LoraSelection(record.name, selection.strength)
            )
            preserved_records.append(record)

        tags = _split_prompt_terms(clean_prompt)
        if not tags:
            raise CharacterSwapError(
                "移除 LoRA 标签后没有可用于语义换角的画面 Tags",
                code="empty_swap_prompt",
            )
        if len(tags) > 240:
            raise CharacterSwapError(
                "换角提示词最多支持 240 个顶层 Tag，请先精简",
                code="too_many_tags",
            )
        _reject_obvious_multi_subject(tags)

        metadata_target_triggers = (
            _target_trigger_candidates(target_metadata)
            if target_metadata is not None
            else ()
        )
        target_triggers = metadata_target_triggers or _dedupe_text(
            fallback_target_tags
        )
        deterministic_trigger = (
            choose_character_identity_trigger(target)
            if target is not None
            else ""
        )
        if not target_triggers:
            if not request.use_target_lora:
                raise CharacterSwapError(
                    "用户已禁用目标角色 LoRA，但未取得可验证的普通身份 Tags",
                    code="semantic_target_tags_missing",
                )
            raise CharacterSwapError(
                "目标角色 LoRA 没有可验证的 Civitai/Manager 触发词",
                code="missing_target_trigger",
            )
        source_hints = (
            _trusted_identity_values(source, self._semantic_index)
            if source is not None
            else _dedupe_text((request.source_query,))
        )
        target_hints = (
            _trusted_identity_values(target_metadata, self._semantic_index)
            if target_metadata is not None
            else _dedupe_text((request.target_query,))
        )
        return CharacterSwapPreparation(
            request=request,
            tags=tags,
            negative_prompt=negative_prompt.strip(" ,"),
            target_record=target,
            target_metadata_record=target_metadata,
            source_record=source,
            preserved_loras=tuple(preserved_selections),
            preserved_lora_records=tuple(preserved_records),
            removed_character_loras=tuple(removed_character_loras),
            deterministic_target_trigger=deterministic_trigger,
            target_trigger_words=target_triggers,
            source_identity_hints=source_hints,
            target_identity_hints=target_hints,
        )

    @staticmethod
    def classification_prompts(
        preparation: CharacterSwapPreparation,
    ) -> tuple[str, str]:
        """Return a bounded JSON-only classification request for the LLM."""

        system_prompt = """You are a conservative Anima/Danbooru tag classifier.
You do not rewrite prompts and you never invent tags. Classify every numbered source
tag into exactly one provided bucket. The task is a single-character identity swap.
Identity includes the source character name, identity token, hair color/style, eye
color, facial markings, species traits and other character-defining appearance.
Outfit includes clothes, shoes and ordinary accessories. Preserve pose, action,
expression, camera, composition, scene, lighting, style and quality. Weighted tag
groups that mix incompatible buckets must go to uncertain_ids. Also verify the
numbered target candidates against the exact requested target character and select
exactly one unique identity token when it is supported. Return null when no candidate
can be proven to identify that exact character. Generic subject, physical appearance,
outfit, pose, style and quality tags are invalid identities. Separately identify only
stable physical appearance candidates and default-outfit candidates; leave pose,
scene, style, quality and unknown candidates unselected. Do not invent any target
tag. For target-outfit mode, select only candidates that explicitly describe the
target's default outfit. Confidence must reflect both source classification and the
target-name-to-identity match. Return one JSON object only. Do not include
explanations."""
        payload = {
            "source_character": preparation.request.source_query,
            "source_identity_hints": list(preparation.source_identity_hints[:24]),
            "target_character": preparation.request.target_query,
            "target_identity_hints": list(preparation.target_identity_hints[:24]),
            "target_candidate_source": (
                "lora_metadata"
                if preparation.target_metadata_record is not None
                else "bounded_semantic_generation"
            ),
            "target_lora_will_be_loaded": preparation.target_record is not None,
            "mode": preparation.request.mode,
            "source_tags": [
                {"id": index, "tag": tag}
                for index, tag in enumerate(preparation.tags)
            ],
            "target_metadata_triggers": [
                {"id": index, "tag": tag}
                for index, tag in enumerate(preparation.target_trigger_words)
            ],
            "required_schema": {
                "source_identity_ids": ["integer"],
                "outfit_ids": ["integer"],
                "pose_action_ids": ["integer"],
                "composition_ids": ["integer"],
                "scene_lighting_ids": ["integer"],
                "style_quality_ids": ["integer"],
                "uncertain_ids": ["integer"],
                "target_identity_trigger_id": "integer or null",
                "target_appearance_trigger_ids": ["integer"],
                "target_default_outfit_trigger_ids": ["integer"],
                "subject_count": "integer",
                "confidence": "number 0..1",
            },
        }
        user_prompt = (
            "Classify this bounded payload and return strict JSON only:\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        return system_prompt, user_prompt

    @staticmethod
    def parse_classification(
        text: str,
        *,
        tag_count: int,
        target_trigger_count: int,
    ) -> CharacterSwapClassification:
        payload = _strict_json_object(text)
        required = set(_CLASSIFICATION_FIELDS) | {
            "target_identity_trigger_id",
            "target_appearance_trigger_ids",
            "target_default_outfit_trigger_ids",
            "subject_count",
            "confidence",
        }
        if set(payload) != required:
            raise CharacterSwapError(
                "换角分类模型返回了错误的 JSON 字段",
                code="classification_schema_invalid",
            )

        groups: dict[str, tuple[int, ...]] = {}
        owner: dict[int, str] = {}
        for field_name in _CLASSIFICATION_FIELDS:
            ids = _integer_ids(payload.get(field_name), tag_count, field_name)
            for item_id in ids:
                if item_id in owner:
                    raise CharacterSwapError(
                        "换角分类结果含有重复 Tag ID",
                        code="classification_duplicate_id",
                    )
                owner[item_id] = field_name
            groups[field_name] = ids
        expected_ids = set(range(tag_count))
        if set(owner) != expected_ids:
            raise CharacterSwapError(
                "换角分类结果没有完整覆盖所有 Tags",
                code="classification_incomplete",
            )

        target_identity_raw = payload.get("target_identity_trigger_id")
        if target_identity_raw is None:
            target_identity_id = None
        elif isinstance(target_identity_raw, bool) or not isinstance(
            target_identity_raw, int
        ):
            raise CharacterSwapError(
                "目标身份触发词 ID 必须为整数或 null",
                code="target_trigger_invalid",
            )
        elif not 0 <= target_identity_raw < target_trigger_count:
            raise CharacterSwapError(
                "目标身份触发词 ID 越界",
                code="target_trigger_invalid",
            )
        else:
            target_identity_id = target_identity_raw
        target_appearance_ids = _integer_ids(
            payload.get("target_appearance_trigger_ids"),
            target_trigger_count,
            "target_appearance_trigger_ids",
        )
        target_outfit_ids = _integer_ids(
            payload.get("target_default_outfit_trigger_ids"),
            target_trigger_count,
            "target_default_outfit_trigger_ids",
        )
        if target_identity_id is not None and (
            target_identity_id in target_outfit_ids
            or target_identity_id in target_appearance_ids
        ):
            raise CharacterSwapError(
                "目标身份触发词不能同时被归为外观或默认服装",
                code="target_trigger_overlap",
            )
        if set(target_appearance_ids) & set(target_outfit_ids):
            raise CharacterSwapError(
                "目标外观触发词与默认服装触发词不能重叠",
                code="target_trigger_overlap",
            )
        subject_count = payload.get("subject_count")
        if isinstance(subject_count, bool) or not isinstance(subject_count, int):
            raise CharacterSwapError(
                "换角分类结果缺少有效 subject_count",
                code="subject_count_invalid",
            )
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise CharacterSwapError(
                "换角分类结果缺少有效置信度",
                code="classification_confidence_invalid",
            ) from exc
        if not 0.0 <= confidence <= 1.0:
            raise CharacterSwapError(
                "换角分类置信度超出 0 到 1",
                code="classification_confidence_invalid",
            )
        return CharacterSwapClassification(
            **groups,
            target_identity_trigger_id=target_identity_id,
            target_appearance_trigger_ids=target_appearance_ids,
            target_default_outfit_trigger_ids=target_outfit_ids,
            subject_count=subject_count,
            confidence=confidence,
        )

    def finalize(
        self,
        preparation: CharacterSwapPreparation,
        classification: CharacterSwapClassification,
    ) -> CharacterSwapPlan:
        if classification.subject_count != 1:
            raise CharacterSwapError(
                "首版语义换角只支持单角色，分类模型判断并非单一人物",
                code="multiple_subjects",
            )
        minimum_confidence = 0.9 if preparation.target_record is None else 0.82
        if classification.confidence < minimum_confidence:
            raise CharacterSwapError(
                f"换角分类置信度不足 {minimum_confidence:.2f}，已停止自动改写",
                code="low_classification_confidence",
            )
        if classification.uncertain_ids:
            raise CharacterSwapError(
                "部分 Tags 无法可靠区分身份与衣装，请先简化或使用 --preview 检查",
                code="uncertain_tags",
                details={"uncertain_count": len(classification.uncertain_ids)},
            )
        if (
            not classification.source_identity_ids
            and not preparation.removed_character_loras
        ):
            raise CharacterSwapError(
                "没有找到可移除的原角色身份 Tag 或角色 LoRA",
                code="source_identity_missing",
            )
        source_identity_keys = {
            _prompt_term_key(value)
            for value in preparation.source_identity_hints
            if _prompt_term_key(value)
        }
        if preparation.source_record is not None:
            reliable_source_trigger = choose_character_identity_trigger(
                preparation.source_record
            )
            if reliable_source_trigger:
                source_identity_keys.add(
                    _prompt_term_key(reliable_source_trigger)
                )
        classified_source_ids = set(classification.source_identity_ids)
        for index, term in enumerate(preparation.tags):
            nested_key = _identity_key(term)
            if index not in classified_source_ids and any(
                _contains_identity_fragment(nested_key, source_key)
                for source_key in source_identity_keys
            ):
                raise CharacterSwapError(
                    "含有可靠原角色身份词的加权或复合 Tag 未被完整移除",
                    code="source_identity_group_misclassified",
                )
        for item_id in classification.source_identity_ids:
            term = preparation.tags[item_id]
            folded = unicodedata.normalize("NFKC", term).casefold()
            key = _prompt_term_key(term)
            if key in _GENERIC_NON_IDENTITY_KEYS or any(
                marker in folded for marker in _OBVIOUS_OUTFIT_MARKERS
            ):
                raise CharacterSwapError(
                    "分类模型把通用主体或明显衣装 Tag 误判为角色身份",
                    code="unsafe_source_identity_classification",
                )
            if key not in source_identity_keys and not any(
                marker in folded for marker in _APPEARANCE_MARKERS
            ):
                raise CharacterSwapError(
                    "分类模型把无法证明属于身份外观的 Tag 标为角色身份",
                    code="unsafe_source_identity_classification",
                )
        if preparation.source_record is not None:
            source_trigger = choose_character_identity_trigger(
                preparation.source_record
            )
            source_trigger_key = _prompt_term_key(source_trigger)
            source_trigger_ids = {
                index
                for index, tag in enumerate(preparation.tags)
                if source_trigger_key
                and _prompt_term_key(tag) == source_trigger_key
            }
            if source_trigger_ids and not source_trigger_ids.issubset(
                set(classification.source_identity_ids)
            ):
                raise CharacterSwapError(
                    "原角色的可靠身份触发词未被分类为身份，已停止改写",
                    code="source_trigger_misclassified",
                )

        target_trigger = preparation.deterministic_target_trigger
        if preparation.target_record is None:
            trigger_id = classification.target_identity_trigger_id
            if trigger_id is None:
                raise CharacterSwapError(
                    "纯 Tags 换角无法确认唯一目标身份 Tag",
                    code="semantic_target_identity_unverified",
                )
            target_trigger = preparation.target_trigger_words[trigger_id]
            folded_target = unicodedata.normalize(
                "NFKC",
                target_trigger,
            ).casefold()
            target_key = _prompt_term_key(target_trigger)
            if (
                not is_character_identity_trigger_candidate(target_trigger)
                or target_key in _GENERIC_NON_IDENTITY_KEYS
                or any(marker in folded_target for marker in _APPEARANCE_MARKERS)
                or any(marker in folded_target for marker in _OBVIOUS_OUTFIT_MARKERS)
            ):
                raise CharacterSwapError(
                    "分类模型选择了通用、外观或服装词作为目标身份触发词",
                    code="unsafe_target_trigger",
                )
            if preparation.target_metadata_record is not None:
                expected_trigger = choose_character_identity_trigger(
                    preparation.target_metadata_record
                )
                if not expected_trigger or _prompt_term_key(
                    expected_trigger
                ) != _prompt_term_key(target_trigger):
                    raise CharacterSwapError(
                        "分类模型未选择 LoRA 元数据中可证明的目标身份词",
                        code="semantic_target_identity_unverified",
                    )
            elif trigger_id != 0:
                raise CharacterSwapError(
                    "纯语义身份规划的首项身份锚点未通过分类确认",
                    code="semantic_target_identity_unverified",
                )
        elif not target_trigger:
            trigger_id = classification.target_identity_trigger_id
            if trigger_id is None:
                raise CharacterSwapError(
                    "无法从目标 LoRA 元数据中确认唯一身份触发词",
                    code="missing_target_trigger",
                )
            target_trigger = preparation.target_trigger_words[trigger_id]
            candidates = tuple(
                value
                for value in preparation.target_trigger_words
                if is_character_identity_trigger_candidate(value)
            )
            if not is_character_identity_trigger_candidate(target_trigger):
                raise CharacterSwapError(
                    "分类模型选择了通用、外观或服装词作为目标身份触发词",
                    code="unsafe_target_trigger",
                )
            if len(candidates) != 1:
                target_keys = {
                    _identity_key(value)
                    for value in preparation.target_identity_hints
                    if _identity_key(value)
                }
                trigger_key = _identity_key(target_trigger)
                if not any(
                    hint in trigger_key or trigger_key in hint
                    for hint in target_keys
                    if len(hint) >= 3
                ):
                    raise CharacterSwapError(
                        "目标 LoRA 有多个可能身份触发词，无法安全自动选择",
                        code="ambiguous_target_trigger",
                    )

        for trigger_id in classification.target_appearance_trigger_ids:
            trigger = preparation.target_trigger_words[trigger_id]
            folded = unicodedata.normalize("NFKC", trigger).casefold()
            if not any(marker in folded for marker in _APPEARANCE_MARKERS) or any(
                marker in folded for marker in _OBVIOUS_OUTFIT_MARKERS
            ):
                raise CharacterSwapError(
                    "目标外观触发词没有可验证的外观证据",
                    code="unsafe_target_appearance_trigger",
                )
        for trigger_id in classification.target_default_outfit_trigger_ids:
            trigger = preparation.target_trigger_words[trigger_id]
            folded = unicodedata.normalize("NFKC", trigger).casefold()
            if not any(marker in folded for marker in _OBVIOUS_OUTFIT_MARKERS):
                raise CharacterSwapError(
                    "目标默认服装触发词没有可验证的衣装证据",
                    code="unsafe_target_outfit_trigger",
                )

        removed_ids = set(classification.source_identity_ids)
        if preparation.request.mode == SWAP_MODE_TARGET_OUTFIT:
            if not classification.target_default_outfit_trigger_ids:
                raise CharacterSwapError(
                    "目标 LoRA 元数据不足，无法可靠应用默认服装",
                    code="target_outfit_metadata_missing",
                )
            removed_ids.update(classification.outfit_ids)
        kept_terms = tuple(
            tag for index, tag in enumerate(preparation.tags) if index not in removed_ids
        )
        removed_terms = tuple(
            tag for index, tag in enumerate(preparation.tags) if index in removed_ids
        )

        added_terms: list[str] = [target_trigger]
        if preparation.target_record is None:
            added_terms.extend(
                preparation.target_trigger_words[index]
                for index in classification.target_appearance_trigger_ids
            )
        if preparation.request.mode == SWAP_MODE_TARGET_OUTFIT:
            added_terms.extend(
                preparation.target_trigger_words[index]
                for index in classification.target_default_outfit_trigger_ids
            )
        added_terms = list(_dedupe_text(added_terms))
        prompt = ", ".join((*kept_terms, *added_terms)).strip(" ,")
        if not prompt:
            raise CharacterSwapError(
                "语义换角后的正面提示词为空",
                code="empty_final_prompt",
            )

        target_negative_keys = {
            _prompt_term_key(value)
            for value in (
                target_trigger,
                *preparation.target_identity_hints,
                *added_terms,
                *(
                    preparation.target_trigger_words[index]
                    for index in classification.target_appearance_trigger_ids
                ),
            )
            if _prompt_term_key(value)
        }
        negative_terms = _split_prompt_terms(preparation.negative_prompt)
        kept_negative = tuple(
            term
            for term in negative_terms
            if not any(
                _contains_identity_fragment(_identity_key(term), target_key)
                for target_key in target_negative_keys
            )
        )
        negative_prompt = ", ".join(kept_negative)

        source_suppressed: list[str] = list(removed_terms)
        source_suppressed.extend(preparation.source_identity_hints)
        if preparation.source_record is not None:
            source_trigger = choose_character_identity_trigger(
                preparation.source_record
            )
            if source_trigger:
                source_suppressed.append(source_trigger)
        suppressed_terms = _dedupe_text(source_suppressed)

        if preparation.target_record is not None:
            target_selection = LoraSelection(
                preparation.target_record.name,
                preparation.request.target_lora_strength,
            )
            loras = (*preparation.preserved_loras, target_selection)
            records = (*preparation.preserved_lora_records, preparation.target_record)
        else:
            loras = preparation.preserved_loras
            records = preparation.preserved_lora_records
        self._verify_final_invariants(
            preparation,
            prompt,
            negative_prompt,
            loras,
            records,
            target_trigger,
            suppressed_terms,
        )
        return CharacterSwapPlan(
            prompt=prompt,
            negative_prompt=negative_prompt,
            loras=tuple(loras),
            expectations=tuple(_expectation(record) for record in records),
            target_record=preparation.target_record,
            source_record=preparation.source_record,
            target_identity_trigger=target_trigger,
            removed_terms=removed_terms,
            kept_terms=kept_terms,
            added_terms=tuple(added_terms),
            suppressed_terms=suppressed_terms,
            suppress_default_style=any(
                str(record.category or "").casefold() in {"artist_style", "mixed"}
                for record in preparation.preserved_lora_records
            ),
        )

    @staticmethod
    def _verify_final_invariants(
        preparation: CharacterSwapPreparation,
        prompt: str,
        negative_prompt: str,
        loras: Sequence[LoraSelection],
        records: Sequence[LoraRecord],
        target_trigger: str,
        suppressed_terms: Sequence[str],
    ) -> None:
        character_keys = {
            _canonical_key(record.name) for record in records if _is_character_record(record)
        }
        if preparation.target_record is None:
            if character_keys:
                raise CharacterSwapError(
                    "纯语义换角的最终 LoRA 栈仍残留角色 LoRA",
                    code="final_character_stack_invalid",
                )
        else:
            target_key = _canonical_key(preparation.target_record.name)
            if character_keys != {target_key}:
                raise CharacterSwapError(
                    "最终 LoRA 栈未能保持唯一目标角色",
                    code="final_character_stack_invalid",
                )
            if sum(_canonical_key(item.name) == target_key for item in loras) != 1:
                raise CharacterSwapError(
                    "目标角色 LoRA 必须且只能注入一次",
                    code="target_lora_count_invalid",
                )
        positive_keys = {_prompt_term_key(term) for term in _split_prompt_terms(prompt)}
        negative_keys = {
            _prompt_term_key(term) for term in _split_prompt_terms(negative_prompt)
        }
        target_trigger_key = _prompt_term_key(target_trigger)
        target_in_negative = any(
            _contains_identity_fragment(key, target_trigger_key)
            for key in negative_keys
        )
        if target_trigger_key not in positive_keys or target_in_negative:
            raise CharacterSwapError(
                "目标身份触发词未正确进入正面提示词或仍存在于负面提示词",
                code="target_trigger_conflict",
            )
        leaked = {
            _prompt_term_key(term)
            for term in suppressed_terms
            if any(
                _contains_identity_fragment(key, _prompt_term_key(term))
                for key in positive_keys
            )
        }
        if leaked:
            raise CharacterSwapError(
                "最终提示词仍残留原角色身份词",
                code="source_identity_leak",
            )


def _strict_json_object(text: str) -> Mapping[str, Any]:
    clean = str(text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", clean, re.DOTALL | re.I)
    if fenced:
        clean = fenced.group(1)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise CharacterSwapError(
            "换角分类模型没有返回合法 JSON",
            code="classification_invalid_json",
        ) from exc
    if not isinstance(payload, Mapping):
        raise CharacterSwapError(
            "换角分类结果必须是 JSON 对象",
            code="classification_invalid_json",
        )
    return payload


def _integer_ids(value: Any, upper_bound: int, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise CharacterSwapError(
            f"换角分类字段 {field_name} 必须是数组",
            code="classification_schema_invalid",
        )
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise CharacterSwapError(
                f"换角分类字段 {field_name} 含有非整数 ID",
                code="classification_schema_invalid",
            )
        if not 0 <= item < upper_bound:
            raise CharacterSwapError(
                f"换角分类字段 {field_name} 含有越界 ID",
                code="classification_id_out_of_range",
            )
        if item in seen:
            raise CharacterSwapError(
                f"换角分类字段 {field_name} 含有重复 ID",
                code="classification_duplicate_id",
            )
        seen.add(item)
        result.append(item)
    return tuple(result)


def parse_character_swap_request(command_text: str) -> CharacterSwapRequest:
    """Parse `/换角色 A -> B [options] | full tags`."""

    head, separator, tags = str(command_text or "").partition("|")
    try:
        tokens = list(
            normalize_command_aliases(
                shlex.split(head.strip(), posix=True),
                context=CONTEXT_CHARACTER_SWAP,
            )
        )
    except ValueError as exc:
        raise CharacterSwapError(
            f"参数引号不完整：{exc}",
            code="invalid_swap_arguments",
        ) from exc
    mapping_parts: list[str] = []
    mode = SWAP_MODE_KEEP_OUTFIT
    strength = 0.65
    preset = ""
    width: Optional[int] = None
    height: Optional[int] = None
    negative_prompt = ""
    preview = False
    use_target_lora = True
    index = 0

    def require_value(option: str) -> str:
        nonlocal index
        if index + 1 >= len(tokens):
            raise CharacterSwapError(
                f"{option} 缺少参数",
                code="invalid_swap_arguments",
            )
        index += 1
        return tokens[index]

    while index < len(tokens):
        token = tokens[index]
        if token == "--mode":
            mode = require_value(token).strip().casefold()
        elif token == "--weight":
            try:
                strength = float(require_value(token))
            except ValueError as exc:
                raise CharacterSwapError(
                    "--weight 必须是数字",
                    code="invalid_swap_arguments",
                ) from exc
        elif token == "--preset":
            preset = require_value(token).strip()
        elif token == "--size":
            size = require_value(token).lower().replace("×", "x").replace("*", "x")
            match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", re.sub(r"\s+", "", size))
            if not match:
                raise CharacterSwapError(
                    "--size 格式应为 宽x高",
                    code="invalid_swap_arguments",
                )
            width, height = int(match.group(1)), int(match.group(2))
        elif token == "--negative":
            negative_prompt = require_value(token).strip()
        elif token == "--preview":
            preview = True
        elif token in {"--no-character-lora", "--no-lora"}:
            use_target_lora = False
        elif token.startswith("--"):
            raise CharacterSwapError(
                f"不支持的换角选项：{token}",
                code="invalid_swap_arguments",
            )
        else:
            mapping_parts.append(token)
        index += 1

    mapping = " ".join(mapping_parts).strip()
    match = re.fullmatch(
        r"(?P<source>.*?)\s*(?:->|=>|→|替换成|替换为|换成|换为)\s*(?P<target>.+)",
        mapping,
    )
    if not match:
        raise CharacterSwapError(
            "用法：/换角色 A角色 -> B角色 [选项]，或在末尾用 | 提供完整 Tags",
            code="invalid_swap_mapping",
        )
    source_query = match.group("source").strip(" \"'，,")
    target_text, natural_no_lora = _strip_no_character_lora_suffix(
        match.group("target")
    )
    target_query = target_text.strip(" \"'，,")
    if natural_no_lora:
        use_target_lora = False
    if not target_query:
        raise CharacterSwapError(
            "目标角色不能为空",
            code="empty_character_query",
        )
    if mode not in SWAP_MODES:
        raise CharacterSwapError(
            "--mode 只支持 keep-outfit 或 target-outfit",
            code="unsupported_swap_mode",
        )
    if not 0.55 <= strength <= 0.75:
        raise CharacterSwapError(
            "语义换角的角色 LoRA 权重必须在 0.55 到 0.75 之间",
            code="unsafe_target_weight",
        )
    return CharacterSwapRequest(
        source_query=source_query,
        target_query=target_query,
        tags=tags.strip() if separator else "",
        mode=mode,
        target_lora_strength=strength,
        preset=preset,
        width=width,
        height=height,
        negative_prompt=negative_prompt,
        preview=preview,
        use_target_lora=use_target_lora,
    )


def parse_natural_character_swap(text: str) -> Optional[CharacterSwapRequest]:
    """Recognize only explicit A-to-B natural-language replacement requests."""

    source = unicodedata.normalize("NFKC", _clean_text(text, 1000))
    if not re.search(r"(?:替换成|替换为|换成|换为)", source):
        return None
    match = re.search(
        r"(?:把|将)?(?P<source>.+?)(?:替换成|替换为|换成|换为)(?P<target>[^，,。；;\n]+)",
        source,
    )
    if not match:
        return None
    source_query = re.sub(
        r"^(?:这张|这个|该|引用|回复)?(?:图片|图像|图|画面)?(?:里的|里|中的|内的)?",
        "",
        match.group("source").strip(),
    ).strip(" \"'，,")
    if _is_generic_source_query(source_query):
        source_query = ""
    target_text, target_no_lora = _strip_no_character_lora_suffix(match.group("target"))
    embedded_edit = ""
    edit_split = re.split(
        r"(?=(?:并|且|同时)(?:让|改|换|穿|戴|加|去掉|移除|保持|保留))",
        target_text,
        maxsplit=1,
    )
    if len(edit_split) == 2:
        target_text, embedded_edit = edit_split
    target_query = re.split(
        r"\s*(?:并|且|同时|衣服|服装|姿势|动作|表情|构图|背景|光线|保持|分辨率|尺寸|画布)\b",
        target_text.strip(),
        maxsplit=1,
    )[0].strip(" \"'，,")
    if not target_query:
        return None
    if any(marker in source_query for marker in _NON_CHARACTER_REQUEST_MARKERS):
        return None
    if _is_generic_source_query(target_query) or any(
        marker in target_query for marker in _NON_CHARACTER_REQUEST_MARKERS
    ):
        return None
    trailing_edit = source[match.end() :].strip(" \t，,。；;")
    edit_requirement = "，".join(
        part.strip(" \t，,。；;")
        for part in (embedded_edit, trailing_edit)
        if part.strip(" \t，,。；;")
    )
    edit_requirement = _NO_CHARACTER_LORA_RE.sub("", edit_requirement).strip(
        " \t，,。；;"
    )
    mode = (
        SWAP_MODE_TARGET_OUTFIT
        if re.search(r"(?:用|换成|采用).{0,8}(?:默认|原版|角色).{0,4}(?:衣服|服装|造型)", source)
        else SWAP_MODE_KEEP_OUTFIT
    )
    use_target_lora = not (
        target_no_lora or bool(_NO_CHARACTER_LORA_RE.search(source))
    )
    return CharacterSwapRequest(
        source_query=source_query,
        target_query=target_query,
        mode=mode,
        use_target_lora=use_target_lora,
        edit_requirement=edit_requirement,
    )


def fit_canvas_to_aspect_ratio(
    width: int,
    height: int,
    *,
    target_pixels: int = 1_000_000,
    multiple: int = 64,
    minimum: int = 256,
    maximum: int = 2048,
) -> tuple[int, int]:
    """Preserve aspect ratio near one megapixel without copying huge inputs."""

    if width <= 0 or height <= 0:
        raise CharacterSwapError("输入图片尺寸无效", code="invalid_image_size")
    ratio = width / height
    raw_width = math.sqrt(target_pixels * ratio)
    raw_height = raw_width / ratio

    def snap(value: float) -> int:
        bounded = min(maximum, max(minimum, int(round(value / multiple)) * multiple))
        return max(multiple, bounded)

    return snap(raw_width), snap(raw_height)


def response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        for key in ("completion_text", "text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value
        if "identity_tags" in response and "confidence" in response:
            try:
                return json.dumps(response, ensure_ascii=False)
            except (TypeError, ValueError, RecursionError):
                return ""
    for attribute in ("completion_text", "text", "content"):
        value = getattr(response, attribute, None)
        if isinstance(value, str):
            return value
    return ""


__all__ = [
    "CharacterSwapClassification",
    "CharacterSwapError",
    "CharacterSwapPlan",
    "CharacterSwapPlanner",
    "CharacterSwapPreparation",
    "CharacterSwapRequest",
    "SWAP_MODE_KEEP_OUTFIT",
    "SWAP_MODE_TARGET_OUTFIT",
    "fit_canvas_to_aspect_ratio",
    "parse_character_swap_request",
    "parse_natural_character_swap",
    "resolve_character_record",
    "response_text",
]
