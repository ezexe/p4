#!/usr/bin/env python3
"""A label follows its file through a rename, and falls back to the file when only its symbol is gone.

    python3 -I lbiza/plugins/p4-recall/scripts/test_renames.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import repo  # noqa: E402
import store as st  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.org"}
BODY = "def open_narwhal_port():\n    return 1\n\n\ndef close_narwhal_port():\n    return 0\n" + "# filler line\n" * 20


def sh(cwd, *a):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise AssertionError(f"{a}: {r.stderr or r.stdout}")
    return r.stdout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class Renames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(os.path.realpath(self.tmp.name), "proj")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(p4conf.sub(self.p4, "models"))
        os.makedirs(p4conf.sub(self.p4, "store"))
        write(os.path.join(self.proj, ".gitignore"), ".claude/\n")
        write(os.path.join(self.proj, "src", "port.py"), BODY)
        write(os.path.join(self.proj, "src", "gone.py"), "def vanish():\n    return 2\n")
        sh(self.proj, "git", "init", "-q")
        self.commit("first")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, msg):
        sh(self.proj, "git", "add", "-A")
        sh(self.proj, "git", "commit", "-q", "-m", msg)

    def ids(self):
        repo.build(self.p4, self.proj)
        self.idx = st.build_index(self.p4)
        return {d["id"] for d in self.idx["docs"]}

    def test_a_label_follows_two_renames_and_a_vanished_symbol(self):
        old_sym = f"repo:src/port.py#{repo.sha8('open_narwhal_port')}"
        self.assertIn(old_sym, self.ids())
        self.assertEqual(repo.rename_map(self.p4), {})
        sh(self.proj, "git", "mv", "src/port.py", "src/narwhal.py")
        self.commit("rename once")
        ids = self.ids()
        self.assertEqual(repo.rename_map(self.p4), {"src/port.py": "src/narwhal.py"})
        os.makedirs(os.path.join(self.proj, "lib"))
        sh(self.proj, "git", "mv", "src/narwhal.py", "lib/narwhal.py")
        write(os.path.join(self.proj, "lib", "narwhal.py"), BODY.replace("def close_narwhal_port", "def shut_narwhal_port"))
        sh(self.proj, "git", "rm", "-q", "src/gone.py")
        self.commit("rename again, drop a symbol, delete a file")
        ids = self.ids()
        self.assertEqual(repo.rename_map(self.p4), {"src/port.py": "lib/narwhal.py", "src/narwhal.py": "lib/narwhal.py"},
                         "read incrementally, and a path renamed twice maps straight to its last name")
        ren = repo.rename_map(self.p4)
        new_sym = f"repo:lib/narwhal.py#{repo.sha8('open_narwhal_port')}"
        self.assertEqual(lb.follow(old_sym, ids, ren), new_sym, "the same symbol, under the file's new path")
        self.assertEqual(lb.follow("repo:src/port.py", ids, ren), "repo:lib/narwhal.py")
        self.assertEqual(lb.follow(f"repo:src/narwhal.py#{repo.sha8('close_narwhal_port')}", ids, ren), "repo:lib/narwhal.py",
                         "the symbol is gone, its file is there: the file's own entry")
        self.assertEqual(lb.follow("repo:src/gone.py", ids, ren), "repo:src/gone.py", "a deleted file's label is left as it is")
        self.assertEqual(lb.follow("rules.md:2026-11-01 10:00:abcdef12", ids, ren), "rules.md:2026-11-01 10:00:abcdef12")
        self.assertIn("2 renamed paths followed", repo.stats_line(self.p4))

    def test_training_labels_are_moved_to_the_current_entry(self):
        self.ids()
        lb.write_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD, [
            {"task": "t1", "entry": "repo:src/port.py", "label": "1", "source": "repo", "weight": "1.0", "time": "2026-11-01 10:00",
             "teacher": "", "edited": "", "note": "edited"},
            {"task": "t1", "entry": "repo:src/gone.py", "label": "0", "source": "repo", "weight": "0.3", "time": "2026-11-01 10:00",
             "teacher": "", "edited": "", "note": "dropped"}])
        sh(self.proj, "git", "mv", "src/port.py", "src/narwhal.py")
        self.commit("rename")
        self.ids()
        got = {r["entry"]: r["label"] for r in lb.training_labels(self.p4, self.idx)}
        self.assertEqual(got, {"repo:src/narwhal.py": 1, "repo:src/gone.py": 0})
        self.assertEqual({r["entry"] for r in lb.training_labels(self.p4)}, {"repo:src/port.py", "repo:src/gone.py"},
                         "without an index nothing is moved, and labels.tsv itself is never rewritten")
        self.assertEqual(lb.followed(self.p4, lb.training_labels(self.p4), self.idx)[1], 1)

    def test_merge_renames(self):
        self.assertEqual(repo.merge_renames({"a": "b", "x": "y"}, {"b": "c", "p": "q"}), {"a": "c", "x": "y", "b": "c", "p": "q"})
        self.assertEqual(repo.merge_renames({"a": "b"}, {"b": "a"}), {"b": "a"}, "renamed back: nothing to follow from a")


if __name__ == "__main__":
    unittest.main()
