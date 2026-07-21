"""Immutable task-level LoRA catalog snapshots.

One drawing operation may query the catalog several times while the LLM plans
the prompt.  Those reads must observe one authoritative view instead of
rescanning LoRA Manager for every tool call.  A separate final refresh is still
performed immediately before workflow submission.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

from ..core.lora import canonical_lora_name
from .lora_catalog import LoraRecord


def record_identity(record: LoraRecord) -> tuple[str, str, str]:
    """Return the load-path, content hash and semantic source identity."""

    name = canonical_lora_name(getattr(record, "name", "")).casefold()
    digest = str(getattr(record, "sha256", "") or "").strip().casefold()
    source = str(getattr(record, "source_fingerprint", "") or "").strip().casefold()
    return name, digest, source


def catalog_fingerprint(records: Iterable[LoraRecord]) -> str:
    """Hash only stable, non-sensitive catalog identity fields."""

    material = sorted(record_identity(record) for record in records)
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LoraOperationSnapshot:
    """Frozen LoRA view reused by every planning read in one user operation."""

    records: tuple[LoraRecord, ...]
    fingerprint: str
    captured_at: float
    refresh_count: int = 1

    @classmethod
    def capture(cls, records: Iterable[LoraRecord]) -> "LoraOperationSnapshot":
        frozen = tuple(records)
        return cls(
            records=frozen,
            fingerprint=catalog_fingerprint(frozen),
            captured_at=time.monotonic(),
        )

    def age(self, *, now: float | None = None) -> float:
        return max(0.0, (time.monotonic() if now is None else now) - self.captured_at)

    def record_map(self) -> dict[str, LoraRecord]:
        return {record_identity(record)[0]: record for record in self.records}

    def selected_fingerprint(self, names: Iterable[Any]) -> str:
        wanted = {
            str(name or "").replace("\\", "/").casefold()
            for name in names
            if str(name or "").strip()
        }
        identities = sorted(
            record_identity(record)
            for record in self.records
            if record_identity(record)[0] in wanted
        )
        encoded = json.dumps(identities, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
