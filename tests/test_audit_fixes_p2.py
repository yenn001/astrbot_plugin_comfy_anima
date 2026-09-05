"""Focused regression tests for remaining audit fixes OP-09..OP-23.

These tests cover backend/data/config changes and leave frontend/HTTP behavior
to ``test_web_ui`` where the live service is already exercised.
"""

from __future__ import annotations

import binascii
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zlib

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()

from ..constants import DEFAULT_DIRECTOR_REFERENCE_FILE  # noqa: E402
from ..models import PluginSettings  # noqa: E402
from ..services import semantic_edit  # noqa: E402
from ..services.lora_archiver import LoraArchiveService  # noqa: E402
from ..services.lora_catalog import LoraRecord  # noqa: E402
from ..services.lora_visuals import LoraVisualService  # noqa: E402
from ..services.prompt_assets import PromptAssetLibrary  # noqa: E402
from ..services.task_store import TaskStore  # noqa: E402
from ..services.web_ui import WebUiActionError, _normalize_web_setting_value  # noqa: E402


def _png(width: int = 3, height: int = 2, rgb: tuple[int, int, int] = (1, 2, 3)) -> bytes:
    def chunk(name: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(name)
        checksum = binascii.crc32(payload, checksum) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", checksum)
        )

    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class Op14TaskStoreLatestPhaseTests(unittest.TestCase):
    def test_recent_tasks_use_sql_latest_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(
                Path(directory) / "tasks.sqlite3",
                max_events=500,
                cleanup_interval=1000,
            )
            try:
                run_id = store.create_task("audit")
                store.append_event(run_id, "phase_one", "first")
                store.append_event(run_id, "phase_two", "second")
                tasks = store.recent_tasks()
                self.assertEqual(tasks[0]["latest_phase"], "phase_two")
                latest = store.latest_events((run_id,), k=1)
                self.assertEqual([item["phase"] for item in latest[run_id]], ["phase_two"])
                latest_two = store.latest_events((run_id,), k=2)
                self.assertEqual(
                    [item["phase"] for item in latest_two[run_id]],
                    ["phase_two", "phase_one"],
                )
            finally:
                store.close()


class Op09LoraVisualIncrementalPruneTests(unittest.TestCase):
    def test_batch_warmup_prunes_once_after_idle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "loras"
            cache = Path(directory) / "cache"
            root.mkdir()
            model = root / "characters/a.safetensors"
            model.parent.mkdir()
            model.write_bytes(b"tensor")
            (root / "characters/a.png").write_bytes(_png())
            service = LoraVisualService((root,), cache)
            try:
                record = LoraRecord(
                    name="characters/a.safetensors",
                    file_path=str(model),
                    category="unknown",
                )
                manifest = service.build_manifest((record,))
                self.assertEqual(manifest.total, 1)
                with mock.patch.object(service, "prune_cache", wraps=service.prune_cache) as pruner:
                    service.schedule_warmup((record,))
                    status = service.wait_for_idle(timeout=5)
                    self.assertEqual(status.completed, 1)
                    self.assertEqual(pruner.call_count, 1)
            finally:
                service.close(wait=True)


class Op10LoraArchiverFingerprintReuseTests(unittest.TestCase):
    def test_catalog_status_computes_each_fingerprint_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = LoraArchiveService(Path(directory) / "archive.json")
            records = tuple(
                LoraRecord(
                    name=f"characters/item-{index}.safetensors",
                    sha256=bytes([index + 1]) * 64,
                    category="unknown",
                )
                for index in range(3)
            )
            with mock.patch.object(
                LoraArchiveService,
                "record_fingerprint",
                wraps=LoraArchiveService.record_fingerprint,
            ) as fingerprint:
                status = service.catalog_status(records)
            self.assertEqual(fingerprint.call_count, len(records))
            self.assertEqual(
                status.fingerprint,
                LoraArchiveService.catalog_fingerprint(records),
            )


class Op11PromptAssetFacetsSqlTests(unittest.TestCase):
    def test_facets_do_not_decode_json_rows_in_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = PromptAssetLibrary(Path(directory) / "assets.sqlite3")
            library.import_bytes(
                json.dumps(
                    [
                        {
                            "asset_type": "character",
                            "name_en": "Denia",
                            "categories": ["student"],
                            "traits": ["white hair"],
                        },
                        {
                            "asset_type": "character",
                            "name_en": "Miku",
                            "categories": ["singer"],
                            "traits": ["long hair"],
                        },
                    ]
                ).encode("utf-8")
            )
            with mock.patch(
                "astrbot_plugin_comfy_anima.services.prompt_assets._decode_json_list",
                side_effect=AssertionError("facets must not decode JSON rows in Python"),
            ), mock.patch(
                "astrbot_plugin_comfy_anima.services.prompt_assets._decode_json_object",
                side_effect=AssertionError("facets must not decode provenance rows in Python"),
            ):
                facets = library.facets()
            self.assertEqual(facets["type_counts"]["character"], 2)
            self.assertIn({"value": "student", "count": 1}, facets["categories"])
            self.assertIn({"value": "white hair", "count": 1}, facets["traits"])


class Op12SemanticEditNormalizeOnceTests(unittest.TestCase):
    def test_validate_normalizes_prompt_once(self) -> None:
        prompt = "1girl, solo, red dress, white stockings"
        calls: list[str] = []
        original = semantic_edit._normalized

        def tracking(value: str) -> str:
            calls.append(value)
            return original(value)

        with mock.patch.object(semantic_edit, "_normalized", side_effect=tracking):
            issues = semantic_edit.validate_semantic_prompt(
                prompt,
                required_groups=(
                    ("red_dress", ("red dress", "red gown")),
                    ("white_thighhighs", ("white stockings", "white thighhighs")),
                ),
                forbidden_terms=("mini skirt",),
                preserved_terms=("solo",),
            )
        self.assertEqual(issues, ())
        self.assertEqual(calls.count(prompt), 1)


class Op21CooldownSafeParseTests(unittest.TestCase):
    def test_invalid_cooldown_uses_safe_default(self) -> None:
        self.assertEqual(
            PluginSettings.from_mapping(
                {"conversation_draw_cooldown_seconds": "not-a-number"}
            ).conversation_draw_cooldown_seconds,
            8.0,
        )
        self.assertEqual(
            PluginSettings.from_mapping(
                {"conversation_draw_cooldown_seconds": -2}
            ).conversation_draw_cooldown_seconds,
            0.0,
        )


class Op22SchemaDefaultAndNoRewriteTests(unittest.TestCase):
    def test_schema_default_matches_constant_and_legacy_is_migrated(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["director_reference_file"]["default"],
            DEFAULT_DIRECTOR_REFERENCE_FILE,
        )
        legacy = PluginSettings.from_mapping(
            {"director_reference_file": "prompts/director_reference.txt"}
        )
        self.assertEqual(
            legacy.director_reference_file,
            DEFAULT_DIRECTOR_REFERENCE_FILE,
        )


class Op23WebSettingsSchemaValidationTests(unittest.TestCase):
    def test_schema_normalizes_and_rejects_out_of_range(self) -> None:
        normalized, changed = _normalize_web_setting_value(
            "intent_router_timeout",
            "30",
            {"type": "int", "min": 3, "max": 120},
        )
        self.assertEqual(normalized, 30)
        self.assertTrue(changed)
        with self.assertRaises(WebUiActionError):
            _normalize_web_setting_value(
                "intent_router_timeout",
                200,
                {"type": "int", "min": 3, "max": 120},
            )
        with self.assertRaises(WebUiActionError):
            _normalize_web_setting_value(
                "interaction_mode",
                "loose",
                {"type": "string", "options": ["smart", "strict"]},
            )


if __name__ == "__main__":
    unittest.main()
