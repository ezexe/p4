"""Deciding tests for p4-native's native features: each is an option that is off by default, each is one call of
Claude Code's own that the module makes and does not wrap, and what was left out is named with its reason."""
import json
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
# the folder of the code these tests read
PLUGIN = LBIZA / "plugins" / "p4-native"
MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MODULE = (PLUGIN / "hooks" / "register.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
SECTION = README.split("## Native features behind an option\n", 1)[1].split("\n## ", 1)[0]


class OptionsTest(unittest.TestCase):
    def test_each_feature_is_an_option_that_is_off_by_default(self):
        """https://code.claude.com/docs/en/plugins/manifest-reference.md, "User configuration": each value is a
        strict object whose `type` is one of `string`, `number`, `boolean`, `directory` or `file`, with a `title` and
        a `description`, and `default` is the "value used when the user provides nothing"."""
        options = MANIFEST["userConfig"]
        self.assertEqual(sorted(options), ["push", "status"])
        for name, option in options.items():
            self.assertEqual(option["type"], "boolean", name)
            self.assertIs(option["default"], False, name)
            self.assertTrue(option["title"] and option["description"], name)
            self.assertNotIn("required", option, name)
            self.assertIn(f"- `{name}`: ezexe ", SECTION, "one sentence on what it does for ezexe")

    def test_the_module_reads_the_options_at_its_load_and_does_nothing_for_one_that_is_off(self):
        self.assertIn("export const register: Register = (on, options) => {", MODULE)
        self.assertIn("wants = { push: options.push === true, status: options.status === true }", MODULE)
        self.assertIn("let wants = { push: false, status: false }", MODULE)
        self.assertEqual(MODULE.count("wants.push"), 1)
        self.assertEqual(MODULE.count("wants.status"), 1)


class CallsTest(unittest.TestCase):
    """The plugin configures or calls each native feature and wraps none."""

    def test_push_is_one_call_of_claude_codes_own_tool_at_a_turns_end(self):
        self.assertIn("const PUSH = 'PushNotification'", MODULE)
        self.assertEqual(MODULE.count("call($, PUSH,"), 1)
        self.assertIn("call($, PUSH, { message: cut, status: 'proactive' })", MODULE)
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("if (e.agentId === undefined && wants.push && !e.isAborted) void push($, e.answer)", end)
        push = MODULE.split("async function push(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("host.run !== 'interactive'", push, "never in a scripted run")
        self.assertIn("if (isChild) return", push, "never in a session another session started")
        for word in ("$.ui.notify", "$.http.", "$.process."):
            self.assertNotIn(word, MODULE, "no notification of the plugin's own making")

    def test_status_is_one_call_of_the_engines_status_line(self):
        self.assertEqual(MODULE.count("$.ui.status("), 1)
        self.assertIn("if (wants.status) $.ui.status(`${host.host}, ${host.run}, Claude Code ${host.claude}`)", MODULE)


class LeftOutTest(unittest.TestCase):
    def test_what_failed_its_check_is_not_shipped_and_is_named_with_the_reason(self):
        """The agent teams switch was built and checked in a terminal session, where no team formed, so the module
        sets no variable. Scheduled runs are ezexe's own choice."""
        self.assertNotIn("$.env.", MODULE)
        self.assertNotIn("AGENT_TEAMS", MODULE)
        left = SECTION.split("Left out, each with its reason.\n", 1)[1]
        self.assertIn("- The agent teams switch for a terminal session: ", left)
        self.assertIn("ran as a background subagent", left)
        self.assertIn("- Scheduled runs: ezexe's own choice", left)
        self.assertIn("Not seen: a notification that was sent", SECTION)


if __name__ == "__main__":
    unittest.main()
