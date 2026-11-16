#!/usr/bin/env python3
"""puppeteer.py (#38): p4's four P's on the session tree, run through phi's own hooks and commands.

    python3 -I lbiza/plugins/p4-phi/scripts/test_puppeteer.py

Checked, one diagram of ezexe/p4's README.md a class:
linear: the ledger an orchestrator's watcher writes holds a row a live session of its subtree, is rewritten only when
a source changed, and leads with a reconcile line when the app archived a session phi lists or shows a child phi does
not hold; the watcher is one background process, started by a hook and ended when its orchestrator is archived; an
ezexe message that is work is drafted from ezexe's words and gate-checked into the exact start_session call, into a
SendMessage to the session whose shard holds its area, or into a start request queued behind the running writer that
holds its files, handed out only once that writer is idle; a question is left alone.
recursive: a landed topic registers its route only once its issue is closed, a commit closing it is pushed and its
session is archived with its outcome kept; a later message with matching words is drafted from that route; a route
whose issue was reopened is withdrawn.
parallel: an under-determined message becomes one child a reading; readings whose results agree collapse, and
readings that fork become one question with options and a default, which the puppeteer can settle itself.
meta: a top session's ezexe message runs the meta pass over every top's ledger into meta-ledger.md, with the
duplicate topic, the conflict over one file and the stale topic it finds.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import puppeteer  # noqa: E402
import starts  # noqa: E402
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


def call_in(ctx, k=0):
    """The k-th exact start_session input a hook's text carries."""
    piece = ctx.split("`mcp__ccd_session__start_session` with ")[k + 1]
    return json.JSONDecoder().raw_decode(piece)[0]


class Base(unittest.TestCase):
    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush port")

    def tearDown(self):
        self._tmp.cleanup()

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
        self.assertEqual(len(rows), 2, "the top and the one child phi holds: a row each")
        self.assertIn(f"({TOP}): working", rows[0])
        self.assertTrue(rows[1].startswith(f"  - \"the flush port\" ({KID}): working; no turn yet"), rows[1])
        before = os.stat(self.path(TOP, "ledger.md")).st_mtime_ns
        text2, said2 = self.ledger()
        self.assertIn("unchanged", said2)
        self.assertEqual((text2, os.stat(self.path(TOP, "ledger.md")).st_mtime_ns), (text, before))
        t.stop(KID, "Port the flush", report="Ported; the suite passes.")
        text3, said3 = self.ledger()
        self.assertIn("rewritten", said3)
        self.assertIn(f"({KID}): idle; 1 turn", text3)
        self.assertIn("reported \"Ported; the suite passes.\"", text3)
        self.assertTrue(os.path.exists(self.path(TOP, "ledger.json")))

    def test_a_divergence_between_phi_and_the_app_is_a_reconcile_line_at_the_top(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        rec = jload(os.path.join(t.app, KID + ".json"))
        rec["isArchived"] = True
        write(os.path.join(t.app, KID + ".json"), json.dumps(rec))
        t.record(GRAND, TOP, title="a child only the app knows")
        text, _ = self.ledger()
        head = text.split("## Sessions")[0]
        self.assertIn(f"phi lists \"the flush port\" ({KID}) as live, and the app has archived it.", head)
        self.assertIn(f"the app shows \"a child only the app knows\" ({GRAND}) started by {TOP}, and phi holds no "
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
        self.assertIn(f"({TOP})", read(self.path(TOP, "ledger.md")))
        beat = jload(self.path(TOP, "watcher.json"))
        self.assertLess(time.time() - beat["beat"], 20, "it says it is alive at every look, before the look")
        self.assertIn("slowestTickMs", beat)
        t.say(TOP, ASK, P4_PHI_WATCH="1", P4_PHI_WATCH_S="0.3", P4_PHI_WATCH_NET="0")
        self.assertEqual(len([x for x in t.log(TOP) if x.get("watcher")]), 1, "one watcher, not one a message")
        t.say(KID, handed("Port the flush to the new writer."))       # the watcher writes it in, no command run
        end = time.time() + 30
        while time.time() < end and f"({KID}): working" not in read(self.path(TOP, "ledger.md")):
            time.sleep(0.2)
        self.assertIn(f"({KID}): working", read(self.path(TOP, "ledger.md")))
        s = t.session(TOP)
        s["archived"] = True
        write(self.path(TOP, "session.json"), json.dumps(s))
        end = time.time() + 30
        while time.time() < end and os.path.exists(self.path(TOP, "watcher.json")):
            time.sleep(0.2)
        self.assertFalse(os.path.exists(self.path(TOP, "watcher.json")), "it ends when its orchestrator is archived")

    def test_a_ledger_is_built_without_git(self):
        # hook-started watchers on the real store spent their looks in git, one call a session a look, stopped
        # saying they were alive and were started again beside themselves: seven processes for four orchestrators
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
        self.assertNotIn("puppeteer", context(t.say(TOP, ASK)), "a question is no draft")
        ctx = context(t.say(TOP, RETRY))
        self.assertIn("prompty read this message", ctx)
        self.assertIn("no running writer holds its files", ctx)
        self.assertIn("its parent is this session", ctx)
        call = call_in(ctx)
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", False))
        self.assertIn("> " + RETRY, call["prompt"], "the brief is built from ezexe's words")
        self.assertIn("Report when done.", call["prompt"])
        self.assertGreaterEqual(len(call["background"]), 80)
        did = puppeteer.DRAFT_RE.search(call["prompt"]).group(1)
        self.assertIn(f"phi draft {did} for {TOP}.", call["prompt"])
        self.assertEqual(jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["verdict"], "start")
        t.say(KID, handed(call["prompt"]))
        self.assertEqual(t.session(KID)["draft"], did, "the child knows the draft it came from")
        other = context(t.say(TOP, "Write a changelog generator for the billing dashboard's release notes"))
        self.assertIn("a new top session in the root", other)
        self.assertIn(phi.NEW_TOP_BRIEF, call_in(other)["prompt"])

    def test_a_draft_whose_area_has_a_live_owner_is_routed_there(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        self.assertEqual(t.cli(KID, "shard", "src/export/**").returncode, 0)
        t.stop(KID, "Port the flush", report="half way")
        ctx = context(t.say(TOP, "Fix the off-by-one in `src/export/flush.py` that drops the last row"))
        self.assertIn(f"its area has a live owner, \"the flush port\" ({KID})", ctx)
        self.assertIn(f"Route it: SendMessage (`to`: {KID})", ctx)
        self.assertNotIn("`mcp__ccd_session__start_session` with {", ctx, "no session is started for it")

    def test_a_draft_whose_writer_is_busy_is_queued_behind_it(self):
        t = self.t
        t.record(TOP2, title="the docs top")
        t.say(TOP, TASK)
        t.say(TOP2, "Write the docs for the billing dashboard")
        t.say(KID, handed("Port `src/export/flush.py` to the new writer."))     # in a turn: a running writer
        ctx = context(t.say(TOP, "Rename the retry helper in `src/export/flush.py` and update its callers"))
        self.assertIn(f"\"the flush port\" ({KID}) holds its files", ctx)
        did = puppeteer.DRAFT_RE.search(ctx.replace("draft drf-", "phi draft drf-").replace(")", " for x.")).group(1)
        self.assertIn(f"pioneer {did}`", ctx)
        r = t.cli(TOP, "pioneer", did)
        self.assertIn("queued as start request req-", r.stdout + r.stderr)
        self.assertEqual([x["after"] for x in starts.state(t.p4).values()], [KID])
        self.assertNotIn("start requests", context(t.say(TOP, "How is the exporter coming along?")),
                         "not handed out while the writer is busy")
        text, _ = self.ledger()
        self.assertIn(f"waits behind \"the flush port\" ({KID})", text)
        t.stop(KID, "Port the flush", report="Ported.")
        self.assertNotIn("start requests", context(t.say(TOP2, "And how are the docs now?")),
                         "#58: never handed to a session that did not file it")
        line = context(t.say(TOP, "And how is the exporter now?"))
        self.assertIn("start requests this session filed", line)
        self.assertIn("Rename the retry helper", call_in(line)["prompt"])


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
        ctx = context(t.say(KID, handed(f"Fix the off-by-one in {self.work}/lib/x.py and commit it. Archive when "
                                        f"done.")))
        self.assertIn("ezexe/demo#7", ctx)
        write(os.path.join(self.work, "lib", "x.py"), "x = 2\n")
        self.git("commit", "-qam", "x: keep the last row\n\nCloses #7")
        routes = os.path.join(t.dir(TOP), "routes.jsonl")
        self.assertIn("the session is not archived", self.why())
        s = t.session(KID)
        s["archived"] = True
        write(os.path.join(t.dir(KID), "session.json"), json.dumps(s))
        self.assertIn("its outcome is not kept", self.why())
        self.assertEqual(t.cli(TOP, "note", f"replaces: \"the x fix\" ({KID}) as a live node: it fixed the "
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
        self.assertIn("narwhal exporter", row["words"], "the request's words are the top session's task")
        self.assertIn("Fix the off-by-one", row["slice"]["brief"])
        self.assertEqual(self.why().count("registered rt-"), 0, "once")
        s = t.session(TOP)
        s["archived"] = True                       # the topic landed, so its top session was archived too
        write(os.path.join(t.dir(TOP), "session.json"), json.dumps(s))
        t.say(TOP2, "Look after the billing dashboard")
        t.stop(TOP2, "Look after the billing dashboard", report="ok")
        ctx = context(t.say(TOP2, "Fix the narwhal exporter flush again: it drops the last row of the ports table"))
        self.assertIn(f"closely matches the registered route \"{row['id']}\"", ctx)
        brief = call_in(ctx)["prompt"]
        self.assertIn("A route that landed before fits these words: \"the x fix\", ezexe/demo#7, a fresh session", brief)
        self.assertIn("Its brief began: Fix the off-by-one", brief)
        self.assertNotIn("route that landed", context(t.say(TOP2, "Add a dark theme to the billing dashboard's "
                                                                  "settings page")), "no match: a fresh draft")
        self.state(**{"7": "OPEN"})
        self.assertIn(f"withdrawn {row['id']}: ezexe/demo#7 was reopened", self.why())
        self.assertEqual(puppeteer.all_routes(t.p4), {})


class AtArchive(Base):
    """#47: the puppeteer checks a session at its archive for what it started and did not finish."""

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

    def test_a_session_archived_with_a_task_running_leaves_a_row_and_its_puppeteer_is_told_once(self):
        self.background(KID, "sh run-suites.sh", "bg12345678")
        self.finish()
        left = self.t.session(KID)["unfinishedAtArchive"]["items"]
        self.assertTrue(any("background task bg12345678" in x and "no end recorded" in x for x in left), left)
        page = self.ledger()[0]
        self.assertIn("## Unfinished at archive", page)
        self.assertLess(page.index("## Unfinished at archive"), page.index("## Reconcile"), "at the top")
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
        puppeteer.PROCESSES = lambda: [(4242, f"python phi.py watch --p4 x --session {KID}"), (7, "python other.py")]
        try:
            starts.add(self.t.p4, KID, "A follow-up nobody starts", "Do the follow-up in the exporter.")
            left = puppeteer.unfinished(self.t.p4, KID)
        finally:
            puppeteer.PROCESSES = None
        self.assertTrue(any(x.startswith("process 4242 it started is still alive") for x in left), left)
        self.assertFalse(any("process 7 " in x for x in left))
        self.assertTrue(any("that it queued was never started" in x for x in left), left)

    def test_a_self_archive_names_the_live_task_that_holds_it(self):
        self.background(KID, "sh run-suites.sh", "bg33333333")
        r = self.t.hook("self-archive", KID, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session_mgmt__archive_session",
                                              "tool_input": {"session_id": "self"}})
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("bg33333333", out["permissionDecisionReason"])


class Scorers(Base):
    """#41: prompty's route and owner picks go through the trained ranker when the store keeps a model, and through
    word overlap, at the measured threshold, when it keeps none."""

    COMMON = ("exporter table rows store writer flush ports check suite build layout index cache hook plan step "
              "report branch commit").split()

    def cases(self):
        """A labelled history where the right candidate shares the message's two rare words and the wrong ones
        share many of its common words: what word overlap cannot tell apart."""
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

    def test_a_trained_route_model_picks_the_route_word_overlap_gets_wrong(self):
        import prompty_eval
        t = self.t
        t.say(TOP, TASK)
        self.routes()
        by_words = puppeteer.score_routes(t.p4, self.MESSAGE)
        self.assertEqual([r["id"] for _, _, r in by_words][:1], ["rt-wrong"],
                         "word overlap picks the route that shares the most words")
        model = prompty_eval.train(self.cases())
        self.assertTrue(model and model["w"])
        prompty_eval.keep(t.p4, "routes", model, {"cases": 80})
        by_model = puppeteer.score_routes(t.p4, self.MESSAGE)
        self.assertEqual([r["id"] for _, _, r in by_model][:1], ["rt-right"],
                         "the trained scorer picks the route that shares the message's rare words")

    def test_with_no_model_word_overlap_is_the_fallback_at_the_measured_threshold(self):
        t = self.t
        t.say(TOP, TASK)
        self.routes()
        self.assertEqual(puppeteer.prompty_model(t.p4), {})
        self.assertIsNone(puppeteer.rank_texts(t.p4, "owners", self.MESSAGE, ["a task", "another task"]))
        self.assertIsNone(puppeteer.rank_texts(t.p4, "routes", self.MESSAGE, ["a route"]))
        got = puppeteer.score_routes(t.p4, self.MESSAGE)
        n, part = puppeteer.share(self.MESSAGE, "port the exporter flush to the new writer and run the ports table "
                                                "suite on the store Port the exporter flush")
        self.assertEqual((got[0][2]["id"], got[0][1], got[0][0]), ("rt-wrong", n, round(part, 2)), "overlap's own score")
        self.assertEqual(puppeteer.OWNER_WORDS, 8, "the measured threshold of .docs/p4/phi-prompty-scores.md")
        self.assertEqual((puppeteer.ROUTE_MIN, puppeteer.ROUTE_CLOSE), (4, 0.6), "routes stay as they were: one "
                         "registered route is too few to measure")
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
        self.assertIsNone(read["owner"], "six shared words name no owner now: at four they named the flush port")
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
        self.assertEqual([r["child"] for r in g["readings"]], [KID, KID2], "one child a reading, siblings")
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
        """#44: both readings of the live proof answered with `phi.py done` and an empty report."""
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
        """#44: an archived reading with no result left its group open for ever."""
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
        """#44: the second pair of sessions carried the same reading line and the group still named the first."""
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
        """#44: grp-2e785dbf03 as it stands: the group names the first pair, the results are on the second."""
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
        """#44: "Reading 2: count only the sessions that the command" was cut at a word count."""
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
        self.assertIn("meta-puppeteer", ctx)
        self.assertIn("carry one topic", ctx)
        self.assertIn(f"\"the exporter top\" ({TOP}) and \"the other exporter top\" ({TOP2}) carry one topic", page)
        self.assertIn("both changed or hold", page)
        self.assertIn("flush.py", page.split("## Conflicts between top sessions")[1].split("##")[0])
        self.assertNotIn("meta-puppeteer", context(t.say(TOP2, ASK)), "a finding is told once")
        before = os.stat(os.path.join(t.p4, "phi", "meta-ledger.md")).st_mtime_ns
        t.say(TOP2, ASK)
        self.assertEqual(os.stat(os.path.join(t.p4, "phi", "meta-ledger.md")).st_mtime_ns, before, "only on change")
        os.environ["P4_PHI_APP_SESSIONS"] = os.path.join(t.tmp, "app")
        try:
            text, found, _ = puppeteer.meta_pass(t.p4, at=time.time() + 3 * 86400)
        finally:
            os.environ.pop("P4_PHI_APP_SESSIONS", None)
        self.assertEqual(len(found["stale"]), 1, "the top inside a turn is at work, not stale")
        self.assertIn(f"({TOP}) has not moved for 3.0 days", text)


class Writes(unittest.TestCase):
    def test_a_refused_replace_leaves_no_temp_file(self):
        """The review of #57, item 9: Windows refuses a replace while another process holds the file open."""
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
