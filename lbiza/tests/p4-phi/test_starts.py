#!/usr/bin/env python3
"""starts.py: the files a brief says it covers, the checkout a started session works in, and the one start request
the app's suggested task card cannot hold, run through phi.py's hooks.

    python -m pytest tests/p4-phi/test_starts.py

The tree: two orchestrators and a child of the first. Every session works in the one checkout, on the paths of its
`Files:` line. A start is refused where a writer's brief names none or names a path a running session that is not above
the starter holds; none is queued behind a busy writer, and no command narrows or releases what a session covers. A start the child may not
make is the app's suggested task card, desktop.md, "Start a task that Claude suggests", so `phi.py request` keeps
only a request to a puppeteer. A brief's `Files:` line is read as what the session covers, a withdrawn request is
handed to no session, and a request is dropped after a day.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
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
START = "mcp__ccd_session__start_session"


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

    def test_the_plain_start_request_is_gone_and_the_card_is_named_in_its_place(self):
        """The app's suggested task card holds a start a session may not make, desktop.md, "Start a task that Claude
        suggests", so p4-phi keeps no request for it: `phi.py request` with no `--to-puppeteer` is refused with the
        card's call and the tool that withdraws a card, starts.add keeps no row with no puppeteer to ask, and the
        functions that handed such a request and ordered the blocked wrap-up are not there."""
        t = self.t
        r = t.cli(KID, "request", "the flush port", "--brief", BRIEF)
        self.assertEqual(r.returncode, 2)
        self.assertIn("`mcp__ccd_session__start_session` with `initiation` `own_initiative`", r.stderr)
        self.assertIn("`mcp__ccd_session__dismiss_task`", r.stderr)
        self.assertIn("`--to-puppeteer`", r.stderr)
        with self.assertRaises(ValueError) as refused:
            starts.add(t.p4, KID, "the flush port", BRIEF)
        self.assertIn("suggested task card", str(refused.exception))
        self.assertEqual(starts.state(t.p4), {}, "no row is kept")
        with open(starts.__file__, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("mcp__ccd_turn__wrap_up", source, "starts.py orders no wrap-up")
        self.assertIn("`mcp__ccd_session__start_session`", source)

    def test_a_start_drafted_for_any_brief_passes_use_worktree_false(self):
        """Every session p4-phi starts works in its starter's checkout, on the paths of its `Files:` line, agent-teams.md,
        "Avoid file conflicts". So the call drafted for a brief that writes, one for a brief that only reads and one
        for a new orchestrator all pass `use_worktree: false`."""
        port = "Port the exporter's flush to the new writer and run its suite. Report when done."
        check = "Check what the exporter's flush does and report it."
        for brief in (port + "\nFiles: src/flush.py", port, port + "\nFiles: none", check + "\nFiles: none", check,
                      check + "\nFiles: src/flush.py", port + "\nFiles: the tests only", port + "\nFiles: read-only",
                      port + "\nFiles: src/flush.py\n" + starts.ORCHESTRATOR_BRIEF, starts.ORCHESTRATOR_BRIEF):
            self.assertIs(starts.use_worktree(brief), False, brief)
        import puppeteer
        draft = {"title": "the flush", "context": "fresh", "brief": port, "background": "x" * 90, "parent": TOP}
        self.assertIs(puppeteer.call_of(draft)["use_worktree"], False, "a worker's draft")
        self.assertIs(puppeteer.call_of({**draft, "brief": check})["use_worktree"], False, "a reader's draft")
        self.assertIs(puppeteer.call_of({**draft, "parent": ""})["use_worktree"], False, "a new orchestrator")

    def writer(self, sid="local_wrt00009", files="src/flush.py"):
        """A worker of the first orchestrator whose brief covers `files` and that is inside a turn."""
        CLI.setdefault(sid, sid.replace("local_wrt", "acac") + "-0000-4000-8000-000000000000")
        self.t.record(sid, TOP, title="the flush writer")
        self.t.say(sid, f"Task:\nRewrite the flush's writer. Report when done.\nFiles: {files}")
        return sid

    def start(self, host, prompt, **more):
        """What p4-phi's hook answers a start call with: its decision and reason, both '' when it says nothing."""
        call = {"initiation": "user_asked", "title": "the port", "context": "fresh", "use_worktree": False,
                "prompt": prompt, "background": "The exporter top holds the port; this child takes the flush. " * 2,
                **more}
        r = self.t.hook("start-advice", host, {"hook_event_name": "PreToolUse", "tool_name": START,
                                               "tool_input": call})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
        return out.get("permissionDecision", ""), out.get("permissionDecisionReason", "")

    def test_a_writers_start_with_no_files_line_is_refused_and_a_readers_is_not(self):
        """A writer's brief with no `Files:` line is refused, with no key to switch it off; a reader's brief and one
        that says `Files: none` start."""
        t = self.t
        # a reader's brief and one that says `Files: none` start
        self.assertEqual(self.start(TOP, "Check what the exporter's flush does and report it.\nFiles: none"), ("", ""))
        # a writer's brief with no `Files:` line is refused here, and in the retired-key case below
        self.assertEqual(self.start(TOP, "Port the exporter's flush to the new writer. Report when done.")[0], "deny")
        self.assertEqual(self.start(TOP, "Port the exporter's flush. Report when done.\nFiles: src/flush.py"),
                         ("", ""))
        import p4conf
        self.assertNotIn("file_sets", p4conf.DEFAULTS["phi"])
        with open(os.path.join(t.p4, "p4.json"), "w", encoding="utf-8") as f:
            json.dump({"phi": {"file_sets": True}}, f)
        self.assertEqual(self.start(TOP, "Port the exporter's flush to the new writer. Report when done.")[0], "deny",
                         "the retired key switches nothing")

    def test_a_start_whose_files_a_live_writer_covers_is_denied_with_its_id_until_the_writer_is_archived(self):
        """The start is refused, with the writer's id in its reason, for the same orchestrator's start and for
        another's, and goes through once the writer is archived. The held start and its helpers, starts.held_by,
        starts.writers and starts.files_overlap, are gone."""
        w = self.writer()
        self.assertEqual(self.t.session(w)["fileSet"], [relay.norm("src/flush.py", self.t.proj)])
        for host in (TOP, TOP2):
            decision, reason = self.start(host, BRIEF)
            self.assertEqual(decision, "deny", host)
            self.assertIn(w, reason, "a live writer of src/flush.py holds the path")
        path = os.path.join(self.t.dir(w), "session.json")
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        s["archived"] = True
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f)
        relay.forget(self.t.p4)
        self.assertEqual(self.start(TOP, BRIEF)[0], "")
        self.assertEqual(self.start(TOP2, BRIEF)[0], "")
        with open(phi.__file__, encoding="utf-8") as f:
            self.assertNotIn("this start is held", f.read())

    def test_no_start_is_queued_behind_a_busy_writer(self):
        """The start request queued behind a busy writer is gone, with its `after` rows: starts.add takes no `after`,
        nothing is handed as free of a writer, and no turn of the session is told of a queued start."""
        t = self.t
        w = self.writer()
        with self.assertRaises(TypeError):
            starts.add(t.p4, KID, "the flush port", BRIEF, after=w)
        self.assertEqual(starts.state(t.p4), {})
        t.cli(w, "done", "rewrote the writer; its suite passes")
        t.stop(w, "Rewrite the writer", report="Rewrote the writer; the suite passes.", uuid="w1")
        for said in (t.say(KID, CROSS), t.say(KID, "How is the port coming?"), t.say(TOP, "and the exporter?")):
            self.assertNotIn("queued", context(said))
            self.assertNotIn("busy writer", context(said))

    def test_no_command_narrows_or_releases_the_files_a_session_covers(self):
        """`phi.py files` is gone, with set_files and the `fileSetAt` and `fileSets` it kept: what a brief's `Files:`
        line names stays on the session's record as `fileSet` and on its page, as what it covers."""
        t = self.t
        w = self.writer(files="src/flush.py, docs/flush.md")
        r = t.cli(w, "files", "--release")
        self.assertEqual(r.returncode, 2, "argparse knows no such command")
        self.assertIn("invalid choice", r.stderr)
        s = t.session(w)
        self.assertEqual([f.rsplit("/", 1)[-1] for f in s["fileSet"]], ["flush.py", "flush.md"])
        self.assertNotIn("fileSetAt", s)
        self.assertNotIn("fileSets", s)
        t.cli(w, "done", "rewrote the writer; its suite passes")
        t.stop(w, "Rewrite the writer", report="Rewrote the writer; the suite passes.", uuid="w1")
        with open(os.path.join(t.dir(w), "session.md"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("## Files", page)
        self.assertIn("The files its brief says it covers:", page)
        self.assertNotIn("still holds", context(t.say(w, "carry on")), "no line on files it still holds")

    def test_a_stopped_or_finished_session_is_not_named_for_the_files_its_brief_covers(self):
        """The address book names a session for the files its brief covers only while it is at work on them: not once
        its last turn was shown done, and not while the app shows it stopped."""
        import book
        t = self.t
        w = self.writer()
        os.environ["P4_PHI_APP_SESSIONS"] = os.path.join(t.tmp, "app")
        try:
            phi.RECORDS.pop(w, None)
            self.assertEqual(book.held_files(t.p4, t.session(w)), [relay.norm("src/flush.py", t.proj)])
            rec = os.path.join(t.app, w + ".json")
            row = json.load(open(rec, encoding="utf-8"))
            with open(rec, "w", encoding="utf-8") as f:
                json.dump({**row, "lastTurnStopped": True}, f)
            phi.RECORDS.pop(w, None)
            self.assertEqual(book.held_files(t.p4, t.session(w)), [], "stopped")
            with open(rec, "w", encoding="utf-8") as f:
                json.dump(row, f)
            phi.RECORDS.pop(w, None)
            t.cli(w, "done", "rewrote the writer; its suite passes")
            t.stop(w, "Rewrite the writer", report="Rewrote the writer; the suite passes.", uuid="w1")
            self.assertEqual(book.held_files(t.p4, t.session(w)), [], "shown done")
        finally:
            os.environ.pop("P4_PHI_APP_SESSIONS", None)
            phi.RECORDS.pop(w, None)

    def test_a_files_line_is_read_as_the_files_a_brief_covers(self):
        self.assertEqual(starts.files_of("Fix it.\n- **Files:** `lib/x.py`, lib/y.py and z.md.", "E:/w"),
                         [relay.norm("E:/w/lib/x.py"), relay.norm("E:/w/lib/y.py"), "z.md"])
        self.assertEqual(starts.files_of("Check it.\nFiles: none"), [])
        self.assertIsNone(starts.files_of("Fix the files in lib."))

    def test_a_files_line_holds_only_the_paths_it_lists_to_write(self):
        """A `Files:` line holds only the paths it lists to write: a sentence after the list, a repository's root
        beside another path and an ancestor of a listed path are context."""
        base = self.t.proj
        os.makedirs(os.path.join(base, "p4", ".git"))
        root = relay.norm(os.path.join(base, "p4"))
        a = relay.norm("docs/a.html", base)
        got = starts.files_of("Write the page.\nFiles: `docs/a.html`. The live checkout is `" + root + "`, never "
                              "edit it.\nReport when done.", base)
        self.assertEqual(got, [a], "a sentence after the list names no file to write")
        got = starts.files_of("Files: docs/a.html, in the checkout `" + root + "`", base)
        self.assertEqual(got, [a], "a repository root beside another path is context")
        got = starts.files_of("Files: `p4/docs/a.html`, `p4/docs`, `p4`", base)
        self.assertEqual(got, [relay.norm("p4/docs/a.html", base)], "an ancestor of a listed path is left out")
        self.assertEqual(starts.files_of("Files: `" + root + "`", base), [root], "the only path on the line is kept")
        self.assertEqual(starts.files_of("Files: src/a.py, src/b.py and README.md.", base),
                         [relay.norm("src/a.py", base), relay.norm("src/b.py", base), "readme.md"])
        self.assertEqual(starts.files_of("Files: none. The checkout is `" + root + "`.", base), [])
        self.assertIsNone(starts.files_of("The checkout is `" + root + "`.", base))

    def test_a_clause_on_a_files_line_holds_no_word_of_it(self):
        """A piece of a `Files:` list that is a clause of words names no file; a piece that is one name, backticked or
        plain, with at most a trailing parenthetical, is kept."""
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
        sessions that name README.md in two repositories name two files; in one repository they name one."""
        base = self.t.proj
        a, b = os.path.join(base, "p4"), os.path.join(base, "phi")
        for r in (a, b):
            os.makedirs(os.path.join(r, ".git"))
        in_a, in_b = starts.files_of("Files: README.md", a), starts.files_of("Files: README.md", b)
        self.assertEqual(in_a, [relay.norm("README.md", a)])
        self.assertNotEqual(in_a, in_b, "the same name in two repositories")
        self.assertEqual(in_a, starts.files_of("Files: `README.md`", a))
        sub = os.path.join(a, "docs")
        os.makedirs(sub)
        self.assertEqual(starts.files_of("Files: docs/x.html", sub), [relay.norm("docs/x.html", a)],
                         "a relative path is read from the repository's root")

    def test_a_request_to_a_puppeteer_is_kept_with_its_background(self):
        """The one start request kept is the one addressed to a puppeteer. Its row carries a background of at least
        80 characters, given or built from the session that filed it, and the files its brief says it covers."""
        t = self.t
        given = "The exporter's flush moved to the new writer in src/flush.py; the docs follow the same layout."
        rid, new = starts.add(t.p4, KID, "the docs port", BRIEF, background=given, to=TOP2)
        self.assertTrue(new)
        self.assertEqual(starts.add(t.p4, KID, "the docs port", BRIEF, background=given, to=TOP2), (rid, False),
                         "kept once")
        short, _ = starts.add(t.p4, KID, "the short one", BRIEF.replace("src/flush.py", "docs/short.md"),
                              background="Short.", to=TOP2)
        rows = starts.state(t.p4)
        self.assertEqual((rows[rid]["to"], rows[rid]["background"]), (TOP2, given))
        self.assertEqual(rows[rid]["files"], [relay.norm("src/flush.py", t.proj)], "what its brief covers")
        self.assertNotIn("after", rows[rid])
        self.assertTrue(rows[short]["background"].startswith("Short."))
        self.assertGreaterEqual(len(rows[short]["background"]), 80)
        self.assertGreaterEqual(len(starts.background_of(t.p4, KID)), 80, "one built from the session that files it")
        bare, _ = starts.add(t.p4, KID, "the flush check", "Check what the exporter's flush does and report it.",
                             to=TOP2)
        self.assertNotIn("files", starts.state(t.p4)[bare], "a brief that names no files is kept all the same")

    def test_a_withdrawn_request_is_not_handed_out(self):
        """A withdrawn request is handed to no session, its row stays with who withdrew it, and the same request can
        be filed again."""
        t = self.t
        rid, _ = starts.add(t.p4, KID, "the port's flush", BRIEF, to=TOP2)
        keep, _ = starts.add(t.p4, KID, "the port's docs", BRIEF.replace("src/flush.py", "docs/flush.md"), to=TOP2)
        r = t.cli(TOP, "request", "--withdraw", rid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"withdrawn: start request {rid} \"the port's flush\"", r.stdout)
        self.assertEqual([x["id"] for x in starts.open_rows(t.p4)], [keep])
        rows = relay._rows(starts.path_of(t.p4))
        self.assertEqual([(x["kind"], x.get("child"), x.get("by")) for x in rows if x["id"] == rid][-1],
                         ("started", "withdrawn", TOP), "kept as a row, with who withdrew it")
        r = t.cli(TOP, "request", "--withdraw", rid)
        self.assertEqual(r.returncode, 2)
        self.assertIn("withdrawn already", r.stderr)
        self.assertEqual(t.cli(TOP, "request", "--withdraw", "req-0000000000").returncode, 2, "an unknown id")
        self.assertEqual(t.cli(TOP, "request", "x title", "--withdraw", keep).returncode, 2, "an id and nothing else")
        again, new = starts.add(t.p4, KID, "the port's flush", BRIEF, to=TOP2)
        self.assertEqual((again, new), (rid, True), "the same request can be filed again")
        starts.claim(t.p4, BRIEF + "\n\n" + starts.marker(keep, KID), TOP2, card=True)
        gone = t.cli(KID, "request", "--withdraw", keep)
        self.assertEqual(gone.returncode, 0, gone.stderr)
        self.assertIn("withdraw that card with `mcp__ccd_session__dismiss_task`", gone.stdout)

    def test_a_request_expires_after_a_day(self):
        home = self.t.p4
        rid, new = starts.add(home, KID, "an old child", BRIEF, at=time.time() - 25 * 3600, to=TOP2)
        self.assertTrue(new)
        self.assertEqual(starts.open_rows(home), [])
        rid2, _ = starts.add(home, KID, "a new child", BRIEF, to=TOP2)
        self.assertEqual([r["id"] for r in starts.open_rows(home)], [rid2])

    def test_a_request_s_background_quotes_no_prompt_of_the_session_that_filed_it(self):
        """A start request's background names the filing session by its title and passes on no run of eight words of
        that session's first prompt, which was sent to it and not to the child."""
        long = "Port the legacy exporter flush path to the streaming writer and keep every row ordered"
        self.t.record(KID2, TOP, title="the streaming port")
        self.t.say(KID2, long)
        rid, _ = starts.add(self.t.p4, KID2, "a flush check", BRIEF, to=TOP2)
        bg = starts.state(self.t.p4)[rid]["background"]
        self.assertIn("the streaming port", bg)
        words = long.split()
        runs = [" ".join(words[i:i + 8]) for i in range(len(words) - 7)]
        self.assertEqual([r for r in runs if r in bg], [], bg)

    def test_a_requested_new_orchestrator_stays_under_the_session_that_started_it(self):
        t = self.t
        rid, _ = starts.add(t.p4, TOP, "the release topic", BRIEF + " " + starts.ORCHESTRATOR_BRIEF, to=TOP2)
        prompt = BRIEF + " " + starts.ORCHESTRATOR_BRIEF + "\n\n" + starts.marker(rid, TOP)
        t.record(NEW, TOP2, title="the release topic")
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + prompt)
        self.assertEqual(t.started_by(NEW)[0], TOP2, "a requested new orchestrator stays under the session that "
                                                     "started it, never under the filing session")
        self.assertEqual(starts.state(t.p4)[rid]["started"], NEW)

    def test_an_orchestrators_brief_line_marks_it_and_one_regex_serves_every_reader(self):
        """The kind `top` and the skipped `Files:` partition are read from the one line, starts.ORCHESTRATOR."""
        import plans
        brief = starts.ORCHESTRATOR_BRIEF
        self.assertTrue(starts.ORCHESTRATOR.search(brief))
        self.assertTrue(starts.ORCHESTRATOR.search("Port it.\nIt is an orchestrator under the session that started it."))
        self.assertTrue(starts.ORCHESTRATOR.search("THIS SESSION IS AN ORCHESTRATOR UNDER THE SESSION THAT STARTED IT"))
        for plain in ("This session is a new top session, orchestrating its own topic.",
                      "Port the exporter's flush to the new writer.\nFiles: src/flush.py",
                      "This session is an orchestrator."):
            self.assertFalse(starts.ORCHESTRATOR.search(plain), plain)
        self.assertEqual(plans.child_kind(brief), "top")
        self.assertEqual(plans.child_level("Build the importer", "Build the importer.\n" + brief)["kind"], "top")
        self.assertEqual(plans.child_kind("Port the exporter's flush to the new writer."), "build")
        self.assertNotIn("detach", brief)

    def test_a_brief_s_one_level_line_names_the_start_s_model_and_effort(self):
        """The one line p4-phi asks a brief to say its level in, `Model and effort: <model> at <effort> effort`,
        gives the start call that model and effort, and the line level_line writes reads back to what it says."""
        import plans
        brief = ("Check the landed commits and report.\nFiles: none\n"
                 "Model and effort: claude-sonnet-5-5 at medium effort.")
        call = plans.with_level({"title": "the landed commits", "context": "fresh", "prompt": brief},
                                "the landed commits\n" + brief)
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
