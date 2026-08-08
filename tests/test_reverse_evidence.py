import unittest

from ..services.reverse_evidence import (
    CAP_COMPOSITION,
    CAP_FLAT_TAGS,
    CAP_SUBJECTS,
    ReverseEvidence,
)


class ReverseEvidenceTests(unittest.TestCase):
    def test_local_tagger_only_claims_flat_tags(self) -> None:
        evidence = ReverseEvidence.flat_tagger("1girl, portrait")

        self.assertTrue(evidence.supports(CAP_FLAT_TAGS))
        self.assertFalse(evidence.supports(CAP_COMPOSITION))
        self.assertFalse(evidence.supports(CAP_SUBJECTS))
        self.assertEqual(evidence.subjects, ())
        self.assertFalse(evidence.confidence_available)
