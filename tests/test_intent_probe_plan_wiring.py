"""3.1.442：`intent_router_probe_plan` 接线。

该开关此前只被装载、从未被读取。现在关闭它会让意图计划不再要求任何资产探测，
导演因而走单阶段直出；默认开启，出厂行为不变。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs

DRAW_REQUEST = "给我看看你现在的样子"


class IntentProbePlanWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, *, probe_plan: bool):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = SimpleNamespace(
            intent_router_probe_plan=probe_plan,
            enable_visual_task_intent=True,
        )
        plugin._requested_subject_hint = lambda message: ""
        return plugin

    def test_enabled_keeps_plan_probes(self) -> None:
        """默认开启：意图计划保留探针（出厂行为不变）。"""

        plan = self._plugin(probe_plan=True)._build_auto_draw_intent_plan(DRAW_REQUEST)
        self.assertTrue(
            plan.required_probes or plan.optional_probes,
            "开启时应当仍然要求资产探测",
        )

    def test_disabled_clears_probes_only(self) -> None:
        """关闭：清空探针，但意图判定与身份要求保持不变。"""

        baseline = self._plugin(
            probe_plan=True
        )._build_auto_draw_intent_plan(DRAW_REQUEST)
        disabled = self._plugin(
            probe_plan=False
        )._build_auto_draw_intent_plan(DRAW_REQUEST)

        self.assertEqual(disabled.required_probes, ())
        self.assertEqual(disabled.optional_probes, ())
        self.assertEqual(disabled.all_probes, ())
        # 其余字段不得被开关影响
        self.assertEqual(disabled.intent, baseline.intent)
        self.assertEqual(disabled.visual_delivery, baseline.visual_delivery)
        self.assertEqual(disabled.identity_required, baseline.identity_required)
        self.assertEqual(disabled.requested_subject, baseline.requested_subject)


if __name__ == "__main__":
    unittest.main()
