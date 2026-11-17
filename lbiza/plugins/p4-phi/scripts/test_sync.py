#!/usr/bin/env python3
"""sync.py: two machines' branches of a store merged into main and moved up to it, each kind of file by its rule.

    python3 -I lbiza/plugins/p4-phi/scripts/test_sync.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import sync  # noqa: E402

RULES = "ezexe's rulings.\nWritten when ezexe rules.\nFields: ruling, time.\n\n- ruling: the base rule\n  time: 2026-11-01 10:00\n"
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
        # a flat store at the top: sync.logical reads every path by its name inside the plugin's directory, so
        # these merges hold for phi/ alike, and test_the_session_tree_merges_across_machines writes phi/ itself
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
                         "every machine's roots, mac's first, since the branches merge in alphabetical order")
        self.assertIs(cfg["recall"]["inject"], False, "one side changed the key: its value")
        self.assertEqual(json.loads(read(out, "models/ranker.json")), {"w": [3, 3]}, "the later round's model, whole")
        self.assertEqual(read(out, "models/eval.tsv").splitlines(),
                         ["round\ttime\tlabels", "0\t2026-11-01 10:00\t1", "1\t2026-11-05 10:00\t9", "1\t2026-11-07 10:00\t9"],
                         "the training log keeps both machines' rounds in time order: neither history is replaced")
        index = read(out, "memory/MEMORY.md")
        self.assertEqual((index.count("- [Shared](shared.md)"), index.count("- [Of win]"), index.count("- [Of mac]")), (1, 1, 1),
                         "an index line both machines wrote is kept once")
        for name in ("win", "mac"):
            self.assertTrue(os.path.exists(os.path.join(out, "store", "messages", f"{name}0001.md")))
        tips = self.tip("main")
        self.assertEqual(self.run_all("--push"), 0)
        self.assertEqual(self.tip("main"), tips, "a second run changes nothing")

    def test_the_session_tree_merges_across_machines(self):
        """phi/ tracked: a session's rows from both machines in time order, its plan step by step."""
        sid = "local_s1"
        base = {"steps": [{"addr": "1", "content": "a", "status": "in_progress"},
                          {"addr": "2", "content": "b", "status": "pending"}], "current": "1", "version": 1}
        for d in (self.win, self.mac):
            sh(d, "git", "pull", "-q", "origin", "main")
        write(self.win, f"phi/sessions/{sid}/plan.json", json.dumps(base, indent=1))
        write(self.win, f"phi/sessions/{sid}/turns.jsonl", json.dumps({"time": "2026-11-12 10:00", "id": "t0"}) + "\n")
        sh(self.win, "git", "add", "-A")
        sh(self.win, "git", "commit", "-q", "-m", "tree")
        sh(self.win, "git", "push", "-q", "origin", "HEAD:main", "HEAD:win", "HEAD:mac", "-f")
        sh(self.mac, "git", "fetch", "-q", "origin")
        sh(self.mac, "git", "reset", "-q", "--hard", "origin/mac")
        win_plan = dict(base, version=2, current="2", steps=[dict(base["steps"][0], status="completed"),
                                                             dict(base["steps"][1], status="in_progress")])
        write(self.win, f"phi/sessions/{sid}/plan.json", json.dumps(win_plan, indent=1))
        write(self.win, f"phi/sessions/{sid}/turns.jsonl", json.dumps({"time": "2026-11-12 11:00", "id": "win"}) + "\n", "a")
        mac_plan = dict(base, version=3, steps=[base["steps"][0], dict(base["steps"][1], content="b, revised")])
        write(self.mac, f"phi/sessions/{sid}/plan.json", json.dumps(mac_plan, indent=1))
        write(self.mac, f"phi/sessions/{sid}/turns.jsonl", json.dumps({"time": "2026-11-12 10:30", "id": "mac"}) + "\n", "a")
        for d, n in ((self.win, "win"), (self.mac, "mac")):
            sh(d, "git", "add", "-A")
            sh(d, "git", "commit", "-q", "-m", f"{n} tree")
            sh(d, "git", "push", "-q", "origin", "HEAD")
        self.assertEqual(self.run_all("--push"), 0)
        out = os.path.join(os.path.dirname(self.origin), "out-tree")
        sh(os.path.dirname(self.origin), "git", "clone", "-q", self.origin, out)
        ids = [json.loads(l)["id"] for l in read(out, f"phi/sessions/{sid}/turns.jsonl").splitlines()]
        self.assertEqual(ids, ["t0", "mac", "win"], "both machines' rows, each once, by time")
        plan = json.loads(read(out, f"phi/sessions/{sid}/plan.json"))
        self.assertEqual(plan["version"], 3, "the higher version gives the rest")
        self.assertEqual(plan["steps"][1]["content"], "b, revised")
        self.assertEqual(plan["steps"][0]["status"], "completed", "the later status wins, from either side")

    def test_merge_plan_keeps_the_lower_sides_new_steps_and_tasks(self):
        """The lower version's added step is kept after the higher's steps, moved to the next free address when its
        own is taken, and a step both sides hold keeps both sides' tasks and the later status."""
        base = {"version": 1, "steps": [{"addr": "1", "content": "a", "status": "pending"},
                                        {"addr": "2", "content": "b", "status": "pending"}]}
        lo = {"version": 2, "steps": [{"addr": "1", "content": "a", "status": "in_progress",
                                       "tasks": [{"id": "t1", "status": "open"}]},
                                      {"addr": "2", "content": "b", "status": "pending"},
                                      {"addr": "3", "content": "c, added here", "status": "pending"}]}
        hi = {"version": 3, "steps": [{"addr": "1", "content": "a", "status": "pending",
                                       "tasks": [{"id": "t2", "status": "open"}]},
                                      {"addr": "2", "content": "b, reworded", "status": "pending"},
                                      {"addr": "3", "content": "d, added there", "status": "pending"}]}
        out = json.loads(sync.merge_plan(json.dumps(lo), json.dumps(hi), json.dumps(base)))
        words = [x["content"] for x in out["steps"]]
        self.assertEqual(words, ["a", "b, reworded", "d, added there", "c, added here"])
        self.assertEqual(out["steps"][3]["addr"], "4", "a taken address moves to the next free one")
        self.assertEqual(out["steps"][0]["status"], "in_progress")
        self.assertEqual(sorted(t["id"] for t in out["steps"][0]["tasks"]), ["t1", "t2"])
        removed = dict(hi, steps=hi["steps"][:2])
        out = json.loads(sync.merge_plan(json.dumps(lo), json.dumps(removed), json.dumps(base)))
        self.assertNotIn("b", [x["content"] for x in out["steps"]], "a base step the higher side reworded stays gone")

    def test_without_push_nothing_leaves(self):
        self.machine(self.win, "win", "2026-11-05 10:00", "Z:/c", [2, 2])
        main = self.tip("main")
        own = os.path.join(os.path.realpath(self.tmp.name), "temp")   # a temp directory of this test's own: a sync
        os.makedirs(own)                                                # running elsewhere on the machine is not seen
        kept, tempfile.tempdir = tempfile.tempdir, own
        try:
            self.assertEqual(self.run_all(), 0)
        finally:
            tempfile.tempdir = kept
        self.assertEqual(self.tip("main"), main)
        self.assertNotIn("p4-sync", sh(self.runner, "git", "worktree", "list"), "the worktree is gone")
        self.assertEqual(os.listdir(own), [], "and so is its temp folder")

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
        # p4.py sync moves the flat store into the plugins' layout first: store.find_p4 calls p4conf.migrate_layout
        self.assertIn("t-live", read(self.win, p4conf.rel("models", "labels.tsv")))
        self.assertIn("the mac rule", read(self.win, p4conf.rel("store", "rules.md")))
        self.assertTrue(os.path.exists(os.path.join(self.win, ".github", "workflows", "p4-sync.yml")))
        self.assertEqual(sh(self.win, "git", "status", "--porcelain").strip(), "")

    def test_entries_merge_field_by_field_and_a_freeing_stays(self):
        head = "ezexe's rulings.\nWritten when ezexe rules.\nFields: ruling, status, time.\n"
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

    def test_a_sync_names_every_entry_whose_state_changed(self):
        """A sync names each entry whose fields changed, so the session checks them instead of trusting a clean
        merge."""
        ent = lambda name, status: f"\n- ruling: the {name} rule\n  status: {status}\n  time: 2026-11-02 10:00\n"
        write(self.win, "store/rules.md", "Rulings.\n" + ent("au", "LIVE") + ent("old", "LIVE"))
        sh(self.win, "git", "add", "-A")
        sh(self.win, "git", "commit", "-q", "-m", "one")
        old = sh(self.win, "git", "rev-parse", "HEAD").strip()
        write(self.win, "store/rules.md", "Rulings.\n" + ent("au", "FREED (2026-11-09)") + ent("new", "LIVE"))
        sh(self.win, "git", "commit", "-q", "-am", "two")
        os.chdir(self.win)
        try:
            got = "\n".join(sync.entry_changes(old, sh(self.win, "git", "rev-parse", "HEAD").strip()))
        finally:
            os.chdir(self.home)
        self.assertIn("the au rule: status: LIVE -> FREED (2026-11-09)", got)
        self.assertIn("new entry - ruling: the new rule", got)
        self.assertIn("entry gone: - ruling: the old rule", got)

    def test_settings_git_merged_cleanly_are_still_merged_by_key(self):
        """Two machines each add a `deps` block to p4.json, far enough apart that git merges the lines without a
        conflict and the file holds the key twice; and both change the same line of a script, which is then one
        side whole, never both sides' lines."""
        def strict(pairs):
            keys = [k for k, _ in pairs]
            self.assertEqual(len(keys), len(set(keys)), f"a key twice: {keys}")
            return dict(pairs)
        long = {"recall": {**{f"k{i}": i for i in range(12)}}}
        for d in (self.win, self.mac):
            sh(d, "git", "pull", "-q")
        write(self.win, "p4.json", json.dumps(long, indent=1) + "\n")
        write(self.win, ".github/p4_sync.py", "# seeded\nA = 1\nB = 1\nC = 1\n")
        sh(self.win, "git", "add", "-A")
        sh(self.win, "git", "commit", "-q", "-m", "long settings")
        sh(self.win, "git", "push", "-q", "origin", "HEAD:win", "HEAD:mac", "HEAD:main")
        sh(self.mac, "git", "pull", "-q", "origin", "mac")
        text = read(self.win, "p4.json")
        write(self.win, "p4.json", text.replace('  "k0": 0,', '  "deps": {\n   "roots": ["Z:/c"]\n  },\n  "k0": 0,'))
        write(self.win, ".github/p4_sync.py", "# seeded\nA = 2\nB = 1\nC = 1\n")
        sh(self.win, "git", "commit", "-q", "-am", "win deps")
        sh(self.win, "git", "push", "-q", "origin", "HEAD")
        write(self.mac, "p4.json", text.replace('  "k11": 11', '  "k11": 11,\n  "deps": {\n   "roots": ["/Users/x/c"]\n  }'))
        write(self.mac, ".github/p4_sync.py", "# seeded\nA = 3\nB = 1\nC = 1\n")        # the same line: a conflict
        sh(self.mac, "git", "commit", "-q", "-am", "mac deps")
        sh(self.mac, "git", "push", "-q", "origin", "HEAD")
        plain = os.path.join(os.path.dirname(self.origin), "plain")          # what git alone does with it
        sh(os.path.dirname(self.origin), "git", "clone", "-q", "-b", "mac", self.origin, plain)
        subprocess.run(["git", "merge", "-q", "--no-edit", "origin/win"], cwd=plain, capture_output=True, env=ENV)   # stops on the script
        self.assertEqual(read(plain, "p4.json").count('"deps"'), 2, "git merges the lines cleanly and the key is there twice")
        self.assertEqual(self.run_all("--push"), 0)
        out = os.path.join(os.path.dirname(self.origin), "out2")
        sh(os.path.dirname(self.origin), "git", "clone", "-q", self.origin, out)
        cfg = json.loads(read(out, "p4.json"), object_pairs_hook=strict)
        self.assertEqual(cfg["recall"]["deps"]["roots"], ["/Users/x/c", "Z:/c"])
        self.assertIn(read(out, ".github/p4_sync.py"), ("# seeded\nA = 2\nB = 1\nC = 1\n", "# seeded\nA = 3\nB = 1\nC = 1\n"),
                      "a conflicted script is one machine's whole, never both sides' lines")

    def test_merge_settings_settles_written_values_by_their_records(self):
        """Of two machines' p4.json, a written value loses to one set by hand, the newer generation's written default
        wins over an older one, and the merged record keeps only written values."""
        m = sync.merge_settings
        rec = lambda v, g: {"v": v, "gen": g}
        base = {"q": {"n": 5, "k": 1}, "_written": {"q.n": rec(5, 1), "q.k": rec(1, 1)}}
        newer = {"q": {"n": 9, "k": 1}, "_written": {"q.n": rec(9, 2), "q.k": rec(1, 2)}}
        hand = {"q": {"n": 7, "k": 1}, "_written": {"q.k": rec(1, 1)}}
        older = {"q": {"n": 5, "k": 1}, "_written": {"q.n": rec(5, 1), "q.k": rec(1, 1)}}
        for ours, theirs in ((newer, hand), (hand, newer)):
            got = m(base, ours, theirs)
            self.assertEqual(got["q"]["n"], 7, "set by hand beats a newer written default")
            self.assertNotIn("q.n", got["_written"])
        for ours, theirs in ((newer, older), (older, newer)):
            got = m(base, ours, theirs)
            self.assertEqual(got["q"]["n"], 9, "the newer generation's default")
            self.assertEqual(got["_written"]["q.n"], rec(9, 2))
        pre = {"q": {"n": 5, "k": 1}}                       # a machine from before the record, at the seeded default
        got = m(None, pre, newer, {"q": {"n": 5, "k": 1}})
        self.assertEqual(got["q"]["n"], 9)

    def test_merge_settings_reads_the_common_ancestor(self):
        """A machine from before the record whose value is the ancestor's has not set it by hand, so the other
        machine's written default wins and keeps its record entry, with or without seeded defaults; a setting one
        side removed stays removed; a recorded path under a value that is no section raises nothing."""
        m = sync.merge_settings
        base = {"t": {"model": "fable-5-1"}, "q": {"n": 5}}
        moved = {"t": {"model": "fable-5-2"}, "q": {"n": 5},
                 "_written": {"t.model": {"v": "fable-5-2", "gen": 1}, "q.n": {"v": 5, "gen": 1}}}
        pre = {"t": {"model": "fable-5-1"}, "q": {"n": 5}, "other": 1}
        for ours, theirs in ((moved, pre), (pre, moved)):
            for dflt in (None, {"t": {"model": "fable-5-2"}, "q": {"n": 5}}):
                got = m(base, ours, theirs, dflt)
                self.assertEqual(got["t"]["model"], "fable-5-2")
                self.assertEqual(got["_written"]["t.model"], {"v": "fable-5-2", "gen": 1})
                self.assertEqual(got["other"], 1)
        gone = {"t": {"model": "fable-5-1"}, "q": {}}
        self.assertNotIn("n", m(base, moved, gone)["q"], "removed on one side, unchanged on the other: removed")
        odd = {"t": "not a section", "q": {"n": 5}, "_written": {"t.model": {"v": "x", "gen": 1}}}
        m(base, odd, pre)
        m(base, pre, odd)

    def test_merge_settings_keeps_the_entry_of_a_setting_only_the_newer_side_has(self):
        """A setting a newer plugin added, absent from the older side and from the ancestor, keeps its record entry."""
        rec = lambda v, g: {"v": v, "gen": g}
        base = {"q": {"n": 5}, "_written": {"q.n": rec(5, 1)}}
        ours = {"q": {"n": 6}, "_written": {}}
        theirs = {"q": {"n": 5, "x": 3}, "_written": {"q.n": rec(5, 2), "q.x": rec(3, 2)}}
        for a, b in ((ours, theirs), (theirs, ours)):
            got = sync.merge_settings(base, a, b)
            self.assertEqual(got["q"], {"n": 6, "x": 3})
            self.assertEqual(got["_written"], {"q.x": rec(3, 2)})

    def test_merge_json(self):
        m = sync.merge_json
        d = {"said": {"mode": "off"}}
        self.assertEqual(m({}, {"said": {"mode": "off"}}, {"said": {"mode": "shadow"}}, d), {"said": {"mode": "shadow"}},
                         "a key new on both sides: the written default loses to the value a person set")
        self.assertEqual(m({}, {"said": {"mode": "shadow"}}, {"said": {"mode": "off"}}, d), {"said": {"mode": "shadow"}})
        self.assertEqual(m({"said": {"mode": "shadow"}}, {"said": {"mode": "off"}}, {"said": {"mode": "shadow"}}, d),
                         {"said": {"mode": "off"}}, "a key that was there and was set back to the default is a choice")
        self.assertEqual(m({"a": 1, "b": 2}, {"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 2}), {"a": 9, "b": 2, "c": 3})
        self.assertEqual(m({"a": 1}, {"a": 2}, {"a": 3}), {"a": 2}, "both changed it: ours")
        self.assertEqual(m({"a": 1, "b": 1}, {"a": 1}, {"a": 1, "b": 1}), {"a": 1}, "we removed b, they left it: gone")
        self.assertEqual(m(None, {"l": ["x"]}, {"l": ["y", "x"]}), {"l": ["x", "y"]})

    def test_seed_writes_updates_and_keeps_a_copy_without_the_seed_line(self):
        p4 = os.path.join(os.path.dirname(self.origin), "p4")
        os.makedirs(p4)
        self.assertEqual(sync.seed(p4, "trunk"), [".github/p4_defaults.json", ".github/workflows/p4-sync.yml", ".github/p4_sync.py"])
        self.assertEqual(json.loads(read(p4, ".github/p4_defaults.json"))["recall"]["said"], {"mode": "off"})
        wf = read(p4, ".github/workflows/p4-sync.yml")
        self.assertIn("python3 .github/p4_sync.py all --main trunk --push", wf)
        self.assertIn("contents: write", wf)
        self.assertNotIn("{main}", wf)
        self.assertEqual(read(p4, ".github/p4_sync.py"), read(HERE, "sync.py"), "the script the plugin runs, verbatim")
        self.assertEqual(sync.seed(p4, "trunk"), [])
        write(p4, ".github/workflows/p4-sync.yml", wf + "# drifted\n")
        self.assertEqual(sync.seed(p4, "trunk"), [".github/workflows/p4-sync.yml"], "a seeded copy that differs is replaced")
        self.assertNotIn("{seed}", wf)
        newer = wf.replace(f"# seed {sync.SEED}", f"# seed {sync.SEED + 1}") + "# from a newer plugin\n"
        write(p4, ".github/workflows/p4-sync.yml", newer)
        self.assertEqual(sync.seed(p4, "trunk"), [], "a copy a newer plugin seeded is never replaced by this one")
        self.assertEqual(read(p4, ".github/workflows/p4-sync.yml"), newer)
        write(p4, ".github/workflows/p4-sync.yml", wf)
        mine = "name: mine\n"
        write(p4, ".github/workflows/p4-sync.yml", mine)
        self.assertEqual(sync.seed(p4, "trunk"), [])
        self.assertEqual(read(p4, ".github/workflows/p4-sync.yml"), mine, "without the seed line it is ezexe's")
        r = subprocess.run([sys.executable, "-I", os.path.join(p4, ".github", "p4_sync.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_training_log_keeps_one_header_with_the_machine_column(self):
        """A log from a plugin that writes the `machine` column merged with one from a plugin that does not keeps the
        wider header once, and every round of both, in time order."""
        old = "round\ttime\twhy\n"
        new = "round\ttime\twhy\tmachine\n"
        got = sync.merge_log(old.encode(), (new + "1\t2026-11-02 10:00\tx\twin\n").encode(),
                             (old + "1\t2026-11-01 10:00\ty\n").encode()).decode()
        self.assertEqual(got, new + "1\t2026-11-01 10:00\ty\n1\t2026-11-02 10:00\tx\twin\n")

    def test_the_seeded_text_is_pinned_to_its_seed(self):
        """seed replaces a store's copy of sync.py that differs and holds no higher SEED, so two plugin versions with
        one SEED and two texts would rewrite each other's copies at every seed. Each SEED's text is pinned here: a
        change to sync.py raises SEED and records its text's hash, and a copy of a lower SEED is replaced."""
        import hashlib
        with open(os.path.join(HERE, "sync.py"), "rb") as f:
            text = f.read().replace(b"\r\n", b"\n")
        self.assertEqual({sync.SEED: hashlib.sha1(text).hexdigest()[:12]}, {17: "4c73defe651c"},
                         "sync.py changed: raise SEED and pin the new text")
        p4 = os.path.join(os.path.dirname(self.origin), "p4")
        os.makedirs(p4)
        sync.seed(p4, "main")
        older = text.decode().replace(f"SEED = {sync.SEED} ", f"SEED = {sync.SEED - 1} ") + "# an older plugin's\n"
        write(p4, ".github/p4_sync.py", older)
        self.assertEqual(sync.seed(p4, "main"), [".github/p4_sync.py"], "a copy of a lower SEED is replaced")
        self.assertEqual(read(p4, ".github/p4_sync.py"), read(HERE, "sync.py"))


if __name__ == "__main__":
    unittest.main()
