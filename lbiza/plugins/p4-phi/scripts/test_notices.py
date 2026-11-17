#!/usr/bin/env python3
"""notices.py: a failing hook or an unreadable ranker file leaves one retrain notice a day per component and kind,
and a row of retrain-resolved.tsv closes the notice it answers."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import hook  # noqa: E402
import notices  # noqa: E402
import p4 as cli  # noqa: E402
import store as st  # noqa: E402


class Notices(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.p4 = os.path.join(self.root, ".claude", "p4")
        os.makedirs(p4conf.sub(self.p4, "store"))
        os.makedirs(p4conf.sub(self.p4, "models"))

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
        self.assertTrue(text.startswith("# p4-phi retrain notices"))
        self.assertEqual(text.count("\n"), 4)

    def test_resolved_rows_close_notices_without_rewriting_them(self):
        notices.notify(self.p4, "pt ranker", RuntimeError("no chain"), "s1", now="2026-11-09 10:00")
        before = open(notices.path(self.p4), encoding="utf-8").read()
        with open(notices.path(self.p4, notices.RESOLVED), "a", encoding="utf-8", newline="\n") as f:
            f.write("2026-11-09 10:00\t0\ts1\tpt ranker\tRuntimeError\tno chain\tretrained 2026-11-09 12:00\n")
        self.assertEqual(notices.open_notices(self.p4), [])
        self.assertEqual(open(notices.path(self.p4), encoding="utf-8").read(), before)
        self.assertEqual([notices.notice_family(c) for c in ("json ranker", "pt ranker", "ranker server", "hook close", "train")],
                         ["json", "ranker", "ranker", "release", "train"])

    def test_a_hook_notice_is_answered_by_a_later_release(self):
        """A hook's notice, on a store with nothing to train, is of the family "release": the release that wrote it
        leaves it open, and the next release of p4-phi answers it with a row of retrain-resolved.tsv. A notice no
        release can answer, an unreadable ranker, stays open across releases."""
        with mock.patch.object(notices, "plugin_version", return_value="0.11.5"):
            self.assertTrue(notices.notify(self.p4, "hook stop", RuntimeError("boom"), "abcd1234", now="2026-11-09 10:00"))
            self.assertTrue(notices.notify(self.p4, "json ranker", ValueError("bad file"), "abcd1234", now="2026-11-09 10:00"))
            self.assertEqual(notices.notice_family("hook stop"), "release")
            self.assertEqual([r["component"] for r in notices.open_notices(self.p4)], ["hook stop", "json ranker"])
        with mock.patch.object(notices, "plugin_version", return_value="0.11.6"):
            self.assertEqual([r["component"] for r in notices.open_notices(self.p4)], ["json ranker"])
            self.assertEqual([r["component"] for r in notices.open_notices(self.p4)], ["json ranker"])
        with open(notices.path(self.p4, notices.RESOLVED), encoding="utf-8") as f:
            answers = [l.rstrip("\n").split("\t") for l in f if l.strip() and not l.startswith("#")]
        self.assertEqual([(a[3], a[4], a[6]) for a in answers], [("hook stop", "RuntimeError", "released p4-phi 0.11.6")])

    def test_an_answer_closes_only_the_notice_of_its_kind(self):
        """Two notices of one minute and one component, each with a plain-string error and so an empty error field,
        differ only in kind: a resolved row answers the one of its kind and leaves the other open."""
        self.assertTrue(notices.notify(self.p4, "hook stop", "timeout", "abcd1234", now="2026-11-09 10:00"))
        self.assertTrue(notices.notify(self.p4, "hook stop", "missing store", "abcd1234", now="2026-11-09 10:00"))
        first = notices.open_notices(self.p4)[0]
        with open(notices.path(self.p4, notices.RESOLVED), "a", encoding="utf-8", newline="\n") as f:
            f.write("\t".join([first["time"], f"{first['epoch']:.6f}", first["session"], first["component"],
                               first["kind"], first["error"], "retrained 2026-11-09 11:00"]) + "\n")
        self.assertEqual([r["kind"] for r in notices.open_notices(self.p4)], ["missing store"])

    def test_a_hook_that_raises_leaves_a_notice_and_still_exits_clean(self):
        payload = json.dumps({"cwd": self.root, "session_id": "deadbeefcafe", "prompt": "hello"})
        with mock.patch.dict(hook.HANDLERS, {"recall": mock.Mock(side_effect=RuntimeError("boom"))}), \
                mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(hook.main(["recall"]), 0)
        self.assertIn("RuntimeError", out.getvalue())
        rows = notices.open_notices(self.p4)
        self.assertEqual([(r["component"], r["kind"], r["session"]) for r in rows], [("hook recall", "RuntimeError", "deadbeef")])

    def test_an_unreadable_ranker_file_leaves_a_notice_and_the_query_falls_back(self):
        with open(p4conf.sub(self.p4, "store", "rules.md"), "w", encoding="utf-8") as f:
            f.write("ezexe's rulings.\nWritten when ezexe rules.\nFields: ruling, status, time.\n\n"
                    "- ruling: the ring buffer drains on the audio thread\n  status: LIVE\n  time: 2026-11-01 10:00\n")
        with open(p4conf.sub(self.p4, "models", "ranker.json"), "w", encoding="utf-8") as f:
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
