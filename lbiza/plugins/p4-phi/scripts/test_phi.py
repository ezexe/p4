#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

    python3 -I lbiza/plugins/p4-phi/scripts/test_phi.py

Checked: a handed-over task read out of its wrapper, a forked session's too; a session's last turn with no human
prompt; which session started a session, from the app's record, with nothing in the payload saying it; the
sessions above it given their files from their records; a `spawnedFrom` the app writes late read from the notes
folder first and corrected by the record; a session with no store of its own living in the store of the session
that started it; every finished turn kept, done or not, once per turn; its report appended to the reports of the
session that started it and given to that session in full at its next message, once; a started session given the
tasks and notes of the sessions above it and the last turn of the other sessions started beside it; a top session
given the last turns of the top sessions before it, with no likeness of words involved; a note refused without a
source; a session detached, and reparented; a session's own turns after a compaction; silence where there is
nothing to say; the user's standing instruction for a message about something else, once in full and then in a
line beside each of the user's messages, never beside the harness's; the task changed by its command; the hook
names of earlier versions still answered; a hook never failing a call; hooks.json's shape.
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
START, PROMPT, STOP = "session-start", "user-prompt-submit", "stop"

TOP, KID, KID2, GRAND = "local_top00001", "local_kid00001", "local_kid00002", "local_grand001"
CLI = {TOP: "aaaa1111-0000-4000-8000-000000000000", KID: "bbbb2222-0000-4000-8000-000000000000",
       KID2: "cccc3333-0000-4000-8000-000000000000", GRAND: "dddd4444-0000-4000-8000-000000000000"}
TASK = "Make the narwhal exporter write its ports table to the store"
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

    def record(self, host, started_by="", title="", cwd=None):
        d = {"sessionId": host, "cliSessionId": CLI.get(host, host), "cwd": cwd or self.proj,
             "originCwd": cwd or self.proj, "title": title or host}
        if started_by:
            d["spawnedFrom"] = {"sessionId": started_by, "taskId": "task_1", "title": title, "sideSession": True}
            d["startChain"] = {"firstSessionId": TOP, "depth": 1}
        write(os.path.join(self.app, host + ".json"), json.dumps(d))

    def env(self, host, proj=None, **more):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "P4_PHI"))}
        env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj or self.proj,
                    "P4_PHI_APP_SESSIONS": os.path.join(self.tmp, "app"), "P4_PHI_WAIT": "0",
                    "P4_PHI_NEW_TASK": "0", **more})
        if host:
            env["CLAUDE_CODE_HOST_SESSION_ID"] = host
            env["CLAUDE_CODE_SESSION_ID"] = CLI.get(host, host)
        return env

    def hook(self, name, host, payload=None, proj=None, cli=None, **more):
        payload = {"session_id": cli or CLI.get(host, host), "cwd": proj or self.proj, **(payload or {})}
        return subprocess.run(["sh", RUN, name], input=json.dumps(payload), capture_output=True, text=True,
                              env=self.env(host, proj, **more), timeout=60)

    def say(self, host, prompt, **more):
        return self.hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, **more)

    def cli(self, host, *args, proj=None):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), *args],
                              capture_output=True, text=True, env=self.env(host, proj), cwd=proj or self.proj,
                              timeout=60)

    def stop(self, host, prompt, calls=(), report="done", uuid="u0", **kw):
        t = transcript(os.path.join(self.tmp, host + uuid + ".jsonl"), prompt, calls, report, uuid)
        return self.hook(STOP, host, {"hook_event_name": "Stop", "transcript_path": t,
                                      "last_assistant_message": report}, **kw)

    def dir(self, host):
        return os.path.join(self.p4, "phi", "sessions", host)

    def session(self, host):
        return jload(os.path.join(self.dir(host), "session.json"))

    def started_by(self, host):
        """(sessionId, source) of a session's `spawnedFrom`; ('', '') for a top session."""
        s = self.session(host).get("spawnedFrom") or {}
        return s.get("sessionId", ""), s.get("source", "")

    def turns(self, host):
        return phi.load_turns(self.p4, host)

    def log(self, host):
        return phi.read_rows(os.path.join(self.dir(host), "log.jsonl"))


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
        self.assertEqual(phi.request_of("<side-sessions-event>a session finished a turn</side-sessions-event>"), "")
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
            row = phi.turn_of(turn, "fixed")
            self.assertEqual(sorted(row), ["done", "failed", "id", "prompt", "report", "steps"])
            self.assertIn("edited export/flush.py", row["steps"])
            self.assertIn("ran `python -I tests/test_flush.py`", row["steps"])
            self.assertIn("started the session \"Check the ports\"", row["steps"])
            self.assertFalse(any("cat notes" in s for s in row["steps"]))
            self.assertEqual(len(row["failed"]), 1)
            self.assertIn("quotes", row["failed"][0])
            self.assertEqual(row["report"], "fixed")

    def test_a_harness_message_does_not_open_a_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = transcript(os.path.join(tmp, "t.jsonl"), BRIEF, [("Edit", {"file_path": "a/b.py"}, "ok")], "one")
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "uuid": "u9", "message": {
                    "content": "<side-sessions-event>a session finished a turn</side-sessions-event>"}}) + "\n")
                f.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "z", "name": "Write", "input": {"file_path": "a/c.py"}}]}}) + "\n")
            turn = phi.last_turn(p)
            self.assertEqual(turn["uuid"], "u0")
            self.assertEqual(len(turn["calls"]), 2)


class Sessions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.record(GRAND, KID, "Bisect flush_rows")

    def tearDown(self):
        self._tmp.cleanup()

    def test_which_session_started_it_comes_from_the_apps_record(self):
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"})
        s = self.t.session(KID)
        self.assertEqual(s["spawnedFrom"], {"sessionId": TOP, "source": "record"})      # the app's own field name
        self.assertEqual(s["startChain"], {"firstSessionId": TOP, "depth": 1})
        self.assertEqual(s["title"], "Fix the dropped row")
        self.assertEqual(s["cliSessionIds"], [CLI[KID]])
        self.assertNotIn("spawnedFrom", self.t.session(TOP))       # a top session: made from its record, started by none

    def test_a_deep_session_gets_every_session_above_it(self):
        self.t.say(GRAND, "bisect it")
        self.assertEqual(self.t.started_by(GRAND)[0], KID)
        self.assertEqual(self.t.started_by(KID)[0], TOP)
        self.assertEqual(phi.chain_of(self.t.p4, GRAND), [KID, TOP])

    def test_a_session_outside_the_app_is_a_top_session(self):
        cli = "eeee5555-0000-4000-8000-000000000000"
        self.t.hook(PROMPT, "", {"hook_event_name": "UserPromptSubmit", "prompt": TASK}, cli=cli)
        s = self.t.session(cli)
        self.assertNotIn("spawnedFrom", s)
        self.assertEqual(s["task"], TASK)

    def test_the_host_id_missing_from_the_environment_is_found_by_the_cli_id(self):
        r = subprocess.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[KID], "cwd": self.t.proj,
                                                                  "prompt": BRIEF}),
                           capture_output=True, text=True, env=self.t.env(""), timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.t.started_by(KID), (TOP, "record"))

    def test_a_record_the_app_writes_late_is_waited_for(self):
        late = "local_late0001"
        write(os.path.join(self.t.app, late + ".json"), json.dumps({"sessionId": late, "cwd": self.t.proj}))
        self.t.hook(START, late, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(self.t.started_by(late), ("", ""))
        import threading
        threading.Timer(0.4, lambda: self.t.record(late, TOP, "Late session")).start()
        self.t.say(late, HANDED, P4_PHI_WAIT="5")
        self.assertEqual(self.t.started_by(late), (TOP, "record"))
        self.assertEqual(self.t.session(late)["title"], "Late session")
        self.assertLess(self.t.log(late)[-1]["waited_ms"], 3000)

    def test_a_record_that_says_nothing_yet_is_read_from_the_notes_folder(self):
        lost = "local_lost0001"
        write(os.path.join(self.t.app, lost + ".json"), json.dumps({"sessionId": lost, "cwd": self.t.proj}))
        prompt = HANDED + "\n\nShared notes folder for this group of sessions (outside the repo): " \
            "C:\\Users\\x\\AppData\\Local\\Claude-Data\\c\\side-session-notes\\" + KID
        self.t.say(lost, prompt, P4_PHI_WAIT="30")
        self.assertEqual(self.t.started_by(lost), (KID, "notes folder"))
        self.assertNotIn("waited_ms", self.t.log(lost)[-1])         # the folder names it: nothing to wait for
        self.assertNotIn("Shared notes folder", self.t.session(lost)["task"])
        self.t.say(lost, "go on")
        self.assertEqual(self.t.started_by(lost), (KID, "notes folder"))    # a record still silent changes nothing
        self.t.record(lost, KID2, "Lost session")
        self.t.say(lost, "go on")
        self.assertEqual(self.t.started_by(lost), (KID2, "record"))         # the record wins over the folder

    def test_a_users_message_waits_for_nothing(self):
        self.t.record("local_plain001")
        self.t.say("local_plain001", TASK, P4_PHI_WAIT="5")
        self.assertNotIn("waited_ms", self.t.log("local_plain001")[-1])

    def test_a_session_with_no_store_lives_in_that_of_the_session_that_started_it(self):
        work = os.path.join(self.t.tmp, "worktree")
        os.makedirs(work)
        self.t.record(KID, TOP, "Fix the dropped row", cwd=work)
        self.t.say(KID, HANDED, proj=work)
        self.assertTrue(self.t.session(KID)["task"].startswith(BRIEF))
        self.assertFalse(os.path.exists(os.path.join(work, ".claude")))

    def test_no_store_anywhere_is_silence_and_nothing_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp, store=False)
            t.record(TOP)
            r = t.say(TOP, TASK)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertFalse(os.path.exists(os.path.join(t.proj, ".claude")))

    def test_the_first_session_of_a_store_hears_nothing(self):
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertEqual(self.t.say(TOP, TASK).stdout.strip(), "")
        self.assertEqual(self.t.session(TOP)["task"], TASK)

    def test_the_hook_names_of_earlier_versions_still_run(self):
        self.t.hook("prompt", TOP, {"hook_event_name": "UserPromptSubmit", "prompt": TASK})
        self.assertEqual(self.t.session(TOP)["task"], TASK)
        self.assertEqual(self.t.log(TOP)[-1]["hook"], PROMPT)


class Turns(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.record(GRAND, KID, "Bisect flush_rows")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def kid_stops(self, host=KID, report=LONG, uuid="u0", prompt=HANDED):
        return self.t.stop(host, prompt, [("Edit", {"file_path": "E:/x/src/export/flush.py"}, "ok"),
                                          ("Bash", {"command": "python -I tests/test_flush.py"}, "OK")], report, uuid)

    def test_every_finished_turn_is_kept_not_done_until_something_showed_it(self):
        r = self.kid_stops()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        turns = self.t.turns(KID)
        self.assertEqual(len(turns), 1)
        t = turns[0]
        self.assertEqual(t["done"], "")
        self.assertTrue(t["prompt"].startswith(BRIEF))
        self.assertEqual(t["steps"], ["edited export/flush.py", "ran `python -I tests/test_flush.py`"])
        self.assertEqual(t["report"], LONG[:phi.REPORT_CHARS])
        self.assertEqual((t["sessionId"], t["cliSessionId"]), (KID, CLI[KID]))

    def test_a_turn_that_only_talked_is_still_kept(self):
        self.t.stop(KID, "what is the port for?", [], "It is 4000.")
        self.assertEqual([t["steps"] for t in self.t.turns(KID)], [[]])

    def test_a_turn_is_kept_once_however_often_it_finishes(self):
        self.kid_stops(report="first")
        self.kid_stops(report="second")
        self.assertEqual([t["report"] for t in self.t.turns(KID)], ["second"])
        self.kid_stops(report="third", uuid="u1", prompt="now the header row")
        self.assertEqual(len(self.t.turns(KID)), 2)

    def test_done_is_said_with_what_showed_it(self):
        r = self.t.cli(KID, "done", "test_flush.py: 14 tests OK")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.kid_stops()
        self.assertEqual(self.t.turns(KID)[0]["done"], "test_flush.py: 14 tests OK")
        self.kid_stops(uuid="u1", prompt="and the header row")      # it was that turn's, not the next one's
        self.assertEqual(self.t.turns(KID)[-1]["done"], "")
        self.assertNotEqual(self.t.cli(KID, "done", "ok").returncode, 0)

    def test_the_report_reaches_the_session_that_started_it_in_full_and_once(self):
        self.kid_stops()
        text = context(self.t.say(TOP, "<side-sessions-event>Fix the dropped row finished a turn</side-sessions-event>"))
        self.assertIn("reports of the sessions this session started", text)
        self.assertIn("Fix the dropped row", text)
        self.assertIn(LONG, text)                       # more than the 400 characters the app relays
        self.assertGreater(len(LONG), 400)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("not shown done", text)
        self.assertEqual(self.t.say(TOP, "and now?").stdout.strip(), "")

    def test_only_the_latest_turn_of_a_session_is_given(self):
        self.kid_stops(report="first try")
        self.kid_stops(report="second try")
        text = context(self.t.say(TOP, "well?"))
        self.assertIn("second try", text)
        self.assertNotIn("first try", text)

    def test_a_sessions_own_turn_lists_the_sessions_it_started(self):
        self.t.cli(KID, "done", "test_flush.py: 14 tests OK")
        self.kid_stops()
        self.t.stop(TOP, TASK, [], "The session I started fixed it.")
        t = self.t.turns(TOP)[0]
        self.assertEqual(t["sessions"], ["\"Fix the dropped row\": done"])
        page = read(os.path.join(self.t.dir(TOP), "session.md"))
        self.assertIn(TASK, page)
        self.assertIn("a top session", page)
        self.assertIn("## Sessions this session started", page)
        self.assertIn("Fix the dropped row", page)
        tops = phi.load_reports(self.t.p4, "")
        self.assertEqual(tops[-1]["sessionId"], TOP)
        self.assertTrue(os.path.exists(os.path.join(self.t.p4, "phi", "reports.jsonl")))
        self.assertIn("Narwhal exporter", read(os.path.join(self.t.p4, "phi", "sessions.md")))

    def test_a_report_goes_to_the_session_that_started_it_not_to_the_top(self):
        self.t.stop(GRAND, "bisect flush_rows", [], "It is commit abc.")
        self.assertEqual([r["sessionId"] for r in phi.load_reports(self.t.p4, KID)], [GRAND])
        self.assertEqual(phi.load_reports(self.t.p4, TOP), [])
        self.assertIn(f"started by `{KID}`", read(os.path.join(self.t.dir(GRAND), "session.md")))


class Background(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.record(KID2, TOP, "Check the ports table")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, host, source="startup"):
        return context(self.t.hook(START, host, {"hook_event_name": "SessionStart", "source": source}))

    def test_a_started_session_is_given_the_task_and_notes_above_it(self):
        r = self.t.cli(TOP, "note", "The ports table is written by flush_rows in export/flush.py",
                       "--source", "export/flush.py:40")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.start(KID)
        self.assertIn("background for this session", text)
        self.assertIn("the session that started it", text)
        self.assertIn(TASK, text)
        self.assertIn("flush_rows in export/flush.py", text)
        self.assertIn("export/flush.py:40", text)
        self.assertIn("Narwhal exporter", text)
        self.assertLessEqual(len(text), phi.BACKGROUND_CHARS)
        self.assertEqual(self.t.say(KID, HANDED).stdout.strip(), "")       # given once
        self.assertEqual([(r["hook"], r["said"] > 0, r["spawnedFrom"]) for r in self.t.log(KID)],
                         [(START, True, TOP), (PROMPT, False, TOP)])

    def test_background_missed_at_the_start_comes_with_the_first_message(self):
        self.assertIn(TASK, context(self.t.say(KID, HANDED)))

    def test_a_session_is_given_the_last_turn_of_the_others_started_beside_it(self):
        self.t.stop(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok"),
                                  ("Bash", {"command": "python -c \"x\""}, "No module named 'numpy'", 1)],
                    "Stopped: the fix needs the owner's word on the format.")
        text = self.start(KID2)
        self.assertIn("the other sessions \"Narwhal exporter\" started", text)
        self.assertIn("Fix the dropped row", text)
        self.assertIn("not shown done", text)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("the owner's word on the format", text)
        self.assertIn("numpy", text)
        self.assertNotIn("- \"Check the ports table\" (", text)     # not its own turns: it has none

    def test_the_next_top_session_is_given_the_one_before_whatever_its_words(self):
        self.t.stop(TOP, TASK, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        other = "local_top00002"
        self.t.record(other, title="Something else entirely")
        self.assertEqual(self.start(other), "")     # in the app a start is given nothing: who started it is unknown
        text = context(self.t.say(other, "paint the fence green"))
        self.assertIn("the top sessions in this project before this one", text)
        self.assertIn(TASK, text)
        self.assertIn("Half done.", text)

    def test_a_session_no_app_runs_is_given_it_at_its_start(self):
        self.t.stop(TOP, TASK, [], "Half done.")
        cli = "eeee5555-0000-4000-8000-000000000000"
        text = context(self.t.hook(START, "", {"hook_event_name": "SessionStart", "source": "startup"}, cli=cli))
        self.assertIn("Half done.", text)

    def test_a_note_needs_its_source(self):
        r = self.t.cli(TOP, "note", "The ports table is written by flush_rows")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("source", r.stderr)
        self.assertEqual(phi.load_notes(self.t.p4, TOP), [])

    def test_a_session_is_given_its_own_turns_after_a_compaction(self):
        self.t.stop(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        text = self.start(KID, "compact")
        self.assertIn("This session's own turns so far", text)
        self.assertIn("Half done.", text)
        self.assertIn("edited export/flush.py", text)

    def test_a_session_is_detached_to_a_top_session(self):
        self.t.stop(KID, HANDED, [], "Half done.")
        r = self.t.cli(TOP, "detach", KID)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.started_by(KID), ("", "detached"))
        self.assertNotIn("Half done.", self.start(KID2))            # no longer one of the sessions beside it
        self.assertEqual(phi.load_reports(self.t.p4, "")[-1]["sessionId"], KID)
        self.t.say(KID, "more")
        self.assertEqual(self.t.started_by(KID), ("", "detached"))  # the app's record does not put it back

    def test_a_session_is_reparented(self):
        self.t.record(GRAND, KID, "Bisect flush_rows")
        self.t.stop(GRAND, "bisect flush_rows", [], "It is commit abc.")
        r = self.t.cli(TOP, "reparent", GRAND, KID2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.started_by(GRAND), (KID2, "reparented"))
        self.assertEqual(phi.load_reports(self.t.p4, KID2)[-1]["sessionId"], GRAND)
        self.assertIn("It is commit abc.", context(self.t.say(KID2, "go on")))
        self.t.say(GRAND, "more")
        self.assertEqual(self.t.started_by(GRAND)[0], KID2)        # the app's record does not move it back
        self.assertNotEqual(self.t.cli(TOP, "reparent", KID2, GRAND).returncode, 0)    # no loops
        self.assertNotEqual(self.t.cli(TOP, "reparent", TOP, GRAND).returncode, 0)

    def test_the_tree_is_printed(self):
        self.t.stop(KID, HANDED, [], "Half done.")
        out = self.t.cli(TOP, "tree").stdout
        self.assertIn("- Narwhal exporter", out)
        self.assertIn("  - Fix the dropped row", out)
        self.assertIn("not shown done, 1 turn", out)

    def test_show_prints_a_sessions_page(self):
        out = self.t.cli(TOP, "show").stdout
        self.assertIn("# Narwhal exporter", out)
        self.assertIn(TASK, out)

    def test_off_is_off(self):
        self.t.cli(TOP, "note", "The ports table is written by flush_rows", "--source", "flush.py:40")
        r = self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"}, P4_PHI="0")
        self.assertEqual(r.stdout.strip(), "")
        self.assertFalse(os.path.exists(self.t.dir(KID)))


class NewTask(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")

    def tearDown(self):
        self._tmp.cleanup()

    def say(self, host, prompt, **more):
        return context(self.t.say(host, prompt, P4_PHI_NEW_TASK="1", **more))

    def test_the_instruction_comes_once_with_the_task_and_then_a_line(self):
        first = self.say(TOP, TASK)
        self.assertIn(TASK, first)
        self.assertIn("this session's task", first)
        self.assertIn("about something else", first)
        self.assertIn("start_session", first)
        self.assertIn("fork", first)
        self.assertIn("stay with the task", first)
        self.assertIn("the user", first)
        second = self.say(TOP, "also, what colour should the fence be?")
        self.assertIn(TASK, second)
        self.assertLess(len(second), 400)
        self.assertNotIn("start_session", second)
        self.assertNotIn("fence", second)                 # the task is the first request, not the newest words
        self.assertEqual([r.get("new_task") for r in self.t.log(TOP)], ["instruction", "line"])

    def test_the_harness_speaking_gets_no_line(self):
        self.say(TOP, TASK)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished a turn</side-sessions-event>"), "")
        self.assertEqual(self.say(TOP, "<task-notification>done</task-notification>"), "")

    def test_a_started_sessions_task_is_its_brief(self):
        self.say(TOP, TASK)
        text = self.say(KID, HANDED)
        self.assertIn(BRIEF, text)
        self.assertIn("start_session", text)

    def test_the_instruction_comes_again_after_a_compaction(self):
        self.say(TOP, TASK)
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "compact"}, P4_PHI_NEW_TASK="1")
        text = context(r)
        self.assertIn(TASK, text)
        self.assertIn("start_session", text)

    def test_the_task_is_changed_by_its_command(self):
        self.say(TOP, TASK)
        r = self.t.cli(TOP, "task", "Make the narwhal importer read the ports table back")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.t.session(TOP)
        self.assertEqual(s["task"], "Make the narwhal importer read the ports table back")
        self.assertEqual(s["earlierTasks"][0]["task"], TASK)        # the task before it is kept
        self.assertIn("importer", self.say(TOP, "go on"))
        self.assertNotEqual(self.t.cli(TOP, "task", "x").returncode, 0)

    def test_off_in_the_stores_settings(self):
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"new_task": False}))
        env = {k: v for k, v in self.t.env(TOP).items() if k != "P4_PHI_NEW_TASK"}
        for prompt in (TASK, "and the next part"):
            r = subprocess.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[TOP], "cwd": self.t.proj,
                                                                      "prompt": prompt}),
                               capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.stdout.strip(), "")


class NeverFails(unittest.TestCase):
    def test_broken_input_and_broken_files_end_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp)
            t.record(TOP)
            t.record(KID, TOP)
            for name in (START, PROMPT, STOP, "nonsense"):
                r = subprocess.run(["sh", RUN, name], input="{not json", capture_output=True, text=True,
                                   env=t.env(KID), timeout=60)
                self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), name)
            t.say(TOP, TASK)
            write(os.path.join(t.dir(TOP), "session.json"), "{broken")
            write(os.path.join(t.dir(TOP), "reports.jsonl"), "not json\n")
            write(os.path.join(t.app, KID + ".json"), "{broken")
            for name, payload in ((START, {"source": "startup"}), (PROMPT, {"prompt": "x"}),
                                  (STOP, {"transcript_path": os.path.join(tmp, "missing.jsonl")})):
                for host in (TOP, KID):
                    r = t.hook(name, host, payload)
                    self.assertEqual(r.returncode, 0, (name, host, r.stderr))
                    self.assertEqual(r.stderr.strip(), "", (name, host))


class Wiring(unittest.TestCase):
    def test_hooks_json(self):
        d = jload(HOOKS_JSON)["hooks"]
        self.assertEqual(sorted(d), ["SessionStart", "Stop", "UserPromptSubmit"])       # nothing around a tool call
        for event, name in (("SessionStart", START), ("UserPromptSubmit", PROMPT), ("Stop", STOP)):
            cmd = d[event][0]["hooks"][0]["command"]
            self.assertIn("run-hook.sh", cmd)
            self.assertTrue(cmd.endswith(" " + name), cmd)

    def test_manifests(self):
        p = jload(os.path.join(ROOT, ".claude-plugin", "plugin.json"))
        self.assertEqual(p["name"], "p4-phi")
        m = jload(os.path.join(os.path.dirname(os.path.dirname(ROOT)), ".claude-plugin", "marketplace.json"))
        self.assertIn("p4-phi", [x["name"] for x in m["plugins"]])
        self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", "phi", "SKILL.md")))

    def test_the_words_given_to_a_session_are_the_apps(self):
        src = read(os.path.join(HERE, "phi.py"))
        given = "\n".join(line for line in src.splitlines() if "f\"" in line or line.strip().startswith(("\"", "f'")))
        for word in ("ghost", "memo", "rollup", "node", "play", "steer", "owner", "goal"):
            self.assertNotRegex(given.lower(), rf"\b{word}s?\b", word)


if __name__ == "__main__":
    unittest.main(verbosity=1)
