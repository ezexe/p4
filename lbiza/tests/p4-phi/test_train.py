#!/usr/bin/env python3
"""Tests for train.py: a round's promotion against its floors, `owed`, a round that writes nothing, the held
documents among a pool task's candidates, the BM25 baseline's count of undrawn positives, a round's precision
measured on the picks the query serves, and the dictionary check.

Run: python -m pytest tests/p4-phi/test_train.py

The tests need only the standard library's unittest and no network, and take a few seconds. The reproduction on
the AudioPlugin-p4 store, whose imported pools must reach FIRST_FLOOR held out, measures one store for about a minute
and a half, so it lives in the experiments repository ezexe/p4-phi, at experiments/p4-suite/test_train.py.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402
import train  # noqa: E402
from test_store import NOW, make_store, write  # noqa: E402

TOPICS = ("axolotl", "bandicoot", "capybara", "dugong", "echidna", "fossa", "gharial", "hoatzin")


def synthetic(root, n_tasks=12, noisy=False):
    """A store whose corpus holds rules naming two topic words and a few naming one, with pool tasks that name two
    topics and whose positives are the rules naming both: learnable, so a round passes its floors. `noisy` labels
    about a quarter of the rules naming neither topic instead."""
    p4 = os.path.join(root, ".claude", "p4")
    rules = []
    for i, a in enumerate(TOPICS):
        for j, b in enumerate(TOPICS):
            if i < j:
                rules.append([("ruling", f"the {a} relay keeps the {b} gauge in step"), ("status", "LIVE"),
                              ("time", f"2026-10-{1 + (i + j) % 20:02d} 09:00")])
                rules.append([("ruling", f"the {a} board alone runs at night"), ("status", "LIVE"),
                              ("time", f"2026-10-{1 + (i + j) % 20:02d} 10:00")]) if j == i + 1 else None
    write(p4conf.sub(p4, "store", "rules.md"), st.render("rules.md", rules))
    for f in ("corrections.md", "retractions.md", "facts.md"):
        write(p4conf.sub(p4, "store", f), st.render(f, []))
    idx = st.build_index(p4)
    tasks, labs = [], []
    k = 0
    for i, a in enumerate(TOPICS):
        for b in TOPICS[i + 1:]:
            if k >= n_tasks:
                break
            tid = f"pool:t{k:02d}"
            tasks.append({"id": tid, "session": f"s{k:07d}", "time": "2026-10-30 12:00",
                          "text": f"how do the {a} relay and the {b} gauge stay in step", "kind": "first"})
            for n, d in enumerate(idx["docs"]):
                hit = f" {a} " in f" {d['show']} " and f" {b} " in f" {d['show']} "
                if (hit and not noisy) or (noisy and f" {a} " not in f" {d['show']} "
                                           and f" {b} " not in f" {d['show']} " and (n + k) % 4 == 0):
                    labs.append({"task": tid, "entry": d["id"], "label": "1", "source": "pool", "weight": "0.7",
                                 "time": "2026-10-30 12:00"})
            k += 1
    lb.add_tasks(p4, tasks)
    lb.write_tsv(lb.mpath(p4, lb.RAW), lb.RAW_HEAD, labs)
    return p4


class Rounds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = synthetic(self.tmp.name)
        self._floor = train.FIRST_FLOOR

    def tearDown(self):
        train.FIRST_FLOOR = self._floor
        self.tmp.cleanup()

    def test_round_promoted_and_recorded(self):
        row = train.run_round(self.p4, now=NOW)
        self.assertEqual(row["promoted"], "promoted", row["why"])
        self.assertGreaterEqual(float(row["r_precision"]), 0.9)
        m = ranker.load(p4conf.sub(self.p4, "models", "ranker.json"))
        self.assertIsNotNone(m)
        self.assertGreaterEqual(m["floor"]["precision"], 0.6)
        rows = train.eval_rows(self.p4)
        self.assertEqual(len(rows), 1)
        self.assertIn("pool:", rows[0]["per_source"])
        self.assertIn("/", rows[0]["short"], "the short-turn subset is reported")

    def test_round_below_the_floor_is_not_promoted(self):
        train.run_round(self.p4, now=NOW)
        path = p4conf.sub(self.p4, "models", "ranker.json")
        before = open(path, encoding="utf-8").read()
        noisy = synthetic(os.path.join(self.tmp.name, "n"), noisy=True)
        shutil.copyfile(p4conf.sub(noisy, "models", "labels-raw.tsv"),
                        p4conf.sub(self.p4, "models", "labels-raw.tsv"))
        row = train.run_round(self.p4, now=NOW)
        self.assertEqual(row["promoted"], "kept old")
        self.assertIn("below the floor", row["why"])
        self.assertEqual(open(path, encoding="utf-8").read(), before, "the promoted model stays")
        self.assertEqual(train.eval_rows(self.p4)[-1]["promoted"], "kept old")

    def test_first_round_needs_the_pool_floor(self):
        train.FIRST_FLOOR = 1.01
        row = train.run_round(self.p4, now=NOW)
        self.assertEqual(row["promoted"], "kept old")
        self.assertIn("first round: pool labels alone", row["why"])
        self.assertFalse(os.path.exists(p4conf.sub(self.p4, "models", "ranker.json")))

    def test_a_first_round_whose_pool_tasks_cannot_be_measured_is_kept_old(self):
        """Before any promoted round, twelve tasks labelled by pools alone, of which only two have a positive among
        their candidates, cannot be measured against FIRST_FLOOR: the round is kept old and says so."""
        tasks = sorted(lb.read_tasks(self.p4).values(), key=lambda t: t["id"])
        lb.write_tsv(lb.mpath(self.p4, lb.TASKS), lb.TASK_HEAD,
                     [{**t, "time": t["time"] if k < 2 else "2026-09-01 12:00"} for k, t in enumerate(tasks)])
        idx = st.build_index(self.p4)
        rule = {d["show"]: d["id"] for d in idx["docs"]}
        more, labs = [], []
        for k, (a, b) in enumerate((("axolotl", "bandicoot"), ("capybara", "dugong"), ("echidna", "fossa"))):
            more.append({"id": f"u{k}", "session": f"u{k:07d}", "time": "2026-10-30 12:00",
                         "text": f"does the {a} relay keep the {b} gauge in step", "kind": "first"})
            labs.append({"task": f"u{k}", "entry": rule[f"the {a} relay keeps the {b} gauge in step"], "label": "1",
                         "source": "usage", "weight": "1.0", "time": "2026-10-30 12:00"})
        lb.add_tasks(self.p4, more)
        lb.append_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD, labs)
        row = train.run_round(self.p4, now=NOW, dictionary=False)
        self.assertEqual(row["promoted"], "kept old")
        self.assertIn("first round: pool labels alone", row["why"])
        self.assertFalse(os.path.exists(p4conf.sub(self.p4, "models", "ranker.json")))

    def test_eval_writes_nothing(self):
        before = sorted(os.listdir(p4conf.sub(self.p4, "models")))
        row = train.run_round(self.p4, write=False, now=NOW)
        self.assertTrue(row["eval"])
        self.assertEqual(sorted(os.listdir(p4conf.sub(self.p4, "models"))), before)

    def test_owed_counts_from_this_machines_last_round(self):
        """ezexe/p4#183: a synced eval.tsv holds every machine's rounds, so `owed` counts the labels since this
        machine's own last round, by the `machine` column, and never from another machine's row."""
        train.run_round(self.p4, now=NOW)
        conf = p4conf.load(self.p4)
        conf["recall"]["train"].update({"owed_labels": 3, "owed_age_s": 0})
        p4conf._write(self.p4, conf)
        path = p4conf.sub(self.p4, "models", "eval.tsv")
        mine = train.eval_rows(self.p4)[-1]
        other = dict(mine, round="1", labels=str(int(mine["labels"]) + 100), machine="another-machine")
        cols = [c for c in train.EVAL_HEAD.rstrip("\n").split("\t") if c != "machine"] + ["machine"]
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\t".join(other.get(c, "") for c in cols) + "\n")
        lb.append_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD,
                      [{"task": "pool:t00", "entry": f"x{k}", "label": "0", "source": "usage", "weight": "0.3"}
                       for k in range(5)])
        ok, why = train.owed(self.p4)
        self.assertTrue(ok, why)
        self.assertEqual(train.eval_rows(self.p4)[0]["machine"], train.machine(self.p4))

    def test_if_owed(self):
        ok, why = train.owed(self.p4)
        self.assertTrue(ok, why)
        train.run_round(self.p4, now=NOW)
        ok, why = train.owed(self.p4)
        self.assertFalse(ok)
        self.assertIn("labels since the last round", why)
        lb.append_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD,
                      [{"task": "pool:t00", "entry": f"x{k}", "label": "0", "source": "usage", "weight": "0.3"}
                       for k in range(10)])
        ok, why = train.owed(self.p4)
        self.assertFalse(ok, "ten labels, but the last round is under an hour old")
        self.assertIn("s old", why)
        old = time.time() - 7200
        os.utime(p4conf.sub(self.p4, "models", "eval.tsv"), (old, old))
        self.assertTrue(train.owed(self.p4)[0])

    def test_if_owed_reads_the_store_settings(self):
        """`p4.py train --if-owed` runs in a new process, as the Stop hook's call does: p4.json's
        `recall.train.owed_labels` and `owed_age_s` decide whether a round is owed, not the module's defaults."""
        train.run_round(self.p4, now=NOW)
        conf = p4conf.load(self.p4)
        conf["recall"]["train"].update({"owed_labels": 3, "owed_age_s": 0})
        p4conf._write(self.p4, conf)
        lb.append_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD,
                      [{"task": "pool:t00", "entry": f"x{k}", "label": "0", "source": "usage", "weight": "0.3"}
                       for k in range(5)])
        r = subprocess.run([sys.executable, "-I", os.path.join(SRC, "p4.py"), "train", "--if-owed", "--p4", self.p4,
                            "--now", NOW], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("train: round 1 ", r.stdout, "five new labels reach the store's three, and it waits no time")

    def test_pool_candidates_keep_held_entries(self):
        """A pool label can name an entry picked while it was FREED or SPENT, and migrate.import_pools keeps the label
        on that entry: its document is among the pool task's candidates, though the index never holds it."""
        path = p4conf.sub(self.p4, "store", "rules.md")
        rules = [list(e.pairs) for e in st.load_file(self.p4, "rules.md")]
        rules.append([("ruling", "the axolotl relay once kept the bandicoot gauge by hand"), ("status", "FREED"),
                      ("time", "2026-10-02 09:00")])
        write(path, st.render("rules.md", rules))
        idx = st.build_index(self.p4)
        held = next(e for e in st.load_store(self.p4)["rules.md"] if e.state == "FREED")
        self.assertNotIn(held.id, {d["id"] for d in idx["docs"]}, "never indexed, so never recalled")
        lb.append_tsv(lb.mpath(self.p4, lb.RAW), lb.RAW_HEAD,
                      [{"task": "pool:t00", "entry": held.id, "label": "1", "source": "pool", "weight": "0.7",
                        "time": "2026-10-30 12:00", "note": "picked while FREED"}])
        sets = {s["task"]: s for s in train.build_sets(self.p4, idx=idx, sources={"pool"})}
        s = sets["pool:t00"]
        self.assertIn(held.id, s["cand_ids"])
        self.assertEqual(s["ys"][s["cand_ids"].index(held.id)], 1)
        self.assertEqual(sum(s["ys"]), s["n_pos"], "every positive drawn")
        self.assertNotIn(held.id, {d["id"] for d in idx["docs"]}, "the caller's index is unchanged")


class BaselineScaling(unittest.TestCase):
    def test_baseline_counts_undrawn_positives_like_the_ranker(self):
        # each task: 4 candidates, its one drawn positive is BM25's top, and it has 2 labelled positives
        sets = []
        for k in range(4):
            xs = [{ranker.h("bias"): 1.0, ranker.h("bm25"): v} for v in (1.0, 0.5, 0.3, 0.1)]
            sets.append({"task": f"t{k}", "xs": xs, "ys": [1, 0, 0, 0], "w": [1.0] * 4, "files": ["a", "b", "c", "d"],
                         "bm25": [4.0, 2.0, 1.0, 0.5], "n_pos": 2, "source": "repo", "missed": False, "time": str(k)})
        ev = train.evaluate(sets)
        self.assertAlmostEqual(ev["baseline"], 0.5, msg="BM25 found 1 of the 2 labelled positives")
        self.assertLessEqual(ev["r-precision"], 0.5, msg="the ranker is held to the same denominator")


class PerFile(unittest.TestCase):
    """A round measures the picks the query serves: at most p4.json's `recall.query.per_file` documents of one file."""

    @staticmethod
    def sets():
        # each task: three like documents of one file, the first two right and the third wrong, and an unlike one of
        # another file; the query picks at most two documents of a file, so it serves the right two alone
        like = {ranker.h("bias"): 1.0, ranker.h("like"): 1.0}
        unlike = {ranker.h("bias"): 1.0, ranker.h("unlike"): 1.0}
        return [{"task": f"t{k}", "xs": [dict(like), dict(like), dict(like), dict(unlike)], "ys": [1, 1, 0, 0],
                 "w": [1.0] * 4, "files": ["a.md", "a.md", "a.md", "b.md"], "bm25": [3.0, 2.0, 1.0, 0.5], "n_pos": 2,
                 "source": "repo", "sources": ["repo"], "missed": False, "time": str(k)} for k in range(6)]

    def setUp(self):
        self._kept = {k: getattr(train, k) for k in ("MIN_PRECISION", "build_sets")}
        self._per_file = getattr(train, "PER_FILE", None)

    def tearDown(self):
        for k, v in self._kept.items():
            setattr(train, k, v)
        if self._per_file is not None:
            train.PER_FILE = self._per_file

    def test_the_precision_is_that_of_the_served_picks(self):
        self.assertAlmostEqual(train.evaluate(self.sets())["precision"], 1.0)
        self.assertAlmostEqual(train.evaluate(self.sets(), per_file=3)["precision"], 2 / 3, places=3,
                               msg="the fixture tells the two caps apart")

    def test_a_round_is_not_held_by_a_pick_the_query_never_serves(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p4 = synthetic(tmp.name)
        conf = p4conf.load(p4)
        conf["recall"]["train"]["min_precision"] = 0.9
        p4conf._write(p4, conf)
        train.build_sets = lambda *a, **k: self.sets()
        row = train.run_round(p4, now=NOW, dictionary=False)
        self.assertEqual(row["promoted"], "promoted", row["why"])
        self.assertEqual(row["precision"], "1.0000")
        self.assertEqual(ranker.load(p4conf.sub(p4, "models", "ranker.json"))["per_file"], 2)
        conf["recall"]["query"]["per_file"] = 3
        p4conf._write(p4, conf)
        row = train.run_round(p4, now=NOW, dictionary=False)
        self.assertEqual(row["precision"], "0.6667", "a store that serves three of a file is measured at three")
        self.assertIn("below 0.9", row["why"])


class HeadFeature(unittest.TestCase):
    def test_training_and_the_query_read_one_head(self):
        """A corpus entry's `head-bm25` in a training set is the one the query hands the ranker for the same text,
        here for an entry whose words come after its first 140 characters."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p4 = os.path.join(tmp.name, ".claude", "p4")
        filler = "the bench clock and the board counters are kept in step by one scheduler thread, "
        rules = [[("ruling", filler * 2 + "and the axolotl relay wakes the bandicoot gauge"), ("status", "LIVE"),
                  ("time", "2026-10-01 09:00")],
                 [("ruling", "the axolotl relay wakes at dawn"), ("status", "LIVE"), ("time", "2026-10-02 09:00")],
                 [("ruling", "the bandicoot gauge reads low after a restart"), ("status", "LIVE"),
                  ("time", "2026-10-03 09:00")]]
        write(p4conf.sub(p4, "store", "rules.md"), st.render("rules.md", rules))
        for f in ("corrections.md", "retractions.md", "facts.md"):
            write(p4conf.sub(p4, "store", f), st.render(f, []))
        idx = st.build_index(p4)
        far = next(d for d in idx["docs"] if "scheduler" in d["show"])
        text = "why the axolotl relay wakes the bandicoot gauge so early"
        lb.add_tasks(p4, [{"id": "u0", "session": "s0000000", "time": "2026-10-30 12:00", "text": text,
                           "kind": "first"}])
        lb.write_tsv(lb.mpath(p4, lb.TRAIN), lb.TRAIN_HEAD, [
            {"task": "u0", "entry": far["id"], "label": "1", "source": "usage", "weight": "1.0",
             "time": "2026-10-30 12:00", "teacher": "", "edited": "", "note": ""}])
        s = next(s for s in train.build_sets(p4, idx, sources={"usage"}) if s["task"] == "u0")
        trained = {i: x[ranker.h("head-bm25")] for i, x in zip(s["cand_ids"], s["xs"])}
        import p4 as cli
        seen = []
        real = ranker.candidate_features

        def spy(terms, cds, *a, **kw):
            out = real(terms, cds, *a, **kw)
            seen.append((cds, out[0]))
            return out
        ranker.candidate_features = spy
        self.addCleanup(setattr, ranker, "candidate_features", real)
        cli.query(p4, text, idx=idx, now="2026-10-30 12:00",
                  model={"w": {ranker.h("bias"): 1.0}, "threshold": 0.99, "features": ["base"], "per_file": 2})
        cds, xs = seen[-1]
        id_of = {d["toks"]: d["id"] for d in idx["docs"]}
        served = {id_of[" ".join(c["toks"])]: x[ranker.h("head-bm25")] for c, x in zip(cds, xs)}
        self.assertEqual(set(served), set(trained), "the same three candidates")
        for i in served:
            self.assertAlmostEqual(served[i], trained[i], msg=i)


class DictionaryCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = make_store(self.tmp.name)
        self.path = p4conf.sub(self.p4, "store", "vocabulary.md")
        rules = st.load_file(self.p4, "rules.md")
        zebra = next(e for e in rules if e.value.startswith("the zebrafish plotter uses"))
        mac = next(e for e in rules if e.value.startswith("the Mac's branch"))
        vocab = [
            st.vocab_entry_pairs("the mac branch thing", "the branch 0.0.1-apple&win&mac_mac, cut under "
                                 "0.0.1-apple&win&mac", '2026-11-01 11:18 — you wrote "rename it to the mac branch '
                                 'thing"', "correction", [mac.id], "2026-11-01 13:30"),
            # expands every message naming the wombat into the zebrafish rules: fixes its own message, but changes
            # the top 5 of the working message "rebuild the wombat installer with the signing step"
            st.vocab_entry_pairs("wombat", "the zebrafish plotter quokka harness golden images",
                                 '2026-10-02 — you wrote "fix the wombat"', "correction", [zebra.id],
                                 "2026-11-01 13:30"),
            st.vocab_entry_pairs("narwhal", "the deployment target", '2026-10-03 — you wrote "move the narwhal"',
                                 "correction", [mac.id], "2026-11-01 13:30"),
            st.vocab_entry_pairs("capybara", "nothing the store holds", '2026-10-04 — you wrote "the capybara"',
                                 "owner", [mac.id], "2026-10-05 09:00"),
        ]
        write(self.path, st.render(st.VOCABULARY, vocab))
        st.build_index(self.p4)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_tests(self):
        owner_before = self.owner_block()
        res = train.dictionary_check(self.p4)
        by = {r["term"]: r for r in res["entries"]}
        self.assertTrue(by["the mac branch thing"]["fixed"])
        self.assertFalse(by["the mac branch thing"]["harmed"])
        self.assertEqual(by["the mac branch thing"]["status_after"], "on")
        self.assertTrue(by["wombat"]["fixed"])
        self.assertTrue(by["wombat"]["harmed"], by["wombat"])
        self.assertEqual(by["wombat"]["status_after"], "off")
        self.assertFalse(by["narwhal"]["fixed"])
        self.assertEqual(by["narwhal"]["status_after"], "off")
        self.assertTrue(by["capybara"]["owner"])
        vocab = {v["term"]: v for v in st.read_vocabulary(self.p4)}
        self.assertEqual(vocab["wombat"]["status"], "off")
        self.assertEqual(vocab["narwhal"]["status"], "off")
        self.assertEqual(vocab["the mac branch thing"]["status"], "on")
        self.assertEqual(vocab["capybara"]["status"], "on", "ezexe's entry is listed, never turned off")
        self.assertEqual(self.owner_block(), owner_before, "ezexe's entry is byte-identical after a round")
        self.assertEqual(res["counts"]["off"], 2)

    def owner_block(self):
        text = st.read_text(self.path)
        return text[text.index("- term: capybara"):]


if __name__ == "__main__":
    unittest.main(verbosity=1)
