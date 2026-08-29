"""307 protocol/resource split tests: code owns protocol, resources own taste."""

import unittest
from pathlib import Path

from ..services.prompt_catalog import PromptCatalog
from ..services.prompt_contracts import (
    PROMPT_CONTRACT_VERSION,
    assemble_director_system_prompt,
    build_auto_draw_contract,
)

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_FORBIDDEN_LITERALS = ("<pic", "emit_anima_plan_v1", "必须返回 JSON", "Terminal seal")


class PromptContractSplitTests(unittest.TestCase):
    def test_contract_version_is_31(self) -> None:
        self.assertEqual(PROMPT_CONTRACT_VERSION, "3.1")

    def test_new_resources_have_no_protocol_literals(self) -> None:
        catalog = PromptCatalog(_PROMPT_DIR)
        for resource in catalog.resources():
            lowered = resource.text.casefold()
            for literal in _FORBIDDEN_LITERALS:
                with self.subTest(prompt_id=resource.prompt_id, literal=literal):
                    self.assertNotIn(literal.casefold(), lowered)

    def test_new_resources_are_catalog_scannable(self) -> None:
        catalog = PromptCatalog(_PROMPT_DIR)
        ids = {item["prompt_id"] for item in catalog.status()}
        self.assertIn("chat_roleplay_draw", ids)
        self.assertIn("director_draw", ids)
        self.assertIn("director_semantic_redraw", ids)
        self.assertIn("director_masked_redraw", ids)
        self.assertIn("director_character_swap_edit", ids)
        self.assertIn("director_prompt_plan", ids)
        self.assertIn("director_control_draw", ids)
        self.assertIn("director_creative_default", ids)

    def test_legacy_files_are_not_scanned(self) -> None:
        catalog = PromptCatalog(_PROMPT_DIR)
        ids = {item["prompt_id"] for item in catalog.status()}
        self.assertNotIn("anima_prompt_source", ids)
        self.assertNotIn("director_reference", ids)

    def test_chat_and_director_defaults_are_not_identical(self) -> None:
        catalog = PromptCatalog(_PROMPT_DIR)
        chat = catalog.get("chat_roleplay_draw").text
        creative = catalog.get("director_creative_default").text
        self.assertNotEqual(chat, creative)
        self.assertIn("角色", chat)
        self.assertIn("稳定", creative)

    def test_director_assembly_order_is_fixed(self) -> None:
        contract = assemble_director_system_prompt(
            task_kind="draw",
            task_prompt="TASK TASTE",
            creative_preference="CREATIVE TASTE",
            transport="function",
        )
        self.assertLess(contract.index("Prompt contract version"), contract.index("TASK TASTE"))
        self.assertLess(contract.index("TASK TASTE"), contract.index("CREATIVE TASTE"))
        self.assertLess(contract.index("CREATIVE TASTE"), contract.index("Terminal seal"))

    def test_auto_draw_contract_keeps_protocol_before_roleplay_prompt(self) -> None:
        contract = build_auto_draw_contract(
            message="画一张",
            roleplay_prompt="ROLEPLAY TASTE",
        )
        self.assertLess(contract.index("ordinary-chat protocol"), contract.index("ROLEPLAY TASTE"))
        self.assertIn("The transport format above remains authoritative.", contract)


if __name__ == "__main__":
    unittest.main()
