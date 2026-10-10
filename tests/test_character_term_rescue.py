"""名字被写歪时，用"索引自己的 canonical + 去分隔符一致性"确认身份。

实测：导演会把角色写成 `rio (bluearchive)`，而规范 tag 是 `rio_(blue_archive)`。
索引其实能给出正确 canonical，但严格校验标为未验证 -> 插件降级 -> 丢角色 LoRA。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
IDX = importlib.import_module("astrbot_plugin_comfy_anima.services.danbooru_index")


class _FakeIndex(IDX.DanbooruTagIndex):
    """只替换 lookup，验证 resolve_candidate 的判定逻辑。"""

    def __init__(self, mapping):
        self._mapping = mapping

    def lookup(self, value, category=""):
        entry = self._mapping.get(IDX.normalize_tag(value))
        if entry is None:
            return SimpleNamespace(verified=False, canonical_tag="", tag="")
        verified, canonical = entry
        return SimpleNamespace(verified=verified, canonical_tag=canonical, tag=canonical)


class SquashIdentityTests(unittest.TestCase):
    def test_separators_do_not_matter(self) -> None:
        self.assertEqual(
            IDX._squash_identity("rio (bluearchive)"),
            IDX._squash_identity(r"rio_\(blue_archive\)"),
        )
        self.assertEqual(
            IDX._squash_identity("Monika  Weisswind"),
            IDX._squash_identity("monika_weisswind"),
        )

    def test_different_identities_stay_different(self) -> None:
        self.assertNotEqual(
            IDX._squash_identity("rio_(blue_archive)"),
            IDX._squash_identity("rio_natsume"),
        )


class ResolveCandidateTests(unittest.TestCase):
    def _index(self, mapping):
        return _FakeIndex({IDX.normalize_tag(k): v for k, v in mapping.items()})

    def test_malformed_term_is_confirmed(self) -> None:
        index = self._index({
            "rio (bluearchive)": (False, "rio_(blue_archive)"),
            "rio_(blue_archive)": (True, "rio_(blue_archive)"),
        })
        result = index.resolve_candidate("rio (bluearchive)", "character")
        self.assertTrue(result.verified)
        self.assertEqual(result.canonical_tag, "rio_(blue_archive)")

    def test_different_canonical_is_not_forced(self) -> None:
        # 索引给的 canonical 与输入不是同一身份 -> 不得强行确认
        index = self._index({
            "rio": (False, "rio_(blue_archive)"),
        })
        result = index.resolve_candidate("rio", "character")
        self.assertFalse(result.verified)

    def test_already_verified_passes_through(self) -> None:
        index = self._index({"rio_(blue_archive)": (True, "rio_(blue_archive)")})
        self.assertTrue(index.resolve_candidate("rio_(blue_archive)", "character").verified)

    def test_unknown_term_is_unchanged(self) -> None:
        index = self._index({})
        self.assertFalse(index.resolve_candidate("nobody_here", "character").verified)


class RescueWiringTests(unittest.TestCase):
    def test_gate_rescues_before_marking_unverified(self) -> None:
        from pathlib import Path

        main = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("def _rescue_character_resolution(", main)
        self.assertIn("resolution = self._rescue_character_resolution(", main)
        # 抢救必须发生在"未验证"分支内部、且在记录降级事件之前
        gate = main.find("if not resolution.verified:")
        rescue = main.find("resolution = self._rescue_character_resolution(")
        self.assertGreater(rescue, gate)


if __name__ == "__main__":
    unittest.main()
