"""用户点名维度（景别/机位/视线）必须能与外貌锚点走同一强制通道。

背景：一条"上半身"的指令连续四次出成全身。取证发现提示词里确实有 upper body，
但 LoRA 触发词占据最前位、且该 LoRA 训练以全身为主，尾部要求压不住。
结论：不靠人工负面清单，而是让 LLM 逐次判断 + 插件校验（复用外貌锚点那套）。
"""

import importlib
import re
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
MAIN = importlib.import_module("astrbot_plugin_comfy_anima.main")

ROOT = Path(__file__).resolve().parents[1]


class UserPriorityAnchorDerivationTests(unittest.TestCase):
    def test_chinese_framing_words_map_to_tags(self) -> None:
        cases = {
            "给我画上半身的娅娅": ("upper body",),
            "来张全身的": ("full body",),
            "脸特写一张": ("close-up",),
            "仰视角度拍一张": ("from below",),
            "画背影": ("from behind",),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = MAIN._user_priority_anchors(text)
                self.assertIn(expected[0], got)

    def test_negated_or_absent_request_yields_nothing(self) -> None:
        self.assertEqual(MAIN._user_priority_anchors("娅娅在干嘛呢"), ())
        self.assertEqual(MAIN._user_priority_anchors(""), ())

    def test_multiple_dimensions_are_collected_once(self) -> None:
        got = MAIN._user_priority_anchors("上半身，仰视，看着镜头")
        self.assertEqual(got, ("upper body", "from below", "looking at viewer"))
        self.assertEqual(len(got), len(set(got)))


class UserPriorityAnchorWiringTests(unittest.TestCase):
    def test_both_director_call_sites_pass_priority_anchors(self) -> None:
        main_src = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertEqual(
            len(re.findall(r"required_appearance_anchors=tuple\(", main_src)),
            2,
            "两个导演调用点都应携带锚点（含用户点名维度）",
        )
        # 3.1.473 起两个调用点改为并集助手（用户消息 ∪ 请求文本），断言随之同步
        self.assertEqual(main_src.count("*_priority_anchors_for("), 2)
        self.assertEqual(main_src.count("def _priority_anchors_for("), 1)

    def test_contract_carries_the_general_rule(self) -> None:
        contracts = (ROOT / "services" / "prompt_contracts.py").read_text(encoding="utf-8")
        self.assertIn("USER_PRIORITY_ANCHOR_CONTRACT =", contracts)
        self.assertEqual(contracts.count("parts.append(USER_PRIORITY_ANCHOR_CONTRACT)"), 1)
        for phrase in (
            "immediately AFTER the character/trigger block",
            "add the opposite term to the negative prompt",
            "Never silently drop an explicit user requirement",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, contracts)

    def test_anchor_error_message_is_not_appearance_specific(self) -> None:
        src = (ROOT / "services" / "prompt_director.py").read_text(encoding="utf-8")
        self.assertIn("没有写入必须包含的锚点标签", src)
        self.assertNotIn("没有写入已验证角色外貌锚点", src)

    def test_english_tag_itself_is_recognised(self) -> None:
        """指令里直接写英文 tag 也必须算点名。

        实测：'/画图 1girl, upper body, blue hair, maid --llm' 原本返回 ()，
        于是位置校验静默失效，upper body 落第 19/22 位仍出全身。
        """

        cases = {
            "upper body": "upper body",
            "1girl, upper body, blue hair, maid": "upper body",
            "/draw 1girl, upper body, maid --llm": "upper body",
            "full body standing": "full body",
            "shot from above": "from above",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(expected, MAIN._user_priority_anchors(text))

    def test_no_false_positive_without_any_signal(self) -> None:
        self.assertEqual(MAIN._user_priority_anchors("娅娅在干嘛呢"), ())
        self.assertEqual(MAIN._user_priority_anchors("1girl, maid, blue hair"), ())

    def test_union_of_message_and_scene_text(self) -> None:
        """批量/续抽路径的通用消息 + 请求文本，两边的点名都要算上。"""

        class _Event:
            def __init__(self, message: str) -> None:
                self.message_str = message

        # 消息里没有点名，请求文本里有 -> 仍要识别出来
        self.assertEqual(
            MAIN._priority_anchors_for(_Event("再来几张"), "1girl, upper body, maid"),
            ("upper body",),
        )
        # 两边各有一个 -> 去重合并
        self.assertEqual(
            MAIN._priority_anchors_for(_Event("上半身来一张"), "full body not needed".replace("not needed", "").replace("full body ", "")),
            ("upper body",),
        )
        # 两边都有不同维度 -> 合并保序
        got = MAIN._priority_anchors_for(_Event("上半身"), "looking at viewer")
        self.assertEqual(got, ("upper body", "looking at viewer"))
        # 都没有 -> 空
        self.assertEqual(MAIN._priority_anchors_for(_Event("再来几张"), "1girl, maid"), ())


if __name__ == "__main__":
    unittest.main()
