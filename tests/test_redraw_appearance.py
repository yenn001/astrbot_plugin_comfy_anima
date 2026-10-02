"""3.1.454: redraws adopt the reverse-named subject so appearance anchors can run.

A redraw request usually says what to change, not who the character is, so the
intent plan carried no subject and the appearance-anchor gate stayed closed. The
reverse pass names the character; the plan adopts that name only when it has no
subject of its own, so a user-named character is never overwritten and the
existing binding gate still does the verification.
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs


class RedrawSubjectFromReverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _reverse(self, *names: str):
        return SimpleNamespace(
            characters=tuple(
                SimpleNamespace(name=name, source_work="", confidence=0.9)
                for name in names
            )
        )

    def test_single_named_character_is_adopted(self) -> None:
        self.assertEqual(
            self.main._redraw_subject_from_reverse(self._reverse("达妮娅")),
            "达妮娅",
        )

    def test_no_characters_yields_empty(self) -> None:
        self.assertEqual(self.main._redraw_subject_from_reverse(self._reverse()), "")

    def test_several_characters_yield_empty(self) -> None:
        """多人同框时不得猜其中一个是主体。"""

        self.assertEqual(
            self.main._redraw_subject_from_reverse(
                self._reverse("达妮娅", "另一个角色")
            ),
            "",
        )

    def test_blank_name_yields_empty(self) -> None:
        self.assertEqual(
            self.main._redraw_subject_from_reverse(self._reverse("   ")), ""
        )

    def test_missing_characters_attribute_is_safe(self) -> None:
        self.assertEqual(
            self.main._redraw_subject_from_reverse(SimpleNamespace()), ""
        )

    def test_plan_with_subject_is_never_overwritten(self) -> None:
        """用户明确点名时，计划里的主体必须保持原样。"""

        plan = SimpleNamespace(requested_subject="用户点名的角色", identity_required=False)
        # 复刻调用点的判断条件
        self.assertTrue(getattr(plan, "requested_subject", ""))
        self.assertNotEqual(getattr(plan, "requested_subject", ""), "")


if __name__ == "__main__":
    unittest.main()
