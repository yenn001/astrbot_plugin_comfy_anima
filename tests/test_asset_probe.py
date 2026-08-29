"""Three-state asset probe classification tests."""

import types
import unittest

from ..services.asset_probe import AssetProbeResult, classify_asset_probe


def _result(text="", is_error=False):
    return types.SimpleNamespace(text=text, isError=is_error, is_error=False)


class AssetProbeTests(unittest.TestCase):
    def test_is_error_is_fatal(self) -> None:
        result = classify_asset_probe(
            "list_anima_loras", None, _result(is_error=True), "{}"
        )
        self.assertEqual(result, AssetProbeResult.FATAL)

    def test_empty_text_is_fatal(self) -> None:
        result = classify_asset_probe("list_anima_loras", None, _result(), "")
        self.assertEqual(result, AssetProbeResult.FATAL)

    def test_prompt_plan_lookup_failed_is_miss(self) -> None:
        text = '{"ok":false,"code":"PROMPT_PLAN_LOOKUP_FAILED","message":"prompt plan not found: 达妮娅"}'
        result = classify_asset_probe(
            "list_anima_prompt_plans",
            {"keyword": "达妮娅"},
            _result(text),
            text,
        )
        self.assertEqual(result, AssetProbeResult.MISS)

    def test_prompt_plan_message_not_found_is_miss(self) -> None:
        text = '{"ok":false,"code":"OTHER","message":"prompt plan not found"}'
        result = classify_asset_probe(
            "list_anima_prompt_plans", {}, _result(text), text
        )
        self.assertEqual(result, AssetProbeResult.MISS)

    def test_no_matching_presets_is_miss(self) -> None:
        text = '{"ok":false,"code":"PRESET_LOOKUP_FAILED","message":"no matching saved LoRA presets were found"}'
        result = classify_asset_probe(
            "list_anima_lora_presets", {}, _result(text), text
        )
        self.assertEqual(result, AssetProbeResult.MISS)

    def test_empty_plans_with_keyword_is_miss(self) -> None:
        text = '{"ok":true,"count":0,"plans":[]}'
        result = classify_asset_probe(
            "list_anima_prompt_plans",
            {"keyword": "foo"},
            _result(text),
            text,
        )
        self.assertEqual(result, AssetProbeResult.MISS)

    def test_failure_marker_is_fatal(self) -> None:
        for marker in (
            "LoRA Manager is unavailable",
            "LoRA Manager refresh failed",
            "LoRA preset query unavailable",
            "error: tool crashed",
        ):
            with self.subTest(marker=marker):
                result = classify_asset_probe(
                    "list_anima_loras", None, _result(marker), marker
                )
                self.assertEqual(result, AssetProbeResult.FATAL)

    def test_unknown_ok_false_is_fatal(self) -> None:
        text = '{"ok":false,"code":"PERMISSION_DENIED"}'
        result = classify_asset_probe(
            "list_anima_loras", {}, _result(text), text
        )
        self.assertEqual(result, AssetProbeResult.FATAL)

    def test_ok_plan_with_items_is_evidence_ok(self) -> None:
        text = '{"ok":true,"count":1,"plans":[{"plan_id":"P-123456"}]}'
        result = classify_asset_probe(
            "list_anima_prompt_plans", {}, _result(text), text
        )
        self.assertEqual(result, AssetProbeResult.EVIDENCE_OK)

    def test_plain_non_error_text_remains_evidence_ok(self) -> None:
        text = "Available Anima LoRAs. - denia_lorav4"
        result = classify_asset_probe(
            "list_anima_loras", {}, _result(text), text
        )
        self.assertEqual(result, AssetProbeResult.EVIDENCE_OK)


if __name__ == "__main__":
    unittest.main()
