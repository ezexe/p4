#!/usr/bin/env python3
"""node.py: a session's place in the session tree, from phi's files and from the app's records.

    python3 -I lbiza/plugins/p4-recall/scripts/test_node.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import node  # noqa: E402
import p4 as cli  # noqa: E402
import store as st  # noqa: E402

COPIES = [HERE.parents[1] / "p4-phi" / "scripts" / "node.py"]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def session(p4, sid, parent="", task="", created="2026-11-10 10:00", cli=(), notes=()):
    d = {"sessionId": sid, "cliSessionIds": list(cli) or [sid + "-cli"], "createdAt": created, "task": task}
    if parent:
        d["spawnedFrom"] = {"sessionId": parent, "source": "record"}
    base = os.path.join(p4, "phi", "sessions", sid)
    write(os.path.join(base, "session.json"), json.dumps(d))
    if notes:
        write(os.path.join(base, "notes.jsonl"), "".join(json.dumps({"time": t, "claim": c}) + "\n" for t, c in notes))


class Tree(unittest.TestCase):
    def setUp(self):
        self.p4 = tempfile.mkdtemp(prefix="p4-node-")

    def tearDown(self):
        shutil.rmtree(self.p4, ignore_errors=True)

    def test_every_plugin_carries_the_same_copy(self):
        src = (HERE / "node.py").read_bytes()
        for c in COPIES:
            self.assertEqual(c.read_bytes(), src, c)

    def test_a_child_reads_its_task_the_tasks_above_and_its_siblings(self):
        session(self.p4, "top", task="port the narwhal plotter to macos",
                notes=[("2026-11-10 10:05", "the plotter builds with cmake 3.28")])
        session(self.p4, "mid", "top", "write the cmake presets for the narwhal port", "2026-11-10 10:10")
        session(self.p4, "leaf", "mid", "check the preset on windows", "2026-11-10 10:20")
        session(self.p4, "twin", "mid", "check the preset on the mac", "2026-11-10 10:21")
        t = node.phi_tree(self.p4)
        n = t.at("leaf")
        self.assertEqual(n.own, "check the preset on windows")
        self.assertEqual([s for s, _ in n.up], ["mid", "top"], "nearest first")
        self.assertEqual(n.notes, ["the plotter builds with cmake 3.28"])
        self.assertEqual(n.side, [("twin", "check the preset on the mac")])
        self.assertIn("narwhal", n.text())
        self.assertNotIn("mac\n", n.text() + "\n", "siblings join the text only when asked")
        self.assertEqual(t.at("leaf-cli").sid, "leaf", "a CLI id finds its session")
        self.assertIsNone(t.at("nobody"))

    def test_nothing_after_the_message_is_read(self):
        session(self.p4, "top", task="first ask", created="2026-11-10 10:00",
                notes=[("2026-11-10 12:00", "a note written later")])
        session(self.p4, "kid", "top", "the kid's brief", "2026-11-10 10:30")
        session(self.p4, "late", "top", "a sibling started later", "2026-11-10 11:30")
        n = node.phi_tree(self.p4).at("kid", "2026-11-10 11:00")
        self.assertEqual(n.notes, [])
        self.assertEqual(n.side, [])

    def test_a_loop_in_the_tree_ends(self):
        session(self.p4, "a", "b", "ask a")
        session(self.p4, "b", "a", "ask b")
        n = node.phi_tree(self.p4).at("a")
        self.assertEqual([s for s, _ in n.up], ["b"])

    def test_the_app_records_and_tasks_tsv_make_the_same_tree(self):
        rec = os.path.join(self.p4, "records", "acct", "org")
        write(os.path.join(rec, "local_p.json"), json.dumps({"sessionId": "local_p", "cliSessionId": "aaaa1111-x",
                                                             "createdAt": 1794470000000}))
        write(os.path.join(rec, "local_c.json"), json.dumps({
            "sessionId": "local_c", "cliSessionId": "bbbb2222-y", "createdAt": 1794471000000,
            "spawnedFrom": str({"sessionId": "local_p", "taskId": "t"})}))
        tsv = os.path.join(self.p4, "tasks.tsv")
        write(tsv, "id\tsession\ttime\ttext\tkind\n"
                   "m1\taaaa1111\t2026-11-10 09:00\tthe parent's ask about the quokka harness\tfirst\n"
                   "m2\tbbbb2222\t2026-11-10 09:30\tthe child's brief\tfirst\n"
                   "m3\tbbbb2222\t2026-11-10 09:40\ta later message\tlater\n")
        t = node.record_tree(tsv, [os.path.join(self.p4, "records")])
        n = t.at("bbbb2222", "2026-11-10 09:45")
        self.assertEqual(n.own, "the child's brief", "a session's task is its first request")
        self.assertEqual(n.up, [("local_p", "the parent's ask about the quokka harness")])
        self.assertEqual(t.at("bbbb2222", "2026-11-10 08:00").up, [], "a parent's task asked later is not read")

    def test_live_reads_the_host_session(self):
        session(self.p4, "local_top", task="top ask")
        session(self.p4, "local_kid", "local_top", "kid ask")
        old = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")
        os.environ["CLAUDE_CODE_HOST_SESSION_ID"] = "local_kid"
        try:
            self.assertEqual(node.live(self.p4).up, [("local_top", "top ask")])
        finally:
            if old is None:
                os.environ.pop("CLAUDE_CODE_HOST_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_HOST_SESSION_ID"] = old
        self.assertIsNone(node.live(os.path.join(self.p4, "none")))


class Overlap(unittest.TestCase):
    def test_items_nearest_the_task_come_first_and_ties_keep_their_order(self):
        items = ["the build cache lives in out/", "golden images of the plotter", "plotter presets per machine"]
        self.assertEqual(node.by_overlap(items, "fix the plotter presets"),
                         ["plotter presets per machine", "golden images of the plotter", "the build cache lives in out/"])
        self.assertEqual(node.by_overlap(items, ""), items, "no task: the order is kept")


class Query(unittest.TestCase):
    """The node changes what recall prints only through the message's own words."""

    def setUp(self):
        self.p4 = tempfile.mkdtemp(prefix="p4-node-q-")
        rules = [[("ruling", "the quokka harness checks golden images on every push"), ("status", "LIVE"),
                  ("time", "2026-10-01 10:00")],
                 [("ruling", "the narwhal plotter needs cmake presets per machine"), ("status", "LIVE"),
                  ("time", "2026-10-02 10:00")],
                 [("ruling", "golden images of the narwhal plotter live in tests/golden"), ("status", "LIVE"),
                  ("time", "2026-10-03 10:00")]]
        write(os.path.join(self.p4, "recall", "store", "rules.md"), st.render("rules.md", rules))
        self.idx, _ = st.ensure_index(self.p4)

    def tearDown(self):
        shutil.rmtree(self.p4, ignore_errors=True)

    def test_the_node_words_join_the_query_below_the_message(self):
        n = node.Node("kid", own="narwhal plotter presets", up=[("top", "port the narwhal plotter")])
        w = cli.node_weights(self.idx, n, ["golden", "images"])
        self.assertTrue(w and all(v == cli.NODE_WEIGHT for v in w.values()))
        self.assertIn("narwhal", w)
        self.assertNotIn("golden", w, "a word the message has is not added again")
        self.assertEqual(cli.node_weights(self.idx, None, ["golden"]), {})

    def test_no_line_prints_that_the_message_gives_no_reason_for(self):
        n = node.Node("kid", own="narwhal plotter cmake presets")
        r = cli.query(self.p4, "what time is it", None, "2026-11-01 10:00", idx=self.idx, model={}, node=n)
        self.assertEqual(r["lines"], [], "a node never makes an ordinary message print")

    def test_an_entry_used_above_passes_on_one_shared_word(self):
        target = [d["id"] for d in self.idx["docs"] if "tests/golden" in d["show"]][0]
        q = "where do the golden files go"
        plain = cli.query(self.p4, q, None, "2026-11-01 10:00", idx=self.idx, model={})
        used = cli.query(self.p4, q, None, "2026-11-01 10:00", idx=self.idx, model={}, node_ids={target})
        self.assertNotIn(target, plain["ids"])
        self.assertIn(target, used["ids"])
        hidden = cli.query(self.p4, q, None, "2026-11-01 10:00", idx=self.idx, model={}, node_ids={target},
                           hide={target})
        self.assertNotIn(target, hidden["ids"], "a hidden entry never prints")


if __name__ == "__main__":
    unittest.main(verbosity=1)
