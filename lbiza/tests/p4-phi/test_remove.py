#!/usr/bin/env python3
"""upkeep.remove, the command `phi.py remove`: a clean, landed worktree goes with its branch, and nothing goes
where the worktree holds work or the shell stands in it.

    python -m pytest tests/p4-phi/test_remove.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import upkeep  # noqa: E402


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Remove(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.origin, self.main = os.path.join(root, "origin.git"), os.path.join(root, "main")
        git(root, "init", "-q", "--bare", "-b", "main", self.origin)
        git(root, "init", "-q", "-b", "main", self.main)
        self.write(self.main, "a.txt", "a")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-q", "-m", "first")
        git(self.main, "remote", "add", "origin", self.origin)
        git(self.main, "push", "-q", "-u", "origin", "main")
        self.tree = os.path.join(self.main, ".claude", "worktrees", "feat")
        git(self.main, "worktree", "add", "-q", "-b", "feat", self.tree)
        self.write(self.tree, "b.txt", "b")
        git(self.tree, "add", "-A")
        git(self.tree, "commit", "-q", "-m", "second")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def write(folder, name, text):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)

    def branches(self):
        return git(self.main, "branch", "--format=%(refname:short)").split()

    def test_a_merged_worktree_goes_with_its_branch(self):
        git(self.main, "merge", "-q", "--ff-only", "feat")
        git(self.main, "push", "-q", "origin", "main")
        status, lines = upkeep.remove(self.tree, self.main)
        self.assertEqual(status, 0, lines)
        self.assertFalse(os.path.exists(self.tree))
        self.assertNotIn("feat", self.branches())

    def test_a_branch_landed_as_another_commit_of_the_same_patch_goes_too(self):
        self.assertIs(upkeep.landed(self.main, "feat"), False, "its commit is on no default branch yet")
        git(self.main, "cherry-pick", "feat")
        git(self.main, "commit", "-q", "--amend", "-m", "second, landed by a rebase")
        git(self.main, "push", "-q", "origin", "main")
        self.assertIs(upkeep.on_default(self.main, "feat"), False, "another hash")
        self.assertIs(upkeep.landed(self.main, "feat"), True, "the same patch")
        status, lines = upkeep.remove(self.tree, self.main)
        self.assertEqual(status, 0, lines)
        self.assertFalse(os.path.exists(self.tree))
        self.assertNotIn("feat", self.branches())

    def test_nothing_goes_where_the_worktree_holds_work_or_the_shell_stands_in_it(self):
        status, _ = upkeep.remove(self.tree, self.main)
        self.assertEqual(status, 2, "its commit is not on the default branch")
        git(self.main, "merge", "-q", "--ff-only", "feat")
        git(self.main, "push", "-q", "origin", "main")
        self.assertEqual(upkeep.remove(self.tree, self.tree)[0], 2, "the shell stands in it")
        self.write(self.tree, "c.txt", "c")
        self.assertEqual(upkeep.remove(self.tree, self.main)[0], 2, "an uncommitted change")
        self.assertTrue(os.path.isdir(self.tree))
        self.assertIn("feat", self.branches())

    def test_what_a_failed_removal_left_is_deleted(self):
        left = os.path.join(self.main, ".claude", "worktrees", "gone")
        os.makedirs(left)
        self.write(left, "x.txt", "x")
        self.assertEqual(upkeep.remove(left, self.main)[0], 2, "it holds a file git does not ignore")
        self.write(os.path.join(self.main, ".git", "info"), "exclude", ".claude/\n")
        self.assertEqual(upkeep.remove(left, left)[0], 2, "the shell stands in it")
        status, lines = upkeep.remove(left, self.main)
        self.assertEqual(status, 0, lines)
        self.assertFalse(os.path.exists(left))
        self.assertEqual(upkeep.remove(os.path.join(self.main, "docs"), self.main)[0], 2, "no folder to remove")
