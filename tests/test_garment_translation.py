"""中文服饰词 → Danbooru tag 的覆盖与"丢关键结构"回归。

A1 内置词典**按键长从长到短做子串匹配**，所以一个更长、更具体的说法若不在词典里，
匹配会退化到更短的键上，把区分性的部分丢掉。实证案例：用户说「吊带丝袜」，
词典只有「吊带袜」与「丝袜」——而"吊带袜"并不是"吊带丝袜"的子串（字序为 吊带·丝·袜），
于是命中「丝袜」→ `pantyhose`，**"吊带"在翻译这一步就丢了**，成图自然没有吊带结构。

本测试按代码同样的方式（最长键优先的子串匹配）复核词典数据。
"""

import importlib
import re
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# 这些说法必须命中一个**含区分性结构**的词条
GARTER_PHRASES = (
    "吊带袜",
    "吊带丝袜",
    "吊带长筒袜",
    "蕾丝吊带袜",
)


class GarmentDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.chinese_prompt_translator"
        )
        cls.dictionary: dict[str, str] = dict(module._A1_DICTIONARY)

    def _longest_match(self, phrase: str) -> tuple[str, str]:
        """按代码的方式取最长命中键（`sorted(..., key=len, reverse=True)`）。"""

        for key in sorted(self.dictionary, key=len, reverse=True):
            if key in phrase:
                return key, self.dictionary[key]
        return "", ""

    def test_garter_phrases_keep_the_garter_structure(self) -> None:
        """任何"吊带X袜"说法都不得退化成没有吊带的普通袜。"""

        for phrase in GARTER_PHRASES:
            with self.subTest(phrase=phrase):
                key, value = self._longest_match(phrase)
                self.assertTrue(key, f"{phrase} 未命中任何词条")
                self.assertIn(
                    "garter",
                    value,
                    f"{phrase} 命中「{key}」→ {value!r}，丢失了吊带结构",
                )

    def test_diao_dai_si_wa_is_a_key(self) -> None:
        """最长匹配必须落在 4 字的词条上，而不是 2 字的「丝袜」。"""

        key, value = self._longest_match("吊带丝袜")
        self.assertEqual(key, "吊带丝袜")
        self.assertIn("thighhighs", value)

    def test_matching_is_longest_key_first(self) -> None:
        """复核匹配语义本身：短键不得抢在长键之前。"""

        keys = sorted(self.dictionary, key=len, reverse=True)
        self.assertEqual(keys[0], max(self.dictionary, key=len))
        # 「吊带袜」不是「吊带丝袜」的子串（这正是当初退化的原因）
        self.assertNotIn("吊带袜", "吊带丝袜")
        self.assertIn("丝袜", "吊带丝袜")

    def test_plain_stockings_still_map_to_stockings(self) -> None:
        """没有吊带的说法不应被误加吊带。"""

        for phrase, expected in (
            ("过膝袜", "thighhighs"),
            ("长筒袜", "thighhighs"),
            ("连裤袜", "pantyhose"),
            ("丝袜", "pantyhose"),
        ):
            with self.subTest(phrase=phrase):
                key, value = self._longest_match(phrase)
                self.assertEqual(key, phrase)
                self.assertEqual(value, expected)
                self.assertNotIn("garter", value)

    def test_no_bare_diao_dai_key(self) -> None:
        """「吊带」单独成键会把吊带裙误判成吊带袜，必须不存在。"""

        self.assertNotIn("吊带", self.dictionary)


class GarmentKeywordCoverageTests(unittest.TestCase):
    """槽位诊断词表必须覆盖实际会出现的服装词。"""

    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_clothing_markers_cover_common_garments(self) -> None:
        markers = self.main._PROMPT_TAG_SLOT_KEYWORDS["clothing"]
        for term in (
            "thighhighs",
            "pantyhose",
            "garter straps",
            "stockings",
            "nightgown",
            "pajamas",
            "lingerie",
        ):
            with self.subTest(term=term):
                self.assertIn(term, markers)

    def test_markers_are_lowercase_for_casefold_matching(self) -> None:
        """计数时用 casefold 比较，词表必须全小写，否则永远匹配不到。"""

        for slot, keywords in self.main._PROMPT_TAG_SLOT_KEYWORDS.items():
            for keyword in keywords:
                with self.subTest(slot=slot, keyword=keyword):
                    self.assertEqual(keyword, keyword.casefold())


if __name__ == "__main__":
    unittest.main()
