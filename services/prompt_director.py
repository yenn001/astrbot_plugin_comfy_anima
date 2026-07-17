"""
AstrBot Comfy Anima 插件 v1.1.1

功能描述：
- 使用 AstrBot 中选定的聊天模型规划单图分镜
- 将模型输出规范化为可提交给 Anima 工作流的英文提示词

作者: Yen
版本: 1.1.1
日期: 2026-07-14
"""

import asyncio
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.lora import LORA_TAG_PATTERN
from ..models import PluginSettings


_PIC_TAG_RE = re.compile(
    r"<pic\b(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)/?>",
    flags=re.IGNORECASE | re.DOTALL,
)
_ANY_PIC_TAG_RE = re.compile(r"</?pic\b[^>]*>", flags=re.IGNORECASE | re.DOTALL)
_THINK_TAG_RE = re.compile(r"</?think\b[^>]*>", flags=re.IGNORECASE)
_PROMPT_ATTR_RE = re.compile(
    r"\bprompt\s*=\s*([\"'])(.*?)\1",
    flags=re.IGNORECASE | re.DOTALL,
)
_NEGATIVE_ATTR_RE = re.compile(
    r"\bnegative\s*=\s*([\"'])(.*?)\1",
    flags=re.IGNORECASE | re.DOTALL,
)


RUNTIME_OVERRIDE = """
你是 ComfyUI Anima 单图分镜导演。用户已经明确要求绘图，因此不要判断是否需要插图。
请从用户提供的剧情或描述中只选择一个最值得定格的视觉核心，优先保证镜头、动作几何、
角色外观连续性与生成稳定性。参考规范用于指导你的导演思路，但本次调用的输出协议覆盖参考规范：

1. 最终只输出一个 `<pic prompt="...">`，不要输出 `<think>`、解释、正文或 Markdown。仅在确有需要时可增加可选的 `negative="..."` 属性，`prompt` 属性始终必需。
2. prompt 必须是单行英文：先写 Anima tags，最后用英文句号分隔一句简短自然语言画面描述；negative 也必须是单行英文 tags。
3. 普通标签使用自然空格和半角逗号；不得改写工具返回的 LoRA 文件名或 trigger words。
4. 默认不添加质量词或安全词；只有用户明确要求时才加入。
5. 只保留单图所需的信息，避免互相矛盾的姿势、镜头和身体方向。
6. 用户文本中的明确人物外观、服装、关系、动作与场景是最高优先级事实，不得被角色 LoRA 的默认服装或示例图覆盖。
7. 若涉及达妮娅或黑娅，严格遵守参考规范中的 LoRA 查询和角色连续性规则。
8. 不要在 prompt 中加入 XML 属性之外的双引号。
9. 每次绘图先确定完整风格底座：用户指定“风格001”或自定义风格名时，先调用 list_anima_lora_presets 精确查询；未指定风格时默认查询“风格001”。不得编造组合。
10. 风格组合是画质、美感、画师、皮肤、背景等组成的完整底座栈。命中后原样保留其全部 LoRA tags 与权重，不得截断、改名或另加近似风格 LoRA；可靠 trigger words 由插件在提交前按最新 Manager 元数据统一补充。
11. 角色 LoRA 永远独立于风格栈。画面包含明确角色时，在查询风格组合之后再调用 list_anima_loras 查询角色，只追加真实返回的精确角色 LoRA tag；不要把角色 trainedWords 列表整包复制到 prompt。
12. 例如“用风格001画达妮娅”必须先查 list_anima_lora_presets(keyword="风格001", category="风格")，再查 list_anima_loras(keyword="denia", detail=true)，最终同时输出风格全栈和角色 LoRA；不得把角色 LoRA 当成风格组合成员。
13. `list_anima_loras` 的角色名、作品名和别名可来自 Civitai 与管理员确认的逻辑归档，但归档只帮助检索，不证明文件仍存在。每次查询都必须以工具本次返回的最新可加载精确名称为准；需要完整说明时用 detail=true，但不要自行复制其中的全部触发词。
14. 用户写“分辨率832x1216”或“分辨率 832×1216”时，这是插件生成参数，不是画面标签；可据纵横比安排构图，但不要把“分辨率”或数字尺寸写进 prompt。
15. 把全部 LoRA 控制标签放在最前方，顺序为风格底座 LoRA、角色 LoRA；插件会写入 `1️⃣Lora堆（默认）`，并按用途补充可靠触发词，其余正面内容会写入 `内容` 节点。
16. 不要从旧对话、归档摘要或角色常识中自行补写 LoRA 文件名与 trigger words。工具无结果、返回多候选或提示记录已失效时，改用可靠的普通英文角色标签，不得猜选。
17. 先把需求拆成不可变身份、可变服装/饰品、动作几何、镜头、场景与光线。用户要求换装时，只保留角色名、脸、发型、发色、瞳色及非服装标志等身份词；不要机械复制角色 LoRA 的全部 trigger words。
18. 明确换装且角色 LoRA 强绑定默认服装时，角色 LoRA 通常降到 0.55 至 0.75，并把目标服装放在正面提示词较前位置，关键服装可用 1.10 至 1.25 的轻权重。没有服装冲突时不要无故降低角色权重。
19. 只有元数据明确指出旧服装词时，才把少量互斥旧服装词写入 negative；不得把角色名、作品名、脸、发色、瞳色、体型等身份词放入 negative。无法可靠区分时宁可省略 negative，不得猜测。
20. 按“明确用户要求 > 当前剧情连续性 > 本次工具元数据 > 一般推断”解决冲突；去掉同义重复，只保留一个镜头、一个主要动作方向和一套服装。
""".strip()


class PromptDirectorError(RuntimeError):
    """LLM 分镜规划失败。"""

    def __init__(self, user_message: str, detail: str = "", *, fatal: bool = False):
        self.user_message = user_message
        self.detail = detail
        self.fatal = fatal
        super().__init__(detail or user_message)


@dataclass(frozen=True)
class PictureResponse:
    """普通 LLM 回复中的绘图控制信息。

    Attributes:
        prompts: 按标签出现顺序提取并规范化的英文绘图提示词。
        text: 移除 ``think`` 块和全部 ``pic`` 标签后保留的回复正文。
    """

    prompts: tuple[str, ...]
    text: str
    negative_prompts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PictureInstruction:
    """One normalized drawing request carried by a ``pic`` tag."""

    prompt: str
    negative_prompt: str = ""


class PromptDirector:
    """封装模型选择、LLM 调用及输出解析。"""

    def __init__(self, reference_path: Path, settings: PluginSettings):
        self._settings = settings
        self._reference = self._load_reference(reference_path)

    @staticmethod
    def _load_reference(path: Path) -> str:
        """读取分镜导演参考提示词。"""
        if not path.is_file():
            raise PromptDirectorError(f"分镜参考文件不存在: {path}")
        if path.stat().st_size > 1024 * 1024:
            raise PromptDirectorError("分镜参考文件超过 1MB")
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptDirectorError(
                "无法读取分镜参考文件", f"读取 {path} 失败: {exc}"
            ) from exc

    def _system_prompt(self) -> str:
        """组合运行时协议、用户附带参考及额外指令。"""
        parts = [RUNTIME_OVERRIDE]
        if self._settings.auto_draw_system_prompt:
            parts.extend(
                [
                    "以下是管理员自定义的绘图人设与偏好；不得覆盖上面的输出、安全和实时 LoRA 约束：",
                    self._settings.auto_draw_system_prompt,
                ]
            )
        else:
            parts.extend(
                [
                "以下内容仅作为分镜与标签写法参考：",
                self._reference,
                ]
            )
        if self._settings.director_extra_instruction:
            parts.extend(
                ["管理员补充要求：", self._settings.director_extra_instruction]
            )
        return "\n\n".join(parts)

    def _lora_tool_call_timeout(self) -> int:
        """Return a per-call budget that covers Manager scan and catalog read."""
        catalog_timeout = max(1, self._settings.lora_catalog_timeout)
        if not self._settings.enable_lora_manager:
            return catalog_timeout
        return max(1, self._settings.lora_manager_scan_timeout) + catalog_timeout

    def _lora_agent_timeout(self, tool_call_timeout: int) -> int:
        """Reserve the configured LLM budget in addition to all tool calls."""
        return self._settings.prompt_llm_timeout + (
            max(1, self._settings.lora_tool_max_steps) * tool_call_timeout
        )

    async def generate(
        self, context: Any, event: Any, scene_text: str, tools: Any = None
    ) -> tuple[str, str]:
        """Backward-compatible positive-prompt API."""
        prompt, provider_id, _ = await self.generate_with_negative(
            context,
            event,
            scene_text,
            tools,
        )
        return prompt, provider_id

    async def generate_with_negative(
        self, context: Any, event: Any, scene_text: str, tools: Any = None
    ) -> tuple[str, str, str]:
        """调用指定 AstrBot 模型生成提示词。

        Args:
            context: AstrBot 插件 Context。
            event: 当前消息事件，用于获取会话默认模型。
            scene_text: 用户提供的剧情或画面描述。

        Returns:
            规范化提示词和实际 provider ID。
        """
        provider_id = await self._resolve_provider_id(context, event)
        user_prompt = (
            "请把下面的剧情或画面需求导演成一张图。只返回规定的 pic 标签。\n\n"
            f"用户内容：\n{scene_text.strip()}"
        )
        kwargs = {
            "prompt": user_prompt,
            "system_prompt": self._system_prompt(),
            "temperature": min(2.0, self._settings.prompt_llm_temperature),
            "max_tokens": self._settings.prompt_llm_max_tokens,
        }

        uses_lora_tools = tools is not None
        tool_call_timeout = 0
        request_timeout = self._settings.prompt_llm_timeout
        try:
            if uses_lora_tools:
                if not hasattr(context, "tool_loop_agent"):
                    raise PromptDirectorError(
                        "当前 AstrBot 不支持 LoRA 查询工具，已停止本次绘图",
                        fatal=True,
                    )
                tool_call_timeout = self._lora_tool_call_timeout()
                request_timeout = self._lora_agent_timeout(tool_call_timeout)
                response = await asyncio.wait_for(
                    context.tool_loop_agent(
                        event=event,
                        chat_provider_id=provider_id,
                        prompt=user_prompt,
                        system_prompt=kwargs["system_prompt"],
                        tools=tools,
                        max_steps=self._settings.lora_tool_max_steps,
                        tool_call_timeout=tool_call_timeout,
                    ),
                    timeout=request_timeout,
                )
            elif hasattr(context, "llm_generate"):
                response = await asyncio.wait_for(
                    context.llm_generate(chat_provider_id=provider_id, **kwargs),
                    timeout=self._settings.prompt_llm_timeout,
                )
            else:
                provider = self._get_legacy_provider(context, event, provider_id)
                response = await asyncio.wait_for(
                    provider.text_chat(contexts=[], **kwargs),
                    timeout=self._settings.prompt_llm_timeout,
                )
        except asyncio.TimeoutError as exc:
            if uses_lora_tools:
                raise PromptDirectorError(
                    "LoRA 查询或 LLM 分镜超时，已停止本次绘图",
                    (
                        f"provider={provider_id}, "
                        f"tool_call_timeout={tool_call_timeout}, "
                        f"agent_timeout={request_timeout}"
                    ),
                    fatal=True,
                ) from exc
            raise PromptDirectorError("LLM 分镜超时") from exc
        except PromptDirectorError:
            raise
        except Exception as exc:
            if uses_lora_tools:
                raise PromptDirectorError(
                    "LoRA 查询工具调用失败，已停止本次绘图",
                    f"provider={provider_id}, error={exc}",
                    fatal=True,
                ) from exc
            raise PromptDirectorError(
                "LLM 分镜调用失败", f"provider={provider_id}, error={exc}"
            ) from exc

        try:
            completion = getattr(response, "completion_text", None)
            if not isinstance(completion, str) or not completion.strip():
                raise PromptDirectorError("LLM 没有返回有效提示词")
            instruction = self.extract_instruction(completion)
        except PromptDirectorError as exc:
            if uses_lora_tools:
                raise PromptDirectorError(
                    "LoRA 工具分镜结果无效，已停止本次绘图",
                    exc.detail or exc.user_message,
                    fatal=True,
                ) from exc
            raise
        return instruction.prompt, provider_id, instruction.negative_prompt

    async def _resolve_provider_id(self, context: Any, event: Any) -> str:
        """优先使用配置模型，否则使用当前会话模型。"""
        if self._settings.prompt_llm_provider_id:
            return self._settings.prompt_llm_provider_id
        umo = getattr(event, "unified_msg_origin", None)
        if hasattr(context, "get_current_chat_provider_id") and umo:
            try:
                provider_id = await context.get_current_chat_provider_id(umo=umo)
            except TypeError:
                provider_id = await context.get_current_chat_provider_id(umo)
            if provider_id:
                return str(provider_id)
        provider = self._get_legacy_provider(context, event, "")
        meta = provider.meta() if hasattr(provider, "meta") else None
        provider_id = getattr(meta, "id", "") if meta else ""
        if not provider_id:
            raise PromptDirectorError("未选择 LLM，当前会话也没有可用模型")
        return str(provider_id)

    @staticmethod
    def _get_legacy_provider(context: Any, event: Any, provider_id: str) -> Any:
        """获取 AstrBot v4.5.7 之前的 Provider 对象。"""
        provider = None
        if provider_id and hasattr(context, "get_provider_by_id"):
            provider = context.get_provider_by_id(provider_id)
        if provider is None and hasattr(context, "get_using_provider"):
            umo = getattr(event, "unified_msg_origin", None)
            try:
                provider = context.get_using_provider(umo)
            except TypeError:
                provider = context.get_using_provider()
        if provider is None or not hasattr(provider, "text_chat"):
            raise PromptDirectorError("找不到可用的 LLM Provider")
        return provider

    @staticmethod
    def extract_prompt(model_output: str) -> str:
        """从 pic 标签、JSON 或纯文本输出中提取单行英文提示词。"""
        return PromptDirector.extract_instruction(model_output).prompt

    @staticmethod
    def extract_instruction(model_output: str) -> PictureInstruction:
        """Extract one positive prompt and an optional negative prompt."""
        text = PromptDirector._remove_think_content(model_output).strip()
        instructions = PromptDirector.extract_pic_instructions(text, max_prompts=1)
        if instructions:
            return instructions[0]
        prompt = ""
        negative_prompt = ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("prompt"), str):
                prompt = parsed["prompt"]
                if isinstance(parsed.get("negative"), str):
                    negative_prompt = parsed["negative"]
                elif isinstance(parsed.get("negative_prompt"), str):
                    negative_prompt = parsed["negative_prompt"]
        except json.JSONDecodeError:
            pass
        if not prompt:
            cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
            cleaned = re.sub(
                r"^\s*(?:prompt|final prompt)\s*:\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            prompt = cleaned.strip().strip("\"'")

        return PictureInstruction(
            prompt=PromptDirector._normalize_prompt(prompt),
            negative_prompt=PromptDirector._normalize_negative_prompt(negative_prompt),
        )

    @staticmethod
    def extract_pic_instructions(
        model_output: str, *, max_prompts: int | None = None
    ) -> list[PictureInstruction]:
        """Extract normalized positive/negative prompt pairs from ``pic`` tags."""
        if max_prompts is not None and max_prompts < 0:
            raise ValueError("max_prompts 不能小于 0")
        if max_prompts == 0:
            return []

        visible_text = PromptDirector._remove_think_content(model_output)
        instructions: list[PictureInstruction] = []
        for match in _PIC_TAG_RE.finditer(visible_text):
            attributes = match.group("attrs")
            prompt_match = _PROMPT_ATTR_RE.search(attributes)
            if prompt_match is None:
                continue
            negative_match = _NEGATIVE_ATTR_RE.search(attributes)
            negative_prompt = (
                PromptDirector._normalize_negative_prompt(negative_match.group(2))
                if negative_match
                else ""
            )
            instructions.append(
                PictureInstruction(
                    prompt=PromptDirector._normalize_prompt(prompt_match.group(2)),
                    negative_prompt=negative_prompt,
                )
            )
            if max_prompts is not None and len(instructions) >= max_prompts:
                break
        return instructions

    @staticmethod
    def extract_pic_prompts(
        model_output: str, *, max_prompts: int | None = None
    ) -> list[str]:
        """提取普通 LLM 回复中的所有有效 ``pic`` 提示词。

        ``think`` 块中的标签会被忽略。调用方可以用 ``max_prompts`` 限制
        本次实际处理的图片数量，而无需改变原始回复的清理结果。

        Args:
            model_output: LLM 返回的完整文本。
            max_prompts: 最多返回多少条提示词；``None`` 表示不限制。

        Returns:
            按 ``pic`` 标签出现顺序排列的规范化提示词列表。

        Raises:
            ValueError: ``max_prompts`` 小于零。
            PromptDirectorError: 被选中的标签含有无效提示词。
        """
        if max_prompts is not None and max_prompts < 0:
            raise ValueError("max_prompts 不能小于 0")
        if max_prompts == 0:
            return []

        return [
            instruction.prompt
            for instruction in PromptDirector.extract_pic_instructions(
                model_output,
                max_prompts=max_prompts,
            )
        ]

    @staticmethod
    def clean_response_text(model_output: str) -> str:
        """移除 LLM 控制标签和隐藏思考，同时保留可发送给用户的正文。"""
        marker = "\x00"
        text = PromptDirector._remove_think_content(model_output, marker)
        text = _PIC_TAG_RE.sub(marker, text)
        text = _ANY_PIC_TAG_RE.sub(marker, text)
        escaped_marker = re.escape(marker)
        text = re.sub(rf"(?m)^[ \t]*(?:{escaped_marker}[ \t]*)+(?:\r?\n|$)", "", text)
        text = re.sub(
            rf"[ \t]*{escaped_marker}(?:[ \t]*{escaped_marker})*[ \t]*",
            " ",
            text,
        )
        text = re.sub(r"[ \t]+(?=\r?$)", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def parse_picture_response(
        model_output: str, *, max_prompts: int | None = None
    ) -> PictureResponse:
        """同时解析绘图控制标签并生成可见回复正文。

        Args:
            model_output: LLM 返回的完整文本。
            max_prompts: 最多返回多少条提示词；正文始终移除全部控制标签。

        Returns:
            包含有序提示词和清理后正文的不可变解析结果。
        """
        instructions = PromptDirector.extract_pic_instructions(
            model_output, max_prompts=max_prompts
        )
        return PictureResponse(
            prompts=tuple(item.prompt for item in instructions),
            text=PromptDirector.clean_response_text(model_output),
            negative_prompts=tuple(item.negative_prompt for item in instructions),
        )

    @staticmethod
    def _remove_think_content(model_output: str, replacement: str = " ") -> str:
        """删除完整、嵌套及未闭合的 ``think`` 区域。"""
        visible_parts: list[str] = []
        cursor = 0
        depth = 0
        for match in _THINK_TAG_RE.finditer(model_output):
            if depth == 0:
                visible_parts.append(model_output[cursor : match.start()])

            is_closing_tag = match.group(0).lstrip().startswith("</")
            if is_closing_tag:
                if depth > 0:
                    depth -= 1
                    if depth == 0:
                        visible_parts.append(replacement)
                else:
                    visible_parts.append(replacement)
            else:
                depth += 1
            cursor = match.end()

        if depth == 0:
            visible_parts.append(model_output[cursor:])
        return "".join(visible_parts)

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """规范化并校验一条英文绘图提示词。"""
        prompt = html.unescape(prompt)
        prompt = re.sub(r"\s*[\r\n]+\s*", ", ", prompt)
        prompt = re.sub(r"(?:,\s*){2,}", ", ", prompt)
        prompt = re.sub(r"\s{2,}", " ", prompt).strip(" ,")
        if not prompt:
            raise PromptDirectorError("LLM 返回的提示词为空")
        if len(prompt) > 6000:
            raise PromptDirectorError("LLM 返回的提示词过长")
        prompt_without_loras = LORA_TAG_PATTERN.sub("", prompt)
        if re.search(r"[\u3400-\u9fff]", prompt_without_loras):
            raise PromptDirectorError("LLM 返回了中文提示词，请更换模型或调整附加要求")
        if "<pic" in prompt.lower() or "</pic" in prompt.lower():
            raise PromptDirectorError("LLM 返回了嵌套或损坏的 pic 标签")
        return prompt

    @staticmethod
    def _normalize_negative_prompt(prompt: str) -> str:
        """Normalize an optional negative prompt without allowing control tags."""
        prompt = html.unescape(str(prompt or ""))
        prompt = re.sub(r"\s*[\r\n]+\s*", ", ", prompt)
        prompt = re.sub(r"(?:,\s*){2,}", ", ", prompt)
        prompt = re.sub(r"\s{2,}", " ", prompt).strip(" ,")
        if not prompt:
            return ""
        if len(prompt) > 2000:
            raise PromptDirectorError("LLM 返回的负面提示词过长")
        if LORA_TAG_PATTERN.search(prompt):
            raise PromptDirectorError("负面提示词不能包含 LoRA 标签")
        if re.search(r"[\u3400-\u9fff]", prompt):
            raise PromptDirectorError("LLM 返回了中文负面提示词")
        if "<pic" in prompt.lower() or "</pic" in prompt.lower():
            raise PromptDirectorError("LLM 返回了损坏的 negative 属性")
        return prompt
