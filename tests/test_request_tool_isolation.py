import sys
import types
import unittest
from unittest import mock

from ..services.request_tool_isolation import (
    COMPETING_DELIVERY_TOOL_NAMES,
    isolate_picture_delivery_tools,
)


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _ToolSet:
    def __init__(self, *names: str) -> None:
        self.tools = [_Tool(name) for name in names]


class _FakeRuntimeToolSet:
    def __init__(self, tools):
        self.tools = list(tools)


class RequestToolIsolationTests(unittest.TestCase):
    def _runtime_module(self):
        module = types.ModuleType("astrbot.core.agent.tool")
        module.ToolSet = _FakeRuntimeToolSet
        return module

    def test_competing_delivery_tools_are_removed_without_mutation(self) -> None:
        tool_set = _ToolSet(
            "send_message_to_user",
            "pc_generate_photo",
            "list_anima_loras",
            "ordinary_agent_tool",
        )
        with mock.patch.dict(
            sys.modules, {"astrbot.core.agent.tool": self._runtime_module()}
        ):
            isolated = isolate_picture_delivery_tools(tool_set)
        self.assertIsNot(isolated, tool_set)
        self.assertEqual(
            {tool.name for tool in isolated.tools},
            {"list_anima_loras", "ordinary_agent_tool"},
        )
        self.assertEqual(
            {tool.name for tool in tool_set.tools},
            {
                "send_message_to_user",
                "pc_generate_photo",
                "list_anima_loras",
                "ordinary_agent_tool",
            },
        )

    def test_none_or_unsupported_toolset_fails_closed(self) -> None:
        self.assertIsNone(isolate_picture_delivery_tools(None))
        self.assertIsNone(isolate_picture_delivery_tools(object()))

    def test_residual_competing_tool_fails_closed(self) -> None:
        with mock.patch.dict(
            sys.modules, {"astrbot.core.agent.tool": self._runtime_module()}
        ):
            isolated = isolate_picture_delivery_tools(
                _ToolSet("send_message_to_user", "safe")
            )
        self.assertEqual(
            {tool.name for tool in isolated.tools},
            {"safe"},
        )

    def test_missing_runtime_constructor_fails_closed(self) -> None:
        with mock.patch.dict(sys.modules, {"astrbot.core.agent.tool": types.ModuleType("x")}):
            self.assertIsNone(
                isolate_picture_delivery_tools(_ToolSet("safe"))
            )

    def test_extra_competing_tool_can_be_removed(self) -> None:
        tool_set = _ToolSet("other_delivery", "ordinary_agent_tool")
        with mock.patch.dict(
            sys.modules, {"astrbot.core.agent.tool": self._runtime_module()}
        ):
            isolated = isolate_picture_delivery_tools(
                tool_set,
                additional_blocked_names=("other_delivery",),
            )
        self.assertEqual([tool.name for tool in isolated.tools], ["ordinary_agent_tool"])
        self.assertEqual(
            [tool.name for tool in tool_set.tools],
            ["other_delivery", "ordinary_agent_tool"],
        )

    def test_allowlist_driven_isolation_removes_unknown_tools(self) -> None:
        tool_set = _ToolSet("safe_inventory_tool", "unknown_private_tool")
        with mock.patch.dict(
            sys.modules, {"astrbot.core.agent.tool": self._runtime_module()}
        ):
            isolated = isolate_picture_delivery_tools(
                tool_set,
                allowed_names=("safe_inventory_tool",),
            )
        self.assertEqual(
            [tool.name for tool in isolated.tools], ["safe_inventory_tool"]
        )

    def test_denylist_is_stable(self) -> None:
        self.assertEqual(
            COMPETING_DELIVERY_TOOL_NAMES,
            {
                "comfy_anima_generate_for_companion",
                "pc_generate_photo",
                "pc_send_current_media",
                "send_message_to_user",
            },
        )


if __name__ == "__main__":
    unittest.main()
