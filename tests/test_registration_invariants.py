"""配置注册一致性：新增一个配置项要同时出现在多处，漏一处就是一类真实缺陷。

这里守护三条此前只能靠人工核对的邻接关系：
  1. 保存白名单 ⇒ bootstrap 载荷 —— 否则界面显示不出当前值；
  2. 表单 checkbox ⇒ booleanFields —— 否则前端读 `.value` 得到字符串，
     取消勾选也会被归一化成 True；
  3. 表单 number ⇒ numberFields —— 否则数字以字符串提交，靠后端强制转换兜底。

（"表单字段 ⇒ 白名单"与"schema ⇒ 有消费点"另有两个测试文件守护。）
"""

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WEB = PLUGIN_ROOT / "web"

# 允许"在白名单但不下发到 bootstrap"的键：{键: 理由}
NOT_IN_BOOTSTRAP_ALLOWED: dict[str, str] = {
    "web_ui_password": "密码不下发；bootstrap 只提供 web_ui_password_set 标记位",
}


def _main_source() -> str:
    return (PLUGIN_ROOT / "main.py").read_text(encoding="utf-8")


def _form_html() -> str:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    marker = html.find('id="settings-form"')
    start = html.rfind("<form", 0, marker)
    return html[start: html.find("</form>", start)]


def _js_set(name: str) -> set[str]:
    source = (WEB / "app.js").read_text(encoding="utf-8")
    block = re.search(rf"const {name} = new Set\(\[(.*?)\]\)", source, re.S)
    assert block is not None, f"app.js 里没有 {name}"
    return set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))


def _whitelist() -> set[str]:
    block = re.search(
        r"WEB_UI_EDITABLE_FIELDS\s*=\s*\((.*?)\n\)", _main_source(), re.S
    )
    assert block is not None, "main.py 里没有 WEB_UI_EDITABLE_FIELDS"
    return set(re.findall(r'"([a-z0-9_]+)"', block.group(1)))


def _bootstrap_keys() -> set[str]:
    source = _main_source()
    start = source.find("async def web_ui_bootstrap")
    assert start >= 0, "main.py 里没有 web_ui_bootstrap"
    boot = source[start: source.find("\n    async def ", start + 10)]
    marker = boot.rfind('"settings":')
    assert marker >= 0, "bootstrap 里没有 settings 载荷"
    return set(re.findall(r'"([a-z][a-z0-9_]*)"\s*:', boot[marker:]))


class RegistrationInvariantTests(unittest.TestCase):
    def test_whitelist_keys_reach_the_bootstrap(self) -> None:
        """可保存的键必须把当前值下发给前端，否则界面显示不出真实状态。"""

        missing = sorted(
            key
            for key in _whitelist()
            if key not in _bootstrap_keys() and key not in NOT_IN_BOOTSTRAP_ALLOWED
        )
        self.assertEqual(
            missing,
            [],
            "以下键可保存但 bootstrap 不下发，界面无法显示当前值：" + ", ".join(missing),
        )

    def test_form_checkboxes_are_boolean_fields(self) -> None:
        """复选框必须登记进 booleanFields，否则取消勾选仍会被存成 True。"""

        form = _form_html()
        boxes = set(re.findall(r'name="([a-z][a-z0-9_]*)"[^>]*type="checkbox"', form))
        boxes |= set(re.findall(r'type="checkbox"[^>]*name="([a-z][a-z0-9_]*)"', form))
        self.assertTrue(boxes, "设置表单里没有解析到复选框")
        missing = sorted(boxes - _js_set("booleanFields"))
        self.assertEqual(
            missing,
            [],
            "以下复选框未登记进 booleanFields，取消勾选会被存成开启："
            + ", ".join(missing),
        )

    def test_form_number_inputs_are_number_fields(self) -> None:
        """数字输入框必须登记进 numberFields。"""

        form = _form_html()
        numbers = set(re.findall(r'name="([a-z][a-z0-9_]*)"[^>]*type="number"', form))
        numbers |= set(re.findall(r'type="number"[^>]*name="([a-z][a-z0-9_]*)"', form))
        self.assertTrue(numbers, "设置表单里没有解析到数字输入框")
        missing = sorted(numbers - _js_set("numberFields"))
        self.assertEqual(
            missing,
            [],
            "以下数字输入框未登记进 numberFields：" + ", ".join(missing),
        )

    def test_allowlist_entries_stay_out_of_the_bootstrap(self) -> None:
        """豁免项若已被下发，就说明清单过期，应删掉。"""

        stale = sorted(
            key
            for key in NOT_IN_BOOTSTRAP_ALLOWED
            if key in _bootstrap_keys()
        )
        self.assertEqual(stale, [], "以下键已下发 bootstrap，请从豁免清单移除：" + ", ".join(stale))

    def test_schema_and_model_stay_aligned(self) -> None:
        """schema 键与设置模型字段必须一致（新增配置最易漏的一处）。"""

        schema = json.loads(
            (PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig")
        )
        models_src = (PLUGIN_ROOT / "models.py").read_text(encoding="utf-8")
        cls = models_src.split("class PluginSettings:", 1)[1].split(
            "\n    @classmethod", 1
        )[0]
        fields = set(re.findall(r"^    ([a-z][a-z0-9_]*)\s*:", cls, re.M))
        self.assertEqual(
            sorted(set(schema) - fields),
            [],
            "schema 有键但设置模型没有对应字段",
        )
        self.assertEqual(
            sorted(fields - set(schema)),
            [],
            "设置模型有字段但 schema 没有对应键（原生页将无法配置）",
        )


if __name__ == "__main__":
    unittest.main()
