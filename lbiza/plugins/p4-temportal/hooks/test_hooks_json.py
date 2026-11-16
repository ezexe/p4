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


def index_prints(source):
    return sum("memory migrate" in c for c in runs("SessionStart", source))


class SessionStartTest(unittest.TestCase):
    def test_index_printed_once_per_context(self):
        counts = {s: index_prints(s) for s in ("startup", "clear", "compact", "resume", "fork")}
        print("memory migrate runs per source:", counts)
        self.assertEqual(counts, {"startup": 1, "clear": 1, "compact": 1, "resume": 0, "fork": 0})


if __name__ == "__main__":
    unittest.main()
