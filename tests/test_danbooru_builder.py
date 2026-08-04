from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer

from ..services.danbooru_builder import (
    DanbooruApiBuilder,
    DanbooruBuildError,
    DanbooruBuildOptions,
)
from ..services.danbooru_index import DanbooruTagIndex


class _FakeDanbooruApi:
    def __init__(self) -> None:
        self.tags = [
            {
                "id": 10,
                "name": "useful_general",
                "category": 0,
                "post_count": 25,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:00Z",
            },
            {
                "id": 11,
                "name": "low_count_general",
                "category": 0,
                "post_count": 2,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:01Z",
            },
            {
                "id": 20,
                "name": "fixture_artist",
                "category": 1,
                "post_count": 40,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:02Z",
            },
            {
                "id": 30,
                "name": "bang_dream!",
                "category": 3,
                "post_count": 500,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:03Z",
            },
            {
                "id": 40,
                "name": "viola_(bang_dream!)",
                "category": 4,
                "post_count": 80,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:04Z",
            },
            {
                "id": 41,
                "name": "kei_(blue_archive)",
                "category": 4,
                "post_count": 120,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:05Z",
            },
            {
                "id": 50,
                "name": "useful_meta",
                "category": 5,
                "post_count": 20,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:06Z",
            },
            {
                "id": 51,
                "name": "low_count_meta",
                "category": 5,
                "post_count": 1,
                "is_deprecated": False,
                "updated_at": "2026-08-01T00:00:07Z",
            },
        ]
        self.aliases = [
            {
                "id": 100,
                "antecedent_name": "viola_old_name",
                "consequent_name": "viola_(bang_dream!)",
                "status": "active",
                "updated_at": "2026-08-01T01:00:00Z",
            },
            {
                "id": 101,
                "antecedent_name": "shared_character_name",
                "consequent_name": "viola_(bang_dream!)",
                "status": "active",
                "updated_at": "2026-08-01T01:00:01Z",
            },
            {
                "id": 102,
                "antecedent_name": "shared_character_name",
                "consequent_name": "kei_(blue_archive)",
                "status": "active",
                "updated_at": "2026-08-01T01:00:02Z",
            },
            {
                "id": 103,
                "antecedent_name": "retired_viola_name",
                "consequent_name": "viola_(bang_dream!)",
                "status": "retired",
                "updated_at": "2026-08-01T01:00:03Z",
            },
            {
                "id": 104,
                "antecedent_name": "viola_legacy",
                "consequent_name": "viola_intermediate",
                "status": "active",
                "updated_at": "2026-08-01T01:00:04Z",
            },
            {
                "id": 105,
                "antecedent_name": "viola_intermediate",
                "consequent_name": "viola_(bang_dream!)",
                "status": "active",
                "updated_at": "2026-08-01T01:00:05Z",
            },
            {
                "id": 106,
                "antecedent_name": "cycle_a",
                "consequent_name": "cycle_b",
                "status": "active",
                "updated_at": "2026-08-01T01:00:06Z",
            },
            {
                "id": 107,
                "antecedent_name": "cycle_b",
                "consequent_name": "cycle_a",
                "status": "active",
                "updated_at": "2026-08-01T01:00:07Z",
            },
            {
                "id": 108,
                "antecedent_name": "branch_identity",
                "consequent_name": "viola_intermediate",
                "status": "active",
                "updated_at": "2026-08-01T01:00:08Z",
            },
            {
                "id": 109,
                "antecedent_name": "branch_identity",
                "consequent_name": "kei_(blue_archive)",
                "status": "active",
                "updated_at": "2026-08-01T01:00:09Z",
            },
        ]
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.rate_limit_once = False
        self.rate_limit_hits = 0

    async def tags_handler(self, request: web.Request) -> web.Response:
        params = dict(request.query)
        self.requests.append(("tags", params))
        if self.rate_limit_once and self.rate_limit_hits == 0:
            self.rate_limit_hits += 1
            return web.json_response(
                {"error": "slow down"},
                status=429,
                headers={"Retry-After": "0"},
            )
        category = int(params.get("search[category]", "0"))
        rows = [row for row in self.tags if int(row["category"]) == category]
        return self._page(rows, params)

    async def aliases_handler(self, request: web.Request) -> web.Response:
        params = dict(request.query)
        self.requests.append(("aliases", params))
        # Deliberately return the retired row too. The builder must not trust
        # server-side status filtering when constructing a verification index.
        return self._page(self.aliases, params)

    @staticmethod
    def _page(
        source: list[dict[str, object]],
        params: dict[str, str],
    ) -> web.Response:
        page = params.get("page", "a0")
        if page.startswith("b"):
            rows = sorted(source, key=lambda item: int(item["id"]), reverse=True)[:1]
            return web.json_response(rows)
        cursor = int(page[1:] or 0) if page.startswith("a") else 0
        high_water = int(params.get("search[id_lteq]", "2147483647"))
        limit = int(params.get("limit", "1000"))
        rows = [
            row
            for row in sorted(source, key=lambda item: int(item["id"]))
            if cursor < int(row["id"]) <= high_water
        ][:limit]
        return web.json_response(rows)


class DanbooruApiBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.index = DanbooruTagIndex(root / "danbooru.sqlite3")
        self.builder = DanbooruApiBuilder(
            self.index,
            root / "danbooru-checkpoint.sqlite3",
        )
        self.api = _FakeDanbooruApi()
        app = web.Application()
        app.router.add_get("/tags.json", self.api.tags_handler)
        app.router.add_get("/tag_aliases.json", self.api.aliases_handler)
        self.server = TestServer(app)
        await self.server.start_server()

    async def asyncTearDown(self) -> None:
        await self.server.close()
        self.directory.cleanup()

    def options(self, **overrides: object) -> DanbooruBuildOptions:
        values: dict[str, object] = {
            "base_url": str(self.server.make_url("/")),
            "mode": "identity",
            "general_min_posts": 10,
            "meta_min_posts": 10,
            "page_size": 1,
            "request_interval_ms": 250,
            "timeout_seconds": 10,
            "include_aliases": True,
            "max_retries": 3,
        }
        values.update(overrides)
        return DanbooruBuildOptions(**values)

    async def _build_without_waits(
        self,
        options: DanbooruBuildOptions | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        with mock.patch.object(
            self.builder,
            "_cancelable_sleep",
            new=mock.AsyncMock(),
        ):
            return await self.builder.build(options or self.options(), **kwargs)

    async def test_build_uses_high_water_cursor_thresholds_and_safe_aliases(
        self,
    ) -> None:
        self.api.rate_limit_once = True
        sleeps = mock.AsyncMock()
        with mock.patch.object(self.builder, "_cancelable_sleep", new=sleeps):
            result = await self.builder.build(self.options())

        self.assertTrue(result["identity_complete"])
        self.assertEqual(result["source_max_tag_id"], 51)
        self.assertEqual(result["source_max_alias_id"], 109)
        self.assertTrue(result["source_cutoff_at"])
        active_status = self.index.status()
        self.assertTrue(active_status["identity_complete"])
        self.assertEqual(active_status["source_cutoff_at"], result["source_cutoff_at"])
        self.assertEqual(
            result["category_counts"],
            {
                "general": 1,
                "artist": 1,
                "copyright": 1,
                "character": 2,
                "meta": 1,
            },
        )
        self.assertEqual(self.api.rate_limit_hits, 1)
        self.assertTrue(
            any(call.args and call.args[0] == 0.25 for call in sleeps.await_args_list)
        )

        tag_requests = [params for kind, params in self.api.requests if kind == "tags"]
        self.assertTrue(any(params.get("page") == "b2147483647" for params in tag_requests))
        self.assertTrue(any(params.get("page") == "a0" for params in tag_requests))
        self.assertTrue(
            all(
                "search[id_lteq]" in params
                for params in tag_requests
                if params.get("page", "").startswith("a")
            )
        )
        threshold_requests = {
            int(params["search[category]"]): params.get("search[post_count_gteq]")
            for params in tag_requests
            if params.get("page") == "b2147483647"
        }
        self.assertEqual(threshold_requests[0], "10")
        self.assertEqual(threshold_requests[5], "10")
        self.assertIsNone(threshold_requests[1])
        self.assertIsNone(threshold_requests[3])
        self.assertIsNone(threshold_requests[4])

        viola = self.index.lookup("viola_(bang_dream!)", "character")
        self.assertTrue(viola.verified)
        self.assertEqual(viola.match_type, "canonical")
        self.assertTrue(self.index.lookup("viola_old_name", "character").verified)
        self.assertTrue(self.index.lookup("viola_legacy", "character").verified)
        self.assertFalse(
            self.index.lookup("shared_character_name", "character").verified,
            "an alias owned by multiple canonicals must never verify",
        )
        self.assertFalse(
            self.index.lookup("branch_identity", "character").verified,
            "a transitive alias that reaches multiple canonicals must stay ambiguous",
        )
        self.assertFalse(self.index.lookup("cycle_a").verified)
        self.assertFalse(self.index.lookup("retired_viola_name", "character").found)
        self.assertFalse(self.index.lookup("low_count_general").found)
        self.assertFalse(self.index.lookup("low_count_meta").found)

    async def test_cooperative_cancel_resumes_from_committed_cursor(self) -> None:
        old = self.index.import_bytes(
            b'[{"tag":"old_character","category":4,"count":1}]'
        )
        cancel_event = threading.Event()

        async def cancel_after_first_page(payload: dict[str, object]) -> None:
            if payload.get("event") == "tag_page_committed":
                cancel_event.set()

        with mock.patch.object(
            self.builder,
            "_cancelable_sleep",
            wraps=self.builder._cancelable_sleep,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.builder.build(
                    self.options(),
                    progress=cancel_after_first_page,
                    cancel_event=cancel_event,
                )

        self.assertEqual(self.index.status()["sha256"], old["sha256"])
        self.assertTrue(self.index.lookup("old_character", "character").verified)
        checkpoint = self.builder.checkpoint_status()
        self.assertTrue(checkpoint["available"])
        self.assertEqual(checkpoint["tag_count"], 1)
        first_run_requests = len(self.api.requests)

        progress_events: list[dict[str, object]] = []
        result = await self._build_without_waits(
            progress=lambda payload: progress_events.append(payload)
        )
        resumed_requests = self.api.requests[first_run_requests:]

        self.assertTrue(result["resumed"])
        self.assertEqual(progress_events[0]["event"], "build_resumed")
        self.assertEqual(resumed_requests[0][0], "tags")
        self.assertEqual(resumed_requests[0][1]["page"], "a40")
        self.assertTrue(self.index.lookup("viola_(bang_dream!)", "character").verified)
        self.assertFalse(self.builder.checkpoint_status()["available"])

    async def test_identity_regression_rejects_activation_and_preserves_old_snapshot(
        self,
    ) -> None:
        old = self.index.import_bytes(
            b"["
            b'{"tag":"old_character_a","category":4,"count":2},'
            b'{"tag":"old_character_b","category":4,"count":1},'
            b'{"tag":"old_copyright","category":3,"count":1},'
            b'{"tag":"old_artist","category":1,"count":1}'
            b"]"
        )
        self.api.tags = [
            row
            for row in self.api.tags
            if row["name"] != "kei_(blue_archive)"
        ]

        with self.assertRaises(DanbooruBuildError) as caught:
            await self._build_without_waits()

        self.assertEqual(caught.exception.code, "identity_completeness_failed")
        self.assertEqual(self.index.status()["sha256"], old["sha256"])
        self.assertTrue(self.index.lookup("old_character_b", "character").verified)
        self.assertFalse(self.index.lookup("viola_(bang_dream!)", "character").found)

    async def test_revision_hash_tracks_content_not_only_counts_and_ids(self) -> None:
        first = await self._build_without_waits()
        first_revision = first["revision"]
        self.api.tags = [
            {
                **row,
                "name": (
                    "renamed_general"
                    if row["name"] == "useful_general"
                    else row["name"]
                ),
            }
            for row in self.api.tags
        ]

        second = await self._build_without_waits()

        self.assertNotEqual(second["revision"], first_revision)
        self.assertFalse(self.index.lookup("useful_general").verified)
        self.assertTrue(self.index.lookup("renamed_general").verified)

    async def test_normalization_collisions_choose_stable_canonical_and_build(self) -> None:
        self.api.tags.extend(
            (
                {
                    "id": 21,
                    "name": "aki__hiko",
                    "category": 1,
                    "post_count": 500,
                    "is_deprecated": False,
                    "updated_at": "2026-08-01T00:00:08Z",
                },
                {
                    "id": 22,
                    "name": "aki_hiko",
                    "category": 1,
                    "post_count": 1,
                    "is_deprecated": False,
                    "updated_at": "2026-08-01T00:00:09Z",
                },
            )
        )
        self.api.aliases.append(
            {
                "id": 110,
                "antecedent_name": "aki_old_alias",
                "consequent_name": "aki__hiko",
                "status": "active",
                "updated_at": "2026-08-01T01:00:10Z",
            }
        )

        result = await self._build_without_waits()

        canonical = self.index.lookup("aki_hiko", "artist")
        legacy_spelling = self.index.lookup("aki__hiko", "artist")
        old_alias = self.index.lookup("aki_old_alias", "artist")
        self.assertTrue(canonical.verified)
        self.assertEqual(canonical.canonical_tag, "aki_hiko")
        self.assertEqual(legacy_spelling.canonical_tag, "aki_hiko")
        self.assertTrue(old_alias.verified)
        self.assertEqual(old_alias.canonical_tag, "aki_hiko")
        self.assertEqual(result["category_counts"]["artist"], 2)
        self.assertEqual(result["source_category_counts"]["artist"], 3)


if __name__ == "__main__":
    unittest.main()
