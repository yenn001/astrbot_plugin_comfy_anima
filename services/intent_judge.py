"""Deterministic + local + online intent judgment for chat drawing.

The service decides whether a Bot reply should enter image generation:
``draw_now``, ``await`` or ``no_draw``. It supports ``off``, ``rule``,
``local`` (embedding + reranker), ``online`` (independent LLM), ``auto``
(local-first; the online semantic judge arbitrates otherwise) and ``both``
(dual-run; on disagreement the online semantic approval wins a local
``no_draw``, every other conflict stays conservative).
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

DEFAULT_POSITIVE_ANCHORS = (
    "Bot is about to generate and send an image",
    "Bot says it will draw or generate a picture now",
    "Bot is describing a picture it is creating for the user",
    "Bot promises to show a photo or selfie now",
    "Bot reports that the image has been drawn and sent",
)

DEFAULT_NEGATIVE_ANCHORS = (
    "Bot is only chatting normally without drawing",
    "Bot says it will not draw or refuses to draw",
    "Bot says it will draw tomorrow or later, not now",
    "Bot asks the user to wait instead of drawing",
    "Bot is answering an unrelated question",
)

DEFAULT_RERANK_POSITIVE_DOCS = (
    "我这就画",
    "这就给你画",
    "画好了",
    "正在生成图片",
    "发图给你",
    "现在就画给你看",
)

DEFAULT_RERANK_NEGATIVE_DOCS = (
    "不画",
    "先不画",
    "明天再画",
    "以后给你画",
    "只是聊天",
    "等会再说",
)

Decision = str
NO_DRAW: Decision = "no_draw"
DRAW_NOW: Decision = "draw_now"
AWAIT: Decision = "await"

EmbedFn = Callable[[tuple[str, ...]], Awaitable[tuple[tuple[float, ...], ...]]]
RerankFn = Callable[
    [str, tuple[str, ...]],
    Awaitable[tuple[float, ...]],
]
LlmFn = Callable[[str, str, float], Awaitable[str]]


@dataclass(frozen=True)
class IntentJudgeResult:
    decision: Decision
    confidence: float
    backend_used: str
    reason: str
    latency_ms: float
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentJudgeSettings:
    backend: str = "rule"
    embedding_provider_id: str = ""
    rerank_provider_id: str = ""
    online_provider_id: str = ""
    positive_anchors: tuple[str, ...] = DEFAULT_POSITIVE_ANCHORS
    negative_anchors: tuple[str, ...] = DEFAULT_NEGATIVE_ANCHORS
    rerank_positive_docs: tuple[str, ...] = DEFAULT_RERANK_POSITIVE_DOCS
    rerank_negative_docs: tuple[str, ...] = DEFAULT_RERANK_NEGATIVE_DOCS
    local_embedding_threshold: float = 0.10
    local_rerank_threshold: float = 0.05
    auto_confidence_floor: float = 0.70
    online_timeout: float = 10.0
    online_temperature: float = 0.0
    fallback: Decision = NO_DRAW

    @property
    def backend_kind(self) -> str:
        return self.backend.strip().casefold()


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _decision_from_scores(
    embedding_diff: float,
    rerank_diff: float,
    *,
    embedding_threshold: float,
    rerank_threshold: float,
) -> tuple[Decision, float]:
    if embedding_diff > embedding_threshold and rerank_diff > rerank_threshold:
        margin = min(1.0, max(0.0, (embedding_diff - embedding_threshold) * 5))
        confidence = 0.65 + margin * 0.3
        return DRAW_NOW, min(0.98, confidence)
    if embedding_diff > embedding_threshold and rerank_diff <= rerank_threshold:
        # The reply looks like drawing language but the local reranker sees
        # future/negation cues: wait, do not generate now.
        return AWAIT, 0.60
    if embedding_diff < -embedding_threshold:
        return NO_DRAW, 0.75
    return NO_DRAW, 0.55


class RuleIntentJudge:
    """Zero-cost keyword judge used when no local/online backend is enabled."""

    _DRAW_NOW_WORDS = (
        "我这就画",
        "这就给你画",
        "画好了",
        "正在生成",
        "发图给你",
        "现在画",
        "马上画",
        "出图",
        "生成图片",
        "自拍给你",
        "画出来",
        "画一下",
        "画给我",
        "给我画",
        "来一张",
        "画一张",
    )
    _NEGATIVE_WORDS = (
        "不画",
        "先不画",
        "别画",
        "不要图",
        "不出图",
        "不给图",
        "拒绝",
    )
    _FUTURE_WORDS = ("明天", "以后", "下次", "等会", "稍后", "过会", "晚点")

    def judge(self, text: str) -> IntentJudgeResult:
        started = time.monotonic()
        folded = str(text or "").casefold()
        has_negative = any(word in folded for word in self._NEGATIVE_WORDS)
        has_future = any(word in folded for word in self._FUTURE_WORDS)
        has_draw_now = any(word in folded for word in self._DRAW_NOW_WORDS)
        if has_draw_now and not has_negative and not has_future:
            decision, confidence = DRAW_NOW, 0.80
            reason = "keyword_positive"
        elif has_future and ("画" in folded or "图" in folded):
            decision, confidence = AWAIT, 0.75
            reason = "keyword_future_draw"
        elif has_draw_now and (has_negative or has_future):
            decision, confidence = AWAIT, 0.75
            reason = "keyword_negative_or_future"
        elif has_negative or has_future:
            decision, confidence = NO_DRAW, 0.75
            reason = "keyword_negative_or_future"
        else:
            decision, confidence = NO_DRAW, 0.70
            reason = "keyword_no_signal"
        return IntentJudgeResult(
            decision=decision,
            confidence=confidence,
            backend_used="rule",
            reason=reason,
            latency_ms=(time.monotonic() - started) * 1000,
            trace={
                "has_draw_now": has_draw_now,
                "has_negative": has_negative,
                "has_future": has_future,
            },
        )


class LocalIntentJudge:
    """Embedding + reranker judge.

    Embedding compares the reply against positive/negative anchor sentences.
    Reranker scores the reply against short literal positive/negative phrases
    and is used only as a second-opinion gate, not as an identity matcher.
    """

    def __init__(
        self,
        settings: IntentJudgeSettings,
        embed_fn: EmbedFn,
        rerank_fn: RerankFn,
    ) -> None:
        self._settings = settings
        self._embed_fn = embed_fn
        self._rerank_fn = rerank_fn

    async def judge(
        self,
        user_message: str,
        bot_reply: str,
        context: str = "",
    ) -> IntentJudgeResult:
        started = time.monotonic()
        text = str(user_message or "").strip()
        if str(bot_reply or "").strip():
            text = f"{text}\nBot: {str(bot_reply).strip()}"
        if str(context or "").strip():
            text = f"{text}\nContext: {str(context).strip()}"
        anchors = tuple(
            dict.fromkeys(
                (
                    *self._settings.positive_anchors,
                    *self._settings.negative_anchors,
                    text,
                )
            )
        )
        vectors = await self._embed_fn(anchors)
        if len(vectors) != len(anchors):
            raise ValueError("embedding provider returned mismatched vectors")
        positive_count = len(self._settings.positive_anchors)
        text_vector = vectors[-1]
        positive_diff = sum(
            _cosine(text_vector, vectors[index]) for index in range(positive_count)
        ) / max(1, positive_count)
        negative_start = positive_count
        negative_end = negative_start + len(self._settings.negative_anchors)
        negative_diff = sum(
            _cosine(text_vector, vectors[index])
            for index in range(negative_start, negative_end)
        ) / max(1, negative_end - negative_start)
        embedding_diff = positive_diff - negative_diff

        positive_scores = await self._rerank_fn(
            text,
            self._settings.rerank_positive_docs,
        )
        negative_scores = await self._rerank_fn(
            text,
            self._settings.rerank_negative_docs,
        )
        rerank_diff = max(positive_scores, default=0.0) - max(
            negative_scores, default=0.0
        )

        decision, confidence = _decision_from_scores(
            embedding_diff,
            rerank_diff,
            embedding_threshold=self._settings.local_embedding_threshold,
            rerank_threshold=self._settings.local_rerank_threshold,
        )
        return IntentJudgeResult(
            decision=decision,
            confidence=confidence,
            backend_used="local",
            reason="embedding+reranker",
            latency_ms=(time.monotonic() - started) * 1000,
            trace={
                "embedding_diff": embedding_diff,
                "rerank_diff": rerank_diff,
                "embedding_threshold": self._settings.local_embedding_threshold,
                "rerank_threshold": self._settings.local_rerank_threshold,
            },
        )


class OnlineIntentJudge:
    """Independent LLM three-class judge.

    The LLM must return JSON: {"decision": "...", "confidence": 0-1,
    "reason": "..."}.
    """

    _PROMPT_HEAD = (
        "Classify whether the Bot reply means it will generate and send an "
        "image NOW, should wait, or is not drawing.\n"
    )

    def _build_prompt(self, user_message: str, bot_reply: str, context: str = "") -> str:
        scratch = (
            self._PROMPT_HEAD
            + f"User message: {user_message}\n"
        )
        if str(bot_reply or "").strip():
            scratch += f"Bot reply: {bot_reply}\n"
        if str(context or "").strip():
            scratch += f"Historical context: {context}\n"
        return scratch + (
            'Return only JSON: {"decision":"draw_now|await|no_draw",'
            + '"confidence":0-1,"reason":"short reason"}'
        )

    def __init__(self, settings: IntentJudgeSettings, llm_fn: LlmFn) -> None:
        self._settings = settings
        self._llm_fn = llm_fn

    async def judge(
        self,
        user_message: str,
        bot_reply: str,
        context: str = "",
    ) -> IntentJudgeResult:
        started = time.monotonic()
        prompt = self._build_prompt(
            str(user_message or "")[:500],
            str(bot_reply or "")[:800],
            str(context or "")[:2000],
        )
        raw = await self._llm_fn(
            prompt,
            "You are a strict drawing-intent classifier.",
            self._settings.online_temperature,
        )
        raw = str(raw or "").strip()
        payload: dict[str, Any] = {}
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                payload = json.loads(raw[start : end + 1])
            else:
                raise ValueError("no json object")
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"online intent judge returned invalid json: {exc}") from exc
        decision = str(payload.get("decision") or "").strip().casefold()
        if decision not in {DRAW_NOW, AWAIT, NO_DRAW}:
            raise ValueError(f"online intent judge returned bad decision: {decision}")
        try:
            confidence = min(1.0, max(0.0, float(payload.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return IntentJudgeResult(
            decision=decision,
            confidence=confidence,
            backend_used="online",
            reason=str(payload.get("reason") or "")[:200],
            latency_ms=(time.monotonic() - started) * 1000,
            trace={"raw_len": len(raw), "raw_prefix": raw[:200]},
        )


class IntentJudgeService:
    """Mode dispatcher with auto/both and no_draw fallback."""

    def __init__(
        self,
        settings: IntentJudgeSettings,
        *,
        embed_fn: EmbedFn | None = None,
        rerank_fn: RerankFn | None = None,
        llm_fn: LlmFn | None = None,
    ) -> None:
        self._settings = settings
        self._rule = RuleIntentJudge()
        self._local = (
            LocalIntentJudge(settings, embed_fn, rerank_fn)
            if embed_fn is not None and rerank_fn is not None
            else None
        )
        self._online = (
            OnlineIntentJudge(settings, llm_fn) if llm_fn is not None else None
        )

    @staticmethod
    def _no_draw(reason: str, *, backend: str, confidence: float = 0.0) -> IntentJudgeResult:
        return IntentJudgeResult(
            decision=NO_DRAW,
            confidence=confidence,
            backend_used=backend,
            reason=reason,
            latency_ms=0.0,
        )

    async def judge(
        self,
        user_message: str,
        bot_reply: str,
        context: str = "",
    ) -> IntentJudgeResult:
        kind = self._settings.backend_kind
        if kind == "off":
            return self._no_draw(
                "auto drawing disabled",
                backend="off",
                confidence=1.0,
            )
        if kind == "rule":
            combined = str(user_message or "").strip()
            if str(bot_reply or "").strip():
                combined = f"{combined}\nBot: {bot_reply}".strip()
            return self._rule.judge(combined)
        if kind == "local":
            if self._local is None:
                return self._no_draw(
                    "local backend unavailable",
                    backend="local",
                )
            try:
                return await self._local.judge(user_message, bot_reply, context)
            except Exception as exc:
                return self._no_draw(
                    f"local backend failed: {type(exc).__name__}",
                    backend="local",
                )
        if kind == "online":
            if self._online is None:
                return self._no_draw(
                    "online backend unavailable",
                    backend="online",
                )
            try:
                return await self._online.judge(user_message, bot_reply, context)
            except Exception as exc:
                return self._no_draw(
                    f"online backend failed: {type(exc).__name__}",
                    backend="online",
                )
        if kind == "auto":
            return await self._judge_auto(user_message, bot_reply, context)
        if kind == "both":
            return await self._judge_both(user_message, bot_reply, context)
        return self._no_draw(
            f"unknown backend {self._settings.backend!r}",
            backend="unknown",
        )

    async def _judge_auto(
        self,
        user_message: str,
        bot_reply: str,
        context: str = "",
    ) -> IntentJudgeResult:
        if self._local is None:
            if self._online is None:
                return self._no_draw("auto has no backends", backend="auto")
            try:
                result = await self._online.judge(user_message, bot_reply, context)
                return self._with_auto_meta(result, "online")
            except Exception as exc:
                return self._no_draw(
                    f"auto online failed: {type(exc).__name__}",
                    backend="auto",
                )
        try:
            local = await self._local.judge(user_message, bot_reply, context)
        except Exception as exc:
            local = self._no_draw(
                f"local failed: {type(exc).__name__}",
                backend="local",
            )
        if (
            local.decision == DRAW_NOW
            and local.confidence >= self._settings.auto_confidence_floor
        ):
            return self._with_auto_meta(local, "local")
        if local.decision == AWAIT:
            # 本地向量发现的否定/推迟线索是保守防线，不被在线判定推翻。
            return self._with_auto_meta(local, "local")
        if self._online is None:
            return self._no_draw(
                "auto uncertain and no online backend",
                backend="auto",
                confidence=local.confidence,
            )
        try:
            online = await self._online.judge(user_message, bot_reply, context)
            return self._with_auto_meta(online, "online")
        except Exception as exc:
            return self._no_draw(
                f"auto online failed after uncertain local: {type(exc).__name__}",
                backend="auto",
                confidence=local.confidence,
            )

    async def _judge_both(
        self,
        user_message: str,
        bot_reply: str,
        context: str = "",
    ) -> IntentJudgeResult:
        if self._local is None or self._online is None:
            return self._no_draw("both mode needs local and online backends", backend="both")
        try:
            local = await self._local.judge(user_message, bot_reply, context)
        except Exception as exc:
            return self._no_draw(
                f"both local failed: {type(exc).__name__}",
                backend="both",
            )
        try:
            online = await self._online.judge(user_message, bot_reply, context)
        except Exception as exc:
            return self._no_draw(
                f"both online failed: {type(exc).__name__}",
                backend="both",
            )
        trace = {
            "local": {
                "decision": local.decision,
                "confidence": local.confidence,
                **local.trace,
            },
            "online": {
                "decision": online.decision,
                "confidence": online.confidence,
                **online.trace,
            },
        }
        if local.decision == online.decision:
            return IntentJudgeResult(
                decision=local.decision,
                confidence=max(local.confidence, online.confidence),
                backend_used="local+online",
                reason="both agree",
                latency_ms=local.latency_ms + online.latency_ms,
                trace=trace,
            )
        if local.decision != online.decision:
            if online.decision == DRAW_NOW and local.decision == NO_DRAW:
                # 向量锚点为 Bot 回复设计，对用户命令结构性偏 no_draw；冲突时
                # 以带完整上下文的在线语义判定为准。
                return IntentJudgeResult(
                    decision=DRAW_NOW,
                    confidence=online.confidence,
                    backend_used="local+online",
                    reason="both disagree; online semantic approval wins",
                    latency_ms=local.latency_ms + online.latency_ms,
                    trace=trace,
                )
            # 其余冲突（本地 await 的否定/推迟线索、本地要画但语义判定不认可）
            # 保持保守，绝不生成。
            return IntentJudgeResult(
                decision=AWAIT,
                confidence=min(local.confidence, online.confidence),
                backend_used="local+online",
                reason="both disagree; conservative await",
                latency_ms=local.latency_ms + online.latency_ms,
                trace=trace,
            )

    @staticmethod
    def _with_auto_meta(
        result: IntentJudgeResult,
        source: str,
    ) -> IntentJudgeResult:
        trace = dict(result.trace)
        trace["auto_source"] = source
        return IntentJudgeResult(
            decision=result.decision,
            confidence=result.confidence,
            backend_used=f"auto:{source}",
            reason=result.reason,
            latency_ms=result.latency_ms,
            trace=trace,
        )


__all__ = [
    "AWAIT",
    "DRAW_NOW",
    "NO_DRAW",
    "IntentJudgeResult",
    "IntentJudgeService",
    "IntentJudgeSettings",
    "LocalIntentJudge",
    "OnlineIntentJudge",
    "RuleIntentJudge",
]
