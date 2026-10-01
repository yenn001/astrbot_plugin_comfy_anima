"""Identity binding resolver tests, including the Kei dual-canonical case."""

import unittest

from ..services.identity_binding import (
    IdentityBindingError,
    identity_required_for_subject,
    resolve_requested_subject_binding,
)


class IdentityBindingTests(unittest.TestCase):
    def test_unique_verified_binding_resolves(self) -> None:
        binding = resolve_requested_subject_binding(
            "denia",
            evidence=[
                {
                    "name": "denia",
                    "canonical": "denia_(original)",
                    "work": "",
                    "activation_terms": ["denia_lorav4"],
                }
            ],
        )
        self.assertEqual(binding.canonical, "denia_(original)")
        self.assertEqual(binding.activation_terms, ("denia_lorav4",))

    def test_alias_is_normalized(self) -> None:
        binding = resolve_requested_subject_binding(
            "KEI",
            evidence=[
                {
                    "name": "kei",
                    "canonical": "kei_(blue_archive)",
                    "activation_terms": [],
                }
            ],
        )
        self.assertEqual(binding.canonical, "kei_(blue_archive)")

    def test_two_verified_canonicals_fail_closed(self) -> None:
        with self.assertRaises(IdentityBindingError) as caught:
            resolve_requested_subject_binding(
                "kei",
                evidence=[
                    {
                        "name": "kei",
                        "canonical": "kei_(blue_archive)",
                        "activation_terms": [],
                    },
                    {
                        "name": "kei",
                        "canonical": "kei_(student)_(blue_archive)",
                        "activation_terms": [],
                    },
                ],
            )
        message = str(caught.exception)
        self.assertIn("multiple verified canonicals", message)
        self.assertIn("kei_(blue_archive)", message)
        self.assertIn("kei_(student)_(blue_archive)", message)

    def test_allowed_canonicals_break_the_tie(self) -> None:
        binding = resolve_requested_subject_binding(
            "kei",
            evidence=[
                {
                    "name": "kei",
                    "canonical": "kei_(blue_archive)",
                    "activation_terms": [],
                },
                {
                    "name": "kei",
                    "canonical": "kei_(student)_(blue_archive)",
                    "activation_terms": [],
                },
            ],
            allowed_canonicals=("kei_(student)_(blue_archive)",),
        )
        self.assertEqual(binding.canonical, "kei_(student)_(blue_archive)")

    def test_missing_subject_or_evidence_fails_closed(self) -> None:
        with self.assertRaises(IdentityBindingError):
            resolve_requested_subject_binding("", evidence=[])
        with self.assertRaises(IdentityBindingError):
            resolve_requested_subject_binding("unknown", evidence=[])

    def test_identity_required_for_nonempty_subject(self) -> None:
        self.assertTrue(identity_required_for_subject("kei"))
        self.assertFalse(identity_required_for_subject(""))


if __name__ == "__main__":
    unittest.main()
