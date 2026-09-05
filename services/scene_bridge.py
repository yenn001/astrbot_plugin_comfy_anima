"""Scene extraction bridge for ``我想看你在干嘛``-style requests.

The service only runs when the user message contains an explicit visual
intent. A plain ``你在干嘛`` question never triggers extraction or drawing.
"""

from __future__ import annotations

import inspect
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

DRAW_THRESHOLD = 0.70
ASK_THRESHOLD = 0.40

_VISUAL_INTENT_RE = re.compile(
    r"(?:想看|让我看看|看看你|看看你现在|你现在(?:什么|的)样子|给我看看)",
    flags=re.IGNORECASE,
)

LlmFn = Callable[[str, str, float], Awaitable[str]]
ContextFilterFn = Callable[
    [str, tuple[str, ...]],
    Awaitable[tuple[int, ...]],
]


@dataclass(frozen=True)
class SceneFacts:
    location: str = ""
    action: str = ""
    clothing: str = ""
    pose: str = ""
    emotion: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class SceneBridgeResult:
    action: str  # draw | ask | skip
    scene: SceneFacts | None = None
    reason: str = ""
    latency_ms: float = 0.0
    trace: dict[str, Any] = field(default_factory=dict)


def has_visual_intent(user_message: str) -> bool:
    return bool(_VISUAL_INTENT_RE.search(str(user_message or "")))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _item_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        for key in ("content", "text", "message", "value"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    for attribute in ("content", "text", "message"):
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    return str(item or "").strip()


def _read_context_items(value: Any, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = (value,)
    elif isinstance(value, (list, tuple, set)):
        raw = tuple(value)
    else:
        raw = ()
    items: list[str] = []
    for item in raw:
        text = _item_text(item).strip()
        if text and text not in items:
            items.append(text)
    return tuple(items[-limit:])


async def scene_context_from_event(
    event: Any,
    *,
    recent_limit: int = 8,
    memory_limit: int = 5,
    persona_limit: int = 120,
) -> dict[str, Any]:
    """Collect Scene Bridge context from available AstrBot event APIs.

    The helper is intentionally duck-typed: it tries common read-only event
    accessors for message history, persona/character name, and living-memory
    recall, and falls back to empty collections when an API is missing or
    raises.  The returned ``sources`` map records which accessor was used.
    """

    safe_recent_limit = max(1, min(32, int(recent_limit)))
    safe_memory_limit = max(0, min(20, int(memory_limit)))
    sources: dict[str, str] = {}
    recent_messages: tuple[str, ...] = ()
    persona_name = ""
    memories: tuple[str, ...] = ()

    message_api = None
    for name in ("get_recent_messages", "get_message_history", "get_history"):
        candidate = getattr(event, name, None)
        if callable(candidate):
            message_api = (name, candidate)
            break
    if message_api is not None:
        try:
            raw = await _maybe_await(message_api[1]())
            recent_messages = _read_context_items(raw, safe_recent_limit)
            sources["recent_messages"] = message_api[0]
        except Exception:
            sources["recent_messages"] = "fallback_empty"
    else:
        raw = getattr(event, "messages", None)
        if raw is not None:
            recent_messages = _read_context_items(raw, safe_recent_limit)
            sources["recent_messages"] = "event.messages"
        else:
            sources["recent_messages"] = "fallback_empty"

    persona_api = None
    for name in ("get_persona_name", "get_character_name", "get_role_name"):
        candidate = getattr(event, name, None)
        if callable(candidate):
            persona_api = (name, candidate)
            break
    if persona_api is not None:
        try:
            raw = await _maybe_await(persona_api[1]())
            persona_name = str(raw or "").strip()[:persona_limit]
            sources["persona_name"] = persona_api[0]
        except Exception:
            sources["persona_name"] = "fallback_empty"
    else:
        for name in ("persona_name", "character_name", "role_name"):
            value = getattr(event, name, "")
            if value:
                persona_name = str(value).strip()[:persona_limit]
                sources["persona_name"] = f"event.{name}"
                break
        else:
            sources["persona_name"] = "fallback_empty"

    memory_api = None
    for name in ("get_memories", "recall_memories", "get_recent_memories", "livingmemory_recall"):
        candidate = getattr(event, name, None)
        if callable(candidate):
            memory_api = (name, candidate)
            break
    if memory_api is None:
        context = getattr(event, "context", None)
        for name in ("get_memories", "recall_memories", "get_recent_memories", "livingmemory_recall"):
            candidate = getattr(context, name, None)
            if callable(candidate):
                memory_api = (name, candidate)
                break
    if memory_api is not None:
        try:
            raw = await _maybe_await(memory_api[1]())
            memories = _read_context_items(raw, safe_memory_limit)
            sources["memories"] = memory_api[0]
        except Exception:
            sources["memories"] = "fallback_empty"
    else:
        sources["memories"] = "fallback_empty"

    return {
        "recent_messages": recent_messages,
        "persona_name": persona_name,
        "memories": memories,
        "sources": sources,
    }


class SceneBridge:
    """Extract current roleplay scene from recent context using a dedicated LLM."""

    _PROMPT_HEAD = (
        "Extract the current visual scene from the conversation for image "
        "generation. Use only facts present in the context. If the scene is "
        "unclear, set confidence low and location to unknown.\n"
    )
    _PROMPT_TAIL = (
        "Return only JSON: "
        '{"location":"...","action":"...","clothing":"...",'
        '"pose":"...","emotion":"...","confidence":0-1}'
    )

    def __init__(
        self,
        llm_fn: LlmFn,
        *,
        filter_fn: ContextFilterFn | None = None,
        context_limit: int = 8,
        draw_threshold: float = DRAW_THRESHOLD,
        ask_threshold: float = ASK_THRESHOLD,
    ) -> None:
        self._llm_fn = llm_fn
        self._filter_fn = filter_fn
        self._context_limit = max(1, int(context_limit))
        self._draw_threshold = draw_threshold
        self._ask_threshold = ask_threshold

    async def decide(
        self,
        user_message: str,
        bot_reply: str,
        *,
        recent_messages: tuple[str, ...] = (),
        persona_name: str = "",
        recipe_summary: str = "",
        memories: tuple[str, ...] = (),
    ) -> SceneBridgeResult:
        started = time.monotonic()
        if not has_visual_intent(user_message):
            return SceneBridgeResult(
                action="skip",
                reason="no_visual_intent",
                latency_ms=(time.monotonic() - started) * 1000,
                trace={"visual_intent": False},
            )
        messages = await self._select_messages(user_message, recent_messages)
        if not messages and not str(bot_reply or "").strip():
            return SceneBridgeResult(
                action="skip",
                reason="empty_context",
                latency_ms=(time.monotonic() - started) * 1000,
            )
        prompt = self._build_prompt(
            user_message,
            bot_reply,
            messages,
            persona_name,
            recipe_summary,
            memories,
        )
        raw = await self._llm_fn(prompt, "You extract roleplay scenes into JSON.", 0.0)
        try:
            facts = self._parse_scene(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return SceneBridgeResult(
                action="ask",
                scene=None,
                reason=f"invalid_scene_json:{type(exc).__name__}",
                latency_ms=(time.monotonic() - started) * 1000,
                trace={"raw": str(raw)[:200]},
            )
        if facts.confidence >= self._draw_threshold and facts.location != "unknown":
            action = "draw"
            reason = "confident_scene"
        elif facts.confidence >= self._ask_threshold:
            action = "ask"
            reason = "scene_needs_confirmation"
        else:
            action = "skip"
            reason = "scene_too_weak"
        return SceneBridgeResult(
            action=action,
            scene=facts,
            reason=reason,
            latency_ms=(time.monotonic() - started) * 1000,
            trace={
                "visual_intent": True,
                "context_messages": len(messages),
                "thresholds": {
                    "draw": self._draw_threshold,
                    "ask": self._ask_threshold,
                },
            },
        )

    async def _select_messages(
        self,
        user_message: str,
        recent_messages: tuple[str, ...],
    ) -> tuple[str, ...]:
        messages = tuple(str(item) for item in recent_messages)
        if not messages:
            return ()
        if self._filter_fn is None:
            return messages[-self._context_limit :]
        try:
            indexes = await self._filter_fn(user_message, messages)
            selected = tuple(messages[index] for index in indexes if 0 <= index < len(messages))
            if not selected:
                return messages[-self._context_limit :]
            return selected[: self._context_limit]
        except Exception:
            return messages[-self._context_limit :]

    def _build_prompt(
        self,
        user_message: str,
        bot_reply: str,
        messages: tuple[str, ...],
        persona_name: str,
        recipe_summary: str,
        memories: tuple[str, ...],
    ) -> str:
        parts = [self._PROMPT_HEAD]
        if persona_name:
            parts.append(f"Persona: {persona_name}\n")
        if messages:
            parts.append("Recent context:\n" + "\n".join(messages[:12]) + "\n")
        if recipe_summary:
            parts.append(f"Session recipe: {recipe_summary}\n")
        if memories:
            parts.append("Memories:\n" + "\n".join(memories[:5]) + "\n")
        parts.append(f"User message: {user_message}\n")
        parts.append(f"Bot reply: {bot_reply}\n")
        parts.append(self._PROMPT_TAIL)
        return "\n".join(parts)

    @staticmethod
    def _parse_scene(raw: str) -> SceneFacts:
        raw = str(raw or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no json object")
        payload = json.loads(raw[start : end + 1])
        confidence = float(payload.get("confidence") or 0.0)
        confidence = min(1.0, max(0.0, confidence))
        return SceneFacts(
            location=str(payload.get("location") or "unknown").strip()[:120],
            action=str(payload.get("action") or "").strip()[:300],
            clothing=str(payload.get("clothing") or "").strip()[:300],
            pose=str(payload.get("pose") or "").strip()[:300],
            emotion=str(payload.get("emotion") or "").strip()[:120],
            confidence=confidence,
        )


__all__ = [
    "ASK_THRESHOLD",
    "DRAW_THRESHOLD",
    "SceneBridge",
    "SceneBridgeResult",
    "SceneFacts",
    "has_visual_intent",
    "scene_context_from_event",
]
