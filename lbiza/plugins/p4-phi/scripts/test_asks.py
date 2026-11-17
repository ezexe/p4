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
from test_phi import CLI, KID, TOP, Tree, context, read, write  # noqa: E402

TASK = "Make the narwhal exporter write its ports table to the store"
DRAFT = "its start draft is"


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


class Ledger(Trees):
    """ezexe sends the puppeteer three requests: the first it routes to `TOP`, the second to `TOP3`, and the third it
    asks ezexe about."""

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
        ctx = context(t.say(PUP, "Give me a short account of where the exporter and importer requests stand today"))
        page = asks.page_path(t.p4, PUP)
        self.assertIn(f"Whole on {page}", ctx, "the turn names the page")
        got = {r["id"]: r for r in asks.rows(t.p4, PUP)}
        self.assertEqual(sorted(got), ["ask-1", "ask-2", "ask-3"], "a status question is no request")
        self.assertEqual((got["ask-1"]["holder"], got["ask-2"]["holder"], got["ask-3"]["holder"]), (TOP, TOP3, ""))
        self.assertEqual(got["ask-3"]["waits"], "The notes are ready. " + WAIT)
        text = read(page)
        self.assertIn(f"ask-1, ", text)
        self.assertIn(f"held by \"Build the narwhal exporter\" `{TOP}` | routed", text)
        self.assertIn(f"held by \"Build the importer\" `{TOP3}` | routed", text)
        self.assertIn(f"held by no session yet | waits on ezexe: The notes are ready. {WAIT}", text)
        self.assertIn("1 waits on ezexe", ctx)
        t.stop(TOP, "Build the narwhal exporter", report="The retry is in and its suite ran green.", uuid="b1")
        context(t.say(PUP, "Go ahead and publish the notes"))
        text = read(page)
        self.assertIn(f"`{TOP}` | reported", text, "the holder's turn since the row was routed")
        self.assertNotIn("waits on ezexe:", text, "ezexe's answer clears the wait")

    def test_a_quick_message_or_a_status_question_opens_no_row(self):
        t = self.t
        t.say(PUP, "yes")
        t.say(PUP, "How are the exporter and importer coming along at the moment overall")
        self.assertEqual(asks.rows(t.p4, PUP), [])
        self.assertNotIn("ezexe's requests to this puppeteer", context(t.say(PUP, "and now?")))


CLOSING = ("Landed the flush retry for the narwhal exporter and pushed main; the importer's quote parser is next in "
           "its queue, and nothing waits on ezexe.")


class PuppeteerRouting(Trees):
    """The puppeteer's own wrap-up and orchestration are read as such, never as a request for a new orchestrator."""

    def test_the_puppeteers_closing_report_and_its_go_to_a_controlled_session_draw_no_start_draft(self):  # 247
        t = self.t
        t.stop(PUP, "Control the exporter and the importer trees", report=CLOSING, uuid="c1")
        self.assertNotIn(DRAFT, context(t.say(PUP, CLOSING)), "its own closing report, come back")
        self.assertNotIn(DRAFT, context(t.say(PUP, f"Go: `{TOP}` can now build the retry writer for the flush "
                                                   f"batches and land it")), "a go to a controlled session")
        self.assertNotIn(DRAFT, context(t.say(PUP, "Relay to \"Build the importer\": add the quote handling to "
                                                   "the parser of the input rows")), "a relay to a controlled session")
        self.assertIn(DRAFT, context(t.say(PUP, "Build a billing dashboard with charts for the monthly invoices of "
                                                "each customer account")), "a new topic is still drafted")

    def test_a_message_route_down_sends_to_a_controlled_topic_draws_no_start_draft(self):              # 230
        ctx = context(self.t.say(PUP, "Write a page about the narwhal exporter's ports table and its rows"))
        self.assertIn("reads as work on the topic \"Build the narwhal exporter\"", ctx)
        self.assertNotIn(DRAFT, ctx)


if __name__ == "__main__":
    unittest.main()
