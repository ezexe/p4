#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

    python -m pytest tests/p4-phi/test_phi.py

Checked: a handed-over task read out of its wrapper, a forked session's too, and a paste read as the person's own
words; a session's last turn with no human prompt, found from the transcript's end; which session started a session,
from the app's record, with nothing in the payload saying it; the sessions above it given their files from their
records; a `spawnedFrom` the app writes late read from the notes folder first and corrected by the record; a session
with no store of its own living in its parent session's store; every finished turn kept, done or not, once per turn;
its report appended to the parent session's reports and given to that session at its next message, once; a
worker given the tasks and notes of the sessions above it and the last turn of its siblings; an orchestrator
given the last turns of the orchestrators before it, with no likeness of words involved; a note refused without
a source; a session detached to top level, and reparented; a session's own turns after a clear; silence where
there is nothing to say; no standing instruction for a message about something else, which the app's own session
tools carry; a feature step as a new topic; a turn another session began told only what the start tool's own text
lacks; the caps on depth and live children;
the task changed by its command; the rules built into p4-phi at a session's start, the store's feedback and user
memories never handed again, which the app loads, and a memory changed mid-session given once; the pieces past
the prompt's cap held on a page; a hook never failing a call; hooks.json's shape and the words given to a session.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import phi  # noqa: E402
import starts  # noqa: E402
import relay  # noqa: E402
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402

inproc.prepare(SRC)              # a hook or a command runs in this process, as its own process would run it
ROOT = os.path.dirname(SRC)
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

    def forget(self, *hosts):
        """The app's record of each session gone: a session that started one is a puppeteer, so a test of what an
        orchestrator with no live session of its own is handed leaves it none."""
        for host in hosts:
            os.remove(os.path.join(self.app, host + ".json"))

    def env(self, host, proj=None, **more):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "P4_PHI"))}
        env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj or self.proj,
                    "P4_PHI_APP_SESSIONS": os.path.join(self.tmp, "app"), "P4_PHI_WAIT": "0",
                    "P4_PHI_STORES": os.path.join(self.tmp, "p4-stores.json"),
                    "P4_PHI_BOOK": "0", "P4_PHI_WATCH": "0",
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
        return inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), *args],
                          capture_output=True, text=True, env=self.env(host, proj), cwd=proj or self.proj,
                          timeout=60, clock=clock)

    def rules(self, host, proj=None, **more):
        """What `phi.py rules` prints for the plugin's hooks module: the one JSON line, with the tools the session's
        model is not offered."""
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "rules"],
                       capture_output=True, text=True, env=self.env(host, proj, **more), cwd=proj or self.proj,
                       timeout=60)
        assert r.returncode == 0 and r.stdout.count("\n") == 1, (r.returncode, r.stdout, r.stderr)
        return json.loads(r.stdout)

    def stop(self, host, prompt, calls=(), report="done", uuid="u0", **kw):
        t = transcript(os.path.join(self.tmp, host + uuid + ".jsonl"), prompt, calls, report, uuid)
        return self.hook(STOP, host, {"hook_event_name": "Stop", "transcript_path": t,
                                      "last_assistant_message": report}, **kw)

    def dir(self, host):
        """The session's folder, its node's where a hook claimed one: the walk is made again, since the hook ran
        in another process."""
        relay.forget(self.p4)
        return relay._dir(self.p4, host)

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
        # a look rewrites ledger.md by os.replace while a hook, a command or a test reads it
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
                except OSError as e:           # the writer is a look: a refused replace ends it
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

    def test_the_prompt_of_a_turn_the_hooks_module_started_is_no_request_of_ezexes(self):
        """ezexe/p4#193: a UserPromptSubmit hook is given a prompt that a plugin's hooks module submitted as the
        module wrote it, with no tag around it, as a live probe on Claude Code 2.1.326 showed. p4-phi's own opens
        with plans.WAKE_MARK or plans.UPKEEP_MARK, and every reader of a prompt tells it from ezexe's words by that
        opening. A message that quotes those words further in is still ezexe's."""
        import plans
        import puppeteer
        import rows
        wake = plans.WAKE_MARK + " step 1, \"Await the reports\", which waits on other sessions."
        self.assertEqual(phi.request_of(wake), "")
        self.assertEqual(phi.request_of("<system-reminder>x</system-reminder>\n" + wake), "")
        self.assertTrue(plans.woken("\n" + wake))
        self.assertTrue(puppeteer.from_session(wake))
        self.assertTrue(rows.WAKE_RE.match(wake), "rows.py spells the mark as plans.py does")
        upkeep = plans.UPKEEP_MARK + ": the sessions this one started are idle."
        self.assertEqual(phi.request_of(upkeep), "")
        self.assertEqual(phi.request_of("<system-reminder>x</system-reminder>\n" + upkeep), "")
        self.assertTrue(plans.woken("\n" + upkeep))
        self.assertTrue(puppeteer.from_session(upkeep))
        asked = "why did it say this: " + wake
        self.assertEqual(phi.request_of(asked), asked)
        self.assertFalse(puppeteer.from_session(asked))
        self.assertFalse(rows.WAKE_RE.match(asked))

    def test_the_apps_notice_about_a_sent_message_is_no_request_of_ezexes(self):
        """The SendMessage tool's text: "a `[Cross-session delivery notice]` tells you when that happens" and
        "exactly one `[Cross-session idle notice]` arrives". Each reaches a session as a prompt that opens with its
        mark and no tag around it, as a live run on Claude Code 2.1.325 showed, where routing drafted a start named
        after the notice. So every reader of a prompt tells it from ezexe's words by that opening, and a message
        that quotes the mark further in is still ezexe's."""
        import plans
        import puppeteer
        import rows
        held = "[Cross-session delivery notice] Your message to another session was held by that session."
        idle = "[Cross-session idle notice] The session you subscribed to went idle."
        marked_held = "[MESSAGE FROM NON-USER SOURCE - NOT USER INPUT]\n" + held
        for said in (held, idle, marked_held, "<system-reminder>x</system-reminder>\n" + held):
            self.assertEqual(phi.request_of(said), "", said[:40])
        for said in (held, idle, marked_held):
            self.assertTrue(plans.app_notice(said), said[:40])
            self.assertTrue(puppeteer.from_session(said), said[:40])
            self.assertTrue(rows.HARNESS_RE.match(said), said[:40])
        asked = "what does this mean: " + held
        self.assertEqual(phi.request_of(asked), asked)
        self.assertFalse(plans.app_notice(asked))
        self.assertFalse(puppeteer.from_session(asked))
        self.assertFalse(rows.HARNESS_RE.match(asked))
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            tree.record(TOP)
            tree.say(TOP, TASK)
            tree.say(TOP, held)
            self.assertEqual(tree.session(TOP)["turnBy"], "event", "not the person's turn")
            self.assertEqual(tree.session(TOP)["task"], TASK)

    def test_the_frame_of_a_background_tasks_event_is_no_request_of_ezexes(self):
        """hooks.md, "UserPromptSubmit": the hooks also run on "A background subagent reporting back to the session
        that started it". In the desktop app such a prompt opens with the frame below and carries a kind rows.whose
        names nobody for, and routing drafted a new orchestrator for each report. A message that quotes the frame
        further in is still ezexe's, and so is one the origin says ezexe typed."""
        import plans
        frame = ("[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message "
                 "from the user.\nThe finder found three call sites in src/export/.")
        for said in (frame, "  \n" + frame, "<system-reminder>x</system-reminder>\n" + frame):
            self.assertEqual(phi.request_of(said), "", said[:40])
        self.assertTrue(plans.system_note(frame))
        asked = "what does this mean: " + frame
        self.assertEqual(phi.request_of(asked), asked)
        self.assertFalse(plans.system_note(asked))
        self.assertEqual(phi.request_of(frame, "user"), frame, "the origin says ezexe typed it")
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            tree.record(TOP)
            tree.say(TOP, TASK)
            tree.say(TOP, frame)
            self.assertEqual(tree.session(TOP)["turnBy"], "event", "not the person's turn")
            self.assertEqual(tree.session(TOP)["task"], TASK)

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
                ("Bash", {"command": "cd /e/x && python -m pytest tests/test_flush.py 2>&1 | tail -3"}, "OK"),
                ("Bash", {"command": "cat notes.txt"}, "words"),
                ("Bash", {"command": "python -c \"print('a\"b')\""}, "unexpected EOF while looking for matching", 1),
                ("mcp__ccd_session__start_session", {"title": "Check the ports"}, "started")], "fixed")
            turn = phi.last_turn(t)
            self.assertTrue(turn["prompt"].startswith(BRIEF))
            self.assertEqual(turn["uuid"], "u0")
            row = phi.turn_of(turn, "fixed")
            self.assertEqual(sorted(row), ["done", "failed", "id", "prompt", "report", "steps"])
            self.assertIn("edited export/flush.py", row["steps"])
            self.assertIn("ran `python -m pytest tests/test_flush.py`", row["steps"])
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
        # a transcript no record names is the child's own, once its start says the session was resumed under it
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "resume"}, cli=KID + "-resumed")
        self.t.say(KID, "and the rest", cli=KID + "-resumed")
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

    def test_no_store_anywhere_hands_nothing_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Tree(tmp, store=False)
            t.record(TOP)
            r = t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), "a start hands nothing with no store")
            r = t.say(TOP, TASK)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
            self.assertFalse(os.path.exists(os.path.join(t.proj, ".claude")), "nothing written")

    def test_the_first_session_of_a_store_is_handed_nothing(self):
        self.t.forget(KID, KID2, GRAND)
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual((r.returncode, context(r)), (0, ""), "no memories and no background: nothing is handed")
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
                                          ("Bash", {"command": "python -m pytest tests/test_flush.py"}, "OK")], report, uuid)

    def test_every_finished_turn_is_kept_not_done_until_something_showed_it(self):
        r = self.kid_stops()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        turns = self.t.turns(KID)
        self.assertEqual(len(turns), 1)
        t = turns[0]
        self.assertEqual(t["done"], "")
        self.assertTrue(t["prompt"].startswith(BRIEF))
        self.assertEqual(t["steps"], ["edited export/flush.py", "ran `python -m pytest tests/test_flush.py`"])
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
        self.assertNotIn("reports of this session's workers", context(self.t.say(TOP, "and now?")))

    def test_a_report_the_hooks_module_sent_is_not_repeated_beside_the_message_that_holds_it(self):
        """ezexe/p4#157: the hooks module's message to a starter holds the worker's report, and the starter's prompt
        hook hands the reports kept for it beside that same message. A report the message already holds is named
        with its steps and its page and not repeated, and one the message does not hold is handed whole."""
        self.kid_stops()
        sent = ("<cross-session-message from=\"uds:x\" from-session=\"" + KID + "\" from-plugin=\"p4-phi\">\n"
                "phi (p4-phi): this session ended a turn. Its report follows, and needs no reply.\n\n" + LONG
                + "\n</cross-session-message>")
        text = context(self.t.say(TOP, sent))
        self.assertIn("reports of this session's workers", text)
        self.assertIn("  reported: in the message this turn began with", text)
        self.assertNotIn(LONG, text)
        self.assertIn("edited export/flush.py", text)
        self.assertIn("its page: ", text)
        self.kid_stops(report="The header row is fixed too, in flush_header, and the suite passes.", uuid="u1",
                       prompt="now the header row")
        text = context(self.t.say(TOP, sent))           # an older message: the newer report is not in it
        self.assertIn("reported: The header row is fixed too", text)
        self.assertTrue(phi.in_message(LONG, sent))
        self.assertFalse(phi.in_message("Done.", "Done."), "too short a report to tell by")

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


class TurnEnds(unittest.TestCase):
    """A turn that ends with no Stop, read by puppeteer.working from the session's log."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_turn_that_ends_on_an_api_error_is_ended(self):
        """ezexe/p4#161: StopFailure runs in place of Stop when a turn ends on an API error, so its entry logs the
        turn's end with the error, and keeps no turn row."""
        import puppeteer
        self.assertTrue(puppeteer.working(self.t.p4, TOP))
        r = self.t.hook("stop-failure", TOP, {"hook_event_name": "StopFailure", "error": "rate_limit",
                                              "error_details": "429 Too Many Requests",
                                              "last_assistant_message": "API Error: Rate limit reached"})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(puppeteer.working(self.t.p4, TOP))
        row = self.t.log(TOP)[-1]
        self.assertEqual((row["hook"], row["event"], row["ended"]), ("stop", "StopFailure", "rate_limit"))
        self.assertEqual(self.t.turns(TOP), [])


class StopEnds(unittest.TestCase):
    """The Stop hook sends a turn back for the issue loop's verdict alone, never for open steps."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.record(KID, TOP, title="the x fix")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, host, steps, status="pending"):
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": {"items": [{"content": c, "status": status} for c in steps]},
                                       "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_turn_with_two_open_steps_and_no_issue_ends_with_nothing_said(self):
        self.plan(TOP, ("Port the hooks", "Write the layout docs"))
        r = self.t.stop(TOP, TASK, report="I ported half the hooks.", uuid="s1")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        r = self.t.stop(TOP, TASK, report="Still porting.", uuid="s2")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), "nor the next turn")

    def test_a_finished_started_session_whose_issue_is_not_proven_is_sent_back_with_the_gates_reason(self):
        import issues
        self.t.say(KID, TASK)
        path = os.path.join(self.t.dir(KID), "session.json")
        s = jload(path)
        s["issue"] = {"repo": "ezexe/demo", "number": 7, "url": "https://github.com/ezexe/demo/issues/7"}
        write(path, json.dumps(s))
        self.plan(KID, ("Fix x",), status="completed")
        r = self.t.stop(KID, TASK, report="Fixed x.", uuid="s3")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("names no regression test that proves ezexe/demo#7 fixed", out.get("reason", ""))
        self.assertTrue(out["reason"].startswith("phi (p4-phi): this session's work looks finished"))
        self.assertNotIn("Carry on", out["reason"])
        self.assertTrue(callable(issues.gate))

    def test_phi_look_answers_no_move(self):
        self.t.say(KID, TASK)
        env = self.t.env(TOP, P4_PHI_WATCH="1", P4_PHI_WATCH_NET="0")
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look"],
                       capture_output=True, text=True, env=env, cwd=self.t.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("move", json.loads(r.stdout))


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
        self.assertEqual(self.start(other), "")   # in the app a start is given no background, since its parent
        # session is not known yet, and the built-in rules are in its system prompt
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

    def test_a_session_is_given_its_own_turns_after_a_clear_and_none_after_a_compaction(self):
        """https://code.claude.com/docs/en/context-window.md, "What survives compaction": "When a long session
        compacts, Claude Code summarizes the conversation history to fit the context window", and the row "Context
        that hooks added earlier" reads "Summarized with the rest of the conversation". The summary carries the
        session's own turns and the background it was handed, so a start after a compaction hands neither again. A
        clear keeps nothing, so a start after it hands the background with the session's own turns."""
        self.t.say(KID, HANDED)
        self.t.stop(KID, HANDED, [("Edit", {"file_path": "src/export/flush.py"}, "ok")], "Half done.")
        text = self.start(KID, "compact")
        for gone in ("This session's own turns so far", "Half done.", "edited export/flush.py",
                     "background for this session"):
            self.assertNotIn(gone, text, gone)
        self.assertNotIn("act-don't-wait", text, "the built-in rules are in the system prompt, sent anew after it")
        text = self.start(KID, "clear")
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
        self.assertIn("- 1 puppeteer \"Narwhal exporter\" `", out)
        self.assertIn("  - 101 orchestrator \"Fix the dropped row\" `", out)
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
        return context(self.t.say(host, prompt, P4_PHI_BOOK="1", **more))

    def test_no_standing_instruction_is_handed_for_a_message_about_something_else(self):
        """The app's own `hand_off_to_session` and `start_session` with `initiation` `offer` say in their tool
        descriptions when a message about something else goes to another session, so p4-phi hands no instruction of
        its own."""
        for host, words in ((TOP, TASK), (TOP, "also, what colour should the fence be?"), (KID, HANDED),
                            (KID, "and what about the fence?")):
            said = self.say(host, words)
            self.assertNotIn("about something else", said, words)
            self.assertNotIn("stay with the task", said, words)

    def test_an_orchestrators_brief_keeps_it_attached_under_the_session_that_started_it(self):
        self.say(TOP, TASK)
        told = self.say(KID, "Task:\nPick the fence colour. ezexe's words: \"the fence colour?\" "
                        + starts.ORCHESTRATOR_BRIEF)
        self.assertNotIn("detach", told, "nothing detaches it, in the app or in p4-phi")
        s = phi.load_session(self.t.p4, KID)
        self.assertEqual(phi.spawned_from(s), TOP, "it stays under its starter")
        self.say(KID, "carry on")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID)), TOP)
        self.assertNotIn(KID, relay._siblings(self.t.p4, phi.load_session(self.t.p4, TOP)))
        self.t.record(KID2, TOP, "a plain child")
        self.say(KID2, "Task:\nWrite the docs; this is not a new top")
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), TOP, "an unmarked brief stays a child")
        r = self.t.cli(KID2, "detach")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(phi.spawned_from(phi.load_session(self.t.p4, KID2)), "", "phi.py detach with no id: itself")

    def test_a_detached_top_level_session_is_never_counted_as_archived_on_its_former_parent(self):
        """Counting as archived, the archive lines and parent steps read spawnedFrom.sessionId, never its `from`."""
        import plans
        self.say(TOP, TASK)
        stale = phi.load_session(self.t.p4, KID) or phi.ensure_session(self.t.p4, KID)
        self.say(KID, "Task:\nPick the fence colour, archive when done.")
        self.assertEqual(self.t.cli(TOP, "detach", KID).returncode, 0)    # by hand: nothing else detaches a session
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

    def test_the_harness_speaking_gets_no_line(self):
        self.t.forget(KID)
        self.say(TOP, TASK)
        self.assertEqual(self.say(TOP, "<side-sessions-event>a session finished a turn</side-sessions-event>"), "")
        self.assertEqual(self.say(TOP, "<task-notification>done</task-notification>"), "")

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

    def start(self, host, brief="Check what the exporter's flush does and report it.\nFiles: none"):
        """What p4-phi's hook answers a start call with: its decision and reason, both '' when it says nothing."""
        call = {"initiation": "user_asked", "title": "the check", "context": "fresh", "use_worktree": False,
                "prompt": brief, "background": "The exporter top holds the port; this child takes the flush. " * 2}
        r = self.t.hook("start-advice", host, {"hook_event_name": "PreToolUse",
                                               "tool_name": "mcp__ccd_session__start_session", "tool_input": call})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
        return out.get("permissionDecision", ""), out.get("permissionDecisionReason", "")

    def test_a_start_from_a_session_another_session_started_is_refused_with_the_draft_command_at_any_depth(self):
        """A desktop session below an orchestrator is what the terminal workers replace: a session another session
        started starts none, so the depth cap holds nothing a desktop start can reach, and one nobody started may."""
        up = TOP
        for k, sid in enumerate(("local_d1", "local_d2", "local_d3")):
            self.t.record(sid, up, title=f"depth {k + 1}")
            self.say(sid, "Task:\nCheck the exporter. Report when done.\nFiles: none")
            up = sid
        self.assertEqual(self.start(TOP), ("", ""), "a session nobody started keeps its start")
        for sid in ("local_d1", "local_d2", "local_d3"):
            decision, why = self.start(sid)
            self.assertEqual(decision, "deny", sid)
            self.assertIn("draft --start", why, sid)
            self.assertIn("--to-puppeteer", why, sid)

    def test_a_start_from_a_session_with_phi_max_children_live_sessions_is_refused(self):
        """A session with phi.MAX_CHILDREN live sessions of its own starts no ninth, and one with fewer may."""
        home = self.t.p4
        self.say(TOP, TASK)
        self.assertEqual(self.start(TOP), ("", ""), "below both caps")
        for k in range(phi.MAX_CHILDREN):
            write(os.path.join(home, "phi", "sessions", f"local_k{k}", "session.json"),
                  json.dumps({"sessionId": f"local_k{k}", "spawnedFrom": {"sessionId": TOP}}))
        decision, why = self.start(TOP)
        self.assertEqual(decision, "deny")
        self.assertIn("this start is refused: This session has ", why)
        self.assertIn("live sessions of its own, the most p4-phi allows", why)

    def test_a_task_list_hands_a_top_session_its_boundary_text_alone_and_the_approval_hands_it_nothing(self):
        """update_plan from a top session with three steps answers with what plans.record says of the list, and
        ExitPlanMode answers with nothing."""
        p = self.t.proj
        self.say(TOP, TASK)
        steps = [{"content": f"Port the exporter in {p}/src/export/flush.py to the new writer", "status": "in_progress"},
                 {"content": f"Rewrite the parser in {p}/src/parse.py for the new grammar", "status": "pending"},
                 {"content": "Commit and push", "status": "pending"}]
        r = self.t.hook("plan", TOP, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                      "tool_input": {"items": steps, "scope": "first_task"},
                                      "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)
        said = context(r)
        for word in ("start_session", "orchestrator of its tree", "new feature", "documented terms", "worker"):
            self.assertNotIn(word, said, word)
        r = self.t.hook("plan-mode", TOP, {"hook_event_name": "PostToolUse", "tool_name": "ExitPlanMode",
                                           "tool_input": {}, "tool_response": {"plan": "p"}})
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)

    def test_a_project_sets_its_caps_in_p4_json(self):
        """ezexe/p4#125: the caps a project would decide are p4.json `phi` keys; a value of the wrong type or out of
        range keeps the default, and a store that sets none gets the defaults back."""
        import plans
        import puppeteer
        home = self.t.p4
        self.say(TOP, TASK)
        write(os.path.join(home, "p4.json"), json.dumps({"phi": {
            "max_depth": 1, "max_children": 2, "sibling_turns": 1, "own_turns": 1, "chain_max": 2, "turn_steps": 4,
            "keep_going_max": 1, "watch_s": 10, "stale_s": 3600}}))
        try:
            phi.project_conf(home)
            self.assertEqual((phi.MAX_DEPTH, phi.MAX_CHILDREN, phi.OTHERS, phi.OWN, phi.CHAIN_MAX, phi.TURN_STEPS),
                             (1, 2, 1, 1, 2, 4))
            self.assertEqual((plans.KEEP_GOING_MAX, puppeteer.WATCH_S, puppeteer.STALE_S), (1, 10.0, 3600.0))
            write(os.path.join(home, "phi", "sessions", KID, "session.json"),
                  json.dumps({"sessionId": KID, "spawnedFrom": {"sessionId": TOP}, "task": "t"}))
            self.assertIn("start no session", phi.caps_text(home, phi.load_session(home, KID)), "one deep is the most")
            write(os.path.join(home, "p4.json"), json.dumps({"phi": {
                "max_depth": "3", "max_children": 0, "keep_going_max": 9, "watch_s": True}}))
            phi.project_conf(home)
            self.assertEqual((phi.MAX_DEPTH, phi.MAX_CHILDREN, plans.KEEP_GOING_MAX, puppeteer.WATCH_S),
                             (3, 8, 2, 5.0), "a value that does not fit keeps the default")
            self.assertEqual((phi.OTHERS, puppeteer.STALE_S), (5, 86400.0), "and unset ones")
            for odd in ([1, 2], "deep", 4):            # a `phi` that is no section raises nothing and keeps the defaults
                write(os.path.join(home, "p4.json"), json.dumps({"phi": odd}))
                phi.MAX_DEPTH = 7
                phi.project_conf(home)
                self.assertEqual((phi.MAX_DEPTH, phi.TURN_STEPS), (3, 12), odd)
            import p4conf
            self.assertEqual(phi.CAP_DEFAULTS, {k: p4conf.DEFAULTS["phi"][k] for k in phi.CAPS},
                             "each default is the one p4conf.py declares, whatever a constant held before")
        finally:
            phi.project_conf("")

    def test_a_started_sessions_task_is_its_brief(self):
        self.say(TOP, TASK)
        self.say(KID, HANDED)
        self.assertIn(BRIEF, self.t.session(KID)["task"])

    def test_the_address_book_comes_by_its_page_after_a_compaction_and_whole_after_a_clear(self):
        """A compaction's summary keeps the conversation, the book the session was handed among it, and no exact id
        or path: the start after it names book.md and hands no entry that did not change. A clear keeps nothing."""
        self.say(TOP, TASK)                          # its first look: the book whole
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "compact"}, P4_PHI_BOOK="1")
        text = context(r)
        self.assertIn("this session's address book, unchanged since it last looked, is whole on", text)
        self.assertIn("/book.md", text.replace("\\", "/"))
        self.assertNotIn("this session's address book, whole on", text)
        self.assertNotIn("about something else", text)
        r = self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "clear"}, P4_PHI_BOOK="1")
        self.assertIn("this session's address book, whole on", context(r))

    def test_the_task_is_changed_by_its_command(self):
        self.say(TOP, TASK)
        r = self.t.cli(TOP, "task", "Make the narwhal importer read the ports table back")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.t.session(TOP)
        self.assertEqual(s["task"], "Make the narwhal importer read the ports table back")
        self.assertEqual(s["earlierTasks"][0]["task"], TASK)        # the task before it is kept
        self.assertNotEqual(self.t.cli(TOP, "task", "x").returncode, 0)

    def test_off_in_the_stores_settings(self):
        self.t.forget(KID)
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"book": False}))
        env = {k: v for k, v in self.t.env(TOP).items() if k != "P4_PHI_BOOK"}
        for prompt in (TASK, "and the next part"):
            r = inproc.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[TOP], "cwd": self.t.proj,
                                                                  "prompt": prompt}),
                           capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.stdout.strip(), "")

    def test_the_older_new_task_names_turn_the_book_off_and_book_wins(self):
        """A store or a run that set `new_task` or P4_PHI_NEW_TASK before the rename keeps its address book off;
        phi.json's `book` wins over `new_task`, and P4_PHI_BOOK over P4_PHI_NEW_TASK."""
        env = {k: v for k, v in self.t.env(TOP).items() if k != "P4_PHI_BOOK"}

        def said(prompt, **more):
            r = inproc.run(["sh", RUN, PROMPT], input=json.dumps({"session_id": CLI[TOP], "cwd": self.t.proj,
                                                                  "prompt": prompt}),
                           capture_output=True, text=True, env={**env, **more}, timeout=60)
            return r.stdout
        conf = os.path.join(self.t.p4, "phi", "phi.json")
        write(conf, json.dumps({"new_task": False}))
        self.assertNotIn("address book", said(TASK))
        write(conf, json.dumps({"new_task": False, "book": True}))
        self.assertIn("address book", said(TASK + " again"), "book wins")
        os.remove(conf)
        held = {k: os.environ.get(k) for k in ("P4_PHI_BOOK", "P4_PHI_NEW_TASK")}
        try:
            for book, new_task, want in (("", "0", False), ("1", "0", True), ("0", "1", False)):
                for k, v in (("P4_PHI_BOOK", book), ("P4_PHI_NEW_TASK", new_task)):
                    os.environ.pop(k, None) if not v else os.environ.__setitem__(k, v)
                phi.BOOK = not want
                phi.configure(self.t.p4)
                self.assertIs(phi.BOOK, want, (book, new_task))
        finally:
            phi.BOOK = True
            for k, v in held.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


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
        """A memory another session changes mid-session reaches sessions already open."""
        conf = os.path.join(self._tmp.name, "conf")
        os.makedirs(conf)
        self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        self.assertNotIn("memories changed", self.live("Build the exporter", conf))
        memory(self.t.p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        got = self.live("carry on", conf)
        self.assertIn("feedback and user memories changed since this session last looked", got)
        self.assertIn("four spaces in the exporter", got)
        self.assertIn("Removed, no longer rules", got)
        self.assertIn("Indent with tabs in the exporter", got)
        self.assertNotIn("memories changed", self.live("and now", conf), "nothing repeats")

    def test_a_memory_whose_issue_landed_is_handed_as_a_pointer_not_a_rule(self):
        """ezexe/p4#226: a memory cut back to a pointer once its issue landed, whose front matter holds `landed:`, and
        one whose body says the plugin carries its rule, are no rules to hand an open session, while a changed
        preference still is."""
        conf = os.path.join(self._tmp.name, "conf")
        os.makedirs(conf)
        p4 = self.t.p4
        memory(p4, "ask-before-push", "feedback", "A session asks ezexe before it pushes a branch of its own.")
        self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        self.assertNotIn("memories changed", self.live("Build the exporter", conf))
        write(os.path.join(p4, "temportal", "memory", "ask-before-push.md"),
              "---\nname: ask-before-push\ndescription: carried by the plugin since ezexe/demo#7 landed in abc1234\n"
              "metadata:\n  type: feedback\nissue: ezexe/demo#7\nlanded: abc1234\n---\n\n"
              "The plugin holds this rule since ezexe/demo#7 landed in abc1234: `scripts/phi.py`.\n")
        memory(p4, "one-child-a-task", "feedback", "p4-phi carries this now: a session starts one child for each task.")
        memory(p4, "tabs-not-spaces", "feedback", "Indent with four spaces in the exporter, never tabs.")
        got = self.live("carry on", conf)
        changed = got.split("Changed or added:")[1].split("Removed, no longer rules")[0]
        self.assertIn("four spaces in the exporter", changed, "a changed preference is still handed")
        self.assertNotIn("ask-before-push", changed, "a pointer is not handed as a rule")
        self.assertNotIn("one-child-a-task", changed, "a memory the plugin carries is not handed as a rule")
        self.assertIn("ask-before-push", got.split("Removed, no longer rules")[1], "the pointer leaves the rules")
        self.assertNotIn("ask-before-push", [n for n, _ in phi.memory_rules(p4, rules_only=True)])
        self.assertIn("ask-before-push", [n for n, _ in phi.memory_rules(p4)], "its name is still read")

    def test_a_line_added_to_the_global_claude_md_is_left_to_the_app(self):
        """memory.md: the app reads CLAUDE.md again after a compaction, so p4-phi hands no line of it."""
        conf = os.path.join(self._tmp.name, "conf")
        write(os.path.join(conf, "CLAUDE.md"), "# Global\n\n- Call the user ezexe.\n")
        self.t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}, CLAUDE_CONFIG_DIR=conf)
        self.live("Build the exporter", conf)
        write(os.path.join(conf, "CLAUDE.md"), "# Global\n\n- Call the user ezexe.\n- Never write parentheticals.\n")
        self.assertNotIn("parentheticals", self.live("carry on", conf))

    def test_each_memory_reaches_a_session_once(self):
        """ezexe/p4#130: a memory's line in the index is the one form a session is handed at its start, so p4-phi
        hands no line of a feedback or user memory at a start, a clear or a compaction, and live_rules alone hands
        one that changed."""
        for host in (TOP, KID):
            for source in ("startup", "clear", "compact"):
                text = self.start(host, source)
                for word in ("tabs-not-spaces", "Indent with tabs", "long-rule", "Run the ports check", "out/Narwhal"):
                    self.assertNotIn(word, text, (host, source))
                self.assertLessEqual(len(text), APP_CAP)


    def test_no_ceiling_or_page_of_p4_phis_own_and_the_acting_lines_lead_past_the_apps_cap(self):
        """Audit candidate 10. hooks.md, "JSON output": "A hook's `additionalContext`, `systemMessage`, and
        `initialUserMessage` strings, and its plain stdout, are capped at 10,000 characters", and over the limit
        "Claude Code saves the output to a file in the session directory. It replaces the output with the file path
        and a preview of up to the first 2,000 characters." So p4-phi keeps no ceiling beside a prompt and no page
        for what would pass one: every piece passes whole, and the lines that ask the session to act lead."""
        self.assertNotIn("prompt_chars", phi.SETTINGS)
        self.assertEqual((phi.APP_CAP, phi.APP_PREVIEW), (APP_CAP, 2000))
        parts = ["first piece " + "a" * 1500, "second piece " + "b" * 3000, "act: third piece " + "c" * 900,
                 "last line " + "d" * 6000]
        text = phi.acting_first(parts, [parts[2]])
        self.assertEqual(text, "\n\n".join([parts[2], parts[0], parts[1], parts[3]]),
                         "every piece whole, the acting one first and the rest in their order")
        self.assertGreater(len(text), APP_CAP, "past the app's cap, which is the app's to cut and keep")
        self.assertLessEqual(text.index(parts[2]) + len(parts[2]), phi.APP_PREVIEW, "the acting line in the preview")
        self.assertEqual(phi.acting_first(["x", "", "y"]), "x\n\ny")
        long_acts = ["act one " + "e" * 1200, "act two " + "f" * 1200]
        text = phi.acting_first(parts + long_acts, long_acts)
        self.assertTrue(text.startswith("\n\n".join(long_acts)), "the acting lines lead, and no line is added")
        self.assertEqual(len(text), len("\n\n".join(parts + long_acts)), "every piece whole")
        self.t.say(TOP, TASK)
        for k in range(40):
            relay.warn(self.t.p4, TOP, f"note:{k}", f"warning {k:02d} of forty: " + "a sibling changed the layout. " * 10)
        ctx = context(self.t.say(TOP, "what now?"))
        self.assertGreater(len(ctx), APP_CAP)
        self.assertTrue(ctx.startswith(relay.STOP_HEAD + "(1) warning 00 of forty"), ctx[:300])
        self.assertIn("(40) warning 39 of forty", ctx, "every warning whole")
        self.assertNotIn("did not fit", ctx)

    def test_a_fresh_childs_background_comes_with_its_first_message_and_its_start_hands_no_rule(self):
        self.t.say(TOP, TASK)
        text = self.start(KID)
        self.assertNotIn("act-don't-wait", text, "the rules are in its system prompt")
        self.assertLessEqual(len(text), APP_CAP)
        first = context(self.t.say(KID, HANDED))                         # a fresh child's background: its first message
        self.assertIn("background for this session", first)
        self.assertLessEqual(len(first), APP_CAP)

    def test_the_start_and_first_message_text_past_7500_characters_passes_whole(self):
        """ezexe/p4#243 D9: p4-phi cuts no text of its own at a session's start or first message; past 10,000
        characters the app's own overflow file takes it."""
        t = self.t
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"background_chars": 12000}))
        t.say(TOP, TASK)
        for k in range(12):                                         # notes long enough to fill a 12,000 background
            r = t.cli(TOP, "note", f"replaces: part {k} of the old exporter, " + "the ports table rows. " * 200,
                      "--source", f"export/part{k}.py:1")
            self.assertEqual(r.returncode, 0, r.stderr)
        t.stop(TOP, TASK, report="Half done: " + "the flush writes the ports table. " * 40)
        first = context(t.say(KID, HANDED))
        self.assertGreater(len(first), 7500)
        self.assertIn("The page this comes from: ", first, "the background's last line, whole")
        self.assertNotIn("did not fit", first)
        later = context(t.say(KID, "go on"))
        self.assertNotIn("did not fit", later, "a later prompt has no ceiling of p4-phi's own either")
        calls = [("Edit", {"file_path": f"src/export/flush_part_{k}.py"}, "ok") for k in range(12)]
        for n in range(3):                                          # its own turns, which a clear's start hands whole
            t.stop(KID, HANDED, calls, "Ported: " + "the flush writes the ports table. " * 12, uuid=f"k{n}")
        start = context(t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "clear"}, P4_PHI_BOOK="1"))
        self.assertGreater(len(start), 7500)
        self.assertIn("The page this comes from: ", start, "the background's last line, whole")
        self.assertNotIn("act-don't-wait", start, "no rule is handed at a start")

    def test_an_orchestrators_long_command_runs_as_sent(self):
        """ezexe/p4#243 D4 and row S22: the app moves a foreground command to the background at its timeout,
        tools-reference.md, "Foreground commands that move to the background", so p4-phi neither rewrites an
        orchestrator's lone test command nor hands a line beside it."""
        t = self.t
        t.forget(KID)
        t.say(TOP, TASK)
        inp = {"command": "cd scripts && python -I -X utf8 test_flush.py 2>&1 | tail -3", "description": "Run tests"}
        body = {"session_id": CLI[TOP], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": inp, "tool_use_id": "toolu_d4"}
        r = inproc.run(["sh", os.path.join(ROOT, "hooks", "recall-hook.sh"), "lookup-check"], input=json.dumps(body),
                       capture_output=True, text=True, timeout=60,
                       env=t.env(TOP, CLAUDE_PLUGIN_DATA=os.path.join(t.tmp, "data")))
        self.assertEqual((r.returncode, r.stderr.strip(), r.stdout.strip()), (0, "", ""), "the call runs as sent")

    def test_the_start_text_carries_every_line_with_any_background(self):
        """A puppeteer whose p4.json names a shared store this machine has not seen, started again after a
        clear and after a compaction, with the default start background and with one set longer than the app's cap:
        each start text carries the missing-home line, the rules and the address book, whole after a clear and by
        its page after a compaction, and stays within the app's cap with the default background; after a compaction
        the line that names its board comes first."""
        t = self.t
        write(os.path.join(t.tmp, "claude_desktop_config.json"), json.dumps({"preferences": {"epitaxyPrefs": {
            "dframe-group-scopes": {"acct/org": {"groups": [{"id": "cg-1", "name": "puppeteers"}],
                                                 "assignments": {"code:" + TOP: "cg-1"}}}}}}))
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/elsewhere.git"}}))
        t.say(TOP, TASK, P4_PHI_BOOK="1")
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
                                      P4_PHI_BOOK="1"))
                sizes[f"{source}, background_chars {chars}"] = len(text)
                self.assertIn("this session's address book, whole on" if source == "clear" else
                              "this session's address book, unchanged since it last looked, is whole on", text, source)
                self.assertIn("names the shared store git@example.com:team/elsewhere.git", text, source)
                self.assertNotIn("act-don't-wait", text, "the built-in rules are no part of a start's text")
                if source == "compact":
                    self.assertTrue(text.startswith("phi (p4-phi): this session is a puppeteer and its "
                                                    "context was compacted"), text[:200])
        self.assertLessEqual(max(v for k, v in sizes.items() if k.endswith(str(phi.BACKGROUND_CHARS))), APP_CAP, sizes)

    def test_past_the_apps_cap_the_notices_lead_and_the_address_book_comes_last(self):
        """ezexe/p4#243 D9: past 10,000 characters the app hands Claude a preview of the first 2,000 and the file's
        path. A clear's start text with a long background and a long address book keeps the notices inside that
        preview and the book last. The built-in rules are in the system prompt, and no part of that text."""
        t = self.t
        subprocess.run(["git", "init", "-q", t.p4], check=True, capture_output=True)
        gd = subprocess.run(["git", "-C", t.p4, "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True).stdout.strip()
        write(os.path.join(gd, relay.TRACK_STATE), json.dumps(
            {"fails": 1, "next": time.time() + 3600, "reason": "index.lock is held", "owed": []}))
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True, "own_turns": 6,
                                                                  "home": "git@example.com:team/elsewhere.git"}}))
        write(os.path.join(t.p4, "phi", "phi.json"), json.dumps({"background_chars": 2 * APP_CAP}))
        t.say(TOP, TASK, P4_PHI_BOOK="1")
        for k in range(24):
            host = f"local_wkr{k:05d}"
            t.record(host, TOP, f"Port part {k} of the narwhal exporter's flush to the new writer")
            t.say(host, f"Port part {k} of the flush.\nFiles: src/export/flush_part_{k}.py, tests/test_part_{k}.py")
        calls = [("Edit", {"file_path": f"src/export/flush_part_{k}.py"}, "ok") for k in range(14)]
        for n in range(6):                                          # six turns of its own, each kept by own_turns
            t.stop(TOP, "Build the next part of the narwhal tools and check it. " * 5, calls,
                   "Built and checked: " + "the part reads the ports table back and its check passes. " * 8,
                   uuid=f"u{n}")
        for k in range(2, 6):                                       # orchestrators before it, past the app's cap
            host = f"local_top0000{k}"
            t.record(host, title=f"Narwhal importer, part {k}")
            t.stop(host, "Build the next part of the narwhal tools and check it. " * 5, calls,
                   "Built and checked: " + "the part reads the ports table back and its check passes. " * 8,
                   uuid=f"o{k}")
        text = context(t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "clear"},
                              P4_PHI_BOOK="1"))
        self.assertGreater(len(text), APP_CAP, "past the app's cap, so only the preview is seen whole")
        for line in ("the session tree's first commit in", "names the shared store git@example.com:team/elsewhere.git"):
            self.assertIn(line, text)
            self.assertLessEqual(text.index(line) + len(line), 2000, f"inside the app's preview: {line}")
        book = text.index("this session's address book")
        self.assertLess(text.index("background for this session"), book, "the background before the address book")
        self.assertNotIn("built-in, ", text, "no rule is handed at a start")

    def test_many_memories_leave_the_start_text_as_it_is(self):
        """However many memories the store holds, no start hands one."""
        for k in range(400):
            memory(self.t.p4, f"a-rather-long-memory-name-number-{k:03d}", "feedback", f"Rule {k} of the many.")
        for source in ("startup", "clear", "compact"):
            self.assertNotIn("a-rather-long-memory-name", self.start(KID, source), source)
        self.assertFalse(os.path.exists(os.path.join(self.t.p4, "phi", "rules.md")), "no page copies them")

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

    def test_the_plan_tool_has_a_switch_of_its_own(self):
        """`phi.plan_mode: false` in the project's p4.json withholds `EnterPlanMode` from no session, and a project
        whose sessions enter plan mode only when asked sets it."""
        self.assertEqual(self.t.rules(KID)["withholds"], [phi.PLAN_TOOL])
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"plan_mode": False}}))
        for host in (TOP, KID):
            self.assertEqual(self.t.rules(host)["withholds"], [], host)
        import p4conf
        self.assertIs(p4conf.DEFAULTS["phi"]["plan_mode"], True)
        self.assertEqual(p4conf.env_name("phi.plan_mode"), "P4_PHI_PLAN_MODE")

    def test_a_started_sessions_model_is_not_offered_the_plan_tool_and_no_text_goes_with_it(self):
        """`phi.py rules` answers the hooks module with the tools the session's model is not offered and no text:
        `EnterPlanMode` for a session another session started, none for a session ezexe is at, and none where the
        project turns the plan tool's withholding off. Neither phi.json `rules` nor P4_PHI_RULES reaches it, and
        P4_PHI=0 withholds nothing."""
        self.assertEqual(self.t.rules(KID), {"withholds": [phi.PLAN_TOOL]})
        self.assertEqual(self.t.rules(TOP), {"withholds": []})
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"rules": False}))
        self.assertEqual(self.t.rules(KID), {"withholds": [phi.PLAN_TOOL]}, "phi.json `rules` gates the memory lines")
        os.remove(os.path.join(self.t.p4, "phi", "phi.json"))
        self.assertEqual(self.t.rules(KID, P4_PHI_RULES="0"), {"withholds": [phi.PLAN_TOOL]})
        self.assertEqual(self.t.rules(KID, P4_PHI="0"), {"withholds": []})
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"plan_mode": False}}))
        self.assertEqual(self.t.rules(KID), {"withholds": []}, "the plan switch is off, so nothing is withheld")

    def test_withheld_tools_is_decided_by_who_started_the_session(self):
        self.assertEqual(phi.withheld_tools(True), [phi.PLAN_TOOL])
        self.assertEqual(phi.withheld_tools(False), [])

    def test_the_plugin_ships_no_search_agent_of_its_own(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "agents", "sweep.md")), "the plugin's own copy is gone")

    def test_the_skill_gives_the_line_that_starts_a_terminal_team_and_p4_writes_the_variable_nowhere(self):
        """desktop.md, "What's not available in Desktop": coordinated teams "are available in the CLI, not in
        Desktop". agent-teams.md, "Enable agent teams": "Spawning teammates also requires an interactive session."
        So a desktop session starts a terminal session that leads the team and talks to it by message. No settings
        keeper or hooks module writes the variable, since every session of the project reads the file it would go
        into."""
        plugins = os.path.dirname(ROOT)
        for path in (os.path.join(ROOT, "scripts", "p4conf.py"), os.path.join(ROOT, "hooks", "register.ts"),
                     os.path.join(plugins, "p4-temportal", "hooks", "p4conf.py"),
                     os.path.join(plugins, "p4-temportal", "hooks", "register.ts")):
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("AGENT_TEAMS", f.read(), path)

    def test_no_p4_setting_names_a_subagents_model_and_the_pages_name_claude_codes_own_routes(self):
        """sub-agents.md, "Choose a model": "When more than one source sets a model, Claude Code uses the first in
        this order", the call's `model`, the definition's `model` field, `CLAUDE_CODE_SUBAGENT_MODEL`, the main
        conversation's model. So p4.json holds no key for a subagent's model or effort, `phi.child_levels` takes a
        worker's kinds only."""
        import p4conf
        plans = phi.plans
        for key in p4conf.DEFAULTS["phi"]:
            self.assertNotIn("agent", key, "no key of p4.json's phi section names a subagent")
        self.assertEqual(sorted(plans.CHILD_LEVELS_DEFAULT), ["build", "design", "plan", "review", "static", "top"])
        given = plans.child_levels({"check": {"model": "claude-haiku-5-5", "effort": "low"},
                                    "Explore": {"model": "opus"}})
        self.assertEqual(given, plans.CHILD_LEVELS_DEFAULT, "a subagent's name is no kind of worker")

    def test_the_check_agent_holds_only_read_tools_and_the_agents_are_the_tables(self):
        with open(os.path.join(ROOT, "agents", "check.md"), encoding="utf-8") as f:
            front = f.read().split("---")[1]
        self.assertIn("tools: Read, Grep, Glob", front, "it still holds no tool that writes or runs")
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "agents"))), ["check.md", "finder.md", "integrator.md", "writer.md"],
                         "the agents of the skill sub-agentic's table")


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
        self.assertEqual(sorted(d), ["SessionEnd", "SessionStart", "Stop", "StopFailure", "UserPromptSubmit"],
                         "frozen: the checks around a tool call ride on the retrieval hooks' entries")
        for event, name in (("SessionStart", START), ("UserPromptSubmit", PROMPT), ("Stop", STOP),
                            ("StopFailure", "stop-failure"), ("SessionEnd", "session-end")):
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
        m = jload(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), ".claude-plugin",
                               "marketplace.json"))
        self.assertIn("p4-phi", [x["name"] for x in m["plugins"]])
        self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", "phi", "SKILL.md")))

    def test_the_repository_holds_one_catalog_at_its_root_with_each_plugin_named_by_its_folder_from_there(self):
        """The marketplace has one catalog, `.claude-plugin/marketplace.json` at the repository's root, the place
        `claude plugin marketplace add ezexe/p4` reads with no `path`. Each source is spelled from that root, by
        https://code.claude.com/docs/en/plugins/marketplace-reference.md, "Marketplace file": "The directory that
        contains `.claude-plugin/` is called the marketplace root, and every relative plugin source resolves from
        it". `lbiza/` holds no catalog of its own: found there by `path`, Claude Code 2.1.328 looked for
        `./plugins/p4-phi` at the clone's root and did not find it. An entry pins no version, since each
        plugin.json's decides, by plugins/loading.md, "How Claude Code computes the version": "The `version` field
        in the plugin's manifest comes first"."""
        repo = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))
        root = jload(os.path.join(repo, ".claude-plugin", "marketplace.json"))
        self.assertFalse(os.path.exists(os.path.join(repo, "lbiza", ".claude-plugin", "marketplace.json")),
                         "a second catalog would have to be kept in step with the first")
        self.assertEqual(root["name"], "p4-marketplace")
        folders = os.path.join(repo, "lbiza", "plugins")
        self.assertEqual(sorted(p["name"] for p in root["plugins"]),
                         sorted(d for d in os.listdir(folders)
                                if os.path.isfile(os.path.join(folders, d, ".claude-plugin", "plugin.json"))))
        for p in root["plugins"]:
            self.assertEqual(p["source"], "./lbiza/plugins/" + p["name"])
            self.assertNotIn("version", p, "each plugin.json's version decides")
            self.assertTrue(p.get("description"), p["name"])
            manifest = jload(os.path.join(repo, "lbiza", "plugins", p["name"], ".claude-plugin", "plugin.json"))
            self.assertEqual(manifest["name"], p["name"])
            self.assertTrue(manifest.get("version"), p["name"])


class FixtureFolder(unittest.TestCase):
    def test_a_tree_is_made_in_the_folder_the_tests_are_given(self):
        with tempfile.TemporaryDirectory() as given:
            folder = os.path.join(given, "fixtures")
            code = ("import tempfile, test_phi\nwith tempfile.TemporaryDirectory() as d:\n"
                    "    print(test_phi.Tree(d).p4)")
            env = {**os.environ, "P4_PHI_TEST_TMP": folder}
            r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                               cwd=os.path.dirname(os.path.abspath(__file__)), env=env, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.normcase(r.stdout.strip()).startswith(os.path.normcase(folder)), r.stdout)


class StatePage(unittest.TestCase):
    """A session whose p4-phi task names a state page resumes from it after a clear, and at a turn's end is told to
    read its context share with the app's `get_usage` and to clear itself past the line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="Build the narwhal exporter")
        self.page = os.path.join(t.tmp, "tmp", "state.md").replace("\\", "/")
        t.say(TOP, "Build the exporter")
        t.cli(TOP, "task", f"Build the narwhal exporter. State page: {self.page}")

    def tearDown(self):
        self._tmp.cleanup()

    def wrap_up(self, used, uuid):
        """TOP's `wrap_up`, answered through `recall-hook.sh lookup-record`, with a transcript whose last assistant
        row holds `used` tokens of usage, which p4-phi does not read."""
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

    def test_a_wrap_up_names_the_apps_usage_read_whatever_the_transcript_holds(self):
        """The app counts a session's context: the description of `mcp__ccd_session_mgmt__get_usage` gives `context`
        as "that session's window as the composer shows it — tokens used, percent, where auto-compact starts". So
        p4-phi sums no usage row of the transcript against a window of its own. The line at a `wrap_up` names that
        call on `"self"` and the share phi.clear_at sets, and reads the same whatever the transcript's last row
        holds and whatever a store's phi.context_window says."""
        import controls
        said = self.wrap_up(130000, "1")
        self.assertIn('`mcp__ccd_session_mgmt__get_usage` on `"self"`', said)
        self.assertIn(f"past {controls.CLEAR_AT} percent", said)
        self.assertIn(self.page, said)
        self.assertIn('`mcp__ccd_session_mgmt__clear_session` with `"self"`', said)
        self.assertLess(said.index("get_usage"), said.index("clear_session"), "the read comes before the clear")
        self.assertNotRegex(said, r"context is at \d+ percent", "p4-phi states no share of its own")
        self.assertEqual(self.wrap_up(20000, "2"), said, "the transcript's usage row is not read")
        write(os.path.join(self.t.p4, "p4.json"), json.dumps({"phi": {"context_window": 1000, "clear_at": 40}}))
        low = self.wrap_up(20000, "3")
        self.assertIn("past 40 percent", low, "phi.clear_at sets the line")
        self.assertEqual(low.replace("past 40 percent", f"past {controls.CLEAR_AT} percent"), said,
                         "phi.context_window steers nothing")


class ClearFamily(unittest.TestCase):
    """ezexe/p4#244. No page and no tool clears a session together with the sessions it started: `/clear` starts one
    conversation over, and the app's `clear_session` takes one session a call, this one or an idle session this one
    started. So a worker that keeps a state page is handed, at a turn's end, one `clear_session` call for each
    coworker p4-phi's records hold idle with an empty queue, ahead of its own, to make where `get_usage` reads its
    context past the line; and every session that keeps a state page is told at each turn's end to bring it up to
    date, so a clear its worker makes loses nothing."""

    KID3 = "local_kid00003"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        CLI.setdefault(self.KID3, "ffff6666-0000-4000-8000-000000000000")
        self.page = {h: os.path.join(t.tmp, "pad", h, "state.md").replace("\\", "/")
                     for h in (TOP, KID, KID2, self.KID3)}
        t.record(TOP, title="Build the narwhal exporter")
        t.say(TOP, "Build the exporter")
        t.cli(TOP, "task", f"Build the narwhal exporter. State page: {self.page[TOP]}")
        for host, part in ((KID, "flush"), (KID2, "ports"), (self.KID3, "retry")):
            t.record(host, started_by=TOP, title=f"the {part} coworker")
            t.say(host, handed(f"Build the {part} of the exporter.\nFiles: src/{part}.py\n"
                               f"State page: {self.page[host]}"))

    def tearDown(self):
        self._tmp.cleanup()

    def wrap_up(self, host, uuid):
        """`host`'s `wrap_up`, answered through `recall-hook.sh lookup-record` as the app runs it, with
        P4_RECALL_SYNC unset, so the gate's detach rule is part of what is tested."""
        t = self.t
        path = transcript(os.path.join(t.tmp, f"wrap-{host}-{uuid}.jsonl"), "Build it", [], "Built.", uuid)
        body = {"session_id": CLI.get(host, host), "cwd": t.proj, "hook_event_name": "PostToolUse",
                "tool_name": "mcp__ccd_turn__wrap_up", "tool_input": {"recap": "Built."},
                "tool_response": "Nothing is pending.", "transcript_path": path,
                "tool_use_id": f"toolu_wrap{host}{uuid}"}
        env = t.env(host)
        env.pop("P4_RECALL_SYNC", None)
        r = inproc.run(["sh", os.path.join(ROOT, "hooks", "recall-hook.sh"), "lookup-record"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def plan(self, host, status):
        return self.t.hook("plan", host, {"hook_event_name": "PostToolUse",
                                          "tool_name": "mcp__ccd_turn__update_plan",
                                          "tool_input": {"items": [{"content": "Build the part", "status": status}]},
                                          "tool_response": "Plan shown."})

    def test_a_worker_past_the_line_clears_its_idle_coworkers_before_itself(self):
        t, kid3 = self.t, self.KID3
        own = '`mcp__ccd_session_mgmt__clear_session` with `"self"`'
        theirs = "`mcp__ccd_session_mgmt__clear_session` on its id"
        for host in (KID, KID2):                    # a message, every plan step completed, a Stop, nothing running
            self.plan(host, "completed")
            t.stop(host, "Build the part", report="Built and checked.")
        said = self.wrap_up(TOP, "1")               # KID3 has a message and no Stop yet: it is inside a turn
        for host in (KID, KID2, kid3):
            self.assertNotIn(host, said, "a report this session has not been handed yet holds its coworker")
        self.assertNotIn(theirs, said)
        t.say(TOP, "what came in?")                 # TOP is handed both reports
        said = self.wrap_up(TOP, "2")
        self.assertIn(f"bring this session's state page up to date at {self.page[TOP]}", said)
        self.assertLess(said.index(self.page[TOP]), said.index("get_usage"), "the page first, whatever it reads")
        self.assertIn('`mcp__ccd_session_mgmt__get_usage` on `"self"`', said)
        self.assertIn(own, said)
        for host in (KID, KID2):
            self.assertIn(f"`{host}`", said)
            self.assertLess(said.index(theirs), said.index(f"`{host}`"))
            self.assertLess(said.index(f"`{host}`"), said.index(own), "a coworker's clear comes ahead of its own")
        self.assertNotIn(kid3, said, "a coworker inside a turn is named nowhere")
        self.assertIn("A coworker clear the app refuses leaves that coworker as it is", said)
        self.assertIn("the last call of this turn", said.split(own, 1)[1])
        mine = self.wrap_up(KID, "3")               # a coworker's own turn's end
        self.assertIn(f"bring this session's state page up to date at {self.page[KID]}", mine)
        self.assertIn("one the session that started it makes", mine)
        self.assertLess(mine.index(self.page[KID]), mine.index("get_usage"), "whatever its context reads")
        for other in (TOP, KID2, kid3):
            self.assertNotIn(other, mine, "it names no other session")
        self.assertNotIn(theirs, mine, "and no clear of another session")
        self.plan(KID2, "in_progress")              # an open plan step
        said = self.wrap_up(TOP, "4")
        self.assertIn(f"`{KID}`", said)
        self.assertNotIn(KID2, said, "a coworker that holds a step is named nowhere")
        path = transcript(os.path.join(t.tmp, "kid-check.jsonl"), "Run the long check", [], "Started it.", "u1")
        t.hook(STOP, KID, {"hook_event_name": "Stop", "transcript_path": path, "last_assistant_message": "Started it.",
                           "background_tasks": [{"id": "bcheck001", "type": "shell", "status": "running",
                                                 "command": "python -m pytest tests/test_ports.py"}]})
        t.record(GRAND, started_by=TOP, title="the docs coworker")       # a coworker whose task names no state page
        t.say(GRAND, handed("Write the exporter's docs.\nFiles: docs/export.md"))
        t.stop(GRAND, "Write the docs", report="Written.")
        t.say(TOP, "and now?")                      # TOP is handed KID's and the docs coworker's reports
        said = self.wrap_up(TOP, "5")
        self.assertNotIn(KID, said, "a coworker with a background task still running is named nowhere")
        self.assertNotIn(GRAND, said, "nor one with no state page to resume from, since a clear would lose its work")
        self.assertNotIn(theirs, said)
        self.assertIn(own, said, "its own clear stays")

    def test_a_coworker_with_no_state_page_is_told_once_to_keep_one_and_where(self):
        """The description of `mcp__ccd_session_mgmt__clear_session` has "The transcript starts over empty while the
        session keeps its folder, model, permissions and settings", for this session or "an idle session this
        session started". So a coworker that keeps no state page, started by a session that keeps one, would resume
        from nothing after that session's clear, and was told nothing. At its `wrap_up` it is handed one line, once,
        that says to keep a page and where, in its own scratchpad. From then on it is a session that keeps a state
        page, and the session that started it names it for a clear only once the page is written."""
        t = self.t
        lone, kid = "local_top00009", "local_kid00009"
        for k, sid in enumerate((lone, kid)):
            CLI.setdefault(sid, f"9999{k}000-0000-4000-8000-000000000000")
        pad = os.path.join(t.tmp, "temp", CLI.get(GRAND, GRAND), "scratchpad").replace("\\", "/")
        page = pad + "/state.md"
        t.record(GRAND, started_by=TOP, title="the docs coworker")       # a coworker whose task names no state page
        t.hook(PROMPT, GRAND, {"hook_event_name": "UserPromptSubmit", "scratchpad_dir": pad,
                               "prompt": handed("Write the exporter's docs.\nFiles: docs/export.md")})
        told = self.wrap_up(GRAND, "1")
        self.assertIn(f"\"Build the narwhal exporter\" `{TOP}`, which started this session, keeps a state page, and "
                      f"this session keeps none.", told)
        self.assertIn(f"on a state page of its own, {page}, rewritten at each turn's end", told)
        self.assertIn("Said once", told)
        self.assertEqual(told.count("\n"), 0, "one line")
        for other in ("clear_session", "get_usage", KID, KID2, self.KID3):
            self.assertNotIn(other, told, "it names no clear and no other session")
        self.assertEqual(writes_under_claude(told), [], "the page is in the app's scratchpad, never under .claude")
        again = self.wrap_up(GRAND, "2")
        self.assertNotIn("this session keeps none", again, "said once")
        self.assertIn(f"bring this session's state page up to date at {page}", again, "from then on it keeps one")
        self.assertIn("one the session that started it makes", again)
        ctx = context(t.hook(START, GRAND, {"hook_event_name": "SessionStart", "source": "clear"}))
        self.assertIn(page, ctx.split("\n", 1)[0], "and it is handed the page first after a clear")
        t.stop(GRAND, "Write the docs", report="Written.")
        t.say(TOP, "what came in?")                 # TOP is handed the docs coworker's report
        self.assertNotIn(GRAND, self.wrap_up(TOP, "3"), "told and not written yet: a clear would lose its work")
        write(page, "# State of the docs coworker\n")
        said = self.wrap_up(TOP, "4")
        self.assertIn(f"`{GRAND}`", said, "written: the session that started it clears it with itself")
        self.assertLess(said.index("`mcp__ccd_session_mgmt__clear_session` on its id"), said.index(f"`{GRAND}`"))
        t.record(lone, title="Build the importer")  # a session that keeps no state page, and one it started
        t.say(lone, "Build the importer")
        t.record(kid, started_by=lone, title="the parser worker")
        t.say(kid, handed("Build the parser.\nFiles: src/parse.py"))
        for host in (lone, kid):
            self.assertEqual(self.wrap_up(host, "5"), "", "no state page above it: handed nothing")
            self.assertEqual(self.wrap_up(host, "6"), "")


ASKS_WRITE = re.compile(r"\b(?:writes?|written|keeps?|kept|saves?|saved|logs?|logged|rewrit\w*|puts?|records?|"
                        r"recorded|append\w*|stores?|stored|edits?|go there|up to date at)\b", re.I)
UNDER_CLAUDE = re.compile(r"(?:^|[\s`'\"(:])([^\s`'\"(]*\.claude/[^\s`'\")]*)")
# The pages p4-phi's own scripts write in the store, which a session reads and never writes: a line may say they are
# kept or rewritten there. A state page or a decisions file is not among them, since a session writes those.
OWN_PAGES = ("book.md", "session.md", "sessions.md", "board.md", "rules.md", "ledger.md")


def writes_under_claude(text, plugin=ROOT):
    """Each sentence of `text` that asks for a write and names a path under a .claude folder; the plugin's own
    folder, which the commands it hands name, is left out, since an install keeps it under ~/.claude, and so are the
    pages p4-phi itself writes."""
    text = text.replace("\\", "/").replace(plugin.replace("\\", "/"), "<plugin>")
    out = []
    for x in re.split(r"(?<=[.;:!?])\s+|\n", text):
        paths = [p.rstrip(".,;:") for p in UNDER_CLAUDE.findall(x)]
        if ASKS_WRITE.search(x) and any(p.rsplit("/", 1)[-1] not in OWN_PAGES for p in paths):
            out.append(x)
    return out


class NoWriteUnderClaude(unittest.TestCase):
    """Row B7 of the plugin defaults inventory: every write under .claude asks ezexe, even in bypass mode, so no line
    p4-phi hands a session names a place under .claude to write. A state page is kept in the app's scratchpad."""

    PUP, CO = "local_pup00001", "local_cow00001"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="Narwhal exporter")
        t.record(KID, TOP, "Fix the dropped row")
        t.record(self.PUP, title="Control the exporter tree")
        t.record(self.CO, started_by=self.PUP, title="a coworker of the puppeteer")

    def tearDown(self):
        self._tmp.cleanup()

    def pad(self, host):
        return os.path.join(self.t.tmp, "temp", CLI.get(host, host), "scratchpad").replace("\\", "/")

    def run_hook(self, name, host, payload):
        return context(self.t.hook(name, host, {"scratchpad_dir": self.pad(host), **payload}, P4_PHI_BOOK="1"))

    def wrap_up(self, host):
        t = self.t
        path = transcript(os.path.join(t.tmp, f"wrap-{host}.jsonl"), "Check the archives", [], "Checked.")
        body ={"session_id": CLI.get(host, host), "cwd": t.proj, "hook_event_name": "PostToolUse",
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
                            (self.CO, "Check the archives.\nFiles: none")):
            said[host, "start"] = self.run_hook(START, host, {"hook_event_name": "SessionStart", "source": "startup"})
            said[host, "first"] = self.run_hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit",
                                                                "prompt": first})
        for host in (TOP, KID, self.CO):
            for source in ("compact", "clear"):
                said[host, source] = self.run_hook(START, host, {"hook_event_name": "SessionStart", "source": source})
        said[self.CO, "wrap_up"] = self.wrap_up(self.CO)
        for key, text in said.items():
            self.assertEqual(writes_under_claude(text), [], key)
        for source in ("compact", "clear"):              # the scan has the address book
            self.assertIn("address book", said[TOP, source], source)


class UsageOnRecord(unittest.TestCase):
    """A command hook is given no context fill and no plan limit, and a mod is: `$.session.usage()` "returns context
    window use and plan limits", https://code.claude.com/docs/en/plugins/mods/api.md. The plugin's hooks module
    writes them to usage.json in the session's folder, and phi.usage_of reads the file back."""

    # The line hooks/register.test.ts holds the module to, from what a live probe was answered on Claude Code 2.1.325.
    RECORD = ('{"at":1794942221358,"context":{"tokens":575167,"window":1000000,"percent":58},'
              '"rateLimits":[{"kind":"seven_day","percentUsed":82,"resetsAt":"2026-11-21T06:00:00.000Z"}]}\n')

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = Tree(self._tmp.name)
        self.path = os.path.join(self.t.dir(TOP), phi.USAGE_FILE)

    def test_the_record_the_module_writes_is_read_back(self):
        self.assertEqual(phi.usage_of(self.t.p4, TOP), {}, "no module ran for the session: no record")
        write(self.path, self.RECORD)
        self.assertEqual(phi.usage_of(self.t.p4, TOP), {
            "at": 1794942221.358,
            "context": {"tokens": 575167, "window": 1000000, "percent": 58},
            "rateLimits": [{"kind": "seven_day", "percentUsed": 82.0, "resetsAt": "2026-11-21T06:00:00.000Z"}]})
        self.assertEqual(os.listdir(self.t.dir(TOP)), [phi.USAGE_FILE], "a read writes nothing")

    def test_a_fresh_window_and_a_session_off_a_subscription_are_read_with_what_they_have(self):
        write(self.path, '{"at":1794942221358,"context":{"window":200000},"rateLimits":[]}\n')
        self.assertEqual(phi.usage_of(self.t.p4, TOP), {
            "at": 1794942221.358, "context": {"tokens": None, "window": 200000, "percent": None}, "rateLimits": []})
        write(self.path, json.dumps({"at": 1, "context": {"tokens": 10, "window": 200000, "percent": 0},
                                     "rateLimits": [{"kind": "five_hour", "percentUsed": 23.5},
                                                    {"kind": "spend_limit", "percentUsed": "much"}, "x"]}))
        got = phi.usage_of(self.t.p4, TOP)
        self.assertEqual(got["rateLimits"], [{"kind": "five_hour", "percentUsed": 23.5, "resetsAt": ""}],
                         "a window with no reset time, and an entry that is no window left out")
        self.assertEqual(got["context"], {"tokens": 10, "window": 200000, "percent": 0})

    def test_a_file_that_is_no_record_reads_as_none(self):
        """`$.fs.write` "isn't atomic: it replaces the file's content in place, so another process can read a partly
        written file", https://code.claude.com/docs/en/plugins/mods/reference.md, so a file cut short is no record."""
        for text in (self.RECORD[:40], "", "[]", '{"context": {"percent": 58}}', '{"context": {"window": true}}',
                     '{"context": "full"}'):
            write(self.path, text)
            self.assertEqual(phi.usage_of(self.t.p4, TOP), {}, text)
        self.assertEqual(phi.usage_of(self.t.p4, ""), {}, "no session")
        self.assertEqual(phi.usage_of(self.t.p4, "local_nobody"), {})
        self.assertFalse(os.path.exists(self.t.dir("local_nobody")), "a read makes no folder")

    def test_the_module_writes_the_file_and_the_line_this_reader_is_held_to(self):
        hooks = os.path.join(ROOT, "hooks")
        module = read(os.path.join(hooks, "register.ts"))
        for call in ("$.session.usage()", "on('session.measure'", f"/{phi.USAGE_FILE}`", "['look', '--folder']"):
            self.assertIn(call, module)
        held = read(os.path.join(hooks, "register.test.ts")).replace("' +\n  '", "")
        self.assertIn(self.RECORD.strip()[len('{"at":1794942221358,'):], held,
                      "the module's test and this one hold the same line")


class Stamps(unittest.TestCase):
    """ezexe/p4#248: phi.now_exact orders two writes of one minute, so its seconds and its thousandths come from one
    read of the clock. Read apart, a stamp taken in a second's first thousandths kept the second before and sorted
    almost a second early, and the later of two writes lost."""

    def test_a_later_stamp_is_never_earlier_across_a_second_boundary(self):
        real = time.time
        base = float(int(real())) + 0.9996             # four ten-thousandths before a second ends
        reads = iter([base, base + 0.0008, base + 0.5, base + 1.0])
        phi.time.time = lambda: next(reads)
        try:
            stamps = [phi.now_exact() for _ in range(4)]
        finally:
            phi.time.time = real
        self.assertEqual(stamps, sorted(stamps), "each stamp sorts at or after the one before it")
        self.assertEqual(stamps[0][-4:], ".999")
        self.assertEqual(stamps[1][-4:], ".000")
        self.assertNotEqual(stamps[0][:19], stamps[1][:19], "the second moved with the thousandths")


class Origins(unittest.TestCase):
    """Whose message a prompt is, by the origin Claude Code stamps on it: the plugin's hooks module is given the
    origin at `prompt.submit` and writes it to origin.json with the prompt's id, and the UserPromptSubmit hooks read
    it back. The types of `claude-code` call PromptOrigin "a closed set, never a text prefix"."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP)
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def keep(self, host, prompt_id, **origin):
        """What the hooks module writes for a project with no store: origin.json in the session's folder."""
        write(os.path.join(self.t.dir(host), "origin.json"), json.dumps({"promptId": prompt_id, **origin}))

    def said(self, host, prompt, prompt_id):
        return self.t.hook(PROMPT, host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                          "prompt_id": prompt_id})

    def test_each_kind_names_whose_words_a_prompt_is(self):
        import rows
        for kind in ("composer", "bridge", "slack-ping"):
            self.assertEqual(rows.whose({"kind": kind}), "user", kind)
        for kind in ("peer", "peer-send-message", "coordinator", "projects-relay"):
            self.assertEqual(rows.whose({"kind": kind}), "session", kind)
        self.assertEqual(rows.whose({"kind": "plugin", "name": "p4-phi"}), "plugin")
        self.assertEqual(rows.whose({"kind": "plugin", "name": "notes", "asUser": True}), "user")
        self.assertEqual(rows.whose({"kind": "task-notification"}), "event")
        self.assertEqual(rows.whose({"kind": "scheduled-trigger"}), "schedule")
        # the kinds that do not say whose words they carry are left to the head of the text
        for kind in ("sdk", "unclassified", "auto-continuation", "channel", "observer",
                     "observer-activity", "a-kind-of-a-later-release"):
            self.assertEqual(rows.whose({"kind": kind}), "", kind)
        self.assertEqual(rows.whose({}), "")
        self.assertEqual(rows.whose(None), "")

    def test_a_message_that_opens_with_a_slash_command_holds_no_request(self):
        """`/goal <condition>` reaches the prompt hooks as it was typed, with the origin `composer` where ezexe typed
        it and `plugin` where a hooks module ran it. Claude Code runs the command, so its words are no message to
        route: seen in a desktop session, routing drafted a session from a typed goal, titled `/goal For each of the
        three sessions`. One slash and one name is a command, commands.md, a plugin's is `/plugin-name:skill-name`,
        skills.md, and a message that opens with a path of more than one part stays ezexe's request."""
        goal = "/goal Add a retry to the narwhal exporter for when the ports table write fails, or stop after 20 turns"
        for by in ("user", "plugin", ""):
            self.assertEqual(phi.request_of(goal, by), "", by)
            self.assertEqual(phi.request_of("<system-reminder>x</system-reminder>\n" + goal, by), "", by)
        for said in ("/goal", "/goal clear", "/plan fix the exporter", "/p4-phi:readings the exporter is slow",
                     "/mcp__github__pr_review 456", "/phi-pane"):
            self.assertEqual(phi.request_of(said, "user"), "", said)
        for said in ("/goal/notes.md holds the retry plan, add it to the exporter",
                     "lib/goal is where the retry goes", "Give the exporter a /goal of its own",
                     "/ is the root, list what is in it", "/goal.md is the file to fix"):
            self.assertEqual(phi.request_of(said, "user"), said, said)

    def test_every_reader_tells_a_scheduled_prompt_and_the_sweeps_own_from_ezexes_words(self):
        """The types of `claude-code` give `scheduled-trigger` as "A scheduled task or /loop firing its stored
        prompt": nobody typed it when it came. It holds no request, a puppeteer reads it as no message of
        ezexe's, and its message row is answered like a turn and is not ezexe's. The sweep's prompt, which p4-phi
        hands a session to schedule, is told the same way by its opening words where no origin was kept, and a
        message that only quotes those words is still ezexe's."""
        import plans
        import puppeteer
        import rows
        import upkeep
        stored = "Port the flush to the new hook in hooks/flush.py"
        self.assertEqual(phi.request_of(stored, "schedule"), "")
        self.assertTrue(puppeteer.from_session(stored, "schedule"))
        self.assertTrue(upkeep.SWEEP.startswith(plans.SWEEP_MARK))
        for sweep in (upkeep.SWEEP, "<system-reminder>x</system-reminder>\n" + upkeep.SWEEP):
            self.assertEqual(phi.request_of(sweep), "")
            self.assertTrue(puppeteer.from_session(sweep))
        self.assertTrue(rows.WAKE_RE.match(upkeep.SWEEP), "rows.py spells the sweep's opening as plans.py does")
        self.assertFalse(plans.woken(upkeep.SWEEP), "the module submitted no prompt, so no wake is counted for it")
        asked = "why did the hook draft a session for this: " + plans.SWEEP_MARK
        self.assertEqual(phi.request_of(asked), asked)
        self.assertFalse(puppeteer.from_session(asked))
        self.assertEqual(rows.whose({"kind": "scheduled-trigger"}), "schedule", "a stored prompt nobody typed")

    def test_the_origin_settles_what_the_head_of_a_text_can_only_suggest(self):
        import puppeteer
        import rows
        markup = "<b>bold</b> is wrong in the exporter's page, make it plain"
        self.assertEqual(phi.request_of(markup), "", "by its opening alone it reads as Claude Code speaking")
        self.assertEqual(phi.request_of(markup, "user"), markup)
        self.assertFalse(puppeteer.from_session(markup, "user"))
        quoted = "[Cross-session idle notice] is what it said, why?"
        self.assertEqual(phi.request_of(quoted, "user"), quoted)
        self.assertFalse(puppeteer.from_session("<task-notification> pasted by hand", "user"))
        bare = "The flush is ported and pushed as 4f1c2aa."
        self.assertEqual(phi.request_of(bare, "event"), "")
        self.assertEqual(phi.request_of(bare, "plugin"), "")
        for by in ("session", "plugin", "event"):
            self.assertTrue(puppeteer.from_session(bare, by), by)
        self.assertTrue(phi.from_peer(bare, "session"))
        self.assertFalse(phi.from_peer('<cross-session-message from="local_x">hm</cross-session-message>', "user"))
        # with no origin every reader goes by the text, as before
        self.assertTrue(rows.HARNESS_RE.match("<task-notification>x</task-notification>"))
        self.assertTrue(puppeteer.from_session("<task-notification>x</task-notification>"))
        self.assertTrue(phi.from_peer('<cross-session-message from="local_x">hm</cross-session-message>'))

    def test_the_hook_reads_the_origin_kept_for_its_prompt(self):
        markup = "<b>bold</b> is wrong in the exporter's page, make it plain"
        self.keep(TOP, "p-1", kind="composer")
        self.said(TOP, markup, "p-1")
        s = self.t.session(TOP)
        self.assertEqual((s["turnBy"], s["toldBy"]), ("user", "user"))
        bare = "The flush is ported and pushed as 4f1c2aa."
        self.keep(TOP, "p-2", kind="peer")
        self.said(TOP, bare, "p-2")
        s = self.t.session(TOP)
        self.assertEqual((s["turnBy"], s["toldBy"]), ("session", "session"), "no wrapper, and still a session's")
        self.keep(TOP, "p-3", kind="task-notification")
        self.said(TOP, bare, "p-3")
        self.assertEqual(self.t.session(TOP)["turnBy"], "event")
        self.keep(TOP, "p-4", kind="plugin", name="p4-phi")
        self.said(TOP, bare, "p-4")
        self.assertEqual(self.t.session(TOP)["turnBy"], "event", "a plugin's prompt is no message of ezexe's")
        self.assertEqual(self.t.session(TOP)["task"], TASK)

    def test_a_record_of_another_prompt_or_of_a_kind_that_does_not_say_leaves_the_text_to_tell(self):
        bare = "The flush is ported and pushed as 4f1c2aa."
        self.keep(TOP, "p-old", kind="peer")
        self.said(TOP, bare, "p-new")                 # the record is of an earlier prompt
        s = self.t.session(TOP)
        self.assertEqual((s["turnBy"], s["toldBy"]), ("user", ""))
        self.t.say(TOP, bare)                          # a hook input with no prompt_id
        self.assertEqual(self.t.session(TOP)["turnBy"], "user")
        self.keep(TOP, "p-5", kind="sdk")              # the desktop app's unstamped deliveries, and a scripted run's
        self.said(TOP, '<cross-session-message from="local_x">look</cross-session-message>', "p-5")
        s = self.t.session(TOP)
        self.assertEqual((s["turnBy"], s["toldBy"]), ("session", ""), "the wrapper tells, as before")
        self.said(TOP, "<side-sessions-event>a session ended a turn</side-sessions-event>", "p-5")
        self.assertEqual(self.t.session(TOP)["turnBy"], "event")

    def test_a_project_with_a_store_keeps_the_origin_beside_a_launchs_lines(self):
        """The record of a project that has a store is in the session's folder under `phi/served`, where the hook
        that hands a launch's text to its subagent keeps it too, and it is read ahead of the session folder's."""
        import rows
        cli = CLI[TOP]
        served = os.path.join(self.t.p4, "phi", "served", "start-" + cli)
        os.makedirs(served)
        write(os.path.join(self.t.p4, "p4.json"), "{}\n")
        write(os.path.join(served, "origin.json"), json.dumps({"promptId": "p-1", "kind": "peer"}))
        payload = {"session_id": cli, "cwd": self.t.proj, "prompt_id": "p-1"}
        old = os.environ.pop("CLAUDE_PROJECT_DIR", None)
        try:
            self.assertEqual(rows.origin_dir(self.t.proj, cli), served)
            self.assertEqual(rows.origin_of(payload), {"promptId": "p-1", "kind": "peer"})
            self.assertEqual(rows.origin_of({**payload, "prompt_id": "p-2"}), {})
            self.assertEqual(rows.origin_of({**payload, "prompt_id": ""}), {})
        finally:
            if old is not None:
                os.environ["CLAUDE_PROJECT_DIR"] = old
        self.keep(TOP, "p-1", kind="composer")
        self.said(TOP, "The flush is ported.", "p-1")
        self.assertEqual(self.t.session(TOP)["turnBy"], "session")

    def test_the_turns_row_keeps_whose_words_began_it(self):
        self.keep(TOP, "p-1", kind="composer")
        self.said(TOP, "and the rest of the port", "p-1")
        self.t.stop(TOP, "and the rest of the port", report="Ported.")
        self.assertEqual(phi.load_turns(self.t.p4, TOP)[-1].get("by"), "user")
        self.t.say(TOP, "one more row")
        self.t.stop(TOP, "one more row", report="Added.", uuid="u1")
        self.assertNotIn("by", phi.load_turns(self.t.p4, TOP)[-1], "the origin did not say, so the row keeps none")

    def test_the_sender_of_a_message_is_the_one_its_wrapper_names(self):
        import rows
        model = '<cross-session-message from="local_wrk00001" from-name="worker">Checked.</cross-session-message>'
        module = ('<cross-session-message from="uds:\\\\.\\pipe\\LOCAL\\cc-msg-00" from-session="local_wrk00001" '
                  'from-name="worker" from-mode="bypass">phi (p4-phi): this session ended a turn.</cross-session-message>')
        self.assertEqual(rows.sender_of(model), "local_wrk00001")
        self.assertEqual(rows.sender_of(module), "local_wrk00001", "the socket is no session's id")
        self.assertEqual(rows.sender_of("<system-reminder>x</system-reminder>\n" + module), "local_wrk00001")
        self.assertEqual(rows.sender_of("Another Claude session sent a message: " + model), "local_wrk00001")
        self.assertEqual(rows.sender_of("it said " + model), "", "a wrapper quoted further in names no sender")
        self.assertEqual(rows.sender_of(""), "")


class ScriptedRuns(unittest.TestCase):
    """A scripted run, `claude -p` started from a desktop session's shell, inherits that session's
    CLAUDE_CODE_HOST_SESSION_ID. Its hooks reported under a CLI id the app's record of that session does not name,
    and the run was recorded as that session: its prompt became a turn of the session, and the hooks module sent its
    reply to the session's starter."""

    SCRIPTED = "cccc3333-0000-4000-8000-000000000000"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP)
        self.t.record(KID, started_by=TOP)
        self.t.say(TOP, TASK)
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"})
        self.t.say(KID, BRIEF)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_scripted_run_is_the_cli_session_it_is(self):
        before = json.dumps(self.t.session(KID), sort_keys=True)
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "startup"}, cli=self.SCRIPTED)
        self.t.say(KID, "Two questions, answered from your context alone.", cli=self.SCRIPTED)
        self.t.stop(KID, "Two questions, answered from your context alone.", report="done", cli=self.SCRIPTED)
        self.assertEqual(json.dumps(self.t.session(KID), sort_keys=True), before, "the session's record is untouched")
        self.assertEqual(phi.load_turns(self.t.p4, KID), [], "and it has no turn of the run's")
        self.assertEqual(phi.load_reports(self.t.p4, TOP), [], "and its starter no report of it")
        run = self.t.session(self.SCRIPTED)
        self.assertEqual(run.get("cliSessionIds"), [self.SCRIPTED])
        self.assertFalse(phi.spawned_from(run), "the run is no child of the session's starter")

    def test_the_modules_look_of_a_scripted_run_names_no_starter(self):
        """The hooks module runs `phi.py look --folder` with the process's own CLI id in CLAUDE_CODE_SESSION_ID, and
        sends a turn's report to the starter that answer names."""
        own = json.loads(inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look",
                                     "--folder"], capture_output=True, text=True, env=self.t.env(KID),
                                    cwd=self.t.proj, timeout=60).stdout.strip().splitlines()[-1])
        self.assertTrue(own.get("starter"), "the session itself has one")
        env = {**self.t.env(KID), "CLAUDE_CODE_SESSION_ID": self.SCRIPTED}
        ran = json.loads(inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look",
                                     "--folder"], capture_output=True, text=True, env=env, cwd=self.t.proj,
                                    timeout=60).stdout.strip().splitlines()[-1])
        self.assertFalse(ran.get("starter"))
        self.assertNotEqual(ran.get("dir"), own.get("dir"))

    def test_a_session_that_goes_on_under_a_new_cli_id_is_still_itself(self):
        cleared = "dddd4444-0000-4000-8000-000000000000"
        self.t.hook(START, KID, {"hook_event_name": "SessionStart", "source": "clear"}, cli=cleared)
        self.t.say(KID, "and the rest", cli=cleared)
        self.assertEqual(self.t.session(KID)["cliSessionIds"], [CLI[KID], cleared])
        self.assertFalse(os.path.isdir(self.t.dir(cleared)), "no session of its own was made for the new id")
        # the app's record catches up, and names the new id
        d = json.loads(open(os.path.join(self.t.app, KID + ".json"), encoding="utf-8").read())
        d["cliSessionId"] = cleared
        write(os.path.join(self.t.app, KID + ".json"), json.dumps(d))
        self.t.say(KID, "one more", cli=cleared)
        self.assertEqual(self.t.session(KID)["cliSessionIds"], [CLI[KID], cleared])

    def test_a_record_that_names_no_cli_session_holds_nothing_against_the_host_id(self):
        new = "local_new00001"
        write(os.path.join(self.t.app, new + ".json"), json.dumps(
            {"sessionId": new, "cwd": self.t.proj, "originCwd": self.t.proj, "title": "new"}))
        self.t.hook(PROMPT, new, {"hook_event_name": "UserPromptSubmit", "prompt": TASK}, cli="eeee5555-0000")
        self.assertEqual(self.t.session(new)["task"], TASK)


class ToolCommands(unittest.TestCase):
    """The command lines the plugin's hooks module runs for its three tools, `mcp__p4-phi__note`, `mcp__p4-phi__done`
    and `mcp__p4-phi__tree`: the options first, then `--`, then the words of the call, so a finding that opens with a
    dash is the finding and no option. hooks/register.test.ts holds the module to these lines."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP)
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def test_note_keeps_a_finding_that_opens_with_a_dash(self):
        claim = "-v is the flag that prints the flush table"
        r = self.t.cli(TOP, "note", "--source", "flush.py:12", "--kind", "decision", "--", claim)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "kept"), r.stderr)
        kept = phi.load_notes(self.t.p4, TOP)[-1]
        self.assertEqual((kept["claim"], kept["source"], kept["kind"]), (claim, "flush.py:12", "decision"))
        again = self.t.cli(TOP, "note", "--source", "flush.py:12", "--", claim)
        self.assertEqual(again.stdout.strip(), "already kept")
        # a finding with no source is refused, and the tool hands that back as the call's error
        r = self.t.cli(TOP, "note", "--", "The ports table is written by flush_rows")
        self.assertEqual(r.returncode, 2)
        self.assertIn("a note needs its source", r.stderr)

    def test_goal_ask_keeps_a_condition_that_opens_with_a_dash(self):
        """The fourth tool, `mcp__p4-phi__goal`, runs `phi.py goal ask -- <condition>`: the condition is kept for the
        next look whatever it opens with, and what the command prints is the tool's result."""
        condition = "--strict passes on the catalog, and the commit is on origin/main"
        r = self.t.cli(TOP, "goal", "ask", "--", condition)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, phi.GOAL_ASKED), r.stderr)
        self.assertEqual(self.t.session(TOP)["goalAsk"]["condition"], condition)
        r = self.t.cli(TOP, "goal", "ask", "--", "off")
        self.assertEqual((r.returncode, r.stderr.strip()), (2, "phi: " + phi.GOAL_SHORT))

    def test_done_takes_its_text_after_the_separator_and_refuses_a_short_one(self):
        r = self.t.cli(TOP, "done", "--", "-q run of pytest passed, 12 of 12")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("this turn will be kept as done", r.stdout)
        self.assertEqual(self.t.session(TOP)["done"]["text"], "-q run of pytest passed, 12 of 12")
        r = self.t.cli(TOP, "done", "--", "ok")
        self.assertEqual((r.returncode, r.stderr.strip()), (2, "phi: say what was run and what it showed"))

    def test_tree_prints_the_session(self):
        r = self.t.cli(TOP, "tree")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(TOP, r.stdout)


class AppTools(unittest.TestCase):
    """Unless phi.json turns `app_tools` off, the plugin's hooks module asks the desktop app's own tools for sessions,
    `get_session` and `list_sessions`, and leaves what they answered in app.json. A session is read from that file
    first, and from the app's record file, which no docs page describes, where the file is absent, stale or does not
    hold the session, and for a key the tools do not answer. The setting is on unless a store turns it off, and
    with it off no look asks for the tools."""

    ON = {"P4_PHI_APP_TOOLS": "1"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def answers(self, host, own=None, linked=None, age=0.0, folder=""):
        """What the module writes for the CLI session of `host`: the answer of `get_session` for the session itself
        and the rows of `list_sessions`, in the store's served folder, or in `folder`."""
        if not folder:
            write(os.path.join(self.t.p4, "p4.json"), "{}\n")
            folder = phi.rows.origin_dir(self.t.proj, CLI[host])
        path = os.path.join(folder, phi.APP_FILE)
        d = {"at": 0, **({"self": own} if own else {}), **({"sessions": linked} if linked is not None else {})}
        write(path, json.dumps(d) + "\n")
        if age:
            os.utime(path, (time.time() - age, time.time() - age))
        return path

    def read(self, host, sid, key):
        """One key of the app's record of `sid`, as a process of the session `host` reads it."""
        code = "import json, sys, phi\nme = phi.Me()\nprint(json.dumps(phi.app_record(sys.argv[1]).get(sys.argv[2])))"
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", "import sys\nsys.path.insert(0, sys.argv.pop(1))\n"
                            + code, SRC, sid, key], capture_output=True, text=True, env=self.t.env(host),
                           cwd=self.t.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def look(self, *args, **env):
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look", *args],
                       capture_output=True, text=True, cwd=self.t.proj, timeout=60,
                       env=self.t.env(TOP, P4_PHI_WATCH="1", P4_PHI_WATCH_NET="0", **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_look_asks_for_the_tools_unless_the_setting_is_off(self):
        """On is the default: a store that sets nothing has a look ask for the tools, `app_tools` false in its
        phi.json or P4_PHI_APP_TOOLS=0 for one run has it ask for none, and the variable set to 1 stands over a
        store's false."""
        self.assertIs(phi.APP_TOOLS, True, "on unless a project turns it off")
        self.assertIs(self.look().get("app_tools"), True, "the store sets nothing")
        self.assertNotIn("app_tools", self.look("--folder"), "the folder question asks for nothing")
        self.assertNotIn("app_tools", self.look(P4_PHI_APP_TOOLS="0"))
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"app_tools": False}))
        self.assertNotIn("app_tools", self.look(), "the store turned it off")
        self.assertIs(self.look(**self.ON).get("app_tools"), True)
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"app_tools": True}))
        self.assertIs(self.look().get("app_tools"), True)
        self.assertNotIn("app_tools", self.look(P4_PHI_APP_TOOLS="0"))
        write(os.path.join(self.t.p4, "phi", "phi.json"), json.dumps({"app_tools": "yes"}))
        self.assertIs(self.look().get("app_tools"), True, "a value that is no true or false leaves the default")

    def test_app_tools_is_on_by_default(self):
        self.assertIs(phi.APP_TOOLS, True)

    def test_app_tools_on_and_off_write_the_key_a_look_reads_and_say_how_it_stands(self):
        """A session writes nothing under `.claude` with its own tools, so `phi.py app_tools on` and `app_tools off`
        set the key in the store's phi/phi.json, as `goal on` sets its own: the file's other keys are kept, the line
        says how the key stands as read back, and a look answers `app_tools` until `off` and from `on`. With neither
        word the command writes nothing and says how the key stands, which is on for a store that has not set it,
        and a file that does not parse is left as it is."""
        path = os.path.join(self.t.p4, "phi", "phi.json")
        write(path, json.dumps({"goal": True}))
        r = self.t.cli(TOP, "app_tools")
        self.assertEqual((r.returncode, r.stdout.strip().split(" in ")[0]), (0, "app_tools is on"), r.stderr)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"goal": True}, "asking how it stands writes nothing")
        r = self.t.cli(TOP, "app_tools", "off")
        self.assertTrue(r.stdout.strip().startswith("app_tools is off in "), r.stdout)
        self.assertNotIn("app_tools", self.look(), "the way out: the store's own key turns it off")
        self.assertEqual(self.t.cli(TOP, "app_tools").stdout.strip(), r.stdout.strip())
        r = self.t.cli(TOP, "app_tools", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        said = r.stdout.strip()
        self.assertTrue(said.startswith("app_tools is on in ") and said.endswith("/phi/phi.json"), said)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"goal": True, "app_tools": True})
        self.assertIs(self.look().get("app_tools"), True, "no variable is set: the store's own key turns it on")
        self.assertEqual(self.t.cli(TOP, "app_tools").stdout.strip(), said)
        r = self.t.cli(TOP, "app_tools", "off")
        self.assertTrue(r.stdout.strip().startswith("app_tools is off in "), r.stdout)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"goal": True, "app_tools": False})
        self.assertNotIn("app_tools", self.look())
        write(path, "{not json")
        r = self.t.cli(TOP, "app_tools", "on")
        self.assertEqual(r.returncode, 2, "a file that does not parse is left as it is")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")

    def test_a_session_is_read_from_the_tools_answer_and_the_rest_from_its_record(self):
        self.t.record(KID, TOP, title="the record's title")
        self.answers(KID, own={"sessionId": KID, "title": "the tool's title", "cwd": self.t.proj,
                               "originCwd": self.t.proj, "isArchived": False, "parentSessionId": TOP,
                               "detached": False, "group": None, "worktreePath": "elsewhere"})
        self.assertEqual(self.read(KID, KID, "title"), "the tool's title")
        self.assertEqual(self.read(KID, KID, "spawnedFrom"), {"sessionId": TOP})
        self.assertEqual(self.read(KID, KID, "cliSessionId"), CLI[KID], "the tools name no CLI session")
        self.assertEqual(self.read(KID, KID, "startChain"), {"firstSessionId": TOP, "depth": 1})
        self.assertIsNone(self.read(KID, KID, "worktreePath"), "not the tool's, which differs from the record's")
        self.assertEqual(self.read(KID, TOP, "title"), "top", "a session the file does not hold is its record's")

    def test_a_session_with_no_record_file_is_served_by_the_tools_alone(self):
        self.answers(TOP, own={"sessionId": TOP, "title": "top", "cwd": self.t.proj},
                     linked=[{"sessionId": KID, "title": "port the flush", "cwd": self.t.proj, "isArchived": True,
                              "startedBy": TOP, "name": "flush"}])
        self.assertEqual(self.read(TOP, KID, "title"), "port the flush")
        self.assertEqual(self.read(TOP, KID, "spawnedFrom"), {"sessionId": TOP, "name": "flush"})
        self.assertIs(self.read(TOP, KID, "isArchived"), True)
        self.assertIsNone(self.read(TOP, KID, "cliSessionId"))

    def test_an_answer_with_no_starter_leaves_the_starter_to_the_record(self):
        """`list_sessions` names no starter for a session moved to top level, where its record still does, and the
        app writes a new session's starter into its record after the session's first hook."""
        self.t.record(KID, TOP)
        self.t.record(KID2, TOP)
        self.answers(KID2, own={"sessionId": KID2, "title": "just started", "cwd": self.t.proj},
                     linked=[{"sessionId": KID, "title": "moved to top level", "cwd": self.t.proj}])
        self.assertEqual(self.read(KID2, KID, "title"), "moved to top level")
        self.assertEqual((self.read(KID2, KID, "spawnedFrom") or {}).get("sessionId"), TOP)
        self.assertEqual((self.read(KID2, KID2, "spawnedFrom") or {}).get("sessionId"), TOP)

    def test_a_stale_file_and_another_sessions_file_are_not_read(self):
        self.t.record(KID, TOP, title="the record's title")
        path = self.answers(KID, own={"sessionId": KID, "title": "the tool's title"}, age=phi.APP_FRESH_S + 60)
        self.assertEqual(self.read(KID, KID, "title"), "the record's title", "older than the file is believed")
        os.utime(path)
        self.assertEqual(self.read(KID, KID, "title"), "the tool's title")
        self.assertEqual(self.read(TOP, KID, "title"), "the record's title", "the file of another CLI session")

    def test_a_project_with_no_served_folder_reads_the_file_in_the_session_folder(self):
        self.t.record(KID, TOP, title="the record's title")
        self.t.say(KID, BRIEF)
        self.answers(KID, own={"sessionId": KID, "title": "the tool's title", "parentSessionId": TOP},
                     linked=[{"sessionId": KID2, "title": "a sibling", "startedBy": TOP}], folder=self.t.dir(KID))
        self.assertEqual(self.read(KID, KID2, "title"), "a sibling")

    def test_a_project_with_no_served_folder_reads_itself_and_its_starter_from_that_file_too(self):
        """Seen in the desktop app on Claude Code 2.1.326, in a session in a worktree whose project has no store: the
        module wrote the answers into the session's folder in the tree's store, and python still read the session
        and the session that started it from their record files, since it reads both to find that folder and kept
        what it read. Once the folder is known, what the answers hold is read from them, and a key the tools do not
        answer still comes from the record file."""
        self.t.record(KID, TOP, title="the record's title")
        self.t.say(KID, BRIEF)
        self.answers(KID, own={"sessionId": KID, "title": "the tool's title", "parentSessionId": TOP},
                     linked=[{"sessionId": TOP, "title": "the tool's title of the starter"}], folder=self.t.dir(KID))
        self.assertEqual(self.read(KID, KID, "title"), "the tool's title")
        self.assertEqual(self.read(KID, TOP, "title"), "the tool's title of the starter")
        self.assertEqual(self.read(KID, KID, "cliSessionId"), CLI[KID], "the tools name no CLI session")
        code = ("import json, sys, phi\nme = phi.Me()\n"
                "print(json.dumps([type(me.rec).__name__, me.rec.get('title'), phi.spawned_from(me.rec)]))")
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", "import sys\nsys.path.insert(0, sys.argv.pop(1))\n"
                            + code, SRC], capture_output=True, text=True, env=self.t.env(KID), cwd=self.t.proj,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), ["AppRow", "the tool's title", TOP])

    def test_a_hook_takes_the_session_and_its_starter_from_the_tools_with_no_record_file(self):
        self.answers(KID, own={"sessionId": KID, "title": "port the flush", "cwd": self.t.proj,
                               "parentSessionId": TOP})
        self.assertEqual(self.t.say(KID, BRIEF).returncode, 0)
        self.assertEqual(self.t.started_by(KID), (TOP, "record"))
        self.assertEqual(self.t.session(KID)["title"], "port the flush")
        self.assertEqual(self.t.session(KID)["cliSessionIds"], [CLI[KID]])

    def test_a_hook_with_no_host_id_finds_its_session_in_the_modules_file(self):
        """A hook whose environment names no host session searched the newest record files for its CLI id. The
        module's file is that CLI session's own, so the session it answers is the one."""
        self.answers(KID, own={"sessionId": KID, "title": "port the flush", "cwd": self.t.proj,
                               "parentSessionId": TOP})
        env = {k: v for k, v in self.t.env(KID).items() if k != "CLAUDE_CODE_HOST_SESSION_ID"}
        code = "import json, sys\nsys.path.insert(0, sys.argv[1])\nimport phi\nprint(phi.Me().id)"
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code, SRC], capture_output=True, text=True,
                           env=env, cwd=self.t.proj, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, KID), r.stderr)

    def test_a_scripted_run_under_an_inherited_host_id_has_no_file_and_stays_itself(self):
        """The check of a scripted run rests on `cliSessionId` of the host's record file, which the tools do not
        give: with the host session's answers on disk, a run under another CLI id is still no such session."""
        scripted = "cccc3333-0000-4000-8000-000000000000"
        self.t.record(KID, TOP)
        self.t.say(KID, BRIEF)
        self.answers(KID, own={"sessionId": KID, "title": "port the flush", "parentSessionId": TOP})
        before = json.dumps(self.t.session(KID), sort_keys=True)
        self.t.say(KID, "Two questions, answered from your context alone.", cli=scripted)
        self.assertEqual(json.dumps(self.t.session(KID), sort_keys=True), before)
        self.assertEqual(self.t.session(scripted).get("cliSessionIds"), [scripted])


class Places(unittest.TestCase):
    """A node's folder: a session another session started is given a folder of phi/tree nested in its starter's at its
    first hook, relay.claim, and its address follows its parent's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="Narwhal exporter")
        self.t.say(TOP, TASK)

    def tearDown(self):
        self._tmp.cleanup()

    def kid(self, host, above=TOP):
        self.t.record(host, above, host)
        self.t.say(host, HANDED)

    def store(self, host):
        relay.forget(self.t.p4)
        return relay.nodes(self.t.p4).get(host, "")

    def flat(self, host):
        return relay.flat(self.t.p4, host)

    def address(self, host):
        import node
        relay.forget(self.t.p4)
        return node.addresses(self.t.p4, relay._sessions(self.t.p4)).get(host)

    def test_a_started_session_gets_a_node_at_its_first_hook_with_its_session_json_and_no_flat_folder(self):
        self.kid(KID)
        node = self.store(KID)
        self.assertEqual(os.path.normcase(node), os.path.normcase(os.path.join(self.t.p4, "phi", "tree", KID)))
        self.assertTrue(os.path.isfile(os.path.join(node, "session.json")))
        self.assertEqual(jload(os.path.join(node, relay.NODE))["kind"], "session")
        self.assertEqual(jload(os.path.join(node, relay.NODE))["parent"], TOP)
        self.assertFalse(os.path.exists(self.flat(KID)), "no flat folder is made")
        self.assertEqual(self.store(TOP), "", "a top stays flat")
        self.assertTrue(os.path.isfile(os.path.join(self.flat(TOP), "session.json")))

    def test_three_children_stand_101_1001_10001_and_a_hook_after_moves_none(self):
        for host in (KID, KID2, GRAND):
            self.kid(host)
        self.t.say(KID, "Again.")
        self.t.stop(KID, HANDED, [], "Half done.")
        self.assertEqual([self.address(h) for h in (TOP, KID, KID2, GRAND)], ["1", "101", "1001", "10001"])
        self.assertEqual(len(relay.nodes(self.t.p4)), 3)

    def test_the_child_of_a_nested_session_is_nested_in_that_sessions_folder(self):
        self.kid(KID)
        self.kid(GRAND, KID)
        self.assertEqual(os.path.normcase(self.store(GRAND)),
                         os.path.normcase(os.path.join(self.store(KID), GRAND)))
        self.assertEqual(self.address(GRAND), "10101")

    def test_a_session_whose_flat_folder_is_there_stays_flat_with_its_later_files_beside_it(self):
        write(os.path.join(self.flat(KID), "log.jsonl"), json.dumps({"hook": "failed"}) + "\n")
        self.kid(KID)
        self.t.stop(KID, HANDED, [], "Half done.")
        self.assertEqual(self.store(KID), "")
        for name in ("session.json", "turns.jsonl", "log.jsonl"):
            self.assertTrue(os.path.isfile(os.path.join(self.flat(KID), name)), name)
        self.assertEqual(self.address(KID), "1")
        self.assertFalse(os.path.isdir(os.path.join(self.t.p4, "phi", "tree")), "no node was made")

    def test_a_first_prompts_hooks_leave_every_file_of_a_started_session_in_its_node(self):
        self.kid(KID)
        self.t.stop(KID, HANDED, [], "Half done.")
        folder = self.store(KID)
        for name in ("session.json", "turns.jsonl", "log.jsonl"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertFalse(os.path.exists(self.flat(KID)))
        self.assertEqual(os.path.normcase(self.t.dir(KID)), os.path.normcase(folder))

    def test_a_record_first_made_with_no_parent_stays_flat_once_it_is_given_one(self):
        self.t.record(KID, title="Fix the dropped row")
        self.t.say(KID, HANDED)
        self.assertEqual(self.t.started_by(KID)[0], "")
        self.t.record(KID, TOP, "Fix the dropped row")
        self.t.say(KID, "Next.")
        self.assertEqual(self.t.started_by(KID)[0], TOP)
        self.assertEqual(self.store(KID), "", "its flat folder was there first")

    def test_a_child_recorded_before_its_parents_record_is_there_is_nested_once_the_parents_is_ensured(self):
        other = Tree(os.path.join(self._tmp.name, "other"))
        other.record("local_up000001", title="Up")
        other.record(KID, "local_up000001", "Down")
        other.say(KID, HANDED)
        relay.forget(other.p4)
        self.assertTrue(os.path.isfile(os.path.join(relay.flat(other.p4, "local_up000001"), "session.json")))
        self.assertEqual(os.path.normcase(relay.nodes(other.p4).get(KID, "")),
                         os.path.normcase(os.path.join(other.p4, "phi", "tree", KID)))

    def test_a_reparented_session_keeps_its_store_and_a_detached_one_too(self):
        for host in (KID, KID2):
            self.kid(host)
        held = self.store(KID2)
        self.assertEqual(self.t.cli(TOP, "reparent", KID2, KID).returncode, 0)
        self.assertEqual(self.t.started_by(KID2)[0], KID)
        self.assertEqual(self.store(KID2), held)
        self.assertEqual(self.address(KID2), "1001", "the address of the node it has")
        self.assertEqual(self.t.cli(TOP, "detach", KID2).returncode, 0)
        self.assertEqual(self.store(KID2), held)

    def test_a_session_json_gets_no_key_for_a_place(self):
        self.kid(KID)
        keys = set(self.t.session(KID))
        self.assertFalse([k for k in keys if "place" in k.lower() or "address" in k.lower() or "child" in k.lower()], keys)
        self.assertEqual(self.t.session(TOP).keys() & {"children", "places"}, set())

    def test_the_tree_prints_each_session_with_its_address_and_level_and_its_leaves_under_it(self):
        self.kid(KID)
        write(os.path.join(self.t.dir(KID), "team.json"), json.dumps(
            {"teammates": [{"name": "fences", "task": "x", "state": "idle", "doing": ""}]}))
        out = self.t.cli(TOP, "tree").stdout.splitlines()
        self.assertEqual(out[0], f"- 1 puppeteer \"Narwhal exporter\" `{TOP}`: no turn yet, 0 turns")
        self.assertRegex(out[1], rf'^  - 101 orchestrator "{KID}" `{KID}`: ')
        self.assertEqual(out[2], "    - teammate fences: idle")

    def test_node_prints_the_record_of_this_session(self):
        self.kid(KID)
        got = json.loads(self.t.cli(KID, "node").stdout)
        self.assertEqual((got["id"], got["level"], got["address"], got["parent"], got["places"]),
                         (KID, "orchestrator", "101", TOP, [1]))
        self.assertEqual(json.loads(self.t.cli(TOP, "node", KID).stdout)["address"], "101")
        self.assertEqual(self.t.cli(TOP, "node", "local_none0001").returncode, 2)


TICKS = chr(96) * 3
WORKER_PLAN = ("# The exporter's move\n\n## Context\n\nNo worker lands this.\n\n"
               "## 1. The writer\n\n- **Files:** `src/export/writer.py`\n- **Checks:** `python -m pytest t.py`\n\n"
               f"{TICKS}python\nx = 1\n{TICKS}\n\n"
               "## 2. The page\n\n- **Files:** `docs/export.md`\n- **Depends on:** 1\n\n"
               f"{TICKS}markdown\nA line.\n{TICKS}\n")


class TerminalWorker(unittest.TestCase):
    """`phi.py coworkers --land` and `--wait --report`, the terminal worker of a plan's sections, in its node."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="p4-phi-worker-", dir=FIXTURES or None)
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.plan = os.path.join(self.base, "plan.md")
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write(WORKER_PLAN)
        self.home = os.path.join(self.base, "proj", ".claude", "p4")
        os.makedirs(self.home)
        self.app = os.path.join(self.base, "app")

    def mode(self, name, mode):
        os.makedirs(os.path.join(self.app, "acct", "org"), exist_ok=True)
        with open(os.path.join(self.app, "acct", "org", name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"sessionId": name, "permissionMode": mode}, f)

    def run_phi(self, *args, session="local_plan0001"):
        env = {**os.environ, "P4_PHI_APP_SESSIONS": self.app}
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "coworkers",
                               self.plan, "--p4", self.home, "--session", session, "--checkout", self.base, *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def node(self):
        """The folder of the worker's node: the planner is no node, so it is the one folder of phi/tree."""
        tree = os.path.join(self.home, "phi", "tree")
        (name,) = os.listdir(tree)
        return os.path.join(tree, name)

    def test_land_from_a_mode_that_asks_or_none_known_writes_the_start_in_bypass_permissions_mode(self):
        """A landing worker always starts in bypassPermissions mode, so what mode its starter is in, or whether the
        app's record names one, changes nothing about its start file."""
        self.mode("local_plan0002", "plan")
        self.mode("local_plan0003", "default")
        for k, session in enumerate(("local_plan0002", "local_plan0003", "cli-0001", "local_nomode001")):
            self.home = os.path.join(self.base, f"proj{k}", ".claude", "p4")
            os.makedirs(self.home)
            ran = self.run_phi("--land", session=session)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            start = next(f for f in os.listdir(self.node()) if f.startswith("start-"))
            with open(os.path.join(self.node(), start), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("--permission-mode bypassPermissions", text, session)
            self.assertNotIn("--permission-mode plan", text, session)
            self.assertNotIn("--permission-mode default", text, session)

    def test_land_from_auto_writes_one_start_file_and_one_brief_into_the_node_and_a_second_land_writes_nothing(self):
        self.mode("local_plan0001", "auto")
        ran = self.run_phi("--land")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        files = sorted(os.listdir(self.node()))
        self.assertEqual([f.split("-")[0].split(".")[0] for f in files], ["brief", "coworker", "node", "resume", "start"])
        self.assertEqual(ran.stdout.count("`mcp__terminal__run_in_terminal` with "), 1, "sections 1 and 2 are one run")
        self.assertIn(f'"cwd": "{self.base.replace(chr(92), "/")}"', ran.stdout, "it runs in the checkout")
        start = next(f for f in files if f.startswith("start-"))
        with open(os.path.join(self.node(), start), encoding="utf-8") as f:
            text = f.read()
        for word in ("--worktree", "--add-dir", "EXPERIMENTAL_AGENT_TEAMS"):
            self.assertNotIn(word, text, word)
        self.assertIn("--permission-mode bypassPermissions", text)
        before = {f: os.path.getmtime(os.path.join(self.node(), f)) for f in files}
        again = self.run_phi("--land")
        self.assertEqual(again.returncode, 2)
        self.assertIn("was started already", again.stderr)
        self.assertIn(self.node().replace(chr(92), "/"), again.stderr, "with its node's folder")
        self.assertEqual(sorted(os.listdir(self.node())), files)
        self.assertEqual({f: os.path.getmtime(os.path.join(self.node(), f)) for f in files}, before)

    def test_land_claims_a_worker_node_under_the_planner_and_leaves_names_it(self):
        self.mode("local_plan0001", "auto")
        self.assertEqual(self.run_phi("--land").returncode, 0)
        n = jload(os.path.join(self.node(), relay.NODE))
        self.assertEqual((n["kind"], n["parent"], n["sections"]), ("worker", "local_plan0001", ["1", "2"]))
        import node
        relay.forget(self.home)
        got = node.leaves(self.home, "local_plan0001")
        self.assertEqual([(x["level"], x["name"], x["address"], x["state"]) for x in got],
                         [("terminal", n["id"], "101", "started")])
        self.assertFalse(os.path.exists(os.path.join(self.home, "phi", "sessions", "local_plan0001",
                                                     "terminals.json")))

    def test_a_quote_in_the_homes_path_makes_land_write_nothing_and_claim_nothing_each_time(self):
        self.mode("local_plan0001", "auto")
        self.home = os.path.join(self.base, "it's", "proj", ".claude", "p4")
        os.makedirs(self.home)
        for _ in range(2):
            ran = self.run_phi("--land")
            self.assertEqual(ran.returncode, 2, ran.stdout)
            self.assertIn("hold no quote", ran.stderr)
            self.assertNotIn("started already", ran.stderr)
            self.assertFalse(os.path.exists(os.path.join(self.home, "phi", "tree")))

    def rows(self):
        return phi.read_rows(os.path.join(self.home, "phi", "worker-starts.jsonl"))

    def test_land_appends_a_start_row_and_a_wait_appends_an_outcome_row_and_balance_sums_them_per_mode(self):
        self.mode("local_plan0001", "auto")
        ran = self.run_phi("--land")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("mode print (the default), profile p4-workers (the pair of print)", ran.stdout)
        (start,) = self.rows()
        self.assertEqual((start["event"], start["mode"], start["profile"], start["kind"], start["starter"]),
                         ("start", "print", "p4-workers", "land", "local_plan0001"))
        self.assertTrue(start["log"].endswith(f"log-{start['name']}.jsonl"))
        write(start["log"], json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                        "total_cost_usd": 0.25, "num_turns": 6, "duration_ms": 900}) + "\n")
        write(start["report"], "done")
        waited = self.run_phi_report(start["report"])
        self.assertEqual(waited.returncode, 0, waited.stderr)
        out = self.rows()[-1]
        self.assertEqual((out["event"], out["name"], out["how"], out["total_cost_usd"], out["num_turns"],
                          out["is_error"], out["subtype"], out["duration_ms"]),
                         ("outcome", start["name"], "done", 0.25, 6, False, "success", 900))
        bal = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "balance", "--p4",
                              self.home, "--session", "local_plan0001"], capture_output=True, text=True, timeout=60)
        self.assertEqual(bal.returncode, 0, bal.stderr)
        self.assertIn("print: 1 starts, 1 done, 0 failed, cost 0.2500 total 0.2500 mean, turns 6.0 mean", bal.stdout)
        self.assertIn("interactive: 0 starts, 0 done, 0 failed", bal.stdout)
        self.assertIn("all: 1 starts, 1 done", bal.stdout)

    def test_balance_reads_the_cost_from_the_log_where_the_result_row_came_after_the_wait(self):
        """Seen live on 2026-11-24: a worker writes its report, the wait ends and records its outcome, and the run's
        final result row, with the cost, lands in the log a turn later."""
        self.mode("local_plan0001", "auto")
        self.assertEqual(self.run_phi("--land").returncode, 0)
        (start,) = self.rows()
        write(start["log"], json.dumps({"type": "assistant", "message": {"id": "m1", "content": []}}) + "\n")
        write(start["report"], "done")
        self.assertEqual(self.run_phi_report(start["report"]).returncode, 0)
        self.assertNotIn("total_cost_usd", self.rows()[-1], "no result row yet when the wait ended")
        with open(start["log"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                "total_cost_usd": 0.5, "num_turns": 4}) + "\n")
        bal = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "balance", "--p4",
                              self.home, "--session", "local_plan0001"], capture_output=True, text=True, timeout=60)
        self.assertIn("print: 1 starts, 1 done, 0 failed, cost 0.5000 total 0.5000 mean, turns 4.0 mean", bal.stdout)

    def run_phi_report(self, report):
        env = {**os.environ, "P4_PHI_APP_SESSIONS": self.app}
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "coworkers", "--wait",
                               "--report", report, "--p4", self.home, "--session", "local_plan0001"],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_wait_report_passes_over_a_report_older_than_the_wait(self):
        import coworker
        report = os.path.join(self.base, "report-tw-the-exporter-s-m-1-2-abcd.md")
        with open(report, "w", encoding="utf-8") as f:
            f.write("the first report\n")
        old = time.time() - 600
        os.utime(report, (old, old))
        now = [0.0]

        def sleep(s):
            now[0] += s
            if now[0] >= 20:
                with open(report, "w", encoding="utf-8") as f:
                    f.write("the second report\n")
        self.assertEqual(coworker.wait_report(report, longest=60, clock=lambda: now[0], sleep=sleep), ("done", 20))
        now[0] = 0.0
        self.assertEqual(coworker.wait_report(report + ".none", longest=30, clock=lambda: now[0],
                                              sleep=lambda s: now.__setitem__(0, now[0] + s)), ("long", 30))


class PoolState(unittest.TestCase):
    """pool_state, log_of_row, last_rate_limit, and the pool-aware worker_settings, each on its own temp store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="p4-phi-pools-", dir=FIXTURES or None)
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.base, "proj", ".claude", "p4")
        os.makedirs(os.path.join(self.home, "phi"))
        self.now = time.time()

    def ledger(self):
        return os.path.join(self.home, "phi", "worker-starts.jsonl")

    def stamp(self, ago=0.0):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.now - ago))

    def row(self, row, ago=0.0):
        phi.append_line(self.ledger(), {"time": self.stamp(ago), **row})

    def start(self, name, profile, lines=(), ago=0.0, mode="print"):
        log = os.path.join(self.home, "logs", f"log-{name}.jsonl").replace("\\", "/")
        if lines is not None:
            write(log, "".join(json.dumps(x) + "\n" for x in lines))
        self.row({"event": "start", "name": name, "mode": mode, "profile": profile, "log": log}, ago)
        return log

    def window(self, u, resets=None, status="allowed"):
        resets = self.now + 3600 if resets is None else resets
        return {"type": "rate_limit_event", "rate_limit_info": {
            "status": status, "resetsAt": resets, "rateLimitType": "seven_day",
            "unifiedWindows": {"seven_day": {"utilization": u, "resetsAt": resets, "status": status}}}}

    def usage(self, sid, pct, limits=True):
        iso = datetime.datetime.fromtimestamp(self.now + 3600, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        write(os.path.join(self.home, "phi", "sessions", sid, "usage.json"), json.dumps(
            {"at": self.now * 1000,
             "rateLimits": [{"kind": "seven_day", "percentUsed": pct, "resetsAt": iso}] if limits else []}))

    refused = {"type": "result", "is_error": True, "result": "Credit balance is too low"}
    ok = {"type": "result", "is_error": False, "total_cost_usd": 0.1}

    def test_log_of_row_falls_back_to_the_one_tree_file(self):
        named = os.path.join(self.base, "gone", "log-w1.jsonl").replace("\\", "/")
        self.assertEqual(phi.log_of_row(self.home, {"name": "w1", "log": named}), named)
        tree = os.path.join(self.home, "phi", "tree", "local_x", "w1", "log-w1.jsonl")
        write(tree, "")
        self.assertEqual(os.path.normpath(phi.log_of_row(self.home, {"name": "w1", "log": named})),
                         os.path.normpath(tree))
        write(os.path.join(self.home, "phi", "tree", "local_y", "w1", "log-w1.jsonl"), "")
        self.assertEqual(phi.log_of_row(self.home, {"name": "w1", "log": named}), named)

    def test_last_rate_limit_is_the_last_rows_info(self):
        log = os.path.join(self.base, "l.jsonl")
        write(log, json.dumps(self.window(0.1)) + "\n" + json.dumps(self.window(0.5)) + "\n")
        self.assertEqual(phi.last_rate_limit(log)["unifiedWindows"]["seven_day"]["utilization"], 0.5)
        self.assertEqual(phi.last_rate_limit(os.path.join(self.base, "none.jsonl")), {})
        write(log, json.dumps(self.ok) + "\n")
        self.assertEqual(phi.last_rate_limit(log), {})

    def test_api_pool_low_on_a_credit_refusal_until_a_success_or_24_hours(self):
        self.start("w1", "p4-workers", [self.refused])
        self.assertTrue(phi.pool_state(self.home, self.now)["api"]["low"])
        self.start("w2", "p4-workers", [self.ok])
        self.assertFalse(phi.pool_state(self.home, self.now)["api"]["low"])
        os.remove(self.ledger())
        self.start("w3", "p4-workers", [self.refused], ago=25 * 3600)
        self.assertFalse(phi.pool_state(self.home, self.now)["api"]["low"])

    def test_api_pool_low_on_this_months_estimates_of_api_profile_workers_only(self):
        write(os.path.join(self.home, "phi", "phi.json"), json.dumps({"worker_api_budget_usd": 1}))
        self.start("w1", "p4-workers", [self.ok])
        self.start("w2", "", [self.ok])
        self.row({"event": "outcome", "name": "w2", "how": "done", "total_cost_usd": 5.0})
        self.row({"event": "outcome", "name": "w1", "how": "done", "total_cost_usd": 0.5})
        self.assertFalse(phi.pool_state(self.home, self.now)["api"]["low"])
        self.row({"event": "outcome", "name": "w1", "how": "done", "total_cost_usd": 0.45})
        self.assertTrue(phi.pool_state(self.home, self.now)["api"]["low"])
        os.remove(self.ledger())
        self.start("w1", "p4-workers", [self.ok], ago=40 * 86400)
        self.row({"event": "outcome", "name": "w1", "how": "done", "total_cost_usd": 0.95}, ago=40 * 86400)
        self.assertFalse(phi.pool_state(self.home, self.now)["api"]["low"])

    def test_max_pool_reads_the_freshest_usage_json_over_a_worker_log(self):
        self.start("w1", "", [self.window(0.95)])
        self.usage("s1", 93)
        got = phi.pool_state(self.home, self.now)["max"]
        self.assertTrue(got["low"])
        self.assertAlmostEqual(got["utilization"], 0.93)
        self.usage("s1", 50)
        got = phi.pool_state(self.home, self.now)["max"]
        self.assertFalse(got["low"], "the usage.json wins over the older log at 0.95")
        self.assertAlmostEqual(got["utilization"], 0.5)
        self.usage("s1", 50, limits=False)
        self.assertTrue(phi.pool_state(self.home, self.now)["max"]["low"], "an empty rateLimits list is skipped")

    def test_max_pool_from_a_profile_off_workers_rate_limit_event(self):
        self.start("w1", "", [self.window(0.95)])
        self.assertTrue(phi.pool_state(self.home, self.now)["max"]["low"])
        os.remove(self.ledger())
        self.start("w1", "", [self.window(0.95, resets=self.now - 10)])
        self.assertFalse(phi.pool_state(self.home, self.now)["max"]["low"])
        os.remove(self.ledger())
        self.start("w1", "", [self.window(0.5, status="allowed_warning")])
        self.assertTrue(phi.pool_state(self.home, self.now)["max"]["low"])

    def test_worker_settings_moves_a_pair_profile_to_off_when_only_the_api_pool_is_low(self):
        self.start("w1", "p4-workers", [self.refused])
        self.usage("s1", 10)
        got = phi.worker_settings(self.home)
        self.assertEqual((got["mode"], got["profile"]), ("print", ""))
        self.assertTrue(got["profile_from"].startswith("the pools"))
        write(os.path.join(self.home, "phi", "phi.json"), json.dumps({"worker_profile": "p4-workers"}))
        self.assertEqual(phi.worker_settings(self.home)["profile"], "p4-workers", "phi.json's profile wins")
        os.remove(os.path.join(self.home, "phi", "phi.json"))
        self.usage("s1", 95)
        got = phi.worker_settings(self.home)
        self.assertEqual(got["profile"], "p4-workers")
        self.assertIn("both pools are low", got["reason"])

    def test_a_session_workerprofile_wins_over_the_pools(self):
        self.start("w1", "p4-workers", [self.refused])
        write(os.path.join(self.home, "phi", "sessions", "s9", "session.json"),
              json.dumps({"id": "s9", "workerProfile": "p4-workers"}))
        got = phi.worker_settings(self.home, "s9")
        self.assertEqual((got["profile"], got["profile_from"], got["pools"]),
                         ("p4-workers", "the session's workerProfile", None))

    def test_worker_settings_interactive_warns_on_a_low_max_and_ignores_a_low_api(self):
        write(os.path.join(self.home, "phi", "phi.json"), json.dumps({"worker_mode": "interactive"}))
        self.usage("s1", 95)
        got = phi.worker_settings(self.home)
        self.assertEqual((got["mode"], got["profile"]), ("interactive", ""))
        self.assertIn("Max plan", got["reason"])
        os.remove(os.path.join(self.home, "phi", "sessions", "s1", "usage.json"))
        self.start("w1", "p4-workers", [self.refused])
        got = phi.worker_settings(self.home)
        self.assertEqual((got["profile"], got["reason"]), ("", ""))

    def test_a_profile_off_start_whose_log_is_missing_feeds_nothing(self):
        self.start("w1", "", None)
        got = phi.pool_state(self.home, self.now)
        self.assertFalse(got["max"]["low"] or got["api"]["low"])
        self.assertIsNone(got["max"]["utilization"])

    def test_with_no_ledger_the_settings_are_the_pairs_plus_pools(self):
        got = phi.worker_settings(self.home)
        self.assertEqual((got["mode"], got["profile"], got["profile_from"]), ("print", "p4-workers", "the pair of print"))
        self.assertIn("pools", got)

    def test_balance_ends_with_a_pools_line_and_counts_a_moved_log(self):
        named = os.path.join(self.base, "gone", "log-w1.jsonl").replace("\\", "/")
        self.row({"event": "start", "name": "w1", "mode": "print", "profile": "p4-workers", "log": named})
        self.row({"event": "outcome", "name": "w1", "how": "done"})
        write(os.path.join(self.home, "phi", "tree", "local_x", "w1", "log-w1.jsonl"),
              json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.4, "num_turns": 2}) + "\n")
        out = phi.worker_balance(self.home)
        self.assertIn("cost 0.4000 total", out)
        self.assertTrue(out.splitlines()[-1].startswith("pools: API credit "), out)

    def test_start_and_outcome_rows_keep_the_pools_and_the_rate_limit(self):
        phi.worker_start(self.home, phi.worker_settings(self.home), "w1", "s", "land", "l", "r")
        log = os.path.join(self.base, "l.jsonl")
        write(log, json.dumps(self.window(0.3)) + "\n")
        phi.worker_outcome(self.home, "w1", "done", {}, log)
        start, out = phi.read_rows(self.ledger())
        self.assertEqual(set(start["pools"]), {"api_low", "api_spent_month", "max_low", "max_utilization"})
        self.assertEqual(out["rate_limit"]["status"], "allowed")


class CommitCommand(unittest.TestCase):
    """`phi.py commit`, the one way a node commits in a shared checkout, run with no store and on real repositories."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="p4-phi-commit-", dir=FIXTURES or None)
        self.addCleanup(self._tmp.cleanup)
        self.repo = os.path.realpath(self._tmp.name)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        for name in ("keep.txt", "gone.txt", "old.txt", "a.txt", "b.txt", "g[1].txt", "sib.txt"):
            self.put(name, f"the first text of {name}\n")
        self.git("add", ".")
        self.git("commit", "-qm", "first\n\nCo-Authored-By: Pair <pair@example.com>")

    def put(self, name, text):
        with open(os.path.join(self.repo, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def git(self, *args):
        ran = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran.stdout

    def commit(self, message, *paths, cwd=None):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "commit",
                               "--checkout", self.repo, "-m", message, "--", *paths],
                              capture_output=True, text=True, timeout=60, cwd=cwd or tempfile.gettempdir())

    def held(self, rev="HEAD"):
        return sorted(self.git("show", "--name-only", "--no-renames", "--format=", rev).split())

    def test_it_runs_with_no_store_and_gives_the_commit_the_trailer_of_the_last_one(self):
        self.put("a.txt", "2\n")
        ran = self.commit("change a", "a.txt")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("a.txt", ran.stdout)
        self.assertEqual(self.held(), ["a.txt"])
        self.assertTrue(self.git("log", "-1", "--format=%B").rstrip()
                        .endswith("Co-Authored-By: Pair <pair@example.com>"))
        self.assertIn(self.git("rev-parse", "--short", "HEAD").strip(), ran.stdout.split("\n")[0])

    def test_it_refuses_a_path_outside_the_checkout_and_one_under_dot_claude(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        self.put(".claude/x.txt", "1\n")
        self.put("a.txt", "2\n")
        before = self.git("rev-parse", "HEAD")
        for bad in ("../outside.txt", ".claude/x.txt", os.path.join(os.path.dirname(self.repo), "z.txt"), "."):
            ran = self.commit("m", "a.txt", bad)
            self.assertEqual(ran.returncode, 2, bad)
            self.assertIn("nothing is committed", ran.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.commit("m").returncode, 2, "no path")

    def test_a_commit_told_that_another_process_moved_head_is_run_again(self):
        """Seen on macOS CI, 2026-11-24: of two commits at once the later was told "cannot lock ref 'HEAD': is at
        <new> but expected <old>" and gave up; git_again runs it again, as it does for index.lock."""
        from unittest import mock
        told = [subprocess.CompletedProcess([], 128, "", "fatal: cannot lock ref 'HEAD': is at 1 but expected 2\n"),
                subprocess.CompletedProcess([], 0, "ok", "")]
        with mock.patch.object(phi.subprocess, "run", side_effect=told) as run, mock.patch.object(phi.time, "sleep"):
            ran, locked = phi.git_again(["commit"], ".", tries=3, wait=0)
        self.assertEqual((ran.returncode, locked, run.call_count), (0, False, 2))
        with mock.patch.object(phi.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, "", "nothing to commit")) as run:
            self.assertEqual(phi.git_again(["commit"], ".", tries=3, wait=0)[0].returncode, 1)
        self.assertEqual(run.call_count, 1, "another failure is not repeated")

    def test_two_processes_started_at_once_on_two_paths_both_commit_each_holding_its_own(self):
        for k in range(4):
            self.put("a.txt", f"a{k}\n")
            self.put("b.txt", f"b{k}\n")
            procs = [subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "commit",
                                       "--checkout", self.repo, "-m", f"change {name} {k}", "--", name],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for name in ("a.txt", "b.txt")]
            outs = [p.communicate(timeout=120) for p in procs]
            self.assertEqual([p.returncode for p in procs], [0, 0], outs)
            held = {rev: self.held(rev) for rev in self.git("log", "-2", "--format=%H").split()}
            self.assertEqual(sorted(sum(held.values(), [])), ["a.txt", "b.txt"])
            self.assertTrue(all(len(v) == 1 for v in held.values()), held)

    def test_a_lock_held_past_the_tries_ends_in_the_failure_and_another_failure_ends_at_once(self):
        import phi as phimod
        self.put("a.txt", "2\n")
        lock = os.path.join(self.repo, ".git", "index.lock")
        open(lock, "w").close()
        status, lines = phimod.commit_paths(self.repo, "m", ["a.txt"], tries=100, wait=0)
        self.assertEqual(status, 1)
        self.assertIn("index.lock", lines[0])
        self.assertIn("100", lines[0])
        os.remove(lock)
        started = time.time()
        status, lines = phimod.commit_paths(self.repo, "m", ["no-such-file.txt"], tries=100, wait=60)
        self.assertNotEqual(status, 0)
        self.assertLess(time.time() - started, 30, "a failure that is no lock is not waited for")
        self.assertIn("no-such-file.txt", lines[0])

    def test_a_new_a_deleted_a_renamed_and_a_glob_path_each_beside_a_siblings_staged_file(self):
        self.put("sib.txt", "staged by a sibling\n")
        self.git("add", "sib.txt")
        self.put("fresh.txt", "new\n")
        os.remove(os.path.join(self.repo, "gone.txt"))
        os.rename(os.path.join(self.repo, "old.txt"), os.path.join(self.repo, "new.txt"))
        self.put("g[1].txt", "2\n")
        self.put("g1.txt", "an untracked neighbour\n")
        ran = self.commit("all of them", "fresh.txt", "gone.txt", "old.txt", "new.txt", "g[1].txt")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(self.held(), ["fresh.txt", "g[1].txt", "gone.txt", "new.txt", "old.txt"])
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["sib.txt"], "the sibling's stays staged")
        self.assertEqual(self.git("ls-files", "--others", "--exclude-standard").split(), ["g1.txt"],
                         "a glob that matched g1.txt would have taken it")


class SharedCheckout(unittest.TestCase):
    """Every session p4-phi starts works in its starter's checkout, on the paths of its `Files:` line: a start that
    passes `use_worktree: true` is asked about, and a child that shares its starter's checkout is refused the git
    commands that stage, commit or set aside what the others changed there, with `phi.py commit` named in their
    place."""

    COMMIT = 'phi.py" commit -m "<message>" -- <path> ...'

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory(prefix="p4-phi-shared-", dir=FIXTURES or None)
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(os.path.realpath(self._tmp.name))
        self.git("init", "-q", ".")
        write(os.path.join(t.proj, "a.py"), "a = 1\n")
        self.git("add", "a.py")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush child")
        t.say(TOP, "Build the exporter")
        t.say(KID, "Task:\nPort the flush.\nFiles: a.py")

    def git(self, *args, cwd=None):
        ran = subprocess.run(["git", *args], cwd=cwd or self.t.proj, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 0, ran.stderr)

    def guard(self, host, cmd, cwd=None):
        r = self.t.hook("branch-guard", host, {"tool_name": "Bash", "tool_input": {"command": cmd},
                                               **({"cwd": cwd} if cwd else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def start(self, prompt, **more):
        path = os.path.join(self._tmp.name, "transcript.jsonl")
        write(path, "x")
        r = self.t.hook("start-advice", TOP, {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session",
            "transcript_path": path, "tool_input": {"initiation": "user_asked", "context": "fresh",
                                                    "title": "the flush", "prompt": prompt, **more}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_a_start_that_passes_use_worktree_true_is_asked_about_and_false_or_omitted_is_not(self):
        brief = "Port the exporter's flush to the new writer and run its suite.\nFiles: src/flush.py"
        out = self.start(brief, use_worktree=True)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        self.assertIn("advises `use_worktree: false`", out["permissionDecisionReason"])
        self.assertIn("starts works in its starter's checkout", out["permissionDecisionReason"])
        self.assertIsNone(self.start(brief, use_worktree=False), "false is what p4-phi's own call passes")
        self.assertIsNone(self.start(brief), "and so is leaving it out")

    def test_a_child_in_the_main_checkout_is_refused_what_takes_the_others_changes(self):
        for cmd in ('git commit -m x', 'git add -A', 'git stash', 'x && git commit -qm y', 'git add . && git status',
                    'git stash pop', 'git rm a.py', 'git mv a.py b.py', 'git -C . commit -m x'):
            out = self.guard(KID, cmd)
            self.assertIsNotNone(out, cmd)
            self.assertEqual(out["permissionDecision"], "deny", cmd)
            self.assertIn(self.COMMIT, out["permissionDecisionReason"], cmd)
            self.assertIn(cmd, out["permissionDecisionReason"], "it names the command it refuses")

    def test_a_child_in_the_main_checkout_is_not_refused_phi_commit_or_a_read(self):
        for cmd in ('python phi.py commit -m "git commit" -- a.py', 'git status', 'git diff', 'git log',
                    'git log --oneline -5', 'git show HEAD', 'grep -n "git commit" docs.md', 'echo "git add -A"'):
            self.assertIsNone(self.guard(KID, cmd), cmd)
        self.assertIsNone(self.guard(TOP, "git commit -m x"), "an orchestrator commits its own")
        for cmd in ("git stash list", "git stash show -p", "git add -n .", "git add --dry-run ."):
            self.assertIsNone(self.guard(KID, cmd), f"it changes nothing: {cmd}")

    def test_a_child_is_not_refused_git_commit_in_a_repository_no_other_session_works_in(self):
        mine = tempfile.mkdtemp(prefix="p4-own-repo-")
        self.addCleanup(shutil.rmtree, mine, ignore_errors=True)
        subprocess.run(["git", "init", "-q", mine], check=True, capture_output=True)
        for cmd in ("git add . && git commit -m base", "git stash"):
            self.assertIsNone(self.guard(KID, cmd, cwd=mine), f"a fixture of its own: {cmd}")
        at = mine.replace("\\", "/")
        self.assertIsNone(self.guard(KID, f"cd {at} && git commit -m base"), "named by cd from the shared checkout")

    def test_a_child_whose_folder_is_a_linked_worktree_of_its_own_is_asked_nothing_for_git_commit(self):
        own = os.path.join(self.t.proj, ".claude", "worktrees", "the-flush").replace("\\", "/")
        self.git("worktree", "add", "-q", "-b", "claude/the-flush", own)
        kid = "local_kid00003"
        CLI.setdefault(kid, "dddd4444-0000-4000-8000-000000000000")
        self.t.record(kid, TOP, title="the flush worker", cwd=own)
        self.assertEqual(self.t.say(kid, "Task:\nLook at the flush.").returncode, 0)
        for cmd in ("git commit -m x", "git add -A", "git stash"):
            self.assertIsNone(self.guard(kid, cmd, cwd=own), f"its own worktree: {cmd}")
        self.assertIsNotNone(self.guard(kid, "git push origin HEAD", cwd=own), "landing stays the orchestrator's")
        out = self.guard(kid, f"cd {self.t.proj} && git commit -m x", cwd=own)
        self.assertEqual(out["permissionDecision"], "deny", "a command aimed at the shared checkout is refused")


class Partition(unittest.TestCase):
    """Two running sessions never hold the same path: a writer's start is refused where its brief names no file or a
    path a running session that is not above the starter holds, an edit outside a started session's paths is refused
    before it runs, and `phi.py commit` takes no path outside them."""

    def setUp(self):
        SharedCheckout.setUp(self)
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.t.record(KID2, TOP, title="the docs child")
        self.t.say(KID2, "Task:\nWrite the docs.\nFiles: docs.md")
        self.t.record(GRAND, "", title="the other top")
        self.t.say(GRAND, "Build another thing")

    git = SharedCheckout.git

    def deny(self, out):
        return out is not None and out["permissionDecision"] == "deny"

    def start(self, host, prompt):
        path = os.path.join(self._tmp.name, "transcript.jsonl")
        write(path, "x")
        r = self.t.hook("start-advice", host, {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session",
            "transcript_path": path, "tool_input": {"initiation": "user_asked", "context": "fresh", "title": "the part",
                                                    "use_worktree": False, "prompt": prompt}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def edit(self, host, path, tool="Edit", cwd=None):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        r = self.t.hook("path-guard", host, {"tool_name": tool, "tool_input": {key: path},
                                             **({"cwd": cwd} if cwd else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def archive(self, host):
        path = os.path.join(self.t.dir(host), "session.json")
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        s["archived"] = True
        write(path, json.dumps(s))
        relay.forget(self.t.p4)

    def mine(self, *names):
        return [os.path.join(self.t.proj, n) for n in names]

    WRITE = "Port the exporter's flush to the new writer and run its suite. Report when done.\nFiles: "

    def test_a_writers_start_with_no_files_line_is_denied(self):
        out = self.start(TOP, "Port the exporter's flush to the new writer and run its suite. Report when done.")
        self.assertTrue(self.deny(out), out)
        self.assertIn("Files:", out["permissionDecisionReason"])

    def test_a_start_whose_path_a_running_child_of_the_starter_holds_is_denied_with_its_id(self):
        out = self.start(TOP, self.WRITE + "a.py")
        self.assertTrue(self.deny(out), out)
        self.assertIn(KID, out["permissionDecisionReason"])
        self.assertFalse(self.deny(self.start(TOP, self.WRITE + "c.py")), "a path nobody holds")

    def test_a_start_whose_path_only_the_starter_holds_is_not_denied(self):
        relay.set_shard(self.t.p4, TOP, ["b.py"], self.t.proj)
        self.assertFalse(self.deny(self.start(TOP, self.WRITE + "b.py")))

    def test_a_readers_start_and_a_new_orchestrators_are_not_read(self):
        reader = "Check what the exporter's flush does and report it.\nFiles: none"
        self.assertFalse(self.deny(self.start(TOP, reader)))
        self.assertFalse(self.deny(self.start(GRAND, starts.ORCHESTRATOR_BRIEF + "\nFiles: a.py")))

    def test_the_same_start_after_the_sibling_is_archived_is_not_denied(self):
        self.assertTrue(self.deny(self.start(TOP, self.WRITE + "a.py")))
        self.archive(KID)
        self.assertFalse(self.deny(self.start(TOP, self.WRITE + "a.py")))

    def test_an_edit_outside_a_started_sessions_paths_is_denied_and_one_inside_them_is_not(self):
        out = self.edit(KID, self.mine("b.py")[0])
        self.assertTrue(self.deny(out), out)
        self.assertIn("outside", out["permissionDecisionReason"])
        self.assertIsNone(self.edit(KID, self.mine("a.py")[0]))

    def test_a_path_under_dot_claude_and_a_file_in_no_repository_are_let_through(self):
        self.assertIsNone(self.edit(KID, os.path.join(self.t.proj, ".claude", "p4", "note.md")))
        with tempfile.TemporaryDirectory() as loose:
            self.assertIsNone(self.edit(KID, os.path.join(loose, "x.py")))

    def test_notebook_edit_is_read_by_its_notebook_path(self):
        self.assertTrue(self.deny(self.edit(KID, self.mine("b.ipynb")[0], tool="NotebookEdit")))
        self.assertIsNone(self.edit(KID, self.mine("a.py")[0], tool="NotebookEdit"))

    def test_a_parents_write_is_denied_while_its_child_holds_paths_there_and_let_through_once_it_is_gone(self):
        out = self.edit(TOP, self.mine("c.py")[0], tool="Write")
        self.assertTrue(self.deny(out), out)
        self.assertIn(KID, out["permissionDecisionReason"])
        self.archive(KID)
        self.archive(KID2)
        self.assertIsNone(self.edit(TOP, self.mine("c.py")[0], tool="Write"))

    def test_a_top_sessions_edit_of_a_path_another_tops_running_child_holds_is_denied(self):
        out = self.edit(GRAND, self.mine("a.py")[0])
        self.assertTrue(self.deny(out), out)
        self.assertIn(KID, out["permissionDecisionReason"])
        self.assertIsNone(self.edit(GRAND, self.mine("c.py")[0]), "a path nobody holds")
        self.archive(KID)
        self.assertIsNone(self.edit(GRAND, self.mine("a.py")[0]), "once the child is gone")

    def commit(self, host, *paths):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "commit",
                               "--checkout", self.t.proj, "-m", "change", "--", *paths], capture_output=True,
                              text=True, timeout=60, cwd=self.t.proj, env=self.t.env(host))

    def test_commit_by_a_started_session_takes_no_path_outside_its_own(self):
        write(os.path.join(self.t.proj, "a.py"), "a = 2\n")
        write(os.path.join(self.t.proj, "b.py"), "b = 1\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.t.proj, capture_output=True, text=True).stdout
        ran = self.commit(KID, "a.py", "b.py")
        self.assertEqual(ran.returncode, 2, ran.stdout)
        self.assertIn("b.py", ran.stderr)
        self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.t.proj, capture_output=True,
                                        text=True).stdout, head, "nothing is committed")
        ran = self.commit(KID, "a.py")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=self.t.proj,
                                        capture_output=True, text=True).stdout.split(), ["a.py"])

    def test_commit_with_no_session_in_the_environment_takes_any_path_as_before(self):
        write(os.path.join(self.t.proj, "b.py"), "b = 1\n")
        ran = self.commit("", "b.py")
        self.assertEqual(ran.returncode, 0, ran.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
