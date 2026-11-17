#!/usr/bin/env python3
"""starts.py: start requests kept in the store, run through phi.py's hooks.

    python3 -I lbiza/plugins/p4-phi/scripts/test_starts.py

The tree: two orchestrators and a child of the first. The child's turn is started by its parent's message, so
the app would refuse it `user_asked`: it is told to show a suggested task card first and to file a start request only
if the card is refused too, and it files one. No other session is handed the request. At the next turn ezexe begins
in the child, the child is handed the request with its exact call; its start_session call claims it; the session that
call starts arrives with the marker and is recorded as the child's own child, so its reports and its archive line go
there. Overlapping write sets hold a start, a withdrawn request is handed to no session, and a request is dropped
after a day.
"""

import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
from test_phi import CLI, KID, KID2, TOP, Tree, context  # noqa: E402

TOP2, NEW = "local_top00002", "local_new00001"
CLI.setdefault(TOP2, "eeee6666-0000-4000-8000-000000000000")
CLI.setdefault(NEW, "ffff7777-0000-4000-8000-000000000000")
BRIEF = ("Port the exporter's flush to the new writer and run its suite. This session is marked archive when done."
         "\nFiles: src/flush.py")
CROSS = "<cross-session-message from=\"local_top00001\">Carry on with the port and split off the docs.</cross-session-message>"


class StartRequests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="the exporter top")
        t.record(TOP2, title="the docs top")
        t.record(KID, TOP, title="the port orchestrator")
        t.say(TOP, "Build the exporter")
        t.say(TOP2, "Write the docs")
        t.say(KID, "Port the exporter in pieces")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_turn_ezexe_did_not_begin_is_told_to_show_a_card_and_a_request_only_if_that_is_refused(self):
        """A turn ezexe did not begin is told to show the child as a card, pressed in this session so the app's parent
        and p4-phi's agree, and to file a request only if the card is refused too."""
        self.t.say(KID, CROSS, P4_PHI_NEW_TASK="1")       # the standing instruction first, once
        ctx = context(self.t.say(KID, CROSS, P4_PHI_NEW_TASK="1"))
        self.assertIn("`initiation` `own_initiative`, which ezexe presses in this session", ctx)
        self.assertIn("Only where the card is refused too", ctx)
        self.assertIn(" request \"<title>\" --brief", ctx)
        self.assertIn("the next turn ezexe begins in this session starts it", ctx)
        self.assertNotIn("any session of this store", ctx)

    def test_a_request_is_started_at_ezexes_next_turn_in_the_session_that_filed_it(self):
        t = self.t
        r = t.cli(KID, "request", "the flush port", "--brief", BRIEF)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kept as start request req-", r.stdout)
        self.assertIn("No other session is handed it", r.stdout)
        self.assertIn("was already kept", t.cli(KID, "request", "the flush port", "--brief", BRIEF).stdout)
        self.assertEqual(context(t.say(KID, CROSS)).count("start requests this session filed"), 0,
                         "a turn another session began carries no request")
        self.assertNotIn("start requests", context(t.say(TOP2, "How are the docs coming?")),
                         "a request filed by one session is not handed to another on ezexe's next turn there")
        self.assertNotIn("start requests", context(t.say(TOP, "and the exporter?")), "nor to its own parent")
        line = context(t.say(KID, "How is the port coming?"))
        self.assertIn("start requests this session filed in turns ezexe did not begin", line)
        self.assertIn("Each is this session's own child", line)
        call = json.loads(line.split("`mcp__ccd_session__start_session` with ", 1)[1].split("\n", 1)[0])
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", False))
        self.assertIn(BRIEF, call["prompt"])
        self.assertGreaterEqual(len(call["background"]), 80, "the app refuses a shorter background")
        self.assertIn(KID, call["background"], "built from the session that filed it")
        self.assertIn(f"for {KID}.", call["prompt"])
        adv = t.hook("start-advice", KID, {"hook_event_name": "PreToolUse",
                                           "tool_name": "mcp__ccd_session__start_session", "tool_input": call})
        self.assertEqual(adv.stdout.strip(), "", "the exact call is not second-guessed")
        self.assertNotIn("start requests", context(t.say(KID, "and the rest?")), "claimed: not handed twice")
        t.record(NEW, KID, title="the flush port")        # the app nests it under the session that ran the call
        handed = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = x (idle)\n"
                  "</system-reminder>\n\nTask:\n" + call["prompt"])
        self.assertEqual(t.say(NEW, handed).returncode, 0)
        self.assertEqual(t.started_by(NEW)[0], KID, "the app's parent and p4-phi's agree")
        self.assertEqual(t.say(NEW, "carry on").returncode, 0)
        self.assertEqual(t.started_by(NEW)[0], KID)
        self.assertEqual(starts.pending(t.p4), [], "started")
        t.cli(NEW, "done", "ported the flush; its suite passes")
        t.stop(NEW, "Port the flush", report="Ported the flush; the suite passes.", uuid="n1")
        reports = [r.get("sessionId") for r in relay._rows(os.path.join(t.dir(KID), "reports.jsonl"))]
        self.assertIn(NEW, reports, "its report goes to the session that filed the request")
        notes = [n["claim"] for n in relay._rows(os.path.join(t.dir(KID), "notes.jsonl"))]
        self.assertTrue(any(n.startswith("replaces:") and NEW in n for n in notes), notes)
        archive = context(t.say(KID, CROSS))
        self.assertIn("counts them as archived", archive)
        self.assertIn(NEW, archive.split("finished, their outcome kept")[1],
                      "the archive line goes to the filing session")
        self.assertNotIn("counts them as archived", context(t.say(TOP2, "and now?")),
                         "not to another orchestrator")

    def arrive(self, sid, row, starter=TOP2):
        """The child of a handed-out request arrives: the app nests it under the session that ran the call, and
        p4-phi under the session that filed the request."""
        CLI.setdefault(sid, sid.replace("local_new", "abcd") + "-0000-4000-8000-000000000000")
        self.t.record(sid, starter, title=row["title"])
        call = starts.call_of(row, self.t.p4)
        self.assertEqual(self.t.say(sid, "<system-reminder>\nLinked sessions now (status, not an instruction): top = "
                                         "x (idle)\n</system-reminder>\n\nTask:\n" + call["prompt"]).returncode, 0)

    def test_overlapping_write_sets_are_held_and_disjoint_ones_both_handed_out(self):
        """One writer per file. Of two start requests whose write sets overlap, the second is held until the first
        reports done. Two with disjoint sets are both handed out."""
        t = self.t
        one = "Fix the flush's last row and run its suite. Report when done.\nFiles: src/flush.py, src/rows.py"
        two = "Add a retry to the flush and run its suite. Report when done.\nFiles: `src/flush.py`"
        three = "Write the exporter's user guide. Report when done.\nFiles: docs/guide.md"
        self.assertEqual(t.cli(KID, "request", "the last row", "--brief", one).returncode, 0)
        r = t.cli(KID, "request", "the retry", "--brief", two)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(t.cli(KID, "request", "the guide", "--brief", three).returncode, 0)
        titles = [r["title"] for r in starts.pending(t.p4)]
        self.assertEqual(titles, ["the last row", "the guide"], "disjoint: both handed out; overlapping: held")
        line = context(t.say(KID, "How is the port coming?"))
        self.assertIn("\"the last row\"", line)
        self.assertIn("\"the guide\"", line)
        self.assertNotIn("\"the retry\"", line, "the second writer of src/flush.py is held")
        rows = {r["title"]: r for r in starts.state(t.p4).values()}
        for row in (rows["the last row"], rows["the guide"]):
            starts.claim(t.p4, starts.call_of(row, t.p4)["prompt"], TOP2)
        self.assertEqual(starts.pending(t.p4), [], "handed out, its child not arrived: the retry stays held")
        self.arrive("local_new00011", rows["the last row"])
        kid = t.session("local_new00011")
        self.assertEqual([f.rsplit("/", 2)[-2:] for f in kid["fileSet"]], [["src", "flush.py"], ["src", "rows.py"]])
        self.assertIn("src/flush.py", open(os.path.join(t.dir("local_new00011"), "session.json"),
                                           encoding="utf-8").read())
        self.assertEqual(starts.pending(t.p4), [], "its child is live and has not reported done")
        self.assertIn("is held until", t.cli(KID, "request", "the retry again", "--brief", two + " Again.").stdout)
        t.cli("local_new00011", "done", "fixed the last row; its suite passes")
        t.stop("local_new00011", "Fix the last row", report="Fixed the last row; the suite passes.", uuid="f1")
        self.assertIn("## Files", open(os.path.join(t.dir("local_new00011"), "session.md"), encoding="utf-8").read())
        self.assertEqual([r["title"] for r in starts.pending(t.p4)][:1], ["the retry"],
                         "the first reported done: the held start goes out")

    def test_a_brief_with_no_write_set_is_refused_with_what_to_add(self):
        """Every brief declares its write set."""
        t = self.t
        r = t.cli(KID, "request", "the flush port", "--brief", "Port the exporter's flush to the new writer.")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("add a line `Files: <each path this session may write", r.stderr)
        self.assertEqual(starts.pending(t.p4), [])
        self.assertEqual(t.cli(KID, "request", "the flush check", "--brief",
                               "Check what the exporter's flush does and report it.\nFiles: none").returncode, 0)
        call = {"initiation": "user_asked", "title": "the port", "context": "fresh", "use_worktree": False,
                "prompt": "Port the exporter's flush to the new writer. Report when done.",
                "background": "The exporter top holds the port; this child takes the flush alone. " * 2}
        adv = t.hook("start-advice", TOP, {"hook_event_name": "PreToolUse",
                                           "tool_name": "mcp__ccd_session__start_session", "tool_input": call})
        out = json.loads(adv.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("add a line `Files:", out["permissionDecisionReason"])
        call["prompt"] += "\nFiles: src/flush.py"
        adv = t.hook("start-advice", TOP, {"hook_event_name": "PreToolUse",
                                           "tool_name": "mcp__ccd_session__start_session", "tool_input": call})
        self.assertNotIn("deny", adv.stdout, "a declared write set that no live session holds starts")
        self.assertEqual(starts.files_of("Fix it.\n- **Files:** `lib/x.py`, lib/y.py and z.md.", "E:/w"),
                         [relay.norm("E:/w/lib/x.py"), relay.norm("E:/w/lib/y.py"), "z.md"])
        self.assertEqual(starts.files_of("Check it.\nFiles: none"), [])
        self.assertIsNone(starts.files_of("Fix the files in lib."))
        self.assertEqual(starts.files_overlap([relay.norm("E:/w/lib/x.py")], ["x.py"]), [relay.norm("E:/w/lib/x.py")])
        self.assertEqual(starts.files_overlap([relay.norm("E:/w/lib")], [relay.norm("E:/w/lib/x.py")]),
                         [relay.norm("E:/w/lib")])
        self.assertEqual(starts.files_overlap([relay.norm("E:/w/lib/x.py")], [relay.norm("E:/w/docs/x.md")]), [])

    def test_a_given_background_is_carried_and_a_short_one_made_long_enough(self):
        """The handed-out call carries a background of at least 80 characters, given or not."""
        t = self.t
        given = "The exporter's flush moved to the new writer in src/flush.py; the docs follow the same layout."
        self.assertEqual(t.cli(KID, "request", "the docs port", "--brief", BRIEF, "--background", given).returncode, 0)
        self.assertEqual(t.cli(KID, "request", "the short one", "--brief",
                               BRIEF.replace("src/flush.py", "docs/short.md"), "--background", "Short.").returncode, 0)
        calls = {r["title"]: starts.call_of(r, t.p4) for r in starts.pending(t.p4)}
        self.assertEqual(calls["the docs port"]["background"], given)
        self.assertTrue(calls["the short one"]["background"].startswith("Short."))
        self.assertGreaterEqual(len(calls["the short one"]["background"]), 80)
        old = {"id": "req-0000000000", "requester": KID, "title": "an old row", "brief": BRIEF}
        self.assertGreaterEqual(len(starts.call_of(old, t.p4)["background"]), 80, "a row with no background gets one")

    def test_a_stopped_or_archived_session_does_not_hold_its_write_set(self):
        """A session the app shows as stopped, or archived, holds no write set, so it holds no other start."""
        t = self.t
        CLI.setdefault("local_wrt00001", "abab0001-0000-4000-8000-000000000000")
        t.record("local_wrt00001", TOP, title="the flush writer")
        t.say("local_wrt00001", "Task:\nPort the flush. Report when done.\nFiles: src/flush.py")
        call = {"hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session",
                "tool_input": {"initiation": "user_asked", "title": "the flush again", "context": "fresh",
                               "use_worktree": False, "prompt": BRIEF}}
        held = t.hook("start-advice", TOP, call)
        self.assertIn("this start is held", held.stdout, "a live writer of src/flush.py holds it")
        rec = os.path.join(t.app, "local_wrt00001.json")
        row = json.load(open(rec, encoding="utf-8"))
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({**row, "lastTurnStopped": True}, f)
        self.assertNotIn("this start is held", t.hook("start-advice", TOP, call).stdout, "stopped: its files are free")
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({**row, "isArchived": True}, f)
        self.assertNotIn("this start is held", t.hook("start-advice", TOP, call).stdout, "archived: free as well")

    def test_a_write_set_narrowed_with_phi_files_frees_the_released_paths(self):
        """A session that narrows its write set with `phi.py files` frees the paths it released at once, and
        `--release` frees them all."""
        t = self.t
        w = "local_wrt00002"
        CLI.setdefault(w, "abab0002-0000-4000-8000-000000000000")
        t.record(w, TOP, title="the flush and docs writer")
        t.say(w, "Task:\nPort the flush and write its page. Report when done.\nFiles: src/flush.py, docs/flush.md")
        call = {"hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session",
                "tool_input": {"initiation": "user_asked", "title": "the flush again", "context": "fresh",
                               "use_worktree": False, "prompt": BRIEF}}
        self.assertIn("this start is held", t.hook("start-advice", TOP, call).stdout)
        r = t.cli(w, "files", "docs/flush.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("docs/flush.md", r.stdout)
        self.assertIn("released: ", r.stdout)
        self.assertIn("src/flush.py", r.stdout.split("released: ", 1)[1])
        self.assertNotIn("this start is held", t.hook("start-advice", TOP, call).stdout,
                         "the guard reads the narrowed set at once")
        s = t.session(w)
        self.assertEqual([f.rsplit("/", 1)[-1] for f in s["fileSet"]], ["flush.md"])
        self.assertEqual(len(s["fileSets"]), 1, "the set before it is recorded")
        self.assertEqual(len(s["fileSets"][0]["files"]), 2)
        docs = {**call, "tool_input": {**call["tool_input"], "prompt": BRIEF.replace("src/flush.py", "docs/flush.md")}}
        self.assertIn("this start is held", t.hook("start-advice", TOP, docs).stdout, "what it kept is still held")
        t.say(w, "carry on")                       # a hook that read the record before the command keeps the new set
        self.assertEqual(len(t.session(w)["fileSet"]), 1)
        r = t.cli(w, "files", "--release")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(t.session(w)["fileSet"], [])
        self.assertNotIn("this start is held", t.hook("start-advice", TOP, docs).stdout)
        self.assertIn("holds no file", t.cli(w, "files").stdout)
        self.assertEqual(t.cli(w, "files", "a.py", "--release").returncode, 2, "one or the other")

    def test_a_files_line_holds_only_the_paths_it_lists_to_write(self):
        """A `Files:` line holds only the paths it lists to write: a sentence after the list, a repository's root
        beside another path and an ancestor of a listed path are context."""
        base = self.t.proj
        os.makedirs(os.path.join(base, "p4", ".git"))
        root = relay.norm(os.path.join(base, "p4"))
        a = relay.norm("dox/a.html", base)
        got = starts.files_of("Write the page.\nFiles: `dox/a.html`. The live checkout is `" + root + "`, never "
                              "edit it.\nReport when done.", base)
        self.assertEqual(got, [a], "a sentence after the list names no file to write")
        got = starts.files_of("Files: dox/a.html, in the checkout `" + root + "`", base)
        self.assertEqual(got, [a], "a repository root beside another path is context")
        got = starts.files_of("Files: `p4/dox/a.html`, `p4/dox`, `p4`", base)
        self.assertEqual(got, [relay.norm("p4/dox/a.html", base)], "an ancestor of a listed path is not held")
        self.assertEqual(starts.files_of("Files: `" + root + "`", base), [root], "the only path on the line is held")
        self.assertEqual(starts.files_of("Files: src/a.py, src/b.py and README.md.", base),
                         [relay.norm("src/a.py", base), relay.norm("src/b.py", base), "readme.md"])
        self.assertEqual(starts.files_of("Files: none. The checkout is `" + root + "`.", base), [])
        self.assertIsNone(starts.files_of("The checkout is `" + root + "`.", base))

    def test_a_clause_on_a_files_line_holds_no_word_of_it(self):
        """A piece of a `Files:` list that is a clause of words names no file; a piece that is one name, backticked or
        plain, with at most a trailing parenthetical, is held."""
        base = self.t.proj
        os.makedirs(os.path.join(base, "p4", ".git"))
        root = relay.norm(os.path.join(base, "p4"))
        sj = relay.norm("E:/x/phi/sessions/*/session.json", base)
        st = relay.norm("lbiza/plugins/p4-phi/scripts/starts.py", base)
        self.assertEqual(starts.files_of("Files: `E:/x/phi/sessions/*/session.json`, its `cliSessionIds` field only.",
                                         base), [sj])
        self.assertEqual(starts.files_of("Files: `lbiza/plugins/p4-phi/scripts/starts.py`, the tests only.", base),
                         [st])
        self.assertEqual(starts.files_of("Files: `lbiza/plugins/p4-phi/scripts/starts.py` and nothing else.", base),
                         [st])
        self.assertEqual(starts.files_of("Files: `" + root + "`, the whole checkout.", base), [root])
        self.assertEqual(starts.files_of("Files: `lbiza/plugins/p4-phi/scripts/starts.py`, `test_starts.py` (new).",
                                         base), [st, "test_starts.py"])
        self.assertEqual(starts.files_of("Files: Makefile, `README`", base), ["makefile", "readme"])
        self.assertEqual(starts.files_of("Files: none, this session changes no file.", base), [])

    def test_a_bare_name_belongs_to_the_session_s_own_repository(self):
        """A bare name or relative path on a Files line is resolved in the repository the session writes in, so two
        sessions that name README.md in two repositories do not hold one file; in one repository they do."""
        base = self.t.proj
        a, b = os.path.join(base, "p4"), os.path.join(base, "phi")
        for r in (a, b):
            os.makedirs(os.path.join(r, ".git"))
        in_a, in_b = starts.files_of("Files: README.md", a), starts.files_of("Files: README.md", b)
        self.assertEqual(in_a, [relay.norm("README.md", a)])
        self.assertEqual(starts.files_overlap(in_a, in_b), [], "the same name in two repositories")
        self.assertEqual(starts.files_overlap(in_a, starts.files_of("Files: `README.md`", a)), in_a)
        sub = os.path.join(a, "docs")
        os.makedirs(sub)
        self.assertEqual(starts.files_of("Files: dox/x.html", sub), [relay.norm("dox/x.html", a)],
                         "a relative path is read from the repository's root")

    def test_a_session_whose_closing_commit_is_pushed_is_told_what_it_still_holds(self):
        """Once its closing commit is on a remote branch, a session is told once what it still holds, with the
        command that releases it."""
        t = self.t
        w = "local_wrt00003"
        CLI.setdefault(w, "abab0003-0000-4000-8000-000000000000")
        t.record(w, TOP, title="the flush writer")
        t.say(w, "Task:\nPort the flush. Report when done.\nFiles: src/flush.py")
        s = t.session(w)
        closing = [(t.proj, "abc1234", "port the flush", ["7"])]
        self.assertEqual(phi.files_held_text(t.p4, s, closing, pushed=lambda repo, sha: False), "", "not pushed yet")
        line = phi.files_held_text(t.p4, s, closing, pushed=lambda repo, sha: True)
        self.assertIn("commit abc1234, which closes #7, is on a remote branch", line)
        self.assertIn("src/flush.py", line)
        self.assertIn(" files --release`", line)
        self.assertIn(" files <path> ...`", line)
        self.assertEqual(phi.files_held_text(t.p4, s, closing, pushed=lambda repo, sha: True), "", "said once")
        s["fileSet"] = []
        s.pop("filesHeldTold")
        self.assertEqual(phi.files_held_text(t.p4, s, closing, pushed=lambda repo, sha: True), "", "holds nothing")

    def test_a_withdrawn_request_is_not_handed_out(self):
        """A withdrawn request is handed to no session, its row stays with who withdrew it, and the same request can
        be filed again."""
        t = self.t
        t.say(KID, CROSS)
        r = t.cli(KID, "request", "the port's flush", "--brief", BRIEF)
        self.assertEqual(r.returncode, 0, r.stderr)
        rid = starts.pending(t.p4)[0]["id"]
        keep, _ = starts.add(t.p4, KID, "the port's docs", BRIEF.replace("src/flush.py", "docs/flush.md"))
        r = t.cli(TOP, "request", "--withdraw", rid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"withdrawn: start request {rid} \"the port's flush\"", r.stdout)
        self.assertEqual([x["id"] for x in starts.pending(t.p4)], [keep], "pending leaves it out")
        self.assertEqual([x["id"] for x in starts.open_rows(t.p4)], [keep])
        rows = relay._rows(starts.path_of(t.p4))
        self.assertEqual([(x["kind"], x.get("child"), x.get("by")) for x in rows if x["id"] == rid][-1],
                         ("started", "withdrawn", TOP), "kept as a row, with who withdrew it")
        ctx = context(t.say(KID, "anything waiting?"))
        self.assertIn("the port's docs", ctx)
        self.assertNotIn("the port's flush", ctx, "a withdrawn request is handed to nobody")
        r = t.cli(TOP, "request", "--withdraw", rid)
        self.assertEqual(r.returncode, 2)
        self.assertIn("withdrawn already", r.stderr)
        self.assertEqual(t.cli(TOP, "request", "--withdraw", "req-0000000000").returncode, 2, "an unknown id")
        self.assertEqual(t.cli(TOP, "request", "x title", "--withdraw", keep).returncode, 2, "an id and nothing else")
        again, new = starts.add(t.p4, KID, "the port's flush", BRIEF)
        self.assertEqual((again, new), (rid, True), "the same request can be filed again")

    def test_a_request_expires_after_a_day(self):
        home = self.t.p4
        rid, new = starts.add(home, KID, "an old child", BRIEF, at=time.time() - 25 * 3600)
        self.assertTrue(new)
        self.assertEqual(starts.pending(home), [])
        self.assertEqual(context(self.t.say(TOP2, "anything waiting?")).count("start requests from"), 0)
        rid2, _ = starts.add(home, KID, "a new child", BRIEF)
        self.assertEqual([r["id"] for r in starts.pending(home)], [rid2])

    def test_a_request_s_background_quotes_no_prompt_of_the_session_that_filed_it(self):
        """A start request's background names the filing session by its title and passes on no run of eight words of
        that session's first prompt, which was sent to it and not to the child."""
        long = "Port the legacy exporter flush path to the streaming writer and keep every row ordered"
        self.t.record(KID2, TOP, title="the streaming port")
        self.t.say(KID2, long)
        starts.add(self.t.p4, KID2, "a flush check", BRIEF)
        bg = starts.call_of(starts.pending(self.t.p4)[0], self.t.p4)["background"]
        self.assertIn("the streaming port", bg)
        words = long.split()
        runs = [" ".join(words[i:i + 8]) for i in range(len(words) - 7)]
        self.assertEqual([r for r in runs if r in bg], [], bg)

    def test_a_requested_new_top_level_session_stays_at_top_level(self):
        t = self.t
        starts.add(t.p4, TOP, "the release topic", BRIEF + " " + phi.NEW_TOP_BRIEF)
        call = starts.call_of(starts.pending(t.p4)[0])
        t.record(NEW, TOP2, title="the release topic")
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + call["prompt"])
        self.assertEqual(t.started_by(NEW)[0], "", "a requested new orchestrator stays at top level, never "
                                                   "under the filing session")

    def test_a_brief_s_one_level_line_names_the_start_s_model_and_effort(self):
        """The one line p4-phi asks a brief to say its level in, `Model and effort: <model> at <effort> effort`,
        gives the start call that model and effort, and the line level_line writes reads back to what it says."""
        import plans
        row = {"id": "req-0123456789", "requester": TOP, "title": "the landed commits", "background": "",
               "brief": "Check the landed commits and report.\nFiles: none\n"
                        "Model and effort: claude-sonnet-5-5 at medium effort."}
        call = starts.call_of(row)
        self.assertEqual((call.get("model"), call.get("effort")), ("claude-sonnet-5-5", "medium"))
        for level in ({"model": "claude-sonnet-5-5", "effort": "medium", "kind": "build", "said": True},
                      {"model": "claude-opus-5-5", "effort": "high", "kind": "design"},
                      {"model": "inherit", "effort": "low", "kind": "static"}):
            got = plans.said_level(plans.level_line(level))
            self.assertEqual((got.get("model"), got.get("effort")), (level["model"], level["effort"]),
                             plans.level_line(level))
        self.assertEqual(plans.said_level("Model and effort: ranker.pt at a guess"), {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
