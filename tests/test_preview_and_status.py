"""Preview permissions and WebUI status payload tests."""

import unittest

from ..services.preview_control import (
    preview_request_allowed,
    sanitize_preview_payload,
)
from ..services.webui_status import build_webui_status


class PreviewControlTests(unittest.TestCase):
    def test_admin_is_allowed(self) -> None:
        decision = preview_request_allowed(
            is_admin=True, user_id="123", config={}
        )
        self.assertTrue(decision.allowed)

    def test_whitelisted_user_is_allowed(self) -> None:
        decision = preview_request_allowed(
            is_admin=False,
            user_id="719397082",
            config={"preview_whitelist_users": ["719397082"]},
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "whitelist")

    def test_regular_user_is_denied(self) -> None:
        decision = preview_request_allowed(
            is_admin=False, user_id="999", config={}
        )
        self.assertFalse(decision.allowed)

    def test_sanitized_payload_never_contains_prompt_text(self) -> None:
        sanitized = sanitize_preview_payload(
            {
                "preset_name": "达妮娅",
                "positive_terms": ["naked", "secret"],
                "lora_entries": [{"name": "secret", "weight": 1.0}],
                "prompt_id": "p-1",
            }
        )
        self.assertNotIn("positive_terms", sanitized)
        self.assertNotIn("lora_entries", sanitized)
        self.assertIn("preset_name", sanitized)
        self.assertIn("prompt_id", sanitized)


class WebUiStatusTests(unittest.TestCase):
    def test_status_payload_is_json_safe(self) -> None:
        payload = build_webui_status(
            target_version="2.1.307",
            prompt_catalog=("director_draw",),
            prompt_contract_version="3.1",
        )
        self.assertEqual(payload["target_version"], "2.1.307")
        self.assertIsInstance(payload["prompt_catalog"], list)
        self.assertEqual(payload["runtime_probe_phase"], "pre-stage1")
        self.assertEqual(payload["delivery_receipt_mode"], "unknown")


if __name__ == "__main__":
    unittest.main()
