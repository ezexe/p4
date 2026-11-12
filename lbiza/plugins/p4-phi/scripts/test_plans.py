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

    def test_the_parent_revising_the_childs_root_reaches_it_at_its_next_advance(self):
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual(self.plan(A, {"advance": True}), "", "nothing bears on 2.2: quiet")
        self.plan(TOP, items("Port the hooks", "Move the store layout into temportal instead", "Write the layout docs",
                             at=1))
        ctx = self.plan(A, {"advance": True})
        self.assertIn("step 2.3 starts now", ctx)
        self.assertIn("your root step 2 in the plan of \"top\" was revised", ctx)
        self.assertIn("up: the parent revised your root step 2", ctx)
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
