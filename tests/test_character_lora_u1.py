from __future__ import annotations

import unittest
from dataclasses import replace

from ..services.character_lora_gate import gate_character_lora_views
from ..services.character_lora_projection import build_character_lora_views
from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import LoraIdentityBinding
from ..services.private_identity_profiles import PrivateIdentityProfile

SHA = "a" * 64


def rec(**changes: object) -> LoraRecord:
    values: dict[str, object] = {"name": "characters/hero.safetensors", "sha256": SHA, "category": "character"}
    values.update(changes)
    return LoraRecord(**values)  # type: ignore[arg-type]


def bind(**changes: object) -> LoraIdentityBinding:
    values: dict[str, object] = {"character_canonical": "hero_(series)", "copyright_canonical": "series", "activation_terms": ("hero_trigger",), "verified_revision": SHA}
    values.update(changes)
    return LoraIdentityBinding(**values)  # type: ignore[arg-type]


class CharacterLoraU1Tests(unittest.TestCase):
    def test_metadata_only_change_keeps_ready_but_changes_metadata_revision(self) -> None:
        first = build_character_lora_views(rec(), public_bindings=(bind(),))[0]
        second = build_character_lora_views(rec(description="new evidence"), public_bindings=(bind(),))[0]
        self.assertEqual(first.health, second.health)
        self.assertEqual(first.asset_revision, second.asset_revision)
        self.assertNotEqual(first.metadata_revision, second.metadata_revision)

    def test_missing_sha_and_revision_drift_fail_closed(self) -> None:
        self.assertEqual(build_character_lora_views(rec(sha256=""), public_bindings=(bind(),))[0].health, "missing_asset")
        self.assertEqual(build_character_lora_views(rec(sha256="b" * 64), public_bindings=(bind(),))[0].health, "revision_changed")

    def test_source_revision_is_audit_only_asset_sha_remains_binding_revision(self) -> None:
        view = build_character_lora_views(
            rec(),
            public_bindings=(bind(verified_source_revision="danbooru:rev-2"),),
        )[0]
        self.assertEqual(view.health, "ready")

        stale = build_character_lora_views(
            rec(),
            public_bindings=(bind(verified_revision="danbooru:rev-2"),),
        )[0]
        self.assertEqual(stale.health, "needs_review")
        self.assertIn("identity_revision_unbound", stale.warnings)

    def test_multi_variant_rules_and_forbidden_activation(self) -> None:
        rows = build_character_lora_views(rec(), public_bindings=(bind(), bind(variant_id="alt", default_for_character=False, activation_terms=())))
        result = gate_character_lora_views(rows)
        self.assertEqual(result.health, "ambiguous")
        forbidden = build_character_lora_views(rec(), public_bindings=(bind(activation_terms=("<lora:hero:1>",)),))[0]
        self.assertEqual(forbidden.health, "conflict")

    def test_public_private_authority_conflict_is_fail_closed(self) -> None:
        profile = PrivateIdentityProfile("hero", "Hero", ("hero",), rec().name, SHA, ("hero_private",))
        rows = build_character_lora_views(rec(), public_bindings=(bind(),), private_profile=profile)
        self.assertEqual(gate_character_lora_views(rows).health, "conflict")

    def test_same_name_multiple_assets_and_duplicate_sha_fail_closed(self) -> None:
        first = build_character_lora_views(rec(), public_bindings=(bind(),))[0]
        renamed_identity = replace(first, identity_ref="public:other_(series):default", asset_revision="b" * 64)
        self.assertEqual(gate_character_lora_views((first, renamed_identity)).health, "conflict")

        other = build_character_lora_views(
            rec(name="characters/other.safetensors"),
            public_bindings=(bind(character_canonical="other_(series)"),),
        )[0]
        self.assertEqual(gate_character_lora_views((first, other)).health, "conflict")

    def test_variant_default_and_activation_groups_must_be_unique(self) -> None:
        default_collision = build_character_lora_views(
            rec(),
            public_bindings=(
                bind(),
                bind(variant_id="alt", activation_terms=("hero_alt",)),
            ),
        )
        self.assertEqual(gate_character_lora_views(default_collision).health, "ambiguous")

        duplicate_activation = build_character_lora_views(
            rec(),
            public_bindings=(
                bind(),
                bind(
                    variant_id="alt",
                    default_for_character=False,
                    activation_terms=("hero_trigger",),
                ),
            ),
        )
        self.assertEqual(gate_character_lora_views(duplicate_activation).health, "ambiguous")

    def test_strength_precedence_is_command_profile_global(self) -> None:
        profile = PrivateIdentityProfile("hero", "Hero", ("hero",), rec().name, SHA, ("hero_private",), lora_strength_override=0.8)
        view = build_character_lora_views(rec(), private_profile=profile, command_strength=0.9, global_strength=0.5)[0]
        self.assertEqual((view.effective_strength, view.strength_source), (0.9, "command"))

    def test_model_family_compatibility_metadata_survives_projection(self) -> None:
        binding = bind(
            compatible_model_families=("anima_legacy_28l",),
            compatibility_mode="legacy_projection",
        )
        view = build_character_lora_views(rec(), public_bindings=(binding,))[0]
        self.assertEqual(view.compatible_model_families, ("anima_legacy_28l",))
        self.assertEqual(view.compatibility_mode, "legacy_projection")

    def test_private_profile_can_declare_native_29b_compatibility(self) -> None:
        profile = PrivateIdentityProfile(
            "hero", "Hero", ("hero",), rec().name, SHA, ("hero_private",),
            compatible_model_families=("anima_29b_40l",),
            compatibility_mode="native_29b",
        )
        view = build_character_lora_views(rec(), private_profile=profile)[0]
        self.assertEqual(view.compatibility_mode, "native_29b")


if __name__ == "__main__":
    unittest.main()
