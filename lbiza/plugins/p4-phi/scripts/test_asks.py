#!/usr/bin/env python3
"""asks.py and the routing of a puppeteer's messages, run through p4-phi's own hooks.

The routing reads only a message's own words for work: a path it names is taken out first, so a folder named `land`
or `build` drafts no start.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import asks  # noqa: E402
import inproc  # noqa: E402
import issues  # noqa: E402
import phi  # noqa: E402,F401  sets controls.PHI, which asks.py reads
import puppeteer  # noqa: E402
import relay  # noqa: E402
from test_phi import CLI, KID, TOP, Tree, context, read, write  # noqa: E402

TASK = "Make the narwhal exporter write its ports table to the store"
DRAFT = "its start draft"             # whole beside the prompt, or the opening of the piece held for want of room


class Routing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush port")

    def test_a_folder_named_land_or_build_in_a_path_drafts_no_start(self):                       # ezexe/p4#209
        """A brief whose one work word is a folder named `land` or `build` in a path it names, run through the prompt
        hook, gets no start draft; the same brief with a work word of its own does."""
        t = self.t
        t.say(TOP, TASK)
        for folder in ("land", "build"):
            ctx = context(t.say(TOP, f"Read `src/{folder}/flush.py` under the exporter and say what the table "
                                     f"rows hold there"))
            self.assertNotIn(DRAFT, ctx, folder)
            ctx = context(t.say(TOP, f"Read lib\\{folder}\\rows.py under the exporter and say what the table "
                                     f"rows hold there"))
            self.assertNotIn(DRAFT, ctx, folder + " in a backslash path")
        ctx = context(t.say(TOP, "Rename the retry helper in `src/export/flush.py` for the ports table and update "
                                 "its callers"))
        self.assertIn(DRAFT, ctx, "a work word of the message's own is still read")

    def test_writing_reads_the_words_and_not_the_paths(self):
        self.assertFalse(issues.writing("Read phi.py under E:/work/land/ and say what it holds."))
        self.assertFalse(issues.writing("Say what https://example.com/build/fix holds."))
        self.assertTrue(issues.writing("Fix the flush in `E:/work/copy/phi.py`."))
        self.assertTrue(issues.writing("Add/remove the retry flag on the exporter's flush."),
                        "a slash-joined pair of words is no path")
        self.assertTrue(issues.writing("Port/rename the retry helper of the exporter."))
        self.assertTrue(issues.writing("The `flush` helper: add/remove its retry `flag`."),
                        "a pair of backticks is one span; the words between two spans stay")


PUP, TOP3 = "local_pup00001", "local_top00003"
for k, sid in enumerate((PUP, TOP3)):
    CLI.setdefault(sid, f"7777{k}000-0000-4000-8000-000000000000")
ASK1 = "Add a retry to the narwhal exporter's flush for batches dropped on a timeout"
ASK2 = "Write the importer's parser for quoted rows that span two lines of the input file"
ASK3 = "Publish the exporter's release notes on the releases page once the flush retry is in"
WAIT = "Shall I publish the notes now, or wait for the retry to land first?"


class Trees(unittest.TestCase):
    """A puppeteer `PUP` controls `TOP` and `TOP3`, each of which ended its first turn."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
        t.record(PUP, title="Control the exporter and the importer trees, and tell ezexe where each stands")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(TOP3, title="Build the importer")
        write(os.path.join(t.tmp, "claude_desktop_config.json"), json.dumps(
            {"preferences": {"epitaxyPrefs": {"dframe-group-scopes": {"acct/org": {
                "groups": [{"id": "cg-1", "name": "puppeteers", "mode": "code"}],
                "assignments": {"code:" + PUP: "cg-1"}}}}}}))
        for k, task in ((TOP, "Build the narwhal exporter"), (TOP3, "Build the importer")):
            t.say(k, task)
            t.stop(k, task, report="Started on it.", uuid="s0")
        t.say(PUP, "Control the exporter and the importer trees")
        self.assertEqual(t.cli(PUP, "controls", TOP, TOP3).returncode, 0)

    def send(self, host, to, message):
        """The PreToolUse of a SendMessage, through `recall-hook.sh lookup-check` as hooks.json runs it."""
        t = self.t
        self._n = getattr(self, "_n", 0) + 1
        body = {"session_id": CLI[host], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": "SendMessage",
                "tool_input": {"to": to, "message": message}, "tool_use_id": f"toolu_asks{self._n:04d}"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(host))
        self.assertEqual(r.returncode, 0, r.stderr)




def marked(text, sender="local_other001"):
    """A message the app marks as another session's, as this app gives it."""
    return (f"Another Claude session sent a message:\n<cross-session-message from=\"{sender}\" from-name=\"a session\">"
            f"\n{text}\n</cross-session-message>")


BILLING = "Build a billing dashboard with charts for the monthly invoices of each customer account"
ACCOUNT = "Give me a short account of where the exporter and importer requests stand today"


class Ledger(Trees):
    """ezexe's requests to the puppeteer, a row each, with their holders, states and waits."""

    def page(self):
        return read(asks.page_path(self.t.p4, PUP))

    def test_three_requests_are_three_rows_with_their_holders_and_states_and_the_turn_names_the_page(self):  # 247
        t = self.t
        t.say(PUP, ASK1)
        self.send(PUP, TOP, ASK1 + ", as the exporter's next step.")
        t.stop(PUP, ASK1, report="Sent to the exporter's orchestrator.", uuid="a1")
        t.say(PUP, ASK2)
        self.send(PUP, TOP3, ASK2 + ", as the importer's next step.")
        t.stop(PUP, ASK2, report="Sent to the importer's orchestrator.", uuid="a2")
        t.say(PUP, ASK3)
        t.stop(PUP, ASK3, report="The notes are ready. " + WAIT, uuid="a3")
        ctx = context(t.say(PUP, marked("The importer's parser is in review.")))   # before ezexe answers
        self.assertIn(f"Whole on {asks.page_path(t.p4, PUP)}", ctx, "the turn names the page")
        got = {r["id"]: r for r in asks.rows(t.p4, PUP)}
        self.assertEqual(sorted(got), ["ask-1", "ask-2", "ask-3"], "an account asked for is no request")
        self.assertEqual((got["ask-1"]["holder"], got["ask-2"]["holder"], got["ask-3"]["holder"]), (TOP, TOP3, ""))
        self.assertEqual(got["ask-3"]["waits"], "The notes are ready. " + WAIT)
        self.assertTrue(all(len(r["topic"]) <= asks.TOPIC_CHARS for r in got.values()), "a short topic each")
        text = self.page()
        self.assertIn(f"held by \"Build the narwhal exporter\" `{TOP}` | routed", text)
        self.assertIn(f"held by \"Build the importer\" `{TOP3}` | routed", text)
        self.assertIn(f"held by no session yet | waits on ezexe: The notes are ready. {WAIT}", text)
        self.assertIn("1 waits on ezexe", ctx)
        t.stop(TOP, "Build the narwhal exporter", report="The retry is in and its suite ran green.", uuid="b1")
        t.say(PUP, "Yes, publish the release notes now; the retry can follow in the next release once it lands")
        text = self.page()
        self.assertIn(f"`{TOP}` | reported", text, "the holder's turn since the row was routed")
        self.assertNotIn("waits on ezexe:", text, "a long answer of ezexe's clears the wait too")
        self.assertEqual(len(asks.rows(t.p4, PUP)), 3, "the answer opens no row of its own")

    def test_a_question_or_another_sessions_message_opens_no_row(self):
        t = self.t
        t.say(PUP, "yes")
        t.say(PUP, "Where does the exporter's flush fix stand, and has it landed?")
        t.say(PUP, marked("Landed the flush retry for the narwhal exporter and pushed main"))
        t.say(PUP, "<task-notification>\n<summary>Agent \"Build the retry\" finished</summary>\n</task-notification>")
        self.assertEqual(asks.rows(t.p4, PUP), [])
        self.assertNotIn("ezexe's requests to this puppeteer", context(t.say(PUP, "and now?")))

    def test_a_request_answered_in_its_own_turn_closes_as_answered(self):
        t = self.t
        t.say(PUP, ASK2)
        t.stop(PUP, ASK2, report="The importer's parser already reads quoted rows over two lines, so nothing is "
                                 "needed.", uuid="n1")
        t.say(PUP, ACCOUNT)
        self.assertIn("held by no session yet | answered", self.page())

    def test_a_send_is_credited_by_its_words_and_states_follow_the_holder(self):
        t = self.t
        t.say(PUP, ASK1)
        self.send(PUP, "local_wrk00001", "Check the board and each coworker's context, and report the counts.")
        self.assertEqual(asks.rows(t.p4, PUP)[0]["holder"], "", "a message on no request's topic holds none")
        self.send(PUP, TOP, ASK1 + ", as the exporter's next step.")
        t.stop(PUP, ASK1, report="Sent to the exporter's orchestrator.", uuid="w1")
        t.say(TOP, "Add the retry to the flush")
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP}` | working", self.page(), "mid-turn")
        self.assertEqual(t.cli(TOP, "done", "the retry landed and its suite ran green").returncode, 0)
        t.stop(TOP, "Add the retry to the flush", report="The retry landed; its suite ran green.", uuid="w2")
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP}` | done", self.page())
        t.say(PUP, ASK2)
        self.send(PUP, TOP3, ASK2 + ", as the importer's next step.")
        rec = os.path.join(t.app, TOP3 + ".json")
        d = json.loads(read(rec))
        d["isArchived"] = True
        write(rec, json.dumps(d))
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP3}` | closed", self.page())

    def test_an_orchestrator_started_for_a_request_holds_it(self):
        t = self.t
        new = "local_new00009"
        CLI.setdefault(new, "77779000-0000-4000-8000-000000000000")
        t.say(PUP, BILLING)
        t.record(new, title="Billing dashboard with monthly invoice charts")
        t.say(new, BILLING)
        self.assertEqual(t.cli(PUP, "controls", new).returncode, 0)
        t.stop(PUP, BILLING, report="Started the billing dashboard's orchestrator.", uuid="o1")
        t.say(PUP, ACCOUNT)
        got = asks.rows(t.p4, PUP)
        self.assertEqual((got[0]["holder"], got[0]["how"]), (new, "started"))


class PuppeteerRouting(Trees):
    """A puppeteer's message is ezexe's unless the app marks it as another session's; only route_down sends one on."""

    def test_the_puppeteers_closing_report_and_its_go_to_a_controlled_session_draw_no_start_draft(self):  # 247
        t = self.t
        for text in ("Landed the flush retry for the narwhal exporter and pushed main; the importer's quote parser "
                     "is next.", f"Go: `{TOP}` can now build the retry writer for the flush batches and land it",
                     "Relay to \"Build the importer\": add the quote handling to the parser of the input rows"):
            self.assertNotIn(DRAFT, context(t.say(PUP, marked(text))), text)
        self.assertEqual(asks.rows(t.p4, PUP), [], "no row for another session's message")
        self.assertIn(DRAFT, context(t.say(PUP, BILLING)), "a new topic of ezexe's is drafted")

    def test_ezexes_own_words_never_cost_a_request_its_draft(self):
        t = self.t
        self.assertIn(DRAFT, context(t.say(PUP, "Go ahead and build a billing dashboard for the monthly invoices of "
                                                "each customer account")), "a request opening with go ahead")
        t.stop(PUP, "Control the trees", report="Shall I build the payroll export with a monthly summary for each "
                                               "employee record?", uuid="e1")
        self.assertIn(DRAFT, context(t.say(PUP, "Build the payroll export with a monthly summary for each employee "
                                                "record")), "ezexe taking the puppeteer's offer")

    def test_a_message_route_down_sends_to_a_controlled_topic_draws_no_start_draft(self):              # 230
        ctx = context(self.t.say(PUP, "Write a page about the narwhal exporter's ports table and its rows"))
        self.assertIn("reads as work on the topic \"Build the narwhal exporter\"", ctx)
        self.assertNotIn(DRAFT, ctx)


class RoutingMarks(Trees):
    """The app's marks are read at the start of a message's body, past its leading reminders, and nowhere else."""

    def test_a_controlled_orchestrator_handed_work_by_another_session_still_gets_its_draft(self):
        t = self.t
        ctx = context(t.say(TOP, marked("Rename the retry helper in `src/export/flush.py` for the ports table and "
                                        "update its callers across the exporter", sender=PUP)))
        self.assertIn(DRAFT, ctx, "the marks hold back only a puppeteer's routing")

    def test_a_slash_commands_wrapper_is_no_message_of_ezexes(self):
        t = self.t
        for tag in ("command-name", "command-message", "local-command-stdout"):
            said = f"<{tag}>/compact</{tag}>\n" + BILLING
            self.assertTrue(puppeteer.from_session(said), tag)
            t.say(PUP, said)
        self.assertEqual(asks.rows(t.p4, PUP), [])

    def test_a_paste_holding_a_session_tag_is_still_ezexes(self):
        t = self.t
        ctx = context(t.say(PUP, BILLING + ". The other session wrote:\n<cross-session-message from=\"local_x\">"
                                           "Landed.</cross-session-message>\nStop hook blocking error: none"))
        self.assertIn(DRAFT, ctx)
        self.assertEqual(len(asks.rows(t.p4, PUP)), 1)

    def test_a_marked_message_behind_long_reminders_is_another_sessions(self):
        t = self.t
        long = "<system-reminder>\n" + "background " * 600 + "\n</system-reminder>\n"
        self.assertNotIn(DRAFT, context(t.say(PUP, long + marked(BILLING))))
        self.assertEqual(asks.rows(t.p4, PUP), [])


class LedgerCloses(Trees):
    """Every row closes: done for good, closed for good, answered or carried, and a send or a start with no shared
    word still holds the row its turn works on."""

    def page(self):
        return read(asks.page_path(self.t.p4, PUP))

    def test_a_done_row_stays_done_after_its_holders_next_turn(self):
        t = self.t
        t.say(PUP, ASK1)
        self.send(PUP, TOP, ASK1 + ", as the exporter's next step.")
        t.stop(PUP, ASK1, report="Sent to the exporter's orchestrator.", uuid="d1")
        t.say(TOP, "Add the retry to the flush")
        self.assertEqual(t.cli(TOP, "done", "the retry landed and its suite ran green").returncode, 0)
        t.stop(TOP, "Add the retry to the flush", report="The retry landed.", uuid="d2")
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP}` | done", self.page())
        t.say(TOP, "Now the batch size")
        t.stop(TOP, "Now the batch size", report="Looking at the batch size.", uuid="d3")
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP}` | done", self.page(), "done is kept on the row")

    def test_a_turn_that_never_ended_leaves_its_row_carried(self):
        t = self.t
        t.say(PUP, ASK2)
        t.say(PUP, ACCOUNT)                        # ezexe moved on before the turn on ask-1 ended
        self.assertIn("held by no session yet | carried", self.page())

    def test_a_holder_archived_in_the_app_closes_its_row_for_good(self):
        t = self.t
        t.say(PUP, ASK2)
        self.send(PUP, TOP3, ASK2 + ", as the importer's next step.")
        t.stop(PUP, ASK2, report="Sent to the importer's orchestrator.", uuid="c1")
        rec = os.path.join(t.app, TOP3 + ".json")
        d = json.loads(read(rec))
        write(rec, json.dumps(dict(d, isArchived=True)))
        t.say(PUP, ACCOUNT)
        self.assertEqual(asks.rows(t.p4, PUP)[0]["end"], "closed", "kept on the row")
        write(rec, json.dumps(d))
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP3}` | closed", self.page(), "closed for good")

    def test_a_holder_that_left_the_book_after_a_done_turn_is_done(self):
        t = self.t
        t.say(PUP, ASK1)
        self.send(PUP, TOP, ASK1 + ", as the exporter's next step.")
        t.stop(PUP, ASK1, report="Sent to the exporter's orchestrator.", uuid="r1")
        t.say(TOP, "Add the retry to the flush")
        self.assertEqual(t.cli(TOP, "done", "the retry landed and its suite ran green").returncode, 0)
        t.stop(TOP, "Add the retry to the flush", report="The retry landed.", uuid="r2")
        s = t.session(TOP)
        relay._write_json(os.path.join(t.dir(TOP), "session.json"), dict(s, doneRetired=True))
        t.say(PUP, ACCOUNT)
        self.assertIn(f"`{TOP}` | done", self.page(), "its done turn, not its leaving, says what became of it")

    def test_an_unmatched_send_or_a_late_start_still_holds_its_row(self):
        t = self.t
        t.say(PUP, ASK2)
        self.send(PUP, TOP3, "Over to you for the next step.")
        self.assertEqual(asks.rows(t.p4, PUP)[0]["holder"], TOP3, "a send to a controlled session holds its row")
        t.stop(PUP, ASK2, report="Sent on.", uuid="u1")
        new = "local_new00008"
        CLI.setdefault(new, "77778000-0000-4000-8000-000000000000")
        t.say(PUP, BILLING)
        t.record(new, title="Ledger of invoices")
        t.say(new, "Lay out the ledger")
        self.assertEqual(t.cli(PUP, "controls", new).returncode, 0)
        t.stop(PUP, BILLING, report="Started its orchestrator.", uuid="u2")
        t.say(PUP, ACCOUNT)
        got = {r["id"]: r for r in asks.rows(t.p4, PUP)}
        self.assertEqual((got["ask-2"]["holder"], got["ask-2"]["how"]), (new, "started"), "a start with no shared word")


class LedgerWaits(Trees):
    """A request is never lost to a row that waits on ezexe, and an answer is never taken for a request."""

    def test_a_new_request_while_a_row_waits_opens_its_own_row(self):
        t = self.t
        t.say(PUP, ASK3)
        t.stop(PUP, ASK3, report="The notes are ready. " + WAIT, uuid="q1")
        t.say(PUP, BILLING)
        got = {r["id"]: r for r in asks.rows(t.p4, PUP)}
        self.assertEqual(sorted(got), ["ask-1", "ask-2"])
        self.assertEqual(got["ask-1"]["waits"], "The notes are ready. " + WAIT, "the wait is not answered")
        self.assertEqual(got["ask-1"]["end"], "")

    def test_a_quick_answer_while_a_row_waits_answers_it_and_opens_none(self):
        t = self.t
        t.say(PUP, ASK3)
        t.stop(PUP, ASK3, report="The notes are ready. " + WAIT, uuid="k1")
        t.say(PUP, "yes, push it")
        got = asks.rows(t.p4, PUP)
        self.assertEqual(len(got), 1, "a quick answer is no request")
        self.assertEqual(got[0]["waits"], "", "it answers the row that waits")

    def test_a_status_question_opens_no_row(self):
        t = self.t
        t.say(PUP, "Did the exporter's flush retry land and get pushed to main this morning?")
        t.say(PUP, "Has the importer's release gone out to the store yet?")
        self.assertEqual(asks.rows(t.p4, PUP), [])

    def test_short_and_question_form_requests_open_rows(self):
        t = self.t
        t.say(PUP, "Push main and sync the stores")
        t.say(PUP, "Can you add a retry to the importer's quote parser?")
        self.assertEqual(len(asks.rows(t.p4, PUP)), 2)

    def test_a_request_repeated_on_another_day_is_a_row_of_its_own(self):
        from unittest import mock
        with mock.patch.object(asks.time, "strftime", return_value="2026-11-17"):
            one = asks._key(ASK1)
        with mock.patch.object(asks.time, "strftime", return_value="2026-11-18"):
            two = asks._key(ASK1)
        self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
