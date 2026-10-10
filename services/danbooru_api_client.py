"""Direct Danbooru API access for character appearance evidence.

Why this exists: appearance evidence used to come only from the ComfyUI-side
``/danbooru_gallery/posts`` proxy, which is broken in this deployment (it answers
HTTP 200 with ``[{"error": ...}]``), so 208 of 243 lookups produced no evidence and
verified characters kept coming out without their canonical appearance tags.

Field names are deliberately the Danbooru-native ones (``id``, ``rating``,
``tag_string_character``, ``tag_string_general``) because the existing profile
parser reads exactly those keys; returning the same structure keeps every consumer
unchanged.

Every entry point here is **blocking** with a hard timeout: callers run it through
``asyncio.to_thread`` and must treat any failure as "no evidence" instead of
blocking the draw (see the optimization plan, section 8).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "AstrBot-ComfyAnima/2.5.1 (danbooru user y59_001)"
_CANONICAL_RE = re.compile(r"[A-Za-z0-9_().!\'&+:/-]{1,160}")
_RATING_SAFE = "g"


class DanbooruApiError(RuntimeError):
    """Raised when the direct Danbooru API cannot supply evidence."""


def build_posts_url(
    canonical_tag: str,
    *,
    base_url: str,
    login: str = "",
    api_key: str = "",
    limit: int = 100,
) -> str:
    """Return the bounded safe-rated posts URL for one verified canonical."""

    canonical = str(canonical_tag or "").strip()
    if not _CANONICAL_RE.fullmatch(canonical):
        raise DanbooruApiError("角色 canonical 无法用于外观证据查询")
    bounded = min(200, max(12, int(limit)))
    params: dict[str, str] = {
        "tags": f"{canonical} solo rating:{_RATING_SAFE}",
        "limit": str(bounded),
        "page": "1",
    }
    if api_key:
        params["login"] = str(login or "").strip()
        params["api_key"] = str(api_key).strip()
    base = str(base_url or "https://danbooru.donmai.us").strip().rstrip("/")
    return f"{base}/posts.json?" + urllib.parse.urlencode(params)


def fetch_character_posts(
    canonical_tag: str,
    *,
    base_url: str,
    login: str = "",
    api_key: str = "",
    proxy_url: str = "",
    limit: int = 100,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Blocking fetch of post metadata for one character.

    ``proxy_url`` accepts the app's usual forms (``socks5://host:port``,
    ``socks5h://host:port`` or ``http://host:port``). When a SOCKS proxy is
    configured the request goes through ``curl`` because that is the only SOCKS
    client proven present in this container; everything is bounded by
    ``timeout`` so a dead tunnel can never stall a draw.
    """

    url = build_posts_url(
        canonical_tag, base_url=base_url, login=login, api_key=api_key, limit=limit
    )
    proxy = str(proxy_url or "").strip()
    if proxy:
        text = _fetch_via_curl(url, proxy, timeout)
    else:
        text = _fetch_via_urllib(url, timeout)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise DanbooruApiError("Danbooru 返回内容无法解析") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise DanbooruApiError(f"Danbooru 返回错误: {str(payload['error'])[:120]}")
    if not isinstance(payload, list):
        raise DanbooruApiError("Danbooru 返回结构不是列表")
    return [item for item in payload if isinstance(item, dict)]


def _proxy_args(proxy: str) -> list[str]:
    value = proxy.strip()
    if value.startswith("socks5h://"):
        return ["--socks5-hostname", value[len("socks5h://"):]]
    if value.startswith("socks5://"):
        return ["--socks5", value[len("socks5://"):]]
    if value.startswith("socks4://"):
        return ["--socks4", value[len("socks4://"):]]
    return ["--proxy", value]


def _fetch_via_curl(url: str, proxy: str, timeout: float) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise DanbooruApiError("缺少 curl，无法使用代理访问 Danbooru")
    args = [
        curl, "-s", "-S", "--fail", "-m", str(int(max(3.0, timeout))),
        "-A", USER_AGENT, *_proxy_args(proxy), url,
    ]
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=max(3.0, timeout) + 5.0
        )
    except subprocess.TimeoutExpired as exc:
        raise DanbooruApiError("Danbooru 请求超时（代理）") from exc
    if completed.returncode != 0:
        raise DanbooruApiError(
            f"Danbooru 请求失败（代理，curl {completed.returncode}）"
        )
    return completed.stdout


def _fetch_via_urllib(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=max(3.0, timeout)) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - every failure means "no evidence"
        raise DanbooruApiError(
            f"Danbooru 请求失败: {type(exc).__name__}"
        ) from exc
