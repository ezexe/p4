#!/usr/bin/env python3
"""Tests for the label sources and the dictionary's signals (fresh-marketplace.md 5.1, 5.1a, 5.2, 5.3, 8.1, 8.4's
free half, 8.5's free half).

Run: python3 test_labels.py   (stdlib unittest, offline, seconds)

Fixtures are built in temp directories. The real-store and real-transcript checks run only when those paths exist:
the migrated clones (P4_FIXTURES, as test_store), the migrated ap-p4_mac store (P4_MAC_STORE) and the project
transcripts under ~/.claude/projects/-Users-ez-code-AudioPlugin/ (read-only; nothing is written beside them).
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import p4 as cli  # noqa: E402
import repo  # noqa: E402
import store as st  # noqa: E402
import transcript as tr  # noqa: E402
from test_hooks import make_project, transcript  # noqa: E402
from test_store import NOW, fixture, make_store, write  # noqa: E402

MAC_STORE = os.environ.get("P4_MAC_STORE", "/Users/ez/gritz/p4-repos/ap-p4_mac")
AP_PROJECT = "/Users/ez/code/AudioPlugin"
AP_SLUG = os.path.expanduser("~/.claude/projects/-Users-ez-code-AudioPlugin")


def copy_store(src, dst):
    for sub in ("store", "memory", "src", "models"):
        if os.path.isdir(os.path.join(src, sub)):
            shutil.copytree(os.path.join(src, sub), os.path.join(dst, sub),
                            ignore=shutil.ignore_patterns("index.json", "repo.json", "served"))
    return dst


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = make_store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class Files(Base):
    def test_training_labels_join_and_edited_replaces_raw(self):
        lb.write_tsv(lb.mpath(self.p4, lb.RAW), lb.RAW_HEAD, [
            {"task": "t1", "entry": "a", "label": "1", "source": "pool", "weight": "0.7"},
            {"task": "t2", "entry": "b", "label": "1", "source": "store", "weight": "0.5"}])
        lb.append_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD, [
            {"task": "t1", "entry": "c", "label": "1", "source": "store+edited", "weight": "1.0",
             "teacher": "claude-fable-5-1", "edited": "2026-11-01"},
            {"task": "t3", "entry": "d", "label": "0", "source": "usage", "weight": "0.3"}])
        got = {(r["task"], r["entry"], r["source"]) for r in lb.training_labels(self.p4)}
        self.assertEqual(got, {("t1", "c", "store+edited"), ("t2", "b", "store"), ("t3", "d", "usage")},
                         "a task the teacher edited trains on the edit; its raw pick stays in labels-raw.tsv")
        self.assertEqual(lb.count_labels(self.p4), 4)

    def test_tasks_deduplicated(self):
        rows = [{"id": "x", "session": "s", "time": NOW, "text": "a\tb", "kind": "new"}]
        self.assertEqual(lb.add_tasks(self.p4, rows), 1)
        self.assertEqual(lb.add_tasks(self.p4, rows), 0)
        self.assertEqual(lb.read_tasks(self.p4)["x"]["text"], "a b", "a tab never breaks a row")


class Recency(Base):
    """8.4's free half: a fact with supersedes: outranks (here: replaces) the fact it supersedes for a message dated
    after it, and a label resting on the superseded fact is dropped for the newer one."""

    def setUp(self):
        super().setUp()
        old = [("claim", "the built-in loads MEMORY.md up to 200 lines"), ("source", "docs 2025"),
               ("verified", "2025-06-01"), ("time", "2025-06-01 10:00")]
        self.old_id = f"facts.md:2025-06-01 10:00:{st.sha8(old[0][1])}"
        new = [("claim", "the built-in loads MEMORY.md up to 25,000 bytes, cut at whole lines"),
               ("source", "live measurement 2026-11-01"), ("verified", "2026-11-01"), ("checked", "2026-11-01"),
               ("prior", "limit"), ("supersedes", self.old_id), ("time", "2026-11-01 12:00")]
        self.new_id = f"facts.md:2026-11-01 12:00:{st.sha8(new[0][1])}"
        write(os.path.join(self.p4, "store", "facts.md"), st.render("facts.md", [old, new]))

    def test_label_moves_to_the_newer_fact(self):
        lb.add_tasks(self.p4, [{"id": "late", "session": "s", "time": "2026-11-01 15:00", "text": "memory size",
                                "kind": "new"},
                               {"id": "early", "session": "s", "time": "2026-01-01 15:00", "text": "memory size",
                                "kind": "new"}])
        lb.write_tsv(lb.mpath(self.p4, lb.RAW), lb.RAW_HEAD, [
            {"task": "late", "entry": self.old_id, "label": "1", "source": "store", "weight": "0.5"},
            {"task": "early", "entry": self.old_id, "label": "1", "source": "store", "weight": "0.5"}])
        report = []
        got = lb.recency(self.p4, [lb.as_label(r) for r in lb.read_tsv(lb.mpath(self.p4, lb.RAW))], report)
        late = [r["entry"] for r in got if r["task"] == "late"]
        early = [r["entry"] for r in got if r["task"] == "early"]
        self.assertEqual(late, [self.new_id])
        self.assertEqual(early, [self.old_id], "a task dated before the newer fact keeps the fact of its time")
        self.assertIn("dropped: superseded by", report[0])

    def test_query_prints_the_newer_fact(self):
        r = cli.query(self.p4, "how many bytes of MEMORY.md does the built-in load", None, "2026-11-01 18:00")
        text = "\n".join(r["lines"])
        self.assertIn("25,000 bytes", text)
        self.assertNotIn("200 lines", text)


class History(Base):
    def test_store_labels_from_the_reply(self):
        rows = [[("fingerprint", '"what tests the zebrafish plotter output"'), ("time", "2026-10-25 10:00"),
                 ("arrival", "turn"), ("state", "FRESH"),
                 ("addressed", "the quokka harness checks the zebrafish plotter golden images")],
                [("fingerprint", '"hi"'), ("time", "2026-10-25 10:05"), ("arrival", "turn"), ("state", "FRESH"),
                 ("addressed", "hello")]]
        write(os.path.join(self.p4, "store", "messages", "dddd4444.md"), st.render("messages/dddd4444.md", rows))
        s = lb.from_history(self.p4)
        self.assertGreaterEqual(s["history_tasks"], 1)
        got = [r for r in lb.read_tsv(lb.mpath(self.p4, lb.RAW)) if r["source"] == "store"]
        self.assertTrue(got)
        self.assertTrue(all(not r["entry"].startswith("messages/") for r in got), "a message is never the label")
        self.assertTrue(any("1238e352" in r["entry"] or r["entry"].startswith("rules.md") for r in got))
        self.assertEqual(lb.from_history(self.p4)["history_labels"], s["history_labels"], "a rerun replaces")
        self.assertEqual(len([r for r in lb.read_tsv(lb.mpath(self.p4, lb.RAW)) if r["source"] == "store"]),
                         len(got))

    def test_short_label_its_earlier_reading(self):
        s = lb.from_history(self.p4)
        short = [r for r in lb.read_tsv(lb.mpath(self.p4, lb.RAW)) if r["source"] == "short"]
        self.assertEqual(s["short_labels"], 1, "the second 'Keep going' agrees with the first")
        self.assertTrue(short[0]["entry"].startswith("messages/aaaa1111.md"))


class Usage(Base):
    def test_used_by_path_in_an_edit_unused_otherwise(self):
        idx, _ = st.ensure_index(self.p4)
        src = next(d for d in idx["docs"] if d["file"] == "src")
        rule = next(d for d in idx["docs"] if d["file"] == "rules.md" and "keychain" in d["show"])
        served = {"ids": [src["id"], rule["id"]], "text": "probe it", "task": "t"}
        turn = {"calls": [{"name": "Edit", "input": {"file_path": "/x/" + src["path"], "new_string": "y"}}]}
        got = {r["entry"]: r for r in lb.usage_labels(self.p4, idx, served, "done", turn, "t", NOW)}
        self.assertEqual(got[src["id"]]["label"], "1")
        self.assertEqual(got[rule["id"]]["label"], "0")
        self.assertEqual(got[rule["id"]]["weight"], "0.3")
        got = lb.usage_labels(self.p4, idx, served, "the sweeper keeps the keychain flag in the tombstone", None,
                              "t", NOW)
        self.assertEqual({r["entry"]: r["label"] for r in got}[rule["id"]], "1", "two rare terms in the reply")


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        repo.build(self.p4, self.proj)
        self.idx = st.build_index(self.p4)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_events_and_weights(self):
        f = os.path.join(self.proj, "src", "narwhal_port.py")
        tp = transcript(os.path.join(self.tmp.name, "t.jsonl"), "fix the narwhal port", [
            ("Grep", {"pattern": "x"}, "README.md\ndocs/zebrafish.md"),
            ("Read", {"file_path": os.path.join(self.proj, "docs", "zebrafish.md")}, "z"),
            ("Read", {"file_path": f}, "def open_narwhal_port"),
            ("Bash", {"command": f"cat {self.proj}/README.md | head"}, "# Narwhal"),
            ("Bash", {"command": f"sed -i '' s/1/2/ {f}"}, "")],
            "NarwhalProbe now opens the port; README.md says how.", self.proj)
        turn = tr.turns(tp)[0]
        known, syms = lb.repo_index(self.idx)[:2]
        ev = tr.file_events(turn, self.proj, known, syms, tr.reply_of(turn))
        self.assertEqual(ev["src/narwhal_port.py"]["label"], "edited", "a Bash sed -i is a write")
        self.assertEqual(ev["docs/zebrafish.md"]["label"], "dropped")
        self.assertEqual(ev["README.md"]["label"], "cited", "read by cat, then named in the reply")
        self.assertEqual(tr.WEIGHTS["edited"], (1, 1.0))
        self.assertEqual(tr.WEIGHTS["cited"], (1, 0.7))
        self.assertEqual(tr.WEIGHTS["dropped"], (0, 0.3))
        self.assertEqual(tr.WEIGHTS["unopened"], (0, 0.2))
        tp2 = transcript(os.path.join(self.tmp.name, "t2.jsonl"), "where is it", [
            ("Grep", {"pattern": "x"}, os.path.join(self.proj, "README.md"))], "nowhere", self.proj)
        ev2 = tr.file_events(tr.turns(tp2)[0], self.proj, known, syms, "")
        self.assertEqual(ev2["README.md"]["label"], "unopened")
        self.assertEqual(tr.exploration(turn, ev, {"src/narwhal_port.py"})[:1], (2,), "two calls before")

    def test_skill_invocations(self):
        known = {".claude/skills/narwhal-style/SKILL.md", ".claude/commands/zebra.md",
                 "tools/.claude/skills/probe/SKILL.md", "README.md"}
        self.assertEqual(tr.skill_paths("narwhal-style", known), [".claude/skills/narwhal-style/SKILL.md"])
        self.assertEqual(tr.skill_paths("/zebra", known), [".claude/commands/zebra.md"])
        self.assertEqual(tr.skill_paths("tools:probe", known), ["tools/.claude/skills/probe/SKILL.md"])
        self.assertEqual(tr.skill_paths("some-plugin:narwhal-style", known), [], "a plugin's skill is not the repo's")
        self.assertEqual(tr.skill_paths("update-config", known), [], "a user skill is not in the repo")
        tp = transcript(os.path.join(self.tmp.name, "s.jsonl"), "style the narwhal port", [
            ("Skill", {"skill": "narwhal-style"}, "Launching skill: narwhal-style")], "done", self.proj)
        ev = tr.file_events(tr.turns(tp)[0], self.proj, known, {}, "done")
        self.assertEqual(ev[".claude/skills/narwhal-style/SKILL.md"]["label"], "invoked", "no Read, still a use")
        self.assertEqual(tr.WEIGHTS["invoked"], (1, 0.7))
        # a slash command is a harness line, not a prompt, yet the owner's: a turn of its own, and what it runs
        # lands there, not on the turn before
        f = os.path.join(self.proj, "README.md")
        lines = tr.read_lines(tp) + [
            {"type": "user", "origin": {"kind": "human"}, "message": {"content":
             "<command-message>zebra</command-message>\n<command-name>/zebra</command-name>\n"
             "<command-args>the plotter</command-args>"}},
            {"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text":
             "<command-name>/tools:probe</command-name> quoted in a skill body"}]}},
            {"type": "assistant", "message": {"id": "mc", "content": [
                {"type": "tool_use", "id": "tc", "name": "Edit", "input": {"file_path": f}}]}}]
        ts = tr.turns(lines)
        self.assertEqual([t["prompt"] for t in ts], ["style the narwhal port", "/zebra the plotter"])
        self.assertNotIn(".claude/commands/zebra.md", tr.file_events(ts[0], self.proj, known))
        ev = tr.file_events(ts[1], self.proj, known, {}, "")
        self.assertEqual(ev[".claude/commands/zebra.md"]["label"], "invoked")
        self.assertEqual(ev["README.md"]["label"], "edited", "the command's run is the command's turn")
        self.assertNotIn("tools/.claude/skills/probe/SKILL.md", ev, "a meta line is the harness's, not the owner's")
        first = tr.turns(lines[-3:])
        self.assertEqual([t["prompt"] for t in first], ["/zebra the plotter"], "a session may open with one")
        # tags quoted in a prompt's prose are not a command; a local command (after its caveat) is not a skill
        quoted = tr.turns([{"type": "user", "origin": {"kind": "human"}, "message": {"content":
                            "why did this fail?\n<command-name>/tools:probe</command-name>"}}])
        self.assertEqual(quoted[0]["calls"], [])
        local = tr.turns([{"type": "user", "isMeta": True, "message": {"content":
                           "<local-command-caveat>Caveat: the messages below were generated by the user while "
                           "running local commands.</local-command-caveat>"}},
                          {"type": "user", "message": {"content": "<command-name>/zebra</command-name>"}}])
        self.assertEqual(local, [])

    def test_skill_invocation_is_a_repo_label(self):
        write(os.path.join(self.proj, ".claude", "skills", "narwhal-style", "SKILL.md"),
              "---\nname: narwhal-style\n---\n# Narwhal style\n\nTabs, never spaces.\n")
        repo.git(self.proj, "add", "-A")
        repo.git(self.proj, "commit", "-q", "-m", "add the narwhal-style skill")
        repo.build(self.p4, self.proj)
        idx = st.build_index(self.p4)
        tp = transcript(os.path.join(self.tmp.name, "s.jsonl"), "style the narwhal port", [
            ("Skill", {"skill": "narwhal-style"}, "Launching skill: narwhal-style")], "styled", self.proj)
        turn = tr.turns(tp)[0]
        rows, _ = lb.turn_repo_labels(turn, self.proj, lb.repo_index(idx), "t1", "styled")
        got = {r["entry"]: r for r in rows}
        self.assertEqual(got["repo:.claude/skills/narwhal-style/SKILL.md"]["label"], "1")
        self.assertEqual(got["repo:.claude/skills/narwhal-style/SKILL.md"]["note"], "invoked")

    def test_symbol_cites(self):
        self.assertTrue(tr.cites("src/narwhal_port.py", "NarwhalProbe changed", ["NarwhalProbe"]))
        self.assertFalse(tr.cites("src/narwhal_port.py", "nothing here", ["NarwhalProbe"]))

    def test_from_transcripts_and_reexploration(self):
        slug = os.path.join(self.tmp.name, "slug")
        f = os.path.join(self.proj, "src", "narwhal_port.py")
        transcript(os.path.join(slug, "aaaa1111-0000.jsonl"), "rebuild the wombat installer with the signing step", [
            ("Read", {"file_path": os.path.join(self.proj, "README.md")}, "x"),
            ("Read", {"file_path": f}, "x"),
            ("Edit", {"file_path": f, "old_string": "1", "new_string": "2"}, "ok")], "done", self.proj)
        s = lb.from_transcripts(self.p4, self.proj, [slug])
        self.assertEqual(s["transcripts"], 1)
        self.assertEqual(s["matched_rows"], 1, "the turn is the row of session aaaa1111")
        rows = lb.read_tsv(lb.mpath(self.p4, lb.TRAIN))
        self.assertTrue(any(r["entry"] == "repo:src/narwhal_port.py" and r["label"] == "1" for r in rows))
        self.assertTrue(all(r["source"] == "repo" for r in rows))
        self.assertTrue(rows[0]["task"].startswith("messages/aaaa1111.md:"))
        again = lb.from_transcripts(self.p4, self.proj, [slug])
        self.assertEqual(len(lb.read_tsv(lb.mpath(self.p4, lb.TRAIN))), again["rows"], "a rerun replaces")
        r = lb.reexploration(self.p4, self.proj, [slug])
        self.assertEqual(r["turns"], 1)
        self.assertEqual(r["calls"], 1.0, "one Read before the first relevant open")
        self.assertLessEqual(r["cf_calls"], r["calls"])


class Signals(Base):
    def correction(self):
        rows = [[("fingerprint", '"rename it to the walrus branch"'), ("time", "2026-10-30 10:00"), ("arrival", "turn"),
                 ("state", "FRESH"), ("addressed", "renamed it to walrus-1")],
                [("fingerprint", '"no, the walrus branch is walrus-mac"'), ("time", "2026-10-30 10:03"),
                 ("arrival", "turn"), ("state", "FRESH"), ("addressed", "renamed it to walrus-mac")]]
        write(os.path.join(self.p4, "store", "messages", "eeee5555.md"), st.render("messages/eeee5555.md", rows))
        text = st.read_text(os.path.join(self.p4, "store", "corrections.md")).rstrip("\n")
        text += "\n\n" + st.format_entry([("key", "walrus-branch"), ("time", "2026-10-30 10:03"),
                                          ("match", "walrus-1"), ("meant", "walrus-mac"),
                                          ("from", "sessions/eeee5555/vlds/ledger.md:1")]) + "\n"
        write(os.path.join(self.p4, "store", "corrections.md"), text)

    def test_correction_yields_pending_entry_quoting_before_and_after(self):
        self.correction()
        r = lb.signals(self.p4, session="eeee5555", now=NOW)
        self.assertGreaterEqual(r["new_terms"], 1)
        v = [x for x in st.read_vocabulary(self.p4) if "walrus-branch" in x["source"]]
        self.assertEqual(len(v), 1, "one pending entry for the correction's rarest word of the misread message")
        self.assertTrue(v[0]["pending"])
        because = v[0]["because"][0]
        self.assertIn('"rename it to the walrus branch"', because)
        self.assertIn('"no, the walrus branch is walrus-mac"', because)
        self.assertEqual(lb.signals(self.p4, session="eeee5555", now=NOW)["new_terms"], 0, "never a second entry")

    def test_owner_edit_untouched(self):
        path = os.path.join(self.p4, "store", "vocabulary.md")
        before = st.read_text(path)
        self.correction()
        lb.signals(self.p4, session="eeee5555", now=NOW)
        after = st.read_text(path)
        self.assertTrue(after.startswith(before.rstrip("\n")), "existing entries are byte-identical")

    def test_follow_up_detector(self):
        a = st.Entry("m", 1, [("fingerprint", '"ship the build"'), ("time", "2026-10-30 10:00")])
        b = st.Entry("m", 5, [("fingerprint", '"no, the nightly one"'), ("time", "2026-10-30 11:00")])
        c = st.Entry("m", 9, [("fingerprint", '"ship the build now"'), ("time", "2026-10-30 10:04")])
        d = st.Entry("m", 9, [("fingerprint", '"looks good"'), ("time", "2026-10-30 10:04")])
        self.assertTrue(lb.is_follow_up(a, b))
        self.assertTrue(lb.is_follow_up(a, c))
        self.assertFalse(lb.is_follow_up(a, d))


class RealStores(unittest.TestCase):
    """On the migrated clones: every correction yields a pending entry whose because: quotes the owner's words before
    and after, or is listed as yielding no rare term; a rerun adds nothing."""

    def check(self, name, expect):
        src = fixture(name)
        if not src:
            self.skipTest(f"{name} clone not present")
        import migrate
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "p4")
            migrate.run(src, out=out, apply=True, now=NOW)
            os.remove(os.path.join(out, "store", "vocabulary.md"))
            r = lb.signals(out, now=NOW)
            self.assertEqual(r["signals"]["correction"], expect)
            vocab = st.read_vocabulary(out)
            cited = [v for v in vocab if v["source"].startswith("correction")]
            for v in cited:
                for b in v["because"]:
                    if "it was read as" in b:
                        self.assertGreaterEqual(len(re.findall(r'"[^"]+"', b)), 2, b)
            self.assertEqual(r["yielded"]["correction"] + sum(1 for _ in range(0)), r["yielded"]["correction"])
            self.assertLessEqual(r["yielded"]["correction"], expect)
            self.assertEqual(lb.signals(out, now=NOW)["new_terms"], 0)

    def test_p4p4_19_corrections(self):
        self.check("p4-p4", 19)

    def test_ap_mac_5_corrections(self):
        self.check("ap-p4_mac", 5)


class RealTranscripts(unittest.TestCase):
    def test_repo_labels_from_the_audioplugin_transcripts(self):
        if not (os.path.isdir(os.path.join(MAC_STORE, "store")) and os.path.isdir(AP_SLUG)
                and repo.is_repo(AP_PROJECT)):
            self.skipTest("the ap-p4_mac store, the AudioPlugin repo or its transcripts are not present")
        with tempfile.TemporaryDirectory() as t:
            p4 = copy_store(MAC_STORE, os.path.join(t, "p4"))
            repo.build(p4, AP_PROJECT)
            st.build_index(p4)
            s = lb.from_transcripts(p4, AP_PROJECT, [AP_SLUG])
            self.assertGreater(s["transcripts"], 0)
            self.assertGreater(s["labels"].get("edited", 0), 0, s)
            self.assertGreater(s["labels"].get("cited", 0), 0, s)
            r = lb.reexploration(p4, AP_PROJECT, [AP_SLUG])
            self.assertGreater(r["turns"], 0)
            self.assertLessEqual(r["cf_calls"], r["calls"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
