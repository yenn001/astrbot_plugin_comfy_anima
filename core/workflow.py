"""
AstrBot Comfy Anima 插件 v1.1.0

功能描述：
- 加载和修改 ComfyUI API 工作流
- 解析绘图指令中的可选参数

作者: Yen
版本: 1.1.0
日期: 2026-07-14
"""

import copy
import json
import secrets
import shlex
from pathlib import Path
from typing import Any

from ..constants import MAX_CFG, MAX_IMAGE_SIDE, MAX_SEED, MAX_STEPS, MIN_IMAGE_SIDE
from ..models import GenerationOptions, PluginSettings
from .lora import inject_loras
from .workflow_profiles import (
    InputBinding,
    WorkflowProfile,
    WorkflowProfileError,
    load_workflow_profile,
)


class WorkflowError(ValueError):
    """工作流格式或节点映射无效。"""


class WorkflowBuilder:
    """基于模板构造单次 ComfyUI 工作流。"""

    def __init__(self, workflow_path: Path, settings: PluginSettings):
        self._workflow_path = workflow_path
        self._settings = settings
        self._template = self._load_workflow(workflow_path)
        try:
            self._profile = load_workflow_profile(workflow_path, settings)
        except WorkflowProfileError as exc:
            raise WorkflowError(f"工作流档案无效: {exc}") from exc
        self._validate_required_nodes()

    @property
    def profile(self) -> WorkflowProfile:
        return self._profile

    @staticmethod
    def _load_workflow(path: Path) -> dict[str, Any]:
        """加载 ComfyUI API 格式工作流。"""
        if not path.is_file():
            raise WorkflowError(f"工作流文件不存在: {path}")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise WorkflowError("工作流文件超过 10MB，已拒绝加载")
        try:
            with path.open("r", encoding="utf-8") as file:
                workflow = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"工作流读取失败: {exc}") from exc
        if not isinstance(workflow, dict) or not workflow:
            raise WorkflowError("工作流根节点必须是非空对象")
        if "nodes" in workflow:
            raise WorkflowError("检测到 UI 工作流，请先导出为 API Format JSON")
        return workflow

    def _validate_required_nodes(self) -> None:
        """验证生成必需的节点及输入字段。"""
        if self._profile.task_type != "text_to_image":
            raise WorkflowError("当前工作流不是生图工作流")
        binding = self._profile.prompt
        if binding is None:
            raise WorkflowError("工作流档案缺少正面提示词映射")
        node = self._template.get(binding.node_id)
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            raise WorkflowError(f"工作流缺少节点 {binding.node_id}")
        if binding.input_name:
            if binding.input_name not in inputs:
                raise WorkflowError(
                    f"节点 {binding.node_id} 缺少输入 {binding.input_name}"
                )
        elif not any(name in inputs for name in ("positive", "text", "prompt")):
            raise WorkflowError(
                f"节点 {binding.node_id} 缺少 positive、text 或 prompt 文本输入"
            )

        for variant in self._profile.output_variants.values():
            for node_id in variant.preferred_node_ids:
                if node_id not in self._template:
                    raise WorkflowError(f"工作流缺少输出节点 {node_id}")

    def get_template_input(self, node_id: str, input_name: str) -> Any:
        """读取模板节点输入，用于管理命令显示当前模型。"""
        node = self._template.get(node_id)
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            return None
        return copy.deepcopy(inputs.get(input_name))

    def template_sampler_settings(self) -> list[dict[str, Any]]:
        """Return safe sampler defaults for WebUI inspection."""
        result: list[dict[str, Any]] = []
        for binding in self._profile.samplers:
            node = self._template.get(binding.node_id)
            inputs = node.get("inputs") if isinstance(node, dict) else None
            if not isinstance(inputs, dict):
                continue
            result.append(
                {
                    "node_id": binding.node_id,
                    "title": str((node.get("_meta") or {}).get("title") or "Sampler"),
                    "class_type": str(node.get("class_type") or ""),
                    "steps": inputs.get(binding.steps_input),
                    "cfg": inputs.get(binding.cfg_input),
                    "denoise": inputs.get(binding.denoise_input),
                }
            )
        return result

    @staticmethod
    def _resolve_input_name(inputs: dict[str, Any], binding: InputBinding) -> str:
        if binding.input_name:
            return binding.input_name
        for name in ("noise_seed", "seed", "positive", "text", "prompt"):
            if name in inputs:
                return name
        raise WorkflowError(f"节点 {binding.node_id} 没有可写入的兼容输入")

    @staticmethod
    def _set_input(
        workflow: dict[str, Any], node_id: str, input_name: str, value: Any
    ) -> None:
        """设置指定节点输入，节点不存在时抛出明确错误。"""
        node = workflow.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise WorkflowError(f"无法设置节点 {node_id}，节点不存在或格式错误")
        node["inputs"][input_name] = value

    def build(
        self, options: GenerationOptions
    ) -> tuple[dict[str, Any], int, list[str]]:
        """生成一次可提交的工作流副本。

        Args:
            options: 用户本次生成参数。

        Returns:
            工作流、实际随机种和优先输出节点列表。
        """
        workflow = copy.deepcopy(self._template)
        seed = options.seed if options.seed is not None else secrets.randbelow(MAX_SEED)

        unet_binding = self._profile.unet
        if self._settings.unet_model_name and unet_binding is not None:
            unet_node = workflow.get(unet_binding.node_id)
            unet_inputs = (
                unet_node.get("inputs") if isinstance(unet_node, dict) else None
            )
            input_name = unet_binding.input_name
            if not isinstance(unet_inputs, dict) or input_name not in unet_inputs:
                raise WorkflowError(
                    f"工作流缺少 UNET 节点 {unet_binding.node_id} "
                    f"或输入 {input_name}"
                )
            unet_inputs[input_name] = self._settings.unet_model_name

        prompt_binding = self._profile.prompt
        assert prompt_binding is not None
        prompt_inputs = workflow[prompt_binding.node_id]["inputs"]
        prompt_input_name = self._resolve_input_name(prompt_inputs, prompt_binding)
        prompt_inputs[prompt_input_name] = options.prompt.strip()
        if options.dynamic_loras:
            if not self._profile.lora_node_id:
                raise WorkflowError("当前工作流档案没有动态 LoRA 节点")
            inject_loras(
                workflow,
                self._profile.lora_node_id,
                options.dynamic_loras,
                mode=(options.lora_injection_mode or self._settings.dynamic_lora_mode),
            )
        if options.negative_prompt:
            negative_binding = self._profile.negative
            if negative_binding is None:
                raise WorkflowError("当前工作流档案没有负面提示词节点")
            negative_node = workflow.get(negative_binding.node_id)
            if not isinstance(negative_node, dict) or not isinstance(
                negative_node.get("inputs"), dict
            ):
                raise WorkflowError(
                    f"工作流缺少负面提示词节点 {negative_binding.node_id}"
                )
            negative_inputs = negative_node["inputs"]
            input_name = self._resolve_input_name(negative_inputs, negative_binding)
            original = str(negative_inputs.get(input_name, "")).strip()
            combined = ", ".join(
                part for part in (original, options.negative_prompt.strip()) if part
            )
            negative_inputs[input_name] = combined

        for binding in self._profile.seed_bindings:
            seed_node = workflow.get(binding.node_id)
            seed_inputs = (
                seed_node.get("inputs") if isinstance(seed_node, dict) else None
            )
            if not isinstance(seed_inputs, dict):
                continue
            input_name = self._resolve_input_name(seed_inputs, binding)
            seed_inputs[input_name] = seed

        resolution_binding = self._profile.resolution
        resolution_node = (
            workflow.get(resolution_binding.node_id)
            if resolution_binding is not None
            else None
        )
        if isinstance(resolution_node, dict) and isinstance(
            resolution_node.get("inputs"), dict
        ):
            width = (
                options.width
                if options.width is not None
                else self._settings.default_width
            )
            height = (
                options.height
                if options.height is not None
                else self._settings.default_height
            )
            assert resolution_binding is not None
            self._set_input(
                workflow,
                resolution_binding.node_id,
                resolution_binding.width_input,
                width,
            )
            self._set_input(
                workflow,
                resolution_binding.node_id,
                resolution_binding.height_input,
                height,
            )
        elif options.width is not None or options.height is not None:
            raise WorkflowError(
                "当前工作流档案没有可写入的分辨率节点"
            )

        configured_steps = int(getattr(self._settings, "sampler_steps_override", 0) or 0)
        effective_steps = options.steps
        if effective_steps is None and configured_steps > 0:
            effective_steps = configured_steps
        for binding in self._profile.samplers:
            node = workflow.get(binding.node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            if effective_steps is not None:
                node["inputs"][binding.steps_input] = effective_steps
            if options.cfg is not None:
                node["inputs"][binding.cfg_input] = options.cfg

        if self._profile.upscale is not None:
            binding = self._profile.upscale
            upscale_node = workflow.get(binding.node_id)
            inputs = (
                upscale_node.get("inputs")
                if isinstance(upscale_node, dict)
                else None
            )
            if isinstance(inputs, dict):
                inputs[binding.scale_input] = self._settings.rtx_scale
                inputs[binding.quality_input] = self._settings.rtx_quality

        upscale_enabled = (
            self._settings.enable_upscale
            if options.enable_upscale is None
            else options.enable_upscale
        )
        variant_name = "rtx" if upscale_enabled else "base"
        variant = self._profile.output_variants.get(variant_name)
        if variant is None:
            variant = self._profile.active_output
        for node_id in variant.prune_node_ids:
            workflow.pop(node_id, None)
        preferred_nodes = list(variant.preferred_node_ids)

        return workflow, seed, preferred_nodes


class ImageWorkflowBuilder:
    """Build a standalone image-processing workflow such as RTX upscale."""

    def __init__(self, workflow_path: Path, settings: PluginSettings):
        self._workflow_path = workflow_path
        self._settings = settings
        self._template = WorkflowBuilder._load_workflow(workflow_path)
        try:
            self._profile = load_workflow_profile(workflow_path, settings)
        except WorkflowProfileError as exc:
            raise WorkflowError(f"工作流档案无效: {exc}") from exc
        if self._profile.task_type != "upscale" or self._profile.input_image is None:
            raise WorkflowError("当前工作流不是独立图片放大工作流")

    @property
    def profile(self) -> WorkflowProfile:
        return self._profile

    def build(
        self,
        image_name: str,
        *,
        scale: float | None = None,
        quality: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        workflow = copy.deepcopy(self._template)
        input_binding = self._profile.input_image
        WorkflowBuilder._set_input(
            workflow,
            input_binding.node_id,
            input_binding.input_name,
            image_name,
        )
        if self._profile.upscale is not None:
            binding = self._profile.upscale
            WorkflowBuilder._set_input(
                workflow,
                binding.node_id,
                binding.scale_input,
                self._settings.rtx_scale if scale is None else scale,
            )
            WorkflowBuilder._set_input(
                workflow,
                binding.node_id,
                binding.quality_input,
                self._settings.rtx_quality if quality is None else quality,
            )
        variant = self._profile.active_output
        for node_id in variant.prune_node_ids:
            workflow.pop(node_id, None)
        return workflow, list(variant.preferred_node_ids)


def parse_generation_options(command_text: str) -> GenerationOptions:
    """解析 `/anima draw` 后的提示词和选项。

    支持 `--negative`、`--seed`、`--size`、`--steps`、`--cfg`、
    `--upscale`、`--no-upscale`、`--llm`、`--raw` 与 `--preset`。
    含空格的负面词需要使用引号。
    """
    try:
        tokens = shlex.split(command_text, posix=True)
    except ValueError as exc:
        raise ValueError(f"参数引号不完整: {exc}") from exc

    prompt_parts: list[str] = []
    negative_prompt = ""
    seed = None
    width = None
    height = None
    steps = None
    cfg = None
    enable_upscale = None
    use_prompt_llm = None
    lora_preset = ""
    index = 0

    def require_value(option: str) -> str:
        nonlocal index
        if index + 1 >= len(tokens):
            raise ValueError(f"{option} 缺少参数")
        index += 1
        return tokens[index]

    while index < len(tokens):
        token = tokens[index]
        if token == "--negative":
            negative_prompt = require_value(token)
        elif token == "--seed":
            value = require_value(token)
            try:
                seed = int(value)
            except ValueError as exc:
                raise ValueError("--seed 必须是整数") from exc
            if seed < 0 or seed > MAX_SEED:
                raise ValueError(f"--seed 必须在 0 到 {MAX_SEED} 之间")
        elif token == "--size":
            value = require_value(token).lower().replace("×", "x")
            try:
                width_text, height_text = value.split("x", 1)
                width, height = int(width_text), int(height_text)
            except (ValueError, AttributeError) as exc:
                raise ValueError("--size 格式应为 宽x高，例如 832x1216") from exc
            if not (
                MIN_IMAGE_SIDE <= width <= MAX_IMAGE_SIDE
                and MIN_IMAGE_SIDE <= height <= MAX_IMAGE_SIDE
            ):
                raise ValueError(
                    f"宽高必须在 {MIN_IMAGE_SIDE} 到 {MAX_IMAGE_SIDE} 之间"
                )
        elif token == "--steps":
            try:
                steps = int(require_value(token))
            except ValueError as exc:
                raise ValueError("--steps 必须是整数") from exc
            if not 1 <= steps <= MAX_STEPS:
                raise ValueError(f"--steps 必须在 1 到 {MAX_STEPS} 之间")
        elif token == "--cfg":
            try:
                cfg = float(require_value(token))
            except ValueError as exc:
                raise ValueError("--cfg 必须是数字") from exc
            if not 0 <= cfg <= MAX_CFG:
                raise ValueError(f"--cfg 必须在 0 到 {MAX_CFG:g} 之间")
        elif token == "--upscale":
            enable_upscale = True
        elif token == "--no-upscale":
            enable_upscale = False
        elif token == "--llm":
            use_prompt_llm = True
        elif token in {"--raw", "--no-llm"}:
            use_prompt_llm = False
        elif token in {"--preset", "--lora-preset"}:
            lora_preset = require_value(token).strip()
        elif token.startswith("--"):
            raise ValueError(f"未知选项: {token}")
        else:
            prompt_parts.append(token)
        index += 1

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        raise ValueError("请输入绘图提示词")
    return GenerationOptions(
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        enable_upscale=enable_upscale,
        use_prompt_llm=use_prompt_llm,
        lora_preset=lora_preset,
    )
