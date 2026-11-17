#!/usr/bin/env python3
"""relay.py: owned paths, deltas, anchors, the rebase check and routing, on a tree of three sessions run through
phi.py's hooks, with fork or fresh, tracking in the store, a shared store and merged worktrees beside them.

    python3 -I lbiza/plugins/p4-phi/scripts/test_relay.py

The tree: an orchestrator and two workers. One of them deprecates a path the other has uncommitted edits
in; the other is warned on its next message, before any tool runs.
"""

import json
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pathfilter  # noqa: E402
import relay  # noqa: E402
from test_phi import CLI, GRAND, KID, KID2, START, TOP, Tree, context, write  # noqa: E402
import inproc  # noqa: E402

A, B = KID, KID2


class Paths(unittest.TestCase):
    def test_globs_and_dirs_cover_and_overlap(self):
        self.assertTrue(relay.covers("e:/w/lib", "e:/w/lib/x.py"))
        self.assertFalse(relay.covers("e:/w/lib", "e:/w/library/x.py"))
        self.assertTrue(relay.covers("e:/w/lib/*.py", "e:/w/lib/x.py"))
        self.assertTrue(relay.overlap("e:/w/lib/**", "e:/w/lib/x.py"))
        self.assertFalse(relay.overlap("e:/w/lib", "e:/w/docs"))
        self.assertEqual(relay.norm("/e/projects/x/", ""), relay.norm("E:/projects/x", ""))

    def test_a_file_in_the_apps_scratchpad_of_the_session_is_scratch_and_never_a_conflict(self):
        """ezexe/p4#131: a session's clones and probes live in the app's scratchpad, so a file there, by any of its
        CLI sessions' <id>/scratchpad or by the scratchpadDir phi keeps, is scratch, as one under the store's
        temportal/tmp of an older session still is; a file of the project is not."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "proj", ".claude", "p4")
            cli = "aaaa1111-0000-4000-8000-000000000000"
            write(os.path.join(home, "phi", "sessions", "local_x", "session.json"), json.dumps(
                {"sessionId": "local_x", "cliSessionIds": [cli], "scratchpadDir": "D:/pads/first-turn"}))
            n = lambda p: relay.norm(p, os.path.join(tmp, "proj"))                        # noqa: E731
            for f in (f"C:/Users/u/AppData/Local/Temp/claude/h/{cli}/scratchpad/p4/x.py",
                      "D:/pads/first-turn/w/p4/x.py", os.path.join(home, "temportal", "tmp", cli, "x.py")):
                self.assertTrue(relay.scratch(home, "local_x", n(f)), f)
            for f in (os.path.join(tmp, "proj", "src", "x.py"), "C:/Users/u/AppData/Local/Temp/claude/h/other/x.py"):
                self.assertFalse(relay.scratch(home, "local_x", n(f)), f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_childs_slice_names_its_paths_relative_and_no_scratchpad_in_the_store(self):
        """The slice's paths as the project names them. No line names a scratchpad under .claude: the app names each
        session's scratchpad itself, and every write under .claude asks ezexe."""
        self.assertFalse(hasattr(relay, "scratch_line"))
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, ".claude", "p4")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"),
                  json.dumps({"sessionId": "top", "cwd": tmp, "task": "t"}))
            kid = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "cwd": tmp,
                   "task": f"fix {tmp}/src/a.py"}
            text = relay.slice_text(home, kid)
            self.assertIn("paths, src/a.py, from", text)
            self.assertNotIn(relay.norm(tmp), text)
            self.assertEqual(relay.slice_text(home, dict(kid, task="no path here")), "", "no empty paths line")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_childs_slice_hands_on_no_run_of_its_parents_prompt(self):
        """A session is handed what its parent wrote for it, never a run of eight words of the prompt the parent was
        sent: the slice names the parent by its title alone."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, ".claude", "p4")
            prompt = ("Resolve the open issues on the plugin repository and land each one with its deciding "
                      "test before the weekly limit comes round again")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"),
                  json.dumps({"sessionId": "top", "cwd": tmp, "task": prompt, "title": "the issues run"}))
            kid = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "cwd": tmp,
                   "task": f"fix {tmp}/src/a.py"}
            text = relay.slice_text(home, kid)
            self.assertIn("\"the issues run\"", text)
            words = prompt.split()
            runs = [" ".join(words[k:k + 8]) for k in range(len(words) - 7)]
            self.assertEqual([r for r in runs if r in text], [], "no eight-word run of the parent's prompt")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_same_words_are_queued_once_and_no_cli_id_gets_no_background(self):
        """The same words under two keys are queued once, and a call with no CLI session id is not given the
        background again."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"), json.dumps({"sessionId": "kid"}))
            self.assertTrue(relay.warn(home, "kid", "turn:top:aaa", "the same quote"))
            self.assertFalse(relay.warn(home, "kid", "turn:top:bbb", "the same quote"))
            self.assertEqual(len(relay._session(home, "kid")["relayPending"]), 1)
            import phi
            s = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "forked": True,
                 "backgroundGivenFor": {"": "top"}}
            me = type("Me", (), {"cli": ""})()
            self.assertEqual(phi.given(s, me, home), "")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "backgroundGivenFor": {"": "top", "c1": "top"}}))
            self.assertEqual(phi.load_session(home, "kid")["backgroundGivenFor"], {"c1": "top"}, "dropped on load")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_first_look_hands_on_no_backlog_and_revisions_collapse(self):
        """A first look hands on none of what was there before it, and a child's revisions since the last look
        collapse into one line."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}}))
            write(os.path.join(home, "phi", "sessions", "top", "anchor.json"), json.dumps({
                "version": 9, "changedAt": {"sib": 9}, "parent": {},
                "nodes": {"sib": {"title": "sib", "marks": [{"claim": "replaces: old news", "time": "2026-11-12 09:00",
                                                             "paths": []}]}}}))
            text, _ = relay.rebase(home, "kid", 9000, lambda xs, n: xs)
            self.assertNotIn("old news", text, "what was there at the first look is taken as seen")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"), json.dumps({"sessionId": "top"}))
            for k in range(5):
                relay.warn(home, "top", f"plan:kid:{k:04d}:up", f"\"kid\", started for a step not in your task list, "
                                                                 f"revised its plan: {k}.1 changed.")
            pend = relay._session(home, "top")["relayPending"]
            self.assertEqual(len(pend), 1)
            self.assertIn("revised its plan 5 times since you last looked; now: 4.1 changed.", pend[0]["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_title_is_cut_at_a_clause_never_mid_phrase(self):
        """A cut ends where a clause ends, never mid-phrase as "count only the sessions that the command" would."""
        self.assertEqual(relay.clause_cut("count only the sessions that the command python -I phi.py tree prints", 46),
                         "count only the sessions")
        self.assertEqual(relay.clause_cut("count every session folder under E:/projects/p4-phi/.claude/p4/phi", 46),
                         "count every session folder")
        self.assertEqual(relay.clause_cut("Cap the hook text. Then hand each note to a session only once, by page", 40),
                         "Cap the hook text")
        self.assertEqual(relay.clause_cut("the issue loop files on the plugin repo, keeps whole titles, and more", 60),
                         "the issue loop files on the plugin repo, keeps whole titles")
        self.assertEqual(relay.clause_cut("a short title", 46), "a short title")

    def test_git_bash_and_wsl_paths_are_absolute(self):
        """/e/x as Git Bash writes it is E:/x, not a path under the base."""
        self.assertEqual(relay.paths_in("cat /e/projects/p4-phi/x/a1.txt", "E:/projects/p4-phi"),
                         [relay.norm("E:/projects/p4-phi/x/a1.txt")])
        self.assertEqual(relay.norm("/mnt/e/projects/x"), relay.norm("E:/projects/x"))

    def test_a_path_on_a_missing_drive_never_hangs(self):
        """A mark's path on a drive this machine lacks gets no repository at once and warns nobody, and that mark is
        still handed on."""
        import time
        t0 = time.time()
        self.assertEqual(relay.repo_of("s:/replaces"), "")
        self.assertTrue(relay.too_broad("s:/replaces", "E:/x"))
        self.assertLess(time.time() - t0, 5)
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "anchorSeen": 0}))
            write(os.path.join(home, "phi", "sessions", "top", "anchor.json"), json.dumps({
                "version": 3, "changedAt": {"sib": 3}, "parent": {},
                "nodes": {"sib": {"title": "sib", "marks": [{"claim": "replaces: x", "time": "2026-11-12 14:00",
                                                             "paths": ["s:/replaces"]}]}}}))
            text, _ = relay.rebase(home, "kid", 9000, lambda xs, n: xs)
            self.assertIn("replaces: x", text, "the mark is still handed on")
            self.assertNotIn("stop before any tool", text)
            self.assertLess(time.time() - t0, 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_paths_a_note_names(self):
        got = relay.paths_in("deprecates: `lib/x.py` and docs/old.md, see https://example.com/a", "E:/w")
        self.assertEqual(got, [relay.norm("E:/w/lib/x.py"), relay.norm("E:/w/docs/old.md")])

    def test_a_repository_is_found_without_starting_git(self):
        """A path's repository is found from the `.git` folders above it, with no git process started."""
        if not shutil.which("git"):
            self.skipTest("no git")
        tmp = os.path.realpath(tempfile.mkdtemp())
        real, asked = relay._git, []
        try:
            repo = os.path.join(tmp, "r")
            os.makedirs(os.path.join(repo, "lib", "deep"))
            subprocess.run(["git", "init", "-q", repo], check=True)
            says = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            relay._git = lambda *a: asked.append(a) or real(*a)
            relay._ABOVE.clear()
            for p in (repo, os.path.join(repo, "lib"), os.path.join(repo, "lib", "deep", "x.py"),
                      os.path.join(repo, "lib", "not", "made", "y.py")):
                self.assertEqual(relay.repo_of(p), relay.norm(says.stdout.strip()), p)
            self.assertTrue(relay.too_broad(relay.norm(repo), os.path.join(tmp, "p4")), "a repository's top folder")
            self.assertFalse(relay.too_broad(relay.norm(os.path.join(repo, "lib")), os.path.join(tmp, "p4")))
            self.assertEqual(asked, [], "no git process for a path under a .git")
        finally:
            relay._git = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_repository_is_named_as_git_names_it(self):
        """A stray `.git` is passed over as git passes over it, a linked path gives the resolved top as git does, and
        what was found is believed only for ABOVE_S, so a later `git init` is seen."""
        if not shutil.which("git"):
            self.skipTest("no git")
        tmp = os.path.realpath(tempfile.mkdtemp())

        def says(path):
            r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            return relay.norm(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ""
        try:
            repo = os.path.join(tmp, "r")
            inner = os.path.join(repo, "pkg", "sub")
            os.makedirs(os.path.join(inner, ".git"))             # an empty .git folder inside a real repository
            os.makedirs(os.path.join(repo, "docs"))
            with open(os.path.join(repo, "docs", ".git"), "w", encoding="utf-8") as f:
                f.write("not a gitdir line\n")                   # and a stray file by that name
            subprocess.run(["git", "init", "-q", repo], check=True)
            relay._ABOVE.clear()
            for p in (inner, os.path.join(repo, "docs")):
                self.assertEqual(relay.repo_of(p), relay.norm(repo), p)
            self.assertEqual(says(inner), relay.norm(repo), "git passes over the empty folder too")
            self.assertEqual(relay.repo_of(os.path.join(inner, "x.py")), relay.norm(repo))
            bare = os.path.join(tmp, "none", "deep")
            os.makedirs(os.path.join(tmp, "none", ".git"))       # a stray .git with no repository above it
            os.makedirs(bare)
            relay._ABOVE.clear()
            self.assertEqual((relay.repo_of(bare), says(bare)), ("", ""))
            link = os.path.join(tmp, "link")
            try:
                if os.name == "nt":
                    import _winapi
                    _winapi.CreateJunction(repo, link)
                else:
                    os.symlink(repo, link)
            except (OSError, ImportError, AttributeError):
                link = ""
            if link:
                relay._ABOVE.clear()
                self.assertEqual(relay.repo_of(os.path.join(link, "pkg")), says(os.path.join(link, "pkg")))
                self.assertEqual(relay.repo_of(os.path.join(link, "pkg")), relay.norm(repo), "the resolved top")
            late = os.path.join(tmp, "late", "src")
            os.makedirs(late)
            relay._ABOVE.clear()
            self.assertEqual(relay.repo_of(late), "")
            subprocess.run(["git", "init", "-q", os.path.dirname(late)], check=True)
            self.assertEqual(relay.repo_of(late), "", "believed for ABOVE_S")
            relay._ABOVE_AT[0] -= relay.ABOVE_S + 1
            self.assertEqual(relay.repo_of(late), relay.norm(os.path.dirname(late)), "then looked for again")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sessions_are_read_again_only_when_they_change(self):
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            path = os.path.join(home, "phi", "sessions", "a", "session.json")
            write(path, json.dumps({"sessionId": "a", "task": "one"}))
            first = relay._sessions(home)
            first["a"]["title"] = "a caller's own change"
            self.assertNotIn("title", relay._sessions(home)["a"], "each caller has its own copy")
            write(path, json.dumps({"sessionId": "a", "task": "one, changed on disk"}))
            self.assertEqual(relay._sessions(home)["a"]["task"], "one, changed on disk")
            shutil.rmtree(os.path.dirname(path))
            self.assertEqual(relay._sessions(home), {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_path_on_a_missing_drive_has_no_repository(self):
        # dirname("s:/") is "s:/": the walk up stops at a root, so a path on a missing drive has no repository
        for p in ("s:/replaces", "q:/no/such/dir/file.txt", "/no/such/place"):
            self.assertEqual(relay.repo_of(p), "", p)


class ThreeSessions(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        t = self.t
        t.record(TOP, title="top")
        t.record(A, TOP, title="the layout work")
        t.record(B, TOP, title="the recall work")
        self.work = os.path.join(t.proj, "work")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        write(os.path.join(self.work, "lib", "y.py"), "y = 1\n")
        write(os.path.join(self.work, "docs", "d.md"), "d\n")
        for args in (("init", "-q"), ("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")):
            subprocess.run(["git", "-C", self.work, *args], check=True, capture_output=True)
        for host, prompt in ((TOP, "Build the two plugins"), (A, "Move the layout"), (B, "Fold recall in")):
            self.assertEqual(t.say(host, prompt).returncode, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def x(self, *rel):
        return os.path.join(self.work, *rel).replace("\\", "/")

    def edit_uncommitted(self, host, rel, uuid):
        """`host` edits a file in a turn and leaves it uncommitted."""
        path = self.x(*rel)
        with open(path, "a", encoding="utf-8") as f:
            f.write("more = 2\n")
        self.assertEqual(self.t.stop(host, "edit it", [("Edit", {"file_path": path}, "ok")], uuid=uuid).returncode, 0)
        return path

    def test_a_child_with_no_issue_record_gets_no_push_line_for_its_closing_commit(self):
        """ezexe/p4#232: a worker with no issue record that commits `Closes #5` has run no regression test p4-phi
        saw, so its orchestrator gets no push line for it: the worker reports the commit and its orchestrator
        decides."""
        t = self.t
        self.edit_uncommitted(A, ("lib", "x.py"), "c1")
        g = ["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["commit", "-qam", "lib: fix x\n\nCloses #5"], check=True, capture_output=True)
        self.edit_uncommitted(A, ("lib", "y.py"), "c2")
        subprocess.run(g + ["commit", "-qam", "lib: tidy y\n\nThis does not close #6, and a prefix #7 is no keyword."],
                       check=True, capture_output=True)
        self.edit_uncommitted(A, ("lib", "x.py"), "c2b")             # a turn whose head is past both commits
        self.assertEqual([c[3] for c in relay.closing_commits(t.p4, A, relay._session(t.p4, A))], [["#5"]],
                         "the closing commit is there to be named, and a negated or prefixed keyword closes nothing")
        self.assertEqual(t.cli(A, "done", "test_x.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "finish", report="Fixed x; suites green.", uuid="c3").returncode, 0)
        self.assertNotIn("close issues", context(t.say(TOP, "what next?")))

    def test_the_push_line_names_an_open_retrain_notice_of_a_store_the_change_touches(self):
        """The push line names, before the push, an open retrain notice of a store the change touches."""
        import notices
        t = self.t
        self.assertEqual(relay.stores_of(self.work), [relay.norm(t.p4)], "the store of the project it sits in")
        self.assertEqual(relay.owed([self.work]), [], "nothing open: nothing owed")
        notices.notify(t.p4, "json ranker", "the pool went stale", session=A)
        ctx = relay.push_text("the child", A, [(self.work, "abc1234", "lib: fix x", ["#5"])], relay.owed([self.work]))
        self.assertIn("finished with commits that close issues", ctx)
        self.assertIn("Before that push, this change owes: 1 open retrain notice in ", ctx)
        self.assertIn("retrain-needed.tsv, for json ranker", ctx)
        self.assertIn("Finish each first. Where one cannot be finished from here, name it in the report before "
                      "pushing, not after.", ctx)
        plain = relay.push_text("the child", A, [(self.work, "abc1234", "lib: fix x", ["#5"])])
        self.assertNotIn("owes", plain, "with nothing owed, the line has no owed part")
        self.assertIn("without asking ezexe", plain)

    def test_a_machine_branch_of_the_store_behind_main_is_owed(self):
        """The other machine's pull is owed when its branch of the store is behind main."""
        store = os.path.join(self.t.tmp, "solo", ".claude", "p4")
        bare = os.path.join(self.t.tmp, "store.git")
        os.makedirs(store)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, capture_output=True)
        g = ["git", "-C", store, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "main", store], check=True, capture_output=True)
        subprocess.run(g + ["remote", "add", "origin", bare], check=True, capture_output=True)
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "one"], check=True, capture_output=True)
        subprocess.run(g + ["push", "-q", "origin", "main", "main:mac"], check=True, capture_output=True)
        self.assertEqual(relay.owed([os.path.dirname(os.path.dirname(store))]), [], "every branch is at main")
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "two"], check=True, capture_output=True)
        subprocess.run(g + ["push", "-q", "origin", "main"], check=True, capture_output=True)
        got = relay.owed([os.path.dirname(os.path.dirname(store))])
        self.assertEqual(len(got), 1)
        self.assertIn("the machine branch `mac` of the store ", got[0])
        self.assertIn("is 1 commit behind main", got[0])

    def test_a_deprecation_warns_the_sibling_with_uncommitted_edits_before_any_tool(self):
        t = self.t
        mine = self.edit_uncommitted(B, ("lib", "x.py"), "b1")
        self.assertEqual(t.cli(A, "note", f"deprecates: `{self.x('lib', 'x.py')}`; the layout lives in p4conf now",
                               "--source", "commit abc123").returncode, 0)
        self.assertEqual(t.stop(A, "deprecate x", [("Edit", {"file_path": self.x("docs", "d.md")}, "ok")],
                                uuid="a1").returncode, 0)
        anchor = json.load(open(relay.anchor_path(t.p4, TOP), encoding="utf-8"))
        self.assertGreaterEqual(anchor["version"], 1)
        self.assertEqual(anchor["nodes"][A]["marks"][0]["paths"], [relay.norm(self.x("lib", "x.py"))])
        self.assertTrue(any(h.startswith(relay.norm(self.work) + "@") for h in anchor["nodes"][A]["heads"]))
        r = t.say(B, "<side-sessions-event>a session finished a turn</side-sessions-event>")
        ctx = context(r)
        first = ctx.split("\n\n")[0]
        self.assertTrue(first.startswith("phi (p4-phi): stop before any tool runs."), ctx[:300])
        self.assertIn("this session has work/lib/x.py there", first, "paths relative to the project, once")
        self.assertEqual(first.count(A), 1, "a session's id once")
        self.assertIn("message " + A, first)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("; source: commit abc123", ctx, "a deprecation is given in full, with its source")
        self.assertEqual(t.session(B)["anchorSeen"], anchor["version"])
        again = context(t.say(B, "carry on"))
        self.assertNotIn("stop before any tool runs", again, "a warning is given once")
        self.assertNotIn("deprecated or replaced", again, "nothing changed since: quiet")

    def test_a_deprecation_of_nothing_this_session_holds_is_handed_on_without_a_warning(self):
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit def456")
        t.stop(A, "replace docs", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("replaces: `", ctx)

    def test_a_note_naming_the_store_or_a_repository_top_warns_nobody(self):
        """A note naming the whole store or a repository's top folder warns nobody, and is still handed on in full."""
        t = self.t
        self.edit_uncommitted(B, ("lib", "x.py"), "b1")
        t.cli(A, "note", f"deprecates: any reading of `{t.p4}` as flat, and of `{self.work}` as one plugin",
              "--source", "commit ccc333")
        t.stop(A, "broad note", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("; source: commit ccc333", ctx, "the note is still handed on, in full")

    def test_thirty_sibling_notes_stay_under_the_cap_and_come_once(self):
        """A session with 30 sibling notes pending gets hook text under the cap, the remainder named by count and
        page, and none of the same notes on the prompt after."""
        import phi
        t = self.t
        filler = "The exporter's ports table moved to the store and the old flush path is gone. " * 12
        for k in range(27):
            self.assertEqual(t.cli(A, "note", f"replaces: narwhal exporter build {k:02d}. {filler}",
                                   "--source", f"commit far{k:02d}").returncode, 0)
        for k in range(3):
            self.assertEqual(t.cli(A, "note", f"replaces: the recall fold plan {k}: fold recall into phi as hook {k}",
                                   "--source", f"commit near{k}").returncode, 0)
        t.stop(A, "thirty notes", uuid="a30")
        ctx = context(t.say(B, "next"))
        self.assertLessEqual(len(ctx), phi.PROMPT_CHARS, "under the cap")
        for k in range(3):
            self.assertIn(f"; source: commit near{k}", ctx, "what touches its task is given in full")
        self.assertNotIn("commit far", ctx, "what does not is not shown")
        self.assertIn("deprecation or replacement notes not shown: 27", ctx, "the remainder by count")
        page = os.path.join(t.p4, "phi", "sessions", A, "session.md").replace("\\", "/")
        self.assertIn(f"27 on {page}", ctx, "and by the page that holds it")
        self.assertIn("narwhal exporter build 26", open(page, encoding="utf-8").read(), "the page holds them whole")
        again = context(t.say(B, "and after"))
        self.assertNotIn("deprecat", again, "none of the same notes on the prompt after")
        self.assertNotIn("commit near", again)
        t.stop(A, "one more turn", [("Edit", {"file_path": self.x("docs", "d.md")}, "ok")], uuid="a31")
        self.assertNotIn("replaces:", context(t.say(B, "third")), "nor when the sibling changes again")

    def test_thirty_warnings_stay_under_the_cap_and_the_rest_is_held(self):
        """An orchestrator too: what does not fit is named by count and kept on held.md, once."""
        import phi
        t = self.t
        for k in range(30):
            relay.warn(t.p4, TOP, f"note:{k}", f"warning {k:02d} of thirty: " + "a sibling changed the layout. " * 10)
        ctx = context(t.say(TOP, "what now?"))
        self.assertLessEqual(len(ctx), phi.PROMPT_CHARS)
        self.assertIn("warning 00 of thirty", ctx)
        self.assertRegex(ctx, r"\d+ more did not fit here and are whole on ")
        held = open(os.path.join(t.p4, "phi", "sessions", TOP, "held.md"), encoding="utf-8").read()
        self.assertIn("warning 29 of thirty", held)
        self.assertNotIn("of thirty", context(t.say(TOP, "and now?")), "none of them again")

    def test_a_mark_is_handed_on_once(self):
        """A session that changes again does not send its older marks again."""
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit ddd444")
        t.stop(A, "one", uuid="a1")
        self.assertIn("ddd444", context(t.say(B, "first")))
        t.cli(A, "note", f"replaces: `{self.x('docs', 'e.md')}` with the wiki", "--source", "commit eee555")
        t.stop(A, "two", uuid="a2")
        ctx = context(t.say(B, "second"))
        self.assertIn("eee555", ctx)
        self.assertNotIn("ddd444", ctx)

    def _tracked_store(self, uuid):
        t = self.t
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        self.assertEqual(t.stop(TOP, "plan it", report="Planned.", uuid=uuid).returncode, 0)
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        gd = subprocess.run(["git", "-C", t.p4, "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True).stdout.strip()
        return gd

    def _subjects(self):
        return subprocess.run(["git", "-C", self.t.p4, "log", "--format=%s"], capture_output=True,
                              text=True).stdout.splitlines()

    def test_a_hook_leaves_the_first_commit_to_a_process_of_its_own(self):
        """Inside a hook the tree's first commit is not waited on: the hook starts it in a process of its own and
        returns, and that process makes it, with the .gitignore the hook changed, and marks the tree tracked."""
        gd = self._tracked_store("hk1")
        self.assertFalse(relay.track(self.t.p4, first_only=True), "the hook does not wait for the commit")
        mark = os.path.join(gd, relay.TRACKED_MARK)
        end = time.time() + 120
        while not os.path.exists(mark) and time.time() < end:
            time.sleep(0.2)
        self.assertTrue(os.path.exists(mark), "the process of its own made the commit")
        self.assertEqual(self._subjects().count(relay.TRACK_SUBJECT), 1)
        shown = subprocess.run(["git", "-C", self.t.p4, "show", "--name-only", "--format=", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertIn(".gitignore", shown)

    def test_a_failed_first_commit_backs_off_says_so_once_and_commits_what_it_owes_on_the_retry(self):
        t = self.t
        gd = self._tracked_store("fc1")
        held = os.path.join(gd, "index.lock")                  # a stale lock of git's own: every commit fails
        write(held, "")
        self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        self.assertFalse(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)), "no mark without the commit")
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        self.assertEqual(st["fails"], 1)
        self.assertGreater(st["next"], time.time(), "tried again only after a wait")
        self.assertIn(".gitignore", st["owed"])
        self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        self.assertEqual(relay._read_json(os.path.join(gd, relay.TRACK_STATE))["fails"], 1, "not tried in the wait")
        self.assertIn("index.lock", relay.track_notice(t.p4))
        self.assertEqual(relay.track_notice(t.p4), "", "said once")
        os.remove(held)
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        relay._write_json(os.path.join(gd, relay.TRACK_STATE), dict(st, next=0))
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        shown = subprocess.run(["git", "-C", t.p4, "show", "--name-only", "--format=", "HEAD"], capture_output=True,
                               text=True).stdout.split()
        self.assertIn(".gitignore", shown, "the retry commits what the first try owed")

    def test_a_hook_spends_no_more_than_its_budget_on_git(self):
        """Every git call relay.track makes in a hook, the path filter's included, ends within TRACK_HOOK_S, however
        slow git is."""
        t = self.t
        self._tracked_store("bg1")
        real, old = relay._git, (relay.TRACK_HOOK_S, relay._start_track_first)

        def slow(cwd, *args, timeout=None):
            time.sleep(min(1.0, timeout or relay.GIT_S))
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git, relay.TRACK_HOOK_S, relay._start_track_first = slow, 2.0, lambda home: None
            began = time.time()
            relay.track(t.p4, first_only=True)
            took = time.time() - began
        finally:
            relay._git = real
            relay.TRACK_HOOK_S, relay._start_track_first = old
        self.assertLess(took, 2.0 + 1.5, "the path filter's git calls are inside the budget too")

    def test_a_running_first_commit_keeps_its_lock_fresh(self):
        """The track-first lock is touched before each git call, so a run longer than the stale limit is never taken
        for a dead one."""
        t = self.t
        gd = self._tracked_store("lk1")
        lock = os.path.join(gd, relay.TRACK_LOCK)
        real, seen = relay._git, []

        def aging(cwd, *args, timeout=None):
            if os.path.exists(lock):
                seen.append(time.time() - os.path.getmtime(lock))
                old = time.time() - relay.TRACK_STALE * relay.TRACK_S - 10
                r = real(cwd, *args, timeout=timeout)
                os.utime(lock, (old, old))            # as if this call took longer than the stale limit
                return r
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git = aging
            self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        self.assertGreater(len(seen), 2)
        self.assertLess(max(seen), 60, "touched before every call")

    def test_what_a_hook_owes_while_the_first_commit_runs_is_staged(self):
        t = self.t
        gd = self._tracked_store("ow1")
        real = relay._git

        def owing(cwd, *args, timeout=None):
            r = real(cwd, *args, timeout=timeout)
            if "commit" in args:                     # a hook records an owed file while the commit runs
                write(os.path.join(t.p4, "owed.txt"), "x\n")
                relay._owe(gd, ["owed.txt"])
            return r
        try:
            relay._git = owing
            self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        staged = subprocess.run(["git", "-C", t.p4, "diff", "--cached", "--name-only"], capture_output=True,
                                text=True).stdout.split()
        self.assertIn("owed.txt", staged)

    def test_a_staging_add_is_not_started_with_too_little_of_the_budget_left(self):
        t = self.t
        gd = self._tracked_store("ad1")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        write(os.path.join(t.p4, "phi", "new.json"), "{}\n")
        real, old, calls = relay._git, relay.TRACK_HOOK_S, []

        def seen(cwd, *args, timeout=None):
            calls.append(args[0])
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git, relay.TRACK_HOOK_S = seen, relay.TRACK_ADD_LEFT_S - 0.5
            relay.track(t.p4)
        finally:
            relay._git, relay.TRACK_HOOK_S = real, old
        self.assertNotIn("add", calls)
        self.assertTrue(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)))

    def test_the_first_commit_sets_the_path_filter_and_fails_closed_without_it(self):
        """A hook whose budget ran out before the path filter was set leaves it to track_first, which sets it before
        its add, and makes no commit when it cannot be set, since git takes an undefined filter as none."""
        t = self.t
        gd = self._tracked_store("pf1")
        real = relay._path_filter
        try:
            relay._path_filter = lambda home, g=None: False          # never set, as a hook out of budget
            self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._path_filter = real
        self.assertFalse(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)))
        self.assertNotIn(relay.TRACK_SUBJECT, self._subjects(), "no commit without the filter")
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        self.assertEqual(st["reason"], "the path filter is not set")
        subprocess.run(["git", "-C", t.p4, "config", "--local", "--unset", "filter.p4path.clean"], capture_output=True)
        relay._write_json(os.path.join(gd, relay.TRACK_STATE), dict(st, next=0))
        self.assertTrue(relay.track_first(t.p4), "track_first sets the filter itself")
        committed = subprocess.run(["git", "-C", t.p4, "show", f"HEAD:phi/sessions/{TOP}/session.json"],
                                   capture_output=True, text=True).stdout
        self.assertIn("{project}", committed)

    def test_a_failed_first_commit_keeps_what_hooks_owed_meanwhile(self):
        t = self.t
        gd = self._tracked_store("om1")
        write(os.path.join(gd, "index.lock"), "")                   # the add fails
        real = relay._git

        def owing(cwd, *args, timeout=None):
            if args[:1] == ("add",):
                relay._owe(gd, ["late.txt"])                       # a hook records an owed file meanwhile
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git = owing
            self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        self.assertIn("late.txt", relay._read_json(os.path.join(gd, relay.TRACK_STATE))["owed"])

    def test_a_commit_made_before_its_mark_is_not_made_again(self):
        t = self.t
        gd = self._tracked_store("lm1")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        os.remove(os.path.join(gd, relay.TRACKED_MARK))       # a run that ended after its commit, before its mark
        write(os.path.join(t.p4, "phi", "later.json"), "{}\n")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        self.assertEqual(self._subjects().count(relay.TRACK_SUBJECT), 1)

    def test_the_phi_folder_is_committed_once_without_logs_and_staged_after(self):
        t = self.t
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        self.assertFalse(relay.track(t.p4, first_only=True), "off until p4.json sets phi.track")
        status = subprocess.run(["git", "-C", t.p4, "status", "--porcelain", "-uall"], capture_output=True,
                                text=True).stdout                  # with tracking off, no tree file shows
        self.assertEqual(t.stop(TOP, "plan it", report="Planned.", uuid="tr1").returncode, 0)
        self.assertEqual(t.stop(A, "move it", report="Moved.", uuid="tr2").returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(t.p4, "phi", "reports.jsonl")))
        self.assertFalse([x for x in status.splitlines() if "phi/sessions/" in x or x.endswith(
            ("phi/anchor.json", "phi/reports.jsonl", "phi/start-requests.jsonl"))], status)
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        shown = subprocess.run(["git", "-C", t.p4, "show", "--name-only", "--format=%s", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(shown[:4], ["phi:", "the", "session", "tree,"])
        files = [x for x in shown if x.startswith("phi/")]
        self.assertTrue(any(x.endswith("/session.json") for x in files))
        self.assertFalse(any(x.endswith(("log.jsonl", "session.md")) for x in files), "per machine or made again")
        self.assertNotIn(relay.UNTRACKED_MARK, open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read(),
                         "tracking on takes the untracked tree's block out")
        self.assertFalse(relay.track(t.p4, first_only=True), "committed once")
        t.cli(B, "note", "the session tree is tracked in the store now", "--source", "test")
        relay.track(t.p4)
        staged = subprocess.run(["git", "-C", t.p4, "diff", "--cached", "--name-only"], capture_output=True,
                                text=True).stdout
        self.assertIn(f"phi/sessions/{B}/notes.jsonl", staged, "after the first time, staged for the next commit")
        root = pathfilter.project_of(t.p4)
        committed = subprocess.run(["git", "-C", t.p4, "show", f"HEAD:phi/sessions/{A}/session.json"],
                                   capture_output=True, text=True).stdout
        on_disk = open(os.path.join(t.p4, "phi", "sessions", A, "session.json"), encoding="utf-8").read()
        self.assertIn(root, on_disk.replace("\\\\", "/"), "the file on disk names this machine's root")
        self.assertIn("{project}", committed, "git holds the root as {project}")
        self.assertNotIn(root.lower(), committed.lower().replace("\\\\", "/"))

    def test_the_watchers_state_files_are_ignored_with_tracking_off_and_on(self):
        """A store is settled when only hook-committed paths show, so the watcher's three state files at the root of
        phi/ never show as untracked, whether phi.track is off or on."""
        t = self.t
        state = ("phi/.issue-states.json", "phi/.routes-checked", "phi/meta-ledger.md")
        for line in state:
            self.assertIn(line, relay.IGNORED)
        subprocess.run(["git", "-C", t.p4, "init", "-q"], check=True, capture_output=True)
        for line in state:
            write(os.path.join(t.p4, *line.split("/")), "{}\n")

        def shown():
            out = subprocess.run(["git", "-C", t.p4, "status", "--porcelain", "-uall"], capture_output=True,
                                 text=True).stdout
            return [x for x in out.splitlines() if x.endswith(state)]

        self.assertEqual(len(shown()), 3, "untracked before the lines are there")
        self.assertFalse(relay.track(t.p4), "tracking is off")
        self.assertEqual(shown(), [], "off: ignored all the same")
        text = open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read()
        relay.track(t.p4)
        self.assertEqual(open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read(), text, "written once")
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        relay.track(t.p4, wait=True)            # no first commit left running past the test's folder
        self.assertEqual(shown(), [], "on: still ignored")
        lines = open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read().splitlines()
        for line in state:
            self.assertEqual(lines.count(line), 1, line)

    def test_an_archived_tmp_and_lock_file_reach_another_machine_whole(self):
        """An older store's archive/ holds files named *.tmp and *.lock and one that names the project's root. The
        layout moves it to phi/archive/ at a session start, the store is committed and pushed, and a second clone
        of it holds every archived file as it was."""
        t = self.t
        g = ["-c", "user.name=t", "-c", "user.email=t@t"]
        bare = os.path.join(t.tmp, "store.git").replace("\\", "/")
        root = pathfilter.project_of(t.p4)
        kept = {"x.tmp": "a temp file the old tree kept\n", "y.lock": "a lock file the old tree kept\n",
                "z.json": json.dumps({"cwd": root}) + "\n"}
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        subprocess.run(["git", "-C", t.p4, "init", "-q", "-b", "main"], check=True, capture_output=True)
        self.assertTrue(relay.track(t.p4, wait=True), "a store p4-phi tracks, with its ignore lines and its path filter")
        for name, text in kept.items():
            write(os.path.join(t.p4, "archive", name), text)
        for args in (("add", "-A", "--", "archive", "p4.json"), (*g, "commit", "-qm", "the old archive")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, capture_output=True)
        self.assertEqual(t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}).returncode, 0)
        for name in kept:
            self.assertTrue(os.path.isfile(os.path.join(t.p4, "phi", "archive", name)), "moved under phi/")
        for args in (("add", "-A"), (*g, "commit", "-q", "--allow-empty", "-m", "the rest"), ("push", "-q", bare, "main")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        other = os.path.join(t.tmp, "other-machine").replace("\\", "/")
        subprocess.run(["git", "clone", "-q", bare, other], check=True, capture_output=True)
        for name, text in kept.items():
            path = os.path.join(other, "phi", "archive", name)
            self.assertTrue(os.path.isfile(path), f"phi/archive/{name} reaches the other machine")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"phi/archive/{name} as it was, no path rewritten")

    def test_the_path_filter_round_trips_every_spelling(self):
        root = "E:/projects/x"
        text = ('{"cwd": "E:\\\\projects\\\\x", "a": "e:/projects/x/lib/a.py", "b": "/e/projects/x/b", '
                '"c": "/mnt/e/projects/x", "d": "E:/projects/xy/no", "e": "C:/Users/me/tmp/f"}')
        out = pathfilter.clean(text, root)
        self.assertEqual(out.count("{project}"), 4)
        self.assertIn("E:/projects/xy/no", out, "a longer name is not the root")
        self.assertIn("C:/Users/me/tmp/f", out, "a path outside the project stays")
        self.assertIn('"a": "E:/projects/x/lib/a.py"', pathfilter.smudge(out, root))
        self.assertEqual(pathfilter.project_of("E:/projects/x/.claude/p4"), root)

    def test_overlapping_owned_paths_are_told_on_both_sides(self):
        t = self.t
        r = t.cli(A, "shard", self.x("lib"))
        self.assertIn("kept as this session's owned paths", r.stdout)
        r = t.cli(B, "shard", self.x("lib", "x.py"), self.x("docs"))
        self.assertIn("overlaps the owned paths of \"the layout work\"", r.stdout)
        ctx = context(t.say(A, "next"))
        self.assertIn(f"the session \"the recall work\" `{B}` declared owned paths that overlap yours", ctx)
        self.assertNotIn("overlap yours", context(t.say(A, "and next")), "told once")

    def test_uncommitted_edits_in_another_sessions_owned_paths_are_stopped(self):
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.edit_uncommitted(B, ("lib", "y.py"), "b1")
        ctx = context(t.say(B, "next"))
        self.assertIn("inside the owned paths of \"the layout work\"", ctx)
        self.assertTrue(ctx.startswith("phi (p4-phi): stop before any tool runs."))

    def test_a_message_about_another_sessions_owned_paths_is_routed_there(self):
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        ctx = context(t.say(B, f"please fix {self.x('lib', 'y.py')} too"))
        self.assertIn(f"among the owned paths of \"the layout work\" `{A}`. Send it there with SendMessage", ctx)
        self.assertNotIn("Send it there", context(t.say(B, f"please fix {self.x('docs', 'd.md')}")),
                         "a path no session owns stays here")
        self.assertNotIn("Send it there", context(t.say(TOP, f"look at {self.x('lib', 'y.py')}")),
                         "a parent's owned paths cover its children's: the parent is not routed down")

    def test_an_archived_session_owns_no_paths_and_is_not_listed(self):
        """An archived session owns no paths a message is routed by."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.assertEqual(relay.owners(t.p4, B, f"please fix {self.x('lib', 'y.py')}", t.proj)[0][0], A)
        rec = os.path.join(t.app, A + ".json")
        d = json.loads(open(rec, encoding="utf-8").read())
        d["isArchived"] = True
        write(rec, json.dumps(d))
        self.assertEqual(relay.owners(t.p4, B, f"please fix {self.x('lib', 'y.py')}", t.proj), [])
        self.assertNotIn("Send it there", context(t.say(B, f"please fix {self.x('lib', 'y.py')} too")))

    def test_the_project_root_the_store_and_a_drive_name_no_owned_paths(self):
        """The project's root, the store, the folder above the project and a drive's root name no session's owned
        paths, and a brief that names only the root is advised fresh."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        for whole in (t.proj, t.p4, os.path.dirname(t.proj), os.path.splitdrive(t.proj)[0] + "/"):
            self.assertEqual(relay.owners(t.p4, B, f"work in `{whole}` on the docs", t.proj), [], whole)
        self.assertEqual(len(relay.owners(t.p4, B, f"work in `{t.proj}` on `{self.x('lib', 'y.py')}`", t.proj)), 1,
                         "a real path beside the root is still routed")
        t.cli(TOP, "shard", self.x("docs"))
        advised, why = relay.advise_start(t.p4, TOP, {"prompt": f"Check one thing in `{t.proj}`, read-only"}, 10 * 1024)
        self.assertEqual(advised, "fresh", why)
        self.assertIn("names no path", why)
        self.assertTrue(relay.names_nothing(relay.norm(t.proj), t.p4, t.proj))
        self.assertFalse(relay.names_nothing(self.x("lib"), t.p4, t.proj))

    def test_nothing_new_is_quiet(self):
        t = self.t
        t.stop(A, "plain turn", uuid="a1")
        t.say(B, "first look")
        ctx = context(t.say(B, "second look"))
        self.assertNotIn("phi (p4-phi): what", ctx)
        self.assertNotIn("stop before", ctx)

    def test_a_child_a_sibling_supersedes_is_listed_as_ready_to_archive(self):
        """A finished child whose work a sibling's newer note supersedes is counted as archived and listed on
        ready-to-archive.md."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.assertEqual(t.cli(A, "done", "test_layout.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "move the layout", report="Moved the layout into lib.", uuid="a1").returncode, 0)
        t.cli(B, "note", f"replaces: `{self.x('lib', 'x.py')}` with p4conf's layout", "--source", "commit abc123")
        self.assertEqual(t.stop(B, "replace x", uuid="b1").returncode, 0)
        self.assertEqual(t.session(A)["stale"]["by"], B, "superseded by the sibling's newer note")
        self.assertIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "listed on ready-to-archive.md")

    def test_a_superseded_child_messaged_again_leaves_the_page(self):
        """A superseded session that is messaged again is live: it leaves ready-to-archive.md at that message, and
        the Stop that clears its mark leaves a page without it."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.assertEqual(t.cli(A, "done", "test_layout.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "move the layout", report="Moved the layout into lib.", uuid="s1").returncode, 0)
        t.cli(B, "note", f"replaces: `{self.x('lib', 'x.py')}` with p4conf's layout", "--source", "commit abc123")
        self.assertEqual(t.stop(B, "replace x", uuid="s2").returncode, 0)
        self.assertIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "superseded: listed")
        t.say(A, "go on with the layout")
        self.assertNotIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "messaged again: off the page")
        self.assertEqual(t.stop(A, "go on with the layout", report="Went on.", uuid="s3").returncode, 0)
        self.assertNotIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "the Stop leaves it off")


class ForkOrFresh(ThreeSessions):
    """The advice on start_session, a fork's pinned agenda, and a fresh child's slice of the parent's anchor."""

    def advise(self, host, context_, prompt, size):
        path = os.path.join(self._tmp.name, host + "-transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * size)
        r = self.t.hook("start-advice", host, {"hook_event_name": "PreToolUse",
                                               "tool_name": "mcp__ccd_session__start_session",
                                               "tool_input": {"initiation": "user_asked", "context": context_,
                                                              "title": "a child", "prompt": prompt + "\nFiles: none"},
                                               "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_a_fork_of_a_long_parent_is_advised_fresh(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fork", f"Fix `{self.x('lib', 'x.py')}`", 3 * 1024 * 1024)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        self.assertIn('advises context "fresh"', out["permissionDecisionReason"])
        self.assertIn("3.0 MB", out["permissionDecisionReason"])

    def test_a_fork_whose_owned_paths_are_the_parents_is_allowed(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        self.assertIsNone(self.advise(TOP, "fork", f"Rework `{self.x('lib')}`", 200 * 1024))

    def test_a_fork_of_a_short_parent_for_other_paths_is_advised_fresh(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fork", f"Write `{self.x('docs', 'new.md')}`", 10 * 1024)
        self.assertIn('advises context "fresh"', out["permissionDecisionReason"])
        self.assertIn("cover 0%", out["permissionDecisionReason"])

    def test_a_fresh_start_where_a_fork_fits_is_asked_too(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fresh", f"Rework `{self.x('lib')}`", 10 * 1024)
        self.assertIn('advises context "fork"', out["permissionDecisionReason"])

    def test_a_start_with_its_own_worktree_or_branch_is_asked(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        path = os.path.join(self._tmp.name, "short.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        for extra in ({"use_worktree": True}, {"branch_name": "my-branch"}):
            r = self.t.hook("start-advice", TOP, {"tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                                  "tool_input": {"context": "fresh", "prompt": "write docs\nFiles: none", **extra}})
            out = json.loads(r.stdout)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "ask")
            self.assertIn("use_worktree: false", out["permissionDecisionReason"])

    def test_a_child_making_its_own_branch_is_asked_and_the_top_level_session_is_not(self):
        def guard(host, cmd, tool="Bash"):
            r = self.t.hook("branch-guard", host, {"tool_name": tool, "tool_input": {"command": cmd}})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        self.assertEqual(guard(B, "git switch -c mine")["permissionDecision"], "ask")
        self.assertIsNotNone(guard(B, "", tool="EnterWorktree"))
        self.assertIsNone(guard(B, "git status && git commit -qm x"), "ordinary git is never asked")
        self.assertIsNone(guard(B, "grep -n 'git checkout -b' docs.md"), "quoted text is not a command")
        self.assertIsNone(guard(B, "git checkout -- lib/x.py"), "restoring a file is not a branch change")
        self.assertEqual(guard(B, "git switch main")["permissionDecision"], "ask", "a branch change in a child")
        self.assertIn("moves the parent's too", guard(B, "git checkout feature/x")["permissionDecisionReason"])
        self.assertIsNone(guard(TOP, "git switch -c mine"), "an orchestrator decides its own branches")

    def test_a_hand_pull_or_push_in_a_store_is_asked_and_names_p4_sync(self):
        """A store moves only by p4.py sync."""
        p4 = self.t.p4
        subprocess.run(["git", "init", "-q", p4], check=True, capture_output=True)
        clone = os.path.join(p4, "temportal", "tmp", "s1", "p4")
        os.makedirs(clone)
        subprocess.run(["git", "init", "-q", clone], check=True, capture_output=True)

        def guard(host, cmd, cwd=None):
            r = self.t.hook("store-guard", host, {"tool_name": "Bash", "tool_input": {"command": cmd},
                                                  "cwd": cwd or self.t.proj})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        for host in (TOP, B):
            out = guard(host, f"cd {p4} && git pull origin main")
            self.assertEqual(out["permissionDecision"], "ask")
            self.assertIn("sync --push --p4", out["permissionDecisionReason"])
        self.assertIn("force-push", guard(TOP, f'git -C "{p4}" push --force origin win')["permissionDecisionReason"])
        self.assertIsNotNone(guard(TOP, "git push", cwd=p4), "the call's own folder")
        self.assertIsNone(guard(TOP, f"git -C {self.work} push"), "a project checkout is not a store")
        self.assertIsNone(guard(TOP, f"cd {clone} && git push origin main"), "a clone kept in a scratchpad directory")
        self.assertIsNone(guard(TOP, f"git -C {p4} status"), "reading a store is never asked")

    def test_a_child_landing_work_is_always_asked(self):
        """ezexe/p4#232: only the tree's orchestrator merges and pushes. Neither a brief that says "Closes #7" and
        "push it yourself", a brief that names issues, an issue on the child's record, nor its parent's message lets
        a child land its own work."""
        def guard(host, cmd):
            r = self.t.hook("branch-guard", host, {"tool_name": "Bash", "tool_input": {"command": cmd}})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        for cmd in ("git push origin main", "cd /x && git merge feature", "git -C p4 rebase main", "git pull",
                    "git -C /x/work push", "git push origin HEAD:main", "x & git push", "(git push)",
                    '& "C:/Program Files/Git/cmd/git.exe" push origin main', "/usr/bin/git push", "FOO=1 git push",
                    'bash -c "git push origin main"', 'pwsh -Command "git push"', "env GIT_TRACE=1 git push",
                    "git --git-dir=/x/.git push", "git -c core.x=y push", "echo $(git push)",
                    "gh pr merge 12 --squash", "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
                    "gh api repos/o/r/merges -f base=main -f head=fix", "gh api -X PUT repos/o/r/pulls/3/merge",
                    'bash -lc "git push"', 'iex "git push"', "{ git push; }", "if x; then git push; fi",
                    "sudo -u x git push", "gh api -XDELETE repos/o/r/git/refs/heads/x",
                    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"P\"}) { a } }'",
                    "gh api graphql -f query='\nmutation {\n  mergePullRequest(input: {pullRequestId: \"P\"}) {\n"
                    "    clientMutationId\n  }\n}'",
                    'git -C "C:/Users/a b/repo" push', 'git -c "user.name=a b" push', "cmd /c git push",
                    'Invoke-Expression "git push"', 'git commit -qm "x" && git push'):
            out = guard(B, cmd)
            self.assertIsNotNone(out, cmd)
            self.assertEqual(out["permissionDecision"], "ask", cmd)
            self.assertIn("merges and pushes", out["permissionDecisionReason"])
        r = self.t.hook("branch-guard", B, {"tool_name": "PowerShell", "tool_input": {
            "command": "Set-Location C:/x; & git.exe push origin main"}})
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "ask", "a PowerShell push")
        gate = os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh")
        for k, cmd in enumerate(("gh pr merge 12", "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
                                 "/usr/bin/git push", "/usr/bin/git pull", "/usr/bin/git rebase main",
                                 "C:\\Git\\bin\\git rebase main", '"/usr/bin/git" pull',
                                 '"/usr/bin/git" rebase main')):
            body = {"session_id": CLI[B], "cwd": self.t.proj, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": cmd}, "tool_use_id": f"toolu_gate000{k}"}
            self.assertTrue(inproc.gate(json.dumps(body).encode(), self.t.proj), f"the in-process gate: {cmd}")
            r = subprocess.run(["sh", gate, "lookup-check"], input=json.dumps(body), capture_output=True,
                               text=True, encoding="utf-8", timeout=60, env=self.t.env(B))   # the script itself
            out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
            self.assertEqual(out.get("permissionDecision"), "ask", f"through the hook gate: {cmd}")
        self.assertIsNone(guard(B, "git merge-base --is-ancestor a b"), "merge-base lands nothing")
        self.assertIsNone(guard(B, "git log --grep 'push'"), "quoted words are not a command")
        self.assertIsNone(guard(B, "git log --grep push"), "a log reads")
        self.assertIsNone(guard(B, "git status"), "a status reads")
        self.assertIsNone(guard(B, "echo push"), "an echo lands nothing")
        self.assertIsNone(guard(B, 'git commit -qm "say git push to land it"'), "a message naming a push")
        self.assertIsNone(guard(B, 'git commit -q --message="then git push"'), "a --message= value is data")
        self.assertIsNone(guard(B, 'grep -rn "git push" docs/'), "a quoted pattern is data")
        self.assertIsNone(guard(B, 'echo "then git pull"'), "a quoted echo is data")
        self.assertIsNone(guard(B, 'rg "gh pr merge"'), "a quoted search is data")
        self.assertIsNone(guard(B, "cat > n.md <<'EOF'\nrun git push, then gh pr merge 3\nEOF"), "a heredoc is data")
        self.assertIsNone(guard(B, "gh api graphql -f query='query { repository(name: \"x\") { id } }'"), "a query")
        self.assertIsNone(guard(B, "gh pr view 12"), "a view lands nothing")
        self.assertIsNone(guard(B, "gh api repos/o/r/git/refs/heads/main"), "reading a ref lands nothing")
        self.assertIsNone(guard(TOP, "git push origin main"), "the orchestrator lands the work")
        s = relay._session(self.t.p4, B)
        for task in ("Fix x. Closes #7 on ezexe/demo; run the suites, then push it yourself.",
                     "Build the queue: issues #19 to #24 on ezexe/p4, the fix for each in its body."):
            s["task"] = task
            relay._write_json(os.path.join(relay._dir(self.t.p4, B), "session.json"), s)
            self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", task)
        s["issue"] = {"repo": "ezexe/demo", "number": 7, "url": "https://github.com/ezexe/demo/issues/7"}
        relay._write_json(os.path.join(relay._dir(self.t.p4, B), "session.json"), s)
        self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", "an issue on its record")
        self.t.say(B, f'<cross-session-message from="{TOP}" from-name="top">Push each green commit as it closes '
                      f'its issue.</cross-session-message>')
        self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", "its parent's message")

    def test_a_fresh_child_starts_with_only_the_slice_for_its_paths(self):
        t = self.t
        t.cli(A, "note", f"deprecates: `{self.x('lib', 'x.py')}`; use p4conf", "--source", "commit aaa111")
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit bbb222")
        t.stop(A, "two decisions", [("Edit", {"file_path": self.x("lib", "x.py")}, "ok")], uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("what the parent, \"top\", has for this session's paths", ctx)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("; source: commit aaa111", ctx)
        self.assertNotIn("bbb222", ctx, "what does not touch the child's paths is left out")
        self.assertIn("Heads to build on:", ctx)

    def test_a_fresh_childs_start_waits_for_its_brief_and_replaces_the_parents_background(self):
        """No slice before the brief, and the slice holds the parent's notes on the child's paths and no sibling's last
        turn."""
        t = self.t
        t.cli(TOP, "note", f"the docs keep their old layout in `{self.x('docs', 'd.md')}`", "--source", "fff666")
        t.cli(TOP, "note", f"the lib reads `{self.x('lib', 'x.py')}` first", "--source", "ggg777")
        t.stop(A, "a sibling's turn", uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        start = context(t.hook("session-start", GRAND, {"hook_event_name": "SessionStart", "source": "startup"}))
        self.assertNotIn("has for this session's paths", start, "no slice before the brief")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("has for this session's paths", ctx)
        self.assertIn("ggg777", ctx, "the parent's note on the child's paths")
        self.assertNotIn("fff666", ctx, "the parent's note on other paths is left out")
        self.assertNotIn("The last turn of", ctx, "the siblings' last turns are left out")

    def test_a_fresh_child_the_parent_has_nothing_for_is_told_in_one_line(self):
        t = self.t
        t.record(GRAND, TOP, title="the docs child")
        ctx = context(t.say(GRAND, f"Write `{self.x('docs', 'new.md')}`"))
        self.assertIn("It has nothing for them yet.", ctx)

    def test_a_forked_child_keeps_its_own_task_above_the_inherited_conversation(self):
        t = self.t
        t.record(GRAND, TOP, title="the forked child")
        brief = f"Fix `{self.x('lib', 'y.py')}` and nothing else"
        first = context(t.say(GRAND, "Task (from the session that started this one):\n" + brief))
        self.assertIn("this session is a fork", first)
        self.assertTrue(t.session(GRAND)["forked"])
        t.cli(GRAND, "shard", self.x("lib", "y.py"))
        later = context(t.say(GRAND, "carry on"))
        self.assertIn(f"Its own task: \"{brief}\"", later)
        self.assertIn("its owned paths: " + relay.norm(self.x("lib", "y.py")), later)
        self.assertNotIn("what the parent", later, "a fork is not given the fresh child's slice")



class MergedWorktrees(unittest.TestCase):
    """Merged worktrees and their branches are named for removal; the others are kept with why."""

    def test_merged_clean_worktrees_are_named_and_the_rest_kept(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            g = lambda cwd, *a: subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                               check=True, capture_output=True, text=True)
            write(os.path.join(repo, "a.txt"), "a\n")
            subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
            g(repo, "add", "-A")
            g(repo, "commit", "-qm", "one")
            wts = {n: os.path.join(tmp, ".claude", "worktrees", n) for n in ("done", "dirty", "open")}
            for n, p in wts.items():
                g(repo, "worktree", "add", "-q", "-b", n, p)
                write(os.path.join(p, n + ".txt"), n + "\n")
                g(p, "add", "-A")
                g(p, "commit", "-qm", n)
            g(repo, "merge", "-q", "--no-edit", "done", "dirty")
            write(os.path.join(wts["dirty"], "left.txt"), "left\n")
            gone, kept = relay.merged_worktrees(relay.repo_of(repo))
            self.assertEqual([(b, base) for _, b, base in gone], [("done", "main")])
            why = {os.path.basename(p.rstrip("/\\")): w for p, w in kept}
            self.assertEqual(why, {"dirty": "uncommitted or untracked files", "open": "open is not merged"})
            home = os.path.join(tmp, "home")
            os.makedirs(relay._dir(home, "local_top"))
            relay._write_json(os.path.join(relay._dir(home, "local_top"), "session.json"), {"sessionId": "local_top"})
            text = relay.worktrees_text(home, "local_top", relay.repo_of(repo))
            self.assertIn("git branch -d done", text)
            self.assertIn("Kept:", text)
            self.assertEqual(relay.worktrees_text(home, "local_top", relay.repo_of(repo)), "", "said once per set")

    def test_a_worktree_is_kept_for_a_stash_unpushed_commits_no_branch_or_pull_requests_gh_could_not_read(self):
        """At an orchestrator's step boundary, with no gh on PATH and with a gh that fails, a merged worktree
        whose branch has an upstream is kept as one whose pull requests could not be read, never named for removal
        as one with none. One with a stash, one with commits its upstream lacks and a detached checkout are kept with
        theirs, and a merged one that holds nothing else is named."""
        git = shutil.which("git")
        if not git:
            self.skipTest("no git")
        with tempfile.TemporaryDirectory() as tmp:
            repo, origin = os.path.join(tmp, "repo"), os.path.join(tmp, "origin.git").replace("\\", "/")
            g = lambda cwd, *a: subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                               check=True, capture_output=True, text=True)
            write(os.path.join(repo, "a.txt"), "a\n")
            write(os.path.join(repo, "s.txt"), "s\n")
            subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
            subprocess.run(["git", "init", "-q", "--bare", origin], check=True, capture_output=True)
            g(repo, "add", "-A")
            g(repo, "commit", "-qm", "one")
            g(repo, "remote", "add", "origin", origin)
            wts = {n: os.path.join(tmp, ".claude", "worktrees", n) for n in ("done", "pr", "stashed", "ahead", "loose")}
            for n in ("done", "pr", "stashed", "ahead"):     # each branch starts at main's commit, so it is merged
                g(repo, "worktree", "add", "-q", "-b", n, wts[n])
            g(repo, "worktree", "add", "-q", "--detach", wts["loose"])
            g(repo, "push", "-q", "-u", "origin", "pr", "ahead")
            write(os.path.join(wts["ahead"], "a.txt"), "a, then more\n")
            g(wts["ahead"], "commit", "-qam", "more")
            g(repo, "merge", "-q", "--ff-only", "ahead")      # merged, and a commit ahead of its upstream
            write(os.path.join(wts["stashed"], "s.txt"), "s, put aside\n")
            g(wts["stashed"], "stash", "-q")
            fails = os.path.join(tmp, "gh-fails")
            if os.name == "nt":                               # found on PATH, and `gh` cannot start a .cmd
                write(os.path.join(fails, "gh.cmd"), "@exit /b 1\n")
            else:
                write(os.path.join(fails, "gh"), "#!/bin/sh\nexit 1\n")
                os.chmod(os.path.join(fails, "gh"), 0o755)
            git_dir = os.path.dirname(git)
            for label, path in (("no gh", git_dir), ("a gh that fails", os.pathsep.join([fails, git_dir]))):
                with self.subTest(label):
                    if label == "no gh" and shutil.which("gh", path=git_dir):
                        self.skipTest("gh sits beside git, so no PATH holds git without it")
                    t = Tree(os.path.join(tmp, label.replace(" ", "-")))
                    t.record(TOP, title="top", cwd=repo)
                    r = t.hook("plan", TOP, {"hook_event_name": "PostToolUse",
                                             "tool_name": "mcp__ccd_turn__update_plan",
                                             "tool_input": {"advance": True}, "tool_response": "Plan updated."},
                               PATH=path)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    line = next((x for x in context(r).split("\n") if "worktrees whose branch is merged" in x), "")
                    self.assertIn("`git branch -d done`, merged into main", line)
                    self.assertNotIn("git branch -d pr", line, "pull requests gh could not read are not none")
                    self.assertIn(" Kept: ", line)
                    kept = dict(x.split(": ", 1) for x in line.split(" Kept: ", 1)[1].rstrip(".").split("; "))
                    self.assertEqual({os.path.basename(p.rstrip("/\\")): why for p, why in kept.items()},
                                     {"pr": "its pull requests could not be read",
                                      "stashed": "a stash on its branch",
                                      "ahead": "commits its upstream lacks",
                                      "loose": "a detached checkout, no branch to judge"})


class GhWrapper(unittest.TestCase):
    """relay._open_pr runs the gh it found, so a gh installed as a .cmd wrapper answers as gh.exe would."""

    @unittest.skipUnless(os.name == "nt", "a .cmd wrapper is a Windows install")
    def test_a_gh_cmd_wrapper_is_run(self):
        tmp = tempfile.mkdtemp(prefix="p4-phi-gh-")
        old = {k: os.environ.get(k) for k in ("PATH", "P4_PHI_GH")}
        try:
            os.environ.pop("P4_PHI_GH", None)               # an environment that names a gh cannot change the result
            os.environ["PATH"] = tmp + os.pathsep + os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
            for listed, want in (("1", True), ("0", False)):
                with open(os.path.join(tmp, "gh.cmd"), "w") as f:
                    f.write(f"@echo {listed}\n")
                self.assertEqual(relay._open_pr(tmp, "topic"), want, listed)
            # cmd.exe reads a .cmd wrapper's arguments again: a branch named x&... must run no second command
            mark = os.path.join(tmp, "ran.txt")
            for name in ("x&echo.>ran.txt", "x|echo.>ran.txt"):     # no space, so no quotes guard it
                relay._open_pr(tmp, name)
                self.assertFalse(os.path.exists(mark), name)
                r = relay.gh(["pr", "list", "--head", name], cwd=tmp)
                self.assertEqual(r.returncode, 1)
                self.assertIn("'&'" if "&" in name else "'|'", r.stderr, "the refusal names what cmd.exe would act on")
            # a comment's body, with lines and parentheses, reaches the wrapper whole as a --body-file
            with open(os.path.join(tmp, "gh.cmd"), "w") as f:
                f.write('@copy /y %7 "%~dp0got.md" >nul\n@echo ok\n')
            body = "p4-phi re-ran it: **passed** (exit code 0).\n\n```\nRan 3 tests\nOK & done | (all)\n```"
            r = relay.gh(["issue", "comment", "7", "-R", "o/r", "--body", body], cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(tmp, "got.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), body)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)


class GhSetting(unittest.TestCase):
    """P4_PHI_GH names the gh every p4-phi call runs, the worktree check's as well as the issue loop's."""

    def test_open_pr_runs_the_gh_p4_phi_gh_names(self):
        tmp = tempfile.mkdtemp(prefix="p4-phi-ghset-")
        stand_in = os.path.join(tmp, "gh_stand_in.py")
        with open(stand_in, "w", encoding="utf-8") as f:
            f.write("print(1)" + chr(10))
        old = {k: os.environ.get(k) for k in ("PATH", "P4_PHI_GH")}
        try:
            os.environ["PATH"] = tmp                         # no gh on PATH
            os.environ["P4_PHI_GH"] = stand_in
            self.assertIs(relay._open_pr(tmp, "topic"), True)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)


class SharedHome(unittest.TestCase):
    """Two projects naming one store as `phi.home`: a session in one hears a session in the other."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self.home = Tree(os.path.join(base, "home"))
        self.a = Tree(os.path.join(base, "a"))
        self.b = Tree(os.path.join(base, "b"))
        for t in (self.home, self.a, self.b):
            subprocess.run(["git", "-C", t.p4, "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.home.p4, "remote", "add", "origin", "https://example.com/team/home.git"],
                       check=True, capture_output=True)
        self.stores = os.path.join(base, "p4-stores.json")
        for t in (self.home, self.a, self.b):
            t.stores = self.stores
        write(os.path.join(self.home.p4, "p4.json"), json.dumps({"phi": {"home": "https://example.com/team/home.git"}}))
        self.home.record(TOP, title="the home")
        self.assertEqual(self.home.hook("session-start", TOP, {"source": "startup"},
                                        P4_PHI_STORES=self.stores).returncode, 0)
        self.assertEqual(json.load(open(self.stores, encoding="utf-8")),
                         {"example.com/team/home": self.home.p4}, "the start keeps this machine's folder for the remote")
        for t in (self.a, self.b):
            write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/home.git"}}))
        self.a.record(A, title="the tree in repo a")
        self.b.record(B, title="the tree in repo b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_deprecation_in_one_repo_reaches_a_session_in_the_other(self):
        a, b = self.a, self.b
        a.say(A, "Rework the exporter", P4_PHI_STORES=self.stores)
        b.say(B, "Port the exporter docs", P4_PHI_STORES=self.stores)
        self.assertTrue(os.path.isdir(os.path.join(self.home.p4, "phi", "sessions", A)), "a's tree is in the home")
        self.assertFalse(os.path.isdir(os.path.join(a.p4, "phi", "sessions", A)))
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), "note",
                        "deprecates: the exporter's v1 table, for both repositories", "--source", "commit iii999"],
                       capture_output=True, text=True, env={**a.env(A), "P4_PHI_STORES": self.stores}, cwd=a.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        a.stop(A, "deprecate v1", uuid="a1", P4_PHI_STORES=self.stores)
        ctx = context(b.say(B, "next", P4_PHI_STORES=self.stores))
        self.assertIn("deprecates: the exporter's v1 table", ctx)
        self.assertIn("; source: commit iii999", ctx)

    def test_no_map_is_written_by_a_store_that_names_no_home(self):
        other = Tree(os.path.join(self._tmp.name, "plain"))
        subprocess.run(["git", "-C", other.p4, "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", other.p4, "remote", "add", "origin", "https://example.com/team/plain.git"],
                       check=True, capture_output=True)
        other.record(TOP, title="plain")
        other.hook("session-start", TOP, {"source": "startup"}, P4_PHI_STORES=self.stores)
        self.assertNotIn("example.com/team/plain", json.load(open(self.stores, encoding="utf-8")))

    def test_a_home_this_machine_has_not_seen_is_said_once_and_the_tree_stays_home(self):
        a = self.a
        write(os.path.join(a.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/elsewhere.git"}}))
        ctx = context(a.hook("session-start", A, {"source": "startup"}, P4_PHI_STORES=self.stores))
        self.assertIn("names the shared store git@example.com:team/elsewhere.git for the session tree, and this "
                      "machine has not seen it", ctx)
        a.say(A, "Rework the exporter", P4_PHI_STORES=self.stores)
        self.assertTrue(os.path.isdir(os.path.join(a.p4, "phi", "sessions", A)), "the tree stays in its own store")


class WarnTogether(unittest.TestCase):
    def test_concurrent_warnings_keep_every_one(self):
        import threading
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            gate = threading.Barrier(12)

            def one(k):
                gate.wait()
                relay.warn(home, top, f"key{k}", f"warning number {k}")
            runs = [threading.Thread(target=one, args=(k,)) for k in range(12)]
            for r in runs:
                r.start()
            for r in runs:
                r.join()
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(len(pend), 12, "no warning is lost to another's write")
            self.assertFalse(os.path.exists(path + ".lock"))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_record_that_reads_empty_keeps_the_warning_for_later(self):
        """A warning that meets a record reading empty, as while another writer's os.replace is under way on Windows,
        is kept on a file of its own and taken in at the next locked write."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        read = relay._read_json
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            relay._read_json = lambda p: {} if p == path else read(p)
            self.assertTrue(relay.warn(home, top, "key1", "met an empty read"), "kept, not dropped")
            relay._read_json = read
            self.assertEqual(len(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json"))), 1)
            relay.warn(home, top, "key2", "written under the lock")
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(sorted(w["text"] for w in pend), ["met an empty read", "written under the lock"])
        finally:
            relay._read_json = read
            shutil.rmtree(home, ignore_errors=True)

    def test_another_write_of_the_record_never_drops_a_waiting_warning(self):
        """No other write of the record drops a waiting warning, however old the copy it writes, from phi.save_session
        or a plain write alike."""
        import threading
        import phi
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            stale = relay._read_json(path)                 # a copy a hook read before the warning came
            relay.warn(home, top, "key0", "came while a hook held an older copy")
            relay._write_json(path, {**stale, "stepRelayed": "1 x"})
            self.assertEqual(len(relay._read_json(path)["relayPending"]), 1, "a plain write keeps it")
            gate = threading.Barrier(16)

            def warns(k):
                gate.wait()
                relay.warn(home, top, f"key{k}", f"warning number {k}")

            def saves(k):
                gate.wait()
                phi.save_session(home, {**stale, "nudged": [str(k)]})
                relay._write_json(path, {**stale, "keptGoing": {"turn": str(k), "n": 1}})
            runs = [threading.Thread(target=warns if k % 2 else saves, args=(k,)) for k in range(1, 17)]
            for r in runs:
                r.start()
            for r in runs:
                r.join()
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(len(pend), 9, "the eight warnings and the first, through eight saves and eight writes")
            self.assertFalse(os.path.exists(path + ".lock"))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_lock_given_up_on_after_permission_errors_is_remembered(self):
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        real, wait = os.open, relay.LOCK_WAIT_S
        try:
            path = os.path.join(home, "session.json")

            def never(p, *a, **k):
                if str(p).endswith(".lock"):
                    raise PermissionError(13, "Permission denied", p)
                return real(p, *a, **k)
            os.open, relay.LOCK_WAIT_S = never, 0.05
            with relay.locked(path) as lk:
                self.assertFalse(lk.held)
            self.assertIn(path + ".lock", relay._GAVE_UP)
        finally:
            os.open, relay.LOCK_WAIT_S = real, wait
            relay._GAVE_UP.pop(os.path.join(home, "session.json") + ".lock", None)
            shutil.rmtree(home, ignore_errors=True)

    def test_a_permission_error_on_the_lock_is_waited_out(self):
        """Windows raises PermissionError creating a lock file another thread is removing: the lock is tried again
        within LOCK_WAIT_S, and the warning lands on the record under the lock."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        real = os.open
        hits = []
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})

            def once(p, *a, **k):
                if str(p).endswith("session.json.lock") and not hits:
                    hits.append(p)
                    raise PermissionError(13, "Permission denied", p)
                return real(p, *a, **k)
            os.open = once
            relay.warn(home, top, "key1", "after one PermissionError")
            os.open = real
            self.assertTrue(hits, "the lock met a PermissionError")
            on = [w["text"] for w in relay._read_json(path).get("relayPending") or []]
            self.assertEqual(on, ["after one PermissionError"])
            self.assertEqual(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json")), [])
        finally:
            os.open = real
            shutil.rmtree(home, ignore_errors=True)

    def test_a_child_counted_as_archived_meets_an_empty_read_and_is_kept(self):
        """A parent's record that reads empty under its lock, as while another writer's os.replace runs on Windows,
        drops no child counted as archived: the child is kept on a file of its own."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        read = relay._read_json
        try:
            path = os.path.join(relay._dir(home, "top"), "session.json")
            relay._write_json(path, {"sessionId": "top"})
            relay._read_json = lambda p: {} if p == path else read(p)
            relay._pend_archive(home, "top", "kid1", {"title": "kid one"}, "done")
            relay._read_json = read
            self.assertEqual([x["id"] for x in relay.drain_archive(home, "top")], ["kid1"])
        finally:
            relay._read_json = read
            shutil.rmtree(home, ignore_errors=True)

    def test_a_warning_that_cannot_get_the_lock_is_kept_and_drained(self):
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        wait = relay.LOCK_WAIT_S
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            relay.LOCK_WAIT_S = 0.05
            with relay.locked(path):
                self.assertTrue(relay.warn(home, top, "key1", "held back"))
                self.assertFalse(relay._read_json(path).get("relayPending"), "never written unlocked")
            relay.warn(home, top, "key2", "written under the lock")
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(sorted(w["text"] for w in pend), ["held back", "written under the lock"])
            self.assertEqual(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json")), [])
        finally:
            relay.LOCK_WAIT_S = wait
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
