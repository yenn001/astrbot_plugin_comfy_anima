"""Bot 回复意图续画（3.1.418）门禁矩阵与载荷校验测试。"""

import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ._stubs import Plain, install_astrbot_stubs
from ..services.preset_manifest import LoraManifestEntry


def _recipe():
    return SimpleNamespace(
        preset_name="风格001",
        pipeline="base",
        width=832,
        height=1216,
        positive_pool=(
            "1girl",
            "solo",
            "long straight black hair",
            "blunt bangs",
            "brown eyes",
            "delicate face",
            "pale skin",
            "slender figure",
            "school uniform",
            "sunflower",
        ),
        negative_pool=("bad hands",),
        lora_manifest=(
            LoraManifestEntry(name="denia_lorav4", weight=0.8, model_family="legacy"),
        ),
        model_family="legacy",
        identity_anchor="denia_(wuthering_waves)",
        required_triggers=("denia (wuthering waves)",),
        character_lora_name="denia_lorav4",
    )


def _instruction():
    return SimpleNamespace(
        prompt="sunflower scene prompt",
        negative_prompt="worst quality",
        pipeline="base",
    )


class _Event:
    def __init__(self, *, admin=True, message="今天天气真好呀"):
        self._admin = admin
        self.message_str = message
        self._extras = {}

    def is_admin(self):
        return self._admin

    def get_session_id(self):
        return "sess-1"

    def get_sender_id(self):
        return "u-1"

    def get_self_id(self):
        return "bot-1"

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value


class _RecipeStore:
    def __init__(self, recipe):
        self._recipe = recipe

    async def get(self, bot_id, session_id, user_id, **kwargs):
        return self._recipe


class _Judge:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def judge(self, user_message, bot_reply, context=""):
        self.calls.append((user_message, bot_reply))
        return SimpleNamespace(
            decision=self.decision,
            confidence=0.9,
            backend_used="rule",
            reason="ok",
            latency_ms=1.0,
            trace={},
        )


class _Ledger:
    def __init__(self):
        self.records = {}

    def start(self, *, user_message, user_id_hash, context_hash, context_source=""):
        decision_id = f"d{len(self.records) + 1}"
        self.records[decision_id] = None
        return decision_id

    def result(self, decision_id, result):
        record_hash = f"h-{decision_id}"
        self.records[decision_id] = record_hash
        return record_hash

    def verify(self, decision_id, payload):
        expected = self.records.get(decision_id)
        return expected is not None and payload.get("result_hash") == expected


class BotReplyDrawGateTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(
        self,
        *,
        recipe="default",
        decision="draw_now",
        instruction="default",
        enabled=True,
        run_job_error=None,
        director_decline=False,
    ):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = SimpleNamespace(
            enable_bot_reply_draw=enabled,
            bot_reply_draw_cooldown_seconds=30.0,
            bot_reply_intent_backend="rule",
            bot_reply_draw_delivery_phrases=["给你看", "给你瞧瞧", "快看"],
            enable_prompt_composer_v2=False,
            max_total_dynamic_loras=24,
            max_dynamic_loras=12,
            show_chat_generation_details=True,
        )
        plugin._bot_reply_draw_last = {}
        plugin._intent_decision_ledger = _Ledger()
        store_recipe = _recipe() if recipe == "default" else recipe
        plugin._session_recipe_store = _RecipeStore(store_recipe)
        plugin._judge = _Judge(decision)
        plugin._build_intent_judge_service = (
            lambda *, backend_override=None, delivery_phrases=(): plugin._judge
        )
        # 重入架构（3.1.422）：判定命中后走 `_generate_directed_instruction`
        # （导演+工具链），再进与 `<pic>` 共用的 `_render_picture_instruction`。
        plugin._scene_calls = []
        scene_instruction = (
            _instruction() if instruction == "default" else instruction
        )
        director_error = (
            self.main.PromptDirectorError("导演拒答", "") if director_decline else None
        )

        async def directed(event, scene_text, *args, **kwargs):
            plugin._scene_calls.append(scene_text)
            if director_error is not None:
                raise director_error
            return scene_instruction, "provider-x"

        plugin._generate_directed_instruction = directed
        plugin._build_auto_draw_intent_plan = lambda message, **kwargs: object()
        plugin._director = SimpleNamespace()
        plugin.marks = []
        plugin._get_drawing_orchestrator = lambda: SimpleNamespace(
            legacy_submission_allowed=lambda event: True,
            state=lambda event: SimpleNamespace(run_id="run-1"),
            mark_completed=lambda event, run_id: plugin.marks.append(run_id),
        )
        plugin.options = None
        plugin.notify_flags = []
        plugin._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(plugin._tmp.cleanup)

        async def run_job(event, options, *, notify_queue=True):
            plugin.options = options
            plugin.notify_flags.append(notify_queue)
            if run_job_error is not None:
                raise run_job_error
            image = Path(plugin._tmp.name) / "out.png"
            image.write_bytes(b"png-bytes")
            return [image], 42, "run-1", "task-1", None

        plugin._run_job = run_job
        plugin._access_error = lambda event, text: None
        plugin._sync_time_context = lambda prompt, user_request="": prompt
        plugin._schedule_cleanup = lambda paths: None
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        plugin._lora_presets = SimpleNamespace(
            resolve=lambda name: (_ for _ in ()).throw(
                self.main.LoraPresetError("unused", "")
            )
        )
        plugin.context = None
        return plugin

    async def _call(self, plugin, event, reply="我摘了朵向日葵递给你"):
        result = SimpleNamespace(chain=[Plain(reply)])
        drawn = await plugin._maybe_draw_from_bot_reply(event, result, reply)
        return drawn, result

    async def test_disabled_switch_skips(self) -> None:
        plugin = self._plugin(enabled=False)
        drawn, result = await self._call(plugin, _Event())
        self.assertFalse(drawn)
        self.assertIsNone(plugin.options)

    async def test_non_admin_skips(self) -> None:
        plugin = self._plugin()
        drawn, result = await self._call(plugin, _Event(admin=False))
        self.assertFalse(drawn)
        self.assertIsNone(plugin.options)

    async def test_missing_recipe_skips(self) -> None:
        plugin = self._plugin(recipe=None)
        drawn, result = await self._call(plugin, _Event())
        self.assertFalse(drawn)
        self.assertIsNone(plugin.options)

    async def test_no_draw_decision_skips(self) -> None:
        plugin = self._plugin(decision="no_draw")
        drawn, result = await self._call(plugin, _Event())
        self.assertFalse(drawn)
        self.assertIsNone(plugin.options)

    async def test_director_decline_skips(self) -> None:
        plugin = self._plugin(director_decline=True)
        drawn, result = await self._call(plugin, _Event())
        self.assertFalse(drawn)
        self.assertIsNone(plugin.options)
        self.assertEqual(len(result.chain), 1)

    async def test_cooldown_blocks_second_draw(self) -> None:
        plugin = self._plugin()
        first, _ = await self._call(plugin, _Event())
        second, _ = await self._call(plugin, _Event())
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(plugin.options is not None, True)

    async def test_happy_path_renders_through_shared_segment(self) -> None:
        plugin = self._plugin()
        event = _Event()
        drawn, result = await self._call(plugin, event)
        self.assertTrue(drawn)
        self.assertEqual(len(result.chain), 2)
        self.assertIsInstance(result.chain[0], Plain)
        self.assertEqual(result.chain[1], ("image", str(Path(plugin._tmp.name) / "out.png")))
        # 导演场景文本必须带 Bot 原话与权威配方块（身份/激活词/LoRA 栈）。
        self.assertEqual(len(plugin._scene_calls), 1)
        scene = plugin._scene_calls[0]
        self.assertIn("我摘了朵向日葵递给你", scene)
        self.assertIn("<authoritative_picture_recipe>", scene)
        self.assertIn("denia_lorav4", scene)
        self.assertIn("denia_(wuthering_waves)", scene)
        options = plugin.options
        # 锚点由共享段的配方不变量分支确定性前置（导演输出缺失时）。
        self.assertEqual(
            options.prompt, "denia_(wuthering_waves), sunflower scene prompt"
        )
        # 负面池 = 配方池 ∪ 导演负面（去重保序）。
        self.assertEqual(options.negative_prompt, "bad hands, worst quality")
        self.assertEqual(options.pipeline, "base")
        self.assertEqual(options.width, 832)
        self.assertEqual(options.height, 1216)
        self.assertEqual(options.lora_preset, "")
        # 配方 LoRA 栈经指令参数通道注入，权重逐项保留。
        self.assertEqual(
            options.dynamic_loras,
            (self.main.LoraSelection(name="denia_lorav4", strength=0.8),),
        )
        self.assertEqual(options.llm_prompt_source, "bot_reply_intent")
        self.assertEqual(
            options.preset_manifest.identity_anchor, "denia_(wuthering_waves)"
        )
        self.assertEqual(options.llm_character_queries, ("denia_(wuthering_waves)",))
        self.assertEqual(
            options.lora_activation_overrides,
            (("denia_lorav4", "denia (wuthering waves)"),),
        )
        self.assertEqual(plugin.marks, ["run-1"])
        # 沉浸交付：排队通知抑制、无技术脚注、终态 trace 已清。
        self.assertEqual(plugin.notify_flags, [False])
        self.assertIsNone(event.get_extra(self.main._CHAT_DRAW_TERMINAL_EXTRA_KEY))

    async def test_director_anchor_not_duplicated_and_negative_deduped(self) -> None:
        plugin = self._plugin(
            instruction=SimpleNamespace(
                prompt="1girl, denia_(wuthering_waves), sunflower field",
                negative_prompt="bad hands, lowres",
                pipeline="base",
            )
        )
        drawn, _ = await self._call(plugin, _Event())
        self.assertTrue(drawn)
        options = plugin.options
        # 已出现的锚点不重复前置。
        self.assertEqual(
            options.prompt, "1girl, denia_(wuthering_waves), sunflower field"
        )
        self.assertEqual(options.negative_prompt, "bad hands, lowres")

    async def test_empty_anchor_recipe_prompt_untouched(self) -> None:
        recipe = _recipe()
        recipe.identity_anchor = ""
        recipe.character_lora_name = ""
        plugin = self._plugin(recipe=recipe)
        drawn, _ = await self._call(plugin, _Event())
        self.assertTrue(drawn)
        self.assertEqual(plugin.options.prompt, "sunflower scene prompt")
        self.assertEqual(plugin.options.llm_character_queries, ())

    async def test_reentry_guard_blocks_second_pass_same_event(self) -> None:
        plugin = self._plugin()
        event = _Event()
        drawn, _ = await self._call(plugin, event)
        self.assertTrue(drawn)
        plugin._bot_reply_draw_last = {}
        drawn_again, _ = await self._call(plugin, event)
        self.assertFalse(drawn_again)
        self.assertEqual(len(plugin._scene_calls), 1)

    async def test_duplicate_submission_stays_silent(self) -> None:
        plugin = self._plugin(
            run_job_error=self.main.DuplicateSubmissionError("dup")
        )
        drawn, result = await self._call(plugin, _Event())
        self.assertFalse(drawn)
        self.assertEqual(len(result.chain), 1)

    async def test_tampered_payload_fails_closed(self) -> None:
        plugin = self._plugin()
        event = _Event()
        reply = "我摘了朵向日葵递给你"
        forged = {
            "status": "judged",
            "decision": "draw_now",
            "decision_id": "d1",
            "result_hash": "forged-hash",
            "user_message_hash": hashlib.sha256(reply.encode()).hexdigest(),
            "user_id_hash": plugin._event_user_id_hash(event),
            "session_id_hash": plugin._event_session_id_hash(event),
            "public_version": self.main.PLUGIN_VERSION,
            "internal_target_version": self.main.INTERNAL_BUILD_ID,
        }
        event.set_extra(self.main._BOT_REPLY_INTENT_EXTRA_KEY, forged)
        self.assertEqual(plugin._event_bot_reply_intent_result(event, reply), {})

    async def test_payload_bound_to_reply_text(self) -> None:
        plugin = self._plugin()
        event = _Event()
        reply = "我摘了朵向日葵递给你"
        payload = await plugin._judge_bot_reply_intent(event, plugin._judge, reply)
        self.assertIsNotNone(payload)
        event.set_extra(self.main._BOT_REPLY_INTENT_EXTRA_KEY, payload)
        self.assertNotEqual(plugin._event_bot_reply_intent_result(event, reply), {})
        self.assertEqual(
            plugin._event_bot_reply_intent_result(event, "另一句话"), {}
        )

    def test_recipe_commit_sources(self) -> None:
        commits = self.main.ComfyAnimaPlugin._commits_session_picture_recipe
        self.assertTrue(commits("conversation_pic"))
        self.assertTrue(commits("bot_reply_intent"))
        self.assertFalse(commits(""))
        self.assertFalse(commits("llm_prompt"))

    async def test_stale_cooldown_entries_evicted(self) -> None:
        plugin = self._plugin()
        plugin._bot_reply_draw_last["stale-session"] = (
            __import__("time").monotonic() - 7200.0
        )
        await self._call(plugin, _Event())
        self.assertNotIn("stale-session", plugin._bot_reply_draw_last)
        self.assertIn("sess-1", plugin._bot_reply_draw_last)


class RuleDeliveryPhraseTests(unittest.IsolatedAsyncioTestCase):
    """Bot 交付语词表：肯定/否定/推迟/疑问四态与用户闸门隔离。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _service(self, phrases):
        from ..services.intent_judge import IntentJudgeService, IntentJudgeSettings

        return IntentJudgeService(
            IntentJudgeSettings(backend="rule", delivery_phrases=phrases)
        )

    async def test_delivery_phrase_draws(self) -> None:
        from ..services.intent_judge import DRAW_NOW

        service = self._service(("给你看",))
        result = await service.judge(
            "看看娅娅今晚穿了什么服装", "主人要看，那我给你看……给你看。"
        )
        self.assertEqual(result.decision, DRAW_NOW)

    async def test_negated_delivery_blocked(self) -> None:
        from ..services.intent_judge import DRAW_NOW

        service = self._service(("给你看",))
        result = await service.judge("x", "不给你看。")
        self.assertNotEqual(result.decision, DRAW_NOW)

    async def test_postponed_delivery_awaits(self) -> None:
        from ..services.intent_judge import AWAIT

        service = self._service(("给你看",))
        result = await service.judge("x", "明天再给你看。")
        self.assertEqual(result.decision, AWAIT)

    async def test_question_delivery_blocked(self) -> None:
        from ..services.intent_judge import DRAW_NOW

        service = self._service(("给你看",))
        result = await service.judge("x", "要不要给你看？")
        self.assertNotEqual(result.decision, DRAW_NOW)

    async def test_user_gate_vocab_unaffected(self) -> None:
        from ..services.intent_judge import NO_DRAW

        service = self._service(())
        result = await service.judge("x", "那我给你看……给你看。")
        self.assertEqual(result.decision, NO_DRAW)

    def test_intent_judge_may_share_provider_with_director(self) -> None:
        settings = self.main.PluginSettings.from_mapping(
            {
                "intent_judge_online_provider_id": "provider-x",
                "prompt_llm_provider_id": "provider-x",
            }
        )
        self.assertEqual(settings.intent_judge_online_provider_id, "provider-x")
        self.assertEqual(settings.prompt_llm_provider_id, "provider-x")


if __name__ == "__main__":
    unittest.main()
