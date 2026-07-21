from __future__ import annotations

import importlib
import types
import unittest

from ..models import GenerationOptions, LoraSelection
from ..services.lora_catalog import LoraRecord
from .test_main_compat import _install_astrbot_stubs


class LoraPlanningSnapshotTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _plugin(catalog: object) -> object:
        plugin = object.__new__(LoraPlanningSnapshotTests.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_task_lora_snapshot=True,
            lora_snapshot_max_age=300,
        )
        plugin._lora_catalog = catalog
        plugin._lora_operation_snapshots = {}
        plugin._lora_snapshot_locks = {}
        return plugin

    async def test_one_task_reuses_planning_refresh_but_submit_forces_refresh(self) -> None:
        record = LoraRecord("styles/current.safetensors", sha256="aa11")

        class Catalog:
            refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (record,)

        catalog = Catalog()
        plugin = self._plugin(catalog)
        first_event = object()

        first = await plugin._refresh_lora_manager_before(
            "first planning read",
            event=first_event,
        )
        second = await plugin._refresh_lora_manager_before(
            "second planning read",
            event=first_event,
        )
        self.assertIs(first, second)
        self.assertEqual(catalog.refreshes, 1)

        await plugin._refresh_lora_manager_before(
            "pre-submit validation",
            event=first_event,
            force=True,
        )
        self.assertEqual(catalog.refreshes, 2)

        await plugin._refresh_lora_manager_before(
            "new task planning",
            event=object(),
        )
        self.assertEqual(catalog.refreshes, 3)

    async def test_changed_lora_identity_between_plan_and_submit_fails_closed(self) -> None:
        old = LoraRecord(
            "characters/denia.safetensors",
            sha256="aa11",
            source_fingerprint="old-source",
        )
        new = LoraRecord(
            "characters/denia.safetensors",
            sha256="bb22",
            source_fingerprint="new-source",
        )

        class Catalog:
            refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (old,) if self.refreshes == 1 else (new,)

            async def resolve_selections_with_records(
                self,
                selections,
                strict=True,
                *,
                records=None,
            ):
                self.assert_strict = strict
                selected = tuple(selections)
                record = tuple(records or ())[0]
                return selected, {"characters/denia": record}

        catalog = Catalog()
        plugin = self._plugin(catalog)
        event = object()
        await plugin._refresh_lora_manager_before("planning", event=event)

        with self.assertRaisesRegex(
            self.main.WorkflowError,
            "内容或元数据变化|规划与提交之间发生变化",
        ):
            await plugin._freshen_dynamic_loras_before_submit(
                GenerationOptions(
                    prompt="1girl, denia",
                    dynamic_loras=(
                        LoraSelection("characters/denia.safetensors", 0.8),
                    ),
                ),
                "pre-submit",
                event=event,
            )

        self.assertEqual(catalog.refreshes, 2)


if __name__ == "__main__":
    unittest.main()
