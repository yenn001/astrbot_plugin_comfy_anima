"""Tests for explicit and natural-language reference-control mode parsing."""

import unittest

from ..services.control_modes import (
    ControlModeError,
    extract_command_control_modes,
    extract_natural_control_modes,
    looks_like_control_request,
    normalize_control_mode,
    parse_explicit_control_modes,
)


class ExplicitControlModeTests(unittest.TestCase):
    def test_short_full_and_chinese_aliases_normalize(self) -> None:
        cases = {
            "p": "pose",
            "POSE": "pose",
            "姿势": "pose",
            "d": "depth",
            "深度图": "depth",
            "l": "lineart",
            "line art": "lineart",
            "线稿": "lineart",
            "r": "reference",
            "ref": "reference",
            "IP-Adapter": "reference",
            "参考图": "reference",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_control_mode(raw), expected)

    def test_multiple_values_are_deduplicated_in_input_order(self) -> None:
        self.assertEqual(
            parse_explicit_control_modes("p d l r p"),
            ("pose", "depth", "lineart", "reference"),
        )
        self.assertEqual(
            parse_explicit_control_modes(("r", "p d", "p", "lineart")),
            ("reference", "pose", "depth", "lineart"),
        )

    def test_common_combination_separators_are_supported(self) -> None:
        for raw in ("p,d", "p+d", "p|d", "p/d", "p、d", "p，d"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parse_explicit_control_modes(raw),
                    ("pose", "depth"),
                )

    def test_empty_or_unknown_explicit_value_is_rejected(self) -> None:
        for raw in ("", "unknown", "p magic"):
            with self.subTest(raw=raw):
                with self.assertRaises(ControlModeError):
                    parse_explicit_control_modes(raw)


class NaturalControlModeTests(unittest.TestCase):
    def test_pose_phrases_are_contextual(self) -> None:
        for message in (
            "参考这张图的姿势画一个女孩",
            "照着这个动作重新画",
            "保持人物骨架和站姿",
            "use OpenPose control",
        ):
            with self.subTest(message=message):
                self.assertEqual(extract_natural_control_modes(message), ("pose",))

    def test_depth_phrases_are_contextual(self) -> None:
        for message in (
            "参考这张图的构图来画",
            "保持原图的空间结构和前后关系",
            "锁定透视布局",
            "use depth control",
        ):
            with self.subTest(message=message):
                self.assertEqual(extract_natural_control_modes(message), ("depth",))

    def test_lineart_phrases_require_a_line_reference_intent(self) -> None:
        for message in (
            "按这张线稿上色",
            "把这个草图完成上色",
            "参考线描重新绘制",
            "use lineart control",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    extract_natural_control_modes(message),
                    ("lineart",),
                )

    def test_reference_phrases_target_appearance_or_style(self) -> None:
        for message in (
            "参考这张图的画风和配色画一个新角色",
            "沿用人物长相和五官",
            "保留服装材质与质感",
            "use IPAdapter reference mode",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    extract_natural_control_modes(message),
                    ("reference",),
                )

    def test_saved_style_names_never_imply_reference(self) -> None:
        for message in (
            "用风格001-1画出来",
            "使用风格2（凛然）画一个女孩",
            "套用风格日系插画",
            "换成油画风格",
            "参考这张图的构图和姿势，用风格001-1画出来",
            "沿用原图构图，使用风格001画",
            "保持底图姿势和构图，换成油画风格",
        ):
            with self.subTest(message=message):
                self.assertNotIn(
                    "reference",
                    extract_natural_control_modes(message),
                )

    def test_reference_style_requires_explicit_source_image_semantics(self) -> None:
        for message in (
            "参考这张图的画风和配色",
            "使用这张参考图的风格",
            "沿用原图配色",
            "保持图中人物的外观",
        ):
            with self.subTest(message=message):
                self.assertIn(
                    "reference",
                    extract_natural_control_modes(message),
                )

    def test_pose_and_depth_can_be_combined(self) -> None:
        self.assertEqual(
            extract_natural_control_modes("照着这张图的姿势和构图画一个新角色"),
            ("pose", "depth"),
        )
        self.assertEqual(
            extract_natural_control_modes("参考人物长相和姿势重新画"),
            ("pose", "reference"),
        )

    def test_negation_removes_one_mode_from_a_combination(self) -> None:
        self.assertEqual(
            extract_natural_control_modes("参考姿势和构图，但不要参考姿势"),
            ("depth",),
        )
        self.assertEqual(
            extract_natural_control_modes("参考人物长相和姿势，但不要参考姿势"),
            ("reference",),
        )

    def test_only_reference_clause_is_a_hard_upper_bound(self) -> None:
        self.assertEqual(
            extract_natural_control_modes("只参考姿势，构图重新设计，画风自由发挥"),
            ("pose",),
        )
        self.assertEqual(
            extract_natural_control_modes("仅保留姿势和构图，其他全部重做"),
            ("pose", "depth"),
        )

    def test_bare_visual_words_do_not_trigger_control_generation(self) -> None:
        for message in (
            "构图漂亮一些",
            "这个角色很有深度",
            "景深浅一点",
            "make the depth of field shallow",
            "给衣服上色",
            "上色细腻一些",
            "画一张黑白线稿",
            "参考原图重新画一张",
        ):
            with self.subTest(message=message):
                self.assertEqual(extract_natural_control_modes(message), ())
                self.assertFalse(looks_like_control_request(message))

    def test_empty_text_has_no_modes(self) -> None:
        self.assertEqual(extract_natural_control_modes(""), ())
        self.assertFalse(looks_like_control_request(None))


class CommandScopedControlModeTests(unittest.TestCase):
    def test_exact_saved_style_request_is_pose_depth_only(self) -> None:
        expected = ("pose", "depth")
        self.assertEqual(
            extract_command_control_modes(
                "/底图控制 构图和姿势不变，用风格001-1 画出来。"
            ),
            expected,
        )
        self.assertEqual(
            extract_command_control_modes(
                "构图和姿势不变，用风格001-1 画出来。"
            ),
            expected,
        )

    def test_command_scoped_locks_can_be_selected_individually(self) -> None:
        self.assertEqual(
            extract_command_control_modes("只保持构图"),
            ("depth",),
        )
        self.assertEqual(
            extract_command_control_modes("只保持姿势"),
            ("pose",),
        )

    def test_command_reference_still_requires_source_semantics(self) -> None:
        self.assertEqual(
            extract_command_control_modes("参考这张图的画风和配色"),
            ("reference",),
        )
        self.assertEqual(
            extract_command_control_modes("用风格001-1画出来"),
            (),
        )


if __name__ == "__main__":
    unittest.main()
