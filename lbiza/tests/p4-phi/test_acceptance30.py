#!/usr/bin/env python3
"""How a top-level session reads its steps, how an empty session is shown in the tree, and how finished children
are archived.

    python -m pytest tests/p4-phi/test_acceptance30.py
"""

import json
import os
import sys
import tempfile
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import phi  # noqa: E402
import plans  # noqa: E402
import relay  # noqa: E402
from test_phi import KID, KID2, TOP, Tree, context, transcript  # noqa: E402


class SplitReads(unittest.TestCase):
    def test_the_four_misread_steps(self):
        for work in ("Check each plugin in its own folder for stray files in src/a.py",
                     "Check phi session tree for the empty node in src/b.py"):
            self.assertEqual(plans.top_stays(work), "", "two checks of things: work")
        self.assertIn("orchestration", plans.top_stays("Re-run the acceptance check"))
        self.assertIn("orchestration", plans.top_stays("Rerun the acceptance check"))
        self.assertIn("results", plans.top_stays("Final six-row pass/fail table"))
        self.assertIn("results", plans.top_stays("Compile the results of every check into one report"))
        self.assertTrue(plans.LANDS.search("Check our own work before the push"), "a check of its own work lands")


class Tracking(unittest.TestCase):
    def test_a_step_another_does_or_ezexe_decides_stays_at_the_top(self):
        """Tracking steps stay with the top-level session."""
        for text in ("Ledger: p4-phi fixer pushes #25", "ezexe updates the Mac's plugins",
                     "Track the #28 builder's progress", "The top session merges the fold branch"):
            self.assertIn("tracks", plans.top_stays(text), text)
        self.assertEqual(plans.top_stays("Write the sync script in src/sync.py"), "")


class Tree_(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        import p4conf
        p4conf.set_key(self.t.p4, "phi.upkeep", False)         # the test reads the lines of a store with upkeep off
        self.t.record(TOP, title="top")
        self.t.record(KID, TOP, title="the child")
        self.t.say(TOP, "Build it")

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_empty_node_is_hidden_and_its_children_kept(self):
        d = os.path.join(self.t.p4, "phi", "sessions", "4c8fb0ad")
        os.makedirs(d)
        relay._write_json(os.path.join(d, "session.json"), {"sessionId": "4c8fb0ad", "createdAt": "2026-11-12 10:00"})
        self.t.say(KID, "Fix the row")
        s = relay._session(self.t.p4, KID)
        s["spawnedFrom"] = {"sessionId": "4c8fb0ad", "source": "reparented"}
        relay._write_json(os.path.join(relay._dir(self.t.p4, KID), "session.json"), s)
        text = phi.tree_text(self.t.p4)
        self.assertNotIn("4c8fb0ad", text)
        self.assertIn("the child", text)

    def test_a_child_archiving_itself_keeps_its_report_and_is_counted_as_archived(self):
        self.t.say(KID, "Fix the row, archive when done")
        long = "The last row was dropped by flush_rows. " * 20
        path = transcript(os.path.join(self._tmp.name, "kid.jsonl"), "Fix the row, archive when done", [], long)
        self.t.cli(KID, "done", "test_flush.py: 3 tests OK")
        r = self.t.hook("self-archive", KID, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                              "tool_input": {"session_id": "self"}, "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        notes = phi.load_notes(self.t.p4, TOP)
        self.assertTrue(notes and "dropped by flush_rows" in notes[-1]["claim"], "its report kept on the parent")
        self.assertEqual(len(phi.load_turns(self.t.p4, KID)), 1)
        self.t.stop(KID, "Fix the row, archive when done", report=long)
        self.assertEqual(len(phi.load_turns(self.t.p4, KID)), 1, "a Stop after it keeps no second copy")
        ctx = context(self.t.say(TOP, "what next?"))
        self.assertIn("counts them as archived", ctx)
        self.assertGreater(ctx.count("dropped by flush_rows"), 5, "the note shown whole, not cut at 300")


    def test_a_child_archiving_itself_with_open_steps_is_counted_as_archived_with_them_named(self):
        """A child that archives itself with steps still open counts as archived, and its parent's note names them."""
        self.t.say(KID, "Fix the row in the exporter")
        r = self.t.hook("plan", KID, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                      "tool_input": {"items": [{"content": "Read flush_rows", "status": "completed"},
                                                               {"content": "Fix the last row", "status": "in_progress"},
                                                               {"content": "Run the exporter suite", "status": "pending"}]},
                                      "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        report = "Read flush_rows: the last row is dropped by an off-by-one. Not fixed yet."
        path = transcript(os.path.join(self._tmp.name, "kid46.jsonl"), "Fix the row in the exporter", [], report)
        r = self.t.hook("self-archive", KID, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                              "tool_input": {"session_id": "self"}, "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(relay._session(self.t.p4, KID).get("doneRetired"), "a self-archive counts as done")
        notes = phi.load_notes(self.t.p4, TOP)
        self.assertTrue(notes, "the parent holds its replaces: note")
        claim = notes[-1]["claim"]
        self.assertIn("it archived itself before its work was shown done, with 2 plan steps still open", claim)
        self.assertIn("\"Fix the last row\" in_progress", claim)
        self.assertIn("\"Run the exporter suite\" pending", claim)
        self.assertNotIn("Read flush_rows\"", claim, "a completed step is not named")
        self.assertIn("dropped by an off-by-one", claim, "its last report is kept")
        self.assertEqual(notes[-1]["source"], "p4-phi, a child that archived itself")
        self.assertEqual(self.t.log(KID)[-1].get("retired"), "archived")


    def archive_call(self, host, target):
        r = self.t.hook("self-archive", host, {"hook_event_name": "PreToolUse",
                                               "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                               "tool_input": {"session_id": target}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else {}

    def test_a_finished_child_is_counted_as_archived_and_ezexe_is_told_once(self):
        """p4-phi counts a finished session as archived at once, and leaves the archive call to the app's ask."""
        self.t.say(KID, "Fix the row in the exporter, report when done")
        self.assertTrue(relay._session(self.t.p4, KID).get("disposable"), "report when done marks it")
        said = self.t.cli(KID, "done", "test_flush.py: 3 tests OK").stdout
        self.assertNotIn("wrap_up", said, "a child that is done is handed no button")
        self.assertNotIn("archive_session", said, "and no archive call")
        self.assertIn("shows no archive button and asks for nothing", said)
        self.assertIn("Call no archive tool", said)
        self.t.stop(KID, "Fix the row in the exporter, report when done", report="Fixed flush_rows; 3 tests pass.")
        kid = relay._session(self.t.p4, KID)
        self.assertTrue(kid.get("doneRetired"))
        self.assertTrue(relay.gone(self.t.p4, kid), "the session tree counts it as archived from that moment")
        notes = phi.load_notes(self.t.p4, TOP)
        self.assertTrue(notes and notes[-1]["claim"].startswith("replaces:") and KID in notes[-1]["claim"])
        self.assertIn("p4-phi counts it as archived from now", notes[-1]["claim"])
        page = open(relay.ready_path(self.t.p4), encoding="utf-8").read()
        self.assertIn(KID, page, "listed as ready to archive")
        ctx = context(self.t.say(TOP, "what next?"))
        self.assertNotIn("archive each with `", ctx, "no archive call is handed out to any session")
        self.assertIn("the archive tool asks ezexe on the app's approval card before it runs", ctx)
        self.assertEqual(ctx.count(f"](#{KID})"), 1, "the notice names it once, as a link ezexe opens")
        again = context(self.t.say(TOP, "and then?"))
        self.assertNotIn("counts them as archived", again, "and only once")
        self.assertNotIn("archive_session", again)
        # the archive call is the app's to ask about: p4-phi neither refuses nor lets it through
        self.assertEqual(self.archive_call(TOP, KID), {})

    def test_a_done_top_level_session_gets_the_button_and_no_question_on_its_finished_tree(self):
        """The button is for a top-level session; its finished children were each named once as they finished, and
        an archive call on one is left to the app, which asks ezexe."""
        self.t.say(KID, "Fix one row of the exporter, report when done")
        self.t.cli(KID, "done", "its suite: 3 tests OK")
        self.t.stop(KID, "Fix one row of the exporter, report when done", report="Fixed; 3 tests pass.")
        self.assertTrue(relay._session(self.t.p4, KID).get("doneRetired"))
        said = self.t.cli(TOP, "done", "every fix landed and its suite passed").stdout
        self.assertIn("`mcp__ccd_turn__wrap_up` whose first action is the app's `archive`", said)
        self.assertNotIn("AskUserQuestion", said, "no question of p4-phi's own")
        self.assertEqual(self.archive_call(TOP, KID), {}, "the app asks ezexe; p4-phi adds no refusal")

    def test_a_session_counted_as_archived_and_messaged_again_is_named_as_reopened(self):
        """The mark of a finished session does not hide live work."""
        self.t.say(KID, "Fix the row in the exporter, report when done")
        self.t.cli(KID, "done", "test_flush.py: 3 tests OK")
        self.t.stop(KID, "Fix the row in the exporter, report when done", report="Fixed flush_rows.")
        context(self.t.say(TOP, "what next?"))
        self.t.say(KID, "One more thing: the header row too")
        kid = relay._session(self.t.p4, KID)
        self.assertFalse(kid.get("doneRetired"))
        self.assertFalse(relay.gone(self.t.p4, kid), "live again")
        ctx = context(self.t.say(TOP, "and now?"))
        self.assertIn("was messaged again and is reopened", ctx)
        self.assertIn(KID, ctx)
        self.assertNotIn(KID, open(relay.ready_path(self.t.p4), encoding="utf-8").read())
        self.assertNotIn("is reopened", context(self.t.say(TOP, "and after?")), "said once")


class ArchiveLock(unittest.TestCase):
    def test_a_held_lock_never_loses_the_child(self):
        with tempfile.TemporaryDirectory() as home:
            ppath = os.path.join(relay._dir(home, "local_p"), "session.json")
            relay._write_json(ppath, {"sessionId": "local_p"})
            with open(ppath + ".lock", "w") as f:
                f.write("x")
            old = relay.LOCK_WAIT_S
            relay.LOCK_WAIT_S = 0.05
            try:
                relay._pend_archive(home, "local_p", "local_c", {"title": "c"}, "done")
            finally:
                relay.LOCK_WAIT_S = old
            self.assertNotIn("staleChildren", relay._read_json(ppath), "never written without the lock")
            self.assertEqual([x["id"] for x in relay.drain_archive(home, "local_p")], ["local_c"])
            self.assertEqual(relay.drain_archive(home, "local_p"), [], "drained once")


if __name__ == "__main__":
    unittest.main(verbosity=1)
