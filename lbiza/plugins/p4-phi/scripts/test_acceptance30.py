#!/usr/bin/env python3
"""#30: the six misreads the acceptance re-run at 336627d left.

    python3 -I lbiza/plugins/p4-phi/scripts/test_acceptance30.py
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import plans  # noqa: E402
import relay  # noqa: E402
from test_phi import KID, KID2, TOP, Tree, context, transcript  # noqa: E402


def plan_of(*steps):
    return {"steps": [{"addr": str(k + 1), "content": c, "status": "pending"} for k, c in enumerate(steps)]}


class SplitReads(unittest.TestCase):
    def test_the_four_misread_steps(self):
        groups, kept = plans.top_groups(plan_of(
            "Check each plugin in its own folder for stray files in src/a.py",
            "Check phi session tree for the empty node in src/b.py",
            "Re-run the acceptance check", "Rerun the acceptance check", "Final six-row pass/fail table",
            "Compile the results of every check into one report"), "")
        self.assertEqual([[st["addr"] for st in g] for g in groups], [["1"], ["2"]], "two checks of things: work")
        why = dict(kept)
        self.assertIn("orchestration", why["3"])
        self.assertIn("orchestration", why["4"])
        self.assertIn("results", why["5"])
        self.assertIn("results", why["6"])
        self.assertTrue(plans.LANDS.search("Check our own work before the push"), "a check of its own work lands")


class Tracking(unittest.TestCase):
    def test_a_step_another_does_or_ezexe_decides_stays_at_the_top(self):
        """#31: tracking steps stay at the top."""
        groups, kept = plans.top_groups(plan_of(
            "Ledger: p4-phi fixer pushes #25", "ezexe updates the Mac's plugins", "Track the #28 builder's progress",
            "The top session merges the fold branch", "Write the sync script in src/sync.py"), "")
        self.assertEqual([a for a, why in kept if "tracks" in why], ["1", "2", "3", "4"])
        self.assertEqual([[st["content"] for st in g] for g in groups], [["Write the sync script in src/sync.py"]])
        free, kept = plans.judge(plan_of("Ledger: p4-phi fixer pushes #25 in src/a.py",
                                         "Write the store sync script and its workflow in src/sync.py"), "")
        self.assertEqual([st["addr"] for st in free], ["2"])


class SiblingWords(unittest.TestCase):
    def test_phi_and_session_alone_never_bear_on_a_sibling(self):
        step = "Check the phi session tree page for archived nodes"
        self.assertTrue(plans.bears("the phi session ran long", step), "a child still hears its parent")
        self.assertFalse(plans.bears_sibling("the phi session ran long", step))
        self.assertTrue(plans.bears_sibling("the tree page lists archived nodes twice", step))


class Tree_(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
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

    def test_a_child_archiving_itself_keeps_its_report_and_is_retired(self):
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
        self.assertIn("Archive them now", ctx)
        self.assertGreater(ctx.count("dropped by flush_rows"), 5, "the note shown whole, not cut at 300")


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
