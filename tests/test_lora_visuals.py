"""Tests for the safe local LoRA visual manifest and thumbnail cache."""

from __future__ import annotations

import binascii
from concurrent.futures import Future
from io import BytesIO
import os
from pathlib import Path
import random
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock
import zlib

from ..services.lora_catalog import LoraRecord
from ..services import lora_visuals
from ..services.lora_visuals import (
    LoraPreviewError,
    LoraVisualSecurityError,
    LoraVisualService,
)


def _png(
    width: int = 3,
    height: int = 2,
    rgb: tuple[int, int, int] = (225, 120, 20),
    text: bytes = b"",
) -> bytes:
    def chunk(name: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(name)
        checksum = binascii.crc32(payload, checksum) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)

    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    metadata = chunk(b"tEXt", b"Description\x00" + text) if text else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + metadata
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _webp() -> bytes:
    if not lora_visuals._PIL_AVAILABLE:
        raise unittest.SkipTest("Pillow is required for WebP regression data")
    assert lora_visuals.Image is not None
    output = BytesIO()
    image = lora_visuals.Image.new("RGB", (3, 2), (12, 34, 56))
    image.save(output, format="WEBP", quality=90)
    return output.getvalue()


class LoraVisualServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "loras"
        self.cache = self.base / "visual-cache"
        self.root.mkdir()
        self.services: list[LoraVisualService] = []

    def tearDown(self) -> None:
        for service in self.services:
            service.close(wait=True)
        self.temporary.cleanup()

    def service(self, **kwargs) -> LoraVisualService:
        service = LoraVisualService((self.root,), self.cache, **kwargs)
        self.services.append(service)
        return service

    def model(self, relative: str, *, preview: str | None = None) -> Path:
        model = self.root / relative
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"safe tensor placeholder")
        if preview:
            (model.parent / preview).write_bytes(_png())
        return model

    @staticmethod
    def record(relative: str, model: Path | None = None, **overrides) -> LoraRecord:
        values = {
            "name": relative,
            "file_path": str(model) if model else "",
            "category": "unknown",
        }
        values.update(overrides)
        return LoraRecord(**values)

    def test_manifest_is_exact_stable_and_cache_residency_is_ephemeral(self) -> None:
        model = self.model("characters/denia.safetensors", preview="denia.preview.png")
        record = self.record(
            "characters/denia.safetensors",
            model,
            model_name="Denia Character",
            category="character",
            trigger_words=("denia_wuwa",),
            tags=("wuthering waves",),
            description="Complete Civitai model description.",
            from_civitai=True,
            favorite=True,
            sha256="a" * 64,
        )
        service = self.service()

        first = service.build_manifest((record,))
        second = service.build_manifest((record,))
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.total, 1)
        item = first.items[0]
        self.assertEqual(len(item.asset_id), 64)
        self.assertEqual(item.name, "characters/denia.safetensors")
        self.assertEqual(item.display_name, "Denia Character")
        self.assertEqual(item.category, "character")
        self.assertEqual(item.size, model.stat().st_size)
        self.assertEqual(item.mtime, model.stat().st_mtime)
        self.assertTrue(item.mtime_iso.endswith("Z"))
        self.assertEqual(len(item.fingerprint), 64)
        self.assertEqual(item.metadata_status, "complete")
        self.assertEqual(item.metadata_source, "civitai")
        self.assertEqual(item.preview_status, "local")
        self.assertEqual(len(item.preview_key), 64)
        self.assertEqual(item.preview_media_type, "image/webp")
        self.assertEqual((item.preview_width, item.preview_height), (3, 2))
        self.assertEqual(item.path_status, "available")
        self.assertTrue(item.favorite)
        public_item = item.to_dict()
        self.assertNotIn("path", public_item)
        self.assertNotIn(str(self.root.resolve()), repr(public_item))
        with self.assertRaises(LoraPreviewError):
            service.resolve_preview(item.preview_key)
        with self.assertRaises(LoraPreviewError):
            service.read_preview(item.preview_key)

        schedule = service.schedule_warmup((record,))
        self.assertEqual(schedule.accepted, 1)
        status = service.wait_for_idle(timeout=5)
        self.assertEqual(status.queued, 0)
        self.assertEqual(status.completed, 1)
        self.assertEqual(status.failed, 0)

        warmed = service.build_manifest((record,))
        self.assertEqual(warmed.items[0].preview_status, "cached")
        self.assertEqual(warmed.fingerprint, first.fingerprint)
        asset = service.resolve_preview(item.preview_key)
        self.assertTrue(asset.cached)
        self.assertFalse(hasattr(asset, "path"))
        self.assertNotIn("path", asset.to_dict())
        self.assertTrue((self.cache / f"{item.preview_key}.webp").exists())
        self.assertEqual(asset.media_type, "image/webp")
        payload, media_type = service.read_preview(item.preview_key)
        self.assertTrue(payload)
        self.assertEqual(media_type, "image/webp")

    def test_companion_matching_is_exact_and_remote_urls_are_never_resolved(self) -> None:
        model = self.model("styles/ink.safetensors")
        (model.parent / "inkish.png").write_bytes(_png())
        outside = self.base / "outside.safetensors"
        outside.write_bytes(b"outside")
        outside.with_suffix(".png").write_bytes(_png())
        service = self.service()

        no_fuzzy = service.build_manifest((self.record("styles/ink.safetensors", model),))
        self.assertEqual(no_fuzzy.items[0].preview_status, "missing")
        self.assertEqual(no_fuzzy.items[0].preview_key, "")

        # The exact full-filename companion convention is accepted.
        (model.parent / "ink.safetensors.png").write_bytes(_png(rgb=(10, 30, 80)))
        exact = service.build_manifest((self.record("styles/ink.safetensors", model),))
        self.assertEqual(exact.items[0].preview_status, "local")

        blocked = self.record(
            "../outside.safetensors",
            outside,
            preview_url="https://example.invalid/private.png?token=secret",
        )
        blocked_item = service.build_manifest((blocked,)).items[0]
        self.assertEqual(blocked_item.name, "")
        self.assertEqual(blocked_item.path_status, "blocked")
        self.assertEqual(blocked_item.preview_status, "remote_only")
        self.assertEqual(len(blocked_item.preview_key), 64)
        self.assertNotIn(str(outside.resolve()), repr(blocked_item.to_dict()))
        with self.assertRaises(LoraVisualSecurityError):
            service.resolve_preview("https://example.invalid/private.png")
        with self.assertRaises(LoraVisualSecurityError):
            service.resolve_preview("../../outside.png")

    def test_invalid_images_and_video_companions_are_not_served(self) -> None:
        model = self.model("broken.safetensors")
        model.with_suffix(".png").write_bytes(b"not a png")
        model.with_suffix(".mp4").write_bytes(b"video")
        service = self.service()
        item = service.build_manifest((self.record("broken.safetensors", model),)).items[0]
        self.assertEqual(item.preview_status, "invalid")
        self.assertEqual(item.preview_key, "")
        self.assertFalse(any(path.suffix == ".mp4" for path in self.cache.glob("*")))

    def test_metadata_filters_search_and_pagination(self) -> None:
        records: list[LoraRecord] = []
        records.append(
            self.record(
                "characters/hero.safetensors",
                self.model("characters/hero.safetensors"),
                model_name="Hero Prime",
                character_name="Hero",
                aliases=("Brave One",),
                category="character",
                trigger_words=("hero_prime",),
                tags=("game",),
                description="A complete record.",
                from_civitai=True,
                favorite=True,
            )
        )
        records.append(
            self.record(
                "styles/ink.safetensors",
                self.model("styles/ink.safetensors"),
                category="artist_style",
                tags=("ink wash",),
            )
        )
        records.append(
            self.record(
                "functional/speed.safetensors",
                self.model("functional/speed.safetensors"),
                category="speed_sampling",
            )
        )
        service = self.service()

        hero_page = service.list_page(records, query="brave one")
        self.assertEqual(hero_page.total, 1)
        self.assertEqual(hero_page.items[0].display_name, "Hero Prime")
        style_page = service.list_page(
            records,
            categories="artist_style",
            metadata_statuses="partial",
            preview_statuses="missing",
        )
        self.assertEqual(style_page.total, 1)
        self.assertEqual(style_page.items[0].name, "styles/ink.safetensors")
        missing_page = service.list_page(records, metadata_statuses=("missing",))
        self.assertEqual(missing_page.total, 1)
        self.assertEqual(missing_page.metadata_counts, {"missing": 1})
        favorites = service.list_page(records, favorite_only=True)
        self.assertEqual(favorites.total, 1)
        self.assertEqual(favorites.items[0].name, "characters/hero.safetensors")
        with self.assertRaises(TypeError):
            service.list_page(records, favorite_only="true")  # type: ignore[arg-type]

        many = tuple(self.record(f"bulk/{index:03d}.safetensors") for index in range(205))
        clamped = service.list_page(many, page_size=999)
        self.assertEqual(clamped.page_size, 200)
        self.assertEqual(len(clamped.items), 200)
        self.assertEqual(clamped.pages, 2)
        second = service.list_page(many, page=2, page_size=200)
        self.assertEqual(len(second.items), 5)

    def test_pillow_absence_fails_closed_without_copying_or_serving_original(self) -> None:
        model = self.model("fallback.safetensors", preview="fallback.png")
        record = self.record("fallback.safetensors", model)
        service = self.service()
        with mock.patch.object(lora_visuals, "_PIL_AVAILABLE", False):
            manifest = service.build_manifest((record,))
            item = manifest.items[0]
            self.assertEqual(item.preview_status, "decoder_unavailable")
            self.assertEqual(item.preview_key, "")
            schedule = service.schedule_warmup((record,))
        self.assertEqual(schedule.accepted, 0)
        self.assertEqual(schedule.unavailable, 1)
        self.assertEqual(tuple(self.cache.glob("*")), ())

    def test_warmup_has_bounded_concurrency_and_deduplicates_queued_keys(self) -> None:
        records: list[LoraRecord] = []
        for index in range(4):
            name = f"queue/item-{index}.safetensors"
            model = self.model(name, preview=f"item-{index}.png")
            (model.parent / f"item-{index}.png").write_bytes(
                _png(rgb=(20 + index, 40 + index, 60 + index))
            )
            records.append(self.record(name, model))
        service = self.service(max_workers=2)
        original = service._cache_preview_by_key
        release = threading.Event()
        counter_lock = threading.Lock()
        active = 0
        peak = 0

        def slow_cache(key: str):
            nonlocal active, peak
            with counter_lock:
                active += 1
                peak = max(peak, active)
            release.wait(timeout=5)
            try:
                return original(key)
            finally:
                with counter_lock:
                    active -= 1

        with mock.patch.object(service, "_cache_preview_by_key", side_effect=slow_cache):
            first = service.schedule_warmup(tuple(records))
            duplicate = service.schedule_warmup(tuple(records))
            self.assertEqual(first.accepted, 4)
            self.assertEqual(duplicate.deduplicated, 4)
            deadline = time.monotonic() + 2
            while peak < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertLessEqual(peak, 2)
            self.assertEqual(peak, 2)
            release.set()
            status = service.wait_for_idle(timeout=10)
        self.assertEqual(status.queued, 0)
        self.assertEqual(status.completed, 4)
        self.assertEqual(status.failed, 0)

    def test_warmup_keys_are_exact_current_manifest_whitelist(self) -> None:
        first = self.model("selected/first.safetensors", preview="first.png")
        second = self.model("selected/second.safetensors", preview="second.png")
        first.with_suffix(".png").write_bytes(_png(rgb=(2, 4, 6)))
        second.with_suffix(".png").write_bytes(_png(rgb=(3, 5, 7)))
        records = (
            self.record("selected/first.safetensors", first),
            self.record("selected/second.safetensors", second),
        )
        service = self.service()
        manifest = service.build_manifest(records)
        selected_key = manifest.items[0].preview_key
        schedule = service.schedule_warmup(
            records,
            keys=(selected_key, selected_key),
        )
        self.assertEqual(schedule.accepted, 1)
        self.assertEqual(schedule.keys, (selected_key,))
        with self.assertRaises(LoraPreviewError):
            service.schedule_warmup(records, keys=("f" * 64,))
        with self.assertRaises(LoraVisualSecurityError):
            service.schedule_warmup(records, keys=("../../first.png",))
        status = service.wait_for_idle(timeout=5)
        self.assertEqual(status.failed, 0)

    def test_public_manifests_and_fingerprints_do_not_depend_on_absolute_roots(self) -> None:
        second_root = self.base / "second-root"
        second_cache = self.base / "second-cache"
        second_root.mkdir()
        first_model = self.model("same/model.safetensors", preview="model.png")
        second_model = second_root / "same/model.safetensors"
        second_model.parent.mkdir(parents=True)
        second_model.write_bytes(first_model.read_bytes())
        second_model.with_suffix(".png").write_bytes(first_model.with_suffix(".png").read_bytes())
        fixed_time = time.time() - 100
        for path in (
            first_model,
            first_model.with_suffix(".png"),
            second_model,
            second_model.with_suffix(".png"),
        ):
            os.utime(path, (fixed_time, fixed_time))
        first_service = self.service()
        second_service = LoraVisualService((second_root,), second_cache)
        self.services.append(second_service)
        first_record = self.record(
            "same/model.safetensors", first_model, sha256="d" * 64
        )
        second_record = self.record(
            "same/model.safetensors", second_model, sha256="d" * 64
        )

        first = first_service.build_manifest((first_record,))
        second = second_service.build_manifest((second_record,))
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.items[0].fingerprint, second.items[0].fingerprint)
        self.assertEqual(first.items[0].asset_id, second.items[0].asset_id)
        first_public = repr(first.to_dict())
        second_public = repr(second.to_dict())
        self.assertNotIn(str(self.root.resolve()), first_public)
        self.assertNotIn(str(second_root.resolve()), second_public)
        self.assertNotIn("file_path", first_public)

    def test_new_manifest_invalidates_old_local_and_remote_cache_keys(self) -> None:
        first_model = self.model("first.safetensors", preview="first.png")
        first_model.with_suffix(".png").write_bytes(_png(rgb=(1, 2, 3)))
        second_model = self.model("second.safetensors", preview="second.png")
        second_model.with_suffix(".png").write_bytes(_png(rgb=(4, 5, 6)))
        first_record = self.record("first.safetensors", first_model)
        second_record = self.record("second.safetensors", second_model)
        service = self.service()

        first_key = service.build_manifest((first_record,)).items[0].preview_key
        service.resolve_preview(first_key, create_cache=True)
        self.assertTrue((self.cache / f"{first_key}.webp").exists())
        service.build_manifest((second_record,))
        with self.assertRaises(LoraPreviewError):
            service.resolve_preview(first_key)
        with self.assertRaises(LoraPreviewError):
            service.read_preview(first_key)

        remote = self.record(
            "remote.safetensors",
            preview_url="/api/lm/previews?path=remote.preview.png&token=private",
        )
        remote_key = service.build_manifest((remote,)).items[0].preview_key
        service.ingest_preview_bytes(remote_key, _png(), "image/png")
        service.build_manifest(())
        with self.assertRaises(LoraPreviewError):
            service.read_preview(remote_key)

    def test_remote_bytes_require_current_opaque_key_and_are_metadata_free_webp(self) -> None:
        service = self.service()
        record = self.record(
            "manager/remote.safetensors",
            preview_url="/api/lm/previews?path=manager%2Fremote.png&token=private",
            source_fingerprint="manager-record-v1",
        )
        manifest = service.build_manifest((record,))
        item = manifest.items[0]
        self.assertEqual(item.preview_status, "remote_only")
        self.assertEqual(len(item.preview_key), 64)
        public = repr(manifest.to_dict())
        self.assertNotIn("/api/lm/previews", public)
        self.assertNotIn("token=private", public)
        self.assertIs(service.record_for_preview((record,), item.preview_key), record)
        changed_record = self.record(
            "manager/remote.safetensors",
            preview_url="/api/lm/previews?path=manager%2Fnew.png",
            source_fingerprint="manager-record-v2",
        )
        with self.assertRaises(LoraPreviewError):
            service.record_for_preview((changed_record,), item.preview_key)
        with self.assertRaises(LoraPreviewError):
            service.record_for_preview((record, record), item.preview_key)
        with self.assertRaises(LoraPreviewError):
            service.resolve_preview(item.preview_key)
        with self.assertRaises(LoraPreviewError):
            service.ingest_preview_bytes("a" * 64, _png(), "image/png")
        with self.assertRaises(LoraPreviewError):
            service.ingest_preview_bytes(item.preview_key, _png(), "video/mp4")
        mislabeled = service.ingest_preview_bytes(
            item.preview_key,
            _webp(),
            "image/jpeg",
        )
        self.assertEqual(mislabeled.media_type, "image/webp")
        octet_stream = service.ingest_preview_bytes(
            item.preview_key,
            _png(),
            "application/octet-stream",
        )
        self.assertEqual(octet_stream.media_type, "image/webp")
        with self.assertRaises(LoraPreviewError):
            service.ingest_preview_bytes(
                item.preview_key,
                b"x" * (lora_visuals.DEFAULT_MAX_PREVIEW_BYTES + 1),
                "image/png",
            )

        secret = b"SECRET-PROMPT-AND-METADATA"
        asset = service.ingest_preview_bytes(
            item.preview_key,
            _png(text=secret),
            "image/png; charset=binary",
        )
        self.assertEqual(asset.media_type, "image/webp")
        self.assertNotIn("path", asset.to_dict())
        payload, media_type = service.read_preview(item.preview_key)
        self.assertEqual(media_type, "image/webp")
        self.assertEqual(payload[:4], b"RIFF")
        self.assertEqual(payload[8:12], b"WEBP")
        self.assertNotIn(secret, payload)
        warmed = service.build_manifest((record,))
        self.assertEqual(warmed.items[0].preview_status, "cached")
        self.assertEqual(warmed.fingerprint, manifest.fingerprint)

    def test_empty_roots_enable_remote_only_mode_without_local_file_access(self) -> None:
        remote_cache = self.base / "remote-only-cache"
        service = LoraVisualService((), remote_cache)
        self.services.append(service)
        outside = self.base / "must-not-read.safetensors"
        outside.write_bytes(b"outside model")
        outside.with_suffix(".png").write_bytes(_png(rgb=(90, 91, 92)))
        record = self.record(
            "remote-only/model.safetensors",
            outside,
            preview_url="/api/lm/previews?path=remote-only%2Fmodel.png",
        )
        manifest = service.build_manifest((record,))
        item = manifest.items[0]
        self.assertEqual(item.path_status, "missing")
        self.assertEqual(item.preview_status, "remote_only")
        self.assertEqual(len(item.preview_key), 64)
        self.assertFalse(remote_cache.exists() and any(remote_cache.iterdir()))
        service.ingest_preview_bytes(item.preview_key, _png(), "image/png")
        payload, media_type = service.read_preview(item.preview_key)
        self.assertEqual(media_type, "image/webp")
        self.assertEqual(payload[:4], b"RIFF")
        self.assertIs(service.record_for_preview((record,), item.preview_key), record)

    def test_local_cache_reencoding_strips_png_text_metadata(self) -> None:
        model = self.model("metadata.safetensors")
        secret = b"LOCAL-SECRET-PROMPT"
        model.with_suffix(".png").write_bytes(_png(text=secret))
        service = self.service()
        key = service.build_manifest(
            (self.record("metadata.safetensors", model),)
        ).items[0].preview_key
        with self.assertRaises(LoraPreviewError):
            service.ingest_preview_bytes(key, _png(), "image/png")
        service.resolve_preview(key, create_cache=True)
        payload, _ = service.read_preview(key)
        self.assertEqual(payload[:4], b"RIFF")
        self.assertNotIn(secret, payload)

    def test_complex_preview_is_adaptively_bounded_to_one_mib(self) -> None:
        if not lora_visuals._PIL_AVAILABLE:
            self.skipTest("Pillow is required for output-cap regression")
        assert lora_visuals.Image is not None
        width = height = 1024
        pixels = random.Random(20260726).randbytes(width * height * 3)
        image = lora_visuals.Image.frombytes("RGB", (width, height), pixels)
        source = BytesIO()
        image.save(source, format="PNG", compress_level=1)
        source_bytes = source.getvalue()
        self.assertLessEqual(len(source_bytes), lora_visuals.DEFAULT_MAX_PREVIEW_BYTES)
        model = self.model("noise.safetensors")
        model.with_suffix(".png").write_bytes(source_bytes)
        service = self.service(thumbnail_size=(1024, 1024), webp_quality=100)
        key = service.build_manifest(
            (self.record("noise.safetensors", model),)
        ).items[0].preview_key
        service.resolve_preview(key, create_cache=True)
        payload, _ = service.read_preview(key)
        self.assertLessEqual(len(payload), lora_visuals.MAX_OUTPUT_BYTES)

    def test_default_limits_worker_cap_and_warmup_hard_limit(self) -> None:
        self.assertEqual(lora_visuals.DEFAULT_MAX_CACHE_BYTES, 256 * 1024 * 1024)
        self.assertEqual(lora_visuals.DEFAULT_MAX_PREVIEW_BYTES, 4 * 1024 * 1024)
        self.assertEqual(lora_visuals.DEFAULT_MAX_PIXELS, 16_000_000)
        self.assertEqual(lora_visuals.MAX_OUTPUT_BYTES, 1 * 1024 * 1024)
        service = self.service(max_workers=99)
        self.assertEqual(service.max_workers, 4)
        records: list[LoraRecord] = []
        for index in range(205):
            name = f"limit/{index:03d}.safetensors"
            model = self.model(name)
            model.with_suffix(".png").write_bytes(
                _png(rgb=(index, (index * 3) % 256, (index * 7) % 256))
            )
            records.append(self.record(name, model))
        manifest = service.build_manifest(tuple(records))
        with self.assertRaises(LoraPreviewError):
            service.schedule_warmup(
                tuple(records),
                keys=tuple(item.preview_key for item in manifest.items),
            )
        schedule = service.schedule_warmup(tuple(records), limit=9999)
        self.assertEqual(schedule.accepted, 200)
        self.assertEqual(schedule.truncated, 5)
        status = service.wait_for_idle(timeout=20)
        self.assertEqual(status.queued, 0)
        self.assertEqual(status.failed, 0)
        self.assertEqual(status.completed, 200)

    def test_cache_quota_removes_only_recognized_oldest_cache_files(self) -> None:
        service = self.service(max_cache_bytes=12)
        self.cache.mkdir(exist_ok=True)
        oldest = self.cache / f"{'a' * 64}.png"
        newest = self.cache / f"{'b' * 64}.jpg"
        unrelated = self.cache / "do-not-delete.txt"
        suspicious = self.cache / "../../not-possible"
        oldest.write_bytes(b"12345678")
        newest.write_bytes(b"abcdefgh")
        unrelated.write_text("keep", encoding="utf-8")
        old_time = time.time() - 60
        newest_time = time.time()
        oldest.touch()
        newest.touch()
        # Explicit times keep the eviction order stable on coarse filesystems.
        os.utime(oldest, (old_time, old_time))
        os.utime(newest, (newest_time, newest_time))
        result = service.prune_cache()
        self.assertEqual(result["removed"], 1)
        self.assertFalse(oldest.exists())
        self.assertTrue(newest.exists())
        self.assertTrue(unrelated.exists())
        self.assertFalse(suspicious.exists())

    def test_clear_cache_deletes_only_idle_strict_webp_assets(self) -> None:
        service = self.service()
        removable = self.cache / f"{'a' * 64}.webp"
        protected = self.cache / f"{'b' * 64}.webp"
        legacy_png = self.cache / f"{'c' * 64}.png"
        unknown = self.cache / "preview.webp"
        removable.write_bytes(b"remove-me")
        protected.write_bytes(b"keep-inflight")
        legacy_png.write_bytes(b"keep-legacy")
        unknown.write_bytes(b"keep-unknown")
        pending: Future = Future()
        with service._state_lock:
            service._inflight["b" * 64] = pending
        try:
            result = service.clear_cache()
        finally:
            with service._state_lock:
                service._inflight.pop("b" * 64, None)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["removed_bytes"], len(b"remove-me"))
        self.assertEqual(result["remaining_bytes"], len(b"keep-inflight"))
        self.assertFalse(removable.exists())
        self.assertTrue(protected.exists())
        self.assertTrue(legacy_png.exists())
        self.assertTrue(unknown.exists())

    def test_preview_source_change_requires_manifest_refresh(self) -> None:
        model = self.model("mutable.safetensors", preview="mutable.png")
        record = self.record("mutable.safetensors", model)
        service = self.service()
        old_key = service.build_manifest((record,)).items[0].preview_key
        preview = model.with_suffix(".png")
        preview.write_bytes(_png(width=4, height=2, rgb=(10, 11, 12)))
        now = time.time() + 2
        os.utime(preview, (now, now))
        with self.assertRaises(LoraPreviewError):
            service.resolve_preview(old_key, create_cache=True)
        refreshed = service.build_manifest((record,)).items[0]
        self.assertNotEqual(refreshed.preview_key, old_key)


if __name__ == "__main__":
    unittest.main()
