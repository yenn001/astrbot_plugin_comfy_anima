"""Shared minimal AstrBot stubs for the plugin test suite.

All test modules must install the same stub class identities so that
``astrbot_plugin_comfy_anima.main`` keeps using the same message component
classes as the tests that construct result chains.
"""

from __future__ import annotations

import sys
import types


class _DecoratorGroup:
    def command(self, *_args, **_kwargs):
        return lambda function: function


class _FilterStub:
    class PermissionType:
        ADMIN = "admin"

    class PlatformAdapterType:
        AIOCQHTTP = "aiocqhttp"

    class EventMessageType:
        ALL = "all"

    @staticmethod
    def command_group(*_args, **_kwargs):
        return lambda _function: _DecoratorGroup()

    @staticmethod
    def _passthrough(*_args, **_kwargs):
        return lambda function: function

    command = _passthrough
    llm_tool = _passthrough
    permission_type = _passthrough
    platform_adapter_type = _passthrough
    event_message_type = _passthrough
    on_llm_request = _passthrough
    on_decorating_result = _passthrough
    on_using_llm_tool = _passthrough
    on_llm_tool_respond = _passthrough
    on_agent_done = _passthrough
    after_message_sent = _passthrough


class _Star:
    def __init__(self, context):
        self.context = context


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    @staticmethod
    def fromFileSystem(path):
        return ("image", str(path))


class Node:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _VerifyOnlyIntentLedger:
    def verify(self, decision_id, expected):
        return True


def make_gate_payload(main, decision, message, user_id="", session_id=""):
    import hashlib

    return {
        "status": "judged",
        "decision": decision,
        "decision_id": "test-decision",
        "result_hash": "test-hash",
        "user_message_hash": hashlib.sha256(
            str(message or "").encode("utf-8")
        ).hexdigest(),
        "user_id_hash": hashlib.sha256(
            str(user_id or "").encode("utf-8")
        ).hexdigest(),
        "session_id_hash": hashlib.sha256(
            str(session_id or "").encode("utf-8")
        ).hexdigest(),
        "public_version": getattr(main, "PLUGIN_VERSION", "2.4.1"),
        "internal_target_version": getattr(main, "INTERNAL_BUILD_ID", "3.1.400"),
        "confidence": 0.9,
        "backend_used": "test",
        "reason": "test",
        "trace": {},
    }


def _install_ledger_fallback() -> None:
    main_module = sys.modules.get("astrbot_plugin_comfy_anima.main")
    if main_module is not None:
        main_module.ComfyAnimaPlugin._intent_decision_ledger = _VerifyOnlyIntentLedger()


def install_astrbot_stubs() -> None:
    """Install or reuse one shared set of AstrBot API stubs."""
    components = sys.modules.get("astrbot.api.message_components")
    if components is not None and getattr(components, "Plain", None) is Plain:
        _install_ledger_fallback()
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")

    api.logger = types.SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    event.AstrMessageEvent = object
    event.filter = _FilterStub
    star.Context = object
    star.Star = _Star
    star.register = lambda *_args, **_kwargs: (lambda cls: cls)
    components.Plain = Plain
    components.Image = Image
    components.Node = Node

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.api.message_components": components,
        }
    )
    _install_ledger_fallback()
