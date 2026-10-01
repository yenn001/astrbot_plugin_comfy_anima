"""Delivery pacing tests: deterministic, no fake success."""

import unittest

from ..services.chat_intent_classifier import (
    build_intent_plan,
)
from ..services.delivery_pacing import build_follow_up_text, decide_delivery_pacing


class DeliveryPacingTests(unittest.TestCase):
    def test_draw_intent_allows_delivery(self) -> None:
        plan = build_intent_plan("画一张")
        decision = decide_delivery_pacing(plan, now=10.0)
        self.assertTrue(decision.allow)
        self.assertEqual(decision.max_images, 1)

    def test_clarify_intent_blocks_delivery(self) -> None:
        plan = build_intent_plan("继续", has_recipe=False)
        decision = decide_delivery_pacing(plan, now=10.0)
        self.assertFalse(decision.allow)
        self.assertEqual(decision.max_images, 1)

    def test_max_images_is_clamped_to_config(self) -> None:
        plan = build_intent_plan("画一套")
        decision = decide_delivery_pacing(
            plan, config={"max_auto_images_per_reply": 7}, now=10.0
        )
        self.assertEqual(decision.max_images, 4)

    def test_cooldown_blocks_too_fast_delivery(self) -> None:
        plan = build_intent_plan("画一张")
        decision = decide_delivery_pacing(
            plan,
            config={"delivery_cooldown_seconds": 8},
            history={"last_delivery_at": 5.0},
            now=9.0,
        )
        self.assertFalse(decision.allow)
        self.assertIn("cooldown", decision.reason)

    def test_in_flight_delivery_blocks_new_image(self) -> None:
        plan = build_intent_plan("画一张")
        decision = decide_delivery_pacing(
            plan, history={"in_flight": 1}, now=10.0
        )
        self.assertFalse(decision.allow)
        self.assertIn("in flight", decision.reason)

    def test_follow_up_text_is_never_a_fake_success(self) -> None:
        text = build_follow_up_text({"pending_follow_up": "接着上面的说"})
        self.assertEqual(text, "接着上面的说")
        self.assertNotIn("已发", text)
        self.assertNotIn("照片来了", text)
        self.assertNotIn("生成完成", text)


if __name__ == "__main__":
    unittest.main()
