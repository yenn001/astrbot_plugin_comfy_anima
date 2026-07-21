"""Safe hybrid LoRA retrieval over one freshly validated catalog snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ..core.lora import canonical_lora_name
from ..models import PluginSettings
from .lora_catalog import LoraCatalogService, LoraRecord


logger = logging.getLogger("astrbot")
_CACHE_SCHEMA = 1
_MAX_VECTOR_DIMENSION = 65_536
_EMBED_BATCH_SIZE = 16


def _normalized_identity(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def _provider_id(provider: Any) -> str:
    config = getattr(provider, "provider_config", {})
    if not isinstance(config, Mapping):
        config = {}
    try:
        meta = provider.meta()
    except Exception:
        meta = None
    return str(
        getattr(meta, "id", "")
        or config.get("id")
        or config.get("provider_id")
        or ""
    ).strip()


def _provider_signature(provider: Any, configured_id: str, kind: str) -> str:
    config = getattr(provider, "provider_config", {})
    if not isinstance(config, Mapping):
        config = {}
    try:
        meta = provider.meta()
    except Exception:
        meta = None
    model = str(
        getattr(meta, "model", "")
        or config.get(f"{kind}_model")
        or config.get("model")
        or config.get("model_name")
        or ""
    )
    provider_type = str(
        getattr(meta, "type", "")
        or config.get("type")
        or config.get("provider_type")
        or ""
    )
    material = "\n".join((configured_id, _provider_id(provider), kind, model, provider_type))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LoraHybridSearchService:
    """Embedding recall and rerank without weakening exact live-file validation."""

    def __init__(
        self,
        settings: PluginSettings,
        context: Any,
        cache_path: Optional[Path] = None,
    ) -> None:
        self._settings = settings
        self._context = context
        self._cache_path = Path(cache_path) if cache_path else None
        self._lock = asyncio.Lock()
        self.last_diagnostics: dict[str, Any] = {
            "mode": "lexical",
            "embedding_used": False,
            "rerank_used": False,
            "fallback_code": "",
        }

    async def search(
        self,
        records: tuple[LoraRecord, ...],
        query: str,
        *,
        limit: int,
    ) -> tuple[LoraRecord, ...]:
        """Rank only records supplied by the caller's current authoritative scan."""
        effective_limit = max(1, int(limit))
        clean_query = str(query or "").strip()
        self.last_diagnostics = {
            "mode": "lexical",
            "embedding_used": False,
            "rerank_used": False,
            "fallback_code": "",
            "records": len(records),
            "query_length": len(clean_query),
        }
        if not clean_query:
            return records[:effective_limit]

        exact, exact_kind = self._exact_matches(records, clean_query)
        trusted_exact_kinds = {"path", "basename"}
        if bool(
            getattr(self._settings, "enable_layered_lora_retrieval", True)
        ):
            trusted_exact_kinds.add("alias")
        if len(exact) == 1 and exact_kind in trusted_exact_kinds:
            self.last_diagnostics.update(mode="exact", exact_kind=exact_kind)
            return exact[:effective_limit]

        lexical_records = self._category_filtered_records(records, clean_query)
        lexical_ranked = LoraCatalogService.rank_records(
            lexical_records,
            clean_query,
        )
        lexical = tuple(record for _score, record in lexical_ranked)
        if not bool(getattr(self._settings, "enable_lora_hybrid_search", False)):
            return self._stable_union(exact, lexical)[:effective_limit]

        timeout = max(
            0.01,
            float(getattr(self._settings, "lora_retrieval_timeout", 30)),
        )
        try:
            return await asyncio.wait_for(
                self._hybrid_search(
                    records,
                    clean_query,
                    lexical,
                    exact,
                    effective_limit,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.last_diagnostics["fallback_code"] = "timeout"
        except Exception as exc:
            self.last_diagnostics["fallback_code"] = f"{type(exc).__name__}"
        self.last_diagnostics["mode"] = "lexical_fallback"
        return self._stable_union(exact, lexical)[:effective_limit]

    async def _hybrid_search(
        self,
        records: tuple[LoraRecord, ...],
        query: str,
        lexical: tuple[LoraRecord, ...],
        exact: tuple[LoraRecord, ...],
        limit: int,
    ) -> tuple[LoraRecord, ...]:
        top_k = max(4, min(100, int(getattr(self._settings, "lora_embedding_top_k", 20))))
        candidate_budget = max(limit, top_k)
        embedding_ranked: tuple[LoraRecord, ...] = ()
        embedding_provider = self._find_embedding_provider()
        if embedding_provider is not None:
            try:
                embedding_ranked = await self._embedding_recall(
                    embedding_provider,
                    records,
                    query,
                    top_k,
                )
                self.last_diagnostics["embedding_used"] = True
            except Exception as exc:
                self.last_diagnostics["embedding_fallback"] = type(exc).__name__
                self.last_diagnostics["fallback_code"] = "embedding_unavailable"

        candidates = self._stable_union(
            exact,
            lexical[:candidate_budget],
            embedding_ranked,
        )
        rerank_provider = self._find_rerank_provider()
        if rerank_provider is not None and candidates:
            pinned_keys = {self._record_key(record) for record in exact}
            pinned = tuple(
                record for record in candidates if self._record_key(record) in pinned_keys
            )
            remainder = tuple(
                record for record in candidates if self._record_key(record) not in pinned_keys
            )
            if remainder:
                try:
                    rerank_budget = min(16, len(remainder))
                    reranked = await self._rerank(
                        rerank_provider,
                        query,
                        remainder[:rerank_budget],
                    )
                    remainder = self._stable_union(
                        reranked,
                        remainder[rerank_budget:],
                    )
                    self.last_diagnostics["rerank_used"] = True
                except Exception as exc:
                    self.last_diagnostics["rerank_fallback"] = type(exc).__name__
                    self.last_diagnostics["fallback_code"] = "rerank_unavailable"
            candidates = self._stable_union(pinned, remainder)

        self.last_diagnostics["mode"] = "hybrid"
        self.last_diagnostics["candidate_count"] = len(candidates)
        return candidates[:limit]

    @staticmethod
    def _category_filtered_records(
        records: tuple[LoraRecord, ...],
        query: str,
    ) -> tuple[LoraRecord, ...]:
        """Narrow lexical recall only when the user states a category intent."""

        folded = str(query or "").casefold()
        wanted: set[str] = set()
        if re.search(r"角色|人物|character|identity", folded):
            wanted.update({"character", "角色"})
        if re.search(r"画师|风格|artist|style|aesthetic", folded):
            wanted.update({"artist", "style", "画师", "风格"})
        if re.search(r"加速|提速|蒸馏|lightning|turbo|hyper|lcm|utility", folded):
            wanted.update({"utility", "acceleration", "功能", "加速"})
        if not wanted:
            return records
        filtered = tuple(
            record
            for record in records
            if any(token in str(record.category or "").casefold() for token in wanted)
        )
        return filtered or records

    def _find_embedding_provider(self) -> Any:
        identifier = str(
            getattr(self._settings, "lora_embedding_provider_id", "") or ""
        ).strip()
        if not identifier:
            return None
        provider = self._provider_by_id(identifier)
        if provider is not None and (
            callable(getattr(provider, "get_embeddings", None))
            or callable(getattr(provider, "get_embedding", None))
        ):
            return provider
        getter = getattr(self._context, "get_all_embedding_providers", None)
        providers = getter() if callable(getter) else ()
        for item in providers or ():
            if _provider_id(item) == identifier:
                return item
        return None

    def _find_rerank_provider(self) -> Any:
        identifier = str(
            getattr(self._settings, "lora_rerank_provider_id", "") or ""
        ).strip()
        if not identifier:
            return None
        provider = self._provider_by_id(identifier)
        if provider is not None and callable(getattr(provider, "rerank", None)):
            return provider
        manager = getattr(self._context, "provider_manager", None)
        instances = getattr(manager, "rerank_provider_insts", ())
        if isinstance(instances, Mapping):
            direct = instances.get(identifier)
            if direct is not None:
                return direct
            instances = instances.values()
        for item in instances or ():
            if _provider_id(item) == identifier:
                return item
        return None

    def _provider_by_id(self, identifier: str) -> Any:
        getter = getattr(self._context, "get_provider_by_id", None)
        if not callable(getter):
            return None
        try:
            return getter(identifier)
        except Exception:
            return None

    async def _embedding_recall(
        self,
        provider: Any,
        records: tuple[LoraRecord, ...],
        query: str,
        top_k: int,
    ) -> tuple[LoraRecord, ...]:
        documents = tuple(self._search_document(record) for record in records)
        vectors = await self._synchronize_vectors(provider, records, documents)
        query_vectors = await self._embed_texts(provider, (query,))
        query_vector = self._normalize_vector(query_vectors[0])
        scored = [
            (self._dot(query_vector, vectors[index]), index, record)
            for index, record in enumerate(records)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(record for _score, _index, record in scored[:top_k])

    async def _synchronize_vectors(
        self,
        provider: Any,
        records: tuple[LoraRecord, ...],
        documents: tuple[str, ...],
    ) -> tuple[tuple[float, ...], ...]:
        async with self._lock:
            identifier = str(
                getattr(self._settings, "lora_embedding_provider_id", "") or ""
            ).strip()
            signature = _provider_signature(provider, identifier, "embedding")
            cache = self._load_cache(signature)
            cached_entries = cache.get("entries", {})
            if not isinstance(cached_entries, Mapping):
                cached_entries = {}

            result: list[Optional[tuple[float, ...]]] = [None] * len(records)
            missing_indexes: list[int] = []
            new_entries: dict[str, dict[str, Any]] = {}
            for index, (record, document) in enumerate(zip(records, documents)):
                identity = self._identity_hash(record)
                fingerprint = hashlib.sha256(document.encode("utf-8")).hexdigest()
                raw_entry = cached_entries.get(identity)
                vector: Optional[tuple[float, ...]] = None
                if isinstance(raw_entry, Mapping) and raw_entry.get("fingerprint") == fingerprint:
                    try:
                        vector = self._normalize_vector(raw_entry.get("vector"))
                    except (TypeError, ValueError):
                        vector = None
                if vector is None:
                    missing_indexes.append(index)
                else:
                    result[index] = vector
                    new_entries[identity] = {
                        "fingerprint": fingerprint,
                        "vector": list(vector),
                    }

            if missing_indexes:
                missing_documents = tuple(documents[index] for index in missing_indexes)
                embedded = await self._embed_texts(provider, missing_documents)
                if len(embedded) != len(missing_indexes):
                    raise ValueError("embedding_count")
                normalized = tuple(self._normalize_vector(vector) for vector in embedded)
                dimensions = {len(vector) for vector in normalized}
                existing_dimensions = {
                    len(vector) for vector in result if vector is not None
                }
                if len(dimensions | existing_dimensions) != 1:
                    raise ValueError("embedding_dimension")
                for index, vector in zip(missing_indexes, normalized):
                    result[index] = vector
                    identity = self._identity_hash(records[index])
                    new_entries[identity] = {
                        "fingerprint": hashlib.sha256(
                            documents[index].encode("utf-8")
                        ).hexdigest(),
                        "vector": list(vector),
                    }

            finalized = tuple(vector for vector in result if vector is not None)
            if len(finalized) != len(records):
                raise ValueError("embedding_partial")
            dimensions = {len(vector) for vector in finalized}
            if len(dimensions) != 1:
                raise ValueError("embedding_dimension")
            self._save_cache(
                {
                    "schema": _CACHE_SCHEMA,
                    "provider_signature": signature,
                    "dimension": next(iter(dimensions), 0),
                    "entries": new_entries,
                }
            )
            return finalized

    async def _embed_texts(
        self,
        provider: Any,
        texts: tuple[str, ...],
    ) -> tuple[Any, ...]:
        results: list[Any] = []
        batch_method = getattr(provider, "get_embeddings", None)
        single_method = getattr(provider, "get_embedding", None)
        for offset in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = list(texts[offset : offset + _EMBED_BATCH_SIZE])
            if callable(batch_method):
                response = await batch_method(batch)
                if not isinstance(response, (list, tuple)):
                    raise ValueError("embedding_response")
                results.extend(response)
            elif callable(single_method):
                for text in batch:
                    results.append(await single_method(text))
            else:
                raise ValueError("embedding_provider")
        if len(results) != len(texts):
            raise ValueError("embedding_count")
        return tuple(results)

    async def _rerank(
        self,
        provider: Any,
        query: str,
        records: tuple[LoraRecord, ...],
    ) -> tuple[LoraRecord, ...]:
        documents = [self._search_document(record) for record in records]
        top_n = max(
            1,
            min(
                len(records),
                int(getattr(self._settings, "lora_rerank_top_n", 8)),
            ),
        )
        response = await provider.rerank(query, documents, top_n=top_n)
        raw_items = getattr(response, "results", response)
        if not isinstance(raw_items, (list, tuple)):
            raise ValueError("rerank_response")
        ranked_indexes: list[int] = []
        seen: set[int] = set()
        for item in raw_items:
            if isinstance(item, Mapping):
                index = item.get("index")
                score = item.get("relevance_score", item.get("score", 0.0))
            else:
                index = getattr(item, "index", None)
                score = getattr(item, "relevance_score", getattr(item, "score", 0.0))
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("rerank_index")
            if index < 0 or index >= len(records) or index in seen:
                raise ValueError("rerank_index")
            numeric_score = float(score)
            if not math.isfinite(numeric_score):
                raise ValueError("rerank_score")
            seen.add(index)
            ranked_indexes.append(index)
        if not ranked_indexes:
            raise ValueError("rerank_empty")
        ranked_indexes.extend(index for index in range(len(records)) if index not in seen)
        return tuple(records[index] for index in ranked_indexes)

    @classmethod
    def _exact_matches(
        cls,
        records: tuple[LoraRecord, ...],
        query: str,
    ) -> tuple[tuple[LoraRecord, ...], str]:
        canonical_query = canonical_lora_name(query).casefold()
        if canonical_query:
            path_matches = tuple(
                record
                for record in records
                if canonical_lora_name(record.name).casefold() == canonical_query
            )
            if path_matches:
                return path_matches, "path"

        identity_query = _normalized_identity(canonical_query or query)
        basename_matches: list[LoraRecord] = []
        alias_matches: list[LoraRecord] = []
        for record in records:
            name = canonical_lora_name(record.name)
            basename = name.rsplit("/", 1)[-1]
            stem = basename.rsplit(".", 1)[0]
            if identity_query and identity_query in {
                _normalized_identity(basename),
                _normalized_identity(stem),
            }:
                basename_matches.append(record)
                continue
            aliases = (
                record.character_name,
                record.source_work,
                *record.aliases,
            )
            if identity_query and any(
                _normalized_identity(value) == identity_query
                for value in aliases
                if value
            ):
                alias_matches.append(record)
        if basename_matches:
            return tuple(basename_matches), "basename"
        if alias_matches:
            return tuple(alias_matches), "alias"
        return (), ""

    @staticmethod
    def _stable_union(*groups: Iterable[LoraRecord]) -> tuple[LoraRecord, ...]:
        output: list[LoraRecord] = []
        seen: set[str] = set()
        for group in groups:
            for record in group:
                key = LoraHybridSearchService._record_key(record)
                if key in seen:
                    continue
                seen.add(key)
                output.append(record)
        return tuple(output)

    @staticmethod
    def _record_key(record: LoraRecord) -> str:
        return canonical_lora_name(record.name).casefold()

    @staticmethod
    def _identity_hash(record: LoraRecord) -> str:
        material = "\n".join(
            (canonical_lora_name(record.name).casefold(), str(record.sha256 or ""))
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _search_document(record: LoraRecord) -> str:
        fields = [
            canonical_lora_name(record.name),
            record.model_name,
            record.category,
            record.character_name,
            record.source_work,
            *record.aliases[:24],
            *record.trigger_words[:32],
            *record.tags[:32],
            re.sub(r"\s+", " ", record.description or "")[:1200],
        ]
        return "\n".join(value.strip() for value in fields if str(value).strip())[:5000]

    @staticmethod
    def _normalize_vector(raw: Any) -> tuple[float, ...]:
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError("embedding_vector")
        if len(raw) > _MAX_VECTOR_DIMENSION:
            raise ValueError("embedding_dimension")
        vector = tuple(float(value) for value in raw)
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding_non_finite")
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm <= 0.0:
            raise ValueError("embedding_zero")
        return tuple(value / norm for value in vector)

    @staticmethod
    def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right):
            raise ValueError("embedding_dimension")
        return sum(a * b for a, b in zip(left, right))

    def _load_cache(self, signature: str) -> dict[str, Any]:
        if self._cache_path is None or not self._cache_path.is_file():
            return {}
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("schema") != _CACHE_SCHEMA:
            return {}
        if payload.get("provider_signature") != signature:
            return {}
        return payload

    def _save_cache(self, payload: dict[str, Any]) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self._cache_path)
        except OSError:
            logger.warning("LoRA vector cache write failed: OSError")
