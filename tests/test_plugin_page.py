"""Tests for the AstrBot-native management page adapter."""

import base64
import sys
import types
import unittest
from unittest import mock
from pathlib import Path

from ..services.plugin_page import (
    PluginPageActionError,
    PluginPageApi,
    V170ApiValidationError,
    decode_plugin_gateway_body,
)


class _Controller:
    def __init__(self) -> None:
        self.saved_settings = None
        self.search_query = None
        self.deleted_preset = None
        self.task_event_query = None
        self.selected_workflow = None
        self.prompt_diagnostic_payload = None
        self.prompt_diagnostics_cleared = 0
        self.danbooru_updates = 0
        self.v170_calls = {}

    async def web_ui_bootstrap(self):
        return {"version": "test"}

    async def web_ui_save_settings(self, payload):
        self.saved_settings = payload
        return {"message": "saved"}

    async def web_ui_list_providers(self):
        return {
            "selected_prompt": "chat-main",
            "selected_reverse": "chat-vision",
            "selected_embedding": "embedding-main",
            "selected_rerank": "rerank-main",
            "chat": {"items": []},
            "embedding": {"items": []},
            "rerank": {"items": []},
        }

    async def web_ui_prompt_status(self):
        return {"composer": {"enabled": True}, "diagnostics": []}

    async def web_ui_diagnose_prompt(self, payload):
        self.prompt_diagnostic_payload = payload
        return {"composed": {"positive_prompt": payload["prompt"]}}

    async def web_ui_clear_prompt_diagnostics(self):
        self.prompt_diagnostics_cleared += 1
        return {"message": "cleared"}

    async def web_ui_update_danbooru_index(self):
        self.danbooru_updates += 1
        return {"message": "updated"}

    async def web_ui_check_experimental_profiles(self):
        return {"items": [{"id": "artist_mixer", "ready": False}]}

    async def web_ui_prompt_assets_status(self):
        self.v170_calls["asset_status"] = True
        return {"ready": True}

    async def web_ui_prompt_assets_search(self, payload):
        self.v170_calls["asset_search"] = payload
        return {"items": []}

    async def web_ui_prompt_assets_facets(self, payload):
        self.v170_calls["asset_facets"] = payload
        return {"types": [], "sources": []}

    async def web_ui_prompt_assets_import(self, payload):
        self.v170_calls["asset_import"] = payload
        return {"imported": 1}

    async def web_ui_prompt_assets_update_url(self, payload):
        self.v170_calls["asset_update_url"] = payload
        return {"updated": True}

    async def web_ui_prompt_assets_sync_local(self, payload=None):
        self.v170_calls["asset_sync_local"] = payload or {}
        return {"imported": 2, "fingerprint": "f" * 64}

    async def web_ui_prompt_asset_create(self, payload):
        self.v170_calls["asset_create"] = payload
        return {"asset_id": "pa_" + "a" * 32}

    async def web_ui_prompt_asset_update(self, payload):
        self.v170_calls["asset_update"] = payload
        return {"asset_id": payload["asset_id"]}

    async def web_ui_prompt_asset_delete(self, payload):
        self.v170_calls["asset_delete"] = payload
        return {"deleted": True}

    async def web_ui_prompt_asset_favorite(self, payload):
        self.v170_calls["asset_favorite"] = payload
        return {"favorite": payload["favorite"]}

    async def web_ui_compose_prompt_slots(self, payload):
        self.v170_calls["compose_slots"] = payload
        return {"layers": payload["slots"]}

    async def web_ui_prompt_lab_generate(self, payload):
        self.v170_calls["lab_generate"] = payload
        return {"batch": {"batch_id": "plb-" + "b" * 20}}

    async def web_ui_prompt_lab_confirm(self, payload):
        self.v170_calls["lab_confirm"] = payload
        return {"confirmed": True}

    async def web_ui_search_loras(self, keyword, limit):
        self.search_query = (keyword, limit)
        return {"items": []}

    async def web_ui_lora_gallery(self, payload):
        self.v170_calls["lora_gallery"] = payload
        return {"items": []}

    async def web_ui_lora_visual_warm(self, payload):
        self.v170_calls["lora_warm"] = payload
        return {"accepted": payload.get("limit", 0)}

    async def web_ui_lora_visual_status(self):
        self.v170_calls["lora_status"] = True
        return {"queued": 0}

    async def web_ui_lora_visual_prune(self):
        self.v170_calls["lora_prune"] = True
        return {"removed": 1}

    async def web_ui_lora_preview(self, key, fingerprint):
        self.v170_calls["lora_preview"] = (key, fingerprint)
        raw = b"png"
        return {
            "key": key,
            "fingerprint": fingerprint,
            "media_type": "image/png",
            "size": len(raw),
            "data_url": "data:image/png;base64,"
            + base64.b64encode(raw).decode("ascii"),
        }

    async def web_ui_delete_preset(self, identifier):
        self.deleted_preset = identifier
        return {"deleted": identifier}

    async def web_ui_list_workflows(self):
        return {"active": "anima.json", "items": []}

    async def web_ui_select_workflow(self, identifier):
        self.selected_workflow = identifier
        return {"selected": identifier}

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

    async def test_provider_catalog_reuses_controller_without_flattening_groups(self) -> None:
        result = await self.api.dispatch(
            {"method": "GET", "path": "/api/providers"}
        )

        self.assertEqual(result["selected_prompt"], "chat-main")
        self.assertEqual(result["selected_reverse"], "chat-vision")
        self.assertEqual(result["selected_embedding"], "embedding-main")
        self.assertEqual(result["selected_rerank"], "rerank-main")
        self.assertIn("embedding", result)
        self.assertIn("rerank", result)

    async def test_prompt_workshop_routes_reuse_controller(self) -> None:
        status = await self.api.dispatch(
            {"method": "GET", "path": "/api/prompt/status"}
        )
        diagnosed = await self.api.dispatch(
            {
                "method": "POST",
                "path": "/api/prompt/diagnose",
                "body": {"prompt": "1girl, portrait", "negative_prompt": "text"},
            }
        )
        cleared = await self.api.dispatch(
            {"method": "DELETE", "path": "/api/prompt/diagnostics"}
        )
        updated = await self.api.dispatch(
            {"method": "POST", "path": "/api/danbooru/update"}
        )
        experiments = await self.api.dispatch(
            {"method": "GET", "path": "/api/experiments/check"}
        )

        self.assertTrue(status["composer"]["enabled"])
        self.assertEqual(diagnosed["composed"]["positive_prompt"], "1girl, portrait")
        self.assertEqual(
            self.controller.prompt_diagnostic_payload,
            {"prompt": "1girl, portrait", "negative_prompt": "text"},
        )
        self.assertEqual(cleared["message"], "cleared")
        self.assertEqual(self.controller.prompt_diagnostics_cleared, 1)
        self.assertEqual(updated["message"], "updated")
        self.assertEqual(self.controller.danbooru_updates, 1)
        self.assertEqual(experiments["items"][0]["id"], "artist_mixer")

        with self.assertRaises(PluginPageActionError):
            await self.api.dispatch(
                {
                    "method": "POST",
                    "path": "/api/prompt/diagnose",
                    "body": {"prompt": ""},
                }
            )

    async def test_v170_routes_reuse_shared_controller_contract(self) -> None:
        asset_id = "pa_" + "a" * 32
        key = "1" * 64
        fingerprint = "2" * 64

        status = await self.api.dispatch(
            {"method": "GET", "path": "/api/prompt-assets/status"}
        )
        self.assertTrue(status["ready"])

        calls = (
            (
                "POST",
                "/api/prompt-assets/search",
                {
                    "query": "dress",
                    "source": "local-runtime",
                    "asset_type": "clothing",
                    "page_size": 200,
                },
                "asset_search",
            ),
            (
                "POST",
                "/api/prompt-assets/facets",
                {"source": "local-runtime", "favorite_only": True, "limit": 200},
                "asset_facets",
            ),
            (
                "POST",
                "/api/prompt-assets/import",
                {
                    "text": '[{"asset_type":"clothing","name_en":"dress"}]',
                    "content_type": "application/json",
                    "source": "unit-test",
                    "mode": "merge",
                },
                "asset_import",
            ),
            (
                "POST",
                "/api/prompt-assets/update-url",
                {"url": "https://example.test/assets.csv", "timeout": 20},
                "asset_update_url",
            ),
            (
                "POST",
                "/api/prompt-assets/sync-local",
                {},
                "asset_sync_local",
            ),
            (
                "POST",
                "/api/prompt-assets/custom",
                {"asset_type": "clothing", "name_en": "dress"},
                "asset_create",
            ),
            (
                "PUT",
                "/api/prompt-assets/custom",
                {"asset_id": asset_id, "changes": {"name_en": "dress 2"}},
                "asset_update",
            ),
            (
                "PUT",
                "/api/prompt-assets/favorite",
                {"asset_id": asset_id, "favorite": True},
                "asset_favorite",
            ),
            (
                "DELETE",
                "/api/prompt-assets/custom",
                {"asset_id": asset_id},
                "asset_delete",
            ),
            (
                "POST",
                "/api/prompt/compose-slots",
                {
                    "slots": {
                        "identity": ["1girl"],
                        "clothing": "white dress",
                        "relation": "She is standing outdoors.",
                    },
                    "locked_slots": ["identity"],
                },
                "compose_slots",
            ),
            (
                "POST",
                "/api/prompt-lab/generate",
                {
                    "seed": "fixed-seed",
                    "count": 6,
                    "asset_pools": {},
                    "asset_library_fingerprint": "a" * 32,
                },
                "lab_generate",
            ),
            (
                "POST",
                "/api/prompt-lab/confirm",
                {
                    "batch_id": "plb-" + "b" * 20,
                    "selection": 1,
                    "asset_library_fingerprint": "a" * 32,
                },
                "lab_confirm",
            ),
            (
                "POST",
                "/api/loras/gallery",
                {
                    "query": "denia",
                    "favorites_only": True,
                    "page": 1,
                    "page_size": 200,
                },
                "lora_gallery",
            ),
            (
                "POST",
                "/api/loras/thumbnails/warm",
                {"keys": [key], "limit": 200},
                "lora_warm",
            ),
        )
        for method, path, body, call_key in calls:
            with self.subTest(path=path):
                await self.api.dispatch(
                    {"method": method, "path": path, "body": body}
                )
                self.assertEqual(self.controller.v170_calls[call_key], body)

        visual_status = await self.api.dispatch(
            {"method": "GET", "path": "/api/loras/thumbnails/status"}
        )
        self.assertEqual(visual_status["queued"], 0)
        pruned = await self.api.dispatch(
            {"method": "DELETE", "path": "/api/loras/thumbnails/cache"}
        )
        self.assertEqual(pruned["removed"], 1)
        preview = await self.api.dispatch(
            {
                "method": "GET",
                "path": "/api/loras/preview",
                "query": {"key": key, "fingerprint": fingerprint},
            }
        )
        self.assertEqual(preview["key"], key)
        self.assertNotIn("path", preview)
        self.assertEqual(
            self.controller.v170_calls["lora_preview"],
            (key, fingerprint),
        )
        facets = await self.api.dispatch(
            {
                "method": "GET",
                "path": "/api/prompt-assets/facets",
                "query": {
                    "asset_type": "clothing",
                    "custom_only": "false",
                    "limit": "50",
                },
            }
        )
        self.assertEqual(facets, {"types": [], "sources": []})
        self.assertEqual(
            self.controller.v170_calls["asset_facets"],
            {"asset_type": "clothing", "custom_only": False, "limit": 50},
        )

    async def test_v170_bad_body_method_and_bounds_fail_safely(self) -> None:
        invalid_envelopes = (
            {
                "method": "POST",
                "path": "/api/prompt-assets/search",
                "body": {"page_size": 201},
            },
            {
                "method": "POST",
                "path": "/api/prompt-assets/update-url",
                "body": {"url": "https://[bad"},
            },
            {
                "method": "POST",
                "path": "/api/prompt-assets/update-url",
                "body": {"url": "https://example.test:99999/assets.json"},
            },
            {
                "method": "GET",
                "path": "/api/prompt-assets/facets",
                "query": {"favorite_only": "sometimes"},
            },
            {
                "method": "POST",
                "path": "/api/prompt-assets/search",
                "body": {"asset_type": "outfit"},
            },
            {
                "method": "POST",
                "path": "/api/prompt-lab/generate",
                "body": {"seed": 1, "count": 7},
            },
            {
                "method": "POST",
                "path": "/api/loras/gallery",
                "body": {"page": "1"},
            },
            {
                "method": "POST",
                "path": "/api/loras/thumbnails/warm",
                "body": {"limit": 201},
            },
            {
                "method": "POST",
                "path": "/api/loras/thumbnails/warm",
                "body": {"keys": ["../preview"]},
            },
            {
                "method": "GET",
                "path": "/api/loras/preview",
                "query": {"key": "../../secret", "fingerprint": "2" * 64},
            },
            {
                "method": "POST",
                "path": "/api/prompt-assets/import",
                "body": {"content": "x" * (1024 * 1024), "source": "test"},
            },
            {
                "method": "POST",
                "path": "/api/prompt-assets/search",
                "body": [],
            },
            {"method": "PATCH", "path": "/api/prompt-assets/custom", "body": {}},
            {"method": "GET", "path": "/api/prompt-assets/search", "body": {}},
        )
        for envelope in invalid_envelopes:
            with self.subTest(envelope={**envelope, "body": "<omitted>"}):
                with self.assertRaises((PluginPageActionError, ValueError)):
                    await self.api.dispatch(envelope)

    def test_native_gateway_body_is_capped_before_json_dispatch(self) -> None:
        envelope = b'{"method":"GET","path":"/api/prompt-assets/status"}'
        self.assertEqual(
            decode_plugin_gateway_body(envelope, str(len(envelope)))["method"],
            "GET",
        )
        with self.assertRaises(V170ApiValidationError):
            decode_plugin_gateway_body(envelope, str(1024 * 1024 + 1))
        with self.assertRaises(V170ApiValidationError):
            decode_plugin_gateway_body(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(V170ApiValidationError):
            decode_plugin_gateway_body(b"[]")

    async def test_native_gateway_rejects_declared_oversize_before_body_read(self) -> None:
        body_reads = 0

        class Request:
            headers = {"content-length": str(1024 * 1024 + 1)}

            @staticmethod
            async def body():
                nonlocal body_reads
                body_reads += 1
                return b"{}"

        web_api = types.ModuleType("astrbot.api.web")
        web_api.request = Request()
        web_api.error_response = lambda message, status_code=400, **_kwargs: {
            "message": message,
            "status_code": status_code,
        }
        web_api.json_response = lambda data, **_kwargs: data
        astrbot = types.ModuleType("astrbot")
        api = types.ModuleType("astrbot.api")
        api.logger = types.SimpleNamespace(error=lambda *_args, **_kwargs: None)

        with mock.patch.dict(
            sys.modules,
            {
                "astrbot": astrbot,
                "astrbot.api": api,
                "astrbot.api.web": web_api,
            },
        ):
            result = await self.api.handle()

        self.assertEqual(result["status_code"], 413)
        self.assertEqual(body_reads, 0)

    async def test_workflow_routes_reuse_safe_controller_operations(self) -> None:
        listed = await self.api.dispatch(
            {"method": "GET", "path": "/api/workflows"}
        )
        selected = await self.api.dispatch(
            {
                "method": "POST",
                "path": "/api/workflows/select",
                "body": {"identifier": "anima_v2_api.json"},
            }
        )

        self.assertEqual(listed["active"], "anima.json")
        self.assertEqual(selected["selected"], "anima_v2_api.json")
        self.assertEqual(self.controller.selected_workflow, "anima_v2_api.json")

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

    def test_both_webui_builds_have_four_provider_selectors_and_vision_tristate(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        for relative_root in (Path("web"), Path("pages") / "control"):
            with self.subTest(root=str(relative_root)):
                html = (plugin_root / relative_root / "index.html").read_text(
                    encoding="utf-8"
                )
                script = (plugin_root / relative_root / "app.js").read_text(
                    encoding="utf-8"
                )
                for field_name in (
                    "prompt_llm_provider_id",
                    "reverse_prompt_provider_id",
                    "lora_embedding_provider_id",
                    "lora_rerank_provider_id",
                ):
                    self.assertIn(f'name="{field_name}"', html)
                for selection_key in (
                    "selected_prompt",
                    "selected_reverse",
                    "selected_embedding",
                    "selected_rerank",
                ):
                    self.assertIn(selection_key, script)
                self.assertIn("item.supports_image === true", script)
                self.assertIn("item.supports_image === false", script)
                self.assertIn("selectedItem.supports_image !== false", script)
                for identifier in (
                    "workflow-select",
                    "workflow-refresh",
                    "workflow-activate",
                    "workflow-tool-title",
                    "workflow-tool-list",
                ):
                    self.assertIn(f'id="{identifier}"', html)
                self.assertIn('api("/api/workflows")', script)
                self.assertIn('api("/api/workflows/select"', script)
                self.assertIn("function renderWorkflowTools()", script)
                self.assertIn("data.generation_items", script)
                self.assertIn("data.tool_items", script)
                self.assertNotIn(
                    'body: JSON.stringify({identifier: item.filename, tool:',
                    script,
                )

    def test_both_webui_builds_expose_prompt_workshop_contract(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        fields = (
            "enable_prompt_composer_v2",
            "adaptive_negative_mode",
            "enable_prompt_diagnostics",
            "prompt_diagnostics_include_content",
            "prompt_diagnostics_capacity",
            "danbooru_validation_mode",
            "danbooru_index_url",
            "danbooru_index_timeout",
            "danbooru_index_max_size_mb",
        )
        scripts = []
        styles = []
        for relative_root in (Path("web"), Path("pages") / "control"):
            html = (plugin_root / relative_root / "index.html").read_text(
                encoding="utf-8"
            )
            script = (plugin_root / relative_root / "app.js").read_text(
                encoding="utf-8"
            )
            scripts.append(script)
            styles.append(
                (plugin_root / relative_root / "app.css").read_text(encoding="utf-8")
            )
            self.assertIn('data-panel="prompt"', html)
            self.assertIn('id="panel-prompt"', html)
            for field in fields:
                self.assertIn(f'name="{field}"', html)
            for route in (
                "/api/prompt/status",
                "/api/prompt/diagnose",
                "/api/prompt/diagnostics",
                "/api/danbooru/update",
                "/api/experiments/check",
            ):
                self.assertIn(route, script)
        self.assertEqual(scripts[0], scripts[1])
        self.assertEqual(styles[0], styles[1])


if __name__ == "__main__":
    unittest.main()
