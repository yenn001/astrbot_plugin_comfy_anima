"""Tests for session picture recipe persistence and invalidation."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from ..services.preset_manifest import PresetManifest
from ..services.session_picture_recipe import (
    SessionPictureRecipe,
    SessionPictureRecipeStore,
)


def _recipe(run_id: str = "run-1") -> SessionPictureRecipe:
    manifest = PresetManifest.build(
        preset_name="达妮娅预设",
        positive_terms=("daniya_(wuwa)", "smile"),
        negative_terms=("lowres", "bad anatomy"),
        lora_entries=(
            {"name": "daniya.safetensors", "weight": 0.8, "model_family": "legacy-28-layer"},
        ),
        model_family="legacy-28-layer",
        identity_anchor="daniya_(wuwa)",
        required_triggers=("daniya",),
    )
    return SessionPictureRecipe.from_success(
        bot_id="bot-1",
        session_id="session-1",
        user_id="user-1",
        run_id=run_id,
        preset_name="达妮娅预设",
        pipeline="rtx",
        width=832,
        height=1216,
        prompt_recipe="<pic>daniya_(wuwa), smile</pic>",
        manifest=manifest,
        content_fingerprint="fp-1",
    )


class SessionPictureRecipeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SessionPictureRecipeStore(Path(self.tmp.name) / "recipes.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip(self) -> None:
        recipe = _recipe()
        asyncio.run(self._roundtrip(recipe))

    async def _roundtrip(self, recipe: SessionPictureRecipe) -> None:
        await self.store.initialize("2.1.305")
        await self.store.put(recipe)
        loaded = await self.store.get("bot-1", "session-1", "user-1")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.last_run_id, "run-1")
        self.assertEqual(loaded.manifest_hash, recipe.manifest_hash)
        self.assertEqual(loaded.content_fingerprint, "fp-1")

    def test_version_change_clears_all(self) -> None:
        async def run() -> None:
            await self.store.initialize("2.1.305")
            await self.store.put(_recipe())
            self.assertTrue(
                await self.store.initialize("2.1.306"),
                "a version change must clear the store",
            )
            self.assertIsNone(await self.store.get("bot-1", "session-1", "user-1"))

        asyncio.run(run())

    def test_same_version_reload_preserves(self) -> None:
        async def run() -> None:
            await self.store.initialize("2.1.305")
            await self.store.put(_recipe())
            self.assertFalse(await self.store.initialize("2.1.305"))
            self.assertIsNotNone(await self.store.get("bot-1", "session-1", "user-1"))

        asyncio.run(run())

    def test_content_fingerprint_invalidation(self) -> None:
        async def run() -> None:
            await self.store.initialize("2.1.305")
            await self.store.put(_recipe())
            removed = await self.store.invalidate_for_content(
                preset_name="达妮娅预设",
                lora_fingerprint="fp-2",
            )
            self.assertEqual(removed, 1)
            self.assertIsNone(await self.store.get("bot-1", "session-1", "user-1"))

        asyncio.run(run())

    def test_schema_bump_drops_legacy_envelope(self) -> None:
        path = Path(self.tmp.name) / "recipes.json"
        path.write_text(
            '{"schema_version": 0, "last_loaded_plugin_version": "2.1.303", '
            '"recipes": {"old": {}}}',
            encoding="utf-8",
        )
        async def run() -> None:
            self.assertTrue(await self.store.initialize("2.1.305"))
            self.assertIsNone(await self.store.get("bot-1", "session-1", "user-1"))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
