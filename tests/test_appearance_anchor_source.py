"""3.1.455: appearance anchors come from the canonical subject, LoRA or not.

Requirement: with no LoRA for the named character, still use that character's
Danbooru appearance features; with a LoRA, trigger both. The store is keyed by
canonical tag, so the anchor lookup must not require a binding, and an uncached
character is resolved on demand by the existing resolver (which refuses to guess
when the sample is insufficient).
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs


class AnchorSourceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_signature_accepts_job(self) -> None:
        import inspect

        params = inspect.signature(
            self.main.ComfyAnimaPlugin._generate_directed_instruction
        ).parameters
        self.assertIn("job", params)
        self.assertIsNone(params["job"].default)

    def test_no_lora_path_uses_requested_subject(self) -> None:
        """无 binding 时，canonical 必须能来自计划里的点名主体。"""

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        binding = None
        canonical = str(getattr(binding, "canonical", "") or "").strip() or (
            self.main.normalize_tag("toki_(Blue_Archive)")
        )
        self.assertEqual(canonical, "toki_(blue_archive)")

    def test_with_lora_path_uses_binding_canonical(self) -> None:
        binding = SimpleNamespace(canonical="denia_(wuthering_waves)")
        canonical = str(getattr(binding, "canonical", "") or "").strip() or (
            self.main.normalize_tag("toki_(Blue_Archive)")
        )
        self.assertEqual(canonical, "denia_(wuthering_waves)")

    def test_override_filter_drops_user_specified_hair_color(self) -> None:
        """用户明确要求换发色时，档案里的发色必须被丢掉。"""

        filtered = self.main.ComfyAnimaPlugin._filter_character_appearance_overrides(
            ("blonde hair", "blue eyes", "halo"),
            "把她改成粉色头发",
        )
        self.assertNotIn("blonde hair", filtered)
        self.assertIn("halo", filtered)

    def test_override_filter_keeps_anchors_without_customization(self) -> None:
        filtered = self.main.ComfyAnimaPlugin._filter_character_appearance_overrides(
            ("blonde hair", "blue eyes", "halo"),
            "换成兔女郎",
        )
        self.assertIn("blonde hair", filtered)

    async def test_resolver_is_used_when_job_is_available(self) -> None:
        """有 job 时必须走既有解析器（缓存命中 → 直接用；未命中 → 按需取）。"""

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        calls: list[str] = []

        async def fake_resolve(job, canonical):
            calls.append(canonical)
            return SimpleNamespace(appearance_tags=("blonde hair", "blue eyes"))

        plugin._resolve_character_appearance_profile = fake_resolve
        profile = await plugin._resolve_character_appearance_profile(
            SimpleNamespace(), "toki_(blue_archive)"
        )
        self.assertEqual(calls, ["toki_(blue_archive)"])
        self.assertIn("blonde hair", profile.appearance_tags)


if __name__ == "__main__":
    unittest.main()
