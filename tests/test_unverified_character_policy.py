"""Regression: unverified character names draw by default, refuse when the policy is off."""

import unittest


class _Gate:
    """复刻门口那段策略判定（与 main.py 的分支一一对应）。"""

    def __init__(self, allow: bool) -> None:
        self.allow = allow

    def outcome(self, *, claim_strict: bool, verified: bool) -> str:
        if verified:
            return "verified"
        if not claim_strict:
            return "advisory_kept"
        if self.allow:
            return "unverified_drawn"
        return "refused"


class UnverifiedCharacterPolicyTests(unittest.TestCase):
    def test_default_policy_draws_unverified_names(self) -> None:
        self.assertEqual(
            _Gate(allow=True).outcome(claim_strict=True, verified=False),
            "unverified_drawn",
        )

    def test_strict_policy_still_refuses(self) -> None:
        self.assertEqual(
            _Gate(allow=False).outcome(claim_strict=True, verified=False),
            "refused",
        )

    def test_director_candidates_still_kept_as_advisory(self) -> None:
        """非严格声明（导演发现）不走新策略，行为不变。"""

        for allow in (True, False):
            with self.subTest(allow=allow):
                self.assertEqual(
                    _Gate(allow=allow).outcome(claim_strict=False, verified=False),
                    "advisory_kept",
                )

    def test_verified_names_unaffected(self) -> None:
        for allow in (True, False):
            with self.subTest(allow=allow):
                self.assertEqual(
                    _Gate(allow=allow).outcome(claim_strict=True, verified=True),
                    "verified",
                )

    def test_plugin_defaults_to_allow(self) -> None:
        import importlib

        from ._stubs import install_astrbot_stubs

        install_astrbot_stubs()
        models = importlib.import_module("astrbot_plugin_comfy_anima.models")
        settings = models.PluginSettings.from_mapping({})
        self.assertTrue(settings.allow_unverified_character_names)

    def test_schema_has_the_setting(self) -> None:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        self.assertIn("allow_unverified_character_names", schema)
        self.assertIs(schema["allow_unverified_character_names"].get("default"), True)


if __name__ == "__main__":
    unittest.main()
