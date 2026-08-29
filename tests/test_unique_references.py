"""Unique references matrix tests: every acceptance item binds once."""

import re
import unittest
from pathlib import Path

_MATRIX = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "ComfyAnima-2.1.307-Unique-References-Matrix-20260828.md"
)


class UniqueReferencesMatrixTests(unittest.TestCase):
    def test_matrix_exists_and_has_unique_ids(self) -> None:
        text = _MATRIX.read_text(encoding="utf-8")
        ids = re.findall(r"^\|\s*([A-Z][A-Z0-9.]+)\s*\|", text, flags=re.MULTILINE)
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_matrix_has_unique_assets(self) -> None:
        text = _MATRIX.read_text(encoding="utf-8")
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("| Q") or line.startswith("| P") or line.startswith("| C")
        ]
        assets = [row.rsplit("|", 2)[1].strip() for row in rows if "|" in row]
        self.assertTrue(assets)
        self.assertEqual(len(assets), len(set(assets)))

    def test_matrix_covers_control_modes(self) -> None:
        text = _MATRIX.read_text(encoding="utf-8")
        self.assertIn("--mode depth", text)
        self.assertIn("--mode pose_depth", text)
        self.assertNotIn("--mode pose depth", text)


if __name__ == "__main__":
    unittest.main()
