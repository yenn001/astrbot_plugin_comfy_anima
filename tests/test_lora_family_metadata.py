from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
)


def test_non_character_family_metadata_round_trips_and_overlays():
    record = LoraRecord(
        name="anima_ushiki_epoch70.safetensors",
        sha256="a" * 64,
        category="artist_style",
    )
    entry = SemanticEntry(
        identity_key=semantic_identity_key(record.name, record.sha256),
        canonical_name=record.name,
        sha256=record.sha256,
        analysis_status="searchable",
        category=(SemanticFact("artist_style", "manual", (), 1.0),),
        compatible_model_families=("anima_29b_40l",),
        compatibility_mode="native_29b",
        source_fingerprint="",
    )
    payload = entry.to_dict()
    restored = SemanticEntry.from_dict(payload)
    overlaid = LoraSemanticIndex(entries={restored.identity_key: restored}).apply_overlay(record)
    assert overlaid.compatible_model_families == ("anima_29b_40l",)
    assert overlaid.compatibility_mode == "native_29b"


def test_unknown_family_remains_unknown_for_legacy_assets():
    record = LoraRecord(name="legacy.safetensors", sha256="b" * 64)
    assert record.compatible_model_families == ()
    assert record.compatibility_mode == "unknown"
