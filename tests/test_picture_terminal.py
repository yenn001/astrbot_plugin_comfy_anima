"""Tests for deterministic picture terminal decode and validation."""

import unittest

from ..services.picture_terminal import (
    PictureTerminalError,
    is_valid_single_pic,
    normalize_picture_terminal_text,
    parse_picture_terminal,
)


class PictureTerminalTests(unittest.TestCase):
    def test_plain_single_pic_valid(self) -> None:
        text = "好的\n<pic>daniya_(wuwa), smile</pic>"
        terminal = parse_picture_terminal(text)
        self.assertTrue(terminal.is_valid_single_pic())

    def test_escaped_once_is_accepted(self) -> None:
        raw = "&lt;pic&gt;daniya_(wuwa), smile&lt;/pic&gt;"
        terminal = parse_picture_terminal(raw)
        self.assertTrue(terminal.is_valid_single_pic())
        self.assertIn("<pic>", terminal.normalized_text)

    def test_double_escape_rejected(self) -> None:
        raw = "&amp;lt;pic&amp;gt;daniya_(wuwa)&amp;lt;/pic&amp;gt;"
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal(raw)

    def test_multiple_pic_rejected(self) -> None:
        raw = "<pic>one</pic><pic>two</pic>"
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal(raw)

    def test_pic_and_edit_together_rejected(self) -> None:
        raw = "<pic>one</pic><edit>mask</edit>"
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal(raw)

    def test_bare_prompt_rejected(self) -> None:
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal("daniya_(wuwa), smile")

    def test_lora_attribute_whitelist(self) -> None:
        parse_picture_terminal('<pic><lora:name:foo.safetensors,weight:0.8></pic>')
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal(
                '<pic><lora:name:foo.safetensors,characters:daniya></pic>'
            )

    def test_lora_weight_range(self) -> None:
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal('<pic><lora:name:foo.safetensors,weight:1.9></pic>')

    def test_fullwidth_brackets_normalized(self) -> None:
        raw = "＜pic＞daniya_(wuwa)＜/pic＞"
        self.assertTrue(is_valid_single_pic(raw))

    def test_zero_width_removed(self) -> None:
        raw = "\u200b<pic>daniya_(wuwa)</pic>\u200b"
        self.assertTrue(is_valid_single_pic(raw))

    def test_single_open_pic_accepted_without_close(self) -> None:
        # The existing <pic prompt="..."> protocol is self-closing style.
        terminal = parse_picture_terminal('<pic prompt="daniya_(wuwa)">')
        self.assertTrue(terminal.is_valid_single_pic())

    def test_extra_close_tag_rejected(self) -> None:
        with self.assertRaises(PictureTerminalError):
            parse_picture_terminal("</pic>")

    def test_normalize_removes_think_and_fences(self) -> None:
        raw = "<think>internal</think>```\n<pic>daniya</pic>\n```"
        self.assertNotIn("<think>", normalize_picture_terminal_text(raw))
        self.assertNotIn("```", normalize_picture_terminal_text(raw))


if __name__ == "__main__":
    unittest.main()
