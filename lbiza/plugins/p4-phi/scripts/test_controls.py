#!/usr/bin/env python3
"""controls.py: a supervisor session and the sessions it controls, run through p4-phi's own hooks.

ezexe files a top-level session in the sidebar section "puppeteers", which makes it a supervisor session. It controls
the top-level sessions of other trees, in any store: p4-phi reads the filing from the app's own file, keeps the
record of the sessions it controls, tells each controlled session, writes the supervisor session's board, leaves its
waiting steps with it, lets it archive only what ezexe picks, names a boundary once as a question with two buttons,
and carries a controlled session's request for a new top-level session to it.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
from test_phi import CLI, KID, TOP, Tree, context, read, transcript, write  # noqa: E402

PUP, PUP2, TOP2, TOP3, NEW = ("local_pup00001", "local_pup00002", "local_top00002", "local_top00003",
                              "local_new00001")
for k, sid in enumerate((PUP, PUP2, TOP2, TOP3, NEW)):
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
        t.record(TOP3, title="A top session nobody put under the puppeteer")
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

    def archive(self, by, target, reason=WHY, picks=None, prompt="what is ready?"):
        """The archive hook for `by`'s call on `target`. With `picks`, the turn holds an answered multiple-choice
        question carrying those labels; `prompt` is the message that began the turn."""
        inp = {"session_id": target, **({"reason": reason} if reason else {})}
        calls = [] if picks is None else [("AskUserQuestion", {"questions": []},
                                           "User has answered your questions: " + ", ".join(f'"{p}"' for p in picks))]
        self._n = getattr(self, "_n", 0) + 1
        path = transcript(os.path.join(self.t.tmp, f"{by}arch{self._n}.jsonl"), prompt, calls, "", f"arch{self._n}")
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
        self.assertIn("not a supervisor session", r.stderr)
        self.assertIn("no section", r.stderr)
        self.assertNotIn("controls", t.session(TOP), "and records nothing")
        t.say(KID, "Fix the row")
        self.file("puppeteers", PUP, KID)
        r = t.cli(KID, "controls")
        self.assertEqual(r.returncode, 2, "a child filed there is no supervisor session")
        self.assertIn("started by another session", r.stderr)
        self.file("Puppeteers", PUP)
        self.assertEqual(t.cli(PUP, "controls").returncode, 0, "the section's name is matched whatever its case")
        self.file("wrappin up", PUP)
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "another section marks nothing")
        self.file("puppeteers", PUP, shape=["reshaped"])
        self.assertEqual(t.cli(PUP, "controls").returncode, 2, "a reshaped file makes nobody a supervisor session")
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
        self.assertIn("This session is a supervisor session: ezexe filed it in the sidebar section \"puppeteers\"", ctx)
        self.assertIn("phi.py\" controls <sessionId>", ctx)
        self.assertNotIn("multiSelect", ctx, "the rule points at the archive offer and does not restate it")
        self.assertTrue(t.session(PUP).get("puppeteerSeen"))
        self.assertNotIn("This session is a supervisor session", context(t.say(PUP, "and now?")), "said once")
        self.assertNotIn("This session is a supervisor session", context(t.say(TOP, "Build the exporter")))
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
        self.assertEqual(r.returncode, 2, "a child is reached through its top-level session")
        self.assertIn("a supervisor session controls top-level sessions", r.stderr)
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
        self.assertIn("This session is controlled by a supervisor session: \"Control the exporter and the importer "
                      f"trees, and tell ezexe where each stands\" `{PUP}`", ctx)
        self.assertIn("stays at the top of its own tree, in its own section", ctx)
        self.assertIn("Its tree is archived only on ezexe's pick", ctx)
        self.assertEqual(t.session(TOP)["puppeteer"]["sessionId"], PUP, "kept on its own record, in its own store")
        self.assertNotIn("This session is controlled by a supervisor session", context(t.say(TOP, "and now?")),
                         "said once")
        ctx = context(t.say(TOP2, "carry on", proj=self.other))
        self.assertIn("This session is controlled by a supervisor session", ctx,
                      "a session in another store is told by its own hook")
        self.assertNotIn("controlled by a supervisor session", context(t.say(TOP3, "carry on")),
                         "an uncontrolled top-level session: nothing")
        relay._write_json(os.path.join(t.dir(TOP3), "session.json"),
                          {**t.session(TOP3), "controls": [{"sessionId": KID, "store": t.p4}]})
        relay._write_json(os.path.join(t.dir(TOP), "session.json"),
                          {**t.session(TOP), "controls": [{"sessionId": TOP3, "store": t.p4}]})
        self.assertNotIn("controlled by a supervisor session", context(t.say(TOP3, "and now?")),
                         "listed by a session outside the section: told nothing")
        t.cli(PUP, "controls", "--drop", TOP)
        ctx = context(t.say(TOP, "and after?"))
        self.assertIn("This session has left the control of its supervisor session", ctx)
        self.assertNotIn("puppeteer", t.session(TOP))
        self.assertNotIn("left the control of its supervisor session", context(t.say(TOP, "and then?")), "said once")

    # --- the archive guard --------------------------------------------------------------------------------------------

    TITLE = "Build the narwhal exporter"

    def complete_top(self):
        """TOP finished and controlled, and the supervisor session handed the line that offers it."""
        t = self.t
        self.finish(TOP)
        t.say(PUP, "Control the tree")
        t.cli(PUP, "controls", TOP)
        return context(t.say(PUP, "a report came in"))

    def test_a_supervisor_sessions_archive_call_with_no_pick_this_turn_is_refused(self):
        self.complete_top()
        out = self.archive(PUP, TOP)
        self.assertEqual(out.get("permissionDecision"), "deny", "complete, controlled and reasoned, but not picked")
        why = out["permissionDecisionReason"]
        self.assertIn("Not picked by ezexe in this turn", why)
        self.assertIn("a supervisor session archives only what ezexe picks", why)
        self.assertIn("p4-phi's records hold it complete, so it can be offered", why)
        out = self.archive(PUP, TOP, picks=["Some other session"])
        self.assertEqual(out.get("permissionDecision"), "deny", "a multiple-choice answer that picked another")
        out = self.archive(PUP, TOP, picks=["None of them"])
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertEqual([a["let"] for a in self.t.session(PUP)["puppeteerArchives"]], [False, False, False])

    def test_the_same_call_after_a_multiple_choice_answer_that_picked_the_target_is_allowed(self):
        self.complete_top()
        self.assertEqual(self.archive(PUP, TOP).get("permissionDecision"), "deny")
        self.assertEqual(self.archive(PUP, TOP, picks=[self.TITLE]), {}, "ezexe's pick lets it through")
        kept = self.t.session(PUP)["puppeteerArchives"]
        self.assertEqual([(a["sessionId"], a["let"]) for a in kept], [(TOP, False), (TOP, True)])
        self.assertEqual(kept[1]["why"], WHY, "the reason it gave is kept beside what it archived")
        self.assertEqual(self.archive(PUP, TOP, reason="", picks=[self.TITLE]), {}, "the pick needs no reason")
        self.assertEqual(self.t.session(PUP)["puppeteerArchives"][-1]["why"],
                         "ezexe picked it in this turn")

    def test_a_boundary_line_for_a_complete_tree_names_the_multiple_choice_question_and_not_the_archive_call(self):
        ctx = self.complete_top()
        self.assertIn("1 session this supervisor session controls is complete", ctx)
        self.assertIn("one `AskUserQuestion` with `multiSelect` true", ctx)
        self.assertIn(f"- label \"{self.TITLE}\", description \"Archive {TOP}.\"", ctx)
        self.assertIn("with a last option \"None of them\"", ctx)
        self.assertIn("Archive none of them before ezexe has answered", ctx)
        self.assertIn("never this session's judgement", ctx)
        self.assertNotIn("archive_session", ctx, "the archive call follows ezexe's pick and is not named here")
        self.assertNotIn("puts its finished sessions to ezexe", ctx)
        self.assertNotIn("session_archives", ctx, "no text tells a session to set it")
        self.assertIn("a boundary: every controlled session is idle", ctx, "the compaction question comes with it")
        self.assertEqual(self.t.session(PUP)["archiveOffer"], [{"label": self.TITLE, "ids": [TOP]}])

    def test_one_complete_session_beside_a_working_one_is_a_button_and_its_press_is_the_pick(self):
        t = self.t
        self.finish(TOP)
        t.say(TOP2, "Build it", proj=self.other)       # mid-turn, so no boundary and no compaction question
        t.say(PUP, "Control the trees")
        t.cli(PUP, "controls", TOP, TOP2)
        ctx = context(t.say(PUP, "a report came in"))
        self.assertIn(f"\"{self.TITLE}\" `{TOP}`, a session this supervisor session controls, is complete", ctx)
        self.assertIn("buttons are the replies \"Archive it\" and \"Not now\"", ctx)
        self.assertIn("Not offered, and named to ezexe as left with the reason: \"Build the importer\"", ctx)
        self.assertNotIn("a boundary", ctx)
        self.assertNotIn("archive_session", ctx)
        self.assertEqual(self.archive(PUP, TOP).get("permissionDecision"), "deny", "not in the turn it was offered")
        self.assertEqual(self.archive(PUP, TOP, prompt="Not now").get("permissionDecision"), "deny")
        self.assertEqual(self.archive(PUP, TOP, prompt="Archive it"), {}, "ezexe pressed the button")
        self.assertEqual(self.archive(PUP, TOP2, prompt="Archive it").get("permissionDecision"), "deny")
        self.assertNotIn("is complete", context(t.say(PUP, "and now?")), "offered once")

    def test_a_supervisor_session_is_refused_what_it_does_not_control_and_what_is_not_complete(self):
        t = self.t
        self.finish(TOP3)
        t.say(KID, "Fix the row")
        t.stop(KID, "Fix the row", report="Fixed.")
        self.complete_top()
        out = self.archive(TOP, KID)
        self.assertEqual(out.get("permissionDecision"), "deny", "a top-level session outside the section: refused")
        self.assertIn("this archive call is refused", out["permissionDecisionReason"])
        out = self.archive(PUP, TOP3, picks=[self.TITLE])
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("is not a session this supervisor session controls", out["permissionDecisionReason"])
        self.assertEqual(self.archive(PUP, TOP, picks=[self.TITLE]), {})
        t.say(TOP, "one more thing")
        out = self.archive(PUP, TOP, picks=[self.TITLE])
        self.assertEqual(out.get("permissionDecision"), "deny", "picked, but not complete after its new turn")
        self.assertIn("so it is mid-turn", out["permissionDecisionReason"])
        self.assertIn("Name it to ezexe as left", out["permissionDecisionReason"])
        self.plan(TOP, "Fix the header row in exporter.py", "Run the exporter suite")
        t.stop(TOP, "one more thing", calls=[("mcp__ccd_turn__wrap_up", {"recap": "half done"}, "ok")],
               report="Half done.", uuid="u1")
        out = self.archive(PUP, TOP, picks=[self.TITLE])
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertNotIn("mid-turn", out["permissionDecisionReason"])
        self.assertIn("2 open plan steps, the next \"Fix the header row in exporter.py\"",
                      out["permissionDecisionReason"])
        kept = t.session(PUP)["puppeteerArchives"]
        self.assertEqual([(a["sessionId"], a["let"]) for a in kept],
                         [(TOP3, False), (TOP, True), (TOP, False), (TOP, False)])
        self.assertEqual(kept[1]["why"], WHY, "the reason it gave is kept beside what it archived")
        said = t.cli(PUP, "controls").stdout
        self.assertIn("- archived ", said)
        self.assertIn("- left ", said)
        self.assertIn("open: 2 open plan steps", said)
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertIn("## Archived and left", board)
        self.assertIn(f"- archived", board)

    def test_a_session_in_another_store_is_archived_and_that_store_is_only_read(self):
        t = self.t
        self.finish(TOP2, proj=self.other)

        def snap():
            return {os.path.join(d, f): read(os.path.join(d, f)) for d, _, fs in os.walk(self.store2) for f in fs}
        before = snap()
        t.say(PUP, "Control the tree")
        t.cli(PUP, "controls", TOP2)
        self.assertIn("- label \"Build the importer\"", context(t.say(PUP, "a report came in")))
        self.assertEqual(self.archive(PUP, TOP2, picks=["Build the importer"]), {})
        t.say(PUP, "where does each stand?")
        t.cli(PUP, "controls")
        self.assertEqual(snap(), before, "the supervisor session writes nothing into a controlled store")
        self.assertTrue(t.session(PUP)["puppeteerArchives"][-1]["let"], "its record is in its own store")

    # --- its own steps ------------------------------------------------------------------------------------------------

    def test_a_supervisor_sessions_task_list_gets_no_delegation_advice_and_its_wait_does_not_send_the_turn_back(self):
        t = self.t
        steps = ("Await reports from the exporter, the importer and the acceptance check",
                 "Check the trees' results against GitHub", "Rewrite flush_rows in src/exporter.py")
        t.say(PUP, "Control the two trees")
        t.say(TOP3, "Control the two trees")
        self.assertIn("child session", context(self.plan(TOP3, *steps)), "any other top-level session")
        ctx = context(self.plan(PUP, *steps))
        self.assertNotIn("child session", ctx)
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
                         "a top-level session outside the section is sent back to its step")

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
        self.assertTrue(ctx.startswith("phi (p4-phi): this session is a supervisor session and its context was "
                                       "compacted. Read its board before anything else: " + board), ctx[:300])
        self.assertTrue(os.path.exists(board))
        self.assertEqual(t.session(PUP)["compactions"], 1)
        r = t.hook("session-start", TOP, {"hook_event_name": "SessionStart", "source": "compact"})
        self.assertNotIn("its board", context(r))

    def test_a_boundary_is_named_once_as_a_question_with_two_buttons(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP, "Build it")                      # mid-turn
        t.cli(PUP, "controls", TOP)
        self.assertNotIn("a boundary", context(t.say(PUP, "anything?")), "a controlled session is working")
        t.cli(TOP, "done", "its suite ran green")
        t.stop(TOP, "Build it", report="Built.")
        ctx = context(t.say(PUP, "a report came in"))
        self.assertIn("a boundary: every controlled session is idle and no request is waiting", ctx)
        self.assertIn("`mcp__ccd_session_mgmt__get_usage` on `\"self\"`", ctx)
        self.assertIn("end the turn with `mcp__ccd_turn__wrap_up`", ctx)
        self.assertIn("\"Compact now\" and \"Later\"", ctx)
        self.assertIn("/compact keep the path of the board", ctx)
        self.assertNotIn("tell ezexe in one line", ctx, "a button, never a paragraph to pass on")
        self.assertNotIn("past the ceiling", ctx)
        self.assertNotIn("a boundary", context(t.say(PUP, "and now?")), "a second hook at the same boundary: nothing")
        relay._write_json(os.path.join(t.p4, "p4.json"), {"phi": {"puppeteer_chars": 50}})
        ctx = context(t.say(PUP, "and now?"))
        self.assertIn("a boundary", ctx, "the count passed the ceiling")
        self.assertRegex(ctx, r"p4-phi has handed this session \d+ characters since its last compaction, past the "
                              r"ceiling of 50")
        s = t.session(PUP)
        relay._write_json(os.path.join(t.dir(PUP), "session.json"), {**s, "compactions": 3, "boundary": {}})
        ctx = context(t.say(PUP, "and now?"))
        self.assertIn("the app's `new_session` action, which starts the successor supervisor session from the board",
                      ctx)

    def test_a_successor_takes_over_the_controlled_sessions_and_archives_the_old_supervisor_session(self):
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
        self.assertIn("offers it to ezexe to archive", r.stdout, "the successor archives it only on ezexe's pick")
        self.assertIn("only on ezexe's pick", r.stdout)
        self.assertNotIn("and archives it", r.stdout)
        t.cli(PUP, "done", "handed the board to the second puppeteer")
        t.stop(PUP, "Control the tree", report="Handed over.")
        r = t.cli(PUP2, "controls", "--from", PUP)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("took over 1 controlled session and 1 note", r.stdout)
        self.assertEqual([e["sessionId"] for e in t.session(PUP2)["controls"]], [TOP])
        self.assertIn("ezexe froze the retry work", read(os.path.join(t.dir(PUP2), "board.md")))
        ctx = context(t.say(TOP, "carry on"))
        self.assertIn(f"\"The second puppeteer\" `{PUP2}`", ctx, "the successor controls it now")
        self.assertEqual(self.archive(PUP2, PUP).get("permissionDecision"), "deny", "not on its own judgement")
        t.say(PUP2, "what is ready?")
        old = "Control the exporter and the importer trees, and tell ezexe where each stands"
        self.assertIn(old, [o["label"] for o in t.session(PUP2)["archiveOffer"]],
                      "the old supervisor session, handed over and done, is offered")
        self.assertEqual(self.archive(PUP2, PUP, picks=[old]), {}, "and archived by the new one on ezexe's pick")
        self.assertEqual(self.archive(PUP2, TOP3, picks=[old]).get("permissionDecision"), "deny")

    # --- a new top-level session goes through the supervisor session ----------------------------------------------------

    def test_a_controlled_top_session_asks_its_supervisor_session_and_its_own_start_is_refused(self):
        t = self.t
        t.say(PUP, "Control the two trees")
        t.say(TOP2, "Build the importer", proj=self.other, P4_PHI_NEW_TASK="1")
        t.cli(PUP, "controls", TOP2)
        t.stop(TOP2, "Build the importer", report="Started.", proj=self.other)
        relay._write_json(os.path.join(self.store2, "phi", "sessions", TOP2, "session.json"),
                          {k: v for k, v in relay._read_json(os.path.join(
                              self.store2, "phi", "sessions", TOP2, "session.json")).items()
                           if k != "newTaskToldAt"})
        ctx = context(t.say(TOP2, "Also, what about a new exporter for the moon format?", proj=self.other,
                            P4_PHI_NEW_TASK="1"))
        self.assertIn("This session is controlled by a supervisor session", ctx)
        self.assertIn("--to-puppeteer", ctx)
        self.assertNotIn("start_session", ctx, "handed a new-topic line, it is given no start call")
        new_top = BRIEF + "\n" + phi.NEW_TOP_BRIEF
        r = t.hook("start-advice", TOP2, {"hook_event_name": "PreToolUse", "tool_name": START,
                                          "tool_input": {"initiation": "user_asked", "title": "the retry",
                                                         "prompt": new_top}}, proj=self.other)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny", "its own start of a new top-level session is refused")
        self.assertIn("--to-puppeteer", out["permissionDecisionReason"])
        r = t.hook("start-advice", TOP3, {"hook_event_name": "PreToolUse", "tool_name": START,
                                          "tool_input": {"initiation": "user_asked", "title": "the retry",
                                                         "prompt": new_top}})
        self.assertNotIn("\"deny\"", r.stdout, "a top-level session with no supervisor session starts its own")
        r = t.cli(TOP3, "request", "the retry", "--brief", BRIEF, "--to-puppeteer")
        self.assertEqual(r.returncode, 2)
        self.assertIn("has no supervisor session", r.stderr)
        r = t.cli(TOP2, "request", "the retry", "--brief", BRIEF, "--to-puppeteer", proj=self.other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("to this session's supervisor session", r.stdout)
        self.assertIn("Start nothing for it here", r.stdout)
        row = next(iter(starts.state(self.store2).values()))
        self.assertEqual(row["to"], PUP, "kept in the store of the session that filed it")
        self.assertEqual(starts.state(t.p4), {}, "and nothing in the supervisor session's")
        self.assertNotIn("start requests", context(t.say(TOP2, "and now?", proj=self.other)),
                         "never handed back to the session that filed it")
        # the supervisor session reads it where it lies, at a turn ezexe began
        ctx = context(t.say(PUP, "what is waiting?"))
        self.assertIn("controlled sessions ask this supervisor session for new top-level sessions", ctx)
        self.assertIn("to be filed in the ungrouped list under its project", ctx)
        call = json.loads(ctx.split("`mcp__ccd_session__start_session` with ", 1)[1].split("\n", 1)[0])
        self.assertEqual(os.path.normcase(os.path.normpath(call["cwd"])),
                         os.path.normcase(os.path.normpath(self.other)), "in the environment of the session that filed it")
        self.assertIn(phi.NEW_TOP_BRIEF, call["prompt"])
        self.assertIn(f"for {TOP2}.", call["prompt"])
        self.assertIn("## Requests to this supervisor session", read(os.path.join(t.dir(PUP), "board.md")))
        self.assertNotIn("a boundary", ctx, "never while a controlled session waits on the supervisor session's answer")
        # it starts it: the new session arrives in the store of the session that filed the request, a top-level
        # session, and is taken under control
        t.record(NEW, started_by=PUP, title="the retry", cwd=self.other)
        t.say(NEW, "Task:\n" + call["prompt"], proj=self.other)
        self.assertEqual(starts.open_rows(self.store2), [], "the request is started")
        self.file("puppeteers", PUP, more={TOP2: "importers"})
        ctx = context(t.say(PUP, "and now?"))
        self.assertIn(f"\"the retry\" `{NEW}` is a top-level session this supervisor session started, so it is "
                      f"controlled", ctx)
        self.assertIn("File it in the section \"importers\" with `mcp__ccd_sidebar__move_sessions`, never in "
                      "\"puppeteers\"", ctx)
        self.assertIn(NEW, [e["sessionId"] for e in t.session(PUP)["controls"]])
        self.assertIn("This session is controlled by a supervisor session", context(t.say(NEW, "carry on",
                                                                                          proj=self.other)))

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
        self.assertNotIn("ask this supervisor session", context(t.say(PUP, "what is waiting?")))
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
                          {"sessionId": TOP3, "title": "A top session nobody put under the puppeteer",
                           "createdAt": "2999-01-01 00:00", "cwd": t.proj})
        ctx = context(t.say(PUP, "anything new?"))
        self.assertIn(f"\"A top session nobody put under the puppeteer\" `{TOP3}` is a new top-level session", ctx)
        self.assertIn(f"controls {TOP3}` takes it under control", ctx)
        self.assertNotIn("does not control", context(t.say(PUP, "and now?")), "named once")

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
        self.assertIn("this go to \"A top session nobody put under the puppeteer\" is early", said)
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
        self.assertNotIn("orchestrates. If so", context(t.say(PUP, "How is the weather on the moon today?")))


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
