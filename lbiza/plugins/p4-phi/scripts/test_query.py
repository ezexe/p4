#!/usr/bin/env python3
"""Tests for `p4.py query`, `p4.py index` and `p4.py check`.

Run: python3 test_query.py

On a small fixture store: the same lines for the same message; no line for "hi", for an ordinary message or for one
that shares a single word with the documents; at most MAX_LINES lines, PER_FILE of them from one file, each with at
most TEXT_CHARS characters of text; the line's shape; no jargon-list word printed; the history line for a short
message sent twice before and none for one sent once; the repeat line for a resembling completed row and none for an
open row or another session's; dictionary expansion; the trained ranker's road. repo.build, which
`p4.py index --repo` runs, on a small git repository and on this checkout. On a store migrated from the
AudioPlugin-p4 fixture, when it is on this machine: how long one `p4.py query` process takes, silence for ordinary
messages and the same bounds. On a copy of the store P4_MAC_STORE names, when it is there: the no-ranker road's
regression cases.
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
import p4conf  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402
from test_store import NOW, fixture, make_store, write  # noqa: E402

LINE_RE = re.compile(r"^- (\d{4}-\d\d-\d\d|undated) (rule|correction|missed detail|retracted|fact|memory|"
                     r"earlier message|saved code): (.+) \(((?:phi/store|temportal/memory|temportal/src)/[^:]+):(\d+)\)$")
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
        path = p4conf.sub(self.p4, "store", "rules.md")
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
        write(p4conf.sub(self.p4, "store", "messages", "cccc3333.md"), st.render("messages/cccc3333.md", rows))
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
        ranker.save(p4conf.sub(self.p4, "models", "ranker.json"), w, 0.5, trained=NOW)
        a = q(self.p4, "does the quokka harness run the zebrafish plotter")
        self.assertIn("ranker", a["road"])
        self.assertTrue(a["lines"])
        self.assertLessEqual(len(a["lines"]), 5)

    def test_a_ranker_json_of_another_kind_is_ignored(self):
        """A ranker.json of another kind is no ranker: the query takes the no-ranker road."""
        write(p4conf.sub(self.p4, "models", "ranker.json"), json.dumps({"kind": "phi_serve", "port": 1}))
        self.assertNotIn("ranker", q(self.p4, "does the quokka harness run the zebrafish plotter")["road"])


class Cli(Fixture):
    def test_index_rebuilds_only_when_newer(self):
        self.assertIn("rebuilt", run_cli("index", "--p4", self.p4).stdout)
        self.assertIn("fresh", run_cli("index", "--p4", self.p4).stdout)

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
    """A store migrated from the AudioPlugin-p4 fixture under P4_FIXTURES, when it is on this machine."""

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
        """The fastest of five `p4.py query` processes on this store, each timed from its start to its exit: the
        interpreter's start, the imports, the index's load and the query, as the prompt hook's own process pays them.
        The prompt hook's budget is stated at `h_recall` in hook.py."""
        text = "the CEF build keeps failing on the proprietary codecs patch, how do I rebuild incrementally?"
        times = []
        for _ in range(5):            # the best of 5: another process's burst on a loaded machine does not fail it
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


class RepoIndex(unittest.TestCase):
    """repo.build, which `p4.py index --repo` runs: paths, headings, symbols, build targets and commits from git, read
    again only where a commit changed them, with the exclusions and the cap; a generated file, an LFS pointer,
    node_modules/, a binary, a file over repo.MAX_BYTES and a `.p4ignore`d directory never appear."""

    def setUp(self):
        from test_hooks import git
        import repo
        self.repo, self.git = repo, git
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        files = {
            "src/axolotl.py": "import os\n\ndef axolotl_gain(x):\n    return x\n\nclass AxolotlMixer:\n    pass\n",
            "src/bandicoot.ts": "export function bandicootRoute() {}\nexport class BandicootStore {}\n",
            "src/capy.cc": "namespace capy {\nint CapybaraTick(int n) {\n  return n;\n}\n}\n",
            "README.md": "# Dugong tools\n\nThe dugong probe.\n\n## Install\n\npip install it\n",
            "CLAUDE.md": "# Conventions\n\nTabs never.\n",
            "CMakeLists.txt": "add_executable(echidna_app main.cc)\nadd_library(fossa_core STATIC a.cc)\n",
            "package.json": '{"scripts": {"gharial-build": "tsc"}}',
            "src/schema.generated.ts": "export const x = 1\n",
            "src/api.pb.go": "// Code generated by protoc-gen-go. DO NOT EDIT.\npackage api\n",
            "assets/big.psd": "x",
            "assets/model.bin": "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 9\n",
            "lfs/weights.txt": "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 9\n",
            "node_modules/left-pad/index.js": "module.exports = function leftPad() {}\n",
            "third_party/zlib/zlib.h": "int deflate(void);\n",
            "web/app.min.js": "function a(){}\n",
            "gen/out.py": "def hoatzin_generated(): pass\n",
            ".p4ignore": "gen\n",
            "huge.txt": "y" * (600 * 1024),
            "blob.dat2": "a\0b",
        }
        for rel, text in files.items():
            write(os.path.join(self.proj, rel), text)
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "first: the axolotl gain and the dugong probe")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(p4conf.sub(self.p4, "store"))

    def tearDown(self):
        self.tmp.cleanup()

    def shows(self):
        return [d["show"] for d in self.repo.entries(self.p4)]

    def test_documents_and_exclusions(self):
        s = self.repo.build(self.p4, self.proj)
        shows = self.shows()
        joined = "\n".join(shows)
        for want in ("src/axolotl.py — axolotl_gain", "src/axolotl.py — AxolotlMixer", "src/bandicoot.ts — "
                     "bandicootRoute", "src/bandicoot.ts — BandicootStore", "src/capy.cc — CapybaraTick",
                     "README.md — Dugong tools", "README.md — Install", "CLAUDE.md — Conventions",
                     "CMakeLists.txt — echidna_app", "CMakeLists.txt — fossa_core", "package.json — script "
                     "gharial-build"):
            self.assertIn(want, joined)
        for gone in ("schema.generated", "api.pb.go", "big.psd", "model.bin", "weights.txt", "node_modules",
                     "third_party", "app.min.js", "gen/out.py", "huge.txt", "blob.dat2", "hoatzin"):
            self.assertNotIn(gone, joined, gone)
        self.assertEqual(s["excluded"].get("lfs pointer"), 1)
        self.assertGreaterEqual(s["excluded"].get("vendored", 0), 2)
        self.assertIn("commit", [d["kind"] for d in self.repo.entries(self.p4)])
        commit = next(d for d in self.repo.entries(self.p4) if d["kind"] == "commit")
        self.assertIn("first: the axolotl gain", commit["show"])
        self.assertIn("src/axolotl.py", commit["show"])
        # into the index and out of a query as a file line, never a file's contents
        st.build_index(self.p4)
        # The no-ranker road wants most of a message's words in one document, so the message names the symbol alone:
        # with "mixer" or "defined" beside it, no one document would hold enough of them.
        r = cli.query(self.p4, "where is the axolotl gain", None, NOW, model={})
        self.assertTrue(any(l.startswith("- file: src/axolotl.py") for l in r["lines"]), r)
        self.assertFalse(any("return x" in l for l in r["lines"]))

    def test_incremental(self):
        self.repo.build(self.p4, self.proj)
        write(os.path.join(self.proj, "src", "axolotl.py"), "def axolotl_gain(x):\n    return 2\n\n"
                                                             "def axolotl_trim(x):\n    return x\n")
        self.git(self.proj, "commit", "-q", "-am", "second: trim the axolotl")
        s = self.repo.build(self.p4, self.proj)
        self.assertEqual((s["changed"], s["new_commits"]), (1, 1), "one commit: its one file read again")
        self.assertIn("src/axolotl.py — axolotl_trim", "\n".join(self.shows()))
        self.assertNotIn("AxolotlMixer", "\n".join(self.shows()))
        s = self.repo.build(self.p4, self.proj)
        self.assertEqual((s["changed"], s["new_commits"]), (0, 0))

    def test_cap_keeps_the_newest_touched(self):
        cap = self.repo.MAX_FILE_ENTRIES
        try:
            self.repo.MAX_FILE_ENTRIES = 4
            write(os.path.join(self.proj, "src", "late.py"), "def late_one(): pass\n")
            self.git(self.proj, "add", "-A")
            self.git(self.proj, "commit", "-q", "-m", "late")
            s = self.repo.build(self.p4, self.proj)
            self.assertGreater(s["cut"], 0)
            self.assertLessEqual(s["entries"], 4)
            self.assertIn("src/late.py", "\n".join(self.shows()), "the newest-touched file is kept")
            self.assertIn("cut at", self.repo.stats_line(self.p4))
        finally:
            self.repo.MAX_FILE_ENTRIES = cap

    def test_on_this_checkout_itself(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
        if not self.repo.is_repo(here):
            self.skipTest("not in a git checkout")
        p4 = os.path.join(self.tmp.name, "self", ".claude", "p4")
        os.makedirs(p4conf.sub(p4, "store"))
        s = self.repo.build(p4, here)
        self.assertGreater(s["files"], 10)
        self.assertIn("lbiza/plugins/p4-phi/scripts/store.py — build_index", "\n".join(d["show"] for d in
                                                                                 self.repo.entries(p4)))


# a real store in the flat layout: P4_MAC_STORE names it, and the default is a path on another machine
MAC_STORE = os.environ.get("P4_MAC_STORE", "/Users/ez/gritz/p4-repos/ap-p4_mac")


class Regressions(unittest.TestCase):
    """The no-ranker road on a copy of a real store, taken without its ranker: "which branch do mac commits go on"
    and "where does the p4 repo live" must each recall the ruling that answers it in the top 5, and ordinary
    messages and the suite's general prompts must print nothing. fallback_order's gates are held to these cases."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p4 = None
        if os.path.isdir(os.path.join(MAC_STORE, "store")):
            import shutil
            cls.p4 = os.path.join(cls.tmp.name, "p4")
            # A flat store's folders of the index's sources, without its scratchpad, built index, ranker or served
            # folder. build_index reads those sources at their places in the layout, under phi/ and temportal/, and
            # nothing here moves the copy there.
            for sub in ("store", "memory", "src", "models"):
                if os.path.isdir(os.path.join(MAC_STORE, sub)):
                    shutil.copytree(os.path.join(MAC_STORE, sub), os.path.join(cls.p4, sub),
                                    ignore=shutil.ignore_patterns("index.json", "ranker.json", "served"))
            st.build_index(cls.p4)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        if not self.p4:
            self.skipTest("ap-p4_mac store not present")

    def top5(self, text):
        return cli.query(self.p4, text, None, NOW, model={})["lines"][:5]

    def test_mac_branch(self):
        got = self.top5("which branch do mac commits go on")
        self.assertTrue(any("on this Mac the work is committed on _mac" in l or
                            "the Mac's branch is 0.0.1-apple&win&mac_mac" in l for l in got), got)

    def test_p4_repo(self):
        got = self.top5("where does the p4 repo live")
        self.assertTrue(any("the p4 repo is nested in the project" in l for l in got), got)

    def test_ordinary_messages_silent(self):
        for text in ("hi", "keep going", "thanks", "ok", "what is the weather like today"):
            self.assertEqual(self.top5(text), [], text)


    def test_suite_prompts_silent(self):
        """At least 95% of the suite's general prompts, those of every category but lessons, print nothing."""
        suite = os.path.join(HERE, "..", "..", "..", "..", "scripts", "session", "overrides_tasks.jsonl")
        if not os.path.exists(suite):
            self.skipTest("the suite's tasks are not beside this checkout")
        with open(suite, encoding="utf-8") as f:
            prompts = [json.loads(l) for l in f if l.strip()]
        prompts = [p for p in prompts if p.get("category") != "lessons"]
        loud = [p["id"] for p in prompts if self.top5(p["prompt"])]
        self.assertGreaterEqual(1 - len(loud) / len(prompts), 0.95, loud)


class Tokens(unittest.TestCase):
    def test_letter_digit_and_forms(self):
        self.assertIn("p4", ranker.tokens("the p4 repo"))
        self.assertIn("mac", ranker.tokens("_mac"))
        self.assertEqual(cli.stem("commits"), cli.stem("committed"))
        self.assertEqual(cli.stem("branches"), "branch")


class OrdinarySilentOnFixture(Fixture):
    def test_hi_and_keep_going_without_history(self):
        p4 = make_store(tempfile.mkdtemp(dir=self.tmp.name))
        for rel in ("aaaa1111.md", "bbbb2222.md"):
            os.remove(p4conf.sub(p4, "store", "messages", rel))
        for text in ("hi", "keep going"):
            self.assertEqual(cli.query(p4, text, None, NOW)["lines"], [], text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
