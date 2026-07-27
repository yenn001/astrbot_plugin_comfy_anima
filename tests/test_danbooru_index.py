from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

from ..services.danbooru_index import (
    DanbooruIndexError,
    DanbooruTagIndex,
    escape_prompt_tag,
    normalize_tag,
)
from ..services import danbooru_index as danbooru_index_module


class DanbooruTagIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "tags.sqlite3"
        self.index = DanbooruTagIndex(self.path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    @staticmethod
    def payload() -> bytes:
        return json.dumps(
            {
                "source": "unit fixture",
                "license": "fixture-only",
                "revision": "r1",
                "tags": [
                    {
                        "tag": "kei_(blue_archive)",
                        "category": "character",
                        "aliases": ["kei_(student)_(blue_archive)", "Kei Student"],
                        "count": 123,
                        "provenance": {"record": "fixture-1"},
                    },
                    {
                        "tag": "roxy_migurdia",
                        "category": "character",
                        "aliases": ["roxy"],
                        "post_count": 456,
                    },
                    {
                        "tag": "artist's_style",
                        "category": "artist",
                        "aliases": ["artist’s style"],
                        "count": 5,
                    },
                ],
            },
            ensure_ascii=False,
        ).encode()

    def test_normalization_handles_nfkc_spacing_parentheses_and_apostrophes(
        self,
    ) -> None:
        self.assertEqual(
            normalize_tag(r"Ｋｅｉ  \(Blue   Archive\)"),
            "kei_(blue_archive)",
        )
        self.assertEqual(normalize_tag("Artist’s Style"), "artist's_style")
        self.assertEqual(
            escape_prompt_tag("kei_(blue_archive)"), r"kei_\(blue_archive\)"
        )

    def test_json_import_exact_canonical_and_alias_are_verified(self) -> None:
        status = self.index.import_bytes(
            self.payload(), source="memory://fixture", content_type="application/json"
        )
        self.assertTrue(status["ready"])
        self.assertEqual(status["tag_count"], 3)
        # The curly-apostrophe spelling normalizes to its canonical tag and is
        # intentionally not stored as a redundant alias.
        self.assertEqual(status["alias_count"], 3)
        self.assertEqual(status["revision"], "r1")
        self.assertEqual(status["source"], "memory://fixture")
        self.assertEqual(status["license"], "fixture-only")
        self.assertEqual(len(status["sha256"]), 64)
        self.assertEqual(status["category_counts"], {"artist": 1, "character": 2})
        self.assertEqual(status["provenance_counts"], {"memory://fixture": 3})

        canonical = self.index.lookup(r"Kei \(Blue Archive\)", "character")
        self.assertTrue(canonical.verified)
        self.assertEqual(canonical.match_type, "canonical")
        self.assertEqual(canonical.tag, "kei_(blue_archive)")
        self.assertEqual(canonical.count, 123)
        self.assertEqual(canonical.provenance["record"], "fixture-1")

        alias = self.index.lookup("ROXY", "character")
        self.assertTrue(alias.verified)
        self.assertEqual(alias.match_type, "alias")
        self.assertEqual(alias.canonical_tag, "roxy_migurdia")
        self.assertEqual(alias.aliases, ("roxy",))

        apostrophe = self.index.lookup("artist`s style")
        self.assertTrue(apostrophe.verified)
        self.assertEqual(apostrophe.tag, "artist's_style")

    def test_prefix_and_fuzzy_matches_are_candidates_never_verified(self) -> None:
        self.index.import_bytes(self.payload(), content_type="json")
        prefix = self.index.lookup("roxy_m")
        self.assertFalse(prefix.verified)
        self.assertEqual(prefix.match_type, "prefix")
        self.assertEqual(prefix.tag, "roxy_migurdia")
        self.assertTrue(prefix.candidates)
        self.assertTrue(all(not item.verified for item in prefix.candidates))

        fuzzy = self.index.lookup("roxy_migurdai")
        self.assertFalse(fuzzy.verified)
        self.assertEqual(fuzzy.match_type, "fuzzy")
        self.assertEqual(fuzzy.tag, "roxy_migurdia")

    def test_explicit_search_modes_keep_discovery_separate_from_verification(
        self,
    ) -> None:
        self.index.import_bytes(self.payload(), content_type="json")

        exact_alias = self.index.search("Kei Student", mode="exact")
        self.assertEqual(len(exact_alias), 1)
        self.assertTrue(exact_alias[0].verified)
        self.assertEqual(exact_alias[0].match_type, "alias")
        self.assertEqual(exact_alias[0].canonical_tag, "kei_(blue_archive)")

        prefix = self.index.search("roxy_m", mode="prefix")
        self.assertEqual([item.canonical_tag for item in prefix], ["roxy_migurdia"])
        self.assertTrue(all(not item.verified for item in prefix))
        self.assertTrue(all("prefix" in item.match_type for item in prefix))
        self.assertEqual(
            self.index.search("roxy_migurdai", mode="prefix"),
            (),
            "prefix mode must never silently add fuzzy candidates",
        )

        canonical_keyword = self.index.search("blue archive", mode="keyword")
        self.assertEqual(canonical_keyword[0].canonical_tag, "kei_(blue_archive)")
        self.assertEqual(canonical_keyword[0].match_type, "keyword")
        self.assertFalse(canonical_keyword[0].verified)

        alias_keyword = self.index.search("student", mode="keyword")
        self.assertEqual(alias_keyword[0].canonical_tag, "kei_(blue_archive)")
        self.assertEqual(alias_keyword[0].match_type, "alias_keyword")
        self.assertFalse(alias_keyword[0].verified)

    def test_batch_lookup_is_exact_alias_only_and_preserves_order(self) -> None:
        self.index.import_bytes(self.payload(), content_type="json")
        results = self.index.lookup_many(
            ("roxy", "missing", r"kei \(blue archive\)", "roxy"),
            "character",
        )

        self.assertEqual([item.query for item in results], [
            "roxy",
            "missing",
            r"kei \(blue archive\)",
            "roxy",
        ])
        self.assertTrue(results[0].verified)
        self.assertFalse(results[1].found)
        self.assertTrue(results[2].verified)
        self.assertTrue(results[3].verified)

    def test_prefix_and_keyword_treat_sql_wildcards_as_literal_text(self) -> None:
        payload = json.dumps(
            [
                {"tag": "literal%tag", "count": 20},
                {"tag": "literalxtag", "count": 10},
                {"tag": "under_score", "count": 5},
            ]
        ).encode()
        self.index.import_bytes(payload)

        self.assertEqual(
            [item.canonical_tag for item in self.index.search("literal%", mode="prefix")],
            ["literal%tag"],
        )
        self.assertEqual(
            [item.canonical_tag for item in self.index.search("%tag", mode="keyword")],
            ["literal%tag"],
        )

    def test_category_filter_and_missing_database(self) -> None:
        missing = self.index.lookup("roxy")
        self.assertFalse(missing.found)
        self.assertFalse(self.index.status()["ready"])
        self.index.import_bytes(self.payload())
        mismatch = self.index.lookup("roxy", "artist")
        self.assertFalse(mismatch.verified)
        self.assertFalse(mismatch.found)

    def test_numeric_danbooru_categories_match_semantic_filter_names(self) -> None:
        payload = json.dumps(
            [{"tag": "numeric_character", "category": 4, "aliases": ["nc"]}]
        ).encode()
        self.index.import_bytes(payload)
        self.assertTrue(self.index.lookup("nc", "character").verified)
        self.assertTrue(self.index.lookup("nc", "4").verified)
        self.assertEqual(self.index.status()["category_counts"], {"character": 1})

    def test_csv_import_and_file_import(self) -> None:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["name", "category", "aliases", "post_count", "provenance"])
        writer.writerow(
            [
                "test_(series)",
                "copyright",
                "test series|test franchise",
                "1,234",
                '{"row":"csv"}',
            ]
        )
        csv_path = Path(self.directory.name) / "tags.csv"
        csv_path.write_text(buffer.getvalue(), encoding="utf-8")
        status = self.index.import_file(
            csv_path,
            provenance={"license": "local-test"},
        )
        self.assertEqual(status["tag_count"], 1)
        self.assertEqual(status["license"], "local-test")
        result = self.index.lookup("test franchise")
        self.assertTrue(result.verified)
        self.assertEqual(result.count, 1234)
        self.assertEqual(result.provenance["row"], "csv")

    def test_headerless_danbooru_csv_import(self) -> None:
        payload = (
            'one_girl,0,123,"sole_female,1girl"\n'
            'kei_(blue_archive),4,456,"kei_(student)_(blue_archive)"\n'
            'long_alias_tag,0,1,"' + ("x" * 300) + '"\n'
            'shared_alias,0,2,"shared"\n'
            'shared,0,3,\n'
        ).encode()
        status = self.index.import_bytes(
            payload,
            source="https://catalog.example/anima.csv",
            content_type="text/csv",
        )
        self.assertEqual(status["tag_count"], 5)
        self.assertEqual(status["category_counts"], {"character": 1, "general": 4})
        result = self.index.lookup("kei_(student)_(blue_archive)", "character")
        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "kei_(blue_archive)")
        self.assertEqual(result.count, 456)
        self.assertTrue(self.index.lookup("long_alias_tag").verified)
        self.assertFalse(self.index.lookup("x" * 300).found)
        self.assertTrue(self.index.lookup("shared").verified)
        self.assertEqual(self.index.lookup("shared").canonical_tag, "shared")

    def test_failed_import_preserves_old_snapshot(self) -> None:
        before = self.index.import_bytes(self.payload())
        before_sha = before["sha256"]
        with self.assertRaises(DanbooruIndexError):
            self.index.import_bytes(b'{"tags":[{"tag":"broken","count":"no"}]}')
        after = self.index.status()
        self.assertTrue(after["ready"])
        self.assertEqual(after["sha256"], before_sha)
        self.assertIn("invalid tag count", after["error"])
        self.assertTrue(self.index.lookup("roxy").verified)

    def test_remote_record_cannot_spoof_source_and_count_error_is_redacted(
        self,
    ) -> None:
        payload = {
            "source": "reviewed dataset",
            "license": "fixture-only",
            "tags": [
                {
                    "tag": "safe_tag",
                    "count": 1,
                    "provenance": {
                        "source": "spoofed source",
                        "license": "spoofed licence",
                        "record": "kept evidence",
                    },
                }
            ],
        }
        self.index.import_bytes(
            json.dumps(payload).encode(),
            source="https://catalog.example/tags.json",
            provenance={"transport": "https"},
        )
        provenance = self.index.lookup("safe_tag").provenance
        self.assertEqual(provenance["source"], "https://catalog.example/tags.json")
        self.assertEqual(provenance["license"], "fixture-only")
        self.assertEqual(provenance["transport"], "https")
        self.assertEqual(provenance["record"], "kept evidence")

        secret = "private-token-" + ("9" * 100)
        with self.assertRaises(DanbooruIndexError) as raised:
            self.index.import_bytes(
                json.dumps({"tags": [{"tag": "bad", "count": secret}]}).encode()
            )
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, self.index.status()["error"])

    def test_duplicate_alias_or_canonical_conflict_is_atomic(self) -> None:
        self.index.import_bytes(self.payload())
        conflicting = json.dumps(
            [
                {"tag": "one", "aliases": ["same"]},
                {"tag": "two", "aliases": ["same"]},
            ]
        ).encode()
        with self.assertRaises(DanbooruIndexError):
            self.index.import_bytes(conflicting)
        self.assertTrue(self.index.lookup("roxy").verified)

    def test_parallel_reads_during_replacements_are_safe(self) -> None:
        self.index.import_bytes(self.payload())
        errors: list[BaseException] = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                try:
                    result = self.index.lookup("roxy")
                    if not result.verified:
                        raise AssertionError("reader observed an incomplete snapshot")
                except BaseException as exc:  # pragma: no cover - assertion capture
                    errors.append(exc)
                    stop.set()

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for revision in range(4):
                payload = json.loads(self.payload())
                payload["revision"] = str(revision)
                self.index.import_bytes(json.dumps(payload).encode())
        finally:
            stop.set()
            thread.join(timeout=2)
        self.assertFalse(errors)

    def test_import_limits_reject_oversized_records_and_stale_updates(self) -> None:
        too_many_aliases = {
            "tags": [
                {
                    "tag": "limited_tag",
                    "aliases": [f"alias_{index}" for index in range(65)],
                }
            ]
        }
        with self.assertRaisesRegex(DanbooruIndexError, "too many aliases"):
            self.index.import_bytes(json.dumps(too_many_aliases).encode())

        with mock.patch.object(danbooru_index_module, "MAX_INDEX_RECORDS", 1):
            with self.assertRaisesRegex(DanbooruIndexError, "too many records"):
                self.index.import_bytes(
                    json.dumps({"tags": [{"tag": "one"}, {"tag": "two"}]}).encode()
                )

        original = self.index.import_bytes(self.payload())
        generation = self.index._begin_update()
        self.index._invalidate_update(generation)
        replacement = json.loads(self.payload())
        replacement["revision"] = "stale"
        with self.assertRaisesRegex(DanbooruIndexError, "stale"):
            self.index.import_bytes(
                json.dumps(replacement).encode(),
                _expected_generation=generation,
            )
        self.assertEqual(self.index.status()["sha256"], original["sha256"])

    def test_slow_snapshot_build_does_not_block_existing_readers(self) -> None:
        self.index.import_bytes(self.payload())
        original_builder = self.index._build_database
        started = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def slow_builder(*args, **kwargs) -> None:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test did not release snapshot builder")
            original_builder(*args, **kwargs)

        def writer() -> None:
            try:
                replacement = json.loads(self.payload())
                replacement["revision"] = "next"
                self.index.import_bytes(json.dumps(replacement).encode())
            except BaseException as exc:  # pragma: no cover - assertion capture
                errors.append(exc)

        with mock.patch.object(self.index, "_build_database", side_effect=slow_builder):
            thread = threading.Thread(target=writer)
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            before = time.monotonic()
            self.assertTrue(self.index.lookup("roxy").verified)
            self.assertLess(time.monotonic() - before, 0.25)
            release.set()
            thread.join(timeout=2)

        self.assertFalse(errors)


class DanbooruTagIndexUrlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.index = DanbooruTagIndex(Path(self.directory.name) / "tags.sqlite3")

    async def asyncTearDown(self) -> None:
        self.directory.cleanup()

    async def test_private_http_update_and_oversize_failure(self) -> None:
        fixture = DanbooruTagIndexTests.payload()

        async def valid(_request: web.Request) -> web.Response:
            return web.Response(body=fixture, content_type="application/json")

        async def large(_request: web.Request) -> web.Response:
            return web.Response(body=b"x" * 2048, content_type="text/csv")

        app = web.Application()
        app.router.add_get("/tags.json", valid)
        app.router.add_get("/large.csv", large)
        async with TestServer(app) as server:
            status = await self.index.update_from_url(
                str(server.make_url("/tags.json?token=private-value"))
            )
            self.assertTrue(status["ready"])
            self.assertNotIn("token", status["source"])
            self.assertNotIn("private-value", status["source"])
            old_sha = status["sha256"]
            with self.assertRaises(DanbooruIndexError):
                await self.index.update_from_url(
                    str(server.make_url("/large.csv")), max_bytes=128
                )
            self.assertEqual(self.index.status()["sha256"], old_sha)

    async def test_rejects_public_plain_http_and_credentials(self) -> None:
        with self.assertRaises(DanbooruIndexError):
            await self.index.update_from_url("http://8.8.8.8/tags.json")
        with self.assertRaises(DanbooruIndexError):
            await self.index.update_from_url("https://user:pass@example.com/tags.json")
        with self.assertRaises(DanbooruIndexError):
            await self.index.update_from_url("https://169.254.169.254/tags.json")
        with self.assertRaises(DanbooruIndexError):
            await self.index.update_from_url("https://example.com/tags.json#secret")

    async def test_timeout_does_not_replace_snapshot(self) -> None:
        self.index.import_bytes(DanbooruTagIndexTests.payload())
        old_sha = self.index.status()["sha256"]

        async def slow(_request: web.Request) -> web.Response:
            await asyncio.sleep(0.1)
            return web.Response(body=b"[]", content_type="application/json")

        app = web.Application()
        app.router.add_get("/slow", slow)
        async with TestServer(app) as server:
            with self.assertRaises(DanbooruIndexError):
                await self.index.update_from_url(
                    str(server.make_url("/slow")), timeout=0.01
                )
        self.assertEqual(self.index.status()["sha256"], old_sha)


if __name__ == "__main__":
    unittest.main()
