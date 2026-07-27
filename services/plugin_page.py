"""AstrBot native plugin-page bridge for the management dashboard."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from ..constants import PLUGIN_NAME
from .task_store import TASK_STATUSES


logger = logging.getLogger("astrbot")


V170_API_MAX_BODY_BYTES = 1024 * 1024
V170_API_MAX_PAGE = 1_000_000
V170_API_MAX_PAGE_SIZE = 200
V170_API_MAX_CANDIDATES = 6
V170_API_MAX_WARMUP = 200
V170_API_MAX_PREVIEW_BYTES = 1024 * 1024
V170_API_MAX_PREVIEW_DATA_URL = 1_400_000
_ASSET_ID_RE = re.compile(r"^pa_[0-9a-f]{32}$")
_CONTENT_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSET_REVISION_RE = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")
_LAB_BATCH_RE = re.compile(r"^plb-[0-9a-f]{20}$")
_LAB_CANDIDATE_RE = re.compile(r"^plc-[0-9a-f]{20}$")
_PROMPT_PLAN_ID_RE = re.compile(r"^P-[0-9A-F]{6}$")
_DATA_URL_RE = re.compile(
    r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]*={0,2})$"
)
_ASSET_TYPES = frozenset(
    {"artist", "background", "character", "clothing", "pose"}
)
_ASSET_SORTS = frozenset({"relevance", "name", "updated", "created"})
_IMPORT_FORMATS = frozenset(
    {"", ".csv", ".json", "application/json", "csv", "json", "text/csv"}
)
_IMPORT_MODES = frozenset({"merge", "replace", "replace_source"})


class V170ApiValidationError(ValueError):
    """A bounded v1.7 management API payload is invalid."""


class V170ApiPayloadTooLargeError(V170ApiValidationError):
    """A v1.7 request exceeded its transport-independent size cap."""


def decode_plugin_gateway_body(
    raw_body: bytes,
    content_length: Any = None,
) -> dict[str, Any]:
    """Decode the authenticated bridge envelope with a hard 1 MiB cap."""

    if content_length not in (None, ""):
        try:
            declared = int(str(content_length))
        except (TypeError, ValueError) as exc:
            raise V170ApiValidationError("invalid Content-Length") from exc
        if declared < 0 or declared > V170_API_MAX_BODY_BYTES:
            raise V170ApiPayloadTooLargeError(
                "request body exceeds the 1 MiB limit"
            )
    if not isinstance(raw_body, bytes):
        raise V170ApiValidationError("request body must be bytes")
    if not raw_body or len(raw_body) > V170_API_MAX_BODY_BYTES:
        raise V170ApiPayloadTooLargeError("request body exceeds the 1 MiB limit")

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        payload = json.loads(
            raw_body.decode("utf-8"),
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise V170ApiValidationError("request body must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise V170ApiValidationError("JSON top level must be an object")
    return payload


def _json_body_size(payload: Mapping[str, Any]) -> int:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise V170ApiValidationError("request body must contain valid JSON values") from exc
    if len(encoded) > V170_API_MAX_BODY_BYTES:
        raise V170ApiPayloadTooLargeError("request body exceeds the 1 MiB limit")
    return len(encoded)


def _bounded_text(
    value: Any,
    field: str,
    maximum: int,
    *,
    required: bool = False,
) -> str:
    if not isinstance(value, str):
        raise V170ApiValidationError(f"{field} must be a string")
    text = value.strip()
    if required and not text:
        raise V170ApiValidationError(f"{field} must not be empty")
    if len(text) > maximum:
        raise V170ApiValidationError(f"{field} exceeds {maximum} characters")
    return text


def _bounded_int(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V170ApiValidationError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise V170ApiValidationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _bounded_number(
    value: Any,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V170ApiValidationError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise V170ApiValidationError(
            f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return number


def _bounded_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise V170ApiValidationError(f"{field} must be a boolean")
    return value


def _bounded_text_list(
    value: Any,
    field: str,
    *,
    maximum_items: int,
    maximum_item_length: int,
    allow_string: bool = False,
) -> list[str] | str:
    if allow_string and isinstance(value, str):
        return _bounded_text(value, field, maximum_item_length)
    if not isinstance(value, list):
        raise V170ApiValidationError(f"{field} must be a list")
    if len(value) > maximum_items:
        raise V170ApiValidationError(f"{field} exceeds {maximum_items} items")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(
            _bounded_text(
                item,
                f"{field}[{index}]",
                maximum_item_length,
                required=True,
            )
        )
    return result


def _validate_json_tree(
    value: Any,
    field: str,
    *,
    depth: int = 0,
    maximum_depth: int = 8,
) -> None:
    if depth > maximum_depth:
        raise V170ApiValidationError(f"{field} is nested too deeply")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise V170ApiValidationError(f"{field} contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > 16_384:
            raise V170ApiValidationError(f"{field} contains an oversized string")
        return
    if isinstance(value, list):
        if len(value) > 1024:
            raise V170ApiValidationError(f"{field} exceeds 1024 items")
        for index, item in enumerate(value):
            _validate_json_tree(
                item,
                f"{field}[{index}]",
                depth=depth + 1,
                maximum_depth=maximum_depth,
            )
        return
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise V170ApiValidationError(f"{field} exceeds 128 fields")
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key or len(raw_key) > 128:
                raise V170ApiValidationError(f"{field} contains an invalid field name")
            _validate_json_tree(
                item,
                f"{field}.{raw_key}",
                depth=depth + 1,
                maximum_depth=maximum_depth,
            )
        return
    raise V170ApiValidationError(f"{field} contains an unsupported value")


def _optional_fingerprint(payload: dict[str, Any], field: str) -> None:
    if field not in payload or payload[field] in (None, ""):
        return
    value = _bounded_text(payload[field], field, 64, required=True).casefold()
    if not _ASSET_REVISION_RE.fullmatch(value):
        raise V170ApiValidationError(
            f"{field} must be a 32- or 64-character asset revision"
        )
    payload[field] = value


def validate_prompt_asset_facets_query(
    raw_query: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize the optional GET form of the facets endpoint."""

    if not isinstance(raw_query, Mapping):
        raise V170ApiValidationError("query parameters must be an object")
    payload: dict[str, Any] = {}
    for field in ("asset_type", "source"):
        value = raw_query.get(field)
        if value not in (None, ""):
            payload[field] = str(value)
    for field in ("favorite_only", "custom_only"):
        value = raw_query.get(field)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            payload[field] = value
            continue
        normalized = str(value).strip().casefold()
        if normalized not in {"0", "1", "false", "true"}:
            raise V170ApiValidationError(f"{field} must be a boolean")
        payload[field] = normalized in {"1", "true"}
    limit = raw_query.get("limit")
    if limit not in (None, ""):
        try:
            payload["limit"] = int(str(limit))
        except (TypeError, ValueError) as exc:
            raise V170ApiValidationError("limit must be an integer") from exc
    return validate_v170_api_payload("prompt_assets_facets", payload)


def _validate_asset_payload(payload: dict[str, Any], *, update: bool) -> None:
    if update:
        asset_id = _bounded_text(payload.get("asset_id"), "asset_id", 35, required=True)
        if not _ASSET_ID_RE.fullmatch(asset_id):
            raise V170ApiValidationError("asset_id has an invalid format")
        changes = payload.get("changes")
        if changes is not None:
            if not isinstance(changes, Mapping):
                raise V170ApiValidationError("changes must be an object")
            target = dict(changes)
        else:
            target = {key: value for key, value in payload.items() if key != "asset_id"}
    else:
        target = payload
        if "asset_id" in payload and payload["asset_id"] not in (None, ""):
            asset_id = _bounded_text(payload["asset_id"], "asset_id", 35, required=True)
            if not _ASSET_ID_RE.fullmatch(asset_id):
                raise V170ApiValidationError("asset_id has an invalid format")

    if "asset_type" in target:
        asset_type = _bounded_text(
            target["asset_type"], "asset_type", 32, required=True
        ).casefold()
        if asset_type not in _ASSET_TYPES:
            raise V170ApiValidationError("asset_type is not supported")
    for field in ("name_zh", "name_en"):
        if field in target:
            _bounded_text(target[field], field, 256)
    if "preview_url" in target:
        _bounded_text(target["preview_url"], "preview_url", 2048)
    for field in ("aliases", "tags", "traits", "categories"):
        if field in target:
            _bounded_text_list(
                target[field],
                field,
                maximum_items=128,
                maximum_item_length=256,
                allow_string=True,
            )
    if "provenance" in target:
        if not isinstance(target["provenance"], Mapping):
            raise V170ApiValidationError("provenance must be an object")
        _validate_json_tree(target["provenance"], "provenance", maximum_depth=5)


def validate_v170_api_payload(
    operation: str,
    raw_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize one shared standalone/native v1.7 API body."""

    if not isinstance(raw_payload, Mapping):
        raise V170ApiValidationError("request body must be a JSON object")
    payload = dict(raw_payload)
    _json_body_size(payload)

    if operation == "prompt_assets_search":
        if "query" in payload:
            payload["query"] = _bounded_text(payload["query"], "query", 256)
        if "source" in payload:
            payload["source"] = _bounded_text(payload["source"], "source", 2048)
        if "asset_type" in payload and payload["asset_type"] not in (None, ""):
            asset_type = _bounded_text(
                payload["asset_type"], "asset_type", 32, required=True
            ).casefold()
            if asset_type not in _ASSET_TYPES:
                raise V170ApiValidationError("asset_type is not supported")
            payload["asset_type"] = asset_type
        for field in ("categories", "traits", "tags"):
            if field in payload:
                payload[field] = _bounded_text_list(
                    payload[field],
                    field,
                    maximum_items=128,
                    maximum_item_length=256,
                    allow_string=True,
                )
        for field in ("favorite_only", "custom_only"):
            if field in payload and payload[field] is not None:
                payload[field] = _bounded_bool(payload[field], field)
        if "page" in payload:
            payload["page"] = _bounded_int(
                payload["page"], "page", minimum=1, maximum=V170_API_MAX_PAGE
            )
        if "page_size" in payload:
            payload["page_size"] = _bounded_int(
                payload["page_size"],
                "page_size",
                minimum=1,
                maximum=V170_API_MAX_PAGE_SIZE,
            )
        if "sort" in payload:
            sort = _bounded_text(payload["sort"], "sort", 32, required=True).casefold()
            if sort not in _ASSET_SORTS:
                raise V170ApiValidationError("sort is not supported")
            payload["sort"] = sort
        return payload

    if operation == "prompt_assets_facets":
        if "asset_type" in payload and payload["asset_type"] not in (None, ""):
            asset_type = _bounded_text(
                payload["asset_type"], "asset_type", 32, required=True
            ).casefold()
            if asset_type not in _ASSET_TYPES:
                raise V170ApiValidationError("asset_type is not supported")
            payload["asset_type"] = asset_type
        if "source" in payload:
            payload["source"] = _bounded_text(payload["source"], "source", 2048)
        for field in ("favorite_only", "custom_only"):
            if field in payload and payload[field] is not None:
                payload[field] = _bounded_bool(payload[field], field)
        if "limit" in payload:
            payload["limit"] = _bounded_int(
                payload["limit"],
                "limit",
                minimum=1,
                maximum=V170_API_MAX_PAGE_SIZE,
            )
        return payload

    if operation == "prompt_assets_import":
        text_values = [
            payload[key]
            for key in ("text", "content")
            if key in payload and payload[key] is not None
        ]
        if not text_values:
            raise V170ApiValidationError("text or content must be provided")
        if any(not isinstance(value, str) for value in text_values):
            raise V170ApiValidationError("import content must be a string")
        if len(text_values) == 2 and text_values[0] != text_values[1]:
            raise V170ApiValidationError("text and content must not conflict")
        content = text_values[0]
        if not content.strip():
            raise V170ApiValidationError("import content must not be empty")
        if len(content.encode("utf-8")) > V170_API_MAX_BODY_BYTES:
            raise V170ApiPayloadTooLargeError(
                "import content exceeds the 1 MiB limit"
            )
        format_values = [
            payload[key]
            for key in ("format", "content_type")
            if key in payload and payload[key] not in (None, "")
        ]
        normalized_formats = [
            _bounded_text(value, "format", 64, required=True).casefold()
            for value in format_values
        ]
        if any(value not in _IMPORT_FORMATS for value in normalized_formats):
            raise V170ApiValidationError("import format must be JSON or CSV")
        if len(set(normalized_formats)) > 1:
            aliases = {
                ".csv": "text/csv",
                ".json": "application/json",
                "csv": "text/csv",
                "json": "application/json",
            }
            canonical = {aliases.get(value, value) for value in normalized_formats}
            if len(canonical) > 1:
                raise V170ApiValidationError("format and content_type must not conflict")
        payload["source"] = _bounded_text(
            payload.get("source"), "source", 2048, required=True
        )
        if "version" in payload:
            payload["version"] = _bounded_text(payload["version"], "version", 256)
        if "mode" in payload:
            mode = _bounded_text(payload["mode"], "mode", 16, required=True).casefold()
            if mode not in _IMPORT_MODES:
                raise V170ApiValidationError(
                    "mode must be merge, replace, or replace_source"
                )
            payload["mode"] = mode
        if "provenance" in payload:
            if not isinstance(payload["provenance"], Mapping):
                raise V170ApiValidationError("provenance must be an object")
            _validate_json_tree(payload["provenance"], "provenance", maximum_depth=5)
        return payload

    if operation == "prompt_assets_update_url":
        url = _bounded_text(payload.get("url"), "url", 2048, required=True)
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise V170ApiValidationError("url contains control characters")
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise V170ApiValidationError("url has an invalid host or port") from exc
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise V170ApiValidationError("url must be an HTTP(S) URL without credentials")
        payload["url"] = url
        if "timeout" in payload:
            payload["timeout"] = _bounded_number(
                payload["timeout"], "timeout", minimum=1, maximum=120
            )
        if "mode" in payload:
            mode = _bounded_text(payload["mode"], "mode", 16, required=True).casefold()
            if mode not in _IMPORT_MODES:
                raise V170ApiValidationError(
                    "mode must be merge, replace, or replace_source"
                )
            payload["mode"] = mode
        if "provenance" in payload:
            if not isinstance(payload["provenance"], Mapping):
                raise V170ApiValidationError("provenance must be an object")
            _validate_json_tree(payload["provenance"], "provenance", maximum_depth=5)
        return payload

    if operation == "prompt_assets_sync_local":
        _validate_json_tree(payload, "local asset sync", maximum_depth=4)
        return payload

    if operation == "prompt_asset_create":
        _validate_asset_payload(payload, update=False)
        _validate_json_tree(payload, "custom asset", maximum_depth=6)
        return payload

    if operation == "prompt_asset_update":
        _validate_asset_payload(payload, update=True)
        _validate_json_tree(payload, "custom asset", maximum_depth=6)
        return payload

    if operation in {"prompt_asset_delete", "prompt_asset_favorite"}:
        asset_id = _bounded_text(payload.get("asset_id"), "asset_id", 35, required=True)
        if not _ASSET_ID_RE.fullmatch(asset_id):
            raise V170ApiValidationError("asset_id has an invalid format")
        payload["asset_id"] = asset_id
        if operation == "prompt_asset_favorite":
            payload["favorite"] = _bounded_bool(payload.get("favorite"), "favorite")
        return payload

    if operation == "compose_prompt_slots":
        slots = payload.get("slots")
        if not isinstance(slots, Mapping):
            raise V170ApiValidationError("slots must be an object")
        if len(slots) > 32:
            raise V170ApiValidationError("slots exceeds 32 fields")
        for raw_name, value in slots.items():
            name = _bounded_text(raw_name, "slot name", 64, required=True)
            _bounded_text_list(
                value,
                f"slots.{name}",
                maximum_items=256,
                maximum_item_length=2048,
                allow_string=True,
            )
        if "locked_slots" in payload:
            payload["locked_slots"] = _bounded_text_list(
                payload["locked_slots"],
                "locked_slots",
                maximum_items=32,
                maximum_item_length=64,
            )
        if "positive_prompt" in payload:
            payload["positive_prompt"] = _bounded_text(
                payload["positive_prompt"], "positive_prompt", 16_384
            )
        if "negative_prompt" in payload:
            payload["negative_prompt"] = _bounded_text(
                payload["negative_prompt"], "negative_prompt", 8192
            )
        return payload

    if operation == "prompt_lab_generate":
        if "seed" not in payload:
            raise V170ApiValidationError("seed must be provided")
        seed = payload["seed"]
        if isinstance(seed, bool) or not isinstance(seed, (int, str)):
            raise V170ApiValidationError("seed must be an integer or string")
        if isinstance(seed, int):
            payload["seed"] = _bounded_int(
                seed,
                "seed",
                minimum=-(2**63),
                maximum=2**63 - 1,
            )
        else:
            payload["seed"] = _bounded_text(seed, "seed", 256, required=True)
        if "count" in payload:
            payload["count"] = _bounded_int(
                payload["count"],
                "count",
                minimum=1,
                maximum=V170_API_MAX_CANDIDATES,
            )
        for field in ("base_layers", "asset_pools"):
            if field in payload and not isinstance(payload[field], Mapping):
                raise V170ApiValidationError(f"{field} must be an object")
        for field in ("locked_layers", "enabled_asset_types"):
            if field in payload:
                payload[field] = _bounded_text_list(
                    payload[field],
                    field,
                    maximum_items=16,
                    maximum_item_length=64,
                )
        if "negative_prompt" in payload:
            payload["negative_prompt"] = _bounded_text(
                payload["negative_prompt"], "negative_prompt", 8192
            )
        if "visual_phrases" in payload:
            payload["visual_phrases"] = _bounded_text_list(
                payload["visual_phrases"],
                "visual_phrases",
                maximum_items=64,
                maximum_item_length=512,
                allow_string=True,
            )
        _optional_fingerprint(payload, "asset_library_fingerprint")
        _validate_json_tree(payload, "prompt lab request", maximum_depth=8)
        return payload

    if operation == "prompt_lab_confirm":
        batch_id = _bounded_text(
            payload.get("batch_id"), "batch_id", 64, required=True
        ).casefold()
        if not _LAB_BATCH_RE.fullmatch(batch_id):
            raise V170ApiValidationError("batch_id has an invalid format")
        payload["batch_id"] = batch_id
        selection = payload.get("selection", payload.get("candidate_id"))
        if selection is None:
            raise V170ApiValidationError("selection or candidate_id must be provided")
        if isinstance(selection, bool) or not isinstance(selection, (int, str)):
            raise V170ApiValidationError("selection must be a candidate ID or ordinal")
        if isinstance(selection, int):
            normalized_selection: int | str = _bounded_int(
                selection,
                "selection",
                minimum=1,
                maximum=V170_API_MAX_CANDIDATES,
            )
        else:
            normalized_selection = _bounded_text(
                selection, "selection", 64, required=True
            ).casefold()
            if normalized_selection.isdecimal():
                normalized_selection = _bounded_int(
                    int(normalized_selection),
                    "selection",
                    minimum=1,
                    maximum=V170_API_MAX_CANDIDATES,
                )
            elif not _LAB_CANDIDATE_RE.fullmatch(normalized_selection):
                raise V170ApiValidationError("candidate_id has an invalid format")
        if "selection" in payload:
            payload["selection"] = normalized_selection
        if "candidate_id" in payload:
            payload["candidate_id"] = normalized_selection
        if "save_plan" in payload:
            payload["save_plan"] = _bounded_bool(
                payload["save_plan"], "save_plan"
            )
        if "plan_name" in payload:
            payload["plan_name"] = _bounded_text(
                payload["plan_name"], "plan_name", 80
            )
        if "pipeline" in payload:
            pipeline = _bounded_text(
                payload["pipeline"], "pipeline", 16, required=True
            ).casefold()
            if pipeline not in {"base", "rtx", "iterative"}:
                raise V170ApiValidationError("pipeline is not supported")
            payload["pipeline"] = pipeline
        _optional_fingerprint(payload, "asset_library_fingerprint")
        return payload

    if operation == "prompt_plan_delete":
        plan_id = _bounded_text(
            payload.get("plan_id"), "plan_id", 8, required=True
        ).upper()
        if not _PROMPT_PLAN_ID_RE.fullmatch(plan_id):
            raise V170ApiValidationError(
                "plan_id must be a custom P-XXXXXX identifier"
            )
        return {"plan_id": plan_id}

    if operation == "lora_gallery":
        if "query" in payload:
            payload["query"] = _bounded_text(payload["query"], "query", 512)
        if "favorites_only" in payload:
            payload["favorites_only"] = _bounded_bool(
                payload["favorites_only"], "favorites_only"
            )
        for field in ("categories", "metadata_statuses", "preview_statuses"):
            if field in payload:
                payload[field] = _bounded_text_list(
                    payload[field],
                    field,
                    maximum_items=64,
                    maximum_item_length=128,
                    allow_string=True,
                )
        if "page" in payload:
            payload["page"] = _bounded_int(
                payload["page"], "page", minimum=1, maximum=V170_API_MAX_PAGE
            )
        if "page_size" in payload:
            payload["page_size"] = _bounded_int(
                payload["page_size"],
                "page_size",
                minimum=1,
                maximum=V170_API_MAX_PAGE_SIZE,
            )
        return payload

    if operation == "lora_visual_warm":
        if "limit" in payload:
            payload["limit"] = _bounded_int(
                payload["limit"],
                "limit",
                minimum=1,
                maximum=V170_API_MAX_WARMUP,
            )
        if "keys" in payload:
            keys = _bounded_text_list(
                payload["keys"],
                "keys",
                maximum_items=V170_API_MAX_WARMUP,
                maximum_item_length=64,
            )
            if not isinstance(keys, list):
                raise V170ApiValidationError("keys must be a list")
            normalized: list[str] = []
            for key in keys:
                safe_key = key.casefold()
                if not _CONTENT_FINGERPRINT_RE.fullmatch(safe_key):
                    raise V170ApiValidationError(
                        "keys must contain only 64-character content keys"
                    )
                if safe_key not in normalized:
                    normalized.append(safe_key)
            payload["keys"] = normalized
        return payload

    raise V170ApiValidationError("unsupported v1.7 API operation")


def validate_lora_preview_query(key: Any, fingerprint: Any) -> tuple[str, str]:
    """Reject paths/URLs and accept content-addressed identifiers only."""

    safe_key = _bounded_text(key, "key", 64, required=True).casefold()
    safe_fingerprint = _bounded_text(
        fingerprint, "fingerprint", 64, required=True
    ).casefold()
    if not _CONTENT_FINGERPRINT_RE.fullmatch(safe_key):
        raise V170ApiValidationError("key must be a 64-character content key")
    if not _CONTENT_FINGERPRINT_RE.fullmatch(safe_fingerprint):
        raise V170ApiValidationError("fingerprint must be a 64-character manifest fingerprint")
    return safe_key, safe_fingerprint


def validate_lora_preview_response(
    result: Any,
    *,
    key: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Return only a strictly bounded data-URL preview response."""

    if not isinstance(result, Mapping):
        raise V170ApiValidationError("preview response must be an object")
    if any(name in result for name in ("path", "file_path", "url", "preview_url")):
        raise V170ApiValidationError("preview response must not expose paths or URLs")
    response_key, response_fingerprint = validate_lora_preview_query(
        result.get("key"), result.get("fingerprint")
    )
    if response_key != key or response_fingerprint != fingerprint:
        raise V170ApiValidationError("preview response does not match the requested manifest")
    media_type = _bounded_text(
        result.get("media_type"), "media_type", 32, required=True
    ).casefold()
    data_url = _bounded_text(
        result.get("data_url"),
        "data_url",
        V170_API_MAX_PREVIEW_DATA_URL,
        required=True,
    )
    match = _DATA_URL_RE.fullmatch(data_url)
    if match is None or match.group(1).casefold() != media_type:
        raise V170ApiValidationError("preview must be a matching image data URL")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise V170ApiValidationError("preview contains invalid base64 data") from exc
    if not decoded or len(decoded) > V170_API_MAX_PREVIEW_BYTES:
        raise V170ApiValidationError("preview exceeds the 1 MiB response limit")
    declared_size = _bounded_int(
        result.get("size"),
        "size",
        minimum=1,
        maximum=V170_API_MAX_PREVIEW_BYTES,
    )
    if declared_size != len(decoded):
        raise V170ApiValidationError("preview size does not match its data URL")
    safe = {
        "key": response_key,
        "fingerprint": response_fingerprint,
        "media_type": media_type,
        "size": declared_size,
        "data_url": data_url,
    }
    for field in ("width", "height"):
        if field in result and result[field] is not None:
            safe[field] = _bounded_int(
                result[field], field, minimum=1, maximum=4096
            )
    if "cached" in result:
        safe["cached"] = _bounded_bool(result["cached"], "cached")
    return safe


class PluginPageActionError(RuntimeError):
    """Safe, user-facing native page request error."""


class PluginPageApi:
    """Expose existing management operations through AstrBot's authenticated bridge."""

    ROUTE = f"/{PLUGIN_NAME}/api/gateway"
    _ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})

    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def register(self, context: Any) -> bool:
        register = getattr(context, "register_web_api", None)
        if not callable(register):
            return False
        try:
            register(
                self.ROUTE,
                self.handle,
                ["POST"],
                "Comfy Anima native management page gateway",
            )
        except Exception as exc:
            logger.warning(
                "[%s] Native plugin-page API registration failed: %s",
                PLUGIN_NAME,
                type(exc).__name__,
            )
            return False
        return True

    async def handle(self):
        """Read the current AstrBot plugin request and return a safe response."""

        from astrbot.api.web import error_response, json_response, request

        from .web_ui import WebUiActionError

        try:
            declared_length = request.headers.get("content-length")
            if declared_length not in (None, ""):
                try:
                    if int(str(declared_length)) > V170_API_MAX_BODY_BYTES:
                        return error_response(
                            "请求体超过 1 MiB 限制",
                            status_code=413,
                        )
                except (TypeError, ValueError):
                    return error_response("Content-Length 无效", status_code=400)
            payload = decode_plugin_gateway_body(
                await request.body(),
                declared_length,
            )
        except V170ApiPayloadTooLargeError as exc:
            return error_response(str(exc), status_code=413)
        except V170ApiValidationError as exc:
            return error_response(str(exc), status_code=400)
        try:
            result = await self.dispatch(payload)
        except (
            PluginPageActionError,
            V170ApiValidationError,
            WebUiActionError,
        ) as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.error(
                "[%s] Native plugin-page operation failed: %s",
                PLUGIN_NAME,
                type(exc).__name__,
                exc_info=True,
            )
            return error_response("操作失败，请查看 AstrBot 日志", status_code=500)
        return json_response({"status": "ok", "data": result})

    async def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        method = str(envelope.get("method") or "GET").strip().upper()
        if method not in self._ALLOWED_METHODS:
            raise PluginPageActionError("不支持的请求方法")
        path = self._normalize_api_path(envelope.get("path"))
        query = self._normalize_query(envelope.get("query"))
        raw_body = envelope.get("body")
        body = {} if raw_body is None else raw_body
        if not isinstance(body, dict):
            raise PluginPageActionError("请求体必须是 JSON 对象")

        if method == "GET" and path == "/api/bootstrap":
            return await self._controller.web_ui_bootstrap()
        if method == "GET" and path == "/api/providers":
            return await self._controller.web_ui_list_providers()
        if method == "PUT" and path == "/api/settings":
            return await self._controller.web_ui_save_settings(
                self._validated_settings(body)
            )
        if method == "GET" and path == "/api/prompt/status":
            return await self._controller.web_ui_prompt_status()
        if method == "POST" and path == "/api/prompt/diagnose":
            prompt = str(body.get("prompt") or "")
            negative = str(body.get("negative_prompt") or "")
            if not prompt.strip() or len(prompt) > 6000:
                raise PluginPageActionError("提示词必须为 1–6000 个字符")
            if len(negative) > 2000:
                raise PluginPageActionError("负面提示词不能超过 2000 个字符")
            return await self._controller.web_ui_diagnose_prompt(
                {"prompt": prompt, "negative_prompt": negative}
            )
        if method == "DELETE" and path == "/api/prompt/diagnostics":
            return await self._controller.web_ui_clear_prompt_diagnostics()
        if method == "POST" and path == "/api/danbooru/update":
            return await self._controller.web_ui_update_danbooru_index()
        if method == "GET" and path == "/api/experiments/check":
            return await self._controller.web_ui_check_experimental_profiles()

        if method == "GET" and path == "/api/prompt-assets/status":
            return await self._controller.web_ui_prompt_assets_status()
        if method == "POST" and path == "/api/prompt-assets/search":
            return await self._controller.web_ui_prompt_assets_search(
                validate_v170_api_payload("prompt_assets_search", body)
            )
        if method == "GET" and path == "/api/prompt-assets/facets":
            return await self._controller.web_ui_prompt_assets_facets(
                validate_prompt_asset_facets_query(query)
            )
        if method == "POST" and path == "/api/prompt-assets/facets":
            return await self._controller.web_ui_prompt_assets_facets(
                validate_v170_api_payload("prompt_assets_facets", body)
            )
        if method == "POST" and path == "/api/prompt-assets/import":
            return await self._controller.web_ui_prompt_assets_import(
                validate_v170_api_payload("prompt_assets_import", body)
            )
        if method == "POST" and path == "/api/prompt-assets/update-url":
            return await self._controller.web_ui_prompt_assets_update_url(
                validate_v170_api_payload("prompt_assets_update_url", body)
            )
        if method == "POST" and path == "/api/prompt-assets/sync-local":
            return await self._controller.web_ui_prompt_assets_sync_local(
                validate_v170_api_payload("prompt_assets_sync_local", body)
            )
        if method == "POST" and path == "/api/prompt-assets/custom":
            return await self._controller.web_ui_prompt_asset_create(
                validate_v170_api_payload("prompt_asset_create", body)
            )
        if method == "PUT" and path == "/api/prompt-assets/custom":
            return await self._controller.web_ui_prompt_asset_update(
                validate_v170_api_payload("prompt_asset_update", body)
            )
        if method == "DELETE" and path == "/api/prompt-assets/custom":
            return await self._controller.web_ui_prompt_asset_delete(
                validate_v170_api_payload("prompt_asset_delete", body)
            )
        if method == "PUT" and path == "/api/prompt-assets/favorite":
            return await self._controller.web_ui_prompt_asset_favorite(
                validate_v170_api_payload("prompt_asset_favorite", body)
            )
        if method == "POST" and path == "/api/prompt/compose-slots":
            return await self._controller.web_ui_compose_prompt_slots(
                validate_v170_api_payload("compose_prompt_slots", body)
            )
        if method == "POST" and path == "/api/prompt-lab/generate":
            return await self._controller.web_ui_prompt_lab_generate(
                validate_v170_api_payload("prompt_lab_generate", body)
            )
        if method == "POST" and path == "/api/prompt-lab/confirm":
            return await self._controller.web_ui_prompt_lab_confirm(
                validate_v170_api_payload("prompt_lab_confirm", body)
            )
        if method == "GET" and path == "/api/prompt-plans":
            return await self._controller.web_ui_list_prompt_plans()
        if method == "POST" and path == "/api/prompt-plans/delete":
            return await self._controller.web_ui_delete_prompt_plan(
                validate_v170_api_payload("prompt_plan_delete", body)
            )

        if method == "GET" and path == "/api/loras":
            return await self._controller.web_ui_search_loras(
                self._query_text(query, "q", 1000),
                self._query_int(query, "limit", 50, minimum=1, maximum=1000),
            )
        if method == "POST" and path == "/api/loras/refresh":
            return await self._controller.web_ui_refresh_loras()
        if method == "POST" and path == "/api/loras/download":
            return await self._controller.web_ui_download_lora(
                str(body.get("url") or "")
            )
        if method == "POST" and path in {
            "/api/loras/metadata",
            "/api/lora/metadata-fetch",
        }:
            return await self._controller.web_ui_fetch_lora_metadata(dict(body))
        if method == "GET" and path == "/api/loras/detail":
            name = self._query_text(query, "name", 500)
            if not name:
                raise PluginPageActionError("LoRA 名称无效")
            return await self._controller.web_ui_get_lora_detail(name)
        if method == "POST" and path == "/api/loras/delete":
            return await self._controller.web_ui_delete_lora(dict(body))
        if method == "PUT" and path == "/api/loras/semantic":
            return await self._controller.web_ui_save_lora_semantic(dict(body))
        if method == "GET" and path in {
            "/api/loras/archive",
            "/api/lora/archive/status",
            "/api/lora/archive/index",
        }:
            archive = await self._controller.web_ui_get_lora_archive()
            if path.endswith("/status"):
                return dict(archive.get("status") or {})
            if path.endswith("/index"):
                return {"items": list(archive.get("items") or [])}
            return archive
        if method == "POST" and path in {
            "/api/loras/archive",
            "/api/lora/archive",
            "/api/lora/archive/run",
        }:
            return await self._controller.web_ui_archive_loras(dict(body))
        if method == "POST" and path == "/api/loras/gallery":
            return await self._controller.web_ui_lora_gallery(
                validate_v170_api_payload("lora_gallery", body)
            )
        if method == "POST" and path == "/api/loras/thumbnails/warm":
            return await self._controller.web_ui_lora_visual_warm(
                validate_v170_api_payload("lora_visual_warm", body)
            )
        if method == "GET" and path == "/api/loras/thumbnails/status":
            return await self._controller.web_ui_lora_visual_status()
        if method == "DELETE" and path == "/api/loras/thumbnails/cache":
            return await self._controller.web_ui_lora_visual_prune()
        if method == "GET" and path == "/api/loras/preview":
            key, fingerprint = validate_lora_preview_query(
                query.get("key"), query.get("fingerprint")
            )
            result = await self._controller.web_ui_lora_preview(key, fingerprint)
            return validate_lora_preview_response(
                result,
                key=key,
                fingerprint=fingerprint,
            )

        if method == "GET" and path == "/api/presets":
            return await self._controller.web_ui_list_presets()
        if method == "POST" and path == "/api/presets":
            return await self._controller.web_ui_save_preset(dict(body))
        if method == "DELETE" and path.startswith("/api/presets/"):
            identifier = self._path_tail(path, "/api/presets/", 500)
            return await self._controller.web_ui_delete_preset(identifier)

        if method == "GET" and path == "/api/workflows":
            return await self._controller.web_ui_list_workflows()
        if method == "GET" and path == "/api/workflows/check":
            return await self._controller.web_ui_check_workflows()
        if method == "POST" and path == "/api/workflows/select":
            return await self._controller.web_ui_select_workflow(
                str(body.get("identifier") or body.get("filename") or "")
            )

        if method == "GET" and path == "/api/unet":
            return await self._controller.web_ui_list_unet()
        if method == "POST" and path == "/api/unet/select":
            return await self._controller.web_ui_select_unet(
                str(body.get("identifier") or "")
            )
        if method == "POST" and path == "/api/unet/delete":
            return await self._controller.web_ui_delete_unet(dict(body))

        if method == "GET" and path == "/api/config-profiles":
            return await self._controller.web_ui_list_config_profiles()
        if method == "POST" and path == "/api/config-profiles":
            return await self._controller.web_ui_save_config_profile(dict(body))
        if method == "POST" and path == "/api/config-profiles/switch":
            return await self._controller.web_ui_switch_config_profile(
                str(body.get("identifier") or body.get("name") or "")
            )
        if method == "POST" and path.startswith("/api/config-profiles/") and path.endswith("/activate"):
            identifier = path[len("/api/config-profiles/") : -len("/activate")]
            return await self._controller.web_ui_switch_config_profile(
                self._path_identifier(identifier, 500)
            )
        if method == "DELETE" and path.startswith("/api/config-profiles/"):
            identifier = self._path_tail(path, "/api/config-profiles/", 500)
            return await self._controller.web_ui_delete_config_profile(identifier)

        if method == "GET" and path == "/api/logs":
            return await self._controller.web_ui_get_logs(
                self._query_int(query, "after", 0, minimum=0, maximum=2**63 - 1),
                self._query_int(query, "limit", 500, minimum=1, maximum=1000),
            )
        if method == "DELETE" and path == "/api/logs":
            return await self._controller.web_ui_clear_logs()

        if method == "GET" and path == "/api/tasks":
            status = self._query_text(query, "status", 100).casefold()
            if status and status not in TASK_STATUSES:
                raise PluginPageActionError("任务状态不受支持")
            return await self._controller.web_ui_list_tasks(
                self._query_int(query, "limit", 50, minimum=1, maximum=500),
                self._query_text(query, "type", 100),
                status,
            )
        if path.startswith("/api/tasks/"):
            suffix = path[len("/api/tasks/") :]
            if suffix.endswith("/events") and method == "GET":
                run_id = self._validated_run_id(suffix[: -len("/events")])
                return await self._controller.web_ui_get_task_events(
                    run_id,
                    self._query_int(
                        query,
                        "after",
                        0,
                        minimum=0,
                        maximum=2**31 - 1,
                    ),
                    self._query_int(
                        query,
                        "limit",
                        500,
                        minimum=1,
                        maximum=2000,
                    ),
                )
            if suffix.endswith("/cancel") and method == "POST":
                run_id = self._validated_run_id(suffix[: -len("/cancel")])
                return await self._controller.web_ui_cancel_task(run_id)
            if method == "GET":
                return await self._controller.web_ui_get_task(
                    self._validated_run_id(suffix)
                )

        if method == "POST" and path == "/api/logout":
            return {"message": "原生插件页由 AstrBot Dashboard 管理登录状态"}
        raise PluginPageActionError("不支持的原生插件页操作")

    @staticmethod
    def _normalize_api_path(raw_path: Any) -> str:
        path = str(raw_path or "").strip()
        if (
            not path.startswith("/api/")
            or len(path) > 2048
            or "\\" in path
            or "?" in path
            or "#" in path
        ):
            raise PluginPageActionError("插件页 API 路径无效")
        decoded: list[str] = []
        for raw_segment in path.split("/")[1:]:
            segment = unquote(raw_segment)
            if (
                not segment
                or segment in {".", ".."}
                or "/" in segment
                or "\\" in segment
                or len(segment) > 500
            ):
                raise PluginPageActionError("插件页 API 路径无效")
            decoded.append(segment)
        return "/" + "/".join(decoded)

    @staticmethod
    def _normalize_query(raw_query: Any) -> dict[str, str]:
        if raw_query is None:
            return {}
        if not isinstance(raw_query, Mapping) or len(raw_query) > 32:
            raise PluginPageActionError("查询参数无效")
        result: dict[str, str] = {}
        for raw_key, raw_value in raw_query.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()
            if not key or len(key) > 100 or len(value) > 2000:
                raise PluginPageActionError("查询参数无效")
            result[key] = value
        return result

    @staticmethod
    def _query_text(query: Mapping[str, str], key: str, limit: int) -> str:
        value = str(query.get(key) or "").strip()
        if len(value) > limit:
            raise PluginPageActionError("查询参数过长")
        return value

    @staticmethod
    def _query_int(
        query: Mapping[str, str],
        key: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = query.get(key)
        if raw_value in (None, ""):
            return default
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise PluginPageActionError("查询参数必须是整数") from exc
        if value < minimum or value > maximum:
            raise PluginPageActionError("查询参数超出允许范围")
        return value

    @staticmethod
    def _validated_settings(body: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(body)
        if "sampler_steps_override" not in payload:
            return payload
        raw_value = payload["sampler_steps_override"]
        if isinstance(raw_value, bool):
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数") from exc
        if str(raw_value).strip() != str(value) or not 0 <= value <= 100:
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数")
        payload["sampler_steps_override"] = value
        return payload

    @staticmethod
    def _path_identifier(identifier: str, limit: int) -> str:
        value = identifier.strip()
        if not value or len(value) > limit or "/" in value or "\\" in value:
            raise PluginPageActionError("资源标识无效")
        return value

    @classmethod
    def _path_tail(cls, path: str, prefix: str, limit: int) -> str:
        return cls._path_identifier(path[len(prefix) :], limit)

    @staticmethod
    def _validated_run_id(run_id: str) -> str:
        value = run_id.strip()
        if (
            not value
            or len(value) > 128
            or not all(character.isalnum() or character in "-_" for character in value)
        ):
            raise PluginPageActionError("任务 ID 格式无效")
        return value


__all__ = [
    "PluginPageActionError",
    "PluginPageApi",
    "V170ApiPayloadTooLargeError",
    "V170ApiValidationError",
    "decode_plugin_gateway_body",
    "validate_lora_preview_query",
    "validate_lora_preview_response",
    "validate_prompt_asset_facets_query",
    "validate_v170_api_payload",
]
