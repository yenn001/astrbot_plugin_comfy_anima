"""Tests for the authenticated dedicated-port Web UI."""

import base64
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
from ..services.plugin_page import (
    validate_v170_api_payload as native_validate_v170_api_payload,
)
from ..services.web_ui import (
    WebUiError,
    WebUiService,
    validate_v170_api_payload as standalone_validate_v170_api_payload,
)


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
        self.deleted_lora = None
        self.deleted_unet = None
        self.selected_workflow = None
        self.prompt_diagnostic_payload = None
        self.prompt_diagnostics_cleared = 0
        self.deleted_prompt_plan = None
        self.danbooru_updates = 0
        self.danbooru_update_payloads = []
        self.experiment_checks = 0
        self.v170_calls = {}

    async def web_ui_bootstrap(self):
        return {
            "version": "test",
            "settings": {"sampler_steps_override": 0},
            "workflow_runtime": {
                "profile_id": "anima_v2",
                "display_name": "Anima V2 + RTX",
                "workflow_file": "workflow/anima_v2_api.json",
                "sampler_steps_override": 0,
                "samplers": [
                    {
                        "node_id": "19",
                        "label": "Anima KSampler",
                        "steps": 8,
                        "cfg": 5,
                        "denoise": 0.6,
                    }
                ],
            },
        }

    async def web_ui_save_settings(self, payload):
        self.saved_settings = payload
        return {"message": "saved", "reload_scheduled": True}

    async def web_ui_list_providers(self):
        return {
            "selected": "provider-main",
            "selected_prompt": "provider-main",
            "selected_reverse": "provider-vision",
            "selected_embedding": "embedding-main",
            "selected_rerank": "rerank-main",
            "items": [
                {
                    "id": "provider-main",
                    "name": "Main",
                    "model": "gpt-test",
                    "type": "openai_chat_completion",
                    "enabled": True,
                    "available": True,
                    "modalities": ["text"],
                    "supports_image": False,
                }
            ],
            "chat": {
                "selected": "provider-main",
                "items": [
                    {
                        "id": "provider-main",
                        "name": "Main",
                        "model": "gpt-test",
                        "type": "openai_chat_completion",
                        "enabled": True,
                        "available": True,
                        "modalities": ["text"],
                        "supports_image": False,
                    },
                    {
                        "id": "provider-vision",
                        "name": "Vision",
                        "model": "vision-test",
                        "type": "openai_chat_completion",
                        "enabled": True,
                        "available": True,
                        "modalities": ["text", "image"],
                        "supports_image": True,
                    },
                ],
            },
            "embedding": {
                "selected": "embedding-main",
                "items": [{"id": "embedding-main", "available": True}],
            },
            "rerank": {
                "selected": "rerank-main",
                "items": [{"id": "rerank-main", "available": True}],
            },
        }

    async def web_ui_prompt_status(self):
        return {
            "composer": {
                "enabled": True,
                "adaptive_negative_mode": "standard",
                "validation_mode": "report",
                "capacity": 50,
                "count": 1,
            },
            "danbooru": {"ready": True, "tag_count": 12, "alias_count": 3},
            "diagnostics": [{"diagnostic_id": "diag-1", "conflicts": []}],
        }

    async def web_ui_diagnose_prompt(self, payload):
        self.prompt_diagnostic_payload = payload
        return {
            "composed": {
                "positive_prompt": payload["prompt"],
                "negative_prompt": payload.get("negative_prompt", ""),
                "diagnostic_id": "diag-2",
            },
            "layers": {"hard_tags": ["1girl"], "scene_sentence": ""},
            "diagnostics": {"diagnostic_id": "diag-2"},
        }

    async def web_ui_clear_prompt_diagnostics(self):
        self.prompt_diagnostics_cleared += 1
        return {"message": "cleared"}

    async def web_ui_update_danbooru_index(self, payload):
        self.danbooru_updates += 1
        self.danbooru_update_payloads.append(payload)
        return {
            "run_id": "danbooru-run-1",
            "message": "updated",
            "status": {"ready": True},
        }

    async def web_ui_check_experimental_profiles(self):
        self.experiment_checks += 1
        return {"items": [{"id": "artist_mixer", "ready": False}]}

    async def web_ui_prompt_assets_status(self):
        self.v170_calls["asset_status"] = True
        return {"ready": True, "asset_count": 2}

    async def web_ui_prompt_assets_search(self, payload):
        self.v170_calls["asset_search"] = payload
        return {"items": [], "page": payload.get("page", 1)}

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
        return {"imported": 2, "source": "local-runtime", "fingerprint": "f" * 64}

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
        return {
            "composed": {"positive_prompt": "1girl", "negative_prompt": ""},
            "layers": payload["slots"],
            "diagnostics": {},
        }

    async def web_ui_prompt_lab_generate(self, payload):
        self.v170_calls["lab_generate"] = payload
        return {"batch": {"batch_id": "plb-" + "b" * 20}}

    async def web_ui_prompt_lab_confirm(self, payload):
        self.v170_calls["lab_confirm"] = payload
        return {"confirmed": True}

    async def web_ui_list_prompt_plans(self):
        self.v170_calls["prompt_plans_list"] = True
        return {
            "items": [
                {
                    "plan_id": "EX-001",
                    "name": "Rainy neon portrait",
                    "builtin": True,
                },
                {
                    "plan_id": "P-ABC123",
                    "name": "My saved plan",
                    "builtin": False,
                },
            ]
        }

    async def web_ui_delete_prompt_plan(self, payload):
        self.deleted_prompt_plan = payload
        return {"deleted": True, "plan_id": payload["plan_id"]}

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

    async def web_ui_lora_gallery(self, payload):
        self.v170_calls["lora_gallery"] = payload
        return {"items": [], "page": payload.get("page", 1)}

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

    async def web_ui_list_presets(self):
        return {"items": []}

    async def web_ui_save_preset(self, payload):
        return payload

    async def web_ui_delete_preset(self, identifier):
        return {"message": identifier}

    async def web_ui_delete_lora(self, payload):
        self.deleted_lora = payload
        return {"deleted": True, "model_type": "lora"}

    async def web_ui_list_workflows(self):
        return {
            "active": "anima_v2_api.json",
            "items": [
                {
                    "filename": "anima_v2_api.json",
                    "task_type": "text_to_image",
                    "task_label": "生图",
                    "selectable": True,
                    "current": True,
                },
                {
                    "filename": "rtx_upscale_api.json",
                    "task_type": "upscale",
                    "task_label": "独立放大",
                    "selectable": False,
                    "current": False,
                    "reason": "不能设为生图工作流",
                },
            ],
        }

    async def web_ui_select_workflow(self, identifier):
        self.selected_workflow = identifier
        return {"selected": identifier, "message": "switched"}

    async def web_ui_list_unet(self):
        return {"items": []}

    async def web_ui_select_unet(self, identifier):
        return {"name": identifier}

    async def web_ui_delete_unet(self, payload):
        self.deleted_unet = payload
        return {"deleted": True, "model_type": "unet"}

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

    def test_lora_catalog_exposes_model_family_filter_and_active_gate_hint(self) -> None:
        for family_filter in (
            "active",
            "all",
            "anima_legacy_28l",
            "anima_29b_40l",
            "unknown",
        ):
            self.assertIn(f'data-family-filter="{family_filter}"', self.html)
        for identifier in (
            "lora-family-filter-note",
            "family-filter-count-active",
            "family-filter-count-legacy",
            "family-filter-count-29b",
            "family-filter-count-unknown",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("isLoraCompatibleWithActiveProfile", self.javascript)
        self.assertIn("loraMatchesFamilyFilter", self.javascript)
        self.assertIn("patch receipt 仍由提交门禁最终复核", self.javascript)

    def test_workflow_sampler_panel_reads_templates_and_saves_override(self) -> None:
        for identifier in (
            "workflow-profile-id",
            "workflow-profile-name",
            "workflow-profile-file",
            "workflow-sampler-list",
            "sampler-steps-override",
        ):
            with self.subTest(identifier=identifier):
                self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('name="sampler_steps_override"', self.html)
        self.assertIn('min="0" max="100"', self.html)
        self.assertIn("renderWorkflowSamplers(data.workflow_runtime", self.javascript)
        self.assertIn('"sampler_steps_override",', self.javascript)
        self.assertIn("sampler.steps", self.javascript)
        self.assertIn("sampler.cfg", self.javascript)
        self.assertIn("sampler.denoise", self.javascript)
        for identifier in (
            "workflow-select",
            "workflow-refresh",
            "workflow-activate",
            "workflow-select-status",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('api("/api/workflows")', self.javascript)
        self.assertIn('api("/api/workflows/select"', self.javascript)
        self.assertIn("item.selectable", self.javascript)

    def test_asset_delete_ui_uses_exact_names_not_browser_paths(self) -> None:
        self.assertIn('api("/api/loras/delete"', self.javascript)
        self.assertIn('api("/api/unet/delete"', self.javascript)
        self.assertIn("confirm_name: confirmName", self.javascript)
        self.assertIn("请在下方输入完整精确名称", self.javascript)
        self.assertIn("expectedValue: exactName", self.javascript)
        self.assertNotIn("file_path: exactName", self.javascript)

    def test_prompt_workshop_exposes_config_status_and_local_diagnostics(self) -> None:
        fields = (
            "enable_chat_draw_terminal_guard",
            "enable_prompt_composer_v2",
            "adaptive_negative_mode",
            "enable_prompt_diagnostics",
            "prompt_diagnostics_include_content",
            "prompt_diagnostics_capacity",
            "danbooru_validation_mode",
            "danbooru_index_url",
            "danbooru_index_timeout",
            "danbooru_index_max_size_mb",
            "danbooru_api_base_url",
            "danbooru_api_proxy_url",
            "danbooru_api_mode",
            "danbooru_api_general_min_posts",
            "danbooru_api_meta_min_posts",
            "danbooru_api_page_size",
            "danbooru_api_request_interval_ms",
            "danbooru_api_timeout",
            "danbooru_api_max_records",
            "danbooru_api_include_aliases",
        )
        for field in fields:
            with self.subTest(field=field):
                self.assertIn(f'name="{field}"', self.html)
        self.assertIn(
            'name="enable_chat_draw_terminal_guard" type="checkbox" checked disabled',
            self.html,
        )
        self.assertIn(
            "Danbooru guarded 只约束 LLM 声明的角色、作品与画师硬锚点",
            self.html,
        )
        self.assertIn('data-panel="prompt"', self.html)
        self.assertIn('id="panel-prompt"', self.html)
        self.assertIn('id="prompt-diagnostic-form"', self.html)
        for route in (
            "/api/prompt/status",
            "/api/prompt/diagnose",
            "/api/prompt/diagnostics",
            "/api/danbooru/update",
            "/api/experiments/check",
        ):
            self.assertIn(route, self.javascript)
        self.assertIn('value="danbooru_index_update"', self.html)
        self.assertIn('id="prompt-index-update"', self.html)
        self.assertIn('id="prompt-index-official-update"', self.html)
        self.assertIn('id="prompt-index-task"', self.html)
        for element_id in (
            "prompt-index-unique-aliases",
            "prompt-index-ambiguous-aliases",
            "prompt-index-source-updated",
            "prompt-index-source-cutoff",
            "prompt-index-localized",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn(">从URL更新</button>", self.html)
        self.assertIn(">从官方API生成</button>", self.html)
        self.assertIn("updateDanbooruIndex(\"url\")", self.javascript)
        self.assertIn("updateDanbooruIndex(\"official_api\")", self.javascript)
        self.assertIn("if (runId) await openTaskCenter(runId);", self.javascript)
        self.assertIn("index.update_task", self.javascript)
        self.assertIn('name="danbooru_api_base_url" type="url"', self.html)
        self.assertIn('name="danbooru_api_proxy_url" type="url"', self.html)
        self.assertIn('<option value="identity">身份优先</option>', self.html)
        self.assertIn('<option value="full">五类全量</option>', self.html)
        for field in (
            "danbooru_api_general_min_posts",
            "danbooru_api_meta_min_posts",
            "danbooru_api_page_size",
            "danbooru_api_request_interval_ms",
            "danbooru_api_timeout",
            "danbooru_api_max_records",
        ):
            with self.subTest(serialized_number=field):
                self.assertIn(f'"{field}",', self.javascript)
        self.assertIn('"danbooru_api_include_aliases",', self.javascript)
        self.assertIn("settings.danbooru_api_base_url", self.javascript)
        self.assertNotIn("chain-of-thought", self.html.casefold())
        self.assertNotIn("思维链", self.html)

    def test_standalone_and_native_prompt_assets_stay_synchronized(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            (plugin_root / "web" / "app.js").read_bytes(),
            (plugin_root / "pages" / "control" / "app.js").read_bytes(),
        )
        self.assertEqual(
            (plugin_root / "web" / "app.css").read_bytes(),
            (plugin_root / "pages" / "control" / "app.css").read_bytes(),
        )

    def test_anima_29b_page_is_deferred(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        page_root = plugin_root / "web" / "anima_29b"
        html = (page_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("2.9B 控制台已暂缓", html)
        self.assertIn("Deferred Scope", html)
        self.assertNotIn("启用 Anima 2.9B", html)
        self.assertNotIn("2.9B RUNTIME SETTINGS", html)
    def test_preset_editor_supports_alias_note_edit_and_trigger_provenance(self) -> None:
        for field in (
            "identifier",
            "aliases",
            "note",
            "trigger_words",
            "character_canonical",
            "work_canonical",
            "identity_anchor",
            "required_trigger_terms",
            "positive_tags",
            "negative_tags",
            "variant_id",
        ):
            self.assertIn(f'name="{field}"', self.html)
        for identifier in (
            "preset-editor-title",
            "preset-save",
            "preset-cancel-edit",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        for marker in (
            "function editPreset(item)",
            "function resetPresetEditor()",
            "Manager 最新：",
            "最终有效：",
            'identifier: values.get("identifier")',
            'aliases: values.get("aliases")',
            'note: values.get("note")',
            'required_trigger_terms:',
            'positive_tags:',
            'negative_tags:',
            'character_canonical: values.get("character_canonical")',
        ):
            self.assertIn(marker, self.javascript)


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

    def test_v170_backends_share_one_payload_validator(self) -> None:
        self.assertIs(
            standalone_validate_v170_api_payload,
            native_validate_v170_api_payload,
        )
        payload = {
            "query": "dress",
            "asset_type": "clothing",
            "page": 1,
            "page_size": 200,
        }
        self.assertEqual(
            standalone_validate_v170_api_payload("prompt_assets_search", payload),
            native_validate_v170_api_payload("prompt_assets_search", payload),
        )

    def test_prompt_plan_delete_payload_is_shared_bounded_and_custom_only(self) -> None:
        payload = {"plan_id": "P-ABC123"}
        self.assertEqual(
            standalone_validate_v170_api_payload("prompt_plan_delete", payload),
            payload,
        )
        self.assertEqual(
            native_validate_v170_api_payload("prompt_plan_delete", payload),
            payload,
        )
        for invalid in (
            {"plan_id": "EX-001"},
            {"plan_id": "../prompt_plans_v1.json"},
            {"plan_id": ""},
            {"plan_id": 123},
            {},
        ):
            with self.subTest(payload=invalid):
                with self.assertRaises(ValueError):
                    standalone_validate_v170_api_payload(
                        "prompt_plan_delete",
                        invalid,
                    )

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

    async def test_29b_page_is_deferred_and_assets_disabled(self) -> None:
        anonymous = await self.client.get("/anima-29b/", allow_redirects=False)
        self.assertEqual(anonymous.status, 302)
        await self._login()
        page = await self.client.get("/anima-29b/")
        self.assertEqual(page.status, 200)
        text = await page.text()
        self.assertIn("2.9B 控制台已暂缓", text)
        self.assertNotIn("启用 Anima 2.9B", text)
        script = await self.client.get("/anima-29b/assets/app.js")
        self.assertEqual(script.status, 404)

    async def test_v170_routes_reuse_authentication_csrf_and_no_store(self) -> None:
        anonymous = await self.client.get("/api/prompt-assets/status")
        self.assertEqual(anonymous.status, 401)
        self.assertEqual(anonymous.headers["Cache-Control"], "no-store")

        csrf = await self._login()
        missing_csrf = await self.client.post(
            "/api/prompt-assets/search",
            json={"query": "portrait"},
        )
        self.assertEqual(missing_csrf.status, 403)
        missing_delete_csrf = await self.client.delete(
            "/api/loras/thumbnails/cache"
        )
        self.assertEqual(missing_delete_csrf.status, 403)

        status = await self.client.get("/api/prompt-assets/status")
        self.assertEqual(status.status, 200)
        self.assertEqual(status.headers["Cache-Control"], "no-store")
        self.assertTrue(self.controller.v170_calls["asset_status"])

        searched = await self.client.post(
            "/api/prompt-assets/search",
            json={
                "query": "portrait",
                "source": "local-runtime",
                "page": 2,
                "page_size": 200,
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(searched.status, 200)
        self.assertEqual(
            self.controller.v170_calls["asset_search"],
            {
                "query": "portrait",
                "source": "local-runtime",
                "page": 2,
                "page_size": 200,
            },
        )
        facets = await self.client.get(
            "/api/prompt-assets/facets?asset_type=clothing&favorite_only=true&limit=200"
        )
        self.assertEqual(facets.status, 200)
        self.assertEqual(
            self.controller.v170_calls["asset_facets"],
            {"asset_type": "clothing", "favorite_only": True, "limit": 200},
        )

    async def test_prompt_plan_routes_require_auth_and_csrf_and_forward_contract(
        self,
    ) -> None:
        anonymous = await self.client.get("/api/prompt-plans")
        self.assertEqual(anonymous.status, 401)
        self.assertEqual(anonymous.headers["Cache-Control"], "no-store")

        csrf = await self._login()
        listed = await self.client.get("/api/prompt-plans")
        self.assertEqual(listed.status, 200, await listed.text())
        self.assertEqual(listed.headers["Cache-Control"], "no-store")
        listed_payload = await listed.json()
        self.assertEqual(listed_payload["data"]["items"][0]["plan_id"], "EX-001")
        self.assertTrue(self.controller.v170_calls["prompt_plans_list"])

        missing_csrf = await self.client.post(
            "/api/prompt-plans/delete",
            json={"plan_id": "P-ABC123"},
        )
        self.assertEqual(missing_csrf.status, 403)
        self.assertIsNone(self.controller.deleted_prompt_plan)

        deleted = await self.client.post(
            "/api/prompt-plans/delete",
            json={"plan_id": "P-ABC123"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(deleted.status, 200, await deleted.text())
        self.assertEqual(
            self.controller.deleted_prompt_plan,
            {"plan_id": "P-ABC123"},
        )
        self.assertEqual((await deleted.json())["data"]["plan_id"], "P-ABC123")

    async def test_prompt_plan_delete_rejects_builtin_and_unsafe_ids_before_controller(
        self,
    ) -> None:
        csrf = await self._login()
        headers = {"X-CSRF-Token": csrf}
        for payload in (
            {"plan_id": "EX-001"},
            {"plan_id": "../prompt_plans_v1.json"},
            {"plan_id": ""},
            {"plan_id": 123},
            {},
        ):
            with self.subTest(payload=payload):
                response = await self.client.post(
                    "/api/prompt-plans/delete",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(response.status, 400, await response.text())
                self.assertFalse((await response.json())["ok"])
        self.assertIsNone(self.controller.deleted_prompt_plan)

    async def test_v170_management_routes_forward_validated_contracts(self) -> None:
        csrf = await self._login()
        headers = {"X-CSRF-Token": csrf}
        asset_id = "pa_" + "a" * 32
        key = "1" * 64
        fingerprint = "2" * 64

        requests = (
            (
                "post",
                "/api/prompt-assets/facets",
                {"source": "local-runtime", "custom_only": False, "limit": 50},
            ),
            (
                "post",
                "/api/prompt-assets/import",
                {
                    "content": '[{"asset_type":"clothing","name_en":"dress"}]',
                    "format": "json",
                    "source": "unit-test",
                    "provenance": {"version": "1"},
                    "mode": "merge",
                },
            ),
            (
                "post",
                "/api/prompt-assets/update-url",
                {
                    "url": "https://example.test/assets.json",
                    "timeout": 15,
                    "mode": "merge",
                },
            ),
            (
                "post",
                "/api/prompt-assets/sync-local",
                {},
            ),
            (
                "post",
                "/api/prompt-assets/custom",
                {
                    "asset_type": "clothing",
                    "name_en": "dress",
                    "tags": ["white dress"],
                },
            ),
            (
                "put",
                "/api/prompt-assets/custom",
                {"asset_id": asset_id, "changes": {"name_en": "wave 2"}},
            ),
            (
                "put",
                "/api/prompt-assets/favorite",
                {"asset_id": asset_id, "favorite": True},
            ),
            (
                "delete",
                "/api/prompt-assets/custom",
                {"asset_id": asset_id},
            ),
            (
                "post",
                "/api/prompt/compose-slots",
                {
                    "slots": {
                        "identity": ["1girl"],
                        "pose": "standing",
                        "scene_sentence": "She is standing outdoors.",
                    },
                    "locked_slots": ["identity"],
                },
            ),
            (
                "post",
                "/api/prompt-lab/generate",
                {
                    "seed": 42,
                    "count": 6,
                    "base_layers": {"character": ["1girl"]},
                    "asset_pools": {},
                    "locked_layers": ["character"],
                    "asset_library_fingerprint": "a" * 32,
                },
            ),
            (
                "post",
                "/api/prompt-lab/confirm",
                {
                    "batch_id": "plb-" + "b" * 20,
                    "candidate_id": "plc-" + "c" * 20,
                    "asset_library_fingerprint": "a" * 32,
                    "save_plan": True,
                    "plan_name": "My rainy-night plan",
                },
            ),
            (
                "post",
                "/api/loras/gallery",
                {
                    "query": "denia",
                    "categories": ["character"],
                    "metadata_statuses": ["complete"],
                    "preview_statuses": ["cached"],
                    "favorites_only": True,
                    "page": 1,
                    "page_size": 200,
                },
            ),
            (
                "post",
                "/api/loras/thumbnails/warm",
                {"keys": [key], "limit": 200},
            ),
        )
        for method, path, body in requests:
            with self.subTest(path=path):
                response = await getattr(self.client, method)(
                    path,
                    json=body,
                    headers=headers,
                )
                self.assertEqual(response.status, 200, await response.text())

        visual_status = await self.client.get("/api/loras/thumbnails/status")
        self.assertEqual(visual_status.status, 200)
        pruned = await self.client.delete(
            "/api/loras/thumbnails/cache", headers=headers
        )
        self.assertEqual(pruned.status, 200)
        preview = await self.client.get(
            f"/api/loras/preview?key={key}&fingerprint={fingerprint}"
        )
        self.assertEqual(preview.status, 200)
        preview_payload = await preview.json()
        self.assertEqual(preview_payload["data"]["key"], key)
        self.assertNotIn("path", preview_payload["data"])
        self.assertEqual(
            self.controller.v170_calls["lora_preview"],
            (key, fingerprint),
        )

    async def test_v170_bad_body_method_and_bounds_fail_without_controller_call(self) -> None:
        csrf = await self._login()
        headers = {"X-CSRF-Token": csrf}
        invalid_requests = (
            ("/api/prompt-assets/search", {"page_size": 201}),
            ("/api/prompt-assets/facets", {"limit": 201}),
            ("/api/prompt-assets/update-url", {"url": "https://[bad"}),
            (
                "/api/prompt-assets/update-url",
                {"url": "https://example.test:99999/assets.json"},
            ),
            ("/api/prompt-lab/generate", {"seed": 1, "count": 7}),
            ("/api/prompt-lab/generate", {"seed": 2**63, "count": 1}),
            (
                "/api/prompt-lab/confirm",
                {
                    "batch_id": "plb-" + "b" * 20,
                    "candidate_id": "plc-" + "c" * 20,
                    "save_plan": "yes",
                    "plan_name": "My plan",
                },
            ),
            (
                "/api/prompt-lab/confirm",
                {
                    "batch_id": "plb-" + "b" * 20,
                    "candidate_id": "plc-" + "c" * 20,
                    "save_plan": True,
                    "plan_name": "x" * 257,
                },
            ),
            ("/api/loras/gallery", {"page": "1"}),
            ("/api/loras/thumbnails/warm", {"limit": 201}),
            ("/api/loras/thumbnails/warm", {"keys": ["../preview"]}),
        )
        for path, body in invalid_requests:
            with self.subTest(path=path, body=body):
                response = await self.client.post(path, json=body, headers=headers)
                self.assertEqual(response.status, 400)
                payload = await response.json()
                self.assertFalse(payload["ok"])

        malformed = await self.client.post(
            "/api/prompt-assets/search",
            data="{",
            headers={**headers, "Content-Type": "application/json"},
        )
        self.assertEqual(malformed.status, 400)
        self.assertFalse((await malformed.json())["ok"])

        oversized = await self.client.post(
            "/api/prompt-assets/import",
            json={
                "content": "x" * (1024 * 1024),
                "format": "csv",
                "source": "unit-test",
            },
            headers=headers,
        )
        self.assertEqual(oversized.status, 413)
        self.assertFalse((await oversized.json())["ok"])

        unsafe_preview = await self.client.get(
            "/api/loras/preview?key=..%2Fsecret&fingerprint=" + "2" * 64
        )
        self.assertEqual(unsafe_preview.status, 400)
        wrong_method = await self.client.get("/api/prompt-assets/search")
        self.assertEqual(wrong_method.status, 405)

    async def test_sampler_steps_override_is_normalized_and_range_checked(self) -> None:
        csrf = await self._login()
        saved = await self.client.put(
            "/api/settings",
            json={"sampler_steps_override": 24},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(saved.status, 200)
        self.assertEqual(
            self.controller.saved_settings,
            {"sampler_steps_override": 24},
        )

        for invalid in (-1, 101, 2.5, True, "abc"):
            with self.subTest(value=invalid):
                response = await self.client.put(
                    "/api/settings",
                    json={"sampler_steps_override": invalid},
                    headers={"X-CSRF-Token": csrf},
                )
                self.assertEqual(response.status, 400)

    async def test_bootstrap_exposes_workflow_sampler_runtime(self) -> None:
        await self._login()
        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        runtime = payload["data"]["workflow_runtime"]
        self.assertEqual(runtime["profile_id"], "anima_v2")
        self.assertEqual(runtime["samplers"][0]["node_id"], "19")
        self.assertEqual(runtime["samplers"][0]["steps"], 8)

    async def test_authenticated_routes_forward_to_controller(self) -> None:
        csrf = await self._login()
        providers = await self.client.get("/api/providers")
        self.assertEqual(providers.status, 200)
        provider_payload = await providers.json()
        self.assertEqual(
            provider_payload["data"]["items"][0]["id"],
            "provider-main",
        )
        self.assertEqual(
            provider_payload["data"]["selected_reverse"],
            "provider-vision",
        )
        self.assertEqual(
            provider_payload["data"]["selected_embedding"],
            "embedding-main",
        )
        self.assertEqual(
            provider_payload["data"]["selected_rerank"],
            "rerank-main",
        )
        self.assertTrue(
            provider_payload["data"]["chat"]["items"][1]["supports_image"]
        )

        prompt_status = await self.client.get("/api/prompt/status")
        self.assertEqual(prompt_status.status, 200)
        prompt_status_payload = await prompt_status.json()
        self.assertEqual(
            prompt_status_payload["data"]["danbooru"]["tag_count"],
            12,
        )

        diagnosed = await self.client.post(
            "/api/prompt/diagnose",
            json={"prompt": "1girl, portrait", "negative_prompt": "text"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(diagnosed.status, 200)
        self.assertEqual(
            self.controller.prompt_diagnostic_payload,
            {"prompt": "1girl, portrait", "negative_prompt": "text"},
        )

        cleared = await self.client.delete(
            "/api/prompt/diagnostics",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(cleared.status, 200)
        self.assertEqual(self.controller.prompt_diagnostics_cleared, 1)

        missing_danbooru_csrf = await self.client.post(
            "/api/danbooru/update",
            json={"mode": "official_api"},
        )
        self.assertEqual(missing_danbooru_csrf.status, 403)

        updated = await self.client.post(
            "/api/danbooru/update",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(updated.status, 200)
        self.assertEqual(self.controller.danbooru_updates, 1)
        self.assertEqual(
            self.controller.danbooru_update_payloads[-1],
            {"mode": "url"},
        )
        updated_payload = await updated.json()
        self.assertEqual(updated_payload["data"]["run_id"], "danbooru-run-1")

        official = await self.client.post(
            "/api/danbooru/update",
            json={"mode": "official_api"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(official.status, 200)
        self.assertEqual(
            self.controller.danbooru_update_payloads[-1],
            {"mode": "official_api"},
        )

        invalid_mode = await self.client.post(
            "/api/danbooru/update",
            json={"mode": "db_export"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(invalid_mode.status, 400)
        extra_field = await self.client.post(
            "/api/danbooru/update",
            json={"mode": "url", "url": "https://example.test"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(extra_field.status, 400)

        experiments = await self.client.get("/api/experiments/check")
        self.assertEqual(experiments.status, 200)
        self.assertEqual(self.controller.experiment_checks, 1)

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

        lora_delete_payload = {
            "exact_name": "characters/denia.safetensors",
            "confirm_name": "characters/denia.safetensors",
            "remove_from_presets": False,
        }
        deleted_lora = await self.client.post(
            "/api/loras/delete",
            json=lora_delete_payload,
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(deleted_lora.status, 200)
        self.assertEqual(self.controller.deleted_lora, lora_delete_payload)

        unet_delete_payload = {
            "exact_name": "models/anima-old.safetensors",
            "confirm_name": "models/anima-old.safetensors",
        }
        deleted_unet = await self.client.post(
            "/api/unet/delete",
            json=unet_delete_payload,
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(deleted_unet.status, 200)
        self.assertEqual(self.controller.deleted_unet, unet_delete_payload)

        workflows = await self.client.get("/api/workflows")
        self.assertEqual(workflows.status, 200)
        workflow_payload = await workflows.json()
        self.assertEqual(
            workflow_payload["data"]["items"][1]["task_type"],
            "upscale",
        )
        switched = await self.client.post(
            "/api/workflows/select",
            json={"identifier": "anima_v2_api.json"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(switched.status, 200)
        self.assertEqual(
            self.controller.selected_workflow,
            "anima_v2_api.json",
        )

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
