#!/usr/bin/env python3
"""lookups.py: every tool call is recorded, and a call is checked against what earlier calls found before it runs.

    python3 -I lbiza/plugins/p4-phi/scripts/test_lookups.py

Checked: a call's key, kind and error signature; one row per tool_use id; a clean call's row written behind the call;
the calls recall-hook.sh ends before python starts; a web finding handed back in place of the same question as a
PreToolUse deny, once, so the same call made again runs; a different question about the same page left alone, and so
the same question about another part of the page or a search of other domains or in another mode; an old finding
left alone; a failed command's signature recognised when it fails again in another session, with the
command that worked after it; the modes "answer", "note" and "shadow", and `on` false, which logs nothing; a corrupt
database never failing a call; the backfill from transcripts taking each tool_use id once; a training round
promoting the fitted model when it answers more held-out calls than the matcher, and keeping the matcher when it does
not, each as a check then reads it; another session's message kept as a row that is not ezexe's; hooks.json's
matchers.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
os.environ["P4_PHI"] = "0"          # phi.py's routed checks stay out of these tests: they touch no live store

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
        data[p4conf.WRITTEN] = {}                   # every value here is the test's own, as if set by hand
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

    def test_tools_with_nothing_to_check_never_start_python(self):
        r = run_hook("lookup-check", pre("Read", {"file_path": "README.md"}, proj=self.proj), self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = run_hook("lookup-check", pre("Bash", {"command": "ls"}, proj=self.proj), self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(lk.db_path(self.p4)))    # no failure model: a command ends before python too

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


class NewDatabase(Base):
    def test_the_file_never_exists_without_its_table(self):
        """L-1: another process reading lookups.db while the first call makes it never finds the file without the
        `calls` table: at the moment the schema is applied, a second connection reads the real path."""
        import types
        failed = []
        real = sqlite3

        class Probe(real.Connection):
            def executescript(self, script):
                path = lk.db_path(self.p4)
                if os.path.exists(path):
                    other = real.connect(path)
                    try:
                        other.execute("SELECT count(*) FROM calls").fetchone()
                    except real.OperationalError as e:
                        failed.append(str(e))
                    finally:
                        other.close()
                return super().executescript(script)

        Probe.p4 = self.p4
        shim = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith("__")})
        shim.connect = lambda *a, **k: real.connect(*a, factory=Probe, **k)
        kept = lk.sqlite3
        lk.sqlite3 = shim
        try:
            lk.connect(self.p4).close()
        finally:
            lk.sqlite3 = kept
        self.assertEqual(failed, [], "the file was there before its table")
        self.assertEqual(self.rows(), [], "and the table is there now")


class AfterOnce(Base):
    def test_a_session_is_told_of_an_error_once(self):
        """B1-72: what earlier sessions did about an error is told to a session once; the same error met again in
        that session adds nothing, and another session is told in its turn."""
        err = "Exit code 1\nModuleNotFoundError: No module named 'numpy'"
        self.out(run_hook("lookup-record", post("Bash", {"command": "python tools/probe.py"}, err, S1, self.proj, "t1",
                                                "PostToolUseFailure"), self.proj))
        S3 = "cccc3333-0000-4000-8000-000000000000"
        got = []
        for session, tid in ((S2, "t2"), (S2, "t3"), (S3, "t4")):
            o = self.out(run_hook("lookup-record", post("Bash", {"command": "python other/thing.py"}, err, session,
                                                        self.proj, tid, "PostToolUseFailure"), self.proj))
            got.append(bool(o))
        self.assertEqual(got, [True, False, True])


class Default(Base):
    def test_a_web_call_runs_with_the_earlier_finding_beside_it_by_default(self):
        """ezexe/p4#243, row D1: with no lookups setting written, the call runs and the stored finding is context."""
        self.record_fetch()
        hso = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj),
                                self.proj))["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)
        self.assertIn("30 seconds", hso["additionalContext"])
        self.assertEqual(self.checks(), ["note"])


class Check(Base):
    """The "answer" mode, which a project sets: an earlier finding in place of the call, once."""

    def setUp(self):
        super().setUp()
        self.conf(web="answer")

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
        self.assertEqual(self.checks(), ["note", "shadow"])           # on false: not even logged

    def test_a_search_like_an_earlier_one_is_answered(self):
        self.out(run_hook("lookup-record", post("WebSearch", {"query": "narwhal port timeout default NARWHAL_TIMEOUT"},
                                                {"query": "x", "results": [{"content": [{"title": "Narwhal ports",
                                                 "url": URL}]}, FOUND]}, S1, self.proj, "t1"), self.proj))
        o = self.out(run_hook("lookup-check", pre("WebSearch", {"query": "NARWHAL_TIMEOUT narwhal port default timeout"},
                                                  proj=self.proj), self.proj))
        self.assertEqual(o["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_fetch_of_another_part_of_the_page_runs(self):
        self.record_fetch()
        far = {"url": URL, "prompt": ASK, "offset": 100000}
        self.assertIsNone(self.out(run_hook("lookup-check", pre("WebFetch", far, proj=self.proj), self.proj)),
                          "the first part's finding says nothing of the part from character 100000")
        part = ("From character 100000 the page lists the narwhal port's retry budget: five retries, then the port "
                "closes until NARWHAL_RETRY_RESET seconds have passed.")
        self.out(run_hook("lookup-record", post("WebFetch", far, {"result": part, "url": URL, "code": 200}, S1,
                                                self.proj, "t2"), self.proj))
        why = self.out(run_hook("lookup-check", pre("WebFetch", far, proj=self.proj, tid="t-far"), self.proj)
                       )["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("five retries", why)
        self.assertNotIn("30 seconds", why)
        start = {"url": URL, "prompt": ASK, "offset": 0}
        why = self.out(run_hook("lookup-check", pre("WebFetch", start, proj=self.proj, tid="t-start"), self.proj)
                       )["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("30 seconds", why, "offset 0 reads from the page's start, as a fetch without one")
        self.assertNotIn("five retries", why)

    def test_a_search_of_other_domains_or_in_another_mode_runs(self):
        q, again = "narwhal port timeout default NARWHAL_TIMEOUT", "NARWHAL_TIMEOUT narwhal port default timeout"

        def search(inp, tid, found):
            self.out(run_hook("lookup-record", post("WebSearch", inp, {"query": inp["query"], "results": [
                {"content": [{"title": "Narwhal ports", "url": URL}]}, found]}, S1, self.proj, tid), self.proj))

        def check(**scope):
            return self.out(run_hook("lookup-check", pre("WebSearch", {"query": again, **scope}, proj=self.proj),
                                     self.proj))

        search({"query": q, "mode": "standard"}, "t1", FOUND)
        self.assertIsNone(check(mode="extended"), "an extended search is asked for when a standard one fell short")
        self.assertIsNone(check(mode="standard", allowed_domains=["docs.example.org"]))
        self.assertIsNone(check(mode="standard", blocked_domains=["example.org"]))
        self.assertEqual(check(mode="standard")["hookSpecificOutput"]["permissionDecision"], "deny")
        narrow = ("Only docs.example.org and b.example.org were searched: the narwhal port page there gives 45 seconds "
                  "for the port timeout on the managed service.")
        search({"query": q, "mode": "extended", "allowed_domains": ["Docs.Example.org", "b.example.org"]}, "t2", narrow)
        why = check(mode="extended", allowed_domains=["b.example.org", "docs.example.org"]
                    )["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("45 seconds", why, "the same domains in another order and case, in the same mode")
        self.assertNotIn("30 seconds", why)

    def test_a_page_with_a_long_address_is_answered_and_kept_apart(self):
        """A page address longer than the 400 characters a stored target holds is answered by an earlier finding for
        it, and never by one for another long address that shares its first 400 characters."""
        long_url = URL + "/" + "a" * 430
        other = URL + "/" + "a" * 430 + "/other"
        self.record_fetch(url=long_url)
        hso = self.out(run_hook("lookup-check", pre("WebFetch", {"url": long_url, "prompt": ASK}, proj=self.proj),
                                self.proj))["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("30 seconds", hso["permissionDecisionReason"])
        self.assertIsNone(self.out(run_hook("lookup-check", pre("WebFetch", {"url": other, "prompt": ASK},
                                                                proj=self.proj, tid="t-other"), self.proj)))

    def test_other_tools_are_never_stopped(self):
        self.record_fetch()
        for tool, inp in (("Read", {"file_path": "README.md"}), ("Edit", {"file_path": "a", "old_string": "x",
                          "new_string": "y"}), ("Bash", {"command": "ls"}), ("Agent", {"prompt": "find the port"})):
            self.assertIsNone(self.out(run_hook("lookup-check", pre(tool, inp, proj=self.proj), self.proj)))
        self.assertEqual(self.checks(), [])                   # recall-hook.sh ends these before python: nothing to log

    def test_a_corrupt_database_never_fails_a_call(self):
        self.record_fetch()
        with open(lk.db_path(self.p4), "wb") as f:
            f.write(b"not a database")
        r = run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj), self.proj)
        self.assertEqual(r.returncode, 0)
        r = run_hook("lookup-record", post("Bash", {"command": "ls"}, {"stdout": "x"}, S1, self.proj, "t5"), self.proj)
        self.assertEqual(r.returncode, 0)


class Lines(Base):
    def test_every_lookup_line_is_the_plugins_own(self):
        """A line lookups.py hands a session opens as p4-phi's lines do, so a report that quotes one has it taken out
        by plans.own_removed, as any line of the plugin's."""
        import plans
        self.record_fetch()
        web = self.out(run_hook("lookup-check", pre("WebFetch", {"url": URL, "prompt": ASK}, proj=self.proj),
                                self.proj))["hookSpecificOutput"]["additionalContext"]
        err = "Exit code 1\nModuleNotFoundError: No module named 'numpy'"
        self.out(run_hook("lookup-record", post("Bash", {"command": "python tools/probe.py"}, err, S1, self.proj, "t2",
                                                "PostToolUseFailure"), self.proj))
        after = self.out(run_hook("lookup-record", post("Bash", {"command": "python other/thing.py"}, err, S2,
                                                        self.proj, "t3", "PostToolUseFailure"), self.proj))
        shell = lk.shell_text({"time": "2026-11-01 10:00", "sig": "ModuleNotFoundError: No module named 'numpy'",
                               "ask": "python tools/probe.py", "fix": ""})
        for text in (web, after["hookSpecificOutput"]["additionalContext"], shell):
            first = text.splitlines()[0]
            self.assertTrue(plans.OWN_LINE.match(first), first)
            self.assertNotIn(first[-40:], plans.own_removed(f"Fixed the port.\n> {first}\nThe tests pass."))


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
    def threshold_used(self, prompt, page):
        """The threshold a check of a fetch of page `page` scores at, as web_match reads the model file."""
        con = lk.connect(self.p4)
        try:
            return lk.web_match(con, self.p4, "WebFetch", {"url": f"{URL}/{page}", "prompt": prompt},
                                "2026-11-14 10:00")[2]
        finally:
            con.close()

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
        web = lk.load_model(self.p4)["web"]
        self.assertTrue(web["promoted"] and web["w"], "a check scores with the fitted weights")
        self.assertEqual(self.threshold_used("Quote the default timeout of the narwhal port 0", 0), web["threshold"],
                         "at the model's own threshold")

    def test_a_round_the_matcher_wins_keeps_the_matcher(self):
        con = lk.connect(self.p4)
        n = 0
        for s in range(12):                                   # every page asked one question, found one answer
            for page in range(4):
                n += 1
                lk.insert(con, {"id": f"t{n}", "time": f"2026-11-{1 + s:02d} 10:{page:02d}", "session": f"s{s}",
                                "agent": "", "tool": "WebFetch",
                                "inp": {"url": f"{URL}/{page}", "prompt": f"Quote the default timeout of port {page}"},
                                "ok": True, "text": f"Port {page} times out after {30 + page} seconds by default."})
        con.commit()
        con.close()
        r = lk.train(self.p4, folds=3)
        self.assertEqual(r["model"]["answered"], r["matcher"]["answered"], "the questions alone tell every time")
        self.assertFalse(r["promoted"])
        web = lk.load_model(self.p4)["web"]
        self.assertFalse(web["promoted"], "the file keeps the weights, unpromoted")
        self.assertEqual(self.threshold_used("Quote the default timeout of port 0", 0), web["matcher_threshold"],
                         "a check uses the matcher at its trained threshold")


class Peer(Base):
    def test_another_sessions_message_is_a_row_that_is_not_the_owners(self):
        import rows
        import store as st
        msg = "<cross-session-message from='local_1' from-name='btw'> Scope correction from ezexe: all tools.</cross-session-message>"
        rows.row_open(self.p4, S1, msg, "2026-11-11 08:19")
        path = rows.session_file(self.p4, S1)
        e = st.parse(st.read_text(path), "messages/x.md")[-1]
        self.assertEqual(e.fields["arrival"], "agent message")
        self.assertFalse(st.owner_message(e))
        self.assertFalse(st.completed(e))                     # answered at the turn end, like a turn
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
        # ezexe/p4#150: a clean call's row is written by an entry the app runs in the background
        self.assertEqual([(x["command"].split()[-1], x.get("async")) for x in h["PostToolUse"][0]["hooks"]],
                         [("lookup-record", None), ("lookup-record-async", True)])

    def test_only_the_lookup_row_goes_to_the_background(self):
        """The entry the call waits on keeps phi.py's records of a clean call that a later check reads, and the async
        entry writes only the lookup row: a stand-in hook.py names the handler each entry reaches."""
        import shutil
        import subprocess
        import tempfile
        real = os.path.dirname(os.path.dirname(os.path.abspath(HOOKS_JSON)))
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "p4-phi")
            shutil.copytree(os.path.join(real, "hooks"), os.path.join(root, "hooks"))
            os.makedirs(os.path.join(root, "scripts"))
            log = os.path.join(tmp, "ran.txt")
            with open(os.path.join(root, "scripts", "hook.py"), "w", encoding="utf-8") as f:
                f.write("import sys\nopen(%r, 'a').write(sys.argv[1] + '\\n')\n" % log)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("P4_", "CLAUDE_"))}
            env.update({"CLAUDE_PLUGIN_ROOT": root, "CLAUDE_PROJECT_DIR": tmp})
            runner = os.path.join(root, "hooks", "recall-hook.sh")

            def ran(name, tool, body):
                if os.path.exists(log):
                    os.remove(log)
                subprocess.run(["sh", runner, name], input=json.dumps({"tool_name": tool, **body}), text=True,
                               capture_output=True, env=env)
                return __import__("pathlib").Path(log).read_text().split() if os.path.exists(log) else []
            clean = {"hook_event_name": "PostToolUse", "tool_response": {"stdout": "a.txt"}}
            self.assertEqual(ran("lookup-record", "Read", clean), [], "a clean read: nothing waits")
            self.assertEqual(ran("lookup-record", "Bash", clean), [], "a clean shell call: p4-phi keeps no record")
            self.assertEqual(ran("lookup-record", "Write", clean), ["lookup-phi"], "phi's memory-gap check waits")
            self.assertEqual(ran("lookup-record", "TaskStop", clean), ["lookup-phi"], "a stop ends a saved entry")
            self.assertEqual(ran("lookup-record", "Read", dict(clean, agent_id="a1")), [],
                             "a subagent's clean read: nothing waits, since its id is bound at its SubagentStart")
            self.assertEqual(ran("lookup-record-async", "Bash", clean), ["lookup-row"], "the row alone, behind")
            failed = {"hook_event_name": "PostToolUseFailure", "error": "Exit code 1"}
            self.assertEqual(ran("lookup-record", "Bash", failed), ["lookup-record"], "a failure is answered whole")
            self.assertEqual(ran("lookup-record-async", "Bash", failed), [])

    def test_a_clean_call_waits_on_nothing_and_its_row_is_written_in_the_background(self):
        """ezexe/p4#150: the entry the call waits on ends at once for a clean call and writes no row; the async entry
        writes it, and a failure is still answered by the entry the call waits on."""
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proj = make_project(tmp)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("P4_", "CLAUDE_"))}
            env.update({"CLAUDE_PLUGIN_ROOT": os.path.dirname(os.path.dirname(os.path.abspath(HOOKS_JSON))), "CLAUDE_PROJECT_DIR": proj})
            runner = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(HOOKS_JSON))), "hooks", "recall-hook.sh")
            clean = json.dumps(post("Read", {"file_path": "README.md"}, "a clean read", S1, proj, "t9"))

            def rows():
                db = lk.db_path(os.path.join(proj, ".claude", "p4"))
                if not os.path.exists(db):
                    return 0
                con = sqlite3.connect(db)
                try:
                    return con.execute("SELECT count(*) FROM calls").fetchone()[0]
                finally:
                    con.close()
            r = subprocess.run(["sh", runner, "lookup-record"], input=clean, capture_output=True, text=True, env=env)
            self.assertEqual((r.returncode, r.stdout), (0, ""))
            self.assertEqual(rows(), 0, "the entry the call waits on writes no row for a clean call")
            r = subprocess.run(["sh", runner, "lookup-record-async"], input=clean, capture_output=True, text=True,
                               env=env)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(rows(), 1, "the async entry writes it")
            failed = json.dumps(post("Bash", {"command": "python x.py"}, "Exit code 1\nTraceback: boom", S1, proj,
                                     "t10", "PostToolUseFailure"))
            subprocess.run(["sh", runner, "lookup-record-async"], input=failed, capture_output=True, text=True,
                           env=env)
            self.assertEqual(rows(), 1, "the async entry leaves a failure to the entry the call waits on")


if __name__ == "__main__":
    unittest.main()
