"""Tests for exact, context-aware command alias normalization."""

import unittest

from ..core.command_aliases import (
    CONTEXT_CHARACTER_SWAP,
    CONTEXT_GENERATION,
    CONTEXT_INPAINT,
    CONTEXT_SEMANTIC_REDRAW,
    CommandAliasError,
    normalize_command_aliases,
)


class CommandAliasTests(unittest.TestCase):
    def test_generation_common_options_and_pipeline_values(self) -> None:
        actual = normalize_command_aliases(
            (
                "portrait",
                "--n",
                "bad hands",
                "--sd",
                "42",
                "--sz",
                "832x1216",
                "--st",
                "20",
                "--c",
                "5",
                "--p",
                "i",
                "--d",
                "0.4",
                "--u",
                "--nu",
                "--l",
                "--r",
                "--pr",
                "风格001",
            ),
            context=CONTEXT_GENERATION,
        )
        self.assertEqual(
            actual,
            (
                "portrait",
                "--negative",
                "bad hands",
                "--seed",
                "42",
                "--size",
                "832x1216",
                "--steps",
                "20",
                "--cfg",
                "5",
                "--pipeline",
                "iterative",
                "--denoise",
                "0.4",
                "--upscale",
                "--no-upscale",
                "--llm",
                "--raw",
                "--preset",
                "风格001",
            ),
        )

    def test_pipeline_r_and_control_r_are_contextually_distinct(self) -> None:
        actual = normalize_command_aliases(
            ("1girl", "--p", "r", "--m", "r"),
            context=CONTEXT_GENERATION,
        )
        self.assertEqual(
            actual,
            (
                "1girl",
                "--pipeline",
                "rtx",
                "--control-mode",
                "reference",
            ),
        )

    def test_generation_control_mode_accepts_multiple_values(self) -> None:
        actual = normalize_command_aliases(
            ("--m", "p", "d", "paint", "a", "girl"),
            context=CONTEXT_GENERATION,
        )
        self.assertEqual(
            actual,
            (
                "--control-mode",
                "pose",
                "--control-mode",
                "depth",
                "paint",
                "a",
                "girl",
            ),
        )

    def test_generation_control_mode_accepts_repetition_and_deduplicates(self) -> None:
        actual = normalize_command_aliases(
            (
                "portrait",
                "--m",
                "p",
                "--control",
                "p",
                "d",
                "--control-mode",
                "l",
                "r",
            ),
            context=CONTEXT_GENERATION,
        )
        self.assertEqual(
            actual,
            (
                "portrait",
                "--control-mode",
                "pose",
                "--control-mode",
                "depth",
                "--control-mode",
                "lineart",
                "--control-mode",
                "reference",
            ),
        )

    def test_control_mode_requires_an_exact_supported_value(self) -> None:
        with self.assertRaisesRegex(CommandAliasError, "仅支持"):
            normalize_command_aliases(
                ("portrait", "--m", "po"),
                context=CONTEXT_GENERATION,
            )
        with self.assertRaisesRegex(CommandAliasError, "仅支持"):
            normalize_command_aliases(
                ("portrait", "--m"),
                context=CONTEXT_GENERATION,
            )

    def test_semantic_redraw_uses_its_own_mode_values(self) -> None:
        self.assertEqual(
            normalize_command_aliases(
                ("换衣服", "--m", "p", "--p", "b"),
                context=CONTEXT_SEMANTIC_REDRAW,
            ),
            ("换衣服", "--mode", "preserve", "--pipeline", "base"),
        )
        self.assertEqual(
            normalize_command_aliases(
                ("重新画", "--mode", "f"),
                context=CONTEXT_SEMANTIC_REDRAW,
            ),
            ("重新画", "--mode", "free"),
        )

    def test_inpaint_uses_quick_and_lanpaint_short_values(self) -> None:
        self.assertEqual(
            normalize_command_aliases(
                ("修手", "--m", "q"),
                context=CONTEXT_INPAINT,
            ),
            ("修手", "--mode", "quick"),
        )
        self.assertEqual(
            normalize_command_aliases(
                ("精修", "--mode", "l"),
                context=CONTEXT_INPAINT,
            ),
            ("精修", "--mode", "lanpaint"),
        )

    def test_character_swap_aliases_are_isolated_from_generation(self) -> None:
        actual = normalize_command_aliases(
            (
                "A",
                "->",
                "B",
                "--m",
                "k",
                "--w",
                "0.65",
                "--pr",
                "风格2",
                "--sz",
                "832x1216",
                "--n",
                "old outfit",
                "--v",
                "--nl",
            ),
            context=CONTEXT_CHARACTER_SWAP,
        )
        self.assertEqual(
            actual,
            (
                "A",
                "->",
                "B",
                "--mode",
                "keep-outfit",
                "--weight",
                "0.65",
                "--preset",
                "风格2",
                "--size",
                "832x1216",
                "--negative",
                "old outfit",
                "--preview",
                "--no-character-lora",
            ),
        )
        self.assertEqual(
            normalize_command_aliases(
                ("A", "->", "B", "--m", "t", "--no-lora"),
                context=CONTEXT_CHARACTER_SWAP,
            ),
            (
                "A",
                "->",
                "B",
                "--mode",
                "target-outfit",
                "--no-character-lora",
            ),
        )

    def test_unknown_option_is_not_fuzzy_matched(self) -> None:
        self.assertEqual(
            normalize_command_aliases(
                ("portrait", "--pip", "r"),
                context=CONTEXT_GENERATION,
            ),
            ("portrait", "--pip", "r"),
        )
        with self.assertRaisesRegex(CommandAliasError, "仅支持"):
            normalize_command_aliases(
                ("portrait", "--pipeline", "it"),
                context=CONTEXT_GENERATION,
            )

    def test_input_is_not_mutated(self) -> None:
        tokens = ["portrait", "--p", "b", "--m", "p", "d"]
        snapshot = list(tokens)
        normalize_command_aliases(tokens, context=CONTEXT_GENERATION)
        self.assertEqual(tokens, snapshot)

    def test_unknown_context_is_rejected(self) -> None:
        with self.assertRaisesRegex(CommandAliasError, "不支持的命令别名上下文"):
            normalize_command_aliases(("portrait",), context="unknown")


if __name__ == "__main__":
    unittest.main()
