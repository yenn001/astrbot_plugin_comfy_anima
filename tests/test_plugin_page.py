"""Tests for the AstrBot-native management page adapter."""

import unittest
from pathlib import Path

from ..services.plugin_page import PluginPageActionError, PluginPageApi


class _Controller:
    def __init__(self) -> None:
        self.saved_settings = None
        self.search_query = None
        self.deleted_preset = None
        self.task_event_query = None

    async def web_ui_bootstrap(self):
        return {"version": "test"}

    async def web_ui_save_settings(self, payload):
        self.saved_settings = payload
        return {"message": "saved"}

    async def web_ui_search_loras(self, keyword, limit):
        self.search_query = (keyword, limit)
        return {"items": []}

    async def web_ui_delete_preset(self, identifier):
        self.deleted_preset = identifier
        return {"deleted": identifier}

    async def web_ui_get_task_events(self, run_id, after_seq, limit):
        self.task_event_query = (run_id, after_seq, limit)
        return {"entries": []}


class PluginPageApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.controller = _Controller()
        self.api = PluginPageApi(self.controller)

    async def test_bootstrap_and_lora_search_reuse_controller(self) -> None:
        bootstrap = await self.api.dispatch(
            {"method": "GET", "path": "/api/bootstrap"}
        )
        searched = await self.api.dispatch(
            {
                "method": "GET",
                "path": "/api/loras",
                "query": {"q": "达妮娅", "limit": "20"},
            }
        )
        self.assertEqual(bootstrap["version"], "test")
        self.assertEqual(searched, {"items": []})
        self.assertEqual(self.controller.search_query, ("达妮娅", 20))

    async def test_settings_validate_sampler_override(self) -> None:
        result = await self.api.dispatch(
            {
                "method": "PUT",
                "path": "/api/settings",
                "body": {"sampler_steps_override": "12"},
            }
        )
        self.assertEqual(result, {"message": "saved"})
        self.assertEqual(
            self.controller.saved_settings["sampler_steps_override"],
            12,
        )
        with self.assertRaises(PluginPageActionError):
            await self.api.dispatch(
                {
                    "method": "PUT",
                    "path": "/api/settings",
                    "body": {"sampler_steps_override": "12.5"},
                }
            )

    async def test_encoded_dynamic_identifier_is_decoded_safely(self) -> None:
        result = await self.api.dispatch(
            {
                "method": "DELETE",
                "path": "/api/presets/%E9%A3%8E%E6%A0%BC2%EF%BC%88%E5%87%9B%E7%84%B6%EF%BC%89",
            }
        )
        self.assertEqual(result["deleted"], "风格2（凛然）")
        self.assertEqual(self.controller.deleted_preset, "风格2（凛然）")

    async def test_task_event_query_is_bounded_and_validated(self) -> None:
        await self.api.dispatch(
            {
                "method": "GET",
                "path": "/api/tasks/run_123/events",
                "query": {"after": "7", "limit": "200"},
            }
        )
        self.assertEqual(self.controller.task_event_query, ("run_123", 7, 200))
        with self.assertRaises(PluginPageActionError):
            await self.api.dispatch(
                {
                    "method": "GET",
                    "path": "/api/tasks/not%2Fsafe/events",
                }
            )

    def test_register_uses_plugin_prefixed_gateway_route(self) -> None:
        calls = []

        class Context:
            @staticmethod
            def register_web_api(route, handler, methods, description):
                calls.append((route, handler, methods, description))

        self.assertTrue(self.api.register(Context()))
        self.assertEqual(calls[0][0], "/astrbot_plugin_comfy_anima/api/gateway")
        self.assertEqual(calls[0][2], ["POST"])

    def test_native_page_assets_use_bridge_and_relative_resources(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        index_path = plugin_root / "pages" / "control" / "index.html"
        self.assertTrue(index_path.is_file())
        html = index_path.read_text(encoding="utf-8")
        self.assertIn('/api/plugin/page/bridge-sdk.js', html)
        self.assertIn('src="./app.js"', html)
        self.assertIn('href="./app.css"', html)
        self.assertIn('id="confirm-dialog"', html)
        self.assertIn('value="cancel" formnovalidate', html)
        self.assertNotIn('src="/assets/app.js"', html)

        script = (plugin_root / "pages" / "control" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("window.confirm(", script)
        self.assertNotIn("window.prompt(", script)
        self.assertNotIn("window.location.reload(", script)
        self.assertNotIn("sessionStorage.getItem(autoKey)", script)
        self.assertIn("await loadBootstrap()", script)
        self.assertIn("confirmAction", script)


if __name__ == "__main__":
    unittest.main()
