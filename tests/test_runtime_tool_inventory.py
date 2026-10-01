"""Capability-driven tool inventory tests."""

import unittest

from ..services.runtime_tool_inventory import (
    RUNTIME_TOOL_CAPABILITIES,
    drawing_request_allowlist,
)


class RuntimeToolInventoryTests(unittest.TestCase):
    def test_every_inventory_name_has_capabilities(self) -> None:
        self.assertTrue(RUNTIME_TOOL_CAPABILITIES)
        for name, capabilities in RUNTIME_TOOL_CAPABILITIES.items():
            self.assertTrue(capabilities, name)

    def test_drawing_allowlist_keeps_anima_assets(self) -> None:
        allowlist = set(drawing_request_allowlist())
        self.assertIn("list_anima_loras", allowlist)
        self.assertIn("search_anima_danbooru_tags", allowlist)
        self.assertNotIn("save_anima_lora_style", allowlist)

    def test_drawing_allowlist_excludes_delivery_and_relay(self) -> None:
        allowlist = set(drawing_request_allowlist())
        for blocked in (
            "send_message_to_user",
            "pc_send_to_group",
            "pc_send_to_groups",
            "pc_send_to_private_user",
            "pc_send_to_private_users",
            "pc_send_current_media",
            "pc_relay_message",
            "pc_schedule_group_relay",
            "pc_qzone_publish_feed",
        ):
            self.assertNotIn(blocked, allowlist)

    def test_drawing_allowlist_excludes_execution_and_web(self) -> None:
        allowlist = set(drawing_request_allowlist())
        for blocked in (
            "astrbot_execute_shell",
            "astrbot_execute_python",
            "astrbot_file_write_tool",
            "web_search_tavily",
            "future_task",
        ):
            self.assertNotIn(blocked, allowlist)


if __name__ == "__main__":
    unittest.main()
