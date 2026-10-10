"""出图任务失败必须通知用户。

实测：09:52 两次 WorkflowError、06:32 一次"生成超过 1200 秒"（挂了三小时），
任务事件里只有 image_task_failed，用户界面一片安静。原因是失败终结处只记录
任务事件、从不向会话发消息；而 _send_job_notice 这条现成通道此前只用于排队提示。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FailureNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        start = main.find(chr(34) + "image_task_failed" + chr(34))
        cls.block = main[start - 400 : start + 1500]
        cls.main = main

    def test_failure_handler_notifies_the_user(self) -> None:
        self.assertIn("_send_job_notice(", self.block)
        self.assertIn("出图失败", self.block)
        self.assertIn("failure_reason", self.block)

    def test_notice_uses_the_real_reason_not_the_class_name(self) -> None:
        self.assertIn('getattr(exc, "user_message", "")', self.block)
        self.assertIn("type(exc).__name__", self.block)

    def test_failure_is_also_logged(self) -> None:
        self.assertIn("image task failed: stage=", self.block)

    def test_queue_notice_helper_is_reused(self) -> None:
        self.assertIn("async def _send_job_notice(", self.main)
        self.assertIn("sender(event.plain_result(message))", self.main)


if __name__ == "__main__":
    unittest.main()
