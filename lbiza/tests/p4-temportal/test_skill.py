"""Deciding tests for the temportal skill's SKILL.md: the commands it names, and who runs them."""
import pathlib
import re
import unittest

HOOKS = pathlib.Path(__file__).resolve().parents[2] / "plugins" / "p4-temportal" / "hooks"
SKILL = HOOKS.parent / "skills" / "temportal" / "SKILL.md"


class SkillCommands(unittest.TestCase):

    def test_each_command_the_page_names_is_one_the_module_takes(self):
        """The words after `/lifetime` on the page are the four the module's table holds, each with as many words
        after it as the module counts."""
        text = SKILL.read_text(encoding="utf-8")
        module = (HOOKS / "register.ts").read_text(encoding="utf-8")
        takes = {name: int(n) for name, n in re.findall(r"\['(\w+)', (\d)\],", module)}
        named = {}
        for words in re.findall(r"`/lifetime ([^`\n]+)`", text):
            name, *rest = words.split()
            named[name] = len(rest)
        self.assertEqual(takes, {"list": 0, "set": 2, "clear": 1, "now": 0})
        self.assertEqual(named, takes)
        self.assertIn("name: 'lifetime',", module)

    def test_the_page_hands_a_session_the_tool(self):
        """The hooks module registers the four commands as the tool `mcp__p4-temportal__lifetime`, served once Claude
        Code allowed the call. The page names that tool."""
        text = SKILL.read_text(encoding="utf-8")
        module = (HOOKS / "register.ts").read_text(encoding="utf-8")
        self.assertIn("const TOOL_ID = 'mcp__p4-temportal__lifetime'", module)
        self.assertIn("`mcp__p4-temportal__lifetime`", text)


if __name__ == "__main__":
    unittest.main()
