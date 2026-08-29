"""Tests for deterministic ordinary-chat intent classification."""

import unittest

from ..services.chat_intent_classifier import (
    INTENT_CLARIFY,
    INTENT_DEBUG_ONLY,
    INTENT_DRAW_NEW,
    INTENT_EDIT_LAST_IMAGE,
    INTENT_QUERY_ONLY,
    classify_chat_intent,
)


class ChatIntentClassifierTests(unittest.TestCase):
    def test_debug_priority_beats_continuation(self) -> None:
        decision = classify_chat_intent("检查一下日志看看怎么回事", has_recipe=True)
        self.assertEqual(decision.intent, INTENT_DEBUG_ONLY)
        self.assertFalse(decision.visual_delivery)

    def test_draw_a_set_is_visual_delivery(self) -> None:
        decision = classify_chat_intent("用角色达妮娅预设组合，画一套jk情趣制服给我看看")
        self.assertEqual(decision.intent, INTENT_DRAW_NEW)
        self.assertTrue(decision.visual_delivery)

    def test_want_to_see_photo_is_visual_delivery(self) -> None:
        decision = classify_chat_intent("想看你的自拍")
        self.assertEqual(decision.intent, INTENT_DRAW_NEW)
        self.assertTrue(decision.visual_delivery)

    def test_what_are_you_doing_is_debug_not_draw(self) -> None:
        decision = classify_chat_intent("我想看你在干嘛")
        self.assertEqual(decision.intent, INTENT_DEBUG_ONLY)
        self.assertFalse(decision.visual_delivery)

    def test_draw_scene_with_doing_phrase_is_draw(self) -> None:
        decision = classify_chat_intent("画一张你在干嘛的图")
        self.assertEqual(decision.intent, INTENT_DRAW_NEW)
        self.assertTrue(decision.visual_delivery)

    def test_continuation_with_recipe(self) -> None:
        decision = classify_chat_intent("再拍一张", has_recipe=True)
        self.assertEqual(decision.intent, INTENT_DRAW_NEW)
        self.assertTrue(decision.needs_previous_image)
        self.assertTrue(decision.visual_delivery)

    def test_continuation_without_recipe_clarifies(self) -> None:
        decision = classify_chat_intent("现在发给我", has_recipe=False)
        self.assertEqual(decision.intent, INTENT_CLARIFY)
        self.assertTrue(decision.needs_previous_image)
        self.assertFalse(decision.visual_delivery)

    def test_persistent_photo_mode_is_draw_new(self) -> None:
        decision = classify_chat_intent("照片，以后都给我照片")
        self.assertEqual(decision.intent, INTENT_DRAW_NEW)
        self.assertFalse(decision.needs_previous_image)

    def test_explicit_edit(self) -> None:
        decision = classify_chat_intent("把上一张换个背景")
        self.assertEqual(decision.intent, INTENT_EDIT_LAST_IMAGE)
        self.assertTrue(decision.needs_previous_image)

    def test_query_only(self) -> None:
        decision = classify_chat_intent("查一下有哪些角色预设")
        self.assertEqual(decision.intent, INTENT_QUERY_ONLY)
        self.assertFalse(decision.visual_delivery)

    def test_ambiguous_clarifies(self) -> None:
        decision = classify_chat_intent("达妮娅那样子来一下")
        self.assertEqual(decision.intent, INTENT_CLARIFY)

    def test_empty_message_clarifies(self) -> None:
        decision = classify_chat_intent("")
        self.assertEqual(decision.intent, INTENT_CLARIFY)


if __name__ == "__main__":
    unittest.main()
