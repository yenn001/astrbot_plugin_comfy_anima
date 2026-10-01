from __future__ import annotations

import asyncio
import csv
import errno
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from typing import Any
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

from ..services.prompt_assets import (
    MAX_PAGE_SIZE,
    PromptAssetConflictError,
    PromptAssetLibrary,
    PromptAssetNotFoundError,
    PromptAssetValidationError,
    normalize_asset_text,
    stable_asset_id,
)
from ..services import prompt_assets as prompt_assets_module


def _subprocess_hold_prompt_asset_reader(
    database_path: str,
    ready: Any,
    release: Any,
) -> None:
    library = PromptAssetLibrary(database_path)
    with library._read_lock():
        connection = library._connect(read_only=True)
        try:
            connection.execute("SELECT COUNT(*) FROM assets").fetchone()
            ready.set()
            if not release.wait(3):
                raise TimeoutError("reader release was not signalled")
        finally:
            connection.close()


def _subprocess_replace_prompt_assets(
    database_path: str,
    payload: bytes,
    started: Any,
    completed: Any,
) -> None:
    library = PromptAssetLibrary(database_path)
    started.set()
    library.import_bytes(payload, mode="replace")
    completed.set()


class PromptAssetLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "external" / "prompt_assets.sqlite3"
        self.library = PromptAssetLibrary(self.path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    @staticmethod
    def payload(source: str = "fixture-v1") -> bytes:
        return json.dumps(
            {
                "dataset": source,
                "license": "fixture-only",
                "assets": [
                    {
                        "asset_type": "artist",
                        "source_id": "artist-7",
                        "name_zh": "画师甲",
                        "name_en": "Artist Alpha",
                        "aliases": ["Alpha", "A 画师"],
                        "tags": ["artist_alpha"],
                        "traits": ["soft lighting", "warm palette"],
                        "categories": ["illustration", "warm"],
                        "preview_url": "https://images.example/alpha.webp",
                        "provenance": {"record": "artist-7"},
                    },
                    {
                        "asset_type": "character",
                        "name_zh": "琪",
                        "name_en": "Kei",
                        "aliases": ["kei (blue archive)", "Key"],
                        "tags": ["kei_(blue_archive)", "white hair", "halo"],
                        "traits": ["white hair", "pink halo"],
                        "categories": ["Blue Archive", "student"],
                        "preview": "http://192.168.10.34:8188/view/kei.png",
                    },
                    {
                        "asset_type": "clothing",
                        "name_zh": "水手服",
                        "name_en": "Sailor uniform",
                        "tags": ["serafuku", "pleated skirt"],
                        "categories": ["school", "uniform"],
                    },
                    {
                        "asset_type": "background",
                        "name_en": "Rainy Tokyo street",
                        "tags": ["rain", "tokyo street", "night"],
                        "traits": ["wet pavement"],
                        "categories": ["city"],
                    },
                    {
                        "asset_type": "pose",
                        "name_zh": "仰视蹲姿",
                        "name_en": "Low-angle squat",
                        "aliases": ["worm's-eye squat"],
                        "tags": ["squatting", "from below"],
                        "categories": ["full body"],
                    },
                ],
            },
            ensure_ascii=False,
        ).encode()

    def test_normalization_and_stable_id(self) -> None:
        self.assertEqual(normalize_asset_text("  Ｋｅｉ__Student  "), "kei student")
        first = stable_asset_id("character", "Kei Student", "fixture")
        second = stable_asset_id("characters", "Ｋｅｉ__Student", "Fixture")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^pa_[0-9a-f]{32}$")

    def test_import_all_types_and_status(self) -> None:
        status = self.library.import_bytes(
            self.payload(), source="https://catalog.example/assets.json"
        )
        self.assertTrue(status["ready"])
        self.assertEqual(status["asset_count"], 5)
        self.assertEqual(status["custom_count"], 0)
        self.assertEqual(status["favorite_count"], 0)
        self.assertEqual(
            status["type_counts"],
            {
                "artist": 1,
                "background": 1,
                "character": 1,
                "clothing": 1,
                "pose": 1,
            },
        )
        self.assertRegex(
            status["last_import_source"],
            r"^remote-https:catalog\.example:[0-9a-f]{12}$",
        )
        self.assertRegex(status["revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(status["last_import_sha256"]), 64)
        self.assertEqual(status["last_import_count"], 5)

        artist = self.library.search(asset_type="artist")["items"][0]
        self.assertEqual(artist["name_zh"], "画师甲")
        self.assertEqual(artist["aliases"], ("Alpha", "A 画师"))
        self.assertEqual(artist["provenance"]["license"], "fixture-only")
        self.assertEqual(artist["provenance"]["source"], status["last_import_source"])
        self.assertNotIn("source_key", artist)
        self.assertNotIn("preview_url", artist)
        self.assertTrue(artist["preview_available"])
        self.assertRegex(artist["preview_key"], r"^pav_[0-9a-f]{32}$")
        self.assertFalse(artist["favorite"])
        database_bytes = self.path.read_bytes()
        self.assertNotIn(b"images.example", database_bytes)
        self.assertNotIn(b"width=512", database_bytes)

    def test_json_section_format_and_generic_chinese_name(self) -> None:
        payload = json.dumps(
            {
                "namespace": "sections",
                "artists": [{"name": "画师乙", "tags": "artist_beta"}],
                "characters": [{"name": "Roxy", "aliases": "洛琪希|Roxy"}],
                "clothes": [{"name": "连衣裙", "tag": "dress"}],
                "backgrounds": [{"name": "Beach", "tag": "beach"}],
                "poses": [{"name": "坐姿", "tag": "sitting"}],
            },
            ensure_ascii=False,
        ).encode()
        self.library.import_bytes(payload)
        self.assertEqual(self.library.status()["asset_count"], 5)
        artist = self.library.search(asset_type="artist")["items"][0]
        self.assertEqual(artist["name_zh"], "画师乙")
        self.assertEqual(artist["name_en"], "")

    def test_csv_import_lists_and_private_preview(self) -> None:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "asset_type",
                "name_en",
                "aliases",
                "tags",
                "traits",
                "categories",
                "preview_url",
                "provenance",
            ]
        )
        writer.writerow(
            [
                "pose",
                "Standing pose",
                "stand|upright",
                "standing;full body",
                '["balanced", "front view"]',
                "basic|solo",
                "http://127.0.0.1:8188/preview.png",
                '{"row":"csv-1"}',
            ]
        )
        status = self.library.import_bytes(
            buffer.getvalue().encode(), content_type="text/csv"
        )
        self.assertEqual(status["asset_count"], 1)
        item = self.library.search(query="upright")["items"][0]
        self.assertEqual(item["tags"], ("standing", "full body"))
        self.assertEqual(item["traits"], ("balanced", "front view"))
        self.assertEqual(item["provenance"], {"row": "csv-1"})

    def test_file_import_does_not_persist_absolute_path(self) -> None:
        secret_directory = Path(self.directory.name) / "private-user-directory"
        secret_directory.mkdir()
        source_file = secret_directory / "assets.json"
        source_file.write_bytes(self.payload())
        status = self.library.import_file(source_file)
        self.assertRegex(
            status["last_import_source"],
            r"^local-import:[0-9a-f]{20}$",
        )
        raw_database = self.path.read_bytes()
        self.assertNotIn(b"private-user-directory", raw_database)
        self.assertNotIn(b"assets.json", raw_database)
        item = self.library.search()["items"][0]
        self.assertEqual(item["provenance"]["source"], status["last_import_source"])

    def test_search_filter_pagination_favourite_and_sort(self) -> None:
        self.library.import_bytes(self.payload())
        result = self.library.search("white halo", asset_type="character")
        self.assertEqual(result["total"], 1)
        character = result["items"][0]

        self.library.set_favorite(character["asset_id"])
        filtered = self.library.search(
            asset_type="character",
            categories=["student", "missing-any-option"],
            traits=["white hair", "pink halo"],
            tags=["halo"],
            favorite_only=True,
            page=1,
            page_size=1,
        )
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["pages"], 1)
        self.assertTrue(filtered["items"][0]["favorite"])

        all_items = self.library.search(page=2, page_size=2, sort="name")
        self.assertEqual(all_items["total"], 5)
        self.assertEqual(all_items["page"], 2)
        self.assertEqual(all_items["pages"], 3)

        facets = self.library.facets(asset_type="character", favorite_only=True)
        self.assertEqual(facets["type_counts"]["character"], 1)
        self.assertIn({"value": "student", "count": 1}, facets["categories"])
        self.assertIn({"value": "white hair", "count": 1}, facets["traits"])

    def test_relevance_sort_has_deterministic_semantic_tiers(self) -> None:
        payload = json.dumps(
            [
                {"asset_type": "artist", "name_en": "Aurora"},
                {
                    "asset_type": "artist",
                    "name_en": "Alias Carrier",
                    "aliases": ["Aurora"],
                },
                {"asset_type": "artist", "name_en": "Aurora Bloom"},
                {"asset_type": "artist", "name_en": "The Aurora Muse"},
                {
                    "asset_type": "artist",
                    "name_en": "Tag Alpha",
                    "tags": ["Aurora"],
                },
                {
                    "asset_type": "artist",
                    "name_en": "Tag Beta",
                    "tags": ["Aurora"],
                },
                {
                    "asset_type": "artist",
                    "name_en": "Provenance Carrier",
                    "provenance": {"note": "Aurora reference board"},
                },
                {"asset_type": "artist", "name_en": "Neoaurora Study"},
            ]
        ).encode()
        self.library.import_bytes(payload)

        ranked = self.library.search("aurora", sort="relevance", page_size=20)
        self.assertEqual(
            [item["name_en"] for item in ranked["items"]],
            [
                "Aurora",
                "Alias Carrier",
                "Aurora Bloom",
                "The Aurora Muse",
                "Tag Alpha",
                "Tag Beta",
                "Provenance Carrier",
                "Neoaurora Study",
            ],
        )
        empty_relevance = self.library.search(sort="relevance", page_size=20)
        name_sorted = self.library.search(sort="name", page_size=20)
        self.assertEqual(
            [item["asset_id"] for item in empty_relevance["items"]],
            [item["asset_id"] for item in name_sorted["items"]],
        )

    def test_custom_crud_and_imported_assets_are_read_only(self) -> None:
        self.library.import_bytes(self.payload())
        custom = self.library.create_custom(
            {
                "asset_type": "clothing",
                "name_zh": "自定义外套",
                "name_en": "Custom coat",
                "tags": ["open coat", "long sleeves"],
                "categories": ["custom wardrobe"],
            }
        )
        identifier = custom["asset_id"]
        self.assertTrue(custom["is_custom"])
        self.assertEqual(custom["provenance"]["source"], "custom")
        self.assertEqual(self.library.status()["custom_count"], 1)

        updated = self.library.update_custom(
            identifier,
            {
                "name_zh": "自定义短外套",
                "aliases": ["短外套"],
                "preview_url": "https://images.example/custom.webp",
            },
        )
        self.assertEqual(updated["asset_id"], identifier)
        self.assertEqual(updated["name_zh"], "自定义短外套")
        self.assertEqual(updated["aliases"], ("短外套",))
        self.library.set_favorite(identifier)
        self.assertEqual(
            self.library.search(custom_only=True, favorite_only=True)["total"], 1
        )
        self.assertTrue(self.library.delete_custom(identifier))
        with self.assertRaises(PromptAssetNotFoundError):
            self.library.get(identifier)

        imported = self.library.search(asset_type="artist")["items"][0]
        with self.assertRaises(PromptAssetConflictError):
            self.library.update_custom(imported["asset_id"], {"name_en": "changed"})
        with self.assertRaises(PromptAssetConflictError):
            self.library.delete_custom(imported["asset_id"])

    def test_custom_only_database_is_created_atomically(self) -> None:
        self.assertFalse(self.path.exists())
        item = self.library.create_custom(
            {"asset_type": "background", "name_en": "Workshop"}
        )
        self.assertTrue(self.path.is_file())
        self.assertTrue(self.library.status()["ready"])
        self.assertEqual(self.library.get(item["asset_id"])["name_en"], "Workshop")
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
        finally:
            connection.close()

    def test_search_and_facets_repair_missing_assets_table(self) -> None:
        broken = Path(self.directory.name) / "broken_assets.sqlite3"
        connection = sqlite3.connect(broken)
        try:
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('schema_version', '1')"
            )
            connection.commit()
        finally:
            connection.close()
        library = PromptAssetLibrary(broken)
        search = library.search()
        self.assertEqual(search["items"], [])
        self.assertEqual(search["total"], 0)
        facets = library.facets()
        self.assertEqual(facets["categories"], [])
        self.assertEqual(facets["traits"], [])
        connection = sqlite3.connect(broken)
        try:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'assets'"
                ).fetchone()
            )
        finally:
            connection.close()

    def test_merge_replace_and_replace_source_preserve_custom_and_favourites(
        self,
    ) -> None:
        self.library.import_bytes(
            self.payload(), source="https://a.example/assets.json"
        )
        artist = self.library.search(asset_type="artist")["items"][0]
        self.library.set_favorite(artist["asset_id"])
        custom = self.library.create_custom(
            {"asset_type": "pose", "name_en": "My pose"}
        )

        extra = json.dumps([{"asset_type": "background", "name_en": "Studio"}]).encode()
        self.library.import_bytes(
            extra, source="https://b.example/assets.json", mode="merge"
        )
        self.assertEqual(self.library.status()["asset_count"], 7)

        replacement = json.dumps(
            [{"asset_type": "artist", "name_en": "Artist Replacement"}]
        ).encode()
        self.library.import_bytes(
            replacement,
            source="https://a.example/assets.json",
            mode="replace_source",
        )
        self.assertEqual(self.library.search(query="Artist Alpha")["total"], 0)
        self.assertEqual(self.library.search(query="Studio")["total"], 1)
        self.assertEqual(self.library.get(custom["asset_id"])["name_en"], "My pose")

        self.library.import_bytes(replacement, mode="replace")
        self.assertEqual(self.library.status()["asset_count"], 2)
        self.assertEqual(self.library.status()["custom_count"], 1)
        self.assertEqual(self.library.status()["favorite_count"], 0)

    def test_failed_import_preserves_snapshot_and_custom_data(self) -> None:
        before = self.library.import_bytes(self.payload())
        custom = self.library.create_custom(
            {"asset_type": "pose", "name_en": "Durable custom pose"}
        )
        before_sha = before["last_import_sha256"]
        with self.assertRaises(PromptAssetValidationError):
            self.library.import_bytes(
                b'{"assets":[{"asset_type":"unknown","name":"bad"}]}'
            )
        after = self.library.status()
        self.assertEqual(after["asset_count"], 6)
        self.assertEqual(after["last_import_sha256"], before_sha)
        self.assertEqual(
            self.library.get(custom["asset_id"])["name_en"],
            "Durable custom pose",
        )

    def test_duplicate_stable_id_is_rejected_atomically(self) -> None:
        self.library.import_bytes(self.payload())
        before = self.library.status()["last_import_sha256"]
        duplicate = json.dumps(
            {
                "assets": [
                    {"asset_type": "pose", "name_en": "Same"},
                    {"asset_type": "pose", "name_en": "same"},
                ]
            }
        ).encode()
        with self.assertRaises(PromptAssetConflictError):
            self.library.import_bytes(duplicate)
        self.assertEqual(self.library.status()["last_import_sha256"], before)

    def test_stable_identity_enrichment_and_source_id_upgrade_preserve_favorite(
        self,
    ) -> None:
        source = "https://catalog.example/characters.json"
        first = json.dumps(
            [{"asset_type": "character", "name_zh": "角色甲"}],
            ensure_ascii=False,
        ).encode()
        self.library.import_bytes(first, source=source)
        original = self.library.search()["items"][0]
        self.library.set_favorite(original["asset_id"])

        enriched = json.dumps(
            [
                {
                    "asset_type": "character",
                    "name_zh": "角色甲",
                    "name_en": "Character Alpha",
                }
            ],
            ensure_ascii=False,
        ).encode()
        self.library.import_bytes(enriched, source=source, mode="replace_source")
        enriched_item = self.library.search()["items"][0]
        self.assertEqual(enriched_item["asset_id"], original["asset_id"])
        self.assertTrue(enriched_item["favorite"])

        upgraded = json.dumps(
            [
                {
                    "source_id": "character-100",
                    "asset_type": "character",
                    "name_zh": "角色甲",
                    "name_en": "Character Alpha",
                }
            ],
            ensure_ascii=False,
        ).encode()
        self.library.import_bytes(upgraded, source=source, mode="replace_source")
        upgraded_item = self.library.search()["items"][0]
        self.assertNotEqual(upgraded_item["asset_id"], original["asset_id"])
        self.assertTrue(upgraded_item["favorite"])
        self.assertEqual(self.library.status()["favorite_count"], 1)

    def test_cross_source_explicit_id_cannot_take_over_favorite(self) -> None:
        asset_id = "pa_" + ("b" * 32)
        first = json.dumps(
            [{"asset_id": asset_id, "asset_type": "artist", "name_en": "A"}]
        ).encode()
        self.library.import_bytes(first, source="https://a.example/assets.json")
        self.library.set_favorite(asset_id)
        hostile = json.dumps(
            [{"asset_id": asset_id, "asset_type": "artist", "name_en": "B"}]
        ).encode()
        with self.assertRaises(PromptAssetConflictError):
            self.library.import_bytes(
                hostile, source="https://b.example/assets.json", mode="merge"
            )
        item = self.library.get(asset_id)
        self.assertEqual(item["name_en"], "A")
        self.assertTrue(item["favorite"])

    def test_duplicate_headers_bom_non_string_and_deep_json_are_rejected(self) -> None:
        bom_payload = (
            b"\xef\xbb\xbf"
            + json.dumps([{"asset_type": "pose", "name_en": "BOM pose"}]).encode()
        )
        self.library.import_bytes(bom_payload)
        before = self.library.status()["revision"]
        duplicate_json = b'{"assets":[],"assets":[]}'
        duplicate_csv = b"asset_type,name_en,name_en\npose,A,B\n"
        non_string = json.dumps(
            [{"asset_type": "pose", "name_en": {"nested": "bad"}}]
        ).encode()
        for payload in (duplicate_json, duplicate_csv, non_string):
            with (
                self.subTest(payload=payload[:24]),
                self.assertRaises(PromptAssetValidationError),
            ):
                self.library.import_bytes(payload)
        self.assertEqual(self.library.status()["revision"], before)
        with self.assertRaises(PromptAssetValidationError):
            self.library.search(page=2**63)

    def test_revision_is_same_snapshot_and_changes_on_crud(self) -> None:
        status = self.library.import_bytes(
            self.payload(), source="https://catalog.example/assets.json"
        )
        revision = status["revision"]
        self.assertRegex(revision, r"^[0-9a-f]{64}$")
        search = self.library.search()
        facets = self.library.facets()
        item = self.library.get(search["items"][0]["asset_id"])
        self.assertEqual(search["revision"], revision)
        self.assertEqual(facets["revision"], revision)
        self.assertEqual(item["revision"], revision)
        favorited = self.library.set_favorite(item["asset_id"])
        self.assertNotEqual(favorited["revision"], revision)
        self.assertEqual(self.library.search()["revision"], favorited["revision"])

    def test_explicit_asset_id_upgrade_preserves_weak_record_favorite(self) -> None:
        source = "named_catalog"
        initial = json.dumps([{"asset_type": "character", "name_en": "Alice"}]).encode()
        self.library.import_bytes(initial, source=source)
        old_item = self.library.search()["items"][0]
        self.library.set_favorite(old_item["asset_id"])
        explicit_id = "pa_" + ("c" * 32)
        upgraded = json.dumps(
            [
                {
                    "asset_id": explicit_id,
                    "asset_type": "character",
                    "name_en": "Alice",
                }
            ]
        ).encode()
        self.library.import_bytes(upgraded, source=source, mode="replace_source")
        item = self.library.search()["items"][0]
        self.assertEqual(item["asset_id"], explicit_id)
        self.assertTrue(item["favorite"])

    def test_clear_source_is_exact_atomic_and_preserves_custom_assets(self) -> None:
        local_payload = json.dumps(
            [
                {"asset_type": "pose", "name_en": "Local A"},
                {"asset_type": "pose", "name_en": "Local B"},
            ]
        ).encode()
        other_payload = json.dumps(
            [{"asset_type": "background", "name_en": "Other"}]
        ).encode()
        self.library.import_bytes(local_payload, source="astrbot_local_assets")
        local_item = self.library.search(query="Local A")["items"][0]
        self.library.set_favorite(local_item["asset_id"])
        self.library.import_bytes(other_payload, source="other_assets")
        custom = self.library.create_custom(
            {"asset_type": "pose", "name_en": "Custom local-like asset"}
        )

        result = self.library.clear_source("astrbot_local_assets")
        self.assertEqual(result["removed"], 2)
        self.assertRegex(result["revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.library.search(source="astrbot_local_assets")["total"], 0)
        with self.assertRaises(PromptAssetNotFoundError):
            self.library.get(local_item["asset_id"])
        self.assertEqual(self.library.search(query="Other")["total"], 1)
        self.assertEqual(
            self.library.get(custom["asset_id"])["name_en"],
            "Custom local-like asset",
        )
        self.assertEqual(self.library.status()["favorite_count"], 0)

        unchanged = self.library.clear_source("astrbot_local_assets")
        self.assertEqual(unchanged["removed"], 0)
        self.assertEqual(unchanged["revision"], result["revision"])
        for unsafe in (
            "C:\\private\\assets.json",
            "../assets.json",
            "https://host/x",
        ):
            with (
                self.subTest(unsafe=unsafe),
                self.assertRaises(PromptAssetValidationError),
            ):
                self.library.clear_source(unsafe)

    def test_alias_only_import_requires_explicit_stable_identity(self) -> None:
        with self.assertRaises(PromptAssetValidationError):
            self.library.import_bytes(
                json.dumps(
                    [{"asset_type": "character", "aliases": ["Alias only"]}]
                ).encode()
            )
        accepted = self.library.import_bytes(
            json.dumps(
                [
                    {
                        "source_id": "alias-1",
                        "asset_type": "character",
                        "aliases": ["Alias only"],
                    }
                ]
            ).encode(),
            source="named_source",
        )
        self.assertEqual(accepted["asset_count"], 1)

    def test_field_record_page_and_size_limits(self) -> None:
        too_long = "x" * 257
        with self.assertRaises(PromptAssetValidationError):
            self.library.import_bytes(
                json.dumps([{"asset_type": "artist", "name_en": too_long}]).encode()
            )
        with mock.patch.object(prompt_assets_module, "MAX_IMPORT_BYTES", 10):
            with self.assertRaises(PromptAssetValidationError):
                self.library.import_bytes(b"x" * 11)
        with self.assertRaises(PromptAssetValidationError):
            self.library.search(page_size=MAX_PAGE_SIZE + 1)
        with self.assertRaises(PromptAssetValidationError):
            self.library.search(page=0)
        with self.assertRaises(PromptAssetValidationError):
            self.library.search(query="x" * 257)

    def test_url_and_provenance_security_rules(self) -> None:
        cases = [
            "http://public.example/preview.png",
            "http://169.254.169.254/latest/meta-data",
            "https://user:pass@example/preview.png",
            "https://example/preview.png#fragment",
            "https://example/preview.png?token=secret",
            "https://example/preview.png?X-Amz-Signature=secret",
        ]
        for preview in cases:
            with (
                self.subTest(preview=preview),
                self.assertRaises(PromptAssetValidationError),
            ):
                self.library.import_bytes(
                    json.dumps(
                        [
                            {
                                "asset_type": "artist",
                                "name_en": "Unsafe",
                                "preview_url": preview,
                            }
                        ]
                    ).encode()
                )
        secret = "do-not-store-this-token"
        with self.assertRaises(PromptAssetValidationError) as raised:
            self.library.import_bytes(
                json.dumps(
                    [
                        {
                            "asset_type": "artist",
                            "name_en": "Unsafe",
                            "provenance": {"api_key": secret},
                        }
                    ]
                ).encode()
            )
        self.assertNotIn(secret, str(raised.exception))
        self.assertFalse(self.path.exists())

        forbidden_provenance = (
            {"credentials": "hidden"},
            {"nested": {"userCredentials": "hidden"}},
            {"note": "ghp_" + ("A" * 36)},
            {"note": "AKIA" + ("A" * 16)},
            {"note": "postgres://user:password@host/db"},
        )
        for provenance in forbidden_provenance:
            with (
                self.subTest(provenance=provenance),
                self.assertRaises(PromptAssetValidationError),
            ):
                self.library.import_bytes(
                    json.dumps(
                        [
                            {
                                "asset_type": "artist",
                                "name_en": "Unsafe",
                                "provenance": provenance,
                            }
                        ]
                    ).encode()
                )

        with self.assertRaises(PromptAssetValidationError):
            self.library.import_bytes(
                b'[{"asset_type":"artist","name_en":"NaN"}]',
                provenance={"score": float("nan")},
            )

    def test_embedded_credentials_are_rejected_without_echo_or_persistence(
        self,
    ) -> None:
        secrets = (
            ("name_en", "Portrait sk-" + ("A" * 24)),
            ("aliases", ["Authorization: Bearer abcdefghijklmnop"]),
            ("tags", ["api_key=do-not-store-this-token"]),
            ("source_id", "item;AWSAccessKeyId=" + "AKIA" + ("A" * 16)),
            (
                "provenance",
                {"note": "release token=do-not-store-this-token"},
            ),
            ("provenance", {"AWSAccessKeyId": "AKIA" + ("A" * 16)}),
        )
        for field, secret_value in secrets:
            payload = {
                "asset_type": "artist",
                "name_en": "Safe display name",
                field: secret_value,
            }
            secret_text = json.dumps(secret_value, ensure_ascii=False)
            with (
                self.subTest(field=field),
                self.assertRaises(PromptAssetValidationError) as raised,
            ):
                self.library.import_bytes(
                    json.dumps([payload], ensure_ascii=False).encode()
                )
            self.assertNotIn("do-not-store-this-token", str(raised.exception))
            self.assertNotIn("AKIA" + ("A" * 16), str(raised.exception))
            self.assertNotIn("sk-" + ("A" * 24), str(raised.exception))
            self.assertNotIn(secret_text, str(raised.exception))
        self.assertFalse(self.path.exists())

        safe = self.library.import_bytes(
            json.dumps(
                [
                    {
                        "asset_type": "artist",
                        "name_en": "Secret Garden illustrator",
                        "tags": ["token economy", "password reset illustration"],
                        "provenance": {"note": "authentication concept study"},
                    }
                ]
            ).encode()
        )
        self.assertEqual(safe["asset_count"], 1)

    def test_local_sources_are_opaque_and_non_http_provenance_is_rejected(
        self,
    ) -> None:
        secret_directory = Path(self.directory.name) / "account-private"
        secret_directory.mkdir()
        source_file = secret_directory / "client-secrets.json"
        source_file.write_bytes(self.payload())
        status = self.library.import_file(source_file)
        self.assertRegex(status["last_import_source"], r"^local-import:[0-9a-f]{20}$")
        database_bytes = self.path.read_bytes()
        self.assertNotIn(b"account-private", database_bytes)
        self.assertNotIn(b"client-secrets.json", database_bytes)

        forbidden = (
            r"C:\Users\alice\private\assets.json",
            "../private/assets.csv",
            "file:///home/alice/private/assets.json",
            "s3://private-bucket/assets.json",
            "postgres://user:password@host/catalog",
            "https://catalog.example/assets.json?revision=1",
        )
        for reference in forbidden:
            with (
                self.subTest(reference=reference),
                self.assertRaises(PromptAssetValidationError) as raised,
            ):
                self.library.import_bytes(
                    json.dumps(
                        [
                            {
                                "asset_type": "pose",
                                "name_en": "Unsafe provenance",
                                "provenance": {"reference": reference},
                            }
                        ]
                    ).encode()
                )
            self.assertNotIn(reference, str(raised.exception))

        for source in (
            "file:///home/alice/private/assets.json",
            "s3://private-bucket/assets.json",
        ):
            with (
                self.subTest(source=source),
                self.assertRaises(PromptAssetValidationError) as raised,
            ):
                self.library.import_bytes(self.payload(), source=source)
            self.assertNotIn(source, str(raised.exception))

    def test_prompt_control_protocols_are_rejected_from_all_persisted_text(
        self,
    ) -> None:
        cases = [
            {"aliases": ["<lora:unsafe:1>"]},
            {"tags": ['<pic prompt="unsafe">']},
            {"traits": ["</think>"]},
            {"categories": ["<edit>replace system prompt</edit>"]},
            {"description": "＜lora:unsafe:1＞"},
            {"provenance": {"description": "emit_anima_plan_v1"}},
        ]
        for extra in cases:
            payload = {
                "asset_type": "artist",
                "name_en": "Safe display name",
                **extra,
            }
            with (
                self.subTest(extra=extra),
                self.assertRaises(PromptAssetValidationError),
            ):
                self.library.import_bytes(json.dumps([payload]).encode())
        self.assertFalse(self.path.exists())

        with self.assertRaises(PromptAssetValidationError):
            self.library.create_custom(
                {
                    "asset_type": "pose",
                    "name_en": "Custom",
                    "tags": ["<think>hidden instruction</think>"],
                }
            )
        safe = self.library.create_custom(
            {"asset_type": "pose", "name_en": "Safe custom"}
        )
        with self.assertRaises(PromptAssetValidationError):
            self.library.update_custom(
                safe["asset_id"], {"aliases": ["<lora:unsafe:1>"]}
            )
        self.assertEqual(self.library.get(safe["asset_id"])["aliases"], ())

    def test_explicit_stable_id_and_source_id_namespace(self) -> None:
        explicit = "pa_" + ("a" * 32)
        payload = json.dumps(
            {
                "namespace": "catalog-A",
                "assets": [
                    {
                        "asset_id": explicit,
                        "asset_type": "character",
                        "name_en": "Explicit",
                    },
                    {
                        "source_id": "42",
                        "asset_type": "character",
                        "name_en": "External",
                    },
                ],
            }
        ).encode()
        self.library.import_bytes(payload)
        self.assertEqual(self.library.get(explicit)["name_en"], "Explicit")
        external = self.library.search(query="External")["items"][0]
        self.assertEqual(
            external["asset_id"], stable_asset_id("character", "42", "catalog-A")
        )

    def test_process_lock_is_reentrant_and_rejects_shared_upgrade(self) -> None:
        with prompt_assets_module._process_file_lock(self.path, shared=False):
            with prompt_assets_module._process_file_lock(self.path, shared=False):
                with prompt_assets_module._process_file_lock(self.path, shared=True):
                    pass
        with prompt_assets_module._process_file_lock(self.path, shared=True):
            with self.assertRaises(PromptAssetConflictError):
                with prompt_assets_module._process_file_lock(
                    self.path, shared=False, timeout=0
                ):
                    self.fail("shared-to-exclusive upgrade must be rejected")

    def test_process_lock_uses_nonblocking_modes_and_explicit_retry(self) -> None:
        if os.name == "nt":
            import msvcrt

            real_locking = msvcrt.locking
            calls: list[int] = []
            blocked_once = False

            def flaky_locking(handle: int, mode: int, length: int) -> None:
                nonlocal blocked_once
                calls.append(mode)
                if mode == msvcrt.LK_NBRLCK and not blocked_once:
                    blocked_once = True
                    raise OSError(errno.EACCES, "busy")
                real_locking(handle, mode, length)

            with (
                mock.patch.object(msvcrt, "locking", side_effect=flaky_locking),
                mock.patch.object(prompt_assets_module.time, "sleep") as sleeping,
            ):
                with prompt_assets_module._process_file_lock(
                    self.path, shared=True, timeout=0.5
                ):
                    pass
            self.assertGreaterEqual(calls.count(msvcrt.LK_NBRLCK), 2)
            self.assertEqual(calls[-1], msvcrt.LK_UNLCK)
            sleeping.assert_called()
            with mock.patch.object(msvcrt, "locking", wraps=real_locking) as locking:
                with prompt_assets_module._process_file_lock(
                    self.path, shared=False, timeout=0.5
                ):
                    pass
            self.assertEqual(locking.call_args_list[0].args[1], msvcrt.LK_NBLCK)
        else:
            import fcntl

            real_flock = fcntl.flock
            calls: list[int] = []
            blocked_once = False

            def flaky_flock(handle: int, mode: int) -> None:
                nonlocal blocked_once
                calls.append(mode)
                if mode & fcntl.LOCK_SH and not blocked_once:
                    blocked_once = True
                    raise BlockingIOError(errno.EAGAIN, "busy")
                real_flock(handle, mode)

            with (
                mock.patch.object(fcntl, "flock", side_effect=flaky_flock),
                mock.patch.object(prompt_assets_module.time, "sleep") as sleeping,
            ):
                with prompt_assets_module._process_file_lock(
                    self.path, shared=True, timeout=0.5
                ):
                    pass
            self.assertTrue(calls[0] & fcntl.LOCK_NB)
            self.assertTrue(calls[0] & fcntl.LOCK_SH)
            sleeping.assert_called()
            with mock.patch.object(fcntl, "flock", wraps=real_flock) as flock:
                with prompt_assets_module._process_file_lock(
                    self.path, shared=False, timeout=0.5
                ):
                    pass
            self.assertTrue(flock.call_args_list[0].args[1] & fcntl.LOCK_NB)
            self.assertTrue(flock.call_args_list[0].args[1] & fcntl.LOCK_EX)

    @unittest.skipUnless(os.name == "nt", "Windows sharing semantics regression")
    def test_windows_replace_retries_transient_reader_sharing_violation(self) -> None:
        source = Path(self.directory.name) / "replacement.sqlite3"
        target = Path(self.directory.name) / "target.sqlite3"
        source.write_bytes(b"new")
        target.write_bytes(b"old")
        real_replace = os.replace
        attempts = 0

        def flaky_replace(raw_source: Any, raw_target: Any) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise PermissionError(errno.EACCES, "sharing violation")
            real_replace(raw_source, raw_target)

        with (
            mock.patch.object(
                prompt_assets_module.os, "replace", side_effect=flaky_replace
            ),
            mock.patch.object(prompt_assets_module.time, "sleep") as sleeping,
        ):
            prompt_assets_module._replace_with_retry(source, target, timeout=0.5)
        self.assertEqual(attempts, 3)
        self.assertEqual(target.read_bytes(), b"new")
        sleeping.assert_called()

    @unittest.skipUnless(os.name == "nt", "Windows subprocess lock regression")
    def test_windows_subprocess_reader_blocks_snapshot_replace(self) -> None:
        self.library.import_bytes(self.payload())
        replacement = json.dumps(
            [{"asset_type": "pose", "name_en": "Replacement pose"}]
        ).encode()
        context = multiprocessing.get_context("spawn")
        reader_ready = context.Event()
        reader_release = context.Event()
        writer_started = context.Event()
        writer_completed = context.Event()
        reader = context.Process(
            target=_subprocess_hold_prompt_asset_reader,
            args=(str(self.path), reader_ready, reader_release),
        )
        writer = context.Process(
            target=_subprocess_replace_prompt_assets,
            args=(str(self.path), replacement, writer_started, writer_completed),
        )
        reader.start()
        try:
            self.assertTrue(reader_ready.wait(2.5))
            writer.start()
            self.assertTrue(writer_started.wait(2.5))
            self.assertFalse(writer_completed.wait(0.2))
            reader_release.set()
            self.assertTrue(writer_completed.wait(2.5))
        finally:
            reader_release.set()
            reader.join(2)
            writer.join(2)
            if reader.is_alive():
                reader.terminate()
                reader.join(1)
            if writer.is_alive():
                writer.terminate()
                writer.join(1)
        self.assertEqual(reader.exitcode, 0)
        self.assertEqual(writer.exitcode, 0)
        self.assertEqual(
            self.library.search()["items"][0]["name_en"], "Replacement pose"
        )

    def test_threaded_favourite_updates_are_serialized(self) -> None:
        self.library.import_bytes(self.payload())
        asset_id = self.library.search(asset_type="character")["items"][0]["asset_id"]
        failures: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                for iteration in range(10):
                    self.library.set_favorite(
                        asset_id, favorite=(index + iteration) % 2 == 0
                    )
            except BaseException as exc:  # pragma: no cover - diagnostic capture
                failures.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertIn(self.library.status()["favorite_count"], {0, 1})


class PromptAssetRemoteImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prompt_assets.sqlite3"
        self.library = PromptAssetLibrary(self.path)

    async def asyncTearDown(self) -> None:
        self.directory.cleanup()

    @staticmethod
    def remote_payload() -> bytes:
        return json.dumps(
            {
                "assets": [
                    {
                        "asset_type": "character",
                        "name_en": "Remote character",
                        "tags": ["remote_character"],
                    }
                ]
            }
        ).encode()

    async def test_private_http_remote_import_and_query_rejection(self) -> None:
        payload = self.remote_payload()
        hits = 0

        async def handler(_request: web.Request) -> web.Response:
            nonlocal hits
            hits += 1
            return web.Response(body=payload, content_type="application/json")

        app = web.Application()
        app.router.add_get("/assets.json", handler)
        async with TestServer(app) as server:
            url = str(server.make_url("/assets.json"))
            with self.assertRaises(PromptAssetValidationError):
                await self.library.update_from_url(url)
            with self.assertRaises(PromptAssetValidationError):
                await self.library.update_from_url(
                    f"{url}?revision=1", allow_private_http=True
                )
            status = await self.library.update_from_url(url, allow_private_http=True)
        self.assertEqual(status["asset_count"], 1)
        self.assertEqual(hits, 1)
        self.assertNotIn("?", status["last_import_source"])
        self.assertRegex(
            status["last_import_source"],
            r"^remote-http:127\.0\.0\.1:\d+:[0-9a-f]{12}$",
        )
        item = self.library.search()["items"][0]
        self.assertEqual(item["provenance"]["transport"], "http")

    async def test_remote_query_semicolon_and_signed_parameter_bypasses_rejected(
        self,
    ) -> None:
        secret = "AKIA" + ("A" * 16)
        urls = (
            "https://example.com/assets.json?revision=1",
            f"https://example.com/assets.json?ok=1;AWSAccessKeyId={secret}",
            "https://example.com/assets.json?X-Amz-Credential=hidden",
            "https://example.com/assets.json?x=1%3BAWSAccessKeyId%3Dhidden",
        )
        for url in urls:
            with (
                self.subTest(url=url),
                self.assertRaises(PromptAssetValidationError) as raised,
            ):
                await self.library.update_from_url(url)
            self.assertNotIn(secret, str(raised.exception))
        self.assertFalse(self.path.exists())

    async def test_public_https_rejects_ipv6_ssrf_tunnel_addresses(self) -> None:
        hosts = (
            "[fec0::1]",
            "[2002:7f00:1::]",
            "[2002:c0a8:101::]",
            "[2001:0:808:808:0:ffff:80ff:fffe]",
            "[::ffff:127.0.0.1]",
        )
        for host in hosts:
            with (
                self.subTest(host=host),
                self.assertRaises(PromptAssetValidationError),
            ):
                await self.library.update_from_url(
                    f"https://{host}/assets.json", timeout=1
                )
        self.assertFalse(self.path.exists())

    async def test_remote_redirect_is_rejected_without_following(self) -> None:
        followed = 0
        redirects = 0

        async def redirect(_request: web.Request) -> web.Response:
            nonlocal redirects
            redirects += 1
            raise web.HTTPFound("/target")

        async def target(_request: web.Request) -> web.Response:
            nonlocal followed
            followed += 1
            return web.Response(body=self.remote_payload())

        app = web.Application()
        app.router.add_get("/redirect", redirect)
        app.router.add_get("/target", target)
        async with TestServer(app) as server:
            with self.assertRaises(PromptAssetValidationError):
                await self.library.update_from_url(
                    str(server.make_url("/redirect")), allow_private_http=True
                )
        self.assertEqual(redirects, 1)
        self.assertEqual(followed, 0)
        self.assertFalse(self.path.exists())

    async def test_remote_content_length_limit_and_url_credentials(self) -> None:
        async def handler(_request: web.Request) -> web.Response:
            return web.Response(
                body=b"{}",
                headers={"Content-Length": "1000"},
                content_type="application/json",
            )

        app = web.Application()
        app.router.add_get("/large", handler)
        async with TestServer(app) as server:
            with self.assertRaises(PromptAssetValidationError):
                await self.library.update_from_url(
                    str(server.make_url("/large")),
                    max_bytes=10,
                    allow_private_http=True,
                )
        with self.assertRaises(PromptAssetValidationError):
            await self.library.update_from_url(
                "https://user:pass@example.com/assets.json"
            )
        with self.assertRaises(PromptAssetValidationError):
            await self.library.update_from_url(
                "https://example.com/assets.json#fragment"
            )

    async def test_cancelled_remote_import_does_not_create_snapshot(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(_request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse()
            await response.prepare(_request)
            started.set()
            await release.wait()
            return response

        app = web.Application()
        app.router.add_get("/slow", handler)
        async with TestServer(app) as server:
            task = asyncio.create_task(
                self.library.update_from_url(
                    str(server.make_url("/slow")), allow_private_http=True
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
