"""Tests for safe LoRA Embedding + Rerank hybrid retrieval.

The fresh ``records`` argument is deliberately treated as the authoritative
loadable set.  Provider output and the on-disk vector cache may change ranking,
but must never manufacture or resurrect a LoRA file.
"""

import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path

from ..services.lora_catalog import LoraCatalogService, LoraRecord
from ..services.lora_retrieval import LoraHybridSearchService


class FakeEmbeddingProvider:
    """Small AstrBot-compatible Embedding Provider test double."""

    def __init__(self, resolver, provider_id="embedding-1"):
        self.provider_config = {
            "id": provider_id,
            "name": "Local embedding",
            "embedding_model": "test-embedding",
            "key": "provider-secret-key",
            "api_base": "http://private-embedding.invalid/v1",
        }
        self._resolver = resolver
        self.calls = []

    def meta(self):
        return types.SimpleNamespace(
            id=self.provider_config["id"],
            model="test-embedding",
            type="embedding",
        )

    async def get_embeddings(self, texts):
        self.calls.append(tuple(texts))
        return [self._resolver(text) for text in texts]

    def get_dim(self):
        return 3


class FakeRerankProvider:
    """Small AstrBot-compatible Rerank Provider test double."""

    def __init__(self, handler, provider_id="rerank-1"):
        self.provider_config = {
            "id": provider_id,
            "name": "Local reranker",
            "rerank_model": "test-reranker",
            "key": "rerank-secret-key",
        }
        self._handler = handler
        self.calls = []

    def meta(self):
        return types.SimpleNamespace(
            id=self.provider_config["id"],
            model="test-reranker",
            type="rerank",
        )

    async def rerank(self, query, documents, top_n=None):
        self.calls.append((query, tuple(documents), top_n))
        return await self._handler(query, documents, top_n)


def make_settings(**overrides):
    values = {
        "enable_lora_hybrid_search": True,
        "lora_embedding_provider_id": "embedding-1",
        "lora_rerank_provider_id": "rerank-1",
        "lora_embedding_top_k": 20,
        "lora_rerank_top_n": 8,
        "lora_retrieval_timeout": 0.05,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def make_context(embedding=None, rerank=None):
    providers = tuple(provider for provider in (embedding, rerank) if provider)

    def get_provider_by_id(provider_id):
        for provider in providers:
            if provider.provider_config.get("id") == provider_id:
                return provider
        return None

    return types.SimpleNamespace(
        get_all_embedding_providers=lambda: [embedding] if embedding else [],
        get_provider_by_id=get_provider_by_id,
        provider_manager=types.SimpleNamespace(
            rerank_provider_insts=[rerank] if rerank else [],
        ),
    )


async def identity_rerank(_query, documents, top_n):
    return [
        types.SimpleNamespace(index=index, relevance_score=1.0 - index / 100)
        for index in range(min(len(documents), top_n or len(documents)))
    ]


class LoraHybridSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_full_path_exact_match_skips_both_providers(self):
        embedding = FakeEmbeddingProvider(lambda _text: [1.0, 0.0, 0.0])
        rerank = FakeRerankProvider(identity_rerank)
        records = (
            LoraRecord("characters/denia.safetensors", aliases=("Denia",)),
            LoraRecord("styles/denia-lighting.safetensors"),
        )

        with tempfile.TemporaryDirectory() as directory:
            service = LoraHybridSearchService(
                make_settings(),
                make_context(embedding, rerank),
                cache_path=Path(directory) / "vectors.json",
            )
            result = await service.search(
                records,
                "characters/denia.safetensors",
                limit=5,
            )

        self.assertEqual(result, (records[0],))
        self.assertEqual(embedding.calls, [])
        self.assertEqual(rerank.calls, [])

    async def test_embedding_recalls_semantic_match_outside_lexical_results(self):
        query = "scarlet swordswoman"

        def vectors(text):
            lowered = text.casefold()
            if lowered == query or "moon_blade" in lowered:
                return [1.0, 0.0, 0.0]
            if "pastel_landscape" in lowered:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        embedding = FakeEmbeddingProvider(vectors)
        records = (
            LoraRecord(
                "characters/moon_blade.safetensors",
                description="red-haired female warrior carrying a katana",
            ),
            LoraRecord(
                "styles/pastel_landscape.safetensors",
                description="soft scenery and watercolor backgrounds",
            ),
        )
        self.assertEqual(LoraCatalogService.search_records(records, query), ())

        with tempfile.TemporaryDirectory() as directory:
            service = LoraHybridSearchService(
                make_settings(lora_rerank_provider_id=""),
                make_context(embedding=embedding),
                cache_path=Path(directory) / "vectors.json",
            )
            result = await service.search(records, query, limit=1)

        self.assertEqual(result, (records[0],))
        self.assertTrue(embedding.calls)
        self.assertTrue(service.last_diagnostics.get("embedding_used"))

    async def test_rerank_reorders_the_non_exact_candidate_pool(self):
        embedding = FakeEmbeddingProvider(lambda _text: [1.0, 0.0, 0.0])

        async def prefer_style_c(_query, documents, _top_n):
            preferred = next(
                index
                for index, document in enumerate(documents)
                if "style_c" in document.casefold()
            )
            remaining = [index for index in range(len(documents)) if index != preferred]
            return [
                types.SimpleNamespace(index=preferred, relevance_score=0.99),
                *(
                    types.SimpleNamespace(
                        index=index,
                        relevance_score=0.5 - offset / 100,
                    )
                    for offset, index in enumerate(remaining)
                ),
            ]

        rerank = FakeRerankProvider(prefer_style_c)
        records = (
            LoraRecord("styles/style_a.safetensors", tags=("portrait",)),
            LoraRecord("styles/style_b.safetensors", tags=("portrait",)),
            LoraRecord("styles/style_c.safetensors", tags=("portrait",)),
        )

        with tempfile.TemporaryDirectory() as directory:
            service = LoraHybridSearchService(
                make_settings(),
                make_context(embedding, rerank),
                cache_path=Path(directory) / "vectors.json",
            )
            result = await service.search(records, "portrait illustration", limit=3)

        self.assertEqual(result[0], records[2])
        self.assertEqual(len(rerank.calls), 1)
        self.assertTrue(service.last_diagnostics.get("rerank_used"))

    async def test_invalid_embedding_response_falls_back_to_lexical_ranking(self):
        query = "denia portrait"

        class InvalidEmbeddingProvider(FakeEmbeddingProvider):
            async def get_embeddings(self, texts):
                self.calls.append(tuple(texts))
                return [[1.0, 0.0, 0.0]] if len(texts) > 1 else []

        embedding = InvalidEmbeddingProvider(lambda _text: [1.0, 0.0, 0.0])
        records = (
            LoraRecord(
                "characters/denia.safetensors",
                aliases=("denia hero",),
                tags=("portrait",),
            ),
            LoraRecord("styles/denia_palette.safetensors", tags=("portrait",)),
            LoraRecord("styles/unrelated.safetensors"),
        )
        expected = LoraCatalogService.search_records(records, query)[:2]

        with tempfile.TemporaryDirectory() as directory:
            service = LoraHybridSearchService(
                make_settings(lora_rerank_provider_id=""),
                make_context(embedding=embedding),
                cache_path=Path(directory) / "vectors.json",
            )
            result = await service.search(records, query, limit=2)

        self.assertEqual(result, expected)
        self.assertFalse(service.last_diagnostics.get("embedding_used"))
        self.assertTrue(service.last_diagnostics.get("fallback_code"))

    async def test_rerank_timeout_falls_back_without_blocking_search(self):
        embedding = FakeEmbeddingProvider(lambda _text: [1.0, 0.0, 0.0])
        never_finishes = asyncio.Event()

        async def timeout(_query, _documents, _top_n):
            await never_finishes.wait()
            return []

        rerank = FakeRerankProvider(timeout)
        records = (
            LoraRecord("styles/portrait_a.safetensors", tags=("portrait",)),
            LoraRecord("styles/portrait_b.safetensors", tags=("portrait",)),
        )

        with tempfile.TemporaryDirectory() as directory:
            service = LoraHybridSearchService(
                make_settings(),
                make_context(embedding, rerank),
                cache_path=Path(directory) / "vectors.json",
            )
            result = await asyncio.wait_for(
                service.search(records, "portrait", limit=2),
                timeout=0.5,
            )

        self.assertEqual(set(result), set(records))
        self.assertEqual(len(result), 2)
        self.assertFalse(service.last_diagnostics.get("rerank_used"))
        self.assertTrue(service.last_diagnostics.get("fallback_code"))

    async def test_deleted_cached_record_cannot_be_resurrected(self):
        query = "forgotten oracle"

        def vectors(text):
            lowered = text.casefold()
            if lowered == query or "deleted_oracle" in lowered:
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0]

        embedding = FakeEmbeddingProvider(vectors)
        current = LoraRecord("characters/current_hero.safetensors")
        deleted = LoraRecord(
            "characters/deleted_oracle.safetensors",
            description="forgotten oracle with a golden crown",
        )

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vectors.json"
            first_service = LoraHybridSearchService(
                make_settings(lora_rerank_provider_id=""),
                make_context(embedding=embedding),
                cache_path=cache_path,
            )
            first = await first_service.search((current, deleted), query, limit=2)
            self.assertIn(deleted, first)

            # A fresh service simulates a later request after Manager + ComfyUI
            # have refreshed the loadable set while the old cache still exists.
            second_service = LoraHybridSearchService(
                make_settings(lora_rerank_provider_id=""),
                make_context(embedding=embedding),
                cache_path=cache_path,
            )
            second = await second_service.search((current,), query, limit=5)

            cache_text = cache_path.read_text(encoding="utf-8")

        self.assertNotIn(deleted, second)
        self.assertTrue(all(record in (current,) for record in second))
        self.assertNotIn("deleted_oracle", cache_text)

    async def test_persistent_cache_contains_no_source_or_secret_text(self):
        query = "PRIVATE QUERY scarlet oracle"
        record = LoraRecord(
            "characters/private_oracle.safetensors",
            trigger_words=("PRIVATE TRIGGER WORD",),
            description="PRIVATE CIVITAI DESCRIPTION",
            file_path=r"D:\\ComfyUI\\models\\loras\\private_oracle.safetensors",
            preview_url="http://192.168.10.34:8188/private-preview.jpg",
            aliases=("PRIVATE MANUAL ALIAS",),
        )

        def vectors(text):
            if text.casefold() == query.casefold() or "private_oracle" in text.casefold():
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0]

        embedding = FakeEmbeddingProvider(vectors)

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "vectors.json"
            service = LoraHybridSearchService(
                make_settings(lora_rerank_provider_id=""),
                make_context(embedding=embedding),
                cache_path=cache_path,
            )
            await service.search((record,), query, limit=5)

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload, ensure_ascii=False)

        forbidden = (
            query,
            record.name,
            record.description,
            record.trigger_words[0],
            record.aliases[0],
            record.file_path,
            record.preview_url,
            embedding.provider_config["key"],
            embedding.provider_config["api_base"],
        )
        for secret in forbidden:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
