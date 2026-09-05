"""Model-family gate tests."""

import types
import unittest

from ..services.model_family_gate import (
    ModelFamilyGateError,
    gate_lora_selection,
)


def _record(families=(), mode="unknown"):
    return types.SimpleNamespace(
        compatible_model_families=families, compatibility_mode=mode
    )


class ModelFamilyGateTests(unittest.TestCase):
    def test_legacy_family_asset_is_allowed_on_legacy_target(self) -> None:
        self.assertTrue(
            gate_lora_selection(
                "asset",
                _record(("anima_legacy_28l",), "legacy_only"),
                target_family="anima_legacy_28l",
                patch_verified=False,
            )
        )

    def test_unclassified_asset_is_allowed_on_legacy_target(self) -> None:
        self.assertTrue(
            gate_lora_selection(
                "asset",
                _record(),
                target_family="anima_legacy_28l",
                patch_verified=False,
            )
        )

    def test_native_29b_asset_is_allowed_on_29b_target(self) -> None:
        self.assertTrue(
            gate_lora_selection(
                "asset",
                _record(("anima_29b_40l",), "native_29b"),
                target_family="anima_29b_40l",
                patch_verified=False,
            )
        )

    def test_native_29b_asset_is_rejected_on_legacy_target(self) -> None:
        with self.assertRaises(ModelFamilyGateError):
            gate_lora_selection(
                "asset",
                _record(("anima_29b_40l",), "native_29b"),
                target_family="anima_legacy_28l",
                patch_verified=False,
            )

    def test_legacy_asset_is_rejected_on_29b_target(self) -> None:
        with self.assertRaises(ModelFamilyGateError):
            gate_lora_selection(
                "asset",
                _record(("anima_legacy_28l",), "legacy_only"),
                target_family="anima_29b_40l",
                patch_verified=False,
            )

    def test_unclassified_asset_is_rejected_on_29b_target(self) -> None:
        with self.assertRaises(ModelFamilyGateError):
            gate_lora_selection(
                "asset",
                _record(),
                target_family="anima_29b_40l",
                patch_verified=False,
            )

    def test_unsupported_target_family_rejects_everything(self) -> None:
        with self.assertRaises(ModelFamilyGateError):
            gate_lora_selection(
                "asset",
                _record(("anima_legacy_28l",), "legacy_only"),
                target_family="other",
                patch_verified=False,
            )

    def test_missing_record_fails_closed(self) -> None:
        with self.assertRaises(ModelFamilyGateError):
            gate_lora_selection(
                "asset",
                None,
                target_family="anima_29b_40l",
                patch_verified=False,
            )


if __name__ == "__main__":
    unittest.main()