"""回归：用户点名的 canonical tag 必须保持完整，外貌查询才不会问错名字。

实测事故（2026-10-03，事件实证）：
  用户在要求里写 "角色是toki_(Blue_Archive)"，
  外貌查询实际发出的是 canonical="archive)"（括号部分被主体解析删掉 ✗）
  或 canonical="background"（从反推事实的 "plain white background" 里捞到别名 ✗）
  → character_swap_appearance_unavailable → 零锚点 → 提示词里没有 blonde hair。

用户对照实验：**同样的 img2img 强度**下，手动加上金发 tag 与不加是两个结果——
即唯一缺的是 tag 本身，因此本回归直接钉住"tag 是否被正确解析出来"。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs


class AppearanceCanonicalHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_user_command_keeps_the_whole_tag(self) -> None:
        """用户原话：必须是完整的 toki_(blue_archive)，而不是 archive)。"""

        self.assertEqual(
            self.main._appearance_canonical_hint(
                "/重绘 角色是toki_(Blue_Archive)；兔女郎，女仆，吊带袜。"
            ),
            "toki_(blue_archive)",
        )

    def test_case_and_spacing_are_normalized(self) -> None:
        for text in (
            "角色是 Toki_(Blue_Archive)",
            "重绘 角色是toki_( blue_archive )",
            "把 Toki_(Blue_Archive) 换成兔女郎",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.main._appearance_canonical_hint(text),
                    "toki_(blue_archive)",
                )

    def test_plain_name_without_work_yields_nothing(self) -> None:
        """没有作品括号时返回空——外貌档案按 canonical 建键，宁可不查也不查错。"""

        self.assertEqual(self.main._appearance_canonical_hint("角色是达妮娅"), "")
        self.assertEqual(self.main._appearance_canonical_hint("画一张自拍"), "")

    def test_reverse_facts_text_never_invents_a_subject(self) -> None:
        """反推事实里的 plain white background 绝不能被当成角色。"""

        facts = (
            "可观察 Tags：1girl, solo, long hair, blue eyes, "
            "plain white background, school uniform"
        )
        self.assertEqual(self.main._appearance_canonical_hint(facts), "")

    def test_first_tag_wins_when_several_appear(self) -> None:
        self.assertEqual(
            self.main._appearance_canonical_hint(
                "把 toki_(Blue_Archive) 换成 rio_(Blue_Archive)"
            ),
            "toki_(blue_archive)",
        )

    def test_empty_input_is_safe(self) -> None:
        self.assertEqual(self.main._appearance_canonical_hint(""), "")
        self.assertEqual(self.main._appearance_canonical_hint(None), "")


if __name__ == "__main__":
    unittest.main()
