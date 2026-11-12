#!/usr/bin/env python3
"""lookups.py: every tool call is recorded, and a call is checked against what earlier calls found before it runs.

    python3 -I lbiza/plugins/p4-phi/scripts/test_lookups.py

Checked: a call's key, kind and error signature; one row per tool_use id; a web finding handed back in place of the
same question (PreToolUse deny, once: the same call again runs); a different question about the same page left
alone; an old finding left alone; a failed command's signature recognised when it fails again in another session,
with the command that worked after it; the modes (answer, note, shadow, off); a corrupt database never failing a
call; the backfill from transcripts taking each tool_use id once; a training round writing a model only when it
beats the matcher; hooks.json's matchers.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
os.environ["P4_PHI"] = "0"          # phi's routed checks stay out of these tests: they touch no live store

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lookups as lk  # noqa: E402
import p4conf  # noqa: E402
from test_hooks import HOOKS_JSON, make_project, run_hook, transcript  # noqa: E402

S1 = "aaaa1111-0000-4000-8000-000000000000"
S2 = "bbbb2222-0000-4000-8000-000000000000"
URL = "https://docs.example.org/narwhal/ports"
ASK = "Quote what the page says about the narwhal port timeout and its default value"
FOUND = ("The narwhal port times out after 30 seconds by default. Set NARWHAL_TIMEOUT to change it; a value of 0 "
         "disables the timeout. The page lists no other setting for the port.")


def pre(tool, inp, session=S2, proj=None, tid="t-pre", **more):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "session_id": session,
            "tool_use_id": tid, "cwd": proj, **more}


def post(tool, inp, resp, session=S1, proj=None, tid="t1", event="PostToolUse", **more):
    d = {"hook_event_name": event, "tool_name": tool, "tool_input": inp, "session_id": session, "tool_use_id": tid,
         "cwd": proj, **more}
    d["error" if event == "PostToolUseFailure" else "tool_response"] = resp
    return d


class Keys(unittest.TestCase):
    def test_kind_and_key(self):
        self.assertEqual(lk.kind("WebFetch"), "web")
        self.assertEqual(lk.kind("PowerShell"), "shell")
        self.assertEqual(lk.kind("Read"), "read")
        self.assertEqual(lk.kind("mcp__thing__do"), "other")
        a = lk.key_of("Bash", {"command": "git  status\n --short", "description": "x"})
        b = lk.key_of("Bash", {"command": "git status --short", "description": "y"})
        self.assertEqual(a, b)
        self.assertEqual(lk.key_of("WebFetch", {"url": URL + "/#top", "prompt": ASK}),
                         lk.key_of("WebFetch", {"url": URL.upper(), "prompt": "  " + ASK}))
        self.assertNotEqual(lk.key_of("Read", {"file_path": "a.py"}), lk.key_of("Read", {"file_path": "b.py"}))

    def test_signature_reads_the_tail_and_drops_numbers_and_paths(self):
        a = lk.signature("line 1\nTraceback (most recent call last):\n  File \"C:\\x\\y.py\", line 71, in <module>\n"
                         "ModuleNotFoundError: No module named 'numpy'", True)
        b = lk.signature("Traceback\n  File \"/home/u/z.py\", line 3\nModuleNotFoundError: No module named 'numpy'", True)
        self.assertEqual(a, b)
        self.assertIn("numpy", a)
        self.assertEqual(lk.signature("def f():\n    raise ValueError('x')\nall good\ndone\nok\nfine", False), "")
        self.assertTrue(lk.signature("Exit code 127\n/usr/bin/bash: line 1: clang-format: command not found", True))
        mid = lk.signature("Traceback (most recent call last):\n  File \"a.py\", line 5, in <module>\n    import numpy\n"
                           "ModuleNotFoundError: No module named 'numpy'\np4 store ok\n  mode: active\n  owed: nothing",
                           False)
        self.assertEqual(mid, a)                              # a traceback mid-output, the command exiting 0
        crlf = lk.signature("Traceback (most recent call last):\r\n  File \"a.py\", line 5, in <module>\r\n"
                            "ModuleNotFoundError: No module named 'numpy'\r\np4 store ok\r\n  mode: active\r\n  owed: x",
                            False)
        self.assertEqual(crlf, a)                             # the same on Windows, whose lines end \r\n
        import time
        t0 = time.time()                                      # a long indented block and no error line after it
        self.assertEqual(lk.signature("Traceback (most recent call last):\n" + ("        deep line\n" * 400) + "end",
                                      False), "")
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(lk.signature("Exit code 1\n-rw-r--r-- 1 u 197609 224 Nov 11 07:50 retrain-resolved.tsv", True), "")
        self.assertEqual(lk.stamp("2026-11-01T18:00:00.000Z")[:4], "2026")

    def test_flatten_takes_strings_from_any_response(self):
        self.assertEqual(lk.flatten("abc"), "abc")
        self.assertIn("out text", lk.flatten({"stdout": "out text", "stderr": "", "interrupted": False}))
        self.assertIn("deep", lk.flatten({"results": [{"content": [{"text": "deep"}]}]}))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)
        self.p4 = os.path.join(self.proj, ".claude", "p4")

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def conf(self, **kw):
        data = p4conf.load(self.p4)
        data["recall"]["lookups"].update(kw)
        p4conf._write(self.p4, data)

    def rows(self, where="1=1"):
        con = sqlite3.connect(lk.db_path(self.p4))
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(f"SELECT * FROM calls WHERE {where} ORDER BY rowid")]
        finally:
            con.close()

    def checks(self):
        con = sqlite3.connect(lk.db_path(self.p4))
        try:
            return [r[0] for r in con.execute("SELECT action FROM checks ORDER BY rowid")]
        finally:
            con.close()

    def record_fetch(self, tid="t1", session=S1, ask=ASK, found=FOUND, url=URL):
        return self.out(run_hook("lookup-record", post("WebFetch", {"url": url, "prompt": ask},
                                                       {"result": found, "url": url, "code": 200}, session, self.proj,
                                                       tid), self.proj))


class Record(Base):
    def test_every_tool_gets_one_row_per_call(self):
        self.record_fetch()
        self.record_fetch()                                   # the same tool_use id again: no second row
        self.out(run_hook("lookup-record", post("Bash", {"command": "ls src"}, {"stdout": "narwhal_port.py"},
                                                S1, self.proj, "t2"), self.proj))
        self.out(run_hook("lookup-record", post("Read", {"file_path": os.path.join(self.proj, "README.md")},
                                                {"file": {"content": "# Narwhal"}}, S1, self.proj, "t3"), self.proj))
        got = self.rows()
        self.assertEqual([r["tool"] for r in got], ["WebFetch", "Bash", "Read"])
        self.assertEqual([r["ok"] for r in got], [1, 1, 1])
        self.assertIn("30 seconds", got[0]["finding"])
        self.assertEqual(got[1]["finding"], "")              # a passing command's output is not kept
        with open(p4conf.sub(self.p4, "store", "lookups.jsonl"), encoding="utf-8") as f:
            kept = [json.loads(l) for l in f]
        self.assertEqual([k["tool"] for k in kept], ["WebFetch"])     # the tracked file: findings, not every call

    def test_a_clean_call_is_recorded_behind_the_call(self):
        import time
        r = run_hook("lookup-record", post("Bash", {"command": "ls src"}, {"stdout": "narwhal_port.py"}, S1, self.proj,
                                           "t7"), self.proj, {"P4_RECALL_SYNC": "0"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        for _ in range(100):                                  # the python left behind writes the row
            if os.path.exists(lk.db_path(self.p4)) and self.rows("id='t7'"):
                break
            time.sleep(0.1)
        self.assertEqual([x["tool"] for x in self.rows("id='t7'")], ["Bash"])

    def test_tools_with_nothing_to_check_never_start_python(self):
        r = run_hook("lookup-check", pre("Read", {"file_path": "README.md"}, proj=self.proj), self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = run_hook("lookup-check", pre("Bash", {"command": "ls"}, proj=self.proj), self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(lk.db_path(self.p4)))    # no model: a command is not looked at either

    def test_a_failure_keeps_its_signature_and_the_command_that_worked_next(self):
        bad = {"command": "python tools/probe.py --port narwhal"}
        err = "Exit code 1\nTraceback (most recent call last):\n  File \"tools/probe.py\", line 3\n" \
              "ModuleNotFoundError: No module named 'numpy'"
        self.out(run_hook("lookup-record", post("Bash", bad, err, S1, self.proj, "t1", "PostToolUseFailure"), self.proj))
        self.out(run_hook("lookup-record", post("Bash", {"command": ".venv/Scripts/python tools/probe.py --port narwhal"},
                                                {"stdout": "ok"}, S1, self.proj, "t2"), self.proj))
        got = self.rows("ok=0")
        self.assertEqual(len(got), 1)
        self.assertIn("numpy", got[0]["sig"])
        self.assertIn(".venv/Scripts/python", got[0]["fix"])

    def test_the_same_failure_in_another_session_is_answered_after_the_call(self):
        err = "Exit code 1\nModuleNotFoundError: No module named 'numpy'"
        first = self.out(run_hook("lookup-record", post("Bash", {"command": "python tools/probe.py"}, err, S1,
                                                        self.proj, "t1", "PostToolUseFailure"), self.proj))
        self.assertIsNone(first)             # the first session to meet it has no earlier one to learn from
        self.out(run_hook("lookup-record", post("Bash", {"command": ".venv/Scripts/python tools/probe.py"},
                                                {"stdout": "ok"}, S1, self.proj, "t2"), self.proj))
        o = self.out(run_hook("lookup-record", post("Bash", {"command": "python other/thing.py"}, err, S2, self.proj,
                                                    "t9", "PostToolUseFailure"), self.proj))
        ctx = o["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(o["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure")
        self.assertIn("numpy", ctx)
        self.assertIn(".venv/Scripts/python tools/probe.py", ctx)


class Check(Base):
    def test_the_same_question_is_answered_once_then_runs(self):
        self.record_fetch()
        o = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK + " exactly"}, proj=self.proj),
                              self.proj))
        hso = o["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("30 seconds", hso["permissionDecisionReason"])
        self.assertIn("again", hso["permissionDecisionReason"])
        again = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK + " exactly"},
                                                      proj=self.proj), self.proj))
        self.assertIsNone(again)
        self.assertEqual(self.checks(), ["answer", "again"])

    def test_two_earlier_answers_to_the_question_are_both_shown(self):
        self.record_fetch("t1", found="The page was cut off before the timeout section; nothing about the default "
                          "value of the narwhal port timeout was in the part received, only the heading of it.")
        self.record_fetch("t2", ask=ASK + ", reading on from the cut")
        hso = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj),
                                self.proj))["hookSpecificOutput"]
        self.assertIn("cut off", hso["permissionDecisionReason"])
        self.assertIn("30 seconds", hso["permissionDecisionReason"])

    def test_another_question_about_the_page_runs(self):
        self.record_fetch()
        o = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": "List the kelp anchor mooring "
                                                                "options and their licences"}, proj=self.proj), self.proj))
        self.assertIsNone(o)
        self.assertEqual(self.checks(), ["silent"])

    def test_an_old_finding_is_left_alone(self):
        self.record_fetch()
        self.conf(max_age_days=0)
        con = sqlite3.connect(lk.db_path(self.p4))
        con.execute("UPDATE calls SET time='2020-01-01 10:00'")
        con.commit()
        con.close()
        o = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj), self.proj))
        self.assertIsNone(o)

    def test_modes(self):
        self.record_fetch()
        p = pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj)
        self.conf(web="note")
        hso = self.out(run_hook("lookup-check", p, self.proj))["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)
        self.assertIn("30 seconds", hso["additionalContext"])
        self.conf(web="shadow")
        self.assertIsNone(self.out(run_hook("lookup-check", p, self.proj)))
        self.conf(on=False)
        self.assertIsNone(self.out(run_hook("lookup-check", p, self.proj)))
        self.assertEqual(self.checks(), ["note", "shadow"])           # off: not even logged

    def test_a_search_like_an_earlier_one_is_answered(self):
        self.out(run_hook("lookup-record", post("WebSearch", {"query": "narwhal port timeout default NARWHAL_TIMEOUT"},
                                                {"query": "x", "results": [{"content": [{"title": "Narwhal ports",
                                                 "url": URL}]}, FOUND]}, S1, self.proj, "t1"), self.proj))
        o = self.out(run_hook("lookup-check", pre("WebSearch", {"query": "NARWHAL_TIMEOUT narwhal port default timeout"},
                                                  proj=self.proj), self.proj))
        self.assertEqual(o["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_other_tools_are_never_stopped(self):
        self.record_fetch()
        for tool, inp in (("Read", {"file_path": "README.md"}), ("Edit", {"file_path": "a", "old_string": "x",
                          "new_string": "y"}), ("Bash", {"command": "ls"}), ("Agent", {"prompt": "find the port"})):
            self.assertIsNone(self.out(run_hook("lookup-check", pre(tool, inp, proj=self.proj), self.proj)))
        self.assertEqual(self.checks(), [])                   # the runner ends these before python: nothing to log

    def test_a_corrupt_database_never_fails_a_call(self):
        self.record_fetch()
        with open(lk.db_path(self.p4), "wb") as f:
            f.write(b"not a database")
        r = run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj), self.proj)
        self.assertEqual(r.returncode, 0)
        r = run_hook("lookup-record", post("Bash", {"command": "ls"}, {"stdout": "x"}, S1, self.proj, "t5"), self.proj)
        self.assertEqual(r.returncode, 0)


class Backfill(Base):
    def test_each_tool_use_id_is_taken_once(self):
        d = os.path.join(self.tmp.name, "tr")
        calls = [("WebFetch", {"url": URL, "prompt": ASK}, FOUND), ("Bash", {"command": "ls src"}, "narwhal_port.py")]
        transcript(os.path.join(d, "one.jsonl"), "look up the port", calls, "done", self.proj)
        transcript(os.path.join(d, "copy.jsonl"), "look up the port", calls, "done", self.proj)   # a resumed session
        n = lk.backfill(self.p4, [d])
        self.assertEqual(n, 2)
        self.assertEqual(lk.backfill(self.p4, [d]), 0)
        self.assertEqual([r["tool"] for r in self.rows()], ["WebFetch", "Bash"])


class Train(Base):
    def test_a_round_reports_both_roads_and_keeps_the_matcher_unless_beaten(self):
        con = lk.connect(self.p4)
        n = 0
        for s in range(12):                                   # twelve sessions asking about four pages
            for page in range(4):
                n += 1
                same = page % 2 == 0                          # two pages are asked the same question every time
                ask = f"Quote the default timeout of the narwhal port {page}" if same else \
                    f"Describe topic {s} number {n} of zebrafish plotter {page} " + "kelp " * (s % 3)
                found = f"Port {page} times out after {30 + page} seconds by default, per the page." if same else \
                    f"Unrelated text {n} about topic {s} " + f"word{n} " * 12
                lk.insert(con, {"id": f"t{n}", "time": f"2026-11-{1 + s:02d} 10:{page:02d}", "session": f"s{s}",
                                "agent": "", "tool": "WebFetch", "inp": {"url": f"{URL}/{page}", "prompt": ask},
                                "ok": True, "text": found})
        con.commit()
        con.close()
        r = lk.train(self.p4, folds=3)
        self.assertGreater(r["calls"], 30)
        self.assertIn("matcher", r)
        self.assertIn("model", r)
        # the fixture's other questions read alike and found different things: the questions alone cannot tell,
        # what was found can, so the model answers at a precision the matcher never reaches
        self.assertGreaterEqual(r["model"]["precision"], 0.9)
        self.assertGreater(r["model"]["answered"], r["matcher"]["answered"])
        self.assertTrue(r["promoted"])
        self.assertEqual(os.path.exists(lk.model_path(self.p4)), r["written"])


class Peer(Base):
    def test_another_sessions_message_is_a_row_that_is_not_the_owners(self):
        import rows
        import store as st
        msg = "<cross-session-message from='local_1' from-name='btw'> Scope correction from the user: all tools.</cross-session-message>"
        rows.row_open(self.p4, S1, msg, "2026-11-11 08:19")
        path = rows.session_file(self.p4, S1)
        e = st.parse(st.read_text(path), "messages/x.md")[-1]
        self.assertEqual(e.fields["arrival"], "agent message")
        self.assertFalse(st.owner_message(e))
        self.assertFalse(st.completed(e))                     # answered at the turn's close, like a turn
        row, done = rows.row_close(self.p4, S1, "Took the correction: the hooks cover every tool.", "2026-11-11 08:25")
        self.assertTrue(done)
        e = st.parse(st.read_text(path), "messages/x.md")[-1]
        self.assertIn("Took the correction", e.fields["addressed"])


class HooksJson(unittest.TestCase):
    def test_matchers(self):
        import test_hooks
        h = test_hooks.own_hooks(HOOKS_JSON, "/hooks/recall-hook.sh")
        self.assertEqual([m["matcher"] for m in h["PreToolUse"]], ["Agent", ".*"])
        self.assertEqual(h["PreToolUse"][1]["hooks"][0]["command"].split()[-1], "lookup-check")
        for ev in ("PostToolUse", "PostToolUseFailure"):
            self.assertEqual(h[ev][0]["matcher"], ".*")
            self.assertEqual(h[ev][0]["hooks"][0]["command"].split()[-1], "lookup-record")
            self.assertEqual(h[ev][0]["hooks"][0]["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
