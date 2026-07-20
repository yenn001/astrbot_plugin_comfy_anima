"""使用轻量 AstrBot 桩验证主模块可导入及基础辅助逻辑。"""

import asyncio
import importlib
import json
import sys
import tempfile
import time
import types
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from ..models import GeneratedImagePaths, LoraIdentityExpectation, LoraSelection
from ..services.reverse_prompt import ReversePromptResult


class _DecoratorGroup:
    """模拟 AstrBot 指令组装饰器返回值。"""

    def command(self, *_args, **_kwargs):
        return lambda function: function


class _FilterStub:
    """模拟主模块定义阶段使用的 filter API。"""

    class PermissionType:
        ADMIN = "admin"

    class PlatformAdapterType:
        AIOCQHTTP = "aiocqhttp"

    class EventMessageType:
        ALL = "all"

    @staticmethod
    def command_group(*_args, **_kwargs):
        return lambda _function: _DecoratorGroup()

    @staticmethod
    def _passthrough(*_args, **_kwargs):
        return lambda function: function

    command = _passthrough
    llm_tool = _passthrough
    permission_type = _passthrough
    platform_adapter_type = _passthrough
    event_message_type = _passthrough
    on_llm_request = _passthrough
    on_decorating_result = _passthrough


class _Star:
    def __init__(self, context):
        self.context = context


class _Plain:
    def __init__(self, text):
        self.text = text


class _Image:
    @staticmethod
    def fromFileSystem(path):
        return ("image", str(path))


class _Node:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _install_astrbot_stubs() -> None:
    """安装导入 main.py 所需的最小模块桩。"""
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    components = types.ModuleType("astrbot.api.message_components")

    api.logger = types.SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    event.AstrMessageEvent = object
    event.filter = _FilterStub
    star.Context = object
    star.Star = _Star
    star.register = lambda *_args, **_kwargs: (lambda cls: cls)
    components.Plain = _Plain
    components.Image = _Image
    components.Node = _Node

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.api.message_components": components,
        }
    )


class MainCompatibilityTests(unittest.TestCase):
    """主插件定义及纯辅助方法测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_main_module_imports_with_documented_api_surface(self) -> None:
        self.assertTrue(hasattr(self.main, "ComfyAnimaPlugin"))

    def test_natural_draw_detection_is_conservative(self) -> None:
        detector = self.main.ComfyAnimaPlugin._looks_like_draw_request
        self.assertTrue(detector("帮我画一个雨夜里的猫娘"))
        self.assertTrue(detector("帮我画一个戴帽子的女孩"))
        self.assertTrue(detector("生成一张赛博朋克城市图片"))
        self.assertFalse(detector("帮我写一个 Python 列表"))

    def test_image_operation_intent_routing_understands_colloquial_requests(self) -> None:
        inpaint = self.main.ComfyAnimaPlugin._looks_like_inpaint_request
        semantic = self.main.ComfyAnimaPlugin._looks_like_semantic_redraw_request
        semantic_mode = self.main.ComfyAnimaPlugin._extract_semantic_redraw_mode_request
        mode = self.main.ComfyAnimaPlugin._extract_inpaint_mode_request
        standalone = self.main.ComfyAnimaPlugin._looks_like_standalone_upscale_request

        for message in (
            "把遮罩区域的衣服换成红裙",
            "请局部修复透明区域里的手",
            "这里重画成一束白色百合",
            "把那块区域擦掉",
        ):
            with self.subTest(message=message):
                self.assertTrue(inpaint(message))
        self.assertFalse(inpaint("帮我画她穿一条红裙"))
        for message in (
            "把这张图里的衣服换成红裙",
            "换个背景",
            "参考原图重新画一张",
            "整张图改成雨夜版本",
        ):
            with self.subTest(message=message):
                self.assertTrue(semantic(message))
        self.assertFalse(semantic("把遮罩区域的衣服换成红裙"))
        self.assertEqual(semantic_mode("只换衣服，其他保持不变"), "preserve")
        self.assertEqual(semantic_mode("参考原图重新画一张"), "free")
        self.assertEqual(
            semantic_mode("重新画一张，但保留角色和构图"),
            "balanced",
        )
        self.assertEqual(mode("精细修复图中的手指"), "lanpaint")
        self.assertEqual(mode("快速改一下这块小范围区域"), "quick")

        self.assertTrue(standalone("把这张图放大到2倍"))
        self.assertTrue(standalone("高清化一下", has_image=True))
        self.assertFalse(
            standalone("参考这张图画一张并用 RTX 放大", has_image=True)
        )

    def test_generation_pipeline_intent_handles_colloquial_variants(self) -> None:
        extract = self.main.ComfyAnimaPlugin._extract_pipeline_request

        self.assertEqual(extract("只出 Anima 底图，不要放大"), "base")
        self.assertEqual(extract("用 RTX 画一张高清大图"), "rtx")
        self.assertEqual(extract("使用迭代二次采样放大"), "iterative")
        self.assertEqual(extract("不要 RTX，用迭代放大"), "iterative")
        with self.assertRaisesRegex(ValueError, "多个互斥管线"):
            extract("只出底图，但同时还要 RTX 放大")

    def test_natural_rtx_scale_parser_is_bounded(self) -> None:
        extract = self.main.ComfyAnimaPlugin._extract_rtx_scale_request

        self.assertEqual(extract("把这张图放大到2.5倍"), 2.5)
        self.assertEqual(extract("进行 3x 高清化"), 3.0)
        self.assertEqual(extract("把图片高清化", default=1.75), 1.75)
        with self.assertRaisesRegex(ValueError, "1 到 4"):
            extract("把这张图放大到5倍")

    def test_chinese_command_keeps_multiword_tags(self) -> None:
        extractor = self.main.ComfyAnimaPlugin._extract_command_text
        self.assertEqual(
            extractor("/画图 1girl, white hair, blue eyes", "1girl", "画图"),
            "1girl, white hair, blue eyes",
        )

    def test_runtime_global_lock_allows_only_admin(self) -> None:
        plugin = self.main.ComfyAnimaPlugin(object(), {"global_lock": True})

        class Event:
            @staticmethod
            def get_group_id():
                return "123"

            def __init__(self, admin):
                self._admin = admin

            def is_admin(self):
                return self._admin

        self.assertIsNotNone(plugin._access_error(Event(False), "cat"))
        self.assertIsNone(plugin._access_error(Event(True), "cat"))


class HelpTextTests(unittest.IsolatedAsyncioTestCase):
    """聊天帮助应准确区分生图管线、独立工具与换角降级。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    @staticmethod
    def _event():
        return types.SimpleNamespace(plain_result=lambda text: text)

    async def test_anima_help_documents_v12_pipelines_tools_and_swap_flags(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        results = [item async for item in plugin.cmd_help(self._event())]

        self.assertEqual(len(results), 1)
        help_text = results[0]
        for expected in (
            "3 个可选生图管线",
            "base - Anima 原图",
            "rtx - Anima 原图 + RTX 高清放大",
            "iterative - Anima 原图 + 迭代采样放大",
            "5 个独立图片操作",
            "/放大 [倍率]",
            "/底图控制 <要求> [--m p|d|l|r]",
            "/改图 <要求> --mode preserve|balanced|free",
            "/重绘 <要求> --mode quick",
            "/重绘 <要求> --mode lanpaint",
            "--pipeline base|rtx|iterative",
            "--no-character-lora / --no-lora",
            "目标角色 LoRA 完全未命中时会自动改用纯语义 Tags",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, help_text)

    async def test_comfy_help_separates_generation_and_image_operations(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        results = [item async for item in plugin.cmd_comfy_help(self._event())]

        self.assertEqual(len(results), 1)
        help_text = results[0]
        for expected in (
            "3 个可选生图管线（先由 Anima 生成）",
            "1. base - 只生成 Anima 原图，不放大",
            "2. rtx - Anima 原图生成后执行 RTX 高清放大",
            "3. iterative - Anima 原图生成后执行迭代采样放大",
            "5 个独立图片操作（不属于生图管线切换）",
            "/放大 [倍率]",
            "/底图控制 <要求> [--m p|d|l|r]",
            "--mode preserve|balanced|free",
            "--mode quick",
            "--mode lanpaint",
            "--no-character-lora / --no-lora",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, help_text)


class NaturalLanguageDrawLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """验证自然语言绘图不会在第一条进度消息后提前终止。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_event_stops_only_after_generator_finishes(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(enable_natural_draw=True)
        plugin._access_error = lambda _event, _message: None
        plugin._director = None
        plugin._director_error = "test unavailable"

        class Event:
            message_str = "帮我画一个小猫"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

            @staticmethod
            def plain_result(text):
                return text

        event = Event()
        generator = plugin.natural_language_draw(event)

        first_result = await anext(generator)
        self.assertIn("LLM", first_result)
        self.assertFalse(event.stopped)

        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_success_path_yields_progress_then_image_before_stopping(
        self,
    ) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            enable_natural_draw=True,
            show_llm_prompt=False,
        )
        plugin._access_error = lambda _event, _message: None
        plugin._director = object()

        async def generate_prompt(_event, _message):
            return "1girl, cat ears", "test-provider", "school uniform"

        captured_options = []

        async def run_job(_event, _options):
            captured_options.append(_options)
            return (["test.png"], 123, "", "", "")

        plugin._generate_directed_prompt = generate_prompt
        plugin._run_job = run_job
        plugin._make_image_result = (
            lambda _event, _paths, _seed, forward=False: "IMAGE_RESULT"
        )
        plugin._schedule_cleanup = lambda _paths: None

        class Event:
            message_str = "帮我画一个小猫"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

            @staticmethod
            def plain_result(text):
                return text

        event = Event()
        generator = plugin.natural_language_draw(event)

        progress = await anext(generator)
        self.assertIn("正在分析", progress)
        self.assertFalse(event.stopped)

        image_result = await anext(generator)
        self.assertEqual(image_result, "IMAGE_RESULT")
        self.assertEqual(captured_options[0].negative_prompt, "school uniform")
        self.assertFalse(event.stopped)

        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_natural_character_swap_stops_only_after_all_replies(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)

        class ImageInput:
            @staticmethod
            async def has_any(_event):
                return True

        async def handle(_event, request):
            self.assertEqual(request.source_query, "达妮娅")
            self.assertEqual(request.target_query, "卡莲")
            yield "SWAP_PROGRESS"
            yield "SWAP_IMAGE"

        plugin._image_input = ImageInput()
        plugin._handle_character_swap = handle
        plugin._find_requested_style_preset = lambda _text: ""

        class Event:
            message_str = "把引用图片里的达妮娅换成卡莲，衣服保持不变"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

            @staticmethod
            def plain_result(text):
                return text

        event = Event()
        generator = plugin.natural_language_character_swap(event)
        self.assertEqual(await anext(generator), "SWAP_PROGRESS")
        self.assertFalse(event.stopped)
        self.assertEqual(await anext(generator), "SWAP_IMAGE")
        self.assertFalse(event.stopped)
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_reverse_draw_command_routes_exact_no_lora_swap_phrase(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        captured = []

        async def handle(_event, request):
            captured.append(request)
            yield "SWAP_PROGRESS"
            yield "SWAP_IMAGE"

        plugin._handle_character_swap = handle
        plugin._extract_resolution_request = lambda _text: (None, None)
        plugin._find_requested_style_preset = lambda _text: ""

        class Event:
            message_str = (
                "/反推画图 把角色换成赛马娘的米浴，无需使用角色lora"
            )

            @staticmethod
            def plain_result(text):
                return text

        replies = [item async for item in plugin.cmd_reverse_draw(Event())]

        self.assertEqual(replies, ["SWAP_PROGRESS", "SWAP_IMAGE"])
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].source_query, "")
        self.assertEqual(captured[0].target_query, "赛马娘的米浴")
        self.assertFalse(captured[0].use_target_lora)

    async def test_control_command_infers_pose_depth_without_reference(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        captured = []
        plugin._find_requested_style_preset = (
            lambda text: "风格001-1" if "风格001-1" in text else ""
        )

        async def handle(_event, options):
            captured.append(options)
            yield "CONTROL_PROGRESS"
            yield "CONTROL_IMAGE"

        plugin._handle_control_draw = handle

        class Event:
            message_str = "/底图控制 构图和姿势不变，用风格001-1 画出来。"

            @staticmethod
            def plain_result(text):
                return text

        replies = [item async for item in plugin.cmd_control_draw(Event())]

        self.assertEqual(replies, ["CONTROL_PROGRESS", "CONTROL_IMAGE"])
        self.assertEqual(captured[0].control_modes, ("pose", "depth"))
        self.assertEqual(captured[0].lora_preset, "风格001-1")

    async def test_control_command_explicit_modes_override_natural_text(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        captured = []
        plugin._find_requested_style_preset = lambda _text: "风格001-1"

        async def handle(_event, options):
            captured.append(options)
            yield "CONTROL_IMAGE"

        plugin._handle_control_draw = handle

        class Event:
            message_str = (
                "/底图控制 构图和姿势不变，用风格001-1画出来 --m r"
            )

            @staticmethod
            def plain_result(text):
                return text

        replies = [item async for item in plugin.cmd_control_draw(Event())]

        self.assertEqual(replies, ["CONTROL_IMAGE"])
        self.assertEqual(captured[0].control_modes, ("reference",))

    async def test_reverse_draw_can_reuse_one_image_for_pose_depth_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            Image.new("RGB", (640, 960), "white").save(image_path)
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.settings = types.SimpleNamespace(
                enable_reverse_prompt=True,
                show_llm_prompt=False,
            )
            plugin.context = object()
            plugin._workflow_builder = object()
            plugin._pipeline_builders = {}
            plugin._director = object()
            plugin._control_workflow_builder = object()
            plugin._control_initialization_error = ""
            plugin._initialization_error = ""
            plugin._director_error = ""
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin._record_image_task_phase = lambda *_args, **_kwargs: None
            plugin._access_error = lambda *_args, **_kwargs: None
            plugin._find_requested_style_preset = (
                lambda text: "风格001-1" if "风格001-1" in text else ""
            )
            collect_count = 0

            class ImageInput:
                @staticmethod
                async def collect_one(_event):
                    nonlocal collect_count
                    collect_count += 1
                    return image_path

            class ReversePrompt:
                @staticmethod
                async def reverse(*_args, **_kwargs):
                    return (
                        types.SimpleNamespace(
                            negative_tags="old outfit",
                            drawing_request=lambda requirement: (
                                f"image facts; request={requirement}"
                            ),
                        ),
                        "vision-provider",
                    )

            uploads = []

            class Client:
                @staticmethod
                async def upload_image(path):
                    uploads.append(path)
                    return types.SimpleNamespace(workflow_value="input/control.png")

            plugin._image_input = ImageInput()
            plugin._reverse_prompt = ReversePrompt()
            plugin._client = Client()

            async def directed(_event, request):
                self.assertIn("image facts", request)
                return (
                    types.SimpleNamespace(
                        prompt="1girl, dynamic pose",
                        negative_prompt="bad anatomy",
                        pipeline="base",
                    ),
                    "director-provider",
                )

            plugin._generate_directed_instruction = directed
            executed = []

            async def execute_job(
                _job,
                options,
                _event,
                *,
                control_image_name="",
                img2img_image_name="",
            ):
                self.assertFalse(img2img_image_name)
                executed.append((options, control_image_name))
                paths = GeneratedImagePaths()
                paths.append(Path("output.png"))
                return paths, 42, options.prompt, "", None

            plugin._execute_job = execute_job

            async def run_auxiliary(_event, _label, operation):
                return await operation(
                    self.main.GenerationJob("tester", "reverse draw", 0.0)
                )

            plugin._run_auxiliary_job = run_auxiliary
            plugin._make_image_result = lambda *_args, **_kwargs: "IMAGE_RESULT"
            plugin._schedule_cleanup = lambda _paths: None

            class Event:
                message_str = (
                    "/反推画图 构图和姿势不变，用风格001-1画出来 "
                    "--size 512x512"
                )

                @staticmethod
                def plain_result(text):
                    return text

            replies = [item async for item in plugin.cmd_reverse_draw(Event())]

        self.assertEqual(collect_count, 1)
        self.assertEqual(uploads, [image_path])
        self.assertEqual(len(executed), 1)
        options, control_image_name = executed[0]
        self.assertEqual(options.control_modes, ("pose", "depth"))
        self.assertEqual(options.lora_preset, "风格001-1")
        self.assertEqual((options.width, options.height), (512, 512))
        self.assertEqual(control_image_name, "input/control.png")
        self.assertTrue(any("pose + depth" in item for item in replies))
        self.assertEqual(replies[-1], "IMAGE_RESULT")

    async def test_natural_upscale_routes_existing_image_without_llm(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(rtx_scale=2.0)

        class ImageInput:
            @staticmethod
            async def has_any(_event):
                return True

        async def handle(_event, scale):
            self.assertEqual(scale, 2.5)
            yield "UPSCALE_PROGRESS"
            yield "UPSCALE_IMAGE"

        plugin._image_input = ImageInput()
        plugin._handle_rtx_upscale = handle

        class Event:
            message_str = "把这张图放大到2.5倍"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

            @staticmethod
            def plain_result(text):
                return text

        event = Event()
        generator = plugin.natural_language_rtx_upscale(event)
        self.assertEqual(await anext(generator), "UPSCALE_PROGRESS")
        self.assertFalse(event.stopped)
        self.assertEqual(await anext(generator), "UPSCALE_IMAGE")
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_natural_inpaint_routes_colloquial_region_edit(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(enable_inpaint=True)
        plugin._find_requested_style_preset = lambda _text: "风格001"

        async def handle(_event, options):
            self.assertEqual(options.inpaint_mode, "lanpaint")
            self.assertEqual(options.lora_preset, "风格001")
            yield "INPAINT_PROGRESS"
            yield "INPAINT_IMAGE"

        plugin._handle_inpaint = handle

        class Event:
            message_str = "精细修复遮罩区域里的手指"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

        event = Event()
        generator = plugin.natural_language_inpaint(event)
        self.assertEqual(await anext(generator), "INPAINT_PROGRESS")
        self.assertFalse(event.stopped)
        self.assertEqual(await anext(generator), "INPAINT_IMAGE")
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_natural_semantic_redraw_routes_one_image_without_mask(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)

        class ImageInput:
            @staticmethod
            async def has_any(_event):
                return True

        plugin._image_input = ImageInput()
        plugin._prepare_semantic_redraw_options = lambda _text: self.main.GenerationOptions(
            prompt="把衣服换成红裙",
            semantic_redraw_mode="preserve",
        )

        async def handle(_event, options):
            self.assertEqual(options.semantic_redraw_mode, "preserve")
            yield "REDRAW_PROGRESS"
            yield "REDRAW_IMAGE"

        plugin._handle_semantic_redraw = handle

        class Event:
            message_str = "把这张图里的衣服换成红裙，其他保持不变"

            def __init__(self):
                self.stopped = False

            def stop_event(self):
                self.stopped = True

        event = Event()
        generator = plugin.natural_language_semantic_redraw(event)
        self.assertEqual(await anext(generator), "REDRAW_PROGRESS")
        self.assertFalse(event.stopped)
        self.assertEqual(await anext(generator), "REDRAW_IMAGE")
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertTrue(event.stopped)

    async def test_redraw_command_without_mask_language_routes_semantic_redraw(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._looks_like_inpaint_request = lambda _text: False
        plugin._prepare_semantic_redraw_options = lambda text: self.main.GenerationOptions(
            prompt=text,
            semantic_redraw_mode="preserve",
        )
        plugin._extract_command_text = lambda *_args, **_kwargs: (
            "把角色泳装换成三点式，加一条白丝大腿袜，构图不变"
        )

        async def semantic(_event, options):
            self.assertIn("泳装", options.prompt)
            yield "SEMANTIC_REDRAW"

        async def swap(_event, _request):
            yield "WRONG_SWAP"

        plugin._handle_semantic_redraw = semantic
        plugin._handle_character_swap = swap

        class Event:
            message_str = "/重绘 把角色泳装换成三点式，加一条白丝大腿袜，构图不变"

            @staticmethod
            def plain_result(text):
                return text

        replies = [item async for item in plugin.cmd_inpaint(Event())]
        self.assertEqual(replies, ["SEMANTIC_REDRAW"])

    async def test_redraw_command_combines_character_and_outfit_change(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._looks_like_inpaint_request = lambda _text: False
        plugin._extract_command_text = lambda *_args, **_kwargs: (
            "把达妮娅换成米浴并穿红色礼服，构图不变"
        )
        plugin._extract_resolution_request = lambda _text: (None, None)
        plugin._find_requested_style_preset = lambda _text: ""

        async def swap(_event, request):
            self.assertEqual(request.target_query, "米浴")
            self.assertIn("红色礼服", request.edit_requirement)
            yield "COMBINED_SWAP"

        plugin._handle_character_swap = swap

        class Event:
            message_str = "/重绘 把达妮娅换成米浴并穿红色礼服，构图不变"

            @staticmethod
            def plain_result(text):
                return text

        replies = [item async for item in plugin.cmd_inpaint(Event())]
        self.assertEqual(replies, ["COMBINED_SWAP"])

    async def test_reverse_draw_without_control_uses_true_img2img(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            Image.new("RGB", (640, 960), "white").save(image_path)
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.settings = types.SimpleNamespace(
                enable_reverse_prompt=True,
                show_llm_prompt=False,
            )
            plugin.context = object()
            plugin._workflow_builder = object()
            plugin._pipeline_builders = {}
            plugin._img2img_workflow_builder = object()
            plugin._director = object()
            plugin._initialization_error = ""
            plugin._director_error = ""
            plugin._img2img_initialization_error = ""
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin._record_image_task_phase = lambda *_args, **_kwargs: None
            plugin._access_error = lambda *_args, **_kwargs: None
            plugin._find_requested_style_preset = lambda _text: ""

            class ImageInput:
                @staticmethod
                async def collect_one(_event):
                    return image_path

            class ReversePrompt:
                @staticmethod
                async def reverse(*_args, **_kwargs):
                    return (
                        types.SimpleNamespace(
                            negative_tags="old outfit",
                            drawing_request=lambda requirement: (
                                f"source facts; request={requirement}"
                            ),
                        ),
                        "vision-provider",
                    )

            class Client:
                @staticmethod
                async def upload_image(_path):
                    return types.SimpleNamespace(workflow_value="input/img2img.png")

            plugin._image_input = ImageInput()
            plugin._reverse_prompt = ReversePrompt()
            plugin._client = Client()

            async def directed(_event, _request):
                return (
                    self.main.PictureInstruction(
                        "1girl, red evening dress",
                        "old outfit",
                        "base",
                    ),
                    "director-provider",
                )

            plugin._generate_directed_instruction = directed
            captured = {}

            async def execute_job(
                _job,
                options,
                _event,
                *,
                img2img_image_name="",
            ):
                captured["options"] = options
                captured["img2img_image_name"] = img2img_image_name
                paths = GeneratedImagePaths()
                paths.append(Path("output.png"))
                return paths, 42, options.prompt, "", None

            plugin._execute_job = execute_job

            async def run_auxiliary(_event, _label, operation):
                return await operation(
                    self.main.GenerationJob("tester", "reverse draw", 0.0)
                )

            plugin._run_auxiliary_job = run_auxiliary
            plugin._make_image_result = lambda *_args, **_kwargs: "IMAGE_RESULT"
            plugin._schedule_cleanup = lambda _paths: None

            class Event:
                message_str = "/反推画图 换成红色晚礼服"

                @staticmethod
                def plain_result(text):
                    return text

            replies = [item async for item in plugin.cmd_reverse_draw(Event())]

        self.assertEqual(captured["img2img_image_name"], "input/img2img.png")
        self.assertEqual(captured["options"].denoise, 0.55)
        self.assertTrue(captured["options"].suppress_default_style)
        self.assertIn("IMAGE_RESULT", replies)

    async def test_control_job_builds_source_aware_director_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (640, 960), "white").save(source)
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.settings = types.SimpleNamespace(
                enable_prompt_llm=True,
                enable_reverse_prompt=True,
            )
            plugin.context = object()
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin._record_image_task_phase = lambda *_args, **_kwargs: None

            class ImageInput:
                @staticmethod
                async def collect_one(_event):
                    return source

            class ReversePrompt:
                @staticmethod
                async def reverse(*_args, **_kwargs):
                    return (
                        ReversePromptResult(
                            positive_tags="1girl, black coat, standing, rainy street",
                            composition="full body, centered",
                            scene_description_zh="雨夜街道",
                        ),
                        "vision-provider",
                    )

            class Client:
                @staticmethod
                async def upload_image(_path):
                    return types.SimpleNamespace(workflow_value="input/control.png")

            plugin._image_input = ImageInput()
            plugin._reverse_prompt = ReversePrompt()
            plugin._client = Client()
            captured = {}

            async def execute(
                _job,
                options,
                _event,
                *,
                control_image_name="",
            ):
                captured["options"] = options
                captured["control_image_name"] = control_image_name
                return GeneratedImagePaths(), 1, options.prompt, "", None

            plugin._execute_job = execute
            await plugin._execute_control_job(
                self.main.GenerationJob("tester", "control", time.monotonic()),
                object(),
                self.main.GenerationOptions(
                    prompt="换成红色晚礼服，构图不变",
                    control_modes=("pose", "depth"),
                ),
            )

        effective = captured["options"]
        self.assertIn("1girl, black coat", effective.prompt)
        self.assertIn("换成红色晚礼服", effective.prompt)
        self.assertTrue(effective.suppress_default_style)
        self.assertEqual(captured["control_image_name"], "input/control.png")

    async def test_semantic_redraw_preserves_source_ratio_and_applies_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            output = Path(directory) / "output.png"
            Image.new("RGB", (1200, 600), "white").save(source)
            Image.new("RGB", (512, 512), "white").save(output)
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.settings = types.SimpleNamespace(
                enable_reverse_prompt=True,
                max_prompt_length=2000,
                show_llm_prompt=False,
            )
            plugin.context = object()
            class Client:
                @staticmethod
                async def upload_image(_path):
                    return types.SimpleNamespace(workflow_value="input/source.png")

            plugin._client = Client()
            plugin._workflow_builder = object()
            plugin._pipeline_builders = {}
            plugin._img2img_workflow_builder = object()
            plugin._director = object()
            plugin._initialization_error = None
            plugin._director_error = None
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin._access_error = lambda *_args, **_kwargs: None
            phases = []
            plugin._record_image_task_phase = (
                lambda _job, _phase, _message, code, **_kwargs: phases.append(code)
            )
            captured = {}

            class ImageInput:
                @staticmethod
                async def collect_one(_event):
                    return source

            class ReversePrompt:
                @staticmethod
                async def reverse(*args, **_kwargs):
                    captured["reverse_focus"] = args[3]
                    return (
                        ReversePromptResult(
                            positive_tags=(
                                "1girl, school uniform, standing, classroom"
                            ),
                            negative_tags="text, watermark",
                        ),
                        "vision-provider",
                    )

            plugin._image_input = ImageInput()
            plugin._reverse_prompt = ReversePrompt()

            async def direct(_event, request):
                captured["director_request"] = request
                return (
                    self.main.PictureInstruction(
                        "1girl, red evening dress, standing, classroom",
                        "school uniform",
                        "base",
                    ),
                    "director-provider",
                )

            plugin._generate_directed_instruction = direct

            async def execute(
                _job,
                options,
                _event,
                *,
                img2img_image_name="",
            ):
                captured["options"] = options
                captured["img2img_image_name"] = img2img_image_name
                paths = GeneratedImagePaths()
                paths.append(output)
                paths.elapsed_seconds = 1.25
                paths.gpu_name = "Test GPU"
                return paths, 42, options.prompt, "", None

            plugin._execute_job = execute

            async def run_auxiliary(_event, label, operation):
                self.assertEqual(label, "semantic redraw")
                return await operation(
                    self.main.GenerationJob("tester", label, time.monotonic())
                )

            plugin._run_auxiliary_job = run_auxiliary
            plugin._schedule_cleanup = lambda _paths: None

            class Event:
                @staticmethod
                def plain_result(text):
                    return text

                @staticmethod
                def chain_result(components):
                    return components

            replies = [
                item
                async for item in plugin._handle_semantic_redraw(
                    Event(),
                    self.main.GenerationOptions(
                        prompt="只把衣服换成红色晚礼服，其他保持不变",
                        semantic_redraw_mode="preserve",
                        use_prompt_llm=False,
                    ),
                )
            ]

        effective = captured["options"]
        self.assertEqual(captured["img2img_image_name"], "input/source.png")
        self.assertEqual(effective.denoise, 0.64)
        self.assertEqual(effective.steps, 16)
        self.assertEqual(effective.width % 64, 0)
        self.assertEqual(effective.height % 64, 0)
        self.assertAlmostEqual(effective.width / effective.height, 2.0, delta=0.15)
        self.assertEqual(effective.pipeline, "base")
        self.assertTrue(effective.suppress_default_style)
        self.assertIn("text, watermark", effective.negative_prompt)
        self.assertIn("school uniform", effective.negative_prompt)
        self.assertIn("source image exactly as shown", captured["reverse_focus"])
        self.assertNotIn("红色晚礼服", captured["reverse_focus"])
        self.assertIn("无蒙版整图语义重绘", captured["director_request"])
        self.assertIn("明确替换的旧内容必须从正面提示词删除", captured["director_request"])
        self.assertIn("不得自动套用默认风格001", captured["director_request"])
        self.assertIn("semantic_redraw_output_ready", phases)
        self.assertEqual(len(replies), 2)


class AuxiliaryImageTaskFailureTests(unittest.IsolatedAsyncioTestCase):
    """验证反推失败阶段和安全错误码进入持久任务记录。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_reverse_failure_keeps_stage_and_omits_private_detail(self) -> None:
        task_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.task_store"
        )

        class Event:
            @staticmethod
            def get_sender_id():
                return "tester"

            @staticmethod
            def is_admin():
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = task_module.TaskStore(Path(directory) / "tasks.sqlite3")
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin._jobs_lock = asyncio.Lock()
            plugin._active_jobs = {}
            plugin._last_request_at = {}
            plugin._task_store = store
            plugin._client = None
            plugin.settings = types.SimpleNamespace(
                admin_ignore_cooldown=False,
                user_cooldown=0,
            )

            async def operation(job):
                job.state = "reverse_prompting"
                raise self.main.ReversePromptError(
                    "结构化反推失败",
                    "PRIVATE_PROVIDER_BODY",
                    code="repair_exhausted",
                )

            with self.assertRaises(self.main.ReversePromptError):
                await plugin._run_auxiliary_job(
                    Event(),
                    "reverse draw",
                    operation,
                )

            task = store.recent_tasks(limit=1)[0]
            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["error_code"], "repair_exhausted")
            self.assertEqual(task["error_summary"], "结构化反推失败")
            events = store.read_events(run_id=task["run_id"], limit=50)["entries"]
            failed = [
                item
                for item in events
                if item["event_code"] == "image_task_failed"
            ]
            self.assertEqual(
                failed[0]["details"]["failed_stage"],
                "reverse_prompting",
            )
            persisted = str(events) + str(store.recent_runtime_logs(limit=50))
            self.assertNotIn("PRIVATE_PROVIDER_BODY", persisted)
            store.close()

    async def test_nested_generation_failure_keeps_the_real_stage(self) -> None:
        task_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.task_store"
        )

        class Event:
            @staticmethod
            def get_sender_id():
                return "tester"

            @staticmethod
            def is_admin():
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = task_module.TaskStore(Path(directory) / "tasks.sqlite3")
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin._jobs_lock = asyncio.Lock()
            plugin._active_jobs = {}
            plugin._last_request_at = {}
            plugin._task_store = store
            plugin._client = object()
            plugin._workflow_builder = object()
            plugin._pipeline_builders = {}
            plugin._control_workflow_builder = None
            plugin._img2img_workflow_builder = object()
            plugin._director = object()
            plugin._initialization_error = ""
            plugin._director_error = ""
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin.settings = self.main.PluginSettings.from_mapping(
                {
                    "admin_ignore_cooldown": False,
                    "user_cooldown": 0,
                    "enable_prompt_llm": True,
                    "prompt_llm_fallback": False,
                }
            )

            async def fail_director(_event, _prompt):
                raise self.main.PromptDirectorError(
                    "director failed",
                    fatal=True,
                )

            plugin._generate_directed_prompt = fail_director

            async def operation(job):
                return await plugin._execute_job(
                    job,
                    self.main.GenerationOptions(prompt="safe prompt"),
                    Event(),
                )

            with self.assertRaises(self.main.PromptDirectorError):
                await plugin._run_auxiliary_job(
                    Event(),
                    "reverse draw",
                    operation,
                )

            task = store.recent_tasks(limit=1)[0]
            events = store.read_events(run_id=task["run_id"], limit=50)["entries"]
            failed = [
                item
                for item in events
                if item["event_code"] == "image_task_failed"
            ]
            self.assertEqual(failed[0]["details"]["failed_stage"], "directing")
            self.assertEqual(failed[0]["details"]["final_state"], "failed")
            store.close()


class ReverseDrawAccessTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_sensitive_director_prompt_is_blocked_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "input.png"
            image_path.write_bytes(b"image")
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.settings = types.SimpleNamespace(
                enable_reverse_prompt=True,
                show_llm_prompt=False,
            )
            plugin.context = object()
            plugin._client = object()
            plugin._workflow_builder = object()
            plugin._director = object()
            plugin._generation_slots = asyncio.Semaphore(1)
            plugin._pipeline_builders = {}
            plugin._control_workflow_builder = None
            plugin._img2img_workflow_builder = object()
            plugin._initialization_error = ""
            plugin._director_error = ""
            plugin._extract_command_text = lambda *_args, **_kwargs: "safe request"
            plugin._extract_resolution_request = lambda _text: (512, 512)
            plugin._find_requested_style_preset = lambda _text: ""
            plugin._record_image_task_phase = lambda *_args, **_kwargs: None

            class ImageInput:
                @staticmethod
                async def collect_one(_event):
                    return image_path

            class ReversePrompt:
                @staticmethod
                async def reverse(*_args, **_kwargs):
                    return (
                        types.SimpleNamespace(
                            negative_tags="",
                            drawing_request=lambda _supplement: "image facts",
                        ),
                        "vision-provider",
                    )

            plugin._image_input = ImageInput()
            plugin._reverse_prompt = ReversePrompt()

            async def directed_prompt(_event, _request):
                return "blocked final prompt", "director-provider", ""

            plugin._generate_directed_prompt = directed_prompt
            access_checks = []

            def access_error(_event, text, check_sensitive=True):
                access_checks.append((text, check_sensitive))
                if text == "blocked final prompt":
                    return "final prompt blocked by policy"
                return None

            plugin._access_error = access_error
            executed = False

            async def execute_job(*_args, **_kwargs):
                nonlocal executed
                executed = True
                raise AssertionError("generation must not run")

            plugin._execute_job = execute_job

            async def run_auxiliary(_event, _label, operation):
                return await operation(
                    self.main.GenerationJob("tester", "reverse draw", 0.0)
                )

            plugin._run_auxiliary_job = run_auxiliary

            class Event:
                message_str = "/reverse draw safe request"

                @staticmethod
                def plain_result(text):
                    return text

            replies = [item async for item in plugin.cmd_reverse_draw(Event())]

        self.assertFalse(executed)
        self.assertIn(("blocked final prompt", True), access_checks)
        self.assertTrue(any("final prompt blocked by policy" in item for item in replies))


class GenerationReplyMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def test_generation_summary_includes_elapsed_time_and_gpu(self) -> None:
        paths = GeneratedImagePaths()
        paths.extend([Path("one.png"), Path("two.png")])
        paths.elapsed_seconds = 12.345
        paths.gpu_name = "NVIDIA GeForce RTX 5060 Ti"
        summary = self.main.ComfyAnimaPlugin._generation_summary(paths, 42)
        self.assertIn("Seed: 42", summary)
        self.assertIn("12.35 秒", summary)
        self.assertIn("NVIDIA GeForce RTX 5060 Ti", summary)
        self.assertIn("2 张", summary)

    def test_explicit_lora_cleanup_updates_all_referencing_presets(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.PluginSettings.from_mapping(
            {"default_style_preset": "风格1"}
        )
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=4)
        plugin._lora_presets.save(
            name="风格1",
            category="style",
            selections=(
                LoraSelection("styles/base", 0.5),
                LoraSelection("shared/remove-me", 0.4),
            ),
        )
        plugin._lora_presets.save(
            name="角色1",
            category="character",
            selections=(LoraSelection("shared/remove-me", 0.8),),
        )
        persisted = []
        plugin._persist_config_updates = lambda updates: persisted.append(updates) or True

        self.assertEqual(
            plugin._lora_preset_references("shared/remove-me.safetensors"),
            ("风格1", "角色1"),
        )
        changed = plugin._remove_lora_from_presets("shared/remove-me.safetensors")
        self.assertEqual(changed, 2)
        self.assertEqual(plugin._lora_preset_references("shared/remove-me"), ())
        self.assertEqual(len(plugin._lora_presets.presets), 1)
        self.assertEqual(plugin._lora_presets.presets[0].name, "风格1")
        self.assertEqual(persisted[0]["lora_presets"][0]["loras"], ["styles/base=0.5"])


class LoraDeleteTransactionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin_with_referenced_preset(self):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.PluginSettings.from_mapping(
            {"default_style_preset": "风格1"}
        )

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = Path(directory.name) / "plugin.json"

        class Config(dict):
            def __init__(self, path: Path, **values):
                super().__init__(**values)
                self.config_path = str(path)

            def save_config(self):
                Path(self.config_path).write_text(
                    json.dumps(self, ensure_ascii=False),
                    encoding="utf-8-sig",
                )

        plugin.config = Config(config_path, default_style_preset="风格1")
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=4)
        plugin._lora_presets.save(
            name="风格1",
            category="style",
            selections=(LoraSelection("shared/remove-me", 0.5),),
        )
        plugin.config["lora_presets"] = plugin._lora_presets.to_config()
        plugin.config.save_config()
        plugin._task_store = None
        plugin._model_manager_error = ""
        return plugin

    async def test_unconfirmed_remote_delete_restores_preset_state(self) -> None:
        plugin = self._plugin_with_referenced_preset()

        class FailingManager:
            async def delete_lora(_self, *_args, **_kwargs):
                plugin._remove_lora_from_presets("shared/remove-me")
                raise self.main.ModelManagerError("Manager 未确认删除成功")

        plugin._model_manager = FailingManager()
        with self.assertRaisesRegex(
            self.main.WebUiActionError, "组合配置已恢复"
        ):
            await plugin._web_ui_delete_asset(
                "lora",
                {
                    "exact_name": "shared/remove-me",
                    "confirm_name": "shared/remove-me",
                    "remove_from_presets": True,
                },
            )

        self.assertEqual(
            plugin._lora_preset_references("shared/remove-me"), ("风格1",)
        )
        self.assertEqual(plugin.config["default_style_preset"], "风格1")
        self.assertEqual(len(plugin.config["lora_presets"]), 1)

    async def test_post_delete_refresh_failure_keeps_cleanup(self) -> None:
        plugin = self._plugin_with_referenced_preset()

        class Result:
            removed_from_presets = True
            preset_cleanup_count = 1

            def as_dict(self):
                return {"deleted": True}

        class SuccessfulManager:
            async def delete_lora(_self, *_args, **_kwargs):
                plugin._remove_lora_from_presets("shared/remove-me")
                return Result()

        class FailingCatalog:
            async def refresh_for_operation(_self):
                raise self.main.LoraCatalogError("删除后刷新失败")

        plugin._model_manager = SuccessfulManager()
        plugin._lora_catalog = FailingCatalog()
        with self.assertRaisesRegex(
            self.main.WebUiActionError, "远端 LoRA 已删除.*已保留组合清理结果"
        ):
            await plugin._web_ui_delete_asset(
                "lora",
                {
                    "exact_name": "shared/remove-me",
                    "confirm_name": "shared/remove-me",
                    "remove_from_presets": True,
                },
            )

        self.assertEqual(plugin._lora_preset_references("shared/remove-me"), ())
        self.assertEqual(plugin.config["default_style_preset"], "")
        self.assertEqual(plugin.config["lora_presets"], [])


class StyleSaveReloadTests(unittest.IsolatedAsyncioTestCase):
    """验证风格保存提示及延迟单插件重载机制。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_scheduler_reloads_only_current_plugin(self) -> None:
        calls = []

        class StarManager:
            async def reload(self, plugin_name):
                calls.append(plugin_name)
                return True, None

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = types.SimpleNamespace(_star_manager=StarManager())
        plugin._self_reload_tasks = set()

        task = plugin._schedule_self_reload(delay=0)
        self.assertIsNotNone(task)
        await task
        self.assertEqual(calls, [self.main.PLUGIN_NAME])

    async def test_scheduler_debounces_multiple_pending_reloads(self) -> None:
        calls = []

        class StarManager:
            async def reload(self, plugin_name):
                calls.append(plugin_name)
                return True, None

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = types.SimpleNamespace(_star_manager=StarManager())
        plugin._self_reload_tasks = set()

        first = plugin._schedule_self_reload(delay=0.05, reason="first")
        second = plugin._schedule_self_reload(delay=0, reason="second")
        await asyncio.gather(first, second, return_exceptions=True)

        self.assertEqual(calls, [self.main.PLUGIN_NAME])

    async def test_started_reload_is_not_cancelled_and_old_instance_rejects_save(
        self,
    ) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        class StarManager:
            async def reload(self, plugin_name):
                calls.append(plugin_name)
                entered.set()
                await release.wait()
                return True, None

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = types.SimpleNamespace(_star_manager=StarManager())
        plugin._self_reload_tasks = set()
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
        plugin.settings = types.SimpleNamespace(
            max_preset_loras=12,
            max_total_dynamic_loras=12,
            strict_lora_validation=False,
        )
        plugin._lora_catalog = None
        plugin._refresh_lora_manager_before = lambda _action: asyncio.sleep(0)
        plugin._persist_config = lambda *_args: True

        first = plugin._schedule_self_reload(delay=0, reason="first")
        await entered.wait()
        second = plugin._schedule_self_reload(delay=0, reason="second")
        self.assertIs(first, second)
        save_task = asyncio.create_task(
            plugin._save_lora_preset_persisted(
                category_text="style",
                name="should-not-commit",
                entries="<lora:styles/blocked.safetensors:0.5>",
            )
        )
        release.set()
        await first

        with self.assertRaisesRegex(self.main.LoraPresetError, "正在重载"):
            await save_task
        self.assertEqual(calls, [self.main.PLUGIN_NAME])
        self.assertEqual(plugin._lora_presets.presets, ())

    async def test_concurrent_style_saves_are_serialized_and_failure_cannot_erase_success(
        self,
    ) -> None:
        self_main = self.main
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            max_preset_loras=12,
            max_total_dynamic_loras=12,
            strict_lora_validation=True,
        )
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
        active_refreshes = 0
        max_active_refreshes = 0

        async def refresh(_action):
            nonlocal active_refreshes, max_active_refreshes
            active_refreshes += 1
            max_active_refreshes = max(max_active_refreshes, active_refreshes)
            await asyncio.sleep(0.01)
            active_refreshes -= 1

        class Catalog:
            async def resolve_selections(self, selections, *, strict):
                return selections

            async def classify_selections(self, selections):
                return {
                    selection.name: self_main.PRESET_CATEGORY_ARTIST_STYLE
                    for selection in selections
                }

        plugin._refresh_lora_manager_before = refresh
        plugin._lora_catalog = Catalog()

        def persist(_key, value):
            return not any(item.get("name") == "失败风格" for item in value)

        plugin._persist_config = persist
        failed, succeeded = await asyncio.gather(
            plugin._save_lora_preset_persisted(
                category_text="style",
                name="失败风格",
                entries="<lora:styles/fail.safetensors:0.5>",
            ),
            plugin._save_lora_preset_persisted(
                category_text="style",
                name="成功风格",
                entries="<lora:styles/success.safetensors:0.5>",
            ),
            return_exceptions=True,
        )

        self.assertIsInstance(failed, self.main.LoraPresetError)
        self.assertEqual(succeeded.name, "成功风格")
        self.assertEqual(max_active_refreshes, 1)
        self.assertEqual(
            plugin._lora_presets.resolve("成功风格").name,
            "成功风格",
        )

    async def test_style_save_schedules_reload_after_persistence(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(
            max_preset_loras=12,
            max_total_dynamic_loras=12,
            strict_lora_validation=False,
            auto_reload_after_style_save=True,
        )
        plugin._lora_catalog = None

        async def refresh_lora_manager(_action):
            return 1

        plugin._refresh_lora_manager_before = refresh_lora_manager
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
        persisted = []
        scheduled = []
        plugin._persist_config = (
            lambda key, value: persisted.append((key, value)) or True
        )
        plugin._schedule_self_reload = (
            lambda **_kwargs: scheduled.append(True) or object()
        )

        class Event:
            message_str = "/lora组合保存 风格 002 <lora:test-style:0.6>"

            @staticmethod
            def plain_result(text):
                return text

        results = [result async for result in plugin.cmd_lora_preset_save(Event())]
        self.assertEqual(len(results), 1)
        self.assertIn("风格002", results[0])
        self.assertIn("自动重载", results[0])
        self.assertEqual(scheduled, [True])
        self.assertEqual(persisted[0][0], "lora_presets")

    async def test_conversation_tool_persists_and_survives_fresh_registry(self) -> None:
        self_main = self.main

        class Config(dict):
            def __init__(self, path: Path):
                super().__init__(lora_presets=[])
                self.config_path = str(path)
                self.save_config()

            def save_config(self):
                Path(self.config_path).write_text(
                    json.dumps(self, ensure_ascii=False),
                    encoding="utf-8-sig",
                )

        class Catalog:
            async def resolve_selections(self, selections, *, strict):
                return selections

            async def classify_selections(self, selections):
                return {
                    selection.name: self_main.PRESET_CATEGORY_ARTIST_STYLE
                    for selection in selections
                }

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "plugin.json"
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin.config = Config(config_path)
            plugin.settings = types.SimpleNamespace(
                max_preset_loras=12,
                max_total_dynamic_loras=12,
                strict_lora_validation=True,
                auto_reload_after_style_save=True,
            )
            plugin._lora_catalog = Catalog()
            plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
            plugin._refresh_lora_manager_before = lambda _action: asyncio.sleep(
                0, result=()
            )
            scheduled = []
            plugin._schedule_self_reload = (
                lambda **kwargs: scheduled.append(kwargs) or object()
            )

            class Event:
                @staticmethod
                def is_admin():
                    return True

            result = await plugin.save_anima_lora_style(
                Event(),
                "006",
                "<lora:styles/ink.safetensors:0.7> "
                "<lora:styles/light.safetensors:0.4>",
                "ink, warm light",
                "聊天保存测试",
            )
            persisted = json.loads(config_path.read_text(encoding="utf-8-sig"))
            fresh_registry = self.main.LoraPresetRegistry(
                persisted["lora_presets"],
                max_loras=12,
            )

        self.assertIn("STYLE_SAVE_COMMITTED", result)
        self.assertEqual(fresh_registry.resolve("风格006").description, "聊天保存测试")
        self.assertEqual(len(fresh_registry.resolve("风格006").selections), 2)
        self.assertEqual(scheduled[0]["delay"], 10.0)

    async def test_conversation_tool_rejects_non_admin_without_mutation(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_presets = self.main.LoraPresetRegistry([])

        class Event:
            @staticmethod
            def is_admin():
                return False

        result = await plugin.save_anima_lora_style(
            Event(),
            "006",
            "<lora:styles/ink.safetensors:0.7>",
        )

        self.assertIn("STYLE_SAVE_DENIED", result)
        self.assertEqual(plugin._lora_presets.presets, ())

    async def test_admin_conversation_requires_committed_style_tool_result(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = types.SimpleNamespace(enable_llm_pic_trigger=True)
        plugin._internal_llm_events = set()
        plugin._auto_draw_system_prompt = ""
        plugin._access_error = lambda *_args, **_kwargs: None

        class Event:
            @staticmethod
            def is_admin():
                return True

        request = types.SimpleNamespace(system_prompt="base")
        await plugin.inject_auto_draw_prompt(Event(), request)

        self.assertIn("save_anima_lora_style", request.system_prompt)
        self.assertIn("STYLE_SAVE_COMMITTED", request.system_prompt)
        self.assertIn("不得用 shell", request.system_prompt)


class UnetModelSwitchTests(unittest.IsolatedAsyncioTestCase):
    """验证切换前刷新清单、持久化并更新 UNET 工作流设置。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_switch_refreshes_latest_catalog_before_persisting(self) -> None:
        events = []
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = Path(directory.name) / "plugin.json"
        entries = (
            types.SimpleNamespace(index=1, name="anima-a.safetensors"),
            types.SimpleNamespace(index=2, name="anima-b.safetensors"),
        )

        class Config(dict):
            def __init__(self, path: Path, **values):
                super().__init__(**values)
                self.config_path = str(path)
                self.save_config()

            def save_config(self):
                Path(self.config_path).write_text(
                    json.dumps(self, ensure_ascii=False),
                    encoding="utf-8-sig",
                )

        class Catalog:
            async def list_models(self):
                events.append("list")
                return entries

            @staticmethod
            def resolve(identifier, refreshed_entries):
                events.append("resolve")
                self.assertEqual(refreshed_entries, entries)
                self.assertEqual(identifier, "2")
                return refreshed_entries[1]

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        plugin.config = Config(
            config_path,
            workflow_file="workflow/anima_api.json",
        )
        plugin.settings = self.main.PluginSettings.from_mapping(plugin.config)
        plugin._unet_catalog = Catalog()
        plugin._unet_catalog_error = ""
        plugin._schedule_self_reload = (
            lambda **kwargs: events.append(f"reload:{kwargs['reason']}") or object()
        )

        class Event:
            message_str = "/模型切换 2"

            @staticmethod
            def plain_result(text):
                return text

        results = [result async for result in plugin.cmd_unet_model_switch(Event())]
        self.assertEqual(events[:2], ["list", "resolve"])
        self.assertEqual(plugin.config["unet_model_name"], "anima-b.safetensors")
        self.assertEqual(plugin.settings.unet_model_name, "anima-b.safetensors")
        self.assertEqual(events[-1], "reload:切换 UNET 模型")
        self.assertIn("全部 2 个模型", results[-1])
        workflow, _, _ = plugin._workflow_builder.build(
            self.main.GenerationOptions(prompt="1girl", seed=1)
        )
        self.assertEqual(
            workflow["429"]["inputs"]["unet_name"],
            "anima-b.safetensors",
        )

    async def test_switch_uses_anima_v2_profile_unet_binding(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = Path(directory.name) / "plugin.json"
        entries = (
            types.SimpleNamespace(index=1, name="anima-v2-a.safetensors"),
            types.SimpleNamespace(index=2, name="anima-v2-b.safetensors"),
        )

        class Config(dict):
            def __init__(self, path: Path, **values):
                super().__init__(**values)
                self.config_path = str(path)
                self.save_config()

            def save_config(self):
                Path(self.config_path).write_text(
                    json.dumps(self, ensure_ascii=False),
                    encoding="utf-8-sig",
                )

        class Catalog:
            async def list_models(self):
                return entries

            @staticmethod
            def resolve(identifier, refreshed_entries):
                self.assertEqual(identifier, "2")
                self.assertEqual(refreshed_entries, entries)
                return refreshed_entries[1]

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        plugin.config = Config(
            config_path,
            workflow_file="workflow/anima_v2_api.json",
        )
        plugin.settings = self.main.PluginSettings.from_mapping(plugin.config)
        plugin._unet_catalog = Catalog()
        plugin._unet_catalog_error = ""
        plugin._schedule_self_reload = lambda **_kwargs: object()

        class Event:
            message_str = "/模型切换 2"

            @staticmethod
            def plain_result(text):
                return text

        results = [result async for result in plugin.cmd_unet_model_switch(Event())]

        self.assertNotIn("缺少 UNET 节点 429", "\n".join(results))
        workflow, _, _ = plugin._workflow_builder.build(
            self.main.GenerationOptions(prompt="1girl", seed=1)
        )
        self.assertEqual(
            workflow["44"]["inputs"]["unet_name"],
            "anima-v2-b.safetensors",
        )


class MandatoryLoraRefreshTests(unittest.IsolatedAsyncioTestCase):
    """每次 LLM LoRA 工具调用都必须重新扫描 Manager。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_repeated_tool_calls_refresh_every_time(self) -> None:
        class Catalog:
            def __init__(self):
                self.refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (types.SimpleNamespace(name="denia"),)

            async def format_for_llm(self, **_kwargs):
                return "fresh denia"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = Catalog()
        plugin.settings = types.SimpleNamespace(lora_max_results=50)

        first = await plugin.list_anima_loras(object(), keyword="denia")
        second = await plugin.list_anima_loras(object(), keyword="denia")

        self.assertEqual(first, "fresh denia")
        self.assertEqual(second, "fresh denia")
        self.assertEqual(plugin._lora_catalog.refreshes, 2)

    async def test_deleted_lora_preset_is_omitted_after_fresh_validation(self) -> None:
        class Catalog:
            async def refresh_for_operation(self):
                return (types.SimpleNamespace(name="present"),)

            async def resolve_selections(self, selections, *, strict):
                if any(selection.name == "deleted-denia" for selection in selections):
                    raise self_main.LoraCatalogError("missing")
                return selections

        self_main = self.main
        registry = self.main.LoraPresetRegistry([], max_loras=4)
        registry.save(
            name="风格正常",
            category="style",
            selections=(LoraSelection("present", 0.5),),
        )
        registry.save(
            name="风格旧缓存",
            category="style",
            selections=(LoraSelection("deleted-denia", 0.8),),
        )
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = Catalog()
        plugin._lora_presets = registry

        result = await plugin.list_anima_lora_presets(
            object(),
            category="风格",
        )

        self.assertIn("<lora:present:0.5>", result)
        self.assertNotIn("<lora:deleted-denia:0.8>", result)
        self.assertIn("风格旧缓存", result)


class GenerationLoraRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """The submitted workflow must use fresh exact files and safe triggers."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        cls.catalog_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.lora_catalog"
        )

    async def test_execute_job_rejects_provider_error_before_submit(self) -> None:
        submit_calls = 0

        class Client:
            @staticmethod
            async def submit(_workflow):
                nonlocal submit_calls
                submit_calls += 1
                raise AssertionError("submit must not be reached")

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._client = Client()
        plugin._workflow_builder = object()
        plugin._pipeline_builders = {}
        plugin._record_image_task_phase = lambda *_args, **_kwargs: None
        job = self.main.GenerationJob("u", "semantic redraw", 0.0)

        with self.assertRaises(self.main.WorkflowError) as raised:
            await plugin._execute_job(
                job,
                self.main.GenerationOptions(
                    prompt=(
                        "All chat models failed: EmptyModelOutputError: "
                        "OpenAI completion has no choices. response_id=private"
                    ),
                    use_prompt_llm=False,
                ),
                object(),
            )

        self.assertIn("安全闸门", str(raised.exception))
        self.assertEqual(submit_calls, 0)

    async def test_execute_job_locks_style_and_adds_role_aware_triggers(self) -> None:
        records = (
            self.catalog_module.LoraRecord(
                "styles/base.safetensors",
                category="quality_enhancement",
                trigger_words=("masterpiece", "very aesthetic"),
            ),
            self.catalog_module.LoraRecord(
                "characters/denia.safetensors",
                category="character",
                trigger_words=("denia_wuwa", "black coat", "silver hair"),
                character_name="Denia",
                aliases=("denia", "达妮娅"),
            ),
        )

        class Catalog(self.catalog_module.LoraCatalogService):
            def __init__(_self):
                super().__init__(self.main.PluginSettings.from_mapping({}))
                _self.refreshes = 0

            async def refresh_for_operation(_self):
                _self.refreshes += 1
                _self._cache = records
                _self._cache_expires_at = float("inf")
                return records

            async def _get_records(_self, *_args, **_kwargs):
                return records

        captured = []

        class Builder:
            @staticmethod
            def build(options):
                captured.append(options)
                return {"workflow": True}, 123, ["out"]

        class Client:
            @staticmethod
            async def submit(workflow):
                self.assertEqual(workflow, {"workflow": True})
                return "prompt-id"

            @staticmethod
            async def wait_for_images(prompt_id, preferred):
                self.assertEqual((prompt_id, preferred), ("prompt-id", ["out"]))
                return (object(),)

            @staticmethod
            async def download_image(_reference, job_dir):
                return job_dir / "result.png"

            @staticmethod
            async def gpu_name():
                return "Test GPU"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.PluginSettings.from_mapping(
            {
                "enable_prompt_llm": False,
                "default_style_preset": "",
                "strict_lora_validation": True,
                "max_dynamic_loras": 3,
                "max_total_dynamic_loras": 12,
                "max_prompt_length": 4000,
            }
        )
        plugin._generation_slots = __import__("asyncio").Semaphore(1)
        plugin._client = Client()
        plugin._workflow_builder = Builder()
        plugin._lora_catalog = Catalog()
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
        plugin._lora_presets.save(
            name="风格001",
            category="style",
            selections=(LoraSelection("styles/base", 0.5),),
        )
        plugin._temp_dir = Path(tempfile.mkdtemp())
        plugin._access_error = lambda _event, _text: None
        job = self.main.GenerationJob("u", "preview", 0.0)
        options = self.main.GenerationOptions(
            prompt=(
                "1girl, casual hoodie, "
                "<lora:styles/base:1.5>, <lora:characters/denia:0.8>"
            ),
            negative_prompt="black coat",
            lora_preset="风格001",
        )

        paths, seed, prompt, _, _ = await plugin._execute_job(
            job,
            options,
            object(),
        )

        # One refresh prepares the exact LoRA plan; a second refresh immediately
        # before submission catches deletion, rename or metadata replacement.
        self.assertEqual(plugin._lora_catalog.refreshes, 2)
        self.assertEqual(seed, 123)
        self.assertEqual(job.state, "completed")
        self.assertEqual(len(paths), 1)
        self.assertEqual(
            captured[0].dynamic_loras,
            (
                LoraSelection("styles/base", 0.5),
                LoraSelection("characters/denia", 0.8),
            ),
        )
        self.assertEqual(
            prompt,
            "1girl, casual hoodie, masterpiece, very aesthetic, denia_wuwa",
        )
        self.assertEqual(captured[0].negative_prompt, "black coat")
        self.assertNotIn("silver hair", prompt)

    async def test_character_swap_rejects_target_changed_after_planning(self) -> None:
        current = self.catalog_module.LoraRecord(
            "characters/kallen.safetensors",
            sha256="bb22cc33",
            category="character",
            character_name="Kallen",
            trigger_words=("kallen",),
        )

        class Catalog(self.catalog_module.LoraCatalogService):
            def __init__(_self):
                super().__init__(self.main.PluginSettings.from_mapping({}))

            async def refresh_for_operation(_self):
                _self._cache = (current,)
                _self._cache_expires_at = float("inf")
                return (current,)

            async def _get_records(_self, *_args, **_kwargs):
                return (current,)

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.PluginSettings.from_mapping(
            {
                "enable_prompt_llm": False,
                "default_style_preset": "",
                "strict_lora_validation": True,
                "max_dynamic_loras": 3,
                "max_total_dynamic_loras": 12,
                "max_prompt_length": 4000,
            }
        )
        plugin._generation_slots = asyncio.Semaphore(1)
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._lora_catalog = Catalog()
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=12)
        job = self.main.GenerationJob("u", "preview", 0.0)

        with self.assertRaisesRegex(self.main.WorkflowError, "内容变化"):
            await plugin._execute_job(
                job,
                self.main.GenerationOptions(
                    prompt="1girl, kallen",
                    use_prompt_llm=False,
                    dynamic_loras=(
                        LoraSelection("characters/kallen.safetensors", 0.65),
                    ),
                    lora_identity_expectations=(
                        LoraIdentityExpectation(
                            "characters/kallen.safetensors",
                            sha256="aa11bb22",
                        ),
                    ),
                    character_swap_target_lora=(
                        "characters/kallen.safetensors"
                    ),
                ),
                object(),
            )
        self.assertEqual(job.failed_stage, "building")

    async def test_fatal_lora_tool_error_never_uses_raw_prompt_fallback(self) -> None:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = self.main.PluginSettings.from_mapping(
            {
                "enable_prompt_llm": True,
                "prompt_llm_fallback": True,
            }
        )
        plugin._generation_slots = __import__("asyncio").Semaphore(1)
        plugin._client = object()
        plugin._workflow_builder = object()
        plugin._director = object()

        async def fail_director(_event, _prompt):
            raise self.main.PromptDirectorError(
                "LoRA 工具失败",
                fatal=True,
            )

        plugin._generate_directed_prompt = fail_director
        job = self.main.GenerationJob("u", "preview", 0.0)

        with self.assertRaises(self.main.PromptDirectorError):
            await plugin._execute_job(
                job,
                self.main.GenerationOptions(prompt="帮我用 LoRA 画图"),
                object(),
            )
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.failed_stage, "directing")


class CharacterSwapClassifierTimeoutTests(unittest.IsolatedAsyncioTestCase):
    """The configured swap timeout is one total retry budget."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_timeout_retry_stays_inside_total_budget(self) -> None:
        calls = 0

        class Context:
            async def llm_generate(self, **_kwargs):
                nonlocal calls
                calls += 1
                await asyncio.sleep(5)
                return types.SimpleNamespace(completion_text="{}")

        class Director:
            @staticmethod
            async def resolve_provider_id(_context, _event):
                return "swap-provider"

        class Planner:
            @staticmethod
            def classification_prompts(_preparation):
                return "system", "user"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = Context()
        plugin.settings = types.SimpleNamespace(
            character_swap_timeout=1,
            prompt_llm_max_tokens=1200,
        )
        plugin._director = Director()
        plugin._internal_llm_events = set()
        phases = []
        plugin._record_image_task_phase = (
            lambda _job, _stage, _message, code, **kwargs: phases.append(
                (code, kwargs.get("details", {}))
            )
        )
        job = self.main.GenerationJob("u", "swap", 0.0)
        preparation = types.SimpleNamespace(
            tags=("1girl",),
            target_trigger_words=("target",),
        )

        started = time.monotonic()
        with self.assertRaises(self.main.CharacterSwapError) as captured:
            await plugin._classify_character_swap(
                object(),
                job,
                Planner(),
                preparation,
            )
        elapsed = time.monotonic() - started

        self.assertEqual(captured.exception.code, "swap_provider_timeout")
        self.assertEqual(calls, 2)
        self.assertLess(elapsed, 1.5)
        timeout_events = [item for item in phases if item[0] == "character_swap_classifier_timeout"]
        self.assertEqual(len(timeout_events), 2)
        self.assertTrue(timeout_events[0][1]["will_retry"])
        self.assertFalse(timeout_events[1][1]["will_retry"])


class SemanticTargetTagValidationTests(unittest.IsolatedAsyncioTestCase):
    """Pure-Tags identity planning rejects malformed or control-bearing JSON."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, response_text):
        calls = []
        responses = list(response_text) if isinstance(response_text, tuple) else [response_text]

        class Context:
            async def llm_generate(self, **kwargs):
                calls.append(kwargs)
                response = responses[min(len(calls) - 1, len(responses) - 1)]
                if isinstance(response, str):
                    return types.SimpleNamespace(completion_text=response)
                return response

        class Director:
            @staticmethod
            async def resolve_provider_id(_context, _event):
                return "semantic-provider"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = Context()
        plugin._director = Director()
        plugin.settings = types.SimpleNamespace(character_swap_timeout=5)
        plugin._record_image_task_phase = lambda *_args, **_kwargs: None
        return plugin, calls

    async def test_valid_payload_uses_json_wrapped_target_data(self) -> None:
        plugin, calls = self._plugin(
            json.dumps(
                {
                    "identity_tags": [
                        "rice_shower_(umamusume)",
                        "brown hair",
                    ],
                    "confidence": 0.95,
                }
            )
        )
        tags, provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(provider, "semantic-provider")
        self.assertEqual(tags[0], "rice_shower_(umamusume)")
        self.assertEqual(
            json.loads(calls[0]["prompt"]),
            {"target_character": "赛马娘的米浴"},
        )

    async def test_formatter_accepts_think_extra_fields_and_numeric_strings(self) -> None:
        plugin, _calls = self._plugin(
            '<think>private reasoning</think>Answer:\n```json\n'
            '{"identity_tags":"rice_shower_(umamusume), brown hair",'
            '"confidence":"0.85","reason":"bounded"}\n```'
        )
        event = object()

        tags, provider = await plugin._generate_semantic_target_tags(
            event,
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(provider, "semantic-provider")
        self.assertEqual(tags, ("rice_shower_(umamusume)", "brown hair"))
        self.assertNotIn(id(event), plugin._internal_llm_events)

    async def test_structured_schema_percent_confidence_and_danbooru_escapes(self) -> None:
        plugin, _calls = self._plugin(
            json.dumps(
                {
                    "canonical_identity_tag": r"rice_shower_\(umamusume\)",
                    "appearance_tags": ["brown hair", "purple eyes"],
                    "confidence": "95%",
                }
            )
        )

        tags, _provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(
            tags,
            ("rice_shower_(umamusume)", "brown hair", "purple eyes"),
        )

    async def test_nested_result_chain_json_component_is_accepted(self) -> None:
        response = types.SimpleNamespace(
            role="assistant",
            result_chain=[
                {
                    "type": "json",
                    "data": {
                        "identity_tag": "rice_shower_(umamusume)",
                        "appearance_tags": ["brown hair"],
                        "confidence": 95,
                    },
                }
            ],
        )
        plugin, _calls = self._plugin(response)

        tags, _provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(tags, ("rice_shower_(umamusume)", "brown hair"))

    async def test_message_history_uses_only_last_assistant_answer(self) -> None:
        response = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        '{"identity_tag":"wrong_character_(wrong_work)",'
                        '"appearance_tags":[],"confidence":0.99}'
                    ),
                },
                {
                    "role": "reasoning",
                    "content": "hidden intermediate text",
                },
                {
                    "role": "assistant",
                    "content": (
                        '{"identity_tag":"rice_shower_(umamusume)",'
                        '"appearance_tags":["brown hair"],"confidence":0.95}'
                    ),
                },
            ]
        }
        plugin, _calls = self._plugin(response)

        tags, _provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(tags[0], "rice_shower_(umamusume)")

    async def test_openai_choices_message_content_is_accepted(self) -> None:
        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"identity_tag":"rice_shower_(umamusume)",'
                            '"appearance_tags":[],"confidence":95.5}'
                        ),
                    }
                }
            ]
        }
        plugin, _calls = self._plugin(response)

        tags, _provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(tags, ("rice_shower_(umamusume)",))

    async def test_nested_error_role_overrides_visible_json(self) -> None:
        response = {
            "messages": [
                {"role": "err", "content": "private upstream error"},
                {
                    "role": "assistant",
                    "content": (
                        '{"identity_tag":"rice_shower_(umamusume)",'
                        '"appearance_tags":[],"confidence":0.95}'
                    ),
                },
            ]
        }
        plugin, _calls = self._plugin(response)

        with self.assertRaises(self.main.CharacterSwapError) as raised:
            await plugin._generate_semantic_target_tags(
                object(),
                self.main.GenerationJob("u", "swap", 0.0),
                "赛马娘的米浴",
            )

        self.assertEqual(raised.exception.code, "semantic_target_provider_error")

    async def test_provider_error_role_is_reported_without_schema_misdiagnosis(self) -> None:
        plugin, calls = self._plugin(
            types.SimpleNamespace(
                role="err",
                completion_text="all_models_failed: private upstream detail",
            )
        )

        with self.assertRaises(self.main.CharacterSwapError) as raised:
            await plugin._generate_semantic_target_tags(
                object(),
                self.main.GenerationJob("u", "swap", 0.0),
                "赛马娘的米浴",
            )

        self.assertEqual(raised.exception.code, "semantic_target_provider_error")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("private", str(raised.exception.details))

    async def test_low_confidence_stops_without_confidence_laundering_retry(self) -> None:
        plugin, calls = self._plugin(
            '{"canonical_identity_tag":"unknown_character_(work)",'
            '"appearance_tags":[],"confidence":0.6}'
        )

        with self.assertRaises(self.main.CharacterSwapError) as raised:
            await plugin._generate_semantic_target_tags(
                object(),
                self.main.GenerationJob("u", "swap", 0.0),
                "冷门角色",
            )

        self.assertEqual(raised.exception.code, "semantic_target_low_confidence")
        self.assertEqual(len(calls), 1)

    async def test_qualified_identity_name_may_contain_appearance_word(self) -> None:
        plugin, _calls = self._plugin(
            '{"canonical_identity_tag":"hat_kid_(a_hat_in_time)",'
            '"appearance_tags":[],"confidence":0.92}'
        )

        tags, _provider = await plugin._generate_semantic_target_tags(
            object(),
            self.main.GenerationJob("u", "swap", 0.0),
            "Hat Kid",
        )

        self.assertEqual(tags, ("hat_kid_(a_hat_in_time)",))

    async def test_generic_qualified_concepts_and_second_identity_are_rejected(self) -> None:
        invalid_responses = (
            '{"identity_tag":"red_dress_(fiction)",'
            '"appearance_tags":[],"confidence":0.95}',
            '{"identity_tag":"target_character_(real_game)",'
            '"appearance_tags":["other_character_(other_game)"],'
            '"confidence":0.95}',
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                plugin, _calls = self._plugin(response)
                with self.assertRaises(self.main.CharacterSwapError):
                    await plugin._generate_semantic_target_tags(
                        object(),
                        self.main.GenerationJob("u", "swap", 0.0),
                        "Target",
                    )

    async def test_internal_llm_event_guard_is_active_during_provider_call(self) -> None:
        seen = []

        class Context:
            async def llm_generate(inner_self, **_kwargs):
                seen.append(id(event) in plugin._internal_llm_events)
                return types.SimpleNamespace(
                    completion_text=(
                        '{"identity_tags":["rice_shower_(umamusume)"],'
                        '"confidence":0.95}'
                    )
                )

        class Director:
            @staticmethod
            async def resolve_provider_id(_context, _event):
                return "semantic-provider"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = Context()
        plugin._director = Director()
        plugin.settings = types.SimpleNamespace(character_swap_timeout=5)
        plugin._record_image_task_phase = lambda *_args, **_kwargs: None
        plugin._internal_llm_events = set()
        event = object()

        await plugin._generate_semantic_target_tags(
            event,
            self.main.GenerationJob("u", "swap", 0.0),
            "赛马娘的米浴",
        )

        self.assertEqual(seen, [True])
        self.assertNotIn(id(event), plugin._internal_llm_events)

    async def test_invalid_json_confidence_and_control_tags_fail_closed(self) -> None:
        invalid_responses = (
            "[]",
            '{"identity_tags":["hero"],"confidence":NaN}',
            '{"identity_tags":["hero"],"confidence":Infinity}',
            '{"identity_tags":["hero"],"confidence":1.2}',
            '{"identity_tags":["BREAK"],"confidence":0.95}',
            '{"identity_tags":["embedding:hero"],"confidence":0.95}',
            '{"identity_tags":["__hero__"],"confidence":0.95}',
        )
        for response_text in invalid_responses:
            with self.subTest(response_text=response_text):
                plugin, _calls = self._plugin(response_text)
                with self.assertRaises(self.main.CharacterSwapError) as raised:
                    await plugin._generate_semantic_target_tags(
                        object(),
                        self.main.GenerationJob("u", "swap", 0.0),
                        "Target",
                    )
                self.assertEqual(
                    raised.exception.code,
                    "semantic_target_tags_invalid",
                )


class WorkflowWebUiTests(unittest.IsolatedAsyncioTestCase):
    """WebUI workflow selection must separate generation and RTX tools."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        plugin.settings = self.main.PluginSettings.from_mapping(
            {
                "workflow_dir": str(plugin.plugin_dir / "workflow"),
                "workflow_file": "workflow/anima_api.json",
            }
        )
        plugin._workflow_registry = self.main.WorkflowRegistry(
            plugin.plugin_dir / "workflow",
            plugin.settings,
        )
        plugin._active_workflow_name = "anima_api.json"
        plugin._active_jobs = {}
        plugin._pipeline_builders = {}
        plugin._control_workflow_builder = None
        plugin._control_initialization_error = ""
        plugin._workflow_switch_lock = asyncio.Lock()
        plugin._initialization_error = None
        return plugin

    async def test_list_distinguishes_generation_and_standalone_upscale(self) -> None:
        plugin = self._plugin()

        result = await plugin.web_ui_list_workflows()

        self.assertEqual(
            [item["capability_id"] for item in result["generation_items"]],
            ["base", "rtx", "iterative"],
        )
        self.assertEqual(
            [item["capability_id"] for item in result["tool_items"]],
            [
                "standalone_rtx",
                "control",
                "img2img",
                "semantic_redraw",
                "quick",
                "lanpaint",
            ],
        )
        self.assertTrue(all(item["selectable"] for item in result["generation_items"]))
        self.assertTrue(all(not item["selectable"] for item in result["tool_items"]))
        self.assertEqual(
            [item["command"] for item in result["tool_items"]],
            [
                "/放大",
                "/底图控制 <要求> [--m p|d|l|r]",
                "/改图 or /反推画图",
                "/改图 <要求> --mode preserve|balanced|free",
                "/重绘 <要求> --mode quick",
                "/重绘 <要求> --mode lanpaint",
            ],
        )
        by_name = {item["filename"]: item for item in result["items"]}
        self.assertTrue(by_name["anima_base_api.json"]["selectable"])
        self.assertFalse(by_name["anima_v2_api.json"]["selectable"])
        self.assertEqual(
            by_name["anima_base_api.json"]["task_type"],
            "text_to_image",
        )
        self.assertFalse(by_name["rtx_upscale_api.json"]["selectable"])
        self.assertEqual(
            by_name["rtx_upscale_api.json"]["task_type"],
            "upscale",
        )

    async def test_select_persists_then_hot_switches_generation_workflow(self) -> None:
        plugin = self._plugin()
        persisted = []
        plugin._persist_config_updates = lambda updates: persisted.append(updates) or True

        result = await plugin.web_ui_select_workflow("anima_iterative_api.json")

        self.assertEqual(result["selected"], "anima_iterative_api.json")
        self.assertEqual(plugin._active_workflow_name, "anima_iterative_api.json")
        self.assertEqual(plugin.settings.default_generation_pipeline, "iterative")
        self.assertEqual(
            persisted,
            [
                {
                    "workflow_file": "workflow/anima_iterative_api.json",
                    "default_generation_pipeline": "iterative",
                    "enable_upscale": True,
                }
            ],
        )

    async def test_select_rejects_upscale_and_running_jobs(self) -> None:
        plugin = self._plugin()
        plugin._persist_config_updates = lambda _updates: True
        with self.assertRaisesRegex(self.main.WebUiActionError, "独立图片放大"):
            await plugin.web_ui_select_workflow("rtx_upscale_api.json")

        task = asyncio.get_running_loop().create_future()
        plugin._active_jobs = {
            "u": self.main.GenerationJob("u", "preview", 0.0, task=task)
        }
        try:
            with self.assertRaisesRegex(self.main.WebUiActionError, "任务运行中"):
                await plugin.web_ui_select_workflow("anima_base_api.json")
        finally:
            task.cancel()

    async def test_workflow_dependency_check_uses_live_object_info(self) -> None:
        plugin = self._plugin()
        filenames = (
            "anima_base_api.json",
            "anima_rtx_api.json",
            "anima_iterative_api.json",
            "rtx_upscale_api.json",
            "anima_inpaint_crop_api.json",
            "anima_lanpaint_api.json",
            "anima_control_api.json",
        )
        class_types = set()
        for filename in filenames:
            payload = json.loads(
                (plugin.plugin_dir / "workflow" / filename).read_text(encoding="utf-8")
            )
            class_types.update(node["class_type"] for node in payload.values())
        object_info = {node_type: {} for node_type in class_types}
        object_info.update(
            {
                "UNETLoader": {
                    "input": {"required": {"unet_name": [["miaomiaoHarem_anima8Step10.safetensors"], {}]}}
                },
                "CLIPLoader": {
                    "input": {
                        "required": {
                            "clip_name": [["qwen_3_06b_base.safetensors"], {}],
                            "type": [["qwen_image"], {}],
                        }
                    }
                },
                "VAELoader": {
                    "input": {"required": {"vae_name": [["qwen_image_vae.safetensors"], {}]}}
                },
                "AnimaLLLiteApply": {
                    "input": {
                        "required": {
                            "lllite_name": [[
                                "Anima/anima-lllite-pose-1.safetensors",
                                "Anima/anima-lllite-depth-1.safetensors",
                                "Anima/anima-lllite-lineart-1.safetensors",
                                "Anima/anima-lllite-any-test-like-v2.safetensors",
                            ], {}]
                        }
                    }
                },
                "DepthAnythingV2Preprocessor": {
                    "input": {
                        "optional": {
                            "ckpt_name": [["depth_anything_v2_vitl.pth"], {}]
                        }
                    }
                },
            }
        )

        class Client:
            async def object_info(self):
                return object_info

        plugin._client = Client()
        result = await plugin.web_ui_check_workflows()
        self.assertEqual(result["ready_count"], 8)

        object_info.pop("LanPaint_MaskBlend")
        degraded = await plugin.web_ui_check_workflows()
        lanpaint = next(item for item in degraded["items"] if item["id"] == "lanpaint")
        self.assertEqual(lanpaint["status"], "unavailable")
        self.assertIn("LanPaint_MaskBlend", lanpaint["missing_node_types"])

    def test_pipeline_priority_preserves_legacy_upscale_flags(self) -> None:
        plugin = self._plugin()
        plugin.settings = replace(
            plugin.settings,
            default_generation_pipeline="iterative",
        )

        self.assertEqual(
            plugin._resolve_generation_pipeline(
                self.main.GenerationOptions(
                    prompt="1girl",
                    pipeline="base",
                    enable_upscale=True,
                )
            ),
            "base",
        )
        self.assertEqual(
            plugin._resolve_generation_pipeline(
                self.main.GenerationOptions(
                    prompt="1girl",
                    enable_upscale=False,
                )
            ),
            "base",
        )
        self.assertEqual(
            plugin._resolve_generation_pipeline(
                self.main.GenerationOptions(prompt="1girl"),
            ),
            "iterative",
        )


class WebUiControllerTests(unittest.IsolatedAsyncioTestCase):
    """Verify that the Web UI reuses the plugin's strict live-data rules."""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_lora_search_refreshes_for_every_request(self) -> None:
        class Catalog:
            def __init__(self):
                self.refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (
                    types.SimpleNamespace(
                        name="black deniav1-2.safetensors",
                        category="character",
                        model_name="Denia",
                        base_model="Anima",
                        trigger_words=("denia",),
                        tags=("character",),
                        source="manager+comfyui",
                        favorite=False,
                        aliases=("denia",),
                        character_name="Denia",
                        source_work="Wuthering Waves",
                        from_civitai=True,
                    ),
                )

            @staticmethod
            def search_records(records, keyword):
                return tuple(
                    record
                    for record in records
                    if keyword.casefold() in record.name.casefold()
                    or keyword.casefold() in record.model_name.casefold()
                )

            @staticmethod
            def archive_summary(records):
                return {
                    "categories": {
                        "character": len(records),
                        "artist_style": 0,
                        "mixed": 0,
                        "unknown": 0,
                    },
                    "civitai_enriched": len(records),
                    "identified_characters": len(records),
                    "works": [],
                }

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = Catalog()

        first = await plugin.web_ui_search_loras("denia", 50)
        second = await plugin.web_ui_search_loras("denia", 50)

        self.assertEqual(plugin._lora_catalog.refreshes, 2)
        self.assertEqual(first["items"][0]["name"], "black deniav1-2.safetensors")
        self.assertEqual(second["total"], 1)

    async def test_web_ui_archive_state_distinguishes_current_stale_and_unarchived(self) -> None:
        catalog_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.lora_catalog"
        )
        record = catalog_module.LoraRecord(
            name="characters/denia.safetensors",
            model_name="Denia",
            description="current metadata",
            base_model="Anima",
            trigger_words=("denia",),
            tags=("character",),
            aliases=("达妮娅",),
            character_name="Denia",
            source_work="Wuthering Waves",
            sha256="abc",
            from_civitai=True,
        )
        fingerprint = self.main.LoraArchiveService.record_fingerprint(record)
        entry = {
            "catalog_source_fingerprint": fingerprint,
            "classification": {"category": "character"},
        }

        self.assertEqual(
            self.main.ComfyAnimaPlugin._web_ui_archive_state(record, entry),
            "archived",
        )
        self.assertEqual(
            self.main.ComfyAnimaPlugin._web_ui_archive_state(
                record,
                {**entry, "catalog_source_fingerprint": "old"},
            ),
            "stale",
        )
        self.assertEqual(
            self.main.ComfyAnimaPlugin._web_ui_archive_state(record, {}),
            "metadata_only",
        )
        self.assertEqual(
            self.main.ComfyAnimaPlugin._web_ui_archive_state(
                replace(record, from_civitai=False),
                {},
            ),
            "unarchived",
        )
        self.assertEqual(
            self.main.ComfyAnimaPlugin._web_ui_archive_state(
                record,
                {"catalog_source_fingerprint": fingerprint, "classification": {}},
            ),
            "metadata_only",
        )

    async def test_removed_only_archive_sync_does_not_call_llm(self) -> None:
        class Status:
            def __init__(self, *, removed=(), changed=True):
                self.added = ()
                self.modified = ()
                self.removed = tuple(removed)
                self.changed = changed

            def to_dict(self):
                return {
                    "added": list(self.added),
                    "modified": list(self.modified),
                    "removed": list(self.removed),
                    "changed": self.changed,
                }

        class Catalog:
            def __init__(self):
                self.refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return ()

        class Archiver:
            def __init__(self):
                self.synced = 0

            def catalog_status(self, _records):
                return Status(removed=("deleted.safetensors",))

            def sync_catalog_presence(self, _records):
                self.synced += 1
                return Status(removed=(), changed=False)

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = Catalog()
        plugin._lora_archiver = Archiver()
        plugin._run_lora_archive_llm = lambda *_args: self.fail("LLM must not run")

        result = await plugin.web_ui_archive_loras({"sync_only": True})

        self.assertTrue(result["synced"])
        self.assertEqual(result["removed_names"], ["deleted.safetensors"])
        self.assertEqual(plugin._lora_catalog.refreshes, 1)
        self.assertEqual(plugin._lora_archiver.synced, 1)

    async def test_provider_list_reads_instantiated_astrbot_chat_models(self) -> None:
        class Provider:
            def __init__(self, provider_id, model, provider_type, name, key):
                self.provider_config = {
                    "id": provider_id,
                    "model": model,
                    "type": provider_type,
                    "name": name,
                    "key": key,
                }
                self._meta = types.SimpleNamespace(
                    id=provider_id,
                    model=model,
                    type=provider_type,
                )

            def meta(self):
                return self._meta

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        runtime_provider = Provider(
            "openai-custom-1",
            "gpt-test",
            "openai_chat_completion",
            "绘图导演",
            "secret-key",
        )
        plugin.context = types.SimpleNamespace(
            get_all_providers=lambda: [runtime_provider],
            provider_manager=types.SimpleNamespace(
                providers_config=[
                    {
                        **runtime_provider.provider_config,
                        "provider_type": "chat_completion",
                        "enable": True,
                    },
                    {
                        "id": "saved-disabled",
                        "type": "openai_chat_completion",
                        "provider_type": "chat_completion",
                        "model": "gpt-disabled",
                        "enable": False,
                        "key": "another-secret",
                    },
                    {
                        "id": "tts-provider",
                        "type": "edge_tts",
                        "provider_type": "text_to_speech",
                        "enable": True,
                    },
                ]
            ),
        )
        plugin.settings = types.SimpleNamespace(
            prompt_llm_provider_id="openai-custom-1"
        )

        result = await plugin.web_ui_list_providers()

        self.assertEqual(result["selected"], "openai-custom-1")
        self.assertEqual(result["items"][0]["model"], "gpt-test")
        self.assertEqual(result["items"][0]["name"], "绘图导演")
        self.assertTrue(result["items"][0]["available"])
        self.assertEqual(result["items"][1]["id"], "saved-disabled")
        self.assertFalse(result["items"][1]["available"])
        self.assertNotIn("tts-provider", str(result))
        self.assertNotIn("key", result["items"][0])
        self.assertNotIn("secret-key", str(result))
        self.assertNotIn("another-secret", str(result))

    async def test_provider_catalog_merges_sources_and_keeps_four_selections_independent(self) -> None:
        class Provider:
            def __init__(self, provider_id, provider_type):
                self.provider_config = {"id": provider_id}
                self._meta = types.SimpleNamespace(
                    id=provider_id,
                    model="",
                    type=provider_type,
                )

            def meta(self):
                return self._meta

        provider_sources = {
            "chat-vision-source": {
                "id": "chat-vision-source",
                "provider_type": "chat_completion",
                "type": "openai_chat_completion",
                "name": "Vision source",
                "model": "vision-model",
                "modalities": ["text", "image"],
                "key": "vision-source-secret",
                "base_url": "http://vision-source.invalid/v1",
            },
            "chat-text-source": {
                "id": "chat-text-source",
                "provider_type": "chat_completion",
                "type": "openai_chat_completion",
                "name": "Text source",
                "model": "text-model",
                "modalities": {"text": True, "image": False},
                "key": "text-source-secret",
            },
            "embedding-source": {
                "id": "embedding-source",
                "provider_type": "embedding",
                "type": "openai_embedding",
                "name": "Embedding source",
                "embedding_model": "bge-m3",
                "key": "embedding-source-secret",
                "api_base": "http://embedding-source.invalid/v1",
            },
            "rerank-source": {
                "id": "rerank-source",
                "provider_type": "rerank",
                "type": "xinference_rerank",
                "name": "Rerank source",
                "rerank_model": "bge-reranker-v2-m3",
                "key": "rerank-source-secret",
            },
        }

        class Manager:
            providers_config = [
                {
                    "id": "chat-vision",
                    "provider_source_id": "chat-vision-source",
                    "enable": True,
                },
                {
                    "id": "chat-text",
                    "provider_source_id": "chat-text-source",
                    "enable": True,
                },
                {
                    "id": "chat-unknown",
                    "provider_type": "chat_completion",
                    "type": "openai_chat_completion",
                    "model": "legacy-unknown-model",
                    "enable": True,
                    "key": "unknown-chat-secret",
                    "base_url": "http://unknown-chat.invalid/v1",
                },
                {
                    "id": "embedding-main",
                    "provider_source_id": "embedding-source",
                    "enable": True,
                },
                {
                    "id": "rerank-main",
                    "provider_source_id": "rerank-source",
                    "enable": True,
                },
            ]

            def __init__(self, rerank_provider):
                self.rerank_provider_insts = [rerank_provider]

            @staticmethod
            def get_merged_provider_config(provider_config):
                source_id = provider_config.get("provider_source_id", "")
                source = provider_sources.get(source_id, {})
                return {**source, **provider_config, "id": provider_config["id"]}

        vision = Provider("chat-vision", "openai_chat_completion")
        text = Provider("chat-text", "openai_chat_completion")
        unknown = Provider("chat-unknown", "openai_chat_completion")
        embedding = Provider("embedding-main", "openai_embedding")
        rerank = Provider("rerank-main", "xinference_rerank")

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.context = types.SimpleNamespace(
            get_all_providers=lambda: [vision, text, unknown],
            get_all_embedding_providers=lambda: [embedding],
            provider_manager=Manager(rerank),
        )
        plugin.settings = types.SimpleNamespace(
            prompt_llm_provider_id="chat-text",
            reverse_prompt_provider_id="chat-vision",
            lora_embedding_provider_id="embedding-main",
            lora_rerank_provider_id="rerank-main",
        )

        result = await plugin.web_ui_list_providers()

        self.assertEqual(result["selected_prompt"], "chat-text")
        self.assertEqual(result["selected_reverse"], "chat-vision")
        self.assertEqual(result["selected_embedding"], "embedding-main")
        self.assertEqual(result["selected_rerank"], "rerank-main")
        self.assertEqual(result["chat"]["selected"], "chat-text")
        self.assertEqual(result["embedding"]["selected"], "embedding-main")
        self.assertEqual(result["rerank"]["selected"], "rerank-main")

        chat = {item["id"]: item for item in result["chat"]["items"]}
        self.assertIs(chat["chat-vision"]["supports_image"], True)
        self.assertIs(chat["chat-text"]["supports_image"], False)
        self.assertIsNone(chat["chat-unknown"]["supports_image"])
        self.assertEqual(chat["chat-vision"]["model"], "vision-model")

        embedding_items = {
            item["id"]: item for item in result["embedding"]["items"]
        }
        rerank_items = {item["id"]: item for item in result["rerank"]["items"]}
        self.assertEqual(embedding_items["embedding-main"]["model"], "bge-m3")
        self.assertEqual(
            rerank_items["rerank-main"]["model"],
            "bge-reranker-v2-m3",
        )
        self.assertTrue(embedding_items["embedding-main"]["available"])
        self.assertTrue(rerank_items["rerank-main"]["available"])

        serialized = str(result)
        for secret in (
            "vision-source-secret",
            "text-source-secret",
            "embedding-source-secret",
            "rerank-source-secret",
            "unknown-chat-secret",
            "http://vision-source.invalid/v1",
            "http://embedding-source.invalid/v1",
            "http://unknown-chat.invalid/v1",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, serialized)
        for group_name in ("chat", "embedding", "rerank"):
            for item in result[group_name]["items"]:
                self.assertNotIn("key", item)
                self.assertNotIn("base_url", item)
                self.assertNotIn("api_base", item)

    async def test_settings_save_keeps_existing_password_when_omitted(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config_path = Path(directory.name) / "plugin.json"

        class Config(dict):
            def __init__(self, path: Path, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.config_path = str(path)
                self.saved = 0
                self.save_config()

            def save_config(self):
                self.saved += 1
                Path(self.config_path).write_text(
                    json.dumps(self, ensure_ascii=False),
                    encoding="utf-8-sig",
                )

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.config = Config(
            config_path,
            {
                "enable_web_ui": True,
                "web_ui_password": "existing-password",
                "default_width": 832,
                "max_preset_loras": 12,
                "max_total_dynamic_loras": 12,
            }
        )
        plugin.settings = self.main.PluginSettings.from_mapping(plugin.config)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        plugin._schedule_self_reload = lambda **_kwargs: object()

        result = await plugin.web_ui_save_settings(
            {
                "default_width": 1024,
                "enable_reverse_json_formatter": False,
                "enable_reverse_json_repair_retry": False,
            }
        )

        self.assertEqual(plugin.config["default_width"], 1024)
        self.assertFalse(plugin.config["enable_reverse_json_formatter"])
        self.assertFalse(plugin.config["enable_reverse_json_repair_retry"])
        self.assertEqual(plugin.config["web_ui_password"], "existing-password")
        self.assertEqual(plugin.config.saved, 2)
        self.assertTrue(result["reload_scheduled"])

    async def test_web_ui_metadata_fetch_refreshes_before_and_after(self) -> None:
        record = types.SimpleNamespace(
            name="characters/denia.safetensors",
            file_path="E:/loras/characters/denia.safetensors",
        )

        class Catalog:
            def __init__(self):
                self.refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (record,)

        class MetadataService:
            def __init__(self):
                self.paths = []

            async def fetch_civitai_metadata(self, path):
                self.paths.append(path)
                return True, "ok"

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = Catalog()
        plugin._lora_downloader = MetadataService()
        plugin._lora_download_error = ""
        plugin._lora_archiver = self.main.LoraArchiveService(Path("archive.json"))

        result = await plugin.web_ui_fetch_lora_metadata(
            {"mode": "selected", "names": [record.name]}
        )

        self.assertEqual(plugin._lora_catalog.refreshes, 2)
        self.assertEqual(plugin._lora_downloader.paths, [record.file_path])
        self.assertEqual(result["success"], 1)

    async def test_web_ui_archive_contract_supports_all_and_force(self) -> None:
        captured = {}

        class Result:
            skipped = False
            selected_count = 2
            batch_count = 1

            @staticmethod
            def to_dict():
                return {
                    "skipped": False,
                    "selected_count": 2,
                    "batch_count": 1,
                    "updated_names": ["a", "b"],
                    "status": {"changed": False},
                }

        class Archiver:
            async def archive_from_catalog(self, catalog, callback, **kwargs):
                captured.update(kwargs)
                captured["callback"] = callback
                return Result()

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_catalog = object()
        plugin._lora_archiver = Archiver()
        plugin.settings = types.SimpleNamespace(prompt_llm_provider_id="director")

        result = await plugin.web_ui_archive_loras(
            {"mode": "all", "names": [], "force": True}
        )

        self.assertIsNone(captured["selected_names"])
        self.assertFalse(captured["skip_when_unchanged"])
        self.assertEqual(result["provider_id"], "director")
        self.assertEqual(result["selected_count"], 2)

    async def test_v2_archive_returns_run_id_and_finishes_in_background(self) -> None:
        catalog_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.lora_catalog"
        )
        semantic_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.lora_semantic"
        )
        task_module = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.task_store"
        )
        record = catalog_module.LoraRecord(
            name="characters/denia.safetensors",
            model_name="Denia",
            category="character",
            sha256="a" * 64,
        )

        class Catalog:
            def __init__(self):
                self.refreshes = 0

            async def refresh_for_operation(self):
                self.refreshes += 1
                return (record,)

            async def get_detail_v2(self, current):
                return types.SimpleNamespace(
                    name=current.name,
                    metadata_health=types.SimpleNamespace(
                        status="complete",
                        missing_sources=(),
                        error_sources=(),
                    ),
                )

        class Analysis:
            def __init__(self, store):
                self.store = store

            async def run(self, details, callback, **kwargs):
                self.store.finish_task(
                    kwargs["run_id"],
                    "succeeded",
                    completed_items=len(details),
                    failed_items=0,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = task_module.TaskStore(root / "tasks.sqlite3")
            plugin = object.__new__(self.main.ComfyAnimaPlugin)
            plugin._lora_catalog = Catalog()
            plugin._semantic_index = semantic_module.LoraSemanticIndex.empty()
            plugin._semantic_index_path = root / "semantic.json"
            plugin._task_store = store
            plugin._task_store_error = ""
            plugin._lora_analysis = Analysis(store)
            plugin._background_task_runs = {}
            plugin.settings = types.SimpleNamespace(
                prompt_llm_provider_id="director",
            )
            plugin.context = types.SimpleNamespace(
                get_all_providers=lambda: [],
                provider_manager=types.SimpleNamespace(providers_config=[]),
                get_provider_by_id=lambda identifier: (
                    object() if identifier == "director" else None
                ),
            )

            result = await plugin.web_ui_archive_loras(
                {"mode": "selected", "names": [record.name]}
            )
            self.assertEqual(result["status"], "queued")
            self.assertTrue(result["run_id"])
            task = plugin._background_task_runs[result["run_id"]]
            await task
            saved = store.get_task(result["run_id"])
            self.assertEqual(saved["status"], "succeeded")
            self.assertEqual(saved["completed_items"], 1)
            self.assertGreaterEqual(plugin._lora_catalog.refreshes, 2)
            store.close()


if __name__ == "__main__":
    unittest.main()
