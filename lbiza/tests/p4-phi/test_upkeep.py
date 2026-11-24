"""Tests for upkeep.py: the upkeep of a session tree, which `phi.upkeep` turns on for a project.

Each act is held to its line with the setting on and to its absence with it off:
archive: a started session that is finished and landed is named by its whole title with the exact archive call, and
one whose work is not landed gets the landing line first.
follow-through: what a finished worker's report lists as found and not fixed is kept as open items, each sent back
to that worker or on to a successor, listed at every later turn, and closed only by a landed commit, a note or ezexe's
word.
waits: a step that waits on another session is handed as due once that session's work is on the default branch.
leftovers: after an archive, the clean worktree and the merged branch are named for removal by git's own commands
with no force, which git then accepts, and a dirty one is named once and left.
the wake: with every started session idle and an act due, a look answers the prompt of one turn, once for an act and
inside the budget of the turns the hooks module starts.
Every git here runs in a repository the test makes, with a bare remote beside it.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402
import p4conf  # noqa: E402
import phi  # noqa: E402
import upkeep  # noqa: E402
import shared  # noqa: E402
import test_phi  # noqa: E402
from test_phi import BRIEF, CLI, KID, KID2, TASK, TOP, Tree, context, handed, jload, write  # noqa: E402

ARCHIVE = "mcp__ccd_session_mgmt__archive_session"
KID_TITLE = "Fix the last row of the narwhal ports table"
KID2_TITLE = "Write the narwhal exporter's retry for a failed ports table write"
REPORT = ("The last row is written now, and the fix is pushed.\n\n"
          "## Found and not fixed\n\n"
          "- The exporter still drops a row when the ports table is empty.\n"
          "- `flush_rows` has no test for a write that fails halfway.\n\n"
          "## What ran\n\n- The exporter's tests, which pass.\n")
FROM_KID = ("<cross-session-message from=\"kid\">phi (p4-phi): this session ended a turn. Its report follows, and "
            "needs no reply.\n\nThe last row is written now.</cross-session-message>")


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       capture_output=True, text=True, timeout=60)
    return r


def flat(text):
    return " ".join(str(text or "").split())


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("P4_PHI_TEST_TMP") or None)
        self.tmp = os.path.realpath(self._tmp.name)
        self.t = Tree(self.tmp)
        self.remote = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "code")
        self.wt = os.path.join(self.tmp, "trees", "kid")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", self.remote, self.repo], check=True, capture_output=True)
        write(os.path.join(self.repo, "exporter.py"), "rows = []\n")
        git(self.repo, "checkout", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        self.assertEqual(git(self.repo, "commit", "-q", "-m", "the exporter").returncode, 0)
        self.assertEqual(git(self.repo, "push", "-q", "-u", "origin", "main").returncode, 0)
        git(self.repo, "remote", "set-head", "origin", "main")
        r = git(self.repo, "worktree", "add", "-q", self.wt, "-b", "worktree-kid", "origin/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.t.record(TOP, title="Orchestrate the narwhal exporter")
        self.t.record(KID, TOP, KID_TITLE, cwd=self.wt)
        self.t.say(TOP, TASK)
        self.t.stop(TOP, TASK, report="A worker is started for the last row.")
        self.t.say(KID, handed(BRIEF))

    def tearDown(self):
        self._tmp.cleanup()

    def turn_on(self):
        r = self.t.cli(TOP, "upkeep", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def commit(self, text="rows = [1]\n", message="the last row is written", push=True):
        write(os.path.join(self.wt, "exporter.py"), text)
        self.assertEqual(git(self.wt, "commit", "-q", "-am", message).returncode, 0)
        if push:
            r = git(self.wt, "push", "-q", "origin", "HEAD:main")
            self.assertEqual(r.returncode, 0, r.stderr)

    def finish(self, report=REPORT, uuid="u1", closed=True):
        """The worker shows its turn done and ends it. With `closed` and upkeep on, the closing step before its
        archive is kept as answered already, so a test of another act reads the archive line at the next message."""
        self.assertEqual(self.t.cli(KID, "done", "ran the exporter's tests and they passed").returncode, 0)
        self.t.stop(KID, BRIEF, report=report, uuid=uuid)
        if closed and p4conf.upkeep_on(self.t.p4):
            d = upkeep.load(self.t.p4, TOP)
            d["closing"][KID] = {"turn": "the turn before its closing message", "asks": 1, "looks": 0,
                                 "time": "2026-11-23 10:00"}
            upkeep.save(self.t.p4, TOP, d)

    def archive_in_app(self, host=KID):
        """The app's record of a session as the archive tool leaves it."""
        p = os.path.join(self.t.app, host + ".json")
        d = jload(p)
        d["isArchived"] = True
        write(p, json.dumps(d))
        phi.RECORDS.clear()

    def said(self, prompt=FROM_KID, host=TOP):
        r = self.t.say(host, prompt)
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def lines(self, text, kind):
        return [x for x in text.splitlines() if x.startswith(f"- {kind}")]

    def look(self, *args):
        env = self.t.env(TOP, **{"P4_PHI_WATCH": "1", "P4_PHI_WATCH_NET": "0"})
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "look", *args],
                       capture_output=True, text=True, env=env, cwd=self.t.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class Setting(Base):
    def test_it_is_off_by_default_and_a_command_turns_it_on_and_off_in_the_stores_p4_json(self):
        self.assertFalse(p4conf.upkeep_on(self.t.p4))
        out = self.turn_on()
        self.assertIn("phi.upkeep is on", out)
        self.assertIs(jload(os.path.join(self.t.p4, "p4.json"))["phi"]["upkeep"], True)
        asked = jload(os.path.join(self.t.p4, p4conf.ASKS))
        self.assertIn("allow", asked["permissions"], "set_on writes what p4-phi asks for")
        self.assertNotIn("adopt", asked.get("p4", {}), "the set is not in force, so nothing is adopted")
        local_file = os.path.join(self.t.proj, ".claude", "settings.local.json")
        local = jload(local_file) if os.path.exists(local_file) else {}
        self.assertNotIn(ARCHIVE, local.get("permissions", {}).get("ask", []), "the keeper wrote no ask rule")
        self.assertIn(f"no ask rule on `{ARCHIVE}`", out)
        r = self.t.cli(TOP, "upkeep", "off")
        self.assertIn("phi.upkeep is off", r.stdout)
        self.assertIs(jload(os.path.join(self.t.p4, "p4.json"))["phi"]["upkeep"], False)
        local = jload(local_file) if os.path.exists(local_file) else {}
        self.assertNotIn(ARCHIVE, local.get("permissions", {}).get("ask", []), "off: the keeper writes none either")
        self.assertIn(f"no ask rule on `{ARCHIVE}`", r.stdout)

    def test_with_it_off_nothing_is_handed_and_nothing_is_kept(self):
        self.commit()
        self.finish()
        got = self.said()
        self.assertNotIn("upkeep", got)
        self.assertNotIn(ARCHIVE, got)
        self.assertNotIn("worktree remove", got)
        self.assertFalse(os.path.exists(upkeep.path(self.t.p4, TOP)), "no record of upkeep is made")
        self.assertNotIn("left", self.t.turns(KID)[-1], "the worker's turn row is as it was")
        self.assertNotIn("upkeep", self.look("--net"))
        r = self.t.cli(TOP, "upkeep")
        self.assertIn("phi.upkeep is off", r.stdout)


class Archive(Base):
    def test_a_finished_landed_session_is_named_by_its_whole_title_with_the_exact_call(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now, and the fix is pushed.")
        got = self.said()
        line = self.lines(got, "archive:")
        self.assertEqual(len(line), 1, got)
        self.assertIn(f"\"{KID_TITLE}\" `{KID}`", line[0])
        self.assertIn(f"`{ARCHIVE}` with `session_id` `{KID}`", line[0])
        self.assertIn("ezexe's standing word", got)
        self.assertNotIn("Archiving one in the app is ezexe's", got)
        self.assertNotIn("land first", got)

    def test_one_whose_work_is_not_landed_gets_the_landing_line_first(self):
        self.turn_on()
        self.commit(push=False)
        self.finish(report="The last row is written now.")
        got = self.said()
        self.assertEqual(self.lines(got, "archive:"), [], got)
        land = self.lines(got, "land first:")
        self.assertEqual(len(land), 1, got)
        self.assertIn(f"\"{KID_TITLE}\" `{KID}`", land[0])
        self.assertIn("1 commit of `worktree-kid`", land[0])
        self.assertIn("not on origin/main", land[0])
        self.assertIn("the full suite once on the commit being pushed, then the push", land[0],
                      "no workflow of the repository runs on a push, so a local run is the only run")
        import relay
        flow = os.path.join(self.wt, ".github", "workflows", "tests.yml")
        os.makedirs(os.path.dirname(flow))
        with open(flow, "w", encoding="utf-8") as fh:
            fh.write("name: tests\non:\n  push:\n    branches: [main]\n")
        self.assertEqual(relay.push_workflows([self.wt]), [("tests", "tests.yml")])
        os.remove(flow)
        git(self.wt, "push", "-q", "origin", "HEAD:main")          # landed: the next turn hands the call
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1)

    def test_an_uncommitted_change_keeps_it_from_the_archive(self):
        self.turn_on()
        self.commit()
        write(os.path.join(self.wt, "notes.txt"), "half a thought\n")
        self.finish(report="The last row is written now.")
        got = self.said()
        self.assertEqual(self.lines(got, "archive:"), [])
        self.assertIn("holds 1 uncommitted change", flat(got))

    def test_a_session_inside_a_turn_or_with_an_open_step_or_an_unread_report_is_not_named(self):
        self.turn_on()
        self.commit()
        self.assertEqual(self.lines(self.said(), "archive:"), [], "inside its first turn, with no turn ended")
        self.finish(report="The last row is written now.")
        self.t.say(KID, "One more thing: check the empty table.")       # a turn of it runs again
        self.assertEqual(self.lines(self.said(), "archive:"), [])

    def test_a_session_with_no_commit_that_another_still_drives_is_not_named(self):
        """A session that made no commit has nothing to land, so "finished and landed" holds for it with no work
        behind the words. On 2026-11-19 the archive of a probe was handed to its starter three times while another
        session still drove it through a plugin's prompts. Its archive is handed only while nobody but its starter
        drives it: not after a turn the prompt of a plugin other than p4-phi began, nor after one another live
        session's message began. p4-phi's own wake drives nobody, the starter's own message makes it the starter's
        again, and a session with a commit of its own is named whoever drives it."""
        self.turn_on()

        def turn(prompt, origin, uuid, host=KID):
            write(os.path.join(self.t.dir(host), "origin.json"), json.dumps({"promptId": uuid, **origin}))
            r = self.t.hook("user-prompt-submit", host, {"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                                                         "prompt_id": uuid})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.t.cli(host, "done", "the step ran").returncode, 0)
            self.t.stop(host, prompt, report="The step ran.", uuid=uuid)

        self.finish(report="Ready, and nothing is committed.")
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1, "no commit and nobody else: named as before")
        turn("The z-card-probe plugin sent a message:\nWrite your plan.", {"kind": "plugin", "name": "z-card-probe"},
             "p1")
        self.assertEqual(self.t.turns(KID)[-1].get("from"), "z-card-probe", "the sender is kept on the turn's row")
        self.assertEqual(upkeep.driver(self.t.p4, KID, self.t.session(KID)), "the plugin z-card-probe")
        self.assertEqual(self.lines(self.said(), "archive:"), [], "another plugin's prompt drives it")
        turn("The p4-phi plugin sent a message:\nphi (p4-phi): a step is due.", {"kind": "plugin", "name": "p4-phi"},
             "p2")
        self.assertEqual(self.lines(self.said(), "archive:"), [], "p4-phi's own wake changes nothing of who drives it")
        self.t.record(KID2, TOP, KID2_TITLE)
        self.t.say(KID2, handed(BRIEF))
        peer = f"<cross-session-message from=\"{KID2}\" from-name=\"a sibling\">One more step.</cross-session-message>"
        turn(peer, {"kind": "peer"}, "p3")
        self.assertEqual(self.t.turns(KID)[-1].get("from"), KID2)
        self.assertIn(KID2, upkeep.driver(self.t.p4, KID, self.t.session(KID)))
        self.assertEqual(self.lines(self.said(), "archive:"), [], "a live sibling drives it")
        mine = f"<cross-session-message from=\"{TOP}\" from-name=\"top\">Thank you, that is all.</cross-session-message>"
        turn(mine, {"kind": "peer"}, "p4")
        self.assertEqual(upkeep.driver(self.t.p4, KID, self.t.session(KID)), "")
        named = self.lines(self.said(), "archive:")
        self.assertEqual(len(named), 1, "its starter's own message makes it the starter's again")
        self.assertIn(f"`{KID}`", named[0])

    def test_a_session_with_a_commit_of_its_own_is_named_whoever_drives_it(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        write(os.path.join(self.t.dir(KID), "origin.json"), json.dumps({"promptId": "p1", "kind": "plugin",
                                                                       "name": "z-card-probe"}))
        said = "The z-card-probe plugin sent a message:\nSay what you pushed."
        self.t.hook("user-prompt-submit", KID, {"hook_event_name": "UserPromptSubmit", "prompt": said,
                                                "prompt_id": "p1"})
        self.assertEqual(self.t.cli(KID, "done", "ran the push again and it passed").returncode, 0)
        self.t.stop(KID, said, report="The fix is pushed.", uuid="p1")
        self.assertTrue(upkeep.made_commits(upkeep.trees_of(self.t.p4, KID, self.t.session(KID))))
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1, "its work is on the default branch: named")

    def test_the_call_is_handed_three_times_and_then_left(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        seen = [len(self.lines(self.said(), "archive:")) for _ in range(4)]
        self.assertEqual(seen, [1, 1, 1, 0])
        self.assertIn(f"archive:{KID}", self.t.cli(TOP, "upkeep").stdout)


class Closing(Base):
    """The ceremony before an archive: the plan moved, one closing message answered, the unfinished row settled.
    Seen on 2026-11-23: a planner left a nine-minute background wait running after its report, and the app
    answered its archive call "it still has live work"."""

    def answer(self, uuid, tasks=(), words="Closing before this session's archive. Stop what you started."):
        """A turn of the worker's that a message of its starter's began, as the app delivers one, which ends with
        `tasks` still running."""
        said = (f"Another Claude session sent a message:\n<cross-session-message from=\"{TOP}\" from-name=\"top\">"
                f"{words}</cross-session-message>")
        write(os.path.join(self.t.dir(KID), "origin.json"), json.dumps({"promptId": uuid, "kind": "peer"}))
        r = self.t.hook("user-prompt-submit", KID, {"hook_event_name": "UserPromptSubmit", "prompt": said,
                                                    "prompt_id": uuid})
        self.assertEqual(r.returncode, 0, r.stderr)
        path = test_phi.transcript(os.path.join(self.tmp, KID + uuid + ".jsonl"), said, (), "Nothing runs. Ready.",
                                   uuid)
        r = self.t.hook("stop", KID, {"hook_event_name": "Stop", "transcript_path": path,
                                      "last_assistant_message": "Nothing runs. Ready.",
                                      "background_tasks": [{"id": t, "type": "shell", "status": "running",
                                                            "description": "sleep 540", "command": "sleep 540"}
                                                           for t in tasks]})
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.t.turns(KID)[-1]
        self.assertEqual((row.get("by"), row.get("from")), ("session", TOP), "the row says whose message began it")

    def record(self, **fields):
        """Fields put on the worker's own record, as its hooks keep them."""
        p = os.path.join(self.t.dir(KID), "session.json")
        write(p, json.dumps({**jload(p), **fields}))

    def test_the_closing_message_is_handed_first_and_the_archive_after_the_sessions_next_turn(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        got = self.said()
        close = self.lines(got, "close:")
        self.assertEqual((len(close), self.lines(got, "archive:")), (1, []), got)
        self.assertIn(f"`SendMessage` to `{KID}`", close[0])
        self.assertEqual(upkeep.load(self.t.p4, TOP)["closing"][KID]["asks"], 1)
        self.answer("u2")
        got = self.said()
        self.assertEqual((len(self.lines(got, "archive:")), self.lines(got, "close:")), (1, []), got)

    def test_a_task_that_still_runs_is_named_and_asked_for_once_more_and_then_left_to_ezexe(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        self.assertEqual(len(self.lines(self.said(), "close:")), 1)
        self.answer("u2", tasks=("bg11111111",))
        again = self.lines(self.said(), "close:")
        self.assertEqual(len(again), 1, "answered, and a task still ran")
        self.assertIn("bg11111111", again[0])
        self.assertEqual(upkeep.load(self.t.p4, TOP)["closing"][KID]["asks"], 2)
        self.answer("u3", tasks=("bg11111111",))
        got = self.said()
        held = self.lines(got, "held:")
        self.assertEqual((len(held), self.lines(got, "close:"), self.lines(got, "archive:")), (1, [], []), got)
        self.assertIn("bg11111111", held[0])
        got = self.said()
        self.assertEqual((self.lines(got, "held:"), self.lines(got, "archive:")), ([], []), "told once, no archive")

    def test_a_session_that_does_not_answer_is_archived_where_nothing_of_it_ran(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        seen = []
        for _ in range(4):
            got = self.said()
            seen.append((len(self.lines(got, "close:")), len(self.lines(got, "archive:"))))
        self.assertEqual(seen, [(1, 0), (0, 0), (0, 0), (0, 1)], "one ask, two quiet messages, then the archive")

    def test_a_closing_message_unanswered_for_five_minutes_counts_as_not_answered(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        self.assertEqual(len(self.lines(self.said(), "close:")), 1)
        d = upkeep.load(self.t.p4, TOP)
        d["closing"][KID]["at"] -= upkeep.CLOSE_S + 1
        upkeep.save(self.t.p4, TOP, d)
        self.assertEqual(upkeep.close_state(self.t.p4, d, KID), "silent")
        self.t.stop(TOP, TASK, report="The closing message is sent.", uuid="t2")
        got = self.look("--net")
        self.assertTrue(str(got.get("upkeep") or "").startswith("phi (p4-phi): upkeep is due"), "a quiet starter is woken")
        self.assertEqual(len(self.lines(self.said(got["upkeep"]), "archive:")), 1, "nothing of it ran: the archive")

    def test_a_turn_given_other_work_after_the_closing_message_is_read_by_its_own_mark(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        self.said()
        self.answer("u2")
        self.assertTrue(upkeep.finished(self.t.p4, KID, self.t.session(KID)))
        self.answer("u2b", words="Thank you, that is all.")
        self.assertTrue(upkeep.finished(self.t.p4, KID, self.t.session(KID)), "its starter's word after is no work")
        self.t.say(KID, "One more thing: check the empty table.")
        self.t.stop(KID, "One more thing: check the empty table.", report="Looking at it.", uuid="u3")
        self.assertFalse(upkeep.finished(self.t.p4, KID, self.t.session(KID)), "new work, and no done mark")
        self.assertEqual(self.lines(self.said(), "archive:"), [])

    def test_a_second_closing_message_keeps_the_turn_its_done_mark_is_read_from(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.", closed=False)
        self.said()
        first = upkeep.load(self.t.p4, TOP)["closing"][KID]["since"]
        self.answer("u2", tasks=("bg11111111",))
        self.said()
        kept = upkeep.load(self.t.p4, TOP)["closing"][KID]
        self.assertEqual((kept["since"], kept["asks"]), (first, 2))
        self.assertTrue(upkeep.finished(self.t.p4, KID, self.t.session(KID)), "the answer undoes no done mark")

    def test_the_closing_message_is_an_act_a_turn_is_started_for(self):
        self.turn_on()
        self.commit(push=False)
        self.finish(report="The last row is written now.", closed=False)
        self.assertEqual(len(self.lines(self.said(), "land first:")), 1)
        self.t.stop(TOP, TASK, report="Waiting on the landing.", uuid="t2")
        self.assertEqual(git(self.wt, "push", "-q", "origin", "HEAD:main").returncode, 0)
        got = self.look("--net")
        self.assertTrue(str(got.get("upkeep") or "").startswith("phi (p4-phi): upkeep is due"), got)
        self.assertEqual(len(self.lines(self.said(got["upkeep"]), "close:")), 1)

    def test_a_plan_still_among_the_plans_being_worked_is_closed_before_the_closing_message(self):
        self.turn_on()
        self.commit()
        plan = os.path.join(self.t.p4, "temportal", "plan-planner", "the-last-row.md")
        write(plan, "# The last row\n")
        self.finish(report="The last row is written now.", closed=False)
        self.record(planFile=plan.replace("\\", "/"))
        got = self.said()
        self.assertEqual((len(self.lines(got, "plan:")), self.lines(got, "close:"), self.lines(got, "archive:")),
                         (1, [], []), got)
        os.makedirs(os.path.join(os.path.dirname(plan), "complete"))
        os.replace(plan, os.path.join(os.path.dirname(plan), "complete", "the-last-row.md"))
        got = self.said()
        self.assertEqual((self.lines(got, "plan:"), len(self.lines(got, "close:"))), ([], 1), "moved: the next step")

    def test_an_unfinished_row_is_settled_before_the_archive_call(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        self.record(unfinishedAtArchive={"time": "2026-11-23 10:00", "items": ["plan step \"Run it\" is open"]})
        got = self.said()
        self.assertEqual((len(self.lines(got, "settle:")), self.lines(got, "archive:")), (1, []), got)
        self.record(unfinishedAtArchive={"time": "2026-11-23 10:00", "items": ["plan step \"Run it\" is open"],
                                         "settled": "the next plan took it up"})
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1)


class Refused(Base):
    """An archive the app refuses is taken as a session still busy: its words are kept as they stand, the call is
    handed once more after the session has been idle, and after a second refusal ezexe is told once. Seen on
    2026-11-23: each refusal fell while the session's own records showed a turn open or a background task
    running, and the same call went through minutes later."""

    BUSY = ("Session local_kid (\"the worker\") was not archived: the app is keeping it for the user (pinned or "
            "in use). Wait or ask the user; they can also archive it from the sidebar.")
    DENIED = ("The server-side auto mode classifier gave no verdict for mcp__ccd_session_mgmt__archive_session: a "
              "hook changed this call's input after auto mode reviewed it.")

    def ends(self, uuid, *calls):
        """A turn of the starter's that made these archive calls of the worker, each as (answer, failed)."""
        made = [(ARCHIVE, {"session_id": KID}, said) + (("failed",) if failed else ()) for said, failed in calls]
        self.t.stop(TOP, TASK, calls=made, report="Called it.", uuid=uuid)
        return upkeep.load(self.t.p4, TOP)["refused"]

    def idle(self):
        """The refusal as one of RETRY_S ago."""
        d = upkeep.load(self.t.p4, TOP)
        d["refused"][KID]["at"] -= upkeep.RETRY_S + 1
        upkeep.save(self.t.p4, TOP, d)

    def ready(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1)

    def test_a_refused_call_is_kept_with_the_apps_words_and_handed_once_more_after_the_session_was_idle(self):
        self.ready()
        kept = self.ends("t5", (self.BUSY, True))
        self.assertEqual((kept[KID]["n"], kept[KID]["said"]), (1, self.BUSY))
        self.assertEqual(self.lines(self.said(), "archive:"), [], "refused a moment ago: no call is handed")
        self.t.stop(TOP, TASK, report="The app kept it, so it waits.", uuid="t5b")
        self.idle()
        got = self.look("--net")
        self.assertTrue(str(got.get("upkeep") or "").startswith("phi (p4-phi): upkeep is due"), "the retry wakes it")
        again = self.lines(self.said(got["upkeep"]), "archive:")
        self.assertEqual(len(again), 1, "the one retry")
        self.assertIn(self.BUSY, again[0], "the app's words are passed on as they stand")

    def test_a_second_refusal_is_told_to_ezexe_once_and_the_call_is_handed_no_more(self):
        self.ready()
        self.ends("t5", (self.BUSY, True))
        self.idle()
        self.assertEqual(len(self.lines(self.said(), "archive:")), 1)
        self.assertEqual(self.ends("t6", (self.BUSY, True))[KID]["n"], 2)
        self.idle()
        got = self.said()
        told = self.lines(got, "refused:")
        self.assertEqual((len(told), self.lines(got, "archive:")), (1, []), got)
        self.assertIn(self.BUSY, told[0])
        got = self.said()
        self.assertEqual((self.lines(got, "refused:"), self.lines(got, "archive:")), ([], []), "once, and no more")

    def test_a_call_denied_for_its_input_and_made_again_is_no_refusal(self):
        self.ready()
        self.assertEqual(self.ends("t4", (self.DENIED, True)), {}, "it never reached the app: no retry is spent")
        self.assertEqual(self.ends("t5", (self.DENIED, True), ("Archived session local_kid.", False)), {})
        self.ends("t6", (self.BUSY, True))
        self.assertEqual(self.ends("t7", ("Archived session local_kid.", False)), {}, "a call that worked clears it")

    def test_with_upkeep_off_no_answer_is_kept(self):
        self.t.stop(TOP, TASK, calls=[(ARCHIVE, {"session_id": KID}, self.BUSY, "failed")], report="Called it.",
                    uuid="t5")
        self.assertFalse(os.path.exists(upkeep.path(self.t.p4, TOP)), "no record of upkeep is made")


class Sweep(Base):
    """An orchestrator is brought back to the sessions it started by events, and by one prompt on a long fixed
    schedule for what no event tells. p4-phi hands that schedule once, as one `CronCreate` call, and its end once."""

    MADE = ("Scheduled recurring job 72f3dc05 (7,37 * * * *). Next run: Nov 22 1:44pm. Session-only (not written "
            "to disk, dies when Claude exits). Auto-expires after 7 days. Use CronDelete to cancel sooner.")

    def made(self):
        return (upkeep.CRON_CREATE, {"cron": upkeep.CRON, "prompt": upkeep.SWEEP, "recurring": True}, self.MADE)

    def test_the_schedule_is_handed_once_while_a_worker_is_out_as_one_cron_create_call(self):
        """scheduled-tasks.md, "Manage session-scoped scheduled tasks": "`CronCreate` | Schedule a new task. Accepts a
        5-field cron expression, the prompt to run, and whether it recurs or fires once." With a started session
        that is not finished and no schedule kept, the session is handed that call once, with the expression
        upkeep.CRON and the words upkeep.SWEEP, after a read of `CronList`."""
        self.turn_on()
        got = self.said()
        line = self.lines(got, "schedule:")
        self.assertEqual(len(line), 1, got)
        for part in (f"`{upkeep.CRON_CREATE}`", f"`{upkeep.CRON}`", f"`{upkeep.CRON_LIST}`", upkeep.SWEEP):
            self.assertIn(part, line[0])
        self.assertEqual(self.lines(self.said(), "schedule:"), [], "handed once")
        self.assertEqual(self.lines(self.said(), "end the schedule:"), [], "and none runs to end")

    def test_the_schedule_comes_seldom_and_its_late_run_stays_inside_the_prompt_cache(self):
        """scheduled-tasks.md, "How late a recurring task runs": "Unless it runs every five minutes, a recurring task
        starts each run late by up to half the gap to the next run, and by at most 30 minutes." best-practices.md,
        "Know what subagents cost": "The prompt cache lasts about an hour on a subscription". And the tool
        `ScheduleWakeup` gives 1200 to 1800 seconds for a wait with no signal to watch. The tool `CronCreate`, in its
        own description: "Avoid the :00 and :30 minute marks when the task allows it", "pick a minute that is NOT 0
        or 30". `CronList` shows a task's first eighty characters, which hold the words the end is told by."""
        minute, *rest = upkeep.CRON.split()
        self.assertEqual(rest, ["*"] * 4, upkeep.CRON)
        marks = sorted(int(m) for m in minute.split(","))
        self.assertFalse({0, 30} & set(marks), "off the marks every other schedule lands on")
        gaps = {(b - a) % 60 or 60 for a, b in zip(marks, marks[1:] + marks[:1])}
        self.assertEqual(len(gaps), 1, "its runs come evenly through the hour")
        gap = gaps.pop()
        self.assertGreaterEqual(gap * 60, 1200)
        self.assertLessEqual(gap + min(gap / 2, 30), 60, "its latest run is inside the hour the cache lasts")
        self.assertTrue(upkeep.SWEEP.startswith(upkeep.OPENS))
        self.assertLessEqual(len(upkeep.OPENS), 80)

    def test_it_is_not_handed_while_a_schedule_runs_and_is_handed_anew_once_claude_code_has_ended_it(self):
        """Whether a schedule runs is read off the session's own calls at each turn's end: a `CronCreate` whose prompt
        holds the sweep's opening words begins it, with the task's id from its answer, until Claude Code's own
        expiry of a recurring task. scheduled-tasks.md: "Recurring tasks automatically expire 7 days after
        creation." """
        self.turn_on()
        self.t.stop(TOP, TASK, [self.made()], report="The sweep's schedule is started.", uuid="c1")
        kept = self.t.session(TOP)
        self.assertEqual((kept.get("schedule") or {}).get("id"), "72f3dc05")
        self.assertAlmostEqual(kept["schedule"]["until"] - time.time(), upkeep.EXPIRY_S, delta=60)
        self.assertTrue(upkeep.schedule_runs(kept))
        self.assertFalse(upkeep.schedule_runs(kept, at=time.time() + upkeep.EXPIRY_S + 5), "Claude Code ends it then")
        self.assertEqual(self.lines(self.said(), "schedule:"), [], "its schedule runs")
        kept = self.t.session(TOP)
        kept["schedule"]["until"] = time.time() - 5         # the seven days passed
        write(os.path.join(self.t.dir(TOP), "session.json"), json.dumps(kept))
        self.assertEqual(len(self.lines(self.said(), "schedule:")), 1, "it expired with a worker out: once more")
        self.assertEqual(self.lines(self.said(), "schedule:"), [])

    def test_the_end_is_handed_once_when_nothing_is_live_by_the_id_the_sessions_own_call_gave(self):
        """With the schedule running and no started session live, the session is handed its end once: `CronList`,
        then `CronDelete` with the task's id. A delete of another task leaves the schedule kept, and a delete of its
        own ends it."""
        self.turn_on()
        self.t.stop(TOP, TASK, [self.made()], report="The sweep's schedule is started.", uuid="c1")
        self.commit()
        self.finish(report="The last row is written now.")
        got = self.said()                                   # a finished worker is no live one, archived or not
        end = self.lines(got, "end the schedule:")
        self.assertEqual(len(end), 1, got)
        for part in (f"`{upkeep.CRON_LIST}`", f"`{upkeep.CRON_DELETE}`", upkeep.OPENS, "`72f3dc05`"):
            self.assertIn(part, end[0])
        self.assertEqual(self.lines(got, "schedule:"), [])
        self.assertEqual(self.lines(self.said(), "end the schedule:"), [], "handed once")
        self.t.stop(TOP, TASK, [(upkeep.CRON_DELETE, {"id": "0a1b2c3d"}, "Cancelled job 0a1b2c3d.")],
                    report="Another task is cancelled.", uuid="c2")
        self.assertTrue(upkeep.schedule_runs(self.t.session(TOP)), "another task's delete ends nothing of the sweep")
        self.t.stop(TOP, TASK, [(upkeep.CRON_DELETE, {"id": "72f3dc05"}, "Cancelled job 72f3dc05.")],
                    report="The schedule is ended.", uuid="c3")
        self.assertNotIn("schedule", self.t.session(TOP))
        self.assertEqual(self.lines(self.said(), "end the schedule:"), [])

    def test_a_started_session_is_asked_for_no_idle_notice(self):
        """A session the desktop app started is told of by the app's own note of its turn end. Seen in the desktop
        app on Claude Code 2.1.326: `SendMessage` with `notify_when_idle` to another session of the app answered
        "no idle subscription was made: notify_when_idle is only supported for Claude sessions on this machine in
        this release". A call so answered keeps no subscription, and a name `ListAgents` gave with its short
        identifier is kept as the name alone."""
        self.turn_on()
        self.assertEqual(self.lines(self.said(), "notice:"), [])
        s = {"sessionId": TOP}
        refused = ("no idle subscription was made: notify_when_idle is only supported for Claude sessions on this "
                   "machine in this release")
        bare = ("{\"success\":false,\"message\":\"Nothing was subscribed: notify_when_idle is only supported for "
                "Claude sessions on this machine in this release (not teammates, subagents, Remote Control or cloud "
                "sessions).\"}")
        for answer in (refused, bare):                  # with a message attached, and with none
            self.assertFalse(upkeep.keep_sweep(s, [{"name": upkeep.SEND, "input": {"to": KID, upkeep.NOTIFY: True},
                                                    "result": answer}]), answer[:40])
            self.assertEqual(upkeep.asked(s), set())
        self.assertTrue(upkeep.keep_sweep(s, [{"name": upkeep.SEND, "result": "Subscribed",
                                               "input": {"to": "upkeep-0a1b2c3d [1adbdd]", upkeep.NOTIFY: True}}]))
        self.assertEqual(upkeep.asked(s), {"upkeep-0a1b2c3d"})
        self.assertEqual(upkeep.asked(s, at=time.time() + upkeep.NOTICE_S + 5), set(), "Claude Code drops it then")
        self.assertFalse(upkeep.keep_sweep(s, [{"name": upkeep.SEND, "input": {"to": "kid", "message": "go on"}}]),
                         "a message with no notice asked for keeps nothing")

    def test_a_session_a_puppeteer_controls_and_did_not_start_counts_as_out_while_it_is_inside_a_turn(self):
        """The app's note of a turn's end goes to the session that started one, and a session's hooks module sends
        each turn's report to that starter, phi.starter_cli, so a puppeteer hears nothing of a session it controls
        and did not start, and no idle notice can be asked of a session the app runs. The sweep's schedule covers
        it: such a session counts as out while it is inside a turn, the schedule's end waits until it is not,
        and a puppeteer with a session it controls is one upkeep keeps."""
        self.turn_on()
        self.t.stop(TOP, TASK, [self.made()], report="The sweep's schedule is started.", uuid="c1")
        self.commit()
        self.finish(report="The last row is written now.")       # the one started session is no live one now
        self.t.record(KID2, title="Another tree's orchestrator")
        self.t.say(KID2, "Port the importer")                    # nobody started it, and it is inside a turn
        rows = [{"sessionId": KID2, "store": self.t.p4}, {"sessionId": KID, "store": self.t.p4}]
        pup = dict(self.t.session(TOP), controls=rows)
        with mock.patch.object(phi, "UPKEEP", True):
            self.assertEqual(upkeep.controlled_out(self.t.p4, pup), [KID2],
                             "the one it started is the app's to tell of")
            keys = [a[0] for a in upkeep.sweep_acts(self.t.p4, pup, upkeep.load(self.t.p4, TOP), False)]
            self.assertEqual(keys, [], "its schedule runs and a controlled session works: no end yet")
            self.t.stop(KID2, "Port the importer", report="The importer is ported.", uuid="k1")
            self.assertEqual(upkeep.controlled_out(self.t.p4, pup), [])
            keys = [a[0] for a in upkeep.sweep_acts(self.t.p4, pup, upkeep.load(self.t.p4, TOP), False)]
            self.assertEqual(keys, [f"schedule-end:{TOP}"], "nothing is out now")
        alone = "local_pup00001"
        write(os.path.join(self.t.dir(alone), "session.json"), json.dumps({"sessionId": alone}))
        self.assertFalse(upkeep.has_tree(self.t.p4, alone), "it started none and controls none")
        write(os.path.join(self.t.dir(alone), "session.json"), json.dumps({"sessionId": alone, "controls": rows}))
        self.assertTrue(upkeep.has_tree(self.t.p4, alone))

    def test_with_upkeep_off_no_line_of_the_sweep_is_handed(self):
        got = self.said()
        self.assertEqual(self.lines(got, "schedule:") + self.lines(got, "notice:"), [])


class FollowThrough(Base):
    def items(self):
        return [i for i in upkeep.load(self.t.p4, TOP)["items"] if not i.get("closed")]

    def test_what_a_report_lists_as_not_fixed_is_kept_and_sent_back_to_its_worker(self):
        self.turn_on()
        self.commit()
        self.finish()
        self.assertEqual(len(self.t.turns(KID)[-1]["left"]), 2, "the Stop hook read the whole report")
        got = self.said()
        lines = self.lines(got, "item it-")
        self.assertEqual(len(lines), 2, got)
        self.assertIn("drops a row when the ports table is empty", lines[0])
        self.assertIn(f"send it back by `SendMessage` with `to` `{KID}`", lines[0])
        ids = [i["id"] for i in self.items()]
        self.assertEqual(len(ids), 2)
        later = self.said("What is still open?")
        self.assertEqual(len(self.lines(later, "item it-")), 2, "a later turn still sees every open item")
        self.assertIn("still open", later)

    def test_an_item_closes_on_a_note_on_a_landed_commit_or_on_ezexes_word_and_on_nothing_else(self):
        self.turn_on()
        self.commit()
        self.finish()
        self.said()
        first, second = [i["id"] for i in self.items()]
        r = self.t.cli(TOP, "upkeep", "close", first)
        self.assertEqual(r.returncode, 2)
        self.assertIn("name what closes it", r.stderr)
        r = self.t.cli(TOP, "upkeep", "close", first, "--ezexe", "leave it")
        self.assertEqual(r.returncode, 2, "this turn began with another session's message")
        self.assertIn("ezexe's own message", r.stderr)
        r = self.t.cli(TOP, "upkeep", "close", first, "--note", "the empty table never reaches the exporter")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([i["id"] for i in self.items()], [second])
        self.assertIn("left:", phi.load_notes(self.t.p4, TOP)[-1]["claim"])
        write(os.path.join(self.wt, "exporter.py"), "rows = [1, 2]\n")     # a commit that names it, not landed
        git(self.wt, "commit", "-q", "-am", f"a test for a write that fails halfway, {second}")
        self.assertEqual(len(self.lines(self.said(), "item it-")), 1, "not on the default branch: still open")
        git(self.wt, "push", "-q", "origin", "HEAD:main")
        self.assertEqual(self.lines(self.said(), "item it-"), [], "landed: closed by that commit")
        closed = [i for i in upkeep.load(self.t.p4, TOP)["items"] if i["id"] == second][0]["closed"]
        self.assertEqual(closed["how"], "commit")

    def test_ezexes_word_closes_one_in_a_turn_ezexe_began(self):
        self.turn_on()
        self.commit()
        self.finish()
        self.said("Leave the empty table case, it cannot happen.")
        first = self.items()[0]["id"]
        r = self.t.cli(TOP, "upkeep", "close", first, "--ezexe", "leave the empty table case")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.items()), 1)

    def test_an_archived_workers_item_goes_to_a_successor_and_to_a_card_on_a_turn_no_person_began(self):
        self.turn_on()
        self.commit()
        self.finish()
        self.archive_in_app()
        got = flat(self.said())
        self.assertIn("is archived, so it goes to a successor", got)
        self.assertIn("no person began this turn", got)
        self.assertIn("`mcp__ccd_session__start_session` with `initiation` `own_initiative`", got)
        self.assertIn("tell ezexe in one line that the card waits", got)
        self.assertIn("`PushNotification`, also send one that says what waits", got)
        self.assertNotIn("wake_when_done", got, "the start tool refuses it on a card")

    def test_a_successor_is_started_on_a_turn_ezexe_began(self):
        self.turn_on()
        self.commit()
        self.finish()
        self.archive_in_app()
        got = flat(self.said("What did the worker leave?"))
        self.assertIn("it goes to a successor: start its session with the call", got)
        self.assertNotIn("own_initiative", got)

    def test_a_report_with_no_such_list_leaves_no_item(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now. Nothing is left open.")
        self.said()
        self.assertEqual(self.items(), [])

    def test_the_reports_words_are_read_by_their_heading_or_label_and_by_nothing_looser(self):
        text = ("Done.\n\n## Findings left open\n- **An 8.3 path:** the compare misses it.\n- One more flake may exist.\n"
                "\n## What landed\n- The fix.\n\nNot checked live: the start of a chosen reading.\n"
                "Still found and not fixed, of the same kind: `meta_pass` holds two ledgers against each other.\n"
                "We left the file as it was and went on.\nFollow-ups: none\n")
        self.assertEqual(upkeep.left_of(text), [
            "An 8.3 path: the compare misses it.", "One more flake may exist.",
            "the start of a chosen reading.", "`meta_pass` holds two ledgers against each other."])


class Waits(Base):
    def test_a_kept_wait_is_handed_as_due_once_that_sessions_work_is_on_the_default_branch(self):
        self.turn_on()
        r = self.t.cli(TOP, "upkeep", "wait", "Run the ports migration on the store", "--on", KID)
        self.assertEqual(r.returncode, 0, r.stderr)
        wid = re.search(r"wt-[0-9a-f]{8}", r.stdout).group(0)
        self.assertEqual(self.lines(self.said(), "due:"), [], "the session it waits on still works")
        self.commit(push=False)
        self.finish(report="The last row is written now.")
        self.assertEqual(self.lines(self.said(), "due:"), [], "finished, and its work is not landed yet")
        git(self.wt, "push", "-q", "origin", "HEAD:main")
        due = self.lines(self.said(), "due:")
        self.assertEqual(len(due), 1)
        self.assertIn(wid, due[0])
        self.assertIn(f"waited on \"{KID_TITLE}\" `{KID}`", due[0])
        self.assertEqual(len(self.lines(self.said("And now?"), "due:")), 1, "a later turn still sees it")
        self.assertEqual(self.t.cli(TOP, "upkeep", "close", wid, "--note", "the migration ran on the store").returncode, 0)
        self.assertEqual(self.lines(self.said(), "due:"), [])

    def test_a_step_that_falls_due_when_no_session_is_open_gets_the_cloud_runs_command_for_ezexe_to_type(self):
        """A step that waits on a time may fall due with no session open, and then no hook of p4-phi runs. Claude
        Code has runs that start with no session open, and p4-phi builds none: scheduled-tasks.md, "Compare
        scheduling options", gives a cloud scheduled task "No (fresh clone)" for local files and no need of the
        machine, and routines.md, "Run `/schedule` in any session to create a scheduled task conversationally. You
        can also pass a description directly". So a step that needs only the repository gets that command with its
        prompt written, on a line of its own, for ezexe to type: making one starts sessions later."""
        self.turn_on()
        step = "Run the tests of main on the newest Claude Code build and say which fail"
        r = self.t.cli(TOP, "upkeep", "wait", step, "--at", "every weekday at 7:17am")
        self.assertEqual(r.returncode, 0, r.stderr)
        said, command, closes = r.stdout.rstrip("\n").split("\n")
        wid = re.match(r"kept as (wt-[0-9a-f]{8}): ", said).group(1)
        for words in ("needs only the repository", "a cloud scheduled task's", "a fresh clone on Anthropic's cloud",
                      "it is ezexe's to make and p4-phi makes none", "give ezexe the command below to type",
                      "do not run it yourself", "asks ezexe for the repository and confirms the time"):
            self.assertIn(words, said)
        self.assertEqual(command, f"/schedule every weekday at 7:17am, {step}. {upkeep.RUN_ENDS}")
        self.assertIn(f"upkeep close {wid} --note", closes)
        kept = [w for w in upkeep.load(self.t.p4, TOP)["waits"] if w["id"] == wid]
        self.assertEqual([(w["step"], w["at"], w["local"], w.get("on")) for w in kept],
                         [(step, "every weekday at 7:17am", False, None)])
        again = self.t.cli(TOP, "upkeep", "wait", step, "--at", "every weekday at 7:17am")
        self.assertIn(f"kept as {wid}", again.stdout)
        self.assertEqual(len(upkeep.load(self.t.p4, TOP)["waits"]), 1, "the same step at the same time is kept once")
        # it waits on no session, so no line hands it as due, and `upkeep` lists it until it is closed
        self.commit()
        self.finish(report="The last row is written now.")
        self.assertEqual(self.lines(self.said(), "due:"), [])
        listed = self.t.cli(TOP, "upkeep").stdout
        self.assertIn("Kept for a scheduled run, which ezexe makes:", listed)
        self.assertIn(f"- {wid}, \"{step}\", every weekday at 7:17am: a cloud scheduled task, by `/schedule`", listed)
        closed = self.t.cli(TOP, "upkeep", "close", wid, "--note", "ezexe made the task with /schedule")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertNotIn("Kept for a scheduled run", self.t.cli(TOP, "upkeep").stdout)

    def test_one_that_needs_the_projects_local_store_gets_a_desktop_scheduled_task_on_ezexes_yes(self):
        """The project's store is in no clone, so a step that needs it is no cloud run's. desktop-scheduled-tasks.md:
        "Tasks only run while the desktop app is running and your computer is awake", with the machine's own files,
        and "You can also ask Claude in any Desktop session to set the schedule". That tool's own text says an
        approval prompt "may or may not appear", so the line asks for ezexe's yes before the call."""
        self.turn_on()
        step = "Sweep the store's lifetimes and write what was cleared into the notebook"
        r = self.t.cli(TOP, "upkeep", "wait", step, "--at", "every day at 6:43am", "--local")
        self.assertEqual(r.returncode, 0, r.stderr)
        said, prompt, closes = r.stdout.rstrip("\n").split("\n")
        wid = re.match(r"kept as (wt-[0-9a-f]{8}): ", said).group(1)
        for words in ("needs the project's local store, which a cloud run's fresh clone does not hold",
                      "a Desktop scheduled task's", "while the desktop app is open and the computer is awake",
                      "it is ezexe's to make and p4-phi makes none", "by the app's own question",
                      "On ezexe's yes alone, make it with `mcp__scheduled-tasks__create_scheduled_task`",
                      "\"every day at 6:43am\" as its schedule", "Scheduled, New task, with Only on this computer on"):
            self.assertIn(words, said)
        self.assertNotIn("/schedule", r.stdout)
        folder = upkeep.spelled(upkeep.main_of(self.t.session(TOP).get("cwd") or "") or self.t.session(TOP).get("cwd") or "")
        self.assertTrue(folder)
        self.assertEqual(prompt, f"{step}. Work in the folder {folder}, whose `.claude/p4` is the project's store. "
                                 f"{upkeep.RUN_ENDS}")
        self.assertIn(folder, said)
        self.assertTrue(next(w for w in upkeep.load(self.t.p4, TOP)["waits"] if w["id"] == wid)["local"])
        self.assertIn(f"- {wid}, \"{step}\", every day at 6:43am: a Desktop scheduled task, by "
                      "`mcp__scheduled-tasks__create_scheduled_task` on ezexe's yes", self.t.cli(TOP, "upkeep").stdout)

    def test_a_wait_names_a_session_or_a_time_and_a_time_is_said(self):
        self.turn_on()
        both = self.t.cli(TOP, "upkeep", "wait", "Run the ports migration on the store", "--on", KID, "--at", "tomorrow at 9am")
        self.assertNotEqual(both.returncode, 0)
        self.assertIn("with --on, or on a time, with --at, and not on both", both.stderr + both.stdout)
        short = self.t.cli(TOP, "upkeep", "wait", "Run it", "--at", "tomorrow at 9am")
        self.assertNotEqual(short.returncode, 0)
        self.assertEqual(upkeep.load(self.t.p4, TOP)["waits"], [])
        with self.assertRaises(ValueError):
            upkeep.later(self.t.p4, self.t.session(TOP), "Run the ports migration on the store", " ,. ")

    def test_a_step_of_the_task_list_that_names_the_session_it_waits_on_is_kept_with_it(self):
        self.turn_on()
        plan = {"items": [{"content": "Start the worker for the last row", "status": "completed"},
                          {"content": f"Run the ports migration once \"{KID_TITLE}\" has landed", "status": "pending"}]}
        self.t.hook("plan", TOP, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                  "tool_input": plan, "tool_response": "Plan updated."})
        self.assertEqual(self.lines(self.said(), "due:"), [])
        self.commit()
        self.finish(report="The last row is written now.")
        due = self.lines(self.said(), "due:")
        self.assertEqual(len(due), 1, due)
        self.assertIn("Run the ports migration", due[0])
        self.assertIn("Do it in this turn", due[0])

    def test_on_a_turn_no_person_began_a_due_step_goes_by_message_to_a_live_worker_that_fits(self):
        self.turn_on()
        self.t.record(KID2, TOP, KID2_TITLE)
        self.t.say(KID2, handed("Run the ports migration for the narwhal exporter's store and report"))
        self.t.stop(KID2, "Run the ports migration", report="Ready for the migration.", uuid="k2")
        self.t.cli(TOP, "upkeep", "wait", "Run the ports migration on the narwhal exporter's store", "--on", KID)
        self.commit()
        self.finish(report="The last row is written now.")
        due = flat(self.lines(self.said(), "due:")[0])
        self.assertIn("the app refuses a new start on such a turn", due)
        self.assertIn(f"send it by `SendMessage` with `to` `{KID2}`", due)
        mine = flat(self.lines(self.said("Carry on."), "due:")[0])        # a turn ezexe began: a start
        self.assertIn("start its session with the call", mine)
        self.assertNotIn("refuses", mine)

    def test_a_due_step_does_not_go_by_message_to_the_session_it_waited_on(self):
        """Seen in the desktop app on Claude Code 2.1.326: a step that waited on a finished session was sent by
        message to that same session, since three words of the step were in its task, while the same handing had
        the orchestrator archive it. The session a step waited on is done with its task, so the step goes on to
        another live session that fits, and with none to a session of its own."""
        self.turn_on()
        step = "Check the last row of the narwhal ports table against the store"
        self.assertGreaterEqual(len(phi.plans.words(step) & phi.plans.words(self.t.session(KID).get("task"))), 3,
                                "the step fits the task of the session it waits on")
        self.t.cli(TOP, "upkeep", "wait", step, "--on", KID)
        self.commit()
        self.finish(report="The last row is written now.")
        due = flat(self.lines(self.said(), "due:")[0])
        self.assertIn(f"waited on \"{KID_TITLE}\" `{KID}`", due)
        self.assertNotIn(f"with `to` `{KID}`", due)
        self.assertIn("no live session's task covers it", due)

    def test_a_due_step_does_not_go_by_message_to_a_session_it_shares_only_everyday_words_with(self):
        """Seen live: a step reached an unrelated session on the three words `nothing`, `own` and `session`, which
        every brief of this project carries or any task may hold. Such words make no fit."""
        self.turn_on()
        self.t.record(KID2, TOP, KID2_TITLE)
        self.t.say(KID2, handed("Write the exporter's retry in a session of its own, and change nothing else"))
        self.t.stop(KID2, "Write the retry", report="Ready for the retry.", uuid="k2")
        step = "Start a session of its own for the walrus importer's schema, with nothing before it"
        self.assertEqual(phi.plans.words(step) & phi.plans.words(self.t.session(KID2).get("task")),
                         {"nothing", "own", "session"}, "the step shares the live case's three words, and no other")
        self.t.cli(TOP, "upkeep", "wait", step, "--on", KID)
        self.commit()
        self.finish(report="The last row is written now.")
        due = flat(self.lines(self.said(), "due:")[0])
        self.assertNotIn(f"with `to` `{KID2}`", due)
        self.assertIn("no live session's task covers it", due)


class Leftovers(Base):
    def test_after_an_archive_the_clean_worktree_and_the_merged_branch_go_by_gits_own_commands(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        first = self.lines(self.said(), "archive:")[0]
        self.assertIn("Once the call returns, remove what it leaves on disk", first)
        self.archive_in_app()
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1)
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        self.assertEqual(len(cmds), 2, left[0])
        self.assertRegex(cmds[0], r"^git -C \"[^\"]+\" worktree remove \"[^\"]+\"$")
        self.assertRegex(cmds[1], r"^git -C \"[^\"]+\" branch -d worktree-kid$")
        self.assertFalse([c for c in cmds if "--force" in c or " -f" in c or " -D" in c])
        for c in cmds:                              # git takes each as it is handed
            r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertFalse(os.path.isdir(self.wt))
        self.assertEqual(git(self.repo, "branch", "--list", "worktree-kid").stdout.strip(), "")
        self.assertEqual(self.lines(self.said(), "leftovers of"), [], "nothing of it is left")

    def reader_in(self, folder):
        """TOP's own folder, as the app's record gives it: p4-phi's record follows it at TOP's next message."""
        self.t.record(TOP, title="Orchestrate the narwhal exporter", cwd=folder)
        phi.RECORDS.clear()

    def tree_of(self, repo, name):
        """A linked worktree of `repo` on a branch of its own, as the file system spells its folder."""
        tree = os.path.join(self.tmp, "trees", name)
        r = git(repo, "worktree", "add", "-q", tree, "-b", f"worktree-{name}", "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.realpath(tree).replace("\\", "/")

    def other_repository(self):
        """A second repository with one commit, and its folder."""
        other = os.path.join(self.tmp, "other")
        subprocess.run(["git", "init", "-q", "-b", "main", other], check=True, capture_output=True)
        write(os.path.join(other, "notes.md"), "notes\n")
        git(other, "add", "-A")
        self.assertEqual(git(other, "commit", "-q", "-m", "the notes").returncode, 0)
        return other

    def test_a_session_in_a_worktree_of_the_repository_is_handed_the_commands_with_no_C(self):
        """https://code.claude.com/docs/en/worktrees.md, "How Claude Code enforces isolation": "While a session is
        isolated in a worktree, Claude Code blocks the tool calls the checks below define", among them "Git
        redirects: Claude Code blocks a Bash or Monitor command that redirects git into the main checkout. The
        redirect can come through `git -C`". The same page, "What worktrees share with the main checkout": "git
        commands in a worktree write to the main repository's shared `.git` directory." So a session whose own
        folder is a worktree of the leftover's repository is handed `git worktree remove` and `git branch -d` with
        no `-C`, to run in its own folder, and git takes each there."""
        mine = self.tree_of(self.repo, "top")
        self.reader_in(mine)
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        first = self.lines(self.said(), "archive:")[0]
        self.assertIn("Once the call returns, remove what it leaves on disk", first)
        self.assertNotIn("git -C", first, "the archive line's removal has no -C either")
        self.archive_in_app()
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1)
        kid = os.path.realpath(self.wt).replace("\\", "/")
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        self.assertEqual(cmds, [f'git worktree remove "{kid}"', "git branch -d worktree-kid"])
        self.assertNotIn("git -C", left[0])
        self.assertIn(f"run in `{mine}` with no `-C`, which Claude Code refuses from a worktree", left[0])
        self.assertFalse([c for c in cmds if "--force" in c or " -f" in c or " -D" in c])
        for c in cmds:                              # git takes each in the session's own folder
            r = subprocess.run(c, shell=True, cwd=mine, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertFalse(os.path.isdir(self.wt))
        self.assertEqual(git(self.repo, "branch", "--list", "worktree-kid").stdout.strip(), "")
        self.assertTrue(os.path.isdir(mine), "its own worktree stays")
        self.assertEqual(self.lines(self.said(), "leftovers of"), [], "nothing of it is left")

    def test_a_session_in_the_checkout_itself_keeps_the_commands_with_C(self):
        """No check of the page holds a session that is in no worktree, so in the repository's main checkout the
        line names that checkout by `-C`, as it did."""
        self.reader_in(self.repo)
        self.archived_kid()
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1)
        checkout = os.path.realpath(self.repo).replace("\\", "/")
        kid = os.path.realpath(self.wt).replace("\\", "/")
        self.assertEqual(re.findall(r"`(git [^`]+)`", left[0]),
                         [f'git -C "{checkout}" worktree remove "{kid}"', f'git -C "{checkout}" branch -d worktree-kid'])
        self.assertNotIn("with no `-C`", left[0])

    def test_a_session_in_a_worktree_of_another_repository_is_told_once_who_removes_it(self):
        """A session whose own folder is a worktree of another repository, and which works in no worktree of the
        leftover's, is handed no command for it: the line says once that a session in that repository removes it,
        with the two commands as that session runs them, and the worktree is left."""
        theirs = self.tree_of(self.other_repository(), "elsewhere")
        self.reader_in(theirs)
        self.archived_kid()
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of"), [], got)
        named = self.lines(got, "left on disk")
        self.assertEqual(len(named), 1, got)
        kid = os.path.realpath(self.wt).replace("\\", "/")
        self.assertIn("is not the one this session's own worktree is of, so a session in that repository removes "
                      f"it, by `git worktree remove \"{kid}\"` and `git branch -d worktree-kid` run there", named[0])
        self.assertNotIn("git -C", named[0])
        self.assertIn("Name each to ezexe once", named[0])
        again = self.said()
        self.assertEqual(self.lines(again, "left on disk") + self.lines(again, "leftovers of"), [], "said once")
        self.assertTrue(os.path.isdir(self.wt), "left as it is")

    def test_a_session_that_works_in_a_worktree_of_the_repository_runs_them_there(self):
        """A session whose own folder is a worktree of another repository can still work in a worktree of the
        leftover's, such as one it made with `git worktree add`: its turns' heads hold it. The commands then carry
        no `-C` and the line names that worktree as the folder they run in."""
        theirs = self.tree_of(self.other_repository(), "elsewhere")
        made = self.tree_of(self.repo, "made")
        self.reader_in(theirs)
        head = git(made, "rev-parse", "HEAD").stdout.strip()
        with open(os.path.join(self.t.dir(TOP), "turns.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"delta": {"heads": [f"{made}@worktree-made {head}"]}}) + "\n")
        self.archived_kid()
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1)
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        kid = os.path.realpath(self.wt).replace("\\", "/")
        self.assertEqual(cmds, [f'git worktree remove "{kid}"', "git branch -d worktree-kid"])
        self.assertIn(f"run in `{made}` with no `-C`", left[0])
        for c in cmds:
            r = subprocess.run(c, shell=True, cwd=made, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertFalse(os.path.isdir(self.wt))

    def test_a_dirty_worktree_is_named_to_ezexe_once_and_left(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        self.said()
        self.archive_in_app()
        write(os.path.join(self.wt, "notes.txt"), "half a thought\n")
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of"), [])
        named = self.lines(got, "left on disk")
        self.assertEqual(len(named), 1, got)
        self.assertIn("holds 1 uncommitted change", named[0])
        self.assertIn("Name each to ezexe once", named[0])
        self.assertIn("`mcp__ccd_host__get_storage_usage` lists it", named[0])
        self.assertIn("`mcp__ccd_host__discard_kept_worktree`", named[0])
        self.assertIn("never on `phi.upkeep` alone", named[0])
        again = self.said()
        self.assertEqual(self.lines(again, "left on disk") + self.lines(again, "leftovers of"), [])
        self.assertTrue(os.path.isdir(self.wt), "left as it is")

    def archived_kid(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        self.said()
        self.archive_in_app()

    def test_a_worktree_a_live_session_still_works_in_is_passed_over_until_that_session_is_archived(self):
        self.archived_kid()
        self.t.record(KID2, TOP, KID2_TITLE, cwd=self.wt)      # a session the app still runs shares the folder
        self.t.say(KID2, handed("Check the ports table once more and report"))
        self.t.stop(KID2, "Check the ports table", report="Checked.", uuid="k2")
        self.assertEqual(self.lines(self.said(), "leftovers of"), [])
        self.assertTrue(os.path.isdir(self.wt))
        self.archive_in_app(KID2)
        self.assertEqual(len(self.lines(self.said(), "leftovers of")), 1, "free now: named")

    def test_a_worktree_that_holds_another_checkout_git_ignores_is_named_once_and_left(self):
        self.archived_kid()
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("inner/\n")
        inner = os.path.join(self.wt, "inner")
        subprocess.run(["git", "init", "-q", inner], check=True, capture_output=True)
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of"), [], got)
        self.assertIn("it holds another checkout", flat(got))
        self.assertTrue(os.path.isdir(inner))

    def test_a_worktree_that_holds_a_link_is_held_until_the_link_is_gone_and_its_target_is_left(self):
        self.archived_kid()
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("node_modules\n")
        target = os.path.realpath(tempfile.mkdtemp())
        kept = os.path.join(target, "keep.txt")
        open(kept, "w").close()
        at = os.path.join(self.wt, "node_modules")
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", at, target], check=True, capture_output=True)
        else:
            os.symlink(target, at, target_is_directory=True)
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of"), [], got)
        self.assertIn("it holds a link", flat(got))
        self.assertIn("unlink", flat(got))
        self.assertTrue(shared.unlink(at))
        self.assertEqual(len(self.lines(self.said(), "leftovers of")), 1, "free now: named")
        self.assertTrue(os.path.isfile(kept), "what the link pointed at is whole")

    def test_a_worktree_the_archive_already_took_leaves_its_merged_branch_to_delete(self):
        import shutil
        self.archived_kid()
        shutil.rmtree(self.wt)                                  # as the app's archive cleans up the folder it made
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1)
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        self.assertEqual([c.split('" ', 1)[1] for c in cmds], ["worktree prune", "branch -d worktree-kid"])
        for c in cmds:
            r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertEqual(git(self.repo, "branch", "--list", "worktree-kid").stdout.strip(), "")
        self.assertEqual(self.lines(self.said(), "leftovers of"), [])

    def test_an_emptied_folder_git_no_longer_lists_leaves_only_its_merged_branch_to_delete(self):
        """A removal on Windows can leave the worktree's emptied folder on disk. git lists no worktree there, so
        `git worktree remove` is refused for it, and until 0.11.146 upkeep handed that command at every message."""
        inner = os.path.join(self.repo, ".claude", "worktrees", "kid").replace("\\", "/")
        os.makedirs(os.path.dirname(inner))
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write(".claude/\n")
        self.assertEqual(git(self.repo, "worktree", "move", self.wt, inner).returncode, 0)
        self.wt = inner
        self.t.record(KID, TOP, KID_TITLE, cwd=self.wt)
        phi.RECORDS.clear()
        self.archived_kid()
        self.assertEqual(git(self.repo, "worktree", "remove", "--force", self.wt).returncode, 0)
        os.makedirs(self.wt)                                    # the emptied folder Windows left
        left = self.lines(self.said(), "leftovers of")
        self.assertEqual(len(left), 1, left)
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        self.assertEqual([c.split('" ', 1)[1] for c in cmds], ["branch -d worktree-kid"])
        for c in cmds:
            r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertEqual(self.lines(self.said(), "leftovers of"), [], "nothing is asked for again")
        self.assertTrue(os.path.isdir(self.wt), "the folder is left as it is")

    def test_a_worktree_on_a_detached_head_goes_and_its_unmerged_branch_stays(self):
        self.archived_kid()
        self.commit("rows = [1, 2, 3]\n", "one more row", push=False)     # the branch moves on, unmerged
        self.assertEqual(git(self.wt, "checkout", "-q", "--detach", "origin/main").returncode, 0)
        d = jload(os.path.join(self.t.app, KID + ".json"))
        d["branch"] = "worktree-kid"                                       # as the app's record names its branch
        write(os.path.join(self.t.app, KID + ".json"), json.dumps(d))
        phi.RECORDS.clear()
        got = self.said()
        left = self.lines(got, "leftovers of")
        self.assertEqual(len(left), 1, got)
        self.assertIn("worktree remove", left[0])
        self.assertNotIn("branch -d", left[0])
        self.assertIn("`worktree-kid` in", flat(got))
        self.assertIn("holds commits that are not on origin/main", flat(got))

    def test_an_unmerged_branch_is_never_named_for_removal(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        self.said()
        self.archive_in_app()
        self.commit("rows = [1, 2, 3]\n", "one more row", push=False)
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of"), [])
        self.assertIn("holds commits that are not on origin/main", flat(got))

    def test_the_worktree_of_a_subagent_whose_branch_is_merged_goes_the_same_way(self):
        self.turn_on()
        tree = os.path.join(self.repo, ".claude", "worktrees", "agent-a1")
        self.assertEqual(git(self.repo, "worktree", "add", "-q", tree, "-b", "worktree-agent-a1",
                             "origin/main").returncode, 0)
        plan = os.path.join(self.t.dir(TOP), "plan.json")
        write(plan, json.dumps({"steps": [], "loose": [{"id": "a1", "agent": "a1", "status": "completed",
                                                         "wrote": [os.path.join(tree, "exporter.py")]}]}))
        left = self.lines(self.said(), "leftovers of a subagent")
        self.assertEqual(len(left), 1)
        self.assertIn("branch -d worktree-agent-a1", left[0])
        self.assertIn("worktree remove", left[0])
        git(self.repo, "worktree", "lock", tree)       # an agent that still runs holds its worktree locked
        self.assertEqual(self.lines(self.said(), "leftovers of a subagent"), [])

    def test_a_folder_a_removed_subagents_worktree_left_is_handed_no_removal(self):
        """A removal run from a shell that stands in the worktree leaves its folder half removed on Windows, with
        no `.git` entry. git lists no worktree there, and until 0.11.147 upkeep handed its removal at every message."""
        self.turn_on()
        tree = os.path.join(self.repo, ".claude", "worktrees", "agent-a1")
        self.assertEqual(git(self.repo, "worktree", "add", "-q", tree, "-b", "worktree-agent-a1",
                             "origin/main").returncode, 0)
        plan = os.path.join(self.t.dir(TOP), "plan.json")
        write(plan, json.dumps({"steps": [], "loose": [{"id": "a1", "agent": "a1", "status": "completed",
                                                         "wrote": [os.path.join(tree, "exporter.py")]}]}))
        self.assertEqual(git(self.repo, "worktree", "remove", "--force", tree).returncode, 0)
        os.makedirs(os.path.join(tree, "src"))                  # what Windows left of it
        write(os.path.join(tree, "README.md"), "left")
        got = self.said()
        self.assertEqual(self.lines(got, "leftovers of a subagent"), [])
        self.assertNotIn("worktree remove", flat(got))
        self.assertTrue(os.path.isdir(tree), "the folder is left as it is")

    def test_the_sessions_own_worktree_a_subagent_wrote_in_is_no_leftover_of_it(self):
        """A subagent with no isolation writes in the session's own folder, which can be a worktree under
        `.claude/worktrees`. The app's record keeps the folder the session began in, so p4-phi's record of its cwd
        names the checkout, and the worktree it moved to is held by its own turns' heads, as a live session's
        record held it. That folder is the session's own and never the subagent's leftover: it is named in
        neither line, dirty or clean, while a true subagent's worktree still goes."""
        mine = os.path.join(self.repo, ".claude", "worktrees", "rebase")
        self.assertEqual(git(self.repo, "worktree", "add", "-q", mine, "-b", "worktree-rebase",
                             "origin/main").returncode, 0)
        theirs = os.path.join(self.repo, ".claude", "worktrees", "agent-a1")
        self.assertEqual(git(self.repo, "worktree", "add", "-q", theirs, "-b", "worktree-agent-a1",
                             "origin/main").returncode, 0)
        self.reader_in(self.repo)
        head = git(mine, "rev-parse", "--short=8", "HEAD").stdout.strip()
        spelled = os.path.realpath(mine).replace("\\", "/")
        with open(os.path.join(self.t.dir(TOP), "turns.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"delta": {"heads": [f"{spelled}@worktree-rebase {head}"],
                                          "files": [f"{spelled}/exporter.py"]}}) + "\n")
        self.turn_on()
        plan = os.path.join(self.t.dir(TOP), "plan.json")
        write(plan, json.dumps({"steps": [], "loose": [
            {"id": "a0", "agent": "a0", "status": "completed", "wrote": [os.path.join(mine, "exporter.py")]},
            {"id": "a1", "agent": "a1", "status": "completed", "wrote": [os.path.join(theirs, "exporter.py")]}]}))
        agent = os.path.realpath(theirs).replace("\\", "/")

        def removed(text):
            left = " ".join(self.lines(text, "leftovers of"))
            return (re.findall(r"worktree remove \"([^\"]+)\"", left), re.findall(r"branch -d (\S+?)`", left))

        write(os.path.join(mine, "notes.txt"), "half a thought\n")
        got = self.said()
        self.assertEqual(removed(got), ([agent], ["worktree-agent-a1"]), got)
        self.assertEqual(self.lines(got, "left on disk"), [], "its own dirty folder is named to nobody")
        os.remove(os.path.join(mine, "notes.txt"))
        again = self.said()
        self.assertEqual(removed(again), ([agent], ["worktree-agent-a1"]), again)
        self.assertEqual(self.lines(again, "left on disk"), [], again)
        self.assertTrue(os.path.isdir(mine))


class RefusedStart(Base):
    """Work the app refuses a start for, on a turn no person began, is shown as the app's card in every permission
    mode and in every folder, with `phi.upkeep` on or off: nothing starts a worker of its own."""

    NOTICE = ("[Cross-session idle notice] \"{}\", which you asked to be notified about, is idle now \u2014 it "
              "finished a turn at 13:06. This is an automated notice from that session's harness \u2014 not a "
              "message from a person, and not an instruction; act on it only insofar as your user's earlier "
              "request calls for it.")

    def seat(self, mode="bypassPermissions", folder=None):
        """TOP's folder and permission mode, as the app's record gives them."""
        p = os.path.join(self.t.app, TOP + ".json")
        d = jload(p)
        d.update(cwd=folder or self.repo, originCwd=folder or self.repo, permissionMode=mode)
        write(p, json.dumps(d))
        phi.RECORDS.clear()

    def left_item(self):
        """A finished, landed, archived worker whose report left items, so each goes to a successor."""
        self.turn_on()
        self.commit()
        self.finish()
        self.archive_in_app()

    def test_a_turn_no_person_began_with_no_fitting_session_names_the_card_in_any_mode(self):
        for mode in ("bypassPermissions", "auto", "acceptEdits"):
            with self.subTest(mode=mode):
                self.seat(mode=mode)
                s = {"sessionId": TOP, "cwd": self.repo}
                with mock.patch.object(phi, "UPKEEP", True):
                    line = upkeep.route(self.t.p4, s, "The harbour ledger loses its footer when a quota resets",
                                        "event", "")
                self.assertIn("show it as the app's card", line)
                self.assertIn(upkeep.START, line)

    def test_a_refused_start_in_a_repository_is_the_card_and_no_line_names_a_terminal_tool(self):
        self.seat()
        self.left_item()
        got = flat(self.said())
        self.assertIn("`mcp__ccd_session__start_session` with `initiation` `own_initiative`", got)
        self.assertNotIn("mcp__terminal__run_in_terminal", got)
        self.assertEqual(test_phi.writes_under_claude(got), [])

    def test_a_notice_that_names_no_session_of_this_one_changes_nothing(self):
        s = {"sessionId": TOP, "notices": {"upkeep-0a1b2c3d": time.time() + 60}}
        self.assertEqual(upkeep.notice_came(s, "Go on with the exporter."), "")
        self.assertEqual(upkeep.notice_came(s, self.NOTICE.format("another-session")), "another-session")
        self.assertEqual(upkeep.asked(s), {"upkeep-0a1b2c3d"})
        self.assertEqual(upkeep.notice_came(s, self.NOTICE.format("upkeep-0a1b2c3d")), "upkeep-0a1b2c3d")
        self.assertEqual(upkeep.asked(s), set())


class Wake(Base):
    def due(self):
        """An act that comes due with no event of the session: its worker's report was handed while the work was not
        landed, the turn ended, and the commit reached the default branch after."""
        self.turn_on()
        self.commit(push=False)
        self.finish(report="The last row is written now.")
        self.assertEqual(len(self.lines(self.said(), "land first:")), 1)
        self.t.stop(TOP, TASK, report="Waiting on the landing.", uuid="t2")
        self.assertEqual(git(self.wt, "push", "-q", "origin", "HEAD:main").returncode, 0)

    def test_with_every_started_session_idle_and_an_act_due_a_look_answers_one_turn_for_it(self):
        self.due()
        got = self.look("--net")
        self.assertTrue(str(got.get("upkeep") or "").startswith("phi (p4-phi): upkeep is due"), got)
        self.assertNotIn("upkeep", self.look("--net"), "one turn for an act, never a second")
        woken = self.said(got["upkeep"])               # the turn the module started is handed the acts themselves
        self.assertEqual(len(self.lines(woken, "archive:")), 1)
        self.assertEqual(self.t.session(TOP)["turnBy"], "event", "the module's prompt is no message of ezexe's")

    def test_no_turn_is_started_while_a_started_session_works_or_this_one_does(self):
        self.due()
        self.t.say(KID, "One more thing.")
        self.assertNotIn("upkeep", self.look("--net"))
        self.t.stop(KID, "One more thing.", report="Done.", uuid="u3")
        self.t.say(TOP, "Anything new?")
        self.assertNotIn("upkeep", self.look("--net"), "this session is inside a turn, which was handed the acts")

    def test_the_turns_started_for_upkeep_stay_inside_the_budget_until_ezexe_speaks(self):
        self.due()
        d = upkeep.load(self.t.p4, TOP)
        d["woke"] = {"n": 2, "time": "2026-11-19 10:00"}        # phi.keep_going_max turns were started already
        upkeep.save(self.t.p4, TOP, d)
        self.assertNotIn("upkeep", self.look("--net"))
        self.said("Where does it stand?")                        # ezexe's own message gives the budget again
        self.assertNotIn("woke", upkeep.load(self.t.p4, TOP))

    def test_a_message_that_carried_an_act_leaves_no_turn_to_start_for_it(self):
        self.due()
        self.said()
        self.t.stop(TOP, TASK, report="Archived.", uuid="t3")
        self.assertNotIn("upkeep", self.look("--net"))


class Words(unittest.TestCase):
    """The words that leave an archive to ezexe stand with the setting off and go with it on."""

    LEAVES = ("Archiving one in the app is ezexe's", "approval card")

    def both(self, make):
        from unittest import mock
        import controls
        import relay
        with mock.patch.object(controls, "UPKEEP", False), mock.patch.object(relay, "UPKEEP", False):
            off = make()
        with mock.patch.object(controls, "UPKEEP", True), mock.patch.object(relay, "UPKEEP", True):
            on = make()
        return off, on

    def test_the_line_about_finished_children(self):
        import relay
        off, on = self.both(lambda: relay.stale_text([{"id": KID, "title": KID_TITLE, "kind": "done"}]))
        self.assertIn(self.LEAVES[0], off)
        self.assertIn(self.LEAVES[1], off)
        self.assertFalse([w for w in self.LEAVES if w in on], on)
        self.assertIn("its upkeep line names the archive call", on)

    def test_a_puppeteers_rule_its_controlled_sessions_line_and_its_complete_sessions(self):
        import controls
        with tempfile.TemporaryDirectory() as tmp:
            s = {"sessionId": TOP}
            for make in (lambda: controls.rule_text(tmp, s),
                         lambda: controls.PAIR.format(title="P", pid=TOP, section="puppeteers", cmd="phi.py",
                                                      asks="" if controls.UPKEEP else controls.PAIR_ASKS),
                         lambda: controls.complete_text([KID])):
                off, on = self.both(make)
                self.assertIn("approval card", off)
                self.assertNotIn("approval card", on)
        _, on = self.both(lambda: controls.complete_text([KID]))
        self.assertIn(f"archive each with `{ARCHIVE}` and its `session_id`", on)
        self.assertIn("waits on nobody", on)


if __name__ == "__main__":
    unittest.main()
