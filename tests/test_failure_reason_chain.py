"""失败通知要说清原因，而不是只报异常类名。

实测：一次出图失败的通知只有 "⚠️ 出图失败（building）：WorkflowError"，
而真正的原因（"LLM 角色校验失败: 角色…命中多个身份，请补充准确作品名"）
被包在内层异常里，用户看不到。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
MAIN = importlib.import_module("astrbot_plugin_comfy_anima.main")


class _WithUserMessage(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.user_message = message


class DescribeFailureTests(unittest.TestCase):
    def test_inner_cause_with_user_message_wins(self) -> None:
        try:
            try:
                raise _WithUserMessage("角色“Narume”在本地 Danbooru 中命中多个身份，请补充准确作品名")
            except _WithUserMessage as inner:
                raise RuntimeError() from inner
        except RuntimeError as outer:
            described = MAIN._describe_failure(outer)
        self.assertIn("命中多个身份", described)

    def test_plain_exception_message_is_used(self) -> None:
        self.assertEqual(MAIN._describe_failure(ValueError("坏参数")), "坏参数")

    def test_bare_exception_falls_back_to_class_name(self) -> None:
        self.assertEqual(MAIN._describe_failure(RuntimeError()), "RuntimeError")

    def test_notice_uses_the_helper(self) -> None:
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("failure_reason = _describe_failure(exc)", src)
        self.assertIn("def _describe_failure(", src)


if __name__ == "__main__":
    unittest.main()
