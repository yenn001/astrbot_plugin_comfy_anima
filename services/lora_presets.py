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
    "风格": PRESET_CATEGORY_ARTIST_STYLE,
    "画师": PRESET_CATEGORY_ARTIST_STYLE,
    "画风": PRESET_CATEGORY_ARTIST_STYLE,
    "style": PRESET_CATEGORY_ARTIST_STYLE,
    "artist": PRESET_CATEGORY_ARTIST_STYLE,
    "artist_style": PRESET_CATEGORY_ARTIST_STYLE,
    "混合": PRESET_CATEGORY_MIXED,
    "组合": PRESET_CATEGORY_MIXED,
    "mixed": PRESET_CATEGORY_MIXED,
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


def _preset_name_aliases(value: str) -> tuple[str, ...]:
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
    return tuple(aliases)


@dataclass(frozen=True)
class LoraPreset:
    """一个可复用的 LoRA 串组合。"""

    name: str
    category: str
    selections: tuple[LoraSelection, ...]
    trigger_words: str = ""
    description: str = ""
    enabled: bool = True

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
    if allow_auto and normalized in {"", "auto", "自动"}:
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

    def load(self, raw_presets: Any) -> None:
        self._presets = []
        if not isinstance(raw_presets, list):
            return
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            try:
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
                    enabled=bool(item.get("enabled", True)),
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
                    preset.trigger_words,
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
                for alias in _preset_name_aliases(preset.name)[1:]
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
        """识别自然语言中的完整风格名或唯一的无备注简称。"""
        source = str(text or "")
        if not source:
            return None

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

        aliases: dict[str, list[tuple[str, LoraPreset]]] = {}
        for preset in self.list_presets(category=PRESET_CATEGORY_ARTIST_STYLE):
            for alias in _preset_name_aliases(preset.name):
                aliases.setdefault(_preset_alias_key(alias), []).append((alias, preset))
        candidates = sorted(
            (
                values[0]
                for values in aliases.values()
                if len({id(preset) for _, preset in values}) == 1
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for alias, preset in candidates:
            escaped = re.escape(alias)
            digit_guard = r"(?!\d)" if alias[-1:].isdigit() else ""
            intent_pattern = (
                rf"(?:用|使用|采用|套用|按|切换(?:到|为)?)\s*"
                rf"[‘’“”\"'「」『』]?\s*{escaped}{digit_guard}"
            )
            if re.search(intent_pattern, source, flags=re.IGNORECASE):
                return preset
            if re.fullmatch(r"风格\d+", alias, flags=re.IGNORECASE) and re.search(
                rf"{escaped}{digit_guard}", source, flags=re.IGNORECASE
            ):
                return preset
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
        enabled: bool = True,
    ) -> LoraPreset:
        normalized_category = normalize_category(category)
        normalized_name = self._normalize_name(name, normalized_category)
        normalized_selections = deduplicate_selections(selections)
        if not normalized_selections:
            raise LoraPresetError("LoRA 组合至少需要一个 LoRA")
        if len(normalized_selections) > self._max_loras:
            raise LoraPresetError(f"单个组合最多允许 {self._max_loras} 个 LoRA")
        preset = LoraPreset(
            name=normalized_name,
            category=normalized_category,
            selections=normalized_selections,
            trigger_words=trigger_words.strip(),
            description=description.strip(),
            enabled=enabled,
        )
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
                "enabled": preset.enabled,
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
            "Saved LoRA presets. Artist/style presets are complete base style stacks; copy every exact tag in order. Query character LoRAs separately and append them after the style stack."
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
            if detail and preset.description:
                line += f" | {preset.description[:300]}"
            lines.append(line)
        return "\n".join(lines)
