"""TTP 开关：WebUI 里必须找得到，且"开着无效"时必须明确告警。

实测：用户在 WebUI 搜"放大"找不到 TTP 开关（它的显示名是"TTP 瓦片细节增强"，
且被杀在通用开关里）；更关键的是开关即使打开，只要当前生成工作流档案没声明
"ttp" 变体（他绑的是 anima_rtx_api.json，variants=['rtx']），就完全无效且毫无提示。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TtpToggleVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        cls.workflow = (ROOT / "core" / "workflow.py").read_text(encoding="utf-8")

    # ---- A：找得到 ----
    def test_label_is_searchable_by_the_word_for_upscale(self) -> None:
        entry = self.schema["enable_ttp_detail"]
        self.assertIn("放大", entry["description"])
        self.assertIn("全局", entry["description"])

    def test_hint_states_the_three_conditions_and_the_switch_workflow(self) -> None:
        hint = self.schema["enable_ttp_detail"]["hint"]
        self.assertIn("enable_upscale", hint)
        self.assertIn("ttp 变体", hint)
        self.assertIn("anima_ttp_api.json", hint)

    def test_hint_keeps_the_cost_visible(self) -> None:
        self.assertIn("3-5 倍", self.schema["enable_ttp_detail"]["hint"])

    # ---- B：开着无效要告警 ----
    def test_missing_variant_is_warned(self) -> None:
        self.assertIn("未声明 'ttp' 变体", self.workflow)
        self.assertIn("本开关当前无效", self.workflow)

    def test_disabled_upscale_is_warned(self) -> None:
        self.assertIn("enable_upscale 已关闭", self.workflow)

    def test_warnings_fire_once(self) -> None:
        self.assertIn("_TTP_WARNED", self.workflow)
        self.assertIn("logger.warning", self.workflow)

    def test_ttp_variant_still_selected_when_possible(self) -> None:
        self.assertIn('variant_name = "ttp"', self.workflow)

    def test_manifest_with_ttp_variant_exists(self) -> None:
        manifest = ROOT / "workflow" / "manifests" / "anima_ttp_api.json"
        self.assertTrue(manifest.exists(), "切换目标档案必须存在")
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        variants = data.get("output_variants") or {}
        self.assertIn("ttp", variants)
        self.assertIn("rtx", variants)  # 关掉开关要能回退 RTX


if __name__ == "__main__":
    unittest.main()
