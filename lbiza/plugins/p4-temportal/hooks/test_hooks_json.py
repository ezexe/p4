"""Deciding tests for hooks.json: read it and count what each start source runs."""
import json
import unittest
from pathlib import Path

HOOKS = json.loads((Path(__file__).resolve().parent / "hooks.json").read_text(encoding="utf-8"))["hooks"]


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


if __name__ == "__main__":
    unittest.main()
