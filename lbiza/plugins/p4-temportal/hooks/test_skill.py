"""Deciding tests for the temportal skill's SKILL.md: the commands it gives the model to run."""
import pathlib
import re
import unittest

SKILL = pathlib.Path(__file__).resolve().parent.parent / "skills" / "temportal" / "SKILL.md"
RUN = 'CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}" sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh"'


def commands():
    text = SKILL.read_text(encoding="utf-8")
    return [c for c in re.findall(r"`([^`\n]+)`", text) + re.findall(r"```bash\n(.*?)```", text, re.S)
            if "CLAUDE_PLUGIN_ROOT" in c]


class SkillCommands(unittest.TestCase):
    def test_commands_go_through_run_hook(self):
        # ezexe/p4#112: a bare python3 can be the WindowsApps alias; run-hook.sh runs the proven interpreter.
        # The skill's substitution is not exported to the Bash tool, so the command passes CLAUDE_PLUGIN_ROOT itself.
        cmds = commands()
        self.assertTrue(cmds)
        for c in cmds:
            self.assertNotRegex(c, r"\bpython3?\b|\bpy\b", c)
            self.assertTrue(c.strip().startswith(RUN), c)

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

    def test_cookie_example_path_is_from_the_project_root(self):
        # lifetime.py set reads a relative path from the working folder and refuses a missing one.
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("<path under temportal/>", text)
        self.assertIn('lifetime set ".claude/p4/temportal/notebook/<file>" 7d', text)

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
