"""AstrBot native plugin-page bridge for the management dashboard."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import unquote

from ..constants import PLUGIN_NAME
from .task_store import TASK_STATUSES


logger = logging.getLogger("astrbot")


class PluginPageActionError(RuntimeError):
    """Safe, user-facing native page request error."""


class PluginPageApi:
    """Expose existing management operations through AstrBot's authenticated bridge."""

    ROUTE = f"/{PLUGIN_NAME}/api/gateway"
    _ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})

    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def register(self, context: Any) -> bool:
        register = getattr(context, "register_web_api", None)
        if not callable(register):
            return False
        try:
            register(
                self.ROUTE,
                self.handle,
                ["POST"],
                "Comfy Anima native management page gateway",
            )
        except Exception as exc:
            logger.warning(
                "[%s] Native plugin-page API registration failed: %s",
                PLUGIN_NAME,
                type(exc).__name__,
            )
            return False
        return True

    async def handle(self):
        """Read the current AstrBot plugin request and return a safe response."""

        from astrbot.api.web import error_response, json_response, request

        from .web_ui import WebUiActionError

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("JSON 顶层必须是对象", status_code=400)
        try:
            result = await self.dispatch(payload)
        except (PluginPageActionError, WebUiActionError) as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.error(
                "[%s] Native plugin-page operation failed: %s",
                PLUGIN_NAME,
                type(exc).__name__,
                exc_info=True,
            )
            return error_response("操作失败，请查看 AstrBot 日志", status_code=500)
        return json_response({"status": "ok", "data": result})

    async def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        method = str(envelope.get("method") or "GET").strip().upper()
        if method not in self._ALLOWED_METHODS:
            raise PluginPageActionError("不支持的请求方法")
        path = self._normalize_api_path(envelope.get("path"))
        query = self._normalize_query(envelope.get("query"))
        body = envelope.get("body") or {}
        if not isinstance(body, dict):
            raise PluginPageActionError("请求体必须是 JSON 对象")

        if method == "GET" and path == "/api/bootstrap":
            return await self._controller.web_ui_bootstrap()
        if method == "GET" and path == "/api/providers":
            return await self._controller.web_ui_list_providers()
        if method == "PUT" and path == "/api/settings":
            return await self._controller.web_ui_save_settings(
                self._validated_settings(body)
            )

        if method == "GET" and path == "/api/loras":
            return await self._controller.web_ui_search_loras(
                self._query_text(query, "q", 1000),
                self._query_int(query, "limit", 50, minimum=1, maximum=1000),
            )
        if method == "POST" and path == "/api/loras/refresh":
            return await self._controller.web_ui_refresh_loras()
        if method == "POST" and path == "/api/loras/download":
            return await self._controller.web_ui_download_lora(
                str(body.get("url") or "")
            )
        if method == "POST" and path in {
            "/api/loras/metadata",
            "/api/lora/metadata-fetch",
        }:
            return await self._controller.web_ui_fetch_lora_metadata(dict(body))
        if method == "GET" and path == "/api/loras/detail":
            name = self._query_text(query, "name", 500)
            if not name:
                raise PluginPageActionError("LoRA 名称无效")
            return await self._controller.web_ui_get_lora_detail(name)
        if method == "POST" and path == "/api/loras/delete":
            return await self._controller.web_ui_delete_lora(dict(body))
        if method == "PUT" and path == "/api/loras/semantic":
            return await self._controller.web_ui_save_lora_semantic(dict(body))
        if method == "GET" and path in {
            "/api/loras/archive",
            "/api/lora/archive/status",
            "/api/lora/archive/index",
        }:
            archive = await self._controller.web_ui_get_lora_archive()
            if path.endswith("/status"):
                return dict(archive.get("status") or {})
            if path.endswith("/index"):
                return {"items": list(archive.get("items") or [])}
            return archive
        if method == "POST" and path in {
            "/api/loras/archive",
            "/api/lora/archive",
            "/api/lora/archive/run",
        }:
            return await self._controller.web_ui_archive_loras(dict(body))

        if method == "GET" and path == "/api/presets":
            return await self._controller.web_ui_list_presets()
        if method == "POST" and path == "/api/presets":
            return await self._controller.web_ui_save_preset(dict(body))
        if method == "DELETE" and path.startswith("/api/presets/"):
            identifier = self._path_tail(path, "/api/presets/", 500)
            return await self._controller.web_ui_delete_preset(identifier)

        if method == "GET" and path == "/api/workflows":
            return await self._controller.web_ui_list_workflows()
        if method == "POST" and path == "/api/workflows/select":
            return await self._controller.web_ui_select_workflow(
                str(body.get("identifier") or body.get("filename") or "")
            )

        if method == "GET" and path == "/api/unet":
            return await self._controller.web_ui_list_unet()
        if method == "POST" and path == "/api/unet/select":
            return await self._controller.web_ui_select_unet(
                str(body.get("identifier") or "")
            )
        if method == "POST" and path == "/api/unet/delete":
            return await self._controller.web_ui_delete_unet(dict(body))

        if method == "GET" and path == "/api/config-profiles":
            return await self._controller.web_ui_list_config_profiles()
        if method == "POST" and path == "/api/config-profiles":
            return await self._controller.web_ui_save_config_profile(dict(body))
        if method == "POST" and path == "/api/config-profiles/switch":
            return await self._controller.web_ui_switch_config_profile(
                str(body.get("identifier") or body.get("name") or "")
            )
        if method == "POST" and path.startswith("/api/config-profiles/") and path.endswith("/activate"):
            identifier = path[len("/api/config-profiles/") : -len("/activate")]
            return await self._controller.web_ui_switch_config_profile(
                self._path_identifier(identifier, 500)
            )
        if method == "DELETE" and path.startswith("/api/config-profiles/"):
            identifier = self._path_tail(path, "/api/config-profiles/", 500)
            return await self._controller.web_ui_delete_config_profile(identifier)

        if method == "GET" and path == "/api/logs":
            return await self._controller.web_ui_get_logs(
                self._query_int(query, "after", 0, minimum=0, maximum=2**63 - 1),
                self._query_int(query, "limit", 500, minimum=1, maximum=1000),
            )
        if method == "DELETE" and path == "/api/logs":
            return await self._controller.web_ui_clear_logs()

        if method == "GET" and path == "/api/tasks":
            status = self._query_text(query, "status", 100).casefold()
            if status and status not in TASK_STATUSES:
                raise PluginPageActionError("任务状态不受支持")
            return await self._controller.web_ui_list_tasks(
                self._query_int(query, "limit", 50, minimum=1, maximum=500),
                self._query_text(query, "type", 100),
                status,
            )
        if path.startswith("/api/tasks/"):
            suffix = path[len("/api/tasks/") :]
            if suffix.endswith("/events") and method == "GET":
                run_id = self._validated_run_id(suffix[: -len("/events")])
                return await self._controller.web_ui_get_task_events(
                    run_id,
                    self._query_int(
                        query,
                        "after",
                        0,
                        minimum=0,
                        maximum=2**31 - 1,
                    ),
                    self._query_int(
                        query,
                        "limit",
                        500,
                        minimum=1,
                        maximum=2000,
                    ),
                )
            if suffix.endswith("/cancel") and method == "POST":
                run_id = self._validated_run_id(suffix[: -len("/cancel")])
                return await self._controller.web_ui_cancel_task(run_id)
            if method == "GET":
                return await self._controller.web_ui_get_task(
                    self._validated_run_id(suffix)
                )

        if method == "POST" and path == "/api/logout":
            return {"message": "原生插件页由 AstrBot Dashboard 管理登录状态"}
        raise PluginPageActionError("不支持的原生插件页操作")

    @staticmethod
    def _normalize_api_path(raw_path: Any) -> str:
        path = str(raw_path or "").strip()
        if (
            not path.startswith("/api/")
            or len(path) > 2048
            or "\\" in path
            or "?" in path
            or "#" in path
        ):
            raise PluginPageActionError("插件页 API 路径无效")
        decoded: list[str] = []
        for raw_segment in path.split("/")[1:]:
            segment = unquote(raw_segment)
            if (
                not segment
                or segment in {".", ".."}
                or "/" in segment
                or "\\" in segment
                or len(segment) > 500
            ):
                raise PluginPageActionError("插件页 API 路径无效")
            decoded.append(segment)
        return "/" + "/".join(decoded)

    @staticmethod
    def _normalize_query(raw_query: Any) -> dict[str, str]:
        if raw_query is None:
            return {}
        if not isinstance(raw_query, Mapping) or len(raw_query) > 32:
            raise PluginPageActionError("查询参数无效")
        result: dict[str, str] = {}
        for raw_key, raw_value in raw_query.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()
            if not key or len(key) > 100 or len(value) > 2000:
                raise PluginPageActionError("查询参数无效")
            result[key] = value
        return result

    @staticmethod
    def _query_text(query: Mapping[str, str], key: str, limit: int) -> str:
        value = str(query.get(key) or "").strip()
        if len(value) > limit:
            raise PluginPageActionError("查询参数过长")
        return value

    @staticmethod
    def _query_int(
        query: Mapping[str, str],
        key: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = query.get(key)
        if raw_value in (None, ""):
            return default
        try:
            value = int(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise PluginPageActionError("查询参数必须是整数") from exc
        if value < minimum or value > maximum:
            raise PluginPageActionError("查询参数超出允许范围")
        return value

    @staticmethod
    def _validated_settings(body: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(body)
        if "sampler_steps_override" not in payload:
            return payload
        raw_value = payload["sampler_steps_override"]
        if isinstance(raw_value, bool):
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数") from exc
        if str(raw_value).strip() != str(value) or not 0 <= value <= 100:
            raise PluginPageActionError("采样步数覆盖必须是 0–100 的整数")
        payload["sampler_steps_override"] = value
        return payload

    @staticmethod
    def _path_identifier(identifier: str, limit: int) -> str:
        value = identifier.strip()
        if not value or len(value) > limit or "/" in value or "\\" in value:
            raise PluginPageActionError("资源标识无效")
        return value

    @classmethod
    def _path_tail(cls, path: str, prefix: str, limit: int) -> str:
        return cls._path_identifier(path[len(prefix) :], limit)

    @staticmethod
    def _validated_run_id(run_id: str) -> str:
        value = run_id.strip()
        if (
            not value
            or len(value) > 128
            or not all(character.isalnum() or character in "-_" for character in value)
        ):
            raise PluginPageActionError("任务 ID 格式无效")
        return value


__all__ = ["PluginPageActionError", "PluginPageApi"]
