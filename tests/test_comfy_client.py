"""
AstrBot Comfy Anima 插件 v1.1.0

功能描述：
- 测试 ComfyUI 历史输出图片提取逻辑

作者: Yen
版本: 1.1.0
日期: 2026-07-14
"""

import unittest

from ..services.comfy_client import ComfyClient


class ComfyClientTests(unittest.TestCase):
    """ComfyUI 客户端纯函数测试。"""

    def test_extract_images_prefers_final_node(self) -> None:
        """存在多个输出时应优先选择最终放大节点。"""
        outputs = {
            "20": {
                "images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]
            },
            "285": {
                "images": [{"filename": "final.png", "subfolder": "", "type": "temp"}]
            },
        }
        images = ComfyClient.extract_images(outputs, ["285", "20"])
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].filename, "final.png")
        self.assertEqual(images[0].node_id, "285")


if __name__ == "__main__":
    unittest.main()
