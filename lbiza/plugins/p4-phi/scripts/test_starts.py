#!/usr/bin/env python3
"""starts.py: start requests carried by the store, run through phi's own hooks.

    python3 -I lbiza/plugins/p4-phi/scripts/test_starts.py

The tree: two top sessions and a child of the first. The child's turn is started by its parent's message, so the
app would refuse it `user_asked`: it is told to write a start request, and writes one. ezexe then speaks in the
other top session, which is handed the request with its exact call; its start_session call claims it; the child
that call starts arrives with the marker and is recorded as the requester's child, not the starter's, so its
reports and its archive line go to the requester. A request is dropped after a day.
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
from test_phi import CLI, KID, TOP, Tree, context  # noqa: E402

TOP2, NEW = "local_top00002", "local_new00001"
CLI.setdefault(TOP2, "eeee6666-0000-4000-8000-000000000000")
CLI.setdefault(NEW, "ffff7777-0000-4000-8000-000000000000")
BRIEF = ("Port the exporter's flush to the new writer and run its suite. This session is marked archive when done.")
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

    def test_a_turn_the_owner_did_not_begin_is_told_to_write_a_request_not_a_card(self):
        self.t.say(KID, CROSS, P4_PHI_NEW_TASK="1")       # the standing instruction first, once
        ctx = context(self.t.say(KID, CROSS, P4_PHI_NEW_TASK="1"))
        self.assertIn(" request \"<title>\" --brief", ctx)
        self.assertNotIn("own_initiative", ctx)
        self.assertNotIn("which ezexe starts with a click", ctx)
        self.assertIn("Do not ask ezexe to type anything", ctx)

    def test_a_request_is_started_by_the_next_owner_turn_and_the_child_is_the_requesters(self):
        t = self.t
        r = t.cli(KID, "request", "the flush port", "--brief", BRIEF)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kept as start request req-", r.stdout)
        self.assertIn("Do not ask ezexe", r.stdout)
        self.assertIn("was already kept", t.cli(KID, "request", "the flush port", "--brief", BRIEF).stdout)
        self.assertEqual(context(t.say(KID, CROSS)).count("start requests from sessions"), 0,
                         "a turn another session began carries no request")
        line = context(t.say(TOP2, "How are the docs coming?"))
        self.assertIn("start requests from sessions whose turns ezexe did not begin", line)
        self.assertIn("claude-code#109282", line)
        call = json.loads(line.split("`mcp__ccd_session__start_session` with ", 1)[1].split("\n", 1)[0])
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", False))
        self.assertIn(BRIEF, call["prompt"])
        self.assertIn(f"for {KID}.", call["prompt"])
        adv = t.hook("start-advice", TOP2, {"hook_event_name": "PreToolUse",
                                            "tool_name": "mcp__ccd_session__start_session", "tool_input": call})
        self.assertEqual(adv.stdout.strip(), "", "the exact call is not second-guessed")
        self.assertNotIn("start requests from", context(t.say(TOP, "and the exporter?")), "claimed: not handed twice")
        t.record(NEW, TOP2, title="the flush port")       # the app nests it under its starter
        handed = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = x (idle)\n"
                  "</system-reminder>\n\nTask:\n" + call["prompt"])
        self.assertEqual(t.say(NEW, handed).returncode, 0)
        self.assertEqual(t.started_by(NEW), (KID, "requested"))
        self.assertEqual(t.say(NEW, "carry on").returncode, 0)
        self.assertEqual(t.started_by(NEW), (KID, "requested"), "the app's record does not move it back")
        self.assertEqual(starts.pending(t.p4), [], "started")
        t.cli(NEW, "done", "ported the flush; its suite passes")
        t.stop(NEW, "Port the flush", report="Ported the flush; the suite passes.", uuid="n1")
        reports = [r.get("sessionId") for r in relay._rows(os.path.join(t.dir(KID), "reports.jsonl"))]
        self.assertIn(NEW, reports, "its report goes to the requester")
        notes = [n["claim"] for n in relay._rows(os.path.join(t.dir(KID), "notes.jsonl"))]
        self.assertTrue(any(n.startswith("replaces:") and NEW in n for n in notes), notes)
        archive = context(t.say(KID, CROSS))
        self.assertIn("Archive them now", archive)
        self.assertIn(NEW, archive.split("started to be archived when done")[1], "the archive line goes to the requester")
        self.assertNotIn("Archive them now", context(t.say(TOP2, "and now?")), "not to the starter")

    def test_a_request_expires_after_a_day(self):
        home = self.t.p4
        rid, new = starts.add(home, KID, "an old child", BRIEF, at=time.time() - 25 * 3600)
        self.assertTrue(new)
        self.assertEqual(starts.pending(home), [])
        self.assertEqual(context(self.t.say(TOP2, "anything waiting?")).count("start requests from"), 0)
        rid2, _ = starts.add(home, KID, "a new child", BRIEF)
        self.assertEqual([r["id"] for r in starts.pending(home)], [rid2])

    def test_a_requested_new_top_session_is_left_in_the_root(self):
        t = self.t
        starts.add(t.p4, TOP, "the release topic", BRIEF + " " + phi.NEW_TOP_BRIEF)
        call = starts.call_of(starts.pending(t.p4)[0])
        t.record(NEW, TOP2, title="the release topic")
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + call["prompt"])
        self.assertEqual(t.started_by(NEW)[0], "", "a new top is detached, never put under the requester")


if __name__ == "__main__":
    unittest.main(verbosity=1)
