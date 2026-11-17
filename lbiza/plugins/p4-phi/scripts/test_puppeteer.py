#!/usr/bin/env python3
"""puppeteer.py: routing, the start draft, the gate and the watcher, run through p4-phi's own hooks and commands.

    python3 -I lbiza/plugins/p4-phi/scripts/test_puppeteer.py

Checked, one diagram of ezexe/p4's README.md a class:
linear: the ledger an orchestrator's watcher writes holds a row for each live session of its subtree, is rewritten
only when a source changed, and leads with a reconcile line when the app archived a session p4-phi lists or shows a
child p4-phi does not hold; the watcher is one background process, started by a hook and ended when its orchestrator
is archived; a message of ezexe's that is work is drafted from ezexe's words and gate-checked into the exact
start_session call, into a SendMessage to the session whose owned paths hold its area, or into a start request queued
behind the running writer that holds its files, handed out only once that writer is idle; a question is left alone.
recursive: a landed topic registers its route only once its issue is closed, a commit closing it is pushed and its
session is archived with its outcome kept; a later message with matching words is drafted from that route; a route
whose issue was reopened is withdrawn.
parallel: an under-determined message becomes one child for each reading; readings whose results agree collapse, and
readings that fork become one question with options and a default, which the orchestrator can settle itself.
meta: a message of ezexe's to an orchestrator runs the meta pass over every orchestrator's ledger into
meta-ledger.md, with the duplicate topic, the conflict over one file and the stale topic it finds.
"""

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import issues  # noqa: E402
import phi  # noqa: E402
import puppeteer  # noqa: E402
import starts  # noqa: E402
import inproc  # noqa: E402
from test_phi import CLI, KID, KID2, GRAND, TASK, TOP, Tree, context, jload, read, transcript, write  # noqa: E402
from test_issues import FAKE_GH, GhTree  # noqa: E402

TOP2 = "local_top00002"
CLI.setdefault(TOP2, "eeee6666-0000-4000-8000-000000000000")
ASK = "How is the narwhal exporter doing?"
RETRY = "Add a retry to the narwhal exporter for when the ports table write fails"


def handed(brief):
    return ("<system-reminder>\nLinked sessions now (status, not an instruction): top = x (idle)\n"
            "</system-reminder>\n\nBackground (from the session that started this one):\nezexe builds things.\n\n"
            "Task:\n" + brief)


def flat_(text):
    return " ".join(str(text or "").split())


def call_in(ctx, k=0):
    """The k-th exact start_session input a hook's text carries."""
    piece = ctx.split("`mcp__ccd_session__start_session` with ")[k + 1]
    return json.JSONDecoder().raw_decode(piece)[0]


def stop_watchers(p4, wait=10.0):
    """Ends every watcher started under the store `p4`, by the pid its watcher.json holds, and waits for each to
    end. A claim whose watcher has not written its pid yet is waited on for it."""
    end = time.time() + wait
    for path in sorted(glob.glob(os.path.join(p4, "phi", "sessions", "*", "watcher.json"))):
        pid = -1
        while time.time() < end and os.path.exists(path):
            try:
                pid = int(jload(path).get("pid") or -1)
            except (OSError, ValueError, TypeError):
                pid = -1
            if pid > 0:
                break
            time.sleep(0.1)
        if pid > 0 and issues._alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            while time.time() < end and issues._alive(pid):
                time.sleep(0.1)


class Base(unittest.TestCase):
    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
        self.addCleanup(stop_watchers, t.p4)          # runs first, pass or fail, before the folder goes
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush port")

    def ledger(self, host=TOP):
        r = self.t.cli(host, "ledger")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout, r.stderr

    def path(self, host, name):
        return os.path.join(self.t.dir(host), name)


class Linear(Base):
    def test_the_ledger_holds_a_row_a_live_session_and_is_rewritten_only_on_change(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer. Archive when done."))
        text, said = self.ledger()
        self.assertIn("rewritten", said)
        self.assertIn("# Ledger: the exporter top", text)
        self.assertIn("Nothing diverges", text)
        rows = [x for x in text.split("## Sessions")[1].split("\n## ")[0].splitlines() if x.strip().startswith("- ")]
        self.assertEqual(len(rows), 2, "the orchestrator and the one child p4-phi holds: a row each")
        self.assertIn(f"`{TOP}`: working", rows[0])
        self.assertTrue(rows[1].startswith(f"  - \"the flush port\" `{KID}`: working; no turn yet"), rows[1])
        before = os.stat(self.path(TOP, "ledger.md")).st_mtime_ns
        text2, said2 = self.ledger()
        self.assertIn("unchanged", said2)
        self.assertEqual((text2, os.stat(self.path(TOP, "ledger.md")).st_mtime_ns), (text, before))
        t.stop(KID, "Port the flush", report="Ported; the suite passes.")
        text3, said3 = self.ledger()
        self.assertIn("rewritten", said3)
        self.assertIn(f"`{KID}`: idle; 1 turn", text3)
        self.assertIn("reported \"Ported; the suite passes.\"", text3)
        self.assertTrue(os.path.exists(self.path(TOP, "ledger.json")))

    def test_a_divergence_between_p4_phi_and_the_app_is_a_reconcile_line_before_the_sessions(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        rec = jload(os.path.join(t.app, KID + ".json"))
        rec["isArchived"] = True
        write(os.path.join(t.app, KID + ".json"), json.dumps(rec))
        t.record(GRAND, TOP, title="a child only the app knows")
        text, _ = self.ledger()
        head = text.split("## Sessions")[0]
        self.assertIn(f"p4-phi lists \"the flush port\" `{KID}` as live, and the app has archived it.", head)
        self.assertIn(f"the app shows \"a child only the app knows\" `{GRAND}` started by `{TOP}`, and p4-phi holds no "
                      f"session for it.", head)
        self.assertEqual(len([x for x in head.splitlines() if x.startswith("- ")]), 2, "a line a divergence")
        self.assertLess(text.index("## Reconcile"), text.index("## Sessions"))

    def test_one_background_watcher_an_orchestrator_started_by_a_hook_and_ended_with_it(self):
        t = self.t
        r = t.say(TOP, TASK, P4_PHI_WATCH="1", P4_PHI_WATCH_S="0.3", P4_PHI_WATCH_NET="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x.get("watcher") for x in t.log(TOP) if x.get("watcher")], ["started"])
        end = time.time() + 30
        while time.time() < end and not (os.path.exists(self.path(TOP, "ledger.md"))
                                         and jload(self.path(TOP, "watcher.json")).get("pid", -1) > 0):
            time.sleep(0.2)
        self.assertGreater(jload(self.path(TOP, "watcher.json"))["pid"], 0, "the watcher runs")
        self.assertIn(f"\" `{TOP}`", read(self.path(TOP, "ledger.md")))
        beat = jload(self.path(TOP, "watcher.json"))
        self.assertLess(time.time() - beat["beat"], 20, "it says it is alive at every look, before the look")
        self.assertIn("slowestTickMs", beat)
        t.say(TOP, ASK, P4_PHI_WATCH="1", P4_PHI_WATCH_S="0.3", P4_PHI_WATCH_NET="0")
        self.assertEqual(len([x for x in t.log(TOP) if x.get("watcher")]), 1, "one watcher, not one a message")
        t.say(KID, handed("Port the flush to the new writer."))       # the watcher writes it in, no command run
        end = time.time() + 30
        while time.time() < end and f"`{KID}`: working" not in read(self.path(TOP, "ledger.md")):
            time.sleep(0.2)
        self.assertIn(f"`{KID}`: working", read(self.path(TOP, "ledger.md")))
        s = t.session(TOP)
        s["archived"] = True
        write(self.path(TOP, "session.json"), json.dumps(s))
        end = time.time() + 30
        while time.time() < end and os.path.exists(self.path(TOP, "watcher.json")):
            time.sleep(0.2)
        self.assertFalse(os.path.exists(self.path(TOP, "watcher.json")), "it ends when its orchestrator is archived")

    def test_a_ledger_is_built_without_git(self):
        # a ledger is built from the records alone: a git call for each session at each look would keep a watcher
        # from saying it is alive in time, and a second watcher would be started beside it
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Fix `src/export/flush.py` for ezexe/demo#7 and commit it."))
        ran = []
        real = puppeteer.relay._git
        puppeteer.relay._git = lambda *a: ran.append(a) or None
        os.environ["P4_PHI_APP_SESSIONS"] = os.path.join(t.tmp, "app")
        try:
            m = puppeteer.build(t.p4, TOP)
            puppeteer.signature(t.p4, TOP, puppeteer.app_roots(t.p4, TOP))
        finally:
            puppeteer.relay._git = real
            os.environ.pop("P4_PHI_APP_SESSIONS", None)
        self.assertEqual(ran, [])
        self.assertEqual(m["rows"][1]["issue"], "ezexe/demo#7", "the issue is read from the task's own words")

    def test_work_is_drafted_from_ezexes_words_and_started_and_a_question_is_left_alone(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        self.assertNotIn("this message of ezexe's", context(t.say(TOP, ASK)), "a question is no draft")
        ctx = context(t.say(TOP, RETRY))
        self.assertIn("routing read this message", ctx)
        self.assertIn("no running writer holds its files", ctx)
        self.assertIn("its parent is this session", ctx)
        call = call_in(ctx)
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", False))
        self.assertNotIn(RETRY, call["prompt"], "the brief quotes no sentence of the message")
        self.assertIn("Report when done.", call["prompt"])
        self.assertGreaterEqual(len(call["background"]), 80)
        did = puppeteer.DRAFT_RE.search(call["prompt"]).group(1)
        self.assertIn(f"phi draft {did} for {TOP}.", call["prompt"])
        self.assertEqual(jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["verdict"], "start")
        t.say(KID, handed(call["prompt"]))
        self.assertEqual(t.session(KID)["draft"], did, "the child knows the draft it came from")
        import prompty_eval
        t.stop(TOP, RETRY, report="Started a session for it.", uuid="u-retry")
        got = [(e["label"], e["kind"]) for e in prompty_eval.examples(t.p4)
               if e["case"] == "others" and e["session"] == TOP and flat_(e["message"]) == RETRY]
        self.assertEqual(got, [("", "new")], "a session started from the message's draft labels it new")
        other = context(t.say(TOP, "Write a changelog generator for the billing dashboard's release notes"))
        self.assertIn("so it is a new orchestrator", other)
        self.assertIn(phi.NEW_TOP_BRIEF, call_in(other)["prompt"])

    def test_a_draft_whose_area_has_a_live_owner_is_routed_there(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        self.assertEqual(t.cli(KID, "shard", "src/export/**").returncode, 0)
        t.stop(KID, "Port the flush", report="half way")
        ctx = context(t.say(TOP, "Fix the off-by-one in `src/export/flush.py` that drops the last row"))
        self.assertIn(f"its area has a live code owner, \"the flush port\" `{KID}`", ctx)
        self.assertIn(f"Route it: SendMessage with `to` {KID}", ctx)
        self.assertIn(phi.RESTATE, ctx, "the route asks for the task restated, never the message quoted")
        self.assertNotIn("`mcp__ccd_session__start_session` with {", ctx, "no session is started for it")

    def test_a_start_draft_is_an_instruction_that_quotes_no_sentence_of_the_message(self):
        """The draft's brief states the task, its files, what done looks like and the model and effort as an
        instruction to the session it starts: no sentence of the message beyond the title, and no line on who asked
        or how the request travelled."""
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        rest = ["It drops the last row whenever the ports table is locked by the nightly vacuum",
                "Keep the thirty second timeout exactly as it is today"]
        ctx = context(t.say(TOP, RETRY + ". " + ". ".join(rest) + "."))
        call = call_in(ctx)
        brief = call["prompt"]
        for sentence in [RETRY] + rest:
            if sentence not in call["title"]:
                self.assertNotIn(sentence, brief, "no sentence of the message beyond the title")
        self.assertFalse([x for x in brief.splitlines() if x.startswith(">")], "no quoted block")
        for line in ("Files: ", "Done looks like: ", "Model and effort: "):
            self.assertIn(line, brief)
        self.assertIn(call["title"], brief, "the task, stated by its title")
        travelled = re.compile(r"ezexe asked|ezexe's (?:words|message)|routed from|relayed by|from ezexe|"
                               r"words quoted", re.I)
        self.assertIsNone(travelled.search(brief), brief)
        self.assertIsNone(travelled.search(call["background"]), call["background"])
        self.assertIn("restate", ctx, "the session that makes the call is told to state the task in its own words")

    def test_no_line_handed_to_a_session_tells_it_to_quote_a_prompt(self):
        """Every road that tells a session to pass work on asks for the task restated as its own instruction."""
        t = self.t
        said = [context(t.say(host, words, P4_PHI_NEW_TASK="1")) for host, words in (
            (TOP, TASK), (TOP, "also, what colour should the fence be?"),
            (KID, handed("Port the flush to the new writer. Archive when done.")), (KID, "and what about the fence?"),
            (KID, "Add a dark mode toggle to the billing dashboard's settings page"))]
        asks = re.compile(r"words,? quoted|quoted words|holding ezexe's words|built from ezexe's words|"
                          r"ezexe's words:", re.I)
        for text in said:
            self.assertIsNone(asks.search(text), text)
        self.assertIn(phi.RESTATE, said[0], "an orchestrator's new topic")
        self.assertIn(phi.RESTATE, said[2], "a worker's new topic, handed up")
        self.assertIn(phi.RESTATE, said[3])
        import ast
        for name in ("phi.py", "controls.py", "puppeteer.py", "issues.py"):
            tree = ast.parse(read(os.path.join(HERE, name)))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                    self.assertIsNone(asks.search(n.value), f"{name}:{n.lineno} {n.value[:120]}")

    def test_a_draft_whose_writer_is_busy_is_queued_behind_it(self):
        t = self.t
        t.record(TOP2, title="the docs top")
        t.say(TOP, TASK)
        t.say(TOP2, "Write the docs for the billing dashboard")
        t.say(KID, handed("Port `src/export/flush.py` to the new writer."))     # in a turn: a running writer
        ctx = context(t.say(TOP, "Rename the retry helper in `src/export/flush.py` and update its callers"))
        self.assertIn(f"\"the flush port\" `{KID}` holds its files", ctx)
        did = puppeteer.DRAFT_RE.search(ctx.replace("draft drf-", "phi draft drf-").replace(";", " for x.")).group(1)
        self.assertIn(f"pioneer {did}`", ctx)
        r = t.cli(TOP, "pioneer", did)
        self.assertIn("queued as start request req-", r.stdout + r.stderr)
        self.assertEqual([x["after"] for x in starts.state(t.p4).values()], [KID])
        self.assertNotIn("start requests", context(t.say(TOP, "How is the exporter coming along?")),
                         "not handed out while the writer is busy")
        text, _ = self.ledger()
        self.assertIn(f"waits behind \"the flush port\" `{KID}`", text)
        t.stop(KID, "Port the flush", report="Ported.")
        self.assertNotIn("start requests", context(t.say(TOP2, "And how are the docs now?")),
                         "never handed to a session that did not file it")
        line = context(t.say(TOP, "And how is the exporter now?"))
        self.assertIn("start requests this session filed", line)
        self.assertIn("Rename the retry helper", call_in(line)["prompt"])


class WorkerSplit(Base):
    """A worker splits at its first message, while the app still lets it start sessions: a part that writes files
    or decides runs in a session of its own, and a subagent that wrote files is a level miss on the ledger."""

    def plan(self, host, inp):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def recall(self, host, name, body):
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), name],
                       input=json.dumps({"session_id": CLI[host], "cwd": self.t.proj, **body}), capture_output=True,
                       text=True, timeout=60, env=self.t.env(host, P4_RECALL_SYNC="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_a_workers_first_message_is_told_to_start_its_writing_parts_now(self):
        t = self.t
        t.say(TOP, TASK)
        first = context(t.say(KID, handed("Port the flush to the new writer and document it. Report when done.")))
        self.assertIn("Plan its split now", first)
        self.assertIn("In these sessions the app has let a started session start others in its first turn", first,
                      "what the app has shown, not a documented rule")
        self.assertIn("where the app refuses that start, the part is shown as a suggested task card", first)
        self.assertIn("one per disjoint set of files", first)
        self.assertIn("Subagents keep reads, searches, single command runs and independent checks", first)
        self.assertIn("is shown as a suggested task card", first, "a writing part that comes up later is a card")
        self.assertIn("only where the card is refused too is it kept as a start request", first)
        t.stop(KID, "Port the flush", report="half way")
        self.assertNotIn("Plan its split now", context(t.say(KID, "carry on")), "said at the first message only")
        self.assertNotIn("Plan its split now", context(t.say(TOP, "and the exporter?")), "never to an orchestrator")

    def test_a_step_that_edits_files_is_named_for_a_session_and_a_read_for_a_subagent(self):
        t = self.t
        p = t.proj
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush and its docs. Report when done."))
        ctx = self.plan(KID, {"items": [
            {"content": f"Edit {p}/src/export/flush.py to write through the new writer", "status": "in_progress"},
            {"content": f"Rewrite the flush page in {p}/docs/flush.md with the new calls", "status": "pending"},
            {"content": f"Find every caller of {p}/src/export/legacy.py across the exporter", "status": "pending"}],
            "scope": "first_task"})
        sessions = ctx.split("can each run on their own")[0]
        self.assertIn("\"Edit ", sessions)
        self.assertIn("\"Rewrite the flush page", sessions)
        self.assertNotIn("Find every caller", sessions, "a read is no session of its own")
        self.assertIn("`p4-phi:sweep`", ctx.split("can each run on their own")[1])

    def test_a_subagent_that_wrote_files_is_a_level_miss_on_the_ledger(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer. Report when done."))
        self.plan(KID, {"items": [{"content": "Port the flush", "status": "in_progress"}], "scope": "first_task"})
        self.recall(KID, "agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_l1",
                                   "tool_input": {"prompt": "port the flush", "description": "port"}})
        self.recall(KID, "lookup-record", {"hook_event_name": "PostToolUse", "tool_name": "Read", "agent_id": "agw01",
                                           "tool_input": {"file_path": "src/export/flush.py"},
                                           "tool_use_id": "toolu_s1", "tool_response": "ok"})
        path = os.path.join(t.tmp, "agent-agw01.jsonl")
        transcript(path, "port the flush", [("Write", {"file_path": "src/export/flush.py", "content": "x"}, "ok")],
                   "ported")
        self.recall(KID, "subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": "agw01",
                                           "agent_type": "general-purpose", "agent_transcript_path": path,
                                           "last_assistant_message": "ported"})
        text, _ = self.ledger()
        self.assertIn("## Level misses", text)
        miss = text.split("## Level misses")[1]
        self.assertIn("agw01", miss)
        self.assertIn("src/export/flush.py", miss)
        self.assertIn("the flush port", miss)


class TermsAndGuides(Base):
    """A session about to create something finds its documented terms and an implementation guide first, logs both
    with their sources in its decisions file, and builds by them."""

    plan = WorkerSplit.plan

    def test_a_writing_workers_first_message_carries_the_research_line(self):
        t = self.t
        t.say(TOP, TASK)
        first = context(t.say(KID, handed("Add a retry module for the flush writer.\nFiles: src/export/retry.py\n"
                                           "Report when done.")))
        self.assertIn("documented terms", first)
        self.assertIn(phi.RESEARCH, first)
        t.stop(KID, "Add a retry module", report="half way")
        self.assertNotIn(phi.RESEARCH, context(t.say(KID, "carry on")), "said at the first message only")
        t.record(KID2, TOP, title="the exporter check")
        checker = context(t.say(KID2, handed("Check that the exporter's tests pass and report.\nFiles: none")))
        self.assertNotIn(phi.RESEARCH, checker, "a read-only worker creates nothing")

    def test_a_start_draft_carries_the_research_step(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        brief = call_in(context(t.say(TOP, RETRY)))["prompt"]
        self.assertIn("documented terms", brief)
        self.assertIn(phi.RESEARCH, brief)

    def test_a_plan_with_no_research_step_before_its_first_creating_step_is_advised_one(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Add a retry module for the flush writer. Report when done."))
        ctx = self.plan(KID, {"items": [
            {"content": "Create the retry module src/export/retry.py", "status": "in_progress"},
            {"content": "Wire the retry into the flush writer", "status": "pending"}], "scope": "first_task"})
        self.assertIn("documented terms", ctx)
        self.assertIn(phi.RESEARCH_STEP_HEAD, ctx)
        self.assertIn("\"Create the retry module", ctx.split(phi.RESEARCH_STEP_HEAD)[1])
        t.record(KID2, TOP, title="the retry module")
        t.say(KID2, handed("Add a retry module for the flush writer. Report when done."))
        ok = self.plan(KID2, {"items": [
            {"content": "Find the documented terms and an implementation guide for a retry module",
             "status": "in_progress"},
            {"content": "Create the retry module src/export/retry.py", "status": "pending"}], "scope": "first_task"})
        self.assertNotIn(phi.RESEARCH_STEP_HEAD, ok, "a plan that researches first is advised nothing")


class WatcherLeft(unittest.TestCase):
    """A test that starts a real watcher ends it, whether the test passes or fails midway."""

    def test_a_watcher_test_made_to_fail_midway_leaves_no_watcher_running(self):
        pids = []

        def midway(case, *args, **kw):
            pids.append(jload(case.path(TOP, "watcher.json")).get("pid", -1))
            raise AssertionError("made to fail midway, once its watcher runs")

        def kill_left():
            for pid in pids:
                if issues._alive(pid):
                    os.kill(pid, signal.SIGTERM)
        self.addCleanup(kill_left)
        kept = []
        case = Linear("test_one_background_watcher_an_orchestrator_started_by_a_hook_and_ended_with_it")
        result = unittest.TestResult()
        # the fixture folder outlives the test, as it does when Windows refuses to delete a folder a live process
        # writes into, so only the test's own cleanup can end the watcher
        with mock.patch.object(Linear, "assertIn", midway), \
                mock.patch.object(tempfile.TemporaryDirectory, "cleanup", lambda d: kept.append(d)):
            case.run(result)
        self.addCleanup(lambda: [d.cleanup() for d in kept])
        if result.skipped:
            self.skipTest(result.skipped[0][1])
        self.assertEqual((len(result.failures), result.errors), (1, []), result.failures)
        self.assertGreater(pids[0], 0, "the watcher ran when the test failed")
        end = time.time() + 5
        while time.time() < end and issues._alive(pids[0]):
            time.sleep(0.2)
        self.assertFalse(issues._alive(pids[0]), "no `phi.py watch` outlives the test that started it")


class Recursive(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git") or not shutil.which("sh"):
            self.skipTest("no git or sh")
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self._tmp.name
        self.ghdir = os.path.join(tmp, "gh")
        os.makedirs(self.ghdir)
        os.environ["FAKE_GH_DIR"] = self.ghdir
        write(os.path.join(self.ghdir, "gh.py"), FAKE_GH)
        self.t = t = GhTree(tmp, os.path.join(self.ghdir, "gh.py"))
        t.record(TOP, title="the exporter top")
        t.record(TOP2, title="the next top")
        t.record(KID, TOP, title="the x fix")
        self.work = os.path.join(t.proj, "work").replace("\\", "/")
        self.bare = os.path.join(tmp, "bare.git").replace("\\", "/")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        subprocess.run(["git", "init", "-q", "--bare", self.bare], check=True, capture_output=True)
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "one")):
            self.git(*args)
        self.git("remote", "add", "origin", "https://github.com/ezexe/demo.git")
        self.git("remote", "set-url", "--push", "origin", self.bare)

    def tearDown(self):
        os.environ.pop("FAKE_GH_DIR", None)
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              check=True, capture_output=True, text=True)

    def state(self, **states):
        write(os.path.join(self.ghdir, "state.json"), json.dumps(states))

    def why(self):
        r = self.t.cli(TOP, "routes", "--register", "--why", KID)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_a_route_is_registered_only_once_the_records_back_it_then_drafted_from_and_withdrawn(self):
        t = self.t
        t.say(TOP, "Fix the narwhal exporter so its flush keeps the last row of the ports table")
        ctx = context(t.say(KID, handed(f"Fix the off-by-one in {self.work}/lib/x.py and commit it, for "
                                        f"ezexe/demo#7. Archive when done.")))
        self.assertIn("ezexe/demo#7, https://github.com/ezexe/demo/issues/7, named in its brief", ctx)
        write(os.path.join(self.work, "lib", "x.py"), "x = 2\n")
        self.git("commit", "-qam", "x: keep the last row\n\nCloses #7")
        routes = os.path.join(t.dir(TOP), "routes.jsonl")
        self.assertIn("the session is not archived", self.why())
        s = t.session(KID)
        s["archived"] = True
        write(os.path.join(t.dir(KID), "session.json"), json.dumps(s))
        self.assertIn("its outcome is not kept", self.why())
        self.assertEqual(t.cli(TOP, "note", f"replaces: \"the x fix\" ({KID}) as a live session: it fixed the "
                               f"off-by-one.", "--source", "its report").returncode, 0)
        self.assertIn("ezexe/demo#7 is open, not closed", self.why())
        self.state(**{"7": "CLOSED"})
        self.assertIn("no pushed commit closes ezexe/demo#7", self.why())
        self.assertFalse(os.path.exists(routes), "nothing is registered while a record is missing")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", self.bare, "main:refs/remotes/origin/main")
        out = self.why()
        self.assertIn("registered rt-", out)
        self.assertIn("backed, by commit", out)
        row = [json.loads(x) for x in read(routes).splitlines()][0]
        self.assertEqual((row["issue"], row["context"], row["session"]), ("ezexe/demo#7", "fresh", KID))
        self.assertIn("narwhal exporter", row["words"], "the request's words are the orchestrator's task")
        self.assertIn("Fix the off-by-one", row["slice"]["brief"])
        self.assertEqual(self.why().count("registered rt-"), 0, "once")
        s = t.session(TOP)
        s["archived"] = True                       # the topic landed, so its orchestrator was archived too
        write(os.path.join(t.dir(TOP), "session.json"), json.dumps(s))
        t.say(TOP2, "Look after the billing dashboard")
        t.stop(TOP2, "Look after the billing dashboard", report="ok")
        ctx = context(t.say(TOP2, "Fix the narwhal exporter flush again: it drops the last row of the ports table"))
        self.assertIn(f"closely matches the registered route \"{row['id']}\"", ctx)
        brief = call_in(ctx)["prompt"]
        self.assertIn("A route that landed before fits this task: \"the x fix\", ezexe/demo#7, a fresh session", brief)
        self.assertNotIn("Fix the off-by-one", brief, "no earlier brief is quoted")
        self.assertNotIn("route that landed", context(t.say(TOP2, "Add a dark theme to the billing dashboard's "
                                                                  "settings page")), "no match: a fresh draft")
        self.state(**{"7": "OPEN"})
        self.assertIn(f"withdrawn {row['id']}: ezexe/demo#7 was reopened", self.why())
        self.assertEqual(puppeteer.all_routes(t.p4), {})


class AtArchive(Base):
    """The watcher, and the Stop hook of a session that archives itself, check a session at its archive for what it
    started and did not finish."""

    def setUp(self):
        super().setUp()
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        t.say(KID, handed("Port the flush to the new writer. Report when done."))

    def background(self, host, command, task_id):
        r = self.t.hook("task", host, {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                       "tool_input": {"command": command, "run_in_background": True},
                                       "tool_response": f"Command running in background with ID: {task_id}."})
        self.assertEqual(r.returncode, 0, r.stderr)

    def finish(self, host=KID):
        self.assertEqual(self.t.cli(host, "done", "the flush suite ran and passed").returncode, 0)
        self.assertEqual(self.t.stop(host, "port it", report="Ported; the suite passes.").returncode, 0)
        self.assertTrue(self.t.session(host).get("doneRetired"))

    def test_a_session_archived_with_a_background_task_running_leaves_a_row_and_its_parent_is_told_once(self):
        self.background(KID, "sh run-suites.sh", "bg12345678")
        self.finish()
        left = self.t.session(KID)["unfinishedAtArchive"]["items"]
        self.assertTrue(any("background task bg12345678" in x and "no end recorded" in x for x in left), left)
        page = self.ledger()[0]
        self.assertIn("## Unfinished at archive", page)
        self.assertLess(page.index("## Unfinished at archive"), page.index("## Reconcile"), "at the head of the page")
        self.assertIn("background task bg12345678", page)
        ctx = context(self.t.say(TOP, "And?"))
        self.assertIn("was archived with 1 thing unfinished", ctx)
        self.assertIn("bg12345678", ctx)
        self.assertNotIn("bg12345678", context(self.t.say(TOP, "And then?")), "told once")
        r = self.t.cli(TOP, "settle", KID, "the suite run was stopped by hand")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Unfinished at archive", self.ledger()[0], "settled: its row leaves the ledger")

    def test_a_session_archived_clean_leaves_no_row(self):
        self.finish()
        s = self.t.session(KID)
        self.assertTrue(s.get("archiveChecked"))
        self.assertNotIn("unfinishedAtArchive", s)
        self.assertNotIn("Unfinished at archive", self.ledger()[0])
        self.assertNotIn("unfinished", context(self.t.say(TOP, "And?")))

    def test_a_second_start_of_a_running_command_is_held_then_flagged_with_the_first_copys_id(self):
        self.background(KID, "sh run-suites.sh", "bg11111111")
        call = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": "sh  run-suites.sh", "run_in_background": True}}
        out = json.loads(self.t.hook("restart-check", KID, dict(call, tool_use_id="tu1")).stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("still running in the background as bg11111111", out["permissionDecisionReason"])
        self.assertEqual(self.t.hook("restart-check", KID, dict(call, tool_use_id="tu2")).stdout.strip(), "",
                         "told once for that copy: the next start goes through")
        other = dict(call, tool_input={"command": "sh other.sh", "run_in_background": True}, tool_use_id="tu3")
        self.assertEqual(self.t.hook("restart-check", KID, other).stdout.strip(), "", "another command is no restart")
        self.background(KID, "sh run-suites.sh", "bg22222222")
        tasks = [t for _, t in puppeteer.plans._tasks(puppeteer.plans.load(self.t.p4, KID))]
        self.assertEqual(tasks[-1].get("repeatOf"), "bg11111111")
        left = puppeteer.unfinished(self.t.p4, KID, procs=False)
        self.assertTrue(any("started 2 times" in x and "while bg11111111 was still running" in x for x in left), left)

    def test_processes_it_left_and_requests_nobody_started_are_named(self):
        puppeteer.PROCESSES = lambda: [(4242, f"python phi.py watch --p4 {self.t.p4} --session {KID}"),
                                       (4343, f"python phi.py watch --p4 /another/store --session {KID}"),
                                       (7, "python other.py")]
        try:
            starts.add(self.t.p4, KID, "A follow-up nobody starts", "Do the follow-up in the exporter.")
            left = puppeteer.unfinished(self.t.p4, KID)
        finally:
            puppeteer.PROCESSES = None
        self.assertTrue(any(x.startswith("process 4242 it started is still alive") for x in left), left)
        self.assertFalse(any("process 7 " in x for x in left))
        self.assertFalse(any("process 4343 " in x for x in left), "the same session id in another store is not its")
        self.assertTrue(any("that it queued was never started" in x for x in left), left)

    def test_a_self_archive_names_the_live_background_task_that_holds_it(self):
        self.background(KID, "sh run-suites.sh", "bg33333333")
        r = self.t.hook("self-archive", KID, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                              "tool_input": {"session_id": "self"}})
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("bg33333333", out["permissionDecisionReason"])


class Scorers(Base):
    """Routing's route and code owner picks go through the trained ranker when the store keeps a model, and through
    shared content words, at the measured threshold, when it keeps none."""

    COMMON = ("exporter table rows store writer flush ports check suite build layout index cache hook plan step "
              "report branch commit").split()

    def cases(self):
        """A labelled history where the right candidate shares the message's two rare words and the wrong ones
        share many of its common words: what shared content words cannot tell apart."""
        import random
        rng = random.Random(41)
        out = []
        for k in range(40):
            rare = [f"zeta{k}a", f"zeta{k}b"]
            said = rng.sample(self.COMMON, 9)
            right = " ".join(rng.sample([w for w in self.COMMON if w not in said], 6) + rare)
            wrong = [" ".join(rng.sample(said, 7) + [f"omega{k}{j}"]) for j in range(3)]
            cands = [(f"wrong{j}", w) for j, w in enumerate(wrong)] + [("right", right)]
            rng.shuffle(cands)
            out.append({"message": " ".join(said + rare), "time": "", "session": f"s{k % 8}", "label": "right",
                        "kind": "doer", "case": "doer", "cands": cands})
            out.append({"message": " ".join(said + [f"lone{k}"]), "time": "", "session": f"s{k % 8}", "label": "",
                        "kind": "here", "case": "others", "cands": [c for c in cands if c[0] != "right"]})
        return out

    def routes(self):
        rows = [{"kind": "route", "id": "rt-right", "session": KID, "issue": "ezexe/demo#7", "context": "fresh",
                 "topic": "Quarantine the narwhal ledger",
                 "words": "quarantine the narwhal ledger when its checksum drifts"},
                {"kind": "route", "id": "rt-wrong", "session": KID2, "issue": "ezexe/demo#8", "context": "fresh",
                 "topic": "Port the exporter flush",
                 "words": "port the exporter flush to the new writer and run the ports table suite on the store"}]
        for k, (topic, words_) in enumerate(self.OTHERS):   # a store's other routes: its common words are common
            rows.append({"kind": "route", "id": f"rt-other{k}", "session": f"local_other{k}", "issue": "",
                         "context": "fresh", "topic": topic, "words": words_})
        write(self.path(TOP, "routes.jsonl"), "".join(json.dumps(r) + "\n" for r in rows))

    OTHERS = (("Move the table writer", "move the exporter table writer onto the store index and build the ports cache"),
              ("Check the flush hook", "check the exporter flush hook and the ports table layout in the store"),
              ("Run the suite", "run the exporter suite on every branch commit and report the ports table rows"))
    MESSAGE = ("Run the exporter flush suite on the store after the ports table writer moves, then quarantine the "
               "narwhal ledger")

    def test_a_trained_route_model_picks_the_route_shared_content_words_get_wrong(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        self.routes()
        by_words = puppeteer.score_routes(t.p4, self.MESSAGE)
        self.assertEqual([r["id"] for _, _, r in by_words][:1], ["rt-wrong"],
                         "shared content words pick the route that shares the most words")
        model = prompty_eval.train(self.cases())
        self.assertTrue(model and model["w"])
        prompty_eval.keep(t.p4, "routes", model, {"cases": 80})
        by_model = puppeteer.score_routes(t.p4, self.MESSAGE)
        self.assertEqual([r["id"] for _, _, r in by_model][:1], ["rt-right"],
                         "the trained scorer picks the route that shares the message's rare words")

    def test_with_no_model_shared_content_words_are_the_fallback_at_the_measured_threshold(self):
        t = self.t
        t.say(TOP, TASK)
        self.routes()
        self.assertEqual(puppeteer.prompty_model(t.p4), {})
        self.assertIsNone(puppeteer.rank_texts(t.p4, "owners", self.MESSAGE, ["a task", "another task"]))
        self.assertIsNone(puppeteer.rank_texts(t.p4, "routes", self.MESSAGE, ["a route"]))
        got = puppeteer.score_routes(t.p4, self.MESSAGE)
        n, part = puppeteer.share(self.MESSAGE, "port the exporter flush to the new writer and run the ports table "
                                                "suite on the store Port the exporter flush")
        self.assertEqual((got[0][2]["id"], got[0][1], got[0][0]), ("rt-wrong", n, round(part, 2)), "its own score")
        self.assertEqual(puppeteer.OWNER_WORDS, 8, "the code owner threshold with no trained model")
        self.assertEqual((puppeteer.ROUTE_MIN, puppeteer.ROUTE_CLOSE), (4, 0.6), "the route thresholds with no "
                         "trained model")
        write(puppeteer.scorer_path(t.p4), "not json")
        self.assertEqual(puppeteer.prompty_model(t.p4), {}, "an unreadable model is no model")
        self.assertEqual(puppeteer.score_routes(t.p4, self.MESSAGE)[0][2]["id"], "rt-wrong")

    def test_an_owner_is_named_by_the_trained_model_and_not_by_four_shared_words(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        t.record(KID2, TOP, title="the ledger keeper")
        t.say(KID, handed("Port the exporter flush to the new writer and run the ports table suite on the store."))
        t.say(KID2, handed("Quarantine the narwhal ledger when its checksum drifts."))
        for kid in (KID, KID2):
            t.stop(kid, "work", report="half way")
        for k, (topic, words_) in enumerate(self.OTHERS):   # the other live sessions of the tree
            write(os.path.join(t.dir(f"local_other{k}"), "session.json"), json.dumps({
                "sessionId": f"local_other{k}", "title": topic, "task": words_, "spawnedFrom": {"sessionId": TOP},
                "createdAt": "2026-11-16 08:00"}))
        s = t.session(TOP)
        read = puppeteer.prompty(t.p4, s, self.MESSAGE, t.proj)
        self.assertIsNone(read["owner"], "six shared words, fewer than OWNER_WORDS, name no code owner")
        self.assertGreaterEqual(puppeteer.share(self.MESSAGE, t.session(KID)["task"])[0], 4)
        prompty_eval.keep(t.p4, "owners", prompty_eval.train(self.cases()), {"cases": 80})
        read = puppeteer.prompty(t.p4, s, self.MESSAGE, t.proj)
        self.assertEqual((read["owner"] or {}).get("sessionId"), KID2)
        self.assertIn("the trained owner model scores its task", read["owner"]["why"])

    def test_the_measurement_reads_a_stores_history_and_writes_nothing(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        t.say(TOP, "Add a retry to the narwhal exporter for when the ports table write fails in the store")
        t.stop(TOP, "Add a retry to the narwhal exporter for when the ports table write fails in the store",
               report="done", uuid="u1")
        t.say(KID, handed("Port the flush to the new writer."))
        t.stop(KID, "Port the flush", report="half way")
        before = sorted(os.listdir(os.path.join(t.p4, "phi")))
        exs = prompty_eval.examples(t.p4)
        self.assertTrue(any(e["case"] == "others" and e["session"] == TOP for e in exs), exs)
        res = prompty_eval.measure(exs)
        self.assertIn("ranker", res)
        self.assertEqual(sorted(os.listdir(os.path.join(t.p4, "phi"))), before)
        self.assertFalse(os.path.exists(puppeteer.scorer_path(t.p4)))

    def test_a_relay_that_restates_the_task_is_labelled_by_the_route_p4_phi_kept(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        t.say(TOP, RETRY + " in the store")
        did = "drf-0123456789"
        # the route the gate kept for the message: its owner is the live session that took it
        write(os.path.join(puppeteer.drafts_dir(t.p4, TOP), f"{did}.json"),
              json.dumps({"id": did, "words": RETRY + " in the store", "verdict": "route", "drafter": TOP,
                          "owner": {"sessionId": KID, "title": "the flush port"}}))
        t.stop(TOP, RETRY + " in the store", report="Sent it on: \"the flush port\" has it.", uuid="u1")
        restated = ("<cross-session-message from=\"" + TOP + "\">Give the exporter a second attempt whenever "
                    "saving rows fails, then report.</cross-session-message>")
        self.assertFalse(prompty_eval.quotes(restated, RETRY + " in the store"))
        t.say(KID, restated)
        t.stop(KID, "Give the exporter a second attempt", report="done", uuid="u2")
        got = [e for e in prompty_eval.examples(t.p4) if e["case"] == "others" and e["session"] == TOP
               and "retry" in e["message"]]
        self.assertEqual([(e["label"], e["kind"]) for e in got], [(KID, "relayed")], got)


    def test_a_route_draft_answered_here_stays_here(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        t.say(TOP, RETRY + " in the store")
        did = "drf-0123456789"
        write(os.path.join(puppeteer.drafts_dir(t.p4, TOP), f"{did}.json"),
              json.dumps({"id": did, "words": RETRY + " in the store", "verdict": "route", "drafter": TOP,
                          "owner": {"sessionId": KID, "title": "the flush port"}}))
        t.stop(TOP, RETRY + " in the store", report="Added the retry here, with its test.", uuid="u1")
        t.say(KID, handed("Port the flush to the new writer."))
        t.stop(KID, "Port the flush", report="done", uuid="u2")
        got = [(e["label"], e["kind"]) for e in prompty_eval.examples(t.p4)
               if e["case"] == "others" and e["session"] == TOP and "retry" in e["message"]]
        self.assertEqual(got, [("", "here")])

    def test_a_message_over_task_chars_kept_cut_still_gets_its_label(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        long = RETRY + " in the store, " + " ".join(f"then check table {k} of the ports writer" for k in range(60))
        self.assertGreater(len(long), phi.TASK_CHARS)
        t.say(TOP, long)
        t.stop(TOP, long, report="Sent it on: \"the flush port\" has it.", uuid="u1")
        kept = [u.get("prompt") for u in prompty_eval.turns_of(t.p4, TOP) if "retry" in str(u.get("prompt"))]
        self.assertTrue(kept and kept[0].endswith(" ..."), kept)
        did = "drf-0123456789"
        write(os.path.join(puppeteer.drafts_dir(t.p4, TOP), f"{did}.json"),
              json.dumps({"id": did, "words": long, "verdict": "route", "drafter": TOP,
                          "owner": {"sessionId": KID, "title": "the flush port"}}))
        t.say(KID, handed("Give the exporter a second attempt whenever saving rows fails."))
        t.stop(KID, "Give the exporter a second attempt", report="done", uuid="u2")
        got = [(e["label"], e["kind"]) for e in prompty_eval.examples(t.p4)
               if e["case"] == "others" and e["session"] == TOP and "retry" in e["message"]]
        self.assertEqual(got, [(KID, "relayed")])

class Parallel(Base):
    EITHER = ("Fix the narwhal exporter's flush: either buffer the rows in memory until the table closes or write "
              "each row straight to the store")

    def start(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        t.record(KID2, TOP, title="the other reading")
        ctx = context(t.say(TOP, self.EITHER))
        self.assertIn("under-determined, with 2 distinct readings", ctx)
        calls = [call_in(ctx, 0), call_in(ctx, 1)]
        self.assertIn("reading 1 of 2: buffer the rows in memory until the table closes", calls[0]["prompt"])
        self.assertIn("reading 2 of 2: write each row straight to the store", calls[1]["prompt"])
        self.assertIn("Result: <what this reading comes to>", calls[0]["prompt"])
        for kid, call in zip((KID, KID2), calls):
            t.say(kid, handed(call["prompt"]))
        gid = t.session(KID)["reading"]["group"]
        g = jload(os.path.join(t.dir(TOP), "readings", gid + ".json"))
        self.assertEqual([r["child"] for r in g["readings"]], [KID, KID2], "one child for each reading, siblings")
        self.assertEqual({t.started_by(KID)[0], t.started_by(KID2)[0]}, {TOP})
        return gid

    def test_readings_that_converge_collapse_to_one_result(self):
        t, gid = self.t, self.start()
        t.stop(KID, "reading 1", report="Tried it.\nResult: write each row straight to the store, a crash loses none")
        self.assertIn("results awaited", self.ledger()[0])
        t.stop(KID2, "reading 2", report="Done.\n\nResult: Write each row straight to the store, a crash loses none.")
        ctx = context(t.say(TOP, "And?"))
        self.assertIn("converged on one result", ctx)
        self.assertIn("put no question to ezexe", ctx)
        self.assertIn(f"{gid} ", self.ledger()[0])
        self.assertIn("2 readings converged", self.ledger()[0])

    def test_a_fork_that_survives_the_merge_is_one_question_with_a_default(self):
        t, gid = self.t, self.start()
        t.stop(KID, "reading 1", report="Result: buffering is faster by a third and loses rows on a crash")
        t.stop(KID2, "reading 2", report="Result: straight writes are slower and never lose a row")
        ctx = context(t.say(TOP, "And?"))
        self.assertIn("fork after the merge", ctx)
        self.assertIn("put one question to ezexe", ctx)
        self.assertIn("reading 1 as the default", ctx)
        self.assertEqual(ctx.count("Which reading of"), 1, "one question")
        r = t.cli(TOP, "merge", gid, "--result", "straight writes: losing a row is not acceptable")
        self.assertIn("converged on \"straight writes", r.stdout)

    def group(self, gid):
        return jload(os.path.join(self.t.dir(TOP), "readings", gid + ".json"))

    def archived_stop(self, kid):
        """A reading that archives itself with an empty report: its turn is kept as it goes."""
        path = transcript(os.path.join(self.t.tmp, kid + "arch.jsonl"), "reading", (), "", "arch")
        r = self.t.hook("stop", kid, {"hook_event_name": "Stop", "transcript_path": path,
                                      "last_assistant_message": "", "_atArchive": True})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_result_given_through_done_is_read(self):
        """Both readings answer with `phi.py done` and an empty report, and the merge reads the done texts."""
        t, gid = self.t, self.start()
        self.assertEqual(t.cli(KID, "done", "buffering was tried and it loses rows on a crash").returncode, 0)
        t.stop(KID, "reading 1", report="")
        self.assertEqual(self.group(gid)["state"], "open")
        self.assertEqual(t.cli(KID2, "done", "straight writes were tried and never lose a row").returncode, 0)
        t.stop(KID2, "reading 2", report="")
        g = self.group(gid)
        self.assertEqual(g["state"], "forked", "the merge took each reading's done text")
        self.assertEqual(g["readings"][0]["result"], "buffering was tried and it loses rows on a crash")
        self.assertIn("put one question to ezexe", context(t.say(TOP, "And?")))

    def test_a_result_line_wins_over_the_done_text(self):
        t, gid = self.t, self.start()
        t.cli(KID, "done", "ran the buffer test and it passed")
        t.stop(KID, "reading 1", report="Result: write each row straight to the store, a crash loses none")
        t.stop(KID2, "reading 2", report="Result: write each row straight to the store, a crash loses none")
        g = self.group(gid)
        self.assertEqual(g["state"], "collapsed")
        self.assertIn("straight to the store", g["result"])

    def test_a_reading_archived_with_no_result_is_lost_and_the_group_closes(self):
        """An archived reading with no result is lost, and its group closes on what the other readings gave."""
        t, gid = self.t, self.start()
        self.archived_stop(KID)
        self.assertEqual(self.group(gid)["state"], "open", "the other reading is still awaited")
        t.stop(KID2, "reading 2", report="Result: straight writes never lose a row")
        g = self.group(gid)
        self.assertEqual(g["state"], "collapsed", "it closes on what the other gave")
        self.assertEqual(g["lost"], [1])
        self.assertIn("reading 1 was archived with no result and is lost", self.ledger()[0])
        ctx = context(t.say(TOP, "And?"))
        self.assertIn("reading 1 was archived with no result and is lost", ctx)
        self.assertIn("straight writes never lose a row", ctx)

    def test_every_reading_lost_closes_the_group_and_says_so(self):
        t, gid = self.t, self.start()
        for kid in (KID, KID2):
            s = t.session(kid)
            s["archived"] = "2026-11-13 00:02"
            write(os.path.join(t.dir(kid), "session.json"), json.dumps(s))
        self.assertEqual(t.cli(TOP, "merge", gid).returncode, 0)
        g = self.group(gid)
        self.assertEqual(g["state"], "lost")
        self.assertIn("closed with no result: readings 1, 2 were archived with no result and are lost", self.ledger()[0])

    def test_a_rerun_session_replaces_the_earlier_child(self):
        """A second pair of sessions carrying the same reading lines takes the first pair's place in the group."""
        t, gid = self.t, self.start()
        self.archived_stop(KID)
        self.archived_stop(KID2)
        self.assertEqual(self.group(gid)["state"], "lost")
        for kid in ("local_kid00003", "local_kid00004"):
            CLI.setdefault(kid, kid.replace("local_kid", "ffff") + "-0000-4000-8000-000000000000")
            t.record(kid, TOP, title="a rerun")
        for kid, old in zip(("local_kid00003", "local_kid00004"), (KID, KID2)):
            brief = jload(os.path.join(t.dir(TOP), "drafts", t.session(old)["draft"] + ".json"))["brief"]
            t.say(kid, handed(brief))
        g = self.group(gid)
        self.assertEqual([r["child"] for r in g["readings"]], ["local_kid00003", "local_kid00004"])
        self.assertEqual([r["earlier"] for r in g["readings"]], [[KID], [KID2]])
        self.assertEqual(g["state"], "open", "open again for the rerun")
        t.stop("local_kid00003", "reading 1", report="Result: straight writes never lose a row")
        t.stop("local_kid00004", "reading 2", report="Result: straight writes never lose a row.")
        self.assertEqual(self.group(gid)["state"], "collapsed")

    def test_a_rerun_the_group_never_heard_of_is_found_at_the_merge(self):
        """The group names the first pair while the results are on a second pair it never recorded."""
        t, gid = self.t, self.start()
        self.archived_stop(KID)
        g = self.group(gid)
        for k, kid in enumerate(("local_kid00003", "local_kid00004"), 1):
            write(os.path.join(t.dir(kid), "session.json"), json.dumps({
                "sessionId": kid, "createdAt": "2026-11-13 00:0%d" % (5 + k), "spawnedFrom": {"sessionId": TOP},
                "archived": "2026-11-13 00:07", "reading": {"group": gid, "k": k, "n": 2, "parent": TOP}}))
            write(os.path.join(t.dir(kid), "turns.jsonl"), json.dumps({
                "id": "t1", "report": "", "atArchive": True,
                "done": "listed the folder: 61 sessions" if k == 1 else "phi.py tree printed 10 sessions"}) + "\n")
        self.assertEqual(t.cli(TOP, "merge", gid).returncode, 0)
        g = self.group(gid)
        self.assertEqual(g["state"], "forked")
        self.assertEqual([r["child"] for r in g["readings"]], ["local_kid00003", "local_kid00004"])
        self.assertEqual(g["readings"][0]["result"], "listed the folder: 61 sessions")

    def test_a_readings_title_ends_at_a_clause(self):
        """A reading's title ends at a clause, never in the middle of one at a word count."""
        t = self.t
        t.say(TOP, TASK)
        r = t.cli(TOP, "readings",
                  "count only the sessions that the command python -I phi.py tree prints, which leaves archived out",
                  "count every session folder under E:/projects/p4-phi/.claude/p4/phi/sessions, archived ones included",
                  "--words", "How many sessions does the store hold right now?")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"title": "Reading 1: count only the sessions"', r.stdout)
        self.assertIn('"title": "Reading 2: count every session folder"', r.stdout)

    def test_the_session_can_name_the_readings_itself_and_the_caps_still_hold(self):
        t = self.t
        t.say(TOP, TASK)
        r = t.cli(TOP, "readings", "keep the table in the store", "keep the table in a file beside it", "--words",
                  "Make the exporter keep its table somewhere safe")
        self.assertEqual(r.stdout.count("`mcp__ccd_session__start_session` with "), 2, r.stderr)
        call = call_in(r.stdout)
        self.assertTrue(call["title"].startswith("Reading 1: keep the table in the store"), call["title"])
        self.assertIn("change no tracked file and commit nothing", call["prompt"])
        did = puppeteer.DRAFT_RE.search(call["prompt"]).group(1)
        kept = t.cli(TOP, "pioneer", did, "--request")       # the app refused the start in a turn ezexe did not begin
        self.assertIn("kept as start request req-", kept.stdout)
        held = list(starts.state(t.p4).values())
        self.assertEqual([(x["requester"], x["title"]) for x in held], [(TOP, call["title"])])
        self.assertIn("phi reading grp-", held[0]["brief"])
        self.assertIn("message has two or more distinct readings", t.cli(TOP, "readings", "only one").stderr)


class Meta(Base):
    def test_a_top_sessions_message_runs_the_meta_pass_into_the_meta_ledger(self):
        t = self.t
        t.record(TOP2, title="the other exporter top")
        t.say(TOP, TASK)
        t.stop(TOP, TASK, calls=[("Edit", {"file_path": os.path.join(t.proj, "src", "export", "flush.py")}, "ok")],
               report="edited")
        t.say(TOP2, "Make the narwhal exporter write the ports table into the store once more")
        t.stop(TOP2, "x", calls=[("Edit", {"file_path": os.path.join(t.proj, "src", "export", "flush.py")}, "ok")],
               report="edited too", uuid="u1")
        ctx = context(t.say(TOP2, ASK))
        page = read(os.path.join(t.p4, "phi", "meta-ledger.md"))
        self.assertIn("the meta pass over every orchestrator's ledger", ctx)
        self.assertIn("carry one topic", ctx)
        self.assertIn(f"\"the exporter top\" `{TOP}` and \"the other exporter top\" `{TOP2}` carry one topic", page)
        self.assertIn("both changed or hold", page)
        self.assertIn("flush.py", page.split("## Conflicts between orchestrators")[1].split("##")[0])
        self.assertNotIn("the meta pass over every orchestrator's ledger", context(t.say(TOP2, ASK)),
                         "a finding is told once")
        before = os.stat(os.path.join(t.p4, "phi", "meta-ledger.md")).st_mtime_ns
        t.say(TOP2, ASK)
        self.assertEqual(os.stat(os.path.join(t.p4, "phi", "meta-ledger.md")).st_mtime_ns, before, "only on change")
        os.environ["P4_PHI_APP_SESSIONS"] = os.path.join(t.tmp, "app")
        try:
            text, found, _ = puppeteer.meta_pass(t.p4, at=time.time() + 3 * 86400)
        finally:
            os.environ.pop("P4_PHI_APP_SESSIONS", None)
        self.assertEqual(len(found["stale"]), 1, "the orchestrator inside a turn is at work, not stale")
        self.assertIn(f"`{TOP}` has not moved for 3.0 days", text)


class Writes(unittest.TestCase):
    def test_a_refused_replace_leaves_no_temp_file(self):
        """Windows refuses a replace while another process holds the file open, and no temp file is left behind."""
        import tempfile
        real = os.replace

        def refuse(a, b):
            raise PermissionError("held open")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".cache", "app-index.json")
            os.replace = refuse
            try:
                with self.assertRaises(OSError):
                    puppeteer._write(path, "{}")
            finally:
                os.replace = real
            self.assertEqual(os.listdir(os.path.dirname(path)), [])
            puppeteer._write(path, "{}")
            self.assertEqual(os.listdir(os.path.dirname(path)), ["app-index.json"])


if __name__ == "__main__":
    unittest.main()
