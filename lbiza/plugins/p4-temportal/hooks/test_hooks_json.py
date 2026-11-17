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


if __name__ == "__main__":
    unittest.main()
