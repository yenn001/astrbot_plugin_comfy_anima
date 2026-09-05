"""
AstrBot Comfy Anima 插件 - 中文服饰/场景提示词翻译器。

作者: Yen
版本: 3.1.400
日期: 2026-08-31
"""

from __future__ import annotations

import inspect
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_WHITESPACE_RE = re.compile(r"\s+")

EmbedFn = Callable[[list[str]], Any]
RerankFn = Callable[[str, list[str]], Any]
LlmFn = Callable[[str, str, float], Any]

# A1 内置词典。按键长到短匹配，避免“穿”先于“穿着”被替换。
_A1_DICTIONARY: dict[str, str] = {
    "JK制服": "school uniform, pleated skirt",
    "水手服": "sailor uniform",
    "女仆装": "maid outfit",
    "护士装": "nurse outfit",
    "自拍": "selfie, looking at viewer, camera facing her",
    "兔女郎": "bunny girl",
    "洛丽塔": "lolita fashion",
    "吊带袜": "garter belt, thighhighs",
    "过膝袜": "thighhighs",
    "长筒袜": "thighhighs",
    "连裤袜": "pantyhose",
    "黑丝": "black pantyhose",
    "白丝": "white pantyhose",
    "丝袜": "pantyhose",
    "裸足": "barefoot",
    "旗袍": "cheongsam",
    "汉服": "hanfu",
    "和服": "kimono",
    "校服": "school uniform",
    "泳装": "swimsuit",
    "睡衣": "pajamas",
    "婚纱": "wedding dress",
    "西装": "suit",
    "衬衫": "shirt",
    "卫衣": "hoodie",
    "毛衣": "sweater",
    "外套": "coat",
    "风衣": "trench coat",
    "制服": "uniform",
    "连衣裙": "dress",
    "短裙": "miniskirt",
    "百褶裙": "pleated skirt",
    "裙子": "skirt",
    "内衣": "lingerie",
    "围裙": "apron",
    "围巾": "scarf",
    "手套": "gloves",
    "袜子": "socks",
    "高跟鞋": "high heels",
    "运动鞋": "sneakers",
    "靴子": "boots",
    "帽子": "hat",
    "眼镜": "glasses",
    "耳环": "earrings",
    "项链": "necklace",
    "手链": "bracelet",
    "戒指": "ring",
    "发饰": "hair ornament",
    "蝴蝶结": "ribbon",
    "领带": "necktie",
    "项圈": "choker",
    "猫耳": "cat ears",
    "兔耳": "rabbit ears",
    "尾巴": "tail",
    "翅膀": "wings",
    "教室": "classroom",
    "图书馆": "library",
    "卧室": "bedroom",
    "厨房": "kitchen",
    "浴室": "bathroom",
    "海滩": "beach",
    "游泳池": "swimming pool",
    "操场": "schoolyard",
    "天台": "rooftop",
    "樱花": "cherry blossoms",
    "街道": "street",
    "咖啡厅": "cafe",
    "餐厅": "restaurant",
    "办公室": "office",
    "公园": "park",
    "森林": "forest",
    "雪山": "snowy mountain",
    "夜景": "night scene",
    "雨天": "rainy day",
    "雪天": "snowy day",
    "黄昏": "sunset",
    "清晨": "morning",
    "白天": "daytime",
    "夜晚": "night",
    "室内": "indoors",
    "室外": "outdoors",
    "窗边": "by the window",
    "床上": "on the bed",
    "沙发上": "on the sofa",
    "椅子上": "on the chair",
    "桌子上": "on the desk",
    "地板上": "on the floor",
    "穿着": "wearing",
    "身穿": "wearing",
    "戴着": "wearing",
    "戴上": "wearing",
    "穿": "wearing",
    "搭配": "with",
    "少女": "girl",
    "少年": "boy",
    "女孩": "girl",
    "男孩": "boy",
    "女人": "woman",
    "男人": "man",
    "微笑": "smile",
    "表情": "expression",
    "姿势": "pose",
    "站着": "standing",
    "坐着": "sitting",
    "躺着": "lying",
    "走路": "walking",
    "奔跑": "running",
    "跳舞": "dancing",
    "唱歌": "singing",
    "看书": "reading",
    "喝": "drinking",
    "吃": "eating",
    "拿": "holding",
    "抱": "holding",
    "和": "and",
    "与": "and",
    "在": "in",
    "里": "in",
}

_LLM_SYSTEM_PROMPT = (
    "You translate a short Chinese clothing/scene fragment into one short "
    "English phrase suitable for an anime image prompt. Return only the "
    "English translation. Do not add quotes, punctuation, explanations, or "
    "any Chinese text."
)
_LLM_TEMPERATURE = 0.2


def _as_float_vector(value: Any) -> tuple[float, ...]:
    """Normalize an embedding result to a flat tuple of floats."""
    try:
        values = list(value)
    except TypeError:
        return ()
    result: list[float] = []
    for item in values:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            result.append(float(item))
        else:
            return ()
    return tuple(result)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity, or NaN when either vector is empty."""
    if not left or not right or len(left) != len(right):
        return math.nan
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return math.nan
    return dot / (left_norm * right_norm)


async def _maybe_await(value: Any) -> Any:
    """Await coroutine callback results while also supporting sync callbacks."""
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True)
class ChinesePromptTranslation:
    """One fragment translation result."""

    translated: str
    source: str
    confidence: float = 0.0
    latency_ms: float = 0.0
    trace: tuple[str, ...] = ()


class ChinesePromptTranslator:
    """Translate short Chinese clothing/scene fragments to English.

    Pipeline order is A2 (embedding/rerank tag library), A1 (built-in
    dictionary), B (LLM fallback). ``source`` is ``"a2"``, ``"a1"``, ``"b"``
    or ``"none"``. A1 may return a partial translation when known terms are
    embedded in a longer Chinese fragment; unknown Chinese remains untouched.
    When no backend produces any translation, the original text is returned
    with ``source="none"``.
    """

    def __init__(
        self,
        *,
        tag_library: Sequence[str] | None = None,
        embed_fn: EmbedFn | None = None,
        rerank_fn: RerankFn | None = None,
        llm_fn: LlmFn | None = None,
        a2_top_k: int = 20,
        a2_margin_threshold: float = 0.05,
    ) -> None:
        self._tag_library = tuple(dict.fromkeys(tag_library or ()))
        self._embed_fn = embed_fn
        self._rerank_fn = rerank_fn
        self._llm_fn = llm_fn
        self._a2_top_k = max(1, int(a2_top_k))
        self._a2_margin_threshold = float(a2_margin_threshold)

    async def translate(self, text: str) -> ChinesePromptTranslation:
        """Translate one Chinese fragment through the A2 -> A1 -> B pipeline."""
        fragment = str(text or "").strip()
        started_at = time.monotonic()
        if not _HAN_RE.search(fragment):
            return ChinesePromptTranslation(
                fragment,
                "none",
                0.0,
                _elapsed_ms(started_at),
                ("none: no Chinese text",),
            )

        trace: list[str] = []
        a2_result = await self._translate_a2(fragment, trace)
        if a2_result is not None:
            translated, confidence, source_trace = a2_result
            return ChinesePromptTranslation(
                translated,
                "a2",
                confidence,
                _elapsed_ms(started_at),
                tuple(trace + source_trace),
            )

        a1_result = self._translate_a1(fragment)
        if a1_result is not None:
            translated, confidence, source_trace = a1_result
            return ChinesePromptTranslation(
                translated,
                "a1",
                confidence,
                _elapsed_ms(started_at),
                tuple(trace + source_trace),
            )

        b_result = await self._translate_b(fragment, trace)
        if b_result is not None:
            translated, confidence, source_trace = b_result
            return ChinesePromptTranslation(
                translated,
                "b",
                confidence,
                _elapsed_ms(started_at),
                tuple(trace + source_trace),
            )

        trace.append("none: no backend translated the fragment")
        return ChinesePromptTranslation(
            fragment,
            "none",
            0.0,
            _elapsed_ms(started_at),
            tuple(trace),
        )

    async def _translate_a2(
        self,
        fragment: str,
        trace: list[str],
    ) -> tuple[str, float, list[str]] | None:
        if not self._tag_library or self._embed_fn is None or self._rerank_fn is None:
            trace.append("a2: skipped (no tag library or callbacks)")
            return None
        source_trace: list[str] = []
        try:
            vectors = await _maybe_await(
                self._embed_fn([fragment, *self._tag_library])
            )
            query_vector = (
                _as_float_vector(vectors[0]) if len(vectors) else ()
            )
            doc_vectors = [_as_float_vector(item) for item in vectors[1:]]
            if len(doc_vectors) != len(self._tag_library) or not query_vector:
                source_trace.append(
                    "a2: invalid embedding result (vector count mismatch)"
                )
                trace.extend(source_trace)
                return None
            scored: list[tuple[int, float]] = []
            for index, doc_vector in enumerate(doc_vectors):
                score = _cosine_similarity(query_vector, doc_vector)
                if math.isnan(score):
                    continue
                scored.append((index, score))
            scored.sort(key=lambda item: item[1], reverse=True)
            top = scored[: self._a2_top_k]
            if not top:
                source_trace.append("a2: no valid embedding similarities")
                trace.extend(source_trace)
                return None
            docs = [self._tag_library[index] for index, _score in top]
            rerank_raw = await _maybe_await(self._rerank_fn(fragment, docs))
            rerank_scores = [] if rerank_raw is None else list(rerank_raw)
            if len(rerank_scores) == len(docs):
                final_scores = rerank_scores
            else:
                final_scores = [score for _index, score in top]
            best_index = max(range(len(final_scores)), key=final_scores.__getitem__)
            best_score = float(final_scores[best_index])
            if len(final_scores) >= 2:
                second_score = sorted(final_scores, reverse=True)[1]
                margin = best_score - second_score
            else:
                margin = 0.0
            if margin < self._a2_margin_threshold:
                source_trace.append(
                    f"a2: best margin {margin:.3f} below threshold "
                    f"{self._a2_margin_threshold:.3f}"
                )
                trace.extend(source_trace)
                return None
            best_tag = str(docs[best_index]).strip()
            source_trace.append(f'a2: matched "{best_tag}"')
            return best_tag, best_score, source_trace
        except Exception as exc:
            source_trace.append(f"a2: error {type(exc).__name__}")
            trace.extend(source_trace)
            return None

    def _translate_a1(
        self,
        fragment: str,
    ) -> tuple[str, float, list[str]] | None:
        translated = fragment
        matched: list[str] = []
        for chinese, english in sorted(
            _A1_DICTIONARY.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if chinese in translated:
                translated = translated.replace(chinese, f" {english} ")
                matched.append(chinese)
        if not matched:
            return None
        cleaned = _WHITESPACE_RE.sub(" ", translated).strip()
        if _HAN_RE.search(translated):
            confidence = min(0.9, 0.55 + 0.05 * len(matched))
            return cleaned, confidence, [
                f"a1: partial matched {len(matched)} phrase(s)"
            ]
        confidence = min(0.98, 0.6 + 0.05 * len(matched))
        return cleaned, confidence, [f"a1: matched {len(matched)} phrase(s)"]

    async def _translate_b(
        self,
        fragment: str,
        trace: list[str],
    ) -> tuple[str, float, list[str]] | None:
        if self._llm_fn is None:
            trace.append("b: skipped (no llm_fn)")
            return None
        source_trace: list[str] = []
        try:
            raw = await _maybe_await(
                self._llm_fn(fragment, _LLM_SYSTEM_PROMPT, _LLM_TEMPERATURE)
            )
            translated = _WHITESPACE_RE.sub(" ", str(raw or "")).strip()
            translated = translated.strip("\"'“”‘’` ")
            if not translated or _HAN_RE.search(translated):
                source_trace.append("b: empty or Chinese output rejected")
                trace.extend(source_trace)
                return None
            source_trace.append("b: llm fallback")
            return translated, 0.85, source_trace
        except Exception as exc:
            source_trace.append(f"b: error {type(exc).__name__}")
            trace.extend(source_trace)
            return None


def _elapsed_ms(started_at: float) -> float:
    return round(max(0.0, time.monotonic() - started_at) * 1000.0, 3)


__all__ = [
    "ChinesePromptTranslation",
    "ChinesePromptTranslator",
    "EmbedFn",
    "LlmFn",
    "RerankFn",
]
