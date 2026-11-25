#!/usr/bin/env python3
"""plans.py: step addresses, the tree of task lists, the check at each step boundary and the revisions told to the
sessions they bear on, on a three-session tree run through phi.py's own hooks.

    python -m pytest tests/p4-phi/test_plans.py
"""

import json
import os
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
import hook  # noqa: E402
import phi  # noqa: E402
import plans  # noqa: E402
import relay  # noqa: E402
from test_phi import CLI, GRAND, KID, KID2, TOP, Tree, context, handed, runs_of, write  # noqa: E402
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402

A, B = KID, KID2


def items(*steps, at=0):
    return {"items": [{"content": c, "status": "completed" if k < at else "in_progress" if k == at else "pending"}
                      for k, c in enumerate(steps)], "scope": "first_task"}


def stamp(at=None):
    """A time as a transcript row carries it, now when none is given."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() if at is None else at)) + ".000Z"


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
    """hooks.md, "Stop input": `background_tasks` lists the work in flight, so p4-phi records no launch of its own and
    keeps that list on session.json for the checks that run between turns."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.say(TOP, "Build it")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_background_launch_writes_no_record_of_p4_phis_own(self):
        hook = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")
        plans.record(self.t.p4, relay._session(self.t.p4, TOP), items("Run the smoke check", "Write the report"))
        for k, (tool, inp, response) in enumerate((
                ("Bash", {"command": "sh smoke.sh", "run_in_background": True}, {"backgroundTaskId": "bsmoke001"}),
                ("Monitor", {"command": "tail -f smoke.log", "timeout_ms": 60000}, "Monitor started (task bwatch001)."),
                ("TaskStop", {"task_id": "bwatch001"}, "stopped"))):
            body = {"session_id": CLI[TOP], "cwd": self.t.proj, "hook_event_name": "PostToolUse", "tool_name": tool,
                    "tool_input": inp, "tool_response": response, "tool_use_id": f"toolu_bg{k}"}
            r = inproc.run(["sh", hook, "lookup-record"], input=json.dumps(body), capture_output=True, text=True,
                           timeout=60, env=self.t.env(TOP, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
        p = plans.load(self.t.p4, TOP)
        self.assertFalse(p.get("loose") or any(st.get("tasks") for st in p.get("steps") or []))

    def test_the_list_is_kept_with_turns_off(self):
        """The Stop hook keeps the list before any of its early returns, so phi.json's `turns` false keeps it too."""
        from test_phi import STOP, transcript
        with open(os.path.join(self.t.p4, "phi", "phi.json"), "w", encoding="utf-8") as f:
            json.dump({"turns": False}, f)
        path = transcript(os.path.join(self.t.tmp, TOP + "off.jsonl"), "Build it", (), "Running.", "off")
        r = self.t.hook(STOP, TOP, {"hook_event_name": "Stop", "transcript_path": path,
                                    "last_assistant_message": "Running.",
                                    "background_tasks": [{"id": "boff00001", "type": "shell", "status": "running",
                                                          "command": "sh smoke.sh"}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([t["id"] for t in plans.in_flight(relay._session(self.t.p4, TOP))], ["boff00001"])

    def test_the_stop_inputs_list_is_kept_until_a_stop_lists_again(self):
        s = {}
        plans.keep_in_flight(s, {"background_tasks": [
            {"id": "bsmoke001", "type": "shell", "status": "running", "description": "smoke", "command": "sh smoke.sh",
             "extra": 1},
            {"id": "a8ed9430d359ce61d", "type": "subagent", "status": "running", "description": "search",
             "agent_type": "Explore"}]})
        self.assertEqual([t["id"] for t in plans.in_flight(s)], ["bsmoke001", "a8ed9430d359ce61d"])
        self.assertNotIn("extra", s["backgroundTasks"][0])
        self.assertTrue(s["backgroundAt"])
        plans.keep_in_flight(s, {})
        self.assertEqual(len(plans.in_flight(s)), 2, "no list: the last one read stands")
        plans.keep_in_flight(s, {"background_tasks": []})
        self.assertEqual(plans.in_flight(s), [], "nothing in flight")


class TreeOfPlans(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"upkeep": False}}))   # set by hand: off
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

    def recall(self, name, body, host=A):
        """One entry of recall-hook.sh, run for a session with the hook input `body`."""
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), name],
                       input=json.dumps({"session_id": CLI[host], "cwd": self.t.proj, **body}),
                       capture_output=True, text=True, timeout=60, env=self.t.env(host, P4_RECALL_SYNC="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def subagent(self, agent_id, started=None, host=A):
        """A subagent as Claude Code keeps it, started through the SubagentStart entry: its own transcript,
        `<session>/subagents/agent-<agent_id>.jsonl` beside the session's, whose first row carries its start ->
        that transcript's path."""
        main = os.path.join(self.t.tmp, "projects", CLI[host] + ".jsonl")
        path = os.path.join(os.path.splitext(main)[0], "subagents", f"agent-{agent_id}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "isSidechain": True, "agentId": agent_id, "sessionId": CLI[host],
                                "timestamp": stamp(started), "message": {"role": "user", "content": "read it"}}) + "\n")
        self.recall("subagent-start", {"hook_event_name": "SubagentStart", "agent_id": agent_id,
                                       "agent_type": "general-purpose", "transcript_path": main}, host)
        return path

    def sub_call(self, agent_id, k, host=A):
        """One tool call of a subagent: checked by `lookup-check` before it runs, the context the check added kept
        as a row of the subagent's transcript, as Claude Code keeps it, and the call recorded after -> what the
        check told the subagent."""
        main = os.path.join(self.t.tmp, "projects", CLI[host] + ".jsonl")
        body = {"transcript_path": main, "agent_id": agent_id, "agent_type": "general-purpose", "tool_name": "Read",
                "tool_input": {"file_path": "README.md"}, "tool_use_id": f"toolu_{agent_id}_{k}"}
        said = context(self.recall("lookup-check", {**body, "hook_event_name": "PreToolUse"}, host))
        if said:
            with open(os.path.join(os.path.splitext(main)[0], "subagents", f"agent-{agent_id}.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps({"type": "attachment", "isSidechain": True, "agentId": agent_id,
                                    "timestamp": stamp(), "attachment": {
                                        "type": "hook_additional_context", "hookEvent": "PreToolUse",
                                        "hookName": "PreToolUse:Read", "toolUseID": body["tool_use_id"],
                                        "content": [said]}}) + "\n")
        self.recall("lookup-record", {**body, "hook_event_name": "PostToolUse", "tool_response": "ok"}, host)
        return said

    def test_a_child_gets_its_parents_step_as_its_parent_step(self):
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual([x["addr"] for x in plans.load(self.t.p4, A)["steps"]], ["2.1", "2.2", "2.3"])
        anchor = json.load(open(relay.anchor_path(self.t.p4, TOP), encoding="utf-8"))
        self.assertEqual(anchor["nodes"][A]["plan"]["current"], "2.1", "the parent's anchor is the tree of task lists")
        self.assertEqual(anchor["parent"]["plan"]["current"], "2")

    def test_siblings_started_in_one_step_get_the_steps_their_briefs_name(self):
        """Two children started while the parent is on step 2, one for its docs step: each its own parent step."""
        home = self.t.p4
        s = {"sessionId": "x", "spawnedFrom": {"sessionId": TOP}, "task": "Write the docs, for step 3 of the list"}
        self.assertEqual(plans.root_of(home, s), "3")
        s["task"] = "Move the store layout into phi, the code part"
        self.assertEqual(plans.root_of(home, s), "2")
        s["task"] = "something else entirely"
        self.assertEqual(plans.root_of(home, s), "2", "no step named: the step in progress")

    def test_a_brief_that_names_no_step_is_bound_to_the_step_in_progress_when_it_started(self):
        """A brief was bound to the open step of the parent's list whose words it shared most. So a worker whose
        brief spoke of a native goal was bound to the parent's step "Give this session a native goal", which was
        another piece of work, and was told of that step's every change. A brief that names no step is bound to the
        step in progress when its session started, whatever words it shares with another step, and keeps that step
        when the parent moves on before the worker's first task list."""
        t = self.t
        s = {"sessionId": "x", "spawnedFrom": {"sessionId": TOP}, "task": "Write the layout docs for the store"}
        self.assertEqual(plans.root_of(t.p4, s), "2", "step 3 holds its words, and step 2 is in progress")
        ctx = context(t.say(B, "Write the layout docs for the store"))
        self.assertIn("this session is for step 2 of its parent's task list, \"Move the store layout into phi\"", ctx)
        self.assertEqual(t.session(B)["rootStep"], "2", "kept from its start")
        self.plan(TOP, {"advance": True})
        self.assertEqual(plans.load(t.p4, TOP)["current"], "3")
        self.plan(B, items("Draft the layout table docs", "Publish the layout table docs"))
        self.assertEqual([x["addr"] for x in plans.load(t.p4, B)["steps"]], ["2.1", "2.2"])
        self.assertEqual(t.session(B)["rootStep"], "2")

    def test_a_subagent_is_a_task_of_the_step_that_launched_it(self):
        t, home = self.t, self.t.p4
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        sa = relay._session(home, A)
        text = plans.agent_launch(home, sa, {"prompt": "read the layout code", "description": "probe"})
        self.assertIn("subagent of", text)
        self.assertIn("step 2.1", text)
        self.assertFalse(any(st.get("tasks") for st in plans.load(home, A)["steps"]), "the Agent call makes no task")
        self.assertTrue(plans.agent_bind(home, sa, "agentx001", "Explore"), "its start binds its id")
        self.assertFalse(plans.agent_bind(home, sa, "agentx001", "Explore"), "a start of the same id makes no second")
        step = plans.load(home, A)["steps"][0]
        self.assertEqual([(x["id"], x["tool"]) for x in step["tasks"]], [("agentx001", "Agent")])
        relay.make_anchor(home, TOP, "2026-11-12 18:00")
        node = json.load(open(relay.anchor_path(home, TOP), encoding="utf-8"))["nodes"][A]
        self.assertEqual(node["plan"]["steps"][0]["tasks"][0]["id"], "agentx001", "the delta carries it")
        own = os.path.join(t.tmp, "agent-agentx001.jsonl")         # its own transcript: it started two minutes ago
        with open(own, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": stamp(time.time() - 120)}) + "\n")
        self.assertEqual(plans.agent_warn(home, sa, "agentx001", own), "", "nothing changed since its launch")
        t.cli(B, "note", "replaces: the old docs layout in docs/layout.md", "--source", "test")
        relay.make_anchor(home, TOP, "2026-11-12 18:01")
        self.assertEqual(plans.agent_warn(home, sa, "agentx001"), "", "what a sibling changed waits for its transcript")
        warned = plans.agent_warn(home, sa, "agentx001", own)
        self.assertIn("the old docs layout", warned)
        self.assertEqual(plans.agent_warn(home, sa, "agentx001", own), "", "told once")
        self.plan(A, items("Rewrite p4conf.LAYOUT and OLDER", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual(plans.load(home, A)["steps"][0]["tasks"][0]["id"], "agentx001", "reworded in place")
        self.assertIn("now reads \"Rewrite p4conf.LAYOUT and OLDER\"", plans.agent_warn(home, sa, "agentx001"))
        self.assertIn("down: \"the layout child\" launched subagent agentx001 for its step 2.1, agent type `Explore`.",
                      " ".join(w["text"] for w in relay._session(home, TOP).get("relayPending") or []),
                      "the parent is told the subagent's id and the agent type its hook input carries")

    def test_a_workers_subagent_is_handed_no_run_of_the_orchestrators_prompt(self):
        """ezexe/p4#204: the Agent launch of a worker, through the `agent` PreToolUse hook, hands its subagent the
        worker's step and the slice of the orchestrator's anchor for its paths, with no run of eight words of the
        orchestrator's first prompt."""
        with tempfile.TemporaryDirectory() as d:
            t = Tree(d)
            p = t.proj.replace("\\", "/")
            sent = (f"Make the narwhal exporter write every row of its ports table through {p}/src/export/flush.py "
                    f"and keep the old table format readable for a month")
            t.record(TOP, title="the exporter orchestrator")
            t.record(A, TOP, title="the flush worker")
            t.say(TOP, sent)
            t.say(A, handed(f"Port the flush writer in {p}/src/export/flush.py to the new store, then report."))
            r = t.hook("plan", A, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                   "tool_input": items("Port the flush writer", "Run the flush tests"),
                                   "tool_response": "Plan updated."})
            self.assertEqual(r.returncode, 0, r.stderr)
            hook = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")
            own = f"Read {p}/src/export/flush.py and list its writes"
            r = inproc.run(["sh", hook, "agent"], input=json.dumps({
                "session_id": CLI[A], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": "Agent",
                "tool_use_id": "toolu_204", "tool_input": {"prompt": own, "description": "flush reads"}}),
                capture_output=True, text=True, timeout=60, env=t.env(A, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("updatedInput", r.stdout, "the subagent's prompt stays as written, ezexe/p4#243 row D2")
            recall = __import__("hook")                      # the file hooks/register.ts writes at `agent.spawn`
            write(os.path.join(recall.pending_dir({"session_id": CLI[A], "cwd": t.proj}), recall.BOUND + "a204"),
                  "toolu_204\n")
            r = inproc.run(["sh", hook, "subagent-start"], input=json.dumps({
                "session_id": CLI[A], "cwd": t.proj, "hook_event_name": "SubagentStart", "agent_id": "a204",
                "agent_type": "general-purpose"}),
                capture_output=True, text=True, timeout=60, env=t.env(A, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]   # what p4-phi adds at its start
            self.assertIn("subagent of \"the flush worker\"", text)
            self.assertIn("what the parent, \"the exporter orchestrator\"", text, "the slice ran, naming it by title")
            self.assertEqual(runs_of(sent, text), [], text)

    def test_a_subagents_step_revised_and_its_stop(self):
        home = self.t.p4
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        sa = relay._session(home, A)
        plans.agent_bind(home, sa, "agenty002", "general-purpose")
        p = plans.load(home, A)
        p["steps"][0]["content"] = "Rewrite p4conf.LAYOUT for the temportal folder"
        relay._write_json(plans._path(home, A), p)
        self.assertIn("now reads \"Rewrite p4conf.LAYOUT for the temportal folder\"", plans.agent_warn(home, sa, "agenty002"))
        self.assertTrue(plans.agent_stop(home, sa, "agenty002"))
        task = plans.load(home, A)["steps"][0]["tasks"][0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(plans.agent_warn(home, sa, "agenty002"), "", "a stopped subagent is told nothing")
        self.assertFalse(plans.agent_stop(home, sa, "agentz003"), "a stop binds nothing: an id no start named has no task")
        self.assertIsNone(plans._agent(plans.load(home, A), "agentz003"))

    def test_a_subagent_is_bound_by_the_id_its_start_carries(self):
        """Candidate 12: hooks.md gives a SubagentStart the subagent's `agent_id` beside the launching session's
        `session_id`, so the task is made there, under the step in progress then. No launch waits for a subagent to
        take it, no tool call and no stop of a subagent binds one, and the starts of two launches may come in either
        order."""
        t, home = self.t, self.t.p4
        hook = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")

        def run(name, body):
            r = inproc.run(["sh", hook, name], input=json.dumps({"session_id": CLI[A], "cwd": t.proj, **body}),
                           capture_output=True, text=True, timeout=60, env=t.env(A, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            return r

        def tasks():
            return [[x["id"] for x in st.get("tasks") or []] for st in plans.load(home, A)["steps"]]

        def start(agent_id, **more):
            return run("subagent-start", {"hook_event_name": "SubagentStart", "agent_id": agent_id,
                                          "agent_type": "Explore", **more})

        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        launch = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                  "tool_input": {"prompt": "read the layout code", "description": "probe", "subagent_type": "Explore"}}
        run("agent", {**launch, "tool_use_id": "toolu_b1"})
        run("agent", {**launch, "tool_use_id": "toolu_b2"})
        self.assertEqual(tasks(), [[], [], []], "and makes no task")
        stray = {"agent_id": "agentq000", "agent_type": "Explore", "tool_name": "Read",
                 "tool_input": {"file_path": "README.md"}, "tool_use_id": "toolu_q1"}
        run("lookup-check", {**stray, "hook_event_name": "PreToolUse"})
        run("lookup-record", {**stray, "hook_event_name": "PostToolUse", "tool_response": "ok"})
        run("subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": "agentq000", "agent_type": "Explore",
                              "last_assistant_message": "done"})
        self.assertEqual(tasks(), [[], [], []], "a tool call and a stop of a subagent bind nothing")
        start("agentb002")
        marker = os.path.join(home, "phi", ".agents", "agentb002")
        self.assertTrue(os.path.exists(marker), "its marker opens recall-hook.sh's gate from its first call")
        self.plan(A, {"advance": True})
        start("agentb001")
        start("agentb001")
        self.assertEqual(tasks(), [["agentb002"], ["agentb001"], []],
                         "each under the step in progress at its own start, once, whichever call came first")
        task = plans._agent(plans.load(home, A), "agentb001")
        self.assertEqual((task["status"], task["stepText"]), ("open", "Move recall/ into phi/"))
        self.assertEqual(task["anchorSeen"] + 1, relay.anchor_version(home, TOP),
                         "the version the parent's anchor had before the task itself changed it")
        run("subagent-start", {"hook_event_name": "SubagentStart", "agent_id": "agentb003"})
        self.assertIsNone(plans._agent(plans.load(home, A), "agentb003"), "no agent type: no subagent of the Agent tool")
        run("subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": "agentb002", "agent_type": "Explore",
                              "last_assistant_message": "done"})
        self.assertEqual(plans._agent(plans.load(home, A), "agentb002")["status"], "completed")
        self.assertFalse(os.path.exists(marker), "its stop closes the marker")
        self.assertNotIn("agent-post", phi.ROUTED, "no route binds a subagent at its tool call")
        self.assertEqual(phi.ROUTED["agent-start"][0], "SubagentStart")

    def test_a_subagents_task_holds_no_copy_of_what_claude_code_keeps(self):
        """Candidate 12: the description, the start, the result and the files a subagent wrote are in the Agent
        call's input, the Stop input's `background_tasks` and the subagent's own transcript, so its task holds the
        step it serves and the anchor's version at its launch, and each reader takes the rest from where Claude Code
        keeps it."""
        t, home = self.t, self.t.p4
        hook = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")

        def run(name, body):
            r = inproc.run(["sh", hook, name], input=json.dumps({"session_id": CLI[A], "cwd": t.proj, **body}),
                           capture_output=True, text=True, timeout=60, env=t.env(A, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)

        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        run("agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_copy",
                      "tool_input": {"prompt": "list every reader of the quagga table",
                                     "description": "Quagga table readers", "subagent_type": "Explore"}})
        sub = {"agent_id": "agentc005", "agent_type": "Explore"}
        run("subagent-start", {**sub, "hook_event_name": "SubagentStart"})
        node = json.load(open(relay.anchor_path(home, TOP), encoding="utf-8"))["nodes"][A]
        self.assertEqual(node["plan"]["steps"][0]["tasks"],
                         [{"id": "agentc005", "tool": "Agent", "status": "open", "heads": []}],
                         "the anchor carries the running subagent by its id, under its step")
        path = os.path.join(t.tmp, "agent-agentc005.jsonl")
        from test_phi import transcript
        transcript(path, "list every reader of the quagga table",
                   [("Write", {"file_path": "docs/quagga.md", "content": "x"}, "ok")], "Seven readers, all listed.")
        run("subagent-stop", {**sub, "hook_event_name": "SubagentStop", "agent_transcript_path": path,
                              "last_assistant_message": "Seven readers, all listed."})
        task = plans.load(home, A)["steps"][0]["tasks"][0]
        self.assertEqual(set(task), {"id", "tool", "agent", "status", "anchorSeen", "stepText", "wrote"}, task)
        self.assertEqual((task["id"], task["status"], task["stepText"], task["wrote"]),
                         ("agentc005", "completed", "Rewrite p4conf.LAYOUT", ["docs/quagga.md"]),
                         "the files are read from the transcript the SubagentStop input names")
        kept = json.dumps(plans.load(home, A))
        for copied in ("Quagga table readers", "list every reader", "Seven readers"):
            self.assertNotIn(copied, kept, "its description, prompt and result stay with Claude Code")
        told = " ".join(w["text"] for w in relay._session(home, TOP).get("relayPending") or [])
        self.assertIn("launched subagent agentc005 for its step 2.1, agent type `Explore`.", told)
        self.assertNotIn("Quagga", told)
        # a turn's words are held against a running subagent's description as the Stop input lists it
        s = {}
        plans.keep_in_flight(s, {"background_tasks": [
            {"id": "agentc006", "type": "subagent", "status": "running", "description": "Quagga table readers",
             "agent_type": "Explore"},
            {"id": "bshell001", "type": "shell", "status": "running", "description": "Quagga table dump",
             "command": "sh dump.sh"}]})
        self.assertEqual(plans.flying(s), ["Quagga table readers"])
        steps = plans.open_steps(home, A)
        said = "The quagga table gained two readers in the exporter."
        self.assertEqual(plans.matches(said, steps, [], ""), [], "no step's own words bear on it")
        self.assertEqual([st["addr"] for st, _ in plans.matches(said, steps, [], "", flying=plans.flying(s))],
                         ["2.1"], "it counts for the step in progress, which the running subagent serves")

    def test_a_siblings_note_is_told_to_a_subagent_once_however_often_that_sibling_changes(self):
        """A subagent's tool calls, run through the `lookup-check` and `lookup-record` hooks, tell it a sibling's note
        once, though that sibling's entry in the parent's anchor changes twice more after it, and tell it that
        sibling's newer note in turn. What it has heard is read from its own transcript: its task keeps no list of
        the notes told."""
        t = self.t
        n = iter(range(100))

        def call():
            return self.sub_call("agentn004", next(n))

        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.recall("agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_launch",
                              "tool_input": {"prompt": "read the layout code", "description": "probe"}})
        own = self.subagent("agentn004", started=time.time() - 120)
        self.assertEqual([call(), call()], ["", ""], "its start bound it, and nothing changed since its launch")
        t.cli(B, "note", "replaces: the old docs layout in docs/layout.md", "--source", "test")
        steps = ("Write the layout docs", "Check the docs build", "Commit the docs")
        told = []
        for at in range(3):                       # each update of the docs child's task list changes its entry
            self.plan(B, items(*steps, at=at))
            told.append(call())
        self.assertEqual(["the old docs layout" in x for x in told], [True, False, False], told)
        t.cli(B, "note", "deprecates: the docs build script in docs/build.sh", "--source", "test")
        self.plan(B, items(*steps, "Push the docs", at=3))
        newer = call()
        self.assertIn("the docs build script", newer, "a newer note of that sibling is told")
        self.assertNotIn("the old docs layout", newer)
        with open(own, encoding="utf-8") as f:              # the transcript alone says what it heard: without those
            first = f.readline()                            # rows the same change tells the first note again
        with open(own, "w", encoding="utf-8") as f:
            f.write(first)
        self.plan(B, items(*steps, "Push the docs", "Tag the docs", at=3))
        self.assertIn("the old docs layout", call())

    def test_a_subagent_is_not_told_a_note_written_before_its_launch(self):
        """ezexe/p4#195: a sibling of the launching session wrote a note, and a subagent launched after it is not
        told that note when the sibling's entry in the parent's anchor next changes, while a subagent that was
        running when the note was written is. The start is the first row of the subagent's own transcript, and the
        task keeps no list of notes."""
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        before = self.subagent("agentd195a", started=time.time() - 120)
        t.cli(B, "note", "replaces: the old docs layout in docs/layout.md", "--source", "test")
        self.plan(B, items("Write the layout docs", "Check the docs build"))    # the anchor holds the note
        self.recall("agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_195",
                              "tool_input": {"prompt": "read the layout code", "description": "probe"}})
        after = self.subagent("agentd195b")
        self.assertTrue(os.path.isfile(before) and os.path.isfile(after))
        self.plan(B, items("Write the layout docs", "Check the docs build", at=1))   # its entry changes, through its plan hook
        self.assertEqual(self.sub_call("agentd195b", 0), "", "launched after the note: not told it")
        self.assertIn("the old docs layout", self.sub_call("agentd195a", 0), "running when it was written: told it")
        for agent_id in ("agentd195a", "agentd195b"):
            task = plans._agent(plans.load(t.p4, A), agent_id)
            self.assertEqual(set(task), {"id", "tool", "agent", "status", "anchorSeen", "stepText"}, "no field added")

    def test_a_subagent_is_told_no_file_a_sibling_changed(self):
        """A sibling of the launching session works in the one checkout, on the paths of its own `Files:` line, so
        a file it changed is not under the subagent's hands: the anchor holds no files, and the subagent's tool calls, through `lookup-check`, give
        no files line however often the sibling's entry changes. A sibling's note still reaches it."""
        t = self.t
        docs = f"{t.proj}/docs/layout.md".replace("\\", "/")
        t.say(B, "Write the layout docs")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.subagent("agente196", started=time.time() - 120)
        n = iter(range(100))

        def call():
            return self.sub_call("agente196", next(n))

        self.assertEqual(call(), "")
        t.stop(B, "Write the layout docs", calls=[("Write", {"file_path": docs, "content": "x"}, "ok")],
               report="Wrote the layout page.")
        steps = ("Write the layout docs", "Check the docs build", "Commit the docs")
        told = [call()]
        for at in range(2):                       # its entry changes twice more
            self.plan(B, items(*steps, at=at))
            told.append(call())
        self.assertEqual([x for x in told if "changed" in x or "layout.md" in x], [], told)
        anchor = relay._read_json(relay.anchor_path(t.p4, TOP))
        self.assertNotIn("files", anchor["nodes"][B])
        self.assertNotIn("heads", anchor["nodes"][B])
        t.cli(B, "note", "replaces: the old docs layout in docs/layout.md", "--source", "test")
        self.plan(B, items(*steps, at=2))
        self.assertIn("\"the docs child\": replaces: the old docs layout", call(), "its note is still told")
        task = plans._agent(plans.load(t.p4, A), "agente196")
        self.assertEqual(set(task), {"id", "tool", "agent", "status", "anchorSeen", "stepText"}, "no field added")

    def test_steps_naming_no_file_stay_and_drawn_trees_match_nothing(self):
        """Neither a session link nor a drawn tree's addresses match a step."""
        steps = [{"addr": "1", "content": "Waits and relays stay in place"},
                 {"addr": "2", "content": "Run every suite, commit, fast-forward"}]
        linked = ("Started:\n- [Record and check phi's own lines\u2026](claude://claude.ai/epitaxy/local_ab12)\n"
                  "- claude://claude.ai/epitaxy/local_cd34")             # a session link names no step
        own = [{"addr": "3", "content": "Record and check phi's own lines"}]
        self.assertEqual(plans.matches(linked, own, [], ""), [])
        self.assertNotIn("Record", plans.own_removed(linked))
        self.assertEqual(len(plans.matches("I will record and check phi's own lines now.", own, [], "")), 1)
        report = ("Here is the tree:\n\u251c\u2500\u2500 x/ \u251c\u2500\u2500 child for step 1 plan: 1.1, 1.2\n"
                  "```\nstep 2 plan: 2.1 run every suite\n```\nNothing else.")
        self.assertEqual(plans.matches(report, steps, [], ""), [])

    def test_a_child_waiting_on_a_question_the_chain_can_settle_is_flagged_up(self):
        """Act-don't-wait: the parent hears of a child's open question that is not ezexe's to answer."""
        self.assertIn("python3", plans.waiting_on("Done. Should the runner use the py launcher or python3?"))
        self.assertEqual(plans.waiting_on("Done. Shall I push it to origin?"), "", "authority: ezexe's")
        self.assertEqual(plans.waiting_on("Done, nothing open."), "")
        s = relay._session(self.t.p4, A)
        plans.turn_relay(self.t.p4, s, {"id": "r1", "report": "Moved it. Should phi/ keep the old folder name?"}, [])
        pend = relay._session(self.t.p4, TOP).get("relayPending") or []
        self.assertTrue(any("ended its turn on a question" in w["text"] and A in w["text"] for w in pend))

    def test_a_report_asking_ezexe_what_the_context_decides_is_relayed_as_a_status_and_a_plan_approval_is_not(self):
        s = relay._session(self.t.p4, A)
        plans.turn_relay(self.t.p4, s, {"id": "r1", "report": "Moved it. Tell me now if ezexe wants X instead."}, [])
        pend = relay._session(self.t.p4, TOP).get("relayPending") or []
        self.assertTrue(any("relay this as a status, not as a question card" in w["text"] for w in pend), pend)
        self.assertFalse(any("ended its turn on a question" in w["text"] for w in pend))
        # a plan's approval is ezexe's: no status line, and not a question the parent answers itself, so it goes up as one
        self.assertEqual(relay.asks_ezexe_in("Moved it. Approve the plan?"), [])
        self.assertEqual(plans.waiting_on("Moved it. Approve the plan?"), "")
        plans.turn_relay(self.t.p4, s, {"id": "r2", "report": "Moved it. Approve the plan?"}, [])
        pend = relay._session(self.t.p4, TOP).get("relayPending") or []
        self.assertFalse(any("Approve the plan" in w["text"] for w in pend), "no status line, no self-answer nag")
        # each of ezexe's four matters is left in the report as the question it asks, beside a line that is flagged
        for q in ("Approve the plan?", "Does the plan's intent change to Y?", "Is a new plan wanted for Z?",
                  "May I spend past the pools?", "Can I delete the remote branch? It cannot be undone."):
            self.assertEqual(relay.asks_ezexe_in("Tell me now if ezexe wants X instead.\n" + q),
                             ["Tell me now if ezexe wants X instead."], q)

    def test_an_up_line_is_said_once(self):
        """An up line, such as "the parent has moved past your root step", is said once, not at every boundary."""
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move", "Tell docs"))
        self.plan(TOP, items("Port the hooks", "Move the store layout into phi", "Write the layout docs", at=2))
        first = self.plan(A, {"advance": True})
        self.assertIn("up: the parent has moved past your root step 2", first)
        again = self.plan(A, {"advance": True})
        self.assertNotIn("moved past", again)

    def test_the_parent_revising_the_childs_parent_step_reaches_it_at_its_next_advance(self):
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.assertEqual(self.plan(A, {"advance": True}), "", "nothing bears on 2.2: quiet")
        self.plan(TOP, items("Port the hooks", "Move the store layout into temportal instead", "Write the layout docs",
                             at=1))
        ctx = self.plan(A, {"advance": True})
        self.assertIn("step 2.3 starts now", ctx)
        self.assertIn("your root step 2 in the task list of \"top\" was revised", ctx)
        self.assertNotIn("up: the parent revised your root step 2", ctx, "the warning about the revision says it once")
        self.assertEqual(ctx.count("root step 2"), 1)
        self.assertEqual(self.plan(A, {"items": [{"content": "Rewrite p4conf.LAYOUT", "status": "completed"},
                                                 {"content": "Move recall/ into phi/", "status": "completed"},
                                                 {"content": "Commit the move", "status": "completed"},
                                                 {"content": "Tell the docs child", "status": "in_progress"}]}).count(
            "was revised"), 0, "a warning is given once")

    def test_a_parent_that_replaces_its_whole_list_tells_its_worker_nothing(self):
        """A worker is bound to its parent's step by the step's number. A parent that keeps the app's task list for
        the turn it is in sends a new list at each request, so the number then names another step or none, while
        the worker's task stands. Seen in three workers of one orchestrator: each was told `your root step 5 ... was
        removed`, `Stop before the next tool`, and that the parent `revised your root step 5` to a step that was
        never theirs. A list that was replaced tells a worker nothing, at its next message, at its next step and
        at each list after, and its record keeps that the step left the list, as `rootLeft`."""
        t = self.t
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.plan(B, items("Draft the layout table docs for p4conf", "Publish the layout table docs"))
        self.assertEqual((t.session(A)["rootStep"], t.session(B)["rootStep"]), ("2", "3"))
        # the next request: four steps that share no words with the three before them
        self.plan(TOP, items("Read each report of the sessions", "Archive whatever landed", "Save the lessons as "
                             "memories", "Answer the question about usage"))
        for kid, step in ((A, "2"), (B, "3")):
            ctx = context(t.say(kid, "carry on"))
            self.assertNotIn("stop before any tool runs", ctx, kid)
            self.assertNotIn("root step", ctx, kid)
            self.assertNotIn("this session is for step", ctx, "no slice of a list that holds its step no more")
            self.assertEqual(t.session(kid)["rootLeft"]["step"], step)
            ctx = self.plan(kid, {"advance": True})
            self.assertNotIn("up: ", ctx, kid)
            self.assertNotIn("root step", ctx, kid)
        self.assertIn("Move the store layout into phi", t.session(A)["task"], "its task stands")
        # a shorter list, in which the number is gone, and the same list sent again, as after a compaction
        self.plan(TOP, items("Answer the question about usage"))
        self.plan(TOP, items("Answer the question about usage"))
        for kid in (A, B):
            ctx = context(t.say(kid, "carry on")) + self.plan(kid, {"advance": True})
            self.assertNotIn("root step", ctx, kid)
            self.assertNotIn("Stop before the next tool", ctx, kid)

    def test_a_step_the_parent_drops_in_words_tells_its_worker_to_stop(self):
        """Only the parent's word stops a worker: a step of the new list that says the worker's step is dropped,
        plans.DROPPED, at the step's own number or anywhere in the list in words that bear on it."""
        t = self.t
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        self.plan(B, items("Draft the layout table docs for p4conf", "Publish the layout table docs"))
        self.plan(TOP, items("Port the hooks", "Dropped: move the store layout into phi", "Write the layout docs",
                             at=0))
        ctx = context(t.say(A, "carry on"))
        self.assertTrue(ctx.startswith("phi (p4-phi): stop before any tool runs."), ctx[:200])
        self.assertIn("your root step 2, \"Move the store layout into phi\", was dropped from the task list of \"top\"",
                      ctx)
        self.assertIn("which now says \"Dropped: move the store layout into phi\"", ctx)
        self.assertIn(f"Stop before the next tool and message {TOP}", ctx)
        self.assertNotIn("rootLeft", t.session(A))
        self.assertNotIn("root step", context(t.say(B, "carry on")), "its own step stands as it was")
        # the docs step is gone from its number, and another step of the list says in words that it is cancelled
        self.plan(TOP, items("Port the hooks", "The layout docs are cancelled, write none"))
        ctx = context(t.say(B, "carry on"))
        self.assertIn("your root step 3, \"Write the layout docs\", was dropped from the task list", ctx)
        self.assertIn("which now says \"The layout docs are cancelled, write none\"", ctx)
        for said, was, now_, hit in (
                ("a word at the step's own number that says nothing else", "Move the store layout", "Dropped", True),
                ("a new step that only names something dropped", "Move the store layout",
                 "Remove the dropped column from the ports table", False),
                ("a step reworded and still wanted", "Move the store layout", "Move the store layout today", False)):
            self.assertEqual(bool(plans.dropped(was, now_, {"2": now_})), hit, said)

    def test_a_worker_follows_its_step_to_the_steps_new_number(self):
        """A step removed above a worker's step moves that step up one number with its words unchanged. The worker
        is told the new number and follows it, in its record and in the addresses of its own list, so the next
        revision is read against the step that is its own, and the worker of the step that left is told nothing."""
        t = self.t
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        self.plan(B, items("Draft the layout table docs for p4conf", "Publish the layout table docs"))
        self.assertEqual([x["addr"] for x in plans.load(t.p4, B)["steps"]], ["3.1", "3.2"])
        self.plan(TOP, items("Port the hooks", "Write the layout docs", at=1))
        self.assertEqual(t.session(B)["rootStep"], "2")
        moved = plans.load(t.p4, B)
        self.assertEqual((moved["root"], moved["current"], [x["addr"] for x in moved["steps"]]),
                         ("2", "2.1", ["2.1", "2.2"]))
        ctx = context(t.say(B, "carry on"))
        self.assertIn("your root step 3 in the task list of \"top\" is now numbered 2; the step itself is unchanged.", ctx)
        self.assertNotIn("Stop before the next tool", ctx)
        self.assertNotIn("root step", context(t.say(A, "carry on")), "the step that left the list says nothing")
        self.assertEqual(t.session(A)["rootLeft"]["step"], "2")
        self.plan(TOP, items("Port the hooks", "Write the layout docs for the store", at=1))
        ctx = context(t.say(B, "carry on"))
        self.assertIn("your root step 2 in the task list of \"top\" was revised from \"Write the layout docs\"", ctx)
        self.assertNotIn("root step", context(t.say(A, "carry on")))

    def test_a_siblings_step_that_changes_the_next_step_is_relayed_across(self):
        t = self.t
        t.say(B, "Write the docs, step 3 of the parent's plan")
        self.plan(B, items("Draft the layout table docs for p4conf", "Publish the layout table docs"))
        self.assertEqual([x["addr"] for x in plans.load(t.p4, B)["steps"]], ["3.1", "3.2"], "the brief names step 3")
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/", "Commit the move"))
        self.plan(A, items("Rewrite the p4conf layout table", "Move recall/ into phi/", "Commit the move"))
        ctx = self.plan(B, {"advance": True})
        self.assertIn("step 3.2 starts now", ctx)
        self.assertIn("revised its task list at 2.1", ctx, "the revision, told across")
        self.assertIn("across: \"the layout child\" is on 2.1", ctx, "the sibling's step in progress")

    def test_down_the_parent_sees_its_childrens_progress_at_its_own_boundary(self):
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        self.plan(A, {"advance": True})
        ctx = self.plan(TOP, {"advance": True})
        self.assertIn("down: \"the layout child\" has 1 of 2 steps done, now on 2.2", ctx)
        self.assertNotIn("down:", self.plan(TOP, {"advance": True}), "told again only when it moved")

    def test_the_parents_report_reaches_the_child_whose_check_it_voids(self):
        """A parent's turn report that voids a child's checks reaches the child."""
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        report = "The plan-step relay replaces the notes relay, so the relay suite checks are void."
        t.stop(TOP, "decide the relay", report=report, uuid="p1")
        ctx = self.plan(A, {"advance": True})
        self.assertIn("ended a turn whose words bear on your open steps: 2.1", ctx)
        self.assertIn(report, ctx, "the parent's own words, quoted")
        nag = context(t.say(TOP, "next"))
        self.assertIn(f"your last turn changed 2.1 in the work of", nag)
        self.assertIn(f"send it the change with SendMessage to `{A}`", nag)
        self.assertNotIn("send it the change", context(t.say(TOP, "and next")), "said once")

    def test_a_progress_report_naming_a_childs_work_is_not_nagged(self):
        """A parent's progress report that shares words with a child's steps is delivered, and the parent is not
        nagged for a change it never sent."""
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        report = ("The layout child is running the relay suite against the notes relay now; the fresh slice sizes "
                  "are next.")
        t.stop(TOP, "progress", report=report, uuid="p3")
        self.assertIn("bear on your open steps: 2.1", self.plan(A, {"advance": True}), "still delivered down")
        self.assertNotIn("send it the change", context(t.say(TOP, "next")), "progress is no change")
        t.stop(TOP, "decide", [("mcp__ccd_session_mgmt__send_message", {"session_id": A, "message": "void"}, "sent")],
               report="The relay suite checks are void; the notes relay is replaced.", uuid="p4")
        self.assertNotIn("send it the change", context(t.say(TOP, "and next")), "the app's send_message counts as sent")

    def test_a_report_the_turn_already_sent_is_not_nagged(self):
        t = self.t
        self.plan(A, items("Run the relay suite against the notes relay", "Check the fresh slice sizes"))
        t.stop(TOP, "decide the relay", [("SendMessage", {"to": A, "message": "the relay suite is void"}, "sent")],
               report="The notes relay is replaced, so the relay suite checks are void.", uuid="p2")
        self.assertNotIn("send it the change", context(t.say(TOP, "next")))

    def lookup(self, host, name, payload, wait=False):
        """A tool call through the `lookup-record` hook, which hooks.json runs after every tool call."""
        t = self.t
        root = os.path.dirname(SRC)
        body = {"session_id": host, "cwd": t.proj, "hook_event_name": "PostToolUse", **payload}
        r = inproc.run(["sh", os.path.join(root, "hooks", "recall-hook.sh"), name], input=json.dumps(body),
                       capture_output=True, text=True, timeout=60,
                       env={**t.env(host), **({"P4_RECALL_SYNC": "1"} if wait else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_the_task_list_check_runs_through_the_lookup_record_hook_once(self):
        """The task-list check rides on the `lookup-record` hook, which hooks.json registers for every tool call; a
        call that also reaches phi.py's own `plan` entry is applied once."""
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
        self.assertIn("plan", logged, "the routed check writes its log line")

    def test_a_session_whose_hook_list_lacks_the_route_gets_its_plan_from_its_transcript(self):
        """A session whose loaded hooks lack the `lookup-record` route, as before `/reload-plugins` loads a newer
        hooks.json, has its update_plan calls read back from the transcript at the next message, each once."""
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

    def test_a_replayed_command_is_no_task_of_p4_phis_own(self):
        """The transcript replay reads task-list calls alone: a command the app moved to the background at its
        timeout is in the Stop input's `background_tasks`, hooks.md, so it is no record of p4-phi's own."""
        t = self.t
        self.plan(A, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        path = os.path.join(self._tmp.name, "c-transcript.jsonl")
        rows = [{"type": "user", "message": {"role": "user", "content": "Move the store layout into phi, in steps"}}]
        for k, (cmd, out) in enumerate((
                ('grep -rn "background with ID" scripts/',
                 'scripts/test_plans.py:889: "Command running in background with ID: bg7quoted1. Output is x"'),
                ("python -m pytest tests/test_flush.py",
                 "Command did not complete within its 120s timeout and was moved to the background with ID: "
                 "bg7moved01. Output is being written to: x"))):
            rows.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"toolu_rq{k}", "name": "Bash", "input": {"command": cmd}}]}})
            rows.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"toolu_rq{k}", "content": out}]}})
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(json.dumps(r) + chr(10) for r in rows))
        t.hook("user-prompt-submit", A, {"hook_event_name": "UserPromptSubmit", "prompt": "go on",
                                         "transcript_path": path})
        self.assertEqual(list(plans._tasks(plans.load(t.p4, A))), [])

    def test_the_transcript_is_read_on_from_where_the_last_replay_stopped(self):
        """Each message and each Stop read the transcript on from the place kept, the first call still without a
        result, so no call is passed before its result is in."""
        t = self.t
        path = os.path.join(self._tmp.name, "b-transcript.jsonl")
        rows = [{"type": "user", "message": {"role": "user", "content": "Move the store layout into phi, in steps"}}]
        kept = os.path.join(t.dir(A), ".calls", "replay.json")

        def put():
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(json.dumps(r) + chr(10) for r in rows))

        def call(k, inp):
            rows.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"toolu_ro{k}", "name": "mcp__ccd_turn__update_plan", "input": inp}]}})
            put()

        def result(k):
            rows.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"toolu_ro{k}", "content": "Plan updated."}]}})
            put()

        def message(text):
            return context(t.hook("user-prompt-submit", A, {"hook_event_name": "UserPromptSubmit", "prompt": text,
                                                           "transcript_path": path}))

        def offset():
            with open(kept, encoding="utf-8") as f:
                return json.load(f)["offset"]
        call(0, items("Rewrite p4conf.LAYOUT", "Move recall/ into phi/"))
        result(0)
        message("go on")
        self.assertEqual([x["addr"] for x in plans.load(t.p4, A)["steps"]], ["2.1", "2.2"])
        self.assertEqual(offset(), os.path.getsize(path), "everything read: the next replay starts at the end")
        before = os.path.getsize(path)
        call(1, {"advance": True})
        message("next")
        self.assertEqual(plans.load(t.p4, A)["current"], "2.1", "a call with no result yet is not applied")
        self.assertEqual(offset(), before, "and holds the place, so it is read again")
        result(1)
        message("and now")
        p = plans.load(t.p4, A)
        self.assertEqual(p["current"], "2.2", "applied once its result is in")
        self.assertEqual(offset(), os.path.getsize(path))
        before = os.path.getsize(path)
        call(3, {"advance": True})
        # lines between a call and its result never move the place past the call
        rows.append({"type": "user", "isSidechain": True, "message": {"role": "user", "content": "a sub-agent's row"}})
        rows.append({"type": "user", "message": {"role": "user", "content": "a message that came while it ran"}})
        put()
        message("a message that came while it ran")
        self.assertEqual(offset(), before, "the call still holds the place")
        self.assertEqual(plans.load(t.p4, A)["current"], "2.2")
        result(3)
        message("go on")
        self.assertNotEqual(plans.load(t.p4, A)["current"], "2.2", "applied once its result came")
        self.assertEqual(offset(), os.path.getsize(path))
        self.assertEqual(phi.resume_at([100, 900], 1000, hold=500), 900, "a call cut off long ago holds nothing")
        self.assertEqual(phi.resume_at([100], 1000, hold=500), 1000)
        self.assertEqual(phi.resume_at([], 1000), 1000)

    def test_a_finished_child_a_newer_note_supersedes_is_counted_as_archived(self):
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
        self.assertTrue(kept[-1]["claim"].startswith(f"replaces: \"the layout child\" ({A}) as a live session."))
        self.assertIn("cb3b6d2", kept[-1]["claim"], "its still-true outcome, with its report")
        ctx = context(t.say(TOP, "next"))
        self.assertIn(f"[the layout child](#{A}). p4-phi counts them as archived from now.", ctx)
        self.assertNotIn("counts them as archived", context(t.say(TOP, "and next")), "said once")
        told = context(t.say(A, "are you still on it?"))
        self.assertIn("this session's work is superseded and it is stale", told)
        t.record(KID2 + "x", TOP, title="a pathless child")
        whole = context(t.say(KID2 + "x", "Help out wherever needed"))
        turns = (whole.split("The last turn of", 1)[1].split("The page this comes from", 1)[0]
                 if "The last turn of" in whole else "")
        self.assertNotIn("the layout child", turns, "a stale session's last turn is no part of a start background")
        t.record(GRAND, TOP, title="a later child")
        self.assertNotIn("the layout child", context(t.say(GRAND, "Write `docs/exporter.md`, step 2")),
                         "left out of a fresh child's start")
        self.plan(TOP, items("Move the store layout into recall", "Write the exporter docs for phi", at=1))
        self.assertIn("your root step 2 in the task list of \"top\" was revised", self.plan(B, {"advance": True}),
                      "the other two keep getting the warnings")
        t.stop(A, "re-based", report="Re-based onto phi/.", uuid="a2")
        self.assertNotIn("stale", t.session(A), "told, and with a turn of its own ended since, live again")
        t.stop(B, "another turn", uuid="b2")
        kept = [json.loads(l) for l in open(os.path.join(t.dir(TOP), "notes.jsonl"), encoding="utf-8")]
        self.assertEqual(sum(1 for k in kept if "as a live session" in k["claim"]), 1,
                         "never counted as archived twice")

    def test_a_fresh_child_starts_with_its_parent_step_and_a_fork_has_it_pinned(self):
        t = self.t
        t.record(GRAND, TOP, title="the step child")
        ctx = context(t.say(GRAND, "Write the docs for step 3"))
        self.assertIn("this session is for step 3 of its parent's task list, \"Write the layout docs\"", ctx)
        self.assertIn("- 2 [in_progress] Move the store layout into phi", ctx, "the parent's task list around it")
        self.assertIn("3.1, 3.2, and so on", ctx)
        t2 = Tree(os.path.join(self._tmp.name, "f"))
        t2.record(TOP, title="top")
        t2.record(GRAND, TOP, title="the forked step child")
        t2.say(TOP, "Build it")
        r = t2.hook("plan", TOP, {"tool_name": "mcp__ccd_turn__update_plan", "tool_input": items("a", "b", at=1)})
        self.assertEqual(r.returncode, 0)
        t2.say(GRAND, "Task (from the session that started this one):\nDo the b part")
        later = context(t2.say(GRAND, "carry on"))
        self.assertIn("It is for step 2 of its parent's task list; its own steps are 2.1, 2.2", later)


class Levels(unittest.TestCase):
    """Delegation: a long foreground command runs as sent with no line, since the app moves it to the background at
    its own timeout; a step is named for where it runs."""

    LONG = {"command": "cd scripts && python -I -X utf8 test_flush.py 2>&1 | tail -3", "description": "Run the tests"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.record(A, TOP, title="the layout child")
        self.t.say(TOP, "Build the exporter")
        self.t.say(A, "Move the store layout into phi, in steps")
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    plan = TreeOfPlans.plan

    def pre(self, host, inp, tool="Bash", tree=None, **more):
        """A shell call's PreToolUse through the `lookup-check` hook -> the hook's own output, {} for none."""
        t = tree or self.t
        self.n += 1
        body = {"session_id": CLI[host], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": f"toolu_lv{self.n}", **more}
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60,
                       env=t.env(host, CLAUDE_PLUGIN_DATA=os.path.join(self._tmp.name, "data")))
        self.assertEqual((r.returncode, r.stderr.strip()), (0, ""))
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else {}

    def test_a_long_foreground_command_runs_as_sent_with_no_line(self):
        """tools-reference.md, "Foreground commands that move to the background": the app moves a foreground command
        to the background at its timeout, so p4-phi rewrites no call and hands no line beside it."""
        self.t.forget(A)                           # a session that started one is a puppeteer: this one started none
        for host in (TOP, A):
            for tool in ("Bash", "PowerShell"):
                self.assertEqual(self.pre(host, dict(self.LONG), tool=tool), {}, (host, tool))

    def test_a_command_already_running_is_not_started_again(self):
        """restart-check reads `run_in_background`: a second background start of a command the Stop input listed as
        still running is refused once, and the shell gate lets every background start through to it."""
        from test_phi import STOP, transcript
        self.t.forget(A)
        path = transcript(os.path.join(self.t.tmp, TOP + "rs.jsonl"), "Build the exporter", (), "Running.", "rs")
        r = self.t.hook(STOP, TOP, {"hook_event_name": "Stop", "transcript_path": path,
                                    "last_assistant_message": "Running.",
                                    "background_tasks": [{"id": "bg7level01", "type": "shell", "status": "running",
                                                          "description": "the tests", "command": self.LONG["command"]}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.pre(TOP, {**self.LONG, "run_in_background": True})
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("bg7level01", out["permissionDecisionReason"])
        self.assertEqual(self.pre(TOP, {**self.LONG, "run_in_background": True}), {}, "a second try goes through")
        self.assertEqual(self.pre(TOP, {"command": "python other.py", "run_in_background": True}), {})

    def test_no_start_call_or_card_is_handed_out_with_neither_key(self):
        """The plugin-gap line hands no start call at all, and a sentence beginning "Model:" is no choice of the
        parent session's."""
        import gaps
        plug = os.path.join(self._tmp.name, "plugproj")
        os.makedirs(os.path.join(plug, ".claude", "p4"))
        subprocess.run(["git", "init", "-q", plug], check=True, capture_output=True)
        subprocess.run(["git", "-C", plug, "remote", "add", "origin", "https://github.com/team/plug.git"],
                       check=True, capture_output=True)
        mem = os.path.join(self.t.p4, "temportal", "memory", "children-on-parent-branch.md")
        os.makedirs(os.path.dirname(mem), exist_ok=True)
        with open(mem, "w", encoding="utf-8") as f:
            f.write("---\nname: children-on-parent-branch\ndescription: x\nmetadata:\n  type: feedback\n---\n\n"
                    "A session started from another works on the parent's branch, and only the parent merges and "
                    "pushes.\n")
        s = relay._session(self.t.p4, TOP)
        said = gaps.advice(self.t.p4, self.t.p4, s, mem, root=plug)
        self.assertIn("\nFinding: the plugin in team/plug", said)
        self.assertNotIn("start_session", said, "the plugin-gap line hands no start call: its finding goes up")
        self.assertEqual(plans.said_level("Model: ranker.pt is rebuilt\nEffort: low on the first pass"), {},
                         "a sentence that begins with Model: or Effort: names no choice")
        self.assertEqual(plans.said_level("Model: ranker.pt\nEffort: loud"), {}, "nor an unknown model or effort")
        self.assertEqual(plans.said_level("- **Model:** `claude-haiku-5-5`.\nEffort: Low"),
                         {"model": "claude-haiku-5-5", "effort": "low"})
        self.assertEqual(plans.said_level("Model: sonnet\nEffort: medium"), {"model": "sonnet", "effort": "medium"})
        call = plans.with_level({"context": "fresh", "title": "the ranker",
                                 "prompt": "Rebuild it in train.py.\nModel: ranker.pt is rebuilt"})
        self.assertEqual((call["model"], call["effort"]), ("claude-opus-5-5", "medium"),
                         "its kind's choice stands: a build is a writer's")

    def test_a_child_session_is_started_with_a_model_and_an_effort_that_fit_its_step(self):
        """A child that writes static pages under docs/ starts on a cheaper model and a lower effort than its parent."""
        import puppeteer
        import starts
        docs, script = "Write the puppeteer pages under docs/", "Change how plans.py reads the address of a step"
        self.assertEqual(plans.child_level(docs), {"model": "claude-sonnet-5-5", "effort": "high", "kind": "static"})
        self.assertEqual(plans.child_level(script), {"model": "claude-opus-5-5", "effort": "medium", "kind": "build"})
        self.assertEqual(plans.child_level("Review the relay's design")["kind"], "review")
        self.assertEqual(plans.child_kind("Bump the version to 0.10.1"), "static")
        self.assertEqual(plans.child_kind("Rename the README's headings and fix phi.py"), "build", "code decides")
        brief = "Write the puppeteer pages. Report when done.\nFiles: docs/puppeteer.html"

        def requested(title, text):
            """The call of a start request, as controls.request_call makes it: the brief, then the request's marker."""
            rid, _ = starts.add(self.t.p4, TOP, title, text, to="local_pup00009")
            return rid, plans.with_level({"context": "fresh", "title": title,
                                          "prompt": text + "\n\n" + starts.marker(rid, TOP)}, title + "\n" + text)
        rid, call = requested("docs: the puppeteer pages", brief)
        self.assertEqual((call["model"], call["effort"]), ("claude-sonnet-5-5", "high"), "cheaper")
        self.assertIn("\n\nModel and effort: claude-sonnet-5-5 at high effort, since this is static or mechanical "
                      "work, an integrator's, as the skill sub-agentic gives it.\n\n" + starts.marker(rid, TOP), call["prompt"])
        self.assertEqual(starts.requester_of(self.t.p4, call["prompt"]), (rid, TOP), "the marker is still read")
        brief2 = "Make relay.py hold the lock in warn. Report when done.\nFiles: scripts/relay.py"
        _, call = requested("the relay lock", brief2)
        self.assertEqual((call["model"], call["effort"]), ("claude-opus-5-5", "medium"), "a writer's")
        self.assertIn("Model and effort: claude-opus-5-5 at medium effort, since this is a build that "
                      "changes behaviour, a writer's", call["prompt"])
        own = brief2 + "\nModel: claude-haiku-5-5\nEffort: low"
        _, call = requested("the relay lock, cheaply", own)
        self.assertEqual((call["model"], call["effort"]), ("claude-haiku-5-5", "low"),
                         "the parent session's choice wins")
        self.assertIn("named by the parent session", call["prompt"])
        draft = {"title": "docs: the levels page", "context": "fresh", "brief": brief, "background": "b" * 90}
        call = puppeteer.call_of(draft)
        self.assertEqual((call["model"], call["effort"]), ("claude-sonnet-5-5", "high"), "the start draft's call")
        fork = puppeteer.call_of({**draft, "context": "fork"})
        self.assertNotIn("effort", fork, "the app gives a fork its parent session's, and takes neither key")
        for c in (plans.with_level({"context": "fresh", "title": t, "prompt": b})
                  for t, b in (("x", ""), ("the docs", brief), ("the lock", brief2), ("Review it", "Review the diff"))):
            self.assertIn(c["effort"], plans.EFFORTS, "a call with neither key is never handed out")
        old = plans.CHILD_LEVELS
        try:
            relay._write_json(os.path.join(self.t.p4, "p4.json"),
                              {"phi": {"child_levels": {"static": {"model": "claude-haiku-5-5", "effort": "low"},
                                                        "build": {"effort": "loud"}}}})
            phi.project_conf(self.t.p4)
            self.assertEqual(plans.child_level(docs), {"model": "claude-haiku-5-5", "effort": "low", "kind": "static"})
            self.assertEqual(plans.child_level(script)["effort"], "medium", "an effort the app does not have is ignored")
        finally:
            plans.CHILD_LEVELS = old


class ParentEffort(unittest.TestCase):
    """The app starts no session above its starter's effort, a limit no docs page states and
    p4-temportal's hooks/claude_code_limits.json logs. hooks.md, "Common input fields", gives every hook with a tool-use context
    `effort`, an "Object whose `level` is the effort level setting when the hook runs", and says "`$CLAUDE_EFFORT`
    holds the same level." So p4-phi reads the starter's level there, keeps the last one seen on the session's record,
    and names no start's effort above it."""

    BUILD = "Change how plans.py reads the address of a step"
    DOCS = "Write the puppeteer pages under docs/"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.say(TOP, "Build the exporter")
        self.env = os.environ.pop("CLAUDE_EFFORT", None)     # a run from a session's shell carries that session's own
        self.me = type("Me", (), {"home": self.t.p4, "id": TOP})()

    def tearDown(self):
        plans.PARENT_EFFORT = ""
        os.environ.pop("CLAUDE_EFFORT", None)
        if self.env is not None:
            os.environ["CLAUDE_EFFORT"] = self.env
        self._tmp.cleanup()

    def plan(self, host, inp, **payload):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated.", **payload})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_a_step_whose_item_names_its_session_is_handed_out_to_nobody(self):
        """An item of `update_plan` has the field `session`, by the tool's own text "When you delegated this step to
        a session you started: that session's short name". A step keeps the field, and such a step stays where it
        is with that as the reason."""
        t, p = self.t, self.t.proj
        port = f"Port the exporter in {p}/src/export/flush.py to the new writer"
        parse = f"Rewrite the parser in {p}/src/parse.py for the new grammar"
        self.plan(TOP, {"scope": "first_task", "items": [
            {"content": port, "status": "in_progress", "session": " exporter-port "},
            {"content": parse, "status": "pending"}, {"content": "Commit and push", "status": "pending"}]})
        kept = plans.load(t.p4, TOP)
        self.assertEqual([st.get("session") for st in kept["steps"]], ["exporter-port", None, None])
        self.plan(TOP, {"advance": True})
        self.assertEqual(plans.load(t.p4, TOP)["steps"][0].get("session"), "exporter-port", "kept through an advance")
        self.assertIn("exporter-port", plans.handed({"session": "exporter-port"}))
        self.assertEqual(plans.handed({"content": parse}), "", "with no session named, a step is nobody's yet")

    def test_the_level_a_task_list_is_seen_at_is_kept_and_holds_a_build_childs_effort(self):
        p = self.t.proj
        self.plan(TOP, items(f"Port the exporter in {p}/src/export/flush.py to the new writer",
                             f"Rewrite the parser in {p}/src/parse.py for the new grammar", "Commit and push"),
                  effort={"level": "medium"})
        self.assertEqual(relay._session(self.t.p4, TOP).get("effort"), "medium", "the level seen is kept on the record")
        plans.PARENT_EFFORT = "low"
        self.assertEqual(plans.child_level(self.BUILD),
                         {"model": "claude-opus-5-5", "effort": "low", "kind": "build", "capped": True})
        call = plans.with_level({"context": "fresh", "title": "the step address",
                                 "prompt": "Change how plans.py reads the address of a step.\nFiles: scripts/plans.py"})
        self.assertEqual(call["effort"], "low")
        self.assertIn("Model and effort: claude-opus-5-5 at low effort, since this is a build that changes behaviour, "
                      "a writer's, as the skill sub-agentic gives it, held to the parent session's own effort.", call["prompt"])
        own = plans.with_level({"context": "fresh", "title": "x", "prompt": "Fix relay.py.\nEffort: max"})
        self.assertEqual(own["effort"], "low", "an effort the brief names itself is held to the starter's too")

    def test_an_effort_at_or_below_the_starters_is_named_as_its_kind_gives_it(self):
        for mine, docs, build in (("", "high", "medium"), ("low", "low", "low"), ("medium", "medium", "medium"),
                                  ("high", "high", "medium"), ("xhigh", "high", "medium"),
                                  ("max", "high", "medium")):
            plans.PARENT_EFFORT = mine
            self.assertEqual((plans.child_level(self.DOCS)["effort"], plans.child_level(self.BUILD)["effort"]),
                             (docs, build), mine or "no level seen")
        plans.PARENT_EFFORT = "high"
        self.assertNotIn("capped", plans.child_level(self.BUILD), "an effort its starter can give is not marked")
        self.assertNotIn("held to", plans.level_line(plans.child_level(self.BUILD)))

    def test_the_level_is_read_from_the_hook_input_or_the_variable_and_the_last_one_seen_is_kept(self):
        me = self.me
        self.assertEqual(phi.own_effort(me, {}), "", "nothing names one")
        self.assertEqual(phi.own_effort(me, {"effort": {"level": "medium"}}), "medium")
        self.assertEqual(relay._session(self.t.p4, TOP)["effort"], "medium")
        self.assertEqual(phi.own_effort(me, {}), "medium", "a hook input with no effort: the record's last level")
        self.assertEqual(phi.own_effort(me, {"effort": {"level": "max"}, "agent_id": "a1"}), "medium",
                         "a subagent's call names the subagent's level")
        self.assertEqual(phi.own_effort(me, {"effort": {"level": "max"}}, other=True), "medium",
                         "a command run for another session names its caller's level")
        self.assertEqual(phi.own_effort(me, {"effort": {"level": "loud"}}), "medium", "no level the app has")
        self.assertEqual(phi.own_effort(me, {"effort": "high"}), "medium", "no object with a level")
        os.environ["CLAUDE_EFFORT"] = "low"
        self.assertEqual(phi.own_effort(me, {}), "low", "CLAUDE_EFFORT holds the same level")
        self.assertEqual(phi.own_effort(me, {"effort": {"level": "xhigh"}}), "xhigh", "the hook input comes first")
        self.assertEqual(relay._session(self.t.p4, TOP)["effort"], "xhigh")
        gone = type("Me", (), {"home": self.t.p4, "id": "local_norecord"})()
        self.assertEqual(phi.own_effort(gone, {"effort": {"level": "high"}}), "high")
        self.assertFalse(os.path.exists(os.path.join(self.t.p4, "phi", "sessions", "local_norecord")),
                         "a session with no record yet gets none made")


class IsPlanner(unittest.TestCase):
    def test_landing_and_code_lines_are_no_planners_and_planning_lines_are(self):
        for line in ("Land section 2 of the plan the user approved", "Land the plan for the ports move",
                     "Review the plan of the release", "Make the plan file executable"):
            self.assertFalse(plans.is_planner(line), line)
        for line in ("Plan the move", "write the plan", "draft a plan for X"):
            self.assertTrue(plans.is_planner(line), line)


class TopOrchestrates(unittest.TestCase):
    """An orchestrator keeps itself free for orchestration. A child whose brief says "report when done" leaves
    its outcome on its parent as a replaces: note and counts as archived, and the parent's line offers it to ezexe
    with no archive call. A child archived in the app leaves the down-lines and the anchor."""

    C = "local_kid00003"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"upkeep": False}}))   # set by hand: off
        self.t.record(TOP, title="top")
        self.t.record(A, TOP, title="the layout child")
        self.t.say(TOP, "Build the exporter")

    def tearDown(self):
        self._tmp.cleanup()

    plan = TreeOfPlans.plan

    def test_a_step_that_plans_stays_and_a_step_that_builds_code_about_plans_is_work(self):
        """Planning stays with the orchestrator, and a plan file has one writer."""
        for stays in ("Enter plan mode", "Research how plans are built and distributed",
                      "Write plan sections with fences and edits", "Put the plan to ezexe for approval",
                      "Plan the exporter's move"):
            self.assertEqual(plans.top_stays(stays), plans.PLANNING_WHY, stays)
        for stays in ("Loop the plan until two rounds are dry", "Revise the development plan after the read",
                      "Enter plan mode", "Write up the plan", "Research and write the plan",
                      "Put together a plan for the exporter"):
            self.assertEqual(plans.top_stays(stays), plans.PLANNING_WHY, stays)
        for work in ("Write the plan parser in src/plan.py", "Write the plan-file reader",
                     "Port the exporter to the new writer", "Write the docs for plan mode",
                     "Revise the plan-mode nudge in phi.py", "Draft the README section on plans",
                     "Write the floor plan renderer in src/render.py", "Put the fixtures under tests/plan/"):
            self.assertEqual(plans.top_stays(work), "", work)
        self.assertEqual(plans.top_stays("Land section 2 of the plan"), "checks or lands the work")
        for stays in ("Start run A and run B", "Launch the two runs of the plan"):
            self.assertEqual(plans.top_stays(stays), "starts a check, test or session, which is orchestration", stays)

    def test_plan_mode_entered_and_left_inside_a_turn_is_known(self):
        """hooks.md names no event for a change of the permission mode, and the hooks module's check hands python
        no mode, so the records of `EnterPlanMode` and `ExitPlanMode` are the word of it. PostToolUse runs
        "immediately after a tool completes successfully", so `ExitPlanMode`'s is the approval. The records hand
        the session nothing."""
        tool = {"hook_event_name": "PostToolUse", "tool_input": {}, "tool_response": {}}
        r = self.t.hook("plan-mode", TOP, {**tool, "tool_name": "EnterPlanMode"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), True)
        r = self.t.hook("plan-mode", TOP, {**tool, "tool_name": "ExitPlanMode",
                                           "hook_event_name": "PostToolUseFailure"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), "a plan sent back is no approval")
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), True, "and the session still plans")
        r = self.t.hook("plan-mode", TOP, {**tool, "tool_name": "ExitPlanMode", "agent_id": "agent-1"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), "a subagent's call is not the session's approval")
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), True, "and the session still plans")
        r = self.t.hook("plan-mode", TOP, {**tool, "tool_name": "ExitPlanMode"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), False, "the approval ends it")

    def test_a_prompts_own_mode_is_over_what_a_plan_mode_tool_said_before_it(self):
        tool = {"hook_event_name": "PostToolUse", "tool_input": {}, "tool_response": {}}
        self.t.hook("plan-mode", TOP, {**tool, "tool_name": "EnterPlanMode"})
        self.t.hook("user-prompt-submit", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": "carry on",
                                                "permission_mode": "default"})
        self.assertEqual(phi.mode_now(type("Me", (), {"id": TOP})(), relay._session(self.t.p4, TOP), {}), "default")
        self.assertEqual(hook.PHI_RECORD["EnterPlanMode"], hook.PHI_RECORD["ExitPlanMode"])

    def test_the_two_plan_mode_tools_reach_their_record_through_the_runner_as_hooks_json_runs_it(self):
        """recall-hook.sh ends a call that worked and printed no word that reads like an error before python
        starts, unless an arm of it names the call. Run without P4_RECALL_SYNC, as a session runs it, the two tools
        reach phi.py's record, and neither answers with a line."""
        runner = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")
        env = self.t.env(TOP)
        env.pop("P4_RECALL_SYNC", None)

        def ran(tool, tid):
            body = {"session_id": CLI[TOP], "cwd": self.t.proj, "hook_event_name": "PostToolUse", "tool_name": tool,
                    "tool_input": {}, "tool_response": {}, "tool_use_id": tid}
            r = subprocess.run(["sh", runner, "lookup-record"], input=json.dumps(body), capture_output=True,
                               text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

        self.assertEqual(ran("EnterPlanMode", "toolu_run_in").strip(), "")
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), True)
        self.assertEqual(ran("ExitPlanMode", "toolu_run_out").strip(), "")
        self.assertIs(relay._session(self.t.p4, TOP).get("planMode"), False)

    def test_a_top_sessions_landing_steps_stay_with_it(self):
        landing = {"steps": [{"addr": str(k + 1), "content": c, "status": "pending"} for k, c in
                             enumerate(("Test and commit the port", "Merge and push main", "Release 0.9"))]}
        self.assertTrue(all(plans.top_stays(st["content"]) for st in landing["steps"]))

    def test_handing_something_to_a_named_session_is_orchestration(self):
        """A step that queues, sends, passes, hands or forwards something to a named session is orchestration."""
        named = ("Queue issues #19-#24 to p4-phi fixer", "Send the findings to local_06483534-0275",
                 "Pass the audit to \"Raise memory patches\"", "Hand the leftover queue to the new owner of p4-phi",
                 "Forward the issue links to the top session", "Relay issue links and queue to top")
        work = ("Pass the parser output to the formatter in src/fmt.py", "Write the queue module in src/queue.py")
        for text in named:
            self.assertTrue(plans.top_stays(text), text)
        for text in work:
            self.assertEqual(plans.top_stays(text), "", text)

    def test_a_child_marked_report_when_done_leaves_a_replaces_note_and_is_named_to_its_parent(self):
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
        self.assertIn("p4-phi counts it as archived from now", mine[0])
        self.assertIn("flush.py", mine[0])
        self.assertIn("Still open:", mine[0])
        self.assertNotIn(C, plans._children(t.p4, TOP), "out of the down-lines")
        self.assertNotIn(C, (relay._read_json(relay.anchor_path(t.p4, TOP)).get("nodes") or {}))
        line = context(t.say(TOP, "what next"))
        self.assertIn("the archive tool asks ezexe on the app's approval card", line)
        self.assertNotIn("archive each with `", line, "no archive call is handed out")
        self.assertIn(C, line.split("finished, their outcome kept")[1])
        self.assertNotIn("finished, their outcome kept", context(t.say(TOP, "and then")), "said once")

    def test_a_numbered_check_is_work_and_starting_a_check_is_orchestration(self):
        """A numbered check of anything else, such as "Check 1: nothing hidden in AppData", is work, and starting a
        check, such as "Start ezexe's-eye acceptance check", is orchestration."""
        for work in ("Check 1: nothing hidden in AppData", "Start the dev server and port the CLI in src/cli.py"):
            self.assertEqual(plans.top_stays(work), "", work)
        self.assertEqual(plans.top_stays("Start ezexe's-eye acceptance check"),
                         "starts a check, test or session, which is orchestration")
        self.assertEqual(plans.top_stays("Check the session's own landed work"), "checks or lands the work")
        self.assertTrue(plans.top_stays("Kick off the review session"))
        self.assertTrue(plans.top_stays("Run the docs check"))

    def test_a_top_sessions_check_steps_go_to_children(self):
        for work in ("Check 1: nothing hidden in AppData or %TEMP%", "Verify phi's session tree matches the app"):
            self.assertEqual(plans.top_stays(work), "", work)
        for stays in ("Check the docs child's progress", "Commit locally", "Sync the store"):
            self.assertTrue(plans.top_stays(stays), "only landing and managing a child stay with the orchestrator")

    def test_top_stays_tells_a_step_the_orchestrator_keeps_from_one_that_goes_to_a_child(self):
        for work in ("Verify the tree", "Confirm the store holds no stray file", "Validate the manifest in src/m.json",
                     "Check 3: confirm the docs match the code", "Audit the hooks for a missing matcher",
                     "Inspect the anchor for stale nodes", "Write the sync script in src/sync.py"):
            self.assertEqual(plans.top_stays(work), "", work)
        for stays in ("Sync the store", "Sync each store with p4.py sync --push", "Check the docs child's progress",
                      "Verify the sub-session's report", "Check the session's own landed work", "Merge and push main",
                      "Confirm the fix, then commit", "Wait until the port lands", "Tell the docs session to go"):
            self.assertTrue(plans.top_stays(stays), stays)

    def test_seeing_landed_work_through_stays_and_a_watch_of_anything_else_is_work(self):
        """Seen in an orchestrator on p4-phi 0.11.133 and 0.11.134: for its steps "Watch GitHub's run on piece D"
        and "Update the installed plugins" the advice named a new session in a worktree for each, and the nudge
        called the first a build that changes behaviour, while "Land piece D" stayed as landing. The orchestrator
        pushed the work, so the run on it and the installed plugins' update to its release are its own to see
        through. The object decides: a watch of something else, and a change to a plugin's own files, is work."""
        for stays in ("Watch GitHub's run on piece D", "Update the installed plugins",
                      "Watch the workflow run on what was just pushed", "Follow the release run to its end",
                      "Wait for the CI run on main to pass", "Check that CI passed on the pushed commit",
                      "Run claude plugin update for the three plugins"):
            self.assertEqual(plans.top_stays(stays), "checks or lands the work", stays)
        for work in ("Watch the lock file while two hooks write and record each failed read",
                     "Watch how the hook runs on Windows and fix what fails",
                     "Update the plugin's README with the new command",
                     "Check the workflow file for a missing matcher",
                     "Confirm this runs on Windows", "Verify the actions run correctly in the parser",
                     "Confirm the workflow finishes within the timeout in the engine code",
                     "Update the installed plugin loader code",
                     "Update installed plugins loader to read manifest"):
            self.assertEqual(plans.top_stays(work), "", work)
        # a pipeline that passes its schema test is code of the repository, and none of the session's own work
        self.assertEqual(plans.top_stays("Check the data pipeline passes the schema test"), "")
        # a child is given only the watch that is work
        self.assertTrue(plans.top_stays("Watch GitHub's run on piece D"))
        self.assertTrue(plans.top_stays("Update the installed plugins from lbiza/plugins/p4-phi"))
        self.assertEqual(plans.top_stays("Watch the lock file in src/lock.py while two hooks write"), "")

    def test_queueing_sending_passing_or_handing_to_a_session_is_orchestration(self):
        for stays in ("Queue the memory-patch flag for the p4-phi fixer session",
                      "Pass the scratchpad findings to the temportal session", "Hand step 3 to a child"):
            self.assertTrue(plans.top_stays(stays), stays)
        self.assertEqual(plans.top_stays("Pass the parser output to the formatter in src/fmt.py"), "")

    def test_children_counted_as_archived_at_once_are_all_kept(self):
        """Children counted as archived at once are all kept, since each write of the parent's session.json takes its
        lock."""
        import threading
        home = self.t.p4
        ids = [f"local_race{k:04d}" for k in range(8)]
        raised = []

        def archive(i):
            try:
                relay._pend_archive(home, TOP, i, {"title": i}, "done")
            except Exception as e:                # a child lost to a write that raised, named in the failure
                raised.append(f"{i}: {e!r}")
        threads = [threading.Thread(target=archive, args=(i,)) for i in ids]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(raised, [])
        pend = relay._session(home, TOP).get("staleChildren") or []
        later = [x["id"] for x in relay.drain_archive(home, TOP)]   # a record read empty mid-replace keeps a file
        self.assertEqual(sorted([x["id"] for x in pend] + later), ids)
        self.assertFalse(os.path.exists(os.path.join(relay._dir(home, TOP), "session.json.lock")))

    def test_a_write_of_a_record_another_reader_holds_open_waits_for_it(self):
        """Every finished child's ready_page reads each session.json with no lock, and on Windows os.replace onto a
        file a reader holds open raises PermissionError, which lost that child in the test above about once in
        four loaded suite runs. The write waits for the reader instead."""
        import threading
        path = os.path.join(relay._dir(self.t.p4, TOP), "session.json")
        before = relay._read_json(path)
        f = open(path, encoding="utf-8")          # a reader, as relay._read_json in ready_page is
        threading.Timer(0.3, f.close).start()
        relay._write_json(path, {**before, "staleTold": ["local_held0001"]})
        f.close()
        self.assertEqual(relay._read_json(path).get("staleTold"), ["local_held0001"])
        self.assertEqual([x for x in os.listdir(os.path.dirname(path)) if x.endswith(".tmp")], [], "no temp file left")

    @unittest.skipUnless(os.name == "nt", "only Windows refuses a replace onto a file a reader holds open")
    def test_a_reader_that_never_lets_go_fails_the_write_well_inside_the_lock_wait(self):
        """A write that cannot replace the record gives up after REPLACE_WAIT_S, a third of LOCK_WAIT_S, so another
        writer waiting on the lock it holds meanwhile takes the lock rather than giving up and writing unlocked."""
        path = os.path.join(relay._dir(self.t.p4, TOP), "session.json")
        before = relay._read_json(path)
        with open(path, encoding="utf-8"):        # a reader that holds the record open throughout
            t0 = time.time()
            with self.assertRaises(PermissionError):
                relay._write_json(path, {**before, "staleTold": ["local_held0002"]})
            took = time.time() - t0
        self.assertLess(relay.REPLACE_WAIT_S, relay.LOCK_WAIT_S / 2)
        self.assertGreaterEqual(took, relay.REPLACE_WAIT_S * 0.9)
        self.assertLess(took, relay.LOCK_WAIT_S * 0.6, "given up well before a writer waiting on the lock gives up")
        self.assertFalse(os.path.exists(path + ".lock"))
        self.assertEqual([x for x in os.listdir(os.path.dirname(path)) if x.endswith(".tmp")], [], "no temp file left")

    def test_a_retired_child_whose_parent_write_fails_is_kept_for_the_parents_next_message(self):
        """relay.retire_done marks the child doneRetired before it puts it on the parent, so a parent write that fails
        for good would leave the parent never told. The child goes to its archive-pending file instead, which the
        parent's next message drains."""
        home, C = self.t.p4, self.C
        self.t.record(C, TOP, title="check 3")
        self.t.say(C, HANDED_DISPOSABLE)
        ppath = os.path.join(relay._dir(home, TOP), "session.json")
        raw = relay._write_raw

        def refused(path, d):
            if os.path.normcase(path) == os.path.normcase(ppath):
                raise PermissionError(13, "held open by a reader", path)
            return raw(path, d)
        relay._write_raw = refused
        try:
            self.assertTrue(relay.retire_done(home, TOP, C, "2026-11-17 19:00"))
        finally:
            relay._write_raw = raw
        self.assertTrue(relay._session(home, C).get("doneRetired"))
        self.assertFalse(relay.retire_done(home, TOP, C, "2026-11-17 19:01"), "a later run does not count it again")
        self.assertEqual([x["id"] for x in relay.drain_archive(home, TOP)], [C], "the parent is still told")
        self.assertFalse(os.path.exists(ppath + ".lock"))

    def test_an_archived_childs_note_keeps_the_findings_of_its_final_report(self):
        """An archived child's replaces: note keeps the findings of its final report, even when they stand in the
        message before its last one."""
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
        head = "Check 2 result: both stores FAIL"
        long = relay.findings_of({"report": head + "\n" + "detail line. " * 400})      # over 5,000 characters
        self.assertIn(head, long, "the head of a long report is kept")
        self.assertTrue(long.endswith('...".'), "its tail is cut and marked")
        self.assertLess(len(long), relay.FINDINGS_CHARS + 100)
        bare = relay.findings_of({"done": "done", "report": "Done."})
        self.assertIn("left no report text", bare)
        self.assertNotIn('"Done."', bare)

    def test_phi_disposable_marks_a_child_and_done_counts_it_as_archived(self):
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
        self.assertNotIn(B, plans._children(t.p4, TOP), "a record deleted from the app leaves the session tree")

    def test_a_session_management_step_stays_at_the_top(self):
        for stays in ("Archive the finished orchestrator-rule child", "Check the docs child's progress",
                      "Send the exporter child its brief"):
            self.assertTrue(plans.top_stays(stays), stays)
        self.assertEqual(plans.top_stays("Start the dev server and port the CLI in src/cli.py"), "",
                         "starting a server is work")
        # ezexe/p4#203: the tree's levels are named worker and coworker, and a step that manages one stays here too
        self.assertEqual(plans.top_stays("Start a worker for the docs"), "manages a worker, which is orchestration")
        for stays in ("Start a worker for the docs", "Message the coworker about the tests",
                      "Check the worker's report", "Stop the co-worker on the old branch"):
            self.assertTrue(plans.top_stays(stays), stays)
        for work in ("Fix the worker pool size in src/pool.py", "Stop the worker pool in src/pool.py"):
            self.assertEqual(plans.top_stays(work), "", "a worker pool is work, not a session")

    def test_top_level_sessions_hear_each_other_as_siblings_and_an_archived_one_drops_out(self):
        t, T2 = self.t, "local_top00002"
        t.record(T2, title="the second top")
        t.say(T2, "Rework the fence exporter")
        self.plan(TOP, items("Port the fence exporter's ports table to the new writer", "Commit and push"))
        self.assertIn(T2, relay._siblings(t.p4, relay._session(t.p4, TOP)), "two orchestrators are siblings")
        self.assertIn(TOP, relay._siblings(t.p4, relay._session(t.p4, T2)))
        r = t.cli(T2, "note", "deprecates: the fence exporter's v1 ports table", "--source", "commit fff111")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.stop(T2, "deprecate v1", report="The fence exporter's ports table now goes to the new writer only; "
                                         "v1 is gone.", uuid="t2a")
        ctx = context(t.say(TOP, "next"))
        self.assertIn("deprecates: the fence exporter's v1 ports table", ctx,
                      "a deprecation crosses between orchestrators")
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
        self.assertNotIn(T2, relay._siblings(t.p4, relay._session(t.p4, TOP)),
                         "an orchestrator archived in the app drops out")
        t.stop(TOP, "a turn", uuid="t1a")
        anchor = json.load(open(relay.anchor_path(t.p4, ""), encoding="utf-8"))
        self.assertNotIn(T2, anchor["nodes"], "and leaves the top level's anchor")
        tree = t.cli(TOP, "tree").stdout
        self.assertIn(TOP, tree)
        self.assertNotIn(T2, tree, "an archived orchestrator is not printed")

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
        self.assertNotIn("counts them as archived", line, "archived by hand: no archive line names it")
        self.assertNotIn("finished, their outcome kept", line)


HANDED_DISPOSABLE = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n"
                     "</system-reminder>\n\nTask:\nPort the exporter to the new writer. This session is marked "
                     "archive when done.\n\nDone looks like: the suite passes.")


class NativeGoal(unittest.TestCase):
    """Claude Code's own goal, https://code.claude.com/docs/en/goal.md, in place of the Stop hook's send-back. Where
    phi.json turns `goal` on, the line `Done looks like:` of a worker's brief is the condition the hooks module sets
    once the worker's first turn has ended. While the goal is set the Stop hook sends no turn back, and the done mark
    is read from the row Claude Code leaves in the transcript. With the setting off nothing of it happens."""

    LINE = "the flush is ported, its test passes and the commit is on main."
    BRIEF = "Port the flush to the new hook.\nFiles: hooks/flush.py\nDone looks like: " + LINE + "\n\nReport then."
    ON = {"P4_PHI_GOAL": "1"}
    OFF = {"P4_PHI_GOAL": "0"}

    def worded(self, line, review=True):
        """A worker's condition as it is set: the line, the review of its change where its brief asks for changes,
        as BRIEF does, then the sentences that name the session that started it. A condition a session asked for
        itself carries no review."""
        return " ".join([line] + [plans.REVIEW_PART] * review + [phi.GOAL_STARTER.format(sid=TOP)])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.say(TOP, "Build the two plugins")
        self.t.record(KID, TOP, title="port the flush")

    def tearDown(self):
        self._tmp.cleanup()

    def brief(self, **env):
        """The worker's brief arrives, and it lists two steps."""
        self.assertEqual(self.t.say(KID, self.BRIEF, **env).returncode, 0)
        r = self.t.hook("plan", KID, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                      "tool_input": items("Port the flush", "Run its test", at=0),
                                      "tool_response": "Plan updated."}, **env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def stop(self, report, uuid, **env):
        r = self.t.stop(KID, self.BRIEF, (), report=report, uuid=uuid, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def phi(self, *args, **env):
        """One command of phi.py as the plugin's hooks module runs it for the worker -> its last line, parsed."""
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), *args], capture_output=True,
                       text=True, env=self.t.env(KID, P4_PHI_WATCH="1", P4_PHI_WATCH_NET="0", **env),
                       cwd=self.t.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def leaves(self, uuid, **row):
        """Claude Code writes a goal row at the end of the transcript of the turn `uuid`, as it does once the Stop
        hooks of a Stop have answered."""
        with open(os.path.join(self.t.tmp, KID + uuid + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", "condition": self.LINE,
                                                                     **row}}) + "\n")

    def given_a_goal(self):
        """The first turn ended, the look answered the goal, and the module said the command set it."""
        self.brief(**self.ON)
        self.stop("I ported half the flush.", "u1", **self.ON)
        self.stop("Still porting.", "u1", **self.ON)
        self.stop("Still porting.", "u1", **self.ON)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), self.worded(self.LINE))
        self.assertEqual(self.phi("goal", "set"), {"set": True})

    def test_a_briefs_line_is_read_whole_and_a_goal_row_says_how_its_goal_ended(self):
        self.assertEqual(plans.done_line(self.BRIEF), self.LINE)
        self.assertEqual(plans.done_line("- **Done looks like:** the suite   passes\nmore"), "the suite passes")
        self.assertEqual(plans.done_line("Done looks like: " + "x" * 5000), "x" * plans.GOAL_CHARS)
        for none in ("Done looks like: clear", "what done looks like is the suite passing", "", None):
            self.assertEqual(plans.done_line(none), "", none)      # too short to be a condition, or no such line
        self.assertEqual(plans.goal_over({"met": True, "reason": "the suite passed"}), "met")
        self.assertEqual(plans.goal_over({"met": False, "failed": True, "reason": "it cannot hold"}), "failed")
        self.assertEqual(plans.goal_over({"met": True, "sentinel": True}), "cleared")
        for still_set in ({"met": False, "sentinel": True}, {"met": False, "reason": "not yet"}, {}, None):
            self.assertEqual(plans.goal_over(still_set), "", still_set)
        path = os.path.join(self.t.tmp, "rows.jsonl")
        write(path, json.dumps({"type": "user", "message": {"content": 'a "goal_status" in a message is no row'}}))
        self.assertEqual(plans.goal_row(path), {})
        self.assertEqual(plans.goal_row(os.path.join(self.t.tmp, "none.jsonl")), {})
        write(path, "\n".join(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", **r}})
                              for r in ({"met": False, "sentinel": True}, {"met": False, "reason": "not yet"},
                                        {"met": True, "reason": "the suite passed", "iterations": 2})) + "\n"
              + json.dumps({"type": "system", "subtype": "stop_hook_summary"}) + "\n")
        self.assertEqual(plans.goal_row(path).get("reason"), "the suite passed", "the last one, from the end")
        self.assertEqual(plans.goal_row(path, tail=40), {}, "a tail that holds no whole goal row")

    def test_goal_is_on_by_default_and_a_key_set_false_or_the_variable_at_0_turns_it_off(self):
        import subprocess as sp
        def goal(env=None, file=None):
            home = os.path.join(self._tmp.name, "home")
            if file is not None:
                write(os.path.join(home, "phi", "phi.json"), json.dumps(file))
            code = "import sys; sys.path.insert(0, %r); import phi; phi.configure(%r); print(phi.GOAL)" % (SRC, home)
            e = {k: v for k, v in os.environ.items() if k != "P4_PHI_GOAL"}
            e.update(env or {})
            return sp.run([sys.executable, "-I", "-X", "utf8", "-c", code], capture_output=True, text=True, env=e).stdout.strip()
        self.assertEqual(goal(), "True", "no key and no variable")
        self.assertEqual(goal(file={"book": False}), "True")
        self.assertEqual(goal(file={"goal": False}), "False", "set false by hand")
        self.assertEqual(goal(file={"goal": True}, env=self.OFF), "False", "P4_PHI_GOAL=0")

    def test_with_the_setting_off_nothing_of_the_goal_happens(self):
        self.brief(**self.OFF)
        self.assertNotIn("doneLine", self.t.session(KID))
        self.assertEqual(self.stop("I ported half the flush.", "u1", **self.OFF), {}, "no turn is sent back for open steps")
        self.assertNotIn("goal", self.phi("look", **self.OFF))
        s = self.t.session(KID)
        self.assertNotIn("goal", s)
        self.assertNotIn("transcript", s)
        self.assertEqual(self.phi("goal", "set", **self.OFF), {"set": False}, "no goal was asked for, so none is marked set")
        self.assertEqual(self.stop("Still porting.", "u2", **self.OFF), {})

    def test_goal_on_and_off_write_the_key_the_hooks_read_and_say_how_it_stands(self):
        """A session writes nothing under `.claude` with its own tools, so `phi.py goal on` and `goal off` set the
        key in the store's phi/phi.json, keep the file's other keys, and print how it stands as read back."""
        path = os.path.join(self.t.p4, "phi", "phi.json")
        write(path, json.dumps({"book": False}))
        r = self.t.cli(KID, "goal", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        said = r.stdout.strip()
        self.assertTrue(said.startswith("goal is on in ") and said.endswith("/phi/phi.json"), said)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"book": False, "goal": True})
        self.brief()                               # no variable is set: the store's own key turns it on
        self.assertEqual(self.t.session(KID).get("doneLine"), self.LINE)
        r = self.t.cli(KID, "goal", "off")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().startswith("goal is off in "), r.stdout)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"book": False, "goal": False})
        self.assertEqual(self.stop("I ported half the flush.", "u1"), {}, "off again")
        self.assertNotIn("goal", self.phi("look"), "and the look answers none")
        write(path, "{not json")
        r = self.t.cli(KID, "goal", "on")
        self.assertEqual(r.returncode, 2, "a file that does not parse is left as it is")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")

    def test_a_brief_no_prompt_hook_saw_gives_its_done_line_at_the_first_stop(self):
        """Seen in the desktop app on Claude Code 2.1.326: a copy of the plugin loaded from a session's mods folder
        starts after the session's first message, so no prompt hook saw the brief. The Stop hook took the task from
        the transcript's turn and kept no done line, and the worker got no goal. The line is kept where the task is,
        and the look after that Stop answers it as the goal, once."""
        self.stop("I ported half the flush.", "u1", **self.ON)
        s = self.t.session(KID)
        self.assertTrue(s.get("task"), "the task, from the transcript's turn")
        self.assertEqual(s.get("doneLine"), self.LINE)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), self.worded(self.LINE))
        self.assertNotIn("goal", self.phi("look", **self.ON), "answered once")

    def test_with_the_setting_off_the_first_stop_keeps_the_task_and_no_done_line(self):
        self.stop("I ported half the flush.", "u1", **self.OFF)
        s = self.t.session(KID)
        self.assertTrue(s.get("task"))
        self.assertNotIn("doneLine", s)

    def test_a_brief_that_changes_files_has_its_change_reviewed_in_its_goal_and_one_that_only_reads_does_not(self):
        """Where p4.json's `phi.goal_review` is on, as it is by default, the goal of a worker whose brief asks for
        changes carries the review of the change, plans.REVIEW_PART, between the brief's line and the starter's
        sentences. A brief that only reads, as issues.writing tells it, keeps no review, and a line too long for
        the 4,000 characters a condition holds is cut so that both parts after it stay whole."""
        import p4conf
        self.assertIs(p4conf.DEFAULTS["phi"]["goal_review"], True)
        self.assertEqual(p4conf.env_name("phi.goal_review"), "P4_PHI_GOAL_REVIEW")
        self.brief(**self.ON)
        self.assertIs(self.t.session(KID).get("doneReview"), True)
        self.stop("I ported half the flush.", "u1", **self.ON)
        tail = phi.GOAL_STARTER.format(sid=TOP)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), " ".join((self.LINE, plans.REVIEW_PART, tail)))
        reads = {"sessionId": KID2}
        phi.keep_review(reads, "Check what hooks/flush.py does and report.\nDone looks like: the report names "
                               "each caller of the flush.")
        self.assertNotIn("doneReview", reads)
        kid = {"sessionId": KID, "spawnedFrom": {"sessionId": TOP}}
        cut = phi.goal_condition(kid, "x" * plans.GOAL_CHARS, review=True)
        self.assertEqual(len(cut), plans.GOAL_CHARS)
        self.assertTrue(cut.startswith("x" * 100) and cut.endswith(" ".join(("", plans.REVIEW_PART, tail))), cut[-90:])

    def test_with_the_key_off_a_workers_goal_asks_for_no_review(self):
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"goal_review": False}}))
        self.brief(**self.ON)
        self.assertNotIn("doneReview", self.t.session(KID))
        self.stop("I ported half the flush.", "u1", **self.ON)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), self.worded(self.LINE, review=False))

    def test_the_done_line_is_the_goal_the_look_answers_once_the_first_turn_has_ended(self):
        self.brief(**self.ON)
        self.assertEqual(self.t.session(KID).get("doneLine"), self.LINE)
        self.assertNotIn("goal", self.phi("look", **self.ON), "no turn has ended yet")
        out = self.stop("I ported half the flush.", "u1", **self.ON)
        self.assertEqual(out, {}, "no goal is set yet, and the Stop hook sends no turn back for open steps")
        self.assertEqual(self.phi("look", **self.ON).get("goal"), self.worded(self.LINE))
        self.assertNotIn("goal", self.phi("look", **self.ON), "answered once")
        goal = self.t.session(KID)["goal"]
        self.assertEqual(goal["condition"], self.worded(self.LINE))
        self.assertEqual(self.t.session(KID)["doneLine"], self.LINE, "the brief's line is kept as the brief has it")
        self.assertNotIn("set", goal)
        self.assertEqual(self.stop("Still porting.", "u2", **self.ON), {}, "asked for and not set: no turn is sent back")
        self.assertNotIn("goal", self.phi("look", "--folder", **self.ON), "the folder question answers no goal")

    # plugins/mods/api.md, "Work your mod started before the interruption": the error of a command a stop found in
    # the queue, which the hooks module passes on as why the goal was not set.
    REMOVED = "the command was removed from the queue before it ran"
    # The same page, "What refused calls return": after a stop `$.command.run` "Rejects with an error whose message
    # ends with" this reason, here as the hooks module of p4-phi 0.11.131 passed it on in the desktop app.
    REFUSED = "p4-phi: $.command.run: the session was stopped and nobody has sent input since"
    # What the goal command itself answered where it could set no goal, which is no stop.
    UNAVAILABLE = "Goals are unavailable: hooks are disabled."

    def tick(self):
        """Waits for the clock's next reading, so what follows is never of one instant with what came before."""
        was = phi.now_exact()
        while phi.now_exact() == was:
            time.sleep(0.001)

    def peer(self, text, **env):
        """A message from the session that started the worker begins a turn of it."""
        said = f'<cross-session-message from="{TOP}">{text}</cross-session-message>'
        self.assertEqual(self.t.say(KID, said, **env).returncode, 0)

    def test_a_condition_that_was_answered_and_not_set_is_answered_again_after_a_later_turn(self):
        """Seen on 2026-11-19: a look answered a session's condition, the hooks module's goal command set no goal,
        and the condition was answered to no look again, so the goal was never set. The condition is now answered
        again to the look after a later turn's end, phi.GOAL_TRIES looks in all for a command that ran and set
        nothing. No look answers it while the module says its command has not answered, and none on the timer
        while no turn has ended since the last answer. The module's word of why is kept and printed."""
        self.brief(**self.ON)
        self.stop("I ported half the flush.", "u1", **self.ON)
        want = self.worded(self.LINE)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 1)
        # the command waits in the queue behind a turn that began at once, and that turn ends
        self.stop("Still porting.", "u2", **self.ON)
        self.assertNotIn("goal", self.phi("look", "--goal-flying", **self.ON), "the command has not answered yet")
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 1, "a look that answers nothing counts nothing")
        # the command runs and sets nothing, and the module says what it answered
        self.assertEqual(self.phi("goal", "failed", "--", self.UNAVAILABLE), {"failed": True})
        self.assertEqual(self.t.session(KID)["goal"]["failed"], self.UNAVAILABLE)
        said = self.t.cli(KID, "goal").stdout
        self.assertIn("goal asked for and not set: " + want, said)
        self.assertIn(f"the command did not set it: {self.UNAVAILABLE}", said)
        self.assertIn("1 of 3 looks", said)
        self.assertNotIn("stop", said, "a command that ran is no stop's")
        # a turn has ended since the first answer, so the next look answers the condition again
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 2)
        for _ in range(2):
            self.assertNotIn("goal", self.phi("look", **self.ON), "no turn has ended since: the timer's look answers none")
        self.assertEqual(self.phi("goal", "failed", "--", "the command printed nothing"), {"failed": True})
        # a later turn ends, and the look at its end is the third and last
        self.stop("Still porting.", "u3", **self.ON)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        self.assertEqual(self.phi("goal", "failed", "--", self.UNAVAILABLE), {"failed": True})
        self.stop("Still porting.", "u4", **self.ON)
        self.assertNotIn("goal", self.phi("look", **self.ON), "three looks in all")
        self.assertEqual(self.t.session(KID)["goal"]["tries"], phi.GOAL_TRIES)
        said = self.t.cli(KID, "goal").stdout
        self.assertIn("3 of 3 looks", said)
        self.assertIn("mcp__p4-phi__goal", said, "with none left, the tool that asks anew is named")
        # a command that answers late still sets it, and a goal that is set takes no word that it failed
        self.assertEqual(self.phi("goal", "set"), {"set": True})
        self.assertNotIn("failed", self.t.session(KID)["goal"])
        self.assertEqual(self.phi("goal", "failed", "--", "late"), {"failed": False})
        self.assertEqual(self.t.cli(KID, "goal").stdout.strip(), "goal set: " + want)

    def test_a_stop_costs_the_goal_no_look_and_its_refusal_waits_for_a_turn_a_persons_own_words_began(self):
        """Seen on 2026-11-22 in the desktop app on Claude Code 2.1.326 with p4-phi 0.11.131, in a worker whose
        starter ended its turn with `mcp__ccd_session_mgmt__stop_session`: the goal command in the queue was
        dropped, the starter's message began a turn, and the command of the look at that turn's end was refused,
        "the session was stopped and nobody has sent input since". Both counted as looks, so a third turn of that
        kind would have spent the last and the goal was never set unless a person typed there within them.
        plugins/mods/api.md, "Calls and background work after the user interrupts a turn": such calls "are refused
        until the user's next input". Now a command a stop took counts as no look, a dropped one is answered again
        after a later turn's end, and a refused one waits for the end of a turn a person's own words began, however
        many turns other sessions' messages begin before it."""
        self.brief(**self.ON)
        self.stop("I ported half the flush.", "u1", **self.ON)
        want = self.worded(self.LINE)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        # the starter stops the turn the command waited behind, which drops the command
        self.assertEqual(self.phi("goal", "failed", "--", self.REMOVED), {"failed": True})
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 0, "the look a stop took is given back")
        # the starter's queued message begins a turn, and the look at its end answers the condition again
        self.peer("Carry on with the port.", **self.ON)
        self.stop("Carrying on.", "u2", **self.ON)
        self.tick()
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        # the stop stands, so Claude Code refuses the command: no session's message is a person's input
        self.assertEqual(self.phi("goal", "failed", "--", self.REFUSED), {"failed": True})
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 0, "nor does the refusal cost a look")
        # more such turns than there are looks: no look answers the condition and none is spent
        for n in range(phi.GOAL_TRIES + 1):
            self.peer("And the test too.", **self.ON)
            self.stop("Done that.", f"m{n}", **self.ON)
            self.assertNotIn("goal", self.phi("look", **self.ON), "refused until a person types there")
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 0)
        said = self.t.cli(KID, "goal").stdout
        self.assertIn("goal asked for and not set: " + want, said)
        self.assertIn("0 of 3 looks", said)
        self.assertIn("until a person types in this session", said)
        # a person's own words begin a turn: no look answers while it runs, and the look at its end does
        self.assertEqual(self.t.say(KID, "Go on, and say when the test passes.", **self.ON).returncode, 0)
        self.assertNotIn("goal", self.phi("look", **self.ON), "the turn those words began has not ended")
        self.stop("The test passes.", "u9", **self.ON)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 1)
        self.assertEqual(self.phi("goal", "set"), {"set": True})
        self.assertEqual(self.t.cli(KID, "goal").stdout.strip(), "goal set: " + want)

    def test_a_refusal_told_after_a_persons_input_holds_nothing(self):
        """The refusal names no input since the stop, so input on record from after the look that the refused
        command answers came after the refusal and has lifted it. The module's word of the refusal can reach
        python after that input's prompt hook ran, and the condition then waits for no second message of a
        person's: the look at the end of the turn that input began answers it."""
        self.brief(**self.ON)
        self.stop("I ported half the flush.", "u1", **self.ON)
        want = self.worded(self.LINE)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)
        self.tick()
        self.assertEqual(self.t.say(KID, "Go on, and say when the test passes.", **self.ON).returncode, 0)
        self.assertEqual(self.phi("goal", "failed", "--", self.REFUSED), {"failed": True})
        self.assertEqual(self.t.session(KID)["goal"]["tries"], 0, "the refusal costs no look either way")
        self.stop("The test passes.", "u2", **self.ON)
        self.assertEqual(self.phi("look", **self.ON).get("goal"), want)

    def test_a_hook_that_read_the_session_before_a_goal_command_ran_keeps_that_commands_word(self):
        """A stop that lets a queued message through drops the goal command at the same moment, so the module's
        word of the drop is written while the prompt hook of that message runs, and that hook saves the copy of the
        session it read at its start. The goal and the ask are the goal commands' alone to change, so a hook's save
        keeps what is in the file: the word of the drop, the look it gave back, and an ask made meanwhile."""
        self.brief(**self.ON)
        self.stop("I ported half the flush.", "u1", **self.ON)
        self.assertTrue(self.phi("look", **self.ON).get("goal"))
        held = phi.load_session(self.t.p4, KID)                 # a hook reads the session at its start
        self.assertEqual(self.phi("goal", "failed", "--", self.REMOVED), {"failed": True})
        self.assertEqual(self.t.cli(KID, "goal", "ask", "--", self.OWN).returncode, 0)
        held["toldBy"] = "session"                              # and saves its copy at its end
        phi.save_session(self.t.p4, held)
        s = self.t.session(KID)
        self.assertEqual(s.get("toldBy"), "session", "the hook's own change is saved")
        self.assertEqual(s["goal"].get("failed"), self.REMOVED)
        self.assertEqual(s["goal"]["tries"], 0)
        self.assertEqual(s["goalAsk"]["condition"], self.OWN)

    def test_a_goal_the_transcript_shows_set_is_marked_set_and_an_ask_waits_for_a_command_in_flight(self):
        """The module tells python that the command set the goal by a run of phi.py, which can fail. The transcript
        holds Claude Code's own row for a goal that is set, so a condition that row names as set is marked set and
        answered to no further look, where a second command would start a second turn on it. A row for another
        condition marks nothing. And a session's new ask is answered only once the module's command for the goal
        before it has answered."""
        t = self.t
        self.assertEqual(self.top("goal", "ask", "--", self.OWN).returncode, 0)
        self.assertNotIn("goal", json.loads(self.top("look", "--goal-flying").stdout), "a command is in flight")
        self.assertEqual(t.session(TOP)["goalAsk"]["condition"], self.OWN, "the ask is kept for the next look")
        r = t.stop(TOP, "Build the two plugins", (), report="Row 1 is on main.", uuid="o1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.top("look").stdout).get("goal"), self.OWN)
        def row(uuid, **more):
            """Claude Code writes a goal row at the end of the transcript of the turn `uuid`."""
            with open(os.path.join(t.tmp, TOP + uuid + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", **more}}) + "\n")
        # a turn ends on a row for another condition: nothing is marked, and the look answers again
        r = t.stop(TOP, "Build the two plugins", (), report="Row 2 is on main.", uuid="o2")
        self.assertEqual(r.returncode, 0, r.stderr)
        row("o2", condition="another condition, of an earlier goal", met=False, sentinel=True)
        self.assertEqual(json.loads(self.top("look").stdout).get("goal"), self.OWN)
        self.assertNotIn("set", t.session(TOP)["goal"])
        # the command ran and Claude Code wrote its row, and the module's word of it never arrived
        r = t.stop(TOP, "Build the two plugins", (), report="Row 3 is on main.", uuid="o3")
        self.assertEqual(r.returncode, 0, r.stderr)
        row("o3", condition=self.OWN, met=False, sentinel=True)
        self.assertNotIn("goal", json.loads(self.top("look").stdout), "set already, so not answered again")
        self.assertTrue(t.session(TOP)["goal"].get("set"))
        self.assertEqual(self.top("goal").stdout.strip(), "goal set: " + self.OWN)

    def test_a_session_nobody_started_and_a_brief_with_no_line_get_no_goal(self):
        self.t.say(TOP, "Port it.\nDone looks like: " + self.LINE, **self.ON)
        self.assertNotIn("doneLine", self.t.session(TOP), "an orchestrator's own request is no worker's brief")
        self.assertEqual(self.t.say(KID, "Port the flush to the new hook.", **self.ON).returncode, 0)
        self.stop("Ported.", "u1", **self.ON)
        self.assertNotIn("goal", self.phi("look", **self.ON))

    OWN = "rows 1 to 6 are each on origin/main with their named checks shown passing, or named as left."

    def top(self, *args, **env):
        """One command of phi.py as the hooks module runs it for the session nobody started -> the finished run."""
        return inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), *args],
                          capture_output=True, text=True, cwd=self.t.proj, timeout=60,
                          env=self.t.env(TOP, P4_PHI_WATCH="1", P4_PHI_WATCH_NET="0", **env))

    def test_a_session_nobody_started_gets_the_goal_it_asks_for_with_the_setting_off(self):
        """`phi.py goal ask <condition>`, which the tool `mcp__p4-phi__goal` runs: a session states its own
        condition, and the next look answers it once, as it answers a worker's line. It needs no starter, no line
        `Done looks like:` and no `goal` in phi.json, which is for the goal a worker is given unasked. From the
        module's word that the command set it, the Stop hook sends no turn of the session back, and the verdict
        Claude Code leaves in the transcript ends it."""
        t = self.t
        r = self.top("goal", "ask", "--", "  " + self.OWN.replace(", ", ",\n") + " ")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), phi.GOAL_ASKED)
        self.assertEqual(t.session(TOP)["goalAsk"]["condition"], self.OWN, "kept as one line")
        self.assertNotIn("goal", t.session(TOP))
        self.assertEqual(self.top("goal").stdout.strip(), "goal asked for and not set: " + self.OWN)
        self.assertNotIn("goal", json.loads(self.top("look", "--folder").stdout), "the folder question answers none")
        self.assertEqual(json.loads(self.top("look").stdout).get("goal"), self.OWN)
        self.assertNotIn("goal", json.loads(self.top("look").stdout), "answered once")
        goal = t.session(TOP)["goal"]
        self.assertEqual((goal["condition"], goal["own"], "set" in goal), (self.OWN, True, False))
        self.assertNotIn("goalAsk", t.session(TOP))
        self.assertEqual(json.loads(self.top("goal", "set").stdout), {"set": True})
        self.assertEqual(self.top("goal").stdout.strip(), "goal set: " + self.OWN)
        # a turn with an open step ends, and the Stop hook sends nothing back: the evaluator does
        r = t.hook("plan", TOP, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                 "tool_input": items("Land row 1", "Land row 2", at=0), "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        r = t.stop(TOP, "Build the two plugins", (), report="Row 1 is on main.", uuid="o1")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)
        self.assertTrue(t.session(TOP).get("transcript"), "where the verdict is read, kept with the setting off")
        with open(os.path.join(t.tmp, TOP + "o1.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "attachment", "attachment": {
                "type": "goal_status", "condition": self.OWN, "met": True, "reason": "Each row is on main."}}) + "\n")
        self.assertNotIn("goal", json.loads(self.top("look").stdout))
        self.assertEqual(t.session(TOP)["goal"].get("over"), "met")
        self.assertEqual(self.top("goal").stdout.strip(), "goal over, met: " + self.OWN + "\nEach row is on main.")

    def test_an_ask_takes_the_place_of_a_goal_and_a_word_that_clears_one_is_refused(self):
        """goal.md, "Set a goal": "If a goal is already active, the new one replaces it." So a worker whose brief
        gave it a goal may ask for another, and the look answers the new condition. A condition shorter than
        plans.GOAL_LEAST is refused, so `clear` or one of its aliases is never sent as one, and so is one past the
        4,000 characters a condition holds."""
        self.given_a_goal()
        for bad, said in (("clear", phi.GOAL_SHORT), ("", phi.GOAL_SHORT), ("x" * 4001, phi.GOAL_LONG)):
            r = self.t.cli(KID, "goal", "ask", "--", bad)
            self.assertEqual((r.returncode, r.stderr.strip()), (2, "phi: " + said), bad[:8])
        self.assertNotIn("goalAsk", self.t.session(KID))
        self.assertEqual(self.t.cli(KID, "goal", "ask", "--", self.OWN).returncode, 0)
        self.assertEqual(self.t.cli(KID, "goal", "ask", "--", self.OWN + " Or stop after 20 turns.").returncode, 0)
        self.assertEqual(self.phi("look").get("goal"), self.worded(self.OWN + " Or stop after 20 turns.", review=False),
                         "the later ask, which names the worker's starter as its brief's line did")
        goal = self.t.session(KID)["goal"]
        self.assertEqual((goal["own"], "set" in goal), (True, False), "the one before it is replaced, and not yet set")
        self.assertNotIn("goal", self.phi("look", **self.ON), "the brief's line is not answered again")

    def test_a_goal_row_is_the_kept_condition_with_other_spaces_or_cut_short(self):
        """A goal that is set and whose `Goal set` answer was lost is known by the transcript's goal row. Claude Code
        writes that row, so its condition is compared as the row can hold it, with other spaces or cut short, and a
        goal that is set is not run again, which would start a turn."""
        kept = self.worded(self.LINE)
        self.assertTrue(phi.same_condition(kept, kept))
        self.assertTrue(phi.same_condition("  " + kept.replace(" ", "  ", 3) + "\n", kept))
        self.assertTrue(phi.same_condition(kept[:60] + "…", kept), "cut short, with the mark of a cut")
        self.assertTrue(phi.same_condition(kept[:60], kept))
        self.assertFalse(phi.same_condition(kept[:20], kept), "too few words to tell one condition from another")
        self.assertFalse(phi.same_condition("another condition of some length, which is not the one kept", kept))
        self.assertFalse(phi.same_condition("", kept))
        self.assertFalse(phi.same_condition(None, kept))

    def test_a_workers_condition_says_its_starters_later_word_settles_a_part(self):
        """Seen in the desktop app on 2026-11-19, on Claude Code 2.1.326: a worker's line named "a session you start"
        and a push, its starter then made that start and that push itself and wrote that the work was taken as done,
        and the evaluator, which reads the conversation alone, answered that the message "did not change the wording
        of the condition" and sent the worker back nine times at the end of every turn. So the condition a session
        another session started is given names that session by its id and says a message of its settles a part. A
        session nobody started gets its condition as stated. A brief's line is cut to leave the sentences room in the
        4,000 characters a condition holds, and a condition a session stated itself that leaves none is set as stated."""
        kid = {"sessionId": KID, "spawnedFrom": {"sessionId": TOP}}
        tail = phi.GOAL_STARTER.format(sid=TOP)
        self.assertIn("`" + TOP + "`", tail)
        self.assertIn("takes that part or the whole work as done", tail)
        self.assertEqual(phi.goal_condition(kid, self.LINE), self.LINE + " " + tail)
        self.assertEqual(phi.goal_condition({"sessionId": TOP}, self.LINE), self.LINE, "nobody started it")
        self.assertEqual(phi.goal_condition(kid, ""), "", "no condition, so no sentence alone")
        long = "x" * plans.GOAL_CHARS
        cut = phi.goal_condition(kid, long)
        self.assertEqual(len(cut), plans.GOAL_CHARS)
        self.assertTrue(cut.endswith(" " + tail) and cut.startswith("x" * 100), cut[-80:])
        self.assertEqual(phi.goal_condition(kid, long, cut_to_fit=False), long, "its own words are not cut")
        fits = "x" * (plans.GOAL_CHARS - len(tail) - 1)
        self.assertEqual(phi.goal_condition(kid, fits, cut_to_fit=False), fits + " " + tail)
        # the whole road: the worker asks for a condition of 4,000 characters, and the look answers it as stated
        self.given_a_goal()
        self.assertEqual(self.t.cli(KID, "goal", "ask", "--", long).returncode, 0)
        self.assertEqual(self.phi("look").get("goal"), long)

    def test_while_the_goal_is_set_the_stop_hook_sends_no_turn_back(self):
        self.given_a_goal()
        self.assertTrue(self.t.session(KID)["goal"].get("set"))
        self.assertEqual(self.stop("Working toward the goal.", "g1", **self.ON), {},
                         "open steps, and the goal's evaluator is the one that sends the turn back")
        self.assertEqual(self.stop("Working toward the goal.", "g1"), {}, "the goal is set whatever the setting says")
        self.leaves("g1", met=False, reason="the test has not run")
        self.assertNotIn("goal", self.phi("look", **self.ON))
        self.assertNotIn("over", self.t.session(KID)["goal"], "not yet met: still set")
        self.assertEqual(self.stop("Still working.", "g1", **self.ON), {})

    def test_a_goal_met_marks_the_turn_done_from_the_row_claude_code_leaves(self):
        self.given_a_goal()
        self.assertEqual(self.stop("The flush is ported and its test passes.", "g1", **self.ON), {})
        self.assertFalse(self.t.turns(KID)[-1].get("done"), "the Stop hook runs ahead of the verdict")
        self.leaves("g1", met=True, reason="The test ran and passed, and the commit is on main.", iterations=3)
        self.phi("look", **self.ON)
        goal = self.t.session(KID)["goal"]
        self.assertEqual(goal.get("over"), "met")
        turns = self.t.turns(KID)
        self.assertEqual(turns[-1]["done"], "goal met: The test ran and passed, and the commit is on main.")
        self.assertEqual(len(turns), 2, "the goal turn's row is marked, and no row is added")
        told = phi.latest_reports(phi.load_reports(self.t.p4, TOP))
        self.assertEqual([r["turn"].get("done") for r in told if r["sessionId"] == KID], [turns[-1]["done"]],
                         "the row its starter reads says done too")
        self.assertEqual(self.stop("One more thing.", "u9", **self.ON), {},
                         "the goal is over, and a later turn with open steps is sent back no more than before")

    def test_a_goal_judged_impossible_or_cleared_is_over_and_marks_nothing_done(self):
        for row, over in (({"met": False, "failed": True, "reason": "No test exists."}, "failed"),
                          ({"met": True, "sentinel": True}, "cleared")):
            with self.subTest(over=over):
                self.tearDown()
                self.setUp()
                self.given_a_goal()
                self.assertEqual(self.stop("I cannot finish this.", "g1", **self.ON), {})
                self.leaves("g1", **row)
                self.phi("look", **self.ON)
                self.assertEqual(self.t.session(KID)["goal"].get("over"), over)
                self.assertFalse(self.t.turns(KID)[-1].get("done"))
                self.assertEqual(self.stop("Next.", "u9", **self.ON), {})


class WaitsOnReports(unittest.TestCase):
    """A step that waits on other sessions' reports stays with the orchestrator and is handed to no child."""

    STEPS = ("Await reports from A, B and C", "Check the trees' results against GitHub")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.record(A, TOP, title="A, the layout child")
        self.t.say(TOP, "Run the three trees")

    def tearDown(self):
        self._tmp.cleanup()

    plan = TreeOfPlans.plan

    def test_other_steps_stay_or_go_by_the_same_rules(self):
        for stays in self.STEPS + ("Collect the children's reports", "Wait until every tree reports",
                                   "Check the acceptance session's results", "Read the reports from the fixers"):
            self.assertEqual(plans.top_stays(stays), plans.AWAITS_WHY, stays)
        for work in ("Fix session report truncation", "Write the children's reports page in docs/reports.html",
                     "Add the trees' results to the board in controls.py",
                     "Collect the timings of the build in out/t.csv", "Verify phi's session tree matches the app",
                     "Check 1: nothing hidden in AppData", "Write the report of the run in docs/run.md"):
            self.assertEqual(plans.top_stays(work), "", work)

class DoerAndObject(unittest.TestCase):
    """Messaging or handing to sessions stays with the orchestrator; running checks yourself goes to a child."""

    def kept(self, text):
        return bool(plans.top_stays(text))

    def test_the_doer_and_the_object_decide(self):
        self.assertTrue(self.kept("Hand fixes to sibling's fixers, stop duplicates"))
        self.assertFalse(self.kept("Re-run failed checks 1, 2, 6"))
        self.assertTrue(self.kept("Start the acceptance session"))
        self.assertTrue(self.kept("Start ezexe's-eye acceptance check"))


class OwnLines(unittest.TestCase):
    """A report quoting p4-phi's own lines is not delivered again, and queued turn reports stay few."""

    def test_phi_lines_are_taken_out_of_a_report(self):
        report = ("I wrote x.txt and marked step x done.\n"
                  "phi (p4-phi): step 1.1 starts now, \"x: write nodetest/split/x.txt\". What bears on it:\n"
                  "- across: \"Live node test A\" is on 1.3, \"Ask a sub-agent to summarise nodetest/a1.txt\".\n"
                  "B ended a turn whose words bear on your open steps: 1.1. Check whether those steps still hold.")
        got = plans.own_removed(report)
        self.assertIn("I wrote x.txt", got)
        for gone in ("phi (p4-phi)", "across:", "bear on your open step", "nodetest/a1.txt"):
            self.assertNotIn(gone, got)

    def test_startup_rules_and_session_links_bear_on_no_step(self):
        report = ("At session start, the project's standing rules from memory: act-don't-wait, never-ship-unfinished, "
                  "decide-by-research, keep-working-through-open-tasks, children-on-parent-branch and "
                  "archive-superseded-children.\n"
                  "- built-in, act-don't-wait: a next step the chain can settle is decided and done.\n"
                  "- [Check 6: phi session lines check](#local_abdc4c95-fe9b-4d58-b3ff-942b8338b3de)\n"
                  "- [Check 5: phi session tree check](#local_c47e02af-87f7-4522-96a7-86113f5d3c14)\n"
                  "Its page is at `.claude/p4/phi/sessions/local_edc121d1-f746/session.md` for this session.")
        steps = [{"addr": "6.2", "content": "Read top session's phi-lines.md and startup rules",
                  "status": "in_progress"},
                 {"addr": "6.4", "content": "Read phi session records for this session tree check", "status": "pending"}]
        self.assertEqual(plans.matches(plans.own_removed(report), steps, [], ""), [])
        real = "The relay drops the anchor tree records before it reads them."
        self.assertEqual([st["addr"] for st, _ in plans.matches(real, steps, [], "")], ["6.4"],
                         "words that are about the step still bear on it")

    def test_the_rule_names_are_read_from_the_stores_memories(self):
        """The rule names come from the store's feedback and user memories, so they follow them as they change."""
        from test_phi import memory
        home = tempfile.mkdtemp(prefix="p4-phi-rules-")
        try:
            memory(home, "tree-records-stay", "feedback", "Keep them.")
            memory(home, "records", "user", "One.")
            memory(home, "a-project-note", "project", "Not a rule.")
            self.assertEqual(plans.rule_names(home), {"tree-records-stay", "records"})
            self.assertEqual(plans.rule_names(), set(), "with no store there are no names")
            steps = [{"addr": "6.4", "content": "Read phi session records for this session tree check",
                      "status": "pending"}]
            recited = ("I hold tree-records-stay, so the tree records are kept.\n"
                       "- tree-records-stay: the tree records of a session are kept after its check.")
            self.assertEqual(plans.matches(plans.own_removed(recited, home), steps, [], "", home=home), [])
            self.assertEqual(len(plans.matches(recited, steps, [], "")), 1, "another store has no such rule")
            plain = "- records: the tree records moved to another folder."
            self.assertEqual(len(plans.matches(plain, steps, [], "", home=home)), 0, "a bullet that is a rule")
            self.assertEqual(len(plans.matches("The tree records moved; records are few.", steps, [], "", home=home)),
                             1, "a one-word rule name in a sentence recites nothing")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_relayed_turn_ignores_the_trees_own_words(self):
        step = "Archive the done child session and report"
        said = "Each child session ended its turn with a report, and none is done."
        self.assertTrue(plans.bears(said, step))
        self.assertFalse(plans.relay_bears(said, step), "down: session, child, report and done never count")
        self.assertFalse(plans.relay_bears_sibling(said + " The parent page links the archive.", step))
        self.assertTrue(plans.relay_bears("The exporter flush drops rows.", "Fix the exporter flush"))

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


class BuildInPlannerFor(unittest.TestCase):
    def test_the_session_then_phi_json_then_the_default(self):
        self.assertEqual(plans.build_in_planner_for({"buildInPlanner": False}, {"build_in_planner": True}),
                         (False, "the session's buildInPlanner"))
        self.assertEqual(plans.build_in_planner_for({}, {"build_in_planner": False}),
                         (False, "phi.json build_in_planner"))
        self.assertEqual(plans.build_in_planner_for({}, {}), (True, "the default"))

    def test_a_non_bool_is_skipped(self):
        self.assertEqual(plans.build_in_planner_for({"buildInPlanner": "no"}, {"build_in_planner": 0}),
                         (True, "the default"))


class BuildRoute(unittest.TestCase):
    def test_the_planner_builds_only_where_the_setting_is_on_the_max_plan_is_not_low_and_a_slot_is_free(self):
        self.assertEqual(plans.build_route(True, False, 1)[0], "planner")
        for args, why in (((False, False, 1), "build_in_planner is off"), ((True, True, 1), "the Max plan is low"),
                          ((True, False, 0), "no Max slot is free")):
            way, said = plans.build_route(*args)
            self.assertEqual(way, "print")
            self.assertIn(why, said)

    def test_the_built_report_and_the_message_that_asks_for_it(self):
        self.assertTrue(plans.built_report("/n/report-tp-1-1-ab12.md").endswith("report-tp-1-1-ab12-built.md"))
        self.assertEqual(plans.built_report("/n/r"), "/n/r-built.md")
        said = plans.build_message("/p/plan.md", "/n/report-x-built.md", ["2", "3"], "/repo")
        for part in ("/p/plan.md", "/n/report-x-built.md", "one commit a section", "sections 2, 3", "/repo"):
            self.assertIn(part, said)

    def test_the_message_names_forward_slash_paths_and_no_backslash(self):
        said = plans.build_message("E:\\p\\plan.md", "E:\\n\\report-built.md", ["2"], "E:\\repo")
        for part in ("E:/p/plan.md", "E:/n/report-built.md", "E:/repo"):
            self.assertIn(part, said)
        self.assertNotIn("\\", said)

    def test_the_message_gives_the_evidence_line_form(self):
        self.assertIn("**Evidence:**", plans.build_message("/p/plan.md", "/n/r-built.md", ["2"], "/repo"))

    def test_a_section_with_that_evidence_line_is_landed(self):
        import sections
        text = "# Plan\n\n## 1. A\n\n**Evidence:** abc1234, a.py:3, 5 passed\n\n- **Files:** `a.py`\n"
        found = sections.parse(text)[1]
        self.assertTrue(found and found[0]["landed"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
