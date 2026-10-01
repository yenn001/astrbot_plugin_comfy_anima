"""Minimal local ComfyUI Mira WD Tagger reverse backend."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from ..models import PluginSettings
from .comfy_client import ComfyClient, ComfyClientError
from .danbooru_index import escape_prompt_tag, normalize_tag
from .reverse_evidence import ReverseEvidence


class ReverseWorkflowError(ValueError):
    def __init__(self, user_message: str, *, code: str = "reverse_workflow_error"):
        self.user_message = user_message
        self.code = code
        super().__init__(user_message)


_ALLOWED_CATEGORIES = frozenset(
    {
        "rating",
        "artist",
        "general",
        "character",
        "copyright",
        "meta",
        "model",
        "quality",
    }
)
_ALLOWED_SESSIONS = frozenset({"CPU", "GPU", "GPU Release"})
_FORBIDDEN_OUTPUT_MARKERS = (
    "<lora:",
    "<pic",
    "<edit",
    "http://",
    "https://",
    "assistant:",
    "developer:",
    "system:",
    "ignore previous",
    "disregard previous",
)
_MAX_TAG_COUNT = 1024
_MAX_TAG_LENGTH = 256


def normalize_reverse_tags(value: Any) -> str:
    """Normalize one bounded WD Tagger result into safe Danbooru prompt syntax."""

    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        raise ReverseWorkflowError("本地反推工作流没有返回 Tags", code="empty_tags")
    if re.match(r"^\[Mira:[^\]]+\]\s*Error:", raw, flags=re.IGNORECASE):
        raise ReverseWorkflowError(
            "本地 Mira Tagger 执行失败，请检查 ONNX 与配套映射文件",
            code="tagger_error",
        )
    if len(raw) > 12000:
        raise ReverseWorkflowError("本地反推 Tags 超过安全长度", code="tags_too_large")
    folded = raw.casefold()
    if any(marker in folded for marker in _FORBIDDEN_OUTPUT_MARKERS):
        raise ReverseWorkflowError(
            "本地反推结果包含不允许的控制文本",
            code="unsafe_tags",
        )

    result: list[str] = []
    seen: set[str] = set()
    for raw_term in re.split(r"[,\r\n]+", raw):
        term = raw_term.strip().strip("`\"'").strip()
        if not term:
            continue
        if len(term) > _MAX_TAG_LENGTH or any(
            character in term for character in "<>\0{}[]"
        ):
            raise ReverseWorkflowError(
                "本地反推结果包含无效 Tag",
                code="invalid_tag",
            )
        normalized = normalize_tag(term)
        if not normalized:
            continue
        if len(normalized) > _MAX_TAG_LENGTH:
            raise ReverseWorkflowError(
                "本地反推结果包含过长 Tag",
                code="invalid_tag",
            )
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(escape_prompt_tag(normalized))
        if len(result) > _MAX_TAG_COUNT:
            raise ReverseWorkflowError(
                "本地反推 Tags 数量超过安全上限",
                code="too_many_tags",
            )
    if not result:
        raise ReverseWorkflowError("本地反推工作流没有返回可用 Tags", code="empty_tags")
    return ", ".join(result)


class ReverseWorkflowBuilder:
    """Load and patch the dedicated analysis workflow, never a UI graph."""

    def __init__(self, workflow_path: Path, settings: PluginSettings):
        self._settings = settings
        self._template = self._load(workflow_path)
        manifest_path = (
            workflow_path.parent / "manifests" / f"{workflow_path.stem}.json"
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReverseWorkflowError(
                f"invalid reverse workflow manifest: {exc}"
            ) from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema_version") != 1
            or manifest.get("task_type") != "analysis"
        ):
            raise ReverseWorkflowError(
                "reverse workflow manifest must declare analysis"
            )
        if str(manifest.get("workflow_file") or "").strip() != workflow_path.name:
            raise ReverseWorkflowError(
                "reverse workflow manifest does not match its API file"
            )
        bindings = manifest.get("bindings")
        if not isinstance(bindings, Mapping):
            raise ReverseWorkflowError("reverse workflow bindings are missing")
        self._input = self._binding(bindings.get("input_image"), "input_image")
        self._tagger = self._binding(bindings.get("tagger"), "tagger")
        self._text = self._binding(bindings.get("text_output"), "text_output")
        for node_id in (self._input[0], self._tagger[0], self._text[0]):
            if node_id not in self._template:
                raise ReverseWorkflowError(f"reverse workflow missing node {node_id}")
        self._validate_settings()
        self._validate_bound_inputs()

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ReverseWorkflowError("reverse workflow file is missing")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ReverseWorkflowError("reverse workflow exceeds 2MB")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReverseWorkflowError(f"invalid reverse workflow: {exc}") from exc
        if not isinstance(payload, dict) or not payload:
            raise ReverseWorkflowError("reverse workflow must be a non-empty object")
        if "nodes" in payload:
            raise ReverseWorkflowError("reverse workflow must use ComfyUI API format")
        return payload

    @staticmethod
    def _binding(raw: Any, label: str) -> tuple[str, dict[str, str]]:
        if not isinstance(raw, Mapping):
            raise ReverseWorkflowError(f"reverse {label} binding is missing")
        node_id = str(raw.get("node_id") or "").strip()
        if not node_id:
            raise ReverseWorkflowError(f"reverse {label}.node_id is missing")
        return node_id, {
            str(key): str(value) for key, value in raw.items() if key != "node_id"
        }

    def _validate_settings(self) -> None:
        model = (
            str(self._settings.reverse_tagger_model or "").strip().replace("\\", "/")
        )
        model_path = Path(model)
        if (
            not model
            or model_path.is_absolute()
            or ".." in model_path.parts
            or model_path.suffix.casefold() != ".onnx"
            or model.startswith("~")
            or ":" in model
        ):
            raise ReverseWorkflowError("reverse tagger model path is invalid")
        for label, value in (
            ("general", self._settings.reverse_general_threshold),
            ("character", self._settings.reverse_character_threshold),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
            ):
                raise ReverseWorkflowError(
                    f"reverse tagger {label} threshold is invalid"
                )
        categories = tuple(self._settings.reverse_categories)
        if not categories or any(
            category not in _ALLOWED_CATEGORIES for category in categories
        ):
            raise ReverseWorkflowError("reverse tagger categories are invalid")
        if self._settings.reverse_session_method not in _ALLOWED_SESSIONS:
            raise ReverseWorkflowError("reverse tagger session is invalid")

    def _validate_bound_inputs(self) -> None:
        requirements = (
            (self._input, ("input",)),
            (
                self._tagger,
                (
                    "image_input",
                    "model_input",
                    "general_input",
                    "character_input",
                    "categories_input",
                    "exclude_tags_input",
                    "session_input",
                ),
            ),
        )
        for (node_id, fields), names in requirements:
            node = self._template.get(node_id)
            inputs = node.get("inputs") if isinstance(node, Mapping) else None
            if not isinstance(inputs, Mapping):
                raise ReverseWorkflowError(
                    f"reverse workflow node {node_id} has invalid inputs"
                )
            for name in names:
                input_name = fields.get(name)
                if not input_name or input_name not in inputs:
                    raise ReverseWorkflowError(
                        f"reverse workflow node {node_id} is missing bound input {name}"
                    )

    def build(self, image_name: str) -> tuple[dict[str, Any], list[str]]:
        if not str(image_name or "").strip():
            raise ReverseWorkflowError("reverse workflow image name is missing")
        workflow = copy.deepcopy(self._template)
        input_id, input_fields = self._input
        tagger_id, tagger_fields = self._tagger
        input_inputs = workflow[input_id].get("inputs")
        tagger_inputs = workflow[tagger_id].get("inputs")
        if not isinstance(input_inputs, dict) or not isinstance(tagger_inputs, dict):
            raise ReverseWorkflowError("reverse workflow nodes have invalid inputs")
        input_inputs[input_fields["input"]] = image_name
        tagger_inputs[tagger_fields["model_input"]] = (
            self._settings.reverse_tagger_model
        )
        tagger_inputs[tagger_fields["general_input"]] = float(
            self._settings.reverse_general_threshold
        )
        tagger_inputs[tagger_fields["character_input"]] = float(
            self._settings.reverse_character_threshold
        )
        tagger_inputs[tagger_fields["categories_input"]] = ",".join(
            self._settings.reverse_categories
        )
        tagger_inputs[tagger_fields.get("exclude_tags_input", "exclude_tags")] = ""
        tagger_inputs[tagger_fields["session_input"]] = (
            self._settings.reverse_session_method
        )
        return workflow, [self._text[0]]


class WorkflowReverseService:
    def __init__(
        self,
        client: ComfyClient,
        builder: ReverseWorkflowBuilder,
        settings: PluginSettings,
    ):
        self._client, self._builder, self._settings = client, builder, settings

    async def reverse(self, image_path: Path) -> ReverseEvidence:
        prompt_id = ""

        async def execute() -> str:
            nonlocal prompt_id
            try:
                uploaded = await self._client.upload_image(image_path)
            except ComfyClientError as exc:
                raise ReverseWorkflowError(
                    f"本地反推图片上传失败: {exc.user_message}",
                    code="upload_failed",
                ) from exc
            workflow, output_ids = self._builder.build(uploaded.workflow_value)
            try:
                prompt_id = await self._client.submit(workflow)
            except ComfyClientError as exc:
                raise ReverseWorkflowError(
                    f"本地反推工作流提交失败（请检查节点和模型）: {exc.user_message}",
                    code="submit_failed",
                ) from exc
            try:
                return await self._client.wait_for_text_output(
                    prompt_id,
                    output_ids,
                    max_chars=12000,
                )
            except ComfyClientError as exc:
                raise ReverseWorkflowError(
                    f"本地反推文本输出失败: {exc.user_message}",
                    code="output_failed",
                ) from exc

        try:
            text = await asyncio.wait_for(
                execute(),
                timeout=self._settings.reverse_workflow_timeout,
            )
        except asyncio.TimeoutError as exc:
            if prompt_id:
                await self._client.cancel(prompt_id)
            raise ReverseWorkflowError(
                "本地反推工作流超时",
                code="timeout",
            ) from exc
        except ReverseWorkflowError:
            raise
        normalized = normalize_reverse_tags(text)
        return ReverseEvidence.flat_tagger(
            normalized,
            backend="workflow:wd_tagger_mira",
        )


__all__ = [
    "ReverseWorkflowBuilder",
    "ReverseWorkflowError",
    "WorkflowReverseService",
    "normalize_reverse_tags",
]
