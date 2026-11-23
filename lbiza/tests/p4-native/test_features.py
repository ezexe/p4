"""Deciding tests for p4-native's native features: each is an option that is off by default, each is one call of
Claude Code's own that the module makes and does not wrap, and what failed its check is not shipped."""
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
        options = {name: option for name, option in MANIFEST["userConfig"].items() if not name.startswith("refuse_")}
        self.assertEqual(sorted(options), ["hints", "push", "status"])
        self.assertIs(options.pop("hints")["default"], True, "the one option that is on: it turns the lines at a miss off")
        for name, option in options.items():
            self.assertEqual(option["type"], "boolean", name)
            self.assertIs(option["default"], False, name)
            self.assertTrue(option["title"] and option["description"], name)
            self.assertNotIn("required", option, name)
            self.assertIn(f"- `{name}`: ezexe ", SECTION, "one sentence on what it does for ezexe")

    def test_the_module_reads_the_options_at_its_load_and_does_nothing_for_one_that_is_off(self):
        self.assertIn("export const register: Register = (on, options) => {", MODULE)
        self.assertIn("wants = { push: options.push === true, status: options.status === true, hints: options.hints !== false }",
                      MODULE)
        self.assertIn("let wants = { push: false, status: false, hints: true }", MODULE)
        self.assertEqual(MODULE.count("wants.push"), 2, "at a turn's end, and where Claude Code says the session waits")
        self.assertEqual(MODULE.count("wants.status"), 1)


class CallsTest(unittest.TestCase):
    """The plugin configures or calls each native feature and wraps none."""

    def test_push_is_one_call_of_claude_codes_own_tool_at_a_turns_end(self):
        self.assertIn("const PUSH = 'PushNotification'", MODULE)
        self.assertEqual(MODULE.count("call($, PUSH,"), 1)
        self.assertIn("call($, PUSH, { message: cut, status: 'proactive' })", MODULE)
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })\n\n", 1)[0]
        self.assertIn("if (e.agentId === undefined && wants.push && !e.isAborted) {\n      void push($, e.answer, true)", end)
        push = MODULE.split("async function push(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("host.run !== 'interactive'", push, "never in a scripted run")
        self.assertIn("if (isChild) return", push, "never in a session another session started")
        self.assertNotIn("$.process.", MODULE, "no process of the plugin's own making")
        self.assertEqual(MODULE.count("$.http.fetch("), 1, "one request, of the docs index, which test_says.py holds")

    def test_a_session_with_no_push_tool_notifies_on_ezexes_own_channel_at_a_turns_end_alone(self):
        """`$.ui.notify` is Claude Code's own call for a notification on the channel `preferredNotifChannel`
        names. The module makes it once, where the session has no `PushNotification` tool and a turn ended, and
        never for a session that waits, since Claude Code has then raised its own notification there."""
        self.assertEqual(MODULE.count("$.ui.notify("), 1)
        push = MODULE.split("async function push(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if (!hasTool && !isTurnEnd) return false", push)
        self.assertLess(push.index("if (isChild) return"), push.index("$.ui.notify("))
        self.assertIn("{ title: where })", push)

    def test_a_session_that_waits_on_ezexe_pushes_when_claude_code_raises_its_own_notification(self):
        """https://code.claude.com/docs/en/hooks.md, "Notification": `permission_prompt` fires once a prompt "has
        waited about six seconds" and `idle_prompt` about 60 seconds after an answer. The hook passes on what the
        settings hooks beneath answered, and acts on those two types alone: a `plugin_notification` is what
        `$.ui.notify` raises, and a hook that pushed on it would answer its own plugin."""
        self.assertIn("const WAITING = new Set(['permission_prompt', 'idle_prompt'])", MODULE)
        hook = MODULE.split("on('classic.Notification'", 1)[1].split("\n  }).catch(", 1)[0]
        self.assertLess(hook.index("const out = await next(e)"), hook.index("void push($, e.message, false)"))
        self.assertIn("if (wants.push && WAITING.has(e.notification_type) && !isTold) void push($, e.message, false)", hook)
        self.assertIn("const isTold = e.notification_type === 'idle_prompt' && wasSent", hook)
        self.assertIn("return out", hook)

    def test_status_is_one_call_of_the_engines_status_line(self):
        self.assertEqual(MODULE.count("$.ui.status("), 1)
        self.assertIn("if (wants.status) $.ui.status(`${host.host}, ${host.run}, Claude Code ${host.claude}`)", MODULE)


class LeftOutTest(unittest.TestCase):
    def test_what_failed_its_check_is_not_shipped(self):
        """The agent teams switch was built and checked in a terminal session, where no team formed, so the module
        sets no variable."""
        self.assertNotIn("$.env.", MODULE)
        self.assertNotIn("AGENT_TEAMS", MODULE)


if __name__ == "__main__":
    unittest.main()
