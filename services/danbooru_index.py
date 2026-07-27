"""Small, local Danbooru tag index with atomic snapshot updates.

The plugin deliberately does not bundle a tag database.  Administrators may import
their own JSON/CSV export and keep its source and licence alongside the snapshot.
Only exact canonical/alias matches are verified; prefix and fuzzy results are hints.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
import unicodedata
from urllib.parse import urlparse, urlunparse

import aiohttp


DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_INDEX_RECORDS = 500_000
MAX_TAG_LENGTH = 256
MAX_ALIASES_PER_TAG = 64
MAX_PROVENANCE_JSON_LENGTH = 8192
_SCHEMA_VERSION = "1"
_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_SPACE_OR_UNDERSCORE = re.compile(r"[\s_]+", re.UNICODE)
_ALIAS_SEPARATOR = re.compile(r"[|;,]")
_DANBOORU_CATEGORIES = {
    "0": "general",
    "1": "artist",
    "3": "copyright",
    "4": "character",
    "5": "meta",
}
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    """Resolve one already-validated host without a second DNS lookup."""

    def __init__(self, hostname: str, addresses: Sequence[IPAddress]):
        self._hostname = str(hostname or "").casefold()
        self._addresses = tuple(addresses)

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict[str, Any]]:
        if str(host or "").casefold() != self._hostname:
            raise OSError("unexpected host requested by pinned resolver")
        result: list[dict[str, Any]] = []
        for address in self._addresses:
            address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            if family not in {socket.AF_UNSPEC, address_family}:
                continue
            result.append(
                {
                    "hostname": host,
                    "host": str(address),
                    "port": port,
                    "family": address_family,
                    "proto": 0,
                    "flags": 0,
                }
            )
        if not result:
            raise OSError("validated host has no address for the requested family")
        return result

    async def close(self) -> None:
        return None


class DanbooruIndexError(Exception):
    """An import, network update, or database operation failed safely."""


@dataclass(frozen=True)
class TagCandidate:
    tag: str
    canonical_tag: str
    category: str
    aliases: tuple[str, ...]
    count: int
    provenance: dict[str, Any]
    match_type: str
    matched_value: str
    score: float
    verified: bool = False


@dataclass(frozen=True)
class TagLookup:
    query: str
    normalized_query: str
    tag: str = ""
    canonical_tag: str = ""
    category: str = ""
    aliases: tuple[str, ...] = ()
    count: int = 0
    provenance: dict[str, Any] | None = None
    match_type: str = "none"
    matched_value: str = ""
    verified: bool = False
    candidates: tuple[TagCandidate, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.tag)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["found"] = self.found
        return payload


@dataclass(frozen=True)
class _ImportRecord:
    tag: str
    normalized_tag: str
    category: str
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]
    count: int
    provenance: dict[str, Any]


def normalize_tag(value: str) -> str:
    """Return a stable lookup key for user-facing Danbooru prompt syntax.

    NFKC folds full-width forms, curly apostrophes become ASCII apostrophes,
    spaces and underscores are equivalent, and Comfy prompt escaping around
    parentheses does not affect identity.
    """

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = text.replace(r"\(", "(").replace(r"\)", ")")
    text = _SPACE_OR_UNDERSCORE.sub("_", text)
    return text.strip("_").casefold()


def escape_prompt_tag(value: str) -> str:
    """Format a normalized tag for prompt text without double escaping it."""

    return normalize_tag(value).replace("(", r"\(").replace(")", r"\)")


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False)).casefold()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _json_mapping(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, Mapping):
                    return {str(key): item for key, item in decoded.items()}
        return {"value": value}
    return {"value": value}


def _aliases(value: Any, *, skip_overlong: bool = False) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                values: Iterable[Any] = decoded
            else:
                values = _ALIAS_SEPARATOR.split(value)
        else:
            values = _ALIAS_SEPARATOR.split(value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        raise DanbooruIndexError("aliases must be a string or list")

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = normalize_tag(str(item))
        if len(normalized) > MAX_TAG_LENGTH:
            if skip_overlong:
                continue
            raise DanbooruIndexError("tag alias exceeds length limit")
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
            if len(result) > MAX_ALIASES_PER_TAG:
                raise DanbooruIndexError("tag record has too many aliases")
    return tuple(result)


def _count(value: Any) -> int:
    if value in (None, ""):
        return 0
    raw = str(value).replace(",", "").strip()
    if len(raw) > 32:
        raise DanbooruIndexError("invalid tag count")
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise DanbooruIndexError("invalid tag count") from exc
    if number < 0:
        raise DanbooruIndexError("tag count cannot be negative")
    return number


def _category(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        raise DanbooruIndexError("category must be a scalar value")
    normalized = str(value).strip().casefold()
    return _DANBOORU_CATEGORIES.get(normalized, normalized)


def _record_from_mapping(
    raw: Mapping[str, Any],
    default_provenance: Mapping[str, Any],
    *,
    skip_overlong_aliases: bool = False,
) -> _ImportRecord:
    tag_value = raw.get("tag", raw.get("name", raw.get("canonical_tag", "")))
    normalized_tag = normalize_tag(str(tag_value))
    if not normalized_tag:
        raise DanbooruIndexError("tag record is missing tag/name")
    if len(normalized_tag) > MAX_TAG_LENGTH:
        raise DanbooruIndexError("tag name exceeds length limit")
    aliases = _aliases(
        raw.get("aliases", raw.get("alias", ())),
        skip_overlong=skip_overlong_aliases,
    )
    aliases = tuple(alias for alias in aliases if alias != normalized_tag)
    provenance = _json_mapping(raw.get("provenance"))
    # Dataset-level reviewed provenance is authoritative. Individual records
    # may add evidence fields but cannot spoof source/licence/transport.
    provenance.update(default_provenance)
    if len(json.dumps(provenance, ensure_ascii=False)) > MAX_PROVENANCE_JSON_LENGTH:
        raise DanbooruIndexError("tag provenance exceeds length limit")
    category = _category(raw.get("category", raw.get("type", "")))
    if len(category) > 64:
        raise DanbooruIndexError("tag category exceeds length limit")
    return _ImportRecord(
        tag=normalized_tag,
        normalized_tag=normalized_tag,
        category=category,
        aliases=aliases,
        normalized_aliases=aliases,
        count=_count(raw.get("count", raw.get("post_count", 0))),
        provenance=provenance,
    )


def _records_from_json(
    data: bytes,
    provenance: Mapping[str, Any],
) -> tuple[list[_ImportRecord], dict[str, Any]]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DanbooruIndexError("invalid tag index JSON") from exc

    metadata: dict[str, Any] = {}
    raw_records: Any = payload
    if isinstance(payload, Mapping):
        for key in ("source", "license", "revision"):
            if key in payload and not isinstance(payload[key], (dict, list)):
                metadata[key] = str(payload[key])
        metadata.update(_json_mapping(payload.get("provenance")))
        for key in ("tags", "records", "data"):
            if key in payload:
                raw_records = payload[key]
                break
        else:
            # Also accept compact {"tag_name": {record fields}} exports.
            raw_records = []
            ignored = {"source", "license", "revision", "provenance"}
            for tag, value in payload.items():
                if tag in ignored:
                    continue
                if isinstance(value, Mapping):
                    item = dict(value)
                    item.setdefault("tag", tag)
                else:
                    item = {"tag": tag, "count": value}
                raw_records.append(item)
    if not isinstance(raw_records, list):
        raise DanbooruIndexError("tag index JSON must contain a record list")
    if len(raw_records) > MAX_INDEX_RECORDS:
        raise DanbooruIndexError("tag index contains too many records")
    defaults = dict(metadata)
    # Explicit caller provenance (for example the configured source URL and
    # reviewed licence) takes precedence over embedded advisory metadata.
    defaults.update(provenance)
    records = []
    for index, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, Mapping):
            raise DanbooruIndexError(f"JSON record {index} is not an object")
        try:
            records.append(_record_from_mapping(raw, defaults))
        except DanbooruIndexError as exc:
            raise DanbooruIndexError(f"invalid JSON record {index}: {exc}") from exc
    return records, metadata


def _records_from_csv(
    data: bytes,
    provenance: Mapping[str, Any],
) -> tuple[list[_ImportRecord], dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DanbooruIndexError("tag index CSV must be UTF-8") from exc
    # Prefer the documented headered format, but also accept the common
    # Danbooru export shape used by Anima tag indexes:
    # ``tag,category,count,aliases`` without a header row.  The latter is
    # intentionally detected conservatively so an arbitrary malformed CSV is
    # still rejected instead of being silently interpreted as tags.
    stream = io.StringIO(text, newline="")
    probe = csv.reader(stream)
    try:
        first_row = next(probe)
    except StopIteration as exc:
        raise DanbooruIndexError("tag index CSV is missing a header") from exc
    lowered = {str(name).strip().casefold() for name in first_row}
    has_header = any(name in lowered for name in ("tag", "name", "canonical_tag"))
    records: list[_ImportRecord] = []

    if has_header:
        stream.seek(0)
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise DanbooruIndexError("tag index CSV is missing a header")
        for row_number, raw in enumerate(reader, start=2):
            if len(records) >= MAX_INDEX_RECORDS:
                raise DanbooruIndexError("tag index contains too many records")
            normalized_row = {
                str(key).strip().casefold(): value for key, value in raw.items() if key
            }
            if not any(str(value or "").strip() for value in normalized_row.values()):
                continue
            try:
                records.append(_record_from_mapping(normalized_row, provenance))
            except DanbooruIndexError as exc:
                raise DanbooruIndexError(
                    f"invalid CSV record on line {row_number}: {exc}"
                ) from exc
        return records, {}

    # Headerless Anima/Danbooru exports have at least tag, category and count.
    # Validate those two numeric/semantic columns before accepting the format.
    if len(first_row) < 3:
        raise DanbooruIndexError("tag index CSV requires tag or name column")
    try:
        _category(first_row[1])
        _count(first_row[2])
    except DanbooruIndexError as exc:
        raise DanbooruIndexError("tag index CSV requires tag or name column") from exc

    def rows() -> Iterable[tuple[int, list[str]]]:
        yield 1, first_row
        for row_number, raw in enumerate(probe, start=2):
            yield row_number, raw

    for row_number, raw in rows():
        if len(records) >= MAX_INDEX_RECORDS:
            raise DanbooruIndexError("tag index contains too many records")
        if not any(str(value or "").strip() for value in raw):
            continue
        normalized_row = {
            "tag": raw[0] if len(raw) > 0 else "",
            "category": raw[1] if len(raw) > 1 else "",
            "count": raw[2] if len(raw) > 2 else "",
            "aliases": raw[3] if len(raw) > 3 else "",
        }
        try:
            records.append(
                _record_from_mapping(
                    normalized_row,
                    provenance,
                    skip_overlong_aliases=True,
                )
            )
        except DanbooruIndexError as exc:
            raise DanbooruIndexError(
                f"invalid CSV record on line {row_number}: {exc}"
            ) from exc

    # Some headerless Danbooru exports intentionally include broad aliases
    # which either name another canonical tag or point to several canonical
    # tags.  Such aliases cannot be verified uniquely.  Drop only those
    # ambiguous aliases while retaining every canonical tag and every unique,
    # bounded alias; JSON and headered CSV imports keep their strict conflict
    # behavior unchanged.
    canonical_tags = {record.normalized_tag for record in records}
    owners: dict[str, set[str]] = {}
    for record in records:
        for alias in record.normalized_aliases:
            owners.setdefault(alias, set()).add(record.normalized_tag)
    ambiguous = {
        alias
        for alias, tag_owners in owners.items()
        if alias in canonical_tags or len(tag_owners) > 1
    }
    if ambiguous:
        records = [
            _ImportRecord(
                tag=record.tag,
                normalized_tag=record.normalized_tag,
                category=record.category,
                aliases=tuple(
                    alias
                    for alias in record.aliases
                    if alias not in ambiguous
                ),
                normalized_aliases=tuple(
                    alias
                    for alias in record.normalized_aliases
                    if alias not in ambiguous
                ),
                count=record.count,
                provenance=record.provenance,
            )
            for record in records
        ]
    return records, {}


class DanbooruTagIndex:
    """SQLite-backed tag catalogue using replace-only immutable snapshots."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = _path_lock(self.path)
        self._last_error = ""
        self._generation_lock = threading.Lock()
        self._update_generation = 0

    def _begin_update(self) -> int:
        with self._generation_lock:
            self._update_generation += 1
            return self._update_generation

    def _invalidate_update(self, generation: int) -> None:
        with self._generation_lock:
            if self._update_generation == generation:
                self._update_generation += 1

    def _generation_is_current(self, generation: int | None) -> bool:
        if generation is None:
            return True
        with self._generation_lock:
            return self._update_generation == generation

    def import_file(
        self,
        path: Path,
        *,
        source: str = "",
        content_type: str = "",
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path)
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            self._last_error = str(exc)
            raise DanbooruIndexError(f"cannot read tag index: {file_path}") from exc
        return self.import_bytes(
            data,
            source=source or str(file_path),
            content_type=content_type or file_path.suffix,
            provenance=provenance,
        )

    def import_bytes(
        self,
        data: bytes,
        source: str = "",
        content_type: str = "",
        provenance: Mapping[str, Any] | None = None,
        _expected_generation: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        payload = bytes(data)
        if not payload:
            raise DanbooruIndexError("tag index is empty")
        base_provenance = _json_mapping(provenance)
        if source:
            base_provenance["source"] = source
        kind = self._content_kind(content_type, payload)
        try:
            if kind == "json":
                records, embedded_metadata = _records_from_json(
                    payload, base_provenance
                )
            else:
                records, embedded_metadata = _records_from_csv(payload, base_provenance)
            if not records:
                raise DanbooruIndexError("tag index contains no records")
            metadata = dict(base_provenance)
            for key, value in embedded_metadata.items():
                metadata.setdefault(key, value)
            if source:
                metadata["source"] = source
            digest = hashlib.sha256(payload).hexdigest()
            metadata.setdefault("revision", digest[:12])
            metadata["sha256"] = digest
            metadata["imported_at"] = datetime.now(timezone.utc).isoformat()
            self._replace_snapshot(
                records,
                metadata,
                expected_generation=_expected_generation,
            )
        except Exception as exc:
            if self._generation_is_current(_expected_generation):
                self._last_error = str(exc)
            if isinstance(exc, DanbooruIndexError):
                raise
            raise DanbooruIndexError(f"tag index import failed: {exc}") from exc
        if self._generation_is_current(_expected_generation):
            self._last_error = ""
        return self.status()

    @staticmethod
    def _content_kind(content_type: str, data: bytes) -> str:
        hint = str(content_type or "").split(";", 1)[0].strip().casefold()
        if "json" in hint or hint.endswith(".json"):
            return "json"
        if "csv" in hint or hint.endswith(".csv"):
            return "csv"
        prefix = data.lstrip()[:1]
        if prefix in {b"[", b"{"}:
            return "json"
        return "csv"

    def _replace_snapshot(
        self,
        records: Sequence[_ImportRecord],
        metadata: Mapping[str, Any],
        *,
        expected_generation: int | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            # Build and fsync outside the reader lock. Existing lookups continue
            # using the immutable old snapshot until the short replace window.
            self._build_database(temporary, records, metadata)
            # Windows rejects fsync on a read-only CRT descriptor.
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            with self._lock:
                if expected_generation is None:
                    os.replace(temporary, self.path)
                else:
                    with self._generation_lock:
                        if self._update_generation != expected_generation:
                            raise DanbooruIndexError(
                                "stale tag index update was discarded"
                            )
                        os.replace(temporary, self.path)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _build_database(
        path: Path,
        records: Sequence[_ImportRecord],
        metadata: Mapping[str, Any],
    ) -> None:
        connection = sqlite3.connect(path, timeout=30)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY,
                    tag TEXT NOT NULL,
                    normalized_tag TEXT NOT NULL UNIQUE,
                    tag_length INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
                    provenance TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE aliases (
                    id INTEGER PRIMARY KEY,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL UNIQUE,
                    alias_length INTEGER NOT NULL
                );
                CREATE INDEX idx_tags_category ON tags(category);
                CREATE INDEX idx_tags_prefix ON tags(normalized_tag);
                CREATE INDEX idx_tags_length ON tags(tag_length);
                CREATE INDEX idx_alias_prefix ON aliases(normalized_alias);
                CREATE INDEX idx_alias_length ON aliases(alias_length);
                """
            )
            canonical_keys = {record.normalized_tag for record in records}
            if len(canonical_keys) != len(records):
                raise DanbooruIndexError("duplicate canonical tag in import")
            alias_owner: dict[str, str] = {}
            for record in records:
                for alias in record.normalized_aliases:
                    if alias in canonical_keys and alias != record.normalized_tag:
                        raise DanbooruIndexError(
                            f"alias conflicts with canonical tag: {alias}"
                        )
                    owner = alias_owner.setdefault(alias, record.normalized_tag)
                    if owner != record.normalized_tag:
                        raise DanbooruIndexError(f"duplicate alias in import: {alias}")

            for record in records:
                cursor = connection.execute(
                    """INSERT INTO tags
                       (tag, normalized_tag, tag_length, category, count, provenance)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        record.tag,
                        record.normalized_tag,
                        len(record.normalized_tag),
                        record.category,
                        record.count,
                        json.dumps(
                            record.provenance,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
                tag_id = int(cursor.lastrowid)
                connection.executemany(
                    """INSERT INTO aliases
                       (tag_id, alias, normalized_alias, alias_length)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (tag_id, alias, alias, len(normalized))
                        for alias, normalized in zip(
                            record.aliases, record.normalized_aliases
                        )
                    ],
                )
            complete_metadata = {
                "schema_version": _SCHEMA_VERSION,
                **{str(key): str(value) for key, value in metadata.items()},
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                complete_metadata.items(),
            )
            check = connection.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0] != "ok":
                raise DanbooruIndexError("SQLite integrity check failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def lookup(self, value: str, category: str = "") -> TagLookup:
        query = str(value or "").strip()
        normalized = normalize_tag(query)
        if not normalized:
            return TagLookup(query=query, normalized_query=normalized, provenance={})
        category_filter = _category(category)
        with self._lock:
            if not self.path.is_file():
                return TagLookup(
                    query=query, normalized_query=normalized, provenance={}
                )
            try:
                connection = self._connect()
                try:
                    exact = self._exact(connection, normalized, category_filter)
                    if exact is not None:
                        return self._lookup_from_row(
                            connection, query, normalized, exact, verified=True
                        )
                    candidates = self._candidates(
                        connection, normalized, category_filter, limit=8
                    )
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                self._last_error = str(exc)
                return TagLookup(
                    query=query, normalized_query=normalized, provenance={}
                )
        if not candidates:
            return TagLookup(query=query, normalized_query=normalized, provenance={})
        first = candidates[0]
        return TagLookup(
            query=query,
            normalized_query=normalized,
            tag=first.tag,
            canonical_tag=first.canonical_tag,
            category=first.category,
            aliases=first.aliases,
            count=first.count,
            provenance=first.provenance,
            match_type=first.match_type,
            matched_value=first.matched_value,
            verified=False,
            candidates=tuple(candidates),
        )

    def lookup_many(
        self,
        values: Sequence[str],
        category: str = "",
    ) -> tuple[TagLookup, ...]:
        """Resolve several exact canonical/alias queries in one immutable snapshot.

        Batch lookup deliberately performs no prefix or fuzzy fallback.  This keeps
        one tool call suitable for validating multiple candidate tags without
        allowing a suggestion to masquerade as a verified canonical match.
        """

        queries = tuple(str(value or "").strip() for value in values)
        category_filter = _category(category)
        if not queries:
            return ()
        results: list[TagLookup] = []
        with self._lock:
            if not self.path.is_file():
                return tuple(
                    TagLookup(
                        query=query,
                        normalized_query=normalize_tag(query),
                        provenance={},
                    )
                    for query in queries
                )
            try:
                connection = self._connect()
                try:
                    for query in queries:
                        normalized = normalize_tag(query)
                        if not normalized:
                            results.append(
                                TagLookup(
                                    query=query,
                                    normalized_query=normalized,
                                    provenance={},
                                )
                            )
                            continue
                        row = self._exact(connection, normalized, category_filter)
                        if row is None:
                            results.append(
                                TagLookup(
                                    query=query,
                                    normalized_query=normalized,
                                    provenance={},
                                )
                            )
                            continue
                        results.append(
                            self._lookup_from_row(
                                connection,
                                query,
                                normalized,
                                row,
                                verified=True,
                            )
                        )
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                self._last_error = str(exc)
                return tuple(
                    TagLookup(
                        query=query,
                        normalized_query=normalize_tag(query),
                        provenance={},
                    )
                    for query in queries
                )
        return tuple(results)

    def search(
        self,
        value: str,
        *,
        mode: str = "exact",
        category: str = "",
        limit: int = 8,
    ) -> tuple[TagCandidate, ...]:
        """Return bounded exact, prefix or keyword candidates from one snapshot.

        Exact canonical and unique-alias matches are verified.  Prefix and keyword
        results are discovery hints only and must be confirmed with a later exact
        lookup before they are treated as user identity evidence.
        """

        query = str(value or "").strip()
        normalized = normalize_tag(query)
        if not normalized:
            return ()
        normalized_mode = str(mode or "exact").strip().casefold()
        if normalized_mode == "alias":
            normalized_mode = "exact"
        if normalized_mode in {"contains", "search"}:
            normalized_mode = "keyword"
        if normalized_mode not in {"exact", "prefix", "keyword"}:
            raise ValueError("mode must be exact, prefix or keyword")
        effective_limit = max(1, min(int(limit), 50))
        category_filter = _category(category)
        with self._lock:
            if not self.path.is_file():
                return ()
            try:
                connection = self._connect()
                try:
                    if normalized_mode == "exact":
                        row = self._exact(connection, normalized, category_filter)
                        if row is None:
                            return ()
                        return (
                            self._candidate_from_row(
                                connection,
                                row,
                                verified=True,
                            ),
                        )
                    if normalized_mode == "prefix":
                        return tuple(
                            self._prefix_candidates(
                                connection,
                                normalized,
                                category_filter,
                                limit=effective_limit,
                            )
                        )
                    return tuple(
                        self._keyword_candidates(
                            connection,
                            normalized,
                            category_filter,
                            limit=effective_limit,
                        )
                    )
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                self._last_error = str(exc)
                return ()

    @staticmethod
    def _connect_path(path: Path) -> sqlite3.Connection:
        uri = path.resolve(strict=False).as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _connect(self) -> sqlite3.Connection:
        return self._connect_path(self.path)

    @staticmethod
    def _category_sql(category: str, prefix: str = "t") -> tuple[str, list[Any]]:
        if not category:
            return "", []
        return f" AND {prefix}.category = ? COLLATE NOCASE", [category]

    def _exact(
        self, connection: sqlite3.Connection, normalized: str, category: str
    ) -> sqlite3.Row | None:
        category_sql, params = self._category_sql(category)
        row = connection.execute(
            """SELECT t.*, 'canonical' AS match_type,
                      t.tag AS matched_value, 1.0 AS score
               FROM tags t WHERE t.normalized_tag = ?"""
            + category_sql,
            [normalized, *params],
        ).fetchone()
        if row is not None:
            return row
        return connection.execute(
            """SELECT t.*, 'alias' AS match_type,
                      a.alias AS matched_value, 1.0 AS score
               FROM aliases a JOIN tags t ON t.id = a.tag_id
               WHERE a.normalized_alias = ?"""
            + category_sql,
            [normalized, *params],
        ).fetchone()

    def _lookup_from_row(
        self,
        connection: sqlite3.Connection,
        query: str,
        normalized: str,
        row: sqlite3.Row,
        *,
        verified: bool,
    ) -> TagLookup:
        candidate = self._candidate_from_row(connection, row, verified=verified)
        return TagLookup(
            query=query,
            normalized_query=normalized,
            tag=candidate.tag,
            canonical_tag=candidate.canonical_tag,
            category=candidate.category,
            aliases=candidate.aliases,
            count=candidate.count,
            provenance=candidate.provenance,
            match_type=candidate.match_type,
            matched_value=candidate.matched_value,
            verified=verified,
            candidates=(),
        )

    def _candidate_from_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        verified: bool = False,
    ) -> TagCandidate:
        aliases = tuple(
            item[0]
            for item in connection.execute(
                "SELECT alias FROM aliases WHERE tag_id = ? ORDER BY alias",
                (row["id"],),
            ).fetchall()
        )
        try:
            provenance = json.loads(row["provenance"] or "{}")
        except (TypeError, json.JSONDecodeError):
            provenance = {}
        return TagCandidate(
            tag=row["tag"],
            canonical_tag=row["tag"],
            category=row["category"],
            aliases=aliases,
            count=int(row["count"]),
            provenance=provenance if isinstance(provenance, dict) else {},
            match_type=row["match_type"],
            matched_value=row["matched_value"],
            score=float(row["score"]),
            verified=verified,
        )

    def _candidates(
        self,
        connection: sqlite3.Connection,
        normalized: str,
        category: str,
        *,
        limit: int,
    ) -> list[TagCandidate]:
        category_sql, category_params = self._category_sql(category)
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        )
        rows = connection.execute(
            """SELECT t.*, 'prefix' AS match_type,
                      t.tag AS matched_value, 0.9 AS score
               FROM tags t
               WHERE t.normalized_tag LIKE ? ESCAPE '\\'"""
            + category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [escaped + "%", *category_params, limit],
        ).fetchall()
        alias_category_sql, alias_params = self._category_sql(category)
        alias_rows = connection.execute(
            """SELECT t.*, 'prefix' AS match_type,
                      a.alias AS matched_value, 0.86 AS score
               FROM aliases a JOIN tags t ON t.id = a.tag_id
               WHERE a.normalized_alias LIKE ? ESCAPE '\\'"""
            + alias_category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [escaped + "%", *alias_params, limit],
        ).fetchall()
        combined: dict[int, sqlite3.Row] = {}
        for row in [*rows, *alias_rows]:
            combined.setdefault(int(row["id"]), row)

        if len(combined) < limit and len(normalized) >= 3:
            low = max(1, len(normalized) - 3)
            high = len(normalized) + 3
            fuzzy_category_sql, fuzzy_params = self._category_sql(category)
            fuzzy_rows = connection.execute(
                """SELECT t.*, 'fuzzy' AS match_type,
                          t.tag AS matched_value, 0.0 AS score
                   FROM tags t WHERE t.tag_length BETWEEN ? AND ?"""
                + fuzzy_category_sql
                + " ORDER BY t.count DESC LIMIT 2000",
                [low, high, *fuzzy_params],
            ).fetchall()
            scored: list[tuple[float, sqlite3.Row]] = []
            for row in fuzzy_rows:
                if int(row["id"]) in combined:
                    continue
                score = difflib.SequenceMatcher(
                    None, normalized, row["normalized_tag"], autojunk=False
                ).ratio()
                if score >= 0.72:
                    scored.append((score, row))
            for score, row in sorted(
                scored,
                key=lambda item: (-item[0], -int(item[1]["count"]), item[1]["tag"]),
            )[: limit - len(combined)]:
                # sqlite.Row cannot be constructed directly; reuse a tiny SELECT.
                selected = connection.execute(
                    """SELECT t.*, 'fuzzy' AS match_type,
                              t.tag AS matched_value, ? AS score
                       FROM tags t WHERE t.id = ?""",
                    (score, row["id"]),
                ).fetchone()
                combined[int(row["id"])] = selected

        candidates = [
            self._candidate_from_row(connection, row) for row in combined.values()
        ]
        candidates.sort(key=lambda item: (-item.score, -item.count, item.tag))
        return candidates[:limit]

    def _prefix_candidates(
        self,
        connection: sqlite3.Connection,
        normalized: str,
        category: str,
        *,
        limit: int,
    ) -> list[TagCandidate]:
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        )
        category_sql, category_params = self._category_sql(category)
        rows = connection.execute(
            """SELECT t.*, 'prefix' AS match_type,
                      t.tag AS matched_value, 0.9 AS score
               FROM tags t
               WHERE t.normalized_tag LIKE ? ESCAPE '\\'"""
            + category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [escaped + "%", *category_params, limit],
        ).fetchall()
        alias_category_sql, alias_params = self._category_sql(category)
        alias_rows = connection.execute(
            """SELECT t.*, 'alias_prefix' AS match_type,
                      a.alias AS matched_value, 0.86 AS score
               FROM aliases a JOIN tags t ON t.id = a.tag_id
               WHERE a.normalized_alias LIKE ? ESCAPE '\\'"""
            + alias_category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [escaped + "%", *alias_params, limit],
        ).fetchall()
        combined: dict[int, sqlite3.Row] = {}
        for row in [*rows, *alias_rows]:
            combined.setdefault(int(row["id"]), row)
        candidates = [
            self._candidate_from_row(connection, row) for row in combined.values()
        ]
        candidates.sort(key=lambda item: (-item.score, -item.count, item.tag))
        return candidates[:limit]

    def _keyword_candidates(
        self,
        connection: sqlite3.Connection,
        normalized: str,
        category: str,
        *,
        limit: int,
    ) -> list[TagCandidate]:
        category_sql, category_params = self._category_sql(category)
        rows = connection.execute(
            """SELECT t.*, 'keyword' AS match_type,
                      t.tag AS matched_value, 0.75 AS score
               FROM tags t
               WHERE instr(t.normalized_tag, ?) > 0"""
            + category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [normalized, *category_params, limit],
        ).fetchall()
        alias_category_sql, alias_params = self._category_sql(category)
        alias_rows = connection.execute(
            """SELECT t.*, 'alias_keyword' AS match_type,
                      a.alias AS matched_value, 0.7 AS score
               FROM aliases a JOIN tags t ON t.id = a.tag_id
               WHERE instr(a.normalized_alias, ?) > 0"""
            + alias_category_sql
            + " ORDER BY t.count DESC, t.tag LIMIT ?",
            [normalized, *alias_params, limit],
        ).fetchall()
        combined: dict[int, sqlite3.Row] = {}
        for row in [*rows, *alias_rows]:
            combined.setdefault(int(row["id"]), row)
        candidates = [
            self._candidate_from_row(connection, row) for row in combined.values()
        ]
        candidates.sort(key=lambda item: (-item.score, -item.count, item.tag))
        return candidates[:limit]

    def status(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "ready": False,
            "tag_count": 0,
            "alias_count": 0,
            "revision": "",
            "source": "",
            "license": "",
            "sha256": "",
            "error": self._last_error,
            "category_counts": {},
            "provenance_counts": {},
        }
        with self._lock:
            if not self.path.is_file():
                return base
            try:
                connection = self._connect()
                try:
                    metadata = {
                        row["key"]: row["value"]
                        for row in connection.execute(
                            "SELECT key, value FROM metadata"
                        ).fetchall()
                    }
                    if metadata.get("schema_version") != _SCHEMA_VERSION:
                        raise DanbooruIndexError("unsupported tag index schema")
                    base["tag_count"] = int(
                        connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
                    )
                    base["alias_count"] = int(
                        connection.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
                    )
                    base["category_counts"] = {
                        str(row[0]): int(row[1])
                        for row in connection.execute(
                            "SELECT category, COUNT(*) FROM tags GROUP BY category"
                        ).fetchall()
                    }
                    provenance_counts: dict[str, int] = {}
                    for raw, amount in connection.execute(
                        "SELECT provenance, COUNT(*) FROM tags GROUP BY provenance"
                    ).fetchall():
                        try:
                            decoded = json.loads(raw or "{}")
                        except (TypeError, json.JSONDecodeError):
                            decoded = {}
                        if isinstance(decoded, dict):
                            label = str(
                                decoded.get("source")
                                or decoded.get("value")
                                or "unspecified"
                            )
                        else:
                            label = "unspecified"
                        provenance_counts[label] = provenance_counts.get(
                            label, 0
                        ) + int(amount)
                    base["provenance_counts"] = provenance_counts
                    for key in (
                        "revision",
                        "source",
                        "license",
                        "sha256",
                        "imported_at",
                    ):
                        base[key] = metadata.get(key, "")
                    base["ready"] = True
                finally:
                    connection.close()
            except (sqlite3.Error, DanbooruIndexError) as exc:
                base["error"] = str(exc)
        return base

    async def update_from_url(
        self,
        url: str,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> dict[str, Any]:
        if timeout <= 0:
            raise DanbooruIndexError("timeout must be positive")
        if max_bytes <= 0:
            raise DanbooruIndexError("max_bytes must be positive")
        parsed = urlparse(str(url or "").strip())
        generation = self._begin_update()
        try:
            addresses = await self._validate_update_url(parsed)
            client_timeout = aiohttp.ClientTimeout(total=float(timeout))
            connector = aiohttp.TCPConnector(
                resolver=_PinnedResolver(parsed.hostname, addresses),
                use_dns_cache=True,
            )
            async with aiohttp.ClientSession(
                timeout=client_timeout,
                connector=connector,
            ) as session:
                async with session.get(
                    parsed.geturl(), allow_redirects=False
                ) as response:
                    if 300 <= response.status < 400:
                        raise DanbooruIndexError(
                            "tag index URL redirects are not allowed"
                        )
                    if response.status >= 400:
                        raise DanbooruIndexError(
                            f"tag index URL returned HTTP {response.status}"
                        )
                    content_length = response.headers.get("Content-Length", "")
                    if content_length:
                        try:
                            declared = int(content_length)
                        except ValueError:
                            declared = 0
                        if declared > max_bytes:
                            raise DanbooruIndexError(
                                "tag index download exceeds size limit"
                            )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise DanbooruIndexError(
                                "tag index download exceeds size limit"
                            )
                        chunks.append(chunk)
                    content_type = response.headers.get("Content-Type", "")
        except DanbooruIndexError as exc:
            self._invalidate_update(generation)
            self._last_error = str(exc)
            raise
        except asyncio.CancelledError:
            self._invalidate_update(generation)
            raise
        except asyncio.TimeoutError as exc:
            self._invalidate_update(generation)
            self._last_error = "tag index download timed out"
            raise DanbooruIndexError(self._last_error) from exc
        except aiohttp.ClientError as exc:
            self._invalidate_update(generation)
            self._last_error = f"tag index request failed: {type(exc).__name__}"
            raise DanbooruIndexError(self._last_error) from exc
        source_label = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
        )
        try:
            # Parsing and SQLite construction can be significant for a 64 MiB
            # catalogue, so keep the AstrBot event loop responsive.
            build_timeout = max(30.0, min(300.0, float(timeout) * 2.0))
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.import_bytes,
                    b"".join(chunks),
                    source=source_label,
                    content_type=content_type,
                    provenance={"transport": parsed.scheme},
                    _expected_generation=generation,
                ),
                timeout=build_timeout,
            )
        except asyncio.CancelledError:
            self._invalidate_update(generation)
            raise
        except asyncio.TimeoutError as exc:
            self._invalidate_update(generation)
            self._last_error = "tag index build timed out"
            raise DanbooruIndexError(self._last_error) from exc
        except DanbooruIndexError:
            # import_bytes records the error and atomic replacement keeps old data.
            raise

    @staticmethod
    async def _validate_update_url(
        parsed: Any,
    ) -> tuple[IPAddress, ...]:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DanbooruIndexError("tag index URL must use HTTP or HTTPS")
        if parsed.username or parsed.password:
            raise DanbooruIndexError("tag index URL cannot contain credentials")
        if parsed.fragment:
            raise DanbooruIndexError("tag index URL cannot contain a fragment")
        if len(parsed.geturl()) > 2048:
            raise DanbooruIndexError("tag index URL exceeds length limit")
        host = parsed.hostname
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                loop = asyncio.get_running_loop()
                resolved = await loop.getaddrinfo(
                    host,
                    parsed.port or 80,
                    type=socket.SOCK_STREAM,
                )
                addresses = list(
                    {
                        ipaddress.ip_address(item[4][0].split("%", 1)[0])
                        for item in resolved
                    }
                )
            except (OSError, ValueError) as exc:
                raise DanbooruIndexError("cannot resolve tag index host") from exc
        if not addresses:
            raise DanbooruIndexError("tag index host has no usable address")
        if any(
            address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or address.is_reserved
            for address in addresses
        ):
            raise DanbooruIndexError("tag index host resolves to a forbidden address")
        if parsed.scheme == "http" and any(
            not (address.is_private or address.is_loopback) for address in addresses
        ):
            raise DanbooruIndexError("plain HTTP is allowed only for private hosts")
        return tuple(addresses)


__all__ = [
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "MAX_ALIASES_PER_TAG",
    "MAX_INDEX_RECORDS",
    "MAX_PROVENANCE_JSON_LENGTH",
    "MAX_TAG_LENGTH",
    "DanbooruIndexError",
    "DanbooruTagIndex",
    "TagCandidate",
    "TagLookup",
    "escape_prompt_tag",
    "normalize_tag",
]
