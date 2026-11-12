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
from test_phi import KID, KID2, TOP, Tree, context, write  # noqa: E402

A, B = KID, KID2


class Paths(unittest.TestCase):
    def test_globs_and_dirs_cover_and_overlap(self):
        self.assertTrue(relay.covers("e:/w/lib", "e:/w/lib/x.py"))
        self.assertFalse(relay.covers("e:/w/lib", "e:/w/library/x.py"))
        self.assertTrue(relay.covers("e:/w/lib/*.py", "e:/w/lib/x.py"))
        self.assertTrue(relay.overlap("e:/w/lib/**", "e:/w/lib/x.py"))
        self.assertFalse(relay.overlap("e:/w/lib", "e:/w/docs"))
        self.assertEqual(relay.norm("/e/projects/x/", ""), relay.norm("E:/projects/x", ""))

    def test_the_paths_a_note_names(self):
        got = relay.paths_in("deprecates: `lib/x.py` and docs/old.md, see https://example.com/a", "E:/w")
        self.assertEqual(got, [relay.norm("E:/w/lib/x.py"), relay.norm("E:/w/docs/old.md")])


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
        self.assertIn(relay.norm(mine), first)
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
