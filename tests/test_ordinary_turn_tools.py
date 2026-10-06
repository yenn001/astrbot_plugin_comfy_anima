"""回归钉：普通聊天轮次不得替换 req.func_tool。

故障（2026-10-06，用户对照实验实证）：开启自然绘图模式后，`director_primary`
分支对**每个**请求都用绘图白名单替换 `req.func_tool`，于是宿主工具
（Tavily 网页搜索、记忆、定时任务、MCP、技能、代码/文件读写）与其它插件的工具
全部被摘掉；用户关掉插件后这些立刻恢复，证实故障点在此。

设计定案：**绘图轮次保留白名单**（fail-closed），**普通轮次零隔离**；
生图链路另有执行阶段的 fail-closed 关卡兜底（`BLOCKED_EXECUTION_TOOL_NAMES`）。

本测试以源码为钉：普通轮次分支内不得再出现 `req.func_tool = ` 赋值。
"""

import re
import unittest
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


class OrdinaryTurnKeepsHostToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = MAIN.read_text(encoding="utf-8")

    def _branch_body(self, marker: str, *, span: int = 1400) -> str:
        start = self.source.find(marker)
        self.assertGreater(start, 0, f"未找到分支标记：{marker}")
        return self.source[start : start + span]

    def test_ordinary_turn_branch_does_not_replace_tool_set(self) -> None:
        body = self._branch_body("if director_primary:")
        self.assertNotIn(
            "req.func_tool = ",
            body,
            "普通聊天轮次不得替换 req.func_tool（会摘掉 AstrBot 宿主工具）",
        )
        self.assertNotIn("drawing_request_allowlist()", body)

    def test_drawing_turn_branch_still_isolates(self) -> None:
        body = self._branch_body("if active:")
        self.assertIn("req.func_tool = isolated", body)
        self.assertIn("drawing_request_allowlist()", body)

    def test_execution_stage_guard_still_exists(self) -> None:
        """执行阶段的 fail-closed 关卡必须保留（它不依赖请求阶段隔离）。"""

        self.assertIn("BLOCKED_EXECUTION_TOOL_NAMES", self.source)
        self.assertRegex(
            self.source,
            re.compile(r"if tool_name in BLOCKED_EXECUTION_TOOL_NAMES:"),
        )


if __name__ == "__main__":
    unittest.main()
