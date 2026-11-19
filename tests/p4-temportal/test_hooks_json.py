"""Deciding tests for hooks.json: read it and count what each start source runs."""
import json
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "lbiza" / "plugins" / "p4-temportal" / "hooks"
FILE = json.loads((SRC / "hooks.json").read_text(encoding="utf-8"))
HOOKS = FILE["hooks"]


def runs(event, source):
    """The commands an event runs for a matcher value such as a SessionStart source."""
    out = []
    for group in HOOKS.get(event, []):
        m = group.get("matcher", "")
        if m in ("", "*") or source in [v.strip() for v in m.replace(",", "|").split("|")]:
            out += [h["command"] for h in group["hooks"]]
    return out


def every_command():
    return [h["command"] for groups in HOOKS.values() for g in groups for h in g["hooks"]]


class SessionStartTest(unittest.TestCase):
    def test_the_memory_start_runs_once_per_context(self):
        counts = {s: sum("memory migrate" in c for c in runs("SessionStart", s))
                  for s in ("startup", "clear", "compact", "resume", "fork")}
        print("memory migrate runs per source:", counts)
        self.assertEqual(counts, {"startup": 1, "clear": 1, "compact": 1, "resume": 0, "fork": 0})


class NativeMemoryTest(unittest.TestCase):
    def test_no_event_moves_memory(self):
        """ezexe/p4#92: Claude Code writes the auto memory itself, so no hook mirrors a write or sweeps at Stop."""
        moves = [c for c in every_command() if "memory mirror" in c or "memory sweep" in c]
        self.assertEqual(moves, [])

    def test_a_write_or_an_edit_starts_no_hook(self):
        """ezexe/p4#118: hook runs per Write or Edit, which the mirror made one each, are none now that Claude Code
        writes the store's memory itself."""
        on_write = [g for g in HOOKS.get("PostToolUse", [])
                    if any(t in (g.get("matcher") or "*").split("|") for t in ("*", "Write", "Edit"))]
        self.assertEqual(on_write, [])


class AppScratchpadTest(unittest.TestCase):
    def test_no_event_runs_a_scratchpad_tmp_command(self):
        """ezexe/p4#131: each session's scratchpad is the app's, so no start, turn end or session end links, stages,
        commits or sweeps one."""
        tmp = [c for e in ("SessionStart", "Stop", "SessionEnd") for s in ("startup", "resume", "clear", "compact", "")
               for c in runs(e, s) if "scratchpad tmp-" in c and "scratchpad tmp-unlink" not in c]
        self.assertEqual(sorted(set(tmp)), [])



class ModuleTest(unittest.TestCase):
    """The hooks module runs the retention sweep, so no command hook does. By
    https://code.claude.com/docs/en/plugins/mods/reference.md, "Files", hooks/hooks.json holds "`modules`: an array
    with one path, relative to this file, to the hooks module" and "Can also hold settings hooks under `hooks`", and
    the module "Exports `register(on, options)`"."""

    def test_hooks_json_names_the_module_beside_the_command_hooks(self):
        self.assertEqual(FILE.get("modules"), ["./register.ts"], "one path, relative to hooks.json")
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^export const register: Register = ")
        self.assertTrue((SRC / "register.test.ts").is_file(), "its tests, for `claude plugin test`")

    def test_no_command_hook_runs_the_retention_sweep(self):
        """The module sweeps at a session's start, on its timer and at the session's end, and it runs lifetime.py with
        no `sh`. A SessionEnd command hook shares 1.5 seconds with every other one, which a plugin's `timeout` does
        not raise, by https://code.claude.com/docs/en/hooks.md, "SessionEnd input"."""
        self.assertEqual([c for c in every_command() if " lifetime " in c], [])
        self.assertNotIn("SessionEnd", HOOKS)
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        for call in ("['tick']", "['tick', '--let-go']", "on('session.start'", "on('session.end'", "$.clock.every("):
            self.assertIn(call, text)
        self.assertNotRegex(text, r"""['"]sh['"]""")

    def test_the_module_runs_the_commands_lifetime_py_takes(self):
        """`tick` and its `--let-go` are what lifetime.py's main reads, and the waits of the two files agree."""
        import sys
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        import lifetime
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        main =(SRC / "lifetime.py").read_text(encoding="utf-8")
        self.assertIn('if sub == "tick":', main)
        self.assertIn('"--let-go" in args[1:]', main)
        self.assertIn(f"const LEAST_WAIT_MS = {int(lifetime.LEAST_WAIT_S * 1000):_}", text)
        self.assertIn(f"const MOST_WAIT_MS = {int(lifetime.MOST_WAIT_S * 1000):_}", text)

    def test_the_slash_command_runs_the_commands_lifetime_py_takes(self):
        """`/lifetime` hands lifetime.py the word typed after it, so each of the module's four is a command of
        lifetime.py's own parser, and the command is registered and answered by one literal name. By
        https://code.claude.com/docs/en/plugins/mods/api.md, "Add a command": "Register it, then handle `command.run`
        for its name." The module hooks no tool event: the page serves a registered tool at `tool.call`, where an
        answer skips the permission check."""
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        main = (SRC / "lifetime.py").read_text(encoding="utf-8")
        names = re.findall(r"\['(\w+)', \d\],", text)
        self.assertEqual(names, ["list", "set", "clear", "now"])
        for name in names:
            self.assertIn(f'sp.add_parser("{name}"', main)
        self.assertIn("name: 'lifetime',", text)
        self.assertIn("on('command.run', { command: 'lifetime' }", text)
        self.assertEqual(re.findall(r"on\('(tool\.\w+)'", text), [])
        self.assertNotIn("$.tool.register", text)


class NoGitBashTest(unittest.TestCase):
    def test_a_hook_that_cannot_start_never_blocks_a_call(self):
        """ezexe/p4#121: on Windows without Git Bash, Claude Code runs a shell-form hook in PowerShell, where `sh` is
        missing, and a PreToolUse hook that fails there with onFailure unset blocks the tool call, by
        https://code.claude.com/docs/en/hooks, "Failed hooks on Windows without Git Bash". Each entry sets onFailure to
        continue, so a runner that never starts lets the call go ahead, as one that starts and exits 0 does."""
        hooks = [h for groups in HOOKS.values() for g in groups for h in g["hooks"]]
        self.assertTrue(hooks)
        self.assertEqual([h["command"] for h in hooks if h.get("onFailure") != "continue"], [])


if __name__ == "__main__":
    unittest.main()
