"""Lifecycle smoke tests: construct, initialize and terminate the plugin."""

from __future__ import annotations

import importlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


from ._stubs import install_astrbot_stubs


install_astrbot_stubs()
main = importlib.import_module("astrbot_plugin_comfy_anima.main")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_initialize_and_terminate_with_stub_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            context = types.SimpleNamespace()
            config = {
                "config_path": str(root / "plugin_config.json"),
                "enable_web_ui": False,
                "danbooru_auto_update_enabled": False,
                "enable_lora_manager": False,
                "enable_lora_download": False,
                "enable_unet_switch": False,
                "enable_prompt_asset_library": False,
            }
            with mock.patch.object(
                main.ComfyAnimaPlugin,
                "_resolve_persistent_data_dir",
                lambda _self: root / "data",
            ), mock.patch.object(
                main.tempfile,
                "gettempdir",
                return_value=str(root / "runtime-tmp"),
            ):
                plugin = main.ComfyAnimaPlugin(context, config)

            self.assertIsNotNone(plugin._task_store)
            self.assertIsNotNone(plugin._config_profiles)
            self.assertIsNotNone(plugin._log_console)
            self.assertIsNotNone(plugin._prompt_plans)
            self.assertIsNotNone(plugin._client)
            self.assertIsNotNone(plugin._drawing_orchestrator)

            async def run() -> None:
                await plugin.initialize()
                # initialize should be safe to call twice.
                await plugin.initialize()
                await plugin.terminate()

            self.run_async(run())
            plugin._task_store.close()
            plugin._log_console.close()

    def run_async(self, awaitable) -> None:
        import asyncio

        asyncio.run(awaitable)


if __name__ == "__main__":
    unittest.main()
