from __future__ import annotations

import asyncio
import importlib
import types
import unittest
from pathlib import Path

from ..models import GeneratedImagePaths, PluginSettings
from ..services.lora_presets import LoraPresetRegistry
from ..services.prompt_director import PromptDirector, PromptDirectorError
from .test_main_compat import _install_astrbot_stubs


class PromptRoutingPerformanceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _settings() -> PluginSettings:
        return PluginSettings.from_mapping(
            {
                "prompt_llm_provider_id": "test-provider",
                "enable_lora_tool": True,
                "enable_local_intent_router": True,
                "structured_director_mode": "legacy",
            }
        )

    def _plugin(self, context: object) -> object:
        settings = self._settings()
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = settings
        plugin.context = context
        plugin._director = PromptDirector(
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "director_reference.txt",
            settings,
        )
        plugin._director_error = ""
        plugin._provider_slots = asyncio.Semaphore(2)
        plugin._internal_llm_events = set()
        plugin._lora_presets = LoraPresetRegistry([], max_loras=12)
        plugin._semantic_index = types.SimpleNamespace(entries={})
        plugin._find_requested_style_preset = lambda _text: ""
        plugin._get_director_output_tool_set = lambda: None
        plugin._get_lora_tool_set = lambda: object()
        return plugin

    async def test_plain_drawing_uses_llm_generate_not_tool_loop(self) -> None:
        class Context:
            llm_calls = 0
            tool_calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.llm_calls += 1
                return types.SimpleNamespace(
                    completion_text='<pic prompt="1girl, red dress, portrait">'
                )

            async def tool_loop_agent(self, **_kwargs: object) -> object:
                self.tool_calls += 1
                raise AssertionError("ordinary drawing must not enter tool loop")

        context = Context()
        plugin = self._plugin(context)
        instruction, _provider = await plugin._generate_directed_instruction(
            object(),
            "画一只猫，坐在窗台上",
        )

        self.assertEqual(instruction.prompt, "1girl, red dress, portrait")
        self.assertEqual(context.llm_calls, 1)
        self.assertEqual(context.tool_calls, 0)

    async def test_explicit_lora_request_keeps_tool_path(self) -> None:
        class Context:
            llm_calls = 0
            tool_calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.llm_calls += 1
                raise AssertionError("explicit LoRA intent should use tool loop")

            async def tool_loop_agent(self, **_kwargs: object) -> object:
                self.tool_calls += 1
                return types.SimpleNamespace(
                    completion_text=(
                        '<pic prompt="1girl, portrait, '
                        '<lora:characters/denia:0.8>">'
                    )
                )

        context = Context()
        plugin = self._plugin(context)
        instruction, _provider = await plugin._generate_directed_instruction(
            object(),
            "使用 LoRA characters/denia 画角色肖像",
        )

        self.assertIn("<lora:characters/denia:0.8>", instruction.prompt)
        self.assertEqual(context.llm_calls, 0)
        self.assertEqual(context.tool_calls, 1)

    async def test_provider_failure_prose_never_becomes_prompt(self) -> None:
        class Context:
            async def llm_generate(self, **_kwargs: object) -> object:
                return types.SimpleNamespace(
                    completion_text=(
                        "All chat models failed: EmptyModelOutputError: "
                        "OpenAI completion has no choices. response_id=private"
                    )
                )

        plugin = self._plugin(Context())
        with self.assertRaises(PromptDirectorError) as raised:
            await plugin._generate_directed_instruction(object(), "画一只猫")
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(raised.exception.detail, "all_models_failed")

    async def test_provider_preparation_can_overlap_while_comfy_execution_is_serial(self) -> None:
        plugin = self._plugin(object())
        plugin._provider_slots = asyncio.Semaphore(2)
        plugin._generation_slots = asyncio.Semaphore(1)

        provider_entered = 0
        both_provider_calls_entered = asyncio.Event()
        release_providers = asyncio.Event()

        async def provider_worker() -> None:
            nonlocal provider_entered
            async with plugin._provider_slot():
                provider_entered += 1
                if provider_entered == 2:
                    both_provider_calls_entered.set()
                await release_providers.wait()

        provider_tasks = [
            asyncio.create_task(provider_worker()),
            asyncio.create_task(provider_worker()),
        ]
        await asyncio.wait_for(both_provider_calls_entered.wait(), timeout=1)
        self.assertEqual(provider_entered, 2)
        release_providers.set()
        await asyncio.gather(*provider_tasks)

        class Client:
            active = 0
            maximum = 0
            counter = 0

            async def submit(self, _workflow):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                self.counter += 1
                return f"prompt-{self.counter}"

            async def wait_for_images(self, _prompt_id, _preferred):
                await asyncio.sleep(0.02)
                self.active -= 1
                return ()

        client = Client()
        plugin._client = client
        plugin._temp_dir = Path(".")

        async def comfy_worker(index: int) -> None:
            await plugin._submit_wait_download(
                self.main.GenerationJob(str(index), "test", 0.0),
                {"job": index},
                ("out",),
                GeneratedImagePaths(),
                active_state="generating",
            )

        await asyncio.gather(comfy_worker(1), comfy_worker(2))
        self.assertEqual(client.maximum, 1)


if __name__ == "__main__":
    unittest.main()
