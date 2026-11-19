"""Deciding tests for the temportal skill's SKILL.md: the commands it names, and who runs them."""
import pathlib
import re
import unittest

HOOKS = pathlib.Path(__file__).resolve().parents[2] / "plugins" / "p4-temportal" / "hooks"
SKILL = HOOKS.parent / "skills" / "temportal" / "SKILL.md"


class SkillCommands(unittest.TestCase):
    def test_the_lifetime_commands_are_the_slash_command_and_no_shell_line(self):
        """The hooks module registers `/lifetime`, by https://code.claude.com/docs/en/plugins/mods/api.md, "Add a
        command": "A command is for the user." So the page gives the model no shell line to run, which ezexe/p4#112
        and #113 had to keep off a bare python and a path left to fill."""
        text = SKILL.read_text(encoding="utf-8")
        fenced = re.findall(r"```(\w*)\n", text)
        for gone in ("CLAUDE_PLUGIN_ROOT", "run-hook.sh", "lifetime.py", "python"):
            self.assertNotIn(gone, text)
        self.assertEqual(fenced, [])
        for line in ("`/lifetime list`", "`/lifetime set notebook/<file> 7d`", "`/lifetime clear notebook/<file>`",
                     "`/lifetime now`"):
            self.assertIn(line, text)

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

    def test_the_page_says_a_session_cannot_run_the_command(self):
        """A live check on Claude Code 2.1.322 had the Skill tool refuse it: "lifetime is a built-in CLI command, not
        a skill. Ask the user to run /lifetime themselves". The page says so, and where the model reads what is set."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("A session cannot run `/lifetime` itself", text)
        self.assertIn("give ezexe the line to type", text)
        self.assertIn("`.claude/p4/temportal/expires.json`", text)

    def test_the_page_hands_a_session_the_tool(self):
        """The hooks module registers the four commands as the tool `mcp__p4-temportal__lifetime`, served once Claude
        Code allowed the call. The page names the tool, what it takes, and ToolSearch for a session whose list does
        not hold it yet, and it still hands no shell line."""
        text = SKILL.read_text(encoding="utf-8")
        module = (HOOKS / "register.ts").read_text(encoding="utf-8")
        self.assertIn("const TOOL_ID = 'mcp__p4-temportal__lifetime'", module)
        said = next(line for line in text.splitlines() if "`mcp__p4-temportal__lifetime`" in line)
        for word in ("`command`", "`path`", "`lifetime`", "ToolSearch", "asks ezexe"):
            self.assertIn(word, said, word)
        self.assertLess(text.index("`mcp__p4-temportal__lifetime`"), text.index("give ezexe the line to type"))

    def test_the_page_names_what_claude_code_keeps_by_itself(self):
        """The rule "Native first" of CONTRIBUTING.md: a session reaches for Claude Code's own command or setting and
        builds no copy by hand. The page names each one the table of dox/temportal-native.html gives, in a section of
        its own that hands no shell line."""
        text = SKILL.read_text(encoding="utf-8")
        section = text.split("## What Claude Code keeps by itself", 1)[1].split("\n## ", 1)[0]
        for named in ("`/memory`", "`consolidate-memory`", "`/rewind`", "`cleanupPeriodDays`", "`/resume`",
                      "`/export`", "`/context`", "`/compact`", "`/autocompact`", "`plansDirectory`", "`CLAUDE.md`"):
            self.assertIn(named, section, named)
        items = [line for line in section.splitlines() if line.startswith("- **")]
        self.assertEqual([re.match(r"- \*\*([^*]+):\*\*", line).group(1) for line in items],
                         ["Memory", "A file as it was before an edit", "The whole conversation", "The context",
                          "Plans", "Worktrees", "Standing instructions"])
        self.assertNotIn("(", section)
        self.assertIn("never by a lifetime", section)
        self.assertIn("make no backup copy", section)

    def test_the_project_is_not_left_to_fill(self):
        # ezexe/p4#113: lifetime.py finds the store from CLAUDE_PROJECT_DIR or the working directory without --p4.
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("<project>", text)
        self.assertNotIn("--p4", text)
        self.assertNotIn("CLAUDE_PROJECT_DIR", text)

    def test_no_lifetime_ends_with_a_session(self):
        # A file that goes when its session goes belongs in the session's scratchpad, which Claude Code deletes with
        # the transcript, by https://code.claude.com/docs/en/claude-directory.md, "Session scratchpad directory".
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("--session", text)
        self.assertNotIn("CLAUDE_SESSION_ID", text)
        self.assertIn("No lifetime ends with a session", text)

    def test_the_cookie_example_path_is_as_list_prints_it(self):
        # lifetime.py set reads a relative path from the working folder and then from temportal/, where `list` prints
        # a cookie from, and refuses a missing one.
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("<path under temportal/>", text)
        self.assertIn("or from `temportal/` as `/lifetime list` prints it", text)

    def test_no_scratchpad_directory_is_named_in_the_store(self):
        # ezexe/p4#131: each session's scratchpad is the app's, so the skill names no folder of the store as one.
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("temportal/tmp", text)
        self.assertNotIn("ended-sweep", text)

    def test_a_session_writes_nothing_under_claude_with_its_own_tools(self):
        # ezexe/p4#131: every write under .claude/ asks ezexe even in bypass mode, so temporary files go in the app's
        # scratchpad, a lasting finding goes through phi.py note, and only p4's scripts write the notebook.
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("`scratchpad_dir`", text)
        self.assertIn('phi.py note "<claim>" --source "<where>"', text)
        self.assertIn("written by p4's scripts only", text)
        self.assertNotIn("is written there on purpose", text)


if __name__ == "__main__":
    unittest.main()
