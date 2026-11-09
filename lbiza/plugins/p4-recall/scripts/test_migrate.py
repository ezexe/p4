#!/usr/bin/env python3
"""Tests for migrate.py (fresh-marketplace.md section 6, 8.1's migrate bullet).

Run: python3 test_migrate.py

A synthetic old tree, built here, covers every row of the migration table; the four cloned repos, when present,
are migrated dry into a temp directory (and ap-p4_mac also applied): every check passes, zero unplaced entries,
counts equal to `scripts/session/store_lessons.py`, the six finding-17 rulings LIVE, archives byte-identical.
The clones are read only; nothing is written into them.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import migrate  # noqa: E402
import store as st  # noqa: E402
from test_store import NOW, REPOS, fixture, write  # noqa: E402

LESSONS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "scripts", "session", "store_lessons.py"))


def store_lessons():
    if not os.path.exists(LESSONS):
        return None
    spec = importlib.util.spec_from_file_location("store_lessons", LESSONS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HEADER = "# VLDS Partition\n\nWhat it holds.\n\n```yaml\n- ruling: [the ruling]\n  time: [YYYY-MM-DD HH:MM]\n```\n\n---\n\n"


def old_tree(root):
    """An old p4 tree: two sessions, every file kind of the migration table."""
    p4 = os.path.join(root, "old")
    s1 = os.path.join(p4, "sessions", "mac-setup--150e7eb7", "vlds")
    s2 = os.path.join(p4, "sessions", "a3ac5de6", "vlds")
    write(os.path.join(s1, "local-storage.md"), HEADER + """- ruling: pull every repo the work spans before a long build starts
  owner-words: "updates u need to pull from both repos then start"
  scope: this Mac
  status: LIVE
  time: 2026-10-28 23:00

- ruling: the Mac's branch is mac_mac, cut under the base
  owner-words: "yes switch under base but branch mac_mac"
  status: LIVE
  time: 2026-11-01 11:18

- ruling: move what landed in ~/gritz into ~/code
  owner-words: "clean what ended up in ~/gritz"
  status: SPENT
  time: 2026-10-29 10:44

- ruling: the old harness keeps its flag in the test runner, all of them
  owner-words: "keep it in the runner"
  status: LIVE
  time: 2026-10-20 09:00
""")
    write(os.path.join(s1, "tombstones.md"), HEADER + """```yaml
- freed: the CEF notice run started before the repos were pulled
  time: 2026-10-28 23:00
  cause: superseded
  owner-words: "updates u need to pull from both repos then start"
  lesson: pull every repo first
```

```yaml
- freed: the Mac's branch named 0.0.1-1.0.0_mac
  time: 2026-11-01 11:18
  owner-words: "yes switch under base but branch mac_mac"
```

- freed: the old harness keeps its flag in the test runner, all of them, kept for CI
  time: 2026-10-25 09:00
""")
    write(os.path.join(s1, "ledger.md"), HEADER + """```yaml
correction:
  key: mac-branch-name
  time: 2026-11-01 11:18
  match: 0.0.1-1.0.0_mac, the README's name
  meant: mac_mac, cut under the base
  delta: renamed
```

- event: 7aaa4c84 commits the mapping
  time: 2026-10-20 09:55
  match: round 43 as picked
""")
    write(os.path.join(s1, "briefs.md"), HEADER + """```yaml
- asked: "why that one?"
  time: 2026-11-01 11:30
  on: widget «Branch»
  at: closing
  omitted: why
```
""")
    write(os.path.join(s1, "dispatch.md"), "# Dispatch\n\n```yaml\n- fingerprint: [the clause]\n  time: [YYYY]\n"
          "  state: FRESH | ECHO | SUPERSEDED\n```\n\n---\n\n" + """- fingerprint: "rename it to the mac branch thing"
  time: 2026-11-01 11:17
  arrival: turn
  state: FRESH
  addressed: renamed it to 0.0.1-1.0.0_mac

- fingerprint: "yes switch under base but branch mac_mac"
  time: 2026-11-01 11:18
  arrival: turn

  state: FRESH
  addressed: switched; the branch is mac_mac
- fingerprint: "Push it"
  time: 2026-11-01 11:21
  arrival: turn
  state: FRESH
  addressed: pushed

- fingerprint: "Push it"
  time: 2026-11-01 11:25
  arrival: turn
  state: ECHO
  match: the 11:21 row, already pushed
  addressed: nothing new to push

- fingerprint: "why that one?"
  time: 2026-11-01 11:30
  arrival: turn

- why that one?
  addressed: explained the branch choice
""")
    write(os.path.join(s1, "data-store.md"), HEADER + """- claim: the CEF C API wraps refcounted objects on each side
  time: 2026-10-12 18:14
  verified: 2026-10-12 18:14
  source: cpptoc_ref_counted.h:31
""")
    write(os.path.join(s1, "logger.md"), HEADER + "- 2026-10-20 09:00 **a log line** about the run\n")
    write(os.path.join(s1, "session-storage.md"), HEADER + "- task: build it\n  state: done\n")
    write(os.path.join(s1, "phi-index.md"), "derived\n")
    write(os.path.join(s1, ".turn-close"), "x")
    write(os.path.join(s1, "idb", "keys.tsv"), "k\tv\n")
    write(os.path.join(s1, "idb", "runs", "data-store-000001.md"), "- claim: poured\n  time: 2026-09-01 00:00\n")
    write(os.path.join(s2, "index.md"), HEADER + """- key: build + timing
  decision: rule
  directive: say the build's time
  owner-words: "always say how long"
""")
    write(os.path.join(s2, "dispatch.md"), "- fingerprint: \"Push it\"\n  time: 2026-10-13 09:00\n  arrival: turn\n"
          "  state: FRESH\n  addressed: pushed 3dce9c0\n")
    write(os.path.join(s2, "recall-pool.md"), """# Recall pool

session: a3ac5de6
task: rename the Mac branch
pooled: 2026-11-02 09:00
read: local-storage.md (children)

## steering — bears on the task

- [local-storage.md 2026-11-01 11:18 LIVE] the Mac's branch is mac_mac, cut under the base; bears: the branch
- [tombstones.md 2026-10-25 09:00 LIVE] the old harness keeps its flag; bears: the harness
- [logger.md 2026-10-20 09:00 LIVE] a log line; bears: the run
- [data-store.md 2026-01-01 00:00 LIVE] a claim no store holds; bears: nothing
""")
    write(os.path.join(p4, "sessions", "a3ac5de6", "src", "frags.md"), "# Frags\n\n---\n\n"
          "- frag: probe/probe.py\n  time: 2026-10-01 00:00\n  task: probe the narwhal port\n  state: live\n")
    write(os.path.join(p4, "sessions", "a3ac5de6", "src", "probe", "probe.py"), "#!/usr/bin/env python3\nprint(1)\n")
    write(os.path.join(p4, "sessions", "a3ac5de6", "mind-reader", "state.json"), "{}")
    write(os.path.join(p4, "models", "pick-model.json"), '{"kind": "vlds pick ranker", "w": {}}')
    write(os.path.join(p4, "models", "ranker-base.pt"), "binary")
    write(os.path.join(p4, "models", "labels", "a3ac5de6.tsv"), "# session: a3ac5de6\n# task: audit task\n"
          "# pooled: 2026-11-02 10:00\n# reader: mister:roboto\nlocal-storage.md\t2026-10-28 23:00\tpull every repo\n")
    write(os.path.join(p4, "vindex", "phi-index.md"), "# index\n\n## recall\n\npool-road: model\n\n## other\n")
    write(os.path.join(p4, "mrindex", "model.json"), "{}")
    write(os.path.join(p4, "memory", "MEMORY.md"), "- [a](a.md)\n")
    write(os.path.join(p4, "memory", "a.md"), "# A\n\nbody\n")
    write(os.path.join(p4, "scratchpad", "notes.md"), "notes\n")
    write(os.path.join(p4, "flights", "20261102-0445-s1", "plan.md"), "flight: 20261102-0445-s1\n")
    write(os.path.join(p4, "flights", "board.tsv"), "id\tplan\tsection\tairspace\tstate\ttower\n")
    write(os.path.join(p4, ".gitignore"), "scratchpad/.out/\n")
    return p4


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = old_tree(self.tmp.name)
        self.out = os.path.join(self.tmp.name, "new")

    def tearDown(self):
        self.tmp.cleanup()

    def run_dry(self):
        return migrate.run(self.old, self.out, apply=False, now=NOW)

    def test_dry_writes_only_the_report(self):
        r = self.run_dry()
        files = [os.path.relpath(os.path.join(a, f), self.out) for a, _d, fs in os.walk(self.out) for f in fs]
        self.assertEqual(files, ["archive/migration-2026-11-01.md"])
        self.assertTrue(all(ok for _n, ok, _d in r["checks"]), [c for c in r["checks"] if not c[1]])
        self.assertEqual(r["plan"].unplaced, [])

    def test_counts_and_statuses(self):
        r = self.run_dry()
        self.assertEqual(r["counts"]["correction"], 1)
        self.assertEqual(r["counts"]["retraction"], 3)
        self.assertEqual(r["counts"]["missed"], 1)
        self.assertEqual(r["counts"]["repeat"], 1)
        self.assertEqual(r["counts"]["claim"], 1)
        rules = {e.value: e.state for e in r["files"]["rules.md"]}
        self.assertEqual(rules["pull every repo the work spans before a long build starts"], "LIVE")
        self.assertEqual(rules["the Mac's branch is mac_mac, cut under the base"], "LIVE")
        self.assertEqual(rules["move what landed in ~/gritz into ~/code"], "SPENT")
        self.assertEqual(rules["the old harness keeps its flag in the test runner, all of them"], "FREED")
        self.assertEqual(len(r["finding17"]), 2)
        self.assertTrue(all(s == "LIVE" for _i, _t, s in r["finding17"]))
        self.assertEqual(len(r["live_new"]), 2)
        self.assertEqual(len(r["live_lost"]), 1, "the harness ruling: freed by a later retraction naming it")

    def test_rows_joined_and_counted(self):
        r = self.run_dry()
        rows = r["files"]["messages/150e7eb7.md"]
        self.assertEqual(len(rows), 5)
        by_fp = {st.unquote(e.fields["fingerprint"]): e for e in rows}
        self.assertEqual(by_fp["yes switch under base but branch mac_mac"].fields.get("addressed"),
                         "switched; the branch is mac_mac", "fields after a blank line join their own row")
        self.assertEqual(by_fp["why that one?"].fields.get("addressed"), "explained the branch choice",
                         "a `- <message>` completion joins its row")
        self.assertEqual(r["labels"]["rows"], 6)
        self.assertEqual(r["labels"]["completed"], 5, "a row with addressed: and no state: stays open, as before")

    def test_store_lessons_agrees(self):
        sl = store_lessons()
        if sl is None:
            self.skipTest("store_lessons.py not found")
        r = self.run_dry()
        got = sl.lessons(self.old)["counts"]
        self.assertEqual(got, r["old"]["counts"])
        self.assertEqual(len(sl.live_rules(self.old)), len(r["old"]["live_rules"]))
        lab = sl.labels(self.old)
        for k in ("sessions", "rows", "completed", "open", "judged"):
            self.assertEqual(lab[k], r["old"]["labels"][k], k)

    def test_pools_and_dictionary(self):
        r = self.run_dry()
        p = r["pools"]
        self.assertEqual(p["labelled"], 0, "the a3ac5de6 pool is left out: a teacher audited that session")
        self.assertEqual(p["audits"], 1)
        r2 = migrate.run(self.old, os.path.join(self.tmp.name, "n2"), now=NOW)
        rows = r2["label_rows"]
        self.assertTrue(all(x[3] == "pool" for x in rows))
        self.assertTrue(any("reader=mister:roboto" in x[6] for x in rows))
        # without the audit, the pool is imported and each pick resolved or listed
        os.remove(os.path.join(self.old, "models", "labels", "a3ac5de6.tsv"))
        r3 = migrate.run(self.old, os.path.join(self.tmp.name, "n3"), now=NOW)
        p3 = r3["pools"]
        self.assertEqual(p3["labelled"], 1)
        self.assertEqual(p3["picks"], 4)
        self.assertEqual(len(p3["unresolved"]), 1)
        ids = [x[1] for x in r3["label_rows"]]
        self.assertTrue(any(i.startswith("rules.md:2026-11-01 11:18:") for i in ids))
        self.assertTrue(any(i.startswith("retractions.md:2026-10-25 09:00:") for i in ids))
        self.assertTrue(any(i.startswith("archive/") for i in ids), "a logger pick resolves into the archive")
        v = r3["vocab"]
        self.assertEqual(sum(v["signals"][k] for k in ("correction", "retraction", "missed", "repeat")), 6)
        vocab = st.parse(r3["texts"][st.VOCABULARY], st.VOCABULARY)
        self.assertTrue(vocab)
        for e in vocab:
            self.assertEqual(e.fields["means"], "(pending)")
            self.assertTrue(e.fields["because"].strip())
            self.assertRegex(e.fields["because"], r'you wrote ".+"')

    def test_pool_picks_resolve_as_pick_model_did(self):
        """The imported labels are the old ranker's labels: a pick of a freed ruling stays on that ruling (the old
        barrier listed it with its state), and a pick whose head is the reader's own words is unresolved, never
        guessed from its file and time (pick_model.build_pairs matched file, time and head prefix alone)."""
        os.remove(os.path.join(self.old, "models", "labels", "a3ac5de6.tsv"))
        pool = os.path.join(self.old, "sessions", "a3ac5de6", "vlds", "recall-pool.md")
        with open(pool, "a", encoding="utf-8") as f:
            f.write("- [local-storage.md 2026-10-20 09:00 LIVE] the old harness keeps its flag in the test runner; "
                    "bears: the harness\n"
                    "- [local-storage.md 2026-10-29 10:44 LIVE] tidy the home directory; bears: the move\n")
        r = migrate.run(self.old, os.path.join(self.tmp.name, "n4"), now=NOW)
        ids = [x[1] for x in r["label_rows"]]
        freed = [x for x in r["label_rows"] if x[1].startswith("rules.md:2026-10-20 09:00:")]
        self.assertEqual(len(freed), 1, ids)
        self.assertIn("picked while FREED", freed[0][6])
        self.assertFalse(any(i.startswith("rules.md:2026-10-29 10:44:") for i in ids),
                         "the one entry at that time is not taken for a head that does not match it")
        self.assertTrue(any("tidy the home directory" in u for u in r["pools"]["unresolved"]))
        self.assertEqual(r["pools"]["to_freed"], 1)

    def test_apply_out(self):
        r = migrate.run(self.old, self.out, apply=True, now=NOW)
        self.assertTrue(all(ok for _n, ok, _d in r["checks"]), [c for c in r["checks"] if not c[1]])
        for f in ("store/rules.md", "store/corrections.md", "store/retractions.md", "store/facts.md",
                  "store/vocabulary.md", "store/messages/150e7eb7.md", "store/messages/a3ac5de6.md",
                  "models/labels-raw.tsv", "models/tasks.tsv", "archive/index-rules.md",
                  "archive/models/pick-model.json", "archive/sessions/mac-setup--150e7eb7/vlds/logger.md",
                  "archive/ledger-events.md", "src/a3ac5de6-probe/probe.py", "memory/a.md", "scratchpad/notes.md",
                  "flights/20261102-0445-s1/plan.md", "flights/board.tsv"):
            self.assertTrue(os.path.exists(os.path.join(self.out, f)), f)
        self.assertFalse(os.path.exists(os.path.join(self.out, "archive", "models", "ranker-base.pt")))
        with open(os.path.join(self.out, "src/a3ac5de6-probe/probe.py"), encoding="utf-8") as f:
            self.assertEqual(f.read().split("\n")[:2], ["#!/usr/bin/env python3", "# probe the narwhal port"])
        with open(os.path.join(self.out, "archive", "migration-2026-11-01.md"), encoding="utf-8") as f:
            report = f.read()
        self.assertIn("pool-road: model", report, "the old ## recall section is copied into the report")
        rules = st.load_file(self.out, "rules.md")
        self.assertTrue(any(e.fields.get("source") == "index" for e in rules), "owner-rooted index rule")
        idx = st.build_index(self.out)
        self.assertGreater(idx["n"], 5)

    def test_apply_in_place(self):
        r = migrate.run(self.old, None, apply=True, now=NOW)
        self.assertEqual(r["plan"].unplaced, [])
        self.assertFalse(os.path.exists(os.path.join(self.old, "sessions")))
        self.assertFalse(os.path.exists(os.path.join(self.old, "vindex")))
        self.assertFalse(os.path.exists(os.path.join(self.old, "models", "pick-model.json")))
        self.assertTrue(os.path.exists(os.path.join(self.old, "store", "rules.md")))
        self.assertTrue(os.path.exists(os.path.join(self.old, "memory", "a.md")))
        self.assertTrue(os.path.exists(os.path.join(self.old, "flights", "20261102-0445-s1", "plan.md")),
                        "flights/ stays in place: p4-plans writes it, phi_store reads it")
        self.assertFalse(os.path.exists(os.path.join(self.old, "archive", "flights")))
        with self.assertRaises(SystemExit):
            migrate.run(self.old, None, apply=True, now=NOW)

    def test_cli(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "p4.py"), "migrate", "--p4", self.old, "--out",
                            self.out, "--now", NOW], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("migrate (dry)", r.stdout)
        self.assertIn("unplaced 0", r.stdout)


class RealRepos(unittest.TestCase):
    """The four clones, migrated dry into a temp dir; read only."""

    def check_repo(self, name):
        src = fixture(name)
        if not src:
            self.skipTest(f"the {name} clone is not on this machine")
        with tempfile.TemporaryDirectory() as d:
            r = migrate.run(src, os.path.join(d, "new"), apply=False, now=NOW)
            fails = [c for c in r["checks"] if not c[1]]
            self.assertEqual(fails, [])
            self.assertEqual(r["plan"].unplaced, [])
            sl = store_lessons()
            if sl:
                got = sl.lessons(src)["counts"]
                self.assertEqual(got["correction"], r["counts"]["correction"])
                self.assertEqual(got["retraction"], r["counts"]["retraction"])
                self.assertEqual(got["missed"], r["counts"]["missed"])
                self.assertEqual(got["repeat"], r["counts"]["repeat"])
                self.assertEqual(len(sl.live_rules(src)), len(r["live_new"]) + len(r["live_lost"]))
                lab = sl.labels(src)
                self.assertEqual(lab["rows"], r["labels"]["rows"] - sum(k - 1 for _w, k, kind in r["plan"].multi
                                                                         if kind == "row"))
                self.assertGreaterEqual(r["labels"]["completed"], lab["completed"])
                self.assertGreaterEqual(r["labels"]["judged"], lab["judged"])
            return r

    def test_audioplugin(self):
        r = self.check_repo("AudioPlugin-p4")
        self.assertEqual(r["counts"]["correction"], 86)
        self.assertEqual(r["pools"]["labelled"], 24)

    def test_ap_mac_finding17(self):
        r = self.check_repo("ap-p4_mac")
        self.assertEqual(len(r["finding17"]), 6)
        self.assertEqual([s for _i, _t, s in r["finding17"]], ["LIVE"] * 6)
        self.assertEqual(len(r["live_new"]), 9)

    def test_p4p4(self):
        self.check_repo("p4-p4")

    def test_phi(self):
        self.check_repo("phi-p4")

    def test_ap_mac_apply_byte_identical(self):
        src = fixture("ap-p4_mac")
        if not src:
            self.skipTest("the ap-p4_mac clone is not on this machine")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "new")
            r = migrate.run(src, out, apply=True, now=NOW)
            names = [n for n, _ok, _d in r["checks"]]
            self.assertIn("archives byte-identical", names)
            self.assertIn("memory/ tree identical", names)
            self.assertEqual([c for c in r["checks"] if not c[1]], [])
            self.assertFalse(os.path.exists(os.path.join(src, "store")), "the clone is never written")


if __name__ == "__main__":
    unittest.main(verbosity=1)
