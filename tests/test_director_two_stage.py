"""Director probe-then-structured two-stage flow tests."""

import json
import types
import unittest
from pathlib import Path

from ..models import PluginSettings
from ..services.prompt_director import PromptDirector, PromptDirectorError


def _response(text: str) -> object:
    return types.SimpleNamespace(completion_text=text)


class DirectorTwoStageTests(unittest.IsolatedAsyncioTestCase):
    def _director(self) -> PromptDirector:
        reference = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "director_creative_default.txt"
        )
        return PromptDirector(
            reference,
            PluginSettings.from_mapping({"prompt_llm_provider_id": "test-provider"}),
        )

    async def test_probe_then_structured_uses_evidence_in_second_stage(self) -> None:
        director = self._director()
        probe_calls: list[dict[str, object]] = []
        generate_calls: list[dict[str, object]] = []

        class Context:
            async def tool_loop_agent(self, **kwargs: object) -> object:
                probe_calls.append(dict(kwargs))
                return _response("probe evidence: denia_lorav4, style001")

            async def llm_generate(self, **kwargs: object) -> object:
                generate_calls.append(dict(kwargs))
                return _response(
                    json.dumps(
                        {
                            "positive_tags": "1girl, portrait",
                            "negative_tags": "",
                            "pipeline": "base",
                        }
                    )
                )

        context = Context()
        output_tools = object()
        instruction, provider_id = (
            await director.generate_instruction_probe_then_structured(
                context,
                object(),
                "draw a portrait",
                tools=object(),
                output_tools=output_tools,
            )
        )

        self.assertEqual(instruction.prompt, "1girl, portrait")
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(len(probe_calls), 1)
        self.assertEqual(len(generate_calls), 1)
        self.assertIn(
            "<verified_asset_evidence>", str(generate_calls[0]["prompt"])
        )
        self.assertIn(
            "probe evidence: denia_lorav4, style001",
            str(generate_calls[0]["prompt"]),
        )
        self.assertIs(generate_calls[0]["tools"], output_tools)

    async def test_probe_stage_never_submits_its_prose(self) -> None:
        director = self._director()

        class Context:
            async def tool_loop_agent(self, **_kwargs: object) -> object:
                return _response("I refuse to output a structured plan.")

            async def llm_generate(self, **kwargs: object) -> object:
                return _response(
                    json.dumps(
                        {
                            "positive_tags": "1girl, portrait",
                            "negative_tags": "",
                            "pipeline": "rtx",
                        }
                    )
                )

        instruction, _provider_id = (
            await director.generate_instruction_probe_then_structured(
                Context(),
                object(),
                "draw a portrait",
                tools=object(),
                output_tools=object(),
            )
        )
        self.assertEqual(instruction.prompt, "1girl, portrait")
        self.assertNotIn("I refuse", instruction.prompt)

    async def test_probe_failure_is_fatal(self) -> None:
        director = self._director()

        class Context:
            async def tool_loop_agent(self, **_kwargs: object) -> object:
                raise RuntimeError("tool executor exploded")

            async def llm_generate(self, **_kwargs: object) -> object:
                raise AssertionError("generate must not run after probe failure")

        with self.assertRaises(PromptDirectorError) as caught:
            await director.generate_instruction_probe_then_structured(
                Context(),
                object(),
                "draw a portrait",
                tools=object(),
                output_tools=object(),
            )
        self.assertTrue(caught.exception.fatal)


if __name__ == "__main__":
    unittest.main()
