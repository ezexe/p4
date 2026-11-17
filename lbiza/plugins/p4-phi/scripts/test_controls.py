#!/usr/bin/env python3
"""controls.py: a puppeteer and the sessions it controls, run through p4-phi's own hooks.

ezexe files an orchestrator in the sidebar section "puppeteers", which makes it a puppeteer. It controls
the orchestrators of other trees, in any store: p4-phi reads the filing from the app's own file, keeps the
record of the sessions it controls, tells each controlled session, writes the puppeteer's board, leaves its
waiting steps with it, lets it archive only what ezexe picks, names a boundary once as a question with two buttons,
and carries a controlled session's request for a new orchestrator to it. A start request stays with the session
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
from test_phi import START as SESSION_START  # noqa: E402

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

    def archive(self, by, target, reason=WHY, picks=None, prompt="what is ready?", answers=None):
        """The archive hook for `by`'s call on `target`. With `picks`, the turn holds an answered multiple-choice
        question carrying those labels; with `answers`, one whose result reads as the AskUserQuestion tool returns
        it, each question with the labels ezexe picked, joined by commas; `prompt` is the message that began the
        turn."""
        inp = {"session_id": target, **({"reason": reason} if reason else {})}
        calls = [] if picks is None else [("AskUserQuestion", {"questions": []},
                                           "User has answered your questions: " + ", ".join(f'"{p}"' for p in picks))]
        if answers:                                # (question, picked labels[, its options[, multiSelect]])
            said = ", ".join(f'"{a[0]}"="{", ".join(a[1])}"' for a in answers)
            asked = [{"question": a[0], "multiSelect": a[3] if len(a) > 3 else True,
                      "options": [{"label": x} for x in (a[2] if len(a) > 2 else [*a[1], "None of them"])]}
                     for a in answers]
            calls = [("AskUserQuestion", {"questions": asked},
                      f"User has answered your questions: {said}. You can now continue with the user's answers in "
                      f"mind.")]
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
        self.assertIn("Its tree is archived only on ezexe's pick", ctx)
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

    # --- the archive guard --------------------------------------------------------------------------------------------

    TITLE = "Build the narwhal exporter"

    def complete_top(self):
        """TOP finished and controlled, and the puppeteer handed the line that offers it."""
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
        self.assertIn("a puppeteer archives only what ezexe picks", why)
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

    def test_a_multiselect_answer_naming_sessions_by_full_title_passes_the_gate_with_no_offer_stored(self):
        """ezexe's picks in a multiSelect AskUserQuestion of the turn name the sessions by their full titles, and
        no offer p4-phi stored holds those labels: each named session passes the gate, for a puppeteer and for an
        orchestrator, and a session the answer does not name is still refused. A name counts only for a session the
        gate offers, a finished one of the caller's own tree, picked among the options of a multiSelect question."""
        t = self.t
        other = "An orchestrator nobody put under the puppeteer"
        self.finish(TOP)
        self.finish(TOP3)
        t.say(PUP, "Control the trees")
        t.cli(PUP, "controls", TOP, TOP3)
        self.assertNotIn("archiveOffer", t.session(PUP), "no offer is stored")
        asked = [("Which finished sessions should be archived?", [self.TITLE, other])]
        self.assertEqual(self.archive(PUP, TOP, answers=asked), {}, "picked by its full title")
        self.assertEqual(self.archive(PUP, TOP3, answers=asked), {}, "picked by its full title")
        none = [("Which finished sessions should be archived?", ["None of them"])]
        self.assertEqual(self.archive(PUP, TOP, answers=none).get("permissionDecision"), "deny")
        q = "Which finished sessions should be archived?"
        t.say(KID, "Task:\nBuild the flush.\nFiles: src/flush.py")
        self.assertEqual(self.archive(TOP, KID, answers=[(q, ["the flush child"])]).get("permissionDecision"),
                         "deny", "a worker never finished is outside the offer, whatever the answer names")
        self.assertEqual(self.archive(TOP, TOP3, answers=[(q, [other])]).get("permissionDecision"), "deny",
                         "a sibling orchestrator is outside the caller's own tree")
        t.record(KID2, started_by=TOP, title="the docs worker")
        t.say(KID2, "Task:\nWrite the flush docs. Report when done.\nFiles: docs/flush.md")
        t.cli(KID2, "done", "the docs page is written and committed")
        t.stop(KID2, "Write the docs", report="Written.")
        self.assertEqual(self.archive(TOP, KID2, answers=[(q, ["the docs worker"])]), {},
                         "a finished worker of its tree, picked by its full title")
        self.assertEqual(self.archive(TOP, KID2, answers=[(q, [KID2])]), {}, "or by its id")
        self.assertEqual(self.archive(TOP, KID2, answers=[(q, ["the docs"])]).get("permissionDecision"), "deny",
                         "a label that only shares words with its title is no pick")
        self.assertEqual(self.archive(TOP, KID2, answers=[("Shall the docs worker go?", ["the docs worker"],
                                                           ["the docs worker", "Keep it"], False)]).get(
            "permissionDecision"), "deny", "only the answer to a multiSelect question is a pick")
        self.assertEqual(self.archive(TOP, KID2, answers=[(q, ["the docs worker"], ["Some other session"])]).get(
            "permissionDecision"), "deny", "a name the question never offered is no pick")

    def test_a_boundary_line_for_a_complete_tree_names_the_multiple_choice_question_and_not_the_archive_call(self):
        ctx = self.complete_top()
        self.assertIn("1 session this puppeteer controls is complete", ctx)
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
        self.assertIn(f"\"{self.TITLE}\" `{TOP}`, a session this puppeteer controls, is complete", ctx)
        self.assertIn("buttons are the replies \"Archive it\" and \"Not now\"", ctx)
        self.assertIn("Not offered, and named to ezexe as left with the reason: \"Build the importer\"", ctx)
        self.assertNotIn("a boundary", ctx)
        self.assertNotIn("archive_session", ctx)
        self.assertEqual(self.archive(PUP, TOP).get("permissionDecision"), "deny", "not in the turn it was offered")
        self.assertEqual(self.archive(PUP, TOP, prompt="Not now").get("permissionDecision"), "deny")
        self.assertEqual(self.archive(PUP, TOP, prompt="Archive it"), {}, "ezexe pressed the button")
        self.assertEqual(self.archive(PUP, TOP2, prompt="Archive it").get("permissionDecision"), "deny")
        self.assertNotIn("is complete", context(t.say(PUP, "and now?")), "offered once")

    def test_five_complete_sessions_are_each_an_option_of_their_own_in_one_askuserquestion(self):
        """An AskUserQuestion takes up to four questions of up to four options each, so five complete sessions are
        two questions of one AskUserQuestion, and ezexe's pick of the fifth alone archives the fifth."""
        t = self.t
        t.record(TOP4, title="Build the ports table")
        t.record(TOP5, title="Build the moon format reader")
        five = [(TOP, self.TITLE), (TOP2, "Build the importer"), (TOP3, "An orchestrator nobody put under the puppeteer"),
                (TOP4, "Build the ports table"), (TOP5, "Build the moon format reader")]
        for sid, _ in five:
            self.finish(sid, proj=self.other if sid == TOP2 else None)
        t.say(PUP, "Control the five trees")
        t.cli(PUP, "controls", *[sid for sid, _ in five])
        ctx = context(t.say(PUP, "five reports came in"))
        self.assertEqual({o["label"]: o["ids"] for o in t.session(PUP)["archiveOffer"]},
                         {title: [sid] for sid, title in five}, "each session under an option of its own")
        self.assertIn("5 sessions this puppeteer controls are complete", ctx)
        self.assertIn("put them to ezexe as 2 multiple-choice questions in one `AskUserQuestion`", ctx)
        asked = ctx.split("under these questions:\nQuestion 1:\n", 1)[-1].split("\nArchive none of them", 1)[0]
        asked = asked.split("\nQuestion 2:\n")
        self.assertEqual(len(asked), 2, ctx)
        for q in asked:
            self.assertTrue(2 <= len(q.splitlines()) <= 4, f"a question holds two to four options:\n{q}")
        for sid, title in five:
            self.assertEqual(sum(f"- label \"{title}\", description \"Archive {sid}.\"" in q for q in asked), 1, title)
        self.assertEqual(self.archive(PUP, TOP5, picks=["Build the moon format reader"]), {}, "the fifth, picked alone")
        self.assertEqual(self.archive(PUP, TOP4, picks=["Build the moon format reader"]).get("permissionDecision"),
                         "deny", "and no session ezexe did not pick")

    def test_a_supervisor_session_is_refused_what_it_does_not_control_and_what_is_not_complete(self):
        t = self.t
        self.finish(TOP3)
        t.say(KID, "Fix the row")
        t.stop(KID, "Fix the row", report="Fixed.")
        self.complete_top()
        out = self.archive(TOP, KID)
        self.assertEqual(out.get("permissionDecision"), "deny", "an orchestrator outside the section: refused")
        self.assertIn("this archive call is refused", out["permissionDecisionReason"])
        out = self.archive(PUP, TOP3, picks=[self.TITLE])
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("is not a session this puppeteer controls", out["permissionDecisionReason"])
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
        self.assertEqual(snap(), before, "the puppeteer writes nothing into a controlled store")
        self.assertTrue(t.session(PUP)["puppeteerArchives"][-1]["let"], "its record is in its own store")

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
        self.assertEqual(t.session(PUP)["compactions"], 1)
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
        self.assertRegex(changed, r"^- tabs-not-spaces, \d{4}-\d\d-\d\d \d\d:\d\d\nEach is whole on .+/phi/rules\.md\.")
        self.assertEqual([x["name"] for x in t.session(PUP)["rulesChanged"]], ["tabs-not-spaces"])

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
        self.assertIn("the app's `new_session` action, which starts the successor puppeteer from the board",
                      ctx)

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
        self.assertIn("\"Compact now\" and \"Later\"", ctx)
        self.assertNotIn("is complete", ctx, "an archived session is offered to nobody")
        board = read(os.path.join(t.dir(PUP), "board.md"))
        self.assertRegex(board, rf"- \"{self.TITLE}\" `{TOP}`, store .+: archived\.")
        self.assertNotIn("a boundary", context(t.say(PUP, "and now?")), "said once")

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
                      "the old puppeteer, handed over and done, is offered")
        self.assertEqual(self.archive(PUP2, PUP, picks=[old]), {}, "and archived by the new one on ezexe's pick")
        self.assertEqual(self.archive(PUP2, TOP3, picks=[old]).get("permissionDecision"), "deny")

    # --- a new orchestrator goes through the puppeteer ----------------------------------------------------

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
        self.assertIn("This session is controlled by a puppeteer", ctx)
        self.assertIn("--to-puppeteer", ctx)
        self.assertIn(phi.RESTATE, ctx, "the request's brief restates the task")
        self.assertNotIn("start_session", ctx, "handed a new-topic line, it is given no start call")
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
        self.assertNotIn("start requests", context(t.say(TOP2, "and now?", proj=self.other)),
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


    def test_rules_md_holds_a_memorys_new_wording_once_the_board_names_its_change(self):       # 200
        t = self.t
        conf = os.path.join(t.tmp, "conf")
        os.makedirs(conf)
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with tabs in the exporter.")
        t.hook("session-start", PUP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        t.say(PUP, "Control the trees", CLAUDE_CONFIG_DIR=conf)
        rules = os.path.join(t.p4, "phi", "rules.md")
        self.assertIn("Indent with tabs in the exporter.", read(rules))
        memory(t.p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        t.say(PUP, "carry on", CLAUDE_CONFIG_DIR=conf)
        self.assertIn("- tabs-not-spaces, ", read(os.path.join(t.dir(PUP), "board.md")))
        self.assertIn("Indent with four spaces in the exporter, never tabs.", read(rules))
        self.assertNotIn("Indent with tabs in the exporter.", read(rules))

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
        said, out = self.pre(PUP, "mcp__ccd_session_mgmt__set_session_model",
                             {"session_id": TOP, "model": "claude-haiku-5-5"})
        self.assertIn("model", said)
        self.assertIn("chosen at its start", said)
        self.assertIn("set_session_effort", controls.RULE)
        self.assertIn("only on the start call", controls.RULE)

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
        ctx = context(t.say(WORKER, brief))
        self.assertIn("standing coworker", ctx)
        self.assertIn("Model and effort:", ctx)
        self.assertIn("one closing message to the puppeteer", ctx)
        self.assertIn(os.path.join(t.dir(WORKER), "state.md").replace("\\", "/"), ctx, "its state page")
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
        for sid in (CO1, CO2):
            t.record(sid, started_by=WORKER, title="a standing coworker")
            self.assertIn("standing coworker", context(t.say(sid, "Check the archives.\nFiles: none")))
        ctx = context(t.say(PUP, f'<cross-session-message from="{WORKER}">Checked 4 archives; page: x.md'
                                 f'</cross-session-message>'))
        line = next((x for x in ctx.splitlines() if "get_usage" in x and WORKER in x), "")
        for sid in (WORKER, CO1, CO2):
            self.assertIn(sid, line)
        self.assertIn(f"{controls.CLEAR_AT} percent", line)
        self.assertNotIn(f"worker `{WORKER}` reported", context(t.say(PUP, "and now?")), "only at its report")
        r = t.hook("session-start", CO1, {"hook_event_name": "SessionStart", "source": "compact"})
        page = os.path.join(t.dir(CO1), "state.md").replace("\\", "/")
        self.assertTrue(context(r).startswith("phi (p4-phi): ") and page in context(r).split("\n", 1)[0],
                        context(r)[:300])

class TreeAndClicks(unittest.TestCase):
    """The tree in the app is the true tree, and ezexe acts by click where one exists. A child's start request is
    started by the child itself, which waits on ezexe by a blocked wrap-up whose first button starts it; its
    puppeteer names the child as a link with the count it holds and is handed no start call for it; a start
    the puppeteer makes on the child's behalf anyway is held under the child in p4-phi, named for detaching
    to top level and kept on the board as an exception; and every ask of ezexe in the lines the session modules hand
    a session offers a click."""

    FLUSH = "Port the exporter's flush to the new writer and run its suite. Report when done.\nFiles: src/flush.py"
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
        self.filed = t.cli(KID, "request", "the flush port", "--brief", self.FLUSH)
        self.assertEqual(self.filed.returncode, 0, self.filed.stderr)
        self.row = starts.pending(t.p4)[0]

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_childs_start_request_waits_on_a_button_there_and_its_supervisor_session_gets_a_link_and_no_call(self):
        t = self.t
        with self.subTest("the child ends its turn on a blocked wrap-up whose first button starts the request"):
            self.assertIn("No other session is handed it", self.filed.stdout)
            self.assertIn("`mcp__ccd_turn__wrap_up` with `blocked` true", self.filed.stdout)
            self.assertIn("the question \"Start \"the flush port\" here?\"", self.filed.stdout)
            self.assertIn("the reply button \"Start it\" first", self.filed.stdout)
            again = context(t.say(KID, self.CROSS))
            self.assertIn("`mcp__ccd_turn__wrap_up` with `blocked` true", again, "and again at each turn ezexe did "
                                                                              "not begin while it holds the request")
            self.assertNotIn("`mcp__ccd_session__start_session` with", again)
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
        with self.subTest("the button's press is a turn ezexe began in the child, which hands it the exact call"):
            line = context(t.say(KID, "Start it"))
            call = json.loads(line.split(f"`{START}` with ", 1)[1].split("\n", 1)[0])
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
    archive = Supervisor.archive

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

    def test_a_worker_landed_by_cherry_pick_with_its_issue_closed_passes_the_archive_gate(self):
        work, bare, land, sha = self.worker_closing_7()
        write(os.path.join(land, "README.md"), "the exporter\n")
        self.git(land, "add", "-A")
        self.git(land, "commit", "-qm", "docs: a readme")
        self.git(land, "fetch", "-q", work, "main:refs/heads/worker")
        self.git(land, "cherry-pick", sha)                # the orchestrator lands it under a new hash
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertEqual(self.git(work, "branch", "-r", "--contains", sha), "", "its own hash is on no remote branch")
        out = self.archive(PUP, KID, answers=[("Which finished sessions should be archived?", ["the flush child"])])
        self.assertEqual(out, {}, out)
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
        out = self.archive(PUP, KID, answers=[("Which finished sessions should be archived?", ["the flush child"])])
        self.assertEqual(out.get("permissionDecision"), "deny", "#7 of ezexe/other is not this repository's #7")
        self.assertIn(f"commit {sha}, which closes #7, is on no remote branch", out["permissionDecisionReason"])
        import issues
        self.assertFalse(issues.landed(work, sha, ["#7"]))
        self.git(land, "commit", "-q", "--allow-empty", "-m", "notes: tidy\n\nFixes ezexe/demo#7")
        self.git(land, "push", "-q", "origin", "main")
        self.git(work, "fetch", "-q", bare, "main:refs/remotes/origin/main")
        self.assertTrue(issues.landed(work, sha, ["#7"]), "this repository's own #7, named whole")


if __name__ == "__main__":
    unittest.main(verbosity=1)
