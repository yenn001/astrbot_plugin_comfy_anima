"""Startup config migration single-path integration tests."""

import json
import tempfile
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs


class StartupConfigMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        import importlib

        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_startup_migration_writes_atomic_file_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = {
                "config_path": str(Path(tmp) / "plugin.json"),
                "enable_natural_draw": True,
                "enable_llm_pic_trigger": False,
            }
            migrated = plugin._migrate_and_writeback_consolidated_config(
                plugin.config
            )
            self.assertEqual(migrated["natural_draw_mode"], "photo_only")
            payload = json.loads(
                Path(plugin.config["config_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(payload["natural_draw_mode"], "photo_only")
            self.assertEqual(payload["config_migration_version"], 2)
            self.assertEqual(plugin.config["natural_draw_mode"], "photo_only")
            first_utc = payload["config_migrated_utc"]
            second = plugin._migrate_and_writeback_consolidated_config(
                plugin.config
            )
            self.assertEqual(second["config_migrated_utc"], first_utc)

    def test_version_two_does_not_touch_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            payload = {
                "natural_draw_mode": "full",
                "config_migration_version": 2,
                "config_migrated_utc": "2026-08-31T00:00:00Z",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.stat().st_mtime_ns
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = {"config_path": str(path), **payload}
            migrated = plugin._migrate_and_writeback_consolidated_config(
                plugin.config
            )
            self.assertEqual(migrated["config_migration_version"], 2)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_writeback_failure_fails_stop_before_settings(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(
                json.dumps({"enable_natural_draw": False}),
                encoding="utf-8",
            )
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = {"config_path": str(path)}
            with mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.replace",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(RuntimeError, "配置迁移写回失败"):
                    plugin._migrate_and_writeback_consolidated_config(
                        plugin.config
                    )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"enable_natural_draw": False},
            )

    def test_writeback_failure_fails_stop_for_photo_only_legacy_combo(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(
                json.dumps(
                    {
                        "enable_natural_draw": True,
                        "enable_llm_pic_trigger": False,
                    }
                ),
                encoding="utf-8",
            )
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = {"config_path": str(path)}
            with mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.replace",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(RuntimeError, "配置迁移写回失败"):
                    plugin._migrate_and_writeback_consolidated_config(
                        plugin.config
                    )

    def test_full_constructor_failure_closes_task_store(self) -> None:
        import types
        from unittest import mock

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            context = types.SimpleNamespace()
            config = {
                "config_path": str(root / "plugin_config.json"),
                "enable_natural_draw": False,
                "enable_web_ui": False,
                "danbooru_auto_update_enabled": False,
                "enable_lora_manager": False,
                "enable_lora_download": False,
                "enable_unet_switch": False,
                "enable_prompt_asset_library": False,
            }
            with mock.patch.object(
                self.main.ComfyAnimaPlugin,
                "_resolve_persistent_data_dir",
                lambda _self: root / "data",
            ), mock.patch(
                "astrbot_plugin_comfy_anima.services.atomic_config.os.replace",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(RuntimeError, "配置迁移写回失败"):
                    self.main.ComfyAnimaPlugin(context, config)
            sqlite = root / "data" / "task_events.sqlite3"
            self.assertTrue(sqlite.exists())
            sqlite.unlink(missing_ok=True)
            self.assertFalse(sqlite.exists())

    def test_startup_migration_does_not_call_generic_saver(self) -> None:
        class Config(dict):
            def save_config(self):
                raise AssertionError("legacy generic saver must not be called")

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.config = Config(
            config_path="",
            enable_natural_draw=False,
        )
        with self.assertRaisesRegex(RuntimeError, "config_path 不可用"):
            plugin._migrate_and_writeback_consolidated_config(plugin.config)

    def test_migration_preserves_durable_config_object_for_persistence(self) -> None:
        """Migration must return the durable host config, not a transient dict.

        AstrBot passes an AstrBotConfig carrying ``save_config()`` and
        ``config_path``; losing them makes every later persistence transaction
        fail with "配置文件保存失败，修改已回滚".
        """

        class DurableConfig(dict):
            def __init__(self, path: Path) -> None:
                super().__init__()
                self.config_path = str(path)
                self.saved_calls = 0

            def save_config(self) -> None:
                self.saved_calls += 1
                Path(self.config_path).write_text(
                    json.dumps(dict(self), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            config = DurableConfig(path)
            config.update(
                {
                    "natural_draw_mode": "full",
                    "config_migration_version": 2,
                    "config_migrated_utc": "2026-09-01T00:00:00Z",
                    "prompt_llm_temperature": 0.8,
                }
            )
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = config

            returned = plugin._migrate_and_writeback_consolidated_config(config)
            self.assertIs(returned, config)
            self.assertTrue(callable(getattr(returned, "save_config", None)))
            self.assertEqual(getattr(returned, "config_path", ""), str(path))

            ok = plugin._persist_config_transaction_sync(
                {"prompt_llm_temperature": 0.95},
                operation="test save",
            )
            self.assertTrue(ok)
            self.assertEqual(config.saved_calls, 1)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["prompt_llm_temperature"], 0.95)


if __name__ == "__main__":
    unittest.main()