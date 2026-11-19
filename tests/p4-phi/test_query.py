#!/usr/bin/env python3
"""Tests for `p4.py query`, `p4.py index` and `p4.py check`.

Run: python -m pytest tests/p4-phi/test_query.py

On a small fixture store: the same lines for the same message; no line for "hi", for an ordinary message or for one
that shares a single word with the documents; at most MAX_LINES lines, PER_FILE of them from one file, each with at
most TEXT_CHARS characters of text; the line's shape; no jargon-list word printed; the history line for a short
message sent twice before and none for one sent once; the repeat line for a resembling completed row and none for an
open row or another session's; dictionary expansion; the trained ranker's road. repo.build, which
`p4.py index --repo` runs, on a small git repository and on this checkout. The cases on real stores, a store
migrated from the AudioPlugin-p4 fixture and a copy of the store P4_MAC_STORE names, are measurements of one store and
live in the experiments repository ezexe/p4-phi, at experiments/p4-suite/test_query.py.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "lbiza", "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import p4conf  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402
from test_store import NOW, make_store, write  # noqa: E402

LINE_RE = re.compile(r"^- (\d{4}-\d\d-\d\d|undated) (rule|correction|missed detail|retracted|fact|memory|"
                     r"earlier message|saved code): (.+) \(((?:phi/store|temportal/memory|temportal/src)/[^:]+):(\d+)\)$")
SCRIPT = os.path.join(SRC, "p4.py")


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

    def test_a_build_that_changes_nothing_leaves_the_index_fresh(self):
        """repo.json is written only when the repository's documents changed: a second build of an unchanged tree,
        at another time, leaves the file as it was, so the index built after the first stays fresh."""
        self.repo.build(self.p4, self.proj, now="2026-11-01 10:00")
        st.build_index(self.p4)
        path = self.repo.state_path(self.p4)
        before = (os.stat(path).st_mtime_ns, open(path, "rb").read())
        time.sleep(0.05)
        self.repo.build(self.p4, self.proj, now="2026-11-01 11:00")
        self.assertEqual((os.stat(path).st_mtime_ns, open(path, "rb").read()), before, "repo.json untouched")
        self.assertFalse(st.index_stale(self.p4), "no index rebuild owed")

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
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SRC))))
        if not self.repo.is_repo(here):
            self.skipTest("not in a git checkout")
        p4 = os.path.join(self.tmp.name, "self", ".claude", "p4")
        os.makedirs(p4conf.sub(p4, "store"))
        s = self.repo.build(p4, here)
        self.assertGreater(s["files"], 10)
        self.assertIn("lbiza/plugins/p4-phi/scripts/store.py — build_index", "\n".join(d["show"] for d in
                                                                                 self.repo.entries(p4)))


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


class PluginReads(unittest.TestCase):
    def test_no_script_reads_outside_the_plugin(self):
        """ezexe/p4#79: no script of p4-phi climbs four folders out of the plugin to read an input."""
        hits = [(n, i) for n in sorted(os.listdir(SRC)) if n.endswith(".py")
                for i, l in enumerate(open(os.path.join(SRC, n), encoding="utf-8"), 1)
                if ", ".join(['".."'] * 4) in l]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
