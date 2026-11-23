#!/usr/bin/env python3
"""progress.py: a session tree's goals, task lists and plan loops as data, for the pane of `/phi-pane`.

    python -m pytest tests/p4-phi/test_progress.py

goal.md names no hook event and no file for a goal, so its state is read from p4-phi's own record on session.json,
and from the transcript's goal row for a goal a person typed. plan-planner, "The plan loop", gives the loop log its
shape: a last heading `## Loop log` and one line a round.
"""

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import phi  # noqa: E402
import progress  # noqa: E402

TOP, KID, GONE = "local_top00001", "local_kid00001", "local_kid00002"
TICKS = chr(96) * 3

PLAN = f"""# The exporter's move

## Context

No worker lands this.

## 1. The writer

- **Files:** `src/export/writer.py`
- **Depends on:** none
- **Checks:** `python -m pytest tests/test_writer.py`
- **Evidence:** landed at `src/export/writer.py:10-40`, and the check passed.

{TICKS}markdown
## Loop log

- Round 9 of 5: a log quoted in a fence is no log
{TICKS}

## 2. The flush

- **Files:** `src/export/flush.py`
- **Depends on:** 1
- **Checks:** `python -m pytest tests/test_flush.py`

## Loop log

- Round 1 of 5: section 2 gained its fence and its check.
- Round 2 of 5: dry
"""


class Store(unittest.TestCase):
    def setUp(self):
        base = tempfile.TemporaryDirectory(prefix="p4-phi-progress-")
        self.addCleanup(base.cleanup)
        self.root = os.path.join(base.name, "proj")
        self.home = os.path.join(self.root, ".claude", "p4")
        self.plans = os.path.join(self.home, "temportal", "plan-planner")
        os.makedirs(self.plans)

    def session(self, sid, parent="", **more):
        folder = os.path.join(self.home, "phi", "sessions", sid)
        os.makedirs(folder, exist_ok=True)
        s = {"sessionId": sid, "title": f"title of {sid}", "task": "port the flush", **more}
        if parent:
            s["spawnedFrom"] = {"sessionId": parent}
        with open(os.path.join(folder, "session.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)
        return folder

    def steps(self, sid, *statuses):
        steps = [{"addr": str(k + 1), "content": f"step {k + 1}", "status": status}
                 for k, status in enumerate(statuses)]
        current = next((x["addr"] for x in steps if x["status"] == "in_progress"), "")
        with open(os.path.join(self.home, "phi", "sessions", sid, "plan.json"), "w", encoding="utf-8") as f:
            json.dump({"root": "", "steps": steps, "current": current, "version": 1}, f)

    def plan(self, name="linear-stallman.md", text=PLAN, folder=None):
        path = os.path.join(folder or self.plans, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class Goal(unittest.TestCase):
    def test_a_goal_is_asked_set_met_failed_or_cleared_as_session_json_holds_it(self):
        self.assertIsNone(progress.goal_of({}))
        asked = progress.goal_of({"goalAsk": {"condition": "the suite passes"}})
        self.assertEqual(asked, {"state": "asked", "condition": "the suite passes"})
        not_set = progress.goal_of({"goal": {"condition": "the suite passes", "failed": "the command was dropped"}})
        self.assertEqual(not_set, {"state": "asked", "condition": "the suite passes",
                                   "reason": "the command was dropped"})
        is_set = progress.goal_of({"goal": {"condition": "the suite passes", "set": "2026-11-23 06:00"}})
        self.assertEqual(is_set, {"state": "set", "condition": "the suite passes"})
        for over in ("met", "failed", "cleared"):
            g = {"condition": "the suite passes", "set": "2026-11-23 06:00", "over": over, "reason": "exit code 0"}
            self.assertEqual(progress.goal_of({"goal": g}),
                             {"state": over, "condition": "the suite passes", "reason": "exit code 0"})

    def test_an_ask_not_yet_answered_stands_before_the_goal_it_replaces(self):
        s = {"goalAsk": {"condition": "the docs build"}, "goal": {"condition": "the suite passes", "set": "x"}}
        self.assertEqual(progress.goal_of(s), {"state": "asked", "condition": "the docs build"})

    def test_a_goal_a_person_typed_is_read_from_the_transcripts_goal_row(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "cli.jsonl")
            rows = [{"attachment": {"type": "goal_status", "condition": "the plan is approved", "met": False,
                                    "sentinel": True}},
                    {"attachment": {"type": "goal_status", "condition": "the plan is approved", "met": False,
                                    "reason": "no approval yet"}}]
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(r) + "\n" for r in rows))
            self.assertEqual(progress.goal_of({"transcript": path}),
                             {"state": "set", "condition": "the plan is approved", "reason": "no approval yet"})
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"attachment": {"type": "goal_status", "condition": "the plan is approved",
                                                   "met": True, "reason": "approved"}}) + "\n")
            self.assertEqual(progress.goal_of({"transcript": path})["state"], "met")


class Plan(Store):
    def test_the_loop_log_gives_the_round_the_last_change_and_the_dry_rounds_in_a_row(self):
        log = "## Loop log\n\n- Round 1 of 5: two fences changed.\n- Round 2 of 5: dry\n"
        self.assertEqual(progress.loop_of(log),
                         {"round": 2, "of": 5, "last": "dry", "dry": 1, "ended": False})
        self.assertEqual(progress.loop_of(log + "- Round 3 of 5: Dry.\n"),
                         {"round": 3, "of": 5, "last": "Dry.", "dry": 2, "ended": True})
        five = "## Loop log\n\n" + "".join(f"- Round {n} of 5: a check changed.\n" for n in range(1, 6))
        self.assertEqual(progress.loop_of(five)["ended"], True)
        self.assertEqual(progress.loop_of(five)["dry"], 0)
        self.assertEqual(progress.loop_of("## Loop log\n"), {"round": 0, "of": 5, "last": "", "dry": 0, "ended": False})
        self.assertIsNone(progress.loop_of("# A plan\n\n## 1. A section\n"))

    def test_a_plans_sections_say_which_land_files_and_which_hold_their_evidence(self):
        path = self.plan()
        got = progress.plan_of({"planFile": path})
        self.assertEqual(got["title"], "The exporter's move")
        self.assertEqual(got["sections"], [{"head": "Context", "lands": False, "done": False},
                                           {"head": "1. The writer", "lands": True, "done": True},
                                           {"head": "2. The flush", "lands": True, "done": False}])
        self.assertEqual(got["loop"], {"round": 2, "of": 5, "last": "dry", "dry": 1, "ended": False})

    def test_a_worker_reads_the_plan_its_brief_names_and_a_plan_that_is_gone_reads_as_none(self):
        path = self.plan().replace("\\", "/")
        task = f"Task: land section 2 of the plan `{path}`, as the fences there say."
        self.assertEqual(progress.plan_of({"task": task})["path"], path)
        self.assertIsNone(progress.plan_of({"task": "port the flush"}))
        self.assertIsNone(progress.plan_of({"planFile": os.path.join(self.plans, "moved-away.md")}))


class Tree(Store):
    def test_the_tree_holds_each_live_session_with_its_steps_and_its_sources(self):
        self.session(TOP)
        self.session(KID, TOP, goal={"condition": "the suite passes", "set": "2026-11-23 06:00"})
        self.session(GONE, TOP, archived="2026-11-23 05:00")
        self.steps(TOP, "completed", "in_progress")
        self.steps(KID, "in_progress", "pending", "pending")
        m = progress.build(self.home, TOP)
        self.assertEqual([(n["sessionId"], n["depth"]) for n in m["nodes"]], [(TOP, 0), (KID, 1)])
        top, kid = m["nodes"]
        self.assertEqual(top["current"], "2")
        self.assertEqual([x["status"] for x in top["steps"]], ["completed", "in_progress"])
        self.assertEqual(kid["goal"], {"state": "set", "condition": "the suite passes"})
        self.assertEqual(kid["steps"][0], {"addr": "1", "content": "step 1", "status": "in_progress", "agents": 0})
        self.assertFalse(kid["working"])
        self.assertIsNone(kid["plan"])
        for sid in (TOP, KID):
            for name in ("session.json", "plan.json"):
                self.assertIn(f"{self.home}/phi/sessions/{sid}/{name}".replace("\\", "/"), m["sources"])
        # the hooks' log and the turns are watched too, since `working` and `done` are read from them
        self.assertEqual(len(m["sources"]), 8)
        self.assertEqual(m["folders"], [f"{self.home}/phi/sessions".replace("\\", "/")])

    def test_the_file_is_written_once_and_again_only_when_the_tree_changed(self):
        folder = self.session(TOP)
        self.steps(TOP, "in_progress")
        first = progress.write(self.home, TOP)
        self.assertEqual(first, {"path": os.path.join(folder, "progress.json").replace("\\", "/"), "changed": True})
        self.assertEqual(progress.write(self.home, TOP)["changed"], False)
        self.steps(TOP, "completed")
        self.assertEqual(progress.write(self.home, TOP)["changed"], True)
        with open(first["path"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["nodes"][0]["steps"][0]["status"], "completed")

    def test_a_session_with_no_folder_gets_no_file_and_no_folder(self):
        self.assertEqual(progress.write(self.home, "local_never001"), {})
        self.assertFalse(os.path.exists(os.path.join(self.home, "phi", "sessions", "local_never001")))


class Kept(Store):
    def me(self):
        return types.SimpleNamespace(home=self.home, store=self.home, id=TOP, rec={}, cli="")

    def test_a_write_into_the_plans_folder_keeps_the_plan_file_and_a_sorted_plan_is_never_kept(self):
        self.session(TOP)
        path = self.plan()
        self.assertFalse(phi.keep_plan_file(self.me(), path, {"agent_id": "a1"}), "a subagent's file is its own")
        self.assertNotIn("planFile", phi.load_session(self.home, TOP))
        self.assertTrue(phi.keep_plan_file(self.me(), path, {}))
        kept = phi.load_session(self.home, TOP)["planFile"]
        self.assertEqual(os.path.normcase(os.path.realpath(kept)), os.path.normcase(os.path.realpath(path)))
        self.assertFalse(phi.keep_plan_file(self.me(), path), "the same path is kept once")
        sorted_away = self.plan("the-exporters-move.md", folder=os.path.join(self.plans, "complete"))
        self.assertFalse(phi.keep_plan_file(self.me(), sorted_away))
        self.assertFalse(phi.keep_plan_file(self.me(), os.path.join(self.root, "src", "writer.py")))
        other = self.plan("another-plan.md")
        self.assertFalse(phi.keep_plan_file(self.me(), other), "the first plan stands while its file is there")
        self.assertEqual(phi.load_session(self.home, TOP)["planFile"], kept)
        os.remove(path)
        self.assertTrue(phi.keep_plan_file(self.me(), other), "the first was sorted away, so the next is kept")

    def test_the_command_prints_the_files_path_for_the_session_it_is_asked_for(self):
        self.session(TOP, planFile=self.plan())
        self.steps(TOP, "in_progress")
        # a process of its own, as the hooks module runs it, so no global of phi.py is left changed for another test
        ran = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "progress",
                              "--p4", self.home, "--session", TOP], capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        said = json.loads(ran.stdout.strip().split("\n")[-1])
        self.assertTrue(said["path"].endswith(f"/{TOP}/progress.json"))
        with open(said["path"], encoding="utf-8") as f:
            node = json.load(f)["nodes"][0]
        self.assertEqual(node["plan"]["loop"]["round"], 2)
        self.assertEqual(node["plan"]["sections"][1], {"head": "1. The writer", "lands": True, "done": True})


if __name__ == "__main__":
    unittest.main()
