"""Workflow-specific node bindings for bundled and custom API prompts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..models import PluginSettings


class WorkflowProfileError(ValueError):
    """Raised when a workflow manifest is malformed or unsafe."""


@dataclass(frozen=True)
class InputBinding:
    node_id: str
    input_name: str


@dataclass(frozen=True)
class SamplerBinding:
    node_id: str
    steps_input: str = "steps"
    cfg_input: str = "cfg"
    denoise_input: str = "denoise"


@dataclass(frozen=True)
class ResolutionBinding:
    node_id: str
    width_input: str = "width"
    height_input: str = "height"


@dataclass(frozen=True)
class UpscaleBinding:
    node_id: str
    scale_input: str = "resize_type.scale"
    quality_input: str = "quality"


@dataclass(frozen=True)
class OutputVariant:
    preferred_node_ids: tuple[str, ...]
    prune_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowProfile:
    profile_id: str
    display_name: str
    task_type: str = "text_to_image"
    prompt: InputBinding | None = None
    negative: InputBinding | None = None
    unet: InputBinding | None = None
    lora_node_id: str = ""
    seed_bindings: tuple[InputBinding, ...] = ()
    resolution: ResolutionBinding | None = None
    samplers: tuple[SamplerBinding, ...] = ()
    input_image: InputBinding | None = None
    mask_image: InputBinding | None = None
    upscale: UpscaleBinding | None = None
    output_variants: Mapping[str, OutputVariant] = field(default_factory=dict)
    default_output_variant: str = "base"
    defaults: Mapping[str, Any] = field(default_factory=dict)
    source: str = "legacy"

    @property
    def active_output(self) -> OutputVariant:
        variant = self.output_variants.get(self.default_output_variant)
        if variant is not None:
            return variant
        if self.output_variants:
            return next(iter(self.output_variants.values()))
        return OutputVariant(())

    @classmethod
    def from_settings(cls, settings: PluginSettings) -> "WorkflowProfile":
        seeds = [InputBinding(settings.primary_seed_node_id, "")]
        if settings.secondary_seed_node_id:
            seeds.append(InputBinding(settings.secondary_seed_node_id, "seed"))
        return cls(
            profile_id="legacy",
            display_name="Legacy workflow",
            prompt=InputBinding(settings.prompt_node_id, ""),
            negative=InputBinding(settings.negative_node_id, "positive"),
            unet=InputBinding(
                settings.unet_loader_node_id,
                settings.unet_model_input_name,
            ),
            lora_node_id=settings.lora_loader_node_id,
            seed_bindings=tuple(seeds),
            resolution=ResolutionBinding(settings.resolution_node_id),
            samplers=tuple(
                SamplerBinding(node_id) for node_id in settings.sampler_node_ids
            ),
            output_variants={
                "base": OutputVariant(
                    tuple(
                        node_id
                        for node_id in settings.output_node_ids
                        if node_id != settings.upscale_output_node_id
                    ),
                    (
                        (settings.upscale_output_node_id,)
                        if settings.upscale_output_node_id
                        else ()
                    ),
                ),
                "rtx": OutputVariant(tuple(settings.output_node_ids)),
            },
            default_output_variant=("rtx" if settings.enable_upscale else "base"),
        )


def _clean_id(value: Any, label: str, *, allow_empty: bool = False) -> str:
    result = str(value or "").strip()
    if not result and not allow_empty:
        raise WorkflowProfileError(f"{label} is required")
    if result and (len(result) > 64 or any(char in result for char in "\\/\0")):
        raise WorkflowProfileError(f"{label} is invalid")
    return result


def _binding(raw: Any, label: str, *, required: bool = False) -> InputBinding | None:
    if raw in (None, ""):
        if required:
            raise WorkflowProfileError(f"{label} binding is required")
        return None
    if not isinstance(raw, Mapping):
        raise WorkflowProfileError(f"{label} binding must be an object")
    return InputBinding(
        _clean_id(raw.get("node_id"), f"{label}.node_id"),
        _clean_id(raw.get("input"), f"{label}.input"),
    )


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise WorkflowProfileError(f"{label} must be a list")
    return tuple(_clean_id(item, label) for item in value)


def load_workflow_profile(
    workflow_path: Path,
    settings: PluginSettings,
) -> WorkflowProfile:
    """Load ``workflow/manifests/<stem>.json`` or use legacy settings."""

    manifest_path = workflow_path.parent / "manifests" / f"{workflow_path.stem}.json"
    if not manifest_path.is_file():
        return WorkflowProfile.from_settings(settings)
    if manifest_path.stat().st_size > 256 * 1024:
        raise WorkflowProfileError("workflow manifest exceeds 256KB")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowProfileError(f"unable to read workflow manifest: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise WorkflowProfileError("unsupported workflow manifest schema")
    expected_file = _clean_id(payload.get("workflow_file"), "workflow_file")
    if expected_file != workflow_path.name:
        raise WorkflowProfileError("workflow manifest does not match its API file")

    bindings = payload.get("bindings")
    if not isinstance(bindings, Mapping):
        raise WorkflowProfileError("bindings must be an object")
    task_type = str(payload.get("task_type") or "text_to_image").strip()
    if task_type not in {"text_to_image", "upscale", "inpaint"}:
        raise WorkflowProfileError(
            "task_type must be text_to_image, upscale or inpaint"
        )

    seed_raw = bindings.get("seed", [])
    if isinstance(seed_raw, Mapping):
        seed_raw = [seed_raw]
    if not isinstance(seed_raw, list):
        raise WorkflowProfileError("bindings.seed must be a list")
    seeds = tuple(
        binding
        for index, item in enumerate(seed_raw)
        if (binding := _binding(item, f"seed[{index}]")) is not None
    )

    sampler_raw = bindings.get("samplers", [])
    if not isinstance(sampler_raw, list):
        raise WorkflowProfileError("bindings.samplers must be a list")
    samplers: list[SamplerBinding] = []
    for index, item in enumerate(sampler_raw):
        if not isinstance(item, Mapping):
            raise WorkflowProfileError(f"samplers[{index}] must be an object")
        samplers.append(
            SamplerBinding(
                node_id=_clean_id(item.get("node_id"), f"samplers[{index}].node_id"),
                steps_input=_clean_id(
                    item.get("steps_input") or "steps",
                    f"samplers[{index}].steps_input",
                ),
                cfg_input=_clean_id(
                    item.get("cfg_input") or "cfg",
                    f"samplers[{index}].cfg_input",
                ),
                denoise_input=_clean_id(
                    item.get("denoise_input") or "denoise",
                    f"samplers[{index}].denoise_input",
                ),
            )
        )

    resolution_raw = bindings.get("resolution")
    resolution = None
    if resolution_raw is not None:
        if not isinstance(resolution_raw, Mapping):
            raise WorkflowProfileError("bindings.resolution must be an object")
        resolution = ResolutionBinding(
            _clean_id(resolution_raw.get("node_id"), "resolution.node_id"),
            _clean_id(
                resolution_raw.get("width_input") or "width",
                "resolution.width_input",
            ),
            _clean_id(
                resolution_raw.get("height_input") or "height",
                "resolution.height_input",
            ),
        )

    upscale_raw = bindings.get("upscale")
    upscale = None
    if upscale_raw is not None:
        if not isinstance(upscale_raw, Mapping):
            raise WorkflowProfileError("bindings.upscale must be an object")
        upscale = UpscaleBinding(
            _clean_id(upscale_raw.get("node_id"), "upscale.node_id"),
            _clean_id(
                upscale_raw.get("scale_input") or "resize_type.scale",
                "upscale.scale_input",
            ),
            _clean_id(
                upscale_raw.get("quality_input") or "quality",
                "upscale.quality_input",
            ),
        )

    variants_raw = payload.get("output_variants")
    if not isinstance(variants_raw, Mapping) or not variants_raw:
        raise WorkflowProfileError("output_variants must be a non-empty object")
    variants: dict[str, OutputVariant] = {}
    for name, value in variants_raw.items():
        if not isinstance(value, Mapping):
            raise WorkflowProfileError(f"output variant {name} must be an object")
        clean_name = _clean_id(name, "output variant")
        preferred = _string_tuple(value.get("preferred_node_ids"), "preferred_node_ids")
        if not preferred:
            raise WorkflowProfileError(f"output variant {clean_name} has no output")
        variants[clean_name] = OutputVariant(
            preferred,
            _string_tuple(value.get("prune_node_ids"), "prune_node_ids"),
        )

    defaults = payload.get("defaults")
    if not isinstance(defaults, Mapping):
        defaults = {}
    return WorkflowProfile(
        profile_id=_clean_id(payload.get("profile_id"), "profile_id"),
        display_name=str(payload.get("display_name") or workflow_path.stem).strip()[:128],
        task_type=task_type,
        prompt=_binding(
            bindings.get("positive_prompt"),
            "positive_prompt",
            required=task_type in {"text_to_image", "inpaint"},
        ),
        negative=_binding(bindings.get("negative_prompt"), "negative_prompt"),
        unet=_binding(bindings.get("unet"), "unet"),
        lora_node_id=_clean_id(
            (bindings.get("lora") or {}).get("node_id")
            if isinstance(bindings.get("lora"), Mapping)
            else "",
            "lora.node_id",
            allow_empty=True,
        ),
        seed_bindings=seeds,
        resolution=resolution,
        samplers=tuple(samplers),
        input_image=_binding(bindings.get("input_image"), "input_image"),
        mask_image=_binding(bindings.get("mask_image"), "mask_image"),
        upscale=upscale,
        output_variants=variants,
        default_output_variant=_clean_id(
            payload.get("default_output_variant") or next(iter(variants)),
            "default_output_variant",
        ),
        defaults=dict(defaults),
        source=str(manifest_path),
    )


__all__ = [
    "InputBinding",
    "OutputVariant",
    "ResolutionBinding",
    "SamplerBinding",
    "UpscaleBinding",
    "WorkflowProfile",
    "WorkflowProfileError",
    "load_workflow_profile",
]
