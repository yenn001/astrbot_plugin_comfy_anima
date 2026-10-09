"""P1 回归钉子：契约与提示词必须符合 ANIMA3 v3.0（不再要求光线、改为分档、句数放宽）。"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PromptTemplateV3P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = (ROOT / "services" / "prompt_contracts.py").read_text(
            encoding="utf-8"
        )
        cls.creative = (ROOT / "prompts" / "director_creative_default.txt").read_text(
            encoding="utf-8"
        )
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    # ---- 冲突① 光线 ----
    def test_contracts_no_longer_demand_lighting(self) -> None:
        for bad in ("main-light", "main/rim light"):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, self.contracts)
        self.assertNotIn("主光", self.creative)
        self.assertNotIn("光效氛围", self.creative)

    def test_contracts_forbid_lighting_tags(self) -> None:
        self.assertIn("Do NOT emit lighting", self.contracts)
        self.assertIn("不写光线", self.creative)

    # ---- 冲突② 数量分档 ----
    def test_counts_use_scene_bands(self) -> None:
        for band in ("16-30", "22-38", "30-48"):
            with self.subTest(band=band):
                self.assertIn(band, self.contracts)
                self.assertIn(band, self.creative)
        # 旧的"只设下限不设上限"必须消失
        self.assertNotIn("只设下限，不设上限", self.creative)
        self.assertNotIn("roughly 14-32", self.contracts)
        self.assertNotIn("30-65", self.contracts)

    # ---- 冲突③ 句数 ----
    def test_sentence_count_relaxed(self) -> None:
        self.assertNotIn("exactly one present-tense scene sentence", self.contracts)
        self.assertIn("zero to three", self.contracts)
        self.assertIn("0–3", self.creative)

    # ---- 槽位 ----
    def test_lighting_slot_removed(self) -> None:
        block = re.search(
            r"_PROMPT_TAG_SLOT_KEYWORDS[^{]*\{(?:[^{}]|\{[^{}]*\})*\}",
            self.main,
            re.S,
        )
        self.assertIsNotNone(block)
        self.assertNotIn('"lighting":', block.group(0))

    # ---- 设置默认值 ----
    def test_min_prompt_tags_default_is_16(self) -> None:
        models = (ROOT / "models.py").read_text(encoding="utf-8")
        self.assertRegex(models, r"min_prompt_tags: int = 16")
        self.assertIn('data.get("min_prompt_tags"), 16', models)

    def test_schema_default_matches(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        entry = schema.get("min_prompt_tags")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("default"), 16)


if __name__ == "__main__":
    unittest.main()
