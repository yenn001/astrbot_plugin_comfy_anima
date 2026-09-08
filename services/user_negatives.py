"""Per-conversation sticky negative terms ("以后都别画X" / "可以画X了").

Distinct from the session recipe's negative pool: entries here are added
and removed only by explicit user instructions (registered through the
deterministic phrase classifier or the ``/别画`` / ``/解禁`` commands),
never by absorbtion of one-shot director negatives.  Terms are merged
into every drawing's final negative prompt and therefore participate in
the preset-manifest audit.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_NEGATIVES_SCHEMA_VERSION = 1
USER_NEGATIVES_MAX_PER_KEY = 64


class UserNegativesStoreError(RuntimeError):
    """Raised when the sticky-negative store cannot be read or written."""


def user_negatives_key(bot_id: str, session_id: str, user_id: str) -> str:
    """Return the stable per-conversation store key."""

    return (
        f"{str(bot_id or '').strip().casefold()}"
        f"|{str(session_id or '').strip()}"
        f"|{str(user_id or '').strip()}"
    )


@dataclass(frozen=True)
class StickyNegativeTerm:
    """One sticky exclusion registered by an explicit user instruction."""

    term: str = ""
    registered_at: float = 0.0

    def to_mapping(self) -> dict[str, Any]:
        return {"term": self.term, "registered_at": self.registered_at}

    @classmethod
    def from_mapping(cls, value: Any) -> "StickyNegativeTerm | None":
        if not isinstance(value, dict):
            return None
        term = str(value.get("term") or "").strip()
        if not term:
            return None
        try:
            registered_at = float(value.get("registered_at") or 0.0)
        except (TypeError, ValueError):
            registered_at = 0.0
        return cls(term=term, registered_at=registered_at)


class UserNegativesStore:
    """Persistent sticky negative terms keyed per conversation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._entries: dict[str, list[StickyNegativeTerm]] = {}
        self._loaded = False

    def _load_envelope(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty_envelope()
        except (OSError, json.JSONDecodeError) as exc:
            raise UserNegativesStoreError(
                f"user negatives store is unreadable: {exc}"
            ) from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != (
            USER_NEGATIVES_SCHEMA_VERSION
        ):
            return self._empty_envelope()
        entries: dict[str, list[StickyNegativeTerm]] = {}
        stored = raw.get("entries")
        if isinstance(stored, dict):
            for key, items in stored.items():
                if not isinstance(items, list):
                    continue
                parsed = [
                    term
                    for term in (
                        StickyNegativeTerm.from_mapping(item) for item in items
                    )
                    if term is not None
                ]
                if parsed:
                    entries[str(key)] = parsed
        return {"schema_version": USER_NEGATIVES_SCHEMA_VERSION, "entries": entries}

    @staticmethod
    def _empty_envelope() -> dict[str, Any]:
        return {"schema_version": USER_NEGATIVES_SCHEMA_VERSION, "entries": {}}

    def _persist_locked(self) -> None:
        payload = {
            "schema_version": USER_NEGATIVES_SCHEMA_VERSION,
            "entries": {
                key: [term.to_mapping() for term in items]
                for key, items in self._entries.items()
            },
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _ensure_loaded_locked(self) -> None:
        if not self._loaded:
            envelope = self._load_envelope()
            self._entries = envelope["entries"]
            self._loaded = True

    @staticmethod
    def _norm(term: str) -> str:
        return str(term or "").strip().casefold()

    async def add(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
        term: str,
    ) -> bool:
        """Register one sticky exclusion; returns False when it existed."""

        clean = str(term or "").strip()
        if not clean or not str(session_id or "").strip():
            return False
        async with self._lock:
            self._ensure_loaded_locked()
            key = user_negatives_key(bot_id, session_id, user_id)
            items = self._entries.get(key, [])
            if any(self._norm(item.term) == self._norm(clean) for item in items):
                return False
            items = [
                item
                for item in items
                if item.term != clean
            ]
            items.append(
                StickyNegativeTerm(term=clean, registered_at=time.time())
            )
            self._entries[key] = items[-USER_NEGATIVES_MAX_PER_KEY:]
            try:
                self._persist_locked()
            except OSError as exc:
                raise UserNegativesStoreError(
                    f"user negatives store write failed: {exc}"
                ) from exc
            return True

    async def remove(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
        term: str,
    ) -> bool:
        """Remove one sticky exclusion (exact, then casefold fallback)."""

        clean = str(term or "").strip()
        if not clean or not str(session_id or "").strip():
            return False
        async with self._lock:
            self._ensure_loaded_locked()
            key = user_negatives_key(bot_id, session_id, user_id)
            items = self._entries.get(key, [])
            remaining = [item for item in items if item.term != clean]
            if len(remaining) == len(items):
                norm = self._norm(clean)
                remaining = [
                    item for item in items if self._norm(item.term) != norm
                ]
            if len(remaining) == len(items):
                return False
            if remaining:
                self._entries[key] = remaining
            else:
                self._entries.pop(key, None)
            try:
                self._persist_locked()
            except OSError as exc:
                raise UserNegativesStoreError(
                    f"user negatives store write failed: {exc}"
                ) from exc
            return True

    async def terms(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
    ) -> tuple[str, ...]:
        """Return the sticky exclusion terms merged into every drawing."""

        async with self._lock:
            self._ensure_loaded_locked()
            key = user_negatives_key(bot_id, session_id, user_id)
            return tuple(item.term for item in self._entries.get(key, []))

    async def all_entries(self) -> dict[str, list[dict[str, Any]]]:
        """Return every key's terms for the Web console panel."""

        async with self._lock:
            self._ensure_loaded_locked()
            return {
                key: [term.to_mapping() for term in items]
                for key, items in self._entries.items()
            }
