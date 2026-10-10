"""未指定 --pipeline 时必须用 WebUI 默认管线，导演不得顶掉它。

实测：同一开关（enable_ttp_detail=True / anima_ttp_api.json / rtx 默认）下连画三张，
分别走了 rtx(TTP, 节点 458) / base / base —— 因为导演在 <pic pipeline="..."> 里
自行写了 pipeline，而代码把它当作兜底（`or instruction.pipeline`），
与插件自己的帮助文档"未指定时使用 WebUI 当前默认生图管线"相矛盾。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PipelineDefaultRespectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_generation_paths_ignore_the_director_pipeline(self) -> None:
        for fragment in (
            "selected_pipeline = requested_pipeline or instruction.pipeline",
            "pipeline=parsed_options.pipeline or instruction.pipeline,",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, self.main)

    def test_redraw_path_still_honours_the_director_pipeline(self) -> None:
        # 重绘（semantic redraw）不在本次改动范围：它的 pipeline 决定重绘走哪条工作流
        self.assertIn(
            "selected_pipeline = options.pipeline or instruction.pipeline", self.main
        )

    def test_user_choice_still_wins(self) -> None:
        # 用户显式 --pipeline 仍然优先（requested_pipeline / parsed_options.pipeline）
        self.assertIn("selected_pipeline = requested_pipeline", self.main)
        self.assertIn("pipeline=parsed_options.pipeline,", self.main)

    def test_default_still_applies_downstream(self) -> None:
        self.assertIn(
            "options.pipeline or self.settings.default_generation_pipeline", self.main
        )

    def test_matches_the_documented_behaviour(self) -> None:
        # 帮助文档写的就是"未指定时使用 WebUI 当前默认生图管线"
        self.assertIn("未指定时使用 WebUI 当前默认生图管线", self.main)


if __name__ == "__main__":
    unittest.main()
