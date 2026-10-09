"""用户点名维度必须前置：位置校验 + 修复指令 + 设置项。

实测依据：契约已要求"紧跟角色块"，但 LLM 只做到写进去 —— upper body 落在第 20/21 个
tag，随后仍出全身。故在既有锚点通道上加位置校验，并给修复回路配一条明确指令。
"""

import importlib
import json
import re
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
MAIN = importlib.import_module("astrbot_plugin_comfy_anima.main")
MODELS = importlib.import_module("astrbot_plugin_comfy_anima.models")
CONTRACTS = importlib.import_module("astrbot_plugin_comfy_anima.services.prompt_contracts")

ROOT = Path(__file__).resolve().parents[1]


class PositionEnforcementTests(unittest.TestCase):
    def test_tag_set_is_single_source(self) -> None:
        """main 侧的中英对照表键必须与契约模块的标签集合完全一致。"""

        table_tags = {tag for tag, _variants in MAIN._USER_PRIORITY_ANCHOR_TERMS}
        self.assertEqual(table_tags, set(CONTRACTS.USER_PRIORITY_ANCHOR_TAGS))

    def test_setting_defaults_to_sixteen(self) -> None:
        settings = MODELS.PluginSettings.from_mapping({})
        self.assertEqual(settings.user_priority_anchor_max_index, 16)
        self.assertEqual(
            MODELS.PluginSettings.from_mapping(
                {"user_priority_anchor_max_index": -3}
            ).user_priority_anchor_max_index,
            0,
        )

    def test_schema_registers_the_setting(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(schema["user_priority_anchor_max_index"]["default"], 16)

    def test_director_checks_position_and_repairs(self) -> None:
        src = (ROOT / "services" / "prompt_director.py").read_text(encoding="utf-8")
        self.assertIn("USER_PRIORITY_ANCHOR_TAGS", src)
        self.assertIn("user_priority_anchor_late:", src)
        self.assertIn("user_priority_anchor_max_index", src)
        # 修复指令必须明确要求前置并写反项到负面
        self.assertIn("directly AFTER the character/trigger", src)
        self.assertIn("`full body` when the user asked for an upper body", src)

    def test_late_position_is_detected_by_the_rule(self) -> None:
        """复现实测数据：第 20/21 个 tag 应判为过晚，第 3 个应通过。"""

        def late(prompt: str, anchors: tuple[str, ...], limit: int = 16) -> list[str]:
            items = [i.strip().casefold() for i in prompt.split(",") if i.strip()]
            out = []
            for anchor in anchors:
                key = anchor.casefold()
                pos = next((n for n, it in enumerate(items) if key in it), None)
                if pos is not None and pos >= limit:
                    out.append(anchor)
            return out

        observed = (
            "@rurudo, deepseek, blue eyes, blue hair, maid, maid headdress, black collar, "
            "blue bow, dark blue dress, dark blue shoes, gold embroidery, gradient hair, "
            "long hair, whale ears, whale print, whale tail, white frilled apron, "
            "white thighhighs, 1girl, solo, upper body, looking at viewer"
        )
        self.assertEqual(late(observed, ("upper body",)), ["upper body"])
        good = "deepseek, upper body, blue eyes, blue hair, maid, dark blue dress"
        self.assertEqual(late(good, ("upper body",)), [])


if __name__ == "__main__":
    unittest.main()
