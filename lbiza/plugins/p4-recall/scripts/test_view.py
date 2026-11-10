#!/usr/bin/env python3
"""view.py: what a session has in view, rebuilt from its transcript.

    python3 -I lbiza/plugins/p4-recall/scripts/test_view.py
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import view  # noqa: E402


def turn(prompt, calls, cwd):
    return {"prompt": prompt, "cwd": cwd, "texts": [], "calls": [
        {"name": n, "input": i, "result": r, "text_index": 0} for n, i, r in calls]}


class View(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(os.path.realpath(self.tmp.name), "proj")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(os.path.join(self.p4, "models"))
        j = lambda *a: os.path.join(self.proj, *a)
        self.turns = [
            turn("look at the port", [("Read", {"file_path": j("src", "port.py")}, "def open()"),
                                      ("Read", {"file_path": j("docs", "notes.md")}, "the file body")], self.proj),
            turn("fix it", [("Edit", {"file_path": j("src", "port.py"), "old_string": "a", "new_string": "b"}, "ok"),
                            ("Bash", {"command": 'git -C "' + j("lib") + '" commit -m "port: stay open"'},
                             "[main 1a2b3c4d] port: stay open\n 1 file changed"),
                            ("Bash", {"command": "git status"}, "clean")], self.proj),
            turn("This session is being continued from a previous conversation that ran out of context.", [], self.proj),
            turn("and the tests", [("Read", {"file_path": j("tests", "test_port.py")}, "def test()"),
                                   ("Bash", {"command": "git commit -q -m quiet"}, "")], self.proj),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_holds_names_and_no_content(self):
        v = view.build(self.turns, self.proj, served={0: ["rules.md:2026-11-01 10:00:abcd1234"]})
        self.assertEqual(v["files"]["src/port.py"], {"turn": 1, "n": 2, "edited": True})
        self.assertEqual(v["files"]["docs/notes.md"], {"turn": 0, "n": 1, "edited": False})
        self.assertEqual(v["commits"], [{"turn": 1, "repo": "lib", "sha": "1a2b3c4d", "subject": "port: stay open"}],
                         "the repository's folder and what git printed; a commit that printed nothing is not guessed at")
        self.assertEqual(v["marks"], [{"turn": 2, "files": 2}])
        text = repr(v)
        for content in ("def open()", "the file body", "def test()", "old_string", "look at the port"):
            self.assertNotIn(content, text, "names and counts only")

    def test_in_view_and_dropped_follow_the_last_compaction(self):
        v = view.build(self.turns, self.proj, served={0: ["rules.md:r"], 3: ["facts.md:f"]})
        self.assertEqual(view.in_view(v), ({"tests/test_port.py"}, {"facts.md:f"}))
        self.assertEqual(view.dropped(v), ({"src/port.py", "docs/notes.md"}, {"rules.md:r"}))
        early = view.build(self.turns[:2], self.proj)
        self.assertEqual(view.in_view(early)[0], {"src/port.py", "docs/notes.md"})
        self.assertEqual(view.dropped(early), (set(), set()), "nothing is dropped before a compaction")
        self.assertEqual(view.in_view(None), (set(), set()))

    def test_a_file_outside_the_project_keeps_its_own_path(self):
        out = os.path.join(os.path.dirname(self.proj), "elsewhere", "x.h")
        v = view.build([turn("p", [("Read", {"file_path": out}, "")], self.proj)], self.proj)
        self.assertEqual(list(v["files"]), [out.replace(os.sep, "/")])

    def test_describe_is_names_for_another_session_to_read(self):
        import json
        v = view.build(self.turns[:2], self.proj)
        os.makedirs(os.path.dirname(view.path(self.p4, "abcdef12")))
        with open(view.path(self.p4, "abcdef12"), "w", encoding="utf-8") as f:
            json.dump(v, f)
        self.assertEqual(view.describe(self.p4), ["abcdef12: 2 turns, 2 files in view, 1 commits, 0 compactions"])
        got = view.describe(self.p4, "abcdef12-and-the-rest")
        self.assertEqual(got[0], "session abcdef12: 2 turns, 2 files in view, 0 dropped at a compaction")
        self.assertIn("  edited turn   1  src/port.py", got)
        self.assertIn("  read   turn   0  docs/notes.md", got)
        self.assertIn("  commit turn   1  lib 1a2b3c4d  port: stay open", got)
        self.assertEqual(view.describe(self.p4, "zzzzzzzz"), ["no record for session zzzzzzzz (records: abcdef12)"])

    def test_sizes_are_the_context_at_every_step(self):
        def user(text):
            return {"type": "user", "message": {"role": "user", "content": text}}

        def call(mid, size, tools=()):
            return {"type": "assistant", "message": {"id": mid, "usage": {"input_tokens": 10, "cache_read_input_tokens": size - 10},
                                                     "content": [{"type": "tool_use", "name": t, "id": mid + t, "input": {}} for t in tools]}}
        lines = [user("first"), call("a", 50000, ["Bash"]), call("b", 90000, ["Read", "Read"]), call("b", 90000),
                 call("c", 100000), user("second"), call("d", 101000, ["Bash"]), call("e", 30000), call("f", 31000)]
        s = view.sizes(lines)
        self.assertEqual((s["baseline"], s["last"], s["peak"], s["calls"], s["compactions"]), (50000, 31000, 101000, 6, 1))
        self.assertEqual(s["by_tool"], {"Bash": 40000, "Read": 10000}, "what the context grew by after each tool's calls; a drop is not growth")
        self.assertEqual(s["turns"], [[0, 50000, 100000], [1, 101000, 31000]])
        text = "\n".join(view.size_lines(s))
        self.assertIn("31k tokens now, 50k when it began, peak 101k, 1 compactions over 6 calls", text)
        self.assertIn("what filled it: Bash 40k, Read 10k", text)
        self.assertEqual(view.sizes([])["calls"], 0)
        self.assertEqual(view.size_lines(view.sizes([])), [])

    def test_backfill_builds_a_record_for_each_transcript(self):
        import json
        d = os.path.join(self.tmp.name, "slug")
        os.makedirs(d)
        for name in ("aaaaaaaa-1.jsonl", "bbbbbbbb-2.jsonl"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "cwd": self.proj, "message": {"role": "user", "content": "look"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 50000}, "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": os.path.join(self.proj, "src", "port.py")}}]}}) + "\n")
        with open(os.path.join(d, "cccccccc-3.jsonl"), "w", encoding="utf-8") as f:      # started by another session
            f.write(json.dumps({"type": "user", "cwd": self.proj, "origin": {"kind": "agent"}, "message": {"role": "user", "content": "go"}}) + chr(10))
            f.write(json.dumps({"type": "assistant", "message": {"id": "m9", "usage": {"input_tokens": 70000}, "content": [
                {"type": "tool_use", "id": "t9", "name": "Read", "input": {"file_path": os.path.join(self.proj, "docs", "notes.md")}}]}}) + chr(10))
        got = view.backfill(self.p4, self.proj, [d])
        self.assertEqual((got["sessions"], got["files"]), (3, 3), "a session with no owner message has a context too")
        self.assertEqual(list(view.load(self.p4, "cccccccc")["files"]), ["docs/notes.md"])
        self.assertEqual(view.describe(self.p4)[0], "aaaaaaaa: 1 turns, 1 files in view, 0 commits, 0 compactions")
        self.assertEqual(view.load(self.p4, "bbbbbbbb")["size"]["baseline"], 50000)

    def test_refresh_writes_and_reads_back(self):
        self.assertIsNone(view.load(self.p4, "abcdef12"))
        self.assertEqual(view.refresh(self.p4, self.proj, "abcdef12-rest", "", None), view.empty(), "no transcript: nothing")
        self.assertEqual(view.stats_line(self.p4), "")


if __name__ == "__main__":
    unittest.main()
