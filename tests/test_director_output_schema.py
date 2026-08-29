"""Built-in emit_anima_plan_v1 schema validator tests."""

import unittest

from ..services.director_output_schema import (
    DirectorOutputSchemaError,
    validate_emit_anima_plan,
)

_VALID = {
    "positive_tags": "1girl, solo, portrait",
    "negative_tags": "bad hands",
    "pipeline": "base",
}


class DirectorOutputSchemaTests(unittest.TestCase):
    def test_valid_payload_is_normalized(self) -> None:
        normalized = validate_emit_anima_plan(_VALID)
        self.assertEqual(normalized["positive_tags"], "1girl, solo, portrait")
        self.assertEqual(normalized["pipeline"], "base")
        self.assertEqual(normalized["lora_stack"], ())
        self.assertEqual(normalized["characters"], ())

    def test_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan({**_VALID, "extra": 1})

    def test_missing_positive_tags_is_rejected(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan({"negative_tags": "", "pipeline": "base"})

    def test_forbidden_text_is_rejected(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan(
                {"positive_tags": "<pic>", "negative_tags": "", "pipeline": "base"}
            )

    def test_invalid_pipeline_is_rejected(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan({**_VALID, "pipeline": "nope"})

    def test_lora_stack_requires_verified_name(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan(
                {
                    **_VALID,
                    "lora_stack": [{"name": "invented.safetensors", "weight": 0.8}],
                },
                allowed_lora_names=("known.safetensors",),
            )

    def test_lora_stack_accepts_verified_name(self) -> None:
        normalized = validate_emit_anima_plan(
            {
                **_VALID,
                "lora_stack": [{"name": "known.safetensors", "weight": 0.8}],
            },
            allowed_lora_names=("known.safetensors",),
        )
        self.assertEqual(normalized["lora_stack"][0]["name"], "known.safetensors")

    def test_character_canonical_requires_verified_evidence(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan(
                {
                    **_VALID,
                    "characters": [
                        {"query": "kei", "canonical": "invented_(blue_archive)"}
                    ],
                },
                allowed_character_canonicals=("kei_(blue_archive)",),
            )

    def test_weight_bounds_are_enforced(self) -> None:
        with self.assertRaises(DirectorOutputSchemaError):
            validate_emit_anima_plan(
                {**_VALID, "lora_stack": [{"name": "known", "weight": 2.5}]}
            )


if __name__ == "__main__":
    unittest.main()
