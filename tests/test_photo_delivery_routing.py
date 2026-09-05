"""Photo-delivery routing tests: immersive requests never stop the main LLM."""

import importlib
import sys
import types
import unittest
from pathlib import Path

from ..services.response_envelope import (
    EXTRAS_KEY,
    BundleKind,
    ReceiptState,
)
from ._stubs import make_gate_payload


class _FilterStub:
    class PlatformAdapterType:
        AIOCQHTTP = "aiocqhttp"

    class EventMessageType:
        ALL = "all"

    class PermissionType:
        ADMIN = "admin"

    @staticmethod
    def _passthrough(*_args, **_kwargs):
        return lambda function: function

    @staticmethod
    def command_group(*_args, **_kwargs):
        class _Group:
            def command(self, *_args, **_kwargs):
                return lambda function: function

        return lambda function: _Group()

    command = _passthrough
    llm_tool = _passthrough
    permission_type = _passthrough
    platform_adapter_type = _passthrough
    event_message_type = _passthrough
    on_llm_request = _passthrough
    on_decorating_result = _passthrough
    on_using_llm_tool = _passthrough
    on_llm_tool_respond = _passthrough
    on_agent_done = _passthrough
    after_message_sent = _passthrough


class _Star:
    def __init__(self, context):
        self.context = context


def _install_astrbot_stubs() -> None:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")

    api.logger = types.SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    event.AstrMessageEvent = object
    event.filter = _FilterStub
    star.Context = object
    star.Star = _Star
    star.register = lambda *_args, **_kwargs: (lambda cls: cls)
    components.Plain = lambda text: types.SimpleNamespace(text=text)
    components.Image = types.SimpleNamespace
    components.Node = types.SimpleNamespace

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.api.message_components": components,
        }
    )


class PhotoDeliveryRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _fake_judge(decision: str) -> object:
        class FakeJudge:
            async def judge(self, message: str, bot: str) -> object:
                return types.SimpleNamespace(
                    decision=decision,
                    confidence=0.9,
                    backend_used="test",
                    reason="test",
                    latency_ms=0.0,
                    trace={},
                )

        return FakeJudge()

    def test_named_photo_request_is_photo_not_command(self) -> None:
        self.assertTrue(
            self.main.ComfyAnimaPlugin._looks_like_photo_delivery_request(
                "我想看娅娅的照片"
            )
        )
        self.assertFalse(
            self.main.ComfyAnimaPlugin._looks_like_draw_command(
                "我想看娅娅的照片"
            )
        )

    def test_pronoun_photo_request_matches_same_path(self) -> None:
        self.assertTrue(
            self.main.ComfyAnimaPlugin._looks_like_photo_delivery_request(
                "我想看你的照片"
            )
        )

    def test_explicit_draw_command_is_command_not_photo(self) -> None:
        self.assertTrue(
            self.main.ComfyAnimaPlugin._looks_like_draw_command(
                "画一张达妮娅自拍"
            )
        )
        self.assertFalse(
            self.main.ComfyAnimaPlugin._looks_like_photo_delivery_request(
                "画一张达妮娅自拍"
            )
        )

    def test_parenthetical_draw_does_not_upgrade_photo(self) -> None:
        self.assertTrue(
            self.main.ComfyAnimaPlugin._looks_like_photo_delivery_request(
                "想看看你现在的样子（画出来）"
            )
        )
        self.assertFalse(
            self.main.ComfyAnimaPlugin._looks_like_draw_command(
                "想看看你现在的样子（画出来）"
            )
        )

    def test_photo_only_natural_draw_returns_before_director(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True,
            director_primary=True,
        )
        plugin._event_has_explicit_command_route = lambda _event: False

        async def collect():
            event = types.SimpleNamespace(message_str="我想看娅娅的照片")
            return [item async for item in plugin._natural_language_draw_impl(event)]

        import asyncio

        replies = asyncio.run(collect())
        self.assertEqual(replies, [])

    def test_photo_only_pre_creates_draw_bundle_before_return(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True,
            director_primary=True,
        )
        plugin._event_has_explicit_command_route = lambda _event: False
        plugin._build_intent_judge_service = lambda: self._fake_judge(
            self.main.DRAW_NOW
        )
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: True
        )

        class Event:
            message_str = "我想看娅娅的照片"

            def __init__(self):
                self._extras = {}

            def get_extra(self, key, default=None):
                return self._extras.get(key, default)

            def set_extra(self, key, value):
                self._extras[key] = value

        event = Event()
        event.set_extra(
            "astrbot_plugin_comfy_anima:intent_router_gate_result",
            make_gate_payload(self.main, self.main.DRAW_NOW, "我想看娅娅的照片"),
        )

        async def collect():
            return [item async for item in plugin._natural_language_draw_impl(event)]

        import asyncio

        self.assertEqual(asyncio.run(collect()), [])
        envelope = event.get_extra(EXTRAS_KEY)
        self.assertIsNotNone(envelope)
        self.assertIsNotNone(envelope.draw_bundle)

    def test_after_send_hook_rejects_missing_output(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace()

        class Event:
            def __init__(self):
                self._extras = {}

            def get_extra(self, key, default=None):
                return self._extras.get(key, default)

            def set_extra(self, key, value):
                self._extras[key] = value

        event = Event()
        ledger = plugin._response_ledger(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        bundle = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="run-1")
        ledger.attach_output(
            bundle.bundle_id,
            run_id="run-1",
            output_path="/missing/out.png",
            output_sha256="abc",
        )

        import asyncio

        asyncio.run(plugin.record_delivery_send_attempt(event))
        envelope = ledger.envelope()
        assert envelope is not None
        receipt = envelope.image_bundle.receipt
        assert receipt is not None
        self.assertEqual(receipt.status, ReceiptState.FAILED)
        self.assertEqual(receipt.last_error, "output_file_missing")

    def test_ordinary_message_does_not_begin_drawing_session(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True, director_primary=False
        )
        plugin._event_has_explicit_command_route = lambda _event: False
        plugin._event_drawing_keys = lambda _event: ("key",)
        plugin._build_intent_judge_service = lambda: self._fake_judge(
            self.main.NO_DRAW
        )

        class Orchestrator:
            def __init__(self):
                self.begins = 0
                self.ends = 0

            def begin_umo_drawing(self, _key):
                self.begins += 1

            def end_umo_drawing(self, _key):
                self.ends += 1

        plugin._orchestrator = Orchestrator()
        plugin._get_drawing_orchestrator = lambda: plugin._orchestrator
        orchestrator = plugin._orchestrator

        async def collect(message):
            event = types.SimpleNamespace(message_str=message)
            return [item async for item in plugin._natural_language_draw_impl(event)]

        import asyncio

        asyncio.run(collect("普通聊天"))
        self.assertEqual(orchestrator.begins, 0)
        self.assertEqual(orchestrator.ends, 0)

    def test_draw_command_begins_and_ends_drawing_session(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True, director_primary=False
        )
        plugin._event_has_explicit_command_route = lambda _event: False
        plugin._event_drawing_keys = lambda _event: ("key",)
        plugin._access_error = lambda *_args: "blocked for test"
        plugin._build_intent_judge_service = lambda: self._fake_judge(
            self.main.DRAW_NOW
        )
        plugin._intent_decision_ledger = types.SimpleNamespace(
            verify=lambda decision_id, expected: True
        )

        class Orchestrator:
            def __init__(self):
                self.begins = 0
                self.ends = 0

            def begin_umo_drawing(self, _key):
                self.begins += 1

            def end_umo_drawing(self, _key):
                self.ends += 1

        plugin._orchestrator = Orchestrator()
        plugin._get_drawing_orchestrator = lambda: plugin._orchestrator
        orchestrator = plugin._orchestrator

        async def collect(message):
            draw_now = self.main.DRAW_NOW
            payload = make_gate_payload(self.main, draw_now, message)

            class Event:
                message_str = message

                def __init__(self):
                    self._extras = {
                        "astrbot_plugin_comfy_anima:intent_router_gate_result": payload
                    }
                    self.stopped = False

                def get_extra(self, key, default=None):
                    return self._extras.get(key, default)

                def set_extra(self, key, value):
                    self._extras[key] = value

                def stop_event(self):
                    self.stopped = True

                @staticmethod
                def plain_result(text):
                    return text

            return [
                item
                async for item in plugin._natural_language_draw_impl(Event())
            ]

        import asyncio

        asyncio.run(collect("画一张猫"))
        self.assertEqual(orchestrator.begins, 1)
        self.assertEqual(orchestrator.ends, 1)

    def test_semantic_alias_subject_detection(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._semantic_index = types.SimpleNamespace(
            entries={
                "k": types.SimpleNamespace(
                    name="denia_lorav4",
                    aliases=("达妮娅", "denia"),
                    character_name="Denia",
                    character_canonical="denia_(wuthering_waves)",
                )
            }
        )
        self.assertEqual(
            plugin._requested_subject_hint("画一张达妮娅自拍"),
            "达妮娅",
        )

    def test_character_preset_has_priority_for_named_subject(self) -> None:
        from ..services.lora_presets import LoraPreset

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_presets = types.SimpleNamespace(
            list_presets=lambda category=None: (
                LoraPreset(
                    name="达妮娅",
                    category="character",
                    selections=(),
                ),
            )
        )
        self.assertEqual(
            plugin._subject_character_preset("达妮娅").name,
            "达妮娅",
        )
        self.assertIsNone(plugin._subject_character_preset("调月莉音"))

    def test_single_character_authority_uses_preset_anchor(self) -> None:
        from ..services.lora_presets import LoraPreset

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._requested_subject_hint = lambda message: "达妮娅"
        plugin._subject_character_preset = lambda subject: LoraPreset(
            name="达妮娅",
            category="character",
            selections=(),
            identity_anchor="denia_(wuthering_waves)",
        )
        authority = plugin._single_character_authority("画一张达妮娅")
        self.assertEqual(authority.identity_anchor, "denia_(wuthering_waves)")

    def test_production_routing_does_not_call_compat_union(self) -> None:
        source = Path(self.main.__file__).read_text(encoding="utf-8")
        impl = source[
            source.index("async def _natural_language_draw_impl") :
            source.index("finally:", source.index("async def _natural_language_draw_impl"))
        ]
        self.assertNotIn("_looks_like_draw_request(message)", impl)
        self.assertIn("_looks_like_draw_command(message)", impl)
        self.assertIn("_looks_like_photo_delivery_request(message)", impl)

    def test_deferred_29b_profile_is_rejected_by_name_family_and_id(self) -> None:
        from ..models import PluginSettings

        with self.assertRaises(self.main.WebUiActionError):
            self.main.ComfyAnimaPlugin._reject_deferred_29b_profile(
                "Anima 2.9B", PluginSettings.from_mapping({})
            )
        with self.assertRaises(self.main.WebUiActionError):
            self.main.ComfyAnimaPlugin._reject_deferred_29b_profile(
                "Custom", PluginSettings.from_mapping({"model_family": "anima_29b_40l"})
            )
        with self.assertRaises(self.main.WebUiActionError):
            self.main.ComfyAnimaPlugin._reject_deferred_29b_profile(
                "Custom", PluginSettings.from_mapping({"model_profile_id": "anima_29b"})
            )

    def test_startup_29b_config_is_forced_back_to_legacy(self) -> None:
        from ..models import PluginSettings

        settings = PluginSettings.from_mapping(
            {
                "model_profile_id": "anima_29b",
                "model_family": "anima_29b_40l",
                "workflow_file": "workflow/anima_29b_base_api.json",
                "lora_patch_required": True,
            }
        )
        forced = self.main.ComfyAnimaPlugin._force_deferred_29b_to_legacy(settings)
        self.assertEqual(forced.model_profile_id, "anima_legacy")
        self.assertEqual(forced.model_family, "anima_legacy_28l")
        self.assertFalse(forced.lora_patch_required)
        self.assertEqual(forced.workflow_file, "workflow/anima_v2_api.json")

    def test_startup_29b_profile_is_not_relabelled_as_legacy(self) -> None:
        from ..models import PluginSettings

        raw = {
            "model_profile_id": "anima_29b",
            "model_family": "anima_29b_40l",
            "workflow_file": "workflow/anima_29b_base_api.json",
            "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
            "lora_patch_required": True,
        }
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.ComfyAnimaPlugin._force_deferred_29b_to_legacy(
            PluginSettings.from_mapping(raw)
        )
        plugin.config = self.main.ComfyAnimaPlugin._canonical_legacy_config(
            plugin.settings,
            dict(raw),
        )

        class Profiles:
            def __init__(self):
                self.saved = []

            def list_profiles(self):
                return [{"name": item[0]} for item in self.saved]

            def save_profile(self, name, settings, overwrite=False):
                self.saved.append((name, dict(settings)))

        plugin._config_profiles = Profiles()
        plugin._ensure_builtin_environment_profiles()
        legacy = plugin._config_profiles.saved[0][1]
        self.assertEqual(legacy["model_family"], "anima_legacy_28l")
        self.assertEqual(legacy["model_profile_id"], "anima_legacy")
        self.assertNotIn("anima_29b", legacy["workflow_file"])
        self.assertNotIn("2.9B", legacy["unet_model_name"])

    def test_legacy_submission_rejects_29b_but_allows_unclassified(self) -> None:
        from ..models import LoraSelection, PluginSettings

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = PluginSettings.from_mapping(
            {"model_family": "anima_legacy_28l"}
        )
        plugin._model_profile_contract_error = lambda _settings: ""
        plugin._semantic_index = types.SimpleNamespace(entries={})

        plugin._gate_active_profile_lora_compatibility(
            (LoraSelection("characters/denia", 0.8),),
            {
                "characters/denia": types.SimpleNamespace(
                    name="characters/denia.safetensors",
                    sha256="a" * 64,
                    compatible_model_families=(),
                    compatibility_mode="unknown",
                )
            },
        )
        with self.assertRaises(self.main.LoraWorkflowError):
            plugin._gate_active_profile_lora_compatibility(
                (LoraSelection("characters/denia", 0.8),),
                {
                    "characters/denia": types.SimpleNamespace(
                        name="characters/denia.safetensors",
                        sha256="a" * 64,
                        compatible_model_families=("anima_29b_40l",),
                        compatibility_mode="native_29b",
                    )
                },
            )

    def test_gate_resolves_adapter_promoted_companion_from_snapshot(self) -> None:
        from ..models import LoraSelection, PluginSettings

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = PluginSettings.from_mapping(
            {"model_family": "anima_legacy_28l"}
        )
        plugin._model_profile_contract_error = lambda _settings: ""
        plugin._semantic_index = types.SimpleNamespace(entries={})

        # 适配器把底座升级成 _29b 同伴：前置 records 只有底座，同伴只在快照里。
        plugin._gate_active_profile_lora_compatibility(
            (LoraSelection("29B/(画质)anima-highres-aesthetic-boost_29b", 0.5),),
            {},
            target_family="anima_29b_40l",
            snapshot_records=(
                types.SimpleNamespace(
                    name="29B/(画质)anima-highres-aesthetic-boost_29b.safetensors",
                    sha256="a" * 64,
                    compatible_model_families=("anima_29b_40l",),
                    compatibility_mode="native_29b",
                ),
            ),
        )

        # 名称在 records 与快照里都没有时仍然失败关闭。
        with self.assertRaises(self.main.LoraWorkflowError):
            plugin._gate_active_profile_lora_compatibility(
                (LoraSelection("29B/missing-asset_29b", 0.5),),
                {},
                target_family="anima_29b_40l",
                snapshot_records=(),
            )

    def test_canonical_legacy_config_overrides_29b_executable_fields(self) -> None:
        from ..models import PluginSettings

        raw = {
            "model_profile_id": "anima_29b",
            "model_family": "anima_29b_40l",
            "workflow_file": "workflow/anima_29b_base_api.json",
            "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
        }
        settings = self.main.ComfyAnimaPlugin._force_deferred_29b_to_legacy(
            PluginSettings.from_mapping(raw)
        )
        canonical = self.main.ComfyAnimaPlugin._canonical_legacy_config(
            settings, dict(raw)
        )
        self.assertEqual(canonical["model_profile_id"], "anima_legacy")
        self.assertEqual(canonical["model_family"], "anima_legacy_28l")
        self.assertEqual(canonical["workflow_file"], "workflow/anima_v2_api.json")
        self.assertNotIn("2.9B", canonical["unet_model_name"])

    def test_builtin_profile_seeding_creates_only_legacy(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.config = {"comfyui_url": "http://127.0.0.1:8188"}
        plugin.settings = types.SimpleNamespace(
            comfyui_url="http://127.0.0.1:8188",
            workflow_dir="",
            lora_loader_node_id="",
            unet_loader_node_id="",
            unet_model_input_name="",
            unet_model_name="",
            unet_model_root="",
            clip_model_name="",
            clip_model_root="",
            vae_model_name="",
            vae_model_root="",
            lora_model_root="",
        )

        class Profiles:
            def __init__(self):
                self.saved = []

            def list_profiles(self):
                return [{"name": item[0]} for item in self.saved]

            def save_profile(self, name, settings, overwrite=False):
                self.saved.append((name, settings))

        plugin._config_profiles = Profiles()
        plugin._ensure_builtin_environment_profiles()
        names = [item[0] for item in plugin._config_profiles.saved]
        self.assertEqual(names, ["Anima Legacy"])
        self.assertNotIn("Anima 2.9B", names)


if __name__ == "__main__":
    unittest.main()
