"""Authenticated LAN Web UI for the Comfy Anima plugin."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Protocol

from aiohttp import web

from astrbot.api import logger

from ..constants import PLUGIN_NAME
from ..models import PluginSettings
from .task_store import TASK_STATUSES


SESSION_COOKIE = "comfy_anima_session"
_request_key_factory = getattr(web, "RequestKey", None)
if _request_key_factory is None:
    REQUEST_SESSION_KEY = "comfy_anima_session_token"
    REQUEST_CSRF_KEY = "comfy_anima_csrf_token"
else:
    REQUEST_SESSION_KEY = _request_key_factory(
        "comfy_anima_session_token",
        str,
    )
    REQUEST_CSRF_KEY = _request_key_factory(
        "comfy_anima_csrf_token",
        str,
    )
MAX_LOGIN_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 60
ASSET_CONTENT_TYPES = {
    "app.css": "text/css",
    "app.js": "application/javascript",
    "theme.js": "application/javascript",
    "login.js": "application/javascript",
}


class WebUiError(RuntimeError):
    """Web UI configuration or startup failure."""


class WebUiActionError(RuntimeError):
    """A safe, user-facing Web UI operation error."""


class WebUiController(Protocol):
    """Operations exposed by the plugin to the HTTP layer."""

    async def web_ui_bootstrap(self) -> dict[str, Any]: ...

    async def web_ui_save_settings(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def web_ui_list_providers(self) -> dict[str, Any]: ...

    async def web_ui_search_loras(self, keyword: str, limit: int) -> dict[str, Any]: ...

    async def web_ui_refresh_loras(self) -> dict[str, Any]: ...

    async def web_ui_download_lora(self, url: str) -> dict[str, Any]: ...

    async def web_ui_fetch_lora_metadata(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def web_ui_get_lora_detail(self, name: str) -> dict[str, Any]: ...

    async def web_ui_save_lora_semantic(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def web_ui_get_lora_archive(self) -> dict[str, Any]: ...

    async def web_ui_archive_loras(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def web_ui_list_presets(self) -> dict[str, Any]: ...

    async def web_ui_save_preset(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def web_ui_delete_preset(self, identifier: str) -> dict[str, Any]: ...

    async def web_ui_list_unet(self) -> dict[str, Any]: ...

    async def web_ui_select_unet(self, identifier: str) -> dict[str, Any]: ...

    async def web_ui_list_config_profiles(self) -> dict[str, Any]: ...

    async def web_ui_save_config_profile(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def web_ui_switch_config_profile(self, identifier: str) -> dict[str, Any]: ...

    async def web_ui_delete_config_profile(self, identifier: str) -> dict[str, Any]: ...

    async def web_ui_get_logs(
        self,
        after_id: int,
        limit: int,
    ) -> dict[str, Any]: ...

    async def web_ui_clear_logs(self) -> dict[str, Any]: ...

    async def web_ui_list_tasks(
        self,
        limit: int,
        task_type: str,
        status: str,
    ) -> dict[str, Any]: ...

    async def web_ui_get_task(self, run_id: str) -> dict[str, Any]: ...

    async def web_ui_get_task_events(
        self,
        run_id: str,
        after_seq: int,
        limit: int,
    ) -> dict[str, Any]: ...

    async def web_ui_cancel_task(self, run_id: str) -> dict[str, Any]: ...


class WebUiService:
    """Serve the plugin management UI on a dedicated configurable port."""

    def __init__(
        self,
        settings: PluginSettings,
        plugin_dir: Path,
        controller: WebUiController,
    ) -> None:
        self._settings = settings
        self._plugin_dir = plugin_dir
        self._controller = controller
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._sessions: dict[str, tuple[float, str]] = {}
        self._login_attempts: dict[str, deque[float]] = defaultdict(deque)

    @property
    def address(self) -> str:
        return f"http://{self._settings.web_ui_host}:{self._settings.web_ui_port}"

    def create_app(self) -> web.Application:
        app = web.Application(
            middlewares=[self._security_headers, self._authenticate],
            client_max_size=1024 * 1024,
        )
        app.add_routes(
            [
                web.get("/", self._index),
                web.get("/login", self._login_page),
                web.get("/favicon.ico", self._favicon),
                web.get("/assets/{name}", self._asset),
                web.post("/api/login", self._login),
                web.post("/api/logout", self._logout),
                web.get("/api/bootstrap", self._bootstrap),
                web.get("/api/providers", self._list_providers),
                web.put("/api/settings", self._save_settings),
                web.get("/api/loras", self._search_loras),
                web.post("/api/loras/refresh", self._refresh_loras),
                web.post("/api/loras/download", self._download_lora),
                web.post("/api/loras/metadata", self._fetch_lora_metadata),
                web.post("/api/lora/metadata-fetch", self._fetch_lora_metadata),
                web.get("/api/loras/detail", self._get_lora_detail),
                web.put("/api/loras/semantic", self._save_lora_semantic),
                web.get("/api/loras/archive", self._get_lora_archive),
                web.post("/api/loras/archive", self._archive_loras),
                web.post("/api/lora/archive", self._archive_loras),
                web.get("/api/lora/archive/status", self._get_lora_archive_status),
                web.get("/api/lora/archive/index", self._get_lora_archive_index),
                web.post("/api/lora/archive/run", self._archive_loras),
                web.get("/api/presets", self._list_presets),
                web.post("/api/presets", self._save_preset),
                web.delete(
                    "/api/presets/{identifier}",
                    self._delete_preset,
                ),
                web.get("/api/unet", self._list_unet),
                web.post("/api/unet/select", self._select_unet),
                web.get("/api/config-profiles", self._list_config_profiles),
                web.post("/api/config-profiles", self._save_config_profile),
                web.post(
                    "/api/config-profiles/switch",
                    self._switch_config_profile,
                ),
                web.post(
                    "/api/config-profiles/{identifier}/activate",
                    self._activate_config_profile,
                ),
                web.delete(
                    "/api/config-profiles/{identifier}",
                    self._delete_config_profile,
                ),
                web.get("/api/logs", self._get_logs),
                web.delete("/api/logs", self._clear_logs),
                web.get("/api/tasks", self._list_tasks),
                web.get("/api/tasks/{run_id}", self._get_task),
                web.get(
                    "/api/tasks/{run_id}/events",
                    self._get_task_events,
                ),
                web.post(
                    "/api/tasks/{run_id}/cancel",
                    self._cancel_task,
                ),
            ]
        )
        return app

    async def start(self) -> None:
        self.validate()
        if self._runner is not None:
            return
        runner = web.AppRunner(self.create_app(), access_log=None)
        await runner.setup()
        site = web.TCPSite(
            runner,
            host=self._settings.web_ui_host,
            port=self._settings.web_ui_port,
        )
        try:
            await site.start()
        except Exception:
            await runner.cleanup()
            raise
        self._runner = runner
        self._site = site
        logger.info(f"[{PLUGIN_NAME}] Web UI started at {self.address}")

    async def close(self) -> None:
        self._sessions.clear()
        self._login_attempts.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    def validate(self) -> None:
        host = self._settings.web_ui_host.strip()
        if host != "0.0.0.0":
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise WebUiError(
                    "Web UI host must be 0.0.0.0 or a LAN IP address"
                ) from exc
            if not (address.is_private or address.is_loopback or address.is_link_local):
                raise WebUiError("Web UI may only bind to a private LAN address")
        if not self._settings.web_ui_username.strip():
            raise WebUiError("Web UI username cannot be empty")
        if len(self._settings.web_ui_password) < 8:
            raise WebUiError(
                "Web UI password must contain at least 8 characters before enabling it"
            )
        asset_dir = self._plugin_dir / "web"
        for filename in ("index.html", "login.html", *ASSET_CONTENT_TYPES):
            if not (asset_dir / filename).is_file():
                raise WebUiError(f"Web UI asset is missing: {filename}")

    @web.middleware
    async def _security_headers(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.StreamResponse:
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @web.middleware
    async def _authenticate(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.StreamResponse:
        path = request.path
        if path in {"/login", "/api/login", "/favicon.ico"} or path.startswith(
            "/assets/"
        ):
            return await handler(request)

        session = self._read_session(request)
        if session is None:
            if path.startswith("/api/"):
                return self._json_error("登录已失效，请重新登录", status=401)
            raise web.HTTPFound("/login")

        token, csrf = session
        request[REQUEST_SESSION_KEY] = token
        request[REQUEST_CSRF_KEY] = csrf
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(supplied, csrf):
                return self._json_error("安全校验失败，请刷新页面后重试", status=403)
        return await handler(request)

    def _read_session(self, request: web.Request) -> tuple[str, str] | None:
        now = time.monotonic()
        token = request.cookies.get(SESSION_COOKIE, "")
        record = self._sessions.get(token)
        if record is None:
            return None
        expires_at, csrf = record
        if expires_at <= now:
            self._sessions.pop(token, None)
            return None
        self._sessions[token] = (
            now + self._settings.web_ui_session_ttl,
            csrf,
        )
        return token, csrf

    def _asset_path(self, filename: str) -> Path:
        return self._plugin_dir / "web" / filename

    async def _index(self, _request: web.Request) -> web.FileResponse:
        return web.FileResponse(self._asset_path("index.html"))

    async def _login_page(self, request: web.Request) -> web.StreamResponse:
        if self._read_session(request) is not None:
            raise web.HTTPFound("/")
        return web.FileResponse(self._asset_path("login.html"))

    async def _favicon(self, _request: web.Request) -> web.Response:
        return web.Response(status=204)

    async def _asset(self, request: web.Request) -> web.StreamResponse:
        filename = request.match_info["name"]
        content_type = ASSET_CONTENT_TYPES.get(filename)
        if content_type is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            self._asset_path(filename),
            headers={"Content-Type": f"{content_type}; charset=utf-8"},
        )

    async def _login(self, request: web.Request) -> web.Response:
        remote = request.remote or "unknown"
        if self._login_is_limited(remote):
            return self._json_error("登录尝试过多，请稍后再试", status=429)
        payload = await self._read_json(request)
        username = str(payload.get("username") or "")
        password = str(payload.get("password") or "")
        valid = hmac.compare_digest(username, self._settings.web_ui_username)
        valid = valid and hmac.compare_digest(
            password,
            self._settings.web_ui_password,
        )
        if not valid:
            self._login_attempts[remote].append(time.monotonic())
            return self._json_error("用户名或密码错误", status=401)

        self._login_attempts.pop(remote, None)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self._sessions[token] = (
            time.monotonic() + self._settings.web_ui_session_ttl,
            csrf,
        )
        response = web.json_response({"ok": True})
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=self._settings.web_ui_session_ttl,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return response

    def _login_is_limited(self, remote: str) -> bool:
        attempts = self._login_attempts[remote]
        cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return len(attempts) >= MAX_LOGIN_ATTEMPTS

    async def _logout(self, request: web.Request) -> web.Response:
        token = request.get(REQUEST_SESSION_KEY, "")
        self._sessions.pop(token, None)
        response = web.json_response({"ok": True})
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def _bootstrap(self, request: web.Request) -> web.Response:
        payload = await self._controller.web_ui_bootstrap()
        payload["csrf_token"] = request[REQUEST_CSRF_KEY]
        return web.json_response({"ok": True, "data": payload})

    async def _save_settings(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_save_settings(await self._read_json(request))
        )

    async def _list_providers(self, _request: web.Request) -> web.Response:
        return await self._controller_response(self._controller.web_ui_list_providers())

    async def _search_loras(self, request: web.Request) -> web.Response:
        keyword = request.query.get("q", "").strip()
        try:
            limit = min(1000, max(1, int(request.query.get("limit", "50"))))
        except ValueError:
            return self._json_error("LoRA 数量限制必须是整数", status=400)
        return await self._controller_response(
            self._controller.web_ui_search_loras(keyword, limit)
        )

    async def _refresh_loras(self, _request: web.Request) -> web.Response:
        return await self._controller_response(self._controller.web_ui_refresh_loras())

    async def _download_lora(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        return await self._controller_response(
            self._controller.web_ui_download_lora(str(payload.get("url") or ""))
        )

    async def _fetch_lora_metadata(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_fetch_lora_metadata(
                await self._read_json(request)
            )
        )

    async def _get_lora_detail(self, request: web.Request) -> web.Response:
        name = request.query.get("name", "").strip()
        if not name or len(name) > 500:
            return self._json_error("LoRA 名称无效", status=400)
        return await self._controller_response(
            self._controller.web_ui_get_lora_detail(name)
        )

    async def _save_lora_semantic(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_save_lora_semantic(
                await self._read_json(request)
            )
        )

    async def _get_lora_archive(self, _request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_get_lora_archive()
        )

    async def _get_lora_archive_status(self, _request: web.Request) -> web.Response:
        async def status_only() -> dict[str, Any]:
            result = await self._controller.web_ui_get_lora_archive()
            return dict(result.get("status") or {})

        return await self._controller_response(status_only())

    async def _get_lora_archive_index(self, _request: web.Request) -> web.Response:
        async def index_only() -> dict[str, Any]:
            result = await self._controller.web_ui_get_lora_archive()
            return {"items": list(result.get("items") or [])}

        return await self._controller_response(index_only())

    async def _archive_loras(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_archive_loras(await self._read_json(request))
        )

    async def _list_presets(self, _request: web.Request) -> web.Response:
        return await self._controller_response(self._controller.web_ui_list_presets())

    async def _save_preset(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_save_preset(await self._read_json(request))
        )

    async def _delete_preset(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_delete_preset(request.match_info["identifier"])
        )

    async def _list_unet(self, _request: web.Request) -> web.Response:
        return await self._controller_response(self._controller.web_ui_list_unet())

    async def _select_unet(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        return await self._controller_response(
            self._controller.web_ui_select_unet(str(payload.get("identifier") or ""))
        )

    async def _list_config_profiles(self, _request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_list_config_profiles()
        )

    async def _save_config_profile(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_save_config_profile(await self._read_json(request))
        )

    async def _switch_config_profile(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        return await self._controller_response(
            self._controller.web_ui_switch_config_profile(
                str(payload.get("identifier") or payload.get("name") or "")
            )
        )

    async def _activate_config_profile(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_switch_config_profile(
                request.match_info["identifier"]
            )
        )

    async def _delete_config_profile(self, request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_delete_config_profile(
                request.match_info["identifier"]
            )
        )

    async def _get_logs(self, request: web.Request) -> web.Response:
        try:
            after_id = max(0, int(request.query.get("after", "0")))
            limit = min(1000, max(1, int(request.query.get("limit", "500"))))
        except ValueError:
            return self._json_error("日志游标和数量限制必须是整数", status=400)
        return await self._controller_response(
            self._controller.web_ui_get_logs(after_id, limit)
        )

    async def _clear_logs(self, _request: web.Request) -> web.Response:
        return await self._controller_response(
            self._controller.web_ui_clear_logs()
        )

    async def _list_tasks(self, request: web.Request) -> web.Response:
        try:
            limit = min(500, max(1, int(request.query.get("limit", "50"))))
        except ValueError:
            return self._json_error("任务数量限制必须是整数", status=400)
        task_type = request.query.get("type", "").strip()
        if len(task_type) > 100:
            return self._json_error("任务类型过长", status=400)
        status = request.query.get("status", "").strip().casefold()
        if status and status not in TASK_STATUSES:
            return self._json_error("任务状态不受支持", status=400)
        return await self._controller_response(
            self._controller.web_ui_list_tasks(limit, task_type, status)
        )

    async def _get_task(self, request: web.Request) -> web.Response:
        run_id = self._validated_run_id(request)
        if run_id is None:
            return self._json_error("任务 ID 格式无效", status=400)
        return await self._controller_response(
            self._controller.web_ui_get_task(run_id)
        )

    async def _get_task_events(self, request: web.Request) -> web.Response:
        run_id = self._validated_run_id(request)
        if run_id is None:
            return self._json_error("任务 ID 格式无效", status=400)
        try:
            after_seq = max(0, int(request.query.get("after", "0")))
            limit = min(2000, max(1, int(request.query.get("limit", "500"))))
        except ValueError:
            return self._json_error("事件游标和数量限制必须是整数", status=400)
        return await self._controller_response(
            self._controller.web_ui_get_task_events(run_id, after_seq, limit)
        )

    async def _cancel_task(self, request: web.Request) -> web.Response:
        run_id = self._validated_run_id(request)
        if run_id is None:
            return self._json_error("任务 ID 格式无效", status=400)
        return await self._controller_response(
            self._controller.web_ui_cancel_task(run_id)
        )

    async def _controller_response(self, awaitable: Any) -> web.Response:
        try:
            result = await awaitable
        except WebUiActionError as exc:
            return self._json_error(str(exc), status=400)
        except Exception as exc:
            logger.error(
                f"[{PLUGIN_NAME}] Web UI operation failed: {exc}",
                exc_info=True,
            )
            return self._json_error("操作失败，请查看 AstrBot 日志", status=500)
        return web.json_response({"ok": True, "data": result})

    @staticmethod
    async def _read_json(request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="请求必须是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="JSON 顶层必须是对象")
        return payload

    @staticmethod
    def _validated_run_id(request: web.Request) -> str | None:
        run_id = request.match_info.get("run_id", "").strip()
        if not run_id or len(run_id) > 128:
            return None
        if not all(character.isalnum() or character in "-_" for character in run_id):
            return None
        return run_id

    @staticmethod
    def _json_error(message: str, *, status: int) -> web.Response:
        return web.json_response(
            {"ok": False, "error": message},
            status=status,
        )


__all__ = [
    "WebUiActionError",
    "WebUiController",
    "WebUiError",
    "WebUiService",
]
