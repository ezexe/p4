#!/usr/bin/env python3
"""issues.py (#28): a writing child's one loop of issue, `Closes #N`, a proving test, push and archive, run through
phi's own hooks with a stand-in for `gh`.

    python3 -I lbiza/plugins/p4-phi/scripts/test_issues.py

The stand-in files issue #7 on create, answers `issue view` from a state file the test writes (GitHub closing the
issue when the `Closes #7` commit is pushed), and logs every call. The work repository's `origin` reads as GitHub
and pushes to a bare repository beside it.
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
import issues  # noqa: E402
from test_phi import GRAND, KID, KID2, TOP, Tree, context, write  # noqa: E402

A, B = KID, KID2
FAKE_GH = r'''
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["issue", "create"]:
    print("https://github.com/ezexe/demo/issues/7")
elif args[:2] == ["issue", "view"]:
    p = os.path.join(d, "state.json")
    states = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    print(states.get(args[2], "OPEN"))
elif args[:2] == ["issue", "comment"]:
    print("https://github.com/ezexe/demo/issues/7#issuecomment-1")
else:
    sys.exit(1)
'''


class GhTree(Tree):
    def __init__(self, tmp, gh):
        super().__init__(tmp)
        self.gh = gh

    def env(self, host, proj=None, **more):
        return super().env(host, proj, P4_PHI_GH=self.gh, **more)


def items(*steps, status="pending"):
    return {"items": [{"content": c, "status": status} for c in steps]}


class Loop(unittest.TestCase):
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
        t.record(TOP, title="top")
        t.record(A, TOP, title="the x fix")
        t.record(B, TOP, title="the x check")
        t.record(GRAND, TOP, title="the plain fix")
        self.work = os.path.join(t.proj, "work").replace("\\", "/")
        self.bare = os.path.join(tmp, "bare.git").replace("\\", "/")
        self.plain = os.path.join(tmp, "plain").replace("\\", "/")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        write(os.path.join(self.plain, "a.py"), "a = 1\n")
        subprocess.run(["git", "init", "-q", "--bare", self.bare], check=True, capture_output=True)
        for repo in (self.work, self.plain):
            for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "one")):
                self.git(repo, *args)
        self.git(self.work, "remote", "add", "origin", "https://github.com/ezexe/demo.git")
        self.git(self.work, "remote", "set-url", "--push", "origin", self.bare)
        self.assertEqual(t.say(TOP, "Build the demo").returncode, 0)

    def tearDown(self):
        os.environ.pop("FAKE_GH_DIR", None)
        self._tmp.cleanup()

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                              capture_output=True, text=True)

    def calls(self):
        p = os.path.join(self.ghdir, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(x) for x in f]

    def plan(self, host, inp):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated.", "cwd": self.work})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def start_writer(self):
        ctx = context(self.t.say(A, f"Fix the off-by-one in {self.work}/lib/x.py and commit it. Archive when done."))
        self.assertIn("ezexe/demo#7", ctx)
        return ctx

    def commit(self, msg, text="x = 2\n"):
        write(os.path.join(self.work, "lib", "x.py"), text)
        self.git(self.work, "commit", "-qam", msg)

    def proving_test(self, ok):
        write(os.path.join(self.work, "test_x.py"), "import sys\nsys.exit(%d)\n" % (0 if ok else 1))
        self.git(self.work, "add", "test_x.py")
        exe = sys.executable.replace("\\", "/")
        return f"Run `\"{exe}\" -I test_x.py` to prove the fix"

    def finish(self, test_step):
        self.plan(A, items("Fix x", test_step, status="completed"))

    def stop(self, uuid):
        r = self.t.stop(A, "finish", report="Fixed x; the test passes.", uuid=uuid)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def test_a_writing_child_in_a_github_repo_gets_an_issue_and_the_others_none(self):
        ctx = self.start_writer()
        self.assertIn("filed now", ctx)
        self.assertIn("Closes #7", ctx)
        iss = self.t.session(A)["issue"]
        self.assertEqual((iss["repo"], iss["number"]), ("ezexe/demo", 7))
        made = [c for c in self.calls() if c[:2] == ["issue", "create"]]
        self.assertEqual(len(made), 1)
        body = made[0][made[0].index("--body") + 1]
        self.assertIn(TOP, body, "the parent's id is in the body")
        self.assertIn("off-by-one", body, "the brief is in the body")
        self.assertNotIn("#7", context(self.t.say(B, f"Check what {self.work}/lib/x.py does and report it.")))
        self.assertNotIn("issue", self.t.session(B), "a read-only child gets no issue")
        self.assertNotIn("#7", context(self.t.say(GRAND, f"Fix the bug in {self.plain}/a.py and commit it.")))
        self.assertNotIn("issue", self.t.session(GRAND), "a repo with no GitHub remote gets none")
        self.assertEqual(len([c for c in self.calls() if c[:2] == ["issue", "create"]]), 1)

    def test_a_reading_gets_no_issue_record(self):
        """#44: reading 2 of the live proof got ezexe/p4#40 and #42; a reading explores and commits nothing."""
        brief = (f"# Reading 2: count the rows\n\nThis session takes one reading of those words, reading 2 of 2: fix "
                 f"the count in {self.work}/lib/x.py\nA reading explores: change no tracked file and commit nothing, "
                 f"since the readings beside this one share the checkout.\nArchive when done.\n\n"
                 f"phi draft drf-0123456789 for {TOP}.\nphi reading grp-0123456789 2 of 2 for {TOP}.")
        ctx = context(self.t.say(A, brief))
        self.assertNotIn("#7", ctx)
        self.assertNotIn("issue", self.t.session(A))
        self.plan(A, items("Fix the count in lib/x.py", "Report the result"))
        self.assertNotIn("issue", self.t.session(A), "nor at its plan")
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])
        self.assertFalse(issues.writing("Fix x.py. A reading explores: change no tracked file and commit nothing."))

    def test_an_issue_title_ends_at_a_clause_or_is_the_briefs_title_line(self):
        """#44, #45: titles were cut with dots in the middle of a sentence."""
        self.t.record(A, TOP, title="Fix the off-by-one in the exporter that drops the last row of the ports table when the ...")
        context(self.t.say(A, f"Fix the off-by-one in the exporter that drops the last row of the ports table when the "
                              f"table closes early, in {self.work}/lib/x.py, and commit it. Archive when done."))
        made = [c for c in self.calls() if c[:2] == ["issue", "create"]]
        title = made[0][made[0].index("--title") + 1]
        self.assertEqual(title, "Fix the off-by-one in the exporter that drops the last row of the ports table")
        self.assertEqual(issues.issue_title("a cut session title ...", "# The x fix, whole\n\nFix lib/x.py."),
                         "The x fix, whole", "the brief's title line")
        self.assertNotIn("...", issues.issue_title("", "Fix " + "the very long thing " * 12))

    def test_the_repository_the_brief_names_wins_over_the_checkouts_origin(self):
        """#45: "Fix the issues on ezexe/p4 ... the code is in <proj>/p4/..." filed ezexe/p4-phi#1 and #2, on the
        origin of the project the session ran in, because "ezexe/p4" was read as a path there."""
        proj = self.t.proj.replace("\\", "/")
        write(os.path.join(proj, "top.py"), "t = 1\n")
        for args in (("init", "-q", "-b", "main"), ("add", "top.py"), ("commit", "-qm", "one"),
                     ("remote", "add", "origin", "https://github.com/ezexe/demo-outer.git")):
            self.git(proj, *args)
        brief = (f"Fix the open issues on ezexe/demo in this order, one at a time. Read each with gh issue view N -R "
                 f"ezexe/demo. The code is in {self.work}/lib, on branch main. Commit each fix.")
        got = issues.repos_named(brief, proj)
        self.assertEqual(got[0][1], "ezexe/demo", got)
        self.assertNotIn("ezexe/demo-outer", [slug for _, slug in got], "an owner/name token is no path in the cwd")
        self.assertEqual(issues.repos_named("Fix the bug the README of ezexe/demo describes, in top.py", proj)[0][1],
                         "ezexe/demo", "named by its slug, found nested under the cwd")
        self.assertEqual(issues.repos_named("Fix top.py and commit it", proj)[0][1], "ezexe/demo-outer")
        self.assertEqual(issues.slugs_said("see ezexe/p4-phi#2, then gh issue view 4 -R ezexe/p4."),
                         ["ezexe/p4-phi", "ezexe/p4"])
        self.assertEqual(issues.slugs_said("on ezexe/p4-phi only"), ["ezexe/p4-phi"], "never ezexe/p4 out of it")
        ctx = context(self.t.hook("user-prompt-submit", A, {"hook_event_name": "UserPromptSubmit", "prompt": brief,
                                                            "cwd": proj}))
        self.assertIn("ezexe/demo#7", ctx)
        self.assertEqual(self.t.session(A)["issue"]["repo"], "ezexe/demo")

    def test_done_names_the_issue_and_what_it_still_owes(self):
        """#45: `phi.py done` named no issue as closable."""
        self.start_writer()
        r = self.t.cli(A, "done", "ran test_x.py and it passed", proj=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("this session closes ezexe/demo#7", r.stdout)
        self.assertIn("a commit that says `Closes #7`", r.stdout)
        self.assertIn("phi.py proof", r.stdout)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(self.proving_test(True))
        r = self.t.cli(A, "done", "ran test_x.py and it passed", proj=self.work)
        self.assertIn("says `Closes #7`", r.stdout)
        self.assertIn("Still owed before it closes: the push of", r.stdout)
        self.assertNotIn("a commit that says", r.stdout)
        self.t.say(B, f"Check what {self.work}/lib/x.py does for ezexe/demo#3 and ezexe/demo#4 and report it.")
        r = self.t.cli(B, "done", "read x.py and reported it", proj=self.work)
        self.assertIn("its task names ezexe/demo#3, ezexe/demo#4", r.stdout)

    def test_an_issue_the_brief_names_is_taken_not_filed_again(self):
        ctx = context(self.t.say(A, f"Build ezexe/demo issue #3: fix {self.work}/lib/x.py. Archive when done."))
        self.assertIn("ezexe/demo#3", ctx)
        self.assertIn("named in its brief", ctx)
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])

    def test_a_brief_naming_only_closed_issues_files_none(self):
        """#39: a queue's brief named #28, closed by then, and its plan filed a new issue for work already filed."""
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"3": "CLOSED", "4": "CLOSED"}))
        ctx = context(self.t.say(A, f"Fix ezexe/demo issue #3, then #4 in {self.work}/lib/x.py. Archive when done."))
        self.plan(A, items("Fix x", "Fix y"))
        self.assertNotIn("issue", self.t.session(A))
        self.assertNotIn("filed now", ctx)
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])

    def test_a_session_with_turns_already_files_none_at_its_plan(self):
        """#39: a session already at work when the loop went live filed an issue at its next plan."""
        self.t.say(B, "Look around")
        self.assertEqual(self.t.stop(B, "Look around", report="Looked.", uuid="b1").returncode, 0)
        self.t.cli(B, "task", f"Fix the off-by-one in {self.work}/lib/x.py and commit it")
        self.assertNotIn("#7", self.plan(B, items(f"Fix {self.work}/lib/x.py", "Commit it")))
        self.assertNotIn("issue", self.t.session(B))

    def test_a_commit_missing_closes_is_flagged_once(self):
        self.start_writer()
        self.plan(A, items("Fix x", "Run the tests"))
        self.commit("lib: tidy x")
        ctx = self.plan(A, {"advance": True})
        self.assertIn("does not say `Closes #7`", ctx)
        self.assertIn("lib: tidy x", ctx)
        self.assertNotIn("Closes #7`", self.plan(A, {"advance": True}), "said once")
        self.commit("lib: fix x\n\nCloses #7", "x = 3\n")
        self.assertNotIn("does not say", self.plan(A, {"advance": True}), "a closing commit is not flagged")
        self.commit("lib: the queue's other fix\n\nCloses #9", "x = 4\n")
        self.assertNotIn("does not say", self.plan(A, {"advance": True}), "another issue's commit is its work")

    def test_a_child_whose_named_test_fails_is_not_retired(self):
        self.start_writer()
        step = self.proving_test(False)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(step)
        out = self.stop("f1")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("failed", out.get("reason", ""))
        self.assertFalse(self.t.session(A).get("doneRetired"), "a failing test keeps the child open")
        said = [c for c in self.calls() if c[:2] == ["issue", "comment"]]
        self.assertTrue(any("failed" in c[c.index("--body") + 1] for c in said), "the result is on the issue")
        notes = os.path.join(self.t.dir(TOP), "notes.jsonl")
        if os.path.exists(notes):
            with open(notes, encoding="utf-8") as f:
                self.assertNotIn("replaces:", f.read())
        r = self.t.hook("self-archive", A, {"hook_event_name": "PreToolUse", "tool_name":
                        "mcp__ccd_session_mgmt__archive_session", "tool_input": {"session_id": "self"},
                        "transcript_path": os.path.join(self.t.tmp, A + "f1.jsonl"), "cwd": self.work})
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_green_child_is_pushed_its_issue_closes_and_it_is_retired_with_the_link(self):
        self.start_writer()
        step = self.proving_test(True)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(step)
        out = self.stop("g1")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("push the `Closes #7` commit", out.get("reason", ""))
        self.assertIn("p4.py sync --push", out.get("reason", ""))
        self.assertFalse(self.t.session(A).get("doneRetired"), "not retired before the push closes the issue")
        guard = self.t.hook("branch-guard", A, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": "git push -u origin main"}})
        self.assertEqual(guard.stdout.strip(), "", "a child with an issue lands its own work")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"7": "CLOSED"}))
        self.assertEqual(self.stop("g2").get("decision"), None)
        self.assertTrue(self.t.session(A).get("doneRetired"), "retired once proven and closed")
        said = [c for c in self.calls() if c[:2] == ["issue", "comment"]]
        self.assertTrue(any("passed" in c[c.index("--body") + 1] for c in said))
        with open(os.path.join(self.t.dir(TOP), "notes.jsonl"), encoding="utf-8") as f:
            notes = f.read()
        self.assertIn("https://github.com/ezexe/demo/issues/7 (closed)", notes)
        self.assertIn("lib: fix x", notes)
        self.assertIn("test_x.py", notes)
        self.assertIn(A, context(self.t.say(TOP, "what next?")), "the parent gets its archive line")


class Words(unittest.TestCase):
    def test_writing_and_read_only_briefs(self):
        self.assertTrue(issues.writing("Fix the bug in relay.py"))
        self.assertTrue(issues.writing("# p4-phi #28 builder brief\n\nBuild ezexe/p4 issue #28 in p4-phi"))
        self.assertFalse(issues.writing("Check the pushed #28 work and report"))
        self.assertFalse(issues.writing("Audit relay.py for dead code"))
        self.assertFalse(issues.writing("Relay this to the top session"))
        self.assertFalse(issues.writing("Look at x.py, read-only: change nothing"))

    def test_a_named_issue_on_another_repo_is_not_taken(self):
        self.assertEqual(issues.named_issue("Build ezexe/p4 issue #28", "ezexe/p4"), 28)
        self.assertEqual(issues.named_issue("see https://github.com/o/r/issues/4", "ezexe/p4"), 0)
        self.assertEqual(issues.named_issue("Closes #9", "ezexe/p4"), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
