"""使用轻量 AstrBot 桩验证主模块可导入及基础辅助逻辑。"""

import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path

from ..models import GeneratedImagePaths, LoraSelection


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
            plugin._director = object()
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

        class Config(dict):
            def save_config(self):
                return None

        plugin.config = Config(default_style_preset="风格1")
        plugin._lora_presets = self.main.LoraPresetRegistry([], max_loras=4)
        plugin._lora_presets.save(
            name="风格1",
            category="style",
            selections=(LoraSelection("shared/remove-me", 0.5),),
        )
        plugin.config["lora_presets"] = plugin._lora_presets.to_config()
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


class UnetModelSwitchTests(unittest.IsolatedAsyncioTestCase):
    """验证切换前刷新清单、持久化并更新 UNET 工作流设置。"""

    @classmethod
    def setUpClass(cls) -> None:
        _install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    async def test_switch_refreshes_latest_catalog_before_persisting(self) -> None:
        events = []
        entries = (
            types.SimpleNamespace(index=1, name="anima-a.safetensors"),
            types.SimpleNamespace(index=2, name="anima-b.safetensors"),
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
        plugin.config = {"workflow_file": "workflow/anima_api.json"}
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
        entries = (
            types.SimpleNamespace(index=1, name="anima-v2-a.safetensors"),
            types.SimpleNamespace(index=2, name="anima-v2-b.safetensors"),
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
        plugin.config = {"workflow_file": "workflow/anima_v2_api.json"}
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

        self.assertEqual(plugin._lora_catalog.refreshes, 1)
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
        class Config(dict):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.saved = 0

            def save_config(self):
                self.saved += 1

        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.config = Config(
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
        self.assertEqual(plugin.config.saved, 1)
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
