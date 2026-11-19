#!/usr/bin/env python3
"""puppeteer.py: routing, the start draft, the gate and the watcher, run through p4-phi's own hooks and commands.

    python -m pytest tests/p4-phi/test_puppeteer.py

Checked, one diagram of ezexe/p4's README.md a class:
linear: the ledger an orchestrator's watcher writes holds a row for each live session of its subtree, is rewritten
only when a source changed, and leads with a reconcile line when the app archived a session p4-phi lists or shows a
child p4-phi does not hold; the watcher is one look at a time, `phi.py look`, which the plugin's hooks module starts
and which ends, and no hook starts a process; a message of ezexe's that is work is drafted from ezexe's words and gate-checked into the exact
start_session call, a worker's with `use_worktree: true` whatever a running writer edits, or into a SendMessage to the
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
import phi  # noqa: E402
import puppeteer  # noqa: E402
import starts  # noqa: E402
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


def flat_(text):
    return " ".join(str(text or "").split())


def runs_of(sent, text, n=8):
    """The runs of `n` words of `sent` that `text` holds, compared word by word with case and punctuation dropped."""
    words = lambda x: re.findall(r"[a-z0-9']+", str(x).lower())
    have = " " + " ".join(words(text)) + " "
    w = words(sent)
    return [" ".join(w[k:k + n]) for k in range(len(w) - n + 1) if " " + " ".join(w[k:k + n]) + " " in have]


def call_in(ctx, k=0):
    """The k-th exact start_session input a hook's text carries."""
    piece = ctx.split("`mcp__ccd_session__start_session` with ")[k + 1]
    return json.JSONDecoder().raw_decode(piece)[0]


class Base(unittest.TestCase):
    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
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
        self.assertEqual((call["initiation"], call["context"], call["use_worktree"]), ("user_asked", "fresh", True),
                         "a worker's draft writes, so it gets a git worktree and a branch of its own")
        self.assertIn(puppeteer.WORKTREE_LINE, call["prompt"], "its brief says where it works and who lands it")
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
        import prompty_eval
        t.stop(TOP, RETRY, report="Started a session for it.", uuid="u-retry")
        got = [(e["label"], e["kind"]) for e in prompty_eval.examples(t.p4)
               if e["case"] == "others" and e["session"] == TOP and flat_(e["message"]) == RETRY]
        self.assertEqual(got, [("", "new")], "a session started from the message's draft labels it new")
        other = context(t.say(TOP, "Write a changelog generator for the billing dashboard's release notes"))
        self.assertIn("so it is a new orchestrator", other)
        self.assertIn(phi.NEW_TOP_BRIEF, call_in(other)["prompt"])
        self.assertIs(call_in(other)["use_worktree"], False, "a new orchestrator lands in this checkout")
        self.assertNotIn(puppeteer.WORKTREE_LINE, call_in(other)["prompt"])

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
        at = re.search(r"Files: `([^`]+)/x\.py`", prompt).group(1)      # the folder as the Files line spells it
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
        self.assertNotIn("Files:", prompt)
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
        self.assertNotIn("Files:", prompt)
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
        self.assertNotIn("Files:", prompt)
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
        self.assertIn("restate", ctx, "the session that makes the call is told to state the task in its own words")

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
        import ast
        for name in ("phi.py", "controls.py", "puppeteer.py", "issues.py"):
            tree = ast.parse(read(os.path.join(SRC, name)))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                    self.assertIsNone(asks.search(n.value), f"{name}:{n.lineno} {n.value[:120]}")

    def test_a_draft_whose_files_a_running_writer_edits_is_started_in_a_worktree_and_never_queued(self):
        """The queue behind a busy writer is gone: a draft that names a file a running writer is at work on is
        handed as a start at once, with `use_worktree: true`, since that worker writes in a git worktree of its own
        and shares no file on disk with the running writer. The gate names no writer, keeps no start request, and
        `pioneer` prints the same verdict again."""
        t = self.t
        t.record(TOP2, title="the docs top")
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
        self.assertIs(call["use_worktree"], bool(draft["parent"]), "a worker's draft in a worktree of its own")
        worker = puppeteer.call_of({**draft, "parent": TOP})
        self.assertIs(worker["use_worktree"], True, "whatever a running writer edits")
        r = t.cli(TOP, "pioneer", did)
        self.assertIn("Start it now: `mcp__ccd_session__start_session` with ", r.stdout)
        self.assertNotIn("queued", r.stdout + r.stderr)
        self.assertEqual(starts.state(t.p4), {}, "no start request is kept")
        text, _ = self.ledger()
        self.assertNotIn("waits behind", text)
        for name in ("queue", "busy"):
            self.assertFalse(hasattr(puppeteer, name), name)


class WorkerSplit(Base):
    """A worker splits at its first message, while the app still lets it start sessions: a part that writes files
    or decides runs in a session of its own, and a subagent that wrote files is a level miss on the ledger."""

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
        self.assertNotIn("start request", first, "the card holds it, and p4-phi keeps no request for it")
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
        self.assertIn("the built-in subagent `Explore`, with `model` `haiku` on the Agent call",
                      ctx.split("can each run on their own")[1])

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

    def test_a_workflows_agent_that_wrote_in_the_worktree_its_run_gave_it_is_no_level_miss(self):
        """The hook input is the one a run of /p4-phi:readings raised on Claude Code 2.1.326: SubagentStart and
        SubagentStop fire for a workflow's agent with `agent_type` `workflow-subagent`, and no Agent call comes
        before them. A reading that writes runs in the folder `.claude/worktrees/wf_<run id>-<n>`."""
        t = self.t
        t.say(TOP, TASK)
        t.say(KID, handed("Port the flush to the new writer. Report when done."))
        self.plan(KID, {"items": [{"content": "Port the flush", "status": "in_progress"}], "scope": "first_task"})
        tree = os.path.join(t.proj, ".claude", "worktrees", "wf_9bd8d43e-c60-1")
        for agent, path in (("agwf1", os.path.join(tree, "src", "export", "flush.py")),
                            ("agwf2", os.path.join(t.proj, "src", "export", "table.py"))):
            self.recall(KID, "subagent-start", {"hook_event_name": "SubagentStart", "agent_id": agent,
                                                "agent_type": "workflow-subagent"})
            log = os.path.join(t.tmp, f"agent-{agent}.jsonl")
            transcript(log, "work the reading", [("Write", {"file_path": path, "content": "x"}, "ok")], "done")
            self.recall(KID, "subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": agent,
                                               "agent_type": "workflow-subagent", "agent_transcript_path": log})
        tasks = {x["id"]: x for st in jload(self.path(KID, "plan.json"))["steps"] for x in st.get("tasks", [])}
        self.assertEqual({k: v["status"] for k, v in tasks.items()}, {"agwf1": "completed", "agwf2": "completed"},
                         "each agent of the run is bound to the step in progress and closed at its stop")
        text, _ = self.ledger()
        miss = text.split("## Level misses")[1]
        self.assertNotIn("agwf1", miss, "a write inside the worktree the run gave the agent is no miss")
        self.assertIn("agwf2", miss, "a write in the session's own checkout still is")
        self.assertIn("table.py", miss)


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

    def test_a_start_draft_carries_the_decide_by_research_line(self):
        """A writing start whose message names its files and one whose message names none both carry the
        decide-by-research sentence. The second has no `Files:` line, since a brief that writes claims no empty
        set of files."""
        t = self.t
        t.say(TOP, TASK)
        t.stop(TOP, TASK, report="planned")
        writing = call_in(context(t.say(TOP, "Add a retry to `src/export/flush.py` for when the ports table write "
                                            "fails")))["prompt"]
        self.assertRegex(writing, r"Files: `[^`]*src/export/flush\.py`")
        self.assertIn(phi.DECIDE, writing)
        t.stop(TOP, "retry", report="drafted")
        none = call_in(context(t.say(TOP, RETRY)))["prompt"]
        self.assertNotIn("Files:", none)
        self.assertIn(phi.DECIDE, none)
        self.assertIn("decisions.md", phi.DECIDE)

    def test_the_decide_line_does_not_change_a_starts_model_or_effort(self):
        """Its words "documentation" and "decisions.md" are no sign of docs work: a reading's start is levelled as
        if the line were not there."""
        words = "Should the exporter buffer rows in memory or write each one to the store"
        brief = "# Reading 1 of 2\n\nTask: Reading 1 of 2.\n\n{}Done looks like: the reading worked through."
        bare = {"title": "Reading 1 of 2", "words": words, "context": "fresh", "background": "x", "brief":
                brief.format("")}
        with_line = dict(bare, brief=brief.format(phi.DECIDE + "\n\n"))
        got, want = puppeteer.call_of(with_line), puppeteer.call_of(bare)
        self.assertEqual((got.get("model"), got.get("effort")), (want.get("model"), want.get("effort")))
        self.assertIn(phi.DECIDE, got["prompt"], "the line itself still reaches the child")

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
        for name in ("process_rows", "left_processes", "PS_S", "PROCESSES"):
            self.assertFalse(hasattr(puppeteer, name), name)
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
    """The readings of an under-determined message run as the workflow the plugin ships, workflows/readings.js.
    p4-phi hands the line that names it and keeps nothing of a reading: no group, no session, no merge."""

    EITHER = ("Fix the narwhal exporter's flush: either buffer the rows in memory until the table closes or write "
              "each row straight to the store")
    GONE = ("explore", "explore_text", "groups_dir", "load_groups", "save_group", "rebind", "carriers", "result_of",
            "lost", "same_result", "merge", "lost_words", "group_line", "merge_text", "merge_all", "READING_RE",
            "RESULT_RE", "shares_run")

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
        self.assertIn('{"text": "<the reading>", "writes": true}', ctx, "a reading that writes is marked for a worktree")
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
        self.assertIn("`source_branch` set to the `branch` that reading returned", after)
        chosen = t.cli(TOP, "draft", "Make the narwhal exporter write each row of the flush straight to the store")
        self.assertIn("Start it now: `mcp__ccd_session__start_session` with ", chosen.stdout,
                      "the chosen reading is an ordinary draft: " + chosen.stderr)

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

    def test_the_explore_and_merge_machinery_is_gone(self):
        t = self.t
        for name in self.GONE:
            self.assertFalse(hasattr(puppeteer, name), name)
        for cmd in ("readings", "merge"):
            self.assertNotIn(cmd, puppeteer.COMMANDS)
        t.say(TOP, TASK)
        r = t.cli(TOP, "readings", "keep the table in the store", "keep the table in a file beside it")
        self.assertEqual(r.returncode, 2, "phi.py has no readings command")
        self.assertIn("invalid choice", r.stderr)
        r = t.cli(TOP, "merge", "grp-0123456789")
        self.assertEqual(r.returncode, 2, "phi.py has no merge command")
        for name in ("phi.py", "puppeteer.py", "issues.py"):
            source = read(os.path.join(SRC, name))
            for gone in ("Result: <", "phi reading ", '"readings", "*.json"', '.get("reading")'):
                self.assertNotIn(gone, source, f"{name} holds {gone!r}")

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
        t.say(KID, handed("Port the flush to the new writer."))
        before = self.files()
        kid = self.look(KID)
        self.assertEqual((kid["watching"], kid["why"], kid["wait_s"]), (False, "no orchestrator", 30.0))
        self.assertNotIn("changed", kid, "no pass over a subtree")
        self.assertFalse(os.path.exists(self.path(KID, "ledger.md")))
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
        answers none, and neither does a puppeteer's standing worker, whose first line asks it for the message its
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
        path = self.path(KID, "session.json")
        kid = json.loads(read(path))
        kid["standingKind"] = "worker"
        write(path, json.dumps(kid))
        self.assertNotIn("starter", self.look(KID), "a standing worker writes its own closing message")

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
        for name in ("ensure_watcher", "watcher_alive", "watcher_path", "code_stamp", "watch", "BEAT_DEAD_S",
                     "WATCH_QUIT_S"):
            self.assertFalse(hasattr(puppeteer, name), name)
        self.assertFalse(hasattr(phi, "watch_over"))
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


if __name__ == "__main__":
    unittest.main()
