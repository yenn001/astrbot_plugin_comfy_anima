"""Director Quality Pack regression tests.

These tests lock the Director's natural-language budget rules, token/word
validators, and DNA-anchor coverage checks introduced from the 2.1.308
ST-context lessons digest.
"""

import unittest
from pathlib import Path

from ..models import PluginSettings
from ..services.prompt_catalog import PromptCatalog
from ..services.prompt_composer import PromptComposer
from ..services.prompt_contracts import (
    TASK_DRAW,
    build_director_contract,
)
from ..services.prompt_director import (
    FINAL_PROMPT_HARD_CAP_TOKENS,
    FINAL_PROMPT_SOFT_CAP_TOKENS,
    PictureInstruction,
    PromptDirector,
    PromptDirectorError,
    dna_coverage,
    estimate_prompt_tokens,
    validate_final_prompt,
)

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PromptTemplateQualityPackTests(unittest.TestCase):
    """PromptCatalog resources must state the new Director rules."""

    def test_director_resources_mention_natural_language_and_budgets(self) -> None:
        catalog = PromptCatalog(_PROMPT_DIR)
        for prompt_id in ("director_draw", "director_creative_default"):
            with self.subTest(prompt_id=prompt_id):
                text = catalog.get(prompt_id).text
                self.assertIn("自然语言", text)
                self.assertIn("150", text)
                self.assertIn("90", text)
                self.assertIn("70", text)
                self.assertIn("800", text)
                self.assertIn("1200", text)
                self.assertIn("发色", text)
                self.assertIn("刘海", text)
                self.assertIn("镜头", text)
                self.assertIn("正面 + 半身 + 中景", text)
                self.assertIn("跨图", text)
                self.assertIn("已验证", text)

    def test_code_contract_contains_quality_budget(self) -> None:
        contract = build_director_contract(task_kind=TASK_DRAW, transport="pic")
        self.assertIn("Prompt quality budget", contract)
        self.assertIn("who + appearance DNA", contract)
        self.assertIn("do not use weight syntax", contract)
        self.assertIn("hair color", contract)
        self.assertIn("front view + upper body + mid shot", contract)
        self.assertIn(str(FINAL_PROMPT_SOFT_CAP_TOKENS), contract)
        self.assertIn(str(FINAL_PROMPT_HARD_CAP_TOKENS), contract)


class PromptQualityValidatorTests(unittest.TestCase):
    """Validator thresholds: soft warnings, hard failures, DNA checks."""

    def test_soft_cap_warns_and_hard_cap_raises(self) -> None:
        # A high explicit person count keeps this test focused on token caps.
        soft_prompt = " ".join(["word"] * 610)
        warnings = validate_final_prompt(soft_prompt, person_count=10)
        self.assertGreaterEqual(estimate_prompt_tokens(soft_prompt), 800)
        self.assertTrue(
            any(item.startswith("final_prompt_soft_cap") for item in warnings)
        )

        hard_prompt = " ".join(["word"] * 950)
        with self.assertRaises(PromptDirectorError) as raised:
            validate_final_prompt(hard_prompt, person_count=10)
        self.assertTrue(
            raised.exception.detail.startswith("final_prompt_hard_cap")
        )

    def test_per_person_budget_warns_without_failing(self) -> None:
        prompt = "2girls, " + " ".join(["word"] * 190)
        warnings = validate_final_prompt(prompt)
        self.assertTrue(
            any(
                item.startswith("per_person_word_budget")
                and not item.startswith("per_person_word_budget_hard")
                for item in warnings
            )
        )

    def test_per_person_budget_clearly_over_raises(self) -> None:
        prompt = "3girls, " + " ".join(["word"] * 500)
        with self.assertRaises(PromptDirectorError) as raised:
            validate_final_prompt(prompt)
        self.assertTrue(
            raised.exception.detail.startswith("per_person_word_budget_hard")
        )

    def test_dna_coverage_missing_is_detected(self) -> None:
        missing_bangs = validate_final_prompt(
            "1girl, long white hair, blue eyes, oval face, fair skin"
        )
        self.assertIn("dna_missing:bangs", missing_bangs)

        missing_skin = validate_final_prompt(
            "1girl, black hair, long hair, bangs, red eyes, oval face"
        )
        self.assertIn("dna_missing:skin/body", missing_skin)

        complete = validate_final_prompt(
            "1girl, black hair, long hair, bangs, red eyes, oval face, fair skin"
        )
        self.assertNotIn("dna_missing", " ".join(complete))

    def test_dna_coverage_helper_returns_stable_anchor_names(self) -> None:
        missing = dna_coverage(
            "1girl, long white hair, blue eyes, oval face, fair skin"
        )
        self.assertEqual(missing, ("bangs",))


class PictureInstructionQualityWarningsTests(unittest.TestCase):
    """The final compose step must surface quality warnings on instructions."""

    def test_compose_records_quality_warnings(self) -> None:
        reference = _PROMPT_DIR / "director_creative_default.txt"
        director = PromptDirector(
            reference,
            PluginSettings.from_mapping({}),
            composer=PromptComposer("off", validation_mode="off"),
        )
        instruction = director.compose_picture_instruction(
            PictureInstruction("1girl, portrait")
        )
        self.assertTrue(instruction.quality_warnings)
        self.assertTrue(
            any(item.startswith("dna_missing:") for item in instruction.quality_warnings)
        )


if __name__ == "__main__":
    unittest.main()
