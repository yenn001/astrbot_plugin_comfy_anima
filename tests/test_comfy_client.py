"""
AstrBot Comfy Anima 插件 v1.2.0

功能描述：
- 测试 ComfyUI 历史输出图片提取逻辑

作者: Yen
版本: 1.2.0
日期: 2026-07-14
"""

import json
from types import SimpleNamespace
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

    def test_extract_text_prefers_declared_node_and_bounds_output(self) -> None:
        outputs = {
            "1": {"text": "fallback"},
            "2": {"ui": {"text": ["preferred", "tags"]}},
        }

        text = ComfyClient.extract_text(outputs, ["2", "1"], max_chars=12)

        self.assertEqual(text, "preferred\nta")

    def test_extract_text_rejects_non_text_output_shapes(self) -> None:
        self.assertEqual(
            ComfyClient.extract_text(
                {"1": {"text": [{"unsafe": "object"}]}},
                ["1"],
                max_chars=100,
            ),
            "",
        )


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


class _JsonResponse(_ChunkedResponse):
    def __init__(self, payload, *, status=200) -> None:
        super().__init__((json.dumps(payload).encode("utf-8"),))
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Session:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def get(self, url, *, params):
        self.calls.append((url, params))
        return self.response


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

    async def test_gallery_autocomplete_is_bounded_and_parsed(self) -> None:
        client = ComfyClient(
            SimpleNamespace(comfyui_url="http://127.0.0.1:8188")
        )
        session = _Session(
            _JsonResponse(
                [{"value": "viola_(bang_dream!)", "category": 4}]
            )
        )
        client._get_session = lambda: _async_value(session)

        rows = await client.danbooru_character_autocomplete("Viola", limit=20)

        self.assertEqual(rows[0]["value"], "viola_(bang_dream!)")
        self.assertEqual(session.calls[0][1]["query"], "viola")

    async def test_gallery_autocomplete_rejects_unsafe_query(self) -> None:
        client = ComfyClient(
            SimpleNamespace(comfyui_url="http://127.0.0.1:8188")
        )

        with self.assertRaises(ComfyClientError):
            await client.danbooru_character_autocomplete("<lora:bad:1>")

    async def test_gallery_posts_accepts_punctuated_canonical(self) -> None:
        client = ComfyClient(
            SimpleNamespace(comfyui_url="http://127.0.0.1:8188")
        )
        session = _Session(_JsonResponse([{"id": 1}]))
        client._get_session = lambda: _async_value(session)

        rows = await client.danbooru_character_posts(
            "viola_(bang_dream!)",
            limit=12,
        )

        self.assertEqual(rows, [{"id": 1}])
        self.assertEqual(
            session.calls[0][1]["search[tags]"],
            "viola_(bang_dream!) solo",
        )


async def _async_value(value):
    return value


if __name__ == "__main__":
    unittest.main()
