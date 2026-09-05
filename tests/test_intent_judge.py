"""Intent judge service tests: modes, thresholds, fallback, both/auto."""

import unittest

from ..services.intent_judge import (
    AWAIT,
    DRAW_NOW,
    NO_DRAW,
    IntentJudgeResult,
    IntentJudgeService,
    IntentJudgeSettings,
    LocalIntentJudge,
    RuleIntentJudge,
)


def _settings(**kwargs) -> IntentJudgeSettings:
    values = dict(kwargs)
    return IntentJudgeSettings(**values)


class RuleIntentJudgeTests(unittest.IsolatedAsyncioTestCase):
    def test_positive_draw_phrase_is_draw_now(self) -> None:
        judge = RuleIntentJudge()
        result = judge.judge("好的，我这就给你画出来")
        self.assertEqual(result.decision, DRAW_NOW)
        self.assertEqual(result.backend_used, "rule")

    def test_negative_phrase_is_no_draw(self) -> None:
        judge = RuleIntentJudge()
        result = judge.judge("先不画，陪你聊天")
        self.assertEqual(result.decision, NO_DRAW)

    def test_future_phrase_is_await(self) -> None:
        judge = RuleIntentJudge()
        result = judge.judge("明天再给你画")
        self.assertEqual(result.decision, AWAIT)

    def test_plain_chat_is_no_draw(self) -> None:
        judge = RuleIntentJudge()
        result = judge.judge("今天天气不错")
        self.assertEqual(result.decision, NO_DRAW)


class LocalIntentJudgeTests(unittest.IsolatedAsyncioTestCase):
    async def _judge(self, text: str) -> IntentJudgeResult:
        async def embed(texts):
            # Deterministic: positive anchors share dimension 0, negative
            # anchors share dimension 1, reply decides which side it points to.
            vectors = []
            for item in texts:
                if (
                    "我这就画" in item
                    or item.startswith("Bot is about")
                    or item.startswith("Bot says it will")
                    or item.startswith("Bot reports")
                ):
                    vectors.append((1.0, 0.0))
                else:
                    vectors.append((0.0, 1.0))
            return tuple(vectors)

        async def rerank(query, docs):
            return tuple(1.0 if doc in query else 0.0 for doc in docs)

        settings = _settings(backend="local")
        judge = LocalIntentJudge(settings, embed, rerank)
        return await judge.judge("user", text)

    async def test_local_positive_text_is_draw_now(self) -> None:
        result = await self._judge("我这就画给你")
        self.assertEqual(result.decision, DRAW_NOW)

    async def test_local_negative_text_is_no_draw(self) -> None:
        result = await self._judge("不画")
        self.assertEqual(result.decision, NO_DRAW)


class IntentJudgeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def _embed_positive(self, texts):
        return tuple(
            (1.0, 0.0)
            if "我这就画" in item
            or "Bot is about" in item
            or "Bot says it will" in item
            or "Bot reports" in item
            else (0.0, 0.0)
            for item in texts
        )

    async def _embed_negative(self, texts):
        return tuple(
            (0.0, 1.0)
            if "我这就画" in item
            or "不画" in item
            or "Bot is only" in item
            else (0.0, 0.0)
            for item in texts
        )

    async def _rerank_positive(self, query, docs):
        return tuple(1.0 if doc in query else 0.0 for doc in docs)

    async def _rerank_negative(self, query, docs):
        return tuple(1.0 if doc in query else 0.0 for doc in docs)

    async def _llm(self, prompt, system, temperature):
        if "will generate and send an image" in prompt:
            return '{"decision":"draw_now","confidence":0.9,"reason":"yes"}'
        return '{"decision":"no_draw","confidence":0.9,"reason":"no"}'

    def _service(self, backend):
        return IntentJudgeService(
            _settings(backend=backend),
            embed_fn=self._embed_positive,
            rerank_fn=self._rerank_positive,
            llm_fn=self._llm,
        )

    async def test_off_mode_returns_no_draw(self) -> None:
        service = self._service("off")
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.decision, NO_DRAW)
        self.assertEqual(result.backend_used, "off")

    async def test_rule_mode_uses_keyword_judge(self) -> None:
        service = self._service("rule")
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.decision, DRAW_NOW)
        self.assertEqual(result.backend_used, "rule")

    async def test_rule_mode_judges_user_message_without_bot_reply(self) -> None:
        service = self._service("rule")
        result = await service.judge("画出来", "")
        self.assertEqual(result.decision, DRAW_NOW)
        self.assertEqual(result.backend_used, "rule")

    async def test_rule_mode_ignores_historical_context(self) -> None:
        service = self._service("rule")
        result = await service.judge("在吗", "", "画好了，发图给你")
        self.assertEqual(result.decision, NO_DRAW)
        self.assertEqual(result.backend_used, "rule")

    async def test_local_missing_backends_falls_back_no_draw(self) -> None:
        service = IntentJudgeService(_settings(backend="local"))
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.decision, NO_DRAW)
        self.assertIn("unavailable", result.reason)

    async def test_auto_online_draw_now_overrides_local_no_draw(self) -> None:
        async def embed_no_draw(texts):
            return tuple((0.0, 0.0) for _item in texts)

        async def rerank_zero(query, docs):
            return tuple(0.0 for _doc in docs)

        async def llm_draw_now(prompt, system, temperature):
            return '{"decision": "draw_now", "confidence": 0.9, "reason": "explicit"}'

        service = IntentJudgeService(
            _settings(backend="auto"),
            embed_fn=embed_no_draw,
            rerank_fn=rerank_zero,
            llm_fn=llm_draw_now,
        )
        result = await service.judge("娅娅早上好呀，检查穿着了！（画出来）", "")
        self.assertEqual(result.decision, DRAW_NOW)
        self.assertEqual(result.backend_used, "auto:online")

    async def test_auto_local_await_stays_await(self) -> None:
        async def embed_positive(texts):
            vectors = []
            for item in texts:
                vectors.append((1.0, 0.0) if item.startswith("Bot is about") or "画" in item else (0.0, 1.0))
            return tuple(vectors)

        async def rerank_zero(query, docs):
            return tuple(0.0 for _doc in docs)

        async def llm_draw_now(prompt, system, temperature):
            return '{"decision": "draw_now", "confidence": 0.9, "reason": "explicit"}'

        service = IntentJudgeService(
            _settings(backend="auto"),
            embed_fn=embed_positive,
            rerank_fn=rerank_zero,
            llm_fn=llm_draw_now,
        )
        result = await service.judge("明天再画出来给我看", "")
        self.assertEqual(result.decision, AWAIT)
        self.assertEqual(result.backend_used, "auto:local")

    async def test_both_online_draw_now_wins_local_no_draw(self) -> None:
        async def embed_no_draw(texts):
            return tuple((0.0, 0.0) for _item in texts)

        async def rerank_zero(query, docs):
            return tuple(0.0 for _doc in docs)

        async def llm_draw_now(prompt, system, temperature):
            return '{"decision": "draw_now", "confidence": 0.9, "reason": "explicit"}'

        service = IntentJudgeService(
            _settings(backend="both"),
            embed_fn=embed_no_draw,
            rerank_fn=rerank_zero,
            llm_fn=llm_draw_now,
        )
        result = await service.judge("娅娅早上好呀，检查穿着了！（画出来）", "")
        self.assertEqual(result.decision, DRAW_NOW)
        self.assertEqual(result.backend_used, "local+online")
        self.assertIn("online semantic approval", result.reason)

    async def test_auto_without_backends_falls_back_no_draw(self) -> None:
        service = IntentJudgeService(_settings(backend="auto"))
        result = await service.judge("娅娅早上好呀，检查穿着了！（画出来）", "")
        self.assertEqual(result.decision, NO_DRAW)
        self.assertEqual(result.reason, "auto has no backends")

    async def test_auto_uses_local_when_confident(self) -> None:
        service = self._service("auto")
        result = await service.judge("user", "我这就画")
        self.assertIn("auto:local", result.backend_used)
        self.assertEqual(result.decision, DRAW_NOW)

    async def test_auto_falls_back_to_online_when_local_low_confidence(self) -> None:
        async def embed_uncertain(texts):
            return tuple((0.0, 0.0) for _item in texts)

        async def rerank_zero(query, docs):
            return tuple(0.0 for _doc in docs)

        service = IntentJudgeService(
            _settings(backend="auto"),
            embed_fn=embed_uncertain,
            rerank_fn=rerank_zero,
            llm_fn=self._llm,
        )
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.backend_used, "auto:online")

    async def test_both_agree_keeps_decision(self) -> None:
        service = self._service("both")
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.backend_used, "local+online")
        self.assertEqual(result.decision, DRAW_NOW)

    async def test_both_disagree_draw_never_beats_await(self) -> None:
        async def llm_disagree(prompt, system, temperature):
            return '{"decision":"no_draw","confidence":0.9,"reason":"disagree"}'

        service = IntentJudgeService(
            _settings(backend="both"),
            embed_fn=self._embed_positive,
            rerank_fn=self._rerank_positive,
            llm_fn=llm_disagree,
        )
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.decision, AWAIT)
        self.assertEqual(result.backend_used, "local+online")

    async def test_online_invalid_json_falls_back_no_draw(self) -> None:
        async def bad_llm(prompt, system, temperature):
            return "not json"

        service = IntentJudgeService(
            _settings(backend="online"),
            llm_fn=bad_llm,
        )
        result = await service.judge("user", "我这就画")
        self.assertEqual(result.decision, NO_DRAW)
        self.assertIn("online backend failed", result.reason)


if __name__ == "__main__":
    unittest.main()
