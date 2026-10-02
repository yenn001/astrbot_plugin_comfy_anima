"""档案过期不等于证据失效：TTL 只安排刷新，不再丢弃已验证聚合。

事故链（2026-10-02）：toki 的档案（blonde hair 0.98 / 52 帖）因超过 TTL 被
``get()`` 判成不存在 → 去 Danbooru 现取只回 1 条 → 样本不足 → 无锚点 → 不成金发。
"""

import importlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
_MOD = importlib.import_module(
    "astrbot_plugin_comfy_anima.services.danbooru_character_profile"
)


def _profile(canonical: str, fetched_at: float):
    return _MOD.CharacterAppearanceProfile(
        canonical_tag=canonical,
        appearance_tags=("blonde hair", "blue eyes", "halo"),
        sample_count=52,
        support=(("blonde hair", 0.98), ("blue eyes", 0.98), ("halo", 1.0)),
        fetched_at=fetched_at,
        source="danbooru_gallery",
    )


class StaleProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "profiles.json"
        self.store = _MOD.CharacterAppearanceProfileStore(self.path, ttl_seconds=3600)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fresh_profile_is_returned_by_both_readers(self) -> None:
        fresh = _profile("toki_(blue_archive)", time.time())
        self.store.put(fresh)
        self.assertIsNotNone(self.store.get("toki_(blue_archive)"))
        self.assertIsNotNone(self.store.get_including_stale("toki_(blue_archive)"))
        self.assertFalse(self.store.is_stale(fresh))

    def test_expired_profile_is_hidden_from_get_but_available_as_evidence(self) -> None:
        """核心：过期档案 get() 不返回，但仍可作为证据使用。"""

        old = _profile("toki_(blue_archive)", time.time() - 60 * 86400)
        self.store.put(old)
        self.assertIsNone(self.store.get("toki_(blue_archive)"))
        stale = self.store.get_including_stale("toki_(blue_archive)")
        self.assertIsNotNone(stale)
        self.assertIn("blonde hair", stale.appearance_tags)
        self.assertTrue(self.store.is_stale(stale))

    def test_stale_lookup_is_normalized(self) -> None:
        old = _profile("toki_(blue_archive)", time.time() - 60 * 86400)
        self.store.put(old)
        self.assertIsNotNone(self.store.get_including_stale("Toki_(Blue_Archive)"))

    def test_unknown_character_still_returns_nothing(self) -> None:
        """不猜：库里没有的角色，两个读取口都必须返回 None。"""

        self.assertIsNone(self.store.get("nobody_(unknown_work)"))
        self.assertIsNone(self.store.get_including_stale("nobody_(unknown_work)"))

    def test_negative_cache_constant_is_bounded(self) -> None:
        main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        self.assertGreater(main.APPEARANCE_UNRESOLVABLE_TTL_SECONDS, 0)
        self.assertLessEqual(main.APPEARANCE_UNRESOLVABLE_TTL_SECONDS, 24 * 3600)


if __name__ == "__main__":
    unittest.main()
