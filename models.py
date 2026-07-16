"""
AstrBot Comfy Anima 插件 v1.0.0

功能描述：
- 定义插件配置、生成参数和任务数据模型

作者: Yen
版本: 1.4.0
日期: 2026-07-14
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from .constants import (
    DEFAULT_DIRECTOR_REFERENCE_FILE,
    DEFAULT_NEGATIVE_NODE_ID,
    DEFAULT_PREVIEW_OUTPUT_NODE_ID,
    DEFAULT_PRIMARY_SAMPLER_NODE_ID,
    DEFAULT_PRIMARY_SEED_NODE_ID,
    DEFAULT_PROMPT_NODE_ID,
    DEFAULT_RESOLUTION_NODE_ID,
    DEFAULT_SECONDARY_SEED_NODE_ID,
    DEFAULT_UPSCALE_OUTPUT_NODE_ID,
    DEFAULT_WORKFLOW_FILE,
    MAX_IMAGE_SIDE,
    MIN_IMAGE_SIDE,
)


def _as_bool(value: Any, default: bool) -> bool:
    """将配置值安全转换为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: Any, default: int, minimum: int = 0) -> int:
    """将配置值安全转换为有下限的整数。"""
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float, minimum: float = 0.0) -> float:
    """将配置值安全转换为有下限的浮点数。"""
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


def _as_string_list(value: Any, default: list[str]) -> list[str]:
    """将列表或逗号分隔字符串转换为字符串列表。"""
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or list(default)
    if isinstance(value, str):
        result = [item.strip() for item in value.split(",") if item.strip()]
        return result or list(default)
    return list(default)


def _as_mapping_list(value: Any) -> list[dict[str, Any]]:
    """保留 template_list 中的字典项并复制，避免修改原配置对象。"""
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _default_lora_presets() -> list[dict[str, Any]]:
    """返回此 Anima 工作流随包提供的默认风格栈。"""
    return [
        {
            "__template_key": "artist_style_combo",
            "name": "风格001",
            "loras": [
                "(画质)anima-highres-aesthetic-boost=0.5",
                "(美感细节)anima-rl-v0.1=0.4",
                "anima-base-1-masterpiece-v51=0.5",
                "748cm_v2_anima=0.3",
                "hanaru_epoch24=0.31",
                "nekoya_v1_epoch21=0.3",
                "real skin.baka.v1-000010=0.65",
                "(写真背景)anima3-photo-background-v3=0.3",
            ],
            "trigger_words": "",
            "description": "默认画质、美感、画师、皮肤与写真背景风格栈",
            "enabled": True,
        }
    ]


def _as_group_levels(value: Any) -> dict[str, str]:
    """解析群号到 none/lite/full 的映射，兼容旧字典与列表格式。"""
    result: dict[str, str] = {}
    if isinstance(value, Mapping):
        items = value.items()
    else:
        raw_items = value if isinstance(value, list) else []
        parsed_items: list[tuple[str, str]] = []
        for raw_item in raw_items:
            text = str(raw_item).strip()
            separator = "=" if "=" in text else ":" if ":" in text else ""
            if not separator:
                continue
            group_id, level = text.split(separator, 1)
            parsed_items.append((group_id, level))
        items = parsed_items
    for raw_group_id, raw_level in items:
        group_id = str(raw_group_id).strip()
        level = str(raw_level).strip().lower()
        if group_id and level in {"none", "lite", "full"}:
            result[group_id] = level
    return result


@dataclass(frozen=True)
class PluginSettings:
    """插件运行配置。"""

    comfyui_url: str = "http://127.0.0.1:8188"
    api_token: str = ""
    enable_web_ui: bool = False
    web_ui_host: str = "0.0.0.0"
    web_ui_port: int = 6198
    web_ui_username: str = "admin"
    web_ui_password: str = ""
    web_ui_session_ttl: int = 43200
    workflow_file: str = DEFAULT_WORKFLOW_FILE
    enable_prompt_llm: bool = True
    prompt_llm_provider_id: str = ""
    prompt_llm_timeout: int = 120
    prompt_llm_temperature: float = 0.3
    prompt_llm_max_tokens: int = 1000
    prompt_llm_fallback: bool = True
    show_llm_prompt: bool = False
    director_reference_file: str = DEFAULT_DIRECTOR_REFERENCE_FILE
    director_extra_instruction: str = ""
    enable_natural_draw: bool = True
    enable_llm_pic_trigger: bool = True
    auto_draw_system_prompt: str = ""
    max_auto_images_per_reply: int = 1
    workflow_dir: str = "workflow"
    enable_unet_switch: bool = True
    unet_catalog_url: str = ""
    unet_catalog_timeout: int = 20
    unet_lan_only: bool = True
    unet_loader_node_id: str = "429"
    unet_model_input_name: str = "unet_name"
    unet_model_name: str = ""
    whitelist_only: bool = False
    group_whitelist: list[str] = field(default_factory=list)
    global_lock: bool = False
    enable_lock_command: bool = True
    admin_ignore_cooldown: bool = True
    admin_ignore_whitelist: bool = True
    admin_ignore_blocklist: bool = False
    default_block_level: str = "lite"
    group_block_levels: dict[str, str] = field(default_factory=dict)
    forward_sender_name: str = "ComfyUI 绘图"
    enable_lora_tool: bool = True
    lora_catalog_url: str = ""
    enable_lora_manager: bool = True
    lora_manager_url: str = ""
    lora_manager_scan_on_refresh: bool = True
    lora_manager_scan_interval: int = 60
    lora_manager_scan_timeout: int = 180
    lora_manager_page_size: int = 100
    enable_lora_download: bool = True
    lora_download_timeout: int = 3600
    lora_metadata_timeout: int = 300
    lora_download_max_concurrent: int = 1
    lora_download_allowed_hosts: list[str] = field(
        default_factory=lambda: [
            "civitai.com",
            "www.civitai.com",
            "civitai.red",
            "www.civitai.red",
        ]
    )
    lora_lan_only: bool = True
    lora_catalog_timeout: int = 15
    lora_cache_ttl: int = 300
    lora_max_results: int = 50
    lora_alias_rules: list[str] = field(default_factory=list)
    lora_tool_max_steps: int = 4
    lora_loader_node_id: str = "462"
    dynamic_lora_mode: str = "append"
    max_dynamic_loras: int = 3
    max_preset_loras: int = 12
    max_total_dynamic_loras: int = 12
    default_style_preset: str = "风格001"
    auto_reload_after_style_save: bool = True
    lora_presets: list[dict[str, Any]] = field(default_factory=_default_lora_presets)
    strict_lora_validation: bool = True
    prompt_node_id: str = DEFAULT_PROMPT_NODE_ID
    negative_node_id: str = DEFAULT_NEGATIVE_NODE_ID
    primary_seed_node_id: str = DEFAULT_PRIMARY_SEED_NODE_ID
    secondary_seed_node_id: str = DEFAULT_SECONDARY_SEED_NODE_ID
    resolution_node_id: str = DEFAULT_RESOLUTION_NODE_ID
    default_width: int = 832
    default_height: int = 1216
    sampler_node_ids: list[str] = field(
        default_factory=lambda: [DEFAULT_PRIMARY_SAMPLER_NODE_ID]
    )
    output_node_ids: list[str] = field(
        default_factory=lambda: [
            DEFAULT_UPSCALE_OUTPUT_NODE_ID,
            DEFAULT_PREVIEW_OUTPUT_NODE_ID,
        ]
    )
    upscale_output_node_id: str = DEFAULT_UPSCALE_OUTPUT_NODE_ID
    enable_upscale: bool = True
    send_generation_notice: bool = True
    allow_global_interrupt: bool = False
    max_concurrent_jobs: int = 1
    user_cooldown: int = 30
    request_timeout: int = 30
    generation_timeout: int = 1200
    poll_interval: float = 2.0
    max_prompt_length: int = 2000
    max_image_size_mb: int = 50

    @classmethod
    def from_mapping(cls, config: Optional[Mapping[str, Any]]) -> "PluginSettings":
        """从 AstrBot 配置对象创建配置实例。

        Args:
            config: 字典兼容的 AstrBot 插件配置。

        Returns:
            经过类型清洗的插件配置。
        """
        data = config or {}
        return cls(
            comfyui_url=str(data.get("comfyui_url", cls.comfyui_url)).strip(),
            api_token=str(data.get("api_token", "")).strip(),
            enable_web_ui=_as_bool(data.get("enable_web_ui"), False),
            web_ui_host=(str(data.get("web_ui_host", "0.0.0.0")).strip() or "0.0.0.0"),
            web_ui_port=min(
                65535,
                _as_int(data.get("web_ui_port"), 6198, 1024),
            ),
            web_ui_username=(
                str(data.get("web_ui_username", "admin")).strip() or "admin"
            ),
            web_ui_password=str(data.get("web_ui_password", "")),
            web_ui_session_ttl=min(
                86400,
                _as_int(data.get("web_ui_session_ttl"), 43200, 300),
            ),
            workflow_file=str(data.get("workflow_file", DEFAULT_WORKFLOW_FILE)).strip(),
            enable_prompt_llm=_as_bool(data.get("enable_prompt_llm"), True),
            prompt_llm_provider_id=str(data.get("prompt_llm_provider_id", "")).strip(),
            prompt_llm_timeout=_as_int(data.get("prompt_llm_timeout"), 120, 10),
            prompt_llm_temperature=_as_float(data.get("prompt_llm_temperature"), 0.3),
            prompt_llm_max_tokens=_as_int(data.get("prompt_llm_max_tokens"), 1000, 128),
            prompt_llm_fallback=_as_bool(data.get("prompt_llm_fallback"), True),
            show_llm_prompt=_as_bool(data.get("show_llm_prompt"), False),
            director_reference_file=str(
                data.get("director_reference_file", DEFAULT_DIRECTOR_REFERENCE_FILE)
            ).strip(),
            director_extra_instruction=str(
                data.get("director_extra_instruction", "")
            ).strip(),
            enable_natural_draw=_as_bool(data.get("enable_natural_draw"), True),
            enable_llm_pic_trigger=_as_bool(data.get("enable_llm_pic_trigger"), True),
            auto_draw_system_prompt=str(
                data.get("auto_draw_system_prompt", "")
            ).strip(),
            max_auto_images_per_reply=_as_int(
                data.get("max_auto_images_per_reply"), 1, 1
            ),
            workflow_dir=str(data.get("workflow_dir", "workflow")).strip()
            or "workflow",
            enable_unet_switch=_as_bool(data.get("enable_unet_switch"), True),
            unet_catalog_url=str(data.get("unet_catalog_url", "")).strip(),
            unet_catalog_timeout=_as_int(data.get("unet_catalog_timeout"), 20, 1),
            unet_lan_only=_as_bool(data.get("unet_lan_only"), True),
            unet_loader_node_id=str(data.get("unet_loader_node_id", "429")).strip()
            or "429",
            unet_model_input_name=str(
                data.get("unet_model_input_name", "unet_name")
            ).strip()
            or "unet_name",
            unet_model_name=str(data.get("unet_model_name", "")).strip(),
            whitelist_only=_as_bool(data.get("whitelist_only"), False),
            group_whitelist=(
                _as_string_list(data.get("group_whitelist"), [])
                if data.get("group_whitelist")
                else []
            ),
            global_lock=_as_bool(data.get("global_lock"), False),
            enable_lock_command=_as_bool(data.get("enable_lock_command"), True),
            admin_ignore_cooldown=_as_bool(data.get("admin_ignore_cooldown"), True),
            admin_ignore_whitelist=_as_bool(data.get("admin_ignore_whitelist"), True),
            admin_ignore_blocklist=_as_bool(data.get("admin_ignore_blocklist"), False),
            default_block_level=(
                str(data.get("default_block_level", "lite")).strip().lower()
                if str(data.get("default_block_level", "lite")).strip().lower()
                in {"none", "lite", "full"}
                else "lite"
            ),
            group_block_levels=_as_group_levels(data.get("group_block_levels", [])),
            forward_sender_name=(
                str(data.get("forward_sender_name", "ComfyUI 绘图")).strip()
                or "ComfyUI 绘图"
            ),
            enable_lora_tool=_as_bool(data.get("enable_lora_tool"), True),
            lora_catalog_url=str(data.get("lora_catalog_url", "")).strip(),
            enable_lora_manager=_as_bool(data.get("enable_lora_manager"), True),
            lora_manager_url=str(data.get("lora_manager_url", "")).strip(),
            lora_manager_scan_on_refresh=_as_bool(
                data.get("lora_manager_scan_on_refresh"), True
            ),
            lora_manager_scan_interval=_as_int(
                data.get("lora_manager_scan_interval"), 60, 0
            ),
            lora_manager_scan_timeout=_as_int(
                data.get("lora_manager_scan_timeout"), 180, 10
            ),
            lora_manager_page_size=_as_int(data.get("lora_manager_page_size"), 100, 10),
            enable_lora_download=_as_bool(data.get("enable_lora_download"), True),
            lora_download_timeout=_as_int(data.get("lora_download_timeout"), 3600, 60),
            lora_metadata_timeout=_as_int(data.get("lora_metadata_timeout"), 300, 10),
            lora_download_max_concurrent=_as_int(
                data.get("lora_download_max_concurrent"), 1, 1
            ),
            lora_download_allowed_hosts=_as_string_list(
                data.get("lora_download_allowed_hosts"),
                [
                    "civitai.com",
                    "www.civitai.com",
                    "civitai.red",
                    "www.civitai.red",
                ],
            ),
            lora_lan_only=_as_bool(data.get("lora_lan_only"), True),
            lora_catalog_timeout=_as_int(data.get("lora_catalog_timeout"), 15, 1),
            lora_cache_ttl=_as_int(data.get("lora_cache_ttl"), 300, 0),
            lora_max_results=_as_int(data.get("lora_max_results"), 50, 1),
            lora_alias_rules=_as_string_list(
                data.get("lora_alias_rules"),
                [],
            ),
            lora_tool_max_steps=_as_int(data.get("lora_tool_max_steps"), 4, 1),
            lora_loader_node_id=str(data.get("lora_loader_node_id", "462")).strip()
            or "462",
            dynamic_lora_mode=(
                str(data.get("dynamic_lora_mode", "append")).strip().lower()
                if str(data.get("dynamic_lora_mode", "append")).strip().lower()
                in {"append", "replace"}
                else "append"
            ),
            max_dynamic_loras=_as_int(data.get("max_dynamic_loras"), 3, 0),
            max_preset_loras=_as_int(data.get("max_preset_loras"), 12, 1),
            max_total_dynamic_loras=_as_int(data.get("max_total_dynamic_loras"), 12, 1),
            default_style_preset=str(
                data.get("default_style_preset", "风格001")
            ).strip(),
            auto_reload_after_style_save=_as_bool(
                data.get("auto_reload_after_style_save"), True
            ),
            lora_presets=_as_mapping_list(
                data.get("lora_presets", _default_lora_presets())
            ),
            strict_lora_validation=_as_bool(data.get("strict_lora_validation"), True),
            prompt_node_id=str(
                data.get("prompt_node_id", DEFAULT_PROMPT_NODE_ID)
            ).strip(),
            negative_node_id=str(
                data.get("negative_node_id", DEFAULT_NEGATIVE_NODE_ID)
            ).strip(),
            primary_seed_node_id=str(
                data.get("primary_seed_node_id", DEFAULT_PRIMARY_SEED_NODE_ID)
            ).strip(),
            secondary_seed_node_id=str(
                data.get("secondary_seed_node_id", DEFAULT_SECONDARY_SEED_NODE_ID)
            ).strip(),
            resolution_node_id=str(
                data.get("resolution_node_id", DEFAULT_RESOLUTION_NODE_ID)
            ).strip(),
            default_width=min(
                MAX_IMAGE_SIDE,
                _as_int(data.get("default_width"), 832, MIN_IMAGE_SIDE),
            ),
            default_height=min(
                MAX_IMAGE_SIDE,
                _as_int(data.get("default_height"), 1216, MIN_IMAGE_SIDE),
            ),
            sampler_node_ids=_as_string_list(
                data.get("sampler_node_ids"), [DEFAULT_PRIMARY_SAMPLER_NODE_ID]
            ),
            output_node_ids=_as_string_list(
                data.get("output_node_ids"),
                [DEFAULT_UPSCALE_OUTPUT_NODE_ID, DEFAULT_PREVIEW_OUTPUT_NODE_ID],
            ),
            upscale_output_node_id=str(
                data.get("upscale_output_node_id", DEFAULT_UPSCALE_OUTPUT_NODE_ID)
            ).strip(),
            enable_upscale=_as_bool(data.get("enable_upscale"), True),
            send_generation_notice=_as_bool(data.get("send_generation_notice"), True),
            allow_global_interrupt=_as_bool(data.get("allow_global_interrupt"), False),
            max_concurrent_jobs=_as_int(data.get("max_concurrent_jobs"), 1, 1),
            user_cooldown=_as_int(data.get("user_cooldown"), 30),
            request_timeout=_as_int(data.get("request_timeout"), 30, 1),
            generation_timeout=_as_int(data.get("generation_timeout"), 1200, 10),
            poll_interval=_as_float(data.get("poll_interval"), 2.0, 0.25),
            max_prompt_length=_as_int(data.get("max_prompt_length"), 2000, 1),
            max_image_size_mb=_as_int(data.get("max_image_size_mb"), 50, 1),
        )

    def resolve_workflow_path(self, plugin_dir: Path) -> Path:
        """解析并返回工作流路径。"""
        path = Path(self.workflow_file).expanduser()
        return path if path.is_absolute() else plugin_dir / path

    def resolve_director_reference_path(self, plugin_dir: Path) -> Path:
        """解析并返回分镜导演参考提示词路径。"""
        path = Path(self.director_reference_file).expanduser()
        return path if path.is_absolute() else plugin_dir / path


@dataclass(frozen=True)
class GenerationOptions:
    """单次生成使用的动态参数。"""

    prompt: str
    negative_prompt: str = ""
    seed: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    steps: Optional[int] = None
    cfg: Optional[float] = None
    enable_upscale: Optional[bool] = None
    use_prompt_llm: Optional[bool] = None
    dynamic_loras: tuple["LoraSelection", ...] = ()
    lora_preset: str = ""
    lora_injection_mode: Optional[str] = None


@dataclass(frozen=True)
class LoraSelection:
    """LLM 或高级用户为单次任务选择的 LoRA。"""

    name: str
    strength: float = 0.8


@dataclass(frozen=True)
class ImageReference:
    """ComfyUI 历史记录中的图片引用。"""

    filename: str
    subfolder: str = ""
    image_type: str = "output"
    node_id: str = ""


@dataclass
class GenerationJob:
    """正在执行或排队中的生成任务。"""

    user_id: str
    prompt_preview: str
    created_at: float
    task: Any = None
    prompt_id: Optional[str] = None
    state: str = "queued"
