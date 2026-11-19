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
import unittest
from unittest import mock

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import inproc  # noqa: E402
import p4conf  # noqa: E402
import phi  # noqa: E402
import upkeep  # noqa: E402
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

    def finish(self, report=REPORT, uuid="u1"):
        """The worker shows its turn done and ends it."""
        self.assertEqual(self.t.cli(KID, "done", "ran the exporter's tests and they passed").returncode, 0)
        self.t.stop(KID, BRIEF, report=report, uuid=uuid)

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
        local = jload(os.path.join(self.t.proj, ".claude", "settings.local.json"))
        self.assertNotIn(ARCHIVE, local.get("permissions", {}).get("ask", []), "the keeper wrote no ask rule")
        self.assertIn(f"no ask rule on `{ARCHIVE}`", out)
        r = self.t.cli(TOP, "upkeep", "off")
        self.assertIn("phi.upkeep is off", r.stdout)
        self.assertIs(jload(os.path.join(self.t.p4, "p4.json"))["phi"]["upkeep"], False)
        local = jload(os.path.join(self.t.proj, ".claude", "settings.local.json"))
        self.assertIn(ARCHIVE, local["permissions"]["ask"], "off: the ask rule is p4's again, as today")

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

    def test_the_call_is_handed_three_times_and_then_left(self):
        self.turn_on()
        self.commit()
        self.finish(report="The last row is written now.")
        seen = [len(self.lines(self.said(), "archive:")) for _ in range(4)]
        self.assertEqual(seen, [1, 1, 1, 0])
        self.assertIn(f"archive:{KID}", self.t.cli(TOP, "upkeep").stdout)


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


class TerminalWorker(Base):
    """With `phi.upkeep` on, work the app refuses a start for goes to a scripted run in the Terminal panel, in
    place of the card: https://code.claude.com/docs/en/headless.md, https://code.claude.com/docs/en/worktrees.md
    and https://code.claude.com/docs/en/cross-session-messaging.md, "Non-interactive sessions"."""

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

    def worker(self, name, pid, push=True, change=""):
        """The worktree and the lock a scripted run named `name` leaves, as Claude Code 2.1.328 left them."""
        tree = os.path.join(self.repo, ".claude", "worktrees", name)
        r = git(self.repo, "worktree", "add", "-q", tree, "-b", f"worktree-{name}", "origin/main")
        self.assertEqual(r.returncode, 0, r.stderr)
        if change:
            write(os.path.join(tree, "exporter.py"), change)
            self.assertEqual(git(tree, "commit", "-q", "-am", "the empty table keeps its row").returncode, 0)
            if push:
                self.assertEqual(git(tree, "push", "-q", "origin", "HEAD:main").returncode, 0)
        r = git(self.repo, "worktree", "lock", "--reason", f"claude session {name} (pid {pid})", tree)
        self.assertEqual(r.returncode, 0, r.stderr)
        return tree

    def ended(self):
        """The id of a process that has ended."""
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_with_it_on_a_refused_start_is_a_worker_in_the_terminal_panel_and_no_card(self):
        self.seat()
        self.left_item()
        got = self.said()
        items = self.lines(got, "item")
        self.assertEqual(len(items), 2)
        names = re.findall(r"named `(upkeep-[0-9a-f]{8})`", got)
        self.assertEqual(len(set(names)), 2, got)
        for line in items:
            self.assertIn("no person began this turn", line)
            self.assertIn("start a worker in the Terminal panel for it", line)
            self.assertIn("waits on nobody", line)
        self.assertNotIn("own_initiative", got)
        self.assertNotIn("the card waits", got)
        tail = got.split(upkeep.TAIL_LINE, 1)[1]
        self.assertEqual(tail.count("worker-settings.json`, once for all of them"), 1, "the form is said once")
        kept = json.loads(re.search(r"holds exactly `(\{.*?\}\})`", tail).group(1))
        self.assertEqual(kept, {"crossSessionInbound": "accept",
                                "enabledPlugins": {"p4-phi@p4-marketplace": False,
                                                   "p4-temportal@p4-marketplace": False}})
        repo = os.path.realpath(self.repo).replace("\\", "/")
        self.assertIn("claude -p '/goal Carry out the brief in the file <folder>", tail)
        self.assertRegex(tail, r"brief-<name>\.md\. This is met when every part of that brief is on origin/main")
        self.assertIn("--permission-mode bypassPermissions --worktree <name> --settings '<folder>", tail)
        self.assertRegex(tail, rf"`mcp__terminal__run_in_terminal` with `title` `<name>`, `cwd` `{re.escape(repo)}`")
        self.assertRegex(tail, r"`command` `(& '<folder>\\start-<name>\.ps1'|sh '<folder>/start-<name>\.sh')`")
        self.assertIn("its branch `worktree-<name>`", tail)
        for name in set(names):
            self.assertEqual(tail.count(f"`{name}`"), 1, "each worker is named once in the form")
        self.assertLess(len(tail.split("phi (p4-phi):")[0]), 3200, "the form stays short beside a message")
        self.assertIn("SendMessage to the session named Orchestrate the narwhal exporter.", tail)
        self.assertIn("CLAUDE_CODE_HOST_SESSION_ID", tail)
        for lack in ("no row in the sidebar", "no Changes card", "no archive"):
            self.assertIn(lack, tail)
        self.assertNotIn("--bare", got, "a bare run binds no inbox and takes no message")
        self.assertEqual(test_phi.writes_under_claude(got), [])

    def test_the_script_is_powershells_on_windows_and_a_posix_shells_elsewhere(self):
        s = {"sessionId": TOP, "title": "It's the \"narwhal\" exporter; $(x) `y`"}
        with mock.patch.object(upkeep, "mode_of", lambda sid: "auto"), \
                mock.patch.object(upkeep, "default_ref", lambda repo: "origin/main"), \
                mock.patch.object(upkeep, "title", lambda sid, s=None: s["title"]):
            win = upkeep.script_of(s, "upkeep-0a1b2c3d", "E:/code/narwhal", windows=True)
            nix = upkeep.script_of(s, "upkeep-0a1b2c3d", "/code/narwhal", windows=False)
        self.assertEqual(win[0], "start-upkeep-0a1b2c3d.ps1")
        self.assertEqual(win[2], "& '<folder>\\start-upkeep-0a1b2c3d.ps1'")
        self.assertTrue(win[1][0].startswith("foreach ($n in 'CLAUDE_CODE_HOST_SESSION_ID', "))
        self.assertEqual(win[1][1], "Set-Location 'E:\\code\\narwhal'")
        self.assertEqual(nix[0], "start-upkeep-0a1b2c3d.sh")
        self.assertEqual(nix[2], "sh '<folder>/start-upkeep-0a1b2c3d.sh'")
        self.assertTrue(nix[1][0].startswith("unset CLAUDE_CODE_HOST_SESSION_ID "))
        self.assertEqual(nix[1][1], "cd '/code/narwhal'")
        for lines, typed in ((win[1], win[2]), (nix[1], nix[2])):
            run = lines[-1]
            self.assertIn("--permission-mode auto --worktree upkeep-0a1b2c3d --settings", run)
            self.assertEqual(run.count("'"), 4, "the prompt and the settings path are the two quoted words")
            self.assertNotRegex(run, r"[\"$`;()]", "no character of the title reaches the shell")
            # the tool types one literal line of printable ASCII and refuses a variable read, a pipe and a backtick
            self.assertRegex(typed, r"^[ -~]+$")
            self.assertNotRegex(typed, r"[$|`()]")

    def test_the_card_stays_in_a_mode_that_asks_and_in_a_folder_of_no_repository(self):
        self.seat(mode="acceptEdits")
        self.left_item()
        got = flat(self.said())
        self.assertIn("`mcp__ccd_session__start_session` with `initiation` `own_initiative`", got)
        self.assertNotIn("Terminal panel", got)

    def test_in_a_folder_of_no_repository_the_card_stays(self):
        self.seat(folder=self.t.proj)
        self.left_item()
        got = flat(self.said())
        self.assertIn("tell ezexe in one line that the card waits", got)
        self.assertNotIn("Terminal panel", got)

    def test_both_states_of_the_setting(self):
        s = {"sessionId": TOP, "cwd": self.repo}
        with mock.patch.object(upkeep, "mode_of", lambda sid: "auto"):
            with mock.patch.object(phi, "UPKEEP", True):
                on = upkeep.terminal(self.t.p4, s, "The harbour ledger loses its footer when a quota resets")
                line = upkeep.route(self.t.p4, s, "The harbour ledger loses its footer when a quota resets", "event", "")
            with mock.patch.object(phi, "UPKEEP", False):
                off = upkeep.terminal(self.t.p4, s, "The harbour ledger loses its footer when a quota resets")
                card = upkeep.route(self.t.p4, s, "The harbour ledger loses its footer when a quota resets", "event", "")
        self.assertRegex(on[0], r"^upkeep-[0-9a-f]{8}$")
        self.assertEqual(on[1], os.path.realpath(self.repo).replace("\\", "/"))
        self.assertIn(f"start a worker in the Terminal panel for it, named `{on[0]}`", line)
        self.assertIsNone(off)
        self.assertIn("show it as the app's card", card)
        self.assertNotIn("Terminal", card)

    def test_with_it_off_no_line_names_a_terminal_worker(self):
        self.seat()
        self.left_item()
        self.assertEqual(self.t.cli(TOP, "upkeep", "off").returncode, 0)
        got = self.said()
        self.assertNotIn("Terminal panel", got)
        self.assertNotIn("mcp__terminal__run_in_terminal", got)
        self.assertNotIn("upkeep of the sessions this one started", got)

    def started(self):
        """A terminal worker was handed, and its name."""
        self.seat()
        self.left_item()
        return re.findall(r"named `(upkeep-[0-9a-f]{8})`", self.said())[0]

    def test_a_due_step_whose_worker_has_its_worktree_is_not_handed_to_start_once_more(self):
        """Seen in the desktop app on Claude Code 2.1.326: the first prompt after a terminal worker's start handed
        the due step's start lines again, since the mark that the worker was started is written after the step's
        line is built. A worker whose worktree exists was started, so the line says where the step went."""
        self.seat()
        self.turn_on()
        self.t.cli(TOP, "upkeep", "wait", "Tabulate the quarterly almanac of quince harvests", "--on", KID)
        self.commit()
        self.finish(report="The last row is written now.")
        first = " ".join(self.lines(self.said(), "due:")[0].split())
        name = re.search(r"named `(upkeep-[0-9a-f]{8})`", first).group(1)
        self.assertIn("start a worker in the Terminal panel for it", first)
        self.worker(name, os.getpid())                  # its run made the worktree and holds the lock
        got = self.said()
        again = " ".join(self.lines(got, "due:")[0].split())
        self.assertNotIn("start a worker in the Terminal panel", again)
        self.assertIn(f"it went to the terminal worker `{name}`", again)
        self.assertNotIn("worker-settings.json`, once for all of them", got, "and the form is not said again")

    def test_once_its_run_has_ended_and_its_work_is_landed_its_tab_worktree_and_branch_go(self):
        name = self.started()
        tree = self.worker(name, os.getpid(), change="rows = [1, 2]\n")
        self.assertEqual(self.lines(self.said(), "leftovers of the terminal worker"), [], "its run holds the lock")
        git(self.repo, "worktree", "unlock", tree)
        git(self.repo, "worktree", "lock", "--reason", f"claude session {name} (pid {self.ended()})", tree)
        git(self.repo, "fetch", "-q", "origin")
        left = self.lines(self.said(), "leftovers of the terminal worker")
        self.assertEqual(len(left), 1)
        self.assertIn("`mcp__terminal__stop_terminal_tab` and `close: true`", left[0])
        self.assertIn("`mcp__terminal__list_terminal_tabs`", left[0])
        cmds = re.findall(r"`(git [^`]+)`", left[0])
        self.assertEqual(len(cmds), 3, left[0])
        self.assertRegex(cmds[0], r"^git -C \"[^\"]+\" worktree unlock \"[^\"]+/\.claude/worktrees/" + name + "\"$")
        self.assertRegex(cmds[1], r"^git -C \"[^\"]+\" worktree remove \"[^\"]+/\.claude/worktrees/" + name + "\"$")
        self.assertEqual(cmds[2].split(" ", 3)[3], f"branch -d worktree-{name}")
        self.assertFalse([c for c in cmds if "--force" in c or " -f" in c or " -D" in c])
        for c in cmds:                              # git takes each as it is handed
            r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, c + "\n" + r.stderr)
        self.assertFalse(os.path.isdir(tree))
        self.assertEqual(git(self.repo, "branch", "--list", f"worktree-{name}").stdout.strip(), "")
        self.assertEqual(self.lines(self.said(), "leftovers of the terminal worker"), [], "nothing of it is left")

    def test_one_whose_run_ended_with_work_that_is_not_landed_is_named_once_and_left(self):
        name = self.started()
        self.worker(name, self.ended(), push=False, change="rows = [1, 2]\n")
        got = self.said()
        named = self.lines(got, f"left on disk, of the terminal worker `{name}`")
        self.assertEqual(len(named), 1, got)
        self.assertIn("holds commits that are not on origin/main", named[0])
        self.assertIn(f"report-{name}.md", named[0])
        self.assertNotIn("worktree unlock", got)
        self.assertEqual(self.lines(self.said(), "left on disk, of the terminal worker"), [], "it is named once")

    def test_an_item_handed_to_a_terminal_worker_is_listed_after_with_no_card(self):
        name = self.started()
        again = self.said()
        self.assertNotIn(f"named `{name}`", again, "an item is handed once, and listed as still open after")
        r = self.t.cli(TOP, "upkeep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("own_initiative", r.stdout)


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
