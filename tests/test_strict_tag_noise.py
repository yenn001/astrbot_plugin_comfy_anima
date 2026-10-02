"""3.1.453: the strict tag check must ignore HTML wrapper noise.

Measured cause of the intermittent redraw failures: the director returned a
complete, valid ``<pic ...>`` tag followed by a stray ``</p>`` (4 characters,
matching ``trailing=4``) or ``</pic>``. Wrapper tags carry no information, so they
are stripped before the strict check; real text outside the tag must still fail.
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs

GOOD = '<pic prompt="1girl, smile" negative="bad hands">'


class StrictControlMatchNoiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")
        cls.pd = importlib.import_module(
            "astrbot_plugin_comfy_anima.services.prompt_director"
        )

    def _match(self, text: str):
        return self.pd.PromptDirector._strict_control_match(
            text,
            pattern=self.pd._PIC_TAG_RE,
            control_name="pic",
            detail="invalid_picture_protocol",
        )

    def test_trailing_paragraph_close_is_tolerated(self) -> None:
        """实测根因：标签后多了 </p>（trailing=4）。"""

        match = self._match(GOOD + "</p>")
        self.assertEqual(match.group(0), GOOD)

    def test_trailing_pic_close_is_tolerated(self) -> None:
        match = self._match(GOOD + "</pic>")
        self.assertEqual(match.group(0), GOOD)

    def test_leading_paragraph_and_breaks_are_tolerated(self) -> None:
        for noise in ("<p>", "<br>", "<br/>", "<br />", "</p>\n"):
            with self.subTest(noise=noise):
                match = self._match(noise + GOOD)
                self.assertEqual(match.group(0), GOOD)

    def test_both_sides_are_tolerated(self) -> None:
        match = self._match("<p>" + GOOD + "</p>")
        self.assertEqual(match.group(0), GOOD)

    def test_real_text_still_fails(self) -> None:
        with self.assertRaises(self.pd.PromptDirectorError) as ctx:
            self._match("这是解释文字 " + GOOD)
        self.assertIn("extra_content", ctx.exception.protocol_reason)

    def test_two_pic_tags_still_fail(self) -> None:
        with self.assertRaises(self.pd.PromptDirectorError) as ctx:
            self._match(GOOD + GOOD)
        self.assertIn("tag_count=2", ctx.exception.protocol_reason)

    def test_protocol_reason_reports_wrapper_stripping(self) -> None:
        with self.assertRaises(self.pd.PromptDirectorError) as ctx:
            self._match(GOOD + GOOD + "</p>")
        self.assertIn("wrapper_stripped=1", ctx.exception.protocol_reason)


if __name__ == "__main__":
    unittest.main()
