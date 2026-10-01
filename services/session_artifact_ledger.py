"""Session-scoped registry of images this plugin has delivered.

The ledger answers one question before an edit-style request (重绘 /
底图控制 / ``<edit>``) chooses its invariants: *is the target image
something this plugin generated in this conversation?*  A SHA-256
exact hit authorises attaching the session recipe's identity
invariants (character LoRA stack, anchor, manifest gate); a miss
degrades gracefully to the pre-change behaviour.  QQ may recompress
images on round-trips, so misses are expected and harmless — only
exact hits are ever trusted, this ledger never guesses.

Entries are keyed by ``(bot, session, user)`` like
:class:`~services.session_picture_recipe.SessionPictureRecipeStore`
and retained for :data:`SESSION_ARTIFACT_RETENTION_DAYS`, aligned
with ``TaskStore.DEFAULT_RETENTION_DAYS``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SESSION_ARTIFACT_SCHEMA_VERSION = 1
SESSION_ARTIFACT_RETENTION_DAYS = 30
SESSION_ARTIFACT_MAX_PER_KEY = 24


class SessionArtifactLedgerError(RuntimeError):
    """Raised when the artifact ledger cannot be read or written safely."""


def artifact_key(bot_id: str, session_id: str, user_id: str) -> str:
    """Return the stable per-conversation ledger key."""

    return (
        f"{str(bot_id or '').strip().casefold()}"
        f"|{str(session_id or '').strip()}"
        f"|{str(user_id or '').strip()}"
    )


@dataclass(frozen=True)
class SessionArtifact:
    """One delivered image recorded for provenance matching."""

    sha256: str = ""
    width: int = 0
    height: int = 0
    run_id: str = ""
    created_at: float = 0.0

    def to_mapping(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "SessionArtifact | None":
        if not isinstance(value, dict):
            return None
        sha = str(value.get("sha256") or "").strip().casefold()
        if not sha:
            return None
        try:
            width = max(0, int(value.get("width") or 0))
            height = max(0, int(value.get("height") or 0))
            created_at = float(value.get("created_at") or 0.0)
        except (TypeError, ValueError):
            return None
        return cls(
            sha256=sha,
            width=width,
            height=height,
            run_id=str(value.get("run_id") or "").strip(),
            created_at=created_at,
        )


class SessionArtifactLedger:
    """Persistent per-conversation registry of delivered image hashes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._entries: dict[str, list[SessionArtifact]] = {}
        self._loaded = False

    def _load_envelope(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty_envelope()
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionArtifactLedgerError(
                f"session artifact ledger is unreadable: {exc}"
            ) from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != (
            SESSION_ARTIFACT_SCHEMA_VERSION
        ):
            return self._empty_envelope()
        entries: dict[str, list[SessionArtifact]] = {}
        stored = raw.get("entries")
        if isinstance(stored, dict):
            for key, items in stored.items():
                if not isinstance(items, list):
                    continue
                parsed = [
                    artifact
                    for artifact in (
                        SessionArtifact.from_mapping(item) for item in items
                    )
                    if artifact is not None
                ]
                if parsed:
                    entries[str(key)] = parsed
        return {"schema_version": SESSION_ARTIFACT_SCHEMA_VERSION, "entries": entries}

    @staticmethod
    def _empty_envelope() -> dict[str, Any]:
        return {"schema_version": SESSION_ARTIFACT_SCHEMA_VERSION, "entries": {}}

    def _persist_locked(self) -> None:
        payload = {
            "schema_version": SESSION_ARTIFACT_SCHEMA_VERSION,
            "entries": {
                key: [artifact.to_mapping() for artifact in items]
                for key, items in self._entries.items()
            },
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _prune_locked(self, now: float) -> None:
        cutoff = now - SESSION_ARTIFACT_RETENTION_DAYS * 86400.0
        fresh: dict[str, list[SessionArtifact]] = {}
        for key, items in self._entries.items():
            kept = [item for item in items if item.created_at >= cutoff]
            kept = sorted(kept, key=lambda item: item.created_at)[
                -SESSION_ARTIFACT_MAX_PER_KEY:
            ]
            if kept:
                fresh[key] = kept
        self._entries = fresh

    async def initialize(self) -> bool:
        """Load the ledger from disk; returns True when entries exist."""

        async with self._lock:
            envelope = self._load_envelope()
            self._entries = envelope["entries"]
            self._loaded = True
            self._prune_locked(time.time())
            if self._entries:
                self._persist_locked()
            return bool(self._entries)

    async def record(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
        *,
        sha256: str,
        width: int,
        height: int,
        run_id: str = "",
    ) -> None:
        """Register one delivered image, newest first, bounded per key."""

        sha = str(sha256 or "").strip().casefold()
        if not sha or not str(session_id or "").strip():
            return
        async with self._lock:
            if not self._loaded:
                envelope = self._load_envelope()
                self._entries = envelope["entries"]
                self._loaded = True
            key = artifact_key(bot_id, session_id, user_id)
            items = [
                item
                for item in self._entries.get(key, [])
                if item.sha256 != sha
            ]
            items.append(
                SessionArtifact(
                    sha256=sha,
                    width=max(0, int(width or 0)),
                    height=max(0, int(height or 0)),
                    run_id=str(run_id or "").strip(),
                    created_at=time.time(),
                )
            )
            self._entries[key] = items[-SESSION_ARTIFACT_MAX_PER_KEY:]
            try:
                self._prune_locked(time.time())
                self._persist_locked()
            except OSError as exc:
                raise SessionArtifactLedgerError(
                    f"session artifact ledger write failed: {exc}"
                ) from exc

    async def is_artifact(
        self,
        bot_id: str,
        session_id: str,
        user_id: str,
        sha256: str,
    ) -> bool:
        """Return True when the sha exactly matches a delivered image."""

        sha = str(sha256 or "").strip().casefold()
        if not sha or not str(session_id or "").strip():
            return False
        async with self._lock:
            if not self._loaded:
                envelope = self._load_envelope()
                self._entries = envelope["entries"]
                self._loaded = True
            key = artifact_key(bot_id, session_id, user_id)
            return any(item.sha256 == sha for item in self._entries.get(key, []))

    async def clear(self) -> None:
        async with self._lock:
            self._entries = {}
            self._persist_locked()
