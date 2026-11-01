#!/usr/bin/env python3
"""Tests for train.py: rounds, the floor of 5.6, `train --if-owed`, `eval` writing nothing, and `dictionary check`
(fresh-marketplace.md 5.3, 5.5, 5.6, 8.1's train/eval and dictionary bullets).

Run: python3 test_train.py   (stdlib unittest, offline, a few seconds)

The AudioPlugin-p4 reproduction (imported pools >= 0.36 R-precision held out) takes about a minute and a half, so
it runs only with P4_SLOW=1 and when the colab clone is present: it migrates the clone into a temp directory first.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402
import train  # noqa: E402
from test_store import NOW, fixture, make_store, write  # noqa: E402

TOPICS = ("axolotl", "bandicoot", "capybara", "dugong", "echidna", "fossa", "gharial", "hoatzin")


def synthetic(root, n_tasks=12, noisy=False):
    """A store of rules, each naming two topic words, and pool tasks naming two topics whose positives are the rules
    naming both: learnable, so a round passes its floors; `noisy` labels the rules naming neither instead."""
    p4 = os.path.join(root, ".claude", "p4")
    rules = []
    for i, a in enumerate(TOPICS):
        for j, b in enumerate(TOPICS):
            if i < j:
                rules.append([("ruling", f"the {a} relay keeps the {b} gauge in step"), ("status", "LIVE"),
                              ("time", f"2026-10-{1 + (i + j) % 20:02d} 09:00")])
                rules.append([("ruling", f"the {a} board alone runs at night"), ("status", "LIVE"),
                              ("time", f"2026-10-{1 + (i + j) % 20:02d} 10:00")]) if j == i + 1 else None
    write(os.path.join(p4, "store", "rules.md"), st.render("rules.md", rules))
    for f in ("corrections.md", "retractions.md", "facts.md"):
        write(os.path.join(p4, "store", f), st.render(f, []))
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
        m = ranker.load(os.path.join(self.p4, "models", "ranker.json"))
        self.assertIsNotNone(m)
        self.assertGreaterEqual(m["floor"]["precision"], 0.6)
        rows = train.eval_rows(self.p4)
        self.assertEqual(len(rows), 1)
        self.assertIn("pool:", rows[0]["per_source"])
        self.assertIn("/", rows[0]["short"], "the short-turn subset is reported")

    def test_round_below_the_floor_is_not_promoted(self):
        train.run_round(self.p4, now=NOW)
        path = os.path.join(self.p4, "models", "ranker.json")
        before = open(path, encoding="utf-8").read()
        noisy = synthetic(os.path.join(self.tmp.name, "n"), noisy=True)
        shutil.copyfile(os.path.join(noisy, "models", "labels-raw.tsv"),
                        os.path.join(self.p4, "models", "labels-raw.tsv"))
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
        self.assertFalse(os.path.exists(os.path.join(self.p4, "models", "ranker.json")))

    def test_eval_writes_nothing(self):
        before = sorted(os.listdir(os.path.join(self.p4, "models")))
        row = train.run_round(self.p4, write=False, now=NOW)
        self.assertTrue(row["eval"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.p4, "models"))), before)

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
        os.utime(os.path.join(self.p4, "models", "eval.tsv"), (old, old))
        self.assertTrue(train.owed(self.p4)[0])

    def test_weights_by_source(self):
        self.assertEqual(train.SOURCE_WEIGHT["store+edited"], 1.0)
        self.assertEqual(train.SOURCE_WEIGHT["pool"], 0.7)
        self.assertEqual(train.SOURCE_WEIGHT["usage"], 0.3)
        self.assertEqual(train.SOURCE_WEIGHT["short"], 1.0)
        self.assertEqual(train.SOURCE_WEIGHT["miss"], 1.0)


class DictionaryCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = make_store(self.tmp.name)
        self.path = os.path.join(self.p4, "store", "vocabulary.md")
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
        self.assertEqual(vocab["capybara"]["status"], "on", "an owner's entry is listed, never turned off")
        self.assertEqual(self.owner_block(), owner_before, "the owner's entry is byte-identical after a round")
        self.assertEqual(res["counts"]["off"], 2)

    def owner_block(self):
        text = st.read_text(self.path)
        return text[text.index("- term: capybara"):]


class AudioPluginFloor(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("P4_SLOW") == "1" and fixture("AudioPlugin-p4"),
                         "slow: P4_SLOW=1 and the AudioPlugin-p4 clone")
    def test_imported_pools_reproduce_the_floor(self):
        import migrate
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "p4")
            migrate.run(fixture("AudioPlugin-p4"), out=out, apply=True, now=NOW)
            st.build_index(out)
            ev = train.evaluate(train.build_sets(out, sources={"pool"}))
            print(f"\nAudioPlugin-p4 imported pools: {train.fmt(ev)}")
            self.assertEqual(ev["n"], 24)
            self.assertGreater(ev["r-precision"], ev["baseline"], "above word overlap")
            self.assertGreaterEqual(ev["r-precision"], train.FIRST_FLOOR)


if __name__ == "__main__":
    unittest.main(verbosity=1)
