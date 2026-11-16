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


if __name__ == "__main__":
    unittest.main()
