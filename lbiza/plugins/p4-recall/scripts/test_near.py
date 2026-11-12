#!/usr/bin/env python3
"""near.py: a task's candidates include what earlier, similar tasks of other sessions used.

    python3 -I lbiza/plugins/p4-recall/scripts/test_near.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import near  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import repo  # noqa: E402
import store as st  # noqa: E402
import train  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_COMMITTER_DATE": "2026-10-30T10:00:00"}   # before every task:
# an entry dated after a task could not have been shown to it
# files whose names and symbols share no word with the prompts that use them
FILES = {"src/kelp/anchor.py": "def moor_line():\n    return 1\n", "src/kelp/buoy.py": "def float_marker():\n    return 2\n",
         "src/reef/polyp.py": "def bud_colony():\n    return 3\n", "docs/tide.md": "# Tide tables\n\nWhen the water turns.\n"}
TASKS = [  # (id, session, time, prompt, positives)
    ("t1", "aaaaaaaa", "2026-11-01 10:00", "the toolbar latency readout flickers when the transport starts", ["repo:src/kelp/anchor.py"]),
    ("t2", "aaaaaaaa", "2026-11-01 10:10", "the toolbar latency readout still flickers on transport stop", ["repo:src/kelp/buoy.py"]),
    ("t3", "bbbbbbbb", "2026-11-02 09:00", "ship the crash dump symbols with the installer", ["repo:src/reef/polyp.py"]),
    ("t4", "cccccccc", "2026-11-03 09:00", "why does the toolbar latency readout flicker after the transport restarts", ["repo:src/kelp/anchor.py"]),
]


def sh(cwd, *a):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise AssertionError(f"{a}: {r.stderr or r.stdout}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class Near(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(os.path.realpath(self.tmp.name), "proj")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(p4conf.sub(self.p4, "models"))
        os.makedirs(p4conf.sub(self.p4, "store"))
        write(os.path.join(self.proj, ".gitignore"), ".claude/\n")
        for rel, text in FILES.items():
            write(os.path.join(self.proj, rel), text)
        sh(self.proj, "git", "init", "-q")
        sh(self.proj, "git", "add", "-A")
        sh(self.proj, "git", "commit", "-q", "-m", "seed", "--date", "2026-10-30T10:00:00")
        lb.add_tasks(self.p4, [{"id": i, "session": s, "time": t, "text": text, "kind": "new"} for i, s, t, text, _ in TASKS])
        lb.write_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD, [
            {"task": i, "entry": e, "label": "1", "source": "repo", "weight": "1.0", "time": t, "teacher": "", "edited": "",
             "note": "edited"} for i, _s, t, _text, pos in TASKS for e in pos])
        repo.build(self.p4, self.proj)
        self.idx = st.build_index(self.p4)
        near.ON, near.NEIGHBOURS, near.MAX, near.SAME_SESSION = True, 20, 100, False
        self.mem = near.build(self.p4, self.idx)

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_is_written_and_read_back(self):
        with open(near.path(self.p4), encoding="utf-8") as f:
            disk = json.load(f)
        self.assertEqual([r[0] for r in disk["tasks"]], [t[2] for t in TASKS], "oldest first")
        self.assertEqual(disk["tasks"][0][1], "aaaaaaaa")
        self.assertEqual(near.load(self.p4)["rows"], self.mem["rows"])
        os.remove(near.path(self.p4))
        self.assertIsNone(near.load(self.p4), "no round yet: no memory, and a query builds none")

    def test_entries_come_from_earlier_tasks_of_other_sessions(self):
        text, when = TASKS[3][3], TASKS[3][2]
        got = near.entries(self.mem, text, when, "cccccccc")
        self.assertEqual(set(got), {"repo:src/kelp/anchor.py", "repo:src/kelp/buoy.py"}, "what the two flicker tasks used")
        self.assertNotIn("repo:src/reef/polyp.py", got, "the crash dump task shares no word")
        self.assertEqual(near.entries(self.mem, TASKS[1][3], TASKS[1][2], "aaaaaaaa"), {},
                         "t2's only earlier neighbour is its own session's t1: already in that session's context")
        self.assertEqual(set(near.entries(self.mem, TASKS[1][3], TASKS[1][2], "aaaaaaaa", same_session=True)),
                         {"repo:src/kelp/anchor.py"})
        self.assertEqual(near.entries(self.mem, TASKS[0][3], TASKS[0][2], "zzzzzzzz"), {}, "nothing is dated before the first task")
        self.assertEqual(len(near.entries(self.mem, text)), 2, "with no time given, every task counts (a live query)")

    def test_training_draws_them_and_marks_them(self):
        task = lb.read_tasks(self.p4)["t4"]
        pos = {"repo:src/kelp/anchor.py": 1.0}
        xs, ys, cand, _ = train.task_examples(self.idx, task, pos)
        self.assertEqual(sum(ys), 0, "BM25 over the prompt never draws the file: no word in common")
        extra = {"near": self.mem, "id_at": near.id_index(self.idx["docs"])}
        xs, ys, cand2, sc = train.task_examples(self.idx, task, pos, docs_by=extra)
        self.assertEqual(sum(ys), 1, "the earlier flicker task of another session brings it in")
        k = ys.index(1)
        self.assertEqual(xs[k][ranker.h("near-hit")], 1.0)
        self.assertGreater(xs[k][ranker.h("near")], 0)
        self.assertEqual(sc[k], 0.0, "and its BM25 score is what it is: nothing")
        self.assertEqual(cand2[:len(cand)], cand, "BM25's candidates first, unchanged")
        sets = train.build_sets(self.p4, self.idx)
        by = {s["task"]: s for s in sets}
        self.assertFalse(by["t4"]["missed"])
        self.assertTrue(by["t1"]["missed"], "the first task has nothing earlier to draw on")
        near.ON = False
        self.assertTrue({s["task"]: s for s in train.build_sets(self.p4, self.idx)}["t4"]["missed"], "off: as before")

    def test_a_query_uses_it_only_with_a_model_trained_on_it(self):
        docs = self.idx["docs"]
        cand, feats = cli.near_candidates(self.p4, {"features": ["base"]}, docs, [0], TASKS[3][3], "cccccccc", set())
        self.assertEqual((cand, feats), ([0], None), "a model without the feature never sees a near candidate")
        cand, feats = cli.near_candidates(self.p4, {"features": ["base", "near"]}, docs, [], TASKS[3][3], "dddddddd", set())
        got = {docs[i]["id"] for i in cand}
        self.assertEqual(got, {"repo:src/kelp/anchor.py", "repo:src/kelp/buoy.py"})
        self.assertEqual(set(feats), {0, 1})
        gone = {"repo:src/kelp/anchor.py"}
        cand, _ = cli.near_candidates(self.p4, {"features": ["near"]}, docs, [], TASKS[3][3], "dddddddd", gone)
        self.assertEqual({docs[i]["id"] for i in cand}, {"repo:src/kelp/buoy.py"}, "a superseded entry is never brought back")
        w = {str(ranker.h("near-hit")): 9.0, str(ranker.h("bias")): -4.0}
        model = {"w": {int(k): v for k, v in w.items()}, "threshold": 0.5, "features": ["base", "near"], "per_file": 2}
        ids = cli.rank(self.p4, TASKS[3][3], idx=self.idx, model=model, k=2)
        self.assertEqual(set(ids), {"repo:src/kelp/anchor.py", "repo:src/kelp/buoy.py"}, "ranked from the near candidates")

    def test_extend_caps_and_ranks(self):
        docs = self.idx["docs"]
        id_at = near.id_index(docs)
        got = {"repo:src/kelp/anchor.py": 2.0, "repo:src/kelp/buoy.py": 1.0, "repo:gone.py": 5.0}
        near.MAX = 1
        cand, feats = near.extend(docs, id_at, [id_at["repo:docs/tide.md"]], got, lambda i: True)
        self.assertEqual([docs[i]["id"] for i in cand], ["repo:docs/tide.md", "repo:src/kelp/anchor.py"], "the best one the index holds")
        self.assertEqual(feats, {1: (2.0 / 5.0, 1.0 / 2)}, "a plain dict of scores carries no likeness")
        got = near.entries(self.mem, TASKS[3][3], TASKS[3][2], "cccccccc")
        self.assertTrue(all(0 < v <= 1 for v in got.like.values()) and set(got.like) == set(got))
        far = near.entries(self.mem, "the readout of something else entirely, unrelated words here", TASKS[3][2], "cccccccc")
        self.assertLess(max(far.like.values()), min(got.like.values()), "a faint likeness reads as one")


if __name__ == "__main__":
    unittest.main()
