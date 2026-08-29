"""Session-scoped picture recipe persistence for continuation requests.

A recipe stores the last successfully delivered picture plan for one
(bot, session, user) tuple.  Recipes never expire by calendar time.  They are
invalidated when the plugin version changes on the first ``initialize()``
after an update, or when the content they depend on (preset, LoRA fingerprint,
model family) changes.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .preset_manifest import LoraManifestEntry, PresetManifest


SESSION_RECIPE_SCHEMA_VERSION = 1


class SessionRecipeError(RuntimeError):
    """Raised when the recipe store cannot be read or written safely."""


@dataclass(frozen=True)
class SessionPictureRecipe:
    """Last successful picture plan for one conversation scope."""

    schema_version: int = SESSION_RECIPE_SCHEMA_VERSION
    bot_id: str = ""
    session_id: str = ""
    user_id: str = ""
    last_run_id: str = ""
    preset_name: str = ""
    pipeline: str = ""
    width: int = 0
    height: int = 0
    prompt_recipe: str = ""
    positive_pool: tuple[str, ...] = ()
    negative_pool: tuple[str, ...] = ()
    lora_manifest: tuple[LoraManifestEntry, ...] = ()
    model_family: str = ""
    identity_anchor: str = ""
    required_triggers: tuple[str, ...] = ()
    manifest_hash: str = ""
    content_fingerprint: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def from_success(
        cls,
        *,
        bot_id: str,
        session_id: str,
        user_id: str,
        run_id: str,
        preset_name: str,
        pipeline: str,
        width: int,
        height: int,
        prompt_recipe: str,
        manifest: PresetManifest,
        content_fingerprint: str,
    ) -> "SessionPictureRecipe":
        """Build a recipe only from a verified successful submission."""

        now = time.time()
        return cls(
            bot_id=str(bot_id or "").strip(),
            session_id=str(session_id or "").strip(),
            user_id=str(user_id or "").strip(),
            last_run_id=str(run_id or "").strip(),
            preset_name=str(preset_name or "").strip(),
            pipeline=str(pipeline or "").strip(),
            width=max(0, int(width or 0)),
            height=max(0, int(height or 0)),
            prompt_recipe=str(prompt_recipe or "")[:32_768],
            positive_pool=tuple(manifest.positive_terms),
            negative_pool=tuple(manifest.negative_terms),
            lora_manifest=tuple(manifest.lora_entries),
            model_family=manifest.model_family,
            identity_anchor=manifest.identity_anchor,
            required_triggers=tuple(manifest.required_triggers),
            manifest_hash=manifest.manifest_hash,
            content_fingerprint=str(content_fingerprint or "").strip()[:160],
            created_at=now,
            updated_at=now,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bot_id": self.bot_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "last_run_id": self.last_run_id,
            "preset_name": self.preset_name,
            "pipeline": self.pipeline,
            "width": self.width,
            "height": self.height,
            "prompt_recipe": self.prompt_recipe,
            "positive_pool": list(self.positive_pool),
            "negative_pool": list(self.negative_pool),
            "lora_manifest": [
                {
                    "name": entry.name,
                    "weight": entry.weight,
                    "model_family": entry.model_family,
                }
                for entry in self.lora_manifest
            ],
            "model_family": self.model_family,
            "identity_anchor": self.identity_anchor,
            "required_triggers": list(self.required_triggers),
            "manifest_hash": self.manifest_hash,
            "content_fingerprint": self.content_fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SessionPictureRecipe":
        try:
            manifest = PresetManifest.build(
                preset_name=value.get("preset_name", ""),
                positive_terms=value.get("positive_pool", ()),
                negative_terms=value.get("negative_pool", ()),
                lora_entries=value.get("lora_manifest", ()),
                model_family=value.get("model_family", ""),
                identity_anchor=value.get("identity_anchor", ""),
                required_triggers=value.get("required_triggers", ()),
            )
        except ValueError as exc:
            raise SessionRecipeError(f"invalid stored recipe manifest: {exc}") from exc
        try:
            created_at = float(value.get("created_at") or 0.0)
            updated_at = float(value.get("updated_at") or 0.0)
        except (TypeError, ValueError) as exc:
            raise SessionRecipeError("invalid recipe timestamp") from exc
        return cls(
            schema_version=int(value.get("schema_version") or SESSION_RECIPE_SCHEMA_VERSION),
            bot_id=str(value.get("bot_id") or "").strip(),
            session_id=str(value.get("session_id") or "").strip(),
            user_id=str(value.get("user_id") or "").strip(),
            last_run_id=str(value.get("last_run_id") or "").strip(),
            preset_name=str(value.get("preset_name") or "").strip(),
            pipeline=str(value.get("pipeline") or "").strip(),
            width=max(0, int(value.get("width") or 0)),
            height=max(0, int(value.get("height") or 0)),
            prompt_recipe=str(value.get("prompt_recipe") or "")[:32_768],
            positive_pool=tuple(manifest.positive_terms),
            negative_pool=tuple(manifest.negative_terms),
            lora_manifest=tuple(manifest.lora_entries),
            model_family=manifest.model_family,
            identity_anchor=manifest.identity_anchor,
            required_triggers=tuple(manifest.required_triggers),
            manifest_hash=manifest.manifest_hash,
            content_fingerprint=str(value.get("content_fingerprint") or "").strip()[:160],
            created_at=created_at,
            updated_at=updated_at,
        )

    def is_empty(self) -> bool:
        return not self.last_run_id or not self.preset_name

    def key(self) -> tuple[str, str, str]:
        return (self.bot_id, self.session_id, self.user_id)


def recipe_key(bot_id: str, session_id: str, user_id: str) -> str:
    """Build a stable, collision-safe store key for one conversation scope."""

    bot = str(bot_id or "").strip().casefold()
    session = str(session_id or "").strip()
    user = str(user_id or "").strip()
    if not session:
        raise SessionRecipeError("session_id must not be empty")
    return f"{bot}|{session}|{user}"


class SessionPictureRecipeStore:
    """JSON-file backed recipe store with update-time invalidation."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._envelope: dict[str, Any] | None = None

    def _load_envelope(self) -> dict[str, Any]:
        if self._envelope is not None:
            return self._envelope
        if not self.path.is_file():
            envelope: dict[str, Any] = {
                "schema_version": SESSION_RECIPE_SCHEMA_VERSION,
                "last_loaded_plugin_version": "",
                "recipes": {},
            }
            self._envelope = envelope
            return envelope
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise SessionRecipeError(f"recipe store is unreadable: {exc}") from exc
        if not isinstance(raw, dict):
            raise SessionRecipeError("recipe store root must be an object")
        if int(raw.get("schema_version") or 0) != SESSION_RECIPE_SCHEMA_VERSION:
            # A schema change invalidates every historical recipe.
            raw = {
                "schema_version": SESSION_RECIPE_SCHEMA_VERSION,
                "last_loaded_plugin_version": "",
                "recipes": {},
            }
        recipes = raw.get("recipes")
        if not isinstance(recipes, dict):
            recipes = {}
        self._envelope = {
            "schema_version": SESSION_RECIPE_SCHEMA_VERSION,
            "last_loaded_plugin_version": str(
                raw.get("last_loaded_plugin_version") or ""
            ).strip(),
            "recipes": recipes,
        }
        return self._envelope

    def _persist_locked(self) -> None:
        envelope = self._envelope
        if envelope is None:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def initialize(
        self,
        plugin_version: str,
        *,
        invalidate_on_change: bool = True,
    ) -> bool:
        """Invalidate all recipes on the first load after a plugin update.

        Returns True when the store was cleared due to a version change.
        """

        async with self._lock:
            envelope = self._load_envelope()
            version = str(plugin_version or "").strip()
            stored = str(envelope.get("last_loaded_plugin_version") or "").strip()
            if stored == version:
                return False
            envelope["last_loaded_plugin_version"] = version
            if not invalidate_on_change:
                self._persist_locked()
                return False
            envelope["recipes"] = {}
            self._persist_locked()
            return True

    async def get(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
        *,
        expected_content_fingerprint: str = "",
    ) -> SessionPictureRecipe | None:
        key = recipe_key(bot_id, session_id, user_id)
        async with self._lock:
            envelope = self._load_envelope()
            raw = envelope.get("recipes", {}).get(key)
        if not isinstance(raw, dict):
            return None
        try:
            recipe = SessionPictureRecipe.from_mapping(raw)
        except SessionRecipeError:
            return None
        if recipe.is_empty():
            return None
        if (
            expected_content_fingerprint
            and recipe.content_fingerprint != expected_content_fingerprint
        ):
            return None
        return recipe

    async def put(self, recipe: SessionPictureRecipe) -> None:
        if recipe.is_empty():
            raise SessionRecipeError("refusing to store an empty recipe")
        key = recipe_key(recipe.bot_id, recipe.session_id, recipe.user_id)
        async with self._lock:
            envelope = self._load_envelope()
            envelope["recipes"][key] = recipe.to_mapping()
            self._persist_locked()

    async def invalidate_for_content(
        self,
        *,
        preset_name: str = "",
        model_family: str = "",
        lora_fingerprint: str = "",
    ) -> int:
        """Drop recipes whose dependent content changed."""

        removed = 0
        async with self._lock:
            envelope = self._load_envelope()
            recipes = envelope.get("recipes", {})
            for key in list(recipes.keys()):
                raw = recipes.get(key)
                if not isinstance(raw, dict):
                    recipes.pop(key, None)
                    removed += 1
                    continue
                if preset_name and str(raw.get("preset_name") or "").casefold() != str(
                    preset_name
                ).casefold():
                    continue
                if model_family and str(raw.get("model_family") or "").casefold() != str(
                    model_family
                ).casefold():
                    continue
                if lora_fingerprint and str(
                    raw.get("content_fingerprint") or ""
                ) == str(lora_fingerprint):
                    # Same content fingerprint: the recipe is still current.
                    continue
                recipes.pop(key, None)
                removed += 1
            if removed:
                self._persist_locked()
        return removed

    async def clear_all(self) -> int:
        async with self._lock:
            envelope = self._load_envelope()
            removed = len(envelope.get("recipes", {}))
            envelope["recipes"] = {}
            self._persist_locked()
            return removed

    def stored_version(self) -> str:
        envelope = self._load_envelope()
        return str(envelope.get("last_loaded_plugin_version") or "").strip()
