#!/usr/bin/env python3
"""issues.py: a writing child's one loop of the issue its brief names, `Closes #N`, a regression test, push and
archive, and the `Finding:` lines that go up in its report where it names none, run through phi.py's own hooks with a
stand-in for `gh`.

    python3 -I lbiza/plugins/p4-phi/scripts/test_issues.py

The stand-in answers `issue view` from a state file the test writes, as GitHub closes the issue once the `Closes #7`
commit is pushed; a state of UNREACHABLE makes `issue view` fail, as gh fails when it cannot reach GitHub. It logs
every call, so a test sees that no `issue create` is made. The work repository's `origin` reads as GitHub and pushes
to a bare repository beside it.
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
import inproc  # noqa: E402
import issues  # noqa: E402
from test_phi import CLI, GRAND, KID, KID2, TOP, Tree, context, read, write  # noqa: E402

A, B = KID, KID2
SUP = "local_sup00001"
CLI.setdefault(SUP, "eeee5555-0000-4000-8000-000000000000")
RECALL = os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh")
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
    if states.get(args[2]) == "UNREACHABLE":
        sys.exit("error connecting to api.github.com")
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
        ctx = context(self.t.say(A, f"Build ezexe/demo issue #7: fix the off-by-one in {self.work}/lib/x.py and commit "
                                    f"it. Archive when done."))
        self.assertIn("ezexe/demo#7", ctx)
        return ctx

    def commit(self, msg, text="x = 2\n"):
        write(os.path.join(self.work, "lib", "x.py"), text)
        self.git(self.work, "commit", "-qam", msg)

    def regression_test(self, ok, wait=0):
        write(os.path.join(self.work, "test_x.py"),
              "import sys, time\ntime.sleep(%s)\nsys.exit(%d)\n" % (wait, 0 if ok else 1))
        self.git(self.work, "add", "test_x.py")
        exe = sys.executable.replace("\\", "/")
        return f"Run `\"{exe}\" -I test_x.py` to prove the fix"

    def finish(self, test_step):
        self.plan(A, items("Fix x", test_step, status="completed"))

    def stop(self, uuid, **env):
        r = self.t.stop(A, "finish", report="Fixed x; the test passes.", uuid=uuid, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def settled(self, path, wait=30.0):
        """proof.json once its run in the background has written a result, or as it is after `wait` seconds."""
        end = time.time() + wait
        d = issues.relay._read_json(path)
        while d.get("state") == "running" and time.time() < end:
            time.sleep(0.1)
            d = issues.relay._read_json(path)
        return d

    def test_a_writing_child_in_a_github_repo_files_no_issue_and_is_told_to_send_its_findings_up(self):
        """A writing child whose brief names no issue is handed the `Finding:` line once and files nothing; a
        read-only child, a repository with no GitHub remote and P4_PHI_ISSUES=0 get neither an issue nor the line."""
        ctx = context(self.t.say(A, f"Fix the off-by-one in {self.work}/lib/x.py and commit it. Archive when done."))
        self.assertIn(issues.FINDINGS_LINE, ctx)
        self.assertNotIn("issue", self.t.session(A), "no issue record")
        self.assertNotIn("Finding:", self.plan(A, items("Fix x", "Run the tests")), "said once")
        self.assertNotIn("Finding:", context(self.t.say(B, f"Check what {self.work}/lib/x.py does and report it.")))
        self.assertNotIn("issue", self.t.session(B), "a read-only child gets no issue")
        self.assertNotIn("Finding:", context(self.t.say(GRAND, f"Fix the bug in {self.plain}/a.py and commit it.")))
        self.assertNotIn("issue", self.t.session(GRAND), "a repo with no GitHub remote gets none")
        off = "local_kid00003"
        self.t.record(off, TOP, title="the switched-off fix")
        self.assertNotIn("Finding:", context(self.t.say(off, f"Fix the off-by-one in {self.work}/lib/x.py and commit "
                                                             f"it.", P4_PHI_ISSUES="0")), "the switch turns it off")
        self.assertEqual([c for c in self.calls() if c[:2] == ["issue", "create"]], [])
        self.assertEqual(issues.findings("Done.\n- Finding: a; source: b; test: c; files: d\n2. Finding:  e  f\n"
                                         "No Finding: here\n> Finding: a; source: b; test: c; files: d"),
                         ["Finding: a; source: b; test: c; files: d", "Finding: e f"], "each line once, at a line start")

    def test_a_reading_gets_no_issue_record(self):
        """A reading explores and commits nothing, so it gets no issue record."""
        brief = (f"# Reading 2: count the rows\n\nThis session takes one reading of those words, reading 2 of 2: fix "
                 f"the count in {self.work}/lib/x.py\nA reading explores: change no tracked file and commit nothing, "
                 f"since the readings beside this one share the checkout.\nArchive when done.\n\n"
                 f"phi draft drf-0123456789 for {TOP}.\nphi reading grp-0123456789 2 of 2 for {TOP}.")
        ctx = context(self.t.say(A, brief))
        self.assertNotIn("#7", ctx)
        self.assertNotIn("issue", self.t.session(A))
        self.plan(A, items("Fix the count in lib/x.py", "Report the result"))
        self.assertNotIn("issue", self.t.session(A), "nor at its task list")
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])
        self.assertFalse(issues.writing("Fix x.py. A reading explores: change no tracked file and commit nothing."))

    def test_the_repository_the_brief_names_wins_over_the_checkouts_origin(self):
        """A repository the brief names by its `owner/name` wins over the origin of the checkout the session runs in,
        and the `owner/name` is never read as a path there."""
        proj = self.t.proj.replace("\\", "/")
        write(os.path.join(proj, "top.py"), "t = 1\n")
        for args in (("init", "-q", "-b", "main"), ("add", "top.py"), ("commit", "-qm", "one"),
                     ("remote", "add", "origin", "https://github.com/ezexe/demo-outer.git")):
            self.git(proj, *args)
        brief = (f"Fix the open issues on ezexe/demo in this order, one at a time, ezexe/demo#7 first. Read each with gh "
                 f"issue view N -R ezexe/demo. The code is in {self.work}/lib, on branch main. Commit each fix.")
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
        """`phi.py done` names the issue the session closes and what it still owes."""
        self.start_writer()
        r = self.t.cli(A, "done", "ran test_x.py and it passed", proj=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("this session closes ezexe/demo#7", r.stdout)
        self.assertIn("a commit that says `Closes #7`", r.stdout)
        self.assertIn("phi.py proof", r.stdout)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(self.regression_test(True))
        r = self.t.cli(A, "done", "ran test_x.py and it passed", proj=self.work)
        self.assertIn("says `Closes #7`", r.stdout)
        self.assertIn("Nothing is owed but the Stop check", r.stdout)
        self.assertIn(f"is its orchestrator's, \"top\" `{TOP}`", r.stdout, "the push is the orchestrator's")
        self.assertNotIn("a commit that says", r.stdout)
        self.t.say(B, f"Check what {self.work}/lib/x.py does for ezexe/demo#3 and ezexe/demo#4 and report it.")
        r = self.t.cli(B, "done", "read x.py and reported it", proj=self.work)
        self.assertIn("its task names ezexe/demo#3, ezexe/demo#4", r.stdout)

    def test_an_issue_the_brief_names_is_taken_not_filed_again(self):
        ctx = context(self.t.say(A, f"Build ezexe/demo issue #3: fix {self.work}/lib/x.py. Archive when done."))
        self.assertIn("ezexe/demo#3", ctx)
        self.assertIn("named in its brief", ctx)
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])

    def test_a_brief_naming_only_closed_issues_files_none_and_sends_its_findings_up(self):
        """A brief that names only closed issues takes none and files none, and its child is told to send its
        findings up in its report."""
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"3": "CLOSED", "4": "CLOSED"}))
        ctx = context(self.t.say(A, f"Fix ezexe/demo issue #3, then #4 in {self.work}/lib/x.py. Archive when done."))
        self.plan(A, items("Fix x", "Fix y"))
        self.assertNotIn("issue", self.t.session(A))
        self.assertIn(issues.FINDINGS_LINE, ctx)
        self.assertFalse([c for c in self.calls() if c[:2] == ["issue", "create"]])

    def test_a_session_with_turns_already_files_none_at_its_plan(self):
        """A session that already has turns of its own files no issue at its next task list."""
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

    def test_a_child_whose_named_test_fails_is_not_counted_as_archived(self):
        self.start_writer()
        step = self.regression_test(False)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(step)
        out = self.stop("f1")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("failed", out.get("reason", ""))
        self.assertFalse(self.t.session(A).get("doneRetired"), "a failing test keeps the child open")
        self.assertNotIn("close issues", json.dumps(self.t.session(TOP)), "unproven work gets no push line")
        self.plan(A, items("Fix x", "Write it up", status="completed"))
        self.stop("f2")
        self.assertNotIn("close issues", json.dumps(self.t.session(TOP)), "nor work whose test is not named")
        said =[c for c in self.calls() if c[:2] == ["issue", "comment"]]
        self.assertTrue(any("failed" in c[c.index("--body") + 1] for c in said), "the result is on the issue")
        notes = os.path.join(self.t.dir(TOP), "notes.jsonl")
        if os.path.exists(notes):
            with open(notes, encoding="utf-8") as f:
                self.assertNotIn("replaces:", f.read())
        r = self.t.hook("self-archive", A, {"hook_event_name": "PreToolUse", "tool_name":
                        "mcp__ccd_session_mgmt__archive_session", "tool_input": {"session_id": "self"},
                        "transcript_path": os.path.join(self.t.tmp, A + "f1.jsonl"), "cwd": self.work})
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_green_childs_closing_commit_is_pushed_by_its_orchestrator_and_it_is_counted_as_archived(self):
        """ezexe/p4#232: only the tree's orchestrator lands and pushes. A worker whose brief names issue 7, with its
        regression test passed and its `Closes #7` commit unpushed, is told at Stop that its work is proven and that
        its orchestrator pushes it, never to push; the top of its tree gets relay.push_text naming that commit; its
        own `git push` is asked first; and once the orchestrator's push closes the issue it is counted as archived
        with the link."""
        self.start_writer()
        step = self.regression_test(True)
        self.git(self.work, "commit", "-q", "--allow-empty", "-m", "lib: a sibling's fix\n\nCloses #9")
        sibling = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.commit("lib: fix x\n\nCloses #7")
        sha = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.finish(step)
        out = self.stop("g1")
        self.assertEqual(out.get("decision"), "block")
        reason = out.get("reason", "")
        self.assertIn("so this work is proven", reason)
        self.assertIn(f"Its orchestrator, \"top\" `{TOP}`", reason, "it names its orchestrator as the one that pushes")
        self.assertIn("this session does not push it", reason)
        self.assertNotIn("push the `Closes #7` commit", reason, "no order to push")
        self.assertNotIn("without asking", reason)
        self.assertFalse(self.t.session(A).get("doneRetired"), "not counted as archived before the push closes it")
        pending = json.dumps(self.t.session(TOP))
        self.assertIn("finished with commits that close issues", pending, "the top of its tree has the push line")
        self.assertIn(sha, pending, "naming the `Closes #7` commit")
        self.assertNotIn(sibling, pending, "and not a sibling's `Closes #9` commit in the shared checkout")
        guard = self.t.hook("branch-guard", A, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                 "tool_input": {"command": "git push -u origin main"}})
        self.assertEqual(json.loads(guard.stdout)["hookSpecificOutput"]["permissionDecision"], "ask",
                         "a child with an issue does not push its own closing commit")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"7": "CLOSED"}))
        self.assertEqual(self.stop("g2").get("decision"), None)
        self.assertTrue(self.t.session(A).get("doneRetired"), "counted as archived once proven and closed")
        said = [c for c in self.calls() if c[:2] == ["issue", "comment"]]
        self.assertTrue(any("passed" in c[c.index("--body") + 1] for c in said))
        with open(os.path.join(self.t.dir(TOP), "notes.jsonl"), encoding="utf-8") as f:
            notes = f.read()
        self.assertIn("https://github.com/ezexe/demo/issues/7, closed", notes)
        self.assertIn("lib: fix x", notes)
        self.assertIn("test_x.py", notes)
        self.assertIn(A, context(self.t.say(TOP, "what next?")), "the parent gets its archive line")

    def test_the_push_line_names_only_commits_whose_own_message_closes_the_issue_in_its_own_repository(self):
        """ezexe/p4#232: the orchestrator's push line for a worker with issue 7 names only a commit of the issue's own
        repository whose own message closes #7: not one whose message says it does not close #7, and not a commit
        that says `Closes #7` in another repository the turn edited in."""
        self.start_writer()
        step = self.regression_test(True)
        self.commit("lib: tidy x\n\nThis does not close #7 yet.")
        tidy = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.git(self.plain, "commit", "-q", "--allow-empty", "-m", "a: other repo\n\nCloses #7")
        other = self.git(self.plain, "rev-parse", "--short", "HEAD").stdout.strip()
        self.commit("lib: fix x\n\nCloses #7", "x = 3\n")
        sha = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.finish(step)
        r = self.t.stop(A, "finish", [("Edit", {"file_path": f"{self.work}/lib/x.py"}, "ok"),
                                      ("Edit", {"file_path": f"{self.plain}/a.py"}, "ok")],
                        report="Fixed x; the test passes.", uuid="o1")
        self.assertEqual(r.returncode, 0, r.stderr)
        pending = json.dumps(self.t.session(TOP))
        self.assertIn(sha, pending, "the commit that closes #7 in the issue's repository")
        self.assertNotIn(tidy, pending, "a message that says it does not close #7")
        self.assertNotIn(other, pending, "a commit in another repository")

    def test_a_pushed_child_is_counted_as_archived_only_once_gh_shows_its_issue_closed(self):
        """With the `Closes #7` commit pushed and `gh issue view` failing, nothing shows the issue closed: the child's
        turn is sent back saying gh could not say, it is not counted as archived, and no note on its parent calls the
        issue closed. Once gh shows the issue closed, the next Stop counts it as archived."""
        self.start_writer()
        step = self.regression_test(True)
        self.commit("lib: fix x\n\nCloses #7")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"7": "UNREACHABLE"}))
        self.finish(step)
        out = self.stop("u1")
        self.assertFalse(self.t.session(A).get("doneRetired"), "nothing showed the issue closed")
        notes = os.path.join(self.t.dir(TOP), "notes.jsonl")
        if os.path.exists(notes):
            with open(notes, encoding="utf-8") as f:
                self.assertNotIn("replaces:", f.read(), "no note on the parent calls the issue closed")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("gh could not say whether ezexe/demo#7 is closed", out.get("reason", ""))
        self.assertNotIn("still open", out.get("reason", ""), "nothing showed the issue open either")
        write(os.path.join(self.ghdir, "state.json"), json.dumps({"7": "CLOSED"}))
        self.assertEqual(self.stop("u2").get("decision"), None)
        self.assertTrue(self.t.session(A).get("doneRetired"), "counted as archived once gh shows the issue closed")
        with open(notes, encoding="utf-8") as f:
            self.assertIn("https://github.com/ezexe/demo/issues/7, closed", f.read())

    def test_the_landing_that_closes_a_memorys_issue_cuts_it_to_a_pointer(self):
        """ezexe/p4#226: a feedback memory tied to ezexe/demo#7 by an `issue:` line in its front matter is cut back at
        the Stop that follows the landing of a `Closes #7` commit on the default branch: its body becomes one pointer
        line naming the issue and the code that carries the rule, which the gap check reads as carried, and its line
        in MEMORY.md says the same. Before the landing it is kept whole, and a memory tied to another issue is too."""
        import gaps
        import p4conf
        mem = p4conf.sub(self.t.p4, "memory")
        rule = ("---\nname: one lander\ndescription: only the orchestrator pushes\ntype: feedback\n"
                "issue: ezexe/demo#7\n---\n\nOnly the tree's orchestrator pushes; a child commits and reports.\n")
        tied, other = os.path.join(mem, "one-lander.md"), os.path.join(mem, "other.md")
        write(tied, rule)
        write(other, rule.replace("#7", "#9"))
        write(os.path.join(mem, "MEMORY.md"), "# Memory index\r\n\r\n- [One lander](one-lander.md) — only the "
                                              "orchestrator pushes\r\n- [Other](other.md) — x\r\n- [A](a.md) — see "
                                              "[One lander](one-lander.md)\r\n")
        self.commit("lib: fix x\n\nCloses #7")
        sha = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.land("m1", "git commit -qam fix")
        self.assertEqual(read(tied), rule, "kept whole while the commit is on no remote default branch")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        self.assertEqual(self.t.stop(TOP, "look", report="Looked.", uuid="m2").returncode, 0)
        self.assertEqual(read(tied), rule, "a Stop whose turn ran no push, pull, fetch or merge checks nothing")
        self.land("m3")
        body = read(tied)
        self.assertNotIn("a child commits and reports", body)
        self.assertIn(f"Pointer: the plugin carries this rule since ezexe/demo#7 landed in commit {sha} \"lib: fix x\""
                      f", in `lib/x.py`", body)
        self.assertIn(f"\nlanded: {sha}\n", body)
        self.assertIn("issue: ezexe/demo#7", body, "it stays tied to its issue")
        self.assertTrue(gaps.carried(gaps.body_of(body)), "the gap check reads the pointer as carried")
        index = read(os.path.join(mem, "MEMORY.md"))
        self.assertIn(f"- [One lander](one-lander.md) — carried by the plugin since ezexe/demo#7 landed in {sha}\n",
                      index)
        self.assertIn("- [Other](other.md) — x", index)
        self.assertIn("- [A](a.md) — see [One lander](one-lander.md)\n", index, "a line whose first link is another's")
        with open(os.path.join(mem, "MEMORY.md"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), "its line endings are kept as found")
        self.assertEqual(raw.count(b"\r\n"), 5)
        self.assertEqual(read(other), rule.replace("#7", "#9"), "a memory whose issue did not land is kept whole")
        self.land("m4")
        self.assertEqual(read(tied), body, "a second Stop leaves the pointer as it is")
        self.assertEqual(read(os.path.join(mem, "MEMORY.md")), index, "and the index too")

    def land(self, uuid, cmd="git push -u origin main"):
        """A Stop of the top session whose turn ran `cmd`."""
        r = self.t.stop(TOP, "land it", [("Bash", {"command": cmd}, "ok")], report="Landed.", uuid=uuid)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_memory_is_not_cut_back_by_a_message_that_does_not_close_its_issue_or_a_commit_off_the_default(self):
        """GitHub's closing keywords count only as whole words at a line's start or after whitespace, and not after a
        negation: "prefix #7", "disclose #7" and "does not close #7" on the default branch cut nothing, and
        issues.landed does not take them for a landing of #7. A `Closes #7` commit on another remote branch cuts
        nothing either."""
        import p4conf
        mem = p4conf.sub(self.t.p4, "memory")
        rule = "---\nname: r\ntype: feedback\nissue: ezexe/demo#7\n---\n\nOnly the orchestrator pushes.\n"
        write(os.path.join(mem, "r.md"), rule)
        for i, msg in enumerate(("lib: a prefix #7 for x", "lib: disclose #7 in the log",
                                 "lib: tidy\n\nThis does not close #7 yet.")):
            self.commit(msg, f"x = {i + 5}\n")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        self.land("n1")
        self.assertEqual(read(os.path.join(mem, "r.md")), rule, "no closing keyword closed #7")
        self.commit("lib: fix x\n\nCloses #7", "x = 9\n")
        sha = self.git(self.work, "rev-parse", "--short", "HEAD").stdout.strip()
        self.assertFalse(issues.landed(self.work, sha, ["#7"]), "no remote commit closes #7")
        self.assertEqual(issues.closing_refs("Fixes #3, closes ezexe/demo#4\nfix: #5\nprefix #6"),
                         ["#3", "ezexe/demo#4", "#5"])
        self.git(self.work, "push", "-q", "origin", "HEAD:feature")
        self.land("n2", "git fetch origin")
        self.assertEqual(read(os.path.join(mem, "r.md")), rule, "a closing commit on another branch has not landed")

    def test_the_cut_back_edits_the_memory_folder_claude_code_loads_with_or_without_an_index_line(self):
        """The cut-back edits the folder `autoMemoryDirectory` names, where Claude Code loads auto memory from, and the
        store's own memory folder. A folder with no MEMORY.md gets none, and a MEMORY.md with no line for the memory
        is left as it is."""
        import p4conf
        loaded = os.path.join(self.t.tmp, "loaded-memory")
        local = p4conf.settings_file(p4conf.session_project(self.t.p4))
        conf = p4conf.read_json(local) or {}
        conf["autoMemoryDirectory"] = loaded.replace("\\", "/")
        write(local, json.dumps(conf))
        rule = "---\nname: r\ntype: feedback\nissue: ezexe/demo#7\n---\n\nOnly the orchestrator pushes.\n"
        mem = p4conf.sub(self.t.p4, "memory")
        write(os.path.join(loaded, "r.md"), rule)
        write(os.path.join(mem, "s.md"), rule)
        index = "# Memory index\n\n- [Other](other.md) — x\n"
        write(os.path.join(mem, "MEMORY.md"), index)
        self.commit("lib: fix x\n\nCloses #7")
        self.git(self.work, "push", "-q", "-u", "origin", "main")
        self.land("l1")
        self.assertEqual((p4conf.read_json(local) or {}).get("autoMemoryDirectory"), loaded.replace("\\", "/"))
        for path in (os.path.join(loaded, "r.md"), os.path.join(mem, "s.md")):
            self.assertIn("Pointer: the plugin carries this rule since ezexe/demo#7", read(path), path)
        self.assertFalse(os.path.exists(os.path.join(loaded, "MEMORY.md")), "no index is made where there was none")
        self.assertEqual(read(os.path.join(mem, "MEMORY.md")), index, "an index with no line for it is kept")

    def test_a_run_in_the_background_whose_process_is_gone_is_run_again_at_the_next_stop(self):
        """A regression test that outlasts P4_PHI_PROOF_S runs on in the background through the `proof-run` entry,
        which writes its result to proof.json. A run in the background that died leaves proof.json in state running
        with its process gone. The next Stop does not take that as running: it runs the test again and takes its
        result."""
        self.start_writer()
        step = self.regression_test(True, wait=0.2)
        self.commit("lib: fix x\n\nCloses #7")
        self.finish(step)
        out = self.stop("b1", P4_PHI_PROOF_S="0.05")
        path = os.path.join(self.t.dir(A), "proof.json")
        ran = self.settled(path)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("runs on in the background", out.get("reason", ""))
        self.assertEqual(ran.get("state"), "passed", "the `proof-run` entry wrote the result of the run")
        ended = subprocess.Popen([sys.executable, "-I", "-c", ""])
        ended.wait()
        left = {k: ran[k] for k in ("cmd", "cwd", "head", "time")}
        write(path, json.dumps(dict(left, state="running", pid=ended.pid)))
        out = self.stop("b2")
        self.assertEqual(issues.relay._read_json(path).get("state"), "passed", "the test ran again")
        self.assertIn("so this work is proven", out.get("reason", ""), "and its pass was taken")


CONSOLE = """import ctypes, json, os, subprocess, sys
REPORT = ("import ctypes, json, sys; json.dump({'window': ctypes.windll.kernel32.GetConsoleWindow() or 0}, "
          "open(sys.argv[1], 'w'))")
out = sys.argv[sys.argv.index("--p4") + 1] if "--p4" in sys.argv else sys.argv[1]
subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run([sys.executable, "-I", "-c", REPORT, os.path.join(out, "grandchild.json")])
json.dump({"window": ctypes.windll.kernel32.GetConsoleWindow() or 0}, open(os.path.join(out, "child.json"), "w"))
"""


@unittest.skipUnless(os.name == "nt", "a console window is a Windows matter")
class NoConsoleWindow(unittest.TestCase):
    """Every process p4-phi leaves running behind a hook, and every console program it starts, such as git, sh or
    python, shares one console that has no window. A process started with DETACHED_PROCESS has no console, so each
    console program it starts gets a console of its own, which opens a window, or a Windows Terminal tab through
    OpenConsole.exe; CREATE_NO_WINDOW is ignored beside DETACHED_PROCESS. The stand-in each start runs reports its
    own console's window and that of a python it starts, after starting git."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = os.path.realpath(self._tmp.name)
        self.fake = os.path.join(self.tmp, "scripts")
        os.makedirs(self.fake)
        for name in ("p4.py", "phi.py", "console.py"):
            write(os.path.join(self.fake, name), CONSOLE)
        self.addCleanup(self._tmp.cleanup)

    def windows(self, out):
        """Each reporter's console window, once both have written."""
        files = [os.path.join(out, f) for f in ("child.json", "grandchild.json")]
        end = time.time() + 60
        while time.time() < end and not all(os.path.exists(f) and os.path.getsize(f) for f in files):
            time.sleep(0.1)
        time.sleep(0.2)
        return {os.path.basename(f)[:-5]: json.load(open(f)).get("window") for f in files if os.path.exists(f)}

    def assertNoWindow(self, out, what):
        self.assertEqual(self.windows(out), {"child": 0, "grandchild": 0},
                         f"{what}: a process it leaves behind, and what that process starts, have no console window")

    def test_the_issue_loops_background_proof_opens_no_console_window(self):
        out = os.path.join(self.tmp, "proof")
        os.makedirs(out)
        cmd = f'"{sys.executable}" -I "{os.path.join(self.fake, "console.py")}" "{out}"'.replace("\\", "/")
        issues.run_background(self.tmp, "local_proof0001", cmd, out, "abc1234")
        self.assertNoWindow(out, "issues.run_background")

    def test_catchups_background_sync_opens_no_console_window(self):
        import catchup
        out = os.path.join(self.tmp, "store")
        os.makedirs(out)
        saved = catchup.HERE
        catchup.HERE = self.fake
        try:
            self.assertTrue(catchup.start_sync(out))
        finally:
            catchup.HERE = saved
        self.assertNoWindow(out, "catchup.start_sync")

    def test_the_orchestrators_watcher_opens_no_console_window(self):
        import puppeteer
        out = os.path.join(self.tmp, "home")
        os.makedirs(out)
        saved = {k: getattr(puppeteer, k) for k in ("HERE", "on", "orchestrator", "closed", "watcher_alive",
                                                     "watcher_path")}
        puppeteer.HERE = self.fake
        puppeteer.on = puppeteer.orchestrator = lambda *a: True
        puppeteer.closed = puppeteer.watcher_alive = lambda *a: False
        puppeteer.watcher_path = lambda home, top: os.path.join(self.tmp, "watcher.json")
        env = os.environ.pop("P4_PHI_WATCH", None)
        try:
            self.assertTrue(puppeteer.ensure_watcher(out, {"sessionId": "local_watch0001"}))
        finally:
            for k, v in saved.items():
                setattr(puppeteer, k, v)
            if env is not None:
                os.environ["P4_PHI_WATCH"] = env
        self.assertNoWindow(out, "puppeteer.ensure_watcher")


class FindingsGoUp(unittest.TestCase):
    """No session publishes a new issue on its own. A writing child whose brief names no issue files none and is told
    to write each finding into its report as one `Finding:` line; the findings of a controlled tree's reports are on
    its puppeteer's board; and the plugin-gap line names that puppeteer, not `gh issue create`."""

    FORM = ("`Finding: <the claim>; source: <the file and line it was read at>; test: <the deciding test>; files: <the paths a "
            "fix changes>`")

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
        t.record(SUP, title="Watch the demo trees")
        write(os.path.join(tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": [{"id": "cg-1", "name": "puppeteers"}],
                                                 "assignments": {"code:" + SUP: "cg-1"}}}}}}))
        self.work = os.path.join(t.proj, "work").replace("\\", "/")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "one"),
                     ("remote", "add", "origin", "https://github.com/ezexe/demo.git")):
            subprocess.run(["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                           capture_output=True)
        self.plug = os.path.join(tmp, "plugproj")
        os.makedirs(os.path.join(self.plug, ".claude", "p4"))
        subprocess.run(["git", "init", "-q", self.plug], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.plug, "remote", "add", "origin", "https://github.com/team/plug.git"],
                       check=True, capture_output=True)

    def tearDown(self):
        os.environ.pop("FAKE_GH_DIR", None)
        self._tmp.cleanup()

    def created(self):
        p = os.path.join(self.ghdir, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [c for c in (json.loads(x) for x in f) if c[:2] == ["issue", "create"]]

    def record(self, host, tool, inp, resp, uid, **env):
        """The `lookup-record` entry hooks.json runs after every tool call, and what it hands the session."""
        body = {"session_id": CLI.get(host, host), "cwd": self.work, "hook_event_name": "PostToolUse",
                "tool_name": tool, "tool_input": inp, "tool_response": resp, "tool_use_id": uid}
        r = inproc.run(["sh", RECALL, "lookup-record"], input=json.dumps(body), capture_output=True, text=True,
                       timeout=60, env=self.t.env(host, **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def test_a_writing_childs_findings_go_up_to_the_supervisor_session_and_no_issue_is_filed(self):
        t = self.t
        t.say(TOP, "Build the demo")
        first = context(t.say(A, f"Fix the off-by-one in {self.work}/lib/x.py and commit it. Archive when done."))
        listed = self.record(A, "mcp__ccd_turn__update_plan", {"items": [
            {"content": "Fix the off-by-one in lib/x.py", "status": "in_progress"},
            {"content": "Commit it", "status": "pending"}]}, "Plan updated.", "toolu_plan01")
        with self.subTest("no issue is filed at the first message or the task list"):
            self.assertEqual(self.created(), [])
            self.assertNotIn("issue", t.session(A))
        with self.subTest("the child is handed the form of a finding line, once"):
            self.assertIn(self.FORM, first)
            self.assertIn("passes those lines up unchanged", first)
            self.assertNotIn("Finding:", listed, "said at the first message only")
        t.cli(SUP, "controls", TOP)
        kid = "Finding: lib/x.py drops the last row; source: lib/x.py line 1; test: test_x.py; files: lib/x.py"
        top = "Finding: the importer reads one row too many; source: lib/y.py line 9; test: test_y.py; files: lib/y.py"
        t.stop(A, "Fix the off-by-one", report="Fixed lib/x.py.\n" + kid, uuid="a1")
        t.stop(TOP, "Build the demo", report="The demo is built.\n\n- " + top, uuid="t1")
        t.say(SUP, "what came in?")
        board = read(os.path.join(t.dir(SUP), "board.md"))
        with self.subTest("each finding of the controlled tree is on the puppeteer's board"):
            self.assertIn("\n## Findings\n", board)
            found = board.split("\n## Findings\n", 1)[-1].split("\n## ", 1)[0]
            self.assertIn(f"- \"top\" `{TOP}`: {top}\n", found)
            self.assertIn(f"- \"the x fix\" `{A}`: {kid}\n", found)
        mem = os.path.join(t.p4, "temportal", "memory", "children-on-parent-branch.md")
        write(mem, "---\nname: children-on-parent-branch\ndescription: x\nmetadata:\n  type: feedback\n---\n\n"
                   "A session started from another works on the parent's branch, and only the parent merges and "
                   "pushes.\n")
        gap = self.record(A, "Write", {"file_path": mem}, "ok", "toolu_write01", P4_PHI_PLUGIN_ROOT=self.plug)
        with self.subTest("the plugin-gap line names the puppeteer and not `gh issue create`"):
            self.assertIn(f"the puppeteer \"Watch the demo trees\" `{SUP}`", gap)
            self.assertIn("Finding: ", gap)
            self.assertNotIn("gh issue create", gap)
        self.assertEqual(self.created(), [], "and no issue is filed by anyone")


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


class RunNowLimit(unittest.TestCase):
    """issues.run_now returns within its limit, with the test and what it started stopped."""

    def test_a_test_past_the_limit_returns_within_it_and_is_stopped(self):
        import issues
        tmp = tempfile.mkdtemp(prefix="p4-phi-runnow-")
        mark = os.path.join(tmp, "ran-on").replace("\\", "/")
        try:
            t = time.monotonic()
            code, _ = issues.run_now(f"sleep 3; echo late > '{mark}'", tmp, 0.3)
            took = time.monotonic() - t
            self.assertIsNone(code)
            self.assertLess(took, 0.3 + 1.0, took)
            time.sleep(3.5)
            self.assertFalse(os.path.exists(mark), "the test ran on past the limit")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
