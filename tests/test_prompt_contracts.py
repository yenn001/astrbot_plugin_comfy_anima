"""Task-scoped Prompt Contract v3 behavior tests."""

import unittest

from ..services.prompt_contracts import (
    TASK_CHARACTER_SWAP_EDIT,
    TASK_CONTROL_DRAW,
    TASK_DRAW,
    TASK_MASKED_REDRAW,
    TASK_PROMPT_PLAN,
    TASK_REVERSE_DRAW,
    TASK_SEMANTIC_REDRAW,
    build_director_contract,
    build_director_user_prompt,
    looks_like_conversation_draw_intent,
    normalize_task_kind,
    normalize_transport,
    transport_terminal_seal,
)


NON_MASKED_TASKS = (
    TASK_DRAW,
    TASK_PROMPT_PLAN,
    TASK_REVERSE_DRAW,
    TASK_SEMANTIC_REDRAW,
    TASK_CONTROL_DRAW,
    TASK_CHARACTER_SWAP_EDIT,
)


class PromptContractMatrixTests(unittest.TestCase):
    def test_semantic_redraw_contract_uses_selected_transport(self) -> None:
        contract = build_director_contract(
            task_kind=TASK_SEMANTIC_REDRAW,
            transport="json",
        )

        self.assertIn("Submit the rebuilt frame through\nthe selected transport", contract)
        self.assertIn("Return exactly one JSON object", contract)
        self.assertNotIn("<pic>", contract)

    def test_non_masked_tasks_accept_pic_json_and_function_transports(self) -> None:
        for task in NON_MASKED_TASKS:
            for transport in ("pic", "json", "function", "structured"):
                with self.subTest(task=task, transport=transport):
                    self.assertTrue(
                        build_director_contract(
                            task_kind=task,
                            transport=transport,
                        )
                    )

    def test_non_masked_tasks_reject_edit_transport(self) -> None:
        for task in NON_MASKED_TASKS:
            with self.subTest(task=task):
                with self.assertRaises(ValueError):
                    build_director_contract(task_kind=task, transport="edit")

    def test_masked_redraw_accepts_only_edit_transport(self) -> None:
        self.assertIn(
            "Return exactly one `<edit",
            build_director_contract(
                task_kind=TASK_MASKED_REDRAW,
                transport="edit",
            ),
        )
        for transport in ("pic", "json", "function", "structured"):
            with self.subTest(transport=transport):
                with self.assertRaises(ValueError):
                    build_director_contract(
                        task_kind=TASK_MASKED_REDRAW,
                        transport=transport,
                    )

    def test_unknown_task_and_transport_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            normalize_task_kind("typo-task")
        with self.assertRaises(ValueError):
            normalize_transport("xml")
        with self.assertRaises(ValueError):
            build_director_contract(task_kind="typo-task", transport="pic")
        with self.assertRaises(ValueError):
            build_director_user_prompt(
                "scene",
                task_kind=TASK_DRAW,
                transport="xml",
            )
        with self.assertRaises(ValueError):
            transport_terminal_seal("xml")

    def test_character_swap_edit_has_dedicated_user_action(self) -> None:
        prompt = build_director_user_prompt(
            "change only the jacket",
            task_kind=TASK_CHARACTER_SWAP_EDIT,
            transport="function",
        )

        self.assertIn("Apply only the requested non-identity edit", prompt)
        self.assertIn("preserve its current identity", prompt)
        self.assertIn("do not add the target identity", prompt)
        self.assertNotIn("Plan one Anima image", prompt)

    def test_prompt_plan_does_not_force_composition_or_density(self) -> None:
        contract = build_director_contract(
            task_kind=TASK_PROMPT_PLAN,
            expansion_mode="ultra",
            transport="json",
        )
        user_prompt = build_director_user_prompt(
            "change the weather only",
            task_kind=TASK_PROMPT_PLAN,
            expansion_mode="ultra",
            transport="json",
        )

        self.assertNotIn("Positive prompt composition:", contract)
        self.assertNotIn("Density: Standard", contract)
        self.assertNotIn("Density: Ultra", contract)
        self.assertNotIn("density=", user_prompt)
        self.assertIn("preserving every unchanged baseline field", user_prompt)


class ConversationDrawIntentTests(unittest.TestCase):
    def test_explicit_chinese_draw_requests_are_detected(self) -> None:
        messages = (
            "帮我画飞鸟马时穿兔女郎自拍",
            "来个赛博朋克雨夜少女",
            "想看飞鸟马时穿兔女郎",
            "整点暖色日系插画",
            "给我看看莉音在教室门口的画面",
            "用风格006画初音未来",
            "不要介绍了，直接画飞鸟马时",
            "不要画旧角色，画飞鸟马时",
            "别查了，给我画飞鸟马时",
        )

        for message in messages:
            with self.subTest(message=message):
                self.assertTrue(looks_like_conversation_draw_intent(message))

    def test_query_then_draw_requests_are_detected(self) -> None:
        messages = (
            "查一下飞鸟马时的 LoRA，然后给我画一张自拍",
            "找一个适合的 LoRA 画飞鸟马时",
            "查一下有没有 Toki LoRA，直接画出来",
            "搜索风格006，找到后就画飞鸟马时",
            "有没有初音未来的角色 LoRA，有的话整点海边烟花",
            "find the Toki LoRA, then draw a portrait",
        )

        for message in messages:
            with self.subTest(message=message):
                self.assertTrue(looks_like_conversation_draw_intent(message))

    def test_negated_or_query_only_messages_do_not_draw(self) -> None:
        messages = (
            "不要画图，只告诉我有哪些风格",
            "不用生成图片，查一下飞鸟马时的 LoRA",
            "别给我画，只需要列出触发词",
            "我不是让你画图，我是在问有哪些工作流",
            "我不想看图，只想知道这个 LoRA 是什么",
            "查询 Toki LoRA，然后生成提示词，不要画图",
            "don't draw an image; list the available styles",
            "有哪些 LoRA 可以画飞鸟马时？",
            "给我看看风格006的触发词",
            "想看有哪些角色 LoRA",
            "这个 LoRA 能画什么？",
            "怎么画飞鸟马时？",
        )

        for message in messages:
            with self.subTest(message=message):
                self.assertFalse(looks_like_conversation_draw_intent(message))


if __name__ == "__main__":
    unittest.main()
