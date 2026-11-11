#!/usr/bin/env python3
"""phi.py: the memo on the session tree.

    python3 -I lbiza/plugins/p4-phi/scripts/test_phi.py

Checked: a handed-over task read out of its wrapper; a session's last turn with no human prompt; a session's node
and its parent from the app's session records, with no parent id in the payload; ancestors the plugin never saw
given nodes from their records; a child without a store of its own living in its parent's; every turn's exit kept
as a play, open without a check and closed with one, once per turn; the exit rolled up into the parent and handed
to the parent whole at its next message, once; a child starting from its parent's goal, notes and its siblings'
plays; a top session starting from the plays of the sessions before it, with no likeness of words involved; a note
refused without a source; a node moved under another parent; a node's own plays after a compaction; silence where
there is nothing to say; a session told its one goal and what to do with a message that steers off it (ship it
to a forked child and stay), once in full and then in a line beside each of the owner's messages, never beside the
harness's; the goal changed by its command; a hook never failing a call; hooks.json's shape.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402

ROOT = os.path.dirname(HERE)
RUN = os.path.join(ROOT, "hooks", "run-hook.sh").replace("\\", "/")
HOOKS_JSON = os.path.join(ROOT, "hooks", "hooks.json")

TOP, KID, KID2, GRAND = "local_top00001", "local_kid00001", "local_kid00002", "local_grand001"
CLI = {TOP: "aaaa1111-0000-4000-8000-000000000000", KID: "bbbb2222-0000-4000-8000-000000000000",
       KID2: "cccc3333-0000-4000-8000-000000000000", GRAND: "dddd4444-0000-4000-8000-000000000000"}
GOAL = "Make the narwhal exporter write its ports table to the store"
BRIEF = "Find why the narwhal exporter drops the last row of the ports table and fix it"
LONG = ("The last row was dropped by an off-by-one in flush_rows. " + "It is fixed and the suite passes. " * 30).strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def jload(path):
    return json.loads(read(path))


class Tree:
    """A project with a store, and the app's session records beside it."""

    def __init__(self, tmp, store=True):
        self.tmp = tmp
        self.proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(self.proj, ".claude", "p4") if store else self.proj)
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        self.app = os.path.join(tmp, "app", "acct", "org")
        os.makedirs(self.app)

    def record(self, host, parent="", title="", cwd=None):
        d = {"sessionId": host, "cliSessionId": CLI.get(host, host), "cwd": cwd or self.proj,
             "originCwd": cwd or self.proj, "title": title or host}
        if parent:
            d["spawnedFrom"] = {"sessionId": parent, "taskId": "task_1", "title": title, "sideSession": True}
        write(os.path.join(self.app, host + ".json"), json.dumps(d))

    def env(self, host, proj=None, **more):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "P4_PHI"))}
        env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj or self.proj,
                    "P4_PHI_APP_SESSIONS": os.path.join(self.tmp, "app"), "P4_PHI_WAIT": "0", "P4_PHI_STEER": "0", **more})
        if host:
            env["CLAUDE_CODE_HOST_SESSION_ID"] = host
            env["CLAUDE_CODE_SESSION_ID"] = CLI.get(host, host)
        return env

    def hook(self, name, host, payload=None, proj=None, cli=None, **more):
        payload = {"session_id": cli or CLI.get(host, host), "cwd": proj or self.proj, **(payload or {})}
        return subprocess.run(["sh", RUN, name], input=json.dumps(payload), capture_output=True, text=True,
                              env=self.env(host, proj, **more), timeout=60)

    def cli(self, host, *args, proj=None):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), *args],
                              capture_output=True, text=True, env=self.env(host, proj), cwd=proj or self.proj,
                              timeout=60)

    def transcript(self, name, prompt, calls=(), reply="done", uuid="u0"):
        return transcript(os.path.join(self.tmp, name + ".jsonl"), prompt, calls, reply, uuid)

    def exit(self, host, prompt, calls=(), reply="done", uuid="u0", **kw):
        t = self.transcript(host + uuid, prompt, calls, reply, uuid)
        return self.hook("exit", host, {"hook_event_name": "Stop", "transcript_path": t,
                                        "last_assistant_message": reply}, **kw)

    def node(self, host):
        return jload(os.path.join(self.p4, "phi", "nodes", host, "node.json"))

    def plays(self, host):
        return phi.load_plays(self.p4, host)


def transcript(path, prompt, calls, reply, uuid="u0"):
    lines = [{"type": "user", "message": {"role": "user", "content": prompt}, "timestamp": "2026-11-01T18:00:00.000Z",
              "uuid": uuid}]
    for k, call in enumerate(calls):
        name, inp, result = call[:3]
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{k}", "name": name, "input": inp}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{k}", "content": result, "is_error": len(call) > 3}]}})
    lines.append({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    write(path, "\n".join(json.dumps(x) for x in lines) + "\n")
    return path


def context(r):
    """A hook's additionalContext, '' when it said nothing."""
    out = r.stdout.strip()
    if not out:
        return ""
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


HANDED = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n"
          "</system-reminder>\n\nBackground (from the session that started this one):\nThe owner builds things.\n\n"
          "Task:\n" + BRIEF + "\n\nDone looks like: the suite passes.")


class Requests(unittest.TestCase):
    def test_a_handed_over_task_is_read_out_of_its_wrapper(self):
        self.assertTrue(phi.request_of(HANDED).startswith(BRIEF))
        self.assertEqual(phi.request_of("fix the port"), "fix the port")
        forked = "Task (from the session that started this one):\n" + BRIEF
        self.assertEqual(phi.request_of(forked), BRIEF)
        self.assertTrue(phi.handed_over(forked))
        self.assertFalse(phi.handed_over("fix the port"))
        self.assertEqual(phi.request_of("<side-sessions-event>a child ended</side-sessions-event>"), "")
        self.assertEqual(phi.request_of("<system-reminder>x</system-reminder>"), "")
        self.assertEqual(phi.request_of(None), "")

    def test_last_turn_of_a_session_no_human_spoke_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = transcript(os.path.join(tmp, "t.jsonl"), HANDED, [
                ("Edit", {"file_path": "E:/x/src/export/flush.py"}, "ok"),
                ("Bash", {"command": "cd /e/x && python -I tests/test_flush.py 2>&1 | tail -3"}, "OK"),
                ("Bash", {"command": "cat notes.txt"}, "words"),
                ("Bash", {"command": "python -c \"print('a\"b')\""}, "unexpected EOF while looking for matching", 1),
                ("mcp__ccd_session__start_session", {"title": "Check the ports"}, "started")], "fixed")
            turn = phi.last_turn(t)
            self.assertTrue(turn["prompt"].startswith(BRIEF))
            self.assertEqual(turn["uuid"], "u0")
            play = phi.play_of(turn, "fixed")
            self.assertIn("edited export/flush.py", play["steps"])
            self.assertIn("ran `python -I tests/test_flush.py`", play["steps"])
            self.assertIn("started the session \"Check the ports\"", play["steps"])
            self.assertFalse(any("cat notes" in s for s in play["steps"]))
            self.assertEqual(len(play["avoid"]), 1)
            self.assertIn("quotes", play["avoid"][0])

    def test_a_harness_message_does_not_open_a_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = transcript(os.path.join(tmp, "t.jsonl"), BRIEF, [("Edit", {"file_path": "a/b.py"}, "ok")], "one")
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "uuid": "u9", "message": {
                    "content": "<side-sessions-event>a child ended</side-sessions-event>"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "z", "name": "Write", "input": {"file_path": "a/c.py"}}]}}) + "\n")
            turn = phi.last_turn(p)
            self.assertEqual(turn["uuid"], "u0")
            self.assertEqual(len(turn["calls"]), 2)


class Nodes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.record(GRAND, KID, "Bisect flush_rows")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_node_learns_its_parent_from_the_apps_record(self):
        self.t.hook("arrive", KID, {"hook_event_name": "SessionStart", "source": "startup"})
        n = self.t.node(KID)
        self.assertEqual(n["parent"], TOP)
        self.assertEqual(n["title"], "Fix the dropped row")
        self.assertIn(CLI[KID], n["sessions"])
        self.assertEqual(self.t.node(TOP)["parent"], "root")      # an ancestor the plugin never saw gets its node
        self.assertTrue(os.path.isdir(os.path.join(self.t.p4, "phi", "nodes", "root")))

    def test_a_deep_node_gets_its_whole_line(self):
        self.t.hook("prompt", GRAND, {"hook_event_name": "UserPromptSubmit", "prompt": "bisect it"})
        self.assertEqual(self.t.node(GRAND)["parent"], KID)
        self.assertEqual(self.t.node(KID)["parent"], TOP)
        self.assertEqual(phi.line_of(self.t.p4, GRAND), [KID, TOP])

    def test_a_session_outside_the_app_is_a_child_of_the_base_node(self):
        cli = "eeee5555-0000-4000-8000-000000000000"
        self.t.hook("prompt", "", {"hook_event_name": "UserPromptSubmit", "prompt": GOAL}, cli=cli)
        n = self.t.node(cli)
        self.assertEqual(n["parent"], "root")
        self.assertEqual(n["goal"], GOAL)

    def test_the_host_id_missing_from_the_environment_is_found_by_the_cli_id(self):
        env = self.t.env("")
        r = subprocess.run(["sh", RUN, "prompt"], input=json.dumps({"session_id": CLI[KID], "cwd": self.t.proj,
                                                                    "prompt": BRIEF}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.t.node(KID)["parent"], TOP)

    def test_a_starter_the_app_records_late_is_waited_for(self):
        late = "local_late0001"
        write(os.path.join(self.t.app, late + ".json"), json.dumps({"sessionId": late, "cwd": self.t.proj}))
        self.t.hook("arrive", late, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(self.t.node(late)["parent"], "root")
        import threading
        threading.Timer(0.4, lambda: self.t.record(late, TOP, "Late child")).start()
        self.t.hook("prompt", late, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED}, P4_PHI_WAIT="5")
        n = self.t.node(late)
        self.assertEqual((n["parent"], n["parent_from"], n["title"]), (TOP, "record", "Late child"))
        log = phi.read_rows(os.path.join(self.t.p4, "phi", "nodes", late, "log.jsonl"))
        self.assertLess(log[-1]["waited_ms"], 3000)

    def test_a_starter_never_recorded_is_read_from_the_notes_folder(self):
        lost = "local_lost0001"
        write(os.path.join(self.t.app, lost + ".json"), json.dumps({"sessionId": lost, "cwd": self.t.proj}))
        prompt = HANDED + "\n\nShared notes folder for this group of sessions (outside the repo): " \
            "C:\\Users\\x\\AppData\\Local\\Claude-Data\\c\\side-session-notes\\" + KID
        self.t.hook("prompt", lost, {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, P4_PHI_WAIT="30")
        n = self.t.node(lost)
        self.assertEqual((n["parent"], n["parent_from"]), (KID, "hint"))
        log = phi.read_rows(os.path.join(self.t.p4, "phi", "nodes", lost, "log.jsonl"))
        self.assertNotIn("waited_ms", log[-1])                      # the folder names the starter: nothing to wait for
        self.assertNotIn("Shared notes folder", n["goal"])
        self.t.hook("prompt", lost, {"hook_event_name": "UserPromptSubmit", "prompt": "go on"})
        self.assertEqual(self.t.node(lost)["parent"], KID)          # a record that still says nothing changes nothing
        self.t.record(lost, KID2, "Lost child")
        self.t.hook("prompt", lost, {"hook_event_name": "UserPromptSubmit", "prompt": "go on"})
        n = self.t.node(lost)
        self.assertEqual((n["parent"], n["parent_from"]), (KID2, "record"))      # the record wins over the folder

    def test_an_owners_message_waits_for_nothing(self):
        self.t.record("local_plain001")
        self.t.hook("prompt", "local_plain001", {"hook_event_name": "UserPromptSubmit", "prompt": GOAL},
                    P4_PHI_WAIT="5")
        log = phi.read_rows(os.path.join(self.t.p4, "phi", "nodes", "local_plain001", "log.jsonl"))
        self.assertNotIn("waited_ms", log[-1])

    def test_a_child_with_no_store_lives_in_its_parents(self):
        work = os.path.join(self.t.tmp, "worktree")
        os.makedirs(work)
        self.t.record(KID, TOP, "Fix the dropped row", cwd=work)
        self.t.hook("prompt", KID, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED}, proj=work)
        self.assertTrue(self.t.node(KID)["goal"].startswith(BRIEF))
        self.assertFalse(os.path.exists(os.path.join(work, ".claude")))

    def test_no_store_anywhere_is_silence_and_nothing_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp, store=False)
            t.record(TOP)
            r = t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": GOAL})
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertFalse(os.path.exists(os.path.join(t.proj, ".claude")))

    def test_the_first_session_of_a_store_hears_nothing(self):
        r = self.t.hook("arrive", TOP, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        r = self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": GOAL})
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(self.t.node(TOP)["goal"], GOAL)


class Exits(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.record(GRAND, KID, "Bisect flush_rows")
        self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": GOAL})

    def tearDown(self):
        self._tmp.cleanup()

    def kid_exits(self, host=KID, reply=LONG, uuid="u0", prompt=HANDED):
        return self.t.exit(host, prompt, [("Edit", {"file_path": "E:/x/src/export/flush.py"}, "ok"),
                                          ("Bash", {"command": "python -I tests/test_flush.py"}, "OK")], reply, uuid)

    def test_every_exit_is_a_play_open_until_something_checked_it(self):
        r = self.kid_exits()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        plays = self.t.plays(KID)
        self.assertEqual(len(plays), 1)
        p = plays[0]
        self.assertEqual(p["state"], "open")
        self.assertTrue(p["goal"].startswith(BRIEF))
        self.assertEqual(p["steps"], ["edited export/flush.py", "ran `python -I tests/test_flush.py`"])
        self.assertEqual(p["closing"], LONG[:phi.CLOSING_CHARS])

    def test_a_turn_that_only_talked_is_still_a_play(self):
        self.t.exit(KID, "what is the port for?", [], "It is 4000.")
        self.assertEqual([p["steps"] for p in self.t.plays(KID)], [[]])

    def test_a_turn_is_one_play_however_often_it_ends(self):
        self.kid_exits(reply="first")
        self.kid_exits(reply="second")
        plays = self.t.plays(KID)
        self.assertEqual([p["closing"] for p in plays], ["second"])
        self.kid_exits(reply="third", uuid="u1", prompt="now the header row")
        self.assertEqual(len(self.t.plays(KID)), 2)

    def test_a_check_closes_the_play(self):
        r = self.t.cli(KID, "close", "--check", "test_flush.py: 14 tests OK")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.kid_exits()
        p = self.t.plays(KID)[0]
        self.assertEqual((p["state"], p["check"]), ("closed", "test_flush.py: 14 tests OK"))
        self.kid_exits(uuid="u1", prompt="and the header row")      # the check was that turn's, not the next one's
        self.assertEqual(self.t.plays(KID)[-1]["state"], "open")

    def test_the_exit_reaches_the_parent_whole_and_once(self):
        self.kid_exits()
        r = self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit",
                                        "prompt": "<side-sessions-event>Fix the dropped row ended a turn</side-sessions-event>"})
        text = context(r)
        self.assertIn("Fix the dropped row", text)
        self.assertIn(LONG, text)                       # more than the 400 characters the app relays
        self.assertGreater(len(LONG), 400)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("open", text)
        again = self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": "and now?"})
        self.assertEqual(again.stdout.strip(), "")

    def test_only_the_latest_exit_of_a_child_is_handed_over(self):
        self.kid_exits(reply="first try")
        self.kid_exits(reply="second try")
        text = context(self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": "well?"}))
        self.assertIn("second try", text)
        self.assertNotIn("first try", text)

    def test_the_parents_own_exit_carries_its_children(self):
        self.t.cli(KID, "close", "--check", "14 tests OK")
        self.kid_exits()
        self.t.exit(TOP, GOAL, [], "The child fixed it.")
        p = self.t.plays(TOP)[0]
        self.assertTrue(any("Fix the dropped row" in c and "closed" in c for c in p["children"]), p)
        memo = read(os.path.join(self.t.p4, "phi", "nodes", TOP, "memo.md"))
        self.assertIn(GOAL, memo)
        self.assertIn("Fix the dropped row", memo)
        root = phi.load_rollup(self.t.p4, "root")
        self.assertEqual(root[-1]["child"], TOP)

    def test_a_grandchilds_exit_goes_to_its_parent_not_to_the_top(self):
        self.t.exit(GRAND, "bisect flush_rows", [], "It is commit abc.")
        self.assertEqual([r["child"] for r in phi.load_rollup(self.t.p4, KID)], [GRAND])
        self.assertEqual(phi.load_rollup(self.t.p4, TOP), [])


class Ghosts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": GOAL})

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, host, source="startup"):
        return context(self.t.hook("arrive", host, {"hook_event_name": "SessionStart", "source": source}))

    def test_a_child_starts_from_its_parents_memo(self):
        r = self.t.cli(TOP, "note", "The ports table is written by flush_rows in export/flush.py",
                       "--source", "export/flush.py:40")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.start(KID)
        self.assertIn(GOAL, text)
        self.assertIn("flush_rows in export/flush.py", text)
        self.assertIn("export/flush.py:40", text)
        self.assertIn("Narwhal exporter", text)
        self.assertLessEqual(len(text), phi.GHOST_CHARS)
        self.assertEqual(self.t.hook("prompt", KID, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED}
                                     ).stdout.strip(), "")       # told once
        log = phi.read_rows(os.path.join(self.t.p4, "phi", "nodes", KID, "log.jsonl"))
        self.assertEqual([(r["hook"], r["said"] > 0, r["parent"]) for r in log],
                         [("arrive", True, TOP), ("prompt", False, TOP)])

    def test_a_ghost_missed_at_the_start_arrives_with_the_first_message(self):
        text = context(self.t.hook("prompt", KID, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED}))
        self.assertIn(GOAL, text)

    def test_a_sibling_starts_from_the_play_before_it(self):
        self.t.exit(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok"),
                                  ("Bash", {"command": "python -c \"x\""}, "No module named 'numpy'", 1)],
                    "Stopped: the fix needs the owner's word on the format.")
        text = self.start(KID2)
        self.assertIn("Fix the dropped row", text)
        self.assertIn("open", text)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("the owner's word on the format", text)
        self.assertIn("numpy", text)
        self.assertNotIn("Check the ports table\" (", text)        # not its own, empty, node

    def test_the_next_top_session_starts_from_the_one_before_whatever_its_words(self):
        self.t.exit(TOP, GOAL, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        other = "local_top00002"
        self.t.record(other, title="Something else entirely")
        self.assertEqual(self.start(other), "")        # in the app a start is told nothing: its starter is unknown
        text = context(self.t.hook("prompt", other, {"hook_event_name": "UserPromptSubmit",
                                                     "prompt": "paint the fence green"}))
        self.assertIn(GOAL, text)
        self.assertIn("Half done.", text)

    def test_a_session_no_app_runs_is_told_at_its_start(self):
        self.t.exit(TOP, GOAL, [], "Half done.")
        cli = "eeee5555-0000-4000-8000-000000000000"
        text = context(self.t.hook("arrive", "", {"hook_event_name": "SessionStart", "source": "startup"}, cli=cli))
        self.assertIn("Half done.", text)

    def test_a_play_that_left_is_not_shown_under_its_old_parent(self):
        self.t.exit(KID, HANDED, [], "Half done.")
        self.t.cli(TOP, "reparent", KID, "root")
        self.assertNotIn("Half done.", self.start(KID2))

    def test_a_note_needs_its_source(self):
        r = self.t.cli(TOP, "note", "The ports table is written by flush_rows")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("source", r.stderr)
        self.assertEqual(phi.load_notes(self.t.p4, TOP), [])

    def test_a_node_meets_its_own_plays_after_a_compaction(self):
        self.t.exit(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        text = self.start(KID, "compact")
        self.assertIn("Half done.", text)
        self.assertIn("edited export/flush.py", text)

    def test_a_node_is_moved_under_another_parent(self):
        self.t.record(GRAND, KID, "Bisect flush_rows")
        self.t.exit(GRAND, "bisect flush_rows", [], "It is commit abc.")
        r = self.t.cli(TOP, "reparent", GRAND, KID2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.node(GRAND)["parent"], KID2)
        self.assertEqual(phi.load_rollup(self.t.p4, KID2)[-1]["child"], GRAND)
        text = context(self.t.hook("prompt", KID2, {"hook_event_name": "UserPromptSubmit", "prompt": "go on"}))
        self.assertIn("It is commit abc.", text)
        self.t.hook("prompt", GRAND, {"hook_event_name": "UserPromptSubmit", "prompt": "more"})
        self.assertEqual(self.t.node(GRAND)["parent"], KID2)       # the app's record does not move it back
        self.assertNotEqual(self.t.cli(TOP, "reparent", KID2, GRAND).returncode, 0)    # no loops
        self.assertNotEqual(self.t.cli(TOP, "reparent", TOP, GRAND).returncode, 0)

    def test_the_tree_is_printed(self):
        self.t.exit(KID, HANDED, [], "Half done.")
        out = self.t.cli(TOP, "tree").stdout
        self.assertIn("Narwhal exporter", out)
        self.assertIn("  Fix the dropped row", out.replace("- ", ""))
        self.assertIn("open", out)

    def test_off_is_off(self):
        self.t.cli(TOP, "note", "The ports table is written by flush_rows", "--source", "flush.py:40")
        r = self.t.hook("arrive", KID, {"hook_event_name": "SessionStart", "source": "startup"}, P4_PHI="0")
        self.assertEqual(r.stdout.strip(), "")
        self.assertFalse(os.path.exists(os.path.join(self.t.p4, "phi", "nodes", KID)))


class Steer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")

    def tearDown(self):
        self._tmp.cleanup()

    def say(self, host, prompt, **more):
        return context(self.t.hook("prompt", host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt},
                                   P4_PHI_STEER="1", **more))

    def test_the_rule_comes_once_with_the_goal_and_then_a_line(self):
        first = self.say(TOP, GOAL)
        self.assertIn(GOAL, first)
        self.assertIn("start_session", first)
        self.assertIn("fork", first)
        self.assertIn("stay", first)
        second = self.say(TOP, "also, what colour should the fence be?")
        self.assertIn(GOAL, second)
        self.assertLess(len(second), 400)
        self.assertNotIn("start_session", second)
        self.assertNotIn("fence", second)                 # the goal is the first request, not the newest words
        log = phi.read_rows(os.path.join(self.t.p4, "phi", "nodes", TOP, "log.jsonl"))
        self.assertEqual([r.get("steer") for r in log], ["rule", "line"])

    def test_the_harness_speaking_gets_no_line(self):
        self.say(TOP, GOAL)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a child ended</side-sessions-event>"), "")
        self.assertEqual(self.say(TOP, "<task-notification>done</task-notification>"), "")

    def test_a_child_is_told_its_goal_is_its_brief(self):
        self.say(TOP, GOAL)
        text = self.say(KID, HANDED)
        self.assertIn(BRIEF, text)
        self.assertIn("start_session", text)

    def test_the_rule_comes_again_after_a_compaction(self):
        self.say(TOP, GOAL)
        r = self.t.hook("arrive", TOP, {"hook_event_name": "SessionStart", "source": "compact"}, P4_PHI_STEER="1")
        text = context(r)
        self.assertIn(GOAL, text)
        self.assertIn("start_session", text)

    def test_the_goal_is_changed_by_its_command(self):
        self.say(TOP, GOAL)
        r = self.t.cli(TOP, "goal", "Make the narwhal importer read the ports table back")
        self.assertEqual(r.returncode, 0, r.stderr)
        n = self.t.node(TOP)
        self.assertEqual(n["goal"], "Make the narwhal importer read the ports table back")
        self.assertEqual(n["goals"][0]["goal"], GOAL)             # the goal before it is kept
        self.assertIn("importer", self.say(TOP, "go on"))
        self.assertNotEqual(self.t.cli(TOP, "goal", "x").returncode, 0)

    def test_off_in_the_stores_settings(self):
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"steer": False}))
        r = self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": GOAL})
        self.assertEqual(r.stdout.strip(), "")
        env = {k: v for k, v in self.t.env(TOP).items() if k != "P4_PHI_STEER"}
        r = subprocess.run(["sh", RUN, "prompt"], input=json.dumps({"session_id": CLI[TOP], "cwd": self.t.proj,
                                                                    "prompt": "and the next part"}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.stdout.strip(), "")


class NeverFails(unittest.TestCase):
    def test_broken_input_and_broken_files_end_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp)
            t.record(TOP)
            t.record(KID, TOP)
            for name in ("arrive", "prompt", "exit", "nonsense"):
                r = subprocess.run(["sh", RUN, name], input="{not json", capture_output=True, text=True,
                                   env=t.env(KID), timeout=60)
                self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), name)
            t.hook("prompt", TOP, {"prompt": GOAL})
            write(os.path.join(t.p4, "phi", "nodes", TOP, "node.json"), "{broken")
            write(os.path.join(t.p4, "phi", "nodes", TOP, "rollup.jsonl"), "not json\n")
            write(os.path.join(t.app, KID + ".json"), "{broken")
            for name, payload in (("arrive", {"source": "startup"}), ("prompt", {"prompt": "x"}),
                                  ("exit", {"transcript_path": os.path.join(tmp, "missing.jsonl")})):
                for host in (TOP, KID):
                    r = t.hook(name, host, payload)
                    self.assertEqual(r.returncode, 0, (name, host, r.stderr))
                    self.assertEqual(r.stderr.strip(), "", (name, host))


class Wiring(unittest.TestCase):
    def test_hooks_json(self):
        d = jload(HOOKS_JSON)["hooks"]
        self.assertEqual(sorted(d), ["SessionStart", "Stop", "UserPromptSubmit"])       # nothing around a tool call
        for event, name in (("SessionStart", "arrive"), ("UserPromptSubmit", "prompt"), ("Stop", "exit")):
            cmd = d[event][0]["hooks"][0]["command"]
            self.assertIn("run-hook.sh", cmd)
            self.assertTrue(cmd.endswith(" " + name), cmd)

    def test_manifests(self):
        p = jload(os.path.join(ROOT, ".claude-plugin", "plugin.json"))
        self.assertEqual(p["name"], "p4-phi")
        m = jload(os.path.join(os.path.dirname(os.path.dirname(ROOT)), ".claude-plugin", "marketplace.json"))
        self.assertIn("p4-phi", [x["name"] for x in m["plugins"]])
        self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", "phi", "SKILL.md")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
