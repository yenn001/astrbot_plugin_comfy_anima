"""回归：中文角色别名（如「大肥鱼」）必须能选中对应 LoRA。

实测：`/重绘 角色是大肥鱼 --m p` 得到 `lora_count: 0` ✗，
而库里条目 `deepseek anima0060` 的语义别名正是 `deepseek娘化(大肥鱼)` ✓、
`character_names` 是 `deepseek娘化` ✓ —— 兜底函数只看了 LoRA 记录自身的
`name/model_name/aliases`（都是文件名类）✗，没有查语义索引，于是中文名永远匹配不到，
只剩一条硬编码的「达妮娅」特例在兜个别人物 ✗。
"""

import importlib
import unittest
from types import SimpleNamespace

from ._stubs import install_astrbot_stubs


class _Value:
    def __init__(self, value: str) -> None:
        self.value = value


class SemanticAliasFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _plugin(self, entries: dict) -> object:
        plugin = object.__new__(self.main.ComfyAnimaPlugin)

        class Index:
            @staticmethod
            def entry_for(record):
                return entries.get(record.name)

        plugin._runtime_semantic_index = lambda: Index()
        return plugin

    def _record(self, name: str, aliases=()):
        return SimpleNamespace(name=name, model_name="", aliases=tuple(aliases))

    def test_chinese_alias_from_semantic_index_matches(self) -> None:
        record = self._record("deepseek anima0060.safetensors")
        entry = SimpleNamespace(
            aliases=(_Value("deepseek anima0060"), _Value("deepseek娘化(大肥鱼)")),
            character_names=(_Value("deepseek娘化"),),
            activation_terms=(_Value("deepseek"),),
            source_works=(),
        )
        plugin = self._plugin({record.name: entry})
        self.assertIs(
            plugin._find_subject_lora_by_alias((record,), "大肥鱼"), record
        )

    def test_plain_name_still_matches_by_filename(self) -> None:
        record = self._record("denia.safetensors")
        plugin = self._plugin({record.name: SimpleNamespace()})
        self.assertIs(
            plugin._find_subject_lora_by_alias((record,), "denia"), record
        )

    def test_29b_projection_does_not_make_it_ambiguous(self) -> None:
        """原版与 29B 投影同时命中同一中文别名时，选非 _29b 的那个。"""

        base = self._record("deepseek anima0060.safetensors")
        clone = self._record("29B/deepseek anima0060_29b.safetensors")
        entry = SimpleNamespace(
            aliases=(_Value("deepseek娘化(大肥鱼)"),),
            character_names=(_Value("deepseek娘化"),),
            activation_terms=(),
            source_works=(),
        )
        plugin = self._plugin({base.name: entry, clone.name: entry})
        self.assertIs(
            plugin._find_subject_lora_by_alias((clone, base), "大肥鱼"), base
        )

    def test_unknown_name_still_returns_none(self) -> None:
        record = self._record("denia.safetensors")
        plugin = self._plugin({record.name: SimpleNamespace()})
        self.assertIsNone(
            plugin._find_subject_lora_by_alias((record,), "完全不存在的角色")
        )

    def test_legacy_denia_special_case_still_works(self) -> None:
        record = self._record("black deniav1-2.safetensors")
        plugin = self._plugin({record.name: SimpleNamespace()})
        self.assertIs(plugin._find_subject_lora_by_alias((record,), "达妮娅"), record)


if __name__ == "__main__":
    unittest.main()
