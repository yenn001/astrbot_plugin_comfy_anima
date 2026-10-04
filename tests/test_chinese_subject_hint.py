"""回归：中文角色名必须能成为"主体"，不得掉进别名兜底。

实测（2026-10-04）：`/重绘 角色是大肥鱼 --m p`
  → `_requested_subject_hint` 提取到「大肥鱼」✓ 但出口的 ASCII 门禁把它丢掉 ✗
  → 掉进"从文本里捞已知别名"的兜底 → 主体变成反推事实里的 "shadow" ✗
  → `lora_count: 0` ✗ → 提示词没有名字 → 导演照字面翻成 "big fat fish" ✗ → 画出真鱼。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs


class ChineseSubjectHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, aliases=()):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        index = type("Index", (), {"alias_lookup": tuple(aliases), "entries": ()})()
        plugin._semantic_index = index
        return plugin

    def test_chinese_name_is_returned(self) -> None:
        plugin = self._plugin()
        self.assertEqual(
            plugin._requested_subject_hint("角色是大肥鱼"), "大肥鱼"
        )

    def test_chinese_name_before_flags(self) -> None:
        plugin = self._plugin()
        self.assertEqual(
            plugin._requested_subject_hint("角色是大肥鱼 --m p"), "大肥鱼"
        )

    def test_chinese_name_with_separator(self) -> None:
        plugin = self._plugin()
        self.assertEqual(
            plugin._requested_subject_hint("重绘 角色是大肥鱼；兔女郎"), "大肥鱼"
        )

    def test_ascii_name_still_works(self) -> None:
        plugin = self._plugin()
        self.assertEqual(
            plugin._requested_subject_hint("角色是denia"), "denia"
        )

    def test_role_phrasing_wins_over_alias_scraping(self) -> None:
        """有「角色是X」时不能用别名兜底把它盖掉（shadow/background 就是这么来的）。"""

        plugin = self._plugin(aliases=("shadow", "background", "大类"))
        self.assertEqual(
            plugin._requested_subject_hint("角色是大肥鱼"), "大肥鱼"
        )

    def test_no_role_phrasing_still_falls_back(self) -> None:
        plugin = self._plugin(aliases=("denia",))
        self.assertEqual(plugin._requested_subject_hint("画一张 denia"), "denia")


if __name__ == "__main__":
    unittest.main()
