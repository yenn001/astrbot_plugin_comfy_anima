"""
AstrBot Comfy Anima 插件 v1.2.0

功能描述：
- 测试 ComfyUI 历史输出图片提取逻辑

作者: Yen
版本: 1.2.0
日期: 2026-07-14
"""

import unittest

from ..services.comfy_client import ComfyClient, ComfyClientError


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


class _ChunkedContent:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _ChunkedResponse:
    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        content_length: int | None = None,
    ) -> None:
        self.content = _ChunkedContent(chunks)
        self.content_length = content_length


class ComfyClientAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_reader_consumes_all_stream_chunks(self) -> None:
        response = _ChunkedResponse((b'[{"id":1},', b'{"id":2}]'))

        content = await ComfyClient._read_bounded_content(response, 1024)

        self.assertEqual(content, b'[{"id":1},{"id":2}]')

    async def test_bounded_reader_rejects_stream_that_exceeds_limit(self) -> None:
        response = _ChunkedResponse((b"1234", b"5678"))

        with self.assertRaises(ComfyClientError):
            await ComfyClient._read_bounded_content(response, 7)

    async def test_bounded_reader_rejects_large_content_length(self) -> None:
        response = _ChunkedResponse((), content_length=2048)

        with self.assertRaises(ComfyClientError):
            await ComfyClient._read_bounded_content(response, 1024)


if __name__ == "__main__":
    unittest.main()
