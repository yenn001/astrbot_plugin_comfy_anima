"""LoRA 组合预设的解析、分类、保存与选择。"""

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ..core.lora import LORA_TAG_PATTERN, canonical_lora_name
from ..models import LoraSelection


PRESET_CATEGORY_CHARACTER = "character"
PRESET_CATEGORY_ARTIST_STYLE = "artist_style"
PRESET_CATEGORY_MIXED = "mixed"
PRESET_CATEGORIES = {
    PRESET_CATEGORY_CHARACTER,
    PRESET_CATEGORY_ARTIST_STYLE,
    PRESET_CATEGORY_MIXED,
}

CATEGORY_ALIASES = {
    "角色": PRESET_CATEGORY_CHARACTER,
    "人物": PRESET_CATEGORY_CHARACTER,
    "character": PRESET_CATEGORY_CHARACTER,
    "c": PRESET_CATEGORY_CHARACTER,
    "风格": PRESET_CATEGORY_ARTIST_STYLE,
    "画师": PRESET_CATEGORY_ARTIST_STYLE,
    "画风": PRESET_CATEGORY_ARTIST_STYLE,
    "style": PRESET_CATEGORY_ARTIST_STYLE,
    "artist": PRESET_CATEGORY_ARTIST_STYLE,
    "artist_style": PRESET_CATEGORY_ARTIST_STYLE,
    "s": PRESET_CATEGORY_ARTIST_STYLE,
    "混合": PRESET_CATEGORY_MIXED,
    "组合": PRESET_CATEGORY_MIXED,
    "mixed": PRESET_CATEGORY_MIXED,
    "m": PRESET_CATEGORY_MIXED,
}

CATEGORY_LABELS = {
    PRESET_CATEGORY_CHARACTER: "角色",
    PRESET_CATEGORY_ARTIST_STYLE: "画师/风格",
    PRESET_CATEGORY_MIXED: "混合",
}

TEMPLATE_KEYS = {
    PRESET_CATEGORY_CHARACTER: "character_combo",
    PRESET_CATEGORY_ARTIST_STYLE: "artist_style_combo",
    PRESET_CATEGORY_MIXED: "mixed_combo",
}
TEMPLATE_CATEGORIES = {value: key for key, value in TEMPLATE_KEYS.items()}


class LoraPresetError(ValueError):
    """LoRA 组合预设格式或操作无效。"""


_TRAILING_ANNOTATION_RE = re.compile(
    r"\s*(?:\([^()]*\)|（[^（）]*）|\[[^\[\]]*\]|【[^【】]*】|"
    r"「[^「」]*」|『[^『』]*』)\s*$"
)
_STYLE_NUMBER_RE = re.compile(r"^(风格|style)0*(\d+)$", flags=re.IGNORECASE)
_STYLE_PREFIX_RE = re.compile(
    r"^(风格|style)\s*0*(\d+)(?=\s|[（(\[【:：|｜])",
    flags=re.IGNORECASE,
)
_NAMED_STYLE_PREFIX_RE = re.compile(
    r"^(?:风格|style)\s*[:：|｜-]?\s*(?P<name>[^\s:：|｜-].*)$",
    flags=re.IGNORECASE,
)


def _preset_lookup_key(value: str) -> str:
    """Normalize harmless typography without weakening exact preset identity."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = text.strip("‘’“”\"'「」『』")
    return re.sub(r"\s+", "", text)


def _preset_alias_key(value: str) -> str:
    """Collapse numeric style zero-padding only for secondary alias lookup."""
    key = _preset_lookup_key(value)
    numeric = _STYLE_NUMBER_RE.fullmatch(key)
    if numeric:
        return f"{numeric.group(1).casefold()}{int(numeric.group(2))}"
    return key


def _strip_trailing_annotations(value: str) -> str:
    """Remove one or more trailing human-readable notes such as ``（凛然）``."""
    text = str(value or "").strip()
    while text:
        shortened = _TRAILING_ANNOTATION_RE.sub("", text).strip()
        if shortened == text:
            break
        text = shortened
    return text


def _lookup_key_mentioned(source_key: str, candidate_key: str) -> bool:
    """Return whether a compact preset key occurs without an ASCII collision.

    Chinese descriptions commonly attach a preset directly to words such as
    ``画`` or punctuation, so ``\b`` is not suitable.  ASCII aliases still need
    guards to prevent a short name such as ``gzc`` from matching a longer
    identifier accidentally.  Numeric style names also keep the historical
    no-prefix-collision guarantee (``风格001`` must not match ``风格0012``).
    """

    if not source_key or not candidate_key:
        return False
    ascii_word = frozenset(
        "abcdefghijklmnopqrstuvwxyz0123456789_"
    )
    start = 0
    while True:
        index = source_key.find(candidate_key, start)
        if index < 0:
            return False
        before = source_key[index - 1] if index > 0 else ""
        after_index = index + len(candidate_key)
        after = source_key[after_index] if after_index < len(source_key) else ""
        if (
            (candidate_key[0] not in ascii_word or before not in ascii_word)
            and (candidate_key[-1] not in ascii_word or after not in ascii_word)
            and (not candidate_key[-1].isdigit() or not after.isdigit())
        ):
            return True
        start = index + 1


def normalize_preset_aliases(value: Any) -> tuple[str, ...]:
    """Normalize user-managed aliases while preserving their display text."""

    if isinstance(value, str):
        raw_items = re.split(r"[\r\n,，;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []
    aliases: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        alias = str(raw or "").strip()
        if not alias:
            continue
        if len(alias) > 40:
            raise LoraPresetError("组合简称不能超过 40 个字符")
        key = _preset_lookup_key(alias)
        if key and key not in seen:
            seen.add(key)
            aliases.append(alias)
    if len(aliases) > 12:
        raise LoraPresetError("单个组合最多允许 12 个简称/别名")
    return tuple(aliases)


def normalize_preset_tags(value: Any, *, limit: int = 200) -> tuple[str, ...]:
    """Normalize user-managed positive/negative prompt tags."""
    if isinstance(value, str):
        raw_items = re.split(r"[\r\n,，;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []
    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        tag = str(raw or "").strip()
        if not tag:
            continue
        if len(tag) > 200:
            raise LoraPresetError("单个提示词 Tag 不能超过 200 个字符")
        key = unicodedata.normalize("NFKC", tag).casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    if len(tags) > limit:
        raise LoraPresetError(f"单个提示词池最多允许 {limit} 个 Tag")
    return tuple(tags)


def _preset_name_aliases(
    value: str,
    explicit_aliases: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return safe, deterministic aliases derived from one saved display name."""
    display_name = str(value or "").strip()
    base_name = _strip_trailing_annotations(display_name)
    aliases: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        key = _preset_lookup_key(candidate)
        if key and key not in seen:
            seen.add(key)
            aliases.append(candidate.strip())

    add(display_name)
    add(base_name)
    numeric = _STYLE_NUMBER_RE.fullmatch(_preset_lookup_key(base_name))
    if numeric:
        add(f"{numeric.group(1)}{int(numeric.group(2))}")
    prefix = _STYLE_PREFIX_RE.match(base_name)
    if prefix:
        add(f"{prefix.group(1)}{int(prefix.group(2))}")
    named_style = _NAMED_STYLE_PREFIX_RE.match(base_name)
    if named_style and not _STYLE_NUMBER_RE.fullmatch(_preset_lookup_key(base_name)):
        add(named_style.group("name"))
    for alias in explicit_aliases:
        add(str(alias or ""))
    return tuple(aliases)


@dataclass(frozen=True)
class LoraPreset:
    """一个可复用的 LoRA 串组合。"""

    name: str
    category: str
    selections: tuple[LoraSelection, ...]
    trigger_words: str = ""
    description: str = ""
    aliases: tuple[str, ...] = ()
    note: str = ""
    enabled: bool = True
    character_canonical: str = ""
    work_canonical: str = ""
    identity_anchor: str = ""
    required_trigger_terms: tuple[str, ...] = ()
    positive_tags: tuple[str, ...] = ()
    negative_tags: tuple[str, ...] = ()
    variant_id: str = "default"
    contract_enabled: bool = False

    @property
    def is_character_preset(self) -> bool:
        return self.category == PRESET_CATEGORY_CHARACTER

    @property
    def required_prompt_terms(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.identity_anchor, *self.required_trigger_terms)
            if str(value).strip()
        )

    @property
    def lora_tags(self) -> str:
        return ", ".join(
            f"<lora:{selection.name}:{selection.strength:g}>"
            for selection in self.selections
        )

    @property
    def expanded_prompt_prefix(self) -> str:
        return ", ".join(
            part for part in (self.lora_tags, self.trigger_words.strip()) if part
        )


def normalize_category(value: str, *, allow_auto: bool = False) -> str:
    """把中文或英文分类名转换为内部分类。"""
    normalized = str(value or "").strip().casefold()
    if allow_auto and normalized in {"", "auto", "自动", "au"}:
        return "auto"
    category = CATEGORY_ALIASES.get(normalized, normalized)
    if category not in PRESET_CATEGORIES:
        raise LoraPresetError("分类必须是 角色、风格/画师、混合 或 auto")
    return category


def deduplicate_selections(
    selections: Iterable[LoraSelection],
) -> tuple[LoraSelection, ...]:
    """校验并按规范名称去重，后出现的权重覆盖前者。"""
    ordered: list[str] = []
    values: dict[str, LoraSelection] = {}
    for selection in selections:
        name = canonical_lora_name(selection.name)
        if not name:
            continue
        try:
            strength = float(selection.strength)
        except (TypeError, ValueError) as exc:
            raise LoraPresetError(f"LoRA 权重无效: {selection.strength}") from exc
        if not math.isfinite(strength) or not 0.0 <= strength <= 2.0:
            raise LoraPresetError("LoRA 权重必须是 0 到 2 之间的有限数字")
        key = name.casefold()
        if key not in values:
            ordered.append(key)
        values[key] = LoraSelection(name=name, strength=strength)
    return tuple(values[key] for key in ordered)


def parse_lora_entries(
    entries: Any,
    *,
    max_loras: int,
) -> tuple[LoraSelection, ...]:
    """解析 template_list 或 QQ 命令中的 LoRA 串。"""
    if isinstance(entries, str):
        raw_entries = [entries]
    elif isinstance(entries, list):
        raw_entries = [str(entry) for entry in entries]
    else:
        raw_entries = []

    selections: list[LoraSelection] = []
    for raw_entry in raw_entries:
        text = raw_entry.strip()
        if not text or not text.strip(" ,;，；、"):
            continue
        matches = list(LORA_TAG_PATTERN.finditer(text))
        if matches:
            remainder = LORA_TAG_PATTERN.sub("", text)
            if remainder.strip(" \t\r\n,;，；、"):
                raise LoraPresetError(
                    "LoRA Tag 外含有无法识别的内容，请每项只填写 LoRA 串"
                )
            selections.extend(
                LoraSelection(
                    name=canonical_lora_name(match.group(1)),
                    strength=float(match.group(2)),
                )
                for match in matches
            )
            continue
        if "=" not in text:
            raise LoraPresetError("LoRA 项格式应为 <lora:名称:权重> 或 名称=权重")
        name, weight_text = text.rsplit("=", 1)
        try:
            weight = float(weight_text.strip())
        except ValueError as exc:
            raise LoraPresetError(f"LoRA 权重无效: {weight_text}") from exc
        selections.append(
            LoraSelection(name=canonical_lora_name(name), strength=weight)
        )

    result = deduplicate_selections(selections)
    if not result:
        raise LoraPresetError("LoRA 组合至少需要一个有效 LoRA")
    if len(result) > max_loras:
        raise LoraPresetError(f"单个组合最多允许 {max_loras} 个 LoRA")
    return result


class LoraPresetRegistry:
    """内存中的 LoRA 组合预设注册表。"""

    def __init__(self, raw_presets: Any, *, max_loras: int = 8):
        self._max_loras = max(1, int(max_loras))
        self._presets: list[LoraPreset] = []
        self.load(raw_presets)

    @property
    def presets(self) -> tuple[LoraPreset, ...]:
        return tuple(self._presets)

    @staticmethod
    def aliases_for(preset: LoraPreset) -> tuple[str, ...]:
        """Return every unique callable alias except the full display name."""

        return _preset_name_aliases(preset.name, preset.aliases)[1:]

    def load(self, raw_presets: Any) -> None:
        self._presets = []
        if not isinstance(raw_presets, list):
            return
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            try:
                raw_character = item.get("character")
                character_mapping = raw_character if isinstance(raw_character, dict) else {}
                contract_enabled = any(
                    key in item
                    for key in (
                        "character_canonical",
                        "work_canonical",
                        "identity_anchor",
                        "required_trigger_terms",
                        "positive_tags",
                        "negative_tags",
                        "variant_id",
                    )
                )
                template_key = str(item.get("__template_key") or "").strip()
                category = TEMPLATE_CATEGORIES.get(template_key)
                if category is None:
                    category = normalize_category(str(item.get("category") or "mixed"))
                raw_name = str(item.get("name") or "").strip()
                if not raw_name:
                    continue
                name = self._normalize_name(raw_name, category)
                selections = parse_lora_entries(
                    item.get("loras", []), max_loras=self._max_loras
                )
                preset = LoraPreset(
                    name=name,
                    category=category,
                    selections=selections,
                    trigger_words=str(item.get("trigger_words") or "").strip(),
                    description=str(item.get("description") or "").strip(),
                    aliases=normalize_preset_aliases(item.get("aliases", [])),
                    note=str(item.get("note") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                    character_canonical=str(
                        item.get("character_canonical")
                        or character_mapping.get("canonical")
                        or ""
                    ).strip(),
                    work_canonical=str(
                        item.get("work_canonical")
                        or character_mapping.get("work")
                        or ""
                    ).strip(),
                    identity_anchor=str(item.get("identity_anchor") or "").strip(),
                    required_trigger_terms=normalize_preset_tags(
                        item.get("required_trigger_terms")
                        or item.get("required_triggers")
                        or ()
                    ),
                    positive_tags=normalize_preset_tags(item.get("positive_tags") or ()),
                    negative_tags=normalize_preset_tags(item.get("negative_tags") or ()),
                    variant_id=str(item.get("variant_id") or "default").strip()
                    or "default",
                    contract_enabled=contract_enabled,
                )
                self._upsert(preset)
            except (LoraPresetError, TypeError, ValueError):
                continue

    def list_presets(
        self,
        *,
        category: str = "",
        keyword: str = "",
        enabled_only: bool = True,
    ) -> tuple[LoraPreset, ...]:
        normalized_category = (
            normalize_category(category) if str(category).strip() else ""
        )
        needle = str(keyword).strip().casefold()
        result = []
        for preset in self._presets:
            if enabled_only and not preset.enabled:
                continue
            if normalized_category and preset.category != normalized_category:
                continue
            searchable = " ".join(
                (
                    preset.name,
                    preset.description,
                    preset.note,
                    preset.trigger_words,
                    *preset.aliases,
                    *(selection.name for selection in preset.selections),
                )
            ).casefold()
            if needle and needle not in searchable:
                continue
            result.append(preset)
        return tuple(result)

    def resolve(self, identifier: str, *, enabled_only: bool = True) -> LoraPreset:
        """按序号、完整名称或唯一的省略备注名称选择组合。"""
        value = str(identifier or "").strip()
        if not value:
            raise LoraPresetError("请选择 LoRA 组合序号或名称")
        if value.isdigit():
            index = int(value)
            if 1 <= index <= len(self._presets):
                preset = self._presets[index - 1]
                if enabled_only and not preset.enabled:
                    raise LoraPresetError(f"LoRA 组合已禁用: {preset.name}")
                return preset
        folded = _preset_lookup_key(value)
        for preset in self._presets:
            if _preset_lookup_key(preset.name) == folded:
                if enabled_only and not preset.enabled:
                    raise LoraPresetError(f"LoRA 组合已禁用: {preset.name}")
                return preset

        alias_matches = [
            preset
            for preset in self._presets
            if any(
                _preset_alias_key(alias) == _preset_alias_key(value)
                for alias in _preset_name_aliases(preset.name, preset.aliases)[1:]
            )
        ]
        if enabled_only:
            enabled_matches = [preset for preset in alias_matches if preset.enabled]
            if enabled_matches:
                alias_matches = enabled_matches
        if len(alias_matches) == 1:
            preset = alias_matches[0]
            if enabled_only and not preset.enabled:
                raise LoraPresetError(f"LoRA 组合已禁用: {preset.name}")
            return preset
        if len(alias_matches) > 1:
            names = "、".join(preset.name for preset in alias_matches[:5])
            raise LoraPresetError(
                f"LoRA 组合简称“{value}”对应多个预设，请使用完整名称：{names}"
            )
        raise LoraPresetError(f"找不到 LoRA 组合: {value}")

    def find_mentioned_style(self, text: str) -> Optional[LoraPreset]:
        """识别完整风格名或唯一别名；任何歧义都拒绝自动选择。"""
        return self.find_mentioned_preset(text, categories=(PRESET_CATEGORY_ARTIST_STYLE,))

    def find_mentioned_preset(
        self,
        text: str,
        *,
        categories: Iterable[str] = PRESET_CATEGORIES,
    ) -> Optional[LoraPreset]:
        """识别用户/Bot 提到的预设名称、别名、角色 canonical 或作品。"""
        source = str(text or "")
        if not source:
            return None

        source_key = _preset_lookup_key(source)
        allowed = set(categories)
        styles = tuple(
            preset
            for preset in self.list_presets()
            if preset.category in allowed
        )

        numeric_request = re.search(
            r"(?:用|使用|采用|套用|按|切换(?:到|为)?)?\s*"
            r"[‘’“”\"'「」『』]?\s*(风格\s*0*\d+)(?!\d)",
            source,
            flags=re.IGNORECASE,
        )
        if numeric_request:
            try:
                numeric_preset = self.resolve(numeric_request.group(1))
            except LoraPresetError:
                numeric_preset = None
            if (
                numeric_preset is not None
                and numeric_preset.category == PRESET_CATEGORY_ARTIST_STYLE
            ):
                return numeric_preset

        # A complete saved display name is stronger than every derived or
        # administrator-managed alias.  Prefer the longest exact name so
        # ``Night Style`` is not shadowed by another preset named ``Night``.
        full_name_matches = [
            preset
            for preset in styles
            if _lookup_key_mentioned(source_key, _preset_lookup_key(preset.name))
        ]
        if full_name_matches:
            longest = max(
                len(_preset_lookup_key(preset.name)) for preset in full_name_matches
            )
            strongest = [
                preset
                for preset in full_name_matches
                if len(_preset_lookup_key(preset.name)) == longest
            ]
            return strongest[0] if len(strongest) == 1 else None

        identity_matches: list[LoraPreset] = []
        for preset in styles:
            identity_values = (
                preset.character_canonical,
                preset.work_canonical,
                *preset.aliases,
            )
            if any(
                value
                and _lookup_key_mentioned(source_key, _preset_lookup_key(value))
                for value in identity_values
            ):
                identity_matches.append(preset)
        if len(identity_matches) == 1:
            return identity_matches[0]

        aliases: dict[str, list[tuple[str, LoraPreset]]] = {}
        for preset in styles:
            for alias in _preset_name_aliases(preset.name, preset.aliases)[1:]:
                aliases.setdefault(_preset_alias_key(alias), []).append((alias, preset))
        unique_alias_matches: dict[int, LoraPreset] = {}
        for alias_key, values in aliases.items():
            matched_presets = {id(preset): preset for _, preset in values}
            if len(matched_presets) != 1:
                continue
            if _lookup_key_mentioned(source_key, alias_key):
                preset = next(iter(matched_presets.values()))
                unique_alias_matches[id(preset)] = preset
        if len(unique_alias_matches) == 1:
            return next(iter(unique_alias_matches.values()))
        return None

    def match_style_selections(
        self, selections: Iterable[LoraSelection]
    ) -> Optional[LoraPreset]:
        """当 LLM 已展开完整风格串时，反向识别对应保存预设。"""
        provided = {
            canonical_lora_name(selection.name).casefold(): float(selection.strength)
            for selection in selections
        }
        candidates = sorted(
            self.list_presets(category=PRESET_CATEGORY_ARTIST_STYLE),
            key=lambda preset: len(preset.selections),
            reverse=True,
        )
        for preset in candidates:
            if all(
                key in provided and abs(provided[key] - selection.strength) < 1e-6
                for selection in preset.selections
                if (key := canonical_lora_name(selection.name).casefold())
            ):
                return preset
        return None

    def save(
        self,
        *,
        name: str,
        category: str,
        selections: tuple[LoraSelection, ...],
        trigger_words: str = "",
        description: str = "",
        aliases: Any = (),
        note: str = "",
        enabled: bool = True,
        identifier: str = "",
        character_canonical: str = "",
        work_canonical: str = "",
        identity_anchor: str = "",
        required_trigger_terms: Any = (),
        positive_tags: Any = (),
        negative_tags: Any = (),
        variant_id: str = "default",
        enforce_character_contract: bool = False,
    ) -> LoraPreset:
        normalized_category = normalize_category(category)
        normalized_name = self._normalize_name(name, normalized_category)
        normalized_selections = deduplicate_selections(selections)
        if not normalized_selections:
            raise LoraPresetError("LoRA 组合至少需要一个 LoRA")
        if len(normalized_selections) > self._max_loras:
            raise LoraPresetError(f"单个组合最多允许 {self._max_loras} 个 LoRA")
        normalized_aliases = tuple(
            alias
            for alias in normalize_preset_aliases(aliases)
            if _preset_lookup_key(alias) != _preset_lookup_key(normalized_name)
        )
        normalized_note = str(note or "").strip()
        if len(normalized_note) > 500:
            raise LoraPresetError("组合备注不能超过 500 个字符")
        normalized_character = str(character_canonical or "").strip()
        normalized_work = str(work_canonical or "").strip()
        normalized_identity_anchor = str(identity_anchor or "").strip()
        normalized_required_terms = normalize_preset_tags(required_trigger_terms)
        normalized_positive_tags = normalize_preset_tags(positive_tags)
        normalized_negative_tags = normalize_preset_tags(negative_tags)
        normalized_variant_id = str(variant_id or "default").strip() or "default"
        if len(normalized_variant_id) > 80:
            raise LoraPresetError("预设变体标识不能超过 80 个字符")
        if enforce_character_contract and normalized_category == PRESET_CATEGORY_CHARACTER:
            if not normalized_identity_anchor:
                raise LoraPresetError("角色预设必须填写身份锚点")
            if not normalized_required_terms:
                raise LoraPresetError("角色预设必须填写必需触发词")
        preset = LoraPreset(
            name=normalized_name,
            category=normalized_category,
            selections=normalized_selections,
            trigger_words=trigger_words.strip(),
            description=description.strip(),
            aliases=normalized_aliases,
            note=normalized_note,
            enabled=enabled,
            character_canonical=normalized_character,
            work_canonical=normalized_work,
            identity_anchor=normalized_identity_anchor,
            required_trigger_terms=normalized_required_terms,
            positive_tags=normalized_positive_tags,
            negative_tags=normalized_negative_tags,
            variant_id=normalized_variant_id,
            contract_enabled=(
                enforce_character_contract
                and normalized_category == PRESET_CATEGORY_CHARACTER
            ),
        )
        if str(identifier or "").strip():
            current = self.resolve(identifier, enabled_only=False)
            current_index = self._presets.index(current)
            duplicate = next(
                (
                    item
                    for item in self._presets
                    if item is not current
                    and _preset_lookup_key(item.name)
                    == _preset_lookup_key(preset.name)
                ),
                None,
            )
            if duplicate is not None:
                raise LoraPresetError(f"LoRA 组合名称已存在: {preset.name}")
            self._presets[current_index] = preset
            return preset
        self._upsert(preset)
        return preset

    def delete(self, identifier: str) -> LoraPreset:
        preset = self.resolve(identifier, enabled_only=False)
        self._presets = [item for item in self._presets if item is not preset]
        return preset

    def _upsert(self, preset: LoraPreset) -> None:
        folded = preset.name.casefold()
        for index, current in enumerate(self._presets):
            if current.name.casefold() == folded:
                self._presets[index] = preset
                return
        self._presets.append(preset)

    def _normalize_name(self, name: str, category: str) -> str:
        value = str(name or "").strip()
        prefix = {
            PRESET_CATEGORY_CHARACTER: "角色",
            PRESET_CATEGORY_ARTIST_STYLE: "风格",
            PRESET_CATEGORY_MIXED: "组合",
        }[category]
        if not value or value.casefold() in {"auto", "自动"}:
            number = 1
            existing = {preset.name.casefold() for preset in self._presets}
            while f"{prefix}{number}".casefold() in existing:
                number += 1
            return f"{prefix}{number}"
        if value.isdigit():
            return f"{prefix}{value}"
        if len(value) > 40:
            raise LoraPresetError("组合名称不能超过 40 个字符")
        return value

    def to_config(self) -> list[dict[str, Any]]:
        """序列化为 AstrBot template_list 配置。"""
        return [
            {
                "__template_key": TEMPLATE_KEYS[preset.category],
                "name": preset.name,
                "loras": [
                    f"{selection.name}={selection.strength:g}"
                    for selection in preset.selections
                ],
                "trigger_words": preset.trigger_words,
                "description": preset.description,
                "aliases": list(preset.aliases),
                "note": preset.note,
                "enabled": preset.enabled,
                "character_canonical": preset.character_canonical,
                "work_canonical": preset.work_canonical,
                "identity_anchor": preset.identity_anchor,
                "required_trigger_terms": list(preset.required_trigger_terms),
                "positive_tags": list(preset.positive_tags),
                "negative_tags": list(preset.negative_tags),
                "variant_id": preset.variant_id,
            }
            for preset in self._presets
        ]

    def format_for_llm(
        self,
        *,
        category: str = "",
        keyword: str = "",
        detail: bool = False,
        enabled_only: bool = True,
    ) -> str:
        presets = self.list_presets(
            category=category,
            keyword=keyword,
            enabled_only=enabled_only,
        )
        return self.format_selected_for_llm(presets, detail=detail)

    def format_selected_for_llm(
        self,
        presets: Iterable[LoraPreset],
        *,
        detail: bool = False,
    ) -> str:
        """格式化已经过最新 Manager 校验的指定预设集合。"""
        presets = tuple(presets)
        if not presets:
            return "No matching saved LoRA presets were found."
        lines = [
            "Saved LoRA presets. Select an exact preset by name or character/work identity. Character preset identity anchors and required triggers are authoritative; after a character preset match, do not append Danbooru character identity tags."
        ]
        global_indices = {
            id(preset): index for index, preset in enumerate(self._presets, 1)
        }
        for preset in presets:
            index = global_indices[id(preset)]
            label = CATEGORY_LABELS[preset.category]
            line = f"- {index}. {preset.name} | category: {label} | {preset.lora_tags}"
            if not preset.enabled:
                line += " | disabled"
            if preset.trigger_words:
                line += f" | triggers: {preset.trigger_words}"
            if preset.character_canonical:
                line += f" | character: {preset.character_canonical}"
            if preset.work_canonical:
                line += f" | work: {preset.work_canonical}"
            if preset.identity_anchor:
                line += f" | identity_anchor: {preset.identity_anchor}"
            if preset.required_trigger_terms:
                line += (
                    " | required_triggers: "
                    + ", ".join(preset.required_trigger_terms)
                )
            if preset.positive_tags:
                line += " | positive_tags: " + ", ".join(preset.positive_tags)
            if preset.negative_tags:
                line += " | negative_tags: " + ", ".join(preset.negative_tags)
            if preset.variant_id != "default":
                line += f" | variant: {preset.variant_id}"
            if preset.aliases:
                line += f" | aliases: {', '.join(preset.aliases)}"
            if detail and preset.description:
                line += f" | {preset.description[:300]}"
            if detail and preset.note:
                line += f" | note: {preset.note[:300]}"
            lines.append(line)
        return "\n".join(lines)
