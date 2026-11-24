#!/usr/bin/env python3
"""workerlog.py: what a `claude -p` worker is doing, read from its stream-json log, and the page that draws it.

    python -m pytest tests/p4-phi/test_workerlog.py

Three fixture logs are built here: a running worker (a tool_use with no result and an api_retry `overloaded`), a
finished one (a success result with cost and turns) and one that the credit refused (a result with `is_error` true).
"""

import json
import os
import sys
import tempfile
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import relay  # noqa: E402
import workerlog  # noqa: E402

TOP = "local_top00001"


def assistant(msg_id, *blocks, **more):
    return {"type": "assistant", "message": {"id": msg_id, "model": "claude-sonnet-5-5", "content": list(blocks)},
            "session_id": "s-1", **more}


def tool_use(use_id, name, **inp):
    return {"type": "tool_use", "id": use_id, "name": name, "input": inp}


def text(said):
    return {"type": "text", "text": said}


def result_of(use_id):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": use_id, "content": "ok"}]}}


RUNNING = [
    {"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-sonnet-5-5"},
    {"type": "assistant", "local_command_run": {"command": "goal"}, "session_id": "s-1",
     "message": {"id": "m0", "content": [text("Goal set: land section 2")]}},
    assistant("m1", text("Reading the plan."), tool_use("t1", "Read", file_path="plan.md")),
    result_of("t1"),
    assistant("m2", text("Running the checks now."), tool_use("t2", "Bash", command="python -m pytest tests -q")),
    {"type": "system", "subtype": "api_retry", "error": "overloaded", "attempt": 1},
]
FINISHED = [
    {"type": "system", "subtype": "init", "session_id": "s-2", "model": "claude-sonnet-5-5"},
    assistant("m1", text("Landed."), tool_use("t1", "Bash", command="git status")),
    result_of("t1"),
    assistant("m2", text("Done: every fence is landed.")),
    {"type": "result", "subtype": "success", "is_error": False, "result": "Done", "total_cost_usd": 0.1039,
     "num_turns": 6, "duration_ms": 91000},
]
CREDIT = [
    {"type": "system", "subtype": "init", "session_id": "s-3"},
    {"type": "result", "subtype": "success", "is_error": True, "result": "Credit balance is too low",
     "total_cost_usd": 0, "num_turns": 1},
]


class Logs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="p4-phi-workerlog-")
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def log(self, name, rows, raw_before="", raw_after=""):
        path = os.path.join(self.dir, f"log-{name}.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw_before + "".join(json.dumps(r) + "\n" for r in rows) + raw_after)
        return path

    def test_a_running_worker_has_its_open_tool_its_turns_its_latest_text_its_goal_and_its_retry_error(self):
        got = workerlog.state(self.log("tw-run", RUNNING))
        self.assertEqual((got["name"], got["session"], got["model"], got["turns"], got["end"]),
                         ("tw-run", "s-1", "claude-sonnet-5-5", 3, "running"))
        self.assertEqual(got["tool"], {"name": "Bash", "input": "python -m pytest tests -q"})
        self.assertEqual(got["text"], "Running the checks now.")
        self.assertEqual((got["goal"], got["error"]), ("set", "overloaded"))
        self.assertEqual((got["cost"], got["num_turns"]), (None, None))
        self.assertGreater(got["updated"], 0)

    def test_a_finished_worker_is_done_with_the_cost_and_turns_of_its_result_row_and_no_open_tool(self):
        got = workerlog.state(self.log("tw-fin", FINISHED))
        self.assertEqual((got["end"], got["cost"], got["num_turns"], got["error"], got["tool"]),
                         ("done", 0.1039, 6, "", None))
        self.assertEqual(got["text"], "Done: every fence is landed.")

    def test_a_credit_failed_worker_is_failed_and_its_error_is_the_results_text(self):
        got = workerlog.state(self.log("tw-bill", CREDIT))
        self.assertEqual((got["end"], got["error"]), ("failed", "Credit balance is too low"))

    def test_a_bom_a_stderr_line_and_a_cut_last_line_are_read_around(self):
        path = self.log("tw-odd", FINISHED[:4], raw_before="﻿", raw_after='{"type": "result", "is_err')
        # a stderr line between two rows
        with open(path, "a", encoding="utf-8") as f:
            f.write("\nWARNING: a line of stderr\n")
        got = workerlog.state(path)
        self.assertEqual((got["end"], got["turns"], got["text"]), ("running", 2, "Done: every fence is landed."))

    def test_the_goal_reads_achieved_and_cleared_from_a_row_that_opens_so(self):
        set_row = RUNNING[1]
        done = {"type": "system", "subtype": "info", "text": "Goal achieved: the condition holds"}
        self.assertEqual(workerlog.state(self.log("tw-g1", [set_row, done]))["goal"], "achieved")
        cleared = assistant("m9", text("Goal cleared."))
        self.assertEqual(workerlog.state(self.log("tw-g2", [set_row, cleared]))["goal"], "cleared")
        self.assertEqual(workerlog.state(self.log("tw-g3", [RUNNING[2]]))["goal"], "")

    def test_an_api_error_assistant_row_is_the_error_and_a_log_that_cannot_be_read_says_so(self):
        err = assistant("m1", text("Credit balance is too low"), isApiErrorMessage=True)
        got = workerlog.state(self.log("tw-api", [err]))
        self.assertEqual((got["error"], got["text"]), ("Credit balance is too low", ""))
        gone = workerlog.state(os.path.join(self.dir, "log-tw-none.jsonl"))
        self.assertIn("cannot be read", gone["error"])
        self.assertEqual(gone["end"], "running")

    def test_only_the_last_two_mebibytes_are_read_and_a_long_text_is_cut(self):
        rows = [assistant(f"m{k}", text("x" * 100)) for k in range(30_000)] + [assistant("mz", text("y" * 2_000))]
        got = workerlog.state(self.log("tw-big", rows))
        self.assertLess(got["turns"], 30_001)
        self.assertEqual(len(got["text"]), workerlog.TEXT)
        self.assertTrue(got["text"].endswith("..."))


class Page(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="p4-phi-workerlog-")
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "proj", ".claude", "p4")
        os.makedirs(os.path.join(self.home, "phi"))

    def worker(self, name, rows, parent=TOP, brief="# Land section 2\n\nTask: land it.\n"):
        store = relay.claim(self.home, self.home, name, "worker", parent, ["2"])
        folder = os.path.join(store, "phi")
        if rows is not None:
            with open(os.path.join(folder, f"log-{name}.jsonl"), "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(json.dumps(r) + "\n" for r in rows))
        with open(os.path.join(folder, f"brief-{name}.md"), "w", encoding="utf-8") as f:
            f.write(brief)
        return folder

    def test_workers_lists_the_nodes_of_the_session_that_hold_a_log_with_their_task_and_paths(self):
        folder = self.worker("tw-a", RUNNING)
        self.worker("tw-b", FINISHED, parent="local_other0001")        # another session's
        self.worker("tw-c", None)                                      # a worker with no log, an interactive one
        got = workerlog.workers(self.home, TOP)
        self.assertEqual([w["name"] for w in got], ["tw-a"])
        w = got[0]
        self.assertEqual(w["task"], "Land section 2")
        self.assertEqual(w["log"], os.path.join(folder, "log-tw-a.jsonl").replace("\\", "/"))
        self.assertEqual(w["report"], os.path.join(folder, "report-tw-a.md").replace("\\", "/"))
        self.assertEqual(w["end"], "running")
        self.assertEqual(workerlog.workers(self.home, ""), [])

    def test_render_puts_the_credit_error_first_in_bold_and_links_the_log_and_the_report(self):
        self.worker("tw-bill", CREDIT)
        self.worker("tw-run", RUNNING)
        self.worker("tw-fin", FINISHED)
        page = workerlog.render(workerlog.workers(self.home, TOP))
        block = page.split("\n\n")[1]
        self.assertTrue(block.startswith("**Credit balance is too low**"), block)
        self.assertIn("`tw-bill`: Land section 2", block)
        self.assertIn("failed", block)
        self.assertIn("[log](", block)
        self.assertIn("[report](", block)
        self.assertIn("running, turn 3, in `Bash` python -m pytest tests -q", page)
        self.assertIn("cost $0.1039, 6 turns", page)
        self.assertIn("goal set", page)
        self.assertIn("> Running the checks now.", page)
        self.assertEqual(workerlog.render([]), "")


if __name__ == "__main__":
    unittest.main()
