#!/usr/bin/env python3
"""The choice of a terminal worker's mode: the draft's `Runner:` line, which the session agent writes by the purpose
of the piece of work, decides it; the session's `workerMode` and phi.json's `worker_mode` still win over it; and
plans.worker_mode_for, the keyword rule, is only the fallback for a draft with no `Runner:` line, said as such.

    python -m pytest tests/p4-phi/test_worker_choice.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_puppeteer as tp  # noqa: E402  (as a module, so its test classes are not collected twice)
from test_phi import TASK, TOP, write  # noqa: E402

phi, plans, relay, coworker = tp.phi, tp.plans, tp.relay, tp.coworker

LAND = "Fix the ports table writer.\nFiles: src/writer.py"
TEAM = "Review the ports table move with an agent team.\nFiles: none"


class WorkerChoice(tp.Base):
    def settings(self, text):
        return phi.worker_settings(self.t.p4, TOP, text)

    def start(self, brief, task="", title="Fix the ports table", did="drf-0123456789"):
        """Starts a kept draft of TOP with `brief` and the task file `task`; its stdout."""
        t = self.t
        t.say(TOP, TASK)
        os.makedirs(os.path.join(t.dir(TOP), "drafts"), exist_ok=True)
        write(os.path.join(t.dir(TOP), "drafts", did + ".json"), json.dumps({
            "id": did, "title": title, "parent": TOP, "verdict": "start", "context": "fresh", "brief": brief,
            "gate": []}))
        args = ["draft", "--start", did]
        if task:
            path = os.path.join(t.tmp, "task.md")
            write(path, task)
            args += ["--task", path]
        r = t.cli(TOP, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_runner_interactive_wins_over_a_brief_the_rule_calls_print(self):
        self.assertEqual(plans.worker_mode_for(LAND)[0], "print")
        s = self.settings(LAND + "\nRunner: interactive")
        self.assertEqual((s["mode"], s["mode_from"]), ("interactive", "the draft's Runner: interactive"))
        self.assertEqual(s["profile"], "", "an interactive worker pairs with off")

    def test_runner_print_wins_over_a_brief_with_team_words(self):
        self.assertEqual(plans.worker_mode_for(TEAM)[0], "interactive")
        s = self.settings(TEAM + "\n- **Runner:** `print`")
        self.assertEqual((s["mode"], s["mode_from"]), ("print", "the draft's Runner: print"))
        self.assertEqual(s["profile"], "p4-workers")

    def test_runner_team_and_print_max_read_as_sections_reads_them(self):
        s = self.settings(LAND + "\nRunner: team")
        self.assertEqual((s["mode"], s["mode_from"]), ("interactive", "the draft's Runner: team"))
        s = self.settings(TEAM + "\nRunner: print max, sonnet at medium")
        self.assertEqual((s["mode"], s["mode_from"]), ("print", "the draft's Runner: print max"))
        self.assertEqual(s["profile"], "", "print max runs -p on the Max plan, its profile off")

    def test_no_runner_line_falls_back_to_the_rule_and_says_fallback(self):
        s = self.settings(TEAM)
        self.assertEqual(s["mode"], plans.worker_mode_for(TEAM)[0])
        self.assertTrue(s["mode_from"].startswith("fallback: no Runner: line"), s["mode_from"])
        self.assertIn("agent team", s["reason"])
        s = self.settings(LAND)
        self.assertEqual(s["mode"], "print")
        self.assertTrue(s["mode_from"].startswith("fallback"), s["mode_from"])

    def test_session_and_phi_json_settings_still_win_over_runner(self):
        t = self.t
        t.say(TOP, TASK)
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"worker_mode": "print"}))
        s = self.settings(LAND + "\nRunner: interactive")
        self.assertEqual((s["mode"], s["mode_from"]), ("print", "phi.json worker_mode"))
        self.assertEqual(t.cli(TOP, "worker_for", "--mode", "interactive").returncode, 0)
        s = self.settings(LAND + "\nRunner: print")
        self.assertEqual((s["mode"], s["mode_from"]), ("interactive", "the session's workerMode"))

    def test_draft_start_names_the_runner_of_its_task_file(self):
        out = self.start(LAND, task="Fix the writer.\nRunner: interactive\n")
        self.assertIn("mode interactive (the draft's Runner: interactive)", out)
        self.assertNotIn("fallback", out)

    def test_draft_start_with_no_runner_prints_the_facts_and_asks_for_one(self):
        out = self.start(TEAM, title="Review the ports table")
        self.assertIn("mode interactive (fallback: no Runner: line)", out)
        (hint,) = [line for line in out.splitlines() if "Billing" in line]
        for words in ("Purpose", "What you lose", "p4-workers", "claude -p", "teammates", "Runner:"):
            self.assertIn(words, hint)
        (row,) = phi.read_rows(os.path.join(self.t.p4, "phi", "worker-starts.jsonl"))
        self.assertEqual(row["mode_from"], "fallback: no Runner: line")


if __name__ == "__main__":
    unittest.main()
