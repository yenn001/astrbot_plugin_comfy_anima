"""Deterministic ordinary-chat intent classifier.

Decision order is fixed and deliberately asymmetric:

    debug_only > continuation > draw_new > edit_last_image > query_only > clarify

Debug queries must never turn into art, and continuations require a stored
session recipe; without one they degrade to ``clarify`` instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


INTENT_DEBUG_ONLY = "debug_only"
INTENT_QUERY_ONLY = "query_only"
INTENT_DRAW_NEW = "draw_new"
INTENT_EDIT_LAST_IMAGE = "edit_last_image"
INTENT_CLARIFY = "clarify"

PROBE_PROMPT_PLAN = "prompt_plan"
PROBE_LORA = "lora"
PROBE_LORA_PRESETS = "lora_presets"
PROBE_DANBOORU = "danbooru"
PROBE_SUBJECT = "subject_resolution"
PROBE_PREVIOUS_IMAGE = "previous_image"


@dataclass(frozen=True)
class ChatIntentDecision:
    intent: str
    visual_delivery: bool
    needs_previous_image: bool
    confidence: float
    source: str = "deterministic"
    rationale: str = ""
    recipe: Optional[Any] = None


@dataclass(frozen=True)
class IntentPlan:
    """Deterministic asset-probe plan; never contains model-authored tools."""

    intent: str
    visual_delivery: bool
    needs_previous_image: bool
    required_probes: tuple[str, ...]
    optional_probes: tuple[str, ...]
    requested_subject: str
    identity_required: bool
    rationale: str = ""
    decision: Optional[ChatIntentDecision] = None

    @property
    def all_probes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.required_probes, *self.optional_probes)))


_DEBUG_QUERY_RE = re.compile(
    r"日志|检查日志|看看日志|看下日志|查日志|看看怎么回事|看下怎么回事|"
    r"为什么失败|为啥失败|怎么失败|刚才失败|刚刚失败|报错|错误|异常|状态|"
    r"排查|debug|debug_only|怎么没出图|为什么没出|为什么没发|怎么没发|"
    r"(?:^|[\s，。！？!?、])(?:我)?(?:想看|看看|看下|看看你|看下你)?"
    r"你在干嘛(?:呢|吗)?(?:$|[\s，。！？!?、])|"
    r"(?:^|[\s，。！？!?、])(?:我)?(?:想看|看看|看下)?"
    r"你在(?:做什么|忙什么)(?:呢|吗)?(?:$|[\s，。！？!?、])",
    flags=re.IGNORECASE,
)

_CONTINUATION_RE = re.compile(
    r"^(?:现在|马上|立刻|这就)?\s*(?:发给我|发我|发出来|发出来看看|让我看看|给我看看|"
    r"再拍一张|再画一张|再来一张|再出一张|继续|把刚才那张发我|把上一张发我|"
    r"看看上一张|看下上一张)"
    r"(?:[。．.！!？?\s]*)$",
    flags=re.IGNORECASE,
)

_DRAW_NEW_RE = re.compile(
    r"以后都给我照片|以后都发照片|每次都要照片|照片，以后都|"
    r"画(?:一张|一个|一下|一套|一组)?|生成(?:一张|图片|图像|图)?|出一张图?|"
    r"来一张|拍一张|照一张|绘图|生图|出图|"
    r"(?:想看|我要看|我想看|我想要看|给我看|让我看看|看看).{0,20}"
    r"(?:照片|图片|图像|画面|自拍|成图|效果图|什么样子|样子|图)",
    flags=re.IGNORECASE,
)

_EDIT_LAST_RE = re.compile(
    r"换(?:成|上)?.{0,24}(?:造型|衣服|服装|发型|背景|姿势)|"
    r"改(?:一下|一改)?(?:上一张|这张|刚才|这图)|"
    r"重画|局部重绘|inpaint|edit_last",
    flags=re.IGNORECASE,
)

_QUERY_ONLY_RE = re.compile(
    r"^(?:查询|搜索|查找|查一下|找一下|找一个|看看|列出|有没有|是否有|有哪些|"
    r"list|search|find)",
    flags=re.IGNORECASE,
)

_NEGATED_DRAW_RE = re.compile(
    r"(?:不要|不用|别|无需|不想|拒绝|禁止).{0,20}"
    r"(?:画|生成|发|给|看|出|提交).{0,12}(?:图|照片|图片|画面|pic)",
    flags=re.IGNORECASE,
)


def _normalized(message: str) -> str:
    return re.sub(r"\s+", " ", str(message or "")).strip()


def classify_chat_intent(
    message: str,
    *,
    has_recipe: bool = False,
    strict: bool = False,
) -> ChatIntentDecision:
    """Classify one user message with deterministic rules only."""

    source = _normalized(message)
    if not source:
        return ChatIntentDecision(
            INTENT_CLARIFY,
            visual_delivery=False,
            needs_previous_image=False,
            confidence=0.0,
            rationale="empty message",
        )

    if _DEBUG_QUERY_RE.search(source):
        return ChatIntentDecision(
            INTENT_DEBUG_ONLY,
            visual_delivery=False,
            needs_previous_image=False,
            confidence=1.0,
            rationale="debug/log/status query has priority over drawing",
        )

    if _NEGATED_DRAW_RE.search(source):
        if _QUERY_ONLY_RE.search(source):
            return ChatIntentDecision(
                INTENT_QUERY_ONLY,
                visual_delivery=False,
                needs_previous_image=False,
                confidence=0.95,
                rationale="negated drawing request with a query",
            )
        return ChatIntentDecision(
            INTENT_CLARIFY,
            visual_delivery=False,
            needs_previous_image=False,
            confidence=0.95,
            rationale="drawing was explicitly negated",
        )

    if _CONTINUATION_RE.search(source):
        if not has_recipe:
            return ChatIntentDecision(
                INTENT_CLARIFY,
                visual_delivery=False,
                needs_previous_image=True,
                confidence=1.0,
                rationale="continuation without a stored session recipe",
            )
        return ChatIntentDecision(
            INTENT_DRAW_NEW,
            visual_delivery=True,
            needs_previous_image=True,
            confidence=1.0,
            rationale="continuation reuses the stored session recipe",
        )

    if strict:
        return ChatIntentDecision(
            INTENT_CLARIFY,
            visual_delivery=False,
            needs_previous_image=False,
            confidence=0.0,
            rationale="strict mode requires an explicit drawing command",
        )

    if _EDIT_LAST_RE.search(source):
        return ChatIntentDecision(
            INTENT_EDIT_LAST_IMAGE,
            visual_delivery=True,
            needs_previous_image=True,
            confidence=0.9,
            rationale="explicit edit/redraw phrasing",
        )

    if _DRAW_NEW_RE.search(source):
        return ChatIntentDecision(
            INTENT_DRAW_NEW,
            visual_delivery=True,
            needs_previous_image=False,
            confidence=0.85,
            rationale="explicit drawing phrasing",
        )

    if _QUERY_ONLY_RE.search(source):
        return ChatIntentDecision(
            INTENT_QUERY_ONLY,
            visual_delivery=False,
            needs_previous_image=False,
            confidence=0.9,
            rationale="asset query phrasing",
        )

    return ChatIntentDecision(
        INTENT_CLARIFY,
        visual_delivery=False,
        needs_previous_image=False,
        confidence=0.0,
        rationale="no deterministic drawing intent",
    )


def build_intent_plan(
    message: str,
    *,
    decision: Optional[ChatIntentDecision] = None,
    requested_subject: str = "",
    identity_required: bool = False,
    has_recipe: bool = False,
    recipe_has_preset: bool = False,
) -> IntentPlan:
    """Build the deterministic probe plan for one user message.

    The returned probe names are a fixed read-only tool budget: optional probes
    may be dropped by the runtime, required probes may not. The model cannot
    request tools outside this plan.
    """

    resolved = decision or classify_chat_intent(message, has_recipe=has_recipe)
    source = _normalized(message)
    subject = str(requested_subject or "").strip()
    required: list[str] = []
    optional: list[str] = []
    rationale_parts = [str(resolved.rationale or "")]

    if resolved.intent is INTENT_EDIT_LAST_IMAGE:
        required.append(PROBE_PREVIOUS_IMAGE)
        rationale_parts.append("edit intent requires the previous image")

    if "方案" in source or "预设方案" in source or "prompt plan" in source.casefold():
        required.append(PROBE_PROMPT_PLAN)
        optional.extend([PROBE_LORA, PROBE_DANBOORU])
        rationale_parts.append("prompt plan mention requires a deterministic plan lookup")

    preset_combo = bool(
        re.search(
            r"预设|风格\d{3}|组合|combo", source, flags=re.IGNORECASE
        )
    )
    if preset_combo:
        required.append(PROBE_LORA_PRESETS)
        optional.extend([PROBE_LORA, PROBE_DANBOORU])
        rationale_parts.append("preset/style combo mention requires preset probe")

    if subject and resolved.intent in {INTENT_DRAW_NEW, INTENT_EDIT_LAST_IMAGE}:
        required.append(PROBE_SUBJECT)
        optional.extend([PROBE_LORA_PRESETS, PROBE_LORA, PROBE_DANBOORU])
        rationale_parts.append("named subject requires deterministic resolution")

    if identity_required:
        if PROBE_SUBJECT not in required:
            required.append(PROBE_SUBJECT)
        rationale_parts.append("identity binding is required before generation")

    explicit_lora = bool(
        re.search(
            r"\blora\b|\.safetensors|characters/|lora:", source, flags=re.IGNORECASE
        )
    )
    if explicit_lora and resolved.intent in {INTENT_DRAW_NEW, INTENT_EDIT_LAST_IMAGE}:
        required.append(PROBE_LORA)
        optional.append(PROBE_DANBOORU)
        rationale_parts.append("explicit LoRA reference requires the LoRA tool path")

    if resolved.intent in {INTENT_DRAW_NEW, INTENT_EDIT_LAST_IMAGE}:
        optional.append(PROBE_DANBOORU)
        if recipe_has_preset and not preset_combo:
            optional.append(PROBE_LORA_PRESETS)
        optional.append(PROBE_LORA)

    required_tuple = tuple(dict.fromkeys(required))
    optional_tuple = tuple(
        probe for probe in dict.fromkeys(optional) if probe not in required_tuple
    )
    return IntentPlan(
        intent=resolved.intent,
        visual_delivery=resolved.visual_delivery,
        needs_previous_image=resolved.needs_previous_image,
        required_probes=required_tuple,
        optional_probes=optional_tuple,
        requested_subject=subject,
        identity_required=bool(identity_required),
        rationale="; ".join(part for part in rationale_parts if part),
        decision=resolved,
    )


def intent_allows_picture_tools(intent: str) -> bool:
    """Return whether the intent may retain asset/delivery tool visibility."""

    return intent in {INTENT_DRAW_NEW, INTENT_EDIT_LAST_IMAGE, INTENT_QUERY_ONLY}
