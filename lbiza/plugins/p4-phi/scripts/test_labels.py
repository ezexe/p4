#!/usr/bin/env python3
"""Tests for labels.py: the two labels files and their join, the recency rule, the history, usage and repo labels
with the transcript reading they rest on, the follow-up detector and the re-exploration measure.

Run: python3 test_labels.py

The tests need the standard library and git, and no network. Fixtures are built in temporary directories.
RealTranscripts needs three paths: the store MAC_STORE names, which P4_MAC_STORE sets when it is given, the
repository AP_PROJECT and its transcripts under AP_SLUG. Where one is missing the test is skipped. It reads them
and writes only into a temporary copy of the store.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import p4 as cli  # noqa: E402
import repo  # noqa: E402
import store as st  # noqa: E402
import transcript as tr  # noqa: E402
from test_hooks import make_project, transcript  # noqa: E402
from test_store import NOW, make_store, write  # noqa: E402

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
    """A fact with `supersedes:` replaces the fact it supersedes for a message dated at or after it: the query
    prints the newer fact alone, and a label on the superseded fact moves to the newer one."""

    def setUp(self):
        super().setUp()
        old = [("claim", "the built-in loads MEMORY.md up to 200 lines"), ("source", "docs 2025"),
               ("verified", "2025-06-01"), ("time", "2025-06-01 10:00")]
        self.old_id = f"facts.md:2025-06-01 10:00:{st.sha8(old[0][1])}"
        new = [("claim", "the built-in loads MEMORY.md up to 25,000 bytes, cut at whole lines"),
               ("source", "live measurement 2026-11-01"), ("verified", "2026-11-01"), ("checked", "2026-11-01"),
               ("prior", "limit"), ("supersedes", self.old_id), ("time", "2026-11-01 12:00")]
        self.new_id = f"facts.md:2026-11-01 12:00:{st.sha8(new[0][1])}"
        write(p4conf.sub(self.p4, "store", "facts.md"), st.render("facts.md", [old, new]))

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
        write(p4conf.sub(self.p4, "store", "messages", "dddd4444.md"), st.render("messages/dddd4444.md", rows))
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

    def test_note_keeps_whether_the_lines_were_shown(self):
        """The hook deletes the served record after it writes the labels, so each usage label's note keeps what
        the record's `shown` and `shadow` fields said."""
        idx, _ = st.ensure_index(self.p4)
        rule = next(d for d in idx["docs"] if d["file"] == "rules.md" and "keychain" in d["show"])
        reply = "the sweeper keeps the keychain flag in the tombstone"
        shown = {"ids": [rule["id"]], "text": "probe it", "task": "t", "lines": 2, "shown": 2, "shadow": False}
        self.assertEqual(lb.usage_labels(self.p4, idx, shown, reply, None, "t", NOW)[0]["note"], "used; shown")
        shadow = {"ids": [rule["id"]], "text": "probe it", "task": "t", "lines": 2, "shown": 0, "shadow": True}
        self.assertEqual(lb.usage_labels(self.p4, idx, shadow, "done", None, "t", NOW)[0]["note"], "unused; shadow")
        self.assertEqual(lb.usage_labels(self.p4, idx, shadow, reply, None, "t", NOW)[0]["note"], "used; shadow")
        agent = {"ids": [rule["id"]], "text": "probe it", "task": "agent:x", "shadow": False}
        self.assertEqual(lb.usage_labels(self.p4, idx, agent, "done", None, "t", NOW)[0]["note"], "unused; shown",
                         "an agent record carries shadow alone")
        old = {"ids": [rule["id"]], "text": "probe it", "task": "t"}
        self.assertEqual(lb.usage_labels(self.p4, idx, old, "done", None, "t", NOW)[0]["note"], "unused",
                         "a record with neither field says nothing")


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

    @unittest.skipUnless(os.sep == "\\", "the spellings of one Windows path")
    def test_a_windows_path_in_any_spelling_is_one_file(self):
        known = lb.repo_index(self.idx)[0]
        f = os.path.join(self.proj, "src", "narwhal_port.py")
        drive, rest = f[0], f[2:].replace("\\", "/")
        for spelled in (f, drive.swapcase() + f[1:], f.replace("\\", "/"), "/" + drive.lower() + rest,
                        "/" + drive.upper() + rest):
            self.assertEqual(tr.bash_paths(f'cat "{spelled}"', self.proj, self.proj, known),
                             ({"src/narwhal_port.py"}, set()), spelled)

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
        # a slash command comes in Claude Code's tags, so it is no prompt, yet it is ezexe's: a turn of its own,
        # and what it runs lands there, not on the turn before
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
        self.assertNotIn("tools/.claude/skills/probe/SKILL.md", ev, "a meta line is Claude Code's, not ezexe's")
        first = tr.turns(lines[-3:])
        self.assertEqual([t["prompt"] for t in first], ["/zebra the plotter"], "a session may open with one")
        # tags quoted in a prompt's prose are not a command, and a local command, the line after its caveat, opens
        # no turn
        quoted = tr.turns([{"type": "user", "origin": {"kind": "human"}, "message": {"content":
                            "why did this fail?\n<command-name>/tools:probe</command-name>"}}])
        self.assertEqual(quoted[0]["calls"], [])
        local = tr.turns([{"type": "user", "isMeta": True, "message": {"content":
                           "<local-command-caveat>Caveat: the messages below were generated by ezexe while "
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


class FollowUp(unittest.TestCase):
    def test_follow_up_detector(self):
        a = st.Entry("m", 1, [("fingerprint", '"ship the build"'), ("time", "2026-10-30 10:00")])
        b = st.Entry("m", 5, [("fingerprint", '"no, the nightly one"'), ("time", "2026-10-30 11:00")])
        c = st.Entry("m", 9, [("fingerprint", '"ship the build now"'), ("time", "2026-10-30 10:04")])
        d = st.Entry("m", 9, [("fingerprint", '"looks good"'), ("time", "2026-10-30 10:04")])
        self.assertTrue(lb.is_follow_up(a, b))
        self.assertTrue(lb.is_follow_up(a, c))
        self.assertFalse(lb.is_follow_up(a, d))


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
