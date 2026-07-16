"""Tests for the authenticated dedicated-port Web UI."""

import tempfile
import sys
import types
import unittest
from pathlib import Path

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

if "astrbot.api" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = types.SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

from ..models import PluginSettings
from ..services.web_ui import WebUiError, WebUiService


class _Controller:
    def __init__(self) -> None:
        self.saved_settings = None
        self.refresh_count = 0
        self.metadata_payload = None
        self.detail_name = None
        self.semantic_payload = None
        self.archive_payload = None
        self.log_query = None
        self.logs_cleared = 0
        self.task_query = None
        self.task_run_id = None
        self.task_event_query = None
        self.cancelled_task = None

    async def web_ui_bootstrap(self):
        return {"version": "test", "settings": {}}

    async def web_ui_save_settings(self, payload):
        self.saved_settings = payload
        return {"message": "saved", "reload_scheduled": True}

    async def web_ui_list_providers(self):
        return {
            "selected": "provider-main",
            "items": [
                {
                    "id": "provider-main",
                    "name": "Main",
                    "model": "gpt-test",
                    "type": "openai_chat_completion",
                    "enabled": True,
                    "available": True,
                }
            ],
        }

    async def web_ui_search_loras(self, keyword, limit):
        return {"total": 1, "items": [{"name": keyword, "limit": limit}]}

    async def web_ui_refresh_loras(self):
        self.refresh_count += 1
        return {"total": 1, "message": "refreshed"}

    async def web_ui_download_lora(self, url):
        return {"message": url}

    async def web_ui_fetch_lora_metadata(self, payload):
        self.metadata_payload = payload
        return {"message": "metadata"}

    async def web_ui_get_lora_detail(self, name):
        self.detail_name = name
        return {"name": name, "metadata_health": {"status": "complete"}}

    async def web_ui_save_lora_semantic(self, payload):
        self.semantic_payload = payload
        return {"message": "reviewed", "item": payload}

    async def web_ui_get_lora_archive(self):
        return {"status": {"changed": True}, "items": []}

    async def web_ui_archive_loras(self, payload):
        self.archive_payload = payload
        return {"message": "archived"}

    async def web_ui_list_presets(self):
        return {"items": []}

    async def web_ui_save_preset(self, payload):
        return payload

    async def web_ui_delete_preset(self, identifier):
        return {"message": identifier}

    async def web_ui_list_unet(self):
        return {"items": []}

    async def web_ui_select_unet(self, identifier):
        return {"name": identifier}

    async def web_ui_list_config_profiles(self):
        return {"items": []}

    async def web_ui_save_config_profile(self, payload):
        return {"profile": payload}

    async def web_ui_switch_config_profile(self, identifier):
        return {"profile": {"name": identifier}}

    async def web_ui_delete_config_profile(self, identifier):
        return {"profile": {"name": identifier}}

    async def web_ui_get_logs(self, after_id, limit):
        self.log_query = (after_id, limit)
        return {
            "entries": [
                {
                    "id": 8,
                    "timestamp": 1.0,
                    "time": "2026-07-16T00:00:00+08:00",
                    "level": "INFO",
                    "category": "plugin",
                    "source": "main.py",
                    "line": 10,
                    "message": "ready",
                    "truncated": False,
                }
            ],
            "cursor": 8,
            "buffer_size": 1,
            "capacity": 1000,
        }

    async def web_ui_clear_logs(self):
        self.logs_cleared += 1
        return {"removed": 1, "cursor": 8, "message": "cleared"}

    async def web_ui_list_tasks(self, limit, task_type, status):
        self.task_query = (limit, task_type, status)
        return {
            "items": [
                {
                    "run_id": "run-123",
                    "task_type": "lora_archive",
                    "status": "running",
                }
            ]
        }

    async def web_ui_get_task(self, run_id):
        self.task_run_id = run_id
        return {
            "run_id": run_id,
            "task_type": "lora_archive",
            "status": "running",
        }

    async def web_ui_get_task_events(self, run_id, after_seq, limit):
        self.task_event_query = (run_id, after_seq, limit)
        return {
            "entries": [
                {
                    "seq": after_seq + 1,
                    "run_id": run_id,
                    "phase": "metadata",
                    "message": "metadata loaded",
                }
            ],
            "cursor": after_seq + 1,
        }

    async def web_ui_cancel_task(self, run_id):
        self.cancelled_task = run_id
        return {"run_id": run_id, "status": "cancelled"}


class WebUiTaskAssetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        web_dir = Path(__file__).resolve().parents[1] / "web"
        cls.html = (web_dir / "index.html").read_text(encoding="utf-8")
        cls.javascript = (web_dir / "app.js").read_text(encoding="utf-8")

    def test_timeline_defaults_to_newest_first_with_supported_page_sizes(self) -> None:
        self.assertIn('<option value="desc" selected>最新在上</option>', self.html)
        for size in (10, 20, 50, 100, 200):
            self.assertIn(f'<option value="{size}"', self.html)
        self.assertIn('let taskEventOrder = "desc";', self.javascript)
        self.assertIn("right.seq - left.seq", self.javascript)
        self.assertIn("ordered.slice(pageStart, pageStart + taskEventPageSize)", self.javascript)

    def test_task_timeline_uses_incremental_cursor_and_persistent_console_copy(self) -> None:
        self.assertIn("after=${taskEventCursor}", self.javascript)
        self.assertIn('id="task-event-prev"', self.html)
        self.assertIn('id="task-event-next"', self.html)
        self.assertIn("SQLITE LEDGER", self.html)
        self.assertIn("插件重载后恢复最近记录", self.html)

    def test_lora_catalog_exposes_all_functional_category_filters(self) -> None:
        categories = {
            "speed_sampling": "加速 / 采样",
            "quality_enhancement": "画质增强",
            "detail_restoration": "细节修复",
            "composition_pose": "构图 / 姿势",
            "lighting_color": "光影 / 色彩",
            "background_environment": "背景 / 环境",
            "clothing_concept": "服装 / 概念",
        }
        for category, label in categories.items():
            with self.subTest(category=category):
                self.assertIn(f'data-category="{category}"', self.html)
                self.assertIn(f'value="{category}">{label}</option>', self.html)
                self.assertIn(f'{category}: "{label}"', self.javascript)


class WebUiValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin_dir = Path(__file__).resolve().parents[1]

    def test_disabled_defaults_are_safe(self) -> None:
        settings = PluginSettings.from_mapping({})
        self.assertFalse(settings.enable_web_ui)
        self.assertEqual(settings.web_ui_host, "0.0.0.0")
        self.assertEqual(settings.web_ui_port, 6198)
        self.assertEqual(settings.web_ui_username, "admin")
        self.assertEqual(settings.web_ui_password, "")

    def test_enabled_ui_requires_password_and_private_bind(self) -> None:
        missing_password = PluginSettings.from_mapping(
            {"enable_web_ui": True, "web_ui_password": "short"}
        )
        with self.assertRaises(WebUiError):
            WebUiService(
                missing_password,
                self.plugin_dir,
                _Controller(),
            ).validate()

        public_host = PluginSettings.from_mapping(
            {
                "enable_web_ui": True,
                "web_ui_host": "8.8.8.8",
                "web_ui_password": "valid-password",
            }
        )
        with self.assertRaises(WebUiError):
            WebUiService(
                public_host,
                self.plugin_dir,
                _Controller(),
            ).validate()

    def test_missing_assets_are_rejected(self) -> None:
        settings = PluginSettings.from_mapping(
            {
                "enable_web_ui": True,
                "web_ui_password": "valid-password",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WebUiError):
                WebUiService(
                    settings,
                    Path(directory),
                    _Controller(),
                ).validate()


class WebUiHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.controller = _Controller()
        settings = PluginSettings.from_mapping(
            {
                "enable_web_ui": True,
                "web_ui_username": "admin",
                "web_ui_password": "test-password",
            }
        )
        plugin_dir = Path(__file__).resolve().parents[1]
        self.service = WebUiService(settings, plugin_dir, self.controller)
        self.client = TestClient(
            TestServer(self.service.create_app()),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def _login(self) -> str:
        response = await self.client.post(
            "/api/login",
            json={"username": "admin", "password": "test-password"},
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["ok"])
        bootstrap = await self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status, 200)
        data = await bootstrap.json()
        return data["data"]["csrf_token"]

    async def test_authentication_and_csrf_protect_mutations(self) -> None:
        anonymous = await self.client.get("/api/bootstrap")
        self.assertEqual(anonymous.status, 401)
        anonymous_tasks = await self.client.get("/api/tasks")
        self.assertEqual(anonymous_tasks.status, 401)

        bad_login = await self.client.post(
            "/api/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        self.assertEqual(bad_login.status, 401)

        csrf = await self._login()
        missing_csrf = await self.client.put(
            "/api/settings",
            json={"default_width": 1024},
        )
        self.assertEqual(missing_csrf.status, 403)

        saved = await self.client.put(
            "/api/settings",
            json={"default_width": 1024},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(saved.status, 200)
        self.assertEqual(self.controller.saved_settings, {"default_width": 1024})

    async def test_authenticated_routes_forward_to_controller(self) -> None:
        csrf = await self._login()
        providers = await self.client.get("/api/providers")
        self.assertEqual(providers.status, 200)
        provider_payload = await providers.json()
        self.assertEqual(
            provider_payload["data"]["items"][0]["id"],
            "provider-main",
        )

        response = await self.client.get("/api/loras?q=denia&limit=12")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["data"]["items"][0]["name"], "denia")

        refresh = await self.client.post(
            "/api/loras/refresh",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(refresh.status, 200)
        self.assertEqual(self.controller.refresh_count, 1)

        metadata = await self.client.post(
            "/api/loras/metadata",
            json={"names": ["denia.safetensors"]},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(metadata.status, 200)
        self.assertEqual(
            self.controller.metadata_payload,
            {"names": ["denia.safetensors"]},
        )

        detail = await self.client.get(
            "/api/loras/detail?name=denia.safetensors"
        )
        self.assertEqual(detail.status, 200)
        self.assertEqual(self.controller.detail_name, "denia.safetensors")

        reviewed = await self.client.put(
            "/api/loras/semantic",
            json={"name": "denia.safetensors", "category": "character"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(reviewed.status, 200)
        self.assertEqual(
            self.controller.semantic_payload,
            {"name": "denia.safetensors", "category": "character"},
        )

        archive = await self.client.post(
            "/api/loras/archive",
            json={"all": True},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(archive.status, 200)
        self.assertEqual(self.controller.archive_payload, {"all": True})

        profile = await self.client.post(
            "/api/config-profiles/switch",
            json={"name": "主工作站"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(profile.status, 200)

        logs = await self.client.get("/api/logs?after=5&limit=25")
        self.assertEqual(logs.status, 200)
        logs_payload = await logs.json()
        self.assertEqual(logs_payload["data"]["entries"][0]["message"], "ready")
        self.assertEqual(self.controller.log_query, (5, 25))

        missing_log_csrf = await self.client.delete("/api/logs")
        self.assertEqual(missing_log_csrf.status, 403)
        clear_logs = await self.client.delete(
            "/api/logs",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(clear_logs.status, 200)
        self.assertEqual(self.controller.logs_cleared, 1)

        tasks = await self.client.get(
            "/api/tasks?limit=12&type=lora_archive&status=running"
        )
        self.assertEqual(tasks.status, 200)
        tasks_payload = await tasks.json()
        self.assertEqual(tasks_payload["data"]["items"][0]["run_id"], "run-123")
        self.assertEqual(
            self.controller.task_query,
            (12, "lora_archive", "running"),
        )

        task = await self.client.get("/api/tasks/run-123")
        self.assertEqual(task.status, 200)
        task_payload = await task.json()
        self.assertEqual(task_payload["data"]["status"], "running")
        self.assertEqual(self.controller.task_run_id, "run-123")

        events = await self.client.get(
            "/api/tasks/run-123/events?after=9&limit=25"
        )
        self.assertEqual(events.status, 200)
        events_payload = await events.json()
        self.assertEqual(events_payload["data"]["cursor"], 10)
        self.assertEqual(
            self.controller.task_event_query,
            ("run-123", 9, 25),
        )

        missing_cancel_csrf = await self.client.post(
            "/api/tasks/run-123/cancel"
        )
        self.assertEqual(missing_cancel_csrf.status, 403)
        cancel = await self.client.post(
            "/api/tasks/run-123/cancel",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(cancel.status, 200)
        self.assertEqual(self.controller.cancelled_task, "run-123")

    async def test_log_query_validation(self) -> None:
        await self._login()
        response = await self.client.get("/api/logs?after=bad")
        self.assertEqual(response.status, 400)

    async def test_task_query_and_identifier_validation(self) -> None:
        await self._login()
        invalid_limit = await self.client.get("/api/tasks?limit=bad")
        self.assertEqual(invalid_limit.status, 400)
        invalid_status = await self.client.get("/api/tasks?status=unknown")
        self.assertEqual(invalid_status.status, 400)
        invalid_type = await self.client.get("/api/tasks?type=" + "x" * 101)
        self.assertEqual(invalid_type.status, 400)
        invalid_event_cursor = await self.client.get(
            "/api/tasks/run-123/events?after=bad"
        )
        self.assertEqual(invalid_event_cursor.status, 400)
        invalid_run_id = await self.client.get("/api/tasks/not%20safe")
        self.assertEqual(invalid_run_id.status, 400)

    async def test_security_headers_are_applied(self) -> None:
        response = await self.client.get("/login")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn(
            "frame-ancestors 'none'", response.headers["Content-Security-Policy"]
        )

        theme = await self.client.get("/assets/theme.js")
        self.assertEqual(theme.status, 200)
        self.assertIn("application/javascript", theme.headers["Content-Type"])
        self.assertIn("comfy-anima-theme", await theme.text())


if __name__ == "__main__":
    unittest.main()
