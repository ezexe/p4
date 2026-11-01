#!/usr/bin/env python3
"""Tests for `p4.py query` and `p4.py index` (fresh-marketplace.md 4.4, 4.5, 8.1's query bullets).

Run: python3 test_query.py

On a small fixture: deterministic output; 0 lines for "hi" and for a message sharing no rare term; at most 5
lines, 2 per file, 160 characters of text; the line shape; no jargon-list word printed; the history line for a
token seen twice and none for once; the repeat line for a resembling completed row and none for an open one;
dictionary expansion; the trained-ranker road. On AudioPlugin-p4 (when the clone is present): under 300 ms.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402
from test_store import NOW, fixture, make_store, write  # noqa: E402

LINE_RE = re.compile(r"^- (\d{4}-\d\d-\d\d|undated) (rule|correction|missed detail|retracted|fact|memory|"
                     r"earlier message|your word|saved code): (.+) \(((?:store|memory|src)/[^:]+):(\d+)\)$")
SCRIPT = os.path.join(HERE, "p4.py")


def q(p4, text, session=None):
    return cli.query(p4, text, session, NOW)


def run_cli(*args):
    return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = make_store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class Silence(Fixture):
    def test_hi(self):
        self.assertEqual(q(self.p4, "hi")["lines"], [])

    def test_no_rare_term(self):
        self.assertEqual(q(self.p4, "can you explain how python decorators work in general")["lines"], [])
        self.assertEqual(q(self.p4, "what is the weather like today")["lines"], [])

    def test_one_rare_term_is_not_enough_without_a_ranker(self):
        self.assertEqual(q(self.p4, "tell me about the zebrafish")["lines"], [])

    def test_empty(self):
        self.assertEqual(q(self.p4, "   ")["lines"], [])


class Shape(Fixture):
    def test_lines_shape_caps_and_determinism(self):
        text = "does the quokka harness run the zebrafish plotter golden images on every push?"
        a = q(self.p4, text)
        self.assertTrue(a["lines"], a)
        self.assertLessEqual(len(a["lines"]), 5)
        per = {}
        for line in a["lines"]:
            m = LINE_RE.match(line)
            self.assertTrue(m, line)
            self.assertLessEqual(len(m.group(3)), 160)
            per[m.group(4)] = per.get(m.group(4), 0) + 1
        self.assertLessEqual(max(per.values()), 2, "at most 2 lines from one file")
        st.build_index(self.p4)
        self.assertEqual(q(self.p4, text)["lines"], a["lines"], "deterministic across a rebuild")
        self.assertEqual(run_cli("query", "--p4", self.p4, "--text", text, "--now", NOW).stdout.strip().split("\n"),
                         a["lines"])

    def test_plain_printed_and_jargon_dropped(self):
        a = q(self.p4, "the zebrafish golden images")
        self.assertIn("checks its golden images", "\n".join(a["lines"]), "the entry's plain: is what prints")
        b = q(self.p4, "the sweeper keychain flag")
        self.assertNotRegex("\n".join(a["lines"] + b["lines"]), st.JARGON, "no jargon-list word in a printed line")
        self.assertGreaterEqual(b["jargon_dropped"], 1, "the tombstone ruling is held back, and counted")

    def test_line_text_cut_at_160(self):
        long_rule = [("ruling", "the pangolin relay " + "keeps every lane open " * 20), ("time", "2026-10-01 00:00")]
        path = os.path.join(self.p4, "store", "rules.md")
        ents = [e.pairs for e in st.load_file(self.p4, "rules.md")]
        write(path, st.render("rules.md", ents + [long_rule]))
        a = q(self.p4, "pangolin relay lane")
        self.assertTrue(a["lines"])
        m = LINE_RE.match(a["lines"][0])
        self.assertEqual(len(m.group(3)), 160)
        self.assertTrue(m.group(3).endswith("…"))


class ShortTurns(Fixture):
    def test_history_line_seen_twice(self):
        a = q(self.p4, "Keep going")
        self.assertEqual(len(a["lines"]), 1, a)
        self.assertRegex(a["lines"][0], r'^- you have said "Keep going" 2 times; last time \(2026-10-02\) it was taken '
                                        r'as: continued the running CEF build')

    def test_no_history_line_seen_once(self):
        self.assertEqual(q(self.p4, "ship it")["lines"], [])

    def test_readings_that_differ(self):
        rows = [[("fingerprint", '"go"'), ("time", f"2026-10-0{k} 10:00"), ("state", "FRESH"),
                 ("addressed", "built it" if k != 3 else "pushed it")] for k in range(1, 5)]
        write(os.path.join(self.p4, "store", "messages", "cccc3333.md"), st.render("messages/cccc3333.md", rows))
        line = q(self.p4, "go")["lines"][0]
        self.assertIn("built it (×3), pushed it (×1)", line)

    def test_repeat_line_for_a_completed_row(self):
        a = q(self.p4, "rebuild the wombat installer with the signing step again", session="aaaa1111-0000")
        self.assertTrue(any(l.startswith("- an earlier message like this one (2026-10-01 10:10) was answered: rebuilt")
                            for l in a["lines"]), a)

    def test_no_repeat_line_for_an_open_row(self):
        a = q(self.p4, "measure the axolotl latency on the second rig", session="aaaa1111")
        self.assertFalse(any("earlier message like this one" in l for l in a["lines"]), a)

    def test_no_repeat_line_from_another_session(self):
        a = q(self.p4, "rebuild the wombat installer with the signing step again", session="bbbb2222")
        self.assertFalse(any("earlier message like this one" in l for l in a["lines"]), a)


class Dictionary(Fixture):
    def test_term_expands_to_its_meaning(self):
        a = q(self.p4, "rename it to the mac branch thing")
        self.assertTrue(any("0.0.1-apple&win&mac_mac" in l for l in a["lines"]), a)

    def test_pending_entry_does_not_expand(self):
        idx = st.build_index(self.p4)
        hits = cli.dictionary_hits(idx, "frobnicate the narwhal", ["frobnicate", "narwhal"])
        self.assertEqual(hits, [])


class RankerRoad(Fixture):
    def test_trained_ranker_is_used(self):
        idx = st.build_index(self.p4)
        terms = ranker.tokens("quokka harness zebrafish plotter")
        cands = [{"file": d["file"], "kind": d["kind"], "state": d["state"], "time": d["time"],
                  "toks": d["toks"].split(), "head": d["head"].split(), "dl": d["dl"]} for d in idx["docs"]]
        idf = {t: ranker.idf_of(len(st.postings(idx, t)) // 2, idx["n"]) for t in terms if t in idx["post"]}
        xs, _s, _t = ranker.candidate_features(terms, cands, idf, idx["avgdl"], NOW)
        ys = [1 if "quokka" in d["toks"] else 0 for d in idx["docs"]]
        w = ranker.fit(list(zip(xs, ys)))
        ranker.save(os.path.join(self.p4, "models", "ranker.json"), w, 0.5, trained=NOW)
        a = q(self.p4, "does the quokka harness run the zebrafish plotter")
        self.assertIn("ranker", a["road"])
        self.assertTrue(a["lines"])
        self.assertLessEqual(len(a["lines"]), 5)

    def test_old_ranker_json_is_ignored(self):
        write(os.path.join(self.p4, "models", "ranker.json"), json.dumps({"kind": "phi_serve", "port": 1}))
        self.assertNotIn("ranker", q(self.p4, "does the quokka harness run the zebrafish plotter")["road"])


class Cli(Fixture):
    def test_index_rebuilds_only_when_newer(self):
        self.assertIn("rebuilt", run_cli("index", "--p4", self.p4).stdout)
        self.assertIn("fresh", run_cli("index", "--p4", self.p4).stdout)

    def test_stubs(self):
        for name in ("row", "serve-log", "usage", "signals", "labels", "train", "eval", "dictionary", "teacher"):
            r = run_cli(name)
            self.assertEqual(r.returncode, 2, name)
            self.assertIn("not built yet", r.stderr)

    def test_check(self):
        r = run_cli("check", "--p4", self.p4)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("jargon rate", r.stdout)

    def test_project_dir_resolution(self):
        r = subprocess.run([sys.executable, SCRIPT, "query", "--text", "Keep going"], capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": self.tmp.name})
        self.assertIn("you have said", r.stdout)


@unittest.skipUnless(fixture("AudioPlugin-p4"), "the AudioPlugin-p4 clone is not on this machine")
class RealAudioPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import migrate
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p4 = os.path.join(cls.tmp.name, "p4")
        migrate.run(fixture("AudioPlugin-p4"), cls.p4, apply=True, now=NOW,
                    report_path=os.path.join(cls.tmp.name, "report.md"))
        st.build_index(cls.p4)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_latency_under_300ms(self):
        text = "the CEF build keeps failing on the proprietary codecs patch, how do I rebuild incrementally?"
        times = []
        for _ in range(3):
            t = time.perf_counter()
            r = run_cli("query", "--p4", self.p4, "--text", text, "--now", NOW)
            times.append(time.perf_counter() - t)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(min(times), 0.300, f"query took {min(times) * 1000:.0f} ms")

    def test_hi_and_ordinary(self):
        self.assertEqual(run_cli("query", "--p4", self.p4, "--text", "hi").stdout, "")
        self.assertEqual(run_cli("query", "--p4", self.p4, "--text", "what is the weather like today").stdout, "")

    def test_deterministic_and_bounded(self):
        for text in ("the CEF build keeps failing on the proprietary codecs patch", "push it",
                     "move the ring writer comment lines and the playhead inject mapping into the plan"):
            a = cli.query(self.p4, text, None, NOW)
            b = cli.query(self.p4, text, None, NOW)
            self.assertEqual(a["lines"], b["lines"])
            self.assertLessEqual(len(a["lines"]), 5)
            for line in a["lines"]:
                self.assertNotRegex(line, st.JARGON)
                m = LINE_RE.match(line)
                if m:
                    self.assertLessEqual(len(m.group(3)), 160)
                else:
                    self.assertTrue(line.startswith(("- you have said", "- an earlier message like this one")), line)


if __name__ == "__main__":
    unittest.main(verbosity=1)
