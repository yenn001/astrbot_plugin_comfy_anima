"""主题注册一致性：主题必须在四处同时登记，否则切换会失效或空白。

四处：
  1. web/theme.js      —— 首屏恢复白名单（避免闪主题）
  2. web/app.css       —— html[data-theme="X"] 变量与覆盖块
  3. web/app.js        —— themeMetaColors（applyTheme 用它校验主题名）
  4. web/index.html    —— #theme-select 的选项

任何一处漏登记，用户在选择器里就选不到、或选到后没有样式。
"""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


class ThemeRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.theme_js = (WEB / "theme.js").read_text(encoding="utf-8")
        cls.css = (WEB / "app.css").read_text(encoding="utf-8")
        cls.app_js = (WEB / "app.js").read_text(encoding="utf-8")
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")

    def _reboot_allowlist(self) -> set[str]:
        match = re.search(r"new Set\(\[([^\]]*)\]\)", self.theme_js)
        self.assertIsNotNone(match, "theme.js 里没有找到白名单")
        return set(re.findall(r'"([a-z]+)"', match.group(1)))

    def _css_themes(self) -> set[str]:
        """默认主题写在 :root，其余主题各有 html[data-theme="…"] 覆盖块。"""

        return set(re.findall(r'html\[data-theme="([a-z]+)"\] \{', self.css)) | {
            self._default_theme()
        }

    def _default_theme(self) -> str:
        """app.js 的主题回退值即默认主题（其变量定义在 :root）。"""

        match = re.search(
            r'hasOwnProperty\.call\(themeMetaColors, name\)\s*\?\s*name\s*:\s*"([a-z]+)"',
            self.app_js,
        )
        self.assertIsNotNone(match, "app.js 里没有找到主题回退值")
        return match.group(1)

    def _meta_themes(self) -> set[str]:
        block = re.search(r"const themeMetaColors = \{(.*?)\n\};", self.app_js, re.S)
        self.assertIsNotNone(block, "app.js 里没有找到 themeMetaColors")
        return set(re.findall(r"^\s*([a-z]+):", block.group(1), re.M))

    def _picker_themes(self) -> set[str]:
        select = re.search(
            r'id="theme-select".*?</select>', self.html, re.S
        )
        self.assertIsNotNone(select, "index.html 里没有找到主题选择器")
        return set(re.findall(r'value="([a-z]+)"', select.group(0)))

    def test_all_four_registries_agree(self) -> None:
        sets = {
            "theme.js 白名单": self._reboot_allowlist(),
            "app.css 主题块": self._css_themes(),
            "app.js themeMetaColors": self._meta_themes(),
            "index.html 选择器": self._picker_themes(),
        }
        reference = sets["app.js themeMetaColors"]
        for name, values in sets.items():
            self.assertEqual(
                values,
                reference,
                f"{name} 与 app.js themeMetaColors 不一致："
                f"缺少 {sorted(reference - values)}，多出 {sorted(values - reference)}",
            )

    def test_every_theme_defines_a_meta_color(self) -> None:
        block = re.search(r"const themeMetaColors = \{(.*?)\n\};", self.app_js, re.S)
        for theme in self._css_themes():
            self.assertRegex(
                block.group(1),
                rf"{theme}:\s*\"#[0-9a-fA-F]{{6}}\"",
                f"主题 {theme} 缺少 theme-color 元色",
            )

    def test_new_themes_are_registered(self) -> None:
        """3.1.445 新增的两套用户可选主题。"""

        for theme in ("neon", "console"):
            self.assertIn(theme, self._css_themes())
            self.assertIn(theme, self._meta_themes())
            self.assertIn(theme, self._picker_themes())
            self.assertIn(theme, self._reboot_allowlist())

    def test_default_theme_is_root_backed(self) -> None:
        """默认主题不得再有 data-theme 覆盖块（值在 :root，避免两份真相）。"""

        default = self._default_theme()
        blocks = set(re.findall(r'html\[data-theme="([a-z]+)"\] \{', self.css))
        self.assertNotIn(
            default,
            blocks,
            f"默认主题 {default} 同时存在于 :root 与覆盖块，会留下两份真相",
        )


if __name__ == "__main__":
    unittest.main()
