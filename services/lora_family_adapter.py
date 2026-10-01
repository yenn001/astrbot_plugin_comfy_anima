"""Explicit, pure model-family LoRA selection and native bypass adapter.

Keeps model-family routing clean and decoupled from LoraCatalog asset indexing.
Zero hardcoding: all adaptations rely on declarative record metadata and
companion variants.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Mapping, Optional, Sequence

from ..core.lora import canonical_lora_name
from ..models import LoraSelection
from .lora_catalog import LoraRecord
from .lora_compatibility import ANIMA_29B_FAMILY

logger = logging.getLogger("astrbot")

_29B_PATTERNS = re.compile(r"(?:2\.9b|29b|40l)", re.IGNORECASE)


def is_29b_model_family(target_family: str, workflow_or_model: str = "") -> bool:
    """Return True if the target family or current model/workflow indicates Anima 2.9B."""
    tf = str(target_family or "").strip().casefold()
    if tf == ANIMA_29B_FAMILY.casefold():
        return True
    combined = f"{target_family} {workflow_or_model}".casefold()
    return bool(_29B_PATTERNS.search(combined))


def adapt_lora_selections_for_target(
    selections: Sequence[LoraSelection],
    target_family: str,
    records_by_name: Mapping[str, LoraRecord],
    *,
    workflow_or_model: str = "",
) -> tuple[tuple[LoraSelection, ...], tuple[LoraRecord, ...], tuple[str, ...]]:
    """Adapt dynamic LoRA selections to match the active model family.

    Args:
        selections: Raw parsed or user-specified dynamic LoRA selections.
        target_family: The active target model family (e.g. anima_29b_40l or legacy).
        records_by_name: Fresh catalog records indexed by canonical and base names.
        workflow_or_model: Optional active workflow file or checkpoint/UNet name.

    Returns:
        tuple of (
            adapted_selections: LoRA selections to be loaded in the workflow,
            bypassed_native_records: Records whose weights were bypassed because
                the base model natively carries the character (Tag-only mode),
            audit_logs: Explicit machine/human readable adaptation audit records.
        )
    """
    is_29b = is_29b_model_family(target_family, workflow_or_model)
    effective_family = ANIMA_29B_FAMILY if is_29b else "anima_legacy_28l"

    adapted: list[LoraSelection] = []
    bypassed: list[LoraRecord] = []
    audit_logs: list[str] = []

    for sel in selections:
        c_name = canonical_lora_name(sel.name)
        rec = records_by_name.get(c_name.casefold())
        if rec is None:
            # Fallback to basename lookup if subfolder was omitted
            rec = records_by_name.get(c_name.rsplit("/", 1)[-1].casefold())

        if rec is None:
            adapted.append(sel)
            continue

        # 1. 声明式内生角色免挂检测 (Native Base Character Bypass)
        native_families = tuple(
            str(f).strip().casefold() for f in rec.native_in_families if str(f).strip()
        )
        compat_families = tuple(
            str(f).strip().casefold() for f in rec.compatible_model_families if str(f).strip()
        )
        is_declared_native = (
            effective_family.casefold() in native_families
            or (is_29b and rec.compatibility_mode == "native_29b" and ANIMA_29B_FAMILY.casefold() in compat_families)
        )
        if effective_family.casefold() in native_families:
            bypassed.append(rec)
            msg = (
                f"角色 [{rec.character_name or rec.name}] 属于 {effective_family} "
                f"原生内生角色，自动免挂 LoRA 节点，仅注入特征 Tag。"
            )
            audit_logs.append(msg)
            logger.info(f"[ComfyAnima] {msg}")
            continue

        # 2. 变体自动切换 (Companion Variant Adaptation)
        companion = rec.companion_variant
        is_sel_29b = bool(
            c_name.casefold().startswith("29b/")
            or re.search(r"[-_](?:29b(?:_40l)?|40l)$", c_name, re.IGNORECASE)
            or is_declared_native
        )

        # 场景 A: 当前是 2.9B 底模，但选了原版，且有配对的 _29b 变体 -> 自动提升为 29b
        if is_29b and not is_sel_29b and companion:
            new_name = canonical_lora_name(companion)
            adapted.append(replace(sel, name=new_name))
            msg = f"目标底模为 2.9B，自动将 LoRA [{sel.name}] 切换为专属变体 [{new_name}]。"
            audit_logs.append(msg)
            logger.info(f"[ComfyAnima] {msg}")

        # 场景 A2: 当前是 2.9B 底模，但该 LoRA 既不是 _29b 也没有 _29b 变体 -> 自动剥离（禁止混入非 29b 的旧 LoRA）
        elif is_29b and not is_sel_29b:
            msg = f"目标底模为 2.9B，已自动拦截并剥离非 2.9B 架构的旧 LoRA [{sel.name}]，防止模型过拟合或画风崩坏。"
            audit_logs.append(msg)
            logger.warning(f"[ComfyAnima] {msg}")

        # 场景 B: 当前是常规底模，但选了 _29b 变体，且有配对的原版 -> 自动回退为原版
        elif not is_29b and is_sel_29b and companion:
            new_name = canonical_lora_name(companion)
            adapted.append(replace(sel, name=new_name))
            msg = f"目标底模为常规模型，自动将 2.9B 变体 [{sel.name}] 回退为原版模型 [{new_name}]。"
            audit_logs.append(msg)
            logger.info(f"[ComfyAnima] {msg}")

        else:
            adapted.append(sel)

    return tuple(adapted), tuple(bypassed), tuple(audit_logs)


__all__ = [
    "adapt_lora_selections_for_target",
    "is_29b_model_family",
]
