"""前端序列化必须与 schema 声明的类型一致。

实测事故（3.1.442 引入）：`group_block_levels` 的 schema 是 ``list``（default []），
而前端把它当成字典发出对象，于是**任何一次保存**都被 AstrBot 的 schema 校验拒绝：
"必须是字符串数组"。

后端解析器或许两种都容得下（`_as_group_levels` 就兼容字典与列表），
但**校验以 schema 为准**——所以这里以 schema 为唯一判据：
  - schema ``list``  ⇒ 前端必须发数组；
  - schema ``dict``  ⇒ 前端必须发对象。
"""

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB = PLUGIN_ROOT / "web"

# 分支名 → 该分支产出的 JS 类型
_ARRAY_BRANCHES = ("组列表", "别名行")  # 占位，见下面实际解析


def _form_field_names() -> set[str]:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    marker = html.find('id="settings-form"')
    start = html.rfind("<form", 0, marker)
    form = html[start : html.find("</form>", start)]
    return set(re.findall(r'name="([a-z][a-z0-9_]*)"', form))


def _branch_names(js: str, pattern: str) -> set[str]:
    block = re.search(pattern, js, re.S)
    assert block is not None, f"未找到分支：{pattern}"
    return set(re.findall(r'field\.name === "([a-z0-9_]+)"', block.group(0)))


def _js_branches() -> tuple[set[str], set[str], set[str]]:
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # 数组分支：以 group_whitelist 开头、以 filter(Boolean) 结束的那一段
    array_branch = _branch_names(
        js, r'field\.name === "group_whitelist".*?filter\(Boolean\);'
    )
    # 字典分支：bot_character_preset_scopes 所在分支（产出 entries 对象）
    dict_branch = _branch_names(
        js, r'field\.name === "bot_character_preset_scopes".*?result\[field\.name\] = entries;'
    )
    # 别名分支：单独一段，同样产出数组
    alias_branch = _branch_names(
        js, r'field\.name === "lora_alias_rules".*?filter\(Boolean\);'
    )
    return array_branch, dict_branch, alias_branch


class SerializationMatchesSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig")
        )
        cls.fields = _form_field_names()
        cls.arrays, cls.dicts, cls.aliases = _js_branches()

    def test_list_fields_are_serialized_as_arrays(self) -> None:
        """schema=list 的表单字段必须走数组分支（否则保存被 schema 校验拒绝）。"""

        offenders = []
        for name in sorted(self.fields):
            entry = self.schema.get(name)
            if not isinstance(entry, dict) or entry.get("type") != "list":
                continue
            if name not in self.arrays and name not in self.aliases:
                offenders.append(name)
        self.assertEqual(
            offenders,
            [],
            "以下 schema=list 字段没有以数组提交，保存会报“必须是字符串数组”："
            + ", ".join(offenders),
        )

    def test_dict_fields_are_serialized_as_objects(self) -> None:
        offenders = []
        for name in sorted(self.fields):
            entry = self.schema.get(name)
            if not isinstance(entry, dict) or entry.get("type") != "dict":
                continue
            if name not in self.dicts:
                offenders.append(name)
        self.assertEqual(
            offenders, [], "以下 schema=dict 字段没有以对象提交：" + ", ".join(offenders)
        )

    def test_group_block_levels_regression(self) -> None:
        """3.1.456 的事故字段：必须是数组、不得再进字典分支。"""

        self.assertIn("group_block_levels", self.arrays)
        self.assertNotIn("group_block_levels", self.dicts)
        self.assertEqual(
            self.schema["group_block_levels"]["type"], "list"
        )

    def test_assets_copies_match(self) -> None:
        for name in ("app.js", "app.css", "theme.js"):
            self.assertEqual(
                (WEB / name).read_bytes(),
                (PLUGIN_ROOT / "pages" / "control" / name).read_bytes(),
                f"{name} 未同步：请运行 scripts/sync_web_assets.py",
            )


if __name__ == "__main__":
    unittest.main()
