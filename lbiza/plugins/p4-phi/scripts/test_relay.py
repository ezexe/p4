#!/usr/bin/env python3
"""relay.py: shards, deltas, anchors and the rebase check, on a three-session tree run through phi's own hooks.

    python3 -I lbiza/plugins/p4-phi/scripts/test_relay.py

The tree: a top session and two sessions it started. One of them deprecates a path the other has uncommitted edits
in; the other is warned on its next message, before any tool runs.
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
import relay  # noqa: E402
from test_phi import GRAND, KID, KID2, TOP, Tree, context, write  # noqa: E402

A, B = KID, KID2


class Paths(unittest.TestCase):
    def test_globs_and_dirs_cover_and_overlap(self):
        self.assertTrue(relay.covers("e:/w/lib", "e:/w/lib/x.py"))
        self.assertFalse(relay.covers("e:/w/lib", "e:/w/library/x.py"))
        self.assertTrue(relay.covers("e:/w/lib/*.py", "e:/w/lib/x.py"))
        self.assertTrue(relay.overlap("e:/w/lib/**", "e:/w/lib/x.py"))
        self.assertFalse(relay.overlap("e:/w/lib", "e:/w/docs"))
        self.assertEqual(relay.norm("/e/projects/x/", ""), relay.norm("E:/projects/x", ""))

    def test_a_child_is_told_its_scratch_folder_and_paths_relative(self):
        """P9 and the slice header: the child's own scratch folder, and paths as the project names them."""
        line = relay.scratch_line("E:/proj/.claude/p4", "abc-1", "E:/proj")
        self.assertIn("scratch folder is .claude/p4/temportal/tmp/abc-1/", line)
        self.assertEqual(relay.scratch_line("E:/proj/.claude/p4", "", "E:/proj"), "")
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, ".claude", "p4")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"),
                  json.dumps({"sessionId": "top", "cwd": tmp, "task": "t"}))
            kid = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "cwd": tmp,
                   "task": f"fix {tmp}/src/a.py"}
            text = relay.slice_text(home, kid)
            self.assertIn("(src/a.py)", text)
            self.assertNotIn(relay.norm(tmp), text.split("Its task")[0])
            self.assertEqual(relay.slice_text(home, dict(kid, task="no path here")), "", "P2: no empty paths line")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_first_look_relays_no_backlog_and_revisions_collapse(self):
        """RF1: a first look once replayed a day of revisions, 40 lines and 11.4 KB."""
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
                relay.warn(home, "top", f"plan:kid:{k:04d}:up", f"\"kid\", started for a step you have no plan for, "
                                                                 f"revised its plan: {k}.1 changed.")
            pend = relay._session(home, "top")["relayPending"]
            self.assertEqual(len(pend), 1)
            self.assertIn("revised its plan 5 times since you last looked; now: 4.1 changed.", pend[0]["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_git_bash_and_wsl_paths_are_absolute(self):
        """P5: /e/x as Git Bash writes it is E:/x, not a path under the base."""
        self.assertEqual(relay.paths_in("cat /e/projects/p4-phi/x/a1.txt", "E:/projects/p4-phi"),
                         [relay.norm("E:/projects/p4-phi/x/a1.txt")])
        self.assertEqual(relay.norm("/mnt/e/projects/x"), relay.norm("E:/projects/x"))

    def test_a_path_on_a_missing_drive_never_hangs(self):
        """H1: a stored mark path on a drive this machine lacks looped repo_of forever and hung every message."""
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
            self.assertIn("replaces: x", text, "the mark is still relayed")
            self.assertNotIn("stop before any tool", text)
            self.assertLess(time.time() - t0, 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_paths_a_note_names(self):
        got = relay.paths_in("deprecates: `lib/x.py` and docs/old.md, see https://example.com/a", "E:/w")
        self.assertEqual(got, [relay.norm("E:/w/lib/x.py"), relay.norm("E:/w/docs/old.md")])

    def test_a_path_on_a_missing_drive_has_no_repository(self):
        # H1: dirname("s:/") is "s:/", and the walk up once never ended, hanging every prompt hook
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
        self.assertIn("this session has work/lib/x.py there", first, "paths relative to the project, once (R1, R2)")
        self.assertEqual(first.count(A), 1, "a node's id once (R3)")
        self.assertIn("message " + A, first)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("(source: commit abc123)", ctx, "a deprecation is given in full, with its source")
        self.assertEqual(t.session(B)["anchorSeen"], anchor["version"])
        again = context(t.say(B, "carry on"))
        self.assertNotIn("stop before any tool runs", again, "a warning is given once")
        self.assertNotIn("deprecated or replaced", again, "nothing changed since: quiet")

    def test_a_deprecation_of_nothing_this_session_holds_is_relayed_without_a_warning(self):
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit def456")
        t.stop(A, "replace docs", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("replaces: `", ctx)

    def test_a_note_naming_the_store_or_a_repository_top_warns_nobody(self):
        """The false positive of 2026-11-12: a note naming the whole store warned of a session's scratch files."""
        t = self.t
        self.edit_uncommitted(B, ("lib", "x.py"), "b1")
        t.cli(A, "note", f"deprecates: any reading of `{t.p4}` as flat, and of `{self.work}` as one plugin",
              "--source", "commit ccc333")
        t.stop(A, "broad note", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("(source: commit ccc333)", ctx, "the note is still relayed, in full")

    def test_a_mark_is_relayed_once(self):
        """R4: a node that changes again does not send its older marks again."""
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit ddd444")
        t.stop(A, "one", uuid="a1")
        self.assertIn("ddd444", context(t.say(B, "first")))
        t.cli(A, "note", f"replaces: `{self.x('docs', 'e.md')}` with the wiki", "--source", "commit eee555")
        t.stop(A, "two", uuid="a2")
        ctx = context(t.say(B, "second"))
        self.assertIn("eee555", ctx)
        self.assertNotIn("ddd444", ctx)

    def test_phi_is_committed_once_without_logs_and_staged_after(self):
        t = self.t
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        self.assertFalse(relay.track(t.p4, first_only=True), "off until p4.json sets phi.track")
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        self.assertTrue(relay.track(t.p4, first_only=True))
        shown = subprocess.run(["git", "-C", t.p4, "show", "--name-only", "--format=%s", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(shown[:4], ["phi:", "the", "session", "tree,"])
        files = [x for x in shown if x.startswith("phi/")]
        self.assertTrue(any(x.endswith("/session.json") for x in files))
        self.assertFalse(any(x.endswith(("log.jsonl", "session.md")) for x in files), "per machine or made again")
        self.assertFalse(relay.track(t.p4, first_only=True), "committed once")
        t.cli(B, "note", "the session tree is tracked in the store now", "--source", "test")
        relay.track(t.p4)
        staged = subprocess.run(["git", "-C", t.p4, "diff", "--cached", "--name-only"], capture_output=True,
                                text=True).stdout
        self.assertIn(f"phi/sessions/{B}/notes.jsonl", staged, "after the first time, staged for the next commit")

    def test_overlapping_shards_are_told_on_both_sides(self):
        t = self.t
        r = t.cli(A, "shard", self.x("lib"))
        self.assertIn("kept as this session's shard", r.stdout)
        r = t.cli(B, "shard", self.x("lib", "x.py"), self.x("docs"))
        self.assertIn("overlaps the shard of \"the layout work\"", r.stdout)
        ctx = context(t.say(A, "next"))
        self.assertIn(f"the session \"the recall work\" ({B}) declared a shard that overlaps yours", ctx)
        self.assertNotIn("overlaps yours", context(t.say(A, "and next")), "told once")

    def test_uncommitted_edits_in_another_nodes_shard_are_stopped(self):
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.edit_uncommitted(B, ("lib", "y.py"), "b1")
        ctx = context(t.say(B, "next"))
        self.assertIn("inside the shard of \"the layout work\"", ctx)
        self.assertTrue(ctx.startswith("phi (p4-phi): stop before any tool runs."))

    def test_a_message_about_another_nodes_shard_is_routed_there(self):
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        ctx = context(t.say(B, f"please fix {self.x('lib', 'y.py')} too"))
        self.assertIn(f"which is the shard of \"the layout work\" ({A}). Send it there with SendMessage", ctx)
        self.assertNotIn("Send it there", context(t.say(B, f"please fix {self.x('docs', 'd.md')}")),
                         "a path no shard covers stays here")
        self.assertNotIn("Send it there", context(t.say(TOP, f"look at {self.x('lib', 'y.py')}")),
                         "a parent's shard covers its children's: the parent is not routed down")

    def test_nothing_new_is_quiet(self):
        t = self.t
        t.stop(A, "plain turn", uuid="a1")
        t.say(B, "first look")
        ctx = context(t.say(B, "second look"))
        self.assertNotIn("phi (p4-phi): what", ctx)
        self.assertNotIn("stop before", ctx)



class ForkOrFresh(ThreeSessions):
    """The advice on start_session, a fork's pinned agenda, and a fresh child's slice of the parent's anchor."""

    def advise(self, host, context_, prompt, size):
        path = os.path.join(self._tmp.name, host + "-transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * size)
        r = self.t.hook("start-advice", host, {"hook_event_name": "PreToolUse",
                                               "tool_name": "mcp__ccd_session__start_session",
                                               "tool_input": {"initiation": "user_asked", "context": context_,
                                                              "title": "a child", "prompt": prompt},
                                               "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_a_fork_of_a_long_parent_is_advised_fresh(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fork", f"Fix `{self.x('lib', 'x.py')}`", 3 * 1024 * 1024)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        self.assertIn('advises context "fresh"', out["permissionDecisionReason"])
        self.assertIn("3.0 MB", out["permissionDecisionReason"])

    def test_a_fork_whose_shard_is_the_parents_is_allowed(self):
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
                                                  "tool_input": {"context": "fresh", "prompt": "write docs", **extra}})
            out = json.loads(r.stdout)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "ask")
            self.assertIn("use_worktree: false", out["permissionDecisionReason"])

    def test_a_child_making_its_own_branch_is_asked_and_the_top_is_not(self):
        def guard(host, cmd, tool="Bash"):
            r = self.t.hook("branch-guard", host, {"tool_name": tool, "tool_input": {"command": cmd}})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        self.assertEqual(guard(B, "git switch -c mine")["permissionDecision"], "ask")
        self.assertIsNotNone(guard(B, "", tool="EnterWorktree"))
        self.assertIsNone(guard(B, "git status && git commit -qm x"), "ordinary git is never asked")
        self.assertIsNone(guard(B, "grep -n 'git checkout -b' docs.md"), "quoted text is not a command (G1)")
        self.assertIsNone(guard(B, "git checkout -- lib/x.py"), "restoring a file is not a branch change")
        self.assertEqual(guard(B, "git switch main")["permissionDecision"], "ask", "a branch change in a child (G2)")
        self.assertIn("moves the parent's too", guard(B, "git checkout feature/x")["permissionDecisionReason"])
        self.assertIsNone(guard(TOP, "git switch -c mine"), "a top session decides its own branches")

    def test_a_fresh_child_starts_with_only_its_shards_slice(self):
        t = self.t
        t.cli(A, "note", f"deprecates: `{self.x('lib', 'x.py')}`; use p4conf", "--source", "commit aaa111")
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit bbb222")
        t.stop(A, "two decisions", [("Edit", {"file_path": self.x("lib", "x.py")}, "ok")], uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("what the parent, \"top\", has for this session's paths", ctx)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("(source: commit aaa111)", ctx)
        self.assertNotIn("bbb222", ctx, "what does not touch the child's paths is left out")
        self.assertIn("Heads to build on:", ctx)

    def test_a_fresh_childs_start_waits_for_its_brief_and_replaces_the_parents_background(self):
        """F1 and F2 of the marketplace test session."""
        t = self.t
        t.cli(TOP, "note", f"the docs keep their old layout in `{self.x('docs', 'd.md')}`", "--source", "fff666")
        t.cli(TOP, "note", f"the lib reads `{self.x('lib', 'x.py')}` first", "--source", "ggg777")
        t.stop(A, "a sibling's turn", uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        start = context(t.hook("session-start", GRAND, {"hook_event_name": "SessionStart", "source": "startup"}))
        self.assertNotIn("has for this session's paths", start, "no slice before the brief (F1)")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("has for this session's paths", ctx)
        self.assertIn("ggg777", ctx, "the parent's note on the child's paths")
        self.assertNotIn("fff666", ctx, "the parent's note on other paths is left out (F2)")
        self.assertNotIn("The last turn of", ctx, "the siblings' last turns are left out (F2)")

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
        self.assertIn("its shard: " + relay.norm(self.x("lib", "y.py")), later)
        self.assertNotIn("what the parent", later, "a fork is not given the fresh child's slice")



class SharedHome(unittest.TestCase):
    """Two projects naming one home store: a session in one hears a session in the other."""

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
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), "note",
                            "deprecates: the exporter's v1 table, for both repositories", "--source", "commit iii999"],
                           capture_output=True, text=True, env={**a.env(A), "P4_PHI_STORES": self.stores}, cwd=a.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        a.stop(A, "deprecate v1", uuid="a1", P4_PHI_STORES=self.stores)
        ctx = context(b.say(B, "next", P4_PHI_STORES=self.stores))
        self.assertIn("deprecates: the exporter's v1 table", ctx)
        self.assertIn("(source: commit iii999)", ctx)

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
        self.assertIn("names the home store git@example.com:team/elsewhere.git, which this machine has not seen", ctx)
        a.say(A, "Rework the exporter", P4_PHI_STORES=self.stores)
        self.assertTrue(os.path.isdir(os.path.join(a.p4, "phi", "sessions", A)), "the tree stays in its own store")


if __name__ == "__main__":
    unittest.main(verbosity=1)
