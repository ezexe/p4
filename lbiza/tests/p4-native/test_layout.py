"""Deciding tests for p4-native's files: what its hooks.json runs, what its module asks the engine, where the
capability map is kept, and that the tests workflow checks the plugin as it checks the others."""
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
REPO = LBIZA.parent
# the folder of the code these tests read
PLUGIN = LBIZA / "plugins" / "p4-native"
HOOKS = PLUGIN / "hooks"
FILE = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
MODULE = (HOOKS / "register.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
SKILL = (PLUGIN / "skills" / "native" / "SKILL.md").read_text(encoding="utf-8")
MAP = ".claude/p4/native/host.json"


class StartTest(unittest.TestCase):
    """The start hook runs at every session start beside the other two plugins', so it is the module alone."""

    def test_hooks_json_names_the_module_and_no_command_hook(self):
        """https://code.claude.com/docs/en/plugins/mods/reference.md, "Files": hooks/hooks.json holds "`modules`: an
        array with one path, relative to this file, to the hooks module". With no `hooks` key, no command hook runs,
        so a session's start starts no `sh` and no python for this plugin."""
        self.assertEqual(FILE.get("modules"), ["./register.ts"])
        self.assertNotIn("hooks", FILE)
        self.assertRegex(MODULE, r"(?m)^export const register: Register = ")
        self.assertTrue((HOOKS / "register.test.ts").is_file(), "its tests, for `claude plugin test`")

    def test_the_plugin_holds_no_script_and_no_copy_of_p4conf(self):
        """p4conf.py is the settings keeper, held byte-equal in p4-phi and p4-temportal. p4-native writes no setting,
        so it carries no third copy, and no other script either."""
        self.assertEqual(sorted(p.name for p in PLUGIN.rglob("*.py")), [])
        self.assertEqual(sorted(p.name for p in PLUGIN.rglob("*.sh")), [])

    def test_the_module_starts_no_process_and_the_session_does_not_wait_for_the_map(self):
        self.assertNotIn("$.process.", MODULE)
        start = MODULE.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("void look($)", start)
        self.assertNotIn("await look($)", start)
        self.assertIn("await offer($)", start, "the command and the tool are listed from the first prompt")


class MapTest(unittest.TestCase):
    def test_every_fact_is_asked_of_the_engine_and_none_of_the_environment(self):
        """A `claude -p` run started from a desktop session's shell inherits that session's CLAUDE_CODE_ENTRYPOINT
        and CLAUDE_CODE_HOST_SESSION_ID, so a variable cannot tell the two hosts apart."""
        for call in ("$.session.surfaces()", "$.session.version()", "$.session.info()", "$.tool.list()",
                     "e.isInteractive"):
            self.assertIn(call, MODULE)
        self.assertNotIn("$.env.", MODULE)

    def test_the_map_is_one_file_of_the_store_named_alike_by_the_module_and_both_pages(self):
        self.assertIn("const STORE = '.claude/p4'", MODULE)
        self.assertIn("const FILE = 'native/host.json'", MODULE)
        for page in (README, SKILL):
            self.assertIn(MAP, page)
            self.assertIn("sessions.<session id>", page)

    def test_the_count_of_sessions_kept_is_the_one_the_pages_give(self):
        most = int(re.search(r"(?m)^const MOST = (\d+)$", MODULE).group(1))
        for page in (README, SKILL):
            self.assertIn(f"the newest {most} sessions", page)

    def test_nothing_of_the_plugins_folder_enters_the_stores_repository(self):
        """The store is a git repository of its own whose commits travel, and what a host can do is one machine's."""
        self.assertIn("const IGNORE = 'native/.gitignore'", MODULE)
        self.assertIn("const IGNORED = '*\\n'", MODULE)

    def test_the_tool_and_the_command_carry_the_names_the_pages_give(self):
        """https://code.claude.com/docs/en/plugins/mods/api.md, "Add a tool": the model sees a registered tool as
        `mcp__`, the plugin's name, two underscores and the registered name, and its calls are handled in a
        `tool.call` hook filtered to that full name."""
        self.assertIn("const TOOL_ID = 'mcp__p4-native__native'", MODULE)
        self.assertIn("on('tool.call', { tool: TOOL_ID }", MODULE)
        self.assertIn("on('command.run', { command: 'native' }", MODULE)
        self.assertEqual(MODULE.count("$.tool.register("), 1)
        self.assertEqual(MODULE.count("$.command.register("), 1)
        for page in (README, SKILL):
            self.assertIn("`mcp__p4-native__native`", page)
            self.assertIn("`/native`", page)


class SkillTest(unittest.TestCase):
    def test_the_skill_is_named_and_described(self):
        head = re.match(r"---\n(.*?)\n---\n", SKILL, re.S).group(1)
        fields = dict(line.split(": ", 1) for line in head.splitlines())
        self.assertEqual(fields["name"], "native")
        self.assertIn("Use ", fields["description"])


class ProseTest(unittest.TestCase):
    """ezexe's rules for a markdown page: one sentence a line, each list item on one line, and no parenthetical."""

    def prose(self, page):
        out, fenced = [], False
        for line in page.splitlines():
            if line.startswith("```"):
                fenced = not fenced
            elif not fenced and not line.startswith(("name:", "description:", "---")):
                out.append(line)
        return out

    def test_no_line_of_prose_holds_two_sentences_or_a_parenthetical(self):
        for name, page in (("README.md", README), ("SKILL.md", SKILL)):
            for line in self.prose(page):
                bare = re.sub(r"`[^`]*`", "`", line)
                if not line.startswith("- "):
                    self.assertNotRegex(bare, r"[.!?] [A-Z]", f"{name}: {line}")
                self.assertNotRegex(bare, r"\([^)]*\)", f"{name}: {line}")


class WorkflowTest(unittest.TestCase):
    def test_the_tests_workflow_validates_and_tests_every_plugin_of_the_catalog(self):
        """tests.yml names the plugins one by one, so a plugin the catalog gains is checked only once the workflow
        names it. release.yml reads `lbiza/plugins/*/.claude-plugin/plugin.json` and names none."""
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        tests = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("p4-native", [entry["name"] for entry in market["plugins"]])
        for entry in market["plugins"]:
            folder = entry["source"].removeprefix("./")
            self.assertIn(f"run: claude plugin validate {folder} --strict", tests, entry["name"])
            hooks = json.loads((REPO / folder / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            if hooks.get("modules"):
                self.assertIn(f"run: claude plugin test {folder}", tests, entry["name"])
            self.assertNotIn(entry["name"], release, "the release workflow lists plugins by a glob")
        self.assertIn("lbiza/plugins/*/.claude-plugin/plugin.json", release)


if __name__ == "__main__":
    unittest.main()
