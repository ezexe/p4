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
nothing to say; ezexe's standing instruction for a message about something else, once in full and then in a
line beside each of ezexe's messages, never beside the harness's; the task changed by its command; the hook
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
import relay  # noqa: E402

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
                    "P4_PHI_STORES": os.path.join(self.tmp, "p4-stores.json"),
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
            r = t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
            self.assertEqual((r.returncode, context(r)), (0, phi.builtin_text()), "AW1: the built-in rule, no store")
            r = t.say(TOP, TASK)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertFalse(os.path.exists(os.path.join(t.proj, ".claude")), "nothing written")

    def test_the_first_session_of_a_store_hears_nothing(self):
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual((r.returncode, context(r)), (0, phi.builtin_text()), "no store rules: the built-in one")
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
        self.assertNotIn("background for this session", self.start(KID), "a fresh child's start waits for its brief")
        text = context(self.t.say(KID, HANDED))
        self.assertIn("background for this session", text)
        self.assertIn("the session that started it", text)
        self.assertIn(TASK, text)
        self.assertIn("flush_rows in export/flush.py", text)
        self.assertIn("export/flush.py:40", text)
        self.assertIn("Narwhal exporter", text)
        self.assertNotIn("background for this session", context(self.t.say(KID, "go on")), "given once")
        self.assertEqual([(r["hook"], r["spawnedFrom"]) for r in self.t.log(KID)],
                         [(START, TOP), (PROMPT, TOP), (PROMPT, TOP)])

    def test_a_child_whose_cli_id_is_its_host_id_unprefixed_still_gets_its_background(self):
        # FB1: the app gives many started sessions a CLI id equal to the host id without "local_"
        same = KID2.removeprefix("local_")
        self.t.cli(TOP, "note", "The ports table is written by flush_rows in export/flush.py", "--source", "x")
        context(self.t.hook(START, KID2, {"hook_event_name": "SessionStart", "source": "startup"}, cli=same,
                            CLAUDE_CODE_SESSION_ID=same))
        text = context(self.t.hook(PROMPT, KID2, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED},
                                   cli=same, CLAUDE_CODE_SESSION_ID=same))
        self.assertIn("background for this session", text)
        self.assertIn(TASK, text)

    def test_background_missed_at_the_start_comes_with_the_first_message(self):
        self.assertIn(TASK, context(self.t.say(KID, HANDED)))

    def test_a_session_is_given_the_last_turn_of_the_others_started_beside_it(self):
        self.t.stop(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok"),
                                  ("Bash", {"command": "python -c \"x\""}, "No module named 'numpy'", 1)],
                    "Stopped: the fix needs ezexe's word on the format.")
        self.start(KID2)
        text = context(self.t.say(KID2, "Check the ports table"))          # no path named: the whole background
        self.assertIn("the other sessions \"Narwhal exporter\" started", text)
        self.assertIn("Fix the dropped row", text)
        self.assertIn("not shown done", text)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("ezexe's word on the format", text)
        self.assertIn("numpy", text)
        self.assertNotIn("- \"Check the ports table\" (", text)     # not its own turns: it has none

    def test_the_next_top_session_is_given_the_one_before_whatever_its_words(self):
        self.t.stop(TOP, TASK, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        other = "local_top00002"
        self.t.record(other, title="Something else entirely")
        self.assertEqual(self.start(other), phi.builtin_text())   # in the app a start is given no background:
        # who started it is unknown; it has the built-in rule, the store having none here
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
        self.assertIn("new top session", first)
        self.assertIn("`context` `fresh`", first)
        self.assertIn("stay with the task", first)
        self.assertIn("ezexe", first)
        second = self.say(TOP, "also, what colour should the fence be?")
        self.assertIn(TASK, second)
        self.assertLess(len(second), 400)
        self.assertNotIn("start_session", second)
        self.assertNotIn("fence", second)                 # the task is the first request, not the newest words
        self.assertEqual([r.get("new_task") for r in self.t.log(TOP)], ["instruction", "line"])

    def test_a_top_sessions_new_topic_is_a_new_top_session_detached_into_the_root(self):
        first = self.say(TOP, TASK)
        self.assertIn("A new topic gets a new top session of its own", first)
        self.assertIn("`initiation` `user_asked`", first)
        self.assertIn("`use_worktree: false`", first)
        self.assertIn(phi.NEW_TOP_BRIEF, first)
        self.assertIn("Its first act: `mcp__ccd_session_mgmt__detach_session` with `\"self\"`", first)
        self.assertIn("phi.py\" detach`", first, "the brief names phi's detach too")
        self.assertIn("call `mcp__ccd_session_mgmt__detach_session` with its id yourself", first,
                      "the starter's line names the app's move")
        self.assertIn("start a new top session", self.say(TOP, "also, the fence colour?"))
        told = self.say(KID, "Task:\nPick the fence colour. ezexe's words: \"the fence colour?\" "
                        + phi.NEW_TOP_BRIEF + " " + phi.new_top_first_act())
        self.assertIn("phi detached it into the root at this first message", told)
        self.assertIn("call `mcp__ccd_session_mgmt__detach_session` with `\"self\"`", told)
        self.assertNotIn("detached it into the root", self.say(KID, "and again"), "said at the first message only")
        s = phi.load_session(self.t.p4, KID)
        self.assertEqual(phi.spawned_from(s), "", "detached at its first hook")
        self.assertEqual(s["spawnedFrom"]["source"], "detached")
        self.assertEqual(s["spawnedFrom"]["from"], TOP)
        self.say(KID, "carry on")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID)), "", "the app's record does not undo it")
        self.assertIn(KID, relay._siblings(self.t.p4, phi.load_session(self.t.p4, TOP)), "tops are siblings")
        self.t.record(KID2, TOP, "a plain child")
        self.say(KID2, "Task:\nWrite the docs; this is not a new top")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), TOP, "an unmarked brief stays a child")
        r = self.t.cli(KID2, "detach")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), "", "phi.py detach with no id: itself")

    def test_a_detached_top_is_never_retired_onto_its_former_starter(self):
        """Retirement, archive lines and step roots read spawnedFrom.sessionId, never its `from`."""
        import plans
        self.say(TOP, TASK)
        stale = phi.load_session(self.t.p4, KID) or phi.ensure_session(self.t.p4, KID)
        self.say(KID, "Task:\nPick the fence colour, archive when done. " + phi.NEW_TOP_BRIEF)
        self.assertEqual(phi.load_session(self.t.p4, KID)["spawnedFrom"]["from"], TOP)
        phi.save_session(self.t.p4, dict(stale, spawnedFrom={"sessionId": TOP, "source": "record"}))
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID)), "", "an older copy never undoes a detach")
        self.t.hook("plan", KID, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                  "tool_input": {"items": [{"content": "Pick it", "status": "completed"}]},
                                  "tool_response": "Plan updated."})
        self.t.stop(KID, "Pick the fence colour", report="Picked green; done.")
        s = phi.load_session(self.t.p4, KID)
        self.assertFalse(s.get("doneRetired"), "a top session is retired onto nobody")
        self.assertEqual(plans.root_of(self.t.p4, s), "")
        self.assertFalse(phi.load_notes(self.t.p4, TOP), "no replaces: note on the former starter")
        self.assertNotIn(KID, json.dumps(phi.load_session(self.t.p4, TOP).get("staleChildren") or []))
        self.assertNotIn("Archive them now", self.say(TOP, "carry on"))

    def test_a_childs_new_topic_is_handed_up(self):
        self.say(TOP, TASK)
        first = self.say(KID, HANDED)
        self.assertIn(f"hand it up to the session that started this one with SendMessage (`to`: {TOP})", first)
        self.assertIn("start no session for it", first)
        self.assertNotIn("new top session of its own", first)
        line = self.say(KID, "and what about the fence?")
        self.assertIn(f"hand it up to {TOP}", line)
        self.assertNotIn("forked", line)

    def test_the_harness_speaking_gets_no_line(self):
        self.say(TOP, TASK)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished a turn</side-sessions-event>"), "")
        self.assertEqual(self.say(TOP, "<task-notification>done</task-notification>"), "")

    def test_a_turn_another_session_started_is_told_to_split_by_a_start_request(self):
        """The app refuses user_asked in a turn ezexe's words did not start: a split is a start request in the store."""
        self.say(TOP, TASK)
        text = self.say(TOP, '<cross-session-message from="local_x">please also look at Y</cross-session-message>')
        self.assertIn(" request \"<title>\" --brief", text, "a start request, not a card")
        self.assertNotIn("own_initiative", text)
        self.assertIn(phi.NEW_TOP_BRIEF, text)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished</side-sessions-event>"), "")
        self.say(KID, HANDED)
        kid = self.say(KID, '<cross-session-message from="local_x">please also look at Y</cross-session-message>')
        self.assertIn(" request \"<title>\" --brief", kid, "a child's split is a start request too")
        self.assertIn("Do not ask ezexe to type anything", kid)

    def test_a_deep_or_full_session_starts_no_session(self):
        """The caps: three deep in the tree, or eight live children."""
        home = self.t.p4
        self.say(TOP, TASK)
        chain = ["local_d1", "local_d2", "local_d3"]
        above = TOP
        for sid in chain:
            write(os.path.join(home, "phi", "sessions", sid, "session.json"),
                  json.dumps({"sessionId": sid, "spawnedFrom": {"sessionId": above}, "task": "t"}))
            above = sid
        self.assertEqual(phi.depth_of(home, phi.load_session(home, "local_d3")), 3)
        self.assertIn("start no session", phi.caps_text(home, phi.load_session(home, "local_d3")))
        self.assertEqual(phi.caps_text(home, phi.load_session(home, "local_d1")), "")
        for k in range(8):
            write(os.path.join(home, "phi", "sessions", f"local_k{k}", "session.json"),
                  json.dumps({"sessionId": f"local_k{k}", "spawnedFrom": {"sessionId": TOP}}))
        self.assertIn("live sessions of its own", phi.caps_text(home, phi.load_session(home, TOP)))

    def test_act_dont_wait_rides_with_the_rules(self):
        self.assertIn("act-don't-wait", phi.BUILT_IN)
        self.assertIn("authority", phi.BUILT_IN)

    def test_a_started_sessions_task_is_its_brief(self):
        self.say(TOP, TASK)
        text = self.say(KID, HANDED)
        self.assertIn(BRIEF, text)
        self.assertIn("hand it up", text)

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


def memory(p4, name, kind, body):
    write(os.path.join(p4, "temportal", "memory", name + ".md"),
          f"---\nname: {name}\ndescription: about {name}\nmetadata:\n  type: {kind}\n---\n\n{body}\n")


class Rules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.record(KID, TOP, "Fix the dropped row")
        p4 = self.t.p4
        memory(p4, "tabs-not-spaces", "feedback",
               "Indent with tabs in the exporter.\n\n**Why:** the boss's editor.\n\n**How to apply:** every file.")
        memory(p4, "long-rule", "feedback", "Run the ports check before a commit. " * 200)
        memory(p4, "where-the-build-is", "project", "The build lives in out/Narwhal.")
        write(os.path.join(p4, "temportal", "memory", "MEMORY.md"), "# Memory index\n\n- [Long](long-rule.md) — x\n"
              "- [Tabs](tabs-not-spaces.md) — y\n")

    def tearDown(self):
        self._tmp.cleanup()

    def start(self, host, source="startup"):
        return context(self.t.hook(START, host, {"hook_event_name": "SessionStart", "source": source}))

    def live(self, prompt, conf):
        return context(self.t.say(TOP, prompt, CLAUDE_CONFIG_DIR=conf))

    def test_a_reworded_memory_reaches_an_open_session_once(self):
        """#26: rules that change mid-session reach sessions already open."""
        conf = os.path.join(self._tmp.name, "conf")
        os.makedirs(conf)
        self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        self.assertNotIn("rules changed", self.live("Build the exporter", conf))
        memory(self.t.p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        got = self.live("carry on", conf)
        self.assertIn("the rules changed since this session last looked", got)
        self.assertIn("four spaces in the exporter", got)
        self.assertIn("Removed, no longer rules", got)
        self.assertIn("Indent with tabs in the exporter", got)
        self.assertNotIn("rules changed", self.live("and now", conf), "nothing repeats")

    def test_a_line_added_to_the_global_claude_md_reaches_an_open_session(self):
        conf = os.path.join(self._tmp.name, "conf")
        write(os.path.join(conf, "CLAUDE.md"), "# Global\n\n- Call the user ezexe.\n")
        self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        self.assertNotIn("rules changed", self.live("Build the exporter", conf))
        write(os.path.join(conf, "CLAUDE.md"), "# Global\n\n- Call the user ezexe.\n- Never write parentheticals.\n")
        got = self.live("carry on", conf)
        self.assertIn("global CLAUDE.md: - Never write parentheticals.", got)
        self.assertNotIn("Call the user ezexe", got, "only what changed")
        self.assertNotIn("rules changed", self.live("and now", conf), "nothing repeats")

    def test_every_session_starts_with_the_rules_and_not_the_projects_facts(self):
        for host in (TOP, KID):
            text = self.start(host)
            self.assertIn("standing rules", text)
            self.assertIn("- tabs-not-spaces: Indent with tabs in the exporter. **How to apply:** every file.", text)
            self.assertNotIn("the boss's editor", text)                 # the Why stays on the page
            self.assertNotIn("out/Narwhal", text)                       # a project memory is no rule
            self.assertLess(text.index("long-rule"), text.index("tabs-not-spaces"))     # the index's order
            self.assertLessEqual(len(text), phi.HOOK_CHARS)
            self.assertIn("...", text)

    def test_the_page_holds_every_rule_in_full(self):
        self.start(TOP)
        page = read(os.path.join(self.t.p4, "phi", "rules.md"))
        self.assertIn("**Why:** the boss's editor.", page)
        self.assertEqual(page.count("Run the ports check"), 200)
        self.assertNotIn("out/Narwhal", page)

    def test_a_resume_is_not_told_again_and_a_compaction_is(self):
        self.start(TOP)
        self.assertNotIn("standing rules", self.start(TOP, "resume"))
        self.assertIn("standing rules", self.start(TOP, "compact"))

    def test_rules_and_background_share_the_hooks_room(self):
        self.t.say(TOP, TASK)
        text = self.start(KID)
        self.assertIn("standing rules", text)
        self.assertLessEqual(len(text), phi.HOOK_CHARS)
        first = context(self.t.say(KID, HANDED))                         # a fresh child's background: its first message
        self.assertIn("background for this session", first)
        self.assertLessEqual(len(first), phi.HOOK_CHARS)

    def test_off_is_silence_and_no_memories_is_the_built_in_rule_alone(self):
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"rules": False}))
        self.assertEqual(self.start(TOP), "")
        os.remove(os.path.join(self.t.p4, "phi", "phi.json"))
        for f in os.listdir(os.path.join(self.t.p4, "temportal", "memory")):
            os.remove(os.path.join(self.t.p4, "temportal", "memory", f))
        self.assertEqual(self.start(TOP), phi.builtin_text(), "act-don't-wait holds in a project with no memories")

    def test_a_fork_gets_the_built_in_rule_alone(self):
        """A fork's inherited conversation already holds the store's rules."""
        self.assertEqual(phi.rules_text(self.t.p4, 9000, fork=True), phi.builtin_text())
        self.assertIn("act-don't-wait", phi.rules_text(self.t.p4, 9000))
        self.assertGreater(len(phi.rules_text(self.t.p4, 9000)), len(phi.builtin_text()))

    def test_act_dont_wait_yields_to_a_projects_go_ahead(self):
        """#23: a project rule that waits for ezexe's go makes that go ezexe's; p4.json can turn it off."""
        self.assertIn("that go is ezexe's to give", phi.BUILT_IN)
        self.assertIn("act-don't-wait", self.start(TOP))
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"act_dont_wait": False}}))
        got = self.start(TOP)
        self.assertNotIn("act-don't-wait", got)
        self.assertIn("tabs-not-spaces", got, "the project's own rules still come")
        try:
            phi.project_conf(self.t.p4)
            self.assertEqual(phi.builtin_text(), "")
        finally:
            phi.project_conf("")


class Ids(unittest.TestCase):
    def test_the_hosts_id_without_its_prefix_is_a_real_cli_session(self):
        # FB1: 58 of the app's 396 records pair the two ids this way; it is no stray id
        old = {k: os.environ.get(k) for k in ("CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
        os.environ["CLAUDE_CODE_HOST_SESSION_ID"] = "local_26c9fe71-aaaa"
        try:
            me = phi.Me({"session_id": "26c9fe71-aaaa"}, p4=tempfile.mkdtemp())
            self.assertEqual(me.cli, "26c9fe71-aaaa")
            self.assertEqual(me.id, "local_26c9fe71-aaaa")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class Wiring(unittest.TestCase):
    def test_hooks_json(self):
        d = {ev: [g for g in gs if all("/hooks/run-hook.sh" in x["command"] for x in g["hooks"])]
             for ev, gs in jload(HOOKS_JSON)["hooks"].items()}
        d = {ev: gs for ev, gs in d.items() if gs}                  # phi's own; recall's run recall-hook.sh
        self.assertEqual(sorted(d), ["SessionStart", "Stop", "UserPromptSubmit"],
                         "frozen: the checks around a tool call ride on recall's lookup entries (L3)")
        for event, name in (("SessionStart", START), ("UserPromptSubmit", PROMPT), ("Stop", STOP)):
            cmd = d[event][0]["hooks"][0]["command"]
            self.assertIn("run-hook.sh", cmd)
            self.assertTrue(cmd.endswith(" " + name), cmd)

    def test_runners_write_nothing_to_temp(self):
        """B1 of the marketplace test session: the proven interpreter is kept in the plugin's install, not %TEMP%."""
        for name in ("run-hook.sh", "recall-hook.sh"):
            with open(os.path.join(ROOT, "hooks", name), encoding="utf-8") as f:
                text = f.read()
            self.assertIn('known="${CLAUDE_PLUGIN_ROOT}/.python"', text, name)
            for word in ("TMPDIR", "TEMP", "/tmp"):
                self.assertNotIn(word, text.replace("%TEMP%", ""), f"{name} names {word}")

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
