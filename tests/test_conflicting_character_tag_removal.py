"""提示词里不能同时留两个角色身份（导演写的错拼/别人必须被删）。

实测：提示词里出现 "narmaya_\(granblue_fantasy\), narume \(granblue fantasy\)" ——
正确的加了，导演写错的那句还在，出图被污染；djeeta_\(granblue_fantasy\)
（另一个真实角色）也会与正确的并列，而调用方只登记了已解析的那个。
"""

import importlib
import unittest

from ._stubs import install_astrbot_stubs

install_astrbot_stubs()
COMPILER = importlib.import_module(
    "astrbot_plugin_comfy_anima.services.character_prompt_compiler"
)

CANONICAL = "narmaya_(granblue_fantasy)"
ESCAPED = "narmaya_\\(granblue_fantasy\\)"
MISSPELLED = "narume \\(granblue fantasy\\)"
OTHER = "djeeta_\\(granblue_fantasy\\)"


def _evidence(canonical: str):
    return COMPILER.CharacterPromptEvidence(query=canonical, canonical_tag=canonical)


class ConflictingCharacterTagTests(unittest.TestCase):
    def _compile(self, prompt: str, canonical: str = CANONICAL):
        return COMPILER.compile_character_prompt(
            prompt,
            "",
            (_evidence(canonical),),
            user_request="碧蓝幻想的娜露梅",
        )

    def test_misspelled_qualified_tag_is_removed(self) -> None:
        result = self._compile("%s, %s, long hair, 1girl" % (ESCAPED, MISSPELLED))
        self.assertNotIn("narume", result.prompt.casefold())
        self.assertIn("narmaya", result.prompt.casefold())

    def test_another_character_of_the_same_work_is_removed(self) -> None:
        result = self._compile("%s, %s, lingerie" % (OTHER, ESCAPED))
        self.assertNotIn("djeeta", result.prompt.casefold())
        self.assertIn("lingerine".replace("ine", "ie"), result.prompt.casefold())

    def test_non_appearance_tags_are_untouched(self) -> None:
        # 注意：该编译器【有意】删除模型自行猜测的外貌词（身份是权威），
        # 所以这里只断言与角色/外貌无关的普通 tag 不受牵连。
        result = self._compile(
            "1girl, solo, outdoors, sitting, " + ESCAPED
        )
        for tag in ("1girl", "solo", "outdoors", "sitting"):
            self.assertIn(tag, result.prompt)
        self.assertIn("narmaya", result.prompt.casefold())

    def test_removal_is_reported_for_audit(self) -> None:
        result = self._compile("%s, nalume \\(granblue fantasy\\)" % ESCAPED)
        self.assertTrue(any("nalume" in term.casefold() for term in result.removed_terms))


if __name__ == "__main__":
    unittest.main()
