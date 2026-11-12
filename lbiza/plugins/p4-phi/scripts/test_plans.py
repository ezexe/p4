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
from test_phi import CLI, GRAND, KID, KID2, TOP, Tree, context  # noqa: E402
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

    def test_a_sub_agent_is_a_child_node_of_the_step_that_launched_it(self):
        t, home = self.t, self.t.p4
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        sa = relay._session(home, A)
        text = plans.agent_launch(home, sa, "toolu_a1", {"prompt": "read the layout code", "description": "probe"})
        self.assertIn("sub-agent of", text)
        self.assertIn("step 2.1", text)
        self.assertTrue(plans.agent_bind(home, sa, "agentx001"), "its first tool call binds its id")
        self.assertFalse(plans.agent_bind(home, sa, "agentx001"))
        step = plans.load(home, A)["steps"][0]
        self.assertEqual([(x["id"], x["tool"]) for x in step["tasks"]], [("agentx001", "Agent")])
        self.assertNotIn("agentsPending", plans.load(home, A))
        relay.make_anchor(home, TOP, "2026-11-12 18:00")
        node = json.load(open(relay.anchor_path(home, TOP), encoding="utf-8"))["nodes"][A]
        self.assertEqual(node["plan"]["steps"][0]["tasks"][0]["id"], "agentx001", "the delta carries it")
        self.assertEqual(plans.agent_warn(home, sa, "agentx001"), "", "nothing changed since its launch")
        t.cli(B, "note", "replaces: the old docs layout in docs/layout.md", "--source", "test")
        relay.make_anchor(home, TOP, "2026-11-12 18:01")
        warned = plans.agent_warn(home, sa, "agentx001")
        self.assertIn("the old docs layout", warned)
        self.assertEqual(plans.agent_warn(home, sa, "agentx001"), "", "told once")
        self.plan(A, items("Rewrite p4conf.LAYOUT and OLDER", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual(plans.load(home, A)["steps"][0]["tasks"][0]["id"], "agentx001", "SA1: reworded in place")
        self.assertIn("now reads \"Rewrite p4conf.LAYOUT and OLDER\"", plans.agent_warn(home, sa, "agentx001"))
        self.assertIn(f"down: \"the layout child\" launched sub-agent agentx001 for its step 2.1",
                      " ".join(w["text"] for w in relay._session(home, TOP).get("relayPending") or []), "SA2")

    def test_a_sub_agents_step_revised_and_its_stop(self):
        home = self.t.p4
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        sa = relay._session(home, A)
        plans.agent_launch(home, sa, "toolu_a2", {"prompt": "move it"})
        plans.agent_bind(home, sa, "agenty002")
        p = plans.load(home, A)
        p["steps"][0]["content"] = "Rewrite p4conf.LAYOUT for the temportal folder"
        relay._write_json(plans._path(home, A), p)
        self.assertIn("now reads \"Rewrite p4conf.LAYOUT for the temportal folder\"", plans.agent_warn(home, sa, "agenty002"))
        self.assertTrue(plans.agent_stop(home, sa, "agenty002", "Moved; tests green."))
        task = plans.load(home, A)["steps"][0]["tasks"][0]
        self.assertEqual((task["status"], task["result"]), ("completed", "Moved; tests green."))
        self.assertEqual(plans.agent_warn(home, sa, "agenty002"), "", "a stopped sub-agent is told nothing")
        self.assertTrue(plans.agent_stop(home, sa, "agentz003", "no tools used"), "one that made no call is bound at stop")

    def three(self, *extra):
        p = self.t.proj
        return items(f"Port the exporter in {p}/src/export/flush.py to the new writer",
                     f"Rewrite the parser tables in {p}/src/parse/tables.py for speed",
                     f"Document the store layout in {p}/docs/layout.md with examples", *extra)

    def test_three_disjoint_steps_are_advised_to_split(self):
        self.t.say(B, "Do the three parts")
        ctx = self.plan(B, self.three())
        self.assertIn("can each run on their own", ctx)
        for a in ("2.1", "2.2", "2.3"):
            self.assertIn(a, ctx.split("can each run")[0])
        self.assertIn("`initiation` `user_asked`", ctx)
        self.assertIn("use_worktree: false", ctx)
        self.assertIn("Judged by", ctx)
        self.assertNotIn("can each run", self.plan(B, {"advance": True}) or "", "said once per set")
        done = self.three()
        done["items"][0]["status"] = "completed"
        done["items"][1]["status"] = "in_progress"
        self.assertNotIn("can each run", self.plan(B, done) or "", "SP1: steps advised before are not again")
        more = self.three(f"Draw the import graph of {self.t.proj}/tools/graph.py for the docs site")
        again = self.plan(B, more) or ""
        self.assertIn("2.4", again.split("can each run")[0], "a new free step is named")
        self.assertNotIn("2.2 \"", again.split("can each run")[0])

    def test_steps_naming_no_file_stay_and_drawn_trees_match_nothing(self):
        """The gap: SA1 and SA2 named no file and both edited plans.py. The noise: a drawn tree's addresses."""
        plan = {"steps": [{"addr": "1", "content": "SA1 keep tasks of a reworded step", "status": "in_progress"},
                          {"addr": "2", "content": "SA2 anchor and down-line for sub-agents", "status": "pending"}]}
        free, kept = plans.judge(plan, "")
        self.assertEqual(free, [])
        self.assertIn("names no file", kept[0][1])
        steps = [{"addr": "1", "content": "Waits and relays stay in place"},
                 {"addr": "2", "content": "Run every suite, commit, fast-forward"}]
        report = ("Here is the tree:\n\u251c\u2500\u2500 x/ \u251c\u2500\u2500 child for step 1 plan: 1.1, 1.2\n"
                  "```\nstep 2 plan: 2.1 run every suite\n```\nNothing else.")
        self.assertEqual(plans.matches(report, steps, [], ""), [])

    def test_a_plan_of_waits_and_relays_is_serial(self):
        """SP2, live: four serial steps were advised to split."""
        plan = {"steps": [{"addr": "1", "content": "Wait for SA1 and SA2 on main", "status": "in_progress"},
                          {"addr": "2", "content": "Tester confirms nodes_test 14/14 on both lists", "status": "pending"},
                          {"addr": "3", "content": "Push p4 and phi main", "status": "pending"},
                          {"addr": "4", "content": "Tell the side chat the reply can go", "status": "pending"}]}
        free, kept = plans.judge(plan, "")
        self.assertEqual(free, [])
        self.assertEqual([a for a, _ in kept], ["1", "2", "3", "4"])
        self.assertEqual(plans.split_advice(self.t.p4, relay._session(self.t.p4, B), plan, True, ""), "")
        mine = {"steps": [{"addr": "1", "content": "Waits and relays stay in place", "status": "in_progress"},
                          {"addr": "2", "content": "Run every suite, commit, fast-forward", "status": "pending"}]}
        self.assertEqual(plans.judge(mine, "")[0], [], "a landing step anywhere in its words, live")

    def test_a_step_that_checks_or_lands_the_others_stays(self):
        self.t.say(B, "Do the parts")
        ctx = self.plan(B, self.three("Test, commit and fast-forward main after review"))
        self.assertIn("2.4 (", ctx)
        self.assertNotIn("2.4 \"", ctx.split("can each run")[0])

    def test_a_step_using_anothers_results_stays_in_place(self):
        self.t.say(B, "Do the parts")
        ctx = self.plan(B, self.three("Write the summary report using the exporter's results for the release"))
        self.assertIn("2.4 (leans on another step (\"using\"))", ctx)
        self.assertNotIn("2.4 \"", ctx.split("can each run")[0])

    def test_two_steps_on_one_file_stay_in_place(self):
        p = self.t.proj
        self.t.say(B, "Do the parts")
        ctx = self.plan(B, items(f"Port the exporter in {p}/src/export/flush.py to the new writer",
                                 f"Speed up the buffered flush path in {p}/src/export/flush.py for large rows",
                                 f"Document the store layout in {p}/docs/layout.md with examples"))
        self.assertNotIn("can each run", ctx or "", "one free step is no split")

    def test_past_the_cap_everything_stays_in_place(self):
        self.t.say(B, "Do the three parts")
        for k in range(8):
            self.t.record(f"local_cap{k:05d}", B, title=f"cap {k}")
            self.t.say(f"local_cap{k:05d}", "work")
        ctx = self.plan(B, self.three())
        self.assertIn("Every step stays here as a sub-step", ctx)
        self.assertNotIn("user_asked", ctx)

    def test_in_a_turn_another_session_began_the_advice_is_start_requests(self):
        self.t.say(B, "Do the three parts")
        self.t.say(B, '<cross-session-message from="local_x">go on</cross-session-message>')
        ctx = self.plan(B, self.three())
        self.assertIn("write each as a start request, `phi.py request", ctx)
        self.assertNotIn("`initiation` `user_asked`", ctx)
        self.assertNotIn("own_initiative", ctx)

    def test_a_child_waiting_on_a_question_the_chain_can_settle_is_flagged_up(self):
        """Act-don't-wait: the parent hears of a child's open question that is not the user's to answer."""
        self.assertIn("python3", plans.waiting_on("Done. Should the runner use the py launcher or python3?"))
        self.assertEqual(plans.waiting_on("Done. Shall I push it to origin?"), "", "authority: the user's")
        self.assertEqual(plans.waiting_on("Done, nothing open."), "")
        s = relay._session(self.t.p4, A)
        plans.turn_relay(self.t.p4, s, {"id": "r1", "report": "Moved it. Should phi/ keep the old folder name?"}, [])
        pend = relay._session(self.t.p4, TOP).get("relayPending") or []
        self.assertTrue(any("ended its turn on a question" in w["text"] and A in w["text"] for w in pend))

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

    def test_a_progress_report_naming_a_childs_work_is_not_nagged(self):
        """The miss this closes: a parent's progress report shared words with a child's steps and was nagged as a
        change it never sent."""
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        report = ("The layout child is running the relay suite against the notes relay now; the fresh slice sizes "
                  "are next.")
        t.stop(TOP, "progress", report=report, uuid="p3")
        self.assertIn("bear on your open step(s): 2.1", self.plan(A, {"advance": True}), "still relayed down")
        self.assertNotIn("relay it", context(t.say(TOP, "next")), "progress is no change")
        t.stop(TOP, "decide", [("mcp__ccd_session_mgmt__send_message", {"session_id": A, "message": "void"}, "sent")],
               report="The relay suite checks are void; the notes relay is replaced.", uuid="p4")
        self.assertNotIn("relay it", context(t.say(TOP, "and next")), "the app's send_message counts as sent")

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


class TopOrchestrates(unittest.TestCase):
    """Rule 1: the top session keeps itself free for orchestration. Rule 2: a child started to be archived when
    done leaves its outcome on the parent and is named for archiving. And an archived child leaves the relay."""

    C = "local_kid00003"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.record(A, TOP, title="the layout child")
        self.t.say(TOP, "Build the exporter")

    def tearDown(self):
        self._tmp.cleanup()

    plan = TreeOfPlans.plan

    def check(self, host, tool, inp, tid):
        """A tool call's PreToolUse through recall's lookup-check entry, as every open session runs it."""
        root = os.path.dirname(HERE)
        body = {"session_id": CLI[host], "cwd": self.t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": tid}
        r = subprocess.run(["sh", os.path.join(root, "hooks", "recall-hook.sh"), "lookup-check"],
                           input=json.dumps(body), capture_output=True, text=True, timeout=60, env=self.t.env(host))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"].get("additionalContext", "") if r.stdout.strip() else ""

    def test_a_top_sessions_work_step_is_advised_to_a_child_and_landing_stays(self):
        p = self.t.proj
        ctx = self.plan(TOP, items(f"Port the exporter in {p}/src/export/flush.py to the new writer",
                                   "Run the suites, commit and push the exporter"))
        self.assertIn("top session of its tree", ctx)
        self.assertIn("(a) step 1 \"Port the exporter", ctx)
        self.assertIn("`initiation` `user_asked`", ctx)
        self.assertIn("archive when done", ctx)
        self.assertIn("Staying here: 2 (checks or lands the work)", ctx)
        self.assertNotIn("(b)", ctx, "the landing step is no child")
        self.assertNotIn("top session of its tree", self.plan(TOP, {"advance": True}) or "", "said once per set")
        landing = {"steps": [{"addr": str(k + 1), "content": c, "status": "pending"} for k, c in
                             enumerate(("Test and commit the port", "Merge and push main", "Release 0.9"))]}
        groups, kept = plans.top_groups(landing, "")
        self.assertEqual((groups, [a for a, _ in kept]), ([], ["1", "2", "3"]))

    def test_a_serial_pair_of_work_steps_becomes_one_child(self):
        p = self.t.proj
        ctx = self.plan(TOP, items(f"Write the parser in {p}/src/parse.py",
                                   f"Then add tests for the parser in {p}/tests/test_parse.py",
                                   f"Document the store layout in {p}/docs/layout.md with examples",
                                   "Commit and fast-forward main"))
        self.assertIn("(a) steps 1, 2 in order, as one child", ctx)
        self.assertIn("(b) step 3 \"Document", ctx)
        self.assertNotIn("(c)", ctx)
        self.assertIn("4 (checks or lands the work)", ctx)
        kid = self.plan(A, items(f"Write the parser in {p}/src/parse.py", f"Document it in {p}/docs/layout.md now"))
        self.assertNotIn("top session of its tree", kid or "", "a child keeps today's split rules")

    def test_the_nudge_fires_once_on_a_top_session_edit_and_never_on_git_status(self):
        p = self.t.proj
        self.plan(TOP, items(f"Port the exporter in {p}/src/export/flush.py to the new writer", "Commit and push"))
        marker = os.path.join(self.t.p4, "phi", ".nudge", CLI[TOP])
        self.assertTrue(os.path.exists(marker), "armed while a work step is in progress")
        self.assertEqual(self.check(TOP, "Bash", {"command": "git status"}, "toolu_n1"), "")
        self.assertEqual(self.check(TOP, "Bash", {"command": "git log --oneline -3 && git diff"}, "toolu_n2"), "")
        self.assertEqual(self.check(TOP, "Read", {"file_path": f"{p}/src/export/flush.py"}, "toolu_n3"), "")
        said = self.check(TOP, "Edit", {"file_path": f"{p}/src/export/flush.py", "old_string": "a", "new_string": "b"},
                          "toolu_n4")
        self.assertIn("this is the top session", said)
        self.assertIn("hand it to a child session", said)
        self.assertFalse(os.path.exists(marker), "disarmed once said")
        self.assertEqual(self.check(TOP, "Edit", {"file_path": f"{p}/src/export/x.py"}, "toolu_n5"), "", "once a step")
        self.plan(TOP, {"advance": True})
        self.assertFalse(os.path.exists(marker), "a landing step owes no nudge")
        self.assertEqual(self.check(TOP, "Bash", {"command": "git commit -am port && git push"}, "toolu_n6"), "")
        self.t.say(A, "Do the layout")
        self.plan(A, items(f"Port the exporter in {p}/src/export/flush.py to the new writer", "Commit it"))
        self.assertEqual(self.check(A, "Edit", {"file_path": f"{p}/src/export/flush.py"}, "toolu_n7"), "",
                         "a child is never nudged")

    def test_a_child_archived_when_done_leaves_a_replaces_note_and_the_parents_archive_line(self):
        t, C = self.t, self.C
        t.record(C, TOP, title="the port child")
        t.say(C, HANDED_DISPOSABLE)
        self.assertTrue(relay._session(t.p4, C).get("disposable"))
        self.plan(C, items("Port the exporter", "Run its suite"))
        self.plan(C, {"done": [1, 2]})
        r = t.stop(C, "Port the exporter", [("Edit", {"file_path": f"{t.proj}/src/export/flush.py"}, "ok")],
                   report="Ported; the suite passes. Nothing left open.", uuid="d1")
        self.assertEqual(r.returncode, 0, r.stderr)
        notes = [n["claim"] for n in relay._rows(os.path.join(relay._dir(t.p4, TOP), "notes.jsonl"))]
        mine = [n for n in notes if n.startswith("replaces:") and C in n]
        self.assertEqual(len(mine), 1, notes)
        self.assertIn("archived when done", mine[0])
        self.assertIn("flush.py", mine[0])
        self.assertIn("Still open:", mine[0])
        self.assertNotIn(C, plans._children(t.p4, TOP), "out of the down-lines")
        self.assertNotIn(C, (relay._read_json(relay.anchor_path(t.p4, TOP)).get("nodes") or {}))
        line = context(t.say(TOP, "what next"))
        self.assertIn("Archive them now with `mcp__ccd_session_mgmt__archive_session`", line)
        self.assertIn(C, line.split("finished, started to be archived when done")[1])
        self.assertNotIn("finished, started to be archived", context(t.say(TOP, "and then")), "said once")

    def test_a_numbered_check_is_work_and_starting_a_check_is_orchestration(self):
        """Check 6: "Check 1: nothing hidden in AppData" was kept on the top as landing work, and "Start the
        owner's-eye acceptance check" was advised as work."""
        groups, kept = plans.top_groups({"steps": [
            {"addr": str(k + 1), "content": c, "status": "pending"} for k, c in enumerate((
                "Check 1: nothing hidden in AppData", "Start the owner's-eye acceptance check",
                "Check the session's own landed work", "Kick off the review session",
                "Run the docs check", "Start the dev server and port the CLI in src/cli.py"))]}, "")
        self.assertEqual([[st["addr"] for st in g] for g in groups], [["1"], ["6"]])
        why = dict(kept)
        self.assertEqual(why["2"], "starts a check, test or session, which is orchestration")
        self.assertEqual(why["3"], "checks or lands the work")
        self.assertIn("4", why)
        self.assertIn("5", why)

    def test_queueing_sending_passing_or_handing_to_a_session_is_orchestration(self):
        groups, kept = plans.top_groups({"steps": [
            {"addr": str(k + 1), "content": c, "status": "pending"} for k, c in enumerate((
                "Queue the memory-patch flag for the p4-phi fixer session",
                "Pass the scratchpad findings to the temportal session", "Hand step 3 to a child",
                "Pass the parser output to the formatter in src/fmt.py"))]}, "")
        self.assertEqual([[st["addr"] for st in g] for g in groups], [["4"]])
        self.assertEqual([a for a, _ in kept], ["1", "2", "3"])

    def test_two_children_retired_at_once_are_both_named_for_archiving(self):
        """Check 6: two unlocked read-modify-writes of the parent's session.json lost one child."""
        import threading
        home = self.t.p4
        ids = [f"local_race{k:04d}" for k in range(8)]
        threads = [threading.Thread(target=relay._pend_archive, args=(home, TOP, i, {"title": i}, "done"))
                   for i in ids]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        pend = relay._session(home, TOP).get("staleChildren") or []
        self.assertEqual(sorted(x["id"] for x in pend), ids)
        self.assertFalse(os.path.exists(os.path.join(relay._dir(home, TOP), "session.json.lock")))

    def test_a_retired_childs_note_keeps_the_findings_of_its_final_report(self):
        """Check 2: the replaces: note kept only "Check 2 is done and reported", the findings being in the message
        before it."""
        t, C = self.t, self.C
        t.record(C, TOP, title="check 2")
        t.say(C, HANDED_DISPOSABLE)
        t.cli(C, "done", "Check 2 is done and reported")
        findings = "Finding: the relay drops the third row because flush_rows stops one short."
        path = os.path.join(self._tmp.name, "c2.jsonl")
        lines = [{"type": "user", "message": {"role": "user", "content": "Run check 2"}, "uuid": "c2",
                  "timestamp": "2026-11-12T19:00:00.000Z"},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": findings}]}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": "Check 2 is done and reported."}]}}]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")
        r = t.hook("stop", C, {"hook_event_name": "Stop", "transcript_path": path,
                               "last_assistant_message": "Check 2 is done and reported."})
        self.assertEqual(r.returncode, 0, r.stderr)
        notes = [n["claim"] for n in relay._rows(os.path.join(relay._dir(t.p4, TOP), "notes.jsonl"))
                 if n["claim"].startswith("replaces:") and C in n["claim"]]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(findings, notes[0])
        self.assertIn("Its findings, from its final report", notes[0])
        bare = relay.findings_of({"done": "done", "report": "Done."})
        self.assertIn("left no report text", bare)
        self.assertNotIn('"Done."', bare)

    def test_phi_disposable_marks_a_child_and_done_retires_it(self):
        t, C = self.t, self.C
        t.record(C, TOP, title="the cli child")
        t.say(C, "Check the exporter's ports table")
        self.assertFalse(relay._session(t.p4, C).get("disposable"))
        r = t.cli(C, "disposable")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.cli(C, "done", "ran the ports check; all rows present")
        t.stop(C, "Check the exporter's ports table", report="All rows present.", uuid="d2")
        self.assertTrue(relay._session(t.p4, C).get("doneRetired"))
        self.assertIn(C, context(t.say(TOP, "next")))

    def test_an_archived_child_is_gone_from_the_parents_down_lines(self):
        t, p = self.t, self.t.proj
        self.plan(TOP, items("Commit the layout", "Push main", "Tell the docs side"))
        t.say(A, "Move the layout")
        self.plan(A, items(f"Move the layout in {p}/src/layout.py", "Commit the move"))
        down = self.plan(TOP, {"advance": True})
        self.assertIn("down: \"the layout child\" has 0 of 2 steps done", down)
        self.plan(A, {"advance": True})
        rec = os.path.join(t.app, A + ".json")
        with open(rec, encoding="utf-8") as f:
            d = json.loads(f.read())
        d["isArchived"] = True
        with open(rec, "w", encoding="utf-8") as f:
            f.write(json.dumps(d))
        self.assertNotIn("the layout child", self.plan(TOP, {"advance": True}) or "")
        self.assertNotIn(A, plans._children(t.p4, TOP))
        self.assertTrue(relay._session(t.p4, A).get("archived"), "kept, for the machines the store syncs to")
        t.record(B, TOP, title="the docs child")
        t.say(B, "Write the docs")
        self.assertIn(B, plans._children(t.p4, TOP))
        os.remove(os.path.join(t.app, B + ".json"))
        self.assertNotIn(B, plans._children(t.p4, TOP), "a record gone from the app is gone from the tree")

    def test_a_session_management_step_stays_at_the_top(self):
        p = self.t.proj
        ctx = self.plan(TOP, items("Archive the finished orchestrator-rule child",
                                   f"Port the exporter in {p}/src/export/flush.py to the new writer",
                                   "Relay the new layout to the docs session", "Start a child session for the docs",
                                   "Review the port child's report", "Message the layout child about the move"))
        self.assertIn("(a) step 2 \"Port the exporter", ctx)
        self.assertNotIn("(b)", ctx, "no session-management step is advised to a child")
        self.assertNotIn("Archive the finished", ctx.split("Staying here")[0])
        groups, kept = plans.top_groups({"steps": [
            {"addr": str(k + 1), "content": c, "status": "pending"} for k, c in enumerate((
                "Archive the finished orchestrator-rule child", "Check the docs child's progress",
                "Send the exporter child its brief", "Start the dev server and port the CLI in src/cli.py"))]}, "")
        self.assertEqual([a for a, _ in kept], ["1", "2", "3"])
        self.assertEqual([[st["addr"] for st in g] for g in groups], [["4"]], "starting a server is work")
        marker = os.path.join(self.t.p4, "phi", ".nudge", CLI[TOP])
        self.assertFalse(os.path.exists(marker), "archiving a child owes no nudge")

    def test_phis_own_commands_are_never_nudged(self):
        p = self.t.proj
        self.plan(TOP, items(f"Port the exporter in {p}/src/export/flush.py to the new writer", "Commit and push"))
        marker = os.path.join(self.t.p4, "phi", ".nudge", CLI[TOP])
        self.assertTrue(os.path.exists(marker))
        for k, cmd in enumerate((
                'P=E:/projects/p4/lbiza/plugins/p4-phi/scripts/phi.py; python -I -X utf8 "$P" note "a; b > c" --source x',
                'python -I -X utf8 "E:/p4/scripts/phi.py" done "ran the suites"',
                'cd /e/p4 && export P=/e/p4/phi.py && python "${P}" done ok',
                '$P = "E:/p4/phi.py"; & python $P note "x"')):
            self.assertEqual(self.check(TOP, "Bash", {"command": cmd}, f"toolu_p{k}"), "", cmd)
        self.assertTrue(os.path.exists(marker), "still armed")
        self.assertIn("this is the top session",
                      self.check(TOP, "Bash", {"command": 'P=x; python "$P" note y && make'}, "toolu_p9"))

    def test_top_sessions_relay_as_siblings_and_an_archived_top_drops_out(self):
        t, T2 = self.t, "local_top00002"
        t.record(T2, title="the second top")
        t.say(T2, "Rework the fence exporter")
        self.plan(TOP, items("Port the fence exporter's ports table to the new writer", "Commit and push"))
        self.assertIn(T2, relay._siblings(t.p4, relay._session(t.p4, TOP)), "two tops are siblings")
        self.assertIn(TOP, relay._siblings(t.p4, relay._session(t.p4, T2)))
        r = t.cli(T2, "note", "deprecates: the fence exporter's v1 ports table", "--source", "commit fff111")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.stop(T2, "deprecate v1", report="The fence exporter's ports table now goes to the new writer only; "
                                         "v1 is gone.", uuid="t2a")
        ctx = context(t.say(TOP, "next"))
        self.assertIn("deprecates: the fence exporter's v1 ports table", ctx, "a deprecation crosses between tops")
        self.assertIn("\"the second top\", a session beside you, ended a turn whose words bear on your open step",
                      ctx, "a turn report crosses as a sibling's")
        anchor = json.load(open(relay.anchor_path(t.p4, ""), encoding="utf-8"))
        self.assertIn(T2, anchor["nodes"])
        rec = os.path.join(t.app, T2 + ".json")
        with open(rec, encoding="utf-8") as f:
            d = json.loads(f.read())
        d["isArchived"] = True
        with open(rec, "w", encoding="utf-8") as f:
            f.write(json.dumps(d))
        self.assertNotIn(T2, relay._siblings(t.p4, relay._session(t.p4, TOP)), "an archived top drops out")
        t.stop(TOP, "a turn", uuid="t1a")
        anchor = json.load(open(relay.anchor_path(t.p4, ""), encoding="utf-8"))
        self.assertNotIn(T2, anchor["nodes"], "and leaves the root anchor")
        tree = t.cli(TOP, "tree").stdout
        self.assertIn(TOP, tree)
        self.assertNotIn(T2, tree, "an archived top is not printed")

    def test_a_child_archived_by_hand_is_not_named_for_archiving(self):
        t, C = self.t, self.C
        t.record(C, TOP, title="the store migration child")
        t.say(C, HANDED_DISPOSABLE)
        self.plan(C, items("Migrate the store", "Run its suite"))
        self.plan(C, {"done": [1, 2]})
        r = t.stop(C, "Migrate the store", report="Migrated. Nothing left open.", uuid="h1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(relay._session(t.p4, C).get("doneRetired"))
        rec = os.path.join(t.app, C + ".json")
        with open(rec, encoding="utf-8") as f:
            d = json.loads(f.read())
        d["isArchived"] = True
        with open(rec, "w", encoding="utf-8") as f:
            f.write(json.dumps(d))
        line = context(t.say(TOP, "what next"))
        self.assertNotIn("Archive them now", line, "archived by hand: no archive line names it")
        self.assertNotIn("started to be archived when done", line)


HANDED_DISPOSABLE = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n"
                     "</system-reminder>\n\nTask:\nPort the exporter to the new writer. This session is marked "
                     "archive when done.\n\nDone looks like: the suite passes.")


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
