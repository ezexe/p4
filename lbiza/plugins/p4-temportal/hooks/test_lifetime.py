#!/usr/bin/env python3
"""test_lifetime.py — p4-temportal's cookie and cache lifetimes, and the layout move run at a start.

    python3 -I lbiza/plugins/p4-temportal/hooks/test_lifetime.py
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
import lifetime  # noqa: E402
import p4conf  # noqa: E402

DAY = 86400


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def put(path, text="x", age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if age_days:
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))
    return path


class Lifetime(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-temportal-life-")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.t = os.path.join(self.p4, "temportal")
        os.makedirs(self.t)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lifetimes_parse(self):
        now = 1_000_000.0
        self.assertEqual(lifetime.parse_lifetime("30m", now), now + 1800)
        self.assertEqual(lifetime.parse_lifetime("2w", now), now + 14 * DAY)
        self.assertEqual(lifetime.parse_lifetime("session"), "session")
        self.assertGreater(lifetime.parse_lifetime("2099-01-01"), now)
        with self.assertRaises(ValueError):
            lifetime.parse_lifetime("soon")

    def test_the_cache_rule_clears_by_age_and_then_by_size(self):
        out = os.path.join(self.t, "scratchpad", ".out")
        put(os.path.join(out, ".gitignore"), "*\n", age_days=100)
        old = put(os.path.join(out, "old.log"), age_days=20)
        new = put(os.path.join(out, "new.log"), age_days=1)
        self.assertTrue(lifetime.sweep(self.p4).startswith("p4-temportal: cleared 1 file(s)"))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.exists(os.path.join(out, ".gitignore")), "the seed is never cleared")
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"scratchpad/.out": {"max_mb": 0.00001}}}}, f)
        big1 = put(os.path.join(out, "a.bin"), "a" * 100, age_days=3)
        big2 = put(os.path.join(out, "b.bin"), "b" * 100, age_days=2)
        lifetime.sweep(self.p4)
        self.assertFalse(os.path.exists(big1), "the oldest goes first")
        self.assertFalse(os.path.exists(big2))
        self.assertEqual(lifetime.sweep(self.p4), "", "a second sweep has nothing to clear")

    def test_memory_is_never_cleared(self):
        mem = put(os.path.join(self.t, "memory", "a.md"), age_days=400)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"memory": {"max_age_days": 1}}}}, f)
        lifetime.sweep(self.p4)
        self.assertTrue(os.path.exists(mem))
        with self.assertRaises(ValueError):
            lifetime.set_cookie(self.p4, mem, "1m")

    def test_a_cookie_expires(self):
        page = put(os.path.join(self.t, "scratchpad", "page.html"))
        keep = put(os.path.join(self.t, "scratchpad", "keep.md"))
        probe = os.path.join(self.t, "tmp", "s1", "probe")
        put(os.path.join(probe, "out.txt"))
        now = time.time()
        lifetime.set_cookie(self.p4, page, "1h", now=now)
        lifetime.set_cookie(self.p4, "tmp/s1/probe", "2d", now=now)
        lifetime.set_cookie(self.p4, keep, "1h", now=now)
        self.assertTrue(lifetime.clear_cookie(self.p4, keep))
        self.assertEqual(lifetime.sweep(self.p4, now=now + 60), "")
        line = lifetime.sweep(self.p4, now=now + 2 * 3600)
        self.assertIn("1 expired file(s): scratchpad/page.html", line)
        self.assertFalse(os.path.exists(page))
        self.assertTrue(os.path.isdir(probe))
        lifetime.sweep(self.p4, now=now + 3 * DAY)
        self.assertFalse(os.path.exists(probe), "a directory cookie clears the whole directory")
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.exists(os.path.join(self.t, lifetime.EXPIRES)), "an empty registry is removed")

    def test_a_session_cookie_ends_with_its_session(self):
        f = put(os.path.join(self.t, "scratchpad", "state.md"))
        lifetime.set_cookie(self.p4, f, "session", session_id="abc")
        lifetime.sweep(self.p4, ended_session="other")
        self.assertTrue(os.path.exists(f))
        lifetime.sweep(self.p4, ended_session="abc")
        self.assertFalse(os.path.exists(f))

    def test_a_path_outside_temportal_is_refused(self):
        with self.assertRaises(ValueError):
            lifetime.set_cookie(self.p4, os.path.join(self.p4, "p4.json"), "1d")

    def test_the_cli(self):
        f = put(os.path.join(self.t, "scratchpad", "n.md"))
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "lifetime.py"), "--p4", self.p4, "set", f, "3d"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "lifetime.py"), "--p4", self.p4, "list"],
                           capture_output=True, text=True)
        self.assertIn("cookie  scratchpad/n.md  expires", r.stdout)
        self.assertIn("cache   scratchpad/.out/", r.stdout)


class Layout(unittest.TestCase):
    """A store written flat by the older plugins moves into each plugin's directory, once, as one commit."""

    def setUp(self):
        self.p4 = tempfile.mkdtemp(prefix="p4-temportal-layout-")
        self.git = shutil.which("git")

    def tearDown(self):
        shutil.rmtree(self.p4, ignore_errors=True)

    def g(self, *a):
        return subprocess.run([self.git, "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout

    def test_a_flat_store_moves_and_is_committed(self):
        put(os.path.join(self.p4, "memory", "MEMORY.md"), "- [a](a.md)\n")
        put(os.path.join(self.p4, "store", "facts.md"), "f\n")
        put(os.path.join(self.p4, "models", "eval.tsv"), "round\n")
        put(os.path.join(self.p4, "models", "served", "x.json"), "{}")
        put(os.path.join(self.p4, "scratchpad", "note.md"), "n\n")
        put(os.path.join(self.p4, "tmp", "sid1", "a.md"), "a\n")
        put(os.path.join(self.p4, ".gitignore"), "scratchpad/.out/\nmodels/served/\n/models/*.tmp\n__pycache__/\n")
        put(os.path.join(self.p4, ".gitattributes"), "models/*.pt filter=lfs\n")
        if self.git:
            self.g("init", "-q")
            self.g("add", "-A")
            self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "flat")
        lines = p4conf.migrate_layout(self.p4)
        self.assertEqual(len(lines), 5, lines)
        for k in p4conf.LAYOUT:
            if k != "src":
                self.assertFalse(os.path.exists(os.path.join(self.p4, k)), k)
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", "memory", "MEMORY.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "phi", "store", "facts.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", "tmp", "sid1", "a.md")))
        with open(os.path.join(self.p4, ".gitignore"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "temportal/scratchpad/.out/\nphi/models/served/\n/phi/models/*.tmp\n"
                                       "__pycache__/\n")
        with open(os.path.join(self.p4, ".gitattributes"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "phi/models/*.pt filter=lfs\n")
        if self.git:
            self.assertEqual(self.g("status", "--porcelain").strip(), "", "the move is committed whole")
            self.assertIn("R100\tstore/facts.md\tphi/store/facts.md",
                          self.g("show", "-M", "--name-status", "--format=", "HEAD"))
        self.assertEqual(p4conf.migrate_layout(self.p4), [], "a second start has nothing to move")

    def test_a_store_of_the_recall_plugin_moves_into_phi(self):
        put(os.path.join(self.p4, "recall", "store", "rules.md"), "r\n")
        put(os.path.join(self.p4, "recall", "models", "eval.tsv"), "round\n")
        put(os.path.join(self.p4, "phi", "sessions", "s", "session.json"), "{}")
        put(os.path.join(self.p4, "models", "late.json"), "{}")         # a flat write from a machine not updated yet
        put(os.path.join(self.p4, ".gitignore"), "recall/models/served/\nmodels/view/\n")
        if self.git:
            self.g("init", "-q")
            self.g("add", "-A")
            self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "recall layout")
        lines = p4conf.migrate_layout(self.p4)
        self.assertIn("moved recall/store/ to phi/store/", lines)
        self.assertIn("moved recall/models/ to phi/models/", lines)
        self.assertIn("moved models/ to phi/models/", lines)
        self.assertFalse(os.path.exists(os.path.join(self.p4, "recall")), "recall/ is gone once emptied")
        for rel in (("phi", "store", "rules.md"), ("phi", "models", "eval.tsv"), ("phi", "models", "late.json"),
                    ("phi", "sessions", "s", "session.json")):
            self.assertTrue(os.path.isfile(os.path.join(self.p4, *rel)), rel)
        self.assertEqual(read(os.path.join(self.p4, ".gitignore")), "phi/models/served/\nphi/models/view/\n")
        if self.git:
            self.assertEqual(self.g("status", "--porcelain").strip(), "", "the move is committed whole")
        self.assertEqual(p4conf.migrate_layout(self.p4), [])

    def test_an_old_plugin_writing_after_the_move_is_merged(self):
        put(os.path.join(self.p4, "temportal", "memory", "a.md"), "new\n")
        put(os.path.join(self.p4, "temportal", "memory", "same.md"), "s\n")
        put(os.path.join(self.p4, "memory", "a.md"), "old\n", age_days=1)
        put(os.path.join(self.p4, "memory", "same.md"), "s\n")
        put(os.path.join(self.p4, "memory", "b.md"), "b\n")
        lines = p4conf.migrate_layout(self.p4, commit=False)
        self.assertIn("1 differing file(s) kept in temportal/.layout-conflicts/", lines[0])
        mem = os.path.join(self.p4, "temportal", "memory")
        self.assertEqual(read(os.path.join(mem, "a.md")), "new\n", "the newer copy stays")
        self.assertTrue(os.path.isfile(os.path.join(mem, "b.md")))
        aside = os.path.join(self.p4, "temportal", ".layout-conflicts", "memory", "a.md")
        self.assertEqual(read(aside), "old\n")
        self.assertFalse(os.path.exists(os.path.join(self.p4, "memory")))

    def test_a_live_session_scratchpad_follows_its_tmp(self):
        temp = tempfile.mkdtemp(prefix="p4-temportal-harness-")
        sid = "c0ffee00-0000-4000-8000-000000000001"
        old = os.path.join(self.p4, "tmp", sid)
        put(os.path.join(old, "n.md"), "n\n")
        harness = os.path.join(temp, "claude", "proj", sid, "scratchpad")
        os.makedirs(os.path.dirname(harness))
        p4conf._make_link(harness, old)
        saved = p4conf.TEMP_ROOTS
        p4conf.TEMP_ROOTS = (temp,)
        try:
            p4conf.migrate_layout(self.p4, commit=False)
        finally:
            p4conf.TEMP_ROOTS = saved
        new = os.path.join(self.p4, "temportal", "tmp", sid)
        self.assertTrue(p4conf.is_link(harness))
        self.assertTrue(os.path.samefile(harness, new), "the harness link reaches the new tmp")
        self.assertTrue(os.path.isfile(os.path.join(harness, "n.md")))
        p4conf._unlink(harness)
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
