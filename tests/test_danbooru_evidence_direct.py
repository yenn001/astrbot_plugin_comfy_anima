"""外貌证据优先走直连 Danbooru API（代理坏掉也能补上外貌）。

实测背景：外观证据原本只走 ComfyUI 侧 /danbooru_gallery/posts，而它在本部署里坏了
（HTTP 200 但内容是 [{"error": ...}]）—— 243 次取证据里 208 次拿不到，已 exact 验证的
角色长期缺 canonical 外貌标签。直连 API 经 SOCKS5 隧道实测可用（HTTP 200 + 真实数据）。
"""

import importlib
import json
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
API = importlib.import_module("astrbot_plugin_comfy_anima.services.danbooru_api_client")

ROOT = Path(__file__).resolve().parents[1]


class PostsUrlTests(unittest.TestCase):
    def test_url_is_bounded_safe_rated_and_scoped(self) -> None:
        url = API.build_posts_url("rio_(blue_archive)", base_url="https://danbooru.donmai.us")
        self.assertIn("/posts.json?", url)
        self.assertIn("tags=rio_%28blue_archive%29+solo+rating%3Ag", url)
        self.assertIn("limit=100", url)

    def test_limit_is_clamped_to_the_api_maximum(self) -> None:
        url = API.build_posts_url("rio", base_url="https://x", limit=9999)
        self.assertIn("limit=200", url)
        url_low = API.build_posts_url("rio", base_url="https://x", limit=1)
        self.assertIn("limit=12", url_low)

    def test_credentials_only_appear_when_a_key_is_set(self) -> None:
        anonymous = API.build_posts_url("rio", base_url="https://x")
        self.assertNotIn("api_key", anonymous)
        authed = API.build_posts_url(
            "rio", base_url="https://x", login="y59_001", api_key="secret"
        )
        self.assertIn("login=y59_001", authed)
        self.assertIn("api_key=secret", authed)

    def test_malformed_canonical_is_rejected(self) -> None:
        with self.assertRaises(API.DanbooruApiError):
            API.build_posts_url("rio; drop table", base_url="https://x")

    def test_proxy_schemes_map_to_curl_flags(self) -> None:
        self.assertEqual(
            API._proxy_args("socks5h://192.168.10.88:7890"),
            ["--socks5-hostname", "192.168.10.88:7890"],
        )
        self.assertEqual(
            API._proxy_args("socks5://h:1"), ["--socks5", "h:1"]
        )
        self.assertEqual(
            API._proxy_args("http://h:8080"), ["--proxy", "http://h:8080"]
        )


class WiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_evidence_helper_prefers_direct_api_with_a_hard_timeout(self) -> None:
        self.assertIn("async def _danbooru_evidence_posts(", self.main)
        self.assertIn("DANBOORU_EVIDENCE_TIMEOUT_SECONDS = 15.0", self.main)
        self.assertIn("asyncio.wait_for(", self.main)
        # 直连在前、代理在后
        helper = self.main[self.main.find("async def _danbooru_evidence_posts(") :]
        helper = helper[: helper.find("\n    async def ", 10) if "\n    async def " in helper else 4000]
        self.assertLess(
            helper.find("fetch_character_posts"), helper.find("client.danbooru_character_posts")
        )

    def test_all_evidence_call_sites_use_the_helper(self) -> None:
        # 只剩 helper 内部那一处旧调用（作为代理兜底）
        self.assertEqual(self.main.count("client.danbooru_character_posts("), 1)
        self.assertGreaterEqual(self.main.count("_danbooru_evidence_posts("), 4)

    def test_module_level_refresh_receives_the_plugin(self) -> None:
        self.assertIn("async def _refresh_appearance_profile(\n    plugin: Any,", self.main)
        self.assertIn("await plugin._danbooru_evidence_posts(", self.main)

    def test_settings_and_schema_carry_the_credentials(self) -> None:
        models = (ROOT / "models.py").read_text(encoding="utf-8")
        self.assertIn("danbooru_api_login", models)
        self.assertIn("danbooru_api_key", models)
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        self.assertIn("danbooru_api_login", schema)
        self.assertIn("danbooru_api_key", schema)


if __name__ == "__main__":
    unittest.main()
