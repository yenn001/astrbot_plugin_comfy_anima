import unittest

from ..services.intent_router import (
    IntentRouterError,
    apply_confidence_gate,
    build_intent_router_prompts,
    parse_intent_decision,
)


class IntentRouterTests(unittest.TestCase):
    def test_parses_strict_decision(self):
        result = parse_intent_decision(
            '{"intent":"draw_new","visual_delivery":true,'
            '"needs_previous_image":false,"confidence":0.91}'
        )
        self.assertEqual(result.intent, "draw_new")
        self.assertTrue(result.visual_delivery)
        self.assertAlmostEqual(result.confidence, 0.91)

    def test_rejects_invalid_shape(self):
        with self.assertRaises(IntentRouterError):
            parse_intent_decision('{"intent":"draw_new","visual_delivery":"yes"}')

    def test_accepts_fenced_json(self):
        result = parse_intent_decision(
            "```json\n{\"intent\":\"query_only\","
            "\"visual_delivery\":false,\"confidence\":1}\n```"
        )
        self.assertEqual(result.intent, "query_only")

    def test_confidence_gate_downgrades_to_clarify(self):
        result = parse_intent_decision(
            '{"intent":"draw_new","visual_delivery":true,'
            '"needs_previous_image":false,"confidence":0.55}'
        )
        gated = apply_confidence_gate(result, min_confidence=0.7)
        self.assertEqual(gated.intent, "clarify")
        self.assertFalse(gated.visual_delivery)

    def test_confidence_gate_passes_high_confidence(self):
        result = parse_intent_decision(
            '{"intent":"draw_new","visual_delivery":true,'
            '"needs_previous_image":false,"confidence":0.8}'
        )
        gated = apply_confidence_gate(result, min_confidence=0.7)
        self.assertEqual(gated.intent, "draw_new")

    def test_router_prompt_requires_debug_priority(self):
        system, _user = build_intent_router_prompts(
            message="检查一下日志",
            tool_names=[],
            evidence=[],
        )
        self.assertIn("debug_only", system)
        self.assertIn("logs", system)


if __name__ == "__main__":
    unittest.main()
