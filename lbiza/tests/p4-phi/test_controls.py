#!/usr/bin/env python3
"""controls.py: a puppeteer and the sessions it controls, run through p4-phi's own hooks.

ezexe files an orchestrator in the sidebar section "puppeteers", which makes it a puppeteer. It controls
the orchestrators of other trees, in any store: p4-phi reads the filing from the app's own file, keeps the
record of the sessions it controls, tells each controlled session, writes the puppeteer's board, leaves its
waiting steps with it, names the sessions its records hold complete and leaves their archive to the app's approval
card, names a boundary once with the line that keeps what its board lacks and no compact question,
and carries a controlled session's request for a new orchestrator to it. No start waits behind a busy writer, so
a puppeteer is named no session that holds one and warned of no early go; a session started for a request another
session filed is held under that session; and every ask of ezexe in the lines a session is handed offers a click.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402
import phi  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
import controls  # noqa: E402
from test_phi import CLI, KID, KID2, TOP, Tree, context, memory, read, transcript, write  # noqa: E402
from test_phi import PROMPT, START as SESSION_START  # noqa: E402
import puppeteer  # noqa: E402  the watcher, whose slow look lists a puppeteer's open issues
from test_issues import FAKE_GH, GhTree  # noqa: E402  the stand-in for gh, and a tree whose hooks run it

PUP, PUP2, TOP2, TOP3, NEW = ("local_pup00001", "local_pup00002", "local_top00002", "local_top00003",
                              "local_new00001")
TOP4, TOP5 = "local_top00004", "local_top00005"
WORKER, CO1, CO2 = "local_wrk00001", "local_cow00001", "local_cow00002"
for k, sid in enumerate((PUP, PUP2, TOP2, TOP3, NEW, TOP4, TOP5, WORKER, CO1, CO2)):
    CLI.setdefault(sid, f"9999{k}000-0000-4000-8000-000000000000")
ARCHIVE = "mcp__ccd_session_mgmt__archive_session"
START = "mcp__ccd_session__start_session"
WHY = "its issue is closed by a pushed commit, its suite ran green, and no session reads its scratch clone"
BRIEF = "Build the importer's retry and run its suite. Report when done.\nFiles: src/retry.py"


class Supervisor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        self.other = os.path.join(t.tmp, "other")              # a second environment, with its own store
        self.store2 = os.path.join(self.other, ".claude", "p4")
        os.makedirs(self.store2)
        t.record(PUP, title="Control the exporter and the importer trees, and tell ezexe where each stands")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(TOP2, title="Build the importer", cwd=self.other)
        t.record(TOP3, title="An orchestrator nobody put under the puppeteer")
        t.record(KID, started_by=TOP, title="the flush child")
        self.file("puppeteers", PUP)

    def tearDown(self):
        self._tmp.cleanup()

    def file(self, section, *sids, shape=None, more=None):
        """The app's own file: `sids` filed in one sidebar section, and `more` mapping a sessionId to another section."""
        groups = [{"id": "cg-1", "name": section, "mode": "code"}]
        given = {"code:" + s: "cg-1" for s in sids}
        for k, (sid, name) in enumerate((more or {}).items()):
            groups.append({"id": f"cg-m{k}", "name": name})
            given["code:" + sid] = f"cg-m{k}"
        write(os.path.join(self.t.tmp, "claude_desktop_config.json"), json.dumps(
            {"preferences": {"epitaxyPrefs": {"dframe-group-scopes": shape if shape is not None
                                              else {"acct/org": {"groups": groups, "assignments": given}}}}}))

    def finish(self, host, proj=None, report="Built.", uuid="u0"):
        """One whole turn of a session, shown done."""
        self.t.say(host, "Build it", proj=proj)
        self.t.cli(host, "done", "its suite ran green and its commit is pushed", proj=proj)
        self.t.stop(host, "Build it", report=report, proj=proj, uuid=uuid)

    def archive(self, by, target, reason=WHY):
        """The archive hook for `by`'s call on `target`: what p4-phi adds to the app's own approval card."""
        inp = {"session_id": target, **({"reason": reason} if reason else {})}
        self._n = getattr(self, "_n", 0) + 1
        path = transcript(os.path.join(self.t.tmp, f"{by}arch{self._n}.jsonl"), "what is ready?", [], "",
                          f"arch{self._n}")
        r = self.t.hook("self-archive", by, {"hook_event_name": "PreToolUse", "tool_name": ARCHIVE,
                                             "tool_input": inp, "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else {}

    def plan(self, host, *steps, proj=None):
        items = [{"content": c, "status": "in_progress" if k == 0 else "pending"} for k, c in enumerate(steps)]
        return self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                          "tool_input": {"items": items}, "tool_response": "Plan shown."}, proj=proj)

    # --- the filing -------------------------------------------------------------------------------------------------

    def test_the_filing_is_read_from_the_apps_file_and_only_a_top_session_counts(self):
        t = self.t
        r = t.cli(PUP, "controls")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no session is controlled yet", r.stdout)
        r = t.cli(TOP, "controls", TOP3)
        self.assertEqual(r.returncode, 2, "a session outside the section is refused")
        self.assertIn("not a puppeteer", r.stderr)
        self.assertIn("no section", r.stderr)
        self.assertNotIn("controls", t.session(TOP), "and records nothing")
        t.say(KID, "Fix the row")
        self.file("puppeteers", PUP, KID)
        r = t.cli(KID, "controls")
        self.assertEqual(r.returncode, 2, "a child filed there is no puppeteer")
        self.assertIn("started by another session", r.stderr)
        self.file("Puppeteers", PUP)
        self.assertEqual(t.cli(PUP, "controls").returncode, 0, "the section's name is matched whatever its case")
        self.file("wrappin up", PUP)
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "another section marks nothing")
        self.file("puppeteers", PUP, shape=["reshaped"])
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "a reshaped file makes nobody a puppeteer")
        os.remove(os.path.join(t.tmp, "claude_desktop_config.json"))
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "and so does a missing one")

    def test_a_project_can_rename_the_section_or_turn_the_rule_off(self):
        t = self.t
        relay._write_json(os.path.join(t.p4, "p4.json"), {"phi": {"puppeteer_section": "strings"}})
        self.assertEqual(t.cli(PUP, "controls").returncode, 2)
        self.file("strings", PUP)
        self.assertEqual(t.cli(PUP, "controls").returncode, 0)
        relay._write_json(os.path.join(t.p4, "p4.json"), {"phi": {"puppeteer_section": ""}})
        self.assertEqual(t.cli(PUP, "controls").returncode, 2)

    def test_a_supervisor_session_is_told_once_what_it_is_and_the_sighting_is_kept(self):
        t = self.t
        ctx = context(t.say(PUP, "Control the two trees"))
        self.assertIn("This session is a puppeteer: ezexe filed it in the sidebar section \"puppeteers\"", ctx)
        self.assertIn("phi.py\" controls <sessionId>", ctx)
        self.assertNotIn("multiSelect", ctx, "the rule points at the archive offer and does not restate it")
        self.assertTrue(t.session(PUP).get("puppeteerSeen"))
        self.assertNotIn("This session is a puppeteer", context(t.say(PUP, "and now?")), "said once")
        self.assertNotIn("This session is a puppeteer", context(t.say(TOP, "Build the exporter")))
        self.assertIn("p4-phi first saw this session in the section at", t.cli(PUP, "controls").stdout)

    # --- the record of controlled sessions ----------------------------------------------------------------------------

    def test_controls_records_top_sessions_with_their_stores_and_prints_where_each_stands(self):
        t = self.t
        self.finish(TOP)
        t.say(TOP2, "Build the importer", proj=self.other)
        r = t.cli(PUP, "controls", TOP, TOP2)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {e["sessionId"]: e["store"] for e in t.session(PUP)["controls"]}
        self.assertTrue(os.path.samefile(rows[TOP], t.p4))
        self.assertTrue(os.path.samefile(rows[TOP2], self.store2), "its own store")
        self.assertIn(f"\"Build the narwhal exporter\" `{TOP}`", r.stdout)
        self.assertIn("shown done", r.stdout)
        self.assertIn(f"\"Build the importer\" `{TOP2}`", r.stdout)
        self.assertIn("working: its last message has no turn's end recorded after it", r.stdout)
        r = t.cli(PUP, "controls", KID)
        self.assertEqual(r.returncode, 2, "a child is reached through its orchestrator")
        self.assertIn("a puppeteer controls orchestrators", r.stderr)
        self.assertEqual(t.cli(PUP, "controls", PUP).returncode, 2, "nor itself")
        t.say(PUP, "where does each stand?")
        self.assertEqual(len(t.session(PUP)["controls"]), 2, "a hook's save keeps the list")
        t.cli(PUP, "controls", "--drop", TOP2)
        self.assertEqual([e["sessionId"] for e in t.session(PUP)["controls"]], [TOP])

    def test_a_controlled_session_is_told_of_its_supervisor_session_once_and_once_more_when_control_ends(self):
        t = self.t
        t.say(TOP, "Build the exporter")
        t.say(TOP2, "Build the importer", proj=self.other)
        t.say(TOP3, "Something else")
        t.cli(PUP, "controls", TOP, TOP2)
        ctx = context(t.say(TOP, "carry on"))
        self.assertIn("This session is controlled by a puppeteer: \"Control the exporter and the importer "
                      f"trees, and tell ezexe where each stands\" `{PUP}`", ctx)
        self.assertIn("stays at the top of its own tree, in its own section", ctx)
        self.assertIn("The app asks ezexe on its approval card before any archive call on its tree", ctx)
        self.assertEqual(t.session(TOP)["puppeteer"]["sessionId"], PUP, "kept on its own record, in its own store")
        self.assertNotIn("This session is controlled by a puppeteer", context(t.say(TOP, "and now?")),
                         "said once")
        ctx = context(t.say(TOP2, "carry on", proj=self.other))
        self.assertIn("This session is controlled by a puppeteer", ctx,
                      "a session in another store is told by its own hook")
        self.assertNotIn("controlled by a puppeteer", context(t.say(TOP3, "carry on")),
                         "an uncontrolled orchestrator: nothing")
        relay._write_json(os.path.join(t.dir(TOP3), "session.json"),
                          {**t.session(TOP3), "controls": [{"sessionId": KID, "store": t.p4}]})
        relay._write_json(os.path.join(t.dir(TOP), "session.json"),
                          {**t.session(TOP), "controls": [{"sessionId": TOP3, "store": t.p4}]})
        self.assertNotIn("controlled by a puppeteer", context(t.say(TOP3, "and now?")),
                         "listed by a session outside the section: told nothing")
        t.cli(PUP, "controls", "--drop", TOP)
        ctx = context(t.say(TOP, "and after?"))
        self.assertIn("This session has left the control of its puppeteer", ctx)
        self.assertNotIn("puppeteer", t.session(TOP))
        self.assertNotIn("left the control of its puppeteer", context(t.say(TOP, "and then?")), "said once")

    # --- complete sessions, and the archive left to the app ----------------------------------------------------------

    TITLE = "Build the narwhal exporter"
    COMPLETE = "p4-phi's records hold this session this puppeteer controls complete"

    def complete_top(self):
        """TOP finished and controlled, and the puppeteer handed the line that names it complete."""
        t = self.t
        self.finish(TOP)
        t.say(PUP, "Control the tree")
        t.cli(PUP, "controls", TOP)
        return context(t.say(PUP, "a report came in"))

    def test_a_complete_controlled_session_is_named_and_its_archive_is_left_to_the_apps_approval_card(self):
        """No tool of the app tells which session p4-phi's records hold complete, so that is named; the archive
        call is the app's to ask about, so p4-phi offers no question and refuses nothing."""
        ctx = self.complete_top()
        self.assertIn(f"{self.COMPLETE}, shown done with nothing open: \"{self.TITLE}\" `{TOP}`", ctx)
        self.assertIn("which the app puts to ezexe on its approval card", ctx)
        self.assertNotIn("AskUserQuestion", ctx)
        self.assertNotIn("session_archives", ctx, "no text tells a session to set it")
        self.assertIn("a boundary: every controlled session is idle", ctx, "the boundary's line comes with it")
        self.assertEqual(self.archive(PUP, TOP), {}, "no refusal of p4-phi's own")
        self.assertEqual(self.archive(PUP, TOP3), {}, "not even for a session it does not control")
        self.assertEqual(self.archive(TOP, KID), {}, "nor for an orchestrator's call")
        s = self.t.session(PUP)
        self.assertNotIn("archiveOffer", s)
        self.assertNotIn("puppeteerArchives", s)

    def test_one_complete_session_beside_a_working_one_is_named_once_and_is_no_boundary(self):
        t = self.t
        self.finish(TOP)
        t.say(TOP2, "Build it", proj=self.other)       # mid-turn, so no boundary
        t.say(PUP, "Control the trees")
        t.cli(PUP, "controls", TOP, TOP2)
        ctx = context(t.say(PUP, "a report came in"))
        self.assertIn(f"{self.COMPLETE}, shown done with nothing open: \"{self.TITLE}\" `{TOP}`.", ctx)
        self.assertNotIn(f"`{TOP2}`", ctx.split(self.COMPLETE, 1)[1].split("\n", 1)[0], "a working one is not named")
        self.assertNotIn("a boundary", ctx)
        self.assertNotIn(self.COMPLETE, context(t.say(PUP, "and now?")), "named once")

    def test_the_complete_line_leads_whole_when_five_ended_turn_lines_come_with_it(self):
        """ezexe/p4#68, by 8bf3e26: a notice that asks a session to act now leads the text. Five reports whose first
        lines run to the 200 characters a line quotes pass 4,000 characters with it; the line naming the complete
        sessions is there whole, inside the 2,000 characters the app shows of a text past its cap, and no piece is
        held on a page of p4-phi's own."""
        t = self.t
        t.record(TOP4, title="Build the ports table")
        t.record(TOP5, title="Build the moon format reader")
        five = [TOP, TOP2, TOP3, TOP4, TOP5]
        for sid in five:
            self.finish(sid, proj=self.other if sid == TOP2 else None, report="Built. " + "the suite ran green " * 12)
        t.say(PUP, "Control the five trees")
        t.cli(PUP, "controls", *five)
        ctx = context(t.say(PUP, "five reports came in"))
        self.assertGreater(len(ctx), 4000)
        self.assertNotIn("did not fit", ctx, "no piece is held")
        head = "p4-phi's records hold these sessions this puppeteer controls complete"
        line = ctx.split(head, 1)[1].split("\n")[0]
        for sid in five:
            self.assertIn(f"`{sid}`", line)
        self.assertIn("approval card", line, "the line whole")
        self.assertLessEqual(ctx.index(head) + len(head) + len(line), 2000, "inside the app's preview")
        after = ctx.split(head, 1)[1]
        self.assertTrue(any(m in after for m in ("ended turns. Each is one line", "set these sessions' effort")),
                        "the informational pieces follow it, whole and beside the prompt")

    def test_what_p4_phis_records_hold_against_a_controlled_session_is_printed_and_never_refuses_an_archive(self):
        t = self.t
        self.complete_top()
        t.say(TOP, "one more thing")
        self.plan(TOP, "Fix the header row in exporter.py", "Run the exporter suite")
        t.stop(TOP, "one more thing", calls=[("mcp__ccd_turn__wrap_up", {"recap": "half done"}, "ok")],
               report="Half done.", uuid="u1")
        self.assertEqual(self.archive(PUP, TOP), {}, "the app's card and the tool's own refusal decide")
        said = t.cli(PUP, "controls").stdout
        self.assertIn("open: 2 open plan steps, the next \"Fix the header row in exporter.py\"", said)
        self.assertNotIn("- left ", said)
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertNotIn("## Archived and left", board)
        self.assertIn("open: 2 open plan steps", board)

    def test_a_session_in_another_store_is_named_complete_and_that_store_is_only_read(self):
        t = self.t
        self.finish(TOP2, proj=self.other)

        def snap():
            return {os.path.join(d, f): read(os.path.join(d, f)) for d, _, fs in os.walk(self.store2) for f in fs}
        before = snap()
        t.say(PUP, "Control the tree")
        t.cli(PUP, "controls", TOP2)
        self.assertIn(f"\"Build the importer\" `{TOP2}`", context(t.say(PUP, "a report came in")))
        self.assertEqual(self.archive(PUP, TOP2), {})
        t.say(PUP, "where does each stand?")
        t.cli(PUP, "controls")
        self.assertEqual(snap(), before, "the puppeteer writes nothing into a controlled store")

    # --- its own steps ------------------------------------------------------------------------------------------------

    def test_a_supervisor_sessions_task_list_gets_no_delegation_advice_and_its_wait_does_not_send_the_turn_back(self):
        t = self.t
        steps = ("Await reports from the exporter, the importer and the acceptance check",
                 "Check the trees' results against GitHub", "Rewrite flush_rows in src/exporter.py")
        t.say(PUP, "Control the two trees")
        t.say(TOP3, "Control the two trees")
        ctx = context(self.plan(PUP, *steps))
        self.assertNotIn("worker", ctx)
        self.assertNotIn("start_session", ctx)
        t.say(TOP, "Build it")                      # a controlled session, mid-turn
        t.cli(PUP, "controls", TOP)
        r = t.stop(PUP, "Control the two trees", report="Waiting on \"Build the narwhal exporter\".")
        self.assertEqual(r.stdout.strip(), "", "its turn may end while it waits")
        self.assertEqual(t.log(PUP)[-1].get("waits_on"), 1)
        t.cli(TOP, "done", "its suite ran green")
        t.stop(TOP, "Build it", report="Built.")
        t.say(PUP, "a report came in")
        r = t.stop(PUP, "a report came in", report="Read it.", uuid="u1")
        self.assertEqual(r.stdout.strip(), "", "nobody left to wait on, and the turn is not sent back to the step")
        r = t.stop(TOP3, "Control the two trees", report="Waiting.")
        self.assertEqual(r.stdout.strip(), "", "an orchestrator outside the section is not sent back either")

    # --- the board ------------------------------------------------------------------------------------------------------

    def test_the_board_is_rewritten_by_hook_and_a_report_reaches_the_supervisor_session_by_reference(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP2, "Build the importer", proj=self.other)
        t.cli(PUP, "controls", TOP2)
        report = ("The importer reads the new format.\nSECOND-LINE-DETAIL: the parser keeps a ring of 64 rows and "
                  "the suite ran 41 tests.")
        t.cli(TOP2, "done", "its suite ran green", proj=self.other)
        t.stop(TOP2, "Build the importer", report=report, proj=self.other)
        ctx = context(t.say(PUP, "what came in?"))
        page = os.path.join(self.store2, "phi", "sessions", TOP2, "session.md").replace("\\", "/")
        self.assertIn(f"\"Build the importer\" `{TOP2}` ended a turn", ctx)
        self.assertIn("The importer reads the new format.", ctx, "one line")
        self.assertIn(page, ctx, "and its page")
        self.assertNotIn("SECOND-LINE-DETAIL", ctx, "never the report's text")
        self.assertNotIn("ended a turn", context(t.say(PUP, "and now?")), "a report is named once")
        t.cli(PUP, "note", "ezexe decides whether the importer ships before the exporter", "--source",
              "ezexe's message of today", "--kind", "decision")
        t.cli(PUP, "note", "The retry issue is parked until the importer lands", "--source", "the issue list",
              "--kind", "parked")
        t.say(PUP, "and the board?")
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertIn(f"- \"Build the importer\" `{TOP2}`", board)
        self.assertIn("shown done", board)
        self.assertIn("The importer reads the new format.", board)
        self.assertIn(page, board)
        self.assertNotIn("SECOND-LINE-DETAIL", board)
        waiting = board.split("## Waiting on")[1].split("## ")[0]
        self.assertIn("ezexe decides whether the importer ships", waiting)
        self.assertIn("The retry issue is parked", board.split("## Parked")[1].split("## ")[0])

    def test_after_a_compaction_the_board_comes_first(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP, "Build it")
        t.cli(PUP, "controls", TOP)
        r = t.hook("session-start", PUP, {"hook_event_name": "SessionStart", "source": "compact"})
        ctx = context(r)
        board = os.path.join(t.dir(PUP), "board.md").replace("\\", "/")
        self.assertTrue(ctx.startswith("phi (p4-phi): this session is a puppeteer and its context was "
                                       "compacted. Read its board before anything else: " + board), ctx[:300])
        self.assertTrue(os.path.exists(board))
        s = t.session(PUP)
        for key in ("compactions", "compactedAt"):
            self.assertNotIn(key, s, "p4-phi counts no compaction: the app decides when one runs")
        r = t.hook("session-start", TOP, {"hook_event_name": "SessionStart", "source": "compact"})
        self.assertNotIn("its board", context(r))

    def test_a_memory_ezexe_changes_during_the_run_is_named_on_the_board(self):
        t = self.t
        conf = os.path.join(t.tmp, "conf")             # no global CLAUDE.md: the store's memories are the rules
        os.makedirs(conf)
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with tabs in the exporter.")
        section = "## Feedback and user memories ezexe changed during the run\n\n"
        board = os.path.join(t.dir(PUP), "board.md")
        t.say(PUP, "Control the trees", CLAUDE_CONFIG_DIR=conf)
        self.assertIn(section + "None.", read(board))
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        t.say(PUP, "carry on", CLAUDE_CONFIG_DIR=conf)
        changed = read(board).split(section, 1)[1].split("\n## ", 1)[0]
        self.assertRegex(changed, r"^- tabs-not-spaces, \d{4}-\d\d-\d\d \d\d:\d\d\nEach is whole in .+/temportal/memory\.")
        self.assertEqual([x["name"] for x in t.session(PUP)["rulesChanged"]], ["tabs-not-spaces"])

    def test_a_boundary_hands_no_compact_question_and_the_board_comes_first_after_a_compaction(self):
        """ezexe/p4#219 and ezexe/p4#155. https://code.claude.com/docs/en/context-window.md, "When your context
        fills up": "Claude Code compacts automatically as you approach the limit, so a full context window doesn't
        end your session." So a boundary is named once with the one thing no compaction does for a puppeteer, keeping
        what its board lacks with `note`, and it hands no compact question, no buttons, no usage read and no
        `/compact` line to type. https://code.claude.com/docs/en/hooks-guide.md, "Re-inject context after
        compaction": "Use a `SessionStart` hook with a `compact` matcher to re-inject critical context after every
        compaction." That entry hands the board's path first, after a typed and an automatic compaction alike."""
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP, "Build it")                      # mid-turn
        t.cli(PUP, "controls", TOP)
        self.assertNotIn("a boundary", context(t.say(PUP, "anything?")), "a controlled session is working")
        t.cli(TOP, "done", "its suite ran green")
        t.stop(TOP, "Build it", report="Built.")
        ctx = context(t.say(PUP, "a report came in"))
        board = os.path.join(t.dir(PUP), "board.md").replace("\\", "/")
        line = next((x for x in ctx.split("\n") if "phi (p4-phi): a boundary: " in x), "")
        self.assertIn("a boundary: every controlled session is idle and no request is waiting", line)
        self.assertIn(f"keep what is not yet on the board, {board}, with `{phi.commands()} note`", line,
                      "the part with no native counterpart stays")
        for gone in ("Compact now", "Later", "/compact", "get_usage", "wrap_up", "button", "to type", "ceiling",
                     "new_session", "successor"):
            self.assertNotIn(gone, line, gone)
        for gone in ("Compact now", "/compact", "auto-compact starts at"):
            self.assertNotIn(gone, ctx, gone)
        self.assertNotIn("a boundary", context(t.say(PUP, "and now?")), "a second hook at the same boundary: nothing")
        relay._write_json(os.path.join(t.p4, "p4.json"), {"phi": {"puppeteer_chars": 50, "compactions": 1}})
        self.assertNotIn("a boundary", context(t.say(PUP, "and now?")), "no count of characters names it again")
        self.assertNotIn("compactions", phi.CAPS)
        r = t.hook("session-start", PUP, {"hook_event_name": "SessionStart", "source": "compact"})
        self.assertTrue(context(r).startswith("phi (p4-phi): this session is a puppeteer and its context was "
                                              "compacted. Read its board before anything else: " + board),
                        context(r)[:300])

    def test_a_controlled_tree_that_closed_is_a_boundary_named_once_while_another_still_works(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP, "Build it")                      # both mid-turn
        t.say(TOP2, "Build it", proj=self.other)
        t.cli(PUP, "controls", TOP, TOP2)
        self.assertNotIn("a boundary", context(t.say(PUP, "anything?")), "both still work")
        app = os.path.join(t.app, TOP + ".json")
        write(app, json.dumps({**json.loads(read(app)), "isArchived": True}))      # ezexe archived it in the app
        ctx = context(t.say(PUP, "anything now?"))
        self.assertIn(f"a boundary: the tree of \"{self.TITLE}\" has closed.", ctx)
        self.assertIn("keep what is not yet on the board", ctx)
        self.assertNotIn("Compact now", ctx)
        self.assertNotIn("is complete", ctx, "an archived session is offered to nobody")
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertRegex(board, rf"- \"{self.TITLE}\" `{TOP}`, store .+: archived\.")
        self.assertNotIn("a boundary", context(t.say(PUP, "and now?")), "said once")

    def test_a_successor_takes_over_the_controlled_sessions_and_the_old_ones_archive_is_left_to_the_app(self):
        t = self.t
        t.record(PUP2, title="The second puppeteer")
        self.finish(TOP)
        t.say(PUP, "Control the tree")
        t.cli(PUP, "controls", TOP)
        t.cli(PUP, "note", "ezexe froze the retry work on 2026-11-16", "--source", "ezexe's message", "--kind",
              "decision")
        self.file("puppeteers", PUP, PUP2)
        r = t.cli(PUP2, "controls", "--from", PUP)
        self.assertEqual(r.returncode, 2, "not before the old one hands over")
        self.assertIn("has not handed over", r.stderr)
        r = t.cli(PUP, "controls", "--hand", PUP2)
        self.assertEqual(r.returncode, 0)
        self.assertIn("the app asks ezexe on its approval card before it archives this session", r.stdout)
        t.cli(PUP, "done", "handed the board to the second puppeteer")
        t.stop(PUP, "Control the tree", report="Handed over.")
        r = t.cli(PUP2, "controls", "--from", PUP)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("took over 1 controlled session and 1 note", r.stdout)
        self.assertEqual([e["sessionId"] for e in t.session(PUP2)["controls"]], [TOP])
        self.assertIn("ezexe froze the retry work", read(os.path.join(t.dir(PUP2), "board.md")))
        ctx = context(t.say(TOP, "carry on"))
        self.assertIn(f"\"The second puppeteer\" `{PUP2}`", ctx, "the successor controls it now")
        self.assertEqual(self.archive(PUP2, PUP), {}, "its archive is the app's to ask about")

    # --- a new orchestrator goes through the puppeteer ----------------------------------------------------

    def test_a_controlled_top_session_asks_its_supervisor_session_and_its_own_start_is_refused(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP2, "Build the importer", proj=self.other, P4_PHI_BOOK="1")
        t.cli(PUP, "controls", TOP2)
        t.stop(TOP2, "Build the importer", report="Started.", proj=self.other)
        ctx = context(t.say(TOP2, "Also, what about a new exporter for the moon format?", proj=self.other,
                            P4_PHI_BOOK="1"))
        self.assertIn("This session is controlled by a puppeteer", ctx)
        new_top = BRIEF + "\n" + phi.NEW_TOP_BRIEF
        r = t.hook("start-advice", TOP2, {"hook_event_name": "PreToolUse", "tool_name": START,
                                          "tool_input": {"initiation": "user_asked", "title": "the retry",
                                                         "prompt": new_top}}, proj=self.other)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny", "its own start of a new orchestrator is refused")
        self.assertIn("--to-puppeteer", out["permissionDecisionReason"])
        r = t.hook("start-advice", TOP3, {"hook_event_name": "PreToolUse", "tool_name": START,
                                          "tool_input": {"initiation": "user_asked", "title": "the retry",
                                                         "prompt": new_top}})
        self.assertNotIn("\"deny\"", r.stdout, "an orchestrator with no puppeteer starts its own")
        r = t.cli(TOP3, "request", "the retry", "--brief", BRIEF, "--to-puppeteer")
        self.assertEqual(r.returncode, 2)
        self.assertIn("has no puppeteer", r.stderr)
        r = t.cli(TOP2, "request", "the retry", "--brief", BRIEF, "--to-puppeteer", proj=self.other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("to this session's puppeteer", r.stdout)
        self.assertIn("Start nothing for it here", r.stdout)
        row = next(iter(starts.state(self.store2).values()))
        self.assertEqual(row["to"], PUP, "kept in the store of the session that filed it")
        self.assertEqual(starts.state(t.p4), {}, "and nothing in the puppeteer's")
        self.assertNotIn(row["id"], context(t.say(TOP2, "and now?", proj=self.other)),
                         "never handed back to the session that filed it")
        # the puppeteer reads it where it lies, at a turn ezexe began
        ctx = context(t.say(PUP, "what is waiting?"))
        self.assertIn("controlled sessions ask this puppeteer for new orchestrators", ctx)
        self.assertIn("to be filed in the ungrouped list under its project", ctx)
        call = json.loads(ctx.split("`mcp__ccd_session__start_session` with ", 1)[1].split("\n", 1)[0])
        self.assertEqual(os.path.normcase(os.path.normpath(call["cwd"])),
                         os.path.normcase(os.path.normpath(self.other)), "in the environment of the session that filed it")
        self.assertIn(phi.NEW_TOP_BRIEF, call["prompt"])
        self.assertIn(f"for {TOP2}.", call["prompt"])
        self.assertIs(call["use_worktree"], False, "a new orchestrator lands in its project's own checkout")
        self.assertIn("## Requests to this puppeteer", read(os.path.join(t.dir(PUP), "board.md")))
        self.assertNotIn("a boundary", ctx, "never while a controlled session waits on the puppeteer's answer")
        # it starts it: the new session arrives in the store of the session that filed the request, an
        # orchestrator, and is taken under control
        t.record(NEW, started_by=PUP, title="the retry", cwd=self.other)
        t.say(NEW, "Task:\n" + call["prompt"], proj=self.other)
        self.assertEqual(starts.open_rows(self.store2), [], "the request is started")
        self.file("puppeteers", PUP, more={TOP2: "importers"})
        ctx = context(t.say(PUP, "and now?"))
        self.assertIn(f"\"the retry\" `{NEW}` is an orchestrator this puppeteer started, so it is "
                      f"controlled", ctx)
        self.assertIn("File it in the section \"importers\" with `mcp__ccd_sidebar__move_sessions`, which takes the "
                      "section's id as `mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` answers "
                      "it, never in \"puppeteers\"", ctx)
        self.assertIn(NEW, [e["sessionId"] for e in t.session(PUP)["controls"]])
        self.assertIn("This session is controlled by a puppeteer", context(t.say(NEW, "carry on",
                                                                                          proj=self.other)))

    def test_a_controlled_sessions_refused_start_says_this_session_is_controlled_by_a_supervisor_session(self):
        """Run through `recall-hook.sh lookup-check`, which runs what the hooks module runs for a checked call."""
        t = self.t
        t.say(TOP, "Build the exporter")
        t.cli(PUP, "controls", TOP)
        t.say(TOP, "carry on")
        body = {"session_id": CLI[TOP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": START,
                "tool_input": {"initiation": "user_asked", "title": "the retry",
                               "prompt": BRIEF + "\n" + phi.NEW_TOP_BRIEF}, "tool_use_id": "toolu_start01"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(TOP))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("this session is controlled by a puppeteer", out["permissionDecisionReason"])

    def test_a_declined_request_is_closed_and_the_session_that_filed_it_is_told(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP2, "Build the importer", proj=self.other)
        t.cli(PUP, "controls", TOP2)
        t.say(TOP2, "carry on", proj=self.other)
        t.cli(TOP2, "request", "the retry", "--brief", BRIEF, "--to-puppeteer", proj=self.other)
        rid = next(iter(starts.state(self.store2)))
        r = t.cli(PUP, "controls", "--decline", rid, "ezexe froze the retry work, and it duplicates issue 50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("declined", read(os.path.join(t.dir(PUP), "board.md")))
        self.assertNotIn("ask this puppeteer", context(t.say(PUP, "what is waiting?")))
        ctx = context(t.say(TOP2, "and the retry?", proj=self.other))
        self.assertIn("declined the request", ctx)
        self.assertIn("ezexe froze the retry work", ctx)
        self.assertEqual(starts.open_rows(self.store2), [], "closed in the store of the session that filed it, by "
                                                            "that session's own hook")
        self.assertNotIn("declined the request", context(t.say(TOP2, "and now?", proj=self.other)), "said once")

    def test_a_top_session_ezexe_started_directly_is_named_to_the_supervisor_session_once(self):
        t = self.t
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the exporter")
        t.cli(PUP, "controls", TOP)
        self.assertNotIn("does not control", context(t.say(PUP, "anything new?")))
        relay._write_json(os.path.join(t.dir(TOP3), "session.json"),
                          {"sessionId": TOP3, "title": "An orchestrator nobody put under the puppeteer",
                           "createdAt": "2999-01-01 00:00", "cwd": t.proj})
        ctx = context(t.say(PUP, "anything new?"))
        self.assertIn(f"\"An orchestrator nobody put under the puppeteer\" `{TOP3}` is a new orchestrator", ctx)
        self.assertIn(f"controls {TOP3}` takes it under control", ctx)
        self.assertNotIn("does not control", context(t.say(PUP, "and now?")), "named once")

    def test_a_worker_whose_app_record_lands_after_its_session_start_is_never_named_a_new_orchestrator(self):
        """A worker a controlled orchestrator started, whose SessionStart ran before the app wrote its record, is
        read by that record as the worker it is, and never named to the puppeteer as a new orchestrator."""
        t = self.t
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the exporter")
        t.cli(PUP, "controls", TOP)
        r = t.hook(SESSION_START, NEW, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(phi.spawned_from(t.session(NEW)), "its SessionStart ran before the app wrote its record")
        t.record(NEW, started_by=TOP, title="the retry worker")
        ctx = context(t.say(PUP, "anything new?"))
        self.assertNotIn(NEW, ctx, "a worker is no new orchestrator")
        t.say(NEW, "Task:\nBuild the retry.\nFiles: src/retry.py")
        self.assertEqual(t.started_by(NEW)[0], TOP)
        self.assertNotIn(NEW, context(t.say(PUP, "and now?")))

    def test_a_go_to_a_writer_is_warned_about_for_no_file_another_controlled_session_covers(self):
        """The early-go warning is gone, with controls.go_text: a puppeteer's go to a controlled session whose brief
        names a file another controlled session covers goes out with no line; the paths each session covers are held
        by the guard at a start and an edit, not by a warning on a go."""
        t = self.t
        t.say(TOP, "Task:\nBuild the exporter's flush.\nFiles: src/flush.py, src/writer.py")
        t.say(TOP3, "Task:\nBuild the retry on the same writer.\nFiles: src/writer.py")
        t.say(PUP, "Control the trees")
        t.cli(PUP, "controls", TOP, TOP3)

        def go(to, message="Go: start on the retry."):
            r = t.hook("go-guard", PUP, {"hook_event_name": "PreToolUse", "tool_name": "SendMessage",
                                         "tool_input": {"to": to, "message": message}})
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()
        self.assertEqual(go(TOP3), "", "no warning for the file another controlled session covers")
        self.assertEqual(go(TOP3, "Go.\nFiles: src/flush.py"), "", "nor for the files the message names")
        self.assertNotIn("goWarned", t.session(PUP))

    def test_work_on_a_controlled_sessions_topic_is_sent_down_and_not_done_by_the_supervisor_session(self):
        t = self.t
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the narwhal exporter and its ports table")
        t.cli(PUP, "controls", TOP)
        ctx = context(t.say(PUP, "Write a page about the narwhal exporter's ports table"))
        self.assertIn(f"work on the topic \"Build the narwhal exporter\" `{TOP}` orchestrates", ctx)
        self.assertIn("do not do it here and start no child for it", ctx)
        self.assertIn("send that session one message with SendMessage", ctx)
        self.assertIn("holding " + phi.RESTATE, ctx, "the task restated, never ezexe's words quoted")
        self.assertNotIn("orchestrates. If so", context(t.say(PUP, "How is the weather on the moon today?")))


    def test_no_rules_page_copies_a_memory_the_board_names(self):       # 200
        """The memory file itself holds its new wording, so p4-phi writes no phi/rules.md copy of it."""
        t = self.t
        conf = os.path.join(t.tmp, "conf")
        os.makedirs(conf)
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with tabs in the exporter.")
        t.hook("session-start", PUP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        t.say(PUP, "Control the trees", CLAUDE_CONFIG_DIR=conf)
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        t.say(PUP, "carry on", CLAUDE_CONFIG_DIR=conf)
        self.assertIn("- tabs-not-spaces, ", read(os.path.join(t.dir(PUP), "board.md")))
        self.assertFalse(os.path.exists(os.path.join(t.p4, "phi", "rules.md")))

    def test_a_finding_the_puppeteer_published_leaves_its_board(self):                          # 210
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP2, "Build the importer", proj=self.other)
        t.cli(PUP, "controls", TOP2)
        line = "the importer drops a row whose quote spans two lines"
        t.cli(TOP2, "done", "its suite ran green", proj=self.other)
        t.stop(TOP2, "Build the importer", report=f"Built.\nFinding: {line}", proj=self.other)
        t.say(PUP, "what came in?")
        board = os.path.join(t.dir(PUP), "board.md")
        self.assertIn(line, read(board).split("## Findings")[1].split("\n## ")[0])
        t.cli(PUP, "note", f"Published as ezexe/p4#301: {line}", "--source", "gh issue create", "--kind", "published")
        t.say(PUP, "and the board?")
        found = read(board).split("## Findings")[1].split("\n## ")[0]
        self.assertNotIn(line, found)
        self.assertIn("None.", found)

    # --- shared by the #211, #224 and #226 drafts ---------------------------------------------------------------

    def pre(self, host, tool, inp, proj=None, **more):
        """One call's check through `recall-hook.sh lookup-check`, which runs what the hooks module runs: the reason or the
        context it hands, '' for none."""
        t = self.t
        self._pre = getattr(self, "_pre", 0) + 1
        body = {"session_id": CLI[host], "cwd": proj or t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": f"toolu_pre{self._pre:04d}", **more}
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(host, proj))
        self.assertEqual(r.returncode, 0, r.stderr)
        print("PRE", tool, repr(r.stdout[:300]), repr(r.stderr[-500:]))
        out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
        return out.get("permissionDecisionReason", "") + out.get("additionalContext", ""), out

    def test_a_puppeteer_is_told_to_set_each_reporting_sessions_effort_and_never_its_model(self):    # 224
        t = self.t
        t.record(TOP4, title="Check the exporter's landing")
        t.say(PUP, "Control the trees")
        for sid in (TOP, TOP3, TOP4):
            t.say(sid, "Build it")
        t.cli(PUP, "controls", TOP, TOP3, TOP4)
        t.stop(TOP, "Build it", report="The check came back with 3 faults in flush_rows; the fix starts again.")
        t.stop(TOP3, "Build it", report="Landed 2 commits and relayed the suite result to the importer.")
        self.finish(TOP4, report="Checked and closed.")
        ctx = context(t.say(PUP, "what came in?"))
        line = next((x for x in ctx.splitlines() if "set_session_effort" in x), "")
        self.assertTrue(line, ctx)
        lines = ctx[ctx.index(line):]
        self.assertRegex(lines, rf"`{TOP}`[^\n]*raise")
        self.assertRegex(lines, rf"`{TOP3}`[^\n]*lower")
        self.assertRegex(lines, rf"`{TOP4}`[^\n]*low\b")
        self.assertIn("note", lines, "logged on the board")
        said, out = self.pre(PUP, "mcp__ccd_session_mgmt__set_session_model",
                             {"session_id": TOP, "model": "claude-haiku-5-5"})
        self.assertNotIn("permissionDecision", out, "p4-phi keeps no refusal of its own")
        self.assertIn("set_session_effort", controls.RULE)

    def test_a_worker_under_a_puppeteer_hands_up_a_pages_path_and_counts_and_never_publishes(self):   # 226
        t = self.t
        t.say(PUP, "Control the trees")
        t.record(NEW, started_by=PUP, title="Puppeteer's standing worker")
        ctx = context(t.say(NEW, "Run the puppeteer's archive checks and counts.\n" + controls.WORKER_BRIEF))
        self.assertIn("page's path and its counts", ctx)
        self.assertIn("never the page's text", ctx)
        self.assertIn("Artifact", ctx)
        self.assertIn("unless ezexe asks", ctx)

    def test_a_puppeteers_turns_hold_messages_and_its_standing_worker_does_the_rest(self):          # 211
        t = self.t
        t.say(PUP, "Control the trees")
        brief = "Run the puppeteer's checks and counts.\n" + controls.WORKER_BRIEF
        said, _ = self.pre(PUP, START, {"initiation": "user_asked", "title": "Standing worker", "prompt": brief})
        self.assertNotIn("refused", said, "the first standing worker is let through")
        t.record(WORKER, started_by=PUP, title="Puppeteer's standing worker")
        pad = os.path.join(t.tmp, "app-scratchpad", "worker").replace("\\", "/")
        ctx = context(t.hook(PROMPT, WORKER, {"hook_event_name": "UserPromptSubmit", "prompt": brief,
                                              "scratchpad_dir": pad}))
        self.assertIn("standing coworker", ctx)
        self.assertIn("Model and effort:", ctx)
        self.assertIn("one closing message to the puppeteer", ctx)
        self.assertIn(f"{pad}/state.md", ctx, "its state page, in the app's scratchpad")
        self.assertNotIn(os.path.join(t.dir(WORKER), "state.md").replace("\\", "/"), ctx, "never under .claude")
        self.assertNotIn("temportal/tmp", ctx, "a started session is told no scratchpad in the store")
        said, out = self.pre(PUP, START, {"initiation": "user_asked", "title": "Standing worker again",
                                          "prompt": brief})
        self.assertEqual(out.get("permissionDecision"), "deny", "a second standing worker while the first is live")
        self.assertIn(WORKER, said)
        said, _ = self.pre(PUP, "Bash", {"command": "ls E:/x"})
        self.assertIn(WORKER, said, "a shell call of the puppeteer is sent to its standing worker")
        said, _ = self.pre(PUP, "Bash", {"command": f'{phi.commands()} note "the importer waits" --source "x"'})
        self.assertNotIn(WORKER, said, "its own phi.py note call is its work")
        said, _ = self.pre(PUP, "Bash", {"command": "ls E:/x"}, agent_id="agent_x1")
        self.assertNotIn(WORKER, said, "a subagent of the puppeteer is not the puppeteer")
        self.assertTrue(os.path.exists(os.path.join(t.p4, "phi", ".puppeteers", CLI[PUP])), "the marker the gate reads")
        copad = os.path.join(t.tmp, "app-scratchpad", "co1").replace("\\", "/")
        for sid in (CO1, CO2):
            t.record(sid, started_by=WORKER, title="a standing coworker")
            said = {"hook_event_name": "UserPromptSubmit", "prompt": "Check the archives.\nFiles: none"}
            if sid == CO1:
                said["scratchpad_dir"] = copad
            self.assertIn("standing coworker", context(t.hook(PROMPT, sid, said)))
        t.hook(PROMPT, CO1, {"hook_event_name": "UserPromptSubmit", "prompt": "next",
                             "scratchpad_dir": copad + "-after-a-clear"})
        ctx = context(t.say(PUP, f'<cross-session-message from="{WORKER}">Checked 4 archives; page: x.md'
                                 f'</cross-session-message>'))
        line = next((x for x in ctx.splitlines() if "get_usage" in x and WORKER in x), "")
        for sid in (WORKER, CO1, CO2):
            self.assertIn(sid, line)
        self.assertIn(f"{controls.CLEAR_AT} percent", line)
        self.assertNotIn(f"worker `{WORKER}` reported", context(t.say(PUP, "and now?")), "only at its report")
        # the hooks module keeps each session's measure in usage.json: a session with one is read there, not asked
        report = f'<cross-session-message from="{WORKER}">Checked 5 archives.</cross-session-message>'

        def measured(sid, percent):
            write(os.path.join(t.dir(sid), phi.USAGE_FILE), json.dumps(
                {"at": 1, "context": {"tokens": percent * 10000, "window": 1000000, "percent": percent},
                 "rateLimits": []}))
        measured(WORKER, controls.CLEAR_AT + 12)
        measured(CO1, controls.CLEAR_AT - 1)
        line = next((x for x in context(t.say(PUP, report)).splitlines() if f"worker `{WORKER}` reported" in x), "")
        self.assertIn(f"`{WORKER}` at {controls.CLEAR_AT + 12} percent", line, "past the line, by its own measure")
        # the report the worker's hooks module sends at its turn's end names the worker as `from-session`, beside
        # the socket it came over, as the transcripts of the desktop app show it
        sent = (f'<cross-session-message from="uds:\\\\.\\pipe\\LOCAL\\cc-msg-001111dc" from-session="{WORKER}" '
                f'from-name="worker" from-mode="bypass">phi (p4-phi): this session ended a turn. Its report follows, '
                f'and needs no reply.\n\nChecked 6 archives.</cross-session-message>')
        self.assertIn(f"worker `{WORKER}` reported", context(t.say(PUP, sent)))
        other = sent.replace(WORKER, CO1)
        self.assertNotIn(f"worker `{WORKER}` reported", context(t.say(PUP, other)), "a coworker's report is not its")
        self.assertEqual(controls.usage_line(t.p4, t.session(PUP), sent, t.p4, "user"), "",
                         "ezexe's own message that quotes a report is none")
        self.assertIn("usage.json", line)
        self.assertNotIn(CO1, line, "a coworker measured under the line is not named")
        self.assertRegex(line, rf"No measure is kept of `{CO2}`: read `mcp__ccd_session_mgmt__get_usage`")
        self.assertEqual(line.count("get_usage"), 1, "only the session with no measure is asked for one")
        self.assertIn("clear_session", line)
        measured(CO2, controls.CLEAR_AT)
        line = next((x for x in context(t.say(PUP, report)).splitlines() if f"worker `{WORKER}` reported" in x), "")
        self.assertNotIn("get_usage", line, "every session measured: no session is asked for its usage")
        self.assertIn(f"`{CO2}` at {controls.CLEAR_AT} percent", line, "at the line counts as past it")
        self.assertIn("naming them", line)
        for sid in (WORKER, CO2):
            measured(sid, controls.CLEAR_AT - 20)
        write(os.path.join(t.dir(CO1), phi.USAGE_FILE), '{"at":1,"context":{"window":1000000},"rateLimits":[]}')
        self.assertNotIn(f"worker `{WORKER}` reported", context(t.say(PUP, report)),
                         "every measure under the line, a fresh window among them: no line")
        r = t.hook("session-start", CO1, {"hook_event_name": "SessionStart", "source": "compact"})
        page = f"{copad}/state.md"              # the scratchpad of its first turn, kept across a clear
        self.assertTrue(context(r).startswith("phi (p4-phi): ") and page in context(r).split("\n", 1)[0],
                        context(r)[:300])

    def test_the_publisher_of_a_tree_is_the_issues_coworker_then_the_standing_worker_then_the_puppeteer(self):  # 227
        """ezexe/p4#227: controls.publisher names the one session that publishes the issues of a tree. Under no
        puppeteer that is the tree's orchestrator. Under a puppeteer it is the issues coworker of the puppeteer's
        standing worker once a coworker's brief marks one on record, else the standing worker, else the puppeteer,
        for every session of the puppeteer's own tree and of each tree it controls, in any store."""
        from unittest import mock
        t = self.t

        def publisher(host, proj=None):
            """controls.publisher for a session, read afresh with the env a hook process gets."""
            store = os.path.join(proj or t.proj, ".claude", "p4")
            with mock.patch.dict(os.environ, t.env(host, proj)), mock.patch.dict(phi.RECORDS, clear=True), \
                    mock.patch.dict(controls._SECTIONS, clear=True):
                return controls.publisher(store, phi.load_session(store, host), store)

        def archive(host):
            app = os.path.join(t.app, host + ".json")
            write(app, json.dumps({**json.loads(read(app)), "isArchived": True}))
        everywhere = ((PUP, None), (TOP, None), (KID, None), (TOP2, self.other))
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the exporter")
        t.say(TOP2, "Build the importer", proj=self.other)
        t.say(TOP3, "Something else")
        t.say(KID, "Fix the row")
        self.assertEqual(publisher(KID), (TOP, "Build the narwhal exporter", ""), "a tree under no puppeteer")
        t.cli(PUP, "controls", TOP, TOP2)
        self.assertEqual(publisher(TOP3), (TOP3, "An orchestrator nobody put under the puppeteer", ""))
        pup = (PUP, "Control the exporter and the importer trees, and tell ezexe where each stands", "puppeteer")
        for host, proj in everywhere:
            self.assertEqual(publisher(host, proj), pup, host)
        t.record(WORKER, started_by=PUP, title="Puppeteer's standing worker")
        t.say(WORKER, "Run the puppeteer's checks and counts.\n" + controls.WORKER_BRIEF)
        worker = (WORKER, "Puppeteer's standing worker", "standing worker")
        for host, proj in everywhere + ((WORKER, None),):
            self.assertEqual(publisher(host, proj), worker, host)
        t.record(CO1, started_by=WORKER, title="Check the archives")
        t.record(CO2, started_by=WORKER, title="Draft and publish the issues")
        t.say(CO1, "Check the archives.\nFiles: none")
        self.assertEqual(publisher(KID), worker, "a coworker whose brief lacks the line is no issues coworker")
        t.say(CO2, "Publish each finding that needs an issue.\n" + controls.ISSUES_BRIEF)
        self.assertEqual(t.session(CO2).get("standingGroup"), "issues", "the brief's line marks it on its record")
        coworker = (CO2, "Draft and publish the issues", "issues coworker")
        for host, proj in everywhere + ((WORKER, None), (CO1, None), (CO2, None)):
            self.assertEqual(publisher(host, proj), coworker, host)
        archive(CO2)
        self.assertEqual(publisher(KID), worker, "an issues coworker the app archived publishes nothing")
        archive(WORKER)
        self.assertEqual(publisher(TOP2, self.other), pup, "nor does an archived standing worker")


class TreeAndClicks(unittest.TestCase):
    """The tree in the app is the true tree, and ezexe acts by click where one exists. No start waits behind a busy
    writer, so a puppeteer is named no session that holds a start request of its own and is handed no line for a
    start made on another session's behalf; a session whose first message carries the marker of a request another
    session filed is held under that session, and its tree's ledger names it."""

    FLUSH = "Port the exporter's flush to the new writer and run its suite. Report when done.\nFiles: src/flush.py"
    CROSS = (f"<cross-session-message from=\"{TOP}\">Carry on with the port, and split the flush off into a session of "
             f"its own.</cross-session-message>")
    ASKS = re.compile(r"(?<!without )\bask(?:s|ing)? ezexe\b|\bputs? (?!no\b)(?:[\w\"'`-]+ ){0,4}?to ezexe\b"
                      r"|\bgo(?:es)? to ezexe\b|\boffer(?:s|ed)? (?:\w+ ){0,3}?to ezexe\b"
                      r"|\bwait(?:s|ing)? (?:on|for) (?:a matter of )?ezexe\b"
                      r"|\bezexe's (?:own )?(?:go|approval|answer|pick|choice|say-so|next message)\b"
                      r"|\bezexe (?:has to|must|needs to)\b|\bturn ezexe begins\b|\bto ezexe as ready\b", re.I)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(PUP, title="Control the exporter tree")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(KID, started_by=TOP, title="the flush child")
        write(os.path.join(t.tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": [{"id": "cg-1", "name": "puppeteers"}],
                                                 "assignments": {"code:" + PUP: "cg-1"}}}}}}))
        t.say(PUP, "Control the exporter tree")
        t.say(TOP, "Build the narwhal exporter")
        t.cli(PUP, "controls", TOP)
        t.say(KID, "Port the exporter in pieces")
        t.say(KID, self.CROSS)                     # its parent session's message began this turn: no user_asked start

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_session_holds_a_queued_start_so_a_puppeteer_is_named_none_and_its_board_lists_none(self):
        """The start queued behind a busy writer is gone, and with it the lines only it fed: a puppeteer is handed
        no link to a session that holds start requests, its board has no row for one under Waiting on and no section
        for starts made on another session's behalf, and a controlled session's standing counts none against it."""
        t = self.t
        ctx = context(t.say(PUP, "what is waiting?"))
        self.assertNotIn("hold start requests", ctx)
        self.assertNotIn("on another session's behalf", ctx)
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertNotIn("## Started on another session's behalf", board)
        self.assertNotIn("start request", board.split("## Waiting on")[1].split("\n## ")[0])
        from unittest import mock
        with mock.patch.dict(os.environ, t.env(PUP)), mock.patch.dict(phi.RECORDS, clear=True):
            _, against = controls.standing(t.p4, TOP)
        self.assertEqual([x for x in against if "start request" in x], [])

    def test_a_session_started_for_another_sessions_request_is_held_under_it_and_the_ledger_names_it(self):
        """ezexe/p4#229: the app nests a started session under the session that called the start tool, and no tool
        moves it after. A session whose first message carries the marker of a request another session filed, and no
        line that makes it an orchestrator, is held under the session that filed the request, and the ledger of that
        session's tree names it as started for another, with the call that detaches it."""
        t = self.t
        rid, _ = starts.add(t.p4, KID, "the flush port", self.FLUSH, to=PUP)
        prompt = self.FLUSH + "\n\n" + starts.marker(rid, KID)
        t.record(NEW, started_by=TOP, title="the flush port")     # the app nests it under the session that ran the call
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + prompt)
        self.assertEqual(t.started_by(NEW), (KID, "requested"))
        self.assertEqual(starts.state(t.p4)[rid]["started"], NEW)
        ledger = t.cli(TOP, "ledger").stdout.split("## Reconcile")[1].split("\n## ")[0]
        self.assertIn(f"`{TOP}` started \"the flush port\" `{NEW}` for a start request of `{KID}`, an exception",
                      ledger)
        self.assertIn(f"`mcp__ccd_session_mgmt__detach_session` with `{NEW}` moves it to top level", ledger)
        app = os.path.join(t.app, NEW + ".json")
        write(app, json.dumps({**json.loads(read(app)), "lineageDetached": True}))     # detached to top level
        ledger = t.cli(TOP, "ledger").stdout.split("## Reconcile")[1].split("\n## ")[0]
        self.assertIn(f"for a start request of `{KID}`, an exception: p4-phi holds it under `{KID}`, and the app "
                      f"shows it at top level.", ledger)
        self.assertNotIn("detach_session", ledger)


class LandedWorker(unittest.TestCase):
    """A worker whose work its orchestrator landed under new hashes, and whose issue is closed, is complete."""

    file = Supervisor.file

    def against(self, sid):
        """What p4-phi's records hold against `sid` being complete, as the board and `controls` print it."""
        from unittest import mock
        with mock.patch.dict(os.environ, self.t.env(PUP)),                 mock.patch.dict(phi.RECORDS, clear=True):       # read afresh, with the env a hook process gets
            _, out = controls.standing(self.t.p4, sid)
        return out

    def setUp(self):
        if not shutil.which("git") or not shutil.which("sh"):
            self.skipTest("no git or sh")
        from test_issues import FAKE_GH, GhTree
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = self._tmp.name
        ghdir = os.path.join(tmp, "gh")
        os.makedirs(ghdir)
        write(os.path.join(ghdir, "gh.py"), FAKE_GH)
        write(os.path.join(ghdir, "state.json"), json.dumps({"7": "CLOSED"}))
        os.environ["FAKE_GH_DIR"] = ghdir
        self.addCleanup(os.environ.pop, "FAKE_GH_DIR", None)
        self.t = t = GhTree(tmp, os.path.join(ghdir, "gh.py"))
        t.record(PUP, title="Control the exporter tree")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(KID, started_by=TOP, title="the flush child")
        self.file("puppeteers", PUP)

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def edit(self, path, uuid):
        """The worker edits a file in a turn of its own."""
        with open(path, "a", encoding="utf-8") as f:
            f.write("more = 2\n")
        self.assertEqual(self.t.stop(KID, "edit it", [("Edit", {"file_path": path}, "ok")], uuid=uuid).returncode, 0)

    def worker_closing_7(self):
        """The worker's clone, with a commit of its own that closes #7 and is on no remote branch, its done turn
        recorded, the store's bare origin, and a second clone to land work from. Returns work, bare, land, sha."""
        t = self.t
        work = os.path.join(t.proj, "work").replace("\\", "/")
        bare = os.path.join(t.tmp, "bare.git").replace("\\", "/")
        land = os.path.join(t.tmp, "land").replace("\\", "/")
        write(os.path.join(work, "lib", "x.py"), "x = 1\n")
        write(os.path.join(work, "lib", "y.py"), "y = 1\n")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "one")):
            self.git(work, *args)
        self.git(work, "remote", "add", "origin", "https://github.com/ezexe/demo.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, capture_output=True)
        self.git(work, "push", "-q", bare, "main")
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the exporter")
        t.cli(PUP, "controls", TOP)
        t.say(KID, "Task:\nFix the flush for ezexe/demo#7. Report when done.\nFiles: work/lib/x.py")
        t.hook("plan", KID, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                             "tool_input": {"items": [{"content": "Fix the flush", "status": "completed"},
                                                      {"content": "Tell the parent session", "status": "pending"}]},
                             "tool_response": "Plan updated."})
        self.edit(os.path.join(work, "lib", "x.py"), "c1")
        self.git(work, "commit", "-qam", "lib: fix the flush\n\nCloses #7")
        sha = self.git(work, "rev-parse", "--short", "HEAD")
        t.cli(KID, "done", "the flush is fixed and committed; closes #7")
        self.edit(os.path.join(work, "lib", "y.py"), "c2")
        self.git(work, "checkout", "-q", "--", "lib/y.py")
        subprocess.run(["git", "clone", "-q", bare, land], check=True, capture_output=True)
        return work, bare, land, sha

    def test_a_worker_landed_by_cherry_pick_with_its_issue_closed_is_held_complete(self):
        work, bare, land, sha = self.worker_closing_7()
        write(os.path.join(land, "README.md"), "the exporter\n")
        self.git(land, "add", "-A")
        self.git(land, "commit", "-qm", "docs: a readme")
        self.git(land, "fetch", "-q", work, "main:refs/heads/worker")
        self.git(land, "cherry-pick", sha)                # the orchestrator lands it under a new hash
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertEqual(self.git(work, "branch", "-r", "--contains", sha), "", "its own hash is on no remote branch")
        self.assertEqual(self.against(KID), [])
        import issues
        write(os.path.join(work, "lib", "y.py"), "y = 2\n")
        self.git(work, "commit", "-qam", "lib: tidy y")
        tidy = self.git(work, "rev-parse", "--short", "HEAD")
        self.assertFalse(issues.landed(work, tidy, ["#8"]), "on no remote branch, in no form")
        self.git(land, "fetch", "-q", work, "main:refs/heads/worker")
        self.git(land, "cherry-pick", tidy)
        self.git(land, "commit", "-q", "--amend", "-m", "lib: y is two")     # landed reworded, closing nothing
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertTrue(issues.landed(work, tidy, ["#8"]), "git cherry finds the same change under a new hash")

    def test_a_remote_commit_closing_another_repositorys_issue_of_the_same_number_lands_nothing(self):
        work, bare, land, sha = self.worker_closing_7()
        write(os.path.join(land, "NOTES.md"), "the other repository's fix\n")
        self.git(land, "add", "-A")
        self.git(land, "commit", "-qm", "notes: the parser\n\nFixes ezexe/other#7")
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertIn(f"commit {sha}, which closes #7, is on no remote branch", "; ".join(self.against(KID)),
                      "#7 of ezexe/other is not this repository's #7")
        import issues
        self.assertFalse(issues.landed(work, sha, ["#7"]))
        self.git(land, "commit", "-q", "--allow-empty", "-m", "notes: tidy\n\nFixes ezexe/demo#7")
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertTrue(issues.landed(work, sha, ["#7"]), "this repository's own #7, named whole")


class OpenIssues(unittest.TestCase):
    """ezexe/p4#231: an open issue of a repository a controlled session works in is the puppeteer's to resolve. The
    puppeteer's own watcher lists the open issues at its slow looks, one `gh issue list` a repository, and keeps the
    ones no live session's record holds as `issue`. When a controlled tree closes or a controlled session reports
    done, the puppeteer is handed one line naming each once, beside the running orchestrator whose topic covers it
    or as the start of a new orchestrator, and none of them as a choice of ezexe's. No page of the Claude Code docs
    hands a session a repository's open issues, and the timer the look runs on is the hooks module's:
    https://code.claude.com/docs/en/plugins/mods/api.md, "Run work in the background"."""

    file = Supervisor.file
    COVERED = "The narwhal exporter writes its ports table twice"
    APART = "The lunar calendar widget misreads leap seconds"

    def setUp(self):
        if not shutil.which("git") or not shutil.which("sh"):
            self.skipTest("no git or sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = self._tmp.name
        self.ghdir = os.path.join(tmp, "gh")
        os.makedirs(self.ghdir)
        write(os.path.join(self.ghdir, "gh.py"), FAKE_GH)
        os.environ["FAKE_GH_DIR"] = self.ghdir
        self.addCleanup(os.environ.pop, "FAKE_GH_DIR", None)
        self.t = t = GhTree(tmp, os.path.join(self.ghdir, "gh.py"))
        t.record(PUP, title="Control the exporter and the importer trees")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(TOP2, title="Build the moon importer")
        t.record(KID, started_by=TOP, title="the flush fix")
        self.file("puppeteers", PUP)
        self.work = os.path.join(t.proj, "work").replace("\\", "/")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "one"),
                     ("remote", "add", "origin", "https://github.com/ezexe/demo.git")):
            subprocess.run(["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                           capture_output=True)

    def scene(self, title):
        """A puppeteer that controls two trees, a live worker of the first that holds ezexe/demo#7 as its issue, and
        GitHub listing #7 and #8, the second under `title`."""
        t = self.t
        t.say(PUP, "Control the trees")
        t.say(TOP, "Build the narwhal exporter and its ports table")
        t.say(TOP2, "Build the moon importer")
        t.cli(PUP, "controls", TOP, TOP2)
        t.say(KID, f"Fix ezexe/demo issue #7: the off-by-one in {self.work}/lib/x.py, and commit it.")
        self.assertEqual(t.session(KID)["issue"]["number"], 7, "the worker holds #7 as its issue")
        write(os.path.join(self.ghdir, "open.json"), json.dumps({"ezexe/demo": [
            {"number": 7, "title": "The exporter drops the last row"}, {"number": 8, "title": title}]}))

    def look(self, clock=None, **env):
        """One slow look of the puppeteer's watcher, as the hooks module runs it."""
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look", "--net"],
                       capture_output=True, text=True, env=self.t.env(PUP, **{"P4_PHI_WATCH": "1", **env}),
                       cwd=self.t.proj, timeout=120, clock=clock)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def listings(self):
        with open(os.path.join(self.ghdir, "calls.jsonl"), encoding="utf-8") as f:
            return [c for c in (json.loads(x) for x in f) if c[:2] == ["issue", "list"]]

    def kept(self):
        return json.loads(read(os.path.join(self.t.dir(PUP), "open-issues.json")))["repos"]

    def close(self, host):
        app = os.path.join(self.t.app, host + ".json")
        write(app, json.dumps({**json.loads(read(app)), "isArchived": True}))      # ezexe archived it in the app

    def said(self, ctx):
        """The line that hands the open issues, with the issues it names, '' when the context holds none."""
        at = ctx.find("open on the repositories the controlled sessions work in")
        if at < 0:
            return ""
        start = ctx.rfind("phi (p4-phi): ", 0, at)
        return ctx[start:].split("\n\n", 1)[0]

    def test_the_look_lists_each_repository_once_and_keeps_the_issues_no_live_session_holds(self):
        t = self.t
        self.scene(self.COVERED)
        got = self.look()
        self.assertEqual((got["watching"], got["net"]), (True, True))
        self.assertEqual(self.kept()["ezexe/demo"]["issues"], [{"number": 8, "title": self.COVERED}],
                         "#7, which a live worker's record holds, is dropped")
        self.assertEqual([c[c.index("-R") + 1] for c in self.listings()], ["ezexe/demo"], "one listing a repository")
        self.look()
        self.assertEqual(len(self.listings()), 1, "never more often than the slow reads of GitHub")
        self.look(clock=inproc.Clock(time.time() + puppeteer.ISSUE_TTL_S + 5))
        self.assertEqual(len(self.listings()), 2, "listed again once that long has passed")
        self.look(clock=inproc.Clock(time.time() + 3 * puppeteer.ISSUE_TTL_S), P4_PHI_WATCH_NET="0")
        self.assertEqual(len(self.listings()), 2, "P4_PHI_WATCH_NET=0 keeps the look from GitHub")
        self.look(clock=inproc.Clock(time.time() + 5 * puppeteer.ISSUE_TTL_S), P4_PHI_ISSUES="0")
        self.assertEqual(len(self.listings()), 2, "and so does the issue loop's switch")
        self.assertIn("phi/sessions/*/open-issues.json", relay.IGNORED, "a tracked store keeps the listing out")
        t.say(TOP, "carry on")
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look", "--net"],
                       capture_output=True, text=True, env=t.env(TOP, P4_PHI_WATCH="1"), cwd=t.proj, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(t.dir(TOP), "open-issues.json")), "only a puppeteer's look lists")
        self.assertEqual(len(self.listings()), 2)

    def test_a_closed_tree_hands_the_puppeteer_the_unheld_issue_beside_the_orchestrator_that_covers_it(self):
        t = self.t
        self.scene(self.COVERED)
        self.look()
        self.assertEqual(self.said(context(t.say(PUP, "anything?"))), "", "no tree has closed or reported done")
        self.close(TOP2)
        ctx = context(t.say(PUP, "anything now?"))
        line = self.said(ctx)
        self.assertIn("a boundary: the tree of \"Build the moon importer\" has closed", ctx)
        with self.subTest("the issue no session holds is named beside the orchestrator whose topic covers it"):
            self.assertIn(f"- ezexe/demo#8 \"{self.COVERED}\", https://github.com/ezexe/demo/issues/8: send it to "
                          f"\"Build the narwhal exporter\" `{TOP}`, whose topic covers it", line)
            self.assertNotIn("so start a new orchestrator for it", line, "a start only where no topic covers it")
        with self.subTest("the one a live worker's record holds is not named"):
            self.assertNotIn("ezexe/demo#7", ctx)
        with self.subTest("it says to close what a landed commit covers and to route or start the rest"):
            self.assertIn("close each one a landed commit already covers", line)
            self.assertIn("Send each other one straight to the orchestrator named beside it", line)
            self.assertIn("start a new orchestrator for each one that names none", line)
        with self.subTest("and holds no ask of ezexe for it"):
            self.assertIn("none of them is a question for ezexe", line)
            self.assertIsNone(TreeAndClicks.ASKS.search(line), line)
            for ask in ("AskUserQuestion", "mcp__ccd_turn__wrap_up", "button", "ezexe decides", "ezexe picks"):
                self.assertNotIn(ask, line)
        with self.subTest("each is named once"):
            self.assertEqual(self.said(context(t.say(PUP, "and now?"))), "")
            t.cli(TOP, "done", "its suite ran green")
            t.stop(TOP, "Build the narwhal exporter and its ports table", report="Built.")
            self.assertEqual(self.said(context(t.say(PUP, "a report came in"))), "", "nor at the next report")

    def test_an_issue_no_controlled_topic_covers_is_named_as_the_start_of_a_new_orchestrator(self):
        t = self.t
        self.scene(self.APART)
        self.look()
        t.cli(TOP2, "done", "its suite ran green")
        t.stop(TOP2, "Build the moon importer", report="Built.")       # a controlled session reports done
        line = self.said(context(t.say(PUP, "a report came in")))
        self.assertIn(f"- ezexe/demo#8 \"{self.APART}\", https://github.com/ezexe/demo/issues/8: no running "
                      f"orchestrator's topic covers it, so start a new orchestrator for it", line)
        self.assertNotIn("send it to", line)
        self.assertNotIn("ezexe/demo#7", line)
        self.assertIsNone(TreeAndClicks.ASKS.search(line), line)

    def test_with_the_issue_loop_off_no_issue_is_named(self):
        t = self.t
        self.scene(self.COVERED)
        self.look()
        self.close(TOP2)
        self.assertEqual(self.said(context(t.say(PUP, "anything now?", P4_PHI_ISSUES="0"))), "", "P4_PHI_ISSUES=0")
        relay._write_json(os.path.join(t.p4, "p4.json"), {"phi": {"issues": False}})
        ctx = context(t.say(PUP, "and now?"))
        self.assertEqual(self.said(ctx), "", "phi.issues false")
        self.assertNotIn("ezexe/demo#8", ctx)
        os.remove(os.path.join(t.p4, "p4.json"))
        self.assertIn("ezexe/demo#8", self.said(context(t.say(PUP, "and with the loop on?"))),
                      "the closed tree is counted once the loop is on")


class OneReadAHook(unittest.TestCase):
    """ezexe/p4#216: a puppeteer's message hook asked where a controlled session stands in its reports, its boundary
    and its board, and its Stop hook in the sessions it waits on and its board, each time running git for every
    closing commit and gh for every issue, which took the hooks past their limits. Inside one hook a controlled
    session is read once and every caller gets that answer. A commit found landed and an issue found closed are kept
    in the store's phi/.cache/known.json, so a later hook asks neither git nor gh for them."""

    file = Supervisor.file
    setUp = LandedWorker.setUp
    git = LandedWorker.git
    edit = LandedWorker.edit
    worker_closing_7 = LandedWorker.worker_closing_7

    def landed_scene(self):
        """The worker's closing commit, pushed and on a remote branch of its clone, with #7 closed on GitHub."""
        work, bare, _, sha = self.worker_closing_7()
        self.git(work, "push", "-q", bare, "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        return sha

    def counted(self):
        """controls._standing and issues.landed wrapped to count, with the env a hook process gets."""
        from unittest import mock
        import issues
        reads, gits = [], []
        stood, landed = controls._standing, issues.landed

        def standing(store, sid):
            reads.append(sid)
            return stood(store, sid)

        def asked(path, sha, closes):
            gits.append(sha)
            return landed(path, sha, closes)
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(controls, "_standing", standing))
        stack.enter_context(mock.patch.object(issues, "landed", asked))
        stack.enter_context(mock.patch.dict(os.environ, self.t.env(PUP)))
        stack.enter_context(mock.patch.dict(phi.RECORDS, clear=True))
        self.addCleanup(stack.close)
        return reads, gits

    def test_inside_one_hook_a_session_is_read_once_and_a_landed_commit_is_asked_of_git_once(self):
        sha = self.landed_scene()
        reads, gits = self.counted()
        controls.one_hook(True)
        try:
            answers = [controls.standing(self.t.p4, KID) for _ in range(3)]      # as reports, boundary and board ask
        finally:
            controls.one_hook(False)
        self.assertEqual(reads, [KID], "three callers of one hook, one read")
        self.assertEqual(gits, [sha], "git is asked once for the closing commit")
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(answers[0], answers[2])
        answers[0][1].append("a caller's own line")
        self.assertNotIn("a caller's own line", controls.standing(self.t.p4, KID)[1], "each caller gets its own list")
        known = json.loads(read(os.path.join(self.t.p4, "phi", ".cache", "known.json")))
        self.assertEqual(known["landed"], [sha], "the commit found landed, kept by its sha")
        self.assertEqual(known["closed"], ["ezexe/demo#7"], "the issue found closed, kept by its number")
        del reads[:], gits[:]
        controls.one_hook(True)                              # a later hook
        try:
            again = controls.standing(self.t.p4, KID)
        finally:
            controls.one_hook(False)
        self.assertEqual(reads, [KID], "a later hook reads the session again")
        self.assertEqual(gits, [], "and runs no git for a commit already found landed")
        self.assertEqual(again[0], answers[0][0])
        del reads[:]
        controls.standing(self.t.p4, KID)
        controls.standing(self.t.p4, KID)
        self.assertEqual(reads, [KID, KID], "outside a hook each call reads afresh")

    def test_a_puppeteers_message_hook_and_its_stop_hook_read_each_controlled_session_once(self):
        self.landed_scene()
        reads, _ = self.counted()
        t = self.t
        self.assertEqual(t.say(PUP, "Where does the exporter tree stand?").returncode, 0)
        self.assertLessEqual(reads.count(TOP), 1, "one message hook reads a controlled session at most once")
        said = len(reads)
        self.assertEqual(t.stop(PUP, "Where does the exporter tree stand?", report="it stands").returncode, 0)
        self.assertLessEqual(reads[said:].count(TOP), 1, "one Stop hook reads a controlled session at most once")
        self.assertIsNone(controls._ONE[0], "the memo ends with the hook")


class NativeCalls(unittest.TestCase):
    """Six calls of Claude Code and the desktop app that a line or a field of p4-phi names, each held to the tool's
    own text as a desktop session's transcript of 2026-11-19 holds it."""

    def watch(self, s, states):
        from unittest import mock
        with mock.patch.object(controls, "standing", lambda store, sid: (states[sid][0], [])), \
                mock.patch.object(controls, "last_report", lambda store, sid: (states[sid][1], "")), \
                mock.patch.object(controls, "full_title", lambda sid, s=None: f"The {sid} tree"):
            return controls.idle_watch("", s)

    def test_a_puppeteer_is_told_what_tells_it_of_a_controlled_sessions_turn_end_and_is_handed_no_call(self):
        """Seen on 2026-11-22 in the desktop app on Claude Code 2.1.326, from two sessions: `SendMessage` with
        `notify_when_idle` to another session of the app answered success false, "Nothing was subscribed:
        notify_when_idle is only supported for Claude sessions on this machine in this release", and with a message
        attached "no idle subscription was made". A controlled session is one the app runs, so the line hands no
        such call. It says once, for each controlled session that works, what tells the puppeteer of its turn's
        end: the app's own note for one it started, and nothing for one it did not start, with whether the sweep's
        schedule covers it. A session is named again once it works after a later report."""
        from unittest import mock
        s = {"sessionId": TOP, "controls": [{"sessionId": KID, "store": "x"}, {"sessionId": KID2, "store": "x"}]}
        got = self.watch(s, {KID: ("working", "09:00"), KID2: ("shown done", "08:00")})
        self.assertIn(f"\"The {KID} tree\", {controls.TOLD_BY_NOTHING} {controls.NOT_COVERED}", got,
                      "nobody started it from here, and `phi.upkeep` is off")
        self.assertNotIn(KID2, got, "a session that does not work is not named")
        self.assertEqual(re.findall(r"`to` `[^`]*`", got), [], "no call is handed")
        self.assertEqual(s["idleWatch"], {KID: "09:00"})
        self.assertEqual(self.watch(s, {KID: ("working", "09:00"), KID2: ("shown done", "08:00")}), "", "once")
        self.assertEqual(self.watch(s, {KID: ("shown done", "09:30"), KID2: ("shown done", "08:00")}), "")
        with mock.patch.object(controls, "UPKEEP", True), \
                mock.patch.object(controls, "started_here", lambda home, s, e: e["sessionId"] == KID2):
            again = self.watch(s, {KID: ("working", "09:30"), KID2: ("working", "08:00")})
        self.assertIn(f"\"The {KID} tree\", {controls.TOLD_BY_NOTHING} {controls.COVERED}", again,
                      "it works again after a later report, and with upkeep on the schedule covers it")
        self.assertIn(f"\"The {KID2} tree\", {controls.TOLD_BY_APP}", again,
                      "the app tells the session that started it")
        self.assertEqual(self.watch({"sessionId": TOP}, {}), "", "a session that controls none is handed nothing")

    def test_the_prompt_hook_hands_the_subscription_beside_the_boundary(self):
        src = read(os.path.join(SRC, "phi.py"))
        at = src.index("edge = controls.boundary(me.home, s)")
        self.assertIn("watch = controls.idle_watch(me.home, s)", src[at:at + 700])

    def test_a_start_that_runs_at_once_passes_wake_when_done_and_no_card_does(self):
        """start_session's schema: true "also continues you if this session never gets its task some other way,
        such as a brief that is not sent; default false; not with own_initiative"."""
        draft = {"title": "the ports table", "context": "fresh", "brief": "Write the last row.\nFiles: a.py",
                 "background": "b" * 90, "parent": TOP}
        for d in (draft, {**draft, "parent": ""}, {**draft, "context": "fork"}):
            call = puppeteer.call_of(d)
            self.assertEqual((call["initiation"], call["wake_when_done"]), ("user_asked", True))
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "proj", ".claude", "p4")
            call = controls.request_call({"store": store, "requester": KID, "id": "rq-1", "title": "the exporter",
                                          "brief": "Orchestrate the exporter.\nFiles: b.py", "background": "b" * 90})
        self.assertEqual((call["initiation"], call["wake_when_done"]), ("user_asked", True))
        self.assertTrue(call["cwd"])

    def test_the_request_line_names_list_start_targets_before_a_start_that_passes_cwd(self):
        """list_start_targets' text: "Call it before a start_session that names a host, folder, environment or
        preset, so the name you pass is one of these; never guess one"."""
        from unittest import mock
        row = {"id": "rq-1", "title": "the exporter", "requester": KID, "store": "x"}
        with mock.patch.object(controls, "requests_for", lambda s: [row]), \
                mock.patch.object(controls, "request_call", lambda r: {"cwd": "D:/proj", "title": r["title"]}), \
                mock.patch.object(controls, "full_title", lambda sid, s=None: "The kid"), \
                mock.patch.object(controls, "filing", lambda store, s: "the section \"work\""):
            got = controls.requests_text("", {"sessionId": TOP})
        self.assertIn("\"cwd\": \"D:/proj\"", got)
        self.assertLess(got.index("`mcp__ccd_session__list_start_targets`"), got.index("exactly the call given"))
        self.assertIn("never guessed", got)

    def test_the_request_line_says_where_a_sections_id_comes_from(self):
        """`move_sessions` takes a section's id and no name, and the app's `list_sections` and `list_groups` answer
        the ids, so the line of the requests names the two beside it."""
        from unittest import mock
        how = ("which takes the section's id as `mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` "
               "answers it, never in")
        row = {"id": "rq-1", "title": "the exporter", "requester": KID, "store": "x"}
        with mock.patch.object(controls, "requests_for", lambda s: [row]), \
                mock.patch.object(controls, "request_call", lambda r: {"cwd": "D:/proj", "title": r["title"]}), \
                mock.patch.object(controls, "full_title", lambda sid, s=None: "The kid"), \
                mock.patch.object(controls, "filing", lambda store, s: "the section \"work\""):
            got = controls.requests_text("", {"sessionId": TOP})
        self.assertIn("then file it with `mcp__ccd_sidebar__move_sessions` where named, " + how
                      + " the section this session is filed in", got)

    def test_the_page_of_the_puppeteer_says_the_rule_as_controls_hands_it(self):
        """The script of docs/puppeteer.html shows the rule a puppeteer is told once. Its function RULE holds the
        words of controls.RULE as rule_text fills them where `phi.upkeep` is off, with the page's own names for the
        section, the command, the board and the restated task, so the two tools that answer a section's id stand
        beside `move_sessions` there too."""
        page = read(os.path.join(SRC, "..", "..", "..", "..", "docs", "puppeteer.html"))
        names = {"section": "SECTION", "cmd": "PHI", "board": "boardPath()", "restate": "RESTATE"}
        text = "phi (p4-phi): " + controls.RULE.format(
            worker=controls.WORKER_BRIEF, archives=controls.ARCHIVES[0], asks=controls.ARCHIVES[1],
            **{key: "\x00" + name + "\x00" for key, name in names.items()})
        parts = text.split("\x00")                 # words and names by turns, joined as the script joins them
        said = "+".join(part if i % 2 else json.dumps(part, ensure_ascii=False) for i, part in enumerate(parts))
        self.assertIn("\nfunction RULE(){return " + said + "}\n", page)
        self.assertIn('var RESTATE=' + json.dumps(phi.RESTATE) + ";", page)


class SidebarTools(unittest.TestCase):
    """Unless phi.json turns `app_tools` off, the plugin's hooks module asks the desktop app's own tools and leaves
    the answers in app.json: the sidebar group of the session and of each session linked to it, from `get_session`
    and `list_sessions`, and for a puppeteer the sections with their ids, from `list_sections` or `list_groups`.
    The filing is read from those answers first, and from the app's own file, `claude_desktop_config.json`, for a
    session they do not answer. With the setting off the file is read as before."""

    SECTIONS = [{"id": "pinned", "kind": "builtin", "name": "", "order": 0},
                {"id": "sessions", "kind": "builtin", "name": "", "order": 1},
                {"id": "cg-9", "kind": "manual", "name": "importers", "order": 2, "session_count": 1, "shown": True}]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        self.other = os.path.join(t.tmp, "other")
        self.store2 = os.path.join(self.other, ".claude", "p4")
        os.makedirs(self.store2)
        t.record(PUP, title="Run the trees")
        t.record(TOP2, title="Build the importer", cwd=self.other)

    def tearDown(self):
        self._tmp.cleanup()

    def answers(self, group=..., linked=None, sections=None):
        """What the module writes for the puppeteer's CLI session: its own answer of `get_session` with `group`, the
        rows of `list_sessions`, and the sections of the sidebar."""
        write(os.path.join(self.t.p4, "p4.json"), "{}\n")
        own = {"sessionId": PUP, "title": "Run the trees", "cwd": self.t.proj, **({} if group is ... else {"group": group})}
        d = {"at": 0, "self": own, **({"sessions": linked} if linked is not None else {}),
             **({"sections": sections} if sections is not None else {})}
        write(os.path.join(phi.rows.origin_dir(self.t.proj, CLI[PUP]), phi.APP_FILE), json.dumps(d) + "\n")

    def file(self, **sections):
        """The app's own file: each session filed in the section its keyword names."""
        groups = [{"id": f"cg-f{k}", "name": name} for k, name in enumerate(sorted(set(sections.values())))]
        ids = {g["name"]: g["id"] for g in groups}
        write(os.path.join(self.t.tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": groups, "assignments": {
                "code:" + sid: ids[name] for sid, name in sections.items()}}}}}}))

    def look(self, host, **env):
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look"],
                       capture_output=True, text=True, cwd=self.t.proj, timeout=60,
                       env=self.t.env(host, P4_PHI_WATCH="1", P4_PHI_WATCH_NET="0", **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_puppeteer_is_known_by_the_group_the_tools_answered_with_no_file_of_the_apps(self):
        t = self.t
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "nothing says where it is filed")
        self.answers(group={"id": "cg-1", "name": "Puppeteers"})
        self.assertEqual(t.cli(PUP, "controls").returncode, 0)
        self.answers(group={"id": "cg-2", "name": "wrappin up"})
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "another section marks nothing")

    def test_a_group_the_tools_answered_stands_over_the_file_and_one_they_left_out_is_the_files(self):
        t = self.t
        self.file(**{PUP: "puppeteers"})
        self.answers(group=None)
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "the tools answered it filed in no section")
        self.answers()
        self.assertEqual(t.cli(PUP, "controls").returncode, 0, "no `group` in the answer: the app's file says")
        self.answers(group=None, linked=[])
        self.assertEqual(t.cli(TOP2, "controls", proj=self.other).returncode, 2,
                         "and a session of another CLI id reads no answer of this one's")

    def test_a_look_asks_for_the_sections_only_for_a_puppeteer_and_not_with_the_setting_off(self):
        t = self.t
        self.file(**{PUP: "puppeteers"})
        t.say(PUP, "Run the trees")
        t.record(TOP, title="top")
        t.say(TOP, "Build the exporter")
        off = {"P4_PHI_APP_TOOLS": "0"}
        self.assertIs(self.look(PUP).get("app_sections"), True, "the setting is on where a store sets nothing")
        self.assertNotIn("app_sections", self.look(PUP, **off))
        self.assertNotIn("app_tools", self.look(PUP, **off))
        self.assertIs(self.look(TOP).get("app_tools"), True)
        self.assertNotIn("app_sections", self.look(TOP), "an orchestrator filed nowhere")

    def started(self):
        """The puppeteer controls an orchestrator of the other project and starts a new one there -> its lines."""
        t = self.t
        t.say(PUP, "Run the trees")
        t.say(TOP2, "Build the importer", proj=self.other)
        self.assertEqual(t.cli(PUP, "controls", TOP2).returncode, 0)
        t.record(NEW, started_by=PUP, title="the retry", cwd=self.other)
        t.say(NEW, "Task:\n" + BRIEF + "\n" + phi.NEW_TOP_BRIEF, proj=self.other)
        return context(t.say(PUP, "and now?"))

    def test_the_filing_line_names_the_sections_id_as_a_linked_sessions_group_gives_it(self):
        self.answers(group={"id": "cg-1", "name": "puppeteers"},
                     linked=[{"sessionId": TOP2, "title": "Build the importer", "cwd": self.other,
                              "group": {"id": "cg-7", "name": "importers"}}])
        ctx = self.started()
        self.assertIn(f"\"the retry\" `{NEW}` is an orchestrator this puppeteer started, so it is controlled", ctx)
        self.assertIn("File it in the section \"importers\" of the id `cg-7` with `mcp__ccd_sidebar__move_sessions`, "
                      "which takes the section's id as `mcp__ccd_sidebar__list_sections` or "
                      "`mcp__ccd_sidebar__list_groups` answers it, never in \"puppeteers\"", ctx)

    def test_the_filing_line_names_the_id_the_sections_list_gives_for_a_section_the_file_names(self):
        self.file(**{TOP2: "importers"})
        self.answers(group={"id": "cg-1", "name": "puppeteers"}, sections=self.SECTIONS)
        self.assertIn("File it in the section \"importers\" of the id `cg-9` with", self.started())

    def test_the_groups_list_serves_for_the_sections_and_no_list_leaves_the_id_to_the_two_tools(self):
        self.file(**{TOP2: "importers"})
        self.answers(group={"id": "cg-1", "name": "puppeteers"},
                     sections=[{"id": "cg-4", "name": "Importers", "session_count": 1, "order": 0}])
        self.assertIn("File it in the section \"importers\" of the id `cg-4` with", self.started())

    def test_with_no_answer_of_the_tools_the_line_names_the_section_and_the_two_tools(self):
        self.file(**{PUP: "puppeteers", TOP2: "importers"})
        self.assertIn("File it in the section \"importers\" with `mcp__ccd_sidebar__move_sessions`, which takes the "
                      "section's id as `mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` answers "
                      "it, never in \"puppeteers\"", self.started())


if __name__ == "__main__":
    unittest.main(verbosity=1)
