#!/usr/bin/env python3
"""plans.py: step addresses, the plan tree, the check at each step boundary and revisions relayed, on a three-session
tree run through phi's own hooks.

    python3 -I lbiza/plugins/p4-phi/scripts/test_plans.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plans  # noqa: E402
import relay  # noqa: E402
from test_phi import GRAND, KID, KID2, TOP, Tree, context  # noqa: E402
import relay as _relay  # noqa: E402,F401

A, B = KID, KID2


def items(*steps, at=0):
    return {"items": [{"content": c, "status": "completed" if k < at else "in_progress" if k == at else "pending"}
                      for k, c in enumerate(steps)], "scope": "first_task"}


class Apply(unittest.TestCase):
    def test_addresses_advance_done_start_and_revisions(self):
        p, started, rev = plans.apply({}, items("one", "two", "three"), "2")
        self.assertEqual([x["addr"] for x in p["steps"]], ["2.1", "2.2", "2.3"])
        self.assertEqual((started, rev), ("2.1", None))
        p, started, _ = plans.apply(p, {"advance": True}, "2")
        self.assertEqual((p["current"], started), ("2.2", "2.2"))
        p, started, _ = plans.apply(p, {"done": [2], "start": 3}, "2")
        self.assertEqual((p["current"], started), ("2.3", "2.3"))
        p, started, rev = plans.apply(p, items("one", "two, rewritten", at=1), "2")
        self.assertEqual(rev["changed"], ["2.2"])
        self.assertEqual(rev["removed"], ["2.3"])
        top, _, _ = plans.apply({}, items("a", "b"), "")
        self.assertEqual([x["addr"] for x in top["steps"]], ["1", "2"])


class Tasks(unittest.TestCase):
    """RB1 and P6 of the marketplace test session: tasks stay with their step's words, and an old task is unknown."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.say(TOP, "Build it")
        self.s = relay._session(self.t.p4, TOP)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_task_follows_its_steps_words_across_a_rewrite(self):
        home = self.t.p4
        plans.record(home, self.s, items("Run the smoke check", "Write the report"))
        plans.register(home, self.s, "Bash", {"command": "sh smoke.sh", "run_in_background": True},
                       "Command running in background with ID: bsmoke001.", "")
        plans.record(home, self.s, items("Plan the layout", "Run the smoke check", "Write the report"))
        p = plans.load(home, TOP)
        self.assertEqual([st["addr"] for st in p["steps"] if st.get("tasks")], ["2"], "with its words, now step 2")
        plans.record(home, self.s, items("Plan the layout", "Write the report"))
        p = plans.load(home, TOP)
        self.assertFalse(any(st.get("tasks") for st in p["steps"]))
        self.assertEqual([t["id"] for t in p["loose"]], ["bsmoke001"], "its step is gone: loose, not on another step")

    def test_a_task_long_past_with_no_notice_is_unknown_and_never_flagged(self):
        import time as _t
        home = self.t.p4
        plans.record(home, self.s, items("Run the smoke check", "Write the report"))
        plans.register(home, self.s, "Bash", {"command": "sh smoke.sh", "run_in_background": True},
                       "Command running in background with ID: bold00001.", "", at_epoch=int(_t.time()) - 86400)
        lines, _ = plans.check_tasks(home, self.s, plans.load(home, TOP))
        self.assertEqual(lines, [])
        p = plans.load(home, TOP)
        self.assertEqual(p["steps"][0]["tasks"][0]["status"], "open", "check_tasks reads; the boundary writes")

    def test_a_stopped_task_closes_and_a_foreground_agent_is_no_task(self):
        """RB1's rest: TaskStop sends no notice, and a finished agent's words may name the background."""
        home = self.t.p4
        plans.record(home, self.s, items("Watch the build", "Write the report"))
        plans.register(home, self.s, "Monitor", {"command": "tail -f log", "timeout_ms": 300000},
                       "Monitor started (task bwatch001, timeout 300000ms).", "")
        task = plans.load(home, TOP)["steps"][0]["tasks"][0]
        self.assertEqual(task["timeoutS"], 300)
        raw = '{"type":"tool_use","id":"toolu_1","name":"TaskStop","input":{"task_id":"bwatch001"}}'
        self.assertEqual(plans.pickup(home, TOP, raw), ["bwatch001"])
        self.assertEqual(plans.load(home, TOP)["steps"][0]["tasks"][0]["status"], "stopped")
        self.assertIsNone(plans.register(home, self.s, "Agent", {"prompt": "look"},
                                         "Done. The background tasks agentId: abec142e99 were fine.", ""))

    def test_loose_tasks_are_never_flagged_and_any_task_past_its_budget_is_unknown(self):
        import time as _t
        home = self.t.p4
        plans.register(home, self.s, "Bash", {"command": f"sh {home}/x.sh", "run_in_background": True},
                       "Command running in background with ID: bloose001.", "")
        p = plans.load(home, TOP)
        self.assertEqual([t["id"] for t in p["loose"]], ["bloose001"])
        p["loose"][0]["heads"] = ["somewhere@0000000"]
        lines, _ = plans.check_tasks(home, self.s, p)
        self.assertEqual(lines, [], "a loose task has no step to be checked against")
        p["loose"][0]["epoch"] = int(_t.time()) - plans.JOB_GAP_S - 60
        plans.check_tasks(home, self.s, p)
        self.assertEqual(p["loose"][0]["status"], "unknown")


class TreeOfPlans(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        t = self.t
        t.record(TOP, title="top")
        t.record(A, TOP, title="the layout child")
        t.record(B, TOP, title="the docs child")
        t.say(TOP, "Build the two plugins")
        self.plan(TOP, items("Port the hooks", "Move the store layout into phi", "Write the layout docs", at=1))
        t.say(A, "Move the store layout into phi, in steps")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, host, inp):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return ""
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        return out["additionalContext"]

    def test_a_child_gets_its_parents_step_as_its_root(self):
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual([x["addr"] for x in plans.load(self.t.p4, A)["steps"]], ["2.1", "2.2", "2.3"])
        anchor = json.load(open(relay.anchor_path(self.t.p4, TOP), encoding="utf-8"))
        self.assertEqual(anchor["nodes"][A]["plan"]["current"], "2.1", "the parent's anchor is the plan tree")
        self.assertEqual(anchor["parent"]["plan"]["current"], "2")

    def test_siblings_started_in_one_step_get_the_steps_their_briefs_name(self):
        """Two children started while the parent is on step 2, one for its docs step: each its own root."""
        home = self.t.p4
        s = {"sessionId": "x", "spawnedFrom": {"sessionId": TOP}, "task": "Write the layout docs for the store"}
        self.assertEqual(plans.root_of(home, s), "3")
        s["task"] = "Move the store layout into phi, the code part"
        self.assertEqual(plans.root_of(home, s), "2")
        s["task"] = "something else entirely"
        self.assertEqual(plans.root_of(home, s), "2", "no match: the step in progress")

    def test_an_up_line_is_said_once(self):
        """P1: "the parent has moved past your root step" came at every boundary after."""
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move", "Tell docs"))
        self.plan(TOP, items("Port the hooks", "Move the store layout into phi", "Write the layout docs", at=2))
        first = self.plan(A, {"advance": True})
        self.assertIn("up: the parent has moved past your root step 2", first)
        again = self.plan(A, {"advance": True})
        self.assertNotIn("moved past", again)

    def test_the_parent_revising_the_childs_root_reaches_it_at_its_next_advance(self):
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual(self.plan(A, {"advance": True}), "", "nothing bears on 2.2: quiet")
        self.plan(TOP, items("Port the hooks", "Move the store layout into temportal instead", "Write the layout docs",
                             at=1))
        ctx = self.plan(A, {"advance": True})
        self.assertIn("step 2.3 starts now", ctx)
        self.assertIn("your root step 2 in the plan of \"top\" was revised", ctx)
        self.assertNotIn("up: the parent revised your root step 2", ctx, "P1: the relayed revision says it once")
        self.assertEqual(ctx.count("root step 2"), 1)
        self.assertEqual(self.plan(A, {"items": [{"content": "Rewrite p4conf.LAYOUT", "status": "completed"},
                                                 {"content": "Move recall/ into phi/", "status": "completed"},
                                                 {"content": "Commit the move", "status": "completed"},
                                                 {"content": "Tell the docs child", "status": "in_progress"}]}).count(
            "was revised"), 0, "a warning is given once")

    def test_a_removed_root_step_tells_the_child_before_its_next_tool(self):
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        self.plan(TOP, items("Port the hooks", "Write the layout docs", at=1))
        ctx = context(t.say(A, "carry on"))
        self.assertTrue(ctx.startswith("phi (p4-phi): stop before any tool runs."), ctx[:200])
        self.assertIn("your root step 2", ctx)
        self.assertIn("was removed from the plan", ctx)

    def test_a_siblings_step_that_changes_the_next_step_is_relayed_across(self):
        t = self.t
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(B, items("Draft the layout table docs for p4conf", "Publish the layout table docs"))
        self.assertEqual([x["addr"] for x in plans.load(t.p4, B)["steps"]], ["3.1", "3.2"], "the brief names step 3")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.plan(A, items("Rewrite the p4conf layout table", "Move recall/ into phi/", "Commit the move"))
        ctx = self.plan(B, {"advance": True})
        self.assertIn("step 3.2 starts now", ctx)
        self.assertIn("revised step(s) 2.1 of its plan", ctx, "the revision, relayed across")
        self.assertIn("across: \"the layout child\" is on 2.1", ctx, "the sibling's step in progress")

    def test_down_the_parent_sees_its_childrens_progress_at_its_own_boundary(self):
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        self.plan(A, {"advance": True})
        ctx = self.plan(TOP, {"advance": True})
        self.assertIn("down: \"the layout child\" has 1 of 2 steps done, now on 2.2", ctx)
        self.assertNotIn("down:", self.plan(TOP, {"advance": True}), "told again only when it moved")

    def test_the_parents_report_reaches_the_child_whose_check_it_voids(self):
        """The miss this closes: a parent's turn report voided a child's checks and the child was never told."""
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        report = "The plan-step relay replaces the notes relay, so the relay suite checks are void."
        t.stop(TOP, "decide the relay", report=report, uuid="p1")
        ctx = self.plan(A, {"advance": True})
        self.assertIn("ended a turn whose words bear on your open step(s): 2.1", ctx)
        self.assertIn(report, ctx, "the parent's own words, quoted")
        nag = context(t.say(TOP, "next"))
        self.assertIn(f"your last turn changed step(s) 2.1", nag)
        self.assertIn(f"relay it with SendMessage (`to`: {A})", nag)
        self.assertNotIn("relay it", context(t.say(TOP, "and next")), "said once")

    def test_a_report_the_turn_already_sent_is_not_nagged(self):
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        t.stop(TOP, "decide the relay", [("SendMessage", {"to": A, "message": "the relay suite is void"}, "sent")],
               report="The notes relay is replaced, so the relay suite checks are void.", uuid="p2")
        self.assertNotIn("relay it", context(t.say(TOP, "next")))

    def lookup(self, host, name, payload, wait=False):
        """A tool call through recall's lookup entry, as every session's frozen hook list runs it."""
        t = self.t
        root = os.path.dirname(HERE)
        body = {"session_id": host, "cwd": t.proj, "hook_event_name": "PostToolUse", **payload}
        r = subprocess.run(["sh", os.path.join(root, "hooks", "recall-hook.sh"), name], input=json.dumps(body),
                           capture_output=True, text=True, timeout=60,
                           env={**t.env(host), **({"P4_RECALL_SYNC": "1"} if wait else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_the_plan_check_runs_through_recalls_lookup_entry_once(self):
        """L3: a session's hook list is read once at its start, so the plan check rides on lookup-record, which every
        open session has; a session that also has the dedicated entry runs it once."""
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        call = {"tool_name": "mcp__ccd_turn__update_plan", "tool_input": {"advance": True},
                "tool_response": "Plan updated.", "tool_use_id": "toolu_route01"}
        self.plan(TOP, items("Port the hooks", "Move the store layout into temportal instead", "Write the docs", at=1))
        ctx = self.lookup(A, "lookup-record", call)
        self.assertIn("step 2.2 starts now", ctx)
        self.assertEqual(plans.load(t.p4, A)["current"], "2.2")
        r = t.hook("plan", A, call)
        self.assertEqual(r.stdout.strip(), "", "the same call through the dedicated entry is not run again")
        self.assertEqual(plans.load(t.p4, A)["current"], "2.2", "advanced once")
        logged = [x.get("hook") for x in t.log(A)]
        self.assertIn("plan", logged, "the routed check writes its log line (P7)")
        self.lookup(A, "lookup-record", {"tool_name": "Monitor", "tool_input": {"command": "tail -f x.log"},
                                         "tool_response": "Monitor started (task bz4dv0pvj, expires in 30m)",
                                         "tool_use_id": "toolu_route02"}, wait=True)   # a clean call runs detached
        self.assertEqual(plans.load(t.p4, A)["steps"][1]["tasks"][0]["id"], "bz4dv0pvj",
                         "a Monitor is recorded by the id its result gives (M1)")

    def test_a_session_whose_hook_list_lacks_the_route_gets_its_plan_from_its_transcript(self):
        """Sessions started before the lookup entries reached them hold only phi's own entries: their update_plan
        calls are read back from the transcript at the next message, each once."""
        t = self.t
        path = os.path.join(self._tmp.name, "a-transcript.jsonl")
        rows = [{"type": "user", "message": {"role": "user", "content": "Move the store layout into phi, in steps"}}]

        def add(k, inp):
            rows.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"toolu_rp{k}", "name": "mcp__ccd_turn__update_plan", "input": inp}]}})
            rows.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"toolu_rp{k}", "content": "Plan updated."}]}})
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r) + chr(10) for r in rows))

        def message(text):
            return context(t.hook("user-prompt-submit", A, {"hook_event_name": "UserPromptSubmit", "prompt": text,
                                                           "transcript_path": path}))
        add(0, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        message("go on")
        self.assertEqual([x["addr"] for x in plans.load(t.p4, A)["steps"]], ["2.1", "2.2"], "read back")
        self.plan(TOP, items("Port the hooks", "Move the store layout into temportal instead", "Write the docs", at=1))
        add(1, {"advance": True})
        ctx = message("next")
        self.assertEqual(plans.load(t.p4, A)["current"], "2.2")
        self.assertIn("step 2.2 starts now", ctx, "the step boundary is answered at the message")
        self.assertIn("your root step 2", ctx)
        self.lookup(A, "lookup-record", {"tool_name": "mcp__ccd_turn__update_plan", "tool_input": {"advance": True},
                                         "tool_response": "Plan updated.", "tool_use_id": "toolu_rp1"})
        self.assertEqual(plans.load(t.p4, A)["current"], "2.2", "a replayed call is not applied again by a hook")

    def task(self, host, command, task_id):
        r = self.t.hook("task", host, {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                       "tool_input": {"command": command, "run_in_background": True},
                                       "tool_response": f"Command running in background with ID: {task_id}. Output"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "", "registering prints nothing")

    def test_a_background_task_whose_feature_a_sibling_replaces_is_told_to_stop(self):
        t = self.t
        if not shutil.which("git"):
            self.skipTest("no git")
        work = os.path.join(t.proj, "work")
        os.makedirs(os.path.join(work, "lib"))
        with open(os.path.join(work, "lib", "x.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        for args in (("init", "-q"), ("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "A")):
            subprocess.run(["git", "-C", work, *args], check=True, capture_output=True)
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(B, items("Check the notes relay against lib", "Write the docs"))
        x = os.path.join(work, "lib", "x.py").replace("\\", "/")
        self.task(B, f"python -I check_relay.py {x}", "bgcheck01")
        p = plans.load(t.p4, B)
        self.assertEqual(p["steps"][0]["tasks"][0]["id"], "bgcheck01")
        self.assertTrue(p["steps"][0]["tasks"][0]["heads"], "the head it runs against is kept")
        self.plan(A, items("Replace the notes relay", "Commit it"))
        t.cli(A, "note", f"replaces: the notes relay in `{x}` with plan steps", "--source", "commit hhh888")
        t.stop(A, "replace it", uuid="a1")
        ctx = self.plan(B, {"advance": True})
        self.assertIn("task bgcheck01", ctx)
        self.assertIn("`TaskStop bgcheck01`", ctx)
        self.assertIn("step 3.1 was marked done while task bgcheck01 under it is flagged and still open", ctx)
        notice = ("<task-notification>\n<task-id>bgcheck01</task-id>\n<status>completed</status>\n"
                  "<summary>Background command finished</summary>\n</task-notification>")
        t.say(B, notice)
        self.assertEqual(plans.load(t.p4, B)["steps"][0]["tasks"][0]["status"], "completed",
                         "a completion read from the message closes the task")

    def test_a_foreground_command_is_no_task(self):
        r = self.t.hook("task", B, {"tool_name": "Bash", "tool_input": {"command": "git status"},
                                    "tool_response": "On branch main"})
        self.assertEqual(r.stdout.strip(), "")
        self.assertFalse(any(st.get("tasks") for st in plans.load(self.t.p4, B).get("steps") or []))

    def test_a_finished_child_a_newer_note_supersedes_is_retired(self):
        t = self.t
        self.plan(TOP, items("Move the store layout into recall", "Write the exporter docs", at=0))
        t.say(A, "Move the store layout into recall")
        self.plan(A, {"items": [{"content": "Rename the folders", "status": "completed"},
                                {"content": "Commit the move", "status": "completed"}]})
        t.stop(A, "the move", report="Moved store/ and models/ under recall/ at cb3b6d2.", uuid="a1")
        self.plan(TOP, {"advance": True})
        t.say(B, "Write the exporter docs, step 2")
        self.plan(B, items("Draft the exporter docs", "Publish them"))
        t.cli(B, "note", "replaces: the store layout move into recall with the move into phi", "--source", "57e7c99")
        t.stop(B, "supersede", uuid="b1")
        anchor = json.load(open(relay.anchor_path(t.p4, TOP), encoding="utf-8"))
        self.assertNotIn(A, anchor["nodes"], "left out of the anchor")
        self.assertIn(B, anchor["nodes"])
        self.assertEqual(t.session(A)["stale"]["by"], B)
        kept = [json.loads(l) for l in open(os.path.join(t.dir(TOP), "notes.jsonl"), encoding="utf-8")]
        self.assertTrue(kept[-1]["claim"].startswith(f"replaces: \"the layout child\" ({A}) as a live node."))
        self.assertIn("cb3b6d2", kept[-1]["claim"], "its still-true outcome, with its report")
        ctx = context(t.say(TOP, "next"))
        self.assertIn(f"\"the layout child\" ({A}). Archive them now with `mcp__ccd_session_mgmt__archive_session`", ctx)
        self.assertNotIn("Archive them now", context(t.say(TOP, "and next")), "said once")
        told = context(t.say(A, "are you still on it?"))
        self.assertIn("this session's work is superseded and it is stale", told)
        t.record(KID2 + "x", TOP, title="a pathless child")
        whole = context(t.say(KID2 + "x", "Help out wherever needed"))
        turns = whole.split("The last turn of", 1)[1].split("The page this comes from", 1)[0]             if "The last turn of" in whole else ""
        self.assertNotIn("the layout child", turns, "a stale node's last turn is no background (ST3)")
        t.record(GRAND, TOP, title="a later child")
        self.assertNotIn("the layout child", context(t.say(GRAND, "Write `docs/exporter.md`, step 2")),
                         "left out of a fresh child's start")
        self.plan(TOP, items("Move the store layout into recall", "Write the exporter docs for phi", at=1))
        self.assertIn("your root step 2 in the plan of \"top\" was revised", self.plan(B, {"advance": True}),
                      "the other two keep relaying")
        t.stop(A, "re-based", report="Re-based onto phi/.", uuid="a2")
        self.assertNotIn("stale", t.session(A), "told and a turn of its own ended since: live again (ST1)")
        t.stop(B, "another turn", uuid="b2")
        kept = [json.loads(l) for l in open(os.path.join(t.dir(TOP), "notes.jsonl"), encoding="utf-8")]
        self.assertEqual(sum(1 for k in kept if "as a live node" in k["claim"]), 1, "never retired twice (ST2)")

    def test_a_fresh_child_starts_with_its_root_step_and_a_fork_has_it_pinned(self):
        t = self.t
        t.record(GRAND, TOP, title="the step child")
        ctx = context(t.say(GRAND, "Write the docs for step 3"))
        self.assertIn("this session is for step 3 of its parent's plan, \"Write the layout docs\"", ctx)
        self.assertIn("- 2 [in_progress] Move the store layout into phi", ctx, "the parent's plan around it")
        self.assertIn("3.1, 3.2, and so on", ctx)
        t2 = Tree(os.path.join(self._tmp.name, "f"))
        t2.record(TOP, title="top")
        t2.record(GRAND, TOP, title="the forked step child")
        t2.say(TOP, "Build it")
        r = t2.hook("plan", TOP, {"tool_name": "mcp__ccd_turn__update_plan", "tool_input": items("a", "b", at=1)})
        self.assertEqual(r.returncode, 0)
        t2.say(GRAND, "Task (from the session that started this one):\nDo the b part")
        later = context(t2.say(GRAND, "carry on"))
        self.assertIn("It is for step 2 of its parent's plan; its own steps are 2.1, 2.2", later)


class OwnLines(unittest.TestCase):
    """R6: a report quoting phi's relay must not be relayed again, and queued turn reports stay few."""

    def test_phi_lines_are_taken_out_of_a_report(self):
        report = ("I wrote x.txt and marked step x done.\n"
                  "phi (p4-phi): step 1.1 starts now, \"x: write nodetest/split/x.txt\". What bears on it:\n"
                  "- across: \"Live node test A\" is on 1.3, \"Ask a sub-agent to summarise nodetest/a1.txt\".\n"
                  "B ended a turn whose words bear on your open step(s): 1.1. Check whether those steps still hold.")
        got = plans.own_removed(report)
        self.assertIn("I wrote x.txt", got)
        for gone in ("phi (p4-phi)", "across:", "bear on your open step", "nodetest/a1.txt"):
            self.assertNotIn(gone, got)

    def test_only_the_newest_turn_reports_wait(self):
        home = tempfile.mkdtemp(prefix="p4-phi-own-")
        try:
            sid = "local_own"
            os.makedirs(relay._dir(home, sid))
            relay._write_json(os.path.join(relay._dir(home, sid), "session.json"), {"sessionId": sid})
            for k in range(6):
                relay.warn(home, sid, f"turn:x:{k}", f"report {k}")
            relay.warn(home, sid, "mark:y", "a deprecation")
            s = relay._read_json(os.path.join(relay._dir(home, sid), "session.json"))
            keys = [w["key"] for w in s["relayPending"]]
            self.assertEqual(keys, ["turn:x:3", "turn:x:4", "turn:x:5", "mark:y"])
            self.assertIn("turn:x:0", s["relayWarned"], "a dropped report counts as told, so it is not queued again")
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
