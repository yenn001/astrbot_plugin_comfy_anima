"""回归：点名 canonical 角色时，原图的发色/瞳色必须从反推事实里剔除。

实测病根（2026-10-04，提示词原文为证）：
  反推事实含 "long blue-gray hair" → _filter_character_appearance_overrides 看到
  文本里有 hair，就认为【用户自己指定了发色】，于是把锚点里的 blonde hair 整条丢掉
  → 强制校验不再报缺 → 任务"成功"但成图仍是原图发色（时好时坏，取决于反推是否提到发色）。

修法：点名角色时从 positive_tags 里剔除"颜色词 + hair/eyes"里的颜色部分；
非颜色特征（long hair / side braid / hair ornament / ahoge）必须原样保留。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs


class StripAppearanceColorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.mod = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.reverse_prompt"
        )

    def _request(self, tags: str, *, strip: bool) -> str:
        result = self.mod.ReversePromptResult(positive_tags=tags)  # type: ignore[call-arg]
        return result.semantic_redraw_request("兔女郎，丝袜", "balanced",
                                              strip_appearance_colors=strip)

    def test_color_is_removed_when_stripping(self) -> None:
        text = self._request("long blue-gray hair, blue eyes, halo", strip=True)
        self.assertNotIn("blue-gray hair", text)
        self.assertNotIn("gray hair", text)
        self.assertIn("long hair", text)      # 长度保留
        self.assertIn("halo", text)           # 非颜色特征保留

    def test_non_color_traits_are_kept(self) -> None:
        tags = "hair ornament, ahoge, side braid, long hair, hair between eyes"
        text = self._request(tags, strip=True)
        for trait in ("hair ornament", "ahoge", "side braid", "long hair"):
            self.assertIn(trait, text)

    def test_without_stripping_nothing_changes(self) -> None:
        """没点名角色（纯图片编辑）时必须原样保留原图颜色。"""

        text = self._request("long blue-gray hair", strip=False)
        self.assertIn("blue-gray hair", text)

    def test_user_words_are_never_touched(self) -> None:
        result = self.mod.ReversePromptResult(positive_tags="blue hair")  # type: ignore[call-arg]
        text = result.semantic_redraw_request(
            "把头发改成粉色", "balanced", strip_appearance_colors=True
        )
        self.assertIn("把头发改成粉色", text)   # 用户的话一字不动


if __name__ == "__main__":
    unittest.main()
