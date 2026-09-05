"""Append-only intent judge decision ledger (Stage 1 contract).

Ordinary no-draw messages have no task run, so decisions are persisted
here instead of TaskStore. Records are self-verifying: every line has a
top-level ``hash`` over the other fields. Integrity checks cover start
record hashes, ordering, duplicate starts/results, and corrupted JSONL.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class IntentDecisionLedgerError(RuntimeError):
    """Raised when the decision ledger cannot be written or validated."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _record_hash(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return stored hash and recomputed hash for a record."""
    without = dict(record)
    stored = str(without.pop("hash", "") or "")
    recomputed = hashlib.sha256(
        json.dumps(without, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return stored, recomputed


class IntentDecisionLedger:
    """JSONL append-only ledger with fsync and restart-safe integrity checks."""

    def __init__(
        self,
        path: Path,
        *,
        public_version: str,
        internal_target_version: str,
    ) -> None:
        self._path = Path(path)
        self._public_version = public_version
        self._internal_target_version = internal_target_version
        self._started, self._corrupt = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def start(
        self,
        *,
        user_message: str,
        user_id_hash: str,
        context_hash: str,
        context_source: str = "",
    ) -> str:
        if self._corrupt:
            raise IntentDecisionLedgerError("decision ledger is corrupted")
        decision_id = uuid.uuid4().hex
        record = self._record(
            event="intent_judge_start",
            decision_id=decision_id,
            user_message_hash=hashlib.sha256(
                str(user_message or "").encode("utf-8")
            ).hexdigest(),
            user_id_hash=str(user_id_hash or ""),
            context_hash=str(context_hash or ""),
            context_source=str(context_source or ""),
        )
        self._append(record)
        self._started.add(decision_id)
        return decision_id

    def result(self, decision_id: str, result: Any) -> str:
        if self._corrupt:
            raise IntentDecisionLedgerError("decision ledger is corrupted")
        if decision_id not in self._started:
            raise IntentDecisionLedgerError(
                f"decision result without start: {decision_id!r}"
            )
        records = self._read_raw_records()
        for record in records:
            if record.get("decision_id") != decision_id:
                continue
            if record.get("event") == "intent_judge_result":
                raise IntentDecisionLedgerError(
                    f"duplicate result for decision {decision_id!r}"
                )
        record = self._record(
            event="intent_judge_result",
            decision_id=decision_id,
            decision=str(getattr(result, "decision", "") or ""),
            confidence=float(getattr(result, "confidence", 0.0) or 0.0),
            backend_used=str(getattr(result, "backend_used", "") or ""),
            reason=str(getattr(result, "reason", "") or ""),
            latency_ms=float(getattr(result, "latency_ms", 0.0) or 0.0),
            trace_json=_canonical_json(getattr(result, "trace", {})),
        )
        self._append(record)
        return str(record["hash"])

    def verify(self, decision_id: str, expected: Mapping[str, Any]) -> bool:
        """Replay and verify start/result integrity and complete binding."""
        if self._corrupt:
            return False
        try:
            records = self._read_raw_records()
        except (OSError, json.JSONDecodeError):
            return False
        start_seen = False
        start_record: dict[str, Any] | None = None
        result_record: dict[str, Any] | None = None
        result_seen_after_start = False
        for record in records:
            if record.get("decision_id") != decision_id:
                continue
            event = record.get("event")
            if event == "intent_judge_start":
                if start_seen:
                    return False  # duplicate start
                stored, recomputed = _record_hash(record)
                if stored != recomputed:
                    return False  # tampered start
                start_record = dict(record)
                start_seen = True
            elif event == "intent_judge_result":
                if result_record is not None:
                    return False  # duplicate result
                if not start_seen:
                    return False  # result before start
                result_record = dict(record)
                result_seen_after_start = True
        if not start_seen or not result_seen_after_start:
            return False
        assert start_record is not None
        if str(start_record.get("user_message_hash") or "") != str(
            expected.get("user_message_hash") or ""
        ):
            return False
        if str(start_record.get("user_id_hash") or "") != str(
            expected.get("user_id_hash") or ""
        ):
            return False
        if str(start_record.get("context_hash") or "") != str(
            expected.get("context_hash") or ""
        ):
            return False
        if str(start_record.get("context_source") or "") != str(
            expected.get("context_source") or ""
        ):
            return False
        if str(start_record.get("public_version") or "") != str(
            expected.get("public_version") or ""
        ):
            return False
        if str(start_record.get("internal_target_version") or "") != str(
            expected.get("internal_target_version") or ""
        ):
            return False
        assert result_record is not None
        stored_hash, recomputed = _record_hash(result_record)
        if stored_hash != recomputed or stored_hash != str(
            expected.get("result_hash") or ""
        ):
            return False
        expected_trace = _canonical_json(expected.get("trace") or {})
        return (
            str(result_record.get("decision") or "")
            == str(expected.get("decision") or "")
            and str(result_record.get("backend_used") or "")
            == str(expected.get("backend_used") or "")
            and str(result_record.get("reason") or "")
            == str(expected.get("reason") or "")
            and _numeric_text(result_record.get("confidence"))
            == _numeric_text(expected.get("confidence"))
            and _numeric_text(result_record.get("latency_ms"))
            == _numeric_text(expected.get("latency_ms"))
            and str(result_record.get("trace_json") or "") == expected_trace
        )

    def _load(self) -> tuple[set[str], bool]:
        """Read valid records; return started decision ids and corruption flag."""
        started: set[str] = set()
        seen_result_ids: set[str] = set()
        try:
            records = self._read_raw_records()
        except (OSError, json.JSONDecodeError):
            return set(), True
        for record in records:
            if not isinstance(record, dict):
                return set(), True
            decision_id = str(record.get("decision_id") or "")
            event = str(record.get("event") or "")
            if not decision_id or event not in {
                "intent_judge_start",
                "intent_judge_result",
            }:
                return set(), True
            stored, recomputed = _record_hash(record)
            if stored != recomputed:
                return set(), True
            if event == "intent_judge_start":
                if decision_id in started:
                    return set(), True
                started.add(decision_id)
            else:
                if decision_id not in started:
                    return set(), True
                if decision_id in seen_result_ids:
                    return set(), True
                seen_result_ids.add(decision_id)
        return started, False

    def _read_raw_records(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        records: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise json.JSONDecodeError("record is not an object", line, 0)
                records.append(value)
        return records

    def _record(self, **fields: Any) -> dict[str, Any]:
        record = {
            "event": fields["event"],
            "decision_id": fields["decision_id"],
            "public_version": self._public_version,
            "internal_target_version": self._internal_target_version,
            "wall_ts": time.time(),
        }
        for key, value in fields.items():
            if key not in {"event", "decision_id"}:
                record[key] = value
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        record["hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return record

    def _append(self, record: dict[str, Any]) -> None:
        if self._corrupt:
            raise IntentDecisionLedgerError("decision ledger is corrupted")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._started, self._corrupt = self._load()
        except OSError as exc:
            raise IntentDecisionLedgerError(
                f"unable to append intent decision: {exc}"
            ) from exc


def _numeric_text(value: Any) -> str:
    try:
        return f"{float(value):.12f}"
    except (TypeError, ValueError):
        return str(value or "")


__all__ = [
    "IntentDecisionLedger",
    "IntentDecisionLedgerError",
]