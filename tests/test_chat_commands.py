"""Direct chat-command handler tests using stub events.

Covers status/cancel/ping/comfy_ls/use/lock/filter_level/reverse_prompt/
prompt_plan_list/unet_model_list success, disabled and error paths.
"""

from __future__ import annotations

import asyncio
import importlib
import types
import unittest

from ..services.reverse_prompt import ReversePromptResult


from ._stubs import install_astrbot_stubs


install_astrbot_stubs()
main = importlib.import_module("astrbot_plugin_comfy_anima.main")


class StubEvent:
    def __init__(self, message_str: str = "", *, group_id: str = "group-1"):
        self.message_str = message_str
        self._group_id = group_id
        self.replies: list[str] = []

    def plain_result(self, text: str) -> str:
        self.replies.append(text)
        return text

    def get_sender_id(self) -> str:
        return "user-1"

    def get_group_id(self) -> str:
        return self._group_id

    def is_admin(self) -> bool:
        return True


async def collect(handler):
    return [reply async for reply in handler]


class ChatCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = main

    def _plugin(self, **attrs):
        plugin = object.__new__(main.ComfyAnimaPlugin)
        for key, value in attrs.items():
            setattr(plugin, key, value)
        return plugin

    async def test_status_success_and_client_error(self) -> None:
        class Client:
            @staticmethod
            async def queue():
                return {"queue_running": [1], "queue_pending": [2, 3]}

        plugin = self._plugin(
            _jobs_lock=asyncio.Lock(),
            _active_jobs={},
            _queued_job_map=lambda: {},
            _queued_job_count_unlocked=lambda: 0,
            _client=Client(),
        )
        event = StubEvent()
        replies = await collect(plugin.cmd_status(event))
        self.assertIn("ComfyUI 运行中 1，排队 2", replies[0])

        class BrokenClient:
            @staticmethod
            async def queue():
                raise main.ComfyClientError("boom", "detail")

        plugin._client = BrokenClient()
        replies = await collect(plugin.cmd_status(StubEvent()))
        self.assertIn("状态读取失败: boom", replies[0])

    async def test_cancel_success_and_invalid_scope(self) -> None:
        plugin = self._plugin(
            _jobs_lock=asyncio.Lock(),
            _active_jobs={},
            _queued_job_map=lambda: {},
            _release_image_job=main.ComfyAnimaPlugin._release_image_job,
            _task_store=None,
            _client=None,
        )
        event = StubEvent()
        replies = await collect(plugin.cmd_cancel(event, "bogus"))
        self.assertIn("用法", replies[0])

        job = main.GenerationJob(
            "user-1",
            "preview",
            0.0,
            ready_event=asyncio.Event(),
            state="running",
        )
        job.task = asyncio.create_task(asyncio.sleep(10))
        plugin._active_jobs = {"user-1": job}

        async def release(_job):
            return None

        plugin._release_image_job = release
        replies = await collect(plugin.cmd_cancel(StubEvent(), "current"))
        self.assertIn("已请求取消当前任务", replies[0])

    async def test_ping_success_disabled_and_error(self) -> None:
        plugin = self._plugin(
            _client=None,
            _initialization_error="not ready",
        )
        replies = await collect(plugin.cmd_ping(StubEvent()))
        self.assertIn("插件尚未就绪", replies[0])

        class Client:
            @staticmethod
            async def health():
                return {"devices": [{"name": "NVIDIA Test"}]}

        plugin._client = Client()
        replies = await collect(plugin.cmd_ping(StubEvent()))
        self.assertIn("ComfyUI 连接正常", replies[0])

        class BrokenClient:
            @staticmethod
            async def health():
                raise main.ComfyClientError("down", "detail")

        plugin._client = BrokenClient()
        replies = await collect(plugin.cmd_ping(StubEvent()))
        self.assertIn("ComfyUI 连接失败: down", replies[0])

    async def test_comfy_ls_success_and_error(self) -> None:
        class Entry:
            filename = "anima_base_api.json"
            index = 1

        class Registry:
            @staticmethod
            def list_workflows():
                return [Entry()]

        plugin = self._plugin(
            _workflow_registry=Registry(),
            _active_workflow_name="anima_base_api.json",
        )
        replies = await collect(plugin.cmd_comfy_ls(StubEvent()))
        self.assertIn("anima_base_api.json", replies[0])

        class BrokenRegistry:
            @staticmethod
            def list_workflows():
                raise main.WorkflowRegistryError("no workflows")

        plugin._workflow_registry = BrokenRegistry()
        replies = await collect(plugin.cmd_comfy_ls(StubEvent()))
        self.assertIn("no workflows", replies[0])

    async def test_comfy_use_success_and_error(self) -> None:
        async def select(_identifier):
            return {"message": "切换成功"}

        plugin = self._plugin(web_ui_select_workflow=select)
        replies = await collect(plugin.cmd_comfy_use(StubEvent(), 1))
        self.assertIn("切换成功", replies[0])

        async def broken(_identifier):
            raise main.WebUiActionError("bad workflow")

        plugin.web_ui_select_workflow = broken
        replies = await collect(plugin.cmd_comfy_use(StubEvent(), 1))
        self.assertIn("切换失败: bad workflow", replies[0])

        replies = await collect(plugin.cmd_comfy_use(StubEvent(), 1, "input", "output"))
        self.assertIn("不再接受 input_id/output_id", replies[0])

    async def test_comfy_lock_success_disabled_and_error(self) -> None:
        class Access:
            @staticmethod
            def set_global_lock(value):
                return None

        async def persist(_key, _value):
            return True

        plugin = self._plugin(
            settings=main.PluginSettings.from_mapping({"enable_lock_command": True}),
            _access_controller=Access(),
            _persist_config=persist,
            _global_locked=False,
        )
        replies = await collect(plugin.cmd_comfy_lock(StubEvent(), "on"))
        self.assertIn("已锁定", replies[0])

        plugin.settings = main.PluginSettings.from_mapping({"enable_lock_command": False})
        replies = await collect(plugin.cmd_comfy_lock(StubEvent(), "on"))
        self.assertIn("锁定命令已在配置中关闭", replies[0])

        plugin.settings = main.PluginSettings.from_mapping({"enable_lock_command": True})
        replies = await collect(plugin.cmd_comfy_lock(StubEvent(), "unknown"))
        self.assertIn("用法", replies[0])

    async def test_filter_level_success_and_no_group(self) -> None:
        class Access:
            @staticmethod
            def set_group_filter_level(group_id, level):
                return types.SimpleNamespace(value=level)

        async def persist(_key, _value):
            return True

        plugin = self._plugin(
            _access_controller=Access(),
            _group_block_levels={},
            _persist_config=persist,
        )
        replies = await collect(plugin.cmd_filter_level(StubEvent(), "full"))
        self.assertIn("已设为 full", replies[0])

        replies = await collect(
            plugin.cmd_filter_level(StubEvent(group_id=""), "full")
        )
        self.assertIn("只能在群聊中使用", replies[0])

    async def test_reverse_prompt_success_disabled_and_error(self) -> None:
        plugin = self._plugin(
            _reverse_backend_ready=lambda: False,
            _access_error=lambda _event, _text, **_kwargs: "",
        )
        replies = await collect(plugin.cmd_reverse_prompt(StubEvent(), ""))
        self.assertIn("反推后端未就绪", replies[0])

        plugin._reverse_backend_ready = lambda: True
        plugin._access_error = lambda _event, _text, **_kwargs: "blocked by policy"
        replies = await collect(plugin.cmd_reverse_prompt(StubEvent(), "x"))
        self.assertIn("blocked by policy", replies[0])

        async def run_auxiliary(_event, _label, _operation):
            result = ReversePromptResult(
                positive_tags="1girl, school uniform",
                negative_tags="text, watermark",
            )
            return result, "vision-provider", 1.25

        plugin._access_error = lambda _event, _text, **_kwargs: ""
        plugin._run_auxiliary_job = run_auxiliary
        event = StubEvent(message_str="/反推")
        replies = await collect(plugin.cmd_reverse_prompt(event, ""))
        self.assertIn("1girl", replies[1])

    async def test_prompt_plan_list_success_and_error(self) -> None:
        class Plans:
            @staticmethod
            def list_plans(*, include_prompts):
                return [
                    {
                        "plan_id": "P-000001",
                        "name": "示例方案",
                        "pipeline": "base",
                        "builtin": True,
                    }
                ]

        plugin = self._plugin(_prompt_plans=Plans())
        replies = await collect(plugin.cmd_prompt_plan_list(StubEvent()))
        self.assertIn("P-000001", replies[0])

        class BrokenPlans:
            @staticmethod
            def list_plans(*, include_prompts):
                raise main.PromptPlanError("read failed")

        plugin._prompt_plans = BrokenPlans()
        replies = await collect(plugin.cmd_prompt_plan_list(StubEvent()))
        self.assertIn("方案库读取失败", replies[0])

    async def test_unet_model_list_success_disabled_and_error(self) -> None:
        plugin = self._plugin(
            settings=main.PluginSettings.from_mapping({"enable_unet_switch": False}),
            _unet_catalog=None,
        )
        replies = await collect(plugin.cmd_unet_model_list(StubEvent()))
        self.assertIn("UNET 模型切换功能已在配置中关闭", replies[0])

        plugin.settings = main.PluginSettings.from_mapping({"enable_unet_switch": True})
        plugin._unet_catalog = None
        plugin._unet_catalog_error = "catalog missing"
        replies = await collect(plugin.cmd_unet_model_list(StubEvent()))
        self.assertIn("catalog missing", replies[0])

        class Catalog:
            @staticmethod
            async def list_models():
                return [types.SimpleNamespace(name="unet-a.safetensors", index=1)]

            @staticmethod
            def format_listing(entries, current):
                return "unet-a.safetensors"

        plugin._unet_catalog = Catalog()
        plugin._current_unet_model = lambda: ""
        replies = await collect(plugin.cmd_unet_model_list(StubEvent()))
        self.assertIn("unet-a.safetensors", replies[-1])


if __name__ == "__main__":
    unittest.main()
