#!/usr/bin/env python3
"""Tests for store.py: the entry format, ids, the status rule (finding 17), the vocabulary, the index's staleness.

Run: python3 test_store.py   (stdlib unittest; pytest collects it too)

The real-store checks run only when the four cloned p4 repos exist (P4_FIXTURES, default the colab clone path);
everything else builds its own small fixture in a temp directory.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import store as st  # noqa: E402

FIXTURES = os.environ.get("P4_FIXTURES", "/Users/ez/gritz/p4/.claude/p4/scratchpad/.out/p4-colab/overrides-1-work/stores")
REPOS = ("AudioPlugin-p4", "ap-p4_mac", "p4-p4", "phi-p4")
NOW = "2026-11-01 18:00"


def fixture(name):
    path = os.path.join(FIXTURES, name)
    return path if os.path.isdir(os.path.join(path, "sessions")) else None


# --- a small new-format store, shared by the query tests ------------------------------------------------

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def entry_file(fname, entries):
    return st.render(fname, entries)


def make_store(root):
    """A .claude/p4 tree in the new layout, small enough to read by eye."""
    p4 = os.path.join(root, ".claude", "p4")
    rules = [
        [("ruling", "the macOS deployment target is 13.3"), ("owner-words", '"Raise to 13.3"'),
         ("scope", "the AudioPlugin project, macOS"), ("status", "LIVE"), ("time", "2026-11-01 10:50")],
        [("ruling", "the Mac's branch is 0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac"),
         ("owner-words", '"yes switch under 0.0.1-apple&win&mac but branch 0.0.1-apple&win&mac_mac"'),
         ("status", "LIVE"), ("time", "2026-11-01 11:18")],
        [("ruling", "pull every repo the work spans before a long build or run starts"),
         ("owner-words", '"updates u need to pull from both repos then start"'), ("status", "LIVE"),
         ("time", "2026-10-28 23:00")],
        [("ruling", "the tombstone sweeper keeps the keychain flag in the quokka harness"),
         ("status", "LIVE"), ("time", "2026-10-20 09:00")],
        [("ruling", "the zebrafish plotter uses the quokka harness for its golden images"),
         ("status", "LIVE"), ("time", "2026-10-21 09:00"),
         ("plain", "the zebrafish plotter checks its golden images with the quokka harness")],
        [("ruling", "move what landed in ~/gritz into ~/code"), ("status", "SPENT"), ("time", "2026-10-29 10:44")],
    ]
    for k in range(3):
        rules.append([("ruling", f"the quokka harness runs case {k} of the zebrafish plotter on every push"),
                      ("status", "LIVE"), ("time", f"2026-10-2{k} 12:00")])
    corrections = [
        [("key", "mac-branch-name"), ("time", "2026-11-01 11:18"),
         ("match", "0.0.1-1.0.0_mac, the README's name for the Mac's branch"),
         ("meant", "0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac"),
         ("delta", "the branch renamed before any commit landed on it")],
    ]
    retractions = [
        [("freed", "the Mac's branch named 0.0.1-1.0.0_mac"), ("time", "2026-11-01 11:18"), ("cause", "superseded"),
         ("owner-words", '"yes switch under 0.0.1-apple&win&mac but branch 0.0.1-apple&win&mac_mac"'),
         ("lesson", "the Mac's branch is 0.0.1-apple&win&mac_mac")],
    ]
    facts = [[("claim", "CEF's C API wraps every refcounted object with a heap allocation on each side"),
              ("time", "2026-10-12 18:14"), ("source", "cpptoc_ref_counted.h:31"), ("verified", "2026-10-12 18:14")]]
    write(os.path.join(p4, "store", "rules.md"), entry_file("rules.md", rules))
    write(os.path.join(p4, "store", "corrections.md"), entry_file("corrections.md", corrections))
    write(os.path.join(p4, "store", "retractions.md"), entry_file("retractions.md", retractions))
    write(os.path.join(p4, "store", "facts.md"), entry_file("facts.md", facts))
    rows_a = [
        [("fingerprint", '"Keep going"'), ("time", "2026-10-01 10:00"), ("arrival", "turn"), ("state", "FRESH"),
         ("addressed", "continued the running CEF build as configured, nothing to change")],
        [("fingerprint", '"ship it"'), ("time", "2026-10-01 10:05"), ("arrival", "turn"), ("state", "FRESH"),
         ("addressed", "pushed the branch")],
        [("fingerprint", '"rebuild the wombat installer with the signing step"'), ("time", "2026-10-01 10:10"),
         ("arrival", "turn"), ("state", "FRESH"), ("addressed", "rebuilt the wombat installer, signed")],
        [("fingerprint", '"measure the axolotl latency on the second rig"'), ("time", "2026-10-01 10:20"),
         ("arrival", "turn")],
    ]
    rows_b = [
        [("fingerprint", '"Keep going"'), ("time", "2026-10-02 09:00"), ("arrival", "turn"), ("state", "FRESH"),
         ("addressed", "continued the running CEF build as configured, nothing to change")],
    ]
    write(os.path.join(p4, "store", "messages", "aaaa1111.md"), entry_file("messages/aaaa1111.md", rows_a))
    write(os.path.join(p4, "store", "messages", "bbbb2222.md"), entry_file("messages/bbbb2222.md", rows_b))
    vocab = [st.vocab_entry_pairs("the mac branch thing",
                                  "the branch 0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac",
                                  '2026-11-01 11:18 — you wrote "rename it to the mac branch thing"', "correction",
                                  ["rules.md:2026-11-01 11:18:" + st.sha8(rules[1][0][1])], "2026-11-01 13:30"),
             st.vocab_entry_pairs("frobnicate", "(pending)", "2026-10-01 — you wrote \"frobnicate it\"",
                                  "follow-up", [], "2026-11-01 13:30")]
    write(os.path.join(p4, "store", "vocabulary.md"), entry_file(st.VOCABULARY, vocab))
    write(os.path.join(p4, "memory", "MEMORY.md"), "- [cef](cef.md)\n")
    write(os.path.join(p4, "memory", "cef.md"), "---\nname: cef\ndescription: how the capybara build is watched\n"
          "---\n\n# Watching a capybara build\n\nThe ninja log names objects by directory.\n")
    write(os.path.join(p4, "src", "tool", "probe.py"), "#!/usr/bin/env python3\n# probe the narwhal port\nprint(1)\n")
    return p4


class EntryFormat(unittest.TestCase):
    def test_round_trip_with_continuations(self):
        pairs = [("fingerprint", '"line one'), ("time", "2026-10-01 10:00"), ("addressed", "a\nb\n- c: d")]
        text = st.render("messages/x.md", [pairs])
        got = st.parse(text, "messages/x.md")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].pairs, pairs)
        self.assertEqual(got[0].head, "fingerprint")
        self.assertEqual(len(text.split("\n\n")[0].split("\n")), 3, "three header lines in ordinary words")

    def test_header_is_not_an_entry(self):
        text = st.render("rules.md", [[("ruling", "x"), ("time", "2026-01-01 00:00")]])
        self.assertEqual([e.head for e in st.parse(text, "rules.md")], ["ruling"])
        for line in text.split("\n")[:3]:
            self.assertNotIn("[", line, "no schema placeholders in the header")


class Ids(unittest.TestCase):
    def test_shape(self):
        e = st.parse(st.render("rules.md", [[("ruling", "abc"), ("time", "2026-01-02 03:04")]]), "rules.md")[0]
        self.assertEqual(e.id, "rules.md:2026-01-02 03:04:" + st.sha8("abc"))

    def test_stable_across_line_insertion(self):
        ents = [[("ruling", f"rule {k}"), ("time", f"2026-01-0{k + 1} 00:00")] for k in range(4)]
        before = {e.value: (e.id, e.line) for e in st.parse(st.render("rules.md", ents), "rules.md")}
        ents2 = [[("ruling", "a new first rule"), ("scope", "x"), ("time", "2026-02-01 00:00")]] + ents
        after = {e.value: (e.id, e.line) for e in st.parse(st.render("rules.md", ents2), "rules.md")}
        for v, (i, line) in before.items():
            self.assertEqual(after[v][0], i)
            self.assertNotEqual(after[v][1], line, "the line moved, the id did not")

    def test_duplicates_numbered(self):
        ents = [[("ruling", "same"), ("time", "t")], [("ruling", "same"), ("time", "t")]]
        ids = [e.id for e in st.parse(st.render("rules.md", ents), "rules.md")]
        self.assertEqual(ids[1], ids[0] + "~2")


class StatusRule(unittest.TestCase):
    def files(self, rule_time, rule_head="the Mac's branch is X", words='"switch to X"', status="LIVE"):
        rules = [[("ruling", rule_head), ("owner-words", words), ("status", status), ("time", rule_time)]]
        rets = [[("freed", "the branch named Y"), ("time", "2026-11-01 11:18"), ("owner-words", '"switch to X"')]]
        files = {"rules.md": st.parse(st.render("rules.md", rules), "rules.md"),
                 "retractions.md": st.parse(st.render("retractions.md", rets), "retractions.md")}
        st.apply_status(files)
        return files

    def test_ruling_made_by_the_retraction_stays_live(self):
        """Finding 17: shared owner-words, the ruling at the retraction's time (it is what the correction wrote)."""
        f = self.files("2026-11-01 11:18")
        self.assertEqual(f["rules.md"][0].state, "LIVE")
        st.apply_status(f, rule="old")
        self.assertEqual(f["rules.md"][0].state, "FREED", "the old mask freed it")

    def test_earlier_entry_with_shared_words_is_freed(self):
        self.assertEqual(self.files("2026-11-01 09:00")["rules.md"][0].state, "FREED")

    def test_head_within_freed(self):
        f = self.files("2026-11-01 12:00", rule_head="the branch named Y and its build tree", words='"other"')
        self.assertEqual(f["rules.md"][0].state, "LIVE", "the shorter side must be 24 chars")
        rets = [[("freed", "the branch named Y and its build tree, kept for the CI"), ("time", "2026-11-01 13:00")]]
        rules = [[("ruling", "the branch named Y and its build tree"), ("time", "2026-11-01 12:00")]]
        files = {"rules.md": st.parse(st.render("rules.md", rules), "rules.md"),
                 "retractions.md": st.parse(st.render("retractions.md", rets), "retractions.md")}
        st.apply_status(files)
        self.assertEqual(files["rules.md"][0].state, "FREED")

    def test_spent_is_a_field(self):
        self.assertEqual(self.files("2026-11-01 11:18", status="SPENT")["rules.md"][0].state, "SPENT")

    def test_retraction_never_freed(self):
        self.assertEqual(self.files("2026-11-01 09:00")["retractions.md"][0].state, "LIVE")


class Vocabulary(unittest.TestCase):
    def test_design_example_parses(self):
        with tempfile.TemporaryDirectory() as d:
            text = """The owner's words.
Grown from corrections.
Fields: term.

- term: the mac branch thing
  means: the branch 0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac
  because: 2026-11-01 11:18 — you wrote "rename it to the mac branch thing" and the session used 0.0.1-1.0.0_mac
  because: 2026-11-02 09:00 — a second exchange
  source: correction (corrections.md: mac-branch-name)
  points-at: rules.md:2026-11-01 11:18:a1b2c3d4, rules.md:2026-11-02 09:00:b1b2c3d4
  added: 2026-11-01 13:30
  status: on

- term: frob
  means: (pending)
  status: off
"""
            write(os.path.join(d, "store", "vocabulary.md"), text)
            v = st.read_vocabulary(d)
            self.assertEqual(len(v), 2)
            self.assertEqual(v[0]["term"], "the mac branch thing")
            self.assertEqual(len(v[0]["because"]), 2)
            self.assertEqual(v[0]["points-at"], ["rules.md:2026-11-01 11:18:a1b2c3d4", "rules.md:2026-11-02 09:00:b1b2c3d4"])
            self.assertFalse(v[0]["pending"])
            self.assertTrue(v[1]["pending"])
            self.assertEqual(v[1]["status"], "off")


class IndexStaleness(unittest.TestCase):
    def test_rebuilt_only_when_newer(self):
        with tempfile.TemporaryDirectory() as d:
            p4 = make_store(d)
            self.assertTrue(st.index_stale(p4))
            idx, rebuilt = st.ensure_index(p4)
            self.assertTrue(rebuilt)
            self.assertFalse(st.index_stale(p4))
            idx2, rebuilt2 = st.ensure_index(p4)
            self.assertFalse(rebuilt2)
            self.assertEqual([d_["id"] for d_ in idx["docs"]], [d_["id"] for d_ in idx2["docs"]])
            # a store file newer than the index
            future = time.time() + 5
            path = os.path.join(p4, "store", "facts.md")
            os.utime(path, (future, future))
            self.assertTrue(st.index_stale(p4))
            st.build_index(p4)
            os.utime(st.index_path(p4), (future + 1, future + 1))
            self.assertFalse(st.index_stale(p4))
            # a memory file removed
            os.remove(os.path.join(p4, "memory", "cef.md"))
            self.assertTrue(st.index_stale(p4))

    def test_index_excludes_freed_spent_and_open(self):
        with tempfile.TemporaryDirectory() as d:
            p4 = make_store(d)
            idx = st.build_index(p4)
            shown = " ".join(x["show"] for x in idx["docs"])
            self.assertNotIn("~/gritz", shown, "a SPENT ruling is kept, never recalled")
            self.assertNotIn("axolotl", shown, "an open row is not indexed")
            self.assertIn("rebuilt the wombat installer", shown)
            self.assertIn("capybara", shown, "memory sections are indexed")
            self.assertIn("narwhal", shown, "a src file's head is indexed")
            self.assertNotIn("frobnicate", shown, "vocabulary expands, it is not indexed")

    def test_ids_stable_across_insertion_in_index(self):
        with tempfile.TemporaryDirectory() as d:
            p4 = make_store(d)
            before = {x["id"] for x in st.build_index(p4)["docs"]}
            path = os.path.join(p4, "store", "rules.md")
            ents = [e.pairs for e in st.load_file(p4, "rules.md")]
            write(path, st.render("rules.md", [[("ruling", "an inserted ruling"), ("time", "2026-12-01 00:00")]] + ents))
            after = {x["id"] for x in st.build_index(p4)["docs"]}
            self.assertEqual(before - after, set())
            self.assertEqual(len(after - before), 1)


@unittest.skipUnless(fixture("ap-p4_mac"), "the ap-p4_mac clone is not on this machine")
class RealFinding17(unittest.TestCase):
    def test_six_rulings_live_after_migration(self):
        import migrate
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "p4")
            migrate.run(fixture("ap-p4_mac"), out, apply=True, now=NOW, report_path=os.path.join(d, "r.md"))
            files = st.load_store(out)
            ms = st.masks(files["retractions.md"])
            masked = [e for e in files["rules.md"]
                      if st.status_of("rules.md", e.value, e.fields, ms, rule="old")[0] == "FREED"]
            self.assertEqual(len(masked), 6)
            self.assertEqual([e.state for e in masked], ["LIVE"] * 6)


if __name__ == "__main__":
    unittest.main(verbosity=1)
