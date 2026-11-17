#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

    python3 -I lbiza/plugins/p4-phi/scripts/test_phi.py

Checked: a handed-over task read out of its wrapper, a forked session's too, and a paste read as the person's own
words; a session's last turn with no human prompt, found from the transcript's end; which session started a session,
from the app's record, with nothing in the payload saying it; the sessions above it given their files from their
records; a `spawnedFrom` the app writes late read from the notes folder first and corrected by the record; a session
with no store of its own living in its parent session's store; every finished turn kept, done or not, once per turn;
its report appended to the parent session's reports and given to that session at its next message, once; a
worker given the tasks and notes of the sessions above it and the last turn of its siblings; an orchestrator
given the last turns of the orchestrators before it, with no likeness of words involved; a note refused without
a source; a session detached to top level, and reparented; a session's own turns after a compaction; silence where
there is nothing to say; the standing instruction for a message about something else, once in full and then in a
line beside each of ezexe's messages, never beside Claude Code's; a feature request as a new topic; a turn another
session began shown a suggested task card first and a start request second; the caps on depth and live children;
the task changed by its command; the rules built into p4-phi at a session's start, the store's feedback and user
memories never handed again as rule lines but whole on their page, and a changed line given once; the pieces past
the prompt's cap held on a page; a hook never failing a call; hooks.json's shape and the words given to a session.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import relay  # noqa: E402
import inproc  # noqa: E402

inproc.prepare(HERE)              # a hook or a command runs in this process, as its own process would run it
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
# P4_PHI_TEST_TMP names a folder the tests are given for their fixtures, in place of the system temp folder, so a
# run's fixtures, and anything a test leaves running there, sit in a folder its caller chose and clears. It must lie
# outside any git repository and any project with a store, since phi reads a fixture's repository and stores by
# walking up from it.
FIXTURES = os.environ.get("P4_PHI_TEST_TMP", "")
if FIXTURES:
    os.makedirs(FIXTURES, exist_ok=True)
    tempfile.tempdir = FIXTURES


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path, wait=5.0, gone=1.0):
    """The text of `path`. A file p4-phi rewrites goes in by os.replace, and on Windows a read that meets the replace
    raises PermissionError for a moment, or finds no file for a moment under load, so a refused read is tried again
    until `wait` runs out, and a missing file until `gone` does."""
    start = time.time()
    while True:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except PermissionError:
            if time.time() - start >= wait:
                raise
        except FileNotFoundError:
            if time.time() - start >= gone:
                raise
        time.sleep(0.02)


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
                    "P4_PHI_NEW_TASK": "0", "P4_PHI_WATCH": "0",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "claude-config"),   # never the machine's own settings
                    **more})
        if host:
            env["CLAUDE_CODE_HOST_SESSION_ID"] = host
            env["CLAUDE_CODE_SESSION_ID"] = CLI.get(host, host)
        return env

    def hook(self, name, host, payload=None, proj=None, cli=None, clock=None, **more):
        payload = {"session_id": cli or CLI.get(host, host), "cwd": proj or self.proj, **(payload or {})}
        return inproc.run(["sh", RUN, name], input=json.dumps(payload), capture_output=True, text=True,
                          env=self.env(host, proj, **more), timeout=60, clock=clock)

    def say(self, host, prompt, **more):
        return self.hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, **more)

    def cli(self, host, *args, proj=None, clock=None):
        return inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), *args],
                          capture_output=True, text=True, env=self.env(host, proj), cwd=proj or self.proj,
                          timeout=60, clock=clock)

    def stop(self, host, prompt, calls=(), report="done", uuid="u0", **kw):
        t = transcript(os.path.join(self.tmp, host + uuid + ".jsonl"), prompt, calls, report, uuid)
        return self.hook(STOP, host, {"hook_event_name": "Stop", "transcript_path": t,
                                      "last_assistant_message": report}, **kw)

    def dir(self, host):
        return os.path.join(self.p4, "phi", "sessions", host)

    def session(self, host):
        return jload(os.path.join(self.dir(host), "session.json"))

    def started_by(self, host):
        """The sessionId and source of a session's `spawnedFrom`, both '' for an orchestrator."""
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


APP_CAP = 10000     # hooks.md: a hook's text past this goes to a file, with a 2,000-character preview


def runs_of(sent, text, n=8):
    """The runs of `n` words of `sent` that `text` holds, compared word by word with case and punctuation dropped."""
    words = lambda x: re.findall(r"[a-z0-9']+", str(x).lower())                       # noqa: E731
    have = " " + " ".join(words(text)) + " "
    w = words(sent)
    return [" ".join(w[k:k + n]) for k in range(len(w) - n + 1) if " " + " ".join(w[k:k + n]) + " " in have]


def handed(brief):
    """A first message as the app hands it to a session another one started."""
    return ("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n"
            "</system-reminder>\n\nTask:\n" + brief + "\n\nDone looks like: the suite passes.")


HANDED = ("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n"
          "</system-reminder>\n\nBackground (from the session that started this one):\nezexe builds things.\n\n"
          "Task:\n" + BRIEF + "\n\nDone looks like: the suite passes.")



class Reading(unittest.TestCase):
    def test_a_file_replaced_in_a_loop_is_read_without_error(self):
        # the watcher rewrites ledger.md and watcher.json by os.replace while a test polls them
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.md")
            import puppeteer
            puppeteer._write(path, '{"n": 0}')
            stop, wrote = threading.Event(), [0]

            def replace():
                while not stop.is_set():
                    wrote[0] += 1
                    puppeteer._write(path, '{"n": %d}' % wrote[0])

            failed = []

            def run():
                try:
                    replace()
                except OSError as e:           # the writer is the watcher: a refused replace ends its look
                    failed.append(e)

            th = threading.Thread(target=run)
            th.start()
            reads, end = 0, time.time() + 3
            try:
                while time.time() < end:
                    self.assertIn('"n"', read(path))
                    reads += 1
            finally:
                stop.set()
                th.join()
            self.assertEqual(failed, [], "every replace went through")
            self.assertGreater(wrote[0], 100)
            self.assertGreater(reads, 100)

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

    def test_a_paste_only_message_is_the_persons_request(self):
        said = "Fix the port table.\nIt drops the last row."
        paste = '<pasted_content id="9b38">\n' + said + '\n</pasted_content id="9b38">\n'
        self.assertEqual(phi.request_of(paste), said)
        self.assertEqual(phi.request_of("<system-reminder>x</system-reminder>\n" + paste), said)
        self.assertEqual(phi.request_of("see this:\n" + paste), "see this:\n" + said)
        # Claude Code's own messages stay Claude Code's, whatever their bodies quote
        for wrapped in ('<task-notification><summary>ran ' + paste + '</summary></task-notification>',
                        '<cross-session-message from="local_x">look at ' + paste + '</cross-session-message>',
                        '<system-reminder>x</system-reminder>\n<side-sessions-event>' + paste + '</side-sessions-event>'):
            self.assertEqual(phi.request_of(wrapped), "", wrapped[:40])
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            tree.record(TOP)
            tree.say(TOP, TASK)
            tree.say(TOP, '<cross-session-message from="local_x">look at ' + paste + '</cross-session-message>')
            self.assertEqual(tree.session(TOP)["turnBy"], "session", "not the person's turn")
            self.assertEqual(tree.session(TOP)["task"], TASK)
        # a pasted page of markup is still the person's message
        self.assertEqual(phi.request_of('<pasted_content id="a1"><b>bold</b></pasted_content id="a1">'), "<b>bold</b>")
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            tree.record(TOP)
            tree.say(TOP, paste)
            s = tree.session(TOP)
            self.assertEqual(s["turnBy"], "user")
            self.assertEqual(s["task"], said)
            t = transcript(os.path.join(tmp, "t.jsonl"), paste, [], "ok")
            self.assertEqual(phi.last_turn(t)["prompt"], said)

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

    def test_the_last_turn_is_found_from_the_transcripts_end(self):
        """A turn that began in the transcript's last lines is found from its end, the same turn the whole file
        gives."""
        held = phi.TURN_WINDOWS
        with tempfile.TemporaryDirectory() as tmp:
            p = transcript(os.path.join(tmp, "t.jsonl"), BRIEF,
                           [("Edit", {"file_path": f"a/b{k}.py"}, "x" * 3000) for k in range(6)], "one")
            whole = phi.last_turn(p)
            self.assertEqual(len(whole["calls"]), 6)
            try:
                phi.TURN_WINDOWS = (2000, 6000)
                self.assertEqual(phi.last_turn(p), whole, "its request lies before both windows: the same turn")
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"type": "user", "uuid": "u2", "message": {"content": "and the docs"}}) + "\n")
                    f.write(json.dumps({"type": "assistant", "message": {"content": [
                        {"type": "tool_use", "id": "z", "name": "Write", "input": {"file_path": "a/docs.md"}}]}}) + "\n")
                near = phi.last_turn(p)
                self.assertEqual((near["prompt"], near["uuid"], len(near["calls"])), ("and the docs", "u2", 1))
                phi.TURN_WINDOWS = ()
                self.assertEqual(phi.last_turn(p), near, "the whole file gives the same turn")
            finally:
                phi.TURN_WINDOWS = held
            rows, end = phi.read_from(p, 0)
            self.assertEqual((len(rows), end), (16, os.path.getsize(p)))
            with open(p, "a", encoding="utf-8") as f:
                f.write('{"type": "user", "message": {"content": "a line still being wri')
            again, stop = phi.read_from(p, end)
            self.assertEqual((again, stop), ([], end), "a line with no newline yet waits for the next read")

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

    def test_no_session_is_told_a_scratchpad_directory_in_the_store(self):
        """ezexe/p4#241: the scratchpad is the app's, so no session, with a parent or none, is told a folder under the
        store's temportal/tmp, at its start, at its first message or at a start after a clear."""
        t = self.t
        said = []
        for host, first in ((TOP, TASK), (KID, HANDED)):
            said.append(context(t.hook(START, host, {"hook_event_name": "SessionStart", "source": "startup"})))
            said.append(context(t.say(host, first)))
            said.append(context(t.hook(START, host, {"hook_event_name": "SessionStart", "source": "clear"})))
        self.assertIn("background for this session", said[4], "the started session's first message ran")
        plugin = ROOT.replace("\\", "/")                   # a clone of the plugin may itself sit under such a folder
        for text in said:
            self.assertNotIn("temportal/tmp", text.replace("\\", "/").replace(plugin, "<plugin>"))
            self.assertNotIn("scratchpad directory is", text)

    def test_which_session_started_it_comes_from_the_apps_record(self):
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"})
        s = self.t.session(KID)
        self.assertEqual(s["spawnedFrom"], {"sessionId": TOP, "source": "record"})      # the app's own field name
        self.assertEqual(s["startChain"], {"firstSessionId": TOP, "depth": 1})
        self.assertEqual(s["title"], "Fix the dropped row")
        self.assertEqual(s["cliSessionIds"], [CLI[KID]])
        self.assertNotIn("spawnedFrom", self.t.session(TOP))       # an orchestrator: its record, started by none

    def test_a_fork_source_with_no_app_record_is_kept_as_a_fork(self):
        """ezexe/p4#144: hooks.md, SessionStart input, `source` is "fork" for a new session forked from an existing
        one, so a fork is known with no `forkedFromSessionId` in an app record."""
        lone = "local_fork00001"
        self.t.hook(START, lone, {"hook_event_name": "SessionStart", "source": "fork"})
        self.assertTrue(self.t.session(lone).get("forked"))
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertFalse(self.t.session(KID).get("forked"))

    def test_session_title_on_stdin_titles_a_session_with_no_app_record(self):
        """ezexe/p4#146: hooks.md, SessionStart and UserPromptSubmit carry `session_title`, the session's custom
        title; with no app record it is the session's title, and an app record's title still wins."""
        lone = "local_named0001"
        self.t.hook(START, lone, {"hook_event_name": "SessionStart", "source": "startup",
                                  "session_title": "Port the flush"})
        self.assertEqual(self.t.session(lone).get("title"), "Port the flush")
        self.t.hook(PROMPT, KID, {"hook_event_name": "UserPromptSubmit", "prompt": "fix it",
                                  "session_title": "Another name"})
        self.assertEqual(self.t.session(KID).get("title"), "Fix the dropped row")

    def test_configure_takes_an_integer_for_a_float_setting(self):
        """ezexe/p4#159: phi/phi.json's `"wait_s": 3` is a number for WAIT_S, which is a float."""
        os.makedirs(os.path.join(self.t.p4, "phi"), exist_ok=True)
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"wait_s": 3, "rules": 1}))
        before = (phi.WAIT_S, phi.RULES)
        try:
            phi.configure(self.t.p4)
            self.assertEqual(phi.WAIT_S, 3)
            self.assertEqual(phi.RULES, before[1], "a number is still not taken for a true/false setting")
        finally:
            phi.WAIT_S, phi.RULES = before

    def test_a_starters_process_never_adds_its_transcript_to_its_childs_record(self):
        """ezexe/p4#191: a hook of the starter's process that handles its child's record, as when it reads the
        child's report, reports the starter's transcript id; the child's cliSessionIds keep only the child's own."""
        self.t.say(TOP, "start the fix")
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"})
        self.t.say(KID, "fix it", cli=CLI[TOP])                     # the starter's transcript handles the child
        self.t.stop(KID, "fix it", report="Fixed.", cli=CLI[TOP])
        self.assertEqual(self.t.session(KID)["cliSessionIds"], [CLI[KID]])
        self.assertEqual(self.t.session(TOP)["cliSessionIds"], [CLI[TOP]])
        self.t.say(KID, "and the rest", cli=KID + "-resumed")      # a transcript no record names is the child's own
        self.assertEqual(self.t.session(KID)["cliSessionIds"], [CLI[KID], KID + "-resumed"])

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
        r = inproc.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[KID], "cwd": self.t.proj,
                                                              "prompt": BRIEF}),
                       capture_output=True, text=True, env=self.t.env(""), timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.t.started_by(KID), (TOP, "record"))

    def test_a_record_the_app_writes_late_is_waited_for(self):
        late = "local_late0001"
        write(os.path.join(self.t.app, late + ".json"), json.dumps({"sessionId": late, "cwd": self.t.proj}))
        self.t.hook(START, late, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(self.t.started_by(late), ("", ""))
        # the record is written on the call's own clock, at the hook's first wait past 0.4 s: only once the hook is
        # waiting, however late a loaded machine starts the hook
        c = inproc.Clock()
        c.after(0.4, lambda: self.t.record(late, TOP, "Late session"))
        self.t.say(late, HANDED, clock=c, P4_PHI_WAIT="5")
        self.assertEqual(self.t.started_by(late), (TOP, "record"))
        self.assertEqual(self.t.session(late)["title"], "Late session")
        self.assertGreaterEqual(self.t.log(late)[-1]["waited_ms"], 400, "it waited for the record")
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

    def test_a_session_with_no_store_lives_in_its_parent_sessions_store(self):
        work = os.path.join(self.t.tmp, "worktree")
        os.makedirs(work)
        self.t.record(KID, TOP, "Fix the dropped row", cwd=work)
        self.t.say(KID, HANDED, proj=work)
        self.assertTrue(self.t.session(KID)["task"].startswith(BRIEF))
        self.assertFalse(os.path.exists(os.path.join(work, ".claude")))

    def test_no_store_anywhere_gives_the_built_in_rules_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp, store=False)
            t.record(TOP)
            r = t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
            self.assertEqual((r.returncode, context(r)), (0, phi.builtin_text()), "the built-in rules, with no store")
            r = t.say(TOP, TASK)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertFalse(os.path.exists(os.path.join(t.proj, ".claude")), "nothing written")

    def test_the_first_session_of_a_store_hears_the_built_in_rules_alone(self):
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual((r.returncode, context(r)), (0, phi.builtin_text()), "no memories: the built-in rules")
        self.assertEqual(self.t.say(TOP, TASK).stdout.strip(), "")
        self.assertEqual(self.t.session(TOP)["task"], TASK)


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

    def test_the_report_reaches_the_parent_session_once(self):
        self.kid_stops()
        text = context(self.t.say(TOP, "<side-sessions-event>Fix the dropped row finished a turn</side-sessions-event>"))
        self.assertIn("reports of this session's workers", text)
        self.assertIn("Fix the dropped row", text)
        self.assertIn(LONG, text)                       # more than the 400 characters the app delivers
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

    def test_a_sessions_own_turn_lists_its_child_sessions(self):
        self.t.cli(KID, "done", "test_flush.py: 14 tests OK")
        self.kid_stops()
        self.t.stop(TOP, TASK, [], "The session I started fixed it.")
        t = self.t.turns(TOP)[0]
        self.assertEqual(t["sessions"], ["\"Fix the dropped row\": done"])
        page = read(os.path.join(self.t.dir(TOP), "session.md"))
        self.assertIn("# Narwhal exporter", page)
        self.assertIn("an orchestrator", page)
        self.assertIn("## Workers", page)
        self.assertIn("Fix the dropped row", page)
        for sent in (TASK, BRIEF):               # ezexe/p4#204: a child is pointed to this page, so it quotes no prompt
            self.assertEqual(runs_of(sent, page), [], sent)
        tops = phi.load_reports(self.t.p4, "")
        self.assertEqual(tops[-1]["sessionId"], TOP)
        self.assertTrue(os.path.exists(os.path.join(self.t.p4, "phi", "reports.jsonl")))
        self.assertIn("Narwhal exporter", read(os.path.join(self.t.p4, "phi", "sessions.md")))

    def test_a_report_goes_to_the_parent_session_not_to_the_top_level_session(self):
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

    def test_a_started_session_is_given_the_sessions_above_by_title_and_their_notes(self):
        r = self.t.cli(TOP, "note", "The ports table is written by flush_rows in export/flush.py",
                       "--source", "export/flush.py:40")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("background for this session", self.start(KID), "a fresh child's start waits for its brief")
        text = context(self.t.say(KID, HANDED))
        self.assertIn("background for this session", text)
        self.assertIn("from its parent session", text)
        self.assertNotIn(TASK, text, "the task above is named by its session's title")
        self.assertIn("by title; this session's task is part of the first's: \"Narwhal exporter\"", text)
        self.assertIn("flush_rows in export/flush.py", text)
        self.assertIn("export/flush.py:40", text)
        self.assertIn("Narwhal exporter", text)
        self.assertNotIn("background for this session", context(self.t.say(KID, "go on")), "given once")
        self.assertEqual([(r["hook"], r["spawnedFrom"]) for r in self.t.log(KID)],
                         [(START, TOP), (PROMPT, TOP), (PROMPT, TOP)])

    def test_a_child_whose_cli_id_is_its_host_id_unprefixed_still_gets_its_background(self):
        # the app gives many workers a CLI id equal to the host id without "local_"
        same = KID2.removeprefix("local_")
        self.t.cli(TOP, "note", "The ports table is written by flush_rows in export/flush.py", "--source", "x")
        context(self.t.hook(START, KID2, {"hook_event_name": "SessionStart", "source": "startup"}, cli=same,
                            CLAUDE_CODE_SESSION_ID=same))
        text = context(self.t.hook(PROMPT, KID2, {"hook_event_name": "UserPromptSubmit", "prompt": HANDED},
                                   cli=same, CLAUDE_CODE_SESSION_ID=same))
        self.assertIn("background for this session", text)
        self.assertIn("\"Narwhal exporter\"", text)

    def test_background_missed_at_the_start_comes_with_the_first_message(self):
        self.assertIn("\"Narwhal exporter\"", context(self.t.say(KID, HANDED)))

    def test_a_coworker_is_handed_no_run_of_the_prompts_above_it(self):
        """ezexe/p4#204: a coworker's first message, under a worker and an orchestrator, holds no run of eight words
        of the orchestrator's first prompt or of the worker's, and names the sessions above by title."""
        t = self.t
        t.stop(TOP, TASK, report="Planned the exporter; the dropped row goes to a worker.")
        t.say(KID, HANDED)
        t.stop(KID, HANDED, [], "Started a coworker to bisect.")
        t.record(GRAND, KID, "Bisect flush_rows")
        t.record("local_grand002", KID, "Time the flush")
        t.say("local_grand002", handed("Time each flush and say which one is slow."))
        t.stop("local_grand002", "Time each flush and say which one is slow.", [], "The third flush is slow.")
        text = context(t.say(GRAND, handed("Bisect the history of flush_rows for the commit that lost the row.")))
        self.assertIn("background for this session", text)
        self.assertIn("\"Fix the dropped row\", \"Narwhal exporter\"", text)
        self.assertIn("The third flush is slow.", text, "a sibling's turn by its report")
        for sent in (TASK, BRIEF, "Time each flush and say which one is slow."):
            self.assertEqual(runs_of(sent, text, 8 if len(sent.split()) >= 8 else len(sent.split())), [], sent)

    def test_a_session_is_given_the_last_turn_of_its_siblings(self):
        self.t.stop(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok"),
                                  ("Bash", {"command": "python -c \"x\""}, "No module named 'numpy'", 1)],
                    "Stopped: the fix needs ezexe's word on the format.")
        self.start(KID2)
        text = context(self.t.say(KID2, "Check the ports table"))          # no path named: the whole background
        self.assertIn("the other workers of \"Narwhal exporter\"", text)
        self.assertIn("Fix the dropped row", text)
        self.assertIn("not shown done", text)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("ezexe's word on the format", text)
        self.assertIn("numpy", text)
        self.assertNotIn("- \"Check the ports table\", ", text)     # not its own turns: it has none

    def test_a_session_with_no_title_is_named_by_its_id_and_never_by_its_prompt(self):
        """ezexe/p4#204: title_of falls back to a cut of a session's prompt, so a session with no title, such as a CLI
        one, is shown to others by its id: in a background, in a report row and in a turn's list of workers, and so on
        the pages a child is pointed to."""
        t = self.t
        t.record("local_grand002", KID, "Time the flush")
        sent = "Time each flush of the ports table and say which one of them is slow."
        t.say(KID, HANDED)
        t.say("local_grand002", handed(sent))
        for sid in (KID, "local_grand002"):                     # no title in the app's record or in p4-phi's
            for path in (os.path.join(t.app, sid + ".json"), os.path.join(t.dir(sid), "session.json")):
                d = jload(path)
                d.pop("title", None)
                write(path, json.dumps(d))
        t.stop("local_grand002", sent, [], "The third flush is slow.")
        t.stop(KID, HANDED, [], "Started a coworker to time the flush.")
        t.record(GRAND, KID, "Bisect flush_rows")
        text = context(t.say(GRAND, handed("Bisect the history of flush_rows for the commit that lost the row.")))
        self.assertIn(f"\"{KID}\"", text)
        self.assertIn("The third flush is slow.", text)
        pages = read(os.path.join(t.dir(TOP), "session.md")) + read(os.path.join(t.dir(KID), "session.md"))
        self.assertIn(f"\"local_grand002\"", pages)
        for said in (BRIEF, sent):
            self.assertEqual(runs_of(said, text), [], said)
            self.assertEqual(runs_of(said, pages), [], said)

    def test_the_next_top_level_session_is_given_the_one_before_whatever_its_words(self):
        self.t.stop(TOP, TASK, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        other = "local_top00002"
        self.t.record(other, title="Something else entirely")
        self.assertEqual(self.start(other), phi.builtin_text())   # in the app a start is given no background,
        # since its parent session is not known yet; it has the built-in rules, the store having no memories here
        text = context(self.t.say(other, "paint the fence green"))
        self.assertIn("the orchestrators in this project before this one", text)
        self.assertIn("\"Narwhal exporter\"", text)
        self.assertNotIn(TASK, text, "its turn by its title and report, never its prompt")
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

    def test_a_session_is_detached_to_top_level(self):
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
        self.assertIn("- \"Narwhal exporter\" `", out)
        self.assertIn("  - \"Fix the dropped row\" `", out)
        self.assertIn("not shown done, 1 turn", out)

    def test_show_prints_a_sessions_page(self):
        out = self.t.cli(TOP, "show").stdout
        self.assertIn("# Narwhal exporter", out)
        self.assertIn("an orchestrator", out)

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
        self.assertIn("new orchestrator", first)
        self.assertIn("`context` `fresh`", first)
        self.assertIn("stay with the task", first)
        self.assertIn("ezexe", first)
        second = self.say(TOP, "also, what colour should the fence be?")
        self.assertIn(TASK, second)
        self.assertLess(len(second), 400)
        self.assertNotIn("start_session", second)
        self.assertNotIn("fence", second)                 # the task is the first request, not the newest words
        self.assertEqual([r.get("new_task") for r in self.t.log(TOP)], ["instruction", "line"])

    def test_a_top_level_sessions_new_topic_is_a_new_top_level_session_detached_to_top_level(self):
        first = self.say(TOP, TASK)
        self.assertIn("A new topic gets a new orchestrator of its own", first)
        self.assertIn("`initiation` `user_asked`", first)
        self.assertIn("`use_worktree: false`", first)
        self.assertIn(phi.NEW_TOP_BRIEF, first)
        self.assertIn("Its first act: `mcp__ccd_session_mgmt__detach_session` with `\"self\"`", first)
        self.assertIn("phi.py\" detach`", first, "the brief names phi.py's detach too")
        self.assertIn("call `mcp__ccd_session_mgmt__detach_session` with its id yourself", first,
                      "the parent session's line names the app's move")
        self.assertIn("start a new orchestrator", self.say(TOP, "also, the fence colour?"))
        told = self.say(KID, "Task:\nPick the fence colour. ezexe's words: \"the fence colour?\" "
                        + phi.NEW_TOP_BRIEF + " " + phi.new_top_first_act())
        self.assertIn("p4-phi detached it to top level at this first message", told)
        self.assertIn("call `mcp__ccd_session_mgmt__detach_session` with `\"self\"`", told)
        self.assertNotIn("detached it to top level", self.say(KID, "and again"), "said at the first message only")
        s = phi.load_session(self.t.p4, KID)
        self.assertEqual(phi.spawned_from(s), "", "detached at its first hook")
        self.assertEqual(s["spawnedFrom"]["source"], "detached")
        self.assertEqual(s["spawnedFrom"]["from"], TOP)
        self.say(KID, "carry on")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID)), "", "the app's record does not undo it")
        self.assertIn(KID, relay._siblings(self.t.p4, phi.load_session(self.t.p4, TOP)),
                      "orchestrators are siblings")
        self.t.record(KID2, TOP, "a plain child")
        self.say(KID2, "Task:\nWrite the docs; this is not a new top")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), TOP, "an unmarked brief stays a child")
        r = self.t.cli(KID2, "detach")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), "", "phi.py detach with no id: itself")

    def test_a_feature_request_in_a_broadly_tasked_top_is_a_new_topic(self):
        """A broad task does not swallow every feature."""
        self.say(TOP, "Sort out the claude dev desktop app files in appdata or temp, and the plugins around them")
        got = self.say(TOP, "build the issue loop")
        self.assertIn("asks for something new that is not in this session's task list", got)
        self.assertIn(phi.NEW_TOP_BRIEF, got)
        for plain in ("fix this typo", "check that the scratchpad link works"):
            self.assertNotIn("something new", self.say(TOP, plain), plain)
        r = self.t.hook("plan", TOP, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                      "tool_input": {"items": [{"content": "Build the child-session issue loop feature",
                                                                "status": "pending"},
                                                               {"content": "Move the tmp folders", "status": "pending"}]},
                                      "tool_response": "Plan updated."}, P4_PHI_NEW_TASK="1")
        ctx = context(r)
        self.assertIn("step 1 \"Build the child-session issue loop feature\" is a new feature", ctx)
        self.assertNotIn("step 2 \"Move", ctx.split("is a new feature")[0])
        self.assertNotIn("something new", self.say(TOP, "add the issue loop's tests"),
                         "a message on an open step of the task list is that step's")

    def test_a_detached_top_level_session_is_never_counted_as_archived_on_its_former_parent(self):
        """Counting as archived, the archive lines and parent steps read spawnedFrom.sessionId, never its `from`."""
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
        self.assertFalse(s.get("doneRetired"), "an orchestrator is counted as archived on no parent")
        self.assertEqual(plans.root_of(self.t.p4, s), "")
        self.assertFalse(phi.load_notes(self.t.p4, TOP), "no replaces: note on the former parent session")
        self.assertNotIn(KID, json.dumps(phi.load_session(self.t.p4, TOP).get("staleChildren") or []))
        self.assertNotIn("counts them as archived", self.say(TOP, "carry on"))

    def test_the_detach_notice_reaches_a_new_orchestrator_whose_brief_names_the_plugin_at_a_long_path(self):
        """The lines beside a prompt repeat the plugin's path, and a notice that asks the session to act now is never
        the piece held for want of room. A new orchestrator's brief names phi.py where a landing clone keeps the
        plugin, 106 characters deep, so its first message gets the new-task instruction and a start draft that fill
        the room, and the detach notice still reaches it whole."""
        land = "E:/projects/p4-phi/.claude/p4/temportal/tmp/83e32f0d-9d33-427a-93fc-f0c8db9acc23/land/lbiza/plugins/p4-phi"
        script = os.path.join(HERE, "phi.py").replace("\\", "/")
        brief = phi.NEW_TOP_BRIEF + " " + phi.new_top_first_act().replace(script, land + "/scripts/phi.py")
        self.assertIn(land, brief)
        self.say(TOP, TASK)
        self.say(TOP, "also, the fence colour?")
        told = self.say(KID, "Task:\nPick the fence colour and update the fence. ezexe's words: \"the fence colour?\" "
                        + brief)                         # a work word of the brief's own, not of the plugin's path
        self.assertIn("did not fit", told, "the room is full, so pieces are held")
        self.assertIn("p4-phi detached it to top level at this first message. Now call "
                      "`mcp__ccd_session_mgmt__detach_session` with `\"self\"` before anything else", told)
        self.assertLessEqual(len(told), phi.PROMPT_CHARS)

    def test_a_childs_new_topic_is_handed_up(self):
        self.say(TOP, TASK)
        first = self.say(KID, HANDED)
        self.assertIn(f"hand it up to your parent session, {TOP}, with SendMessage, holding {phi.RESTATE}", first)
        self.assertIn("start no session for it", first)
        self.assertNotIn("new orchestrator of its own", first)
        line = self.say(KID, "and what about the fence?")
        self.assertIn(f"hand it up to {TOP}", line)
        self.assertNotIn("forked", line)

    def test_the_harness_speaking_gets_no_line(self):
        self.say(TOP, TASK)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished a turn</side-sessions-event>"), "")
        self.assertEqual(self.say(TOP, "<task-notification>done</task-notification>"), "")

    def test_a_turn_another_session_started_is_told_to_split_by_a_card_then_a_start_request(self):
        """The app refuses user_asked in a turn ezexe's words did not start: a split is a suggested task card ezexe
        presses in this session, and a start request in the store only when the card is refused too."""
        self.say(TOP, TASK)
        text = self.say(TOP, '<cross-session-message from="local_x">please also look at Y</cross-session-message>')
        self.assertIn("`initiation` `own_initiative`, which ezexe presses in this session", text)
        self.assertIn(" request \"<title>\" --brief", text, "the request, where the card is refused too")
        self.assertNotIn("any session of this store", text)
        self.assertIn(phi.NEW_TOP_BRIEF, text)
        again = self.say(TOP, '<cross-session-message from="local_x">and Z as well</cross-session-message>')
        self.assertNotIn(phi.NEW_TOP_BRIEF, again, "said once in full, then a line with its page")
        self.assertIn("standing.md", again)
        self.assertLess(len(again), 400)
        self.assertIn(phi.NEW_TOP_BRIEF, read(os.path.join(self.t.dir(TOP), "standing.md")))
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished</side-sessions-event>"), "")
        self.say(KID, HANDED)
        kid = self.say(KID, '<cross-session-message from="local_x">please also look at Y</cross-session-message>')
        self.assertIn("`initiation` `own_initiative`", kid, "a child's split is a card too")
        self.assertIn(" request \"<title>\" --brief", kid)

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

    def test_a_project_sets_its_caps_in_p4_json(self):
        """ezexe/p4#125: the caps a project would decide are p4.json `phi` keys; a value of the wrong type or out of
        range keeps the default, and a store that sets none gets the defaults back."""
        import controls
        import plans
        import puppeteer
        home = self.t.p4
        self.say(TOP, TASK)
        write(os.path.join(home, "p4.json"), json.dumps({"phi": {
            "max_depth": 1, "max_children": 2, "sibling_turns": 1, "own_turns": 1, "chain_max": 2, "turn_steps": 4,
            "tree_checks": 2, "keep_going_max": 1, "compactions": 5, "watch_s": 10, "stale_s": 3600}}))
        try:
            phi.project_conf(home)
            self.assertEqual((phi.MAX_DEPTH, phi.MAX_CHILDREN, phi.OTHERS, phi.OWN, phi.CHAIN_MAX, phi.TURN_STEPS,
                              phi.TREE_CHECKS), (1, 2, 1, 1, 2, 4, 2))
            self.assertEqual((plans.KEEP_GOING_MAX, controls.COMPACTIONS, puppeteer.WATCH_S, puppeteer.STALE_S),
                             (1, 5, 10.0, 3600.0))
            write(os.path.join(home, "phi", "sessions", KID, "session.json"),
                  json.dumps({"sessionId": KID, "spawnedFrom": {"sessionId": TOP}, "task": "t"}))
            self.assertIn("start no session", phi.caps_text(home, phi.load_session(home, KID)), "one deep is the most")
            write(os.path.join(home, "p4.json"), json.dumps({"phi": {
                "max_depth": "3", "max_children": 0, "keep_going_max": 9, "watch_s": True}}))
            phi.project_conf(home)
            self.assertEqual((phi.MAX_DEPTH, phi.MAX_CHILDREN, plans.KEEP_GOING_MAX, puppeteer.WATCH_S),
                             (3, 8, 2, 5.0), "a value that does not fit keeps the default")
            self.assertEqual((phi.OTHERS, controls.COMPACTIONS, puppeteer.STALE_S), (5, 3, 86400.0), "and unset ones")
        finally:
            phi.project_conf("")

    def test_act_dont_wait_rides_with_the_rules(self):
        self.assertIn("act-don't-wait", phi.BUILT_IN)
        self.assertIn("authority", phi.BUILT_IN)
        self.assertIn("ends each turn with one SendMessage line to the starter", phi.BUILT_IN, "ezexe/p4#157")

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
        self.assertIn("start a new orchestrator", text)
        page = os.path.join(self.t.dir(TOP), "standing.md").replace("\\", "/")
        self.assertIn(page, text, "after a compaction, a line with its page, not the instruction in full")
        self.assertNotIn("start_session", text)
        self.assertIn("start_session", read(page), "the page holds it whole")

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
            r = inproc.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[TOP], "cwd": self.t.proj,
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
                r = inproc.run(["sh", RUN, name], input="{not json", capture_output=True, text=True,
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

    def test_a_failing_hook_leaves_a_line_naming_it_and_its_error(self):
        """A hook whose handler raises still ends quietly, and its session's log.jsonl names the hook and the error."""
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp)
            t.record(TOP)
            t.say(TOP, TASK)

            def broken(payload):
                raise ValueError("the handler broke")

            payload = {"session_id": CLI.get(TOP, TOP), "cwd": t.proj, "hook_event_name": "Stop",
                       "transcript_path": os.path.join(tmp, "missing.jsonl")}
            r = inproc.run(["sh", RUN, STOP], input=json.dumps(payload), capture_output=True, text=True,
                           env=t.env(TOP), timeout=60, stand_ins={"phi.HOOKS": {**phi.HOOKS, STOP: ("Stop", broken)}})
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            rows = t.log(TOP)
            self.assertTrue(any(x.get("hook") == STOP and "ValueError: the handler broke" in str(x.get("error"))
                                for x in rows), rows[-3:])


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
               "Indent with tabs in the exporter.\n\n**Why:** ezexe's editor.\n\n**How to apply:** every file.")
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
        """Rules that change mid-session reach sessions already open."""
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

    def test_each_memory_reaches_a_session_once(self):
        """ezexe/p4#130: a memory's line in the index is the one form a session is handed at its start, so p4-phi
        hands the built-in rules whole and no line of a feedback or user memory, at a start, a clear or a compaction."""
        for host in (TOP, KID):
            for source in ("startup", "clear", "compact"):
                text = self.start(host, source)
                self.assertIn("- " + phi.BUILT_IN, text, (host, source))
                for word in ("tabs-not-spaces", "Indent with tabs", "long-rule", "Run the ports check", "out/Narwhal"):
                    self.assertNotIn(word, text, (host, source))
                self.assertLessEqual(len(text), APP_CAP)

    def test_the_page_holds_every_rule_in_full(self):
        self.start(TOP)
        page = read(os.path.join(self.t.p4, "phi", "rules.md"))
        self.assertIn("**Why:** ezexe's editor.", page)
        self.assertEqual(page.count("Run the ports check"), 200)
        self.assertNotIn("out/Narwhal", page)

    def test_a_resume_is_not_told_again_and_a_compaction_is(self):
        self.start(TOP)
        self.assertNotIn("act-don't-wait", self.start(TOP, "resume"))
        self.assertIn("act-don't-wait", self.start(TOP, "compact"))

    def test_pieces_past_the_cap_are_held_on_a_page_and_named_by_count(self):
        """The text beside one prompt has a hard ceiling; what does not fit is named by count and page."""
        home = self.t.p4
        self.t.say(TOP, TASK)
        parts = ["first piece " + "a" * 1500, "second piece " + "b" * 3000, "third piece " + "c" * 2500, "last line"]
        text = phi.fit(parts, phi.PROMPT_CHARS, home, TOP)
        self.assertLessEqual(len(text), phi.PROMPT_CHARS)
        self.assertIn("first piece", text)
        self.assertIn("last line", text, "a short piece after a long one still fits")
        self.assertIn("2 of the pieces p4-phi had for this prompt", text)
        self.assertIn("They begin: \"second piece bbbb", text, "each held piece is named by how it begins")
        self.assertIn("\"third piece cccc", text)
        self.assertNotIn("b" * 200, text, "no piece is shown cut")
        asks = "phi (p4-phi): start requests from sessions whose turns ezexe did not begin: " + "x" * 5000
        text = phi.fit(["a short line", asks], phi.PROMPT_CHARS, home, TOP)
        self.assertLessEqual(len(text), phi.PROMPT_CHARS)
        self.assertIn("They begin: \"start requests from sessions whose turns ezexe did not begin", text)
        self.assertIn("Read that page before going on", text)
        held = read(os.path.join(self.t.dir(TOP), "held.md"))
        self.assertIn("b" * 3000, held)
        self.assertIn("c" * 2500, held)
        self.assertEqual(phi.fit(["x", "y"], 100, home, TOP), "x\n\ny", "what fits is untouched")

    def test_the_built_in_rules_come_beside_the_background(self):
        self.t.say(TOP, TASK)
        text = self.start(KID)
        self.assertIn("act-don't-wait", text)
        self.assertLessEqual(len(text), APP_CAP)
        first = context(self.t.say(KID, HANDED))                         # a fresh child's background: its first message
        self.assertIn("background for this session", first)
        self.assertLessEqual(len(first), APP_CAP)

    def test_the_start_and_first_message_text_past_9500_characters_passes_whole_act_lines_first(self):
        """ezexe/p4#243 D9: p4-phi cuts no text of its own at a session's start or first message; past 10,000
        characters the app's own overflow file takes it, so the lines that ask the session to act come first, inside
        the app's preview, and the rest follows whole."""
        t = self.t
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"background_chars": 12000}))
        t.say(TOP, TASK)
        for k in range(12):                                         # notes long enough to fill a 12,000 background
            r = t.cli(TOP, "note", f"replaces: part {k} of the old exporter, " + "the ports table rows. " * 200,
                      "--source", f"export/part{k}.py:1")
            self.assertEqual(r.returncode, 0, r.stderr)
        t.stop(TOP, TASK, report="Half done: " + "the flush writes the ports table. " * 40)
        first = context(t.say(KID, HANDED))
        self.assertGreater(len(first), 9500)
        self.assertIn("Each turn's report is kept either way", first, "the background's last line, whole")
        self.assertNotIn("did not fit", first)
        self.assertFalse(os.path.exists(os.path.join(t.dir(KID), "held.md")), "no page of p4-phi's own")
        self.assertLess(first.index("phi (p4-phi): this is this session's first message"),
                        first.index("background for this session"), "the act line leads, inside the app's preview")
        self.assertLessEqual(len(context(t.say(KID, "go on"))), phi.PROMPT_CHARS, "a later prompt keeps its room")
        start = context(t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "clear"}, P4_PHI_NEW_TASK="1"))
        self.assertGreater(len(start), 9500)
        self.assertIn("Each turn's report is kept either way", start, "the background's last line, whole")
        act = start.index("When a message from ezexe is about something else")
        self.assertLess(act, 2000, "inside the app's 2,000-character preview")
        self.assertLess(act, start.index("act-don't-wait"), "what asks it to act comes before the rules")
        self.assertLess(start.index("act-don't-wait"), start.index("background for this session"))

    def test_an_orchestrators_long_command_runs_as_sent(self):
        """ezexe/p4#243 D4: the app moves a foreground command to the background at its timeout, so p4-phi returns
        no `updatedInput` for an orchestrator's lone test command, only the line."""
        t = self.t
        t.say(TOP, TASK)
        inp = {"command": "cd scripts && python -I -X utf8 test_flush.py 2>&1 | tail -3", "description": "Run tests"}
        body = {"session_id": CLI[TOP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": inp, "tool_use_id": "toolu_d4"}
        r = inproc.run(["sh", os.path.join(ROOT, "hooks", "recall-hook.sh"), "lookup-check"], input=json.dumps(body),
                       capture_output=True, text=True, timeout=60,
                       env=t.env(TOP, CLAUDE_PLUGIN_DATA=os.path.join(t.tmp, "data")))
        self.assertEqual((r.returncode, r.stderr.strip()), (0, ""))
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertNotIn("updatedInput", out, "the call runs as sent")
        self.assertNotIn("permissionDecision", out)
        self.assertIn("on a call of its own with `run_in_background: true`", out["additionalContext"])

    def test_the_start_text_carries_every_line_with_any_background(self):
        """A puppeteer whose p4.json names a shared store this machine has not seen, started again after a
        clear and after a compaction, with the default start background and with one set longer than the app's cap:
        each start text carries the standing instruction, the missing-home line and the rules, and stays within the
        app's cap with the default background; after a compaction the line that names its board comes first."""
        t = self.t
        write(os.path.join(t.tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": [{"id": "cg-1", "name": "puppeteers"}],
                                                 "assignments": {"code:" + TOP: "cg-1"}}}}}}))
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/elsewhere.git"}}))
        t.say(TOP, TASK, P4_PHI_NEW_TASK="1")
        calls = ([("Edit", {"file_path": f"src/export/flush_part_{k}.py"}, "ok") for k in range(14)]
                 + [("Bash", {"command": f"python -I tests/test_part_{k}.py"}, f"No module named 'part{k}'", 1)
                    for k in range(4)])
        for n, host in enumerate([f"local_top0000{k}" for k in range(2, 6)] + [TOP] * 3):
            if host != TOP:
                t.record(host, title=f"Narwhal importer, part {n}")
            t.stop(host, "Build the next part of the narwhal tools and check it. " * 5, calls,
                   "Built and checked: " + "the part reads the ports table back and its check passes. " * 8,
                   uuid=f"u{n}")
        sizes = {}
        for chars in (phi.BACKGROUND_CHARS, 2 * APP_CAP):
            write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"background_chars": chars}))
            for source in ("clear", "compact"):
                text = context(t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": source},
                                      P4_PHI_NEW_TASK="1"))
                sizes[f"{source}, background_chars {chars}"] = len(text)
                self.assertIn("When a message from ezexe is about something else", text, source)
                self.assertIn("names the shared store git@example.com:team/elsewhere.git", text, source)
                self.assertIn("act-don't-wait", text, "the built-in rules come with any background")
                if source == "compact":
                    self.assertTrue(text.startswith("phi (p4-phi): this session is a puppeteer and its "
                                                    "context was compacted"), text[:200])
        self.assertLessEqual(max(v for k, v in sizes.items() if k.endswith(str(phi.BACKGROUND_CHARS))), APP_CAP, sizes)

    def test_past_the_apps_cap_the_act_lines_and_notices_lead_and_the_address_book_comes_last(self):
        """ezexe/p4#243 D9: past 10,000 characters the app hands Claude a preview of the first 2,000 and the file's
        path. A clear's start text with a long background and a long address book keeps the notices and the
        standing instruction inside that preview, the built-in rules before the background, and the book last."""
        t = self.t
        subprocess.run(["git", "init", "-q", t.p4], check=True, capture_output=True)
        gd = subprocess.run(["git", "-C", t.p4, "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True).stdout.strip()
        write(os.path.join(gd, relay.TRACK_STATE), json.dumps(
            {"fails": 1, "next": time.time() + 3600, "reason": "index.lock is held", "owed": []}))
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True,
                                                                  "home": "git@example.com:team/elsewhere.git"}}))
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"background_chars": 2 * APP_CAP}))
        t.say(TOP, TASK, P4_PHI_NEW_TASK="1")
        for k in range(24):
            host = f"local_wkr{k:05d}"
            t.record(host, TOP, f"Port part {k} of the narwhal exporter's flush to the new writer")
            t.say(host, f"Port part {k} of the flush.\nFiles: src/export/flush_part_{k}.py, tests/test_part_{k}.py")
        calls = [("Edit", {"file_path": f"src/export/flush_part_{k}.py"}, "ok") for k in range(14)]
        for n in range(3):
            t.stop(TOP, "Build the next part of the narwhal tools and check it. " * 5, calls,
                   "Built and checked: " + "the part reads the ports table back and its check passes. " * 8,
                   uuid=f"u{n}")
        text = context(t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "clear"},
                              P4_PHI_NEW_TASK="1"))
        self.assertGreater(len(text), APP_CAP, "past the app's cap, so only the preview is seen whole")
        for line in ("the session tree's first commit in", "names the shared store git@example.com:team/elsewhere.git",
                     "When a message from ezexe is about something else"):
            self.assertIn(line, text)
            self.assertLessEqual(text.index(line) + len(line), 2000, f"inside the app's preview: {line}")
        book = text.index("this session's address book")
        for later in ("built-in, act-don't-wait", "built-in, levels", "background for this session"):
            self.assertLess(text.index(later), book, f"{later} comes before the address book")
        self.assertLess(text.index("built-in, levels"), text.index("background for this session"))

    def test_off_is_silence_and_no_memories_is_the_built_in_rules_alone(self):
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"rules": False}))
        self.assertEqual(self.start(TOP), "")
        os.remove(os.path.join(self.t.p4, "phi", "phi.json"))
        for f in os.listdir(os.path.join(self.t.p4, "temportal", "memory")):
            os.remove(os.path.join(self.t.p4, "temportal", "memory", f))
        self.assertEqual(self.start(TOP), phi.builtin_text(), "act-don't-wait holds in a project with no memories")

    def test_the_built_in_rule_names_research_and_the_decisions_file(self):
        """A question research can answer is decided by the session and logged with its source, never put to ezexe."""
        line = next(x for x in self.start(TOP).splitlines() if "act-don't-wait" in x)
        for word in ("code", "history", "issues", "documentation", "decisions file", "decisions.md", "source"):
            self.assertIn(word, line)

    def test_many_memories_leave_the_start_text_as_it_is(self):
        """However many memories the store holds, the start carries the built-in rules whole and none of them."""
        for k in range(400):
            memory(self.t.p4, f"a-rather-long-memory-name-number-{k:03d}", "feedback", f"Rule {k} of the many.")
        for source in ("startup", "clear", "compact"):
            got = self.start(KID, source)
            self.assertIn("- " + phi.BUILT_IN, got, source)
            self.assertNotIn("a-rather-long-memory-name", got, source)
        self.assertIn("Rule 399 of the many.", read(os.path.join(self.t.p4, "phi", "rules.md")), "the page holds them")

    def test_a_failed_first_commit_is_told_at_the_next_start_once(self):
        """ezexe/p4#218: a store whose index.lock fails the tree's first commit; the next start says so once."""
        p4 = self.t.p4
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", p4, *args], check=True, capture_output=True)
        write(os.path.join(p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        gd = subprocess.run(["git", "-C", p4, "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True).stdout.strip()
        write(os.path.join(gd, "index.lock"), "")               # a stale lock of git's own: every commit fails
        self.assertFalse(relay.track(p4, first_only=True, wait=True))
        told = self.start(TOP)
        self.assertEqual(told.count("the session tree's first commit in"), 1, told)
        self.assertIn("index.lock", told)
        self.assertNotIn("the session tree's first commit in", self.start(TOP), "said once")

    def test_a_fork_gets_the_built_in_rules_alone(self):
        """A fork's inherited conversation already holds the store's feedback and user memories, and so does every
        other session's start."""
        self.assertEqual(phi.rules_text(self.t.p4, fork=True), phi.builtin_text())
        self.assertEqual(phi.rules_text(self.t.p4), phi.builtin_text())

    def test_act_dont_wait_yields_to_a_projects_go_ahead(self):
        """A project rule that waits for ezexe's go makes that go ezexe's; p4.json can turn it off."""
        self.assertIn("that go is ezexe's to give", phi.BUILT_IN)
        self.assertIn("act-don't-wait", self.start(TOP))
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"act_dont_wait": False}}))
        got = self.start(TOP)
        self.assertNotIn("act-don't-wait", got)
        self.assertIn("built-in, levels", got, "the other built-in rule still comes")
        try:
            phi.project_conf(self.t.p4)
            self.assertNotIn("act-don't-wait", phi.builtin_text())
            self.assertIn("built-in, levels", phi.builtin_text(), "the other built-in rule stands on its own")
            write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"act_dont_wait": False, "levels": False}}))
            phi.project_conf(self.t.p4)
            self.assertEqual(phi.builtin_text(), "")
        finally:
            phi.project_conf("")

    def test_the_levels_rule_is_given_with_no_configuration_and_p4_json_turns_it_off(self):
        """On in every project, a store or none; only p4.json's phi.levels: false leaves it out."""
        got = self.start(TOP)
        for word in ("built-in, levels", "`p4-phi:sweep`", "`p4-phi:runner`", "`p4-phi:check`",
                     "`run_in_background: true`", "completion notification"):
            self.assertIn(word, got)
        self.assertNotIn("ezexe", phi.LEVELS, "it addresses the session and names no person")
        self.assertIn("built-in, levels", phi.builtin_text())
        with tempfile.TemporaryDirectory() as tmp:
            bare = Tree(tmp, store=False)
            bare.record(TOP)
            r = bare.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
            self.assertIn("built-in, levels", context(r), "a project with no store")
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"levels": False}}))
        off = self.start(KID)
        self.assertNotIn("built-in, levels", off)
        self.assertIn("act-don't-wait", off)


class Ids(unittest.TestCase):
    def test_the_hosts_id_without_its_prefix_is_a_real_cli_session(self):
        # the app pairs the two ids this way for many sessions; it is no stray id
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
        d = {ev: gs for ev, gs in d.items() if gs}                  # phi.py's own; retrieval's run recall-hook.sh
        self.assertEqual(sorted(d), ["SessionStart", "Stop", "UserPromptSubmit"],
                         "frozen: the checks around a tool call ride on the retrieval hooks' entries")
        for event, name in (("SessionStart", START), ("UserPromptSubmit", PROMPT), ("Stop", STOP)):
            cmd = d[event][0]["hooks"][0]["command"]
            self.assertIn("run-hook.sh", cmd)
            self.assertTrue(cmd.endswith(" " + name), cmd)

    def test_runners_write_nothing_to_temp(self):
        """The proven interpreter is kept in the plugin's install, not in %TEMP%."""
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

    def test_the_words_given_to_a_session_hold_no_banned_name(self):
        """Every string the session modules can hand a session: each literal and f-string part, docstrings, keys and
        regex sources aside; owner is banned outside puppeteer.py, whose code owner is that word's programming sense."""
        import ast
        for name in ("phi.py", "relay.py", "plans.py", "controls.py", "starts.py", "puppeteer.py", "issues.py",
                     "gaps.py"):
            tree, skip = ast.parse(read(os.path.join(HERE, name))), set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                    skip.add(id(n.body[0].value))
                elif isinstance(n, ast.Subscript):
                    skip.add(id(n.slice))
                elif isinstance(n, ast.Dict):
                    skip.update(id(k) for k in n.keys if k is not None)
                elif isinstance(n, ast.Call) and n.args and getattr(n.func, "attr", "") in ("get", "pop", "setdefault",
                                                                                            "compile"):
                    skip.add(id(n.args[0]))
            given = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                              and isinstance(n.value, str) and id(n) not in skip).lower()
            for word in ("ghost", "memo", "rollup", "node", "play", "steer", "goal") + (
                    ("owner",) if name != "puppeteer.py" else ()):
                self.assertNotRegex(given, rf"\b{word}s?\b", f"{word} in {name}")


class FixtureFolder(unittest.TestCase):
    def test_a_tree_is_made_in_the_folder_the_tests_are_given(self):
        with tempfile.TemporaryDirectory() as given:
            folder = os.path.join(given, "fixtures")
            code = ("import tempfile, test_phi\nwith tempfile.TemporaryDirectory() as d:\n"
                    "    print(test_phi.Tree(d).p4)")
            env = {**os.environ, "P4_PHI_TEST_TMP": folder}
            r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=HERE, env=env, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.normcase(r.stdout.strip()).startswith(os.path.normcase(folder)), r.stdout)


class StatePage(unittest.TestCase):
    """A session whose p4-phi task names a state page resumes from it after a clear, and is told to clear itself
    at a turn's end once its context passes the line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="Build the narwhal exporter")
        self.page = os.path.join(t.tmp, "tmp", "state.md").replace("\\", "/")
        t.say(TOP, "Build the exporter")
        t.cli(TOP, "task", f"Build the narwhal exporter. State page: {self.page}")
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"context_window": 200000}}))

    def tearDown(self):
        self._tmp.cleanup()

    def wrap_up(self, used, uuid):
        t = self.t
        path = os.path.join(t.tmp, f"wrap{uuid}.jsonl")
        transcript(path, "Build the exporter", [], "Built.", uuid)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [], "usage": {
                "input_tokens": 2000, "cache_creation_input_tokens": 8000,
                "cache_read_input_tokens": used - 10000}}}) + "\n")
        body = {"session_id": CLI.get(TOP, TOP), "cwd": t.proj, "hook_event_name": "PostToolUse",
                "tool_name": "mcp__ccd_turn__wrap_up", "tool_input": {"recap": "Built."},
                "tool_response": "Nothing is pending.", "transcript_path": path, "tool_use_id": f"toolu_wrap{uuid}"}
        r = inproc.run(["sh", os.path.join(ROOT, "hooks", "recall-hook.sh"), "lookup-record"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(TOP))
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def test_a_session_whose_task_names_a_state_page_gets_its_path_first_after_a_clear(self):
        ctx = context(self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "clear"}))
        self.assertTrue(ctx.startswith("phi (p4-phi): ") and self.page in ctx.split("\n", 1)[0], ctx[:300])

    def test_past_the_line_a_wrap_up_is_answered_with_the_clear_and_below_it_with_nothing(self):
        said = self.wrap_up(130000, "1")
        self.assertIn(self.page, said)
        self.assertIn("mcp__ccd_session_mgmt__clear_session", said)
        self.assertIn('"self"', said)
        self.assertNotIn("clear_session", self.wrap_up(100000, "2"))

    def test_a_worker_past_the_line_is_told_to_clear_its_coworkers_first(self):
        t = self.t
        t.record(KID, started_by=TOP, title="the flush coworker")
        t.say(KID, "Flush the rows.\nFiles: src/flush.py")
        said = self.wrap_up(130000, "3")
        self.assertIn(f"`{KID}`", said)
        self.assertIn("idle with an empty queue", said)


ASKS_WRITE = re.compile(r"\b(?:write|writes|keep|keeps|save|saves|logs?|rewritten|puts?|go there|up to date at|"
                        r"edit)\b", re.I)
UNDER_CLAUDE = re.compile(r"(?:^|[\s`'\"(:])[^\s`'\"(]*\.claude/[^\s`'\")]*")


def writes_under_claude(text, plugin=ROOT):
    """Each sentence of `text` that asks for a write and names a path under a .claude folder; the plugin's own
    folder, which the commands it hands name, is left out, since an install keeps it under ~/.claude."""
    text = text.replace("\\", "/").replace(plugin.replace("\\", "/"), "<plugin>")
    return [x for x in re.split(r"(?<=[.;:!?])\s+|\n", text) if UNDER_CLAUDE.search(x) and ASKS_WRITE.search(x)]


class NoWriteUnderClaude(unittest.TestCase):
    """Row B7 of the plugin defaults inventory: every write under .claude asks ezexe, even in bypass mode, so no line
    p4-phi hands a session names a place under .claude to write. A state page is kept in the app's scratchpad."""

    PUP, WORKER, CO = "local_pup00001", "local_wrk00001", "local_cow00001"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="Narwhal exporter")
        t.record(KID, TOP, "Fix the dropped row")
        t.record(self.PUP, title="Control the exporter tree")
        t.record(self.WORKER, started_by=self.PUP, title="Puppeteer's standing worker")
        t.record(self.CO, started_by=self.WORKER, title="a standing coworker")
        write(os.path.join(t.tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": [{"id": "cg-1", "name": "puppeteers", "mode": "code"}],
                                                 "assignments": {"code:" + self.PUP: "cg-1"}}}}}}))
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"context_window": 200000}}))

    def tearDown(self):
        self._tmp.cleanup()

    def pad(self, host):
        return os.path.join(self.t.tmp, "temp", CLI.get(host, host), "scratchpad").replace("\\", "/")

    def run_hook(self, name, host, payload):
        return context(self.t.hook(name, host, {"scratchpad_dir": self.pad(host), **payload}))

    def wrap_up(self, host):
        t = self.t
        path = transcript(os.path.join(t.tmp, f"wrap-{host}.jsonl"), "Check the archives", [], "Checked.")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [], "usage": {
                "input_tokens": 2000, "cache_creation_input_tokens": 8000, "cache_read_input_tokens": 120000}}}) + "\n")
        body = {"session_id": CLI.get(host, host), "cwd": t.proj, "hook_event_name": "PostToolUse",
                "tool_name": "mcp__ccd_turn__wrap_up", "tool_input": {"recap": "Checked."},
                "tool_response": "Nothing is pending.", "transcript_path": path, "tool_use_id": f"toolu_wrap{host}",
                "scratchpad_dir": self.pad(host)}
        r = inproc.run(["sh", os.path.join(ROOT, "hooks", "recall-hook.sh"), "lookup-record"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(host))
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def test_no_line_handed_to_a_session_names_a_place_under_claude_to_write(self):
        import controls
        said = {}
        for host, first in ((TOP, TASK), (KID, HANDED), (self.PUP, "Control the trees"),
                            (self.WORKER, "Run the puppeteer's checks.\n" + controls.WORKER_BRIEF),
                            (self.CO, "Check the archives.\nFiles: none")):
            said[host, "start"] = self.run_hook(START, host, {"hook_event_name": "SessionStart", "source": "startup"})
            said[host, "first"] = self.run_hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit",
                                                                "prompt": first})
        for host in (TOP, KID, self.WORKER, self.CO):
            for source in ("compact", "clear"):
                said[host, source] = self.run_hook(START, host, {"hook_event_name": "SessionStart", "source": source})
        said[self.WORKER, "wrap_up"] = self.wrap_up(self.WORKER)
        for key, text in said.items():
            self.assertEqual(writes_under_claude(text), [], key)
        page = self.pad(self.WORKER) + "/state.md"
        self.assertIn(page, said[self.WORKER, "first"], "a standing worker keeps its state page in its scratchpad")
        self.assertIn(page, said[self.WORKER, "clear"].split("\n", 1)[0], "and is handed it first after a clear")
        self.assertIn(page, said[self.WORKER, "wrap_up"], "and brings it up to date there before it clears")
        self.assertIn("decisions.md in the scratchpad directory the app names", said[TOP, "start"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
