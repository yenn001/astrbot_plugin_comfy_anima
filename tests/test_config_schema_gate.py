"""配置面闸门：`_conf_schema.json` 里的每个键都必须有生产消费点。

动机：插件曾积累了一批"配置项存在但没有任何代码读它"的字段（用户在界面上
看到开关、改了、保存成功，却什么都不会发生）。这比缺功能更糟——它让 UI 说谎。

判定：
  A. 字段名出现在生产代码里（排除 models.py 与 tests；
     `self.settings.X` / `settings.X` 都算）；
  B. 字段在 models.py 的某方法内被引用，且该方法被生产代码调用
     （例如 director_reference_file ← resolve_director_reference_path；
     只统计"排除纯装载方法"后的方法，因为 from_mapping 只是搬运值）；
  C. 允许清单（有明确理由、且不产生用户可见的假开关）。

新增 schema 键却没有任何消费点时，本测试会失败；此时应三选一：
接线 / 移除该键 / 记入允许清单并写明理由。
"""

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# 允许"无消费点"的键：{键: 理由}
SCHEMA_WITHOUT_CONSUMER_ALLOWED: dict[str, str] = {
    "config_migrated_utc": "迁移元数据：由迁移流程写入并持久化，不参与运行期决策",
    "config_migration_version": "迁移元数据：同上，用于判定迁移是否已完成",
    "conversation_draw_cooldown_seconds": (
        "已批准接线（沉浸聊天出图冷却，会改变出图节奏），完成前登记在此以免闸门误报"
    ),
}

# 只搬运值、不构成消费的方法名
CARRIER_METHODS = frozenset(
    {"from_mapping", "migrate_legacy_consolidated_config", "__post_init__"}
)


def _production_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8", errors="ignore")
        for path in PLUGIN_ROOT.rglob("*.py")
        if path.name != "models.py" and "tests" not in path.parts
    }


class SchemaConsumerGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8-sig")
        )
        cls.models_src = (PLUGIN_ROOT / "models.py").read_text(encoding="utf-8")
        cls.production = _production_sources()
        cls.production_text = "\n".join(cls.production.values())

    def _owner_methods(self, key: str) -> set[str]:
        """models.py 中引用该键的行，其所属方法名。"""

        owners: set[str] = set()
        lines = self.models_src.splitlines()
        pattern = re.compile(rf"\b{re.escape(key)}\b")
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            for back in range(index, -1, -1):
                match = re.match(r"\s*def (\w+)", lines[back])
                if match:
                    owners.add(match.group(1))
                    break
        return owners

    def _consumers(self, key: str) -> list[str]:
        pattern = re.compile(rf"\b{re.escape(key)}\b")
        if pattern.search(self.production_text):
            return ["production reference"]
        found: list[str] = []
        for method in sorted(self._owner_methods(key) - CARRIER_METHODS):
            if re.search(rf"\b{re.escape(method)}\b", self.production_text):
                found.append(f"via {method}()")
        return found

    def test_every_schema_key_has_a_consumer(self) -> None:
        dead = sorted(
            key
            for key in self.schema
            if not self._consumers(key)
            and key not in SCHEMA_WITHOUT_CONSUMER_ALLOWED
        )
        self.assertEqual(
            dead,
            [],
            "以下配置项在 schema 里存在，但没有任何生产代码消费它（界面在说谎）："
            + ", ".join(dead),
        )

    def test_allowlist_entries_are_still_dead(self) -> None:
        """接线或移除后必须同步清理允许清单，避免清单变成垃圾场。"""

        stale = sorted(
            key
            for key in SCHEMA_WITHOUT_CONSUMER_ALLOWED
            if key in self.schema and self._consumers(key)
        )
        self.assertEqual(
            stale,
            [],
            "以下键已具备消费点，请从允许清单中移除：" + ", ".join(stale),
        )

    def test_allowlist_entries_exist_in_schema(self) -> None:
        missing = sorted(
            key for key in SCHEMA_WITHOUT_CONSUMER_ALLOWED if key not in self.schema
        )
        self.assertEqual(
            missing, [], "允许清单里的键已不在 schema 中，请删除：" + ", ".join(missing)
        )

    def test_removed_keys_are_gone(self) -> None:
        """3.1.442 移除的两个无效果配置项不得回归。"""

        for key in ("show_command_progress", "follow_up_draw_priority"):
            self.assertNotIn(key, self.schema)
            self.assertNotIn(f"    {key}:", self.models_src)


if __name__ == "__main__":
    unittest.main()
