"""提示词导演的 LLM 控制标签解析测试。"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from ..models import PluginSettings
from ..services.prompt_composer import PromptComposer, PromptDiagnosticsStore
from ..services.prompt_director import (
    PictureInstruction,
    PromptDirector,
    PromptDirectorError,
)
from ..services.prompt_contracts import CAPABILITY_DANBOORU


class PictureResponseParserTests(unittest.TestCase):
    """普通 LLM 回复应正确拆分正文与绘图任务。"""

    def test_pipeline_aliases_for_model_synonyms(self) -> None:
        """模型输出的常见管线同义词应归一化，未知值仍拒绝。"""

        for raw in ("draw", "txt2img", "text2img", "文生图", "生图", "生成",
                    "standard", "normal"):
            self.assertEqual(PromptDirector._normalize_pipeline(raw), "base", raw)
        self.assertEqual(PromptDirector._normalize_pipeline("高清放大"), "rtx")
        with self.assertRaises(PromptDirectorError):
            PromptDirector._normalize_pipeline("unknown_pipeline")

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

    def test_pic_character_declarations_are_preserved_per_image(self) -> None:
        parsed = PromptDirector.parse_picture_response(
            '<pic prompt="1girl, rio, stage" characters="Rio|Blue Archive">'
            '<pic prompt="1girl, firefly, classroom" '
            'characters="Firefly|Honkai: Star Rail">'
        )

        self.assertEqual(
            parsed.character_queries,
            (
                ("Rio|Blue Archive",),
                ("Firefly|Honkai: Star Rail",),
            ),
        )

    def test_prompt_text_cannot_forge_top_level_character_attribute(self) -> None:
        instruction = PromptDirector.extract_instruction(
            "<pic prompt='1girl, sign reading characters=\"Evil|Work\"'>"
        )

        self.assertEqual(instruction.character_queries, ())
        self.assertIn("characters=", instruction.prompt)

    def test_duplicate_or_unknown_control_attributes_fail_closed(self) -> None:
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_pic_instructions(
                '<pic prompt="1girl" prompt="1boy">'
            )
        with self.assertRaises(PromptDirectorError):
            PromptDirector.extract_pic_instructions(
                '<pic prompt="1girl" confidence="0.9">'
            )

    def test_character_html_entity_is_unescaped_before_separator_split(self) -> None:
        instruction = PromptDirector.extract_instruction(
            '<pic prompt="1girl, rio" characters="Rio|Blue &amp; Archive">'
        )

        self.assertEqual(instruction.character_queries, ("Rio|Blue & Archive",))

    def test_invalid_character_hint_types_and_delimiters_are_rejected(self) -> None:
        with self.assertRaises(PromptDirectorError):
            PromptDirector._normalize_character_queries(["Rio", 42])
        with self.assertRaises(PromptDirectorError):
            PromptDirector._normalize_character_queries("Rio|Blue|Archive")
        with self.assertRaises(PromptDirectorError):
            PromptDirector._normalize_character_queries("Rio\u202e|Blue Archive")

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

    def test_strict_pic_transport_requires_one_sealed_tag(self) -> None:
        instruction = PromptDirector.extract_instruction(
            '\n  <pic prompt="1girl, red dress" />\t',
            strict_protocol=True,
        )
        self.assertEqual(instruction.prompt, "1girl, red dress")

        invalid_outputs = (
            '正文 <pic prompt="1girl, red dress">',
            '<pic prompt="1girl, red dress"> {"status":"ok"}',
            '<pic prompt="first"><pic prompt="second">',
            '<pic prompt="first"><edit prompt="second" mode="quick">',
            '{"prompt":"1girl, red dress"}',
            '<think>hidden</think><pic prompt="1girl, red dress">',
        )
        for output in invalid_outputs:
            with self.subTest(output=output), self.assertRaises(
                PromptDirectorError
            ) as raised:
                PromptDirector.extract_instruction(output, strict_protocol=True)
            self.assertEqual(raised.exception.detail, "invalid_picture_protocol")

    def test_strict_edit_transport_requires_one_sealed_tag(self) -> None:
        instruction = PromptDirector.extract_edit_instruction(
            '\n<edit prompt="red dress" mode="quick">\t',
            strict_protocol=True,
        )
        self.assertEqual(instruction.prompt, "red dress")

        invalid_outputs = (
            '正文 <edit prompt="red dress" mode="quick">',
            '<edit prompt="red dress"><edit prompt="blue dress">',
            '<edit prompt="red dress"><pic prompt="1girl">',
            '{"prompt":"red dress","mode":"quick"}',
            '<think>hidden</think><edit prompt="red dress">',
        )
        for output in invalid_outputs:
            with self.subTest(output=output), self.assertRaises(
                PromptDirectorError
            ) as raised:
                PromptDirector.extract_edit_instruction(
                    output,
                    strict_protocol=True,
                )
            self.assertEqual(raised.exception.detail, "invalid_edit_protocol")

    def test_control_fields_cannot_embed_transport_tags(self) -> None:
        invalid_outputs = (
            '<pic prompt="1girl, &lt;edit mode=\'quick\'&gt;">',
            '<pic prompt="1girl" negative="lowres, &lt;think&gt;hidden">',
            '<pic prompt="1girl" pipeline="base&lt;pic&gt;">',
            (
                '<pic prompt="1girl" '
                'characters="Rio|Blue Archive&lt;/edit&gt;">'
            ),
            '<edit prompt="red dress, &lt;pic prompt=\'bad\'&gt;">',
            '<edit prompt="red dress" mode="quick&lt;think&gt;">',
        )
        for output in invalid_outputs:
            parser = (
                PromptDirector.extract_edit_instruction
                if output.startswith("<edit")
                else PromptDirector.extract_instruction
            )
            with self.subTest(output=output), self.assertRaises(
                PromptDirectorError
            ) as raised:
                parser(output, strict_protocol=True)
            self.assertEqual(raised.exception.detail, "embedded_control_tag")

        with self.assertRaises(PromptDirectorError) as raised:
            PromptDirector.extract_instruction(
                '<pic prompt="1girl, <think>hidden</think>">'
            )
        self.assertEqual(raised.exception.detail, "embedded_control_tag")

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

    def test_empty_pipeline_stays_unspecified(self) -> None:
        instruction = PromptDirector.extract_instruction(
            '<pic prompt="1girl, portrait" pipeline="">'
        )

        self.assertEqual(instruction.pipeline, "")

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
            Path(__file__).resolve().parents[1] / "prompts" / "director_creative_default.txt"
        )
        director = PromptDirector(reference, PluginSettings.from_mapping({}))
        system_prompt = director._system_prompt(capabilities=())

        self.assertIn("Prompt contract version: 3.1", system_prompt)
        self.assertIn('Return exactly one `<pic prompt="...">`', system_prompt)
        self.assertIn("not authoritative for Danbooru identity", system_prompt)
        self.assertIn("角色连续性优先于堆砌信息", system_prompt)
        self.assertIn("景别决定细节", system_prompt)
        self.assertIn("不叠加互相竞争的时间与光源", system_prompt)
        self.assertIn("Terminal seal", system_prompt)
        self.assertNotIn("list_anima_loras", system_prompt)
        self.assertNotIn("search_anima_danbooru_tags", system_prompt)
        self.assertLess(len(system_prompt), 9000)

    def test_system_prompt_exposes_dynamic_bounded_danbooru_status(self) -> None:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_creative_default.txt"
        )
        status = {
            "ready": True,
            "tag_count": 111513,
            "alias_count": 28903,
            "revision": "safe-rev-1",
            "source": "must-not-leak",
            "sha256": "must-not-leak",
        }
        director = PromptDirector(
            reference,
            PluginSettings.from_mapping({}),
            danbooru_status_provider=lambda: status,
        )

        prompt = director._system_prompt(capabilities=(CAPABILITY_DANBOORU,))
        self.assertIn("canonical_tags=111513", prompt)
        self.assertIn("aliases=28903", prompt)
        self.assertIn("revision=safe-rev-1", prompt)
        self.assertIn("search_anima_danbooru_tags", prompt)
        self.assertIn("verified exact canonical/alias", prompt)
        self.assertNotIn("must-not-leak", prompt)

        status.clear()
        status.update({"ready": False, "error": "private database path"})
        refreshed = director._system_prompt(capabilities=(CAPABILITY_DANBOORU,))
        self.assertIn("ready=false", refreshed)
        self.assertNotIn("private database path", refreshed)

        no_capability = director._system_prompt(capabilities=())
        self.assertNotIn("search_anima_danbooru_tags", no_capability)
        self.assertNotIn("canonical_tags=", no_capability)

    def test_custom_prompt_keeps_runtime_constraints(self) -> None:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_creative_default.txt"
        )
        director = PromptDirector(
            reference,
            PluginSettings.from_mapping(
                {"director_creative_preference": "请使用温柔的杂志插画口吻。"}
            ),
        )

        system_prompt = director._system_prompt()

        self.assertIn("请使用温柔的杂志插画口吻", system_prompt)
        self.assertIn(
            "不得覆盖上面的传输、证据、实时资产和安全约束",
            system_prompt,
        )
        self.assertIn("Density: Standard", system_prompt)
        self.assertIn("Terminal seal", system_prompt)

        local_task_prompt = director._system_prompt(task_kind="prompt_plan")
        self.assertNotIn("温柔的杂志插画口吻", local_task_prompt)
        self.assertTrue(system_prompt.rstrip().endswith("nothing else."))


class PromptDirectorToolTimeoutTests(unittest.IsolatedAsyncioTestCase):
    """LoRA 工具链应有独立预算，且失败时不得静默降级。"""

    @staticmethod
    def _director(
        *,
        composer: PromptComposer | None = None,
        **overrides: object,
    ) -> PromptDirector:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_creative_default.txt"
        )
        settings = PluginSettings.from_mapping(
            {
                "prompt_llm_provider_id": "test-provider",
                **overrides,
            }
        )
        return PromptDirector(reference, settings, composer=composer)

    async def test_all_success_transports_share_one_local_composer(self) -> None:
        positive = (
            "1girl, holding flower, full body. "
            "She holds a flower while standing in a quiet garden."
        )
        outputs = (
            (
                "function_call",
                object(),
                {
                    "tools_call_name": "emit_anima_plan_v1",
                    "tools_call_args": {
                        "positive_tags": positive,
                        "negative_tags": "",
                        "pipeline": "base",
                    },
                },
            ),
            (
                "json",
                None,
                {
                    "completion_text": (
                        '{"positive_tags":"'
                        + positive
                        + '","negative_tags":"","pipeline":"base"}'
                    )
                },
            ),
            (
                "auto",
                None,
                {"completion_text": f'<pic prompt="{positive}">'},
            ),
        )
        results: list[PictureInstruction] = []

        for mode, output_tools, response_fields in outputs:
            with self.subTest(mode=mode):
                store = PromptDiagnosticsStore()
                director = self._director(
                    structured_director_mode=mode,
                    composer=PromptComposer(
                        "conservative",
                        diagnostics_store=store,
                        validation_mode="off",
                    ),
                )

                class Context:
                    calls = 0

                    async def llm_generate(self, **_kwargs: object) -> object:
                        self.calls += 1
                        return type("Response", (), response_fields)()

                context = Context()
                instruction, provider_id = await director.generate_instruction(
                    context,
                    object(),
                    "draw a girl holding a flower",
                    output_tools=output_tools,
                )

                self.assertEqual(context.calls, 1)
                self.assertEqual(provider_id, "test-provider")
                self.assertTrue(instruction.diagnostic_id)
                self.assertIsNotNone(instruction.diagnostics)
                assert instruction.diagnostics is not None
                self.assertEqual(instruction.diagnostics.source, "director")
                self.assertEqual(
                    instruction.diagnostics.provider_id,
                    "test-provider",
                )
                self.assertIn(instruction.diagnostics.pipeline, {"", "base"})
                stored = store.get(instruction.diagnostic_id)
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored.diagnostic_id, instruction.diagnostic_id)
                self.assertEqual(stored.adaptive_negative_added, ())
                self.assertGreater(stored.adaptive_negative_count, 0)
                results.append(instruction)

        self.assertEqual(
            {item.prompt for item in results},
            {positive},
        )
        negatives = {item.negative_prompt for item in results}
        self.assertEqual(len(negatives), 1)
        final_negative = negatives.pop()
        self.assertIn("bad hands", final_negative)
        self.assertIn("bad feet", final_negative)

    async def test_json_transport_rejects_duplicate_nan_unknown_and_nonobject(self) -> None:
        payloads = (
            '{"positive_tags":"1girl","positive_tags":"1boy"}',
            '{"positive_tags":"1girl","pipeline":NaN}',
            '{"positive_tags":"1girl","confidence":0.9}',
            '[{"positive_tags":"1girl"}]',
            '{"positive_tags":"1girl","prompt":"1boy"}',
            '{"positive_tags":"1girl","negative_tags":"lowres",'
            '"negative_prompt":"bad anatomy"}',
            '{"positive_tags":"1girl, &lt;edit&gt;"}',
            '{"positive_tags":"1girl","negative_tags":"&lt;think&gt;"}',
            '{"positive_tags":"1girl","pipeline":"base&lt;pic&gt;"}',
            '{"positive_tags":"1girl","characters":["Rio|&lt;edit&gt;"]}',
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                director = self._director(structured_director_mode="json")

                class Context:
                    calls = 0

                    async def llm_generate(self, **_kwargs: object) -> object:
                        self.calls += 1
                        return type(
                            "Response",
                            (),
                            {"completion_text": payload},
                        )()

                context = Context()
                with self.assertRaises(PromptDirectorError):
                    await director.generate_instruction(
                        context,
                        object(),
                        "draw a portrait",
                    )
                self.assertEqual(context.calls, 2)

    async def test_lookup_and_output_tools_fail_fast(self) -> None:
        director = self._director(structured_director_mode="auto")

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                raise AssertionError("LLM must not be called")

            async def tool_loop_agent(self, **_kwargs: object) -> object:
                self.calls += 1
                raise AssertionError("agent must not be called")

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_instruction(
                context,
                object(),
                "draw a portrait",
                tools=object(),
                output_tools=object(),
            )

        self.assertEqual(context.calls, 0)
        self.assertEqual(raised.exception.detail, "conflicting_tool_transports")
        self.assertTrue(raised.exception.fatal)

    def test_task_transport_contracts_are_mutually_scoped(self) -> None:
        director = self._director()
        masked = director._system_prompt(
            task_kind="masked_redraw",
            capabilities=(),
            transport="edit",
        )
        control = director._system_prompt(
            task_kind="control_draw",
            capabilities=(),
            transport="pic",
        )

        self.assertIn("exactly one `<edit", masked)
        self.assertNotIn("exactly one `<pic", masked)
        self.assertNotIn("scene sentence", masked)
        self.assertIn("image-conditioned Anima generation", control)
        self.assertIn("exactly one `<pic", control)
        self.assertNotIn("exactly one `<edit", control)

    async def test_composer_validation_failure_does_not_call_llm_twice(self) -> None:
        director = self._director(
            composer=PromptComposer(
                "off",
                tag_index={"1girl": True},
                validation_mode="strict",
            )
        )

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="1girl, invented_token">'},
                )()

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_instruction(context, object(), "draw")

        self.assertEqual(context.calls, 1)
        self.assertEqual(raised.exception.detail, "prompt_composition_failed")
        self.assertTrue(raised.exception.fatal)

    async def test_edit_uses_edit_diagnostic_source_without_scene_expansion(
        self,
    ) -> None:
        store = PromptDiagnosticsStore()
        director = self._director(
            composer=PromptComposer(
                "off",
                diagnostics_store=store,
                validation_mode="off",
            )
        )

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": (
                            '<edit prompt="red dress, detailed lace" '
                            'negative="school uniform" mode="quick">'
                        )
                    },
                )()

        context = Context()
        instruction, provider_id = await director.generate_edit_instruction(
            context,
            object(),
            "replace the masked clothes with a red dress",
        )

        self.assertEqual(context.calls, 1)
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(instruction.prompt, "red dress, detailed lace")
        self.assertNotIn(". ", instruction.prompt)
        self.assertEqual(instruction.negative_prompt, "school uniform")
        diagnostics = store.list(limit=1)[0]
        self.assertEqual(diagnostics.source, "edit")
        self.assertEqual(diagnostics.provider_id, "test-provider")

    async def test_edit_repair_exception_is_sanitized(self) -> None:
        director = self._director()

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                if self.calls == 1:
                    return type(
                        "Response",
                        (),
                        {"completion_text": "invalid edit transport"},
                    )()
                raise RuntimeError("private-provider-secret")

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_edit_instruction(
                context,
                object(),
                "replace the masked clothes",
            )

        self.assertEqual(context.calls, 2)
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(
            raised.exception.detail,
            "provider=test-provider, error_type=RuntimeError",
        )
        self.assertNotIn("private-provider-secret", raised.exception.detail)

    def test_composed_picture_instruction_is_idempotent(self) -> None:
        store = PromptDiagnosticsStore()
        director = self._director(
            composer=PromptComposer(
                "off",
                diagnostics_store=store,
                validation_mode="off",
            )
        )
        first = director.compose_picture_instruction(
            PictureInstruction("1girl, portrait"),
            provider_id="test-provider",
            source="chat_pic",
        )
        second = director.compose_picture_instruction(
            first,
            provider_id="test-provider",
            source="chat_pic",
        )

        self.assertIs(second, first)
        self.assertEqual(len(store), 1)
        self.assertEqual(first.diagnostics.source, "chat_pic")

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

    async def test_invalid_lookup_terminal_repairs_without_lookup_tools(self) -> None:
        director = self._director()
        lookup_calls: list[dict[str, object]] = []
        repair_calls: list[dict[str, object]] = []

        class Context:
            async def tool_loop_agent(self, **kwargs: object) -> object:
                lookup_calls.append(dict(kwargs))
                return type(
                    "Response",
                    (),
                    {"completion_text": "I found the assets but forgot the terminal."},
                )()

            async def llm_generate(self, **kwargs: object) -> object:
                repair_calls.append(dict(kwargs))
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": (
                            '<pic prompt="kei_\\(blue_archive\\), maid, selfie. '
                            'Kei takes a maid selfie.">'
                        )
                    },
                )()

        instruction, _provider_id = await director.generate_instruction(
            Context(),
            object(),
            "《BlueArchive》Kei，女仆装，自拍",
            tools=object(),
        )

        self.assertEqual(len(lookup_calls), 1)
        self.assertEqual(len(repair_calls), 1)
        self.assertNotIn("tools", repair_calls[0])
        self.assertIn("Return exactly one", str(repair_calls[0]["prompt"]))
        self.assertIn("kei_\\(blue_archive\\)", instruction.prompt)

    async def test_invalid_lookup_terminal_accepts_strict_json_repair(self) -> None:
        director = self._director()

        class Context:
            lookup_calls = 0
            repair_calls = 0

            async def tool_loop_agent(self, **_kwargs: object) -> object:
                self.lookup_calls += 1
                return type(
                    "Response",
                    (),
                    {"completion_text": "Asset lookup complete without a terminal."},
                )()

            async def llm_generate(self, **kwargs: object) -> object:
                self.repair_calls += 1
                self.repair_kwargs = dict(kwargs)
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": json.dumps(
                            {
                                "positive_tags": (
                                    r"viola_\(bang_dream!\), maid, selfie. "
                                    "Viola takes a maid selfie."
                                ),
                                "negative_tags": "bad hands",
                                "pipeline": "base",
                                "characters": ["Viola|BanG Dream!"],
                            }
                        )
                    },
                )()

        context = Context()
        instruction, _provider_id = await director.generate_instruction(
            context,
            object(),
            "《Bang！Dream！》薇欧拉，女仆装，自拍",
            tools=object(),
        )

        self.assertEqual(context.lookup_calls, 1)
        self.assertEqual(context.repair_calls, 1)
        self.assertNotIn("tools", context.repair_kwargs)
        self.assertIn("Do not call any tool again", context.repair_kwargs["prompt"])
        self.assertIn(r"viola_\(bang_dream!\)", instruction.prompt)
        self.assertEqual(instruction.character_queries, ("Viola|BanG Dream!",))

    async def test_invalid_lookup_terminal_accepts_fenced_json_repair(self) -> None:
        director = self._director()

        class Context:
            lookup_calls = 0
            repair_calls = 0

            async def tool_loop_agent(self, **_kwargs: object) -> object:
                self.lookup_calls += 1
                return type("Response", (), {"completion_text": "lookup done"})()

            async def llm_generate(self, **_kwargs: object) -> object:
                self.repair_calls += 1
                payload = json.dumps(
                    {
                        "positive_tags": "1girl, maid, selfie. A maid selfie.",
                        "negative_tags": "bad hands",
                        "pipeline": "base",
                    }
                )
                return type(
                    "Response",
                    (),
                    {"completion_text": f"```json\n{payload}\n```"},
                )()

        context = Context()
        instruction, _provider_id = await director.generate_instruction(
            context,
            object(),
            "女仆自拍",
            tools=object(),
        )

        self.assertEqual(context.lookup_calls, 1)
        self.assertEqual(context.repair_calls, 1)
        self.assertIn("1girl", instruction.prompt)

    async def test_invalid_lookup_terminal_accepts_embedded_json_repair(self) -> None:
        director = self._director()

        class Context:
            async def tool_loop_agent(self, **_kwargs: object) -> object:
                return type("Response", (), {"completion_text": "lookup done"})()

            async def llm_generate(self, **_kwargs: object) -> object:
                payload = json.dumps(
                    {
                        "positive_tags": "1girl, stairs, uniform. A staircase scene.",
                        "negative_tags": "",
                        "pipeline": "base",
                    }
                )
                return type(
                    "Response",
                    (),
                    {"completion_text": f"ok, plan ready\n{payload}\nthank you"},
                )()

        instruction, _provider_id = await director.generate_instruction(
            Context(),
            object(),
            "画一张楼梯间的图",
            tools=object(),
        )

        self.assertIn("stairs", instruction.prompt)
        self.assertEqual(instruction.pipeline, "base")

    async def test_invalid_lookup_terminal_rejects_prose_repair_with_shape_only_detail(
        self,
    ) -> None:
        director = self._director()

        class Context:
            async def tool_loop_agent(self, **_kwargs: object) -> object:
                return type("Response", (), {"completion_text": "lookup done"})()

            async def llm_generate(self, **_kwargs: object) -> object:
                return type(
                    "Response",
                    (),
                    {"completion_text": "private prose must never become a prompt"},
                )()

        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_instruction(
                Context(),
                object(),
                "draw",
                tools=object(),
            )

        self.assertIn("invalid_terminal_repair:", raised.exception.detail)
        self.assertIn("chars=40", raised.exception.detail)
        self.assertNotIn("private prose", raised.exception.detail)

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

        self.assertIn("本地资产查询工具调用失败", raised.exception.user_message)
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

        self.assertIn("不支持本地资产查询工具", raised.exception.user_message)
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
                            "characters": ["Rio|Blue Archive"],
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
        self.assertEqual(instruction.character_queries, ("Rio|Blue Archive",))

    async def test_function_call_request_requires_hybrid_prompt_inside_arguments(
        self,
    ) -> None:
        director = self._director(structured_director_mode="function_call")

        class Context:
            async def llm_generate(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type(
                    "Response",
                    (),
                    {
                        "tools_call_name": ["emit_anima_plan_v1"],
                        "tools_call_args": [
                            {
                                "positive_tags": (
                                    "1girl, squatting, beach, night. "
                                    "She squats in the moonlit shallows."
                                ),
                                "negative_tags": "",
                                "pipeline": "base",
                            }
                        ],
                    },
                )()

        context = Context()
        instruction, _ = await director.generate_instruction(
            context,
            object(),
            "draw a beach scene",
            output_tools=object(),
        )

        request_prompt = str(context.kwargs["prompt"])
        system_prompt = str(context.kwargs["system_prompt"])
        self.assertIn(
            "task=draw; density=Standard; "
            "output=emit_anima_plan_v1 function call",
            request_prompt,
        )
        self.assertIn("draw a beach scene", request_prompt)
        self.assertIn("ordered English Danbooru/Anima hard tags", system_prompt)
        self.assertIn(
            "sentence belongs inside the same positive prompt",
            system_prompt,
        )
        self.assertIn("Density: Standard", system_prompt)
        self.assertIn("18-45", system_prompt)
        self.assertIn(
            "Terminal seal: call emit_anima_plan_v1 exactly once",
            system_prompt,
        )
        self.assertIn("moonlit shallows", instruction.prompt)

    async def test_ultra_mode_is_injected_into_user_and_system_prompts(self) -> None:
        director = self._director(structured_director_mode="function_call")

        class Context:
            async def llm_generate(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": "",
                        "tools_call_name": ["emit_anima_plan_v1"],
                        "tools_call_args": [
                            {
                                "positive_tags": (
                                    "2girls, ornate dresses, palace hall, rim light. "
                                    "They stand beneath a gilded arch while layered "
                                    "fabrics catch the warm backlight."
                                ),
                                "negative_tags": "",
                                "pipeline": "rtx",
                            }
                        ],
                    },
                )()

        context = Context()
        instruction, _ = await director.generate_instruction(
            context,
            object(),
            "draw an ornate fantasy poster",
            output_tools=object(),
            expansion_mode="ultra",
        )

        self.assertIn("density=Ultra", str(context.kwargs["prompt"]))
        self.assertIn("Density: Ultra", str(context.kwargs["system_prompt"]))
        self.assertIn("35-80 word scene sentence", str(context.kwargs["system_prompt"]))
        self.assertIn(
            "Terminal seal: call emit_anima_plan_v1 exactly once",
            str(context.kwargs["system_prompt"]),
        )
        self.assertEqual(instruction.pipeline, "rtx")

    async def test_astrbot_parallel_function_call_lists_continue_generation(self) -> None:
        director = self._director(structured_director_mode="function_call")
        output_tools = object()

        class Context:
            async def llm_generate(self, **kwargs: object) -> object:
                self.tools = kwargs.get("tools")
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": "",
                        "tools_call_name": ["emit_anima_plan_v1"],
                        "tools_call_args": [
                            {
                                "positive_tags": "1girl, red dress, city night",
                                "negative_tags": "lowres, bad anatomy",
                                "pipeline": "rtx",
                            }
                        ],
                    },
                )()

        context = Context()
        instruction, provider_id = await director.generate_instruction(
            context,
            object(),
            "draw a girl in a red dress at night",
            output_tools=output_tools,
        )

        self.assertIs(context.tools, output_tools)
        self.assertEqual(provider_id, "test-provider")
        self.assertEqual(instruction.prompt, "1girl, red dress, city night")
        self.assertEqual(instruction.negative_prompt, "lowres, bad anatomy")
        self.assertEqual(instruction.pipeline, "rtx")

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

    async def test_auto_mode_repair_drops_ignored_output_tool_and_uses_pic(self) -> None:
        director = self._director(structured_director_mode="auto")
        output_tools = object()

        class Context:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            async def llm_generate(self, **kwargs: object) -> object:
                self.calls.append(dict(kwargs))
                if len(self.calls) == 1:
                    return type(
                        "Response",
                        (),
                        {"completion_text": "Here is the optimized drawing prompt."},
                    )()
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": (
                            '<pic prompt="1girl, blue hair, beach, night. '
                            'She watches the waves under moonlight." pipeline="rtx">'
                        )
                    },
                )()

        context = Context()
        instruction, _ = await director.generate_instruction(
            context,
            object(),
            "draw a blue-haired girl at the beach",
            output_tools=output_tools,
        )

        self.assertEqual(len(context.calls), 2)
        self.assertIs(context.calls[0]["tools"], output_tools)
        self.assertNotIn("tools", context.calls[1])
        self.assertNotIn(
            "Runtime structured-output override",
            str(context.calls[1]["system_prompt"]),
        )
        self.assertIn("Return exactly one", str(context.calls[1]["prompt"]))
        self.assertIn("<pic prompt=", str(context.calls[1]["prompt"]))
        self.assertEqual(instruction.pipeline, "rtx")
        self.assertIn("She watches the waves", instruction.prompt)

    async def test_auto_mode_does_not_accept_pic_beside_unexpected_tool_call(
        self,
    ) -> None:
        director = self._director(structured_director_mode="auto")
        output_tools = object()

        class Context:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            async def llm_generate(self, **kwargs: object) -> object:
                self.calls.append(dict(kwargs))
                if len(self.calls) == 1:
                    return type(
                        "Response",
                        (),
                        {
                            "completion_text": '<pic prompt="unsafe first response">',
                            "tools_call_name": ["unexpected_tool"],
                            "tools_call_args": [{"positive_tags": "unsafe"}],
                        },
                    )()
                return type(
                    "Response",
                    (),
                    {"completion_text": '<pic prompt="1girl, safe repaired result">'},
                )()

        context = Context()
        instruction, _ = await director.generate_instruction(
            context,
            object(),
            "draw a portrait",
            output_tools=output_tools,
        )

        self.assertEqual(len(context.calls), 2)
        self.assertIs(context.calls[0]["tools"], output_tools)
        self.assertNotIn("tools", context.calls[1])
        self.assertEqual(instruction.prompt, "1girl, safe repaired result")

    async def test_auto_mode_two_malformed_calls_with_pic_fail_closed(self) -> None:
        director = self._director(structured_director_mode="auto")

        class Context:
            calls = 0

            async def llm_generate(self, **_kwargs: object) -> object:
                self.calls += 1
                return type(
                    "Response",
                    (),
                    {
                        "completion_text": '<pic prompt="must not be accepted">',
                        "tools_call_name": ["emit_anima_plan_v1"],
                        "tools_call_args": ["not-json"],
                    },
                )()

        context = Context()
        with self.assertRaises(PromptDirectorError) as raised:
            await director.generate_instruction(
                context,
                object(),
                "draw a portrait",
                output_tools=object(),
            )

        self.assertEqual(context.calls, 2)
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(raised.exception.detail, "invalid_json")


class PromptDirectorProviderFailureTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _director() -> PromptDirector:
        reference = (
            Path(__file__).resolve().parents[1] / "prompts" / "director_creative_default.txt"
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
