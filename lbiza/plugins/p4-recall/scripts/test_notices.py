#!/usr/bin/env python3
"""notices.py: a failing hook or an unreadable ranker leaves one retrain notice a day per component, and an
answered notice is no longer open."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hook  # noqa: E402
import notices  # noqa: E402
import p4 as cli  # noqa: E402
import store as st  # noqa: E402


class Notices(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.p4 = os.path.join(self.root, ".claude", "p4")
        os.makedirs(os.path.join(self.p4, "store"))
        os.makedirs(os.path.join(self.p4, "models"))

    def test_notify_once_a_day_per_component_and_kind(self):
        self.assertTrue(notices.notify(self.p4, "json ranker", ValueError("bad file"), "abcd1234efgh", now="2026-11-09 10:00"))
        self.assertFalse(notices.notify(self.p4, "json ranker", ValueError("bad file again"), "abcd1234", now="2026-11-09 11:00"))
        self.assertTrue(notices.notify(self.p4, "json ranker", KeyError("w"), "abcd1234", now="2026-11-09 11:00"))
        self.assertTrue(notices.notify(self.p4, "json ranker", ValueError("bad file"), "abcd1234", now="2026-11-10 09:00"))
        rows = notices.open_notices(self.p4)
        self.assertEqual([(r["time"], r["kind"], r["session"]) for r in rows],
                         [("2026-11-09 10:00", "ValueError", "abcd1234"), ("2026-11-09 11:00", "KeyError", "abcd1234"),
                          ("2026-11-10 09:00", "ValueError", "abcd1234")])
        self.assertEqual(rows[0]["error"], "bad file")
        text = open(notices.path(self.p4), encoding="utf-8").read()
        self.assertTrue(text.startswith("# p4-recall retrain notices"))
        self.assertEqual(text.count("\n"), 4)

    def test_resolved_rows_close_notices_without_rewriting_them(self):
        notices.notify(self.p4, "pt ranker", RuntimeError("no chain"), "s1", now="2026-11-09 10:00")
        before = open(notices.path(self.p4), encoding="utf-8").read()
        with open(notices.path(self.p4, notices.RESOLVED), "a", encoding="utf-8", newline="\n") as f:
            f.write("2026-11-09 10:00\t0\ts1\tpt ranker\tRuntimeError\tno chain\tretrained 2026-11-09 12:00\n")
        self.assertEqual(notices.open_notices(self.p4), [])
        self.assertEqual(open(notices.path(self.p4), encoding="utf-8").read(), before)
        self.assertEqual([notices.notice_family(c) for c in ("json ranker", "pt ranker", "ranker server", "hook close", "train")],
                         ["json", "ranker", "ranker", "hook", "train"])

    def test_a_hook_that_raises_leaves_a_notice_and_still_exits_clean(self):
        payload = json.dumps({"cwd": self.root, "session_id": "deadbeefcafe", "prompt": "hello"})
        with mock.patch.dict(hook.HANDLERS, {"recall": mock.Mock(side_effect=RuntimeError("boom"))}), \
                mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(hook.main(["recall"]), 0)
        self.assertIn("RuntimeError", out.getvalue())
        rows = notices.open_notices(self.p4)
        self.assertEqual([(r["component"], r["kind"], r["session"]) for r in rows], [("hook recall", "RuntimeError", "deadbeef")])

    def test_an_unreadable_ranker_file_leaves_a_notice_and_the_query_falls_back(self):
        with open(os.path.join(self.p4, "store", "rules.md"), "w", encoding="utf-8") as f:
            f.write("The owner's rulings.\nWritten when the owner rules.\nFields: ruling, status, time.\n\n"
                    "- ruling: the ring buffer drains on the audio thread\n  status: LIVE\n  time: 2026-11-01 10:00\n")
        with open(os.path.join(self.p4, "models", "ranker.json"), "w", encoding="utf-8") as f:
            f.write("<<<<<<< HEAD\n{")
        idx = st.build_index(self.p4)
        r = cli.query(self.p4, "where does the ring buffer drain?", "deadbeef", idx=idx)
        self.assertIn("bm25", r["road"])
        rows = notices.open_notices(self.p4)
        self.assertEqual([(r["component"], r["kind"]) for r in rows], [("json ranker", "ValueError")])
        cli.query(self.p4, "where does the ring buffer drain?", "deadbeef", idx=idx)
        self.assertEqual(len(notices.open_notices(self.p4)), 1)                  # once a day


if __name__ == "__main__":
    unittest.main(verbosity=1)
