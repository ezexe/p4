#!/usr/bin/env python3
"""said.py: a session states what it did with the store's lines it was shown.

    python3 -I lbiza/plugins/p4-phi/scripts/test_said.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hook  # noqa: E402
import labels as lb  # noqa: E402
import p4conf  # noqa: E402
import said  # noqa: E402
import store as st  # noqa: E402

RULES = """ezexe's rulings: what holds past the turn, in ezexe's own words.
Written when ezexe rules.
Fields: ruling, owner-words, scope, form, status, time, pinned, plain; from (migrated entries).

- ruling: the narwhal port stays open across zebrafish plots and closes only at exit
  owner-words: "keep the narwhal port open"
  status: LIVE
  time: 2026-11-01 10:00
  plain: keep the narwhal port open across zebrafish plots; close it only at exit

- ruling: the quokka cache is rebuilt before every wombat release, never patched in place
  owner-words: "rebuild the quokka cache"
  status: LIVE
  time: 2026-11-02 10:00
  plain: rebuild the quokka cache before every wombat release
"""
SESSION = "abcdef12-3456-7890-abcd-ef1234567890"
PROMPT = "should the narwhal port close between zebrafish plots or stay open"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class Said(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(os.path.realpath(self.tmp.name), "proj")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(p4conf.sub(self.p4, "models"))
        write(p4conf.sub(self.p4, "store", "rules.md"), RULES)
        os.makedirs(p4conf.sub(self.p4, "store", "messages"))
        self.env = dict(os.environ)
        os.environ["CLAUDE_PROJECT_DIR"] = self.proj
        os.environ.pop("P4_RECALL_INJECT", None)
        st.build_index(self.p4)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def set_mode(self, mode):
        cfg = p4conf.load(self.p4)
        cfg["recall"]["said"] = {"mode": mode}
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def recall(self):
        out = hook.h_recall({"prompt": PROMPT, "session_id": SESSION, "cwd": self.proj})
        return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")

    def test_off_is_recall_as_it_was(self):
        text = self.recall()
        self.assertIn("rule: keep the narwhal port open", text)
        self.assertNotIn("[r1]", text)
        self.assertNotIn("said", text)
        self.assertEqual(lb.read_served(self.p4, f"turn-{SESSION}")["handles"], {})
        self.assertFalse(os.path.exists(said.path(self.p4)), "nothing asked, nothing written")
        self.assertEqual(said.stats_line(self.p4), "")

    def test_shadow_tags_asks_and_records_without_training(self):
        self.set_mode("shadow")
        text = self.recall()
        first = text.splitlines()[0]
        self.assertRegex(first, r"^- \[r1\] \S+ rule: keep the narwhal port open")
        self.assertIn("where SAID is: ", text)
        self.assertIn("said --session " + SESSION, text)
        words = text.split("If a line above")[1]
        for p in (self.p4.replace("\\", "/"), HERE.replace("\\", "/")):     # the paths are as long as the install's (T1)
            words = words.replace(p, "")
        self.assertLess(len(words), 500, "the instruction stays short: the command once")
        self.assertIn("SAID applied r1", text)
        self.assertIn("--p4 " + self.p4.replace("\\", "/"), text, "the command names the store, so any folder will do")
        self.assertNotIn("\\", text.split("If a line above")[1], "forward slashes: Bash and PowerShell both take it")
        served = lb.read_served(self.p4, f"turn-{SESSION}")
        rule_id = served["handles"]["r1"]
        self.assertTrue(rule_id.startswith("rules.md:2026-11-01 10:00:"))
        cmd = [sys.executable, "-I", os.path.join(HERE, "p4.py"), "said", "--session", SESSION, "--p4", self.p4]
        r = subprocess.run(cmd + ["applied", "r1"], capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "said: noted"), r.stderr)
        r = subprocess.run(cmd + ["set-aside", "r9", "--why", "not this turn"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no line with the handle r9 was shown this turn (shown: r1", r.stdout)
        r = subprocess.run(cmd + ["lacked", "--why", "which   plotter the port serves"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = lb.read_tsv(said.path(self.p4))
        self.assertEqual([x["act"] for x in rows], ["asked", "applied", "lacked"])
        self.assertEqual((rows[1]["entry"], rows[1]["task"]), (rule_id, served["task"]))
        self.assertEqual(rows[2]["note"], "which plotter the port serves")
        lab = [x for x in lb.read_tsv(lb.mpath(self.p4, lb.TRAIN)) if x["source"] == "said"]
        self.assertEqual([(x["entry"], x["label"], x["note"]) for x in lab], [(rule_id, "1", "applied")])
        self.assertEqual([x for x in lb.training_labels(self.p4) if x["source"] == "said"], [], "shadow: nothing trains on it")
        self.assertEqual(said.stats(self.p4), {"asked": 1, "stated": 1, "applied": 1, "set-aside": 0, "lacked": 1})
        self.assertIn("said (shadow): asked on 1 turns, stated on 1", said.stats_line(self.p4))
        self.set_mode("on")
        got = [x for x in lb.training_labels(self.p4) if x["source"] == "said"]
        self.assertEqual([(x["entry"], x["label"], x["weight"]) for x in got], [(rule_id, 1, 1.0)], "on: it is a label")

    def test_set_aside_is_a_negative_and_needs_no_reason(self):
        self.set_mode("shadow")
        self.recall()
        lines, code = said.state(self.p4, SESSION, "set-aside", ["r1"], "the port is already shut")
        self.assertEqual(code, 0, lines)
        lab = [x for x in lb.read_tsv(lb.mpath(self.p4, lb.TRAIN)) if x["source"] == "said"]
        self.assertEqual((lab[0]["label"], lab[0]["note"]), ("0", "set-aside: the port is already shut"))
        self.assertEqual(said.state(self.p4, SESSION, "applied", [], "")[1], 2, "a handle is needed")
        self.assertEqual(said.state(self.p4, SESSION, "lacked", [], "")[1], 2, "what was missing is needed")
        self.assertEqual(said.state(self.p4, "another-session", "applied", ["r1"], "")[1], 2, "another session's turn showed nothing")

    def test_tag_leaves_other_lines_alone(self):
        lines, handles = said.tag([("- file: src/a.py", "repo:src/a.py"), ("- 2026-11-01 rule: x (store/rules.md:5)", "rules.md:2026-11-01 10:00:ab"),
                                   ("an earlier reading", "history:tok"), ("- 2026-11-02 fact: y (store/facts.md:3)", "facts.md:2026-11-02 10:00:cd")])
        self.assertEqual(lines, ["- file: src/a.py", "- [r1] 2026-11-01 rule: x (store/rules.md:5)", "an earlier reading",
                                 "- [r2] 2026-11-02 fact: y (store/facts.md:3)"])
        self.assertEqual(handles, {"r1": "rules.md:2026-11-01 10:00:ab", "r2": "facts.md:2026-11-02 10:00:cd"})


if __name__ == "__main__":
    unittest.main()
