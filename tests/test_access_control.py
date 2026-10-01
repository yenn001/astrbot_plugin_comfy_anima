"""Comfy Anima 风控纯逻辑单元测试。"""

import unittest

from ..core.access_control import (
    AccessBypass,
    AccessController,
    AccessPolicy,
    AccessReason,
    FilterLevel,
    SensitiveWordFilter,
    normalize_filter_level,
    policy_from_mapping,
)


class SensitiveWordFilterTests(unittest.TestCase):
    """测试中英文分级敏感词匹配。"""

    def setUp(self) -> None:
        """使用小型确定词库隔离匹配行为。"""
        self.word_filter = SensitiveWordFilter(
            lite_words={"儿童色情", "child porn", "rape"},
            full_words={"裸体", "nude", "self harm"},
        )

    def test_none_level_never_blocks(self) -> None:
        """None 等级应完全跳过敏感词。"""
        self.assertFalse(
            self.word_filter.contains_sensitive("儿童色情 child porn", "none")
        )

    def test_lite_matches_chinese_and_english_obfuscation(self) -> None:
        """Lite 应识别中文分隔和英文短语标点变形。"""
        matches = self.word_filter.find_matches(
            "儿 童-色 情 and CHILD-PORN", FilterLevel.LITE
        )
        self.assertEqual({match.term for match in matches}, {"儿童色情", "child porn"})

    def test_english_boundary_avoids_substring_false_positive(self) -> None:
        """英文单词边界应避免 rape 命中 grape。"""
        self.assertFalse(self.word_filter.contains_sensitive("grape field", "lite"))
        self.assertTrue(self.word_filter.contains_sensitive("rape", "lite"))

    def test_full_includes_lite_and_full_only_terms(self) -> None:
        """Full 应包含 Lite 规则及自身附加规则。"""
        matches = self.word_filter.find_matches(
            "child porn, nude, self-harm", FilterLevel.FULL
        )
        self.assertEqual(
            {match.term for match in matches}, {"child porn", "nude", "self harm"}
        )
        self.assertFalse(self.word_filter.contains_sensitive("nude", FilterLevel.LITE))

    def test_invalid_level_is_rejected(self) -> None:
        """未知过滤等级应明确报错。"""
        with self.assertRaises(ValueError):
            normalize_filter_level("strict")


class AccessControllerTests(unittest.TestCase):
    """测试锁定、白名单、群级策略及显式绕过。"""

    def setUp(self) -> None:
        """创建群 100 为白名单、群 200 为 Full 的控制器。"""
        policy = AccessPolicy(
            whitelist_enabled=True,
            whitelist_groups={"100"},
            default_filter_level=FilterLevel.LITE,
            group_filter_levels={"200": FilterLevel.FULL},
        )
        word_filter = SensitiveWordFilter(
            lite_words={"blocked lite"},
            full_words={"blocked full"},
        )
        self.controller = AccessController(policy, word_filter)

    def test_global_lock_precedes_other_checks_and_can_be_bypassed(self) -> None:
        """锁定应优先拦截，并只按调用方显式权限绕过。"""
        self.controller.set_global_lock(True)
        denied = self.controller.evaluate("safe", "100")
        self.assertEqual(denied.reason, AccessReason.GLOBAL_LOCKED)

        allowed = self.controller.evaluate(
            "safe", "100", bypass=AccessBypass(global_lock=True)
        )
        self.assertTrue(allowed.allowed)

    def test_whitelist_blocks_group_but_not_private_chat(self) -> None:
        """群白名单不应误伤私聊。"""
        denied = self.controller.evaluate("safe", "999")
        self.assertEqual(denied.reason, AccessReason.GROUP_NOT_WHITELISTED)
        self.assertTrue(self.controller.evaluate("safe", None).allowed)

    def test_whitelist_bypass_does_not_imply_sensitive_bypass(self) -> None:
        """不同管理员特权必须彼此独立。"""
        decision = self.controller.evaluate(
            "blocked lite",
            "999",
            bypass=AccessBypass(whitelist=True),
        )
        self.assertEqual(decision.reason, AccessReason.SENSITIVE_CONTENT)

    def test_group_level_and_sensitive_bypass(self) -> None:
        """群覆盖等级生效，敏感词特权可单独绕过。"""
        bypass_whitelist = AccessBypass(whitelist=True)
        denied = self.controller.evaluate(
            "blocked full", "200", bypass=bypass_whitelist
        )
        self.assertEqual(denied.filter_level, FilterLevel.FULL)
        self.assertEqual(denied.reason, AccessReason.SENSITIVE_CONTENT)

        allowed = self.controller.evaluate(
            "blocked full",
            "200",
            bypass=AccessBypass(whitelist=True, sensitive_words=True),
        )
        self.assertTrue(allowed.allowed)

    def test_dynamic_group_level_update_and_clear(self) -> None:
        """管理命令可动态设置和清除群级覆盖。"""
        self.controller.set_group_filter_level(100, "full")
        self.assertEqual(self.controller.get_filter_level("100"), FilterLevel.FULL)
        self.assertTrue(self.controller.clear_group_filter_level(100))
        self.assertEqual(self.controller.get_filter_level("100"), FilterLevel.LITE)

    def test_policy_from_mapping_normalizes_config(self) -> None:
        """通用配置映射应规范化群号和过滤等级。"""
        policy = policy_from_mapping(
            {
                "global_locked": True,
                "whitelist_enabled": True,
                "whitelist_groups": [100, " 200 "],
                "default_filter_level": "NONE",
                "group_filter_levels": {100: "full"},
            }
        )
        self.assertTrue(policy.global_locked)
        self.assertEqual(policy.whitelist_groups, {"100", "200"})
        self.assertEqual(policy.default_filter_level, FilterLevel.NONE)
        self.assertEqual(policy.group_filter_levels["100"], FilterLevel.FULL)


if __name__ == "__main__":
    unittest.main()
