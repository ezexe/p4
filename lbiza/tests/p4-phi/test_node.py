#!/usr/bin/env python3
"""node.py: the content words two texts share, which order the notes and the siblings' tasks of a session's start, and the node a session is: its level and its address.

    python -m pytest tests/p4-phi/test_node.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "plugins" / "p4-phi" / "scripts"
sys.path.insert(0, str(SRC))
import node  # noqa: E402
import relay  # noqa: E402


class Overlap(unittest.TestCase):
    def test_items_nearest_the_task_come_first_and_ties_keep_their_order(self):
        items = ["the build cache lives in out/", "golden images of the plotter", "plotter presets per machine"]
        self.assertEqual(node.by_overlap(items, "fix the plotter presets"),
                         ["plotter presets per machine", "golden images of the plotter", "the build cache lives in out/"])
        self.assertEqual(node.by_overlap(items, ""), items, "no task: the order is kept")

    def test_a_key_reads_the_text_of_an_item_and_the_words_leave_the_common_ones_out(self):
        items = [{"t": "golden images"}, {"t": "the plotter presets"}]
        self.assertEqual(node.by_overlap(items, "plotter presets", key=lambda x: x["t"]), [items[1], items[0]])
        self.assertEqual(node.words("The plotter and the presets"), {"plotter", "presets"})


def put(home, sid, name, data, lines=False):
    folder = os.path.join(home, "phi", "sessions", sid)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(x) + "\n" for x in data) if lines else json.dumps(data))


def rec(sid, above="", **more):
    return {"sessionId": sid, **({"spawnedFrom": {"sessionId": above}} if above else {}), **more}


class Address(unittest.TestCase):
    """A session's address is that of the store that holds its folder: "1" for the root, and one more place for
    each step of `.claude` folders and a `p4` under it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = self._tmp.name

    def claim(self, sid, above, store=None):
        return relay.claim(self.home, store or self.home, sid, "session", above)

    def test_parent_and_child_give_the_first_five_addresses_of_ezexe_phis_tree(self):
        self.assertEqual([node.child("1", 1), node.child("1", 2), node.child("1", 3), node.child("101", 1)],
                         ["101", "1001", "10001", "10101"])
        self.assertEqual([node.parent(a) for a in ("1", "101", "1001", "10001", "10101")],
                         [None, "1", "1", "1", "101"])

    def test_the_address_of_a_session_is_its_stores(self):
        sessions = {"top": rec("top"), "a": rec("a", "top"), "b": rec("b", "top"), "aa": rec("aa", "a"),
                    "old": rec("old", "top")}
        a = self.claim("a", "top")
        self.claim("b", "top")
        self.claim("aa", "a", a)
        self.assertEqual(node.addresses(self.home, sessions),
                         {"top": "1", "a": "101", "b": "1001", "aa": "10101", "old": "1"},
                         "a flat session is 1, the first two children 101 and 1001, the first child of the first 10101")
        self.assertEqual(node.place_of(self.home, self.home), ("1", []))
        deep = os.path.join(self.home, ".claude", ".claude", "p4", ".claude", "p4")
        self.assertEqual(node.place_of(self.home, deep), ("100101", [2, 1]))

    def test_two_tops_of_one_store_are_each_1(self):
        found = node.addresses(self.home, {"a": rec("a"), "b": rec("b"), "c": rec("c", "gone")})
        self.assertEqual(found, {"a": "1", "b": "1", "c": "1"})

    def test_no_address_of_a_tree_of_30_sessions_holds_11(self):
        sessions, stores = {"s0": rec("s0")}, {"s0": self.home}
        for k in range(1, 30):
            above = f"s{(k - 1) // 3}"                                   # three under each
            sessions[f"s{k}"] = rec(f"s{k}", above)
            stores[f"s{k}"] = self.claim(f"s{k}", above, stores[above])
        found = node.addresses(self.home, sessions)
        self.assertEqual(len(found), 30)
        self.assertEqual(found["s0"], "1")
        for sid, a in found.items():
            self.assertNotIn("11", a, sid)
            if a != "1":
                self.assertEqual(node.parent(a), found[sessions[sid]["spawnedFrom"]["sessionId"]])

    def test_an_address_longer_than_32_characters_prints_as_1_and_its_places_and_record_holds_places(self):
        self.assertEqual(node.short("101", [1]), "101")
        self.assertEqual(node.short("1" + "0" * 40 + "1", [41]), "1/41")
        sessions = {"top": rec("top"), "x": rec("x", "top"),
                    "kid": rec("kid", "top", task="Fix the port", shard=["a.py"]),
                    "grand": rec("grand", "kid", fileSet=["b.py"])}
        self.claim("x", "top")
        kid = self.claim("kid", "top")
        self.claim("grand", "kid", kid)
        r = node.record(self.home, "grand", sessions)
        self.assertEqual((r["address"], r["places"], r["paths"], r["parent"]), ("100101", [2, 1], ["b.py"], "kid"))
        self.assertEqual(node.record(self.home, "kid", sessions)["paths"], ["a.py"], "shard before fileSet")
        self.assertEqual(sorted(r), ["address", "id", "leaves", "level", "parent", "paths", "places", "title"])


class Level(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = self._tmp.name

    def test_a_session_whose_parent_has_no_record_is_a_top_1_and_an_orchestrator(self):
        sessions = {"lost": rec("lost", "nobody")}
        self.assertTrue(node.top(sessions["lost"], sessions))
        self.assertEqual(node.level(sessions["lost"], sessions), "orchestrator")
        r = node.record(self.home, "lost", sessions)
        self.assertEqual((r["address"], r["parent"]), ("1", ""))

    def test_level_gives_each_of_the_three(self):
        sessions = {"top": rec("top"), "ctl": rec("ctl", controls=[{"sessionId": "w"}]),
                    "stand": rec("stand", standingWorker="w"), "mid": rec("mid", "top"), "leaf": rec("leaf", "mid"),
                    "coworker": rec("coworker", "mid", standingKind="coworker")}
        got = {k: node.level(v, sessions) for k, v in sessions.items()}
        self.assertEqual(got, {"top": "orchestrator", "ctl": "puppeteer", "stand": "puppeteer", "mid": "orchestrator",
                               "leaf": "worker", "coworker": "worker"})

    def test_level_needs_no_module_but_node_py(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, sys.argv[1]); sys.modules['controls'] = None; import node; "
                "s = {'a': {'sessionId': 'a', 'controls': [{'sessionId': 'b'}]}}; print(node.level(s['a'], s))")
        r = subprocess.run([sys.executable, "-I", "-c", code, str(SRC)], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "puppeteer", r.stderr)

    def test_leaves_give_a_subagent_a_teammate_a_terminal_and_the_claimed_reader_and_worker_with_addresses(self):
        put(self.home, "s", "plan.json", {"steps": [{"addr": "1", "tasks": [
            {"id": "a1", "tool": "Agent", "agent": True, "status": "open", "stepText": "Read the port"},
            {"id": "t1", "tool": "Bash", "status": "open"}]}], "loose": [
            {"id": "a2", "tool": "Agent", "agent": True, "status": "done", "stepText": ""}]})
        put(self.home, "s", "team.json", {"teammates": [{"name": "fences", "task": "x", "state": "idle", "doing": ""}]})
        put(self.home, "s", "upkeep.json", {"terminals": [{"name": "upkeep-1", "main": "E:/r", "time": "t", "text": ""},
                                                          {"name": "upkeep-2", "removed": True}]})
        worker = relay.claim(self.home, self.home, "tw-x", "worker", "s", ["8"])
        relay.claim(self.home, self.home, "cw-z", "reader", "s", ["1"], session="5e55-1")
        relay.claim(self.home, self.home, "s2", "session", "s")
        relay.claim(self.home, self.home, "tw-other", "worker", "t", ["9"])
        got = [(x["level"], x["name"], x["state"], x.get("address")) for x in node.leaves(self.home, "s")]
        self.assertEqual(got, [
            ("subagent", "Read the port", "open", None), ("subagent", "a2", "done", None),
            ("teammate", "fences", "idle", None), ("terminal", "upkeep-1", "started", None),
            ("terminal", "upkeep-2", "removed", None), ("terminal", "tw-x", "started", "101"),
            ("terminal", "cw-z", "started", "1001")], "a session's node and another's worker are no leaves of it")
        with open(os.path.join(worker, "phi", "report-tw-x.md"), "w", encoding="utf-8") as f:
            f.write("done\n")
        self.assertEqual([x["state"] for x in node.leaves(self.home, "s") if x["name"] == "tw-x"], ["reported"])
        self.assertEqual(node.leaves(self.home, "none"), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
