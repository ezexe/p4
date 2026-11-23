#!/usr/bin/env python3
"""Tests for digests.py, which writes one corpus entry for each session that is no longer live, and for the corpus's
`digests/` folder in store.py.

Run: python -m pytest tests/p4-phi/test_digests.py

Every test builds its own small store and one session's records in a temp directory.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import p4conf  # noqa: E402
import digests  # noqa: E402
import hook  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import relay  # noqa: E402
import store as st  # noqa: E402

ROOT = os.path.dirname(SRC)
RUN = os.path.join(ROOT, "hooks", "recall-hook.sh")
SID = "sess-narwhal-0001"
TITLE = "Fix the narwhal exporter"
TOKEN = "ghp_" + "a" * 30
REPORT = ("The last row was dropped by an off-by-one in flush_rows.\n\n```\nRAW-TOOL-OUTPUT of the suite\n```\n\n"
          f"The token {TOKEN} was in the log.")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def jsonl(path, items):
    write(path, "".join(json.dumps(r) + "\n" for r in items))


def make(tmp, sid=SID, notes=None, files=None, **session):
    """A store under `tmp` with one session's records, and the store's path."""
    proj = os.path.join(tmp, "proj")
    p4 = os.path.join(proj, ".claude", "p4")
    os.makedirs(p4conf.sub(p4, "store"), exist_ok=True)
    d = relay._dir(p4, sid)
    write(os.path.join(d, "session.json"), json.dumps({
        "sessionId": sid, "title": TITLE, "cwd": proj,
        "task": "Find why the narwhal exporter drops the last row of the ports table", **session}))
    files = files if files is not None else [relay.norm(os.path.join(proj, "src", "flush.py"))]
    jsonl(os.path.join(d, "turns.jsonl"), [{
        "id": "u1", "time": "2026-11-02 10:00", "prompt": "Find why the last row is dropped", "report": REPORT,
        "done": "the suite passes with the last row written", "said": "SAID-ONLY words of the turn",
        "steps": ["edited src/flush.py", "ran `curl -H 'x: SECRETCMD' https://example.test`"],
        "delta": {"files": files, "heads": [f"{relay.norm(proj)}@main 1a2b3c4d"]}}])
    jsonl(os.path.join(d, "notes.jsonl"), notes if notes is not None else [
        {"time": "2026-11-02 09:40", "kind": "code", "source": "src/flush.py:41",
         "claim": "flush_rows stops one row early when the table length is a multiple of the page size"},
        {"time": "2026-11-02 09:50", "kind": "decision", "source": "ezexe's message",
         "claim": "the exporter keeps its page size at 64 rows"},
        {"time": "2026-11-02 09:55", "kind": "decision", "source": "p4-phi, a report-when-done child",
         "claim": "replaces: \"an older child\" (x) as a live session: it finished"}])
    write(os.path.join(d, "plan.json"), json.dumps({"steps": [
        {"addr": "1", "content": "Fix flush_rows", "status": "completed"},
        {"addr": "2", "content": "Add the wombat regression case", "status": "pending"}]}))
    return p4


def mark(p4, sid=SID, **fields):
    path = os.path.join(relay._dir(p4, sid), "session.json")
    write(path, json.dumps({**json.loads(read(path)), **fields}))


def out_path(p4, sid=SID):
    return os.path.join(st.store_dir(p4), st.DIGESTS, sid + ".md")


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(t.cleanup)
        self.tmp = t.name


class Written(Base):
    def test_a_closed_session_gets_one_entry_from_its_records(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        self.assertEqual(digests.sweep(p4, gap=0), [SID])
        es = st.load_file(p4, f"digests/{SID}.md")
        self.assertEqual(len(es), 1)
        e, f = es[0], es[0].fields
        self.assertEqual((e.head, e.value, e.time, f["id"]), ("digest", TITLE, "2026-11-02 10:00", SID))
        self.assertIn("ports table", f["asked"])
        self.assertEqual(f["done"], "the suite passes with the last row written")
        self.assertIn("off-by-one", f["reported"])
        self.assertIn("page size at 64", f["decided"])
        self.assertIn("multiple of the page size; source: src/flush.py:41", f["found"])
        self.assertEqual((f["changed"], f["heads"]), ("src/flush.py", "proj@main 1a2b3c4d"))
        self.assertIn("wombat regression", f["open"])
        self.assertNotIn("Fix flush_rows", f["open"])

    def test_commands_tool_output_secrets_and_another_sessions_note_are_left_out(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        digests.sweep(p4, gap=0)
        text = read(out_path(p4))
        for gone in ("RAW-TOOL-OUTPUT", TOKEN, "SECRETCMD", "SAID-ONLY", "replaces:"):
            self.assertNotIn(gone, text)
        self.assertIn("[redacted]", text)

    def test_a_secret_shaped_string_is_replaced(self):
        for s in (TOKEN, "sk-" + "b" * 24, "AKIA" + "A" * 16, "Authorization: Bearer " + "c" * 24,
                  "API_KEY=" + "d" * 16, "password: '" + "e" * 14 + "'"):
            self.assertNotIn(s[-12:], digests.scrub(f"it read {s} from the file"), s)
        self.assertEqual(digests.scrub("the password prompt was shown"), "the password prompt was shown")

    def test_a_live_session_gets_none(self):
        p4 = make(self.tmp)
        self.assertEqual(digests.sweep(p4, gap=0), [])
        self.assertFalse(os.path.exists(out_path(p4)))

    def test_a_session_closed_long_ago_gets_one(self):
        p4 = make(self.tmp, doneRetired={"time": "2020-01-01 00:00"})
        self.assertEqual(digests.sweep(p4, gap=0), [SID])

    def test_a_session_only_the_app_has_archived_gets_one(self):
        sid = "local_narwhal01"
        p4 = make(self.tmp, sid=sid)
        was = relay.RECORD, relay.ROOTED
        self.addCleanup(lambda: setattr(relay, "RECORD", was[0]) or setattr(relay, "ROOTED", was[1]))
        relay.RECORD = lambda s: {"sessionId": s, "isArchived": True}
        relay.ROOTED = lambda root, s: {"sessionId": s, "isArchived": True}
        self.assertEqual(digests.sweep(p4, gap=0), [sid])

    def test_a_session_with_no_turn_gets_none(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        os.remove(os.path.join(relay._dir(p4, SID), "turns.jsonl"))
        self.assertEqual(digests.sweep(p4, gap=0), [])

    def test_a_digest_as_new_as_its_records_is_not_written_again(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        digests.sweep(p4, gap=0)
        self.assertEqual(digests.sweep(p4, gap=0), [])

    def test_a_session_revived_and_archived_again_is_written_again_in_the_same_file(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        digests.sweep(p4, gap=0)
        turns = os.path.join(relay._dir(p4, SID), "turns.jsonl")
        with open(turns, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"id": "u2", "time": "2026-11-03 09:00", "prompt": "Add the regression case",
                                "report": "The wombat regression case is added and passes."}) + "\n")
        later = time.time() + 5
        os.utime(turns, (later, later))
        mark(p4, archived=False, doneRetired=False)             # revived: a prompt clears both marks
        self.assertEqual(digests.sweep(p4, gap=0), [])
        self.assertIn("2026-11-02 10:00", read(out_path(p4)))
        mark(p4, archived="2026-11-03 09:05")
        self.assertEqual(digests.sweep(p4, gap=0), [SID])
        es = st.load_file(p4, f"digests/{SID}.md")
        self.assertEqual((len(es), es[0].time), (1, "2026-11-03 09:00"))
        self.assertIn("regression case is added", es[0].fields["reported"])
        self.assertEqual(os.listdir(os.path.dirname(out_path(p4))), [SID + ".md"])

    def test_a_session_whose_records_cannot_be_read_stops_no_other(self):
        p4 = make(self.tmp, sid="sess-aardvark-0000", archived="2026-11-02 10:05")
        jsonl(os.path.join(relay._dir(p4, "sess-aardvark-0000"), "turns.jsonl"),
              [{"id": "u1", "time": "2026-11-02 10:00", "report": "It broke.", "delta": "no object"}])
        make(self.tmp, archived="2026-11-02 10:05")
        self.assertEqual(digests.sweep(p4, gap=0), [SID])

    def test_a_digest_a_merge_left_with_two_entries_is_written_again_as_one(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        digests.sweep(p4, gap=0)
        with open(out_path(p4), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n" + st.format_entry([("digest", TITLE), ("time", "2026-11-01 08:00"), ("id", SID)]) + "\n")
        self.assertEqual(len(st.load_file(p4, f"digests/{SID}.md")), 2)
        self.assertEqual(digests.sweep(p4, gap=0), [SID])
        self.assertEqual(len(st.load_file(p4, f"digests/{SID}.md")), 1)

    def test_a_store_is_swept_once_in_the_gap(self):
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        self.assertEqual(digests.sweep(p4), [SID])
        make(self.tmp, sid="sess-wombat-0002", archived="2026-11-02 11:00")
        self.assertEqual(digests.sweep(p4), [])
        self.assertEqual(digests.sweep(p4, gap=0), ["sess-wombat-0002"])

    def test_a_digest_is_never_larger_than_its_bound(self):
        proj = os.path.join(self.tmp, "proj")
        notes = [{"time": "2026-11-02 09:00", "kind": "code", "source": "\U0001d518" * 300,
                  "claim": f"finding {k} " + "\U0001d518" * 600} for k in range(40)]
        files = [relay.norm(os.path.join(proj, "src", f"file_{k}_" + "x" * 150 + ".py")) for k in range(60)]
        p4 = make(self.tmp, notes=notes, files=files, archived="2026-11-02 10:05")
        digests.sweep(p4, gap=0)
        text = read(out_path(p4))
        self.assertLessEqual(len(text.encode("utf-8")), digests.DIGEST_BYTES)
        self.assertLessEqual(text.count("\n"), 200)
        self.assertEqual(len(st.load_file(p4, f"digests/{SID}.md")), 1)


class Index(Base):
    def setUp(self):
        super().setUp()
        self.p4 = make(self.tmp, archived="2026-11-02 10:05")
        digests.sweep(self.p4, gap=0)

    def doc(self):
        got = [d for d in st.build_index(self.p4, write=False)["docs"] if d["file"] == st.DIGESTS]
        self.assertEqual(len(got), 1)
        return got[0]

    def test_the_index_holds_one_document_for_it(self):
        d = self.doc()
        self.assertEqual((d["kind"], d["state"], d["time"], d["path"]),
                         ("archived session", "LIVE", "2026-11-02 10:00", f"phi/store/digests/{SID}.md"))
        self.assertTrue(d["id"].startswith(f"digests/{SID}.md:2026-11-02 10:00:"), d["id"])
        self.assertTrue(d["show"].startswith(f"\"{TITLE}\" was asked: "), d["show"])
        self.assertNotIn("fkind", d)

    def test_no_retraction_frees_it(self):
        write(os.path.join(st.store_dir(self.p4), "retractions.md"), st.render("retractions.md", [
            [("freed", TITLE), ("time", "2026-11-03 00:00"), ("cause", "superseded")]]))
        self.assertEqual(self.doc()["state"], "LIVE")

    def test_its_line_names_an_archived_session_and_the_default_gate_holds_it_back(self):
        line = cli.entry_line(self.doc())
        self.assertRegex(line, r"^- 2026-11-02 archived session: \"Fix the narwhal exporter\" was asked: ")
        self.assertTrue(line.endswith(f"(phi/store/digests/{SID}.md:5)"), line)
        self.assertIsNone(hook.RULES_FACTS.match(line))

    def test_a_message_on_its_subject_has_it_among_the_candidates(self):
        idx, _ = st.ensure_index(self.p4)
        terms = ranker.tokens("why does flush_rows stop one row early at a multiple of the page size")
        ids = {idx["docs"][i]["id"] for i in cli.bm25_scores(idx, terms, {})}
        self.assertTrue(any(i.startswith(f"digests/{SID}.md:") for i in ids), ids)


class AtStop(Base):
    def test_the_stop_entry_writes_it_with_learning_off(self):
        """The `train` entry as Claude Code runs it at Stop, through recall-hook.sh, with recall.learn false: the
        sweep runs before that gate, since a digest is corpus and no model."""
        p4 = make(self.tmp, archived="2026-11-02 10:05")
        proj = os.path.dirname(os.path.dirname(p4))
        write(os.path.join(p4, "p4.json"), json.dumps({"recall": {"learn": False}}))
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj})
        r = subprocess.run(["sh", RUN, "train"], input=json.dumps({"session_id": "s1", "cwd": proj}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr[-800:])
        self.assertTrue(os.path.isfile(out_path(p4)))


if __name__ == "__main__":
    unittest.main()
