"""v2.4.3（内部 3.1.427）新增能力测试。

覆盖：TTP 三档变体选择与回退、采样器覆写、会话产物登记表、粘性负面
正则与 store、咽喉注入、瘦身提交语义、HYBRID 契约条款与 --负面 别名。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import tempfile
import types
import unittest
from types import SimpleNamespace
from pathlib import Path

from ._stubs import install_astrbot_stubs


def _settings_mapping(**overrides):
    base = {
        "comfyui_url": "http://127.0.0.1:8188",
        "enable_ttp_detail": True,
        "enable_upscale": True,
        "unet_model_name": "Anima-2.9B-preview-v1.safetensors",
        "rtx_scale": 1.3,
    }
    base.update(overrides)
    return base


class TtpVariantSelectionTests(unittest.TestCase):
    """三档阶梯：ttp 开关只在放大链路且模板声明 ttp 变体时生效。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        cls.plugin_dir = Path(__file__).resolve().parents[1]
        cls.template = cls.plugin_dir / "workflow" / "anima_ttp_api.json"

    def _build(self, **overrides) -> tuple[list[str], dict]:
        mapping = _settings_mapping(**overrides)
        settings = self.main.PluginSettings.from_mapping(mapping)
        builder = self.main.WorkflowBuilder(self.template, settings)
        options = self.main.GenerationOptions(prompt="1girl", width=832, height=1216)
        workflow, _seed, preferred = builder.build(options)
        return preferred, workflow

    def test_ttp_variant_selected_when_enabled(self) -> None:
        preferred, workflow = self._build()
        self.assertEqual(preferred, ["458"])
        self.assertIn("458", workflow)
        # 互斥剪枝：另两个终点被移除
        self.assertNotIn("459", workflow)
        self.assertNotIn("460", workflow)

    def test_rtx_variant_selected_when_ttp_disabled(self) -> None:
        preferred, _ = self._build(enable_ttp_detail=False)
        self.assertEqual(preferred, ["459"])

    def test_base_variant_selected_when_upscale_disabled(self) -> None:
        preferred, _ = self._build(enable_upscale=False)
        self.assertEqual(preferred, ["460"])
        # TTP 开关在直出档无效
        self.assertEqual(preferred, ["460"])

    def test_base_template_never_enters_ttp(self) -> None:
        mapping = _settings_mapping(
            rtx_generation_workflow_file="workflow/anima_base_api.json",
            default_generation_pipeline="base",
            enable_upscale=False,
        )
        settings = self.main.PluginSettings.from_mapping(mapping)
        builder = self.main.WorkflowBuilder(
            self.plugin_dir / "workflow" / "anima_base_api.json", settings
        )
        options = self.main.GenerationOptions(prompt="1girl", width=832, height=1216)
        _workflow, _seed, preferred = builder.build(options)
        self.assertNotEqual(preferred, ["458"])

    def test_seed_written_to_both_seed_nodes(self) -> None:
        _preferred, workflow = self._build()
        self.assertEqual(workflow["8"]["inputs"]["noise_seed"], workflow["262"]["inputs"]["seed"])

    def test_no_denoise_key_injected_into_advanced_sampler(self) -> None:
        """KSampler Adv. (Efficient) 没有 denoise 输入，绑定空值时不得写。"""

        _preferred, workflow = self._build()
        self.assertNotIn("denoise", workflow["8"]["inputs"])

    def test_cfg_override_applied_to_bound_sampler(self) -> None:
        _preferred, workflow = self._build(sampler_cfg_override=6.5)
        self.assertEqual(workflow["8"]["inputs"]["cfg"], 6.5)

    def test_sampler_and_scheduler_override_applied(self) -> None:
        _preferred, workflow = self._build(
            sampler_name_override="euler_ancestral",
            sampler_scheduler_override="karras",
        )
        self.assertEqual(workflow["8"]["inputs"]["sampler_name"], "euler_ancestral")
        self.assertEqual(workflow["8"]["inputs"]["scheduler"], "karras")


class SessionArtifactLedgerTests(unittest.TestCase):
    def test_record_and_exact_match(self) -> None:
        from ..services.session_artifact_ledger import SessionArtifactLedger

        async def flow() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                ledger = SessionArtifactLedger(Path(tmp) / "ledger.json")
                await ledger.record(
                    "bot", "sess", "user",
                    sha256="a" * 64, width=832, height=1216, run_id="r1",
                )
                self.assertTrue(await ledger.is_artifact("bot", "sess", "user", "A" * 64))
                self.assertFalse(await ledger.is_artifact("bot", "sess", "user", "b" * 64))
                # 不同会话不命中
                self.assertFalse(await ledger.is_artifact("bot", "other", "user", "a" * 64))

        asyncio.run(flow())


class UserNegativesStoreTests(unittest.TestCase):
    def test_add_remove_terms_lifecycle(self) -> None:
        from ..services.user_negatives import UserNegativesStore

        async def flow() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                store = UserNegativesStore(Path(tmp) / "neg.json")
                self.assertTrue(await store.add("bot", "sess", "user", "项圈"))
                self.assertFalse(await store.add("bot", "sess", "user", "项圈"))
                self.assertEqual(await store.terms("bot", "sess", "user"), ("项圈",))
                self.assertTrue(await store.remove("bot", "sess", "user", "项圈"))
                self.assertEqual(await store.terms("bot", "sess", "user"), ())
                # 重启（重新加载）后仍无残留
                store2 = UserNegativesStore(Path(tmp) / "neg.json")
                self.assertEqual(await store2.terms("bot", "sess", "user"), ())

        asyncio.run(flow())


class StickyNegativeParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.parser = staticmethod(
            importlib.import_module(
                "astrbot_plugin_comfy_anima.services.chat_intent_classifier"
            ).parse_sticky_negative_update
        )

    def test_forbid_phrases(self) -> None:
        for message, term in (
            ("以后都别画项圈了。", "项圈"),
            ("再也不画眼镜了", "眼镜"),
            ("不再画锁链", "锁链"),
            ("今后不要出现纹身", "纹身"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.parser(message), {"action": "add", "term": term})

    def test_release_phrases(self) -> None:
        for message, term in (
            ("可以画项圈了", "项圈"),
            ("解禁 项圈", "项圈"),
            ("不用避讳项圈了", "项圈"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.parser(message), {"action": "remove", "term": term})

    def test_one_shot_and_smalltalk_never_register(self) -> None:
        for message in (
            "这次别画项圈",
            "这张别带项链",
            "以后画项圈给我看",
            "我今天很开心",
        ):
            with self.subTest(message=message):
                self.assertIsNone(self.parser(message))


class NegativeThroatTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, sticky=(), extra_pos=(), extra_neg=()):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            global_extra_positive_tags=list(extra_pos),
            global_extra_negative_tags=list(extra_neg),
        )

        class _Store:
            def __init__(self, terms):
                self._terms = tuple(terms)

            async def terms(self, *_args):
                return self._terms

        plugin._user_negatives_store = _Store(sticky)
        event = types.SimpleNamespace(
            get_session_id=lambda: "sess",
            get_self_id=lambda: "bot",
            get_sender_id=lambda: "user",
        )
        return plugin, event

    async def test_sticky_and_global_negative_merged(self) -> None:
        plugin, event = self._plugin(
            sticky=("项圈",), extra_neg=("text",), extra_pos=("very aesthetic",)
        )
        prompt, negative = await plugin._apply_session_negative_terms(
            event, "1girl", "lowres"
        )
        self.assertEqual(prompt, "1girl, very aesthetic")
        self.assertEqual(negative, "lowres, 项圈, text")

    async def test_no_store_no_crash(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            global_extra_positive_tags=[], global_extra_negative_tags=[],
        )
        event = types.SimpleNamespace(
            get_session_id=lambda: "sess",
        )
        prompt, negative = await plugin._apply_session_negative_terms(
            event, "1girl", "lowres"
        )
        self.assertEqual((prompt, negative), ("1girl", "lowres"))


class IdentityMaterialInjectionTests(unittest.IsolatedAsyncioTestCase):
    """3.1.430：配方/默认角色注入必须携带权威 LoRA 材料与使用指令。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _recipe(self, **overrides):
        from ..services.session_picture_recipe import SessionPictureRecipe
        from ..services.preset_manifest import LoraManifestEntry

        fields = dict(
            bot_id="bot",
            session_id="sess",
            user_id="user",
            preset_name="conversation_pic",
            pipeline="rtx",
            width=832,
            height=1216,
            identity_anchor="denia_(wuthering_waves)",
            required_triggers=("denia_(wuthering_waves)",),
            character_lora_name="29B/anima-000040_29b.safetensors",
            lora_manifest=(
                LoraManifestEntry(name="29B/anima-000040_29b", weight=0.8),
            ),
        )
        fields.update(overrides)
        return SessionPictureRecipe(**fields)

    def _req(self):
        req = SimpleNamespace(extra_user_content_parts=[])
        return req

    def _part_text(self, req):
        part = req.extra_user_content_parts[-1]
        return part.text if hasattr(part, "text") else part["text"]

    async def test_recipe_payload_carries_authoritative_lora(self) -> None:
        recipe = self._recipe()
        req = self._req()
        self.main.ComfyAnimaPlugin._inject_recipe_context(req, recipe)
        text = self._part_text(req)
        self.assertIn("character_lora_name", text)
        self.assertIn("29B/anima-000040_29b.safetensors", text)
        self.assertIn('"weight": 0.8', text)
        self.assertIn("禁止换用同名的其他家族变体", text)
        self.assertIn("<authoritative_picture_recipe>", text)

    def _binding(self, canonical="denia_(wuthering_waves)", source="manual",
                 default=True, lora_name="29B/anima-000040_29b"):
        return SimpleNamespace(
            character_canonical=canonical,
            source=source,
            default_for_character=default,
            activation_terms=(),
        )

    def _index(self, entries):
        return SimpleNamespace(entries=entries)

    async def test_default_binding_unique_resolves(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index({
            "k": SimpleNamespace(
                canonical_name="29B/anima-000040_29b",
                identity_bindings=(self._binding(),),
            ),
        })
        identity = plugin._default_character_identity_binding()
        self.assertIsNotNone(identity)
        self.assertEqual(identity["canonical"], "denia_(wuthering_waves)")
        self.assertEqual(identity["required_triggers"], ["denia"])
        self.assertEqual(identity["character_lora_name"], "29B/anima-000040_29b")

    async def test_default_binding_ambiguous_returns_none(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index({
            "k1": SimpleNamespace(
                canonical_name="29B/a_29b",
                identity_bindings=(self._binding(canonical="a_(x)"),),
            ),
            "k2": SimpleNamespace(
                canonical_name="29B/b_29b",
                identity_bindings=(self._binding(canonical="b_(y)"),),
            ),
        })
        self.assertIsNone(plugin._default_character_identity_binding())

    async def test_default_binding_requires_manual_default(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._semantic_index = self._index({
            "k1": SimpleNamespace(
                canonical_name="29B/a_29b",
                identity_bindings=(
                    self._binding(source="observed"),
                    self._binding(default=False),
                ),
            ),
        })
        self.assertIsNone(plugin._default_character_identity_binding())

    async def test_default_injection_uses_conditional_instruction(self) -> None:
        identity = {
            "canonical": "denia_(wuthering_waves)",
            "identity_anchor": "denia_(wuthering_waves)",
            "required_triggers": ["denia"],
            "character_lora_name": "29B/anima-000040_29b",
        }
        req = self._req()
        self.main.ComfyAnimaPlugin._inject_default_character_context(req, identity)
        text = self._part_text(req)
        self.assertIn("非强制", text)
        self.assertIn("忽略本块", text)
        self.assertIn("denia_(wuthering_waves)", text)


class RecipeIdentityHintTests(unittest.TestCase):
    """3.1.433：注入阶段锚点落 event extra，bind 放行据此读取。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _event(self, extras):
        return SimpleNamespace(
            set_extra=lambda key, value: extras.__setitem__(key, value),
            get_extra=lambda key, default=None: extras.get(key, default),
        )

    def test_persist_and_read_roundtrip(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        extras = {}
        event = self._event(extras)
        plugin._persist_identity_hint(event, "denia_(wuthering_waves)")
        self.assertEqual(
            plugin._event_recipe_identity_hint(event), "denia_(wuthering_waves)"
        )

    def test_persist_skips_blank_and_unreachable(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        extras = {}
        event = self._event(extras)
        plugin._persist_identity_hint(event, "   ")
        plugin._persist_identity_hint(object(), "denia")  # 无 set_extra 的事件
        self.assertEqual(extras, {})
        self.assertEqual(plugin._event_recipe_identity_hint(event), "")

    def test_hint_normalized_for_bind_comparison(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        extras = {}
        event = self._event(extras)
        plugin._persist_identity_hint(event, "Denia_(Wuthering_Waves)")
        self.assertEqual(
            plugin._event_recipe_identity_hint(event), "denia_(wuthering_waves)"
        )


class InpaintSamplerOverrideTests(unittest.TestCase):
    """3.1.435：quick/lanpaint 采样器全局覆写（CFG/采样器/调度器）。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        cls.plugin_dir = Path(__file__).resolve().parents[1]

    def _build(self, settings_overrides, options_overrides, manifest="anima_lanpaint_api"):
        settings = self.main.PluginSettings.from_mapping(
            {"comfyui_url": "http://127.0.0.1:8188", **settings_overrides}
        )
        builder = self.main.InpaintWorkflowBuilder(
            self.plugin_dir / "workflow" / f"{manifest}.json", settings
        )
        options = self.main.GenerationOptions(prompt="1girl", **options_overrides)
        workflow, _seed, _preferred = builder.build(
            "source.png", "mask.png", options
        )
        return workflow

    def test_global_cfg_applies_when_request_omits(self) -> None:
        workflow = self._build({"sampler_cfg_override": 6.5}, {})
        node = "22"  # lanpaint 主采样器
        self.assertEqual(workflow[node]["inputs"]["cfg"], 6.5)

    def test_request_cfg_wins_over_global(self) -> None:
        workflow = self._build(
            {"sampler_cfg_override": 6.5}, {"cfg": 4.0}
        )
        self.assertEqual(workflow["22"]["inputs"]["cfg"], 4.0)

    def test_global_steps_applies_when_request_omits(self) -> None:
        workflow = self._build({"sampler_steps_override": 24}, {})
        self.assertEqual(workflow["22"]["inputs"]["steps"], 24)

    def test_sampler_and_scheduler_override_applies(self) -> None:
        workflow = self._build(
            {
                "sampler_name_override": "euler_ancestral",
                "sampler_scheduler_override": "karras",
            },
            {},
        )
        self.assertEqual(workflow["22"]["inputs"]["sampler_name"], "euler_ancestral")
        self.assertEqual(workflow["22"]["inputs"]["scheduler"], "karras")

    def test_zero_overrides_keep_template_values(self) -> None:
        template = json.loads(
            (self.plugin_dir / "workflow" / "anima_lanpaint_api.json").read_text(
                encoding="utf-8"
            )
        )
        workflow = self._build({}, {})
        self.assertEqual(
            workflow["22"]["inputs"]["cfg"], template["22"]["inputs"]["cfg"]
        )


class ContractAndAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_hybrid_contract_requires_exclusion_in_negative(self) -> None:
        from ..services.prompt_contracts import HYBRID_PROMPT_CONTRACT

        self.assertIn("Exclusion intent is authoritative", HYBRID_PROMPT_CONTRACT)
        self.assertIn("MUST appear", HYBRID_PROMPT_CONTRACT)

    def test_hybrid_contract_forbids_identity_disclaimers(self) -> None:
        from ..services.prompt_contracts import HYBRID_PROMPT_CONTRACT

        self.assertIn("must NOT recite identity, copyright, licensing or", HYBRID_PROMPT_CONTRACT)

    def test_chinese_negative_alias_resolves(self) -> None:
        from ..core.command_aliases import CONTEXT_GENERATION, normalize_command_aliases

        tokens = normalize_command_aliases(
            ["--负面", "眼镜,项圈"], context=CONTEXT_GENERATION
        )
        self.assertIn("--negative", tokens)
        self.assertNotIn("--负面", tokens)


if __name__ == "__main__":
    unittest.main()
