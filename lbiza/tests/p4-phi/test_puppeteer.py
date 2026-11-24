#!/usr/bin/env python3
"""puppeteer.py: routing, the start draft, the gate and the watcher, run through p4-phi's own hooks and commands.

    python -m pytest tests/p4-phi/test_puppeteer.py

Checked, one diagram of ezexe/p4's README.md a class:
linear: the ledger an orchestrator's watcher writes holds a row for each live session of its subtree, is rewritten
only when a source changed, and leads with a reconcile line when the app archived a session p4-phi lists or shows a
child p4-phi does not hold; the watcher is one look at a time, `phi.py look`, which the plugin's hooks module starts
and which ends, and no hook starts a process; a message of ezexe's that is work is drafted from ezexe's words and gate-checked into the exact
start_session call, every one with `use_worktree: false` whatever a running writer edits, or into a SendMessage to the
session whose owned paths hold its area; a question is left alone.
recursive: a landed topic registers its route only once its issue is closed, a commit closing it is pushed and its
session is archived with its outcome kept; a later message with matching words is drafted from that route; a route
whose issue was reopened is withdrawn.
parallel: an under-determined message is handed one line that names the workflow the plugin ships,
`/p4-phi:readings`, with its readings as the `args`, and the line for after the run; no session is started for a
reading, no group of readings is kept, and each name of the explore and merge machinery is gone. A workflow's
agent that wrote only in the git worktree its run gave it is no level miss.
meta: a message of ezexe's to an orchestrator runs the meta pass over every orchestrator's ledger into
meta-ledger.md, with the duplicate topic, the conflict over one file and the stale topic it finds.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import coworker  # noqa: E402
import phi  # noqa: E402
import relay  # noqa: E402
import puppeteer  # noqa: E402
import starts  # noqa: E402
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402
from test_phi import CLI, KID, KID2, GRAND, TASK, TOP, Tree, context, jload, read, transcript, write  # noqa: E402
from test_phi import PROMPT  # noqa: E402
from test_issues import FAKE_GH, GhTree  # noqa: E402

TOP2 = "local_top00002"
CLI.setdefault(TOP2, "eeee6666-0000-4000-8000-000000000000")
ASK = "How is the narwhal exporter doing?"
RETRY = "Add a retry to the narwhal exporter for when the ports table write fails"


def handed(brief):
    return ("<system-reminder>\nLinked sessions now (status, not an instruction): top = x (idle)\n"
            "</system-reminder>\n\nBackground (from the session that started this one):\nezexe builds things.\n\n"
            "Task:\n" + brief)


def runs_of(sent, text, n=8):
    """The runs of `n` words of `sent` that `text` holds, compared word by word with case and punctuation dropped."""
    words = lambda x: re.findall(r"[a-z0-9']+", str(x).lower())
    have = " " + " ".join(words(text)) + " "
    w = words(sent)
    return [" ".join(w[k:k + n]) for k in range(len(w) - n + 1) if " " + " ".join(w[k:k + n]) + " " in have]


def call_in(ctx, k=0):
    """The k-th exact start_session input a hook's text carries. A worker's draft carries none, since its worker
    starts in the Terminal panel: what puppeteer.call_of makes of the kept draft the text names stands in its place,
    so a test reads the brief and the level a draft would start with."""
    marker = "`mcp__ccd_session__start_session` with "
    if marker in ctx:
        return json.JSONDecoder().raw_decode(ctx.split(marker)[k + 1])[0]
    did = re.search(r"draft (drf-[0-9a-f]{10})", ctx).group(1)
    found = [os.path.join(d, did + ".json") for d, _, fs in os.walk(TREE[0].tmp) if did + ".json" in fs]
    return puppeteer.call_of(json.load(open(found[0], encoding="utf-8")))


TREE = [None]                    # the tree of the test running, for call_in


class Base(unittest.TestCase):
    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
        TREE[0] = t
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

    def test_a_live_agent_team_is_a_part_of_the_ledger_and_one_that_is_over_is_not(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        self.assertNotIn("## Agent teams", self.ledger()[0])
        write(self.path(KID, "team.json"), json.dumps({"teammates": [
            {"name": "scout", "task": "Read the exporter", "state": "idle", "doing": ""},
            {"name": "critic", "task": "Argue against the plan", "state": "running", "doing": "reading flush.py"}]}))
        part = self.ledger()[0].split("## Agent teams")[1]
        self.assertIn(f"`{KID}`:", part)
        for word in ("scout", "idle", "Read the exporter", "critic", "running", "Argue against the plan"):
            self.assertIn(word, part, word)
        write(self.path(KID, "team.json"), json.dumps({"teammates": [
            {"name": "scout", "task": "Read the exporter", "state": "completed", "doing": ""}]}))
        self.assertNotIn("## Agent teams", self.ledger()[0])

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

    def test_a_ledger_is_built_without_git(self):
        # a ledger is built from the records alone: a look runs every few seconds, and a git call for each session
        # at each one would make every look slow
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
        self.assertNotIn("running writer", ctx, "the gate looks for no writer of its files")
        self.assertIn("its parent is this session", ctx)
        call = call_in(ctx)
        self.assertIn("draft --start", ctx, "a worker's draft is started in the Terminal panel")
        self.assertNotIn("mcp__ccd_session__start_session", ctx)
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", False),
                         "a worker's draft works in this checkout, on the paths of its `Files:` line")
        for line in puppeteer.checkout_lines():
            if line:
                self.assertIn(line, call["prompt"], "its brief says where it works, what it changes and how it commits")
        # docs/plugin-development.html, "Plan mode for a worker": a worker started in plan mode comes out of it in
        # auto, and under a starter that bypasses permission prompts every message between the two is then held,
        # so a draft names no permission mode and its worker starts in its starter's own
        self.assertNotIn("permission_mode", call, "a worker starts in its starter's permission mode")
        self.assertNotIn(RETRY, call["prompt"], "the brief quotes no sentence of the message")
        self.assertIn("Report when done.", call["prompt"])
        self.assertGreaterEqual(len(call["background"]), 80)
        did = puppeteer.DRAFT_RE.search(call["prompt"]).group(1)
        self.assertIn(f"phi draft {did} for {TOP}.", call["prompt"])
        self.assertEqual(jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["verdict"], "start")
        t.say(KID, handed(call["prompt"]))
        self.assertEqual(t.session(KID)["draft"], did, "the child knows the draft it came from")
        t.stop(TOP, RETRY, report="Started a session for it.", uuid="u-retry")
        other = context(t.say(TOP, "Write a changelog generator for the billing dashboard's release notes"))
        self.assertIn("so it is a new orchestrator", other)
        self.assertIn(starts.ORCHESTRATOR_BRIEF, call_in(other)["prompt"])
        self.assertIs(call_in(other)["use_worktree"], False, "a new orchestrator lands in this checkout")
        self.assertNotIn(puppeteer.checkout_lines()[0], call_in(other)["prompt"], "a new orchestrator's brief has no worker's lines")

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

    def test_a_draft_names_the_test_files_of_its_files_line(self):
        """ezexe/p4#234: a draft names the test files of the paths on its `Files:` line, the one beside each python
        file and the ones of its folder that import it, and never a whole suite, so its worker runs the tests its
        change touches."""
        t = self.t
        for name, text in (("x.py", "x = 1\n"), ("test_x.py", "import unittest\n"), ("test_y.py", "from x import x\n"),
                           ("test_z.py", "import os\n")):
            write(os.path.join(t.proj, "lib", name), text)
        self.assertEqual(puppeteer.test_files(t.proj, ["lib/x.py"]), ["lib/test_x.py", "lib/test_y.py"])
        self.assertEqual(puppeteer.test_files(t.proj, ["lib/test_x.py", "docs/a.md", "lib/gone.py"]), [],
                         "a test file, a page and a file with no test beside it name none")
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        prompt = call_in(context(t.say(TOP, RETRY + ", in `lib/x.py`")))["prompt"]
        # the folder as the test line spells it: norm form, as test_files gives it, where Files: is spelled on disk
        at = re.search(r"Files: `([^`]+)/x\.py`", prompt).group(1).lower()
        self.assertIn(f"Run these test files, and no whole suite: `{at}/test_x.py`, `{at}/test_y.py`.", prompt)
        self.assertIn("Done looks like: the change made, those test files passing, committed and reported.", prompt)
        self.assertNotIn("test_z.py", prompt)
        self.assertNotIn("its regression test passing", prompt)

    def test_a_draft_takes_no_slash_command_for_a_path(self):
        """A message that names Claude Code's commands `/goal` and `/plan` got a draft whose `Area:` and `Files:`
        lines held the folders `e:/goal` and `e:/plan`, since relay.paths_in joined each to the project's folder as
        a path. A slash command is no path, relay.command_word, so such a draft names no area and no files, and a
        message that names a file beside the commands gets that file alone."""
        t = self.t
        write(os.path.join(t.proj, "lib", "x.py"), "x = 1\n")
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        said = RETRY + ", and give its session a /goal as /plan would"
        prompt = call_in(context(t.say(TOP, said)))["prompt"]
        self.assertNotIn("Area:", prompt)
        self.assertNotRegex(prompt, r"(?m)^Files: ")
        self.assertNotRegex(prompt, r"`[^`\n]*/(goal|plan)`")
        prompt = call_in(context(t.say(TOP, said + ", in `lib/x.py`")))["prompt"]
        files = next(x for x in prompt.splitlines() if x.startswith("Files: "))
        self.assertRegex(files, r"^Files: `[^`]*lib/x\.py`$", "the file it names, and no command")
        self.assertRegex(prompt, r"(?m)^Area: `[^`]*lib/x\.py`\.$")

    def test_a_draft_takes_no_git_ref_and_no_repositorys_name_for_a_path(self):
        """A message that names `origin/main` and `ezexe/p4` got a draft whose `Area:` and `Files:` lines held both,
        joined to the project's folder. A git ref and a repository's name that the project's repository knows, by
        its remote `origin` and that remote's address, are no path, relay.ref_word, so the draft names the file the
        message names and neither of those."""
        t = self.t
        write(os.path.join(t.proj, "lib", "x.py"), "x = 1\n")
        subprocess.run(["git", "init", "-q", t.proj], check=True)
        subprocess.run(["git", "-C", t.proj, "remote", "add", "origin", "https://github.com/ezexe/p4.git"], check=True)
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        said = RETRY + ", rebased onto origin/main of ezexe/p4"
        prompt = call_in(context(t.say(TOP, said)))["prompt"]
        self.assertNotIn("Area:", prompt)
        self.assertNotRegex(prompt, r"(?m)^Files: ")
        prompt = call_in(context(t.say(TOP, said + ", in `lib/x.py`")))["prompt"]
        files = next(x for x in prompt.splitlines() if x.startswith("Files: "))
        self.assertRegex(files, r"^Files: `[^`]*lib/x\.py`$", "the file it names, and no ref and no repository")

    def test_a_draft_names_a_folder_still_to_be_made_as_its_area(self):
        """A brief that asks for a folder to be made names it as its area, though the folder is two parts with no
        file extension and not on disk yet, which is also how `origin/main` and `ezexe/p4` are written: the
        project's repository knows those two and knows nothing of the folder."""
        t = self.t
        subprocess.run(["git", "init", "-q", t.proj], check=True)
        subprocess.run(["git", "-C", t.proj, "remote", "add", "origin", "https://github.com/ezexe/p4.git"], check=True)
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        said = RETRY + ", in a new folder docs/guides, rebased onto origin/main of ezexe/p4"
        prompt = call_in(context(t.say(TOP, said)))["prompt"]
        area = next(x for x in prompt.splitlines() if x.startswith("Area: "))
        self.assertRegex(area, r"^Area: `[^`]*docs/guides`\.$", "the folder to be made, and no ref and no repository")
        self.assertRegex(prompt, r"(?m)^Files: `[^`]*docs/guides`$")

    def test_a_draft_takes_no_other_repositorys_name_for_a_path(self):
        """A message that names another repository as one, `the repository anthropics/claude-code`, got a draft
        whose `Area:` and `Files:` lines held `anthropics/claude-code` under the project's folder, since the
        project's repository knows nothing of it. relay.repos_said reads the message's own words, so the draft
        names the folder still to be made and no repository."""
        t = self.t
        subprocess.run(["git", "init", "-q", t.proj], check=True)
        subprocess.run(["git", "-C", t.proj, "remote", "add", "origin", "https://github.com/ezexe/p4.git"], check=True)
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        said = RETRY + ", as the repository anthropics/claude-code and anthropics/claude-code#110694 have it"
        prompt = call_in(context(t.say(TOP, said)))["prompt"]
        self.assertNotIn("Area:", prompt)
        self.assertNotRegex(prompt, r"(?m)^Files: ")
        prompt = call_in(context(t.say(TOP, said + ", in a new folder docs/guides")))["prompt"]
        self.assertRegex(prompt, r"(?m)^Files: `[^`]*docs/guides`$", "the folder to be made, and no repository")
        self.assertNotIn("claude-code`", prompt)

    def test_a_typed_slash_command_is_drafted_as_no_session(self):
        """A message that is a slash command is Claude Code's to run and no work of ezexe's to route: `/goal` with a
        condition that reads as work got a start draft titled by the command. phi.request_of takes no request from
        it, so the hook hands no draft, and the same words with no command before them are drafted as before."""
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        before = set(os.listdir(os.path.join(t.dir(TOP), "drafts"))) if os.path.isdir(
            os.path.join(t.dir(TOP), "drafts")) else set()
        ctx = context(t.say(TOP, "/goal " + RETRY))
        self.assertNotIn("routing read this message", ctx)
        self.assertNotIn("`mcp__ccd_session__start_session` with {", ctx)
        after = set(os.listdir(os.path.join(t.dir(TOP), "drafts"))) if os.path.isdir(
            os.path.join(t.dir(TOP), "drafts")) else set()
        self.assertEqual(after, before, "no draft is kept for it")
        self.assertIn("routing read this message", context(t.say(TOP, RETRY)))

    def test_the_sweeps_own_prompt_and_a_prompt_a_schedule_fired_draft_no_start(self):
        """Seen in an orchestrator on p4-phi 0.11.137 when the job upkeep had handed it fired for the first time:
        beside the prompt that opens "Sweep the sessions this one started, as p4-phi's upkeep has it." the hook
        handed "routing read this message of ezexe's as work for a session of its own" with a start draft titled
        by the sweep's words. The prompt is p4-phi's own, upkeep.SWEEP, and no person typed it. Seen in the
        desktop app on Claude Code 2.1.326, for a one-shot `CronCreate`: the hooks module is handed the origin
        kind `scheduled-trigger` for such a prompt. So a prompt with that origin holds no request of ezexe's,
        whatever its words, and where no origin was kept the sweep's prompt is told by its opening words."""
        import upkeep
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        drafts = os.path.join(t.dir(TOP), "drafts")

        def kept():
            return set(os.listdir(drafts)) if os.path.isdir(drafts) else set()

        def said(prompt, prompt_id="", kind=""):
            if kind:                                   # what the hooks module keeps for the prompt
                write(os.path.join(t.dir(TOP), "origin.json"), json.dumps({"promptId": prompt_id, "kind": kind}))
            return context(t.hook(PROMPT, TOP, {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                                "prompt_id": prompt_id}))
        before = kept()
        # the sweep's prompt with no origin kept, as on a build that loads no hooks module, and with its origin
        for ctx in (said(upkeep.SWEEP), said(upkeep.SWEEP, "p-1", "scheduled-trigger")):
            self.assertNotIn("routing read this message", ctx)
            self.assertNotIn("`mcp__ccd_session__start_session` with {", ctx)
        # words a person stored for a schedule, which read as work: the origin says a schedule fired them
        self.assertNotIn("routing read this message", said(RETRY, "p-2", "scheduled-trigger"))
        self.assertEqual(kept(), before, "no draft is kept for any of the three")
        self.assertEqual(t.session(TOP).get("turnBy"), "event", "and no person began that turn")
        # the same words as ezexe's own message are drafted as before
        self.assertIn("routing read this message", said(RETRY, "p-3", "composer"))
        self.assertEqual(t.session(TOP).get("turnBy"), "user")

    def test_a_python_files_tests_are_found_in_the_tests_folders_above_it_too(self):
        """A project that keeps its tests in a `tests` folder, at its top or beside the code, as pytest's good
        practices lay a project out, has them named too: the folder nearest the file first, in each the file named
        after the python file and then the ones that import it. No folder above the project is read, and none whose
        name starts with a dot."""
        t = self.t
        for name, text in (("src/pkg/x.py", "x = 1\n"), ("src/pkg/tests/test_u.py", "from x import x\n"),
                           ("tests/unit/test_w.py", "import x\n"), ("tests/unit/test_v.py", "import os\n"),
                           ("tests/test_x.py", "import unittest\n"), ("tests/.kept/test_h.py", "import x\n")):
            write(os.path.join(t.proj, name), text)
        write(os.path.join(os.path.dirname(t.proj), "tests", "test_x.py"), "import x\n")
        self.assertEqual(puppeteer.test_files(t.proj, ["src/pkg/x.py"]),
                         ["src/pkg/tests/test_u.py", "tests/test_x.py", "tests/unit/test_w.py"])
        top = t.proj.replace("\\", "/")
        self.assertEqual(puppeteer.test_files(t.proj, [f"{top}/src/pkg/x.py"]),
                         [f"{top}/src/pkg/tests/test_u.py", f"{top}/tests/test_x.py", f"{top}/tests/unit/test_w.py"])
        self.assertEqual(puppeteer.test_files(t.proj, ["src/pkg/gone.py", "src/pkg/tests/test_u.py"]), [])
        for i in range(puppeteer.TESTS_MOST + 2):
            write(os.path.join(t.proj, "tests", f"test_more{i}.py"), "import x\n")
        got = puppeteer.test_files(t.proj, ["src/pkg/x.py"])
        self.assertEqual(len(got), puppeteer.TESTS_MOST)
        self.assertEqual(got[:2], ["src/pkg/tests/test_u.py", "tests/test_x.py"],
                         "the file named after it is named before the ones that only import it")

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
        for line in ("Done looks like: ", "Model and effort: "):
            self.assertIn(line, brief)
        self.assertNotIn("Files: none", brief, "a brief that writes and names no path claims no empty set of files")
        named = call_in(context(t.say(TOP, "Fix the row count in `src/export/flush.py` when the table is empty")))
        self.assertRegex(named["prompt"], r"(?m)^Files: `[^`]*src/export/flush\.py`$", "its files, where it names them")
        self.assertIn(call["title"], brief, "the task, stated by its title")
        travelled = re.compile(r"ezexe asked|ezexe's (?:words|message)|routed from|relayed by|from ezexe|"
                               r"words quoted", re.I)
        self.assertIsNone(travelled.search(brief), brief)
        self.assertIsNone(travelled.search(call["background"]), call["background"])
        self.assertIn("draft --start", ctx, "a worker's draft is started by the command that gives it its node")

    def test_no_line_handed_to_a_session_tells_it_to_quote_a_prompt(self):
        """Every road that tells a session to pass work on asks for the task restated as its own instruction."""
        t = self.t
        said = [context(t.say(host, words, P4_PHI_BOOK="1")) for host, words in (
            (TOP, TASK), (TOP, "also, what colour should the fence be?"),
            (KID, handed("Port the flush to the new writer. Archive when done.")), (KID, "and what about the fence?"),
            (KID, "Add a dark mode toggle to the billing dashboard's settings page"))]
        asks = re.compile(r"words,? quoted|quoted words|holding ezexe's words|built from ezexe's words|"
                          r"ezexe's words:", re.I)
        for text in said:
            self.assertIsNone(asks.search(text), text)

    def test_a_draft_whose_files_a_running_writer_edits_is_started_in_the_checkout_and_never_queued(self):
        """The queue behind a busy writer is gone: a draft that names a file a running writer is at work on is
        handed as a start at once, with `use_worktree: false`, since the part of the partition that holds the two
        sessions to their own paths is section 2's guard in phi.py, not a wait here. The gate names no writer, keeps no start request, and
        `pioneer` prints the same verdict again."""
        t = self.t
        t.record(TOP2, title="the docs top")
        t.record(KID, TOP2, title="the flush port")     # the running writer is another orchestrator's
        t.say(TOP, TASK)
        t.say(TOP2, "Write the docs for the billing dashboard")
        t.say(KID, handed("Port `src/export/flush.py` to the new writer."))     # in a turn: a running writer
        ctx = context(t.say(TOP, "Rename the retry helper in `src/export/flush.py` and update its callers"))
        self.assertNotIn("holds its files", ctx)
        self.assertNotIn("Queue it", ctx)
        self.assertNotIn("running writer", ctx)
        call = call_in(ctx)
        self.assertIn("Files: `", call["prompt"], "the files its brief says it covers")
        did = puppeteer.DRAFT_RE.search(call["prompt"]).group(1)
        draft = jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))
        self.assertEqual(draft["verdict"], "start")
        self.assertNotIn("busy", draft)
        self.assertEqual((call["initiation"], call["context"]), ("user_asked", "fresh"))
        self.assertIs(call["use_worktree"], False, "a worker's draft works in this checkout")
        worker = puppeteer.call_of({**draft, "parent": TOP})
        self.assertIs(worker["use_worktree"], False, "whatever a running writer edits")
        r = t.cli(TOP, "pioneer", did)
        self.assertIn("Start it now: `mcp__ccd_session__start_session` with ", r.stdout)
        self.assertNotIn("queued", r.stdout + r.stderr)
        self.assertEqual(starts.state(t.p4), {}, "no start request is kept")
        text, _ = self.ledger()
        self.assertNotIn("waits behind", text)


class WorkerSplit(Base):
    """A subagent that wrote files is a level miss on the ledger."""

    def plan(self, host, inp):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def recall(self, host, name, body):
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), name],
                       input=json.dumps({"session_id": CLI[host], "cwd": self.t.proj, **body}), capture_output=True,
                       text=True, timeout=60, env=self.t.env(host, P4_RECALL_SYNC="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_a_subagent_that_wrote_files_is_a_level_miss_on_the_ledger(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer. Report when done."))
        self.plan(KID, {"items": [{"content": "Port the flush", "status": "in_progress"}], "scope": "first_task"})
        self.recall(KID, "agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": "toolu_l1",
                                   "tool_input": {"prompt": "port the flush", "description": "port"}})
        self.recall(KID, "subagent-start", {"hook_event_name": "SubagentStart", "agent_id": "agw01",
                                            "agent_type": "general-purpose"})
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
    """A start draft holds the task and the lines code reads back, and no paragraph of advice."""

    def test_a_start_draft_holds_the_task_and_what_code_reads_back(self):
        """A writing start whose message names its files carries its `Files:` line, the done line, "Report when
        done." and the draft marker. One whose message names none has no `Files:` line, since a brief that writes
        claims no empty set of files."""
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        writing = call_in(context(t.say(TOP, "Add a retry to `src/export/flush.py` for when the ports table write "
                                            "fails")))["prompt"]
        self.assertRegex(writing, r"Files: `[^`]*src/export/flush\.py`")
        self.assertIn("Done looks like:", writing)
        self.assertIn("Report when done.", writing)
        self.assertRegex(writing, r"phi draft drf-[0-9a-f]+ for ")
        self.assertNotIn("decisions.md", writing)
        t.stop(TOP, "retry", report="drafted")
        none = call_in(context(t.say(TOP, RETRY)))["prompt"]
        self.assertNotRegex(none, r"(?m)^Files: ")
        self.assertNotIn("decisions.md", none)

    def test_a_briefs_paths_keep_their_spelling_on_disk_and_a_path_not_there_is_kept_as_given(self):
        t = self.t
        t.say(TOP, TASK)
        real = os.path.join(t.tmp, "ReadMe.MD")
        write(real, "x")
        want = os.path.realpath(real).replace("\\", "/")
        lower = real.lower().replace("\\", "/")
        missing = os.path.join(t.tmp, "Not-There.md").lower().replace("\\", "/")
        self.assertEqual(puppeteer.spelled(missing), missing)
        if os.path.exists(lower):                    # a case-insensitive file system
            self.assertEqual(puppeteer.spelled(lower), want)
            d = puppeteer.prompter(t.p4, t.session(TOP), RETRY,
                                   {"within": False, "routes": [], "paths": [lower, missing]}, t.proj)
            self.assertIn(f"Files: `{want}`, `{missing}`", d["brief"])
            self.assertEqual(d["paths"], [lower, missing], "the paths comparisons read are unchanged")
        else:
            self.skipTest("the file system is case-sensitive")

class WatcherCaps(unittest.TestCase):
    def test_a_watcher_reads_its_caps_from_the_orchestrators_own_store_not_the_shared_one(self):
        """ezexe/p4#125: phi.project_conf reads the caps from the store where the session runs, so a look over a
        tree kept in a shared store, which phi.home names, reads them from its orchestrator's own project too."""
        tmp = tempfile.mkdtemp()
        try:
            shared, proj = os.path.join(tmp, "shared", ".claude", "p4"), os.path.join(tmp, "proj")
            own = os.path.join(proj, ".claude", "p4")
            os.makedirs(own)
            write(os.path.join(shared, "phi", "sessions", "local_t", "session.json"),
                  json.dumps({"sessionId": "local_t", "cwd": proj}))
            write(os.path.join(shared, "phi", "sessions", "local_u", "session.json"),
                  json.dumps({"sessionId": "local_u", "cwd": os.path.join(tmp, "bare")}))
            self.assertEqual(puppeteer.conf_store(shared, "local_t"), own)
            self.assertEqual(puppeteer.conf_store(shared, "local_u"), shared, "with no store of its own, the tree's")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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
        past = "What did we decide about the narwhal exporter flush that drops the last row of the ports table?"
        self.assertEqual(puppeteer.earlier_text(t.p4, past), "", "a registered route matches: no line")
        self.state(**{"7": "OPEN"})
        self.assertIn(f"withdrawn {row['id']}: ezexe/demo#7 was reopened", self.why())
        self.assertEqual(puppeteer.all_routes(t.p4), {})
        self.assertIn(puppeteer.SEARCH_TOOL, puppeteer.earlier_text(t.p4, past), "no route is left to match")


class Earlier(Base):
    """A message of ezexe's own that asks about earlier work and matches no registered route is handed one line
    that names the desktop app's tool for searching its sessions' transcripts, in a session the app holds a record
    of."""
    PAST = "What did we decide about the fence in an earlier session?"

    def setUp(self):
        super().setUp()
        self.t.say(TOP, TASK)
        self.t.stop(TOP, TASK, report="planned")

    def said(self, host, prompt, prompt_id="", **more):
        return context(self.t.hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                                  "prompt_id": prompt_id}, **more))

    def test_ezexes_message_about_earlier_work_with_no_route_gets_the_one_line(self):
        ctx = self.said(TOP, self.PAST)
        line = [x for x in ctx.splitlines() if puppeteer.SEARCH_TOOL in x]
        self.assertEqual(len(line), 1, ctx)
        self.assertEqual(line[0], "phi (p4-phi): this message of ezexe's asks about earlier work and matches no "
                         "registered route, and p4-phi finds no earlier turn by a message's words: search the app's "
                         "transcripts for it with `mcp__ccd_session_mgmt__search_session_transcripts`.")
        for words in ("Did we already fix the flush last week?", "which chat was it, the previous conversation?"):
            self.assertIn(puppeteer.SEARCH_TOOL, self.said(TOP, words), words)

    def test_no_line_for_a_message_that_asks_nothing_of_earlier_work(self):
        for words in (ASK, RETRY, "also, what colour should the fence be?"):
            self.assertNotIn(puppeteer.SEARCH_TOOL, self.said(TOP, words), words)

    def test_no_line_for_another_sessions_message_or_an_event(self):
        peer = f'<cross-session-message from="{KID}">{self.PAST}</cross-session-message>'
        event = f"<task-notification>{self.PAST}</task-notification>"
        for words in (peer, event):
            self.assertNotIn(puppeteer.SEARCH_TOOL, self.said(TOP, words), words)
        for k, kind in enumerate(("peer", "task-notification")):   # by the origin, whatever the text opens with
            write(os.path.join(self.t.dir(TOP), "origin.json"), json.dumps({"promptId": f"p-{k}", "kind": kind}))
            self.assertNotIn(puppeteer.SEARCH_TOOL, self.said(TOP, self.PAST, f"p-{k}"), kind)
        write(os.path.join(self.t.dir(TOP), "origin.json"), json.dumps({"promptId": "p-9", "kind": "composer"}))
        self.assertIn(puppeteer.SEARCH_TOOL, self.said(TOP, self.PAST, "p-9"))

    def test_no_line_in_a_session_the_app_holds_no_record_of_or_with_routing_off(self):
        """The tool is the desktop app's, so a session started in a terminal, which the app holds no record of, has
        none to be pointed at."""
        self.t.say("local_noapp001", TASK)
        self.assertNotIn(puppeteer.SEARCH_TOOL, self.said("local_noapp001", self.PAST))
        self.assertNotIn(puppeteer.SEARCH_TOOL, self.said(TOP, self.PAST, P4_PHI_PUPPETEER="0"))


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
        """A turn that ends with the command still running, as the Stop input's `background_tasks` lists it."""
        path = transcript(os.path.join(self.t.tmp, host + task_id + ".jsonl"), "port it", (), "Running.", task_id)
        r = self.t.hook("stop", host, {"hook_event_name": "Stop", "transcript_path": path,
                                       "last_assistant_message": "Running.",
                                       "background_tasks": [{"id": task_id, "type": "shell", "status": "running",
                                                             "description": command, "command": command}]})
        self.assertEqual(r.returncode, 0, r.stderr)

    def finish(self, host=KID):
        self.assertEqual(self.t.cli(host, "done", "the flush suite ran and passed").returncode, 0)
        self.assertEqual(self.t.stop(host, "port it", report="Ported; the suite passes.").returncode, 0)
        self.assertTrue(self.t.session(host).get("doneRetired"))

    def test_a_session_archived_with_a_background_task_running_leaves_a_row_and_its_parent_is_told_once(self):
        self.background(KID, "sh run-suites.sh", "bg12345678")
        self.finish()
        left = self.t.session(KID)["unfinishedAtArchive"]["items"]
        self.assertTrue(any("background task bg12345678" in x and "still running at its last turn's end" in x
                            for x in left), left)
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

    def test_a_second_start_of_a_running_command_is_held_once(self):
        self.background(KID, "sh run-suites.sh", "bg11111111")
        call = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": "sh  run-suites.sh", "run_in_background": True}}
        out = json.loads(self.t.hook("restart-check", KID, dict(call, tool_use_id="tu1")).stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("still running in the background as bg11111111", out["permissionDecisionReason"])
        self.assertIn("by the app's own list", out["permissionDecisionReason"])
        self.assertEqual(self.t.hook("restart-check", KID, dict(call, tool_use_id="tu2")).stdout.strip(), "",
                         "told once for that copy: the next start goes through")
        other = dict(call, tool_input={"command": "sh other.sh", "run_in_background": True}, tool_use_id="tu3")
        self.assertEqual(self.t.hook("restart-check", KID, other).stdout.strip(), "", "another command is no restart")

    def test_a_request_nobody_started_is_named(self):
        starts.add(self.t.p4, KID, "A follow-up nobody starts", "Do the follow-up in the exporter.", to=TOP)
        left = puppeteer.unfinished(self.t.p4, KID)
        self.assertTrue(any("that it filed was never started" in x for x in left), left)

    def test_no_process_list_is_read_and_running_work_is_the_archive_tools_own_to_refuse(self):
        """Audit candidate 20. The archive tool's description: "Archiving stops the session's process" and "A session
        that is still working (mid-turn, or with live background work) is not archived and the call says so", and
        desktop.md, "Archive a session": "Cloud sessions and sessions that are still running don't archive
        themselves." So p4-phi reads no process list of the machine at an archive, with a process of the session's
        own running, and names no background task of a session the app holds archived. What the refusal lacks is a
        session p4-phi only counts as archived, which no archive call closed: its task is still named."""
        from unittest import mock
        import inspect
        for fn in (puppeteer.unfinished, puppeteer.archive_check):
            self.assertEqual(list(inspect.signature(fn).parameters), ["home", "sid"], fn.__name__)
        self.background(KID, "sh run-suites.sh", "bg77777777")
        ran = []
        real = subprocess.run

        def run(args, *a, **k):
            ran.append(" ".join(map(str, args)) if isinstance(args, (list, tuple)) else str(args))
            return real(args, *a, **k)
        with mock.patch.object(subprocess, "run", run), mock.patch.dict(os.environ, self.t.env(KID)),                 mock.patch.dict(phi.RECORDS, clear=True):         # the app's records, as a hook process reads them
            left = puppeteer.unfinished(self.t.p4, KID)
        self.assertFalse([c for c in ran if "Win32_Process" in c or c.startswith("ps ")], "no process list is read")
        self.assertFalse(any(x.startswith("process ") for x in left), left)
        self.assertTrue(any("background task bg77777777" in x for x in left),
                        "counted as archived by p4-phi alone, its process still runs: named")
        app = os.path.join(self.t.app, KID + ".json")
        write(app, json.dumps({**json.loads(read(app)), "isArchived": True}))      # archived in the app
        with mock.patch.dict(os.environ, self.t.env(KID)), mock.patch.dict(phi.RECORDS, clear=True):
            left = puppeteer.unfinished(self.t.p4, KID)
        self.assertFalse(any("bg77777777" in x for x in left), "the archive stopped its process, or was refused")

    def test_a_self_archive_is_never_held_by_a_background_task(self):
        """The archive tool itself refuses a session with live background work, audit row S24, so p4-phi neither
        holds a self-archive for a saved entry nor names one in its refusal."""
        self.background(KID, "sh run-suites.sh", "bg33333333")
        call = {"hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session_mgmt__archive_session",
                "tool_input": {"session_id": "self"}}
        self.assertNotIn("bg33333333", self.t.hook("self-archive", KID, dict(call, tool_use_id="sa1")).stdout)

    def test_a_completion_notice_clears_the_saved_entry(self):
        """main read a task's end from its notice; the saved list does too, so a notice in the message that ends
        the task ends its entry, and the restart check and the pages stop naming it as running."""
        self.background(KID, "sh run-suites.sh", "bg44444444")
        self.assertTrue(puppeteer.held_tasks(self.t.p4, KID))
        self.t.say(KID, "<task-notification>\n<task-id>bg44444444</task-id>\n<status>completed</status>\n"
                        "<summary>Background command finished</summary>\n</task-notification>")
        self.assertEqual(puppeteer.held_tasks(self.t.p4, KID), [])
        call = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "tu4",
                "tool_input": {"command": "sh run-suites.sh", "run_in_background": True}}
        self.assertEqual(self.t.hook("restart-check", KID, call).stdout.strip(), "", "ended: started again freely")
        self.assertFalse(any("bg44444444" in x for x in puppeteer.unfinished(self.t.p4, KID)))

    def test_a_task_stop_clears_the_saved_entry(self):
        """A stop sends no notice, so a TaskStop call ends the entry, named by `task_id` or `shell_id`, through the lookup-record gate."""
        for tool, key, tid in (("TaskStop", "task_id", "bg55555555"), ("TaskStop", "shell_id", "bg66666666")):
            self.background(KID, "sh run-suites.sh", tid)
            body = {"session_id": CLI[KID], "cwd": self.t.proj, "hook_event_name": "PostToolUse", "tool_name": tool,
                    "tool_input": {key: tid}, "tool_response": "stopped", "tool_use_id": f"toolu_{tid}"}
            r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), "lookup-record"],
                           input=json.dumps(body), capture_output=True, text=True, timeout=60,
                           env=self.t.env(KID, P4_RECALL_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(puppeteer.held_tasks(self.t.p4, KID), [], tool)


class Scorers(Base):
    """Routing's route and code owner picks go by shared content words, at the measured threshold."""

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

    def test_shared_content_words_pick_the_route_at_the_measured_threshold(self):
        t = self.t
        t.say(TOP, TASK)
        self.routes()
        got = puppeteer.score_routes(t.p4, self.MESSAGE)
        n, part = puppeteer.share(self.MESSAGE, "port the exporter flush to the new writer and run the ports table "
                                                "suite on the store Port the exporter flush")
        self.assertEqual((got[0][2]["id"], got[0][1], got[0][0]), ("rt-wrong", n, round(part, 2)), "its own score")
        self.assertEqual(puppeteer.OWNER_WORDS, 8, "the code owner threshold")
        self.assertEqual((puppeteer.ROUTE_MIN, puppeteer.ROUTE_CLOSE), (4, 0.6), "the route thresholds")


class Terminal(Base):
    """`draft --start`: a worker's draft starts in the Terminal panel, an orchestrator's with the desktop call."""

    def drafted(self, words=RETRY):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        ctx = context(t.say(TOP, words))
        return ctx, re.search(r"draft (drf-[0-9a-f]{10})", ctx).group(1)

    def test_a_workers_draft_names_the_command_and_the_command_gives_its_terminal_call(self):
        t = self.t
        ctx, did = self.drafted()
        self.assertIn(f"draft --start {did}", ctx)
        self.assertNotIn("mcp__ccd_session__start_session` with", ctx)
        r = t.cli(TOP, "draft", "--start", did)
        self.assertEqual(r.returncode, 0, r.stderr)
        title = jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["title"]
        name = coworker.draft_name(title, did)
        self.assertIn(f"worker `{name}`", r.stdout)
        self.assertIn("`mcp__terminal__run_in_terminal` with ", r.stdout)
        self.assertIn("coworkers --wait --report ", r.stdout)
        node = relay.nodes(t.p4)[name]
        for f in (f"brief-{name}.md", "coworker-settings.json"):
            self.assertTrue(os.path.isfile(os.path.join(node, "phi", f)), f)
        self.assertEqual(relay.node_record(t.p4, name)["kind"], "worker")
        again = t.cli(TOP, "draft", "--start", did)
        self.assertEqual(again.returncode, 2, "a worker is started once")

    def test_a_draft_started_with_a_task_file_gives_the_worker_the_starters_task_and_its_done_line(self):
        t = self.t
        ctx, did = self.drafted()
        task = os.path.join(t.tmp, "task.md")
        write(task, "Step one: run the exporter.\nDone looks like: the report holds X\n")
        r = t.cli(TOP, "draft", "--start", did, "--task", task)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--task <file>", r.stdout)
        title = jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["title"]
        name = coworker.draft_name(title, did)
        folder = os.path.join(relay.nodes(t.p4)[name], "phi")
        with open(os.path.join(folder, f"brief-{name}.md"), encoding="utf-8") as f:
            brief = f.read()
        self.assertIn("## The task", brief)
        self.assertIn("Step one: run the exporter.", brief)
        self.assertEqual(brief.count("Done looks like:"), 1)
        self.assertLess(brief.index("## The task"), brief.index("phi draft "))
        ext = "ps1" if os.name == "nt" else "sh"
        with open(os.path.join(folder, f"start-{name}.{ext}"), encoding="utf-8") as f:
            self.assertIn("the report holds X", f.read())

    def test_a_draft_started_without_a_task_file_says_how_to_give_one(self):
        t = self.t
        ctx, did = self.drafted()
        r = t.cli(TOP, "draft", "--start", did)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pass `--task <file>`", r.stdout)
        title = jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["title"]
        name = coworker.draft_name(title, did)
        with open(os.path.join(relay.nodes(t.p4)[name], "phi", f"brief-{name}.md"), encoding="utf-8") as f:
            self.assertNotIn("## The task", f.read())

    def test_a_missing_or_empty_task_file_exits_2(self):
        t = self.t
        ctx, did = self.drafted()
        r = t.cli(TOP, "draft", "--start", did, "--task", os.path.join(t.tmp, "none.md"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("phi:", r.stderr)
        empty = os.path.join(t.tmp, "empty.md")
        write(empty, "  \n")
        r = t.cli(TOP, "draft", "--start", did, "--task", empty)
        self.assertEqual(r.returncode, 2)
        self.assertIn("phi:", r.stderr)
        with self.assertRaises(ValueError):
            big = os.path.join(t.tmp, "big.md")
            write(big, "x" * (puppeteer.TASK_CHARS_MOST + 1))
            puppeteer.task_text(big)

    def test_an_orchestrators_draft_is_refused_there_and_keeps_its_desktop_call(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        draft = puppeteer.prompter(t.p4, t.session(TOP), RETRY, {"within": False, "routes": [], "paths": []}, t.proj)
        self.assertEqual(draft["parent"], "")
        text = puppeteer.verdict_text(t.p4, t.session(TOP), {**draft, "verdict": "start", "gate": ["x"]})
        self.assertIn("mcp__ccd_session__start_session` with", text)
        self.assertIn("stays there", text)
        self.assertNotIn("draft --start", text)
        os.makedirs(os.path.join(t.dir(TOP), "drafts"), exist_ok=True)
        write(os.path.join(t.dir(TOP), "drafts", draft["id"] + ".json"), json.dumps(draft))
        r = t.cli(TOP, "draft", "--start", draft["id"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("an orchestrator's draft is started with the call the draft printed", r.stderr)
        self.assertEqual(t.cli(TOP, "draft", "--start", "drf-0000000000").returncode, 2)

    def test_sections_prints_the_terminal_call_of_each_run_and_a_report_wait_needs_no_plan(self):
        t = self.t
        t.say(TOP, TASK)
        plan = os.path.join(t.tmp, "plan.md")
        write(plan, "# A note\n\n## 1. The page\n\n- **Files:** `docs/export.md`\n")
        r = t.cli(TOP, "sections", plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("`mcp__terminal__run_in_terminal` with ", r.stdout)
        self.assertNotIn("mcp__ccd_session__start_session", r.stdout)
        name = re.search(r"worker `(tw-[^`]+)`", r.stdout).group(1)
        report = re.search(r"its report (\S+)", r.stdout).group(1)
        self.assertEqual(os.path.basename(report), f"report-{name}.md")
        write(report, "done")
        waited = t.cli(TOP, "coworkers", "--wait", "--report", report)
        self.assertEqual(waited.returncode, 0, waited.stderr)
        self.assertIn("is there", waited.stdout)

    def planner_draft(self, settings=None):
        """Starts a planner's draft; its start file's text, its resume file's text, the output and the node folder."""
        t = self.t
        if settings is not None:
            write(os.path.join(t.p4, "phi", "phi.json"), json.dumps(settings))
        t.say(TOP, TASK)
        did = "drf-0123456789"
        os.makedirs(os.path.join(t.dir(TOP), "drafts"), exist_ok=True)
        write(os.path.join(t.dir(TOP), "drafts", did + ".json"), json.dumps({
            "id": did, "title": "Plan the ports table move", "parent": TOP, "verdict": "start", "context": "fresh",
            "brief": "Plan the ports table move.\nThis session starts in plan mode.\nFiles: none", "gate": []}))
        r = t.cli(TOP, "draft", "--start", did)
        self.assertEqual(r.returncode, 0, r.stderr)
        name = coworker.draft_name("Plan the ports table move", did)
        folder = os.path.join(relay.nodes(t.p4)[name], "phi")
        ext = "ps1" if os.name == "nt" else "sh"
        with open(os.path.join(folder, f"start-{name}.{ext}"), encoding="utf-8") as f:
            start = f.read()
        with open(os.path.join(folder, f"resume-{name}.{ext}"), encoding="utf-8") as f:
            resume = f.read()
        with open(os.path.join(folder, "coworker-settings.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["enabledPlugins"]["p4-temportal@p4-marketplace"])
        return start, resume, r.stdout, name

    def test_an_interactive_planners_draft_starts_in_plan_mode_with_the_team_variable(self):
        start, resume, out, name = self.planner_draft({"worker_mode": "interactive"})
        self.assertIn("--permission-mode plan", start)
        self.assertIn(coworker.TEAMS, start)
        self.assertNotIn("/goal", start)
        self.assertNotIn("claude -p", start)
        self.assertIn("--session-id", start)
        self.assertIn("--resume", resume)
        self.assertNotIn("--session-id", resume)
        self.assertNotIn("log-", out)

    def test_a_print_planners_draft_starts_headless_with_its_plan_file_and_prints_the_resume_and_the_land_line(self):
        start, resume, out, name = self.planner_draft()
        self.assertIn("claude -p", start)
        self.assertIn("--permission-mode bypassPermissions", start)
        self.assertNotIn(coworker.TEAMS, start)
        self.assertIn("/goal Write the plan", start)
        plan_file = os.path.join(self.t.p4, "temportal", "plan-planner", f"{name}.md").replace("\\", "/")
        self.assertIn(plan_file, start)
        self.assertIn("--resume", resume)
        self.assertIn(f"log-{name}.jsonl", out)
        self.assertIn(f"resume-{name}", out)
        self.assertIn(plan_file, out)
        self.assertIn("--land", out)

    def started_file(self, name_words="Fix the ports table", settings=None):
        t = self.t
        if settings is not None:
            write(os.path.join(t.p4, "phi", "phi.json"), json.dumps(settings))
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        ctx = context(t.say(TOP, RETRY))
        did = re.search(r"draft (drf-[0-9a-f]{10})", ctx).group(1)
        self.assertEqual(t.cli(TOP, "draft", "--start", did).returncode, 0)
        title = jload(os.path.join(t.dir(TOP), "drafts", did + ".json"))["title"]
        folder = os.path.join(relay.nodes(t.p4)[coworker.draft_name(title, did)], "phi")
        name = [f for f in os.listdir(folder) if f.startswith("start-")][0]
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            return f.read()

    def test_a_drafted_workers_start_file_names_the_workers_profile_by_default_and_not_when_it_is_off(self):
        self.assertIn("ANTHROPIC_PROFILE", self.started_file())

    def test_the_profile_and_the_mode_combine_all_four_ways(self):
        for profile in ("p4-workers", ""):
            for mode in ("print", "interactive"):
                with self.subTest(profile=profile, mode=mode):
                    self.setUp()
                    text = self.started_file(settings={"worker_profile": profile, "worker_mode": mode})
                    self.assertEqual("ANTHROPIC_PROFILE" in text, bool(profile))
                    self.assertEqual("claude -p" in text, mode == "print")
                    self.assertEqual("stream-json" in text, mode == "print")

    def test_worker_mode_reads_print_where_the_key_is_absent_and_the_command_writes_it(self):
        t = self.t
        t.say(TOP, TASK)
        path = os.path.join(t.p4, "phi", "phi.json")
        self.assertEqual(phi.worker_mode(t.p4), "print")
        self.assertIn("worker_mode is print", t.cli(TOP, "worker_mode").stdout)
        self.assertFalse(os.path.exists(path) and "worker_mode" in jload(path), "reading writes nothing")
        write(path, json.dumps({"book": False}))
        r = t.cli(TOP, "worker_mode", "interactive")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(jload(path), {"book": False, "worker_mode": "interactive"}, "the other keys are kept")
        self.assertEqual(phi.worker_mode(t.p4), "interactive")
        r = t.cli(TOP, "worker_mode", "print")
        self.assertIn("worker_mode is print", r.stdout)
        self.assertEqual(jload(path), {"book": False, "worker_mode": "print"})
        bad = t.cli(TOP, "worker_mode", "tab")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("phi:", bad.stderr)
        self.assertEqual(jload(path)["worker_mode"], "print", "a bad word writes nothing")
        write(path, json.dumps({"worker_mode": "nonsense"}))
        self.assertEqual(phi.worker_mode(t.p4), "print")

    def test_wait_report_prints_ended_with_the_result_row_where_the_log_ends_with_no_report(self):
        t = self.t
        t.say(TOP, TASK)
        folder = os.path.join(t.tmp, "node")
        os.makedirs(folder)
        report, log = os.path.join(folder, "report-tw-x.md"), os.path.join(folder, "log-tw-x.jsonl")
        write(log, json.dumps({"type": "result", "subtype": "success", "is_error": True,
                               "result": "Credit balance is too low"}) + "\n")
        import threading
        import time

        stop = threading.Event()

        def later():
            # The row is written again until the CLI is done, so one lands past the offset its wait began at however
            # slowly the process starts: a single row written once raced a slow runner and the wait ran an hour.
            while not stop.wait(1):
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                                        "result": "Credit balance is too low"}) + "\n")
                old = time.time() - 3600            # the run ended past the quiet window
                os.utime(log, (old, old))
        threading.Thread(target=later, daemon=True).start()
        try:
            r = t.cli(TOP, "coworkers", "--wait", "--report", report)
        finally:
            stop.set()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ended:", r.stdout)
        self.assertIn("Credit balance is too low", r.stdout)
        self.assertIn("error", r.stdout)

    def test_an_empty_profile_in_phi_json_leaves_the_start_file_without_the_line(self):
        self.assertNotIn("ANTHROPIC_PROFILE", self.started_file(settings={"worker_profile": ""}))

    def test_worker_profile_reads_p4_workers_where_the_key_is_absent_and_the_command_writes_it(self):
        t = self.t
        t.say(TOP, TASK)
        path = os.path.join(t.p4, "phi", "phi.json")
        self.assertEqual(phi.worker_profile(t.p4), "p4-workers")
        self.assertIn("worker_profile is p4-workers", t.cli(TOP, "worker_profile").stdout)
        write(path, json.dumps({"book": False}))
        r = t.cli(TOP, "worker_profile", "p4-bill")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(jload(path), {"book": False, "worker_profile": "p4-bill"}, "the other keys are kept")
        self.assertIn("ant auth login --profile p4-bill", r.stdout)
        self.assertEqual(phi.worker_profile(t.p4), "p4-bill")
        r = t.cli(TOP, "worker_profile", "off")
        self.assertIn("worker_profile is off", r.stdout)
        self.assertEqual(jload(path), {"book": False, "worker_profile": ""})
        self.assertEqual(phi.worker_profile(t.p4), "")
        self.assertEqual(t.cli(TOP, "worker_profile", "bad name").returncode, 2)
        r = t.cli(TOP, "worker_profile", "default")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(jload(path), {"book": False}, "default removes the key and keeps the others")
        self.assertEqual(phi.worker_settings(t.p4, TOP)["profile_from"], "the pair of print")
        write(path, json.dumps({"book": False, "worker_mode": "interactive"}))
        self.assertEqual(phi.worker_settings(t.p4, TOP)["profile"], "", "an interactive worker pairs with off")

    def test_a_session_another_session_started_is_an_orchestrator_whether_or_not_it_started_one(self):
        s = {"sessionId": KID, "spawnedFrom": {"sessionId": TOP}}
        self.assertTrue(puppeteer.orchestrator(self.t.p4, s))
        self.assertFalse(puppeteer.orchestrator(self.t.p4, {"sessionId": TOP}), "one nobody started needs a task")
        self.assertTrue(puppeteer.orchestrator(self.t.p4, {"sessionId": TOP, "task": "Build it"}))
        self.assertFalse(puppeteer.orchestrator(self.t.p4, {}))


class WorkerSettings(Base):
    """A session's own worker mode and profile, the paired defaults and the rule by the piece of work."""

    LAND = "Fix the ports table writer.\nFiles: src/writer.py"
    TEAM = "Review the ports table move with an agent team.\nFiles: none"
    APPROVE = ("Plan the ports table move.\nThis session starts in plan mode and ezexe approves it with "
               "ExitPlanMode.\nFiles: none")

    def start(self, host, brief, title="Fix the ports table", did="drf-0123456789"):
        """Starts a draft of `host` with `brief`; the text of its start file."""
        t = self.t
        t.say(host, TASK)
        os.makedirs(os.path.join(t.dir(host), "drafts"), exist_ok=True)
        write(os.path.join(t.dir(host), "drafts", did + ".json"), json.dumps({
            "id": did, "title": title, "parent": host, "verdict": "start", "context": "fresh", "brief": brief,
            "gate": []}))
        r = t.cli(host, "draft", "--start", did)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.out = r.stdout
        folder = os.path.join(relay.nodes(t.p4)[coworker.draft_name(title, did)], "phi")
        with open(os.path.join(folder, [f for f in os.listdir(folder) if f.startswith("start-")][0]),
                  encoding="utf-8") as f:
            return f.read()

    def test_worker_for_writes_a_sessions_override_default_removes_it_and_a_bad_word_exits_2(self):
        t = self.t
        t.say(TOP, TASK)
        t.record(TOP2, title="the other top")
        t.say(TOP2, TASK)
        r = t.cli(TOP, "worker_for")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mode print (the default), profile p4-workers (the pair of print)", r.stdout)
        r = t.cli(TOP, "worker_for", "--mode", "interactive")
        self.assertIn("mode interactive (the session's workerMode), profile off (the pair of interactive)", r.stdout)
        self.assertEqual(t.session(TOP)["workerMode"], "interactive")
        self.assertEqual(phi.worker_settings(t.p4, TOP)["mode"], "interactive")
        self.assertEqual(phi.worker_settings(t.p4, TOP2)["mode"], "print", "another session's own")
        r = t.cli(TOP, "worker_for", "--profile", "p4-bill")
        self.assertIn("profile p4-bill (the session's workerProfile)", r.stdout)
        self.assertEqual(t.cli(TOP, "worker_for", "--profile", "off").returncode, 0)
        self.assertEqual(t.session(TOP)["workerProfile"], "")
        r = t.cli(TOP, "worker_for", "--session", TOP2, "--mode", "interactive")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(t.session(TOP2)["workerMode"], "interactive")
        r = t.cli(TOP, "worker_for", "--mode", "default", "--profile", "default")
        self.assertIn("mode print (the default)", r.stdout)
        self.assertNotIn("workerMode", t.session(TOP))
        self.assertNotIn("workerProfile", t.session(TOP))
        for args in (("--mode", "tab"), ("--profile", "bad name"), ("--session", "local_nobody", "--mode", "print")):
            bad = t.cli(TOP, "worker_for", *args)
            self.assertEqual(bad.returncode, 2, args)
            self.assertIn("phi:", bad.stderr)

    def test_two_sessions_of_one_store_start_their_workers_in_their_own_modes(self):
        t = self.t
        t.record(TOP2, title="the docs top")
        t.say(TOP, TASK)
        t.say(TOP2, TASK)
        self.assertEqual(t.cli(TOP, "worker_for", "--mode", "interactive").returncode, 0)
        self.assertEqual(t.cli(TOP2, "worker_for", "--mode", "print").returncode, 0)
        one = self.start(TOP, self.LAND, did="drf-0123456789")
        self.assertIn("mode interactive (the session's workerMode)", self.out)
        two = self.start(TOP2, self.LAND, did="drf-0123456790")
        self.assertIn("mode print (the session's workerMode)", self.out)
        self.assertNotIn("claude -p", one)
        self.assertIn("claude -p", two)

    def test_the_paired_defaults_and_the_explicit_profile_that_wins(self):
        t = self.t
        # PowerShell's `$env:ANTHROPIC_PROFILE = 'p4-workers'` or sh's `export ANTHROPIC_PROFILE=p4-workers`
        self.assertRegex(self.start(TOP, self.LAND), r"ANTHROPIC_PROFILE ?= ?'?p4-workers")
        self.assertIn("mode print (the piece of work), profile p4-workers (the pair of print)", self.out)
        self.setUp()
        t = self.t
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"worker_mode": "interactive"}))
        self.assertNotIn("ANTHROPIC_PROFILE", self.start(TOP, self.LAND))
        for mode in ("print", "interactive"):
            self.setUp()
            t = self.t
            write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"worker_mode": mode, "worker_profile": "p4-bill"}))
            self.assertIn("p4-bill", self.start(TOP, self.LAND), mode)
        self.setUp()
        t = self.t
        t.say(TOP, TASK)
        self.assertEqual(t.cli(TOP, "worker_for", "--profile", "off").returncode, 0)
        self.assertNotIn("ANTHROPIC_PROFILE", self.start(TOP, self.LAND))
        self.assertIn("profile off (the session's workerProfile)", self.out)

    def test_worker_mode_for_reads_the_piece_and_an_explicit_mode_overrides_it(self):
        import plans
        self.assertEqual(plans.worker_mode_for(self.LAND)[0], "print")
        self.assertEqual(plans.worker_mode_for(self.TEAM)[0], "interactive")
        self.assertEqual(plans.worker_mode_for(self.APPROVE)[0], "interactive")
        self.assertEqual(plans.worker_mode_for("Plan it.\nThis session starts in plan mode.\nFiles: none")[0], "print")
        self.assertEqual(plans.worker_mode_for("Fix it in a tab ezexe steers.")[0], "interactive")
        self.assertEqual(plans.worker_mode_for("Fix it in an interactive tab.")[0], "interactive")
        self.assertEqual(plans.worker_mode_for("Document worker_mode, print or interactive, and ExitPlanMode in the "
                                               "README.\nFiles: README.md")[0], "print",
                         "a landing brief that only names the modes lands headless")
        t = self.t
        t.say(TOP, TASK)
        self.assertEqual(phi.worker_settings(t.p4, TOP, self.TEAM)["mode"], "interactive")
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"worker_mode": "print"}))
        s = phi.worker_settings(t.p4, TOP, self.TEAM)
        self.assertEqual((s["mode"], s["mode_from"]), ("print", "phi.json worker_mode"))
        self.assertEqual(t.cli(TOP, "worker_for", "--mode", "interactive").returncode, 0)
        s = phi.worker_settings(t.p4, TOP, self.LAND)
        self.assertEqual((s["mode"], s["mode_from"]), ("interactive", "the session's workerMode"))

    def test_each_start_appends_one_row_with_its_settings_and_the_rules_reason(self):
        t = self.t
        self.start(TOP, self.TEAM, title="Review the ports table")
        (row,) = phi.read_rows(os.path.join(t.p4, "phi", "worker-starts.jsonl"))
        self.assertEqual((row["event"], row["mode"], row["profile"], row["starter"], row["mode_from"]),
                         ("start", "interactive", "", TOP, "the piece of work"))
        self.assertIn("agent team", row["reason"])
        self.assertTrue(row["report"].endswith(f"report-{row['name']}.md"))
        self.assertIn("mode interactive (the piece of work), profile off (the pair of interactive)", self.out)


class Parallel(Base):
    """The readings of an under-determined message run as the workflow the plugin ships, workflows/readings.js.
    p4-phi hands the line that names it and keeps nothing of a reading: no group, no session, no merge."""

    EITHER = ("Fix the narwhal exporter's flush: either buffer the rows in memory until the table closes or write "
              "each row straight to the store")
    def args_in(self, text):
        """The `args` a line gives the Workflow tool, read as the JSON it is."""
        return json.JSONDecoder().raw_decode(text.split("and `args` ")[1])[0]

    def test_an_under_determined_message_is_handed_the_workflow_and_no_start(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        ctx = context(t.say(TOP, self.EITHER))
        self.assertIn("under-determined, with 2 distinct readings", ctx)
        self.assertIn("run the plugin's workflow `/p4-phi:readings`", ctx)
        self.assertIn("the `Workflow` tool with `name` `p4-phi:readings`", ctx)
        self.assertEqual(self.args_in(ctx), {"words": "<the message, whole>", "readings": [
            "buffer the rows in memory until the table closes", "write each row straight to the store"]})
        self.assertNotIn("writes", ctx, "no reading is marked as one that writes")
        self.assertIn("Start no session for it", ctx)
        self.assertNotIn("`mcp__ccd_session__start_session` with {", ctx, "no start_session call for a reading")
        self.assertNotIn("Result:", ctx, "no reading is asked for a Result line")
        self.assertFalse(os.path.exists(os.path.join(t.dir(TOP), "readings")), "no group of readings is kept")
        self.assertFalse(os.path.exists(os.path.join(t.dir(TOP), "drafts")), "and no draft is made for a reading")
        rows = [json.loads(x) for x in read(os.path.join(t.dir(TOP), "log.jsonl")).splitlines() if x.strip()]
        self.assertEqual([r.get("puppeteer") for r in rows if r.get("hook") == "user-prompt-submit"][-1],
                         "readings", "the prompt hook's row says what routing did")

    def test_the_line_for_after_the_run_asks_ezexe_once_on_a_fork_and_starts_the_chosen_reading(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        ctx = context(t.say(TOP, self.EITHER))
        after = ctx.split("After the run: ")[1]
        self.assertIn("`collapsed` carries its `result` on as the answer, with no question to ezexe", after)
        self.assertIn("`forked` puts its one `question` to ezexe with `AskUserQuestion`", after)
        self.assertEqual(after.count("AskUserQuestion"), 1, "one question")
        self.assertIn("its `default` first", after)
        self.assertIn("the chosen reading then goes on as an ordinary child session", after)
        self.assertIn(f'{phi.commands()} draft "<the chosen reading>"', after)
        self.assertNotIn("source_branch", after)
        chosen = t.cli(TOP, "draft", "Make the narwhal exporter write each row of the flush straight to the store")
        self.assertIn("draft --start", chosen.stdout, "the chosen reading is an ordinary draft: " + chosen.stderr)

    def test_the_draft_command_hands_the_same_line(self):
        t = self.t
        t.say(TOP, TASK)
        r = t.cli(TOP, "draft", self.EITHER)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("run the plugin's workflow `/p4-phi:readings`", r.stdout)
        self.assertEqual(len(self.args_in(r.stdout)["readings"]), 2)
        self.assertNotIn("`mcp__ccd_session__start_session` with {", r.stdout)

    def test_a_start_draft_names_the_workflow_for_when_one_draft_would_guess(self):
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        ctx = context(t.say(TOP, RETRY))
        hint = ctx.split("If one draft would have to guess between distinct readings of the message")[1]
        self.assertIn("run the plugin's workflow `/p4-phi:readings`", hint)
        self.assertEqual(self.args_in(hint), {"words": "<the message, whole>",
                                               "readings": ["<reading one>", "<reading two>"]})
        self.assertIn("After the run: ", hint)
        self.assertNotIn(" readings \"<reading one>\"", ctx, "no command of phi.py drafts readings")

    def test_the_line_names_the_workflow_the_plugin_ships(self):
        plugin = os.path.dirname(SRC)
        name = json.loads(read(os.path.join(plugin, ".claude-plugin", "plugin.json")))["name"]
        script = read(os.path.join(plugin, "workflows", "readings.js"))
        meta = re.search(r"name: '([^']+)'", script.split("}", 1)[0]).group(1)
        self.assertEqual(puppeteer.READINGS, f"{name}:{meta}", "workflows.md: a plugin workflow runs as /<plugin>:<name>")

    def test_a_first_message_keeps_its_draft_and_no_reading(self):
        """A brief an earlier version drafted for a reading still carries its line. The draft it names is kept, and
        the session is no reading: nothing reads that line any more."""
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed(f"# Reading 1 of 2\n\nReport when done.\n\nphi draft drf-0123456789 for {TOP}.\n"
                          f"phi reading grp-0123456789 1 of 2 for {TOP}."))
        self.assertEqual(t.session(KID)["draft"], "drf-0123456789")
        self.assertNotIn("reading", t.session(KID))
        text, _ = self.ledger()
        self.assertNotIn("## Readings", text)
        self.assertNotIn("reading 1 of", text)


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
            os.replace, wait = refuse, puppeteer.REPLACE_S
            puppeteer.REPLACE_S = 0                # a replace refused for good: no waiting it out
            try:
                with self.assertRaises(OSError):
                    puppeteer._write(path, "{}")
            finally:
                os.replace, puppeteer.REPLACE_S = real, wait
            self.assertEqual(os.listdir(os.path.dirname(path)), [])
            puppeteer._write(path, "{}")
            self.assertEqual(os.listdir(os.path.dirname(path)), ["app-index.json"])


class Look(Base):
    """The watcher runs from the plugin's hooks module: "`$.clock.every` and `$.clock.after` take the place of
    `setInterval` and `setTimeout`" and "The timer's callback runs outside any event, so it keeps running between
    turns and doesn't start one.", https://code.claude.com/docs/en/plugins/mods/api.md. The module starts
    `phi.py look`, one pass over an orchestrator's subtree that ends, and paces itself by what the look answers. No
    hook starts a process, and nothing of the detached watcher is left."""

    def look(self, host=TOP, *args, **env):
        env = self.t.env(host, **{"P4_PHI_WATCH": "1", "P4_PHI_WATCH_NET": "0", **env})
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look", *args],
                       capture_output=True, text=True, env=env, cwd=self.t.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def files(self):
        """Every file and folder of the store with its size and time."""
        out = {}
        for root, dirs, names in os.walk(self.t.p4):
            for n in dirs + names:
                st = os.stat(os.path.join(root, n))
                out[os.path.relpath(os.path.join(root, n), self.t.p4)] = (st.st_size, st.st_mtime_ns)
        return out

    def test_a_look_is_one_pass_that_writes_the_ledger_and_answers_what_the_module_paces_by(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        got = self.look()
        self.assertEqual((got["watching"], got["changed"], got["net"]), (True, True, False))
        self.assertEqual(os.path.normcase(os.path.normpath(got["dir"])), os.path.normcase(t.dir(TOP)))
        self.assertEqual((got["watch_s"], got["wait_s"], got["net_s"]), (5.0, 5.0, 120.0),
                         "a look every phi.watch_s seconds at most, and GitHub read every two minutes")
        self.assertIn(f"`{KID}`: working", read(self.path(TOP, "ledger.md")), "written in, with no command run")
        before = os.stat(self.path(TOP, "ledger.md")).st_mtime_ns
        again = self.look()
        self.assertEqual((again["watching"], again["changed"]), (True, False))
        self.assertEqual(os.stat(self.path(TOP, "ledger.md")).st_mtime_ns, before, "rewritten only on a change")
        old = time.time() - puppeteer.WATCH_CALM_S - 5
        os.utime(self.path(TOP, "ledger.sig"), (old, old))
        self.assertEqual(self.look()["wait_s"], 30.0, "the slow tick once nothing changed for ten minutes")
        quick = self.look(P4_PHI_WATCH_S="0.3")
        self.assertEqual((quick["watch_s"], quick["wait_s"]), (0.3, 0.3), "P4_PHI_WATCH_S is the tick for one run")
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"watch_s": 12}}))
        try:
            self.assertEqual(self.look()["watch_s"], 12.0, "phi.watch_s of the orchestrator's own store")
        finally:
            os.remove(os.path.join(t.p4, "p4.json"))
            phi.project_conf(t.p4)

    def test_a_session_with_nothing_to_watch_pays_one_cheap_check(self):
        t = self.t
        t.say(TOP, TASK)
        t.record(GRAND, title="a session with no task")
        t.hook("session-start", GRAND, {"hook_event_name": "SessionStart", "source": "startup"})
        before = self.files()
        kid = self.look(GRAND)
        self.assertEqual((kid["watching"], kid["why"], kid["wait_s"]), (False, "no orchestrator", 30.0))
        self.assertNotIn("changed", kid, "no pass over a subtree")
        self.assertFalse(os.path.exists(self.path(GRAND, "ledger.md")))
        off = self.look(P4_PHI_WATCH="0")
        self.assertEqual((off["watching"], off["off"]), (False, True), "P4_PHI_WATCH=0 keeps every look from running")
        self.assertEqual(self.look(P4_PHI="0")["off"], True)
        self.assertEqual(self.look(P4_PHI_PUPPETEER="0")["why"], "the puppeteer steps are off")
        only = self.look(TOP, "--folder", P4_PHI_WATCH="0")
        self.assertEqual(list(only), ["dir", "watching"], "where the session's folder is, and nothing else")
        self.assertEqual(self.files(), before, "none of them wrote a file")

    def test_a_look_answers_a_workers_starter_as_the_address_the_module_sends_its_report_to(self):
        """ezexe/p4#157: the hooks module sends a worker's report to the session that started it with
        `$.session.send({ to: { sessionId } })`, whose `sessionId` is "what its `$.session.id()` answers on this
        machine", by the API's types. That is the CLI session id on the app's record of the starter, so every look
        of a started session answers it, the one that only asks for the folder too. A session nobody started
        answers none, and neither does a puppeteer's worker, whose first line asks it for the message its
        turn ends with."""
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        self.assertEqual(self.look(KID)["starter"], CLI[TOP])
        only = self.look(KID, "--folder", P4_PHI_WATCH="0")
        self.assertEqual((list(only), only["starter"]), (["dir", "starter", "watching"], CLI[TOP]))
        self.assertNotIn("starter", self.look(), "nobody started the orchestrator")
        with open(os.path.join(t.app, TOP + ".json"), encoding="utf-8") as f:
            rec = json.load(f)
        rec["cliSessionId"] = "cccc3333-0000-4000-8000-000000000000"   # the starter runs under a new id since a clear
        write(os.path.join(t.app, TOP + ".json"), json.dumps(rec))
        self.assertEqual(self.look(KID)["starter"], "cccc3333-0000-4000-8000-000000000000")
        rec.pop("cliSessionId")                     # no record names one: the last its session.json holds
        write(os.path.join(t.app, TOP + ".json"), json.dumps(rec))
        self.assertEqual(self.look(KID)["starter"], CLI[TOP])

    def test_a_look_on_a_deleted_session_folder_writes_nothing_and_makes_no_folder(self):
        """ezexe/p4#206: a session folder that is gone gets no look, and one deleted while a look runs is not made
        again by any write of that look."""
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        self.assertTrue(self.look()["watching"])
        shutil.rmtree(t.dir(TOP))
        before = self.files()
        gone = self.look()
        self.assertEqual((gone["watching"], gone["why"]), (False, "no session folder"))
        self.assertNotIn("dir", gone)
        self.assertEqual(self.look(TOP, "--folder"), {"watching": False, "why": "no session folder", "watch_s": 5.0,
                                                      "wait_s": 30.0, "net_s": 120.0})
        self.assertEqual(self.files(), before, "nothing written, and no folder made")
        self.assertFalse(os.path.exists(t.dir(TOP)))

    def test_a_session_folder_deleted_while_its_look_runs_stays_gone(self):
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer."))
        t.stop(KID, "Port the flush", report="Ported; the suite passes.")       # a source changed: the look rebuilds
        real = puppeteer.build

        def build_then_delete(home, top, net=False):
            m = real(home, top, net)
            shutil.rmtree(t.dir(TOP))               # deleted in the middle of the look, ahead of its writes
            return m
        env = {"P4_PHI_APP_SESSIONS": os.path.join(t.tmp, "app"), "P4_PHI_WATCH": "1", "P4_PHI_WATCH_NET": "0"}
        with mock.patch.object(puppeteer, "build", build_then_delete), mock.patch.dict(os.environ, env):
            os.environ.pop("P4_PHI", None)
            got = puppeteer.look(t.p4, TOP, net=True)
        self.assertEqual((got["watching"], got["why"]), (False, "no session folder"))
        self.assertFalse(os.path.exists(t.dir(TOP)), "no write of the look brought the folder back")
        self.assertEqual(puppeteer._LOOKED, [""], "the guard ends with the look")

    def test_a_look_makes_a_folder_below_its_session_folder_only_while_that_folder_stands(self):
        folder = self.t.dir(TOP)
        os.makedirs(folder)
        puppeteer._LOOKED[0] = os.path.normcase(os.path.abspath(folder))
        try:
            puppeteer._write_json(os.path.join(folder, "readings", "grp-1.json"), {"id": "grp-1"})
            self.assertEqual(jload(os.path.join(folder, "readings", "grp-1.json")), {"id": "grp-1"})
            puppeteer._write(os.path.join(self.t.p4, "phi", ".cache", "app-index.json"), "{}")     # a file of the store
            shutil.rmtree(folder)
            for path in (os.path.join(folder, "ledger.md"), os.path.join(folder, "readings", "grp-2.json"),
                         os.path.join(self.t.p4, "phi", ".routes-checked")):
                with self.assertRaises(FileNotFoundError):
                    puppeteer._write(path, "x")
            with self.assertRaises(FileNotFoundError):
                puppeteer._append(os.path.join(folder, "routes.jsonl"), {"kind": "route"})
        finally:
            puppeteer._LOOKED[0] = ""
        self.assertFalse(os.path.exists(folder))
        self.assertFalse(os.path.exists(os.path.join(self.t.p4, "phi", ".routes-checked")))

    def test_the_slow_pass_runs_only_when_the_ledger_changed_or_the_look_is_a_slow_one(self):
        """A look is a fresh process, so it holds no clock of its own: the module asks for the slow pass, which
        registers and checks the routes and reads GitHub, once every `net_s` seconds."""
        t = self.t
        t.say(TOP, TASK)
        self.look()
        ran = []
        with mock.patch.object(puppeteer, "register_routes", lambda *a, **k: ran.append("register") or []), \
                mock.patch.object(puppeteer, "check_routes", lambda *a, **k: ran.append("check") or []):
            self.assertFalse(puppeteer.tick(t.p4, TOP, net=False, slow=False))
            self.assertEqual(ran, [], "nothing changed and the look is no slow one")
            puppeteer.tick(t.p4, TOP, net=False, slow=True)
            self.assertEqual(ran, ["register", "check"])

    def test_no_hook_starts_a_process_and_nothing_of_the_detached_watcher_is_left(self):
        t = self.t
        self.assertNotIn("watch", puppeteer.COMMANDS)
        self.assertIn("look", puppeteer.COMMANDS)
        for text in (read(os.path.join(SRC, "phi.py")), read(os.path.join(SRC, "puppeteer.py"))):
            self.assertNotIn("Popen", text, "no script of the session tree leaves a process behind for a watcher")
        t.hook("session-start", TOP, {"hook_event_name": "SessionStart", "source": "startup"}, P4_PHI_WATCH="1")
        t.say(TOP, TASK, P4_PHI_WATCH="1")
        t.stop(TOP, TASK, report="planned", P4_PHI_WATCH="1")
        self.assertFalse(os.path.exists(self.path(TOP, "watcher.json")))
        self.assertEqual([x for x in t.log(TOP) if x.get("watcher")], [])
        hooks = os.path.join(os.path.dirname(SRC), "hooks")
        self.assertEqual(jload(os.path.join(hooks, "hooks.json"))["modules"], ["./register.ts"])
        module = read(os.path.join(hooks, "register.ts"))
        for call in ("$.clock.every(", "$.process.run(", "on('turn.complete'", "on('session.receive'", "'look'"):
            self.assertIn(call, module, "the watcher's timer, events and look are the hooks module's")



class CheckoutLines(unittest.TestCase):
    def test_a_brief_with_nothing_shared_holds_the_checkout_lines_alone(self):
        cmd = phi.commands()
        want = [line.replace("{cmd}", cmd) for line in puppeteer.CHECKOUT_LINES] + [""]
        self.assertEqual(len(puppeteer.CHECKOUT_LINES), 3)
        self.assertEqual(puppeteer.checkout_lines(), want)
        self.assertEqual(puppeteer.checkout_lines(tempfile.mkdtemp()), want)
        self.assertIn("`Files:` line", want[1])
        self.assertIn(f"{cmd} commit -m", want[2])
        self.assertNotIn("worktree of its own", " ".join(want))


class NodeStores(unittest.TestCase):
    """The watcher reads the sessions of every store of the tree: a node's as the root's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "proj", ".claude", "p4")
        write(os.path.join(self.home, "phi", "sessions", TOP, "session.json"), json.dumps({"sessionId": TOP}))
        import relay
        self.store = relay.claim(self.home, self.home, KID, "session", TOP)
        self.kid = os.path.join(self.store, "phi", "sessions", KID)
        write(os.path.join(self.kid, "session.json"), json.dumps({"sessionId": KID, "spawnedFrom": {"sessionId": TOP}}))

    def test_the_signature_changes_when_a_nested_session_json_changes(self):
        before = puppeteer.signature(self.home, TOP, [])
        self.assertEqual(puppeteer.signature(self.home, TOP, []), before)
        time.sleep(0.05)
        write(os.path.join(self.kid, "session.json"),
              json.dumps({"sessionId": KID, "title": "the kid", "spawnedFrom": {"sessionId": TOP}}))
        self.assertNotEqual(puppeteer.signature(self.home, TOP, []), before)

    def test_all_routes_reads_a_nested_routes_jsonl(self):
        row = {"kind": "route", "id": "r1", "session": KID, "issue": "ezexe/demo#7"}
        write(os.path.join(self.kid, "routes.jsonl"), json.dumps(row) + "\n")
        got = puppeteer.all_routes(self.home)
        self.assertEqual(list(got), ["r1"])
        self.assertTrue(os.path.normcase(got["r1"]["file"]).startswith(os.path.normcase(self.store)))


if __name__ == "__main__":
    unittest.main()
