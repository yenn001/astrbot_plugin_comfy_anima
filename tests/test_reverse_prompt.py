"""Tests for safe structured multimodal reverse prompting."""

import tempfile
import types
import unittest
from pathlib import Path

from ..models import PluginSettings
from ..services.reverse_prompt import (
    ReversePromptError,
    ReversePromptService,
    parse_reverse_prompt,
)


class ReversePromptParserTests(unittest.TestCase):
    def test_think_content_is_ignored_and_json_is_normalized(self) -> None:
        result = parse_reverse_prompt(
            """<think>private analysis</think>
```json
{
  "positive_tags": "1girl, black hair, looking at viewer",
  "negative_tags": "text, watermark",
  "composition": "waist-up portrait",
  "scene_description_zh": "暖色室内肖像",
  "characters": [{"name": "unknown heroine", "confidence": 0.2}],
  "uncertain_terms": ["character identity"],
  "confidence": 0.82
}
```"""
        )
        self.assertEqual(result.positive_tags, "1girl, black hair, looking at viewer")
        self.assertEqual(result.negative_tags, "text, watermark")
        self.assertEqual(result.confidence, 0.82)
        self.assertEqual(result.characters[0].confidence, 0.2)
        self.assertNotIn("private analysis", result.render("vision-provider"))

    def test_missing_positive_tags_is_rejected(self) -> None:
        with self.assertRaises(ReversePromptError):
            parse_reverse_prompt('{"positive_tags": "", "confidence": 1}')


class ReversePromptServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_provider_receives_local_image_only(self) -> None:
        captured = {}

        class Context:
            async def llm_generate(self, **kwargs):
                captured.update(kwargs)
                return types.SimpleNamespace(
                    completion_text=(
                        '{"positive_tags":"1girl, portrait",'
                        '"negative_tags":"text","confidence":0.9}'
                    )
                )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            service = ReversePromptService(
                PluginSettings.from_mapping(
                    {
                        "reverse_prompt_provider_id": "vision-provider",
                        "reverse_prompt_timeout": 10,
                    }
                )
            )
            result, provider_id = await service.reverse(
                Context(),
                types.SimpleNamespace(unified_msg_origin="umo"),
                image_path,
                "focus on composition",
            )
        self.assertEqual(provider_id, "vision-provider")
        self.assertEqual(captured["chat_provider_id"], "vision-provider")
        self.assertEqual(captured["image_urls"], [str(image_path)])
        self.assertIn("User focus", captured["prompt"])
        self.assertEqual(result.confidence, 0.9)
        self.assertNotIn("api_key", captured)

    async def test_current_chat_provider_is_used_as_last_fallback(self) -> None:
        class Context:
            async def get_current_chat_provider_id(self, **_kwargs):
                return "current-provider"

            async def llm_generate(self, **_kwargs):
                return types.SimpleNamespace(
                    completion_text='{"positive_tags":"landscape","confidence":0.7}'
                )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            result, provider_id = await ReversePromptService(
                PluginSettings()
            ).reverse(
                Context(),
                types.SimpleNamespace(unified_msg_origin="umo"),
                image_path,
            )
        self.assertEqual(provider_id, "current-provider")
        self.assertEqual(result.positive_tags, "landscape")


if __name__ == "__main__":
    unittest.main()
