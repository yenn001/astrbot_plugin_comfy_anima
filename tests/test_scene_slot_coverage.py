"""诊断关键词表必须覆盖常见写法：否则"写了却报 0"会误导判断。

实测依据：用户明确要求空白背景，提示词里也有 white background / blank background，
但 scene 槽报 0（关键词表里没有 background 类词），我据此误判"场景偏薄"。
二审确认 slot_markers 只进一条"仅告警，不阻断出图"的文案，故补表零行为风险。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
MAIN = importlib.import_module("astrbot_plugin_comfy_anima.main")


class SceneSlotCoverageTests(unittest.TestCase):
    def test_blank_background_counts_as_scene(self) -> None:
        markers = MAIN._prompt_tag_metrics(
            "@rurudo, 1girl, solo, upper body, simple background, "
            "white background, blank background, daytime"
        )["slot_markers"]
        self.assertGreater(markers["scene"], 0, "白底/空白背景必须计入 scene")

    def test_common_words_are_counted_in_their_slots(self) -> None:
        cases = {
            "chest up": "camera",
            "looking at viewer": "camera",
            "smug": "action",
            "thumbs up": "action",
            "gradient hair": "identity",
            "maid headdress": "clothing",
        }
        for phrase, slot in cases.items():
            with self.subTest(phrase=phrase):
                markers = MAIN._prompt_tag_metrics("1girl, %s" % phrase)["slot_markers"]
                self.assertGreater(markers[slot], 0, "%s 应计入 %s" % (phrase, slot))

    def test_slot_set_is_unchanged(self) -> None:
        markers = MAIN._prompt_tag_metrics("1girl, maid")["slot_markers"]
        self.assertEqual(
            set(markers), {"identity", "clothing", "action", "camera", "scene"}
        )


if __name__ == "__main__":
    unittest.main()
