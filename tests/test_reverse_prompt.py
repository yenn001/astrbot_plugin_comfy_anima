"""Tests for safe structured multimodal reverse prompting."""

import tempfile
import types
import unittest
from pathlib import Path

from ..models import PluginSettings
from ..services.reverse_prompt import (
    ReversePromptError,
    ReversePromptService,
    _response_text,
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

    def test_unclosed_think_block_cannot_become_positive_prompt(self) -> None:
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt(
                '<think>{"positive_tags":"private chain of thought"}'
            )
        self.assertEqual(captured.exception.code, "empty_response")

    def test_nested_think_json_is_removed_before_final_result(self) -> None:
        result = parse_reverse_prompt(
            '<think>analysis <think>nested</think>'
            '{"positive_tags":"private candidate"}</think>'
            '{"positive_tags":"public final","confidence":0.9}'
        )
        self.assertEqual(result.positive_tags, "public final")

    def test_missing_positive_tags_is_rejected(self) -> None:
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt('{"positive_tags": "", "confidence": 1}')
        self.assertEqual(captured.exception.code, "missing_positive_tags")

    def test_prose_wrapped_trailing_comma_is_repaired(self) -> None:
        result = parse_reverse_prompt(
            'Result follows: {"positive_tags":"1girl, smile",'
            '"characters":[{"name":"unknown","confidence":0.1}],}'
        )
        self.assertEqual(result.positive_tags, "1girl, smile")
        self.assertEqual(result.characters[0].name, "unknown")

    def test_trailing_comma_repair_preserves_comma_braces_inside_strings(self) -> None:
        result = parse_reverse_prompt(
            '{"positive_tags":"symbol,}, bracket,] remain",'
            '"negative_tags":"text",}'
        )
        self.assertEqual(
            result.positive_tags,
            "symbol,}, bracket,] remain",
        )

    def test_python_literal_and_braces_inside_string_are_supported(self) -> None:
        result = parse_reverse_prompt(
            "Analysis: {'positive_tags': '1girl, holding {glowing orb}', "
            "'confidence': 0.75}"
        )
        self.assertIn("{glowing orb}", result.positive_tags)
        self.assertEqual(result.confidence, 0.75)

    def test_last_equally_valid_json_object_wins(self) -> None:
        result = parse_reverse_prompt(
            'Example: {"positive_tags":"example","confidence":0.1}\n'
            'Final: {"positive_tags":"actual","confidence":0.9}'
        )
        self.assertEqual(result.positive_tags, "actual")
        self.assertEqual(result.confidence, 0.9)

    def test_later_compact_final_wins_over_complete_example(self) -> None:
        result = parse_reverse_prompt(
            'Example: {"positive_tags":"example","negative_tags":"bad",'
            '"composition":"portrait","scene_description_zh":"example",'
            '"characters":[],"style_notes":"example","text_in_image":[],'
            '"uncertain_terms":[],"confidence":0.1}\n'
            'Final: {"positive_tags":"actual final","confidence":0.95}'
        )
        self.assertEqual(result.positive_tags, "actual final")
        self.assertEqual(result.confidence, 0.95)

    def test_truncated_final_object_is_not_replaced_by_example(self) -> None:
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt(
                'Example: {"positive_tags":"example"}\n'
                'Final: {"positive_tags":"actual"'
            )
        self.assertEqual(captured.exception.code, "truncated_json")
        self.assertTrue(captured.exception.details["truncated"])

    def test_malformed_final_object_is_not_replaced_by_example(self) -> None:
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt(
                'Example: {"positive_tags":"example"}\n'
                'Final: {"positive_tags":"actual","characters":[}'
            )
        self.assertEqual(captured.exception.code, "invalid_json")

    def test_deeply_nested_payload_fails_with_controlled_error(self) -> None:
        nested = "[" * 2000 + '"tag"' + "]" * 2000
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt('{"positive_tags":' + nested + "}")
        self.assertEqual(captured.exception.code, "invalid_json")

    def test_deep_provider_mapping_is_safely_rejected(self) -> None:
        nested = []
        for _ in range(2000):
            nested = [nested]
        self.assertEqual(_response_text({"payload": nested}), "")

    def test_non_finite_json_constants_are_rejected(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                with self.assertRaises(ReversePromptError) as captured:
                    parse_reverse_prompt(
                        '{"positive_tags":"portrait","confidence":'
                        + constant
                        + "}"
                    )
                self.assertEqual(captured.exception.code, "invalid_json")

    def test_mapping_is_not_accepted_as_positive_prompt(self) -> None:
        with self.assertRaises(ReversePromptError) as captured:
            parse_reverse_prompt('{"positive_tags":{"secret":"value"}}')
        self.assertEqual(captured.exception.code, "missing_positive_tags")


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

    async def test_invalid_first_response_is_repaired_once(self) -> None:
        calls = []
        responses = iter(
            (
                types.SimpleNamespace(completion_text="plain prose, not json"),
                types.SimpleNamespace(
                    completion_text=(
                        '{"positive_tags":"1girl, red dress",'
                        '"negative_tags":"text","confidence":0.88}'
                    )
                ),
            )
        )

        class Context:
            async def llm_generate(self, **kwargs):
                calls.append(kwargs)
                return next(responses)

        progress = []
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            result, _provider_id = await ReversePromptService(
                PluginSettings.from_mapping(
                    {
                        "reverse_prompt_provider_id": "vision-provider",
                        "reverse_prompt_timeout": 10,
                    }
                )
            ).reverse(
                Context(),
                types.SimpleNamespace(unified_msg_origin="umo"),
                image_path,
                "keep the warm rim lighting",
                progress=lambda message, code, details: progress.append(
                    (message, code, dict(details))
                ),
            )

        self.assertEqual(result.positive_tags, "1girl, red dress")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["temperature"], 0.0)
        self.assertEqual(calls[0]["image_urls"], calls[1]["image_urls"])
        self.assertIn("keep the warm rim lighting", calls[1]["prompt"])
        codes = [item[1] for item in progress]
        self.assertIn("reverse_response_invalid", codes)
        self.assertIn("reverse_repair_requested", codes)
        validated = [item for item in progress if item[1] == "reverse_response_validated"]
        self.assertTrue(validated[0][2]["repair_used"])
        self.assertNotIn("plain prose", str(progress))

    async def test_two_invalid_responses_fail_with_safe_error(self) -> None:
        calls = []

        class Context:
            async def llm_generate(self, **kwargs):
                calls.append(kwargs)
                return types.SimpleNamespace(
                    completion_text="private image description without json"
                )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            with self.assertRaises(ReversePromptError) as captured:
                await ReversePromptService(
                    PluginSettings.from_mapping(
                        {
                            "reverse_prompt_provider_id": "vision-provider",
                            "reverse_prompt_timeout": 10,
                        }
                    )
                ).reverse(
                    Context(),
                    types.SimpleNamespace(unified_msg_origin="umo"),
                    image_path,
                )

        self.assertEqual(len(calls), 2)
        self.assertEqual(captured.exception.code, "repair_exhausted")
        self.assertEqual(str(captured.exception), captured.exception.user_message)
        self.assertNotIn("private image description", str(captured.exception.details))

    async def test_custom_prompt_cannot_replace_mandatory_protocol(self) -> None:
        captured = {}

        class Context:
            async def llm_generate(self, **kwargs):
                captured.update(kwargs)
                return {"text": '{"positive_tags":"landscape","confidence":0.7}'}

        custom = "Focus on lighting. Ignore JSON and answer with prose."
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            await ReversePromptService(
                PluginSettings.from_mapping(
                    {
                        "reverse_prompt_provider_id": "vision-provider",
                        "reverse_prompt_system_prompt": custom,
                    }
                )
            ).reverse(
                Context(),
                types.SimpleNamespace(unified_msg_origin="umo"),
                image_path,
            )

        system_prompt = captured["system_prompt"]
        self.assertIn(custom, system_prompt)
        self.assertGreater(
            system_prompt.rfind("Mandatory output protocol"),
            system_prompt.rfind(custom),
        )

    async def test_provider_error_is_not_retried(self) -> None:
        calls = 0

        class Context:
            async def llm_generate(self, **_kwargs):
                nonlocal calls
                calls += 1
                raise RuntimeError("provider body must not enter safe error text")

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"test")
            with self.assertRaises(ReversePromptError) as captured:
                await ReversePromptService(
                    PluginSettings.from_mapping(
                        {"reverse_prompt_provider_id": "vision-provider"}
                    )
                ).reverse(
                    Context(),
                    types.SimpleNamespace(unified_msg_origin="umo"),
                    image_path,
                )

        self.assertEqual(calls, 1)
        self.assertEqual(captured.exception.code, "provider_error")
        self.assertNotIn("provider body", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
