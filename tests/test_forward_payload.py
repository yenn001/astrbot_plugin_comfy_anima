"""`_make_image_result` 转发/普通两投递分支的图片段形态测试。

3.1.417 修复：合并转发 Node 内容内的图片段必须内联 base64，
普通消息保持 file 路径由适配器顶层转换。
"""

import base64
import importlib
import tempfile
import types
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs


class ForwardPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(forward_sender_name="测试机器人")
        plugin._get_drawing_orchestrator = lambda: types.SimpleNamespace(
            state=lambda _event: types.SimpleNamespace(run_id="run-forward")
        )
        return plugin

    def _event(self):
        captured = []

        def chain_result(comps):
            captured.append(comps)
            return "SENT"

        event = types.SimpleNamespace(
            message_obj=types.SimpleNamespace(self_id=12345),
            chain_result=chain_result,
        )
        return event, captured

    def _image_file(self, directory: str) -> Path:
        image = Path(directory) / "done.png"
        image.write_bytes(b"synthetic-png-bytes")
        return image

    def test_forward_embeds_base64_image_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = self._image_file(directory)
            event, captured = self._event()
            result = self._plugin()._make_image_result(
                event, [image], 42, forward=True
            )
            self.assertEqual(result, "SENT")
            (chain,) = captured
            (node,) = chain
            self.assertEqual(node.uin, "12345")
            self.assertEqual(node.name, "测试机器人")
            summary, *segments = node.content
            self.assertIn("Seed: 42", summary.text)
            self.assertEqual(
                segments,
                [
                    (
                        "image-base64",
                        base64.b64encode(b"synthetic-png-bytes").decode("ascii"),
                    )
                ],
            )

    def test_plain_keeps_filesystem_image_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = self._image_file(directory)
            event, captured = self._event()
            result = self._plugin()._make_image_result(
                event, [image], 42, forward=False
            )
            self.assertEqual(result, "SENT")
            (chain,) = captured
            summary, *segments = chain
            self.assertIn("Seed: 42", summary.text)
            self.assertEqual(segments, [("image", str(image))])


if __name__ == "__main__":
    unittest.main()
