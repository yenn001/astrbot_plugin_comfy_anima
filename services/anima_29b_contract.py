"""Auditable Anima 2.9B model and legacy-LoRA compatibility facts."""

from __future__ import annotations

from dataclasses import dataclass


INSERTED_TO_SOURCE = {
    2: 1,
    5: 3,
    8: 5,
    11: 7,
    14: 9,
    17: 11,
    21: 14,
    24: 16,
    27: 18,
    30: 20,
    33: 22,
    36: 24,
}


def legacy_block_mapping(*, duplicate: bool = True) -> dict[int, tuple[int, ...]]:
    """Return the documented 28-layer -> 40-layer block mapping."""
    order: list[int | None] = [None] * 40
    iterator = iter(range(28))
    for index in range(40):
        source = INSERTED_TO_SOURCE.get(index)
        order[index] = source if source is not None else next(iterator)
    mapping: dict[int, list[int]] = {}
    for new_index, source in enumerate(order):
        assert source is not None
        mapping.setdefault(source, []).append(new_index)
    return {
        source: tuple(indices if duplicate else indices[:1])
        for source, indices in mapping.items()
    }


@dataclass(frozen=True)
class Anima29BContract:
    model_family: str = "anima_29b_40l"
    unet_model_name: str = "Anima-2.9B-preview-v1.safetensors"
    clip_model_name: str = "qwen_3_06b_base.safetensors"
    vae_model_name: str = "qwen_image_vae.safetensors"
    patch_node_type: str = "ComfyUI-Anima-2.9B"
    patch_contract_id: str = "anima29b-runtime-patch:detect-unet-blocks-28-to-40@2de99f23e31ccf75d1a0f3d04c16ac5cfcd320e6"
    verification_status: str = "needs_review"


__all__ = ["Anima29BContract", "INSERTED_TO_SOURCE", "legacy_block_mapping"]
