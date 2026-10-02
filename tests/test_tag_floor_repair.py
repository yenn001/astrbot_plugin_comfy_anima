"""3.1.449：tag 串补轮（Phase 2）。

导演稿的 tag 块不足下限时，带反馈再要一轮；**至多一轮**，且**任何情况都不抛出**——
出图不得依赖导演是否听话。

下限判定在导演稿上做（预设词在其后才合并），所以最终合并稿的 tag 数必然不少于该下限。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs

SHORT_PROMPT = (
    "1girl, red hair, smile, white dress. She stands by the window at night."
)
# tag 数达标（24 项）但【没有镜头与主光 tag】——正是线上三张图的症状
FULL_TAGS_NO_CAMERA_LIGHT = (
    "1girl, red hair, long hair, bangs, green eyes, pale skin, smile, "
    "white dress, necklace, earrings, thighhighs, garter straps, boots, "
    "gloves, ribbon, belt, sitting, holding cup, looking at viewer, "
    "bedroom, window, indoors, night, bed. She sits by the window at night."
)
# 同样 24 项，但把两项换成镜头与主光 tag → 总数不变、空槽位减少
FULL_TAGS_WITH_CAMERA_LIGHT = (
    "1girl, red hair, long hair, bangs, green eyes, pale skin, smile, "
    "white dress, necklace, earrings, thighhighs, garter straps, boots, "
    "gloves, close-up, soft lighting, sitting, holding cup, looking at viewer, "
    "bedroom, window, indoors, night, bed. She sits by the window at night."
)
LONG_PROMPT = (
    "1girl, denia_(wuthering_waves), red hair, long hair, bangs, smile, "
    "white dress, necklace, earrings, thighhighs, garter straps, boots, "
    "sitting, holding cup, looking at viewer, close-up, upper body, bedroom, "
    "window, indoors, night, soft lighting, rim light, moonlight. "
    "She sits by the window with a warm cup, lit by soft moonlight."
)


class DirectorTagFloorRepairTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, *, floor: int, replies: list, raises: bool = False):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin.settings = SimpleNamespace(min_prompt_tags=floor)
        plugin._director = SimpleNamespace()
        calls: list[str] = []

        async def fake_generate(event, scene_text, expansion_mode="standard",
                                task_kind=None, intent_plan=None):
            calls.append(scene_text)
            if raises:
                raise self.main.PromptDirectorError("补轮失败", "")
            prompt = replies[min(len(calls) - 1, len(replies) - 1)]
            return SimpleNamespace(prompt=prompt, negative_prompt="", pipeline="base"), "p"

        async def fake_timed(job, coro):
            return await coro

        plugin._generate_directed_instruction = fake_generate
        plugin._timed_llm_call = fake_timed
        plugin._record_image_task_phase = (
            lambda *args, **kwargs: None
        )
        return plugin, calls

    async def _run(self, plugin, prompt: str):
        return await plugin._repair_director_tag_floor(
            None,
            SimpleNamespace(),
            SimpleNamespace(prompt=prompt),
            "p",
            expansion_mode="standard",
            task_kind="draw",
        )

    async def test_disabled_floor_keeps_the_original(self) -> None:
        plugin, calls = self._plugin(floor=0, replies=[LONG_PROMPT])
        instruction, _ = await self._run(plugin, SHORT_PROMPT)
        self.assertEqual(instruction.prompt, SHORT_PROMPT)
        self.assertEqual(calls, [], "关闭下限时不得再调导演")

    async def test_compliant_prompt_is_not_repaired(self) -> None:
        plugin, calls = self._plugin(floor=20, replies=[LONG_PROMPT])
        instruction, _ = await self._run(plugin, LONG_PROMPT)
        self.assertEqual(instruction.prompt, LONG_PROMPT)
        self.assertEqual(calls, [], "已达标时不得再调导演")

    async def test_short_prompt_triggers_exactly_one_repair(self) -> None:
        plugin, calls = self._plugin(floor=20, replies=[LONG_PROMPT])
        instruction, _ = await self._run(plugin, SHORT_PROMPT)
        self.assertEqual(len(calls), 1, "至多补一轮")
        self.assertEqual(instruction.prompt, LONG_PROMPT, "应采用补轮结果")

    async def test_feedback_names_the_thin_slots(self) -> None:
        plugin, calls = self._plugin(floor=20, replies=[LONG_PROMPT])
        await self._run(plugin, SHORT_PROMPT)
        feedback = calls[0]
        self.assertIn("min_tags", feedback.replace("required_min_tags", "min_tags"))
        self.assertIn("empty_slots", feedback)

    async def test_repair_failure_keeps_the_original_and_does_not_raise(self) -> None:
        """补轮失败不得阻断出图。"""

        plugin, calls = self._plugin(floor=20, replies=[LONG_PROMPT], raises=True)
        instruction, _ = await self._run(plugin, SHORT_PROMPT)
        self.assertEqual(instruction.prompt, SHORT_PROMPT)
        self.assertEqual(len(calls), 1)

    async def test_worse_repair_is_rejected(self) -> None:
        plugin, calls = self._plugin(floor=20, replies=[SHORT_PROMPT])
        instruction, _ = await self._run(plugin, SHORT_PROMPT)
        self.assertEqual(instruction.prompt, SHORT_PROMPT, "未优于原稿时应保留原稿")
        self.assertEqual(len(calls), 1)

    async def test_empty_slot_triggers_repair_even_when_total_is_fine(self) -> None:
        """总数达标但某槽位为空时也必须补轮（线上三张图的症状）。"""

        plugin, calls = self._plugin(floor=20, replies=[LONG_PROMPT])
        original = self.main._prompt_tag_metrics(FULL_TAGS_NO_CAMERA_LIGHT)
        self.assertGreaterEqual(original["tag_count"], 20, "样例必须先满足总数下限")
        self.assertEqual(original["slot_markers"]["camera"], 0)
        self.assertEqual(original["slot_markers"]["lighting"], 0)

        instruction, _ = await self._run(plugin, FULL_TAGS_NO_CAMERA_LIGHT)
        self.assertEqual(len(calls), 1, "空槽位应触发补轮")
        self.assertEqual(instruction.prompt, LONG_PROMPT)

    async def test_repair_accepted_when_only_the_slots_improve(self) -> None:
        """补齐槽位但总数不变，也算改善，必须采用。"""

        before = self.main._prompt_tag_metrics(FULL_TAGS_NO_CAMERA_LIGHT)
        after = self.main._prompt_tag_metrics(FULL_TAGS_WITH_CAMERA_LIGHT)
        self.assertEqual(
            before["tag_count"], after["tag_count"], "样例总数应相同"
        )
        self.assertGreater(after["slot_markers"]["camera"], 0)
        self.assertGreater(after["slot_markers"]["lighting"], 0)

        plugin, calls = self._plugin(floor=20, replies=[FULL_TAGS_WITH_CAMERA_LIGHT])
        instruction, _ = await self._run(plugin, FULL_TAGS_NO_CAMERA_LIGHT)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            instruction.prompt,
            FULL_TAGS_WITH_CAMERA_LIGHT,
            "只改善槽位的补轮稿不应被当作劣稿丢弃",
        )

    async def test_fully_covered_prompt_is_not_repaired(self) -> None:
        """总数与槽位都满足时不得补轮。"""

        metrics = self.main._prompt_tag_metrics(LONG_PROMPT)
        self.assertGreaterEqual(metrics["tag_count"], 20)
        self.assertTrue(
            all(count > 0 for count in metrics["slot_markers"].values()),
            "样例应覆盖全部槽位",
        )
        plugin, calls = self._plugin(floor=20, replies=[FULL_TAGS_WITH_CAMERA_LIGHT])
        instruction, _ = await self._run(plugin, LONG_PROMPT)
        self.assertEqual(calls, [])
        self.assertEqual(instruction.prompt, LONG_PROMPT)


if __name__ == "__main__":
    unittest.main()
