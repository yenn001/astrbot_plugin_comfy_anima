from __future__ import annotations

import math
import types
import unittest

from astrbot_plugin_comfy_anima.services.structured_provider import (
    StructuredProviderError,
    extract_structured_payload,
)


EXPECTED = "plan_character_identity"


class StructuredProviderTests(unittest.TestCase):
    def test_astrbot_llm_response_tool_fields(self) -> None:
        response = types.SimpleNamespace(
            tools_call_name=EXPECTED,
            tools_call_args='{"identity":"rice_shower_(umamusume)"}',
        )

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.tool_name, EXPECTED)
        self.assertEqual(parsed.source, "astrbot.tools_call")
        self.assertEqual(parsed.arguments["identity"], "rice_shower_(umamusume)")

    def test_astrbot_llm_response_parallel_tool_lists(self) -> None:
        response = types.SimpleNamespace(
            tools_call_name=["emit_anima_plan_v1"],
            tools_call_args=[
                {
                    "positive_tags": "1girl, portrait",
                    "negative_tags": "lowres",
                    "pipeline": "base",
                }
            ],
        )

        parsed = extract_structured_payload(
            response,
            expected_tool_name="emit_anima_plan_v1",
        )

        self.assertEqual(parsed.tool_name, "emit_anima_plan_v1")
        self.assertEqual(parsed.source, "astrbot.tools_call[0]")
        self.assertEqual(parsed.arguments["positive_tags"], "1girl, portrait")

    def test_astrbot_parallel_tool_lists_support_multiple_mirrored_calls(self) -> None:
        response = {
            "tools_call_name": [EXPECTED, EXPECTED],
            "tools_call_args": [
                {"identity": "a_(work)"},
                {"identity": "a_(work)"},
            ],
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments, {"identity": "a_(work)"})

    def test_astrbot_parallel_tool_lists_must_have_matching_lengths(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                {
                    "tools_call_name": [EXPECTED],
                    "tools_call_args": [],
                },
                expected_tool_name=EXPECTED,
            )
        self.assertEqual(raised.exception.code, "malformed_astrbot_tool_call")

    def test_astrbot_parallel_tool_lists_reject_mixed_shapes(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                {
                    "tools_call_name": [EXPECTED],
                    "tools_call_args": {"identity": "a_(work)"},
                },
                expected_tool_name=EXPECTED,
            )
        self.assertEqual(raised.exception.code, "malformed_astrbot_tool_call")

    def test_mapping_tool_calls_function_envelope(self) -> None:
        response = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": EXPECTED,
                        "arguments": {"identity": "kiki_(game)"},
                    },
                }
            ]
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments, {"identity": "kiki_(game)"})

    def test_mapping_legacy_function_call(self) -> None:
        response = {
            "function_call": {
                "name": EXPECTED,
                "arguments": '{"identity":"denia_(wuthering_waves)"}',
            }
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments["identity"], "denia_(wuthering_waves)")

    def test_openai_choices_message_tool_calls(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": EXPECTED,
                                    "arguments": '{"identity":"alice_(wonderland)"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments["identity"], "alice_(wonderland)")

    def test_result_chain_single_json_component(self) -> None:
        response = types.SimpleNamespace(
            result_chain=[
                {
                    "type": "json",
                    "data": {"identity": "rice_shower_(umamusume)"},
                }
            ]
        )

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.tool_name, "")
        self.assertEqual(parsed.source, "result_chain[0].json")

    def test_visible_json_text_and_fenced_json(self) -> None:
        for response in (
            '{"identity":"kiki_(game)"}',
            types.SimpleNamespace(
                completion_text='```json\n{"identity":"kiki_(game)"}\n```'
            ),
        ):
            with self.subTest(response=type(response).__name__):
                parsed = extract_structured_payload(
                    response,
                    expected_tool_name=EXPECTED,
                )
                self.assertEqual(parsed.arguments["identity"], "kiki_(game)")

    def test_openai_visible_json_content(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"identity":"kiki_(game)"}',
                    }
                }
            ]
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.source, "choices[0].message.content")

    def test_wrong_tool_name_fails_closed(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "delete_everything",
                                "arguments": "{}",
                            }
                        }
                    ]
                },
                expected_tool_name=EXPECTED,
            )
        self.assertEqual(raised.exception.code, "unexpected_tool_name")

    def test_multiple_distinct_calls_fail_closed(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                {
                    "tool_calls": [
                        {
                            "function": {
                                "name": EXPECTED,
                                "arguments": '{"identity":"a_(work)"}',
                            }
                        },
                        {
                            "function": {
                                "name": EXPECTED,
                                "arguments": '{"identity":"b_(work)"}',
                            }
                        },
                    ]
                },
                expected_tool_name=EXPECTED,
            )
        self.assertEqual(raised.exception.code, "multiple_tool_calls")

    def test_identical_mirrored_call_is_deduplicated(self) -> None:
        response = {
            "tools_call_name": EXPECTED,
            "tools_call_args": {"identity": "a_(work)"},
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": EXPECTED,
                                    "arguments": '{"identity":"a_(work)"}',
                                }
                            }
                        ]
                    }
                }
            ],
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments["identity"], "a_(work)")

    def test_conflicting_tool_call_and_visible_json_fail_closed(self) -> None:
        response = {
            "tool_calls": [
                {
                    "function": {
                        "name": EXPECTED,
                        "arguments": '{"identity":"a_(work)"}',
                    }
                }
            ],
            "completion_text": '{"identity":"b_(work)"}',
        }

        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(response, expected_tool_name=EXPECTED)
        self.assertEqual(raised.exception.code, "conflicting_payload_sources")

    def test_multiple_result_chain_json_objects_fail_closed(self) -> None:
        response = {
            "result_chain": [
                {"type": "json", "data": {"identity": "a_(work)"}},
                {"type": "json", "data": {"identity": "b_(work)"}},
            ]
        }

        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(response, expected_tool_name=EXPECTED)
        self.assertEqual(raised.exception.code, "multiple_json_payloads")

    def test_plain_text_with_explanation_is_not_recovered(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                'Here is the result: {"identity":"a_(work)"}',
                expected_tool_name=EXPECTED,
            )
        self.assertEqual(raised.exception.code, "invalid_json")

    def test_duplicate_keys_and_non_finite_numbers_are_rejected(self) -> None:
        for text, code in (
            ('{"identity":"a","identity":"b"}', "duplicate_json_key"),
            ('{"confidence":NaN}', "non_finite_number"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(StructuredProviderError) as raised:
                    extract_structured_payload(text, expected_tool_name=EXPECTED)
                self.assertEqual(raised.exception.code, code)

    def test_mapping_non_finite_and_cycle_are_rejected(self) -> None:
        cycle: dict[str, object] = {}
        cycle["self"] = cycle
        for arguments, code in (
            ({"confidence": math.inf}, "non_finite_number"),
            (cycle, "cyclic_payload"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(StructuredProviderError) as raised:
                    extract_structured_payload(
                        {
                            "function_call": {
                                "name": EXPECTED,
                                "arguments": arguments,
                            }
                        },
                        expected_tool_name=EXPECTED,
                    )
                self.assertEqual(raised.exception.code, code)

    def test_json_fallback_can_be_disabled(self) -> None:
        with self.assertRaises(StructuredProviderError) as raised:
            extract_structured_payload(
                '{"identity":"a_(work)"}',
                expected_tool_name=EXPECTED,
                allow_json_fallback=False,
            )
        self.assertEqual(raised.exception.code, "missing_tool_call")

    def test_reasoning_field_is_ignored(self) -> None:
        response = {
            "reasoning_content": '{"identity":"wrong_(work)"}',
            "completion_text": '{"identity":"right_(work)"}',
        }

        parsed = extract_structured_payload(response, expected_tool_name=EXPECTED)

        self.assertEqual(parsed.arguments["identity"], "right_(work)")


if __name__ == "__main__":
    unittest.main()
