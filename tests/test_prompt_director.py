"""提示词导演的 LLM 控制标签解析测试。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from ..models import PluginSettings
from ..services.prompt_director import PromptDirector, PromptDirectorError


class PictureResponseParserTests(unittest.TestCase):
    """普通 LLM 回复应正确拆分正文与绘图任务。"""

    def test_extracts_multiple_prompts_in_source_order(self) -> None:
        """多个 pic 标签应按出现顺序提取并规范化。"""
        output = (
            '第一张。<pic prompt="1girl, white hair &amp; blue eyes">\n'
            "第二张。<PIC prompt='city skyline,\nnight' />"
        )

        prompts = PromptDirector.extract_pic_prompts(output)

        self.assertEqual(
            prompts,
            ["1girl, white hair & blue eyes", "city skyline, night"],
        )

    def test_think_content_is_ignored_for_prompt_extraction(self) -> None:
        """隐藏思考中的 pic 标签不得触发绘图。"""
        output = (
            '<think>候选方案 <pic prompt="discarded draft"></think>'
            '最终方案 <pic prompt="1cat, cyberpunk city">'
        )

        self.assertEqual(
            PromptDirector.extract_pic_prompts(output),
            ["1cat, cyberpunk city"],
        )

    def test_clean_response_keeps_body_and_removes_all_control_tags(self) -> None:
        """清理后应保留正文格式，不泄露 think 或 pic 控制内容。"""
        output = (
            "我选择了雨夜街景。\n\n"
            "<think>内部推理\n不应展示</think>\n"
            '<pic prompt="1cat, rainy tokyo">\n'
            "图片生成后我会发给你。\n"
            "<pic prompt='close-up, neon lights' />"
        )

        cleaned = PromptDirector.clean_response_text(output)

        self.assertEqual(
            cleaned,
            "我选择了雨夜街景。\n\n图片生成后我会发给你。",
        )

    def test_parse_response_can_limit_prompts_but_cleans_every_tag(self) -> None:
        """数量限制仅影响返回任务，全部标签仍从正文中移除。"""
        output = '开始生成。<pic prompt="first scene"><pic prompt="second scene">完成。'

        parsed = PromptDirector.parse_picture_response(output, max_prompts=1)

        self.assertEqual(parsed.prompts, ("first scene",))
        self.assertEqual(parsed.text, "开始生成。 完成。")

    def test_unclosed_think_block_is_hidden(self) -> None:
        """未闭合的 think 块也不应泄露或触发其中的标签。"""
        output = '可见正文。<think>隐藏 <pic prompt="secret draft">'

        parsed = PromptDirector.parse_picture_response(output)

        self.assertEqual(parsed.prompts, ())
        self.assertEqual(parsed.text, "可见正文。")

    def test_nested_think_blocks_are_fully_hidden(self) -> None:
        """嵌套 think 的外层结束前都属于隐藏内容。"""
        output = (
            "开头。<think>外层<think>内层</think>仍在外层"
            '<pic prompt="hidden"></think>结尾。'
        )

        parsed = PromptDirector.parse_picture_response(output)

        self.assertEqual(parsed.prompts, ())
        self.assertEqual(parsed.text, "开头。 结尾。")

    def test_clean_response_preserves_body_spacing(self) -> None:
        """正文自身的缩进和连续空格不应被控制标签清理改写。"""
        output = "说明：\n    缩进正文\nA  B<pic prompt='one image'>C"

        cleaned = PromptDirector.clean_response_text(output)

        self.assertEqual(cleaned, "说明：\n    缩进正文\nA  B C")

    def test_extract_prompt_remains_compatible(self) -> None:
        """原单提示词 API 继续支持 pic、JSON 和纯文本格式。"""
        self.assertEqual(
            PromptDirector.extract_prompt(
                '<think><pic prompt="draft"></think>'
                '<pic prompt="1girl, red dress"><pic prompt="ignored">'
            ),
            "1girl, red dress",
        )
        self.assertEqual(
            PromptDirector.extract_prompt('{"prompt": "1boy, black coat"}'),
            "1boy, black coat",
        )
        self.assertEqual(
            PromptDirector.extract_prompt("Final prompt: 1cat, sleeping"),
            "1cat, sleeping",
        )

    def test_selected_invalid_prompt_is_rejected(self) -> None:
        """被选中的 pic 提示词仍沿用单图 API 的英文校验。"""
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_pic_prompts('<pic prompt="一只猫">')

    def test_chinese_lora_filename_is_allowed(self) -> None:
        """LoRA 文件名可含中文，但其余提示词仍必须使用英文。"""
        prompt = PromptDirector.extract_prompt(
            '<pic prompt="<lora:角色/达妮娅:0.88>, 1girl, portrait">'
        )

        self.assertEqual(prompt, "<lora:角色/达妮娅:0.88>, 1girl, portrait")

    def test_negative_prompt_limit_is_rejected(self) -> None:
        """负数数量限制属于调用方参数错误。"""
        with self.assertRaises(ValueError):
            PromptDirector.parse_picture_response("正文", max_prompts=-1)

    def test_anima_v11_hybrid_prompt_is_accepted(self) -> None:
        prompt = PromptDirector.extract_prompt(
            '<pic prompt="1girl, long blue hair, smile, upper body, concert stage. '
            'A cheerful blue-haired idol smiles beneath the stage lights.">'
        )

        self.assertIn("concert stage. A cheerful", prompt)

    def test_optional_negative_attribute_is_aligned_with_each_picture(self) -> None:
        parsed = PromptDirector.parse_picture_response(
            '<pic prompt="1girl, red evening gown" '
            'negative="school uniform, necktie">'
            '<pic prompt="1cat, sleeping">'
        )

        self.assertEqual(
            parsed.prompts,
            ("1girl, red evening gown", "1cat, sleeping"),
        )
        self.assertEqual(
            parsed.negative_prompts,
            ("school uniform, necktie", ""),
        )
        self.assertEqual(
            PromptDirector.extract_prompt(
                '<pic prompt="1girl, red evening gown" negative="school uniform">'
            ),
            "1girl, red evening gown",
        )

    def test_picture_pipeline_and_edit_protocol_are_parsed(self) -> None:
        parsed = PromptDirector.parse_picture_response(
            '<pic prompt="1girl, portrait" pipeline="iterative">'
        )
        self.assertEqual(parsed.pipelines, ("iterative",))

        edited = PromptDirector.parse_picture_response(
            '正在处理。<edit prompt="red evening dress" mode="lanpaint" '
            'negative="school uniform">'
        )
        self.assertEqual(edited.prompts, ())
        self.assertEqual(len(edited.edits), 1)
        self.assertEqual(edited.edits[0].mode, "lanpaint")
        self.assertEqual(edited.edits[0].negative_prompt, "school uniform")
        self.assertEqual(edited.text, "正在处理。")

    def test_unknown_pipeline_or_edit_mode_is_rejected(self) -> None:
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_pic_instructions(
                '<pic prompt="1girl" pipeline="magic">'
            )
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_edit_instructions(
                '<edit prompt="red dress" mode="guess">'
            )

    def test_think_edit_never_triggers(self) -> None:
        parsed = PromptDirector.parse_picture_response(
            '<think><edit prompt="hidden" mode="quick"></think>正文'
        )
        self.assertEqual(parsed.edits, ())
        self.assertEqual(parsed.text, "正文")

    def test_negative_attribute_rejects_lora_or_chinese_content(self) -> None:
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_instruction(
                '<pic prompt="1girl" negative="<lora:bad:1.0>">'
            )
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_instruction(
                '<pic prompt="1girl" negative="校服">'
            )

    def test_builtin_reference_covers_plugin_contract(self) -> None:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_reference.txt"
        )
        director = PromptDirector(reference, PluginSettings.from_mapping({}))
        system_prompt = director._system_prompt()

        self.assertIn('绘图触发基础格式是 `<pic prompt="...">`', system_prompt)
        self.assertIn("自动强制刷新 LoRA Manager", system_prompt)
        self.assertIn("detail=true", system_prompt)
        self.assertIn("1️⃣Lora堆（默认）", system_prompt)
        self.assertIn("English natural-language description", system_prompt)
        self.assertIn("不可变身份", system_prompt)
        self.assertIn("0.55 至 0.75", system_prompt)
        self.assertIn('negative="..."', system_prompt)
        self.assertIn("现有图片独立 RTX 放大", system_prompt)
        self.assertIn("把图里的手修好", system_prompt)
        self.assertIn("唯一操作类型", system_prompt)
        self.assertIn("整图语义重绘", system_prompt)
        self.assertIn("重新生成而非像素级修改", system_prompt)
        self.assertIn("不得自动套用默认风格001", system_prompt)

    def test_custom_prompt_keeps_runtime_constraints(self) -> None:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_reference.txt"
        )
        director = PromptDirector(
            reference,
            PluginSettings.from_mapping(
                {"auto_draw_system_prompt": "请使用温柔的杂志插画口吻。"}
            ),
        )

        system_prompt = director._system_prompt()

        self.assertIn("请使用温柔的杂志插画口吻", system_prompt)
        self.assertIn("不可变身份", system_prompt)
        self.assertIn("不得覆盖上面的输出", system_prompt)


class PromptDirectorToolTimeoutTests(unittest.IsolatedAsyncioTestCase):
    """LoRA 工具链应有独立预算，且失败时不得静默降级。"""

    @staticmethod
    def _director(**overrides: object) -> PromptDirector:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_reference.txt"
        )
        settings = PluginSettings.from_mapping(
            {
                "prompt_llm_provider_id": "test-provider",
                **overrides,
            }
        )
        return PromptDirector(reference, settings)

    async def test_tool_budget_covers_manager_scan_and_all_agent_steps(self) -> None:
        director = self._director(
            prompt_llm_timeout=120,
            lora_catalog_timeout=15,
            lora_manager_scan_timeout=180,
            lora_tool_max_steps=4,
        )
        captured: dict[str, object] = {}
        wait_timeouts: list[float | None] = []

        class Context:
            async def tool_loop_agent(self, **kwargs: object) -> object:
                captured.update(kwargs)
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="1girl, portrait">'},
                )()

        async def capture_wait_for(awaitable: object, timeout: float | None) -> object:
            wait_timeouts.append(timeout)
            return await awaitable  # type: ignore[misc]

        with patch(
            "astrbot_plugin_comfy_anima.services.prompt_director.asyncio.wait_for",
            new=capture_wait_for,
        ):
            prompt, provider_id, negative = await director.generate_with_negative(
                Context(),
                object(),
                "draw a portrait",
                tools=object(),
            )

        self.assertEqual(prompt, "1girl, portrait")
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(negative, "")
        self.assertEqual(captured["tool_call_timeout"], 195)
        self.assertEqual(captured["max_steps"], 4)
        self.assertEqual(wait_timeouts, [900])

    async def test_tool_failure_never_retries_without_tools(self) -> None:
        director = self._director()

        class Context:
            llm_generate_calls = 0

            async def tool_loop_agent(self, **kwargs: object) -> object:
                raise RuntimeError("manager scan failed")

            async def llm_generate(self, **kwargs: object) -> object:
                self.llm_generate_calls += 1
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="unsafe fallback">'},
                )()

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_with_negative(
                context,
                object(),
                "draw with a LoRA",
                tools=object(),
            )

        self.assertIn("LoRA 查询工具调用失败", raised.exception.user_message)
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(context.llm_generate_calls, 0)

    async def test_missing_tool_loop_support_is_not_silently_ignored(self) -> None:
        director = self._director()

        class Context:
            llm_generate_calls = 0

            async def llm_generate(self, **kwargs: object) -> object:
                self.llm_generate_calls += 1
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="unsafe fallback">'},
                )()

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_with_negative(
                context,
                object(),
                "draw with a LoRA",
                tools=object(),
            )

        self.assertIn("不支持 LoRA 查询工具", raised.exception.user_message)
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(context.llm_generate_calls, 0)

    async def test_invalid_tool_result_is_fatal(self) -> None:
        director = self._director()

        class Context:
            async def tool_loop_agent(self, **_kwargs: object) -> object:
                return type("Response", (), {"completion_text": "<pic>"})()

        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_with_negative(
                Context(),
                object(),
                "draw with a LoRA",
                tools=object(),
            )

        self.assertIn("结果无效", raised.exception.user_message)
        self.assertTrue(raised.exception.fatal)

    async def test_plain_llm_call_keeps_configured_timeout(self) -> None:
        director = self._director(prompt_llm_timeout=120)
        wait_timeouts: list[float | None] = []

        class Context:
            async def llm_generate(self, **kwargs: object) -> object:
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="1girl, portrait">'},
                )()

        async def capture_wait_for(awaitable: object, timeout: float | None) -> object:
            wait_timeouts.append(timeout)
            return await awaitable  # type: ignore[misc]

        with patch(
            "astrbot_plugin_comfy_anima.services.prompt_director.asyncio.wait_for",
            new=capture_wait_for,
        ):
            await director.generate_with_negative(
                Context(),
                object(),
                "draw a portrait",
            )

        self.assertEqual(wait_timeouts, [120])

    async def test_function_call_plan_is_parsed_without_visible_text(self) -> None:
        director = self._director(structured_director_mode="function_call")
        output_tools = object()

        class Context:
            async def llm_generate(self, **kwargs: object) -> object:
                self.tools = kwargs.get("tools")
                return type(
                    "Response",
                    (),
                    {
                        "tools_call_name": "emit_anima_plan_v1",
                        "tools_call_args": {
                            "positive_tags": "1girl, orange sunset",
                            "negative_tags": "lowres",
                            "pipeline": "base",
                        },
                    },
                )()

        context = Context()
        instruction, provider_id = await director.generate_instruction(
            context,
            object(),
            "draw a girl at sunset",
            output_tools=output_tools,
        )

        self.assertIs(context.tools, output_tools)
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(instruction.prompt, "1girl, orange sunset")
        self.assertEqual(instruction.negative_prompt, "lowres")
        self.assertEqual(instruction.pipeline, "base")

    async def test_auto_mode_falls_back_when_context_rejects_tools_kwarg(self) -> None:
        director = self._director(structured_director_mode="auto")

        class Context:
            calls = 0

            async def llm_generate(self, **kwargs: object) -> object:
                self.calls += 1
                if "tools" in kwargs:
                    raise TypeError("tools unsupported")
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="1girl, portrait">'},
                )()

        context = Context()
        instruction, _ = await director.generate_instruction(
            context,
            object(),
            "draw a portrait",
            output_tools=object(),
        )
        self.assertEqual(context.calls, 2)
        self.assertEqual(instruction.prompt, "1girl, portrait")


class PromptDirectorProviderFailureTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _director() -> PromptDirector:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_reference.txt"
        )
        return PromptDirector(
            reference,
            PluginSettings.from_mapping(
                {"prompt_llm_provider_id": "test-provider"}
            ),
        )

    def test_provider_error_markers_are_never_accepted_as_prompt(self) -> None:
        samples = (
            "All chat models failed: EmptyModelOutputError: OpenAI completion has no choices. response_id=private",
            "EmptyModelOutputError",
            "OpenAI completion has no choices",
            "ProviderError: failed",
            "APIError: failed",
            "AuthenticationError: failed",
            "RateLimitError: failed",
            "TimeoutError: failed",
            '<pic prompt="All chat models failed: EmptyModelOutputError">',
            '{"prompt":"OpenAI completion has no choices, response_id=private"}',
        )
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(PromptDirectorError):
                PromptDirector.extract_instruction(sample)

        self.assertEqual(
            PromptDirector.extract_instruction(
                '<pic prompt="1girl, error screen motif, glitch art">'
            ).prompt,
            "1girl, error screen motif, glitch art",
        )

    def test_strict_protocol_rejects_plain_english_fallback(self) -> None:
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_instruction(
                "Final prompt: 1girl, red dress",
                strict_protocol=True,
            )
        self.assertEqual(
            PromptDirector.extract_instruction(
                '<pic prompt="1girl, red dress">',
                strict_protocol=True,
            ).prompt,
            "1girl, red dress",
        )

    async def test_invalid_protocol_retries_once_then_accepts_pic(self) -> None:
        director = self._director()

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                output = (
                    "not a valid drawing protocol"
                    if self.calls == 1
                    else '<pic prompt="1girl, red dress">'
                )
                return type("Response", (), {"completion_text": output})()

        context = Context()
        instruction, provider_id = await director.generate_instruction(
            context,
            object(),
            "draw",
        )
        self.assertEqual(context.calls, 2)
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(instruction.prompt, "1girl, red dress")

    async def test_two_invalid_outputs_fail_closed_with_sanitized_detail(self) -> None:
        director = self._director()

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": (
                            "All chat models failed: EmptyModelOutputError: "
                            "OpenAI completion has no choices. response_id=private-secret"
                        )
                    },
                )()

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_instruction(context, object(), "draw")
        self.assertEqual(context.calls, 1)
        self.assertTrue(raised.exception.fatal)
        self.assertNotIn("private-secret", raised.exception.detail)
        self.assertNotIn("response_id=", raised.exception.detail)
        self.assertEqual(raised.exception.detail, "all_models_failed")


if __name__ == "__main__":
    unittest.main()
