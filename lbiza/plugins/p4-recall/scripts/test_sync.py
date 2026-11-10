#!/usr/bin/env python3
"""sync.py: two machines' branches of a store merged into main and moved up to it, each kind of file by its rule.

    python3 -I lbiza/plugins/p4-recall/scripts/test_sync.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sync  # noqa: E402

RULES = "The owner's rulings.\nWritten when the owner rules.\nFields: ruling, time.\n\n- ruling: the base rule\n  time: 2026-11-01 10:00\n"
LABELS = "task\tentry\tlabel\n"
EVAL = "round\ttime\tlabels\n0\t2026-11-01 10:00\t1\n"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.org"}


def sh(cwd, *a):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise AssertionError(f"{a}: {r.stderr or r.stdout}")
    return r.stdout


def write(root, rel, text, mode="w"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = os.path.realpath(self.tmp.name)
        self.origin = os.path.join(t, "origin.git")
        sh(t, "git", "init", "-q", "--bare", "-b", "main", self.origin)
        seed = os.path.join(t, "seed")
        sh(t, "git", "clone", "-q", self.origin, seed)
        write(seed, "store/rules.md", RULES)
        write(seed, "models/labels.tsv", LABELS)
        write(seed, "models/eval.tsv", EVAL)
        write(seed, "models/ranker.json", json.dumps({"w": [1, 1]}))
        write(seed, "p4.json", json.dumps({"recall": {"inject": "rules-facts", "deps": {"roots": []}}}, indent=1) + "\n")
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "-q", "-m", "seed")
        sh(seed, "git", "push", "-q", "origin", "HEAD:main", "HEAD:win", "HEAD:mac")
        self.win, self.mac, self.runner = (os.path.join(t, n) for n in ("win", "mac", "runner"))
        for d, b in ((self.win, "win"), (self.mac, "mac")):
            sh(t, "git", "clone", "-q", "-b", b, self.origin, d)
        sh(t, "git", "clone", "-q", self.origin, self.runner)       # the workflow's checkout
        self.home = os.getcwd()

    def tearDown(self):
        os.chdir(self.home)
        self.tmp.cleanup()

    def machine(self, d, name, round_time, root, weights):
        write(d, "store/rules.md", f"\n- ruling: the {name} rule\n  time: 2026-11-0{2 if name == 'win' else 3} 10:00\n", "a")
        write(d, "models/labels.tsv", f"t-{name}\trepo:a.py\t1\nt-shared\trepo:b.py\t1\n", "a")
        write(d, "models/eval.tsv", f"1\t{round_time}\t9\n", "a")
        write(d, "models/ranker.json", json.dumps({"w": weights}))
        write(d, f"store/messages/{name}0001.md", f"rows of {name}\n")
        write(d, "memory/MEMORY.md", f"# Memory index\n\n- [Shared](shared.md) — on both machines\n- [Of {name}]({name}.md) — its own\n")
        cfg = json.loads(read(d, "p4.json"))
        cfg["recall"]["deps"]["roots"] = ["library_packages", root]
        if name == "mac":
            cfg["recall"]["inject"] = False
        write(d, "p4.json", json.dumps(cfg, indent=1) + "\n")
        sh(d, "git", "add", "-A")
        sh(d, "git", "commit", "-q", "-m", f"{name} works")
        sh(d, "git", "push", "-q", "origin", "HEAD")

    def run_all(self, *extra):
        os.chdir(self.runner)
        try:
            return sync.main(["all", *extra])
        finally:
            os.chdir(self.home)

    def tip(self, branch):
        return sh(self.origin, "git", "rev-parse", branch).strip()

    def test_all_merges_by_kind_and_moves_every_branch_up(self):
        self.machine(self.win, "win", "2026-11-05 10:00", "Z:/code/chromium_git", [2, 2])
        self.machine(self.mac, "mac", "2026-11-07 10:00", "/Users/x/code/chromium_git", [3, 3])
        before = sh(self.runner, "git", "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.assertEqual(self.run_all("--push"), 0)
        self.assertEqual(sh(self.runner, "git", "rev-parse", "--abbrev-ref", "HEAD").strip(), before,
                         "the checkout it ran from never moved")
        self.assertEqual(self.tip("main"), self.tip("win"))
        self.assertEqual(self.tip("main"), self.tip("mac"))
        out = os.path.join(os.path.dirname(self.origin), "out")
        sh(os.path.dirname(self.origin), "git", "clone", "-q", self.origin, out)
        rules = read(out, "store/rules.md")
        for want in ("the base rule", "the win rule", "the mac rule"):
            self.assertEqual(rules.count(want), 1, want)
        labels = read(out, "models/labels.tsv").splitlines()
        self.assertEqual(labels[0], "task\tentry\tlabel")
        self.assertEqual(sorted(labels[1:]), ["t-mac\trepo:a.py\t1", "t-shared\trepo:b.py\t1", "t-win\trepo:a.py\t1"],
                         "both machines' rows, the shared one once")
        cfg = json.loads(read(out, "p4.json"))
        self.assertEqual(cfg["recall"]["deps"]["roots"], ["library_packages", "/Users/x/code/chromium_git", "Z:/code/chromium_git"],
                         "every machine's roots (mac was merged first: alphabetical)")
        self.assertIs(cfg["recall"]["inject"], False, "one side changed the key: its value")
        self.assertEqual(json.loads(read(out, "models/ranker.json")), {"w": [3, 3]}, "the later round's model, whole")
        self.assertEqual(read(out, "models/eval.tsv").splitlines()[-1], "1\t2026-11-07 10:00\t9")
        self.assertNotIn("2026-11-05", read(out, "models/eval.tsv"), "and its record with it, not a mix")
        index = read(out, "memory/MEMORY.md")
        self.assertEqual((index.count("- [Shared](shared.md)"), index.count("- [Of win]"), index.count("- [Of mac]")), (1, 1, 1),
                         "an index line both machines wrote is kept once")
        for name in ("win", "mac"):
            self.assertTrue(os.path.exists(os.path.join(out, "store", "messages", f"{name}0001.md")))
        tips = self.tip("main")
        self.assertEqual(self.run_all("--push"), 0)
        self.assertEqual(self.tip("main"), tips, "a second run changes nothing")

    def test_without_push_nothing_leaves(self):
        self.machine(self.win, "win", "2026-11-05 10:00", "Z:/c", [2, 2])
        main = self.tip("main")
        self.assertEqual(self.run_all(), 0)
        self.assertEqual(self.tip("main"), main)
        self.assertNotIn("p4-sync", sh(self.runner, "git", "worktree", "list"), "the worktree is gone")
        import glob
        self.assertEqual(glob.glob(os.path.join(tempfile.gettempdir(), "p4-sync-*")), [], "and so is its temp folder")

    def test_pull_brings_main_into_a_machine_with_its_own_commit(self):
        self.machine(self.mac, "mac", "2026-11-07 10:00", "/Users/x/c", [3, 3])
        self.assertEqual(self.run_all("--push"), 0)
        write(self.win, "store/rules.md", "\n- ruling: the win rule, written offline\n  time: 2026-11-08 10:00\n", "a")
        sh(self.win, "git", "commit", "-q", "-am", "win offline")
        os.chdir(self.win)
        self.assertEqual(sync.main(["pull", "--push"]), 0)
        os.chdir(self.home)
        rules = read(self.win, "store/rules.md")
        self.assertIn("the mac rule", rules)
        self.assertIn("written offline", rules)
        self.assertEqual(self.tip("win"), sh(self.win, "git", "rev-parse", "HEAD").strip())
        write(self.win, "store/rules.md", "dirty\n", "a")
        os.chdir(self.win)
        self.assertEqual(sync.main(["pull"]), 1, "uncommitted tracked changes: refused, nothing merged")
        self.assertEqual(sync.main(["pull", "--snapshot"]), 0, "or committed first, when asked")
        self.assertIn("win's work so far", sh(self.win, "git", "log", "-1", "--format=%s"))

    def test_p4_sync_all_from_a_machine(self):
        """`p4.py sync --all --push` on a live checkout: seeds and commits the workflow, commits what the hooks
        changed, pushes, merges every branch in a worktree, and leaves this branch at the merged commit."""
        self.machine(self.mac, "mac", "2026-11-07 10:00", "/Users/x/c", [3, 3])
        write(self.win, "models/labels.tsv", "t-live\trepo:c.py\t1\n", "a")        # a hook wrote this; nobody committed
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "p4.py"), "sync", "--all", "--push", "--p4", self.win],
                           capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        head = sh(self.win, "git", "rev-parse", "HEAD").strip()
        self.assertEqual((self.tip("main"), self.tip("win"), self.tip("mac")), (head, head, head))
        self.assertEqual(sh(self.win, "git", "rev-parse", "--abbrev-ref", "HEAD").strip(), "win")
        self.assertIn("t-live", read(self.win, "models/labels.tsv"))
        self.assertIn("the mac rule", read(self.win, "store/rules.md"))
        self.assertTrue(os.path.exists(os.path.join(self.win, ".github", "workflows", "p4-sync.yml")))
        self.assertEqual(sh(self.win, "git", "status", "--porcelain").strip(), "")

    def test_entries_merge_field_by_field_and_a_freeing_stays(self):
        head = "The owner's rulings.\nWritten when the owner rules.\nFields: ruling, status, time.\n"
        ent = lambda name, status, extra="": f"\n- ruling: the {name} rule\n  scope: everywhere\n  status: {status}\n  time: 2026-11-02 10:00\n{extra}"
        base = (head + ent("au", "LIVE") + ent("old", "LIVE")).encode()
        ours = (head + ent("au", "LIVE") + ent("old", "LIVE") + ent("mac", "LIVE")).encode()
        theirs = (head + ent("au", 'FREED (2026-11-09, "lift it")', "  plain: lifted\n") + ent("win", "LIVE")).encode()
        for a, b in ((ours, theirs), (theirs, ours)):
            got = sync.merge_entries(base, a, b).decode()
            self.assertEqual(got.count("status:"), 3, "one status line an entry")
            self.assertIn('- ruling: the au rule\n  scope: everywhere\n  status: FREED (2026-11-09, "lift it")\n  time: 2026-11-02 10:00\n  plain: lifted', got)
            self.assertNotIn("the old rule", got, "one machine removed it, the other left it alone: gone")
            self.assertEqual((got.count("the mac rule"), got.count("the win rule")), (1, 1))
            self.assertTrue(got.startswith(head))
        both = sync.merge_entries(base, (head + ent("au", "SPENT")).encode(), (head + ent("au", "LIVE (again)")).encode()).decode()
        self.assertIn("status: SPENT", both, "both changed it: what is no longer LIVE stays that way")
        self.assertIsNone(sync.merge_entries(b"", b"plain text\n", b"other text\n"), "no entries: the caller unions lines")
        voc = lambda *why: ("Terms.\n\n- term: lmk\n  means: let me know\n" + "".join(f"  because: {w}\n" for w in why)).encode()
        got = sync.merge_entries(voc("first"), voc("first", "on mac"), voc("first", "on win")).decode()
        self.assertEqual([l.strip() for l in got.splitlines() if "because" in l],
                         ["because: first", "because: on mac", "because: on win"], "a repeated field keeps every occurrence")
        twice = (head + "\n- key: cmake\n  time: 2026-11-01 10:00\n  meant: a\n\n- key: cmake\n  time: 2026-11-05 10:00\n  meant: b\n").encode()
        self.assertEqual(sync.merge_entries(twice, twice, twice).decode().count("- key: cmake"), 2, "a repeated key is two entries")

    def test_merge_json(self):
        m = sync.merge_json
        self.assertEqual(m({"a": 1, "b": 2}, {"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 2}), {"a": 9, "b": 2, "c": 3})
        self.assertEqual(m({"a": 1}, {"a": 2}, {"a": 3}), {"a": 2}, "both changed it: ours")
        self.assertEqual(m({"a": 1, "b": 1}, {"a": 1}, {"a": 1, "b": 1}), {"a": 1}, "we removed b, they left it: gone")
        self.assertEqual(m(None, {"l": ["x"]}, {"l": ["y", "x"]}), {"l": ["x", "y"]})

    def test_seed_writes_updates_and_respects_the_owner(self):
        p4 = os.path.join(os.path.dirname(self.origin), "p4")
        os.makedirs(p4)
        self.assertEqual(sync.seed(p4, "trunk"), [".github/workflows/p4-sync.yml", ".github/p4_sync.py"])
        wf = read(p4, ".github/workflows/p4-sync.yml")
        self.assertIn("python3 .github/p4_sync.py all --main trunk --push", wf)
        self.assertIn("contents: write", wf)
        self.assertNotIn("{main}", wf)
        self.assertEqual(read(p4, ".github/p4_sync.py"), read(HERE, "sync.py"), "the script the plugin runs, verbatim")
        self.assertEqual(sync.seed(p4, "trunk"), [])
        write(p4, ".github/workflows/p4-sync.yml", wf + "# drifted\n")
        self.assertEqual(sync.seed(p4, "trunk"), [".github/workflows/p4-sync.yml"], "a seeded copy that differs is replaced")
        mine = "name: mine\n"
        write(p4, ".github/workflows/p4-sync.yml", mine)
        self.assertEqual(sync.seed(p4, "trunk"), [])
        self.assertEqual(read(p4, ".github/workflows/p4-sync.yml"), mine, "without the seed line it is the owner's")
        r = subprocess.run([sys.executable, "-I", os.path.join(p4, ".github", "p4_sync.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
