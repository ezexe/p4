#!/usr/bin/env python3
"""deps.py: dependency roots as recall entries, read again when a package is installed or updated.

    python3 -I lbiza/plugins/p4-recall/scripts/test_deps.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deps  # noqa: E402
import labels as lb  # noqa: E402
import store as st  # noqa: E402
import train  # noqa: E402
import transcript as tr  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class Deps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = os.path.realpath(self.tmp.name)
        self.proj, self.ext = os.path.join(t, "proj"), os.path.join(t, "elsewhere", "framework")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(os.path.join(self.p4, "models"))
        os.makedirs(os.path.join(self.p4, "store"))
        nm = os.path.join(self.proj, "node_modules")
        write(os.path.join(self.proj, "package.json"),
              json.dumps({"dependencies": {"left-pad": "^1.0.0", "@scope/tool": "2.0.0"}}))
        write(os.path.join(nm, "left-pad", "package.json"),
              json.dumps({"name": "left-pad", "version": "1.0.0", "description": "pads strings", "main": "lib/pad.js"}))
        write(os.path.join(nm, "left-pad", "lib", "pad.js"), "export function leftPad(s, n) { return s }\n")
        write(os.path.join(nm, "left-pad", "README.md"), "# left-pad\n\n## Usage\n\nCall leftPad.\n")
        write(os.path.join(nm, "left-pad", "test", "pad.test.js"), "function testOnly() {}\n")
        write(os.path.join(nm, "left-pad", "node_modules", "inner", "package.json"), '{"version": "9.9.9"}')
        write(os.path.join(nm, "@scope", "tool", "package.json"), json.dumps({"version": "2.0.0"}))
        write(os.path.join(nm, "transitive", "package.json"), json.dumps({"version": "0.3.0", "main": "index.js"}))
        write(os.path.join(nm, "transitive", "index.js"), "export function deepHelper() {}\n")
        write(os.path.join(nm, "transitive", "lib", "more.js"), "export function notRead() {}\n")
        fc = os.path.join(self.proj, "library_packages", "_deps")
        write(os.path.join(fc, "juce-src", "CMakeLists.txt"), "cmake_minimum_required(VERSION 3.22)\nproject(JUCE VERSION 8.0.4 LANGUAGES C CXX)\n")
        write(os.path.join(fc, "juce-src", "modules", "juce_core", "juce_core.h"), "class StringArray {\n};\n")
        write(os.path.join(fc, "juce-build", "generated.h"), "class BuildOutput {\n};\n")
        write(os.path.join(self.proj, "library_packages", "cef", "include", "cef_app.h"), "class CefApp {\n};\n")
        write(os.path.join(self.proj, "library_packages", "cef.sha256"), "abcdef0123456789\n")
        write(os.path.join(self.ext, ".git", "HEAD"), "ref: refs/heads/main\n")
        write(os.path.join(self.ext, ".git", "refs", "heads", "main"), "1111111111111111111111111111111111111111\n")
        write(os.path.join(self.ext, "include", "api.h"), "class FrameworkApi {\n};\n")
        deps.AUTO, deps.ROOTS, deps.MAX_ENTRIES = True, ["library_packages", self.ext], 20000

    def tearDown(self):
        self.tmp.cleanup()

    def pkgs(self):
        s = deps.load_state(self.p4)
        return {n: v for r in s["roots"].values() for n, v in r["packages"].items()}

    def ids(self):
        return {d["id"]: d for d in deps.entries(self.p4)}

    def test_roots_and_packages(self):
        got = dict(deps.roots(self.proj))
        self.assertEqual(sorted(got.values()), ["@framework", "library_packages", "node_modules"],
                         "the _deps inside a configured root is not a root of its own")
        s = deps.build(self.p4, self.proj)
        self.assertEqual((s["roots"], s["packages"], s["read"], s["installed"], s["updated"]), (3, 6, 6, 6, 0))
        p = self.pkgs()
        self.assertEqual({n: v["version"] for n, v in p.items()},
                         {"left-pad": "1.0.0", "@scope/tool": "2.0.0", "transitive": "0.3.0", "juce": "8.0.4",
                          "cef": "sha256:abcdef012345", "framework": "@111111111111"})
        self.assertEqual({n for n, v in p.items() if v["light"]}, {"transitive"})
        ids = self.ids()
        for want in ("repo:node_modules/left-pad", "repo:node_modules/left-pad/lib/pad.js",
                     "repo:library_packages/_deps/juce-src", "repo:library_packages/_deps/juce-src/modules/juce_core/juce_core.h",
                     "repo:library_packages/cef/include/cef_app.h", "repo:@framework", "repo:@framework/include/api.h",
                     "repo:node_modules/transitive/index.js"):
            self.assertIn(want, ids)
        shows = " | ".join(d["show"] for d in ids.values())
        for sym in ("leftPad", "StringArray", "CefApp", "FrameworkApi", "Usage", "deepHelper"):
            self.assertIn(sym, shows)
        for out in ("testOnly", "BuildOutput", "inner", "notRead"):
            self.assertNotIn(out, shows, "tests, build output, nested modules and a transitive package's depths stay out")
        self.assertIn("node_modules/left-pad (left-pad 1.0.0, a dependency)", shows)
        self.assertFalse([i for i in ids if i.startswith("dep-update:")], "a root's first reading records no updates")

    def test_unchanged_is_not_read_or_written_again(self):
        deps.build(self.p4, self.proj, now_s=1000.0)
        before = os.stat(deps.state_path(self.p4)).st_mtime_ns
        s = deps.build(self.p4, self.proj, now_s=2000.0)
        self.assertEqual((s["read"], s["updated"], s["installed"], s["removed"], s["complete"]), (0, 0, 0, 0, True))
        self.assertEqual(os.stat(deps.state_path(self.p4)).st_mtime_ns, before, "the index does not go stale")
        self.assertEqual(deps.changed_at(self.p4), 1000.0)

    def test_update_install_remove(self):
        deps.build(self.p4, self.proj, now="2026-11-01 10:00", now_s=1000.0)
        nm = os.path.join(self.proj, "node_modules")
        write(os.path.join(nm, "left-pad", "package.json"), json.dumps({"version": "1.1.0", "main": "lib/pad.js"}))
        write(os.path.join(nm, "left-pad", "lib", "pad.js"), "export function leftPadFast(s, n) { return s }\n")
        write(os.path.join(self.ext, ".git", "refs", "heads", "main"), "2222222222222222222222222222222222222222\n")
        write(os.path.join(nm, "fresh", "package.json"), json.dumps({"version": "0.0.1"}))
        shutil.rmtree(os.path.join(nm, "transitive"))
        s = deps.build(self.p4, self.proj, now="2026-11-10 12:00", now_s=5000.0)
        self.assertEqual((s["read"], s["updated"], s["installed"], s["removed"]), (3, 2, 1, 1))
        self.assertEqual(deps.changed_at(self.p4), 5000.0)
        ids = self.ids()
        ups = sorted(d["show"] for i, d in ids.items() if i.startswith("dep-update:"))
        self.assertEqual(ups, ["framework updated @111111111111 -> @222222222222 (@framework)",
                               "fresh 0.0.1 installed (node_modules/fresh)",
                               "left-pad updated 1.0.0 -> 1.1.0 (node_modules/left-pad)",
                               "transitive 0.3.0 removed (node_modules/transitive)"])
        self.assertTrue(all(d["time"] == "2026-11-10" and d["kind"] == "commit" for i, d in ids.items()
                            if i.startswith("dep-update:")))
        shows = " | ".join(d["show"] for d in ids.values())
        self.assertIn("leftPadFast", shows)
        self.assertNotIn("deepHelper", shows)

    def test_opened_file_is_read_past_the_caps(self):
        deep = os.path.join(self.ext, "a", "b", "c", "d", "e", "f", "g", "deep.h")       # below DEPTH: never walked
        write(deep, "class DeepThing {\n};\n")
        deps.build(self.p4, self.proj)
        self.assertNotIn("repo:@framework/a/b/c/d/e/f/g/deep.h", self.ids())
        tr.EXTERNAL = deps.externals(self.p4)
        turn = {"cwd": self.proj, "calls": [{"name": "Read", "input": {"file_path": deep}},
                                            {"name": "Read", "input": {"file_path": os.path.join(self.ext, "include", "api.h")}}]}
        got = deps.opened_in_turn(turn, self.proj)
        self.assertEqual(got, ["@framework/a/b/c/d/e/f/g/deep.h", "@framework/include/api.h"])
        self.assertEqual(deps.note_opened(self.p4, got), 1, "the one the index lacks")
        self.assertEqual(deps.note_opened(self.p4, got), 0)
        s = deps.build(self.p4, self.proj)
        self.assertEqual((s["read"], s["updated"]), (1, 0), "its package alone, and not as an update")
        self.assertIn("DeepThing", self.ids()["repo:@framework/a/b/c/d/e/f/g/deep.h#" + deps.repo.sha8("DeepThing")]["show"])
        self.assertEqual(deps.build(self.p4, self.proj)["read"], 0)

    def test_spread_takes_from_every_directory(self):
        files = [f"modules/a/f{i}.h" for i in range(5)] + [f"modules/z/g{i}.h" for i in range(5)] + ["README.md"]
        got = deps.spread(files, set())
        self.assertEqual(got[:5], ["README.md", "modules/a/f0.h", "modules/z/g0.h", "modules/a/f1.h", "modules/z/g1.h"])

    def test_deadline_resumes(self):
        s = deps.build(self.p4, self.proj, deadline_s=-1.0)
        self.assertEqual((s["read"], s["complete"]), (0, False))
        s = deps.build(self.p4, self.proj)
        self.assertEqual((s["read"], s["complete"]), (6, True))

    def test_cap_leaves_whole_packages_out(self):
        deps.MAX_ENTRIES = 6
        s = deps.build(self.p4, self.proj)
        self.assertGreater(s["cut"], 0)
        self.assertLessEqual(len([d for d in deps.entries(self.p4) if d["kind"] == "file"]), 6)
        self.assertIn("cut at 6 entries", deps.stats_line(self.p4))

    def test_index_labels_and_owed_round(self):
        deps.build(self.p4, self.proj, now_s=time.time() - 50)
        idx = st.build_index(self.p4)
        by = {d["id"]: d for d in idx["docs"]}
        self.assertEqual(by["repo:@framework/include/api.h"]["file"], "repo")
        self.assertFalse(st.index_stale(self.p4))
        # a turn that opened a file of the root outside the project, and one of node_modules, is labelled on both
        turn = {"cwd": self.proj, "texts": [], "time": "2026-11-10 12:00", "calls": [
            {"name": "Read", "input": {"file_path": os.path.join(self.ext, "include", "api.h")}, "text_index": 0},
            {"name": "Read", "input": {"file_path": os.path.join(self.proj, "node_modules", "left-pad", "lib", "pad.js")},
             "text_index": 0}]}
        rows, _ = lb.turn_repo_labels(turn, self.proj, lb.repo_index(idx), "t1", "FrameworkApi is the entry", p4=self.p4)
        got = {r["entry"]: r["note"] for r in rows}
        self.assertEqual(got.get("repo:@framework/include/api.h"), "cited")
        self.assertEqual(got.get("repo:node_modules/left-pad/lib/pad.js"), "dropped")
        self.assertEqual(tr.rel(os.path.join(self.ext, "..", "other.h"), self.proj), "", "outside every root: no path")
        # the retrain: a round older than the change is owed again, a round after it is not
        ev = os.path.join(self.p4, "models", "eval.tsv")
        write(ev, "round\ttime\tlabels\tpromoted\twhy\n0\t2026-11-01 00:00\t0\tkept old\tx\n")
        os.utime(ev, (time.time() - 100, time.time() - 100))
        ok, why = train.owed(self.p4)
        self.assertTrue(ok, why)
        self.assertIn("dependency", why)
        os.utime(ev, None)
        self.assertFalse(train.owed(self.p4)[0])


if __name__ == "__main__":
    unittest.main()
