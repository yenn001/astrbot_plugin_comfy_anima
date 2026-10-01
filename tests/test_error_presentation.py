"""Error presentation tests: no fake success, no internal leakage."""

import unittest

from ..services.error_presentation import present_error


class ErrorPresentationTests(unittest.TestCase):
    def test_each_code_has_safe_visible_text(self) -> None:
        for code in (
            "invalid_terminal_repair",
            "invalid_json",
            "missing_positive_tags",
            "prompt_plan_lookup_failed",
            "prompt_composition_failed",
            "lora_identity_binding_failed",
            "preset_manifest_mismatch",
            "provider_failed",
        ):
            with self.subTest(code=code):
                text = present_error(code)
                self.assertTrue(text)
                self.assertIn("没有生成图片", text)
        self.assertIn("暂时无法确认", present_error("delivery_unknown"))

    def test_failed_repair_never_claims_success(self) -> None:
        text = present_error("invalid_terminal_repair")
        for marker in (
            "已发给你",
            "照片来了",
            "生成完成",
            "已生成",
        ):
            self.assertNotIn(marker, text)

    def test_internal_ids_are_hidden(self) -> None:
        text = present_error(
            "provider_failed",
            "provider=W-Xy/glm-5.3 run_id=029df077989d43f2a9a0f1b8c03de5c2",
        )
        self.assertNotIn("029df077989d43f2a9a0f1b8c03de5c2", text)
        self.assertNotIn("W-Xy", text)
        self.assertIn("内部信息已隐藏", text)

    def test_delivery_unknown_does_not_claim_delivery(self) -> None:
        text = present_error("delivery_unknown")
        self.assertIn("暂时无法确认", text)
        self.assertNotIn("已送达", text)


if __name__ == "__main__":
    unittest.main()
