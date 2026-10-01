"""Persistent per-user picture preferences.

The store writes a small JSON document at the configured path.  It is safe to
share one store instance from the AstrBot event loop; writes are serialized
with a process-local lock and atomically replace the file.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from .log_console import redact_log_text


class UserPicturePreferencesError(RuntimeError):
    """The preference store could not complete an operation."""


def _preference_payload(value: Any) -> dict[str, Any]:
    """Return a JSON-safe preference mapping with secret-ish keys redacted."""
    if not isinstance(value, Mapping):
        return {}
    payload: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key or "").strip().casefold().replace("-", "_")
        if normalized in {"api_key", "apikey", "token", "password", "secret", "cookie"}:
            payload[str(key)] = "***"
        elif isinstance(item, Mapping):
            payload[str(key)] = _preference_payload(item)
        elif isinstance(item, (list, tuple)):
            payload[str(key)] = [
                _preference_payload(entry) if isinstance(entry, Mapping) else entry
                for entry in item[:200]
            ]
        elif isinstance(item, (str, int, float, bool)) or item is None:
            payload[str(key)] = (
                redact_log_text(str(item)) if isinstance(item, str) else item
            )
        else:
            payload[str(key)] = redact_log_text(str(item))[:1000]
    return payload


class UserPicturePreferencesStore:
    """JSON file store for per-user picture preferences with optional TTL."""

    _SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Path | str,
        *,
        ttl_seconds: float = 0.0,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def save_preference(
        self,
        user_id: str,
        preference: Mapping[str, Any],
        *,
        timestamp: Optional[float] = None,
    ) -> dict[str, Any]:
        """Save one user's picture preference and return the stored record."""
        user_key = str(user_id or "").strip()
        if not user_key:
            raise ValueError("user_id must not be empty")
        now = float(time.time() if timestamp is None else timestamp)
        record = {
            "user_id": user_key,
            "preference": _preference_payload(preference),
            "updated_at": now,
        }
        with self._lock:
            self._entries[user_key] = record
            self._save_locked()
        return dict(record)

    def get_preference(
        self,
        user_id: str,
        *,
        timestamp: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """Return the user's stored preference, or ``None`` when absent/expired."""
        user_key = str(user_id or "").strip()
        if not user_key:
            return None
        now = float(time.time() if timestamp is None else timestamp)
        with self._lock:
            record = self._entries.get(user_key)
            if record is None:
                return None
            updated_at = float(record.get("updated_at") or 0.0)
            if self.ttl_seconds > 0 and now - updated_at > self.ttl_seconds:
                self._entries.pop(user_key, None)
                self._save_locked()
                return None
            preference = record.get("preference")
            return dict(preference) if isinstance(preference, Mapping) else None

    def clear_preference(
        self,
        user_id: str,
        *,
        timestamp: Optional[float] = None,
    ) -> bool:
        """Remove one user's preference; return ``True`` if it existed."""
        del timestamp
        user_key = str(user_id or "").strip()
        if not user_key:
            return False
        with self._lock:
            removed = self._entries.pop(user_key, None) is not None
            if removed:
                self._save_locked()
            return removed

    def clear_all(self) -> int:
        """Remove every stored preference and return the removed count."""
        with self._lock:
            count = len(self._entries)
            if count:
                self._entries.clear()
                self._save_locked()
            return count

    def all_preferences(self) -> dict[str, dict[str, Any]]:
        """Return a copy of all current preference records keyed by user id."""
        with self._lock:
            return {
                key: dict(record)
                for key, record in self._entries.items()
                if isinstance(record, Mapping)
            }

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            raise UserPicturePreferencesError(
                f"Unable to read user picture preferences: {exc}"
            ) from exc
        try:
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise UserPicturePreferencesError(
                f"Invalid user picture preferences JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("version") != self._SCHEMA_VERSION:
            raise UserPicturePreferencesError(
                f"Unsupported user picture preferences schema: {payload.get('version')!r}"
            )
        entries = payload.get("preferences")
        if not isinstance(entries, dict):
            raise UserPicturePreferencesError("Missing preferences object in store")
        self._entries = {
            str(key): dict(record)
            for key, record in entries.items()
            if isinstance(record, Mapping)
        }

    def _save_locked(self) -> None:
        payload = {
            "version": self._SCHEMA_VERSION,
            "preferences": self._entries,
        }
        try:
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise UserPicturePreferencesError(
                f"Unable to write user picture preferences: {exc}"
            ) from exc


__all__ = [
    "UserPicturePreferencesError",
    "UserPicturePreferencesStore",
]
