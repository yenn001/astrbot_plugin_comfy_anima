"""
AstrBot Comfy Anima 插件 v1.1.2

功能描述：
- 通过 AstrBot 指令提交 Anima 工作流到 ComfyUI
- 使用可选的 AstrBot LLM 模型把剧情导演为 Anima 提示词
- 支持提示词、负面词、随机种、分辨率、步数和 CFG 参数
- 支持任务状态查询、取消和生成图片回传

作者: Yen
版本: 1.1.2
日期: 2026-07-14
"""

import asyncio
import re
import shlex
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, AsyncGenerator, Mapping, Optional

from astrbot.api import logger
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .constants import (
    MAX_IMAGE_SIDE,
    MIN_IMAGE_SIDE,
    MessageEmoji,
    PLUGIN_NAME,
    PLUGIN_VERSION,
)
from .core.access_control import (
    AccessBypass,
    AccessController,
    AccessPolicy,
    AccessReason,
    FilterLevel,
)
from .core.lora import (
    LoraWorkflowError,
    canonical_lora_name,
    extract_lora_selections,
)
from .core.workflow import (
    ImageWorkflowBuilder,
    WorkflowBuilder,
    WorkflowError,
    parse_generation_options,
)
from .core.workflow_registry import WorkflowRegistry, WorkflowRegistryError
from .models import (
    GeneratedImagePaths,
    GenerationJob,
    GenerationOptions,
    PluginSettings,
)
from .services.comfy_client import ComfyClient, ComfyClientError
from .services.config_profiles import ConfigProfileError, ConfigProfileService
from .services.lora_catalog import LoraCatalogError, LoraCatalogService
from .services.lora_analysis import (
    LoraAnalysisError,
    LoraAnalysisPipeline,
)
from .services.lora_archiver import LoraArchiveError, LoraArchiveService
from .services.lora_downloader import LoraDownloadError, LoraDownloadService
from .services.lora_semantic import (
    SEMANTIC_CATEGORIES,
    SEMANTIC_FIELDS,
    LoraSemanticError,
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_catalog_fingerprint,
    semantic_identity_key,
    semantic_source_fingerprint,
)
from .services.lora_presets import (
    CATEGORY_LABELS,
    LoraPreset,
    LoraPresetError,
    LoraPresetRegistry,
    PRESET_CATEGORY_ARTIST_STYLE,
    PRESET_CATEGORY_CHARACTER,
    PRESET_CATEGORY_MIXED,
    deduplicate_selections,
    normalize_category,
    parse_lora_entries,
)
from .services.lora_prompting import (
    build_lora_trigger_plan,
    merge_runtime_lora_selections,
)
from .services.log_console import PluginLogConsole
from .services.image_input import IncomingImageError, IncomingImageService
from .services.model_manager import (
    ModelManagerError,
    ModelManagerService,
)
from .services.prompt_director import PromptDirector, PromptDirectorError
from .services.reverse_prompt import ReversePromptError, ReversePromptService
from .services.unet_catalog import UnetCatalogError, UnetCatalogService
from .services.task_store import TaskStore, TaskStoreError
from .services.web_ui import WebUiActionError, WebUiError, WebUiService


WEB_UI_EDITABLE_FIELDS = (
    "comfyui_url",
    "default_width",
    "default_height",
    "sampler_steps_override",
    "enable_upscale",
    "rtx_scale",
    "rtx_quality",
    "max_concurrent_jobs",
    "user_cooldown",
    "send_generation_notice",
    "enable_prompt_llm",
    "prompt_llm_provider_id",
    "prompt_llm_temperature",
    "prompt_llm_max_tokens",
    "enable_natural_draw",
    "enable_llm_pic_trigger",
    "enable_reverse_prompt",
    "reverse_prompt_provider_id",
    "reverse_prompt_timeout",
    "reverse_prompt_temperature",
    "reverse_prompt_max_tokens",
    "reverse_prompt_system_prompt",
    "max_input_image_size_mb",
    "max_input_image_pixels",
    "auto_draw_system_prompt",
    "enable_lora_tool",
    "lora_manager_url",
    "enable_lora_download",
    "default_style_preset",
    "max_total_dynamic_loras",
    "max_preset_loras",
    "max_dynamic_loras",
    "lora_alias_rules",
    "strict_lora_validation",
    "default_block_level",
    "group_whitelist",
    "global_lock",
    "whitelist_only",
    "admin_ignore_cooldown",
    "admin_ignore_whitelist",
    "admin_ignore_blocklist",
    "enable_web_ui",
    "web_ui_host",
    "web_ui_port",
    "web_ui_username",
    "web_ui_password",
    "web_ui_session_ttl",
)


@register(
    PLUGIN_NAME,
    "Yen",
    "连接 ComfyUI 并使用内置 Anima 工作流生成图片",
    PLUGIN_VERSION,
)
class ComfyAnimaPlugin(Star):
    """AstrBot ComfyUI Anima 绘图插件。"""

    def __init__(self, context: Context, config: Optional[dict[str, Any]] = None):
        super().__init__(context)
        self.config = config
        self.plugin_dir = Path(__file__).resolve().parent
        self._persistent_data_dir = self._resolve_persistent_data_dir()
        self._task_store_error = ""
        self._task_store: Optional[TaskStore] = None
        try:
            self._task_store = TaskStore(
                self._persistent_data_dir / "task_events.sqlite3"
            )
        except TaskStoreError as exc:
            self._task_store_error = str(exc)
            logger.error(
                f"[{PLUGIN_NAME}] 持久任务事件库初始化失败，将使用临时日志: {exc}"
            )
        self._log_console = PluginLogConsole(
            self.plugin_dir,
            persistent_store=self._task_store,
        )
        self._config_profiles = ConfigProfileService(
            self._persistent_data_dir / "config_profiles.json"
        )
        self._semantic_index_path = self._persistent_data_dir / "lora_semantic_v2.json"
        self._semantic_index_error = ""
        try:
            if self._semantic_index_path.is_file():
                self._semantic_index = LoraSemanticIndex.load(
                    self._semantic_index_path
                )
            else:
                legacy_path = self._persistent_data_dir / "lora_archive.json"
                self._semantic_index = LoraSemanticIndex.load(legacy_path)
                if legacy_path.is_file() and self._semantic_index.entries:
                    self._semantic_index.entries = {
                        key: replace(
                            entry,
                            analysis_status=(
                                "searchable"
                                if entry.has_manual_facts
                                else "review_needed"
                            ),
                        )
                        for key, entry in self._semantic_index.entries.items()
                    }
                self._semantic_index.save(self._semantic_index_path)
        except LoraSemanticError as exc:
            self._semantic_index_error = str(exc)
            self._semantic_index = LoraSemanticIndex.empty()
            logger.error(
                f"[{PLUGIN_NAME}] LoRA v2 语义索引读取失败，已安全停用覆盖: {exc}"
            )
        self._lora_analysis: Optional[LoraAnalysisPipeline] = None
        if self._task_store is not None:
            analysis_prompt = ""
            analysis_prompt_path = (
                self.plugin_dir / "prompts" / "lora_semantic_analysis.txt"
            )
            try:
                if analysis_prompt_path.is_file():
                    analysis_prompt = analysis_prompt_path.read_text(
                        encoding="utf-8"
                    ).strip()
            except OSError as exc:
                logger.warning(
                    f"[{PLUGIN_NAME}] LoRA v2 建档提示词读取失败，使用内置版本: {exc}"
                )
            self._lora_analysis = LoraAnalysisPipeline(
                self._semantic_index,
                self._semantic_index_path,
                self._task_store,
                **({"system_prompt": analysis_prompt} if analysis_prompt else {}),
            )
        self._lora_archive_error = ""
        try:
            self._lora_archiver = LoraArchiveService(
                self._persistent_data_dir / "lora_archive.json",
                self.plugin_dir / "prompts" / "lora_archive_reference.txt",
            )
        except LoraArchiveError as exc:
            self._lora_archive_error = exc.user_message
            logger.warning(
                f"[{PLUGIN_NAME}] LoRA 归档提示词读取失败，使用内置规则: {exc}"
            )
            self._lora_archiver = LoraArchiveService(
                self._persistent_data_dir / "lora_archive.json"
            )
        self.settings = PluginSettings.from_mapping(config)
        self._log_console_attached = self._log_console.attach(logger)
        self._active_jobs: dict[str, GenerationJob] = {}
        self._jobs_lock = asyncio.Lock()
        self._generation_slots = asyncio.Semaphore(self.settings.max_concurrent_jobs)
        self._last_request_at: dict[str, float] = {}
        self._cleanup_tasks: set[asyncio.Task[Any]] = set()
        self._self_reload_tasks: set[asyncio.Task[Any]] = set()
        self._background_task_runs: dict[str, asyncio.Task[Any]] = {}
        self._web_ui_start_task: Optional[asyncio.Task[Any]] = None
        self._web_ui: Optional[WebUiService] = None
        self._web_ui_error = ""
        self._internal_llm_events: set[int] = set()
        self._temp_dir = Path(tempfile.gettempdir()) / PLUGIN_NAME
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._image_input = IncomingImageService(self.settings, self._temp_dir)
        self._reverse_prompt = (
            ReversePromptService(self.settings)
            if self.settings.enable_reverse_prompt
            else None
        )
        self._upscale_workflow_builder: Optional[ImageWorkflowBuilder] = None
        self._upscale_initialization_error = ""
        self._initialization_error: Optional[str] = None
        self._director_error: Optional[str] = None
        self._director: Optional[PromptDirector] = None
        self._global_locked = self.settings.global_lock
        self._group_block_levels = dict(self.settings.group_block_levels)
        self._auto_draw_system_prompt = self.settings.auto_draw_system_prompt
        self._unet_catalog: Optional[UnetCatalogService] = None
        self._unet_catalog_error = ""
        if self.settings.enable_unet_switch:
            try:
                self._unet_catalog = UnetCatalogService(self.settings)
            except UnetCatalogError as exc:
                self._unet_catalog_error = exc.user_message
                logger.warning(
                    f"[{PLUGIN_NAME}] UNET 模型清单初始化失败: {exc.user_message}"
                )
        self._lora_catalog = (
            LoraCatalogService(self.settings)
            if self.settings.enable_lora_tool
            else None
        )
        if self._lora_catalog is not None:
            self._lora_catalog.set_record_overlay(
                self._semantic_index.apply_overlays
            )
        self._lora_downloader: Optional[LoraDownloadService] = None
        self._lora_download_error = ""
        if self.settings.enable_lora_manager:
            try:
                self._lora_downloader = LoraDownloadService(
                    self.settings,
                    self._lora_catalog,
                )
            except LoraDownloadError as exc:
                self._lora_download_error = exc.user_message
                logger.warning(
                    f"[{PLUGIN_NAME}] LoRA Manager 服务初始化失败: {exc.user_message}"
                )
        elif self.settings.enable_lora_download:
            self._lora_download_error = "LoRA Manager 未启用"
        self._lora_presets = LoraPresetRegistry(
            self.settings.lora_presets,
            max_loras=self.settings.max_preset_loras,
        )
        self._model_manager: Optional[ModelManagerService] = None
        self._model_manager_error = ""
        if (
            self.settings.enable_lora_manager
            and self._lora_catalog is not None
            and self._unet_catalog is not None
        ):
            try:
                self._model_manager = ModelManagerService(
                    self.settings,
                    self._lora_catalog,
                    self._unet_catalog,
                    preset_reference_resolver=self._lora_preset_references,
                    preset_removal_callback=self._remove_lora_from_presets,
                    current_unet_resolver=self._current_unet_model,
                )
            except ModelManagerError as exc:
                self._model_manager_error = exc.user_message
                logger.warning(
                    f"[{PLUGIN_NAME}] model deletion service unavailable: "
                    f"{exc.user_message}"
                )
        self._access_controller = AccessController(
            AccessPolicy(
                global_locked=self._global_locked,
                whitelist_enabled=self.settings.whitelist_only,
                whitelist_groups=set(self.settings.group_whitelist),
                default_filter_level=FilterLevel(self.settings.default_block_level),
                group_filter_levels={
                    group_id: FilterLevel(level)
                    for group_id, level in self._group_block_levels.items()
                },
            )
        )
        workflow_dir = Path(self.settings.workflow_dir).expanduser()
        if not workflow_dir.is_absolute():
            workflow_dir = self.plugin_dir / workflow_dir
        self._workflow_registry = WorkflowRegistry(workflow_dir, self.settings)
        self._active_workflow_name = Path(self.settings.workflow_file).name

        try:
            workflow_path = self.settings.resolve_workflow_path(self.plugin_dir)
            self._workflow_builder = WorkflowBuilder(workflow_path, self.settings)
            self._client = ComfyClient(self.settings)
            try:
                self._upscale_workflow_builder = ImageWorkflowBuilder(
                    self.settings.resolve_upscale_workflow_path(self.plugin_dir),
                    self.settings,
                )
            except (OSError, ValueError, WorkflowError) as upscale_exc:
                self._upscale_initialization_error = str(upscale_exc)
                logger.warning(
                    f"[{PLUGIN_NAME}] standalone RTX workflow unavailable: {upscale_exc}"
                )
            logger.info(
                f"[{PLUGIN_NAME}] 初始化完成，ComfyUI: {self.settings.comfyui_url}"
            )
        except (OSError, ValueError, WorkflowError) as exc:
            self._workflow_builder = None
            self._client = None
            self._initialization_error = str(exc)
            logger.error(f"[{PLUGIN_NAME}] 初始化失败: {exc}", exc_info=True)

        try:
            reference_path = self.settings.resolve_director_reference_path(
                self.plugin_dir
            )
            self._director = PromptDirector(reference_path, self.settings)
            if not self._auto_draw_system_prompt:
                self._auto_draw_system_prompt = reference_path.read_text(
                    encoding="utf-8"
                ).strip()
        except (OSError, ValueError, PromptDirectorError) as exc:
            self._director_error = str(exc)
            logger.error(
                f"[{PLUGIN_NAME}] LLM 分镜模块初始化失败: {exc}", exc_info=True
            )

        if self.settings.enable_web_ui:
            self._web_ui = WebUiService(self.settings, self.plugin_dir, self)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._web_ui_error = "AstrBot event loop is not ready"
                logger.warning(
                    f"[{PLUGIN_NAME}] Web UI was not started: {self._web_ui_error}"
                )
            else:
                self._web_ui_start_task = loop.create_task(self._start_web_ui())
        if self._log_console_attached:
            logger.info(
                f"[{PLUGIN_NAME}] 专属 WebUI 日志控制台已启用，"
                f"内存上限 {self._log_console.capacity} 条"
            )
        else:
            logger.warning(
                f"[{PLUGIN_NAME}] 当前 AstrBot logger 不支持日志处理器，"
                "专属 WebUI 控制台将显示为未连接"
            )

    @filter.command_group("anima")
    def anima(self) -> None:
        """Anima 绘图指令组。"""

    async def _start_web_ui(self) -> None:
        """Start the optional authenticated management UI."""
        if self._web_ui is None:
            return
        try:
            await self._web_ui.start()
        except asyncio.CancelledError:
            raise
        except (OSError, WebUiError) as exc:
            self._web_ui_error = str(exc)
            logger.error(
                f"[{PLUGIN_NAME}] Web UI startup failed: {exc}",
                exc_info=True,
            )

    @filter.llm_tool(name="list_anima_loras")
    async def list_anima_loras(
        self,
        event: AstrMessageEvent,
        keyword: str = "",
        limit: int = 30,
        refresh: bool = False,
        detail: bool = False,
    ) -> str:
        """查询或刷新局域网中实际可用的 Anima LoRA 与管理器元数据。

        Args:
            keyword(string): 可选搜索词，如角色名、画风、服装或作者名。
            limit(number): 最多返回多少项，建议 10 到 50。
            refresh(boolean): 兼容旧提示词；当前版本无论取值都强制刷新 Manager。
            detail(boolean): 需要完整说明、推荐权重或详细触发词时设为 true。
        """
        if not self._lora_catalog:
            return "LoRA Manager is unavailable. Stop this LoRA drawing request."
        try:
            await self._refresh_lora_manager_before("LLM 查询 LoRA")
            return await self._lora_catalog.format_for_llm(
                query=keyword,
                limit=max(1, min(int(limit), self.settings.lora_max_results)),
                force_refresh=False,
                detail=bool(detail),
            )
        except (LoraCatalogError, ValueError) as exc:
            logger.warning(f"[{PLUGIN_NAME}] LoRA 工具查询失败: {exc}")
            message = getattr(exc, "user_message", str(exc))
            return (
                f"LoRA Manager refresh failed: {message}. "
                "Do not select any LoRA; stop the drawing request."
            )

    @filter.llm_tool(name="list_anima_lora_presets")
    async def list_anima_lora_presets(
        self,
        event: AstrMessageEvent,
        keyword: str = "",
        category: str = "",
        detail: bool = False,
    ) -> str:
        """查询管理员保存的角色、画师/风格或混合 LoRA 组合。

        Args:
            keyword(string): 组合名称、用途、触发词或 LoRA 文件名搜索词。
            category(string): 可选分类：角色、风格、画师或混合。
            detail(boolean): 是否返回组合说明。
        """
        try:
            await self._refresh_lora_manager_before("LLM 查询 LoRA 组合")
            presets = self._lora_presets.list_presets(
                keyword=keyword,
                category=category,
            )
            valid_presets: list[LoraPreset] = []
            invalid_names: list[str] = []
            assert self._lora_catalog is not None
            for preset in presets:
                try:
                    await self._lora_catalog.resolve_selections(
                        preset.selections,
                        strict=True,
                    )
                except LoraCatalogError:
                    invalid_names.append(preset.name)
                else:
                    valid_presets.append(preset)
            result = self._lora_presets.format_selected_for_llm(
                valid_presets,
                detail=bool(detail),
            )
            if invalid_names:
                result += (
                    "\nUnavailable presets omitted after mandatory fresh validation: "
                    + ", ".join(invalid_names)
                )
            return result
        except (LoraPresetError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            return (
                f"LoRA preset query unavailable: {message}. "
                "Stop this LoRA drawing request."
            )

    @filter.on_llm_request(priority=20)
    async def inject_auto_draw_prompt(self, event: AstrMessageEvent, req: Any) -> None:
        """向普通对话 LLM 注入可编辑的 pic 标签协议。"""
        if not self.settings.enable_llm_pic_trigger:
            return
        if id(event) in self._internal_llm_events:
            return
        if self._access_error(event, "", check_sensitive=False):
            return
        system_prompt = self._auto_draw_system_prompt.strip()
        if not system_prompt:
            return
        current = str(getattr(req, "system_prompt", "") or "")
        req.system_prompt = f"{current}\n\n{system_prompt}".strip()

    @filter.on_decorating_result(priority=20)
    async def render_llm_picture_tags(self, event: AstrMessageEvent) -> None:
        """移除 think/pic 控制标签，并把 pic 标签替换为生成图片。"""
        if not self.settings.enable_llm_pic_trigger or not self._director:
            return
        result = event.get_result()
        if not result or not getattr(result, "chain", None):
            return
        plain_components = [
            component for component in result.chain if isinstance(component, Comp.Plain)
        ]
        if not plain_components:
            return
        raw_text = "\n".join(str(component.text) for component in plain_components)
        if "<pic" not in raw_text.lower() and "<think" not in raw_text.lower():
            return

        try:
            parsed = self._director.parse_picture_response(
                raw_text,
                max_prompts=self.settings.max_auto_images_per_reply,
            )
        except PromptDirectorError as exc:
            parsed_text = self._director.clean_response_text(raw_text)
            preserved = [
                component
                for component in result.chain
                if not isinstance(component, Comp.Plain)
            ]
            result.chain = (
                ([Comp.Plain(parsed_text)] if parsed_text else [])
                + preserved
                + [Comp.Plain(f"{MessageEmoji.ERROR} 绘图标签无效: {exc.user_message}")]
            )
            return

        preserved = [
            component
            for component in result.chain
            if not isinstance(component, Comp.Plain)
        ]
        new_chain: list[Any] = []
        if parsed.text:
            new_chain.append(Comp.Plain(parsed.text))
        new_chain.extend(preserved)

        request_text = str(event.message_str or "")
        try:
            width, height = self._extract_resolution_request(request_text)
        except ValueError as exc:
            new_chain.append(Comp.Plain(f"{MessageEmoji.WARNING} {exc}"))
            result.chain = new_chain
            return
        style_preset = self._find_requested_style_preset(request_text)

        for index, prompt in enumerate(parsed.prompts):
            negative_prompt = (
                parsed.negative_prompts[index]
                if index < len(parsed.negative_prompts)
                else ""
            )
            access_error = self._access_error(event, prompt)
            if access_error:
                new_chain.append(Comp.Plain(f"{MessageEmoji.WARNING} {access_error}"))
                continue
            if not self._client or not self._workflow_builder:
                new_chain.append(
                    Comp.Plain(f"{MessageEmoji.ERROR} ComfyUI 插件尚未就绪")
                )
                continue
            try:
                image_paths, seed, _, _, _ = await self._run_job(
                    event,
                    GenerationOptions(
                        prompt=prompt,
                        use_prompt_llm=False,
                        width=width,
                        height=height,
                        lora_preset=style_preset,
                        negative_prompt=negative_prompt,
                    ),
                )
            except ValueError as exc:
                new_chain.append(Comp.Plain(f"{MessageEmoji.WARNING} {exc}"))
                continue
            except (ComfyClientError, WorkflowError) as exc:
                logger.error(f"[{PLUGIN_NAME}] pic 标签出图失败: {exc}", exc_info=True)
                message = getattr(exc, "user_message", str(exc))
                new_chain.append(
                    Comp.Plain(f"{MessageEmoji.ERROR} 自动绘图失败: {message}")
                )
                continue
            new_chain.append(Comp.Plain(self._generation_summary(image_paths, seed)))
            new_chain.extend(Comp.Image.fromFileSystem(path) for path in image_paths)
            self._schedule_cleanup(image_paths)
        result.chain = new_chain

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=15)
    async def natural_language_draw(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """识别“帮我画一个……”并使用所选 LLM 自动生成提示词。"""
        message = (event.message_str or "").strip()
        if (
            not self.settings.enable_natural_draw
            or message.startswith(("/", "／"))
            or not self._looks_like_draw_request(message)
        ):
            return
        try:
            access_error = self._access_error(event, message)
            if access_error:
                yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
                return
            if not self._director:
                yield event.plain_result(
                    f"{MessageEmoji.ERROR} LLM 分镜模块不可用: {self._director_error}"
                )
                return
            try:
                width, height = self._extract_resolution_request(message)
            except ValueError as exc:
                yield event.plain_result(f"{MessageEmoji.ERROR} 分辨率错误: {exc}")
                return
            style_preset = self._find_requested_style_preset(message)
            yield event.plain_result(f"{MessageEmoji.DRAW} 正在分析画面并整理提示词……")
            try:
                (
                    final_prompt,
                    provider_id,
                    directed_negative,
                ) = await self._generate_directed_prompt(event, message)
                final_access_error = self._access_error(event, final_prompt)
                if final_access_error:
                    yield event.plain_result(
                        f"{MessageEmoji.WARNING} {final_access_error}"
                    )
                    return
                image_paths, seed, _, _, _ = await self._run_job(
                    event,
                    GenerationOptions(
                        prompt=final_prompt,
                        use_prompt_llm=False,
                        width=width,
                        height=height,
                        lora_preset=style_preset,
                        negative_prompt=directed_negative,
                    ),
                )
            except PromptDirectorError as exc:
                logger.error(f"[{PLUGIN_NAME}] 自然语言分镜失败: {exc}", exc_info=True)
                yield event.plain_result(
                    f"{MessageEmoji.ERROR} LLM 分镜失败: {exc.user_message}"
                )
                return
            except ValueError as exc:
                yield event.plain_result(f"{MessageEmoji.WARNING} {exc}")
                return
            except (ComfyClientError, WorkflowError) as exc:
                logger.error(f"[{PLUGIN_NAME}] 自然语言出图失败: {exc}", exc_info=True)
                message_text = getattr(exc, "user_message", str(exc))
                yield event.plain_result(
                    f"{MessageEmoji.ERROR} 生成失败: {message_text}"
                )
                return
            if self.settings.show_llm_prompt:
                yield event.plain_result(
                    f"{MessageEmoji.INFO} 分镜模型: {provider_id}\n"
                    f"最终提示词: {final_prompt}"
                    + (
                        f"\n换装负面词: {directed_negative}"
                        if directed_negative
                        else ""
                    )
                )
            yield self._make_image_result(event, image_paths, seed, forward=False)
            self._schedule_cleanup(image_paths)
        finally:
            # AstrBot v4.26 会在异步生成器每次 yield 后检查 stopped 状态。
            # 必须等当前处理器完全结束后再阻止默认 LLM，否则只会发出进度提示。
            event.stop_event()

    @filter.command("画图")
    async def cmd_draw_forward(
        self, event: AstrMessageEvent, prompt: str = ""
    ) -> AsyncGenerator[Any, None]:
        """直接使用英文 Tag，并以 QQ 合并转发发送图片。"""
        command_text = self._extract_command_text(
            event.message_str, prompt, command="画图"
        )
        async for response in self._handle_direct_draw(
            event, command_text, forward=True
        ):
            yield response

    @filter.command("画图no")
    async def cmd_draw_direct(
        self, event: AstrMessageEvent, prompt: str = ""
    ) -> AsyncGenerator[Any, None]:
        """直接使用英文 Tag，并以普通 QQ 图片消息发送。"""
        command_text = self._extract_command_text(
            event.message_str, prompt, command="画图no"
        )
        async for response in self._handle_direct_draw(
            event, command_text, forward=False
        ):
            yield response

    @filter.command("反推")
    async def cmd_reverse_prompt(
        self, event: AstrMessageEvent, focus: str = ""
    ) -> AsyncGenerator[Any, None]:
        """Reverse one direct or replied image with an AstrBot multimodal Provider."""
        supplement = self._extract_command_text(
            event.message_str, focus, command="反推"
        )
        if not self.settings.enable_reverse_prompt or self._reverse_prompt is None:
            yield event.plain_result(f"{MessageEmoji.ERROR} 在线反推功能未启用")
            return
        access_error = self._access_error(event, supplement, check_sensitive=bool(supplement))
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        if len(supplement) > 500:
            yield event.plain_result(f"{MessageEmoji.ERROR} 反推补充要求不能超过 500 字符")
            return

        async def operation(job: GenerationJob) -> tuple[Any, str, float]:
            image_path: Optional[Path] = None
            started_at = time.monotonic()
            try:
                job.state = "reading_image"
                image_path = await self._image_input.collect_one(event)
                self._record_image_task_phase(
                    job,
                    "input",
                    "输入图片校验完成，准备调用多模态 Provider。",
                    "reverse_input_ready",
                    details={"bytes": image_path.stat().st_size},
                )
                job.state = "reverse_prompting"
                self._record_image_task_phase(
                    job,
                    "provider",
                    "正在调用所选多模态 Provider 提取结构化画面事实。",
                    "reverse_provider_started",
                )

                def reverse_progress(
                    message: str,
                    event_code: str,
                    details: Mapping[str, Any],
                ) -> None:
                    self._record_image_task_phase(
                        job,
                        "provider",
                        message,
                        event_code,
                        details=dict(details),
                        level=(
                            "WARNING"
                            if event_code == "reverse_response_invalid"
                            else "INFO"
                        ),
                    )

                async with self._generation_slots:
                    result, provider_id = await self._reverse_prompt.reverse(
                        self.context,
                        event,
                        image_path,
                        supplement,
                        reverse_progress,
                    )
                job.state = "completed"
                self._record_image_task_phase(
                    job,
                    "provider",
                    "多模态反推完成，结构化结果已通过校验。",
                    "reverse_provider_completed",
                    details={"provider_id": provider_id},
                )
                return result, provider_id, max(0.0, time.monotonic() - started_at)
            finally:
                if image_path is not None:
                    image_path.unlink(missing_ok=True)

        yield event.plain_result(f"{MessageEmoji.INFO} 正在读取图片并调用多模态模型反推……")
        try:
            result, provider_id, elapsed = await self._run_auxiliary_job(
                event,
                "reverse prompt",
                operation,
            )
        except ReversePromptError as exc:
            message = exc.user_message
            logger.error(
                f"[{PLUGIN_NAME}] reverse prompt failed: "
                f"code={exc.code}, details={exc.details}"
            )
            yield event.plain_result(f"{MessageEmoji.ERROR} 反推失败: {message}")
            return
        except IncomingImageError as exc:
            message = getattr(exc, "user_message", str(exc))
            logger.error(f"[{PLUGIN_NAME}] reverse prompt failed: {exc}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 反推失败: {message}")
            return
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.WARNING} {exc}")
            return
        yield event.plain_result(
            f"{result.render(provider_id)}\n\n反推耗时：{elapsed:.2f} 秒"
        )

    @filter.command("反推画图")
    async def cmd_reverse_draw(
        self, event: AstrMessageEvent, requirement: str = ""
    ) -> AsyncGenerator[Any, None]:
        """Reverse an image, direct the prompt, then generate with Anima."""
        supplement = self._extract_command_text(
            event.message_str, requirement, command="反推画图"
        )
        if not self.settings.enable_reverse_prompt or self._reverse_prompt is None:
            yield event.plain_result(f"{MessageEmoji.ERROR} 在线反推功能未启用")
            return
        if not self._client or not self._workflow_builder or not self._director:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 反推画图组件未就绪: "
                f"{self._initialization_error or self._director_error or '未知错误'}"
            )
            return
        access_error = self._access_error(event, supplement, check_sensitive=bool(supplement))
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        try:
            width, height = self._extract_resolution_request(supplement)
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} 分辨率错误: {exc}")
            return
        style_preset = self._find_requested_style_preset(supplement)

        async def operation(job: GenerationJob) -> tuple[Any, str, Any, str, str]:
            image_path: Optional[Path] = None
            try:
                job.state = "reading_image"
                image_path = await self._image_input.collect_one(event)
                self._record_image_task_phase(
                    job,
                    "input",
                    "输入图片校验完成，准备执行反推画图链路。",
                    "reverse_draw_input_ready",
                    details={"bytes": image_path.stat().st_size},
                )
                job.state = "reverse_prompting"
                self._record_image_task_phase(
                    job,
                    "provider",
                    "正在提取图片中的可观察画面事实。",
                    "reverse_draw_provider_started",
                )

                def reverse_progress(
                    message: str,
                    event_code: str,
                    details: Mapping[str, Any],
                ) -> None:
                    self._record_image_task_phase(
                        job,
                        "provider",
                        message,
                        event_code,
                        details=dict(details),
                        level=(
                            "WARNING"
                            if event_code == "reverse_response_invalid"
                            else "INFO"
                        ),
                    )

                async with self._generation_slots:
                    reverse_result, reverse_provider = await self._reverse_prompt.reverse(
                        self.context,
                        event,
                        image_path,
                        supplement,
                        reverse_progress,
                    )
                job.state = "directing"
                self._record_image_task_phase(
                    job,
                    "director",
                    "反推结果已就绪，正在由绘图导演整理 Anima 提示词。",
                    "reverse_draw_director_started",
                    details={"reverse_provider_id": reverse_provider},
                )
                final_prompt, director_provider, directed_negative = (
                    await self._generate_directed_prompt(
                        event,
                        reverse_result.drawing_request(supplement),
                    )
                )
                final_access_error = self._access_error(event, final_prompt)
                if final_access_error:
                    raise ValueError(final_access_error)
                negative_prompt = ", ".join(
                    part
                    for part in (
                        reverse_result.negative_tags.strip(" ,"),
                        directed_negative.strip(" ,"),
                    )
                    if part
                )
                generated = await self._execute_job(
                    job,
                    GenerationOptions(
                        prompt=final_prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        lora_preset=style_preset,
                        use_prompt_llm=False,
                    ),
                    event,
                )
                self._record_image_task_phase(
                    job,
                    "comfyui",
                    "Anima 与可选 RTX 生成链路完成，图片已下载。",
                    "reverse_draw_output_ready",
                    details={"director_provider_id": director_provider},
                )
                return (
                    reverse_result,
                    reverse_provider,
                    generated,
                    final_prompt,
                    director_provider,
                )
            finally:
                if image_path is not None:
                    image_path.unlink(missing_ok=True)

        yield event.plain_result(
            f"{MessageEmoji.DRAW} 正在反推图片、整理 Anima 提示词并生成……"
        )
        try:
            (
                _reverse_result,
                reverse_provider,
                generated,
                final_prompt,
                director_provider,
            ) = await self._run_auxiliary_job(event, "reverse draw", operation)
        except ReversePromptError as exc:
            message = exc.user_message
            logger.error(
                f"[{PLUGIN_NAME}] reverse draw failed: "
                f"code={exc.code}, details={exc.details}"
            )
            yield event.plain_result(f"{MessageEmoji.ERROR} 反推画图失败: {message}")
            return
        except (IncomingImageError, PromptDirectorError) as exc:
            message = getattr(exc, "user_message", str(exc))
            logger.error(f"[{PLUGIN_NAME}] reverse draw failed: {exc}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 反推画图失败: {message}")
            return
        except (ComfyClientError, WorkflowError) as exc:
            message = getattr(exc, "user_message", str(exc))
            logger.error(f"[{PLUGIN_NAME}] reverse draw generation failed: {exc}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 生成失败: {message}")
            return
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.WARNING} {exc}")
            return
        image_paths, seed, _, _, director_warning = generated
        if director_warning:
            yield event.plain_result(f"{MessageEmoji.WARNING} {director_warning}")
        if self.settings.show_llm_prompt:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 反推模型: {reverse_provider}\n"
                f"分镜模型: {director_provider}\n最终提示词: {final_prompt}"
            )
        yield self._make_image_result(event, image_paths, seed, forward=False)
        self._schedule_cleanup(image_paths)

    @filter.command("放大")
    async def cmd_rtx_upscale(
        self, event: AstrMessageEvent, scale: str = ""
    ) -> AsyncGenerator[Any, None]:
        """Upscale one direct or replied image with the standalone RTX workflow."""
        if not self._client or not self._upscale_workflow_builder:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} RTX 放大工作流未就绪: "
                f"{self._upscale_initialization_error or self._initialization_error or '未知错误'}"
            )
            return
        access_error = self._access_error(event, "", check_sensitive=False)
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        scale_text = self._extract_command_text(event.message_str, scale, command="放大")
        try:
            scale_value = (
                self.settings.rtx_scale
                if not scale_text
                else float(scale_text.rstrip("xX倍 "))
            )
        except ValueError:
            yield event.plain_result(f"{MessageEmoji.ERROR} 放大倍率必须是数字，例如 /放大 2")
            return
        if not 1.0 <= scale_value <= 4.0:
            yield event.plain_result(f"{MessageEmoji.ERROR} RTX 放大倍率必须在 1 到 4 之间")
            return

        async def operation(job: GenerationJob) -> GeneratedImagePaths:
            return await self._execute_upscale_job(job, event, scale_value)

        yield event.plain_result(
            f"{MessageEmoji.INFO} 正在上传图片并执行 RTX {scale_value:g}× 放大……"
        )
        try:
            image_paths = await self._run_auxiliary_job(
                event,
                "RTX upscale",
                operation,
            )
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.WARNING} {exc}")
            return
        except (IncomingImageError, ComfyClientError, WorkflowError) as exc:
            message = getattr(exc, "user_message", str(exc))
            logger.error(f"[{PLUGIN_NAME}] RTX upscale failed: {exc}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} RTX 放大失败: {message}")
            return
        components = [
            Comp.Plain(self._upscale_summary(image_paths, scale_value)),
            *(Comp.Image.fromFileSystem(path) for path in image_paths),
        ]
        yield event.chain_result(components)
        self._schedule_cleanup(image_paths)

    @anima.command("draw")
    async def cmd_draw(
        self, event: AstrMessageEvent, prompt: str = ""
    ) -> AsyncGenerator[Any, None]:
        """使用 Anima 工作流生成图片。

        Args:
            event: AstrBot 消息事件。
            prompt: 绘图提示词及可选参数。
        """
        command_text = self._extract_command_text(
            event.message_str, prompt, command="draw"
        )
        try:
            options = parse_generation_options(command_text)
            detected_width, detected_height = self._extract_resolution_request(
                options.prompt
            )
            options = replace(
                options,
                width=(options.width if options.width is not None else detected_width),
                height=(
                    options.height if options.height is not None else detected_height
                ),
                lora_preset=(
                    options.lora_preset
                    or self._find_requested_style_preset(options.prompt)
                ),
            )
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} 参数错误: {exc}")
            return

        if len(options.prompt) > self.settings.max_prompt_length:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 提示词不能超过 "
                f"{self.settings.max_prompt_length} 个字符"
            )
            return
        access_error = self._access_error(event, options.prompt)
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        if self._initialization_error or not self._client or not self._workflow_builder:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 插件尚未就绪: {self._initialization_error}"
            )
            return

        user_id = str(event.get_sender_id() or "unknown")
        job_or_error = await self._create_job(user_id, options, event)
        if isinstance(job_or_error, str):
            yield event.plain_result(f"{MessageEmoji.WARNING} {job_or_error}")
            return
        job = job_or_error

        if self.settings.send_generation_notice:
            upscale = (
                self.settings.enable_upscale
                if options.enable_upscale is None
                else options.enable_upscale
            )
            mode_text = "含二次放大" if upscale else "仅首轮出图"
            use_llm = (
                self.settings.enable_prompt_llm
                if options.use_prompt_llm is None
                else options.use_prompt_llm
            )
            director_text = "LLM 分镜、" if use_llm else "原始提示词、"
            yield event.plain_result(
                f"{MessageEmoji.DRAW} 已接收任务（{director_text}{mode_text}），请稍候……"
            )

        try:
            (
                image_paths,
                seed,
                effective_prompt,
                provider_id,
                director_warning,
            ) = await job.task
        except asyncio.CancelledError:
            yield event.plain_result(f"{MessageEmoji.WARNING} 生成任务已取消")
            return
        except ComfyClientError as exc:
            logger.error(
                f"[{PLUGIN_NAME}] 生成失败，用户={user_id}: {exc}", exc_info=True
            )
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 生成失败: {exc.user_message}"
            )
            return
        except WorkflowError as exc:
            logger.error(f"[{PLUGIN_NAME}] 工作流构造失败: {exc}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 工作流错误: {exc}")
            return
        except PromptDirectorError as exc:
            logger.error(
                f"[{PLUGIN_NAME}] LLM 分镜失败，用户={user_id}: {exc}",
                exc_info=True,
            )
            yield event.plain_result(
                f"{MessageEmoji.ERROR} LLM 分镜失败: {exc.user_message}"
            )
            return
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] 未处理的生成异常: {exc}", exc_info=True)
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 生成失败，请联系管理员查看日志"
            )
            return
        finally:
            async with self._jobs_lock:
                if self._active_jobs.get(user_id) is job:
                    self._active_jobs.pop(user_id, None)

        if director_warning:
            yield event.plain_result(
                f"{MessageEmoji.WARNING} {director_warning}，已改用原始提示词"
            )
        yield event.plain_result(self._generation_summary(image_paths, seed))
        if self.settings.show_llm_prompt and provider_id:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 分镜模型: {provider_id}\n"
                f"最终提示词: {effective_prompt}"
            )
        for image_path in image_paths:
            yield event.image_result(str(image_path))
        self._schedule_cleanup(image_paths)

    @anima.command("prompt")
    async def cmd_prompt(
        self, event: AstrMessageEvent, scene: str = ""
    ) -> AsyncGenerator[Any, None]:
        """仅调用所选模型生成提示词，不提交 ComfyUI。"""
        scene_text = self._extract_command_text(
            event.message_str, scene, command="prompt"
        )
        if not scene_text:
            yield event.plain_result(f"{MessageEmoji.ERROR} 请输入剧情或画面描述")
            return
        if len(scene_text) > self.settings.max_prompt_length:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 内容不能超过 "
                f"{self.settings.max_prompt_length} 个字符"
            )
            return
        access_error = self._access_error(event, scene_text)
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        if not self._director:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} LLM 分镜模块不可用: {self._director_error}"
            )
            return
        try:
            (
                final_prompt,
                provider_id,
                directed_negative,
            ) = await self._generate_directed_prompt(event, scene_text)
        except PromptDirectorError as exc:
            logger.error(f"[{PLUGIN_NAME}] 提示词预览失败: {exc}", exc_info=True)
            yield event.plain_result(
                f"{MessageEmoji.ERROR} LLM 分镜失败: {exc.user_message}"
            )
            return
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 分镜模型: {provider_id}\n{final_prompt}"
            + (
                f"\nNegative: {directed_negative}"
                if directed_negative
                else ""
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("comfy_ls")
    async def cmd_comfy_ls(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """列出运行时可切换的 ComfyUI 工作流。"""
        try:
            entries = self._workflow_registry.list_workflows()
        except WorkflowRegistryError as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} {exc}")
            return
        if not entries:
            yield event.plain_result(f"{MessageEmoji.INFO} 工作流目录中没有 JSON 文件")
            return
        lines = ["📚 可用 ComfyUI 工作流:"]
        for entry in entries:
            marker = " ✅" if entry.filename == self._active_workflow_name else ""
            lines.append(f"{entry.index}. {entry.filename}{marker}")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("comfy_use")
    async def cmd_comfy_use(
        self,
        event: AstrMessageEvent,
        index: int,
        input_id: str = "",
        output_id: str = "",
    ) -> AsyncGenerator[Any, None]:
        """按序号热切换工作流及可选输入、输出节点。"""
        try:
            selection = self._workflow_registry.select(
                index,
                input_node_id=input_id or None,
                output_node_id=output_id or None,
            )
        except (WorkflowRegistryError, WorkflowError) as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} 切换失败: {exc}")
            return
        self._workflow_builder = selection.builder
        self._active_workflow_name = selection.entry.filename
        self._workflow_registry = WorkflowRegistry(
            self._workflow_registry.workflow_dir, selection.settings
        )
        try:
            relative = selection.entry.path.relative_to(self.plugin_dir)
            workflow_value = relative.as_posix()
        except ValueError:
            workflow_value = str(selection.entry.path)
        self._persist_config("workflow_file", workflow_value)
        if input_id:
            self._persist_config("prompt_node_id", input_id)
        if output_id:
            self._persist_config("output_node_ids", [output_id])
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已切换到 {selection.entry.filename}\n"
            f"输入节点: {selection.settings.prompt_node_id}\n"
            f"输出节点: {', '.join(selection.settings.output_node_ids)}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("comfy_lock")
    async def cmd_comfy_lock(
        self, event: AstrMessageEvent, state: str = "status"
    ) -> AsyncGenerator[Any, None]:
        """动态查看或切换全局绘图锁定。"""
        if not self.settings.enable_lock_command:
            yield event.plain_result(f"{MessageEmoji.WARNING} 锁定命令已在配置中关闭")
            return
        normalized = state.strip().lower()
        if normalized not in {"on", "off", "status"}:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 用法: /comfy_lock on|off|status"
            )
            return
        if normalized != "status":
            self._global_locked = normalized == "on"
            self._access_controller.set_global_lock(self._global_locked)
            self._persist_config("global_lock", self._global_locked)
        status_text = "已锁定（仅管理员可用）" if self._global_locked else "未锁定"
        yield event.plain_result(f"{MessageEmoji.INFO} ComfyUI 全局状态: {status_text}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("模型列表")
    async def cmd_unet_model_list(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """实时读取 ComfyUI UNETLoader 当前全部模型。"""
        if not self.settings.enable_unet_switch:
            yield event.plain_result(
                f"{MessageEmoji.WARNING} UNET 模型切换功能已在配置中关闭"
            )
            return
        if not self._unet_catalog:
            reason = self._unet_catalog_error or "UNET 模型清单服务不可用"
            yield event.plain_result(f"{MessageEmoji.ERROR} {reason}")
            return
        yield event.plain_result(
            f"{MessageEmoji.INFO} 正在读取局域网 ComfyUI 最新 UNET 模型清单……"
        )
        try:
            entries = await self._unet_catalog.list_models()
        except UnetCatalogError as exc:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} UNET 模型清单读取失败: {exc.user_message}"
            )
            return
        yield event.plain_result(
            f"{MessageEmoji.INFO} "
            + self._unet_catalog.format_listing(
                entries,
                self._current_unet_model(),
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("模型切换")
    async def cmd_unet_model_switch(
        self, event: AstrMessageEvent, identifier: str = ""
    ) -> AsyncGenerator[Any, None]:
        """刷新完整 UNET 清单后按序号或名称切换当前档案的 UNET。"""
        value = self._extract_command_text(
            event.message_str,
            identifier,
            command="模型切换",
        )
        if not value:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 用法: /模型切换 <序号|完整UNET文件名>"
            )
            return
        if not self.settings.enable_unet_switch:
            yield event.plain_result(
                f"{MessageEmoji.WARNING} UNET 模型切换功能已在配置中关闭"
            )
            return
        if not self._unet_catalog:
            reason = self._unet_catalog_error or "UNET 模型清单服务不可用"
            yield event.plain_result(f"{MessageEmoji.ERROR} {reason}")
            return

        yield event.plain_result(
            f"{MessageEmoji.INFO} 切换前正在读取局域网最新 UNET 模型数据……"
        )
        try:
            entries = await self._unet_catalog.list_models()
            selected = self._unet_catalog.resolve(value, entries)
        except UnetCatalogError as exc:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} UNET 模型切换失败: {exc.user_message}"
            )
            return

        if self.config is None:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} UNET 模型切换失败: 插件配置不可写"
            )
            return
        config_mapping = dict(self.config)
        config_mapping["unet_model_name"] = selected.name
        new_settings = PluginSettings.from_mapping(config_mapping)
        try:
            workflow_path = new_settings.resolve_workflow_path(self.plugin_dir)
            new_builder = WorkflowBuilder(workflow_path, new_settings)
            # 新工作流由档案声明节点映射；没有档案绑定的旧工作流才回退配置。
            profile_binding = new_builder.profile.unet
            if profile_binding is not None:
                unet_node_id = profile_binding.node_id
                unet_input_name = profile_binding.input_name
            else:
                unet_node_id = new_settings.unet_loader_node_id
                unet_input_name = new_settings.unet_model_input_name
            # 立即验证目标节点确实能接受 UNET 输入。
            node_value = new_builder.get_template_input(
                unet_node_id,
                unet_input_name,
            )
            if node_value is None:
                raise WorkflowError(
                    f"工作流缺少 UNET 节点 {unet_node_id} "
                    f"或输入 {unet_input_name}"
                )
        except (OSError, ValueError, WorkflowError) as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} UNET 模型切换失败: {exc}")
            return

        if not self._persist_config("unet_model_name", selected.name):
            yield event.plain_result(
                f"{MessageEmoji.ERROR} UNET 模型切换失败: 配置文件未能持久化"
            )
            return

        self.settings = new_settings
        self._workflow_builder = new_builder
        workflow_dir = Path(new_settings.workflow_dir).expanduser()
        if not workflow_dir.is_absolute():
            workflow_dir = self.plugin_dir / workflow_dir
        self._workflow_registry = WorkflowRegistry(workflow_dir, new_settings)
        self._active_workflow_name = Path(new_settings.workflow_file).name
        reload_task = self._schedule_self_reload(reason="切换 UNET 模型")
        reload_text = (
            "插件将在约 2 秒后自动重载。"
            if reload_task
            else "自动重载不可用，但当前运行实例已立即应用。"
        )
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已切换 Anima UNET 模型\n"
            f"{selected.index}. {selected.name}\n"
            f"本次切换前已刷新全部 {len(entries)} 个模型；{reload_text}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("违禁级别")
    async def cmd_filter_level(
        self, event: AstrMessageEvent, level: str = ""
    ) -> AsyncGenerator[Any, None]:
        """设置当前 QQ 群的违禁词过滤等级。"""
        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            yield event.plain_result(f"{MessageEmoji.ERROR} 此命令只能在群聊中使用")
            return
        normalized = level.strip().lower()
        if normalized not in {"none", "lite", "full"}:
            current = self._access_controller.get_filter_level(group_id).value
            yield event.plain_result(
                f"{MessageEmoji.INFO} 当前群级别: {current}\n"
                "用法: /违禁级别 none|lite|full"
            )
            return
        selected = self._access_controller.set_group_filter_level(group_id, normalized)
        self._group_block_levels[group_id] = selected.value
        serialized_levels = [
            f"{group}={filter_level}"
            for group, filter_level in sorted(self._group_block_levels.items())
        ]
        self._persist_config("group_block_levels", serialized_levels)
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 当前群违禁词级别已设为 {selected.value}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("lora组合列表")
    async def cmd_lora_preset_list(
        self, event: AstrMessageEvent, category: str = ""
    ) -> AsyncGenerator[Any, None]:
        """按分类列出已保存的 LoRA 组合。"""
        try:
            await self._refresh_lora_manager_before("管理员查看 LoRA 组合")
            text = self._lora_presets.format_for_llm(
                category=category,
                detail=True,
                enabled_only=False,
            )
        except (LoraPresetError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            yield event.plain_result(f"{MessageEmoji.ERROR} {message}")
            return
        yield event.plain_result(f"{MessageEmoji.INFO} {text}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("lora组合保存")
    async def cmd_lora_preset_save(
        self, event: AstrMessageEvent, args: str = ""
    ) -> AsyncGenerator[Any, None]:
        """创建或覆盖 LoRA 组合。"""
        raw = self._extract_command_text(
            event.message_str,
            args,
            command="lora组合保存",
        )
        try:
            tokens = shlex.split(raw, posix=True)
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} 参数引号不完整: {exc}")
            return
        if len(tokens) < 3:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 用法: /lora组合保存 <角色|风格|混合|auto> "
                '<名称|数字|auto> <lora:名称:权重>... [--trigger "触发词"] '
                '[--description "说明"]'
            )
            return

        category_text, name = tokens[0], tokens[1]
        lora_parts: list[str] = []
        trigger_words = ""
        description = ""
        index = 2
        while index < len(tokens):
            token = tokens[index]
            if token in {"--trigger", "--triggers"}:
                if index + 1 >= len(tokens):
                    yield event.plain_result(f"{MessageEmoji.ERROR} {token} 缺少参数")
                    return
                index += 1
                trigger_words = tokens[index]
            elif token in {"--description", "--desc"}:
                if index + 1 >= len(tokens):
                    yield event.plain_result(f"{MessageEmoji.ERROR} {token} 缺少参数")
                    return
                index += 1
                description = tokens[index]
            elif token.startswith("--"):
                yield event.plain_result(f"{MessageEmoji.ERROR} 未知选项: {token}")
                return
            else:
                lora_parts.append(token)
            index += 1

        previous_presets = self._lora_presets.to_config()
        try:
            await self._refresh_lora_manager_before("管理员保存 LoRA 组合")
            category = normalize_category(category_text, allow_auto=True)
            joined_lora_text = " ".join(lora_parts)
            selections = parse_lora_entries(
                (
                    joined_lora_text
                    if "<lora:" in joined_lora_text.casefold()
                    else lora_parts
                ),
                max_loras=self.settings.max_preset_loras,
            )
            if self._lora_catalog:
                selections = await self._lora_catalog.resolve_selections(
                    selections,
                    strict=self.settings.strict_lora_validation,
                )
                classifications = await self._lora_catalog.classify_selections(
                    selections
                )
                if (
                    category == PRESET_CATEGORY_ARTIST_STYLE
                    and PRESET_CATEGORY_CHARACTER in classifications.values()
                ):
                    character_names = [
                        name
                        for name, item_category in classifications.items()
                        if item_category == PRESET_CATEGORY_CHARACTER
                    ]
                    raise LoraPresetError(
                        "风格串不能包含角色 LoRA，请把角色独立追加: "
                        + ", ".join(character_names)
                    )
            if category == "auto":
                category = (
                    await self._lora_catalog.infer_preset_category(selections)
                    if self._lora_catalog
                    else "mixed"
                )
            if len(selections) > self.settings.max_total_dynamic_loras:
                raise LoraPresetError(
                    "组合本身的 LoRA 数量不能超过单次任务动态 LoRA 总上限 "
                    f"{self.settings.max_total_dynamic_loras}"
                )
            preset = self._lora_presets.save(
                name=name,
                category=category,
                selections=selections,
                trigger_words=trigger_words,
                description=description,
            )
        except (LoraPresetError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            yield event.plain_result(f"{MessageEmoji.ERROR} 保存失败: {message}")
            return

        if not self._persist_config("lora_presets", self._lora_presets.to_config()):
            self._lora_presets.load(previous_presets)
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 保存失败: 配置文件未能持久化，已回滚本次修改"
            )
            return
        reload_note = ""
        if (
            preset.category == PRESET_CATEGORY_ARTIST_STYLE
            and self.settings.auto_reload_after_style_save
        ):
            reload_task = self._schedule_self_reload(reason="保存风格")
            if reload_task:
                reload_note = "\n♻️ 风格配置已持久化，插件将在约 2 秒后自动重载。"
            else:
                reload_note = (
                    "\n⚠️ 风格已保存，但当前 AstrBot 未提供插件重载接口，"
                    "请手动重载一次。"
                )
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已保存 {CATEGORY_LABELS[preset.category]}组合 "
            f"“{preset.name}”\n{preset.lora_tags}{reload_note}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("保存风格")
    async def cmd_save_style_preset(
        self, event: AstrMessageEvent, args: str = ""
    ) -> AsyncGenerator[Any, None]:
        """快捷覆盖完整风格栈：`/保存风格 风格001 <LoRA串>`。"""
        raw = self._extract_command_text(
            event.message_str,
            args,
            command="保存风格",
        )
        if not raw:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 用法: /保存风格 <名称|数字> <LoRA串> "
                '[--trigger "触发词"] [--description "说明"]'
            )
            return
        async for response in self.cmd_lora_preset_save(event, f"风格 {raw}"):
            yield response

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("lora组合删除")
    async def cmd_lora_preset_delete(
        self, event: AstrMessageEvent, identifier: str = ""
    ) -> AsyncGenerator[Any, None]:
        """按序号或名称删除 LoRA 组合。"""
        value = self._extract_command_text(
            event.message_str,
            identifier,
            command="lora组合删除",
        )
        previous_presets = self._lora_presets.to_config()
        try:
            await self._refresh_lora_manager_before("管理员删除 LoRA 组合")
            preset = self._lora_presets.delete(value)
        except (LoraPresetError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            yield event.plain_result(f"{MessageEmoji.ERROR} {message}")
            return
        if not self._persist_config("lora_presets", self._lora_presets.to_config()):
            self._lora_presets.load(previous_presets)
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 删除失败: 配置文件未能持久化，已回滚本次修改"
            )
            return
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已删除 LoRA 组合“{preset.name}”"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("lora刷新")
    async def cmd_lora_refresh(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """让 LoRA Manager 扫描磁盘并刷新插件清单。"""
        if not self._lora_catalog:
            yield event.plain_result(f"{MessageEmoji.ERROR} LoRA 查询工具未启用")
            return
        yield event.plain_result(f"{MessageEmoji.INFO} 正在刷新 LoRA Manager 索引……")
        try:
            summary = await self._lora_catalog.refresh_summary()
        except LoraCatalogError as exc:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} LoRA 刷新失败: {exc.user_message}"
            )
            return
        yield event.plain_result(f"{MessageEmoji.SUCCESS} {summary}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("lora下载")
    async def cmd_lora_download(
        self, event: AstrMessageEvent, url: str = ""
    ) -> AsyncGenerator[Any, None]:
        """从 Civitai 模型页下载 LoRA，随后补抓元数据并刷新清单。"""
        raw_url = self._extract_command_text(
            event.message_str,
            url,
            command="lora下载",
        )
        if not raw_url:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 用法: /lora下载 <Civitai模型页URL>\n"
                "仅支持 civitai.com / civitai.red 的 HTTPS 模型页。"
            )
            return
        if not self.settings.enable_lora_download:
            yield event.plain_result(
                f"{MessageEmoji.WARNING} LoRA 下载命令已在配置中关闭"
            )
            return
        if not self._lora_downloader:
            reason = self._lora_download_error or "LoRA 下载服务不可用"
            yield event.plain_result(f"{MessageEmoji.ERROR} {reason}")
            return

        try:
            yield event.plain_result(
                f"{MessageEmoji.INFO} 正在强制刷新 LoRA Manager 最新索引……"
            )
            await self._refresh_lora_manager_before("下载 LoRA 前")
            yield event.plain_result(
                f"{MessageEmoji.INFO} 最新索引已就绪，正在通过 LoRA Manager 下载，"
                "文件完成后会再次获取 Civitai 元数据，请耐心等待……"
            )
            result = await self._lora_downloader.download_from_url(raw_url)
        except (LoraDownloadError, LoraCatalogError) as exc:
            detail_value = str(getattr(exc, "detail", ""))
            detail = f"：{detail_value[:300]}" if detail_value else ""
            message = getattr(exc, "user_message", str(exc))
            yield event.plain_result(
                f"{MessageEmoji.ERROR} LoRA 下载失败: {message}{detail}"
            )
            return

        if result.downloaded:
            headline = f"{MessageEmoji.SUCCESS} LoRA 下载完成"
        else:
            headline = f"{MessageEmoji.INFO} 该版本已存在，已跳过重复下载"
        lines = [
            headline,
            f"模型 ID: {result.model_id}",
            f"版本: {result.version_name}（{result.version_id}）",
        ]
        if result.auto_selected_version:
            lines.append("版本选择: URL 未指定 modelVersionId，已自动选择最新版本")
        lines.append(f"文件: {result.file_name or 'Manager 暂未返回文件名'}")
        lines.append(f"位置: {result.file_path or 'Manager 清单中暂未定位'}")

        if result.metadata_success:
            lines.append(
                f"{MessageEmoji.SUCCESS} Civitai 元数据: {result.metadata_message}"
            )
        else:
            lines.append(
                f"{MessageEmoji.WARNING} Civitai 元数据获取失败: "
                f"{result.metadata_message}"
            )
        if result.catalog_success:
            lines.append(
                f"{MessageEmoji.SUCCESS} AstrBot 清单: {result.catalog_message}"
            )
        else:
            lines.append(
                f"{MessageEmoji.WARNING} AstrBot 清单刷新失败: "
                f"{result.catalog_message or '未知错误'}"
            )
        if not result.metadata_success or not result.catalog_success:
            lines.append(
                f"{MessageEmoji.WARNING} 部分成功：LoRA 文件状态不受后处理失败影响。"
            )
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("comfy帮助")
    async def cmd_comfy_help(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """显示面向 QQ/NapCat 的绘图帮助。"""
        yield event.plain_result(
            """📖 ComfyUI 绘图帮助
━━━━━━━━━━━━
自然语言: 帮我画一个……
/画图 <英文 Tag> - 合并转发图片
/画图no <英文 Tag> - 直接发送图片
/反推 [关注点] - 发送或引用图片，返回结构化 Anima 提示词
/反推画图 [补充要求] - 反推后直接调用 Anima 生图
/放大 [倍率] - 发送或引用图片，执行独立 RTX 放大
/画图与 /画图no 均可追加 --preset <序号|名称>

管理员:
/comfy_ls - 列出工作流
/comfy_use <序号> [input_id] [output_id] - 热切换工作流
/comfy_lock on|off|status - 全局锁定
/模型列表 - 实时读取全部 UNET 模型
/模型切换 <序号|完整名称> - 刷新清单后切换 Anima UNET
/lora刷新 - 重新扫描 LoRA Manager 并更新 LLM 清单
/lora下载 <Civitai模型页URL> - 下载后补抓元数据并刷新清单
/lora组合列表 [角色|风格|混合] - 查看组合
/lora组合保存 <分类> <名称> <LoRA串> - 创建或覆盖组合
/保存风格 <名称|数字> <LoRA串> - 保存风格并自动重载插件
/lora组合删除 <序号|名称> - 删除组合
/违禁级别 none|lite|full - 设置当前群策略
/comfy帮助 - 查看帮助

普通 LLM 回复中的 pic prompt 控制标签会自动触发绘图，
think 控制块内容会被自动忽略。"""
        )

    @anima.command("status")
    async def cmd_status(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看个人任务和 ComfyUI 队列状态。"""
        user_id = str(event.get_sender_id() or "unknown")
        async with self._jobs_lock:
            job = self._active_jobs.get(user_id)
            local_total = len(self._active_jobs)

        personal = "无进行中任务"
        if job:
            elapsed = max(0, int(time.monotonic() - job.created_at))
            personal = f"状态={job.state}，已等待 {elapsed} 秒"

        queue_text = "ComfyUI 队列不可用"
        if self._client:
            try:
                queue = await self._client.queue()
                running = len(queue.get("queue_running", []))
                pending = len(queue.get("queue_pending", []))
                queue_text = f"ComfyUI 运行中 {running}，排队 {pending}"
            except ComfyClientError as exc:
                queue_text = f"ComfyUI 状态读取失败: {exc.user_message}"

        yield event.plain_result(
            f"{MessageEmoji.INFO} 个人: {personal}\n"
            f"插件任务数: {local_total}\n{queue_text}"
        )

    @anima.command("cancel")
    async def cmd_cancel(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """取消当前用户提交的生成任务。"""
        user_id = str(event.get_sender_id() or "unknown")
        async with self._jobs_lock:
            job = self._active_jobs.get(user_id)
        if not job or not job.task or job.task.done():
            yield event.plain_result(f"{MessageEmoji.INFO} 你没有可取消的任务")
            return

        if job.prompt_id and self._client:
            await self._client.cancel(job.prompt_id)
        job.task.cancel()
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已发送取消请求。"
            "若任务正在 ComfyUI 执行，是否立即中断取决于插件配置。"
        )

    @anima.command("ping")
    async def cmd_ping(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """测试 ComfyUI 连接。"""
        if not self._client:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 插件尚未就绪: {self._initialization_error}"
            )
            return
        started = time.monotonic()
        try:
            status = await self._client.health()
        except ComfyClientError as exc:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} ComfyUI 连接失败: {exc.user_message}"
            )
            return
        elapsed_ms = int((time.monotonic() - started) * 1000)
        devices = status.get("devices", [])
        device_name = "未知设备"
        if isinstance(devices, list) and devices and isinstance(devices[0], dict):
            device_name = str(devices[0].get("name", device_name))
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} ComfyUI 连接正常｜{elapsed_ms}ms｜{device_name}"
        )

    @anima.command("help")
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """显示插件帮助。"""
        help_text = f"""📖 Comfy Anima 插件 v{PLUGIN_VERSION}
━━━━━━━━━━━━
/anima draw <提示词> - 生成图片
/anima prompt <剧情> - 仅预览 LLM 分镜提示词
/anima status - 查看任务状态
/anima cancel - 取消自己的任务
/anima ping - 测试 ComfyUI 连接
/anima help - 查看帮助

QQ快捷指令:
/画图 <英文 Tag> - 合并转发
/画图no <英文 Tag> - 直接图片
/反推 [关注点] - 在线图片反推
/反推画图 [补充要求] - 反推并生成
/放大 [倍率] - RTX 图片放大
/comfy帮助 - 完整帮助

可选参数:
--negative "负面提示词"
--seed 123456
--size 832x1216
--steps 30
--cfg 5
--upscale / --no-upscale
--llm / --raw
--preset "风格001或自定义名称"

示例:
/anima draw 她在雨夜回头看向镜头 --seed 123
/anima draw 用风格001画达妮娅，分辨率832x1216
/anima draw 1girl, white hair, blue eyes --raw --no-upscale --preset 风格001
"""
        yield event.plain_result(help_text)

    async def _handle_direct_draw(
        self, event: AstrMessageEvent, prompt: str, *, forward: bool
    ) -> AsyncGenerator[Any, None]:
        """处理 `/画图` 与 `/画图no` 的共享直接出图流程。"""
        try:
            prompt, preset_name = self._extract_preset_option(prompt)
            prompt, width, height = self._extract_size_option(prompt)
            if width is None or height is None:
                detected_width, detected_height = self._extract_resolution_request(
                    prompt
                )
                width = width if width is not None else detected_width
                height = height if height is not None else detected_height
            preset_name = preset_name or self._find_requested_style_preset(prompt)
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.ERROR} 参数错误: {exc}")
            return
        prompt = prompt.strip()
        if not prompt:
            command = "/画图" if forward else "/画图no"
            yield event.plain_result(f"{MessageEmoji.ERROR} 用法: {command} <英文 Tag>")
            return
        if len(prompt) > self.settings.max_prompt_length:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 提示词不能超过 "
                f"{self.settings.max_prompt_length} 个字符"
            )
            return
        access_error = self._access_error(event, prompt)
        if access_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {access_error}")
            return
        if not self._client or not self._workflow_builder:
            yield event.plain_result(
                f"{MessageEmoji.ERROR} 插件尚未就绪: {self._initialization_error}"
            )
            return
        if self.settings.send_generation_notice:
            yield event.plain_result(f"{MessageEmoji.DRAW} 已提交 ComfyUI，请稍候……")
        try:
            image_paths, seed, _, _, _ = await self._run_job(
                event,
                GenerationOptions(
                    prompt=prompt,
                    use_prompt_llm=False,
                    lora_preset=preset_name,
                    width=width,
                    height=height,
                ),
            )
        except ValueError as exc:
            yield event.plain_result(f"{MessageEmoji.WARNING} {exc}")
            return
        except (ComfyClientError, WorkflowError) as exc:
            logger.error(f"[{PLUGIN_NAME}] 直接出图失败: {exc}", exc_info=True)
            message = getattr(exc, "user_message", str(exc))
            yield event.plain_result(f"{MessageEmoji.ERROR} 生成失败: {message}")
            return
        yield self._make_image_result(event, image_paths, seed, forward=forward)
        self._schedule_cleanup(image_paths)

    async def _generate_directed_prompt(
        self, event: AstrMessageEvent, scene_text: str
    ) -> tuple[str, str, str]:
        """调用分镜模型，并防止内部请求再次注入自动绘图提示词。"""
        if not self._director:
            raise PromptDirectorError("LLM 分镜模块不可用", self._director_error or "")
        event_key = id(event)
        self._internal_llm_events.add(event_key)
        try:
            return await self._director.generate_with_negative(
                self.context,
                event,
                scene_text,
                tools=self._get_lora_tool_set(),
            )
        finally:
            self._internal_llm_events.discard(event_key)

    def _get_lora_tool_set(self) -> Any:
        """构造只读的 LoRA 清单与保存组合查询工具集。"""
        if not self.settings.enable_lora_tool:
            return None
        try:
            from astrbot.core.agent.tool import ToolSet

            manager = self.context.get_llm_tool_manager()
            tool_names = ["list_anima_lora_presets"]
            if self._lora_catalog:
                tool_names.append("list_anima_loras")
            tools = [
                tool
                for name in tool_names
                if (tool := manager.get_func(name)) is not None
            ]
            return ToolSet(tools) if tools else None
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] 无法构造 LoRA 工具集: {exc}")
            return None

    def _make_image_result(
        self,
        event: AstrMessageEvent,
        image_paths: list[Path],
        seed: int,
        *,
        forward: bool,
    ) -> Any:
        """按命令模式构造普通图片或 NapCat 合并转发消息。"""
        images = [Comp.Image.fromFileSystem(path) for path in image_paths]
        summary = self._generation_summary(image_paths, seed)
        if not forward:
            return event.chain_result([Comp.Plain(summary), *images])
        self_id = str(getattr(event.message_obj, "self_id", "0") or "0")
        node = Comp.Node(
            uin=self_id,
            name=self.settings.forward_sender_name,
            content=[Comp.Plain(summary)] + images,
        )
        return event.chain_result([node])

    @staticmethod
    def _generation_summary(image_paths: list[Path], seed: int) -> str:
        elapsed = max(
            0.0,
            float(getattr(image_paths, "elapsed_seconds", 0.0) or 0.0),
        )
        gpu_name = str(
            getattr(image_paths, "gpu_name", "未知 GPU") or "未知 GPU"
        )
        return (
            f"{MessageEmoji.SUCCESS} 生成完成｜Seed: {seed}｜图片: {len(image_paths)} 张\n"
            f"生成耗时: {elapsed:.2f} 秒｜GPU: {gpu_name}"
        )

    @staticmethod
    def _upscale_summary(image_paths: list[Path], scale: float) -> str:
        elapsed = max(
            0.0,
            float(getattr(image_paths, "elapsed_seconds", 0.0) or 0.0),
        )
        gpu_name = str(
            getattr(image_paths, "gpu_name", "未知 GPU") or "未知 GPU"
        )
        return (
            f"{MessageEmoji.SUCCESS} RTX {scale:g}× 放大完成｜图片: {len(image_paths)} 张\n"
            f"处理耗时: {elapsed:.2f} 秒｜GPU: {gpu_name}"
        )

    def _access_error(
        self,
        event: AstrMessageEvent,
        text: str,
        *,
        check_sensitive: bool = True,
    ) -> Optional[str]:
        """执行锁定、白名单及群级违禁词检查并返回友好错误。"""
        is_admin = bool(event.is_admin())
        bypass = AccessBypass(
            global_lock=is_admin,
            whitelist=is_admin and self.settings.admin_ignore_whitelist,
            sensitive_words=(
                not check_sensitive
                or (is_admin and self.settings.admin_ignore_blocklist)
            ),
        )
        decision = self._access_controller.evaluate(
            text,
            group_id=event.get_group_id() or None,
            bypass=bypass,
        )
        if decision.allowed:
            return None
        if decision.reason is AccessReason.GLOBAL_LOCKED:
            return "绘图功能已全局锁定，仅管理员可用"
        if decision.reason is AccessReason.GROUP_NOT_WHITELISTED:
            return "当前群不在绘图白名单中"
        if decision.reason is AccessReason.SENSITIVE_CONTENT:
            return f"请求触发 {decision.filter_level.value} 级违禁词策略"
        return "当前请求不允许绘图"

    @staticmethod
    def _looks_like_draw_request(message: str) -> bool:
        """保守识别明确的中文自然语言绘图请求。"""
        patterns = (
            r"(?:帮|给|替|为)我?.{0,4}(?:画|绘制|生成)(?:一|1)?(?:张|个|幅)",
            r"(?:帮|给|替|为)我?.{0,4}(?:画|绘制|生成).{0,12}(?:图|图片|插画|立绘)",
            r"(?:画|绘制|生成)(?:一|1)?(?:张|个|幅).{0,200}",
            r"(?:来|整)(?:一|1)?(?:张|个|幅).{0,200}(?:图|图片|插画)",
        )
        return any(
            re.search(pattern, message, flags=re.IGNORECASE) for pattern in patterns
        )

    def _resolve_persistent_data_dir(self) -> Path:
        """Return AstrBot's persistent plugin-data directory with a safe fallback."""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

            root = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        except Exception:
            root = self.plugin_dir / "data"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _persist_config(self, key: str, value: Any) -> bool:
        """更新 AstrBot 插件配置并在支持时立即保存。"""
        if self.config is None:
            return False
        had_previous = key in self.config
        previous = self.config.get(key)
        try:
            self.config[key] = value
            save_config = getattr(self.config, "save_config", None)
            if callable(save_config):
                save_config()
            return True
        except Exception as exc:
            try:
                if had_previous:
                    self.config[key] = previous
                else:
                    self.config.pop(key, None)
            except Exception:
                pass
            logger.warning(f"[{PLUGIN_NAME}] 保存配置 {key} 失败: {exc}")
            return False

    def _persist_config_updates(self, updates: dict[str, Any]) -> bool:
        """Persist multiple configuration fields as one logical change."""
        if self.config is None or not updates:
            return False
        previous = {key: (key in self.config, self.config.get(key)) for key in updates}
        try:
            for key, value in updates.items():
                self.config[key] = value
            save_config = getattr(self.config, "save_config", None)
            if callable(save_config):
                save_config()
            return True
        except Exception as exc:
            for key, (existed, value) in previous.items():
                try:
                    if existed:
                        self.config[key] = value
                    else:
                        self.config.pop(key, None)
                except Exception:
                    pass
            logger.warning(
                f"[{PLUGIN_NAME}] Failed to save Web UI configuration: {exc}"
            )
            return False

    async def web_ui_bootstrap(self) -> dict[str, Any]:
        """Return a secret-free snapshot for the management dashboard."""
        settings = self.settings
        workflow_runtime: dict[str, Any] = {
            "profile_id": "",
            "display_name": "工作流未就绪",
            "workflow_file": settings.workflow_file,
            "sampler_steps_override": settings.sampler_steps_override,
            "samplers": [],
        }
        if self._workflow_builder is not None:
            profile = self._workflow_builder.profile
            workflow_runtime.update(
                {
                    "profile_id": profile.profile_id,
                    "display_name": profile.display_name,
                    "samplers": self._workflow_builder.template_sampler_settings(),
                }
            )
        return {
            "version": PLUGIN_VERSION,
            "active_jobs": len(self._active_jobs),
            "web_ui_error": self._web_ui_error,
            "lora_archive_error": getattr(self, "_lora_archive_error", ""),
            "workflow_runtime": workflow_runtime,
            "settings": {
                "comfyui_url": settings.comfyui_url,
                "workflow_file": settings.workflow_file,
                "default_width": settings.default_width,
                "default_height": settings.default_height,
                "sampler_steps_override": settings.sampler_steps_override,
                "enable_upscale": settings.enable_upscale,
                "rtx_scale": settings.rtx_scale,
                "rtx_quality": settings.rtx_quality,
                "max_concurrent_jobs": settings.max_concurrent_jobs,
                "user_cooldown": settings.user_cooldown,
                "send_generation_notice": settings.send_generation_notice,
                "enable_prompt_llm": settings.enable_prompt_llm,
                "prompt_llm_provider_id": settings.prompt_llm_provider_id,
                "prompt_llm_temperature": settings.prompt_llm_temperature,
                "prompt_llm_max_tokens": settings.prompt_llm_max_tokens,
                "enable_natural_draw": settings.enable_natural_draw,
                "enable_llm_pic_trigger": settings.enable_llm_pic_trigger,
                "enable_reverse_prompt": settings.enable_reverse_prompt,
                "reverse_prompt_provider_id": settings.reverse_prompt_provider_id,
                "reverse_prompt_timeout": settings.reverse_prompt_timeout,
                "reverse_prompt_temperature": settings.reverse_prompt_temperature,
                "reverse_prompt_max_tokens": settings.reverse_prompt_max_tokens,
                "reverse_prompt_system_prompt": settings.reverse_prompt_system_prompt,
                "max_input_image_size_mb": settings.max_input_image_size_mb,
                "max_input_image_pixels": settings.max_input_image_pixels,
                "auto_draw_system_prompt": self._auto_draw_system_prompt,
                "enable_lora_tool": settings.enable_lora_tool,
                "lora_manager_url": settings.lora_manager_url,
                "enable_lora_download": settings.enable_lora_download,
                "default_style_preset": settings.default_style_preset,
                "max_total_dynamic_loras": settings.max_total_dynamic_loras,
                "max_preset_loras": settings.max_preset_loras,
                "max_dynamic_loras": settings.max_dynamic_loras,
                "lora_alias_rules": list(settings.lora_alias_rules),
                "strict_lora_validation": settings.strict_lora_validation,
                "default_block_level": settings.default_block_level,
                "group_whitelist": list(settings.group_whitelist),
                "global_lock": self._global_locked,
                "whitelist_only": settings.whitelist_only,
                "admin_ignore_cooldown": settings.admin_ignore_cooldown,
                "admin_ignore_whitelist": settings.admin_ignore_whitelist,
                "admin_ignore_blocklist": settings.admin_ignore_blocklist,
                "unet_model_name": settings.unet_model_name,
                "enable_web_ui": settings.enable_web_ui,
                "web_ui_host": settings.web_ui_host,
                "web_ui_port": settings.web_ui_port,
                "web_ui_username": settings.web_ui_username,
                "web_ui_session_ttl": settings.web_ui_session_ttl,
                "web_ui_password_set": bool(settings.web_ui_password),
            },
        }

    async def web_ui_save_settings(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate, persist and reload configuration changed in the Web UI."""
        if self.config is None:
            raise WebUiActionError("当前 AstrBot 配置对象不支持持久化")
        candidate = dict(self.config)
        supplied: set[str] = set()
        for key in WEB_UI_EDITABLE_FIELDS:
            if key not in payload:
                continue
            if key == "web_ui_password" and not str(payload[key]):
                continue
            candidate[key] = payload[key]
            supplied.add(key)
        if not supplied:
            raise WebUiActionError("没有收到可保存的设置")

        normalized = PluginSettings.from_mapping(candidate)
        if normalized.max_preset_loras > normalized.max_total_dynamic_loras:
            raise WebUiActionError("单个组合 LoRA 上限不能超过单次 LoRA 总上限")
        if normalized.enable_web_ui:
            try:
                WebUiService(normalized, self.plugin_dir, self).validate()
            except WebUiError as exc:
                raise WebUiActionError(str(exc)) from exc

        updates = {key: getattr(normalized, key) for key in supplied}
        if not self._persist_config_updates(updates):
            raise WebUiActionError("配置文件保存失败，修改已回滚")
        reload_task = self._schedule_self_reload(
            delay=1.5,
            reason="Web UI 保存设置",
        )
        return {
            "message": "设置已保存，插件即将自动重载",
            "reload_scheduled": reload_task is not None,
        }

    async def web_ui_list_providers(self) -> dict[str, Any]:
        """Read saved and currently available AstrBot chat providers safely."""
        getter = getattr(self.context, "get_all_providers", None)
        providers = getter() if callable(getter) else []
        runtime_items: dict[str, dict[str, Any]] = {}
        for provider in providers:
            try:
                meta = provider.meta()
            except Exception as exc:
                logger.warning(
                    f"[{PLUGIN_NAME}] Failed to read provider metadata: {exc}"
                )
                continue
            provider_id = str(getattr(meta, "id", "") or "").strip()
            if not provider_id:
                continue
            config = getattr(provider, "provider_config", {})
            if not isinstance(config, dict):
                config = {}
            model = str(getattr(meta, "model", "") or config.get("model") or "").strip()
            provider_type = str(
                getattr(meta, "type", "") or config.get("type") or ""
            ).strip()
            display_name = str(
                config.get("name") or config.get("display_name") or provider_id
            ).strip()
            runtime_items[provider_id] = {
                "id": provider_id,
                "name": display_name,
                "model": model,
                "type": provider_type,
                "enabled": True,
                "available": True,
            }

        items_by_id: dict[str, dict[str, Any]] = {}
        manager = getattr(self.context, "provider_manager", None)
        saved_configs = getattr(manager, "providers_config", ())
        if not isinstance(saved_configs, (list, tuple)):
            saved_configs = ()
        for raw_config in saved_configs:
            if not isinstance(raw_config, dict):
                continue
            provider_id = str(raw_config.get("id") or "").strip()
            if not provider_id:
                continue
            provider_kind = str(raw_config.get("provider_type") or "").strip()
            adapter_type = str(raw_config.get("type") or "").strip()
            if provider_kind and provider_kind != "chat_completion":
                continue
            if (
                not provider_kind
                and provider_id not in runtime_items
                and "chat" not in adapter_type.casefold()
            ):
                continue
            runtime = runtime_items.get(provider_id, {})
            enabled = bool(raw_config.get("enable", True))
            items_by_id[provider_id] = {
                "id": provider_id,
                "name": str(
                    raw_config.get("name")
                    or raw_config.get("display_name")
                    or runtime.get("name")
                    or provider_id
                ).strip(),
                "model": str(
                    runtime.get("model")
                    or raw_config.get("model")
                    or raw_config.get("model_name")
                    or ""
                ).strip(),
                "type": str(runtime.get("type") or adapter_type).strip(),
                "enabled": enabled,
                "available": bool(runtime) and enabled,
            }

        for provider_id, runtime in runtime_items.items():
            items_by_id.setdefault(provider_id, runtime)
        items = list(items_by_id.values())
        items.sort(
            key=lambda item: (
                not item["available"],
                not item["enabled"],
                item["name"].casefold(),
                item["model"].casefold(),
                item["id"].casefold(),
            )
        )
        return {
            "selected": self.settings.prompt_llm_provider_id,
            "items": items,
        }

    async def web_ui_search_loras(
        self,
        keyword: str,
        limit: int,
    ) -> dict[str, Any]:
        """Force refresh and search only currently loadable LoRAs."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        try:
            catalog_records = await self._lora_catalog.refresh_for_operation()
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        records = (
            self._lora_catalog.search_records(catalog_records, keyword)
            if keyword.strip()
            else catalog_records
        )
        semantic_index = self._runtime_semantic_index()
        before_presence = {
            key: entry.present for key, entry in semantic_index.entries.items()
        }
        semantic_index.sync_presence(catalog_records)
        after_presence = {
            key: entry.present for key, entry in semantic_index.entries.items()
        }
        semantic_path = getattr(self, "_semantic_index_path", None)
        if before_presence != after_presence and semantic_path is not None:
            try:
                semantic_index.save(semantic_path)
            except LoraSemanticError as exc:
                logger.warning(f"[{PLUGIN_NAME}] LoRA 语义在库状态保存失败: {exc}")
        archive_summary = self._lora_catalog.archive_summary(catalog_records)
        effective_categories = {category: 0 for category in SEMANTIC_CATEGORIES}
        effective_works: dict[str, int] = {}
        effective_characters = 0
        analysis_counts = {
            "metadata_ready": 0,
            "analyzing": 0,
            "searchable": 0,
            "review_needed": 0,
            "failed": 0,
            "stale": 0,
        }
        for record in catalog_records:
            entry = semantic_index.entry_for(record)
            analysis_state = self._semantic_analysis_state(record, entry)
            analysis_counts[analysis_state] = analysis_counts.get(analysis_state, 0) + 1
            category = getattr(record, "category", "unknown")
            if entry is not None and entry.effective_category in SEMANTIC_CATEGORIES:
                category = entry.effective_category
            elif category not in effective_categories:
                category = "unclassified"
            effective_categories[category] += 1
            character_names = (
                list(entry.effective_values("character_names")) if entry else []
            )
            source_works = list(entry.effective_values("source_works")) if entry else []
            if isinstance(character_names, list) and character_names:
                effective_characters += 1
            elif getattr(record, "character_name", ""):
                effective_characters += 1
            work_values = (
                source_works
                if isinstance(source_works, list) and source_works
                else str(getattr(record, "source_work", "") or "").split("；")
            )
            for work in work_values:
                work_name = str(work or "").strip()
                if work_name:
                    effective_works[work_name] = effective_works.get(work_name, 0) + 1
        archive_summary["categories"] = effective_categories
        archive_summary["identified_characters"] = effective_characters
        archive_summary["works"] = [
            {"name": name, "count": count}
            for name, count in sorted(
                effective_works.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ]
        archive_summary["status"] = (
            self._semantic_catalog_status(catalog_records)
        )
        metadata_only = sum(
            1
            for record in catalog_records
            if self._semantic_analysis_state(
                record, semantic_index.entry_for(record)
            )
            == "metadata_ready"
            and bool(record.from_civitai)
        )
        unarchived = analysis_counts["metadata_ready"] - metadata_only
        archive_summary["analysis"] = {
            **analysis_counts,
            "total": len(catalog_records),
            "pending": sum(
                analysis_counts[key]
                for key in ("metadata_ready", "review_needed", "failed", "stale")
            ),
            "percent": round(
                analysis_counts["searchable"]
                * 100
                / max(1, len(catalog_records)),
                1,
            ),
        }
        archive_summary["digestion"] = {
            "archived": analysis_counts["searchable"],
            "stale": analysis_counts["stale"],
            "metadata_only": metadata_only,
            "unarchived": unarchived,
            "total": len(catalog_records),
            "pending": archive_summary["analysis"]["pending"],
            "percent": archive_summary["analysis"]["percent"],
        }
        return {
            "total": len(records),
            "catalog_total": len(catalog_records),
            "archive": archive_summary,
            "items": [
                self._web_ui_lora_item_v2(record)
                for record in records[:limit]
            ],
        }

    def _runtime_semantic_index(self) -> LoraSemanticIndex:
        """Return the v2 index, including lightweight compatibility instances."""
        semantic_index = getattr(self, "_semantic_index", None)
        if semantic_index is None:
            semantic_index = LoraSemanticIndex.empty()
            self._semantic_index = semantic_index
        return semantic_index

    def _semantic_analysis_state(self, record: Any, entry: Any) -> str:
        if entry is None:
            return "metadata_ready"
        current_fingerprint = semantic_source_fingerprint(record)
        if entry.source_fingerprint and entry.source_fingerprint != current_fingerprint:
            return "stale"
        return str(entry.analysis_status or "metadata_ready")

    def _semantic_catalog_status(
        self, records: tuple[Any, ...]
    ) -> dict[str, Any]:
        added: list[str] = []
        modified: list[str] = []
        current_keys: set[str] = set()
        for record in records:
            entry = self._runtime_semantic_index().entry_for(record)
            if entry is not None:
                current_keys.add(entry.identity_key)
            state = self._semantic_analysis_state(record, entry)
            if entry is None:
                added.append(record.name)
            elif state == "stale":
                modified.append(record.name)
        removed = [
            entry.canonical_name
            for key, entry in self._runtime_semantic_index().entries.items()
            if entry.present is False and key not in current_keys
        ]
        added.sort(key=str.casefold)
        modified.sort(key=str.casefold)
        removed.sort(key=str.casefold)
        return {
            "changed": bool(added or modified or removed),
            "fingerprint": semantic_catalog_fingerprint(records),
            "archived_fingerprint": "",
            "added": added,
            "modified": modified,
            "removed": removed,
            "pending": [*added, *modified],
            "current_count": len(records),
            "archived_count": sum(
                1
                for record in records
                if self._semantic_analysis_state(
                    record, self._runtime_semantic_index().entry_for(record)
                )
                == "searchable"
            ),
        }

    def _web_ui_lora_item_v2(self, record: Any) -> dict[str, Any]:
        entry = self._runtime_semantic_index().entry_for(record)
        analysis_status = self._semantic_analysis_state(record, entry)
        category = (
            getattr(record, "category", "unknown")
            if getattr(record, "category", "unknown")
            in SEMANTIC_CATEGORIES
            else "unclassified"
        )
        archive: dict[str, Any] = {}
        sources: dict[str, list[str]] = {}
        if entry is not None:
            archive = {
                "category": entry.effective_category or category,
                "character_names": list(entry.effective_values("character_names")),
                "source_works": list(entry.effective_values("source_works")),
                "artist_style_names": list(
                    entry.effective_values("artist_style_names")
                ),
                "aliases": list(entry.effective_values("aliases")),
                "summary": entry.analysis_summary,
                "confidence": entry.analysis_confidence,
            }
            sources = {
                field_name: sorted(
                    {fact.source for fact in entry.facts(field_name)}
                )
                for field_name in (
                    "category",
                    "character_names",
                    "source_works",
                    "artist_style_names",
                    "aliases",
                )
            }
        return {
            "name": record.name,
            "category": archive.get("category") or category,
            "catalog_category": getattr(record, "category", "unknown"),
            "model_name": getattr(record, "model_name", ""),
            "base_model": getattr(record, "base_model", ""),
            "description": getattr(record, "description", ""),
            "trigger_words": list(getattr(record, "trigger_words", ())),
            "tags": list(getattr(record, "tags", ())),
            "source": getattr(record, "source", ""),
            "favorite": bool(getattr(record, "favorite", False)),
            "aliases": list(getattr(record, "aliases", ())),
            "character_name": getattr(record, "character_name", ""),
            "source_work": getattr(record, "source_work", ""),
            "from_civitai": bool(getattr(record, "from_civitai", False)),
            "analysis_status": analysis_status,
            "searchable": analysis_status == "searchable",
            "review_needed": analysis_status == "review_needed",
            "archive_state": analysis_status,
            "archived": analysis_status == "searchable",
            "archive_current": analysis_status == "searchable",
            "archive_stale": analysis_status == "stale",
            "classified_at": entry.updated_at if entry is not None else "",
            "manual_override": entry.has_manual_facts if entry is not None else False,
            "has_manual_override": entry.has_manual_facts if entry is not None else False,
            "category_source": (
                "manual"
                if entry is not None and entry.has_manual_facts
                else "semantic"
                if entry is not None
                else "catalog"
            ),
            "archive": archive,
            "analysis_summary": entry.analysis_summary if entry is not None else "",
            "analysis_confidence": (
                entry.analysis_confidence if entry is not None else 0.0
            ),
            "semantic_sources": sources,
        }

    async def web_ui_refresh_loras(self) -> dict[str, Any]:
        """Run the mandatory LoRA Manager refresh gate."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        try:
            records = await self._lora_catalog.refresh_for_operation()
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        return {
            "total": len(records),
            "message": f"LoRA Manager 已刷新，共 {len(records)} 个可加载文件",
        }

    async def web_ui_download_lora(self, url: str) -> dict[str, Any]:
        """Download through LoRA Manager, fetch metadata, then refresh again."""
        if not url.strip():
            raise WebUiActionError("请填写 Civitai 模型页 URL")
        if not self.settings.enable_lora_download:
            raise WebUiActionError("LoRA 下载功能未启用")
        if self._lora_downloader is None:
            raise WebUiActionError(self._lora_download_error or "LoRA 下载服务不可用")
        try:
            await self._refresh_lora_manager_before("Web UI 下载 LoRA 前")
            result = await self._lora_downloader.download_from_url(url)
        except (LoraCatalogError, LoraDownloadError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        action = "已下载" if result.downloaded else "文件已存在"
        metadata = "元数据完成" if result.metadata_success else result.metadata_message
        return {
            "file_name": result.file_name,
            "downloaded": result.downloaded,
            "metadata_success": result.metadata_success,
            "message": f"{action}：{result.file_name}；{metadata}",
        }

    @staticmethod
    def _web_ui_archive_state(record: Any, entry: Any) -> str:
        """Describe whether the latest live LoRA has been digested by the LLM."""
        classification = (
            entry.get("classification") if isinstance(entry, dict) else None
        )
        if isinstance(classification, dict) and classification:
            current_fingerprint = LoraArchiveService.record_fingerprint(record)
            archived_fingerprint = str(
                entry.get("catalog_source_fingerprint") or ""
            )
            return (
                "archived"
                if archived_fingerprint == current_fingerprint
                else "stale"
            )
        return (
            "metadata_only"
            if bool(getattr(record, "from_civitai", False))
            else "unarchived"
        )

    @staticmethod
    def _web_ui_lora_item(
        record: Any,
        archive_by_name: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        entry = archive_by_name.get(
            canonical_lora_name(record.name).casefold(),
            {},
        )
        effective = entry.get("effective") if isinstance(entry, dict) else {}
        if not isinstance(effective, dict):
            effective = {}
        category = str(effective.get("category") or "")
        if category not in SEMANTIC_CATEGORIES:
            category = (
                record.category
                if record.category in SEMANTIC_CATEGORIES
                else "unclassified"
            )
        archive_character_names = effective.get("character_names", [])
        archive_source_works = effective.get("source_works", [])
        archive_aliases = effective.get("aliases", [])
        archive_style_names = effective.get("artist_style_names", [])
        character_name = (
            " / ".join(str(value) for value in archive_character_names if str(value))
            if isinstance(archive_character_names, list) and archive_character_names
            else getattr(record, "character_name", "")
        )
        source_work = (
            "；".join(str(value) for value in archive_source_works if str(value))
            if isinstance(archive_source_works, list) and archive_source_works
            else getattr(record, "source_work", "")
        )
        aliases = list(getattr(record, "aliases", ()))
        for values in (
            archive_aliases,
            archive_character_names,
            archive_source_works,
            archive_style_names,
        ):
            if isinstance(values, list):
                aliases.extend(str(value) for value in values if str(value).strip())
        aliases = list(dict.fromkeys(aliases))
        archive_state = ComfyAnimaPlugin._web_ui_archive_state(record, entry)
        manual_override = (
            dict(entry.get("manual_override") or {})
            if isinstance(entry, dict)
            and isinstance(entry.get("manual_override"), dict)
            else {}
        )
        category_source = (
            "manual"
            if manual_override
            else "llm"
            if archive_state in {"archived", "stale"}
            else "catalog"
        )
        return {
            "name": record.name,
            "category": category,
            "catalog_category": getattr(record, "category", "unknown"),
            "model_name": getattr(record, "model_name", ""),
            "base_model": getattr(record, "base_model", ""),
            "description": getattr(record, "description", ""),
            "trigger_words": list(getattr(record, "trigger_words", ())),
            "tags": list(getattr(record, "tags", ())),
            "source": getattr(record, "source", ""),
            "favorite": bool(getattr(record, "favorite", False)),
            "aliases": aliases,
            "character_name": character_name,
            "source_work": source_work,
            "from_civitai": bool(getattr(record, "from_civitai", False)),
            "archived": archive_state in {"archived", "stale"},
            "archive_state": archive_state,
            "archive_current": archive_state == "archived",
            "archive_stale": archive_state == "stale",
            "classified_at": str(entry.get("classified_at") or "")
            if isinstance(entry, dict)
            else "",
            "manual_override": manual_override,
            "has_manual_override": bool(manual_override),
            "category_source": category_source,
            "archive": effective,
        }

    async def web_ui_fetch_lora_metadata(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch Civitai metadata for one, many, or every current LoRA."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        if self._lora_downloader is None:
            raise WebUiActionError(
                self._lora_download_error or "LoRA Manager 元数据服务不可用"
            )
        mode = str(payload.get("mode") or "").strip().casefold()
        if mode not in {"", "selected", "all"}:
            raise WebUiActionError("元数据获取模式必须是 selected 或 all")
        select_all = bool(payload.get("all")) or mode == "all"
        raw_names = payload.get("names", [])
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        if not isinstance(raw_names, list):
            raise WebUiActionError("LoRA 选择必须是名称数组")
        names = [str(name).strip() for name in raw_names if str(name).strip()]
        if not select_all and not names:
            raise WebUiActionError("请至少选择一个需要获取元数据的 LoRA")
        if len(names) > 200:
            raise WebUiActionError("单次最多选择 200 个 LoRA")

        try:
            records = await self._lora_catalog.refresh_for_operation()
            if select_all:
                manager_result = await self._lora_downloader.fetch_all_civitai_metadata()
                try:
                    successes = max(
                        0,
                        int(
                            manager_result.get("updated")
                            or manager_result.get("success_count")
                            or 0
                        ),
                    )
                except (TypeError, ValueError):
                    successes = 0
                raw_failures = manager_result.get("failures", [])
                failures = (
                    [
                        {
                            "name": str(item.get("name") or ""),
                            "error": str(item.get("error") or "未知错误"),
                        }
                        for item in raw_failures
                        if isinstance(item, dict)
                    ]
                    if isinstance(raw_failures, list)
                    else []
                )
            else:
                selected = self._lora_archiver.select_records(records, names)
                successes = 0
                failures = []
                for record in selected:
                    if not record.file_path:
                        failures.append(
                            {"name": record.name, "error": "LoRA Manager 未返回文件路径"}
                        )
                        continue
                    ok, message = await self._lora_downloader.fetch_civitai_metadata(
                        record.file_path
                    )
                    if ok:
                        successes += 1
                    else:
                        failures.append({"name": record.name, "error": message})
                manager_result = {
                    "processed": len(selected),
                    "success": successes,
                    "failure_count": len(failures),
                }
            refreshed = await self._lora_catalog.refresh_for_operation()
        except (LoraArchiveError, LoraCatalogError, LoraDownloadError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        try:
            processed = max(
                0,
                int(manager_result.get("processed") or (len(records) if select_all else len(names))),
            )
        except (TypeError, ValueError):
            processed = len(records) if select_all else len(names)
        try:
            skipped = max(0, int(manager_result.get("skipped_count") or 0))
        except (TypeError, ValueError):
            skipped = 0
        try:
            failed_count = max(
                len(failures),
                int(manager_result.get("failure_count") or 0),
            )
        except (TypeError, ValueError):
            failed_count = len(failures)
        return {
            "all": select_all,
            "success": successes,
            "succeeded": successes,
            "processed": processed,
            "failed": failed_count,
            "skipped": skipped,
            "failures": failures,
            "manager_result": manager_result,
            "catalog_total": len(refreshed),
            "message": (
                f"Civitai 元数据获取完成：处理 {processed} 个，更新 {successes} 个"
                + (f"，跳过 {skipped} 个" if skipped else "")
                + (f"，失败 {failed_count} 个" if failed_count else "")
                + f"；最新可加载清单 {len(refreshed)} 个"
            ),
        }

    async def web_ui_get_lora_archive(self) -> dict[str, Any]:
        """Return archive status after the mandatory live LoRA refresh."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        if getattr(self, "_semantic_index", None) is not None:
            try:
                records = await self._lora_catalog.refresh_for_operation()
                semantic_index = self._runtime_semantic_index()
                semantic_index.sync_presence(records)
                semantic_index.save(self._semantic_index_path)
            except (LoraCatalogError, LoraSemanticError) as exc:
                message = getattr(exc, "user_message", str(exc))
                raise WebUiActionError(message) from exc
            return {
                "schema_version": 2,
                "status": self._semantic_catalog_status(records),
                "items": [self._web_ui_lora_item_v2(record) for record in records],
            }
        try:
            records = await self._lora_catalog.refresh_for_operation()
            status = self._lora_archiver.catalog_status(records)
            entries = self._lora_archiver.list_entries()
        except (LoraArchiveError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        return {
            "status": status.to_dict(),
            "items": list(entries),
        }

    async def web_ui_get_lora_detail(self, name: str) -> dict[str, Any]:
        """Refresh live sources before returning one exact safe LoRA dossier."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        try:
            records = await self._lora_catalog.refresh_for_operation()
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        target_key = canonical_lora_name(name).casefold()
        matches = [
            record
            for record in records
            if canonical_lora_name(record.name).casefold() == target_key
        ]
        if len(matches) != 1:
            raise WebUiActionError(
                "LoRA 不在刚刷新的可加载清单中，或名称无法唯一匹配"
            )
        detail = await self._lora_catalog.get_detail_v2(matches[0])
        result = detail.to_public_dict()
        result["semantic"] = self._web_ui_lora_item_v2(matches[0]).get(
            "archive", {}
        )
        result["analysis_status"] = self._semantic_analysis_state(
            matches[0], self._runtime_semantic_index().entry_for(matches[0])
        )
        return result

    async def web_ui_save_lora_semantic(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a human-reviewed semantic override after a fresh exact match."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        name = str(payload.get("name") or "").strip()
        if not name:
            raise WebUiActionError("请提供需要人工审核的 LoRA 精确名称")
        try:
            records = await self._lora_catalog.refresh_for_operation()
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        target_key = canonical_lora_name(name).casefold()
        matches = [
            record
            for record in records
            if canonical_lora_name(record.name).casefold() == target_key
        ]
        if len(matches) != 1:
            raise WebUiActionError(
                "LoRA 不在刚刷新的可加载清单中，或名称无法唯一匹配"
            )
        record = matches[0]
        category = str(payload.get("category") or "unclassified").strip()
        if category not in SEMANTIC_CATEGORIES:
            raise WebUiActionError("人工分类值不受支持")

        def values(field_name: str) -> tuple[str, ...]:
            raw = payload.get(field_name, [])
            if isinstance(raw, str):
                raw = re.split(r"[\n,，;；|]+", raw)
            if not isinstance(raw, (list, tuple, set)):
                raise WebUiActionError(f"{field_name} 必须是文本或数组")
            cleaned = tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in raw
                    if str(item).strip()
                )
            )
            if len(cleaned) > 100:
                raise WebUiActionError(f"{field_name} 最多保存 100 项")
            if any(len(item) > 240 for item in cleaned):
                raise WebUiActionError(f"{field_name} 中存在过长内容")
            return cleaned

        manual_values = {
            "category": (category,),
            "character_names": values("character_names"),
            "source_works": values("source_works"),
            "artist_style_names": values("artist_style_names"),
            "aliases": values("aliases"),
        }
        if category == "character" and not manual_values["character_names"]:
            raise WebUiActionError("角色分类至少需要一个角色名")
        if category == "artist_style" and not manual_values["artist_style_names"]:
            raise WebUiActionError("画师/风格分类至少需要一个画师或风格名")
        if category == "mixed" and not (
            manual_values["character_names"]
            and manual_values["artist_style_names"]
        ):
            raise WebUiActionError("混合分类必须同时填写角色名和画师/风格名")

        semantic_index = self._runtime_semantic_index()
        previous = semantic_index.entry_for(record)
        facts: dict[str, tuple[SemanticFact, ...]] = {}
        for field_name in SEMANTIC_FIELDS:
            retained = tuple(
                fact
                for fact in (previous.facts(field_name) if previous else ())
                if fact.source != "manual"
            )
            manual = tuple(
                SemanticFact(
                    value,
                    "manual",
                    ("web_ui.manual_review",),
                    1.0,
                )
                for value in manual_values[field_name]
            )
            facts[field_name] = (*retained, *manual)
        entry = SemanticEntry(
            identity_key=semantic_identity_key(record.name, record.sha256),
            canonical_name=record.name,
            sha256=record.sha256,
            analysis_status=(
                "searchable" if category != "unclassified" else "review_needed"
            ),
            analysis_summary=(previous.analysis_summary if previous else ""),
            analysis_confidence=(previous.analysis_confidence if previous else 0.0),
            source_fingerprint=semantic_source_fingerprint(record),
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error="",
            present=True,
            **facts,
        )
        semantic_index.upsert(entry)
        try:
            semantic_index.save(self._semantic_index_path)
        except LoraSemanticError as exc:
            raise WebUiActionError(f"人工审核结果保存失败：{exc}") from exc
        return {
            "item": self._web_ui_lora_item_v2(record),
            "message": f"已保存 LoRA 人工语义审核：{record.name}",
        }

    async def _run_lora_archive_llm(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Any:
        provider_id = self.settings.prompt_llm_provider_id.strip()
        if not provider_id:
            raise LoraArchiveError(
                "请先在插件设置中选择 LLM 绘图导演思考模型 Provider"
            )
        kwargs = {
            "prompt": user_prompt,
            "system_prompt": system_prompt,
            "temperature": 0.1,
            "max_tokens": min(
                12000,
                max(6000, int(self.settings.prompt_llm_max_tokens)),
            ),
        }
        timeout = max(300, int(self.settings.prompt_llm_timeout))
        try:
            if hasattr(self.context, "llm_generate"):
                return await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=provider_id,
                        **kwargs,
                    ),
                    timeout=timeout,
                )
            provider = self.context.get_provider_by_id(provider_id)
            if provider is None or not hasattr(provider, "text_chat"):
                raise LoraArchiveError("找不到所选 LLM 绘图导演 Provider")
            return await asyncio.wait_for(
                provider.text_chat(contexts=[], **kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LoraArchiveError("LLM LoRA 归档超时") from exc
        except LoraArchiveError:
            raise
        except Exception as exc:
            raise LoraArchiveError(
                "LLM LoRA 归档调用失败",
                f"provider={provider_id}, error={exc}",
            ) from exc

    async def web_ui_archive_loras(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Queue the v2 per-LoRA semantic pipeline when persistence is available."""
        if (
            getattr(self, "_lora_analysis", None) is None
            or getattr(self, "_task_store", None) is None
        ):
            return await self._web_ui_archive_loras_legacy(payload)
        return await self._queue_lora_semantic_analysis(payload)

    async def _queue_lora_semantic_analysis(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        store = self._require_task_store()
        semantic_index = self._runtime_semantic_index()
        try:
            records = await self._lora_catalog.refresh_for_operation()
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc

        semantic_index.sync_presence(records)
        try:
            semantic_index.save(self._semantic_index_path)
        except LoraSemanticError as exc:
            raise WebUiActionError(f"LoRA 语义索引保存失败：{exc}") from exc

        if bool(payload.get("sync_only")):
            removed = [
                entry.canonical_name
                for entry in semantic_index.entries.values()
                if not entry.present
            ]
            status = self._semantic_catalog_status(records)
            return {
                "skipped": True,
                "synced": True,
                "selected_count": 0,
                "batch_count": 0,
                "updated_names": [],
                "removed_names": sorted(removed, key=str.casefold),
                "status": status,
                "provider_id": "",
                "message": f"已同步 {len(removed)} 个删除记录，无需调用 LLM",
            }

        mode = str(payload.get("mode") or "").strip().casefold()
        if mode not in {"", "selected", "all"}:
            raise WebUiActionError("LoRA 归档模式必须是 selected 或 all")
        select_all = bool(payload.get("all")) or mode == "all"
        raw_names = payload.get("names", [])
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        if not isinstance(raw_names, list):
            raise WebUiActionError("LoRA 选择必须是名称数组")
        names = list(
            dict.fromkeys(
                str(name).strip() for name in raw_names if str(name).strip()
            )
        )
        if not select_all and not names:
            raise WebUiActionError("请至少选择一个需要 LLM 消化归档的 LoRA")
        if len(names) > 200:
            raise WebUiActionError("单次最多选择 200 个 LoRA")

        by_name = {record.name: record for record in records}
        if select_all:
            selected_records = list(records)
            if bool(payload.get("skip_when_unchanged")) and not bool(
                payload.get("force")
            ):
                selected_records = [
                    record
                    for record in records
                    if self._semantic_analysis_state(
                        record, semantic_index.entry_for(record)
                    )
                    != "searchable"
                ]
        else:
            missing = [name for name in names if name not in by_name]
            if missing:
                raise WebUiActionError(
                    "以下 LoRA 不在刚刷新的可加载清单中：" + "、".join(missing)
                )
            selected_records = [by_name[name] for name in names]

        if not selected_records:
            return {
                "skipped": True,
                "synced": False,
                "selected_count": 0,
                "batch_count": 0,
                "updated_names": [],
                "removed_names": [],
                "status": self._semantic_catalog_status(records),
                "provider_id": self.settings.prompt_llm_provider_id,
                "message": "LoRA 库没有需要重复建档的变化",
            }

        provider_id = await self._require_lora_analysis_provider()
        selected_names = [record.name for record in selected_records]
        run_id = store.create_task(
            "lora_semantic_analysis",
            mode="all" if select_all else "selected",
            requested_by="web_ui",
            total_items=len(selected_names),
            metadata={
                "selected_names": selected_names,
                "provider_id": provider_id,
                "fresh_catalog_count": len(records),
                "per_item_requests": True,
            },
        )
        store.append_event(
            run_id,
            "queue",
            "LoRA 语义建档任务已排队，等待再次刷新实时清单。",
            event_code="analysis_queued",
            details={"selected_count": len(selected_names)},
        )
        background = asyncio.create_task(
            self._run_lora_semantic_analysis(
                run_id,
                selected_names,
                select_all=select_all,
            ),
            name=f"{PLUGIN_NAME}:lora-analysis:{run_id}",
        )
        self._background_task_runs[run_id] = background
        background.add_done_callback(
            lambda _task, identifier=run_id: self._background_task_runs.pop(
                identifier, None
            )
        )
        return {
            "run_id": run_id,
            "status": "queued",
            "selected_count": len(selected_names),
            "provider_id": provider_id,
            "message": (
                f"LoRA 语义建档任务已创建：{len(selected_names)} 项；"
                "可在任务中心查看逐项进度、重试与失败原因"
            ),
        }

    async def _require_lora_analysis_provider(self) -> str:
        provider_id = self.settings.prompt_llm_provider_id.strip()
        if not provider_id:
            raise WebUiActionError(
                "请先在插件设置中选择 LLM 绘图导演思考模型 Provider"
            )
        provider_data = await self.web_ui_list_providers()
        selected = next(
            (
                item
                for item in provider_data.get("items", [])
                if str(item.get("id") or "") == provider_id
            ),
            None,
        )
        if selected is not None and bool(selected.get("available")):
            return provider_id
        getter = getattr(self.context, "get_provider_by_id", None)
        provider = getter(provider_id) if callable(getter) else None
        if provider is None:
            raise WebUiActionError(
                f"所选 Provider 当前不可用或未加载：{provider_id}"
            )
        return provider_id

    async def _run_lora_semantic_analysis(
        self,
        run_id: str,
        selected_names: list[str],
        *,
        select_all: bool,
    ) -> None:
        store = self._require_task_store()
        try:
            store.start_task(run_id, total_items=len(selected_names))
            store.append_event(
                run_id,
                "refresh",
                "正在执行建档前的 LoRA Manager 扫描与 ComfyUI 可加载清单刷新。",
                event_code="fresh_catalog_refresh_started",
            )
            records = await self._lora_catalog.refresh_for_operation()
            by_name = {record.name: record for record in records}
            missing = [name for name in selected_names if name not in by_name]
            if missing:
                store.append_event(
                    run_id,
                    "refresh",
                    "建档前实时清单已变化；任务已安全停止，请重新选择。",
                    level="ERROR",
                    event_code="fresh_catalog_changed",
                    details={"missing_count": len(missing)},
                )
                store.finish_task(
                    run_id,
                    "failed",
                    completed_items=0,
                    failed_items=len(missing),
                    error_code="fresh_catalog_changed",
                    error_summary=(
                        f"{len(missing)} 个所选 LoRA 已不在实时可加载清单中。"
                    ),
                )
                return
            selected_records = [by_name[name] for name in selected_names]
            store.append_event(
                run_id,
                "refresh",
                f"实时清单刷新完成，确认 {len(selected_records)} 个精确文件身份。",
                event_code="fresh_catalog_ready",
                details={"catalog_total": len(records)},
            )

            details = []
            for index, record in enumerate(selected_records, start=1):
                store.heartbeat(
                    run_id,
                    completed_items=0,
                    failed_items=0,
                    total_items=len(selected_records),
                )
                store.append_event(
                    run_id,
                    "metadata",
                    "正在聚合 Manager 元数据、模型/版本描述和使用提示。",
                    item_name=record.name,
                    batch_index=index,
                    batch_total=len(selected_records),
                    event_code="metadata_fetch_started",
                )
                detail = await self._lora_catalog.get_detail_v2(record)
                details.append(detail)
                store.append_event(
                    run_id,
                    "metadata",
                    f"LoRA 资料包已就绪（健康状态：{detail.metadata_health.status}）。",
                    item_name=record.name,
                    batch_index=index,
                    batch_total=len(selected_records),
                    event_code="metadata_fetch_completed",
                    details={
                        "metadata_health": detail.metadata_health.status,
                        "missing_sources": list(
                            detail.metadata_health.missing_sources
                        ),
                        "error_sources": list(detail.metadata_health.error_sources),
                    },
                )

            await self._lora_analysis.run(
                details,
                self._run_lora_archive_llm,
                selected_names=selected_names,
                run_id=run_id,
                requested_by="web_ui",
                max_repair_retries=2,
            )
        except asyncio.CancelledError:
            current = store.get_task(run_id)
            if current and current.get("status") in {"queued", "running"}:
                store.finish_task(
                    run_id,
                    "cancelled",
                    error_code="cancelled",
                    error_summary="管理员取消了 LoRA 语义建档任务。",
                )
            raise
        except (LoraAnalysisError, LoraCatalogError, LoraSemanticError) as exc:
            current = store.get_task(run_id)
            if current and current.get("status") in {"queued", "running"}:
                store.append_event(
                    run_id,
                    "run",
                    "LoRA 语义建档任务安全失败。",
                    level="ERROR",
                    event_code="analysis_setup_failed",
                    details={"exception_type": type(exc).__name__},
                )
                store.finish_task(
                    run_id,
                    "failed",
                    error_code="analysis_setup_failed",
                    error_summary=str(getattr(exc, "user_message", exc))[:500],
                )
        except Exception as exc:
            current = store.get_task(run_id)
            if current and current.get("status") in {"queued", "running"}:
                store.append_event(
                    run_id,
                    "run",
                    "LoRA 语义建档发生未预期错误。",
                    level="ERROR",
                    event_code="analysis_unexpected_error",
                    details={"exception_type": type(exc).__name__},
                )
                store.finish_task(
                    run_id,
                    "failed",
                    error_code="analysis_unexpected_error",
                    error_summary=f"建档内部错误（{type(exc).__name__}）。",
                )
            logger.error(
                f"[{PLUGIN_NAME}] LoRA v2 semantic analysis failed: {exc}",
                exc_info=True,
            )

    async def _web_ui_archive_loras_legacy(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run conservative LLM classification for selected or all LoRAs."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        if bool(payload.get("sync_only")):
            try:
                records = await self._lora_catalog.refresh_for_operation()
                before = self._lora_archiver.catalog_status(records)
                if before.added or before.modified:
                    raise WebUiActionError(
                        "当前仍有新增或修改的 LoRA，需要先执行 LLM 消化归档"
                    )
                status = self._lora_archiver.sync_catalog_presence(records)
            except WebUiActionError:
                raise
            except (LoraArchiveError, LoraCatalogError) as exc:
                message = getattr(exc, "user_message", str(exc))
                raise WebUiActionError(message) from exc
            return {
                "skipped": True,
                "synced": True,
                "selected_count": 0,
                "batch_count": 0,
                "updated_names": [],
                "removed_names": list(before.removed),
                "status": status.to_dict(),
                "provider_id": "",
                "message": f"已同步 {len(before.removed)} 个删除记录，无需调用 LLM",
            }
        mode = str(payload.get("mode") or "").strip().casefold()
        if mode not in {"", "selected", "all"}:
            raise WebUiActionError("LoRA 归档模式必须是 selected 或 all")
        select_all = bool(payload.get("all")) or mode == "all"
        raw_names = payload.get("names", [])
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        if not isinstance(raw_names, list):
            raise WebUiActionError("LoRA 选择必须是名称数组")
        names = [str(name).strip() for name in raw_names if str(name).strip()]
        if not select_all and not names:
            raise WebUiActionError("请至少选择一个需要 LLM 消化归档的 LoRA")
        if len(names) > 200:
            raise WebUiActionError("单次最多选择 200 个 LoRA")
        try:
            result = await self._lora_archiver.archive_from_catalog(
                self._lora_catalog,
                self._run_lora_archive_llm,
                selected_names=None if select_all else names,
                enrich_details=True,
                batch_size=8,
                max_batch_chars=60000,
                skip_when_unchanged=(
                    not bool(payload.get("force"))
                    if select_all
                    else bool(payload.get("skip_when_unchanged", False))
                ),
            )
        except (LoraArchiveError, LoraCatalogError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        response = result.to_dict()
        response["provider_id"] = self.settings.prompt_llm_provider_id
        response["message"] = (
            "LoRA 库没有变化，已跳过 LLM 归档"
            if result.skipped
            else (
                f"LLM 已消化归档 {result.selected_count} 个 LoRA，"
                f"共 {result.batch_count} 批"
            )
        )
        return response

    async def web_ui_list_presets(self) -> dict[str, Any]:
        """Refresh LoRA data and validate every saved preset."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        try:
            await self._refresh_lora_manager_before("Web UI 读取 LoRA 组合")
        except LoraCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        items: list[dict[str, Any]] = []
        for preset in self._lora_presets.presets:
            available = True
            error = ""
            try:
                await self._lora_catalog.resolve_selections(
                    preset.selections,
                    strict=True,
                )
            except LoraCatalogError as exc:
                available = False
                error = exc.user_message
            items.append(
                {
                    "name": preset.name,
                    "category": preset.category,
                    "category_label": CATEGORY_LABELS[preset.category],
                    "loras": [
                        f"{selection.name}={selection.strength:g}"
                        for selection in preset.selections
                    ],
                    "trigger_words": preset.trigger_words,
                    "description": preset.description,
                    "enabled": preset.enabled,
                    "available": available,
                    "error": error,
                }
            )
        active = next(
            (str(item.get("name") or "") for item in items if item.get("active")),
            "",
        )
        return {"items": items, "active_profile": active}

    async def web_ui_save_preset(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate against fresh Manager data, then persist a preset."""
        if self._lora_catalog is None:
            raise WebUiActionError("LoRA 工具未启用")
        previous_presets = self._lora_presets.to_config()
        try:
            await self._refresh_lora_manager_before("Web UI 保存 LoRA 组合")
            selections = parse_lora_entries(
                payload.get("loras", []),
                max_loras=self.settings.max_preset_loras,
            )
            selections = await self._lora_catalog.resolve_selections(
                selections,
                strict=True,
            )
            category = normalize_category(
                str(payload.get("category") or "auto"),
                allow_auto=True,
            )
            if category == "auto":
                category = await self._lora_catalog.infer_preset_category(selections)
            preset = self._lora_presets.save(
                name=str(payload.get("name") or ""),
                category=category,
                selections=selections,
                trigger_words=str(payload.get("trigger_words") or ""),
                description=str(payload.get("description") or ""),
                enabled=bool(payload.get("enabled", True)),
            )
        except (LoraCatalogError, LoraPresetError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        if not self._persist_config(
            "lora_presets",
            self._lora_presets.to_config(),
        ):
            self._lora_presets.load(previous_presets)
            raise WebUiActionError("组合保存失败，配置修改已回滚")
        reload_task = self._schedule_self_reload(
            delay=1.5,
            reason="Web UI 保存 LoRA 组合",
        )
        return {
            "name": preset.name,
            "message": f"已保存 {CATEGORY_LABELS[preset.category]}组合：{preset.name}",
            "reload_scheduled": reload_task is not None,
        }

    async def web_ui_delete_preset(self, identifier: str) -> dict[str, Any]:
        """Refresh Manager before deleting a saved preset."""
        previous_presets = self._lora_presets.to_config()
        try:
            await self._refresh_lora_manager_before("Web UI 删除 LoRA 组合")
            preset = self._lora_presets.delete(identifier)
        except (LoraCatalogError, LoraPresetError) as exc:
            message = getattr(exc, "user_message", str(exc))
            raise WebUiActionError(message) from exc
        if not self._persist_config(
            "lora_presets",
            self._lora_presets.to_config(),
        ):
            self._lora_presets.load(previous_presets)
            raise WebUiActionError("组合删除失败，配置修改已回滚")
        reload_task = self._schedule_self_reload(
            delay=1.5,
            reason="Web UI 删除 LoRA 组合",
        )
        return {
            "message": f"已删除 LoRA 组合：{preset.name}",
            "reload_scheduled": reload_task is not None,
        }

    async def web_ui_delete_lora(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delete one exact live LoRA without accepting a browser path."""
        return await self._web_ui_delete_asset("lora", payload)

    async def web_ui_delete_unet(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Delete one exact non-active UNET without accepting a browser path."""
        return await self._web_ui_delete_asset("unet", payload)

    async def _web_ui_delete_asset(
        self,
        asset_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._model_manager is None:
            raise WebUiActionError(
                self._model_manager_error or "模型删除服务未启用"
            )
        exact_name = str(payload.get("exact_name") or "").strip()
        confirm_name = str(payload.get("confirm_name") or "").strip()
        remove_from_presets = bool(payload.get("remove_from_presets"))
        preset_snapshot = (
            self._snapshot_lora_preset_state()
            if asset_type == "lora" and remove_from_presets
            else None
        )
        remote_delete_succeeded = False
        store = self._task_store
        run_id = ""
        if store is not None:
            run_id = store.create_task(
                "asset_delete",
                mode=asset_type,
                requested_by="web_ui",
                total_items=1,
                metadata={"asset_type": asset_type, "exact_name": exact_name},
            )
            store.start_task(run_id, total_items=1)
            store.append_event(
                run_id,
                "refresh",
                "正在强制刷新 LoRA Manager 与 ComfyUI 最新可加载清单。",
                event_code="asset_refresh_started",
                item_name=exact_name,
            )
        try:
            if asset_type == "lora":
                result = await self._model_manager.delete_lora(
                    exact_name,
                    confirm_name,
                    remove_from_presets=remove_from_presets,
                )
                remote_delete_succeeded = True
                fresh_records = await self._lora_catalog.refresh_for_operation()
                semantic_index = self._runtime_semantic_index()
                semantic_index.sync_presence(fresh_records)
                semantic_index.save(self._semantic_index_path)
            elif asset_type == "unet":
                result = await self._model_manager.delete_unet(
                    exact_name,
                    confirm_name,
                )
                await self._unet_catalog.list_models()
            else:
                raise WebUiActionError("不支持的模型类型")
        except WebUiActionError:
            raise
        except (ModelManagerError, LoraCatalogError, UnetCatalogError, LoraSemanticError) as exc:
            message = getattr(exc, "user_message", str(exc))
            rollback_applied = False
            rollback_failed = False
            if preset_snapshot is not None and not remote_delete_succeeded:
                try:
                    rollback_applied = self._restore_lora_preset_state(preset_snapshot)
                except ModelManagerError as rollback_exc:
                    rollback_failed = True
                    message = (
                        f"{message}；LoRA 组合回滚失败："
                        f"{rollback_exc.user_message}"
                    )
                    logger.error(
                        f"[{PLUGIN_NAME}] LoRA preset rollback failed after "
                        f"asset deletion error: {rollback_exc}"
                    )
                else:
                    if rollback_applied:
                        message = f"{message}；删除前的 LoRA 组合配置已恢复"
                        logger.warning(
                            f"[{PLUGIN_NAME}] Restored LoRA preset state after "
                            "asset deletion transaction failed"
                        )
            if remote_delete_succeeded:
                message = (
                    f"{message}；远端 LoRA 已删除，但删除后同步失败，"
                    "已保留组合清理结果"
                )
            if store is not None and run_id:
                event_message = (
                    "远端 LoRA 已删除，但删除后的实时清单刷新失败。"
                    if remote_delete_succeeded
                    else "资产删除未完成，远端文件未被确认移除。"
                )
                if rollback_applied:
                    event_message += " 删除前的 LoRA 组合配置和运行状态已恢复。"
                elif rollback_failed:
                    event_message += " LoRA 组合回滚失败，请立即检查配置。"
                store.append_event(
                    run_id,
                    "delete",
                    event_message,
                    level="ERROR",
                    event_code="asset_delete_failed",
                    item_name=exact_name,
                    details={
                        "asset_type": asset_type,
                        "error_type": type(exc).__name__,
                        "remote_delete_succeeded": remote_delete_succeeded,
                        "preset_rollback_applied": rollback_applied,
                        "preset_rollback_failed": rollback_failed,
                    },
                )
                store.finish_task(
                    run_id,
                    "failed",
                    completed_items=0,
                    failed_items=1,
                    error_code="asset_delete_failed",
                    error_summary=message,
                )
            raise WebUiActionError(message) from exc

        response = result.as_dict()
        response["run_id"] = run_id
        response["message"] = f"已安全删除 {asset_type.upper()}：{result.exact_name}"
        if store is not None and run_id:
            store.append_event(
                run_id,
                "delete",
                "远端删除成功，并已完成删除后的实时清单刷新。",
                event_code="asset_delete_succeeded",
                item_name=result.exact_name,
                details={
                    "asset_type": asset_type,
                    "preset_cleanup_count": result.preset_cleanup_count,
                },
            )
            store.finish_task(
                run_id,
                "succeeded",
                completed_items=1,
                failed_items=0,
                result=response,
            )
        if result.removed_from_presets:
            response["reload_scheduled"] = self._schedule_self_reload(
                delay=1.5,
                reason="Web UI 删除 LoRA 并清理组合",
            ) is not None
        return response

    async def web_ui_list_unet(self) -> dict[str, Any]:
        """Always read the latest UNETLoader catalog."""
        if self._unet_catalog is None:
            raise WebUiActionError(self._unet_catalog_error or "UNET 模型切换未启用")
        try:
            entries = await self._unet_catalog.list_models()
        except UnetCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        current = self._current_unet_model().casefold()
        return {
            "items": [
                {
                    "index": entry.index,
                    "name": entry.name,
                    "current": entry.name.casefold() == current,
                }
                for entry in entries
            ]
        }

    async def web_ui_select_unet(self, identifier: str) -> dict[str, Any]:
        """Refresh the UNET list, select a model and reload the plugin."""
        if self._unet_catalog is None:
            raise WebUiActionError(self._unet_catalog_error or "UNET 模型切换未启用")
        try:
            entries = await self._unet_catalog.list_models()
            selected = self._unet_catalog.resolve(identifier, entries)
        except UnetCatalogError as exc:
            raise WebUiActionError(exc.user_message) from exc
        if not self._persist_config("unet_model_name", selected.name):
            raise WebUiActionError("UNET 模型保存失败")
        reload_task = self._schedule_self_reload(
            delay=1.5,
            reason="Web UI 切换 UNET 模型",
        )
        return {
            "name": selected.name,
            "message": f"已切换 UNET 模型：{selected.name}",
            "reload_scheduled": reload_task is not None,
        }

    async def web_ui_list_config_profiles(self) -> dict[str, Any]:
        """List secret-free named ComfyUI environment profiles."""
        try:
            items = self._config_profiles.list_profiles()
        except ConfigProfileError as exc:
            raise WebUiActionError(str(exc)) from exc
        return {"items": items}

    async def web_ui_save_config_profile(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Save the current environment without credentials or global policy."""
        if self.config is None:
            raise WebUiActionError("当前 AstrBot 配置对象不支持持久化")
        name = str(payload.get("name") or "").strip()
        try:
            profile = self._config_profiles.save_profile(
                name,
                self.config,
                overwrite=bool(payload.get("overwrite")),
                activate=bool(payload.get("activate", True)),
            )
        except ConfigProfileError as exc:
            raise WebUiActionError(str(exc)) from exc
        return {
            "profile": profile,
            "message": f"已保存环境配置档案：{profile['name']}",
        }

    async def web_ui_switch_config_profile(self, identifier: str) -> dict[str, Any]:
        """Atomically apply a named environment and reload this plugin."""
        if self.config is None:
            raise WebUiActionError("当前 AstrBot 配置对象不支持持久化")
        try:
            profile = self._config_profiles.switch_profile(
                identifier,
                self.config,
                persist_updates=self._persist_config_updates,
            )
        except ConfigProfileError as exc:
            raise WebUiActionError(str(exc)) from exc
        reload_task = self._schedule_self_reload(
            delay=1.5,
            reason=f"Web UI 切换环境配置档案 {profile['name']}",
        )
        return {
            "profile": profile,
            "message": f"已切换环境配置档案：{profile['name']}，插件即将重载",
            "reload_scheduled": reload_task is not None,
        }

    async def web_ui_delete_config_profile(self, identifier: str) -> dict[str, Any]:
        """Delete a named environment profile without changing live settings."""
        try:
            profile = self._config_profiles.delete_profile(identifier)
        except ConfigProfileError as exc:
            raise WebUiActionError(str(exc)) from exc
        return {
            "profile": profile,
            "message": f"已删除环境配置档案：{profile['name']}",
        }

    async def web_ui_get_logs(
        self,
        after_id: int,
        limit: int,
    ) -> dict[str, Any]:
        """Return recent redacted records emitted by this plugin only."""
        return self._log_console.snapshot(after_id=after_id, limit=limit)

    async def web_ui_clear_logs(self) -> dict[str, Any]:
        """Clear the plugin's in-memory WebUI view, not AstrBot's file logs."""
        return self._log_console.clear_buffer()

    def _require_task_store(self) -> TaskStore:
        if self._task_store is None:
            raise WebUiActionError(
                self._task_store_error or "持久任务事件库不可用"
            )
        return self._task_store

    async def web_ui_list_tasks(
        self,
        limit: int,
        task_type: str,
        status: str,
    ) -> dict[str, Any]:
        store = self._require_task_store()
        statuses = [status] if status else None
        return {
            "items": store.recent_tasks(
                limit=limit,
                statuses=statuses,
                task_type=task_type,
            )
        }

    async def web_ui_get_task(self, run_id: str) -> dict[str, Any]:
        task = self._require_task_store().get_task(run_id)
        if task is None:
            raise WebUiActionError("任务不存在或已超过保留期限")
        return task

    async def web_ui_get_task_events(
        self,
        run_id: str,
        after_seq: int,
        limit: int,
    ) -> dict[str, Any]:
        store = self._require_task_store()
        if store.get_task(run_id) is None:
            raise WebUiActionError("任务不存在或已超过保留期限")
        return store.read_events(
            run_id=run_id,
            after_seq=after_seq,
            limit=limit,
        )

    async def web_ui_cancel_task(self, run_id: str) -> dict[str, Any]:
        store = self._require_task_store()
        task_info = store.get_task(run_id)
        if task_info is None:
            raise WebUiActionError("任务不存在或已超过保留期限")
        if task_info.get("status") not in {"queued", "running"}:
            raise WebUiActionError("该任务已经结束，不能取消")
        task = self._background_task_runs.get(run_id)
        if task is None or task.done():
            raise WebUiActionError("任务当前不在此插件实例中运行")
        task.cancel()
        store.append_event(
            run_id,
            "cancel",
            "管理员请求取消任务",
            level="WARNING",
            event_code="cancel_requested",
        )
        return {"run_id": run_id, "message": "已请求取消任务"}

    async def _create_job(
        self, user_id: str, options: GenerationOptions, event: AstrMessageEvent
    ) -> GenerationJob | str:
        """检查重复任务和冷却，并登记新任务。"""
        now = time.monotonic()
        async with self._jobs_lock:
            existing = self._active_jobs.get(user_id)
            if existing and existing.task and not existing.task.done():
                return "你已有生成任务，请先等待完成或使用 /anima cancel"

            bypass_cooldown = bool(
                event.is_admin() and self.settings.admin_ignore_cooldown
            )
            if not bypass_cooldown:
                last_request = self._last_request_at.get(user_id, 0.0)
                remaining = self.settings.user_cooldown - (now - last_request)
                if remaining > 0:
                    return f"操作过快，请在 {int(remaining) + 1} 秒后重试"

            job = GenerationJob(
                user_id=user_id,
                prompt_preview=options.prompt[:80],
                created_at=now,
            )
            job.task = asyncio.create_task(self._execute_job(job, options, event))
            self._active_jobs[user_id] = job
            self._last_request_at[user_id] = now
            return job

    async def _run_job(
        self, event: AstrMessageEvent, options: GenerationOptions
    ) -> tuple[list[Path], int, str, str, Optional[str]]:
        """登记、等待并清理一次用户生成任务。"""
        user_id = str(event.get_sender_id() or "unknown")
        job_or_error = await self._create_job(user_id, options, event)
        if isinstance(job_or_error, str):
            raise ValueError(job_or_error)
        job = job_or_error
        try:
            return await job.task
        finally:
            async with self._jobs_lock:
                if self._active_jobs.get(user_id) is job:
                    self._active_jobs.pop(user_id, None)

    async def _run_auxiliary_job(
        self,
        event: AstrMessageEvent,
        label: str,
        operation: Any,
    ) -> Any:
        """Apply the normal per-user duplicate and cooldown rules to image tools."""
        user_id = str(event.get_sender_id() or "unknown")
        now = time.monotonic()
        async with self._jobs_lock:
            existing = self._active_jobs.get(user_id)
            if existing and existing.task and not existing.task.done():
                raise ValueError("你已有图片任务，请等待完成或先取消当前任务")
            bypass_cooldown = bool(
                event.is_admin() and self.settings.admin_ignore_cooldown
            )
            if not bypass_cooldown:
                remaining = self.settings.user_cooldown - (
                    now - self._last_request_at.get(user_id, 0.0)
                )
                if remaining > 0:
                    raise ValueError(f"操作过快，请在 {int(remaining) + 1} 秒后重试")
            job = GenerationJob(
                user_id=user_id,
                prompt_preview=label[:80],
                created_at=now,
            )
            task_type = {
                "reverse prompt": "reverse_prompt",
                "reverse draw": "reverse_draw",
                "RTX upscale": "rtx_upscale",
            }.get(label, "image_tool")
            if self._task_store is not None:
                job.task_run_id = self._task_store.create_task(
                    task_type,
                    mode="qq_command",
                    requested_by=user_id,
                    total_items=1,
                    metadata={"operation": task_type},
                )
                self._task_store.start_task(job.task_run_id, total_items=1)
                self._task_store.append_event(
                    job.task_run_id,
                    "run",
                    "图片任务开始执行，正在读取本次显式提供或引用的图片。",
                    event_code="image_task_started",
                )

            async def runner() -> Any:
                try:
                    result = await operation(job)
                    if self._task_store is not None and job.task_run_id:
                        self._task_store.append_event(
                            job.task_run_id,
                            "run",
                            "图片任务的全部阶段已执行完成。",
                            event_code="image_task_succeeded",
                            details={"final_state": job.state},
                        )
                        self._task_store.finish_task(
                            job.task_run_id,
                            "succeeded",
                            completed_items=1,
                            failed_items=0,
                            result={"final_state": job.state},
                        )
                    return result
                except asyncio.CancelledError:
                    job.state = "cancelled"
                    if job.prompt_id and self._client:
                        await self._client.cancel(job.prompt_id)
                    if self._task_store is not None and job.task_run_id:
                        self._task_store.finish_task(
                            job.task_run_id,
                            "cancelled",
                            completed_items=0,
                            failed_items=0,
                            error_code="cancelled",
                            error_summary="用户或管理员取消了图片任务。",
                        )
                    raise
                except Exception as exc:
                    failed_stage = job.failed_stage or job.state
                    job.failed_stage = failed_stage
                    job.state = "failed"
                    error_code = str(
                        getattr(exc, "code", "image_task_failed")
                    )[:80]
                    if not re.fullmatch(r"[a-z0-9_\-]+", error_code):
                        error_code = "image_task_failed"
                    if self._task_store is not None and job.task_run_id:
                        safe_message = str(
                            getattr(exc, "user_message", type(exc).__name__)
                        )[:500]
                        self._task_store.append_event(
                            job.task_run_id,
                            "run",
                            "图片任务在当前阶段失败。",
                            level="ERROR",
                            event_code="image_task_failed",
                            details={
                                "final_state": job.state,
                                "failed_stage": failed_stage,
                                "error_type": type(exc).__name__,
                                "error_code": error_code,
                            },
                        )
                        self._task_store.finish_task(
                            job.task_run_id,
                            "failed",
                            completed_items=0,
                            failed_items=1,
                            error_code=error_code,
                            error_summary=safe_message,
                        )
                    raise

            job.task = asyncio.create_task(runner())
            self._active_jobs[user_id] = job
            self._last_request_at[user_id] = now
        try:
            return await job.task
        finally:
            async with self._jobs_lock:
                if self._active_jobs.get(user_id) is job:
                    self._active_jobs.pop(user_id, None)

    def _record_image_task_phase(
        self,
        job: GenerationJob,
        phase: str,
        message: str,
        event_code: str,
        *,
        details: Optional[dict[str, Any]] = None,
        level: str = "INFO",
    ) -> None:
        if self._task_store is None or not job.task_run_id:
            return
        self._task_store.append_event(
            job.task_run_id,
            phase,
            message,
            level=level,
            event_code=event_code,
            details=details,
        )

    async def _execute_upscale_job(
        self,
        job: GenerationJob,
        event: AstrMessageEvent,
        scale: float,
    ) -> GeneratedImagePaths:
        """Upload one validated QQ image and execute the standalone RTX workflow."""
        assert self._client is not None
        assert self._upscale_workflow_builder is not None
        source: Optional[Path] = None
        image_paths = GeneratedImagePaths()
        started_at = time.monotonic()
        try:
            job.state = "reading_image"
            source = await self._image_input.collect_one(event)
            self._record_image_task_phase(
                job,
                "input",
                "输入图片校验完成，格式、文件大小与像素总量均在限制内。",
                "input_image_ready",
                details={"bytes": source.stat().st_size},
            )
            async with self._generation_slots:
                job.state = "uploading"
                self._record_image_task_phase(
                    job,
                    "upload",
                    "正在将安全命名的图片副本上传到 ComfyUI input。",
                    "comfy_upload_started",
                )
                uploaded = await self._client.upload_image(source)
                job.state = "building"
                self._record_image_task_phase(
                    job,
                    "workflow",
                    "图片上传完成，正在构建独立 RTX 放大工作流。",
                    "rtx_workflow_building",
                    details={"scale": scale, "quality": self.settings.rtx_quality},
                )
                workflow, preferred_nodes = self._upscale_workflow_builder.build(
                    uploaded.workflow_value,
                    scale=scale,
                    quality=self.settings.rtx_quality,
                )
                job.state = "submitting"
                job.prompt_id = await self._client.submit(workflow)
                job.state = "upscaling"
                self._record_image_task_phase(
                    job,
                    "comfyui",
                    "RTX 工作流已提交，正在等待 ComfyUI 输出。",
                    "rtx_generation_waiting",
                )
                references = await self._client.wait_for_images(
                    job.prompt_id,
                    preferred_nodes,
                )
                job.state = "downloading"
                job_dir = self._temp_dir / job.prompt_id
                for reference in references:
                    image_paths.append(
                        await self._client.download_image(reference, job_dir)
                    )
                image_paths.elapsed_seconds = max(
                    0.0,
                    time.monotonic() - started_at,
                )
                try:
                    image_paths.gpu_name = await self._client.gpu_name()
                except Exception as exc:
                    logger.warning(
                        f"[{PLUGIN_NAME}] unable to read ComfyUI GPU model: {exc}"
                    )
                job.state = "completed"
                self._record_image_task_phase(
                    job,
                    "download",
                    "RTX 输出下载完成。",
                    "rtx_output_ready",
                    details={"image_count": len(image_paths)},
                )
                return image_paths
        except Exception:
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise
        finally:
            if source is not None:
                source.unlink(missing_ok=True)

    async def _execute_job(
        self,
        job: GenerationJob,
        options: GenerationOptions,
        event: AstrMessageEvent,
    ) -> tuple[list[Path], int, str, str, Optional[str]]:
        """占用并发槽，提交任务、等待结果并下载图片。"""
        assert self._client is not None
        assert self._workflow_builder is not None
        started_at = time.monotonic()
        image_paths = GeneratedImagePaths()
        effective_prompt = options.prompt
        provider_id = ""
        director_negative = ""
        director_warning: Optional[str] = None
        try:
            async with self._generation_slots:
                use_llm = (
                    self.settings.enable_prompt_llm
                    if options.use_prompt_llm is None
                    else options.use_prompt_llm
                )
                if use_llm:
                    job.state = "directing"
                    try:
                        if not self._director:
                            raise PromptDirectorError(
                                "LLM 分镜模块不可用", self._director_error or ""
                            )
                        (
                            effective_prompt,
                            provider_id,
                            director_negative,
                        ) = await self._generate_directed_prompt(event, options.prompt)
                    except PromptDirectorError as exc:
                        if exc.fatal or not self.settings.prompt_llm_fallback:
                            raise
                        director_warning = exc.user_message
                        logger.warning(
                            f"[{PLUGIN_NAME}] LLM 分镜失败并回退原始提示词: {exc}"
                        )

                job.state = "building"
                try:
                    job.state = "refreshing_lora"
                    await self._refresh_lora_manager_before("生成图片前注入 LoRA")
                    job.state = "building"
                    clean_prompt, parsed_loras = extract_lora_selections(
                        effective_prompt,
                        max_loras=self.settings.max_total_dynamic_loras,
                    )
                    selected_presets, replace_lora_stack = self._resolve_job_presets(
                        options.lora_preset,
                        parsed_loras,
                    )
                    resolved_records = {}

                    async def resolve_lora_group(
                        selections: tuple[Any, ...],
                    ) -> tuple[Any, ...]:
                        if not selections:
                            return ()
                        if not self._lora_catalog:
                            if self.settings.strict_lora_validation:
                                raise LoraCatalogError(
                                    "LoRA 清单工具未启用，无法严格校验动态 LoRA"
                                )
                            return deduplicate_selections(selections)
                        resolved, records = (
                            await self._lora_catalog.resolve_selections_with_records(
                                selections,
                                strict=self.settings.strict_lora_validation,
                            )
                        )
                        resolved_records.update(records)
                        return deduplicate_selections(resolved)

                    runtime_presets = []
                    for selected_preset in selected_presets:
                        runtime_presets.append(
                            replace(
                                selected_preset,
                                selections=await resolve_lora_group(
                                    selected_preset.selections
                                ),
                            )
                        )
                    selected_presets = tuple(runtime_presets)
                    resolved_option_loras = await resolve_lora_group(
                        options.dynamic_loras
                    )
                    resolved_prompt_loras = await resolve_lora_group(parsed_loras)
                    preset_selections = tuple(
                        selection
                        for selected_preset in selected_presets
                        for selection in selected_preset.selections
                    )
                    preset_names = {
                        canonical_lora_name(selection.name).casefold()
                        for selection in preset_selections
                    }
                    extra_prompt_loras = {
                        canonical_lora_name(selection.name).casefold()
                        for selection in resolved_prompt_loras
                        if canonical_lora_name(selection.name).casefold()
                        not in preset_names
                    }
                    if len(extra_prompt_loras) > self.settings.max_dynamic_loras:
                        raise LoraWorkflowError(
                            "完整风格栈之外最多允许 LLM 自行追加 "
                            f"{self.settings.max_dynamic_loras} 个 LoRA"
                        )
                    merge_plan = merge_runtime_lora_selections(
                        selected_presets,
                        resolved_option_loras,
                        resolved_prompt_loras,
                    )
                    dynamic_loras = merge_plan.selections
                    if merge_plan.ignored_locked_overrides:
                        logger.warning(
                            f"[{PLUGIN_NAME}] 已忽略对保存风格权重的覆盖: "
                            + ", ".join(merge_plan.ignored_locked_overrides)
                        )
                    if len(dynamic_loras) > self.settings.max_total_dynamic_loras:
                        raise LoraWorkflowError(
                            "组合、指令与提示词中的动态 LoRA 合计最多允许 "
                            f"{self.settings.max_total_dynamic_loras} 个"
                        )
                    combined_negative = ", ".join(
                        part
                        for part in (
                            options.negative_prompt.strip(" ,"),
                            director_negative.strip(" ,"),
                        )
                        if part
                    )
                    trigger_plan = build_lora_trigger_plan(
                        prompt=clean_prompt,
                        negative_prompt=combined_negative,
                        selections=dynamic_loras,
                        records_by_name=resolved_records,
                        presets=selected_presets,
                    )
                    clean_prompt = trigger_plan.prompt
                    if trigger_plan.added:
                        logger.info(
                            f"[{PLUGIN_NAME}] 已按最新 LoRA 元数据补充触发词: "
                            + ", ".join(trigger_plan.added)
                        )
                    for skipped_trigger in trigger_plan.skipped:
                        logger.info(
                            f"[{PLUGIN_NAME}] LoRA 触发词未自动注入: "
                            f"{skipped_trigger}"
                        )
                    if not clean_prompt:
                        raise LoraWorkflowError("移除 LoRA 标签后绘图提示词为空")
                    if len(clean_prompt) > self.settings.max_prompt_length:
                        raise LoraWorkflowError(
                            "应用组合触发词后的提示词不能超过 "
                            f"{self.settings.max_prompt_length} 个字符"
                        )
                except (LoraWorkflowError, LoraCatalogError, LoraPresetError) as exc:
                    message = getattr(exc, "user_message", str(exc))
                    raise WorkflowError(f"动态 LoRA 处理失败: {message}") from exc

                effective_options = replace(
                    options,
                    prompt=clean_prompt,
                    negative_prompt=combined_negative,
                    dynamic_loras=dynamic_loras,
                    lora_injection_mode=(
                        "replace" if replace_lora_stack else options.lora_injection_mode
                    ),
                )
                workflow, seed, preferred_nodes = self._workflow_builder.build(
                    effective_options
                )
                job.state = "submitting"
                job.prompt_id = await self._client.submit(workflow)
                job.state = "generating"
                references = await self._client.wait_for_images(
                    job.prompt_id, preferred_nodes
                )
                job.state = "downloading"
                job_dir = self._temp_dir / job.prompt_id
                for reference in references:
                    image_paths.append(
                        await self._client.download_image(reference, job_dir)
                    )
                image_paths.elapsed_seconds = max(0.0, time.monotonic() - started_at)
                try:
                    image_paths.gpu_name = await self._client.gpu_name()
                except Exception as exc:
                    logger.warning(
                        f"[{PLUGIN_NAME}] unable to read ComfyUI GPU model: {exc}"
                    )
                job.state = "completed"
                return (
                    image_paths,
                    seed,
                    clean_prompt,
                    provider_id,
                    director_warning,
                )
        except asyncio.CancelledError:
            job.state = "cancelled"
            if job.prompt_id:
                await self._client.cancel(job.prompt_id)
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise
        except Exception:
            job.failed_stage = job.failed_stage or job.state
            job.state = "failed"
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise

    async def _refresh_lora_manager_before(self, action: str) -> int:
        """所有 LoRA 操作的统一强制刷新门禁。"""
        if not self._lora_catalog:
            raise LoraCatalogError("LoRA Manager 清单服务未启用，已停止后续 LoRA 操作")
        records = await self._lora_catalog.refresh_for_operation()
        logger.info(
            f"[{PLUGIN_NAME}] {action}：LoRA Manager 强制刷新完成，"
            f"最新可加载文件 {len(records)} 个"
        )
        return len(records)

    def _resolve_job_presets(
        self,
        explicit_identifier: str,
        parsed_loras: tuple[Any, ...],
    ) -> tuple[tuple[LoraPreset, ...], bool]:
        """选择本次风格/角色预设，并决定是否替换节点 462 的原风格栈。"""
        if explicit_identifier:
            explicit = self._lora_presets.resolve(explicit_identifier)
            if explicit.category in {
                PRESET_CATEGORY_ARTIST_STYLE,
                PRESET_CATEGORY_MIXED,
            }:
                return (explicit,), True
            if explicit.category == PRESET_CATEGORY_CHARACTER:
                default_style = self._resolve_default_style_preset()
                if default_style:
                    return (default_style, explicit), True
                return (explicit,), False

        expanded_style = self._lora_presets.match_style_selections(parsed_loras)
        if expanded_style:
            return (expanded_style,), True

        default_style = self._resolve_default_style_preset()
        if default_style:
            return (default_style,), True
        return (), False

    def _lora_preset_references(self, exact_name: str) -> tuple[str, ...]:
        """Return saved preset names that currently reference one exact LoRA."""
        target = canonical_lora_name(exact_name).casefold()
        if not target:
            return ()
        return tuple(
            preset.name
            for preset in self._lora_presets.presets
            if any(
                canonical_lora_name(selection.name).casefold() == target
                for selection in preset.selections
            )
        )

    def _snapshot_lora_preset_state(self) -> dict[str, Any]:
        """Capture persisted and in-memory preset state before a delete transaction."""
        config = getattr(self, "config", None)
        default_style = self.settings.default_style_preset
        if config is not None:
            default_style = str(config.get("default_style_preset", default_style) or "")
        return {
            "lora_presets": self._lora_presets.to_config(),
            "default_style_preset": default_style,
        }

    def _restore_lora_preset_state(self, snapshot: dict[str, Any]) -> bool:
        """Restore a preset cleanup that preceded an unconfirmed remote delete."""
        presets = list(snapshot.get("lora_presets") or [])
        default_style = str(snapshot.get("default_style_preset") or "")
        config = getattr(self, "config", None)
        current_default = self.settings.default_style_preset
        if config is not None:
            current_default = str(
                config.get("default_style_preset", current_default) or ""
            )
        if (
            self._lora_presets.to_config() == presets
            and current_default == default_style
        ):
            return False
        if not self._persist_config_updates(
            {
                "lora_presets": presets,
                "default_style_preset": default_style,
            }
        ):
            raise ModelManagerError(
                "删除失败后无法恢复 LoRA 组合配置，请立即检查配置文件"
            )
        self._lora_presets.load(presets)
        return True

    def _remove_lora_from_presets(self, exact_name: str) -> int:
        """Explicitly remove one LoRA from presets and persist the new registry."""
        target = canonical_lora_name(exact_name).casefold()
        if not target:
            return 0
        updated: list[dict[str, Any]] = []
        changed_count = 0
        removed_preset_names: set[str] = set()
        for item in self._lora_presets.to_config():
            remaining = []
            removed_here = False
            for raw in item.get("loras", []):
                name = str(raw).split("=", 1)[0].strip()
                if canonical_lora_name(name).casefold() == target:
                    removed_here = True
                    continue
                remaining.append(raw)
            if removed_here:
                changed_count += 1
            if remaining:
                updated.append({**item, "loras": remaining})
            elif removed_here:
                removed_preset_names.add(str(item.get("name") or ""))

        if changed_count == 0:
            return 0
        updates: dict[str, Any] = {"lora_presets": updated}
        if self.settings.default_style_preset in removed_preset_names:
            updates["default_style_preset"] = ""
        if not self._persist_config_updates(updates):
            raise ModelManagerError("LoRA 预设清理保存失败，已阻止删除")
        self._lora_presets.load(updated)
        return changed_count

    def _current_unet_model(self) -> str:
        """返回配置覆盖值；未覆盖时读取当前工作流模板的 UNET。"""
        configured = self.settings.unet_model_name.strip()
        if configured:
            return configured
        if not self._workflow_builder:
            return ""
        binding = self._workflow_builder.profile.unet
        if binding is not None:
            value = self._workflow_builder.get_template_input(
                binding.node_id,
                binding.input_name,
            )
            return str(value or "").strip()
        value = self._workflow_builder.get_template_input(
            self.settings.unet_loader_node_id,
            self.settings.unet_model_input_name,
        )
        return str(value or "").strip()

    def _resolve_default_style_preset(self) -> Optional[LoraPreset]:
        """读取配置中的默认完整风格栈；配置错误时给出可操作提示。"""
        identifier = self.settings.default_style_preset.strip()
        if not identifier:
            return None
        try:
            preset = self._lora_presets.resolve(identifier)
        except LoraPresetError as exc:
            raise LoraPresetError(
                f"默认风格预设“{identifier}”不可用，请在后台修正或清空该设置"
            ) from exc
        if preset.category != PRESET_CATEGORY_ARTIST_STYLE:
            raise LoraPresetError(f"默认风格预设“{identifier}”必须属于画师/风格分类")
        return preset

    def _find_requested_style_preset(self, text: str) -> str:
        """从自然语言中识别“用风格001……”并返回精确保存名称。"""
        registry = getattr(self, "_lora_presets", None)
        if registry is None:
            return ""
        preset = registry.find_mentioned_style(text)
        if preset:
            return preset.name
        requested = re.search(r"风格\d+(?!\d)", str(text or ""), flags=re.IGNORECASE)
        return requested.group(0) if requested else ""

    @staticmethod
    def _parse_resolution_value(value: str) -> tuple[int, int]:
        """解析并校验 `宽x高` 分辨率。"""
        normalized = str(value or "").strip().lower()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = normalized.replace("×", "x").replace("＊", "x").replace("*", "x")
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", normalized)
        if not match:
            raise ValueError("分辨率格式应为 宽x高，例如 832x1216")
        width, height = int(match.group(1)), int(match.group(2))
        if not (
            MIN_IMAGE_SIDE <= width <= MAX_IMAGE_SIDE
            and MIN_IMAGE_SIDE <= height <= MAX_IMAGE_SIDE
        ):
            raise ValueError(f"宽高必须在 {MIN_IMAGE_SIDE} 到 {MAX_IMAGE_SIDE} 之间")
        return width, height

    @classmethod
    def _extract_resolution_request(
        cls, text: str
    ) -> tuple[Optional[int], Optional[int]]:
        """从“分辨率832x1216”等自然语言中提取本次画布大小。"""
        source = str(text or "")
        patterns = (
            r"(?:分辨率|尺寸|画布)\s*(?:设置?为|设为|为|是|[:：])?\s*(\d{2,5}\s*[xX×＊*]\s*\d{2,5})",
            r"(\d{2,5}\s*[xX×＊*]\s*\d{2,5})\s*(?:的)?\s*(?:分辨率|尺寸|画布)",
            r"(?<!\d)(\d{2,5}\s*[xX×＊*]\s*\d{2,5})(?!\d)",
        )
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE)
            if match:
                return cls._parse_resolution_value(match.group(1))
        return None, None

    @classmethod
    def _extract_size_option(
        cls, command_text: str
    ) -> tuple[str, Optional[int], Optional[int]]:
        """从 `/画图` 原始 Tag 中提取可选 `--size 宽x高`。"""
        text = str(command_text or "")
        marker = re.search(r"(?:^|\s)--size(?:\s|$)", text)
        pattern = re.compile(
            r"(?:^|\s)--size\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))",
            flags=re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if marker and not matches:
            raise ValueError("--size 缺少宽x高参数")
        if not matches:
            return text.strip(), None, None
        if len(matches) > 1:
            raise ValueError("单次只能指定一个 --size")
        match = matches[0]
        value = next((part for part in match.groups() if part is not None), "")
        width, height = cls._parse_resolution_value(value)
        cleaned = f"{text[: match.start()]} {text[match.end() :]}"
        return re.sub(r"\s{2,}", " ", cleaned).strip(), width, height

    @staticmethod
    def _extract_preset_option(command_text: str) -> tuple[str, str]:
        """从直接绘图指令中提取 --preset，同时保留原始 Tag 格式。"""
        text = str(command_text or "")
        marker = re.search(r"(?:^|\s)--(?:lora-)?preset(?:\s|$)", text)
        pattern = re.compile(
            r"(?:^|\s)--(?:lora-)?preset\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
        )
        matches = list(pattern.finditer(text))
        if marker and not matches:
            raise ValueError("--preset 缺少组合名称或序号")
        if not matches:
            return text.strip(), ""
        if len(matches) > 1:
            raise ValueError("单次只能选择一个 --preset")
        match = matches[0]
        preset = next((part for part in match.groups() if part is not None), "")
        cleaned = f"{text[: match.start()]} {text[match.end() :]}"
        return re.sub(r"\s{2,}", " ", cleaned).strip(), preset.strip()

    @staticmethod
    def _extract_command_text(message: str, fallback: str, command: str) -> str:
        """从完整消息中提取子指令后内容，兼容多词提示词。"""
        raw = (message or "").strip()
        if command in {"draw", "prompt"}:
            command_pattern = (
                rf"(?:anima\s+{re.escape(command)}|anima_{re.escape(command)})"
            )
        else:
            command_pattern = re.escape(command)
        match = re.match(
            rf"^[\s/!！。.]*{command_pattern}\s+(.+)$",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        return (fallback or "").strip()

    def _schedule_cleanup(self, image_paths: list[Path]) -> None:
        """在消息发送完成后延迟清理临时图片。"""

        async def cleanup() -> None:
            await asyncio.sleep(300)
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
                try:
                    image_path.parent.rmdir()
                except OSError:
                    pass

        task = asyncio.create_task(cleanup())
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def _schedule_self_reload(
        self,
        delay: float = 2.0,
        reason: str = "配置更新",
    ) -> Optional[asyncio.Task[Any]]:
        """延迟重载当前插件，让保存成功回复先完成发送。"""
        star_manager = getattr(self.context, "_star_manager", None)
        reload_plugin = getattr(star_manager, "reload", None)
        if not callable(reload_plugin):
            logger.warning(
                f"[{PLUGIN_NAME}] 无法自动重载：Context 未提供 StarManager.reload"
            )
            return None

        reason_text = reason.strip() or "配置更新"

        async def reload_later() -> None:
            try:
                await asyncio.sleep(max(0.0, delay))
                success, error = await reload_plugin(PLUGIN_NAME)
                if success:
                    logger.info(f"[{PLUGIN_NAME}] {reason_text}后自动重载成功")
                else:
                    logger.error(
                        f"[{PLUGIN_NAME}] {reason_text}后自动重载失败: "
                        f"{error or '未知错误'}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    f"[{PLUGIN_NAME}] {reason_text}后自动重载异常: {exc}",
                    exc_info=True,
                )

        task = asyncio.create_task(reload_later())
        self._self_reload_tasks.add(task)
        task.add_done_callback(self._self_reload_tasks.discard)
        return task

    async def terminate(self) -> None:
        """Always detach the WebUI log handler even if resource cleanup fails."""
        try:
            await self._terminate_resources()
        finally:
            self._log_console.close()
            if self._task_store is not None:
                self._task_store.close()

    async def _terminate_resources(self) -> None:
        """插件卸载时取消任务并释放网络和临时文件资源。"""
        if self._web_ui_start_task and not self._web_ui_start_task.done():
            self._web_ui_start_task.cancel()
            await asyncio.gather(
                self._web_ui_start_task,
                return_exceptions=True,
            )
        if self._web_ui is not None:
            await self._web_ui.close()

        async with self._jobs_lock:
            jobs = list(self._active_jobs.values())
            self._active_jobs.clear()
        for job in jobs:
            if job.task and not job.task.done():
                job.task.cancel()
        if jobs:
            await asyncio.gather(
                *(job.task for job in jobs if job.task), return_exceptions=True
            )

        background_runs = [
            task for task in self._background_task_runs.values() if not task.done()
        ]
        for task in background_runs:
            task.cancel()
        if background_runs:
            await asyncio.gather(*background_runs, return_exceptions=True)
        self._background_task_runs.clear()

        for task in list(self._cleanup_tasks):
            task.cancel()
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)

        current_task = asyncio.current_task()
        pending_reloads = [
            task
            for task in self._self_reload_tasks
            if task is not current_task and not task.done()
        ]
        for task in pending_reloads:
            task.cancel()
        if pending_reloads:
            await asyncio.gather(*pending_reloads, return_exceptions=True)
        for image_path in self._temp_dir.glob("*/*"):
            if image_path.is_file():
                image_path.unlink(missing_ok=True)
        for directory in self._temp_dir.glob("*"):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
        if self._client:
            await self._client.close()
        if self._lora_catalog:
            await self._lora_catalog.close()
        if self._lora_downloader:
            await self._lora_downloader.close()
        if self._unet_catalog:
            await self._unet_catalog.close()
        logger.info(f"[{PLUGIN_NAME}] 已安全卸载")
