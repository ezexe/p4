#!/usr/bin/env python3
"""controls.py: a puppeteer and the sessions it controls, run through p4-phi's own hooks.

ezexe files an orchestrator in the sidebar section "puppeteers", which makes it a puppeteer. It controls
the orchestrators of other trees, in any store: p4-phi reads the filing from the app's own file, keeps the
record of the sessions it controls, tells each controlled session, writes the puppeteer's board, leaves its
waiting steps with it, names the sessions its records hold complete and leaves their archive to the app's approval
card, names a boundary once with the line that keeps what its board lacks and no compact question,
and carries a controlled session's request for a new orchestrator to it. A queued start stays with the session
that filed it, which waits on ezexe by a button, and its puppeteer names that session as a link and is
handed no start call for it; a start the puppeteer makes on another session's behalf is held under that
session and named for detaching to top level; and every ask of ezexe in the lines a session is handed offers a click.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import inproc  # noqa: E402
import phi  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
import controls  # noqa: E402
from test_phi import CLI, KID, KID2, TOP, Tree, context, memory, read, transcript, write  # noqa: E402
from test_phi import PROMPT, START as SESSION_START  # noqa: E402

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

    def test_the_complete_line_is_never_the_piece_held_when_the_ended_turn_lines_fill_the_room(self):
        """ezexe/p4#68, by 8bf3e26: a notice that asks a session to act now is never held. Five reports whose first
        lines run to the 200 characters a line quotes overflow the default 4000; the line naming the complete
        sessions is there whole, and an informational piece goes to held.md."""
        t = self.t
        t.record(TOP4, title="Build the ports table")
        t.record(TOP5, title="Build the moon format reader")
        five = [TOP, TOP2, TOP3, TOP4, TOP5]
        for sid in five:
            self.finish(sid, proj=self.other if sid == TOP2 else None, report="Built. " + "the suite ran green " * 12)
        t.say(PUP, "Control the five trees")
        t.cli(PUP, "controls", *five)
        ctx = context(t.say(PUP, "five reports came in"))
        self.assertIn("did not fit in its 4000 beside one prompt", ctx, "the room overflows")
        line = ctx.split("p4-phi's records hold these sessions this puppeteer controls complete", 1)[1].split("\n")[0]
        for sid in five:
            self.assertIn(f"`{sid}`", line)
        self.assertIn("approval card", line, "the line whole")
        with open(relay.held_path(t.p4, PUP), encoding="utf-8") as f:
            held = f.read()
        self.assertNotIn("this puppeteer controls complete", held, "the line is not held")
        self.assertTrue(any(m in held for m in ("ended turns. Each is one line", "set these sessions' effort")), held)

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
        self.assertIn("worker", context(self.plan(TOP3, *steps)), "any other orchestrator")
        ctx = context(self.plan(PUP, *steps))
        self.assertNotIn("worker", ctx)
        self.assertNotIn("start_session", ctx)
        self.assertFalse(os.path.exists(os.path.join(t.p4, "phi", ".nudge", CLI[PUP])), "and no nudge")
        t.say(TOP, "Build it")                      # a controlled session, mid-turn
        t.cli(PUP, "controls", TOP)
        r = t.stop(PUP, "Control the two trees", report="Waiting on \"Build the narwhal exporter\".")
        self.assertEqual(r.stdout.strip(), "", "its turn may end while it waits")
        self.assertEqual(t.log(PUP)[-1].get("waits_on"), 1)
        t.cli(TOP, "done", "its suite ran green")
        t.stop(TOP, "Build it", report="Built.")
        t.say(PUP, "a report came in")
        r = t.stop(PUP, "a report came in", report="Read it.", uuid="u1")
        self.assertEqual(json.loads(r.stdout).get("decision"), "block", "nobody left to wait on: back to the step")
        r = t.stop(TOP3, "Control the two trees", report="Waiting.")
        self.assertEqual(json.loads(r.stdout).get("decision"), "block",
                         "an orchestrator outside the section is sent back to its step")

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
        for name in ("CHARS", "COMPACTIONS", "ceiling", "handed_chars"):
            self.assertFalse(hasattr(controls, name), f"controls.{name} counts toward no question")
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
        self.assertIn("File it in the section \"importers\" with `mcp__ccd_sidebar__move_sessions`, never in "
                      "\"puppeteers\"", ctx)
        self.assertIn(NEW, [e["sessionId"] for e in t.session(PUP)["controls"]])
        self.assertIn("This session is controlled by a puppeteer", context(t.say(NEW, "carry on",
                                                                                          proj=self.other)))

    def test_a_controlled_sessions_refused_start_says_this_session_is_controlled_by_a_supervisor_session(self):
        """Run through `recall-hook.sh lookup-check`, the entry hooks.json runs before every tool call."""
        t = self.t
        t.say(TOP, "Build the exporter")
        t.cli(PUP, "controls", TOP)
        t.say(TOP, "carry on")
        body = {"session_id": CLI[TOP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": START,
                "tool_input": {"initiation": "user_asked", "title": "the retry",
                               "prompt": BRIEF + "\n" + phi.NEW_TOP_BRIEF}, "tool_use_id": "toolu_start01"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
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

    def test_a_go_to_a_waiting_writer_is_warned_about_while_another_controlled_session_holds_its_files(self):
        """A go to a writer whose files another controlled session still holds is warned about once for that go and
        its holders."""
        t = self.t
        t.say(TOP, "Task:\nBuild the exporter's flush.\nFiles: src/flush.py, src/writer.py")
        t.say(TOP3, "Task:\nBuild the retry on the same writer.\nFiles: src/writer.py")
        t.say(PUP, "Control the trees")
        t.cli(PUP, "controls", TOP, TOP3)

        def go(to, message="Go: your files are free now."):
            r = t.hook("go-guard", PUP, {"hook_event_name": "PreToolUse", "tool_name": "SendMessage",
                                         "tool_input": {"to": to, "message": message}})
            self.assertEqual(r.returncode, 0, r.stderr)
            return context(r)
        said = go(TOP3)
        self.assertIn("this go to \"An orchestrator nobody put under the puppeteer\" is early", said)
        self.assertIn(f"\"Build the narwhal exporter\" `{TOP}` holds ", said, "the holder by its full title")
        self.assertIn("writer.py", said)
        self.assertIn(" files --release`", said)
        self.assertEqual(go(TOP3), "", "said once for this go and its holders")
        self.assertEqual(go(KID), "", "a session it does not control is not its go")
        self.assertEqual(t.cli(TOP, "files", "src/flush.py").returncode, 0)
        s = t.session(PUP)
        relay._write_json(os.path.join(t.dir(PUP), "session.json"), {**s, "goWarned": []})
        self.assertEqual(go(TOP3), "", "released: the go is free")
        self.assertIn("flush.py", go(TOP3, "Go.\nFiles: src/flush.py"), "the write set the message declares is read")

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
        """One PreToolUse call through `recall-hook.sh lookup-check`, as hooks.json runs it: the reason or the
        context it hands, '' for none."""
        t = self.t
        self._pre = getattr(self, "_pre", 0) + 1
        body = {"session_id": CLI[host], "cwd": proj or t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": f"toolu_pre{self._pre:04d}", **more}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
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
        import p4conf
        self.assertIn("mcp__ccd_session_mgmt__set_session_model", p4conf.DENY_RULES, "the app's deny rule refuses it")
        said, out = self.pre(PUP, "mcp__ccd_session_mgmt__set_session_model",
                             {"session_id": TOP, "model": "claude-haiku-5-5"})
        self.assertNotIn("permissionDecision", out, "p4-phi keeps no refusal of its own")
        self.assertIn("set_session_effort", controls.RULE)
        self.assertIn("only on the start call", controls.RULE)

    def test_a_worker_under_a_puppeteer_hands_up_a_pages_path_and_counts_and_never_publishes(self):   # 226
        t = self.t
        t.say(PUP, "Control the trees")
        self.assertIn("short table or list", controls.RULE)
        t.record(NEW, started_by=PUP, title="Puppeteer's standing worker")
        ctx = context(t.say(NEW, "Run the puppeteer's archive checks and counts.\n" + controls.WORKER_BRIEF))
        self.assertIn("page's path and its counts", ctx)
        self.assertIn("never the page's text", ctx)
        self.assertIn("Artifact", ctx)
        self.assertIn("unless ezexe asks", ctx)

    def test_a_puppeteers_turns_hold_messages_and_its_standing_worker_does_the_rest(self):          # 211
        t = self.t
        t.say(PUP, "Control the trees")
        rule = controls.RULE
        self.assertIn("turns hold messages only", rule)
        self.assertIn("one standing worker", rule)
        self.assertNotIn("comms worker", rule)
        self.assertNotIn("read-only checks of their results against git and GitHub", rule)
        self.assertIn("relays none of these to ezexe", rule)
        self.assertIn("checks the orchestrators and its own worker", rule)
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
        r = t.hook("session-start", CO1, {"hook_event_name": "SessionStart", "source": "compact"})
        page = f"{copad}/state.md"              # the scratchpad of its first turn, kept across a clear
        self.assertTrue(context(r).startswith("phi (p4-phi): ") and page in context(r).split("\n", 1)[0],
                        context(r)[:300])

class TreeAndClicks(unittest.TestCase):
    """The tree in the app is the true tree, and ezexe acts by click where one exists. A start a child queued behind
    a busy writer is made by the child itself once that writer is free: a turn ezexe did not begin hands it the
    app's suggested task card and no blocked wrap-up; its puppeteer names the child as a link with the count it
    holds and is handed no start call for it; a start the puppeteer makes on the child's behalf anyway is held
    under the child in p4-phi, named for detaching to top level and kept on the board as an exception; a start any
    other session makes on the child's behalf gets the same line and is named in its tree's ledger; and every
    ask of ezexe in the lines the session modules hand a session offers a click."""

    FLUSH = "Port the exporter's flush to the new writer and run its suite. Report when done.\nFiles: src/flush.py"
    FREE = "local_wrt00000"       # a writer the store holds no session of, so what is queued behind it is free to go
    CROSS = (f"<cross-session-message from=\"{TOP}\">Carry on with the port, and split the flush off into a session of "
             f"its own.</cross-session-message>")
    MODULES = ("starts.py", "puppeteer.py", "controls.py", "phi.py", "relay.py", "plans.py")
    ASKS = re.compile(r"(?<!without )\bask(?:s|ing)? ezexe\b|\bputs? (?!no\b)(?:[\w\"'`-]+ ){0,4}?to ezexe\b"
                      r"|\bgo(?:es)? to ezexe\b|\boffer(?:s|ed)? (?:\w+ ){0,3}?to ezexe\b"
                      r"|\bwait(?:s|ing)? (?:on|for) (?:a matter of )?ezexe\b"
                      r"|\bezexe's (?:own )?(?:go|approval|answer|pick|choice|say-so|next message)\b"
                      r"|\bezexe (?:has to|must|needs to)\b|\bturn ezexe begins\b|\bto ezexe as ready\b", re.I)
    CLICKS = re.compile(r"mcp__ccd_turn__wrap_up|AskUserQuestion|multiple-choice question|\bbuttons?\b"
                        r"|\bpress(?:es|ed)?\b|\bclicks?\b|\bcards?\b|\]\(#|\blinks?\b|`archive`|`new_session`", re.I)
    TYPED = re.compile(r"\bfor ezexe to type\b|\bezexe types\b", re.I)
    NO_CLICK = re.compile(r"\bno (?:click|button)\b", re.I)
    SENTENCE = re.compile(r"(?<=[.!?:;])\s+(?=[A-Z`\"(])")

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
        starts.add(t.p4, KID, "the flush port", self.FLUSH, after=self.FREE)
        self.row = starts.pending(t.p4)[0]

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_childs_queued_start_is_a_card_there_and_its_puppeteer_gets_a_link_and_no_call(self):
        t = self.t
        with self.subTest("a turn ezexe did not begin hands the child the card's exact call and no blocked wrap-up"):
            said = context(t.say(KID, self.CROSS))
            self.assertIn("propose each as a suggested task card", said)
            self.assertIn("\"initiation\": \"own_initiative\"", said)
            self.assertNotIn("mcp__ccd_turn__wrap_up", said)
            self.assertNotIn("`blocked`", said)
        ctx = context(t.say(PUP, "what is waiting?"))
        with self.subTest("its puppeteer's next turn names the child as a link with the count it holds"):
            self.assertIn(f"- [the flush child](#{KID}): 1 start request", ctx)
            self.assertIn("Start none of them here", ctx)
        with self.subTest("and drafts no start call for the puppeteer"):
            self.assertNotIn(START, ctx)
            self.assertNotIn(self.row["id"], ctx)
        with self.subTest("the board names the child as a link with the count it holds"):
            waiting = read(os.path.join(t.dir(PUP), "board.md")).split("## Waiting on")[1].split("\n## ")[0]
            self.assertIn(f"- [the flush child](#{KID}) holds 1 start request", waiting)
            self.assertIn("starts the suggested task card it shows", waiting)
        with self.subTest("a turn ezexe begins in the child hands it the exact call of a start"):
            line = context(t.say(KID, "How is the port coming?"))
            call = json.loads(line.split(f"`{START}` with ", 1)[1].split("\n", 1)[0])
            self.assertEqual(call["initiation"], "user_asked")
            self.assertIn(starts.marker(self.row["id"], KID), call["prompt"])

    def test_a_supervisor_sessions_start_of_a_childs_request_is_held_under_the_child_and_named_for_detaching(self):
        t = self.t
        call = starts.call_of(self.row, t.p4)
        body = {"session_id": CLI[PUP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": START,
                "tool_input": call, "tool_use_id": "toolu_behalf01"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(PUP))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}
        said = out.get("additionalContext", "")
        with self.subTest("the start goes through, made on the child's behalf, with the detach to follow"):
            self.assertNotEqual(out.get("permissionDecision"), "deny")
            self.assertIn(f"start request {self.row['id']} of [the flush child](#{KID})", said)
            self.assertIn("`mcp__ccd_session_mgmt__detach_session`", said)
        t.record(NEW, started_by=PUP, title="the flush port")     # the app nests it under the session that ran the call
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + call["prompt"])
        with self.subTest("p4-phi holds the new session under the child that filed the request"):
            self.assertEqual(t.started_by(NEW), (KID, "requested"))
        ctx = context(t.say(PUP, "what came in?"))
        with self.subTest("its puppeteer is told to detach it to top level in the app"):
            self.assertIn(f"[the flush port](#{NEW})", ctx)
            self.assertIn(f"call `mcp__ccd_session_mgmt__detach_session` with `{NEW}`", ctx)
        with self.subTest("and the board names it as an exception"):
            made = read(os.path.join(t.dir(PUP), "board.md")).split("## Started on another session's behalf")[1]
            made = made.split("\n## ")[0]
            self.assertIn(f"[the flush port](#{NEW})", made)
            self.assertIn(f"[the flush child](#{KID})", made)
            self.assertIn("nests it under this puppeteer", made)
        app = os.path.join(t.app, NEW + ".json")
        write(app, json.dumps({**json.loads(read(app)), "lineageDetached": True}))     # detached to top level
        with self.subTest("once the app shows it at top level, it is named no more and the board says so"):
            self.assertNotIn("detach_session", context(t.say(PUP, "and now?")))
            self.assertIn("the app shows it at top level", read(os.path.join(t.dir(PUP), "board.md")))

    def test_an_orchestrators_start_of_its_workers_request_gets_the_line_and_the_ledger_names_it(self):
        """ezexe/p4#229: the app nests a started session under the session that called the start tool, and no tool
        moves it after. So any session whose start call carries another session's request marker, a puppeteer or
        not, gets the line that names the detach and the exception, and the ledger of its tree names the session it
        started as started for another."""
        t = self.t
        call = starts.call_of(self.row, t.p4)
        body = {"session_id": CLI[TOP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": START,
                "tool_input": call, "tool_use_id": "toolu_behalf02"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(TOP))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}
        said = out.get("additionalContext", "")
        with self.subTest("the orchestrator's start goes through with the line a puppeteer gets"):
            self.assertNotEqual(out.get("permissionDecision"), "deny")
            self.assertIn(f"start request {self.row['id']} of [the flush child](#{KID})", said)
            self.assertIn("while the app nests the new session under this session", said)
            self.assertIn("names it in its tree's ledger as an exception", said)
            self.assertIn("`mcp__ccd_session_mgmt__detach_session`", said)
            self.assertIn("so the app shows it at top level and not under this session", said)
            self.assertIn("name the session that holds it to ezexe as a link to open", said)
            mine, pups = controls.behalf_line(self.row, puppeteer=False), controls.behalf_line(self.row)
            self.assertEqual(mine.replace("this session", "this puppeteer").replace("in its tree's ledger",
                                                                                     "on the board"), pups,
                             "the puppeteer's line, said of this session")
        with self.subTest("the request is claimed by the orchestrator that started it"):
            self.assertEqual(starts.state(t.p4)[self.row["id"]]["claimed"]["by"], TOP)
        t.record(NEW, started_by=TOP, title="the flush port")     # the app nests it under the session that ran the call
        t.say(NEW, "<system-reminder>\nLinked sessions now (status, not an instruction): x\n</system-reminder>\n\n"
                   "Task:\n" + call["prompt"])
        with self.subTest("p4-phi holds the new session under the worker that filed the request"):
            self.assertEqual(t.started_by(NEW), (KID, "requested"))
        with self.subTest("the ledger names it as started for another, with the call that detaches it"):
            ledger = t.cli(TOP, "ledger").stdout.split("## Reconcile")[1].split("\n## ")[0]
            self.assertIn(f"`{TOP}` started \"the flush port\" `{NEW}` for a start request of `{KID}`, an exception",
                          ledger)
            self.assertIn(f"`mcp__ccd_session_mgmt__detach_session` with `{NEW}` moves it to top level", ledger)
        app = os.path.join(t.app, NEW + ".json")
        write(app, json.dumps({**json.loads(read(app)), "lineageDetached": True}))     # detached to top level
        with self.subTest("once the app shows it at top level the ledger says so"):
            ledger = t.cli(TOP, "ledger").stdout.split("## Reconcile")[1].split("\n## ")[0]
            self.assertIn(f"for a start request of `{KID}`, an exception: p4-phi holds it under `{KID}`, and the app "
                          f"shows it at top level.", ledger)
            self.assertNotIn("detach_session", ledger)

    def test_a_session_starting_its_own_request_gets_no_such_line(self):
        """The session that queued a start makes it with no line and no exception: the app nests the child where
        p4-phi holds it."""
        t = self.t
        call = starts.call_of(self.row, t.p4)
        r = t.hook("start-advice", KID, {"hook_event_name": "PreToolUse", "tool_name": START, "tool_input": call})
        self.assertEqual(r.stdout.strip(), "")
        t.record(NEW, started_by=KID, title="the flush port")
        t.say(NEW, "Task:\n" + call["prompt"])
        self.assertEqual(t.started_by(NEW)[0], KID)
        self.assertNotIn("for a start request of", t.cli(TOP, "ledger").stdout)

    def test_every_ask_of_ezexe_in_the_lines_a_session_is_handed_offers_a_click(self):
        """Each sentence of the strings these modules can hand a session that asks ezexe for a choice, a go or an
        approval carries a click form, in it or in the sentence after it: a wrap-up question with buttons, an
        AskUserQuestion with options, the app's own actions, a suggested task card, or a session named as a link. A
        sentence that has ezexe type says why no click can carry the answer. Docstrings, subscripts, keys and the
        first argument of get, pop, setdefault and compile are left aside, as the banned-names scan of test_phi.py
        leaves them."""
        bare = []
        for name in self.MODULES:
            tree, skip = ast.parse(read(os.path.join(HERE, name))), set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                    skip.add(id(n.body[0].value))
                elif isinstance(n, ast.Subscript):
                    skip.add(id(n.slice))
                elif isinstance(n, ast.Dict):
                    skip.update(id(k) for k in n.keys if k is not None)
                elif isinstance(n, ast.Call) and n.args and getattr(n.func, "attr", "") in ("get", "pop", "setdefault",
                                                                                            "compile"):
                    skip.add(id(n.args[0]))
            for st in ast.walk(tree):
                if not isinstance(st, ast.stmt) or hasattr(st, "body"):
                    continue                       # a statement that holds statements is read through them
                parts = sorted((n.lineno, n.col_offset, n.value) for n in ast.walk(st) if isinstance(n, ast.Constant)
                               and isinstance(n.value, str) and id(n) not in skip)
                said = self.SENTENCE.split(" ".join("".join(p[2] for p in parts).split()))
                for k, s in enumerate(said):
                    if self.ASKS.search(s) and not (self.NO_CLICK.search(s) or any(
                            self.CLICKS.search(x) for x in said[k:k + 2])):
                        bare.append(f"{name}:{st.lineno}: {s[:240]}")
                    elif self.TYPED.search(s) and not self.NO_CLICK.search(s):
                        bare.append(f"{name}:{st.lineno}, typed text with no reason: {s[:240]}")
        self.assertEqual(bare, [], "asks of ezexe with no click form beside them:\n" + "\n".join(bare))


class Waits(unittest.TestCase):
    def test_keep_going_lets_a_waiting_step_end_the_turn_only_with_someone_to_wait_on(self):
        import plans
        with tempfile.TemporaryDirectory() as home:
            s = {"sessionId": "local_p"}
            relay._write_json(os.path.join(relay._dir(home, "local_p"), "session.json"), s)
            relay._write_json(os.path.join(relay._dir(home, "local_p"), "plan.json"), {"steps": [
                {"addr": "1", "content": "Await reports from A, B and C", "status": "in_progress"},
                {"addr": "2", "content": "Check the trees' results against GitHub", "status": "pending"}]})
            self.assertEqual(plans.keep_going(home, s, "Waiting on A.", [], "t1", waits=["A"]), "")
            self.assertIn("is still in_progress", plans.keep_going(home, s, "Waiting on A.", [], "t1"))
            relay._write_json(os.path.join(relay._dir(home, "local_p"), "plan.json"), {"steps": [
                {"addr": "1", "content": "Rewrite the exporter", "status": "in_progress"}]})
            self.assertIn("is still in_progress", plans.keep_going(home, s, "Not yet.", [], "t2", waits=["A"]),
                          "a step that is work is not a wait")


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
