"""3.1.446：tag 串下限的计数口径。

Anima 成图质量由 tag 块与自然语言场景句共同承载，所以下限只作用于 **tag 块**：
先把混合提示词在句子边界切开，再只数 tag 侧。若把场景句里的逗号也算进来，
计数就会虚高，下限形同虚设。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs

HYBRID = (
    "1girl, denia_(wuthering_waves), red hair, long hair, smile, "
    "white dress, necklace, thighhighs. "
    "She stands by the window looking at the rain, with soft rim lighting."
)
TAGS_ONLY = "1girl, red hair, smile, white dress, necklace"
WEIGHTED = "(red hair:1.2), smile, white dress"
VERSIONED = "model v1.2 style, smile, white dress"


class PromptTagMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_counts_tag_block_only(self) -> None:
        """场景句（含内部逗号）不得计入 tag 数。"""

        metrics = self.main._prompt_tag_metrics(HYBRID)
        # tag 块有 8 项：1girl / denia / red hair / long hair / smile /
        # white dress / necklace / thighhighs
        self.assertEqual(metrics["tag_count"], 8)

    def test_sentence_commas_do_not_inflate(self) -> None:
        without_sentence = self.main._prompt_tag_metrics(TAGS_ONLY)
        with_sentence = self.main._prompt_tag_metrics(
            TAGS_ONLY + ". She stands by the window, looking at the rain."
        )
        self.assertEqual(with_sentence["tag_count"], without_sentence["tag_count"])

    def test_weighted_groups_are_not_split(self) -> None:
        """括号内的逗号不得拆成多项。"""

        metrics = self.main._prompt_tag_metrics(WEIGHTED)
        self.assertEqual(metrics["tag_count"], 3)

    def test_version_string_is_not_a_sentence_boundary(self) -> None:
        metrics = self.main._prompt_tag_metrics(VERSIONED)
        self.assertEqual(metrics["tag_count"], 3)

    def test_slot_markers_report_thin_slots(self) -> None:
        """槽位标记只统计 tag 块，用于诊断"哪个槽位没进 tag 串"。"""

        metrics = self.main._prompt_tag_metrics(HYBRID)
        markers = metrics["slot_markers"]
        self.assertEqual(set(markers), {
            "identity", "clothing", "action", "camera", "scene", "lighting",
        })
        self.assertGreater(markers["clothing"], 0)
        self.assertGreater(markers["identity"], 0)
        # 该样例的 "soft rim lighting" 只出现在场景句里、没进 tag 串，
        # 槽位标记据此报 0 —— 这正是"该槽位未被 tag 串覆盖"的诊断信号。
        self.assertEqual(markers["lighting"], 0)
        self.assertEqual(markers["camera"], 0)

    def test_slot_markers_ignore_the_scene_sentence(self) -> None:
        """把光效写进 tag 串才会被记为覆盖。"""

        tags_only = self.main._prompt_tag_metrics(
            "1girl, red hair, white dress, rim lighting, soft lighting"
        )
        self.assertGreater(tags_only["slot_markers"]["lighting"], 0)

    def test_empty_prompt_is_zero_not_an_error(self) -> None:
        metrics = self.main._prompt_tag_metrics("")
        self.assertEqual(metrics["tag_count"], 0)
        self.assertEqual(metrics["tag_block_chars"], 0)


class PromptTagFloorConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        cls.models = importlib.import_module("astrbot_plugin_comfy_anima.models")

    def test_floor_defaults_to_twenty(self) -> None:
        settings = self.models.PluginSettings.from_mapping({})
        self.assertEqual(settings.min_prompt_tags, 20)

    def test_floor_is_clamped(self) -> None:
        self.assertEqual(
            self.models.PluginSettings.from_mapping(
                {"min_prompt_tags": -5}
            ).min_prompt_tags,
            0,
        )
        self.assertEqual(
            self.models.PluginSettings.from_mapping(
                {"min_prompt_tags": 999}
            ).min_prompt_tags,
            60,
        )

    def test_floor_is_saveable_from_the_console(self) -> None:
        self.assertIn("min_prompt_tags", self.main.WEB_UI_EDITABLE_FIELDS)


if __name__ == "__main__":
    unittest.main()
