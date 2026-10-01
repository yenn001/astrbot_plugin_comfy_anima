from types import SimpleNamespace

from ..services.lora_compatibility import (
    ANIMA_29B_FAMILY,
    LEGACY_FAMILY,
    assess_lora_compatibility,
)


def record(*, families=(), mode="unknown"):
    return SimpleNamespace(
        compatible_model_families=tuple(families),
        compatibility_mode=mode,
    )


def test_29b_rejects_unclassified_asset():
    result = assess_lora_compatibility(record(), ANIMA_29B_FAMILY, patch_verified=True)
    assert not result.eligible
    assert result.reason == "asset_family_not_declared"


def test_29b_accepts_native_asset_only_with_explicit_family():
    result = assess_lora_compatibility(
        record(families=(ANIMA_29B_FAMILY,), mode="native_29b"),
        ANIMA_29B_FAMILY,
    )
    assert result.eligible
    assert result.mode == "native_29b"


def test_29b_accepts_legacy_projection_only_with_verified_patch():
    asset = record(families=(LEGACY_FAMILY,), mode="legacy_projection")
    assert not assess_lora_compatibility(asset, ANIMA_29B_FAMILY).eligible
    result = assess_lora_compatibility(asset, ANIMA_29B_FAMILY, patch_verified=True)
    assert result.eligible
    assert result.reason == "verified_legacy_projection"


def test_legacy_rejects_explicit_29b_only_asset():
    result = assess_lora_compatibility(
        record(families=(ANIMA_29B_FAMILY,), mode="native_29b"),
        LEGACY_FAMILY,
    )
    assert not result.eligible
