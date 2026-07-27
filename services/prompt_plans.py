"""Persistent, execution-neutral prompt plans for Prompt Lab and QQ drawing.

The store deliberately knows nothing about AstrBot events or ComfyUI.  It
only validates and atomically persists confirmed prompts under short stable
identifiers.  Callers must still route a resolved plan through the plugin's
ordinary permission, moderation, LoRA freshness and generation pipeline.

Bundled examples are materialized in memory and never written to the state
file.  Consequently an uploaded release cannot overwrite user plans and a
tampered state file cannot replace an ``EX-*`` example.
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROMPT_PLAN_SCHEMA = "astrbot-comfy-anima-prompt-plans"
PROMPT_PLAN_SCHEMA_VERSION = 1
MAX_CUSTOM_PLANS = 128
MAX_NAME_LENGTH = 80
MAX_PROMPT_LENGTH = 32_768
MAX_PIPELINE_LENGTH = 64
MAX_SOURCE_LENGTH = 128
MAX_LAYER_DEPTH = 8
MAX_LAYER_ITEMS = 512
MAX_LAYER_TEXT_LENGTH = 4096

_CUSTOM_ID_RE = re.compile(r"^P-[0-9A-F]{6}$")
_BUILTIN_ID_RE = re.compile(r"^EX-[0-9]{3}$")
_TRAILING_ANNOTATION_RE = re.compile(
    r"\s*(?:\([^()]+\)|（[^（）]+）|\[[^\[\]]+\]|【[^【】]+】)\s*$"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptPlanError(RuntimeError):
    """Base error for prompt-plan operations."""


class PromptPlanValidationError(PromptPlanError, ValueError):
    """Caller input or stored data does not satisfy the plan contract."""


class PromptPlanStorageError(PromptPlanError):
    """The state file could not be safely read or atomically replaced."""


class PromptPlanNotFoundError(PromptPlanError, LookupError):
    """No plan matches the supplied identifier or name."""


class PromptPlanAmbiguousError(PromptPlanError, LookupError):
    """A shortened name matches more than one plan."""


class PromptPlanConflictError(PromptPlanError):
    """A plan name already exists or an immutable example was targeted."""


class PromptPlanLimitError(PromptPlanError):
    """The custom-plan capacity has been reached."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _normalize_lookup(value: Any) -> str:
    if not isinstance(value, str):
        raise PromptPlanValidationError("plan identifier or name must be text")
    text = unicodedata.normalize("NFKC", value).strip()
    text = " ".join(text.split())
    if not text:
        raise PromptPlanValidationError("plan identifier or name must not be empty")
    return text.casefold()


def _clean_text(value: Any, *, label: str, limit: int, required: bool) -> str:
    if not isinstance(value, str):
        raise PromptPlanValidationError(f"{label} must be text")
    # Preserve user-facing punctuation and prompt syntax.  Compatibility
    # folding belongs only in lookup keys, never in persisted display text.
    text = unicodedata.normalize("NFC", value).strip()
    if required and not text:
        raise PromptPlanValidationError(f"{label} must not be empty")
    if _CONTROL_RE.search(text):
        raise PromptPlanValidationError(f"{label} contains control characters")
    if len(text) > limit:
        raise PromptPlanValidationError(f"{label} exceeds {limit} characters")
    return text


def _short_alias(name: str) -> str:
    """Return a name without one or more trailing bracketed annotations."""

    alias = name.strip()
    while True:
        shortened = _TRAILING_ANNOTATION_RE.sub("", alias).strip()
        if shortened == alias or not shortened:
            return alias
        alias = shortened


def _validate_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_LAYER_DEPTH:
        raise PromptPlanValidationError("layers nesting is too deep")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clean_text(
            value,
            label="layers text",
            limit=MAX_LAYER_TEXT_LENGTH,
            required=False,
        )
    if isinstance(value, Mapping):
        if len(value) > MAX_LAYER_ITEMS:
            raise PromptPlanValidationError("layers contains too many entries")
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _clean_text(
                raw_key,
                label="layers key",
                limit=128,
                required=True,
            )
            if key in normalized:
                raise PromptPlanValidationError(f"layers repeats key: {key}")
            normalized[key] = _validate_json_value(raw_value, depth=depth + 1)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        if len(value) > MAX_LAYER_ITEMS:
            raise PromptPlanValidationError("layers contains too many items")
        return [_validate_json_value(item, depth=depth + 1) for item in value]
    raise PromptPlanValidationError("layers must contain only JSON-compatible values")


def _normalize_locked_layers(value: Iterable[Any] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)):
        raise PromptPlanValidationError("locked_layers must be a sequence of text")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        layer = _clean_text(
            raw,
            label="locked layer",
            limit=64,
            required=True,
        ).casefold()
        if layer not in seen:
            seen.add(layer)
            result.append(layer)
    if len(result) > 32:
        raise PromptPlanValidationError("locked_layers contains too many items")
    return result


def _example(
    plan_id: str,
    name: str,
    positive_prompt: str,
    *,
    layers: Mapping[str, Any],
) -> dict[str, Any]:
    timestamp = "2026-07-26T00:00:00Z"
    return {
        "plan_id": plan_id,
        "name": name,
        "positive_prompt": positive_prompt,
        "negative_prompt": (
            "lowres, blurry, bad anatomy, bad hands, extra digits, missing digits, "
            "text, watermark, logo"
        ),
        "pipeline": "base",
        "layers": _copy(dict(layers)),
        "locked_layers": [],
        "source": "builtin_example",
        "builtin": True,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


BUILTIN_PROMPT_PLANS: tuple[dict[str, Any], ...] = (
    _example(
        "EX-001",
        "雨夜霓虹肖像",
        (
            "1girl, solo, portrait, looking at viewer, wet hair, black coat, "
            "city lights, neon lights, rain, night, reflections, shallow depth of field. "
            "A woman pauses beneath a shop awning while amber and cyan signs reflect "
            "across the rain-soaked street behind her."
        ),
        layers={
            "identity": ["1girl", "solo"],
            "clothing": ["black coat"],
            "pose": ["looking at viewer"],
            "camera": ["portrait", "shallow depth of field"],
            "background": ["city lights", "neon lights", "rain", "night", "reflections"],
            "style": [],
            "relation": "A woman pauses beneath a shop awning while neon signs reflect across the wet street.",
            "lora": [],
        },
    ),
    _example(
        "EX-002",
        "海边烟花全身",
        (
            "1girl, solo, full body, standing, looking at fireworks, summer dress, "
            "sandals, beach, ocean, night, fireworks, wind, rim lighting. A woman "
            "stands where the tide reaches the sand as fireworks bloom above the dark sea."
        ),
        layers={
            "identity": ["1girl", "solo"],
            "clothing": ["summer dress", "sandals"],
            "pose": ["standing", "looking at fireworks"],
            "camera": ["full body"],
            "background": ["beach", "ocean", "night", "fireworks"],
            "style": ["rim lighting"],
            "relation": "A woman stands at the tide line as fireworks bloom above the sea.",
            "lora": [],
        },
    ),
    _example(
        "EX-003",
        "和风庭院侧坐",
        (
            "1girl, solo, sitting sideways, hands on lap, kimono, hair ornament, "
            "japanese garden, engawa, maple leaves, stone lantern, afternoon, soft light. "
            "A woman sits sideways on a wooden veranda beside a quiet maple garden."
        ),
        layers={
            "identity": ["1girl", "solo"],
            "clothing": ["kimono", "hair ornament"],
            "pose": ["sitting sideways", "hands on lap"],
            "camera": [],
            "background": ["japanese garden", "engawa", "maple leaves", "stone lantern", "afternoon"],
            "style": ["soft light"],
            "relation": "A woman sits sideways on a veranda beside a quiet maple garden.",
            "lora": [],
        },
    ),
    _example(
        "EX-004",
        "低角度动作构图",
        (
            "1girl, solo, running, dynamic pose, coat tails, determined expression, "
            "from below, wide angle, foreshortening, city street, sunset, motion blur. "
            "A runner charges past the camera as her coat sweeps through the warm evening air."
        ),
        layers={
            "identity": ["1girl", "solo"],
            "clothing": ["coat tails"],
            "pose": ["running", "dynamic pose", "determined expression"],
            "camera": ["from below", "wide angle", "foreshortening"],
            "background": ["city street", "sunset"],
            "style": ["motion blur"],
            "relation": "A runner charges past the low camera as her coat sweeps through the air.",
            "lora": [],
        },
    ),
    _example(
        "EX-005",
        "咖啡馆暖光",
        (
            "1girl, solo, sitting, holding cup, gentle smile, knit sweater, cafe, "
            "window, wooden table, books, afternoon, warm light, dust particles. A woman "
            "warms her hands around a cup beside a sunlit cafe window."
        ),
        layers={
            "identity": ["1girl", "solo"],
            "clothing": ["knit sweater"],
            "pose": ["sitting", "holding cup", "gentle smile"],
            "camera": [],
            "background": ["cafe", "window", "wooden table", "books", "afternoon"],
            "style": ["warm light", "dust particles"],
            "relation": "A woman warms her hands around a cup beside a sunlit cafe window.",
            "lora": [],
        },
    ),
)


class PromptPlanStore:
    """Validate, resolve and atomically persist custom prompt plans."""

    def __init__(self, storage_path: str | Path):
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()

    def list_plans(
        self,
        *,
        keyword: Any = "",
        include_prompts: bool = True,
    ) -> list[dict[str, Any]]:
        query = ""
        if keyword not in (None, ""):
            query = _normalize_lookup(keyword)
        with self._lock:
            records = [*_copy(BUILTIN_PROMPT_PLANS), *self._read_state()["plans"].values()]
        if query:
            records = [
                record
                for record in records
                if query in _normalize_lookup(record["plan_id"])
                or query in _normalize_lookup(record["name"])
                or query in _normalize_lookup(_short_alias(record["name"]))
            ]
        records.sort(
            key=lambda item: (
                0 if item["builtin"] else 1,
                item["plan_id"],
            )
        )
        result = [_copy(record) for record in records]
        if not include_prompts:
            for record in result:
                record.pop("positive_prompt", None)
                record.pop("negative_prompt", None)
                record.pop("layers", None)
        return result

    def get_plan(self, selection: Any) -> dict[str, Any]:
        return self.resolve_plan(selection)

    def resolve_plan(self, selection: Any) -> dict[str, Any]:
        lookup = _normalize_lookup(selection)
        with self._lock:
            records = [*_copy(BUILTIN_PROMPT_PLANS), *self._read_state()["plans"].values()]

        id_matches = [
            record for record in records if _normalize_lookup(record["plan_id"]) == lookup
        ]
        if id_matches:
            return _copy(id_matches[0])

        full_matches = [
            record for record in records if _normalize_lookup(record["name"]) == lookup
        ]
        if len(full_matches) == 1:
            return _copy(full_matches[0])
        if len(full_matches) > 1:
            raise PromptPlanAmbiguousError(f"plan name is ambiguous: {selection}")

        alias_matches = [
            record
            for record in records
            if _normalize_lookup(_short_alias(record["name"])) == lookup
        ]
        if len(alias_matches) == 1:
            return _copy(alias_matches[0])
        if len(alias_matches) > 1:
            choices = ", ".join(record["plan_id"] for record in alias_matches)
            raise PromptPlanAmbiguousError(
                f"short plan name is ambiguous: {selection} ({choices})"
            )
        raise PromptPlanNotFoundError(f"prompt plan not found: {selection}")

    def save_plan(
        self,
        *,
        name: Any,
        positive_prompt: Any,
        negative_prompt: Any = "",
        pipeline: Any = "base",
        layers: Mapping[str, Any] | None = None,
        locked_layers: Iterable[Any] | None = None,
        source: Any = "prompt_lab",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        normalized_name = _clean_text(
            name,
            label="name",
            limit=MAX_NAME_LENGTH,
            required=True,
        )
        positive = _clean_text(
            positive_prompt,
            label="positive_prompt",
            limit=MAX_PROMPT_LENGTH,
            required=True,
        )
        negative = _clean_text(
            negative_prompt,
            label="negative_prompt",
            limit=MAX_PROMPT_LENGTH,
            required=False,
        )
        normalized_pipeline = _clean_text(
            pipeline,
            label="pipeline",
            limit=MAX_PIPELINE_LENGTH,
            required=True,
        ).casefold()
        normalized_source = _clean_text(
            source,
            label="source",
            limit=MAX_SOURCE_LENGTH,
            required=True,
        )
        normalized_layers = _validate_json_value(dict(layers or {}))
        normalized_locks = _normalize_locked_layers(locked_layers)
        name_key = _normalize_lookup(normalized_name)
        now = _utc_now()

        with self._lock:
            state = self._read_state()
            all_records = [*BUILTIN_PROMPT_PLANS, *state["plans"].values()]
            matches = [
                record
                for record in all_records
                if _normalize_lookup(record["name"]) == name_key
            ]
            if any(record["builtin"] for record in matches):
                raise PromptPlanConflictError("built-in prompt plans cannot be overwritten")
            previous = matches[0] if matches else None
            if previous is not None and not overwrite:
                raise PromptPlanConflictError(
                    f"prompt plan already exists: {previous['name']}"
                )
            if previous is None and len(state["plans"]) >= MAX_CUSTOM_PLANS:
                raise PromptPlanLimitError(
                    f"custom prompt-plan limit reached: {MAX_CUSTOM_PLANS}"
                )
            plan_id = previous["plan_id"] if previous else self._new_plan_id(state)
            record = {
                "plan_id": plan_id,
                "name": normalized_name,
                "positive_prompt": positive,
                "negative_prompt": negative,
                "pipeline": normalized_pipeline,
                "layers": normalized_layers,
                "locked_layers": normalized_locks,
                "source": normalized_source,
                "builtin": False,
                "created_at": previous["created_at"] if previous else now,
                "updated_at": now,
            }
            state["plans"][plan_id] = record
            self._write_state(state)
            return _copy(record)

    def delete_plan(self, selection: Any) -> dict[str, Any]:
        with self._lock:
            resolved = self.resolve_plan(selection)
            if resolved["builtin"]:
                raise PromptPlanConflictError("built-in prompt plans cannot be deleted")
            state = self._read_state()
            removed = state["plans"].pop(resolved["plan_id"], None)
            if removed is None:
                raise PromptPlanNotFoundError(
                    f"prompt plan not found: {resolved['plan_id']}"
                )
            self._write_state(state)
            return _copy(removed)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema": PROMPT_PLAN_SCHEMA,
            "version": PROMPT_PLAN_SCHEMA_VERSION,
            "plans": {},
        }

    @staticmethod
    def _new_plan_id(state: Mapping[str, Any]) -> str:
        occupied = set(state["plans"])
        for _ in range(128):
            candidate = f"P-{secrets.token_hex(3).upper()}"
            if candidate not in occupied:
                return candidate
        raise PromptPlanStorageError("could not allocate a unique prompt-plan id")

    def _read_state(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return self._empty_state()
        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PromptPlanStorageError(
                f"cannot read prompt-plan file {self.storage_path}: {exc}"
            ) from exc
        try:
            return self._validate_state(raw)
        except PromptPlanValidationError as exc:
            raise PromptPlanStorageError(f"prompt-plan file is invalid: {exc}") from exc

    def _validate_state(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise PromptPlanValidationError("state root must be an object")
        if raw.get("schema") != PROMPT_PLAN_SCHEMA:
            raise PromptPlanValidationError("state schema does not match")
        if raw.get("version") != PROMPT_PLAN_SCHEMA_VERSION:
            raise PromptPlanValidationError("state version is unsupported")
        raw_plans = raw.get("plans")
        if not isinstance(raw_plans, Mapping):
            raise PromptPlanValidationError("state plans must be an object")
        if len(raw_plans) > MAX_CUSTOM_PLANS:
            raise PromptPlanValidationError("state exceeds the custom-plan limit")

        plans: dict[str, dict[str, Any]] = {}
        names: set[str] = set()
        required_fields = {
            "plan_id",
            "name",
            "positive_prompt",
            "negative_prompt",
            "pipeline",
            "layers",
            "locked_layers",
            "source",
            "builtin",
            "created_at",
            "updated_at",
        }
        builtin_names = {_normalize_lookup(item["name"]) for item in BUILTIN_PROMPT_PLANS}
        for raw_id, raw_record in raw_plans.items():
            if not isinstance(raw_id, str) or not isinstance(raw_record, Mapping):
                raise PromptPlanValidationError("stored plan record is malformed")
            if set(raw_record) != required_fields:
                raise PromptPlanValidationError(
                    f"stored plan {raw_id} has invalid fields"
                )
            plan_id = str(raw_record.get("plan_id") or "").upper()
            if raw_id != plan_id or not _CUSTOM_ID_RE.fullmatch(plan_id):
                raise PromptPlanValidationError(f"stored plan id is invalid: {raw_id}")
            if _BUILTIN_ID_RE.fullmatch(plan_id) or raw_record.get("builtin") is not False:
                raise PromptPlanValidationError("stored plans cannot be built-in")
            name = _clean_text(
                raw_record.get("name"),
                label="name",
                limit=MAX_NAME_LENGTH,
                required=True,
            )
            name_key = _normalize_lookup(name)
            if name_key in names or name_key in builtin_names:
                raise PromptPlanValidationError(f"stored plan name conflicts: {name}")
            names.add(name_key)
            created_at = _clean_text(
                raw_record.get("created_at"),
                label="created_at",
                limit=64,
                required=True,
            )
            updated_at = _clean_text(
                raw_record.get("updated_at"),
                label="updated_at",
                limit=64,
                required=True,
            )
            layers = raw_record.get("layers")
            if not isinstance(layers, Mapping):
                raise PromptPlanValidationError("layers must be an object")
            plans[plan_id] = {
                "plan_id": plan_id,
                "name": name,
                "positive_prompt": _clean_text(
                    raw_record.get("positive_prompt"),
                    label="positive_prompt",
                    limit=MAX_PROMPT_LENGTH,
                    required=True,
                ),
                "negative_prompt": _clean_text(
                    raw_record.get("negative_prompt"),
                    label="negative_prompt",
                    limit=MAX_PROMPT_LENGTH,
                    required=False,
                ),
                "pipeline": _clean_text(
                    raw_record.get("pipeline"),
                    label="pipeline",
                    limit=MAX_PIPELINE_LENGTH,
                    required=True,
                ).casefold(),
                "layers": _validate_json_value(layers),
                "locked_layers": _normalize_locked_layers(
                    raw_record.get("locked_layers")
                ),
                "source": _clean_text(
                    raw_record.get("source"),
                    label="source",
                    limit=MAX_SOURCE_LENGTH,
                    required=True,
                ),
                "builtin": False,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        return {
            "schema": PROMPT_PLAN_SCHEMA,
            "version": PROMPT_PLAN_SCHEMA_VERSION,
            "plans": plans,
        }

    def _write_state(self, state: Mapping[str, Any]) -> None:
        validated = self._validate_state(state)
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PromptPlanStorageError(
                f"cannot create prompt-plan directory {self.storage_path.parent}: {exc}"
            ) from exc

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{self.storage_path.name}.",
                suffix=".tmp",
                dir=self.storage_path.parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(
                    validated,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.storage_path)
            temporary_path = None
            try:
                os.chmod(self.storage_path, 0o600)
            except OSError:
                pass
        except (OSError, TypeError, ValueError) as exc:
            raise PromptPlanStorageError(
                f"cannot atomically save prompt-plan file {self.storage_path}: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = [
    "BUILTIN_PROMPT_PLANS",
    "MAX_CUSTOM_PLANS",
    "PROMPT_PLAN_SCHEMA",
    "PROMPT_PLAN_SCHEMA_VERSION",
    "PromptPlanAmbiguousError",
    "PromptPlanConflictError",
    "PromptPlanError",
    "PromptPlanLimitError",
    "PromptPlanNotFoundError",
    "PromptPlanStorageError",
    "PromptPlanStore",
    "PromptPlanValidationError",
]
