"""Deterministic PromptCatalog loading and resolution tests."""

import tempfile
import unittest
from pathlib import Path

from ..services.prompt_catalog import (
    EffectivePrompt,
    PromptCatalog,
    PromptCatalogError,
)

_HEADER = (
    "# prompt_id: director_draw\n"
    "# prompt_role: director_task\n"
    "# prompt_version: 1\n"
    "\n"
    "1girl, solo\n"
)


class PromptCatalogTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, text: str) -> Path:
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_header_fields_and_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "director_draw.txt", _HEADER)
            catalog = PromptCatalog(Path(tmp))
            resource = catalog.get("director_draw")
            self.assertEqual(resource.role, "director_task")
            self.assertEqual(resource.version, 1)
            self.assertEqual(resource.path, path)
            self.assertEqual(len(resource.sha256), 64)
            self.assertEqual(resource.sha256_prefix, resource.sha256[:12])

    def test_effective_prefers_config_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "director_draw.txt", _HEADER)
            catalog = PromptCatalog(Path(tmp))
            effective = catalog.effective(
                role="director_creative",
                settings=object(),
                default_prompt_id="director_draw",
                config_text="  admin preference  ",
            )
            self.assertIsInstance(effective, EffectivePrompt)
            self.assertEqual(effective.source, "config:director_creative")
            self.assertEqual(effective.text, "  admin preference  ")
            self.assertEqual(effective.version, 0)

    def test_effective_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "director_draw.txt", _HEADER)
            catalog = PromptCatalog(Path(tmp))
            effective = catalog.effective(
                role="director_creative",
                settings=object(),
                default_prompt_id="director_draw",
                config_text="",
            )
            self.assertTrue(effective.source.startswith("file:"))
            self.assertEqual(effective.prompt_id, "director_draw")
            self.assertEqual(effective.version, 1)

    def test_status_lists_sorted_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "b_prompt.txt", _HEADER.replace("director_draw", "b_prompt"))
            self._write(Path(tmp), "a_prompt.txt", _HEADER.replace("director_draw", "a_prompt"))
            catalog = PromptCatalog(Path(tmp))
            self.assertEqual(
                [item["prompt_id"] for item in catalog.status()],
                ["a_prompt", "b_prompt"],
            )

    def test_duplicate_prompt_id_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "one.txt", _HEADER)
            self._write(Path(tmp), "two.txt", _HEADER)
            with self.assertRaises(PromptCatalogError):
                PromptCatalog(Path(tmp))

    def test_missing_header_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "bad.txt", "no header here\n1girl\n")
            with self.assertRaises(PromptCatalogError):
                PromptCatalog(Path(tmp))

    def test_non_positive_version_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp),
                "bad.txt",
                "# prompt_id: bad\n# prompt_role: director_task\n# prompt_version: 0\n",
            )
            with self.assertRaises(PromptCatalogError):
                PromptCatalog(Path(tmp))

    def test_unknown_prompt_id_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "director_draw.txt", _HEADER)
            catalog = PromptCatalog(Path(tmp))
            with self.assertRaises(PromptCatalogError):
                catalog.get("missing")


if __name__ == "__main__":
    unittest.main()
