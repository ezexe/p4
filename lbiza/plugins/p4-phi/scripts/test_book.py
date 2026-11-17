#!/usr/bin/env python3
"""book.py: the address book every session is handed, and the recipient named before a message is sent, run through
p4-phi's own hooks.

A puppeteer controls an orchestrator, whose workers each declare a `Files:` line. Each session is handed the live
sessions by full title and id with what each holds, the puppeteer as the address for a decision of ezexe's and its
parent for work off its task, kept whole on book.md; a later message is handed only the entries that changed. A
message naming a file or an issue another live session holds, sent elsewhere, is held once with that session named,
and so is a message to the puppeteer that names no matter of ezexe's; a finding on a held file goes to its holder.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import book  # noqa: E402
import inproc  # noqa: E402
import phi  # noqa: E402
import relay  # noqa: E402
from test_phi import CLI, KID, KID2, TOP, Tree, context, read, write  # noqa: E402

PUP, TOP3, KID3 = "local_pup00001", "local_top00003", "local_kid00003"
for k, sid in enumerate((PUP, TOP3, KID3)):
    CLI.setdefault(sid, f"8888{k}000-0000-4000-8000-000000000000")
SEND = "SendMessage"
FINDING = ("Finding: src/flush.py drops the last batch on retry; source: src/flush.py:40; test: test_flush; files: "
           "src/flush.py")


class Supervisor(unittest.TestCase):
    """A puppeteer `PUP` controls `TOP`; `KID` under `TOP` declares `Files: src/flush.py`; `KID2` under `TOP`
    declares `Files: none`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = t = Tree(self._tmp.name)
        t.record(PUP, title="Control the exporter and the importer trees, and tell ezexe where each stands")
        t.record(TOP, title="Build the narwhal exporter")
        t.record(TOP3, title="An orchestrator nobody put under the puppeteer")
        t.record(KID, started_by=TOP, title="the flush child")
        t.record(KID2, started_by=TOP, title="the retry check")
        self.file("puppeteers", PUP)

    def tearDown(self):
        self._tmp.cleanup()

    def file(self, section, *sids):
        """The app's own file: `sids` filed in one sidebar section."""
        write(os.path.join(self.t.tmp, "claude_desktop_config.json"), json.dumps(
            {"preferences": {"epitaxyPrefs": {"dframe-group-scopes": {"acct/org": {
                "groups": [{"id": "cg-1", "name": section, "mode": "code"}],
                "assignments": {"code:" + s: "cg-1" for s in sids}}}}}}))

    def tree(self, standing="1"):
        """The puppeteer over TOP, KID holding src/flush.py, and KID2's first message, whose context is returned."""
        t = self.t
        t.say(TOP, "Build the narwhal exporter")
        t.say(PUP, "Control the trees")
        self.assertEqual(t.cli(PUP, "controls", TOP).returncode, 0)
        t.say(KID, "Task:\nBuild the flush's batching.\nFiles: src/flush.py")
        return context(t.say(KID2, "Task:\nCheck the flush's retry and report.\nFiles: none",
                             P4_PHI_NEW_TASK=standing))

    def pre(self, host, tool, inp):
        """One PreToolUse call through `recall-hook.sh lookup-check`, as hooks.json runs it: the reason or the
        context it hands, '' for none, and the decision."""
        t = self.t
        self._pre = getattr(self, "_pre", 0) + 1
        body = {"session_id": CLI[host], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": f"toolu_book{self._pre:04d}"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-check"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60, env=t.env(host))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
        return (out.get("permissionDecisionReason", "") + out.get("additionalContext", ""),
                out.get("permissionDecision", ""))

    # --- the deciding test of ezexe/p4#245 ---------------------------------------------------------------------------

    def test_a_finding_on_a_file_another_live_worker_holds_names_that_worker_and_its_message_to_the_puppeteer_is_flagged(self):  # noqa: E501
        first = self.tree()
        self.assertIn(KID, first, "KID2 is told KID's id")
        self.assertIn("flush.py", first, "beside the file KID holds")
        self.assertIn(f"to the puppeteer \"Control the exporter and the importer trees, and tell ezexe where each "
                      f"stands\" `{PUP}`", first, "the puppeteer, by full title and id, as the address for a "
                                                  "decision of ezexe's")
        self.assertIn("decision of ezexe's", first)
        said, decision = self.pre(KID2, SEND, {"to": PUP, "message": FINDING})
        self.assertIn(KID, said, "the flag names the worker that holds the file")
        self.assertEqual(decision, "deny", "held before it is sent")
        self.assertEqual(self.pre(KID2, SEND, {"to": KID, "message": FINDING}), ("", ""), "to the holder, it goes")
        self.assertEqual(self.pre(KID2, SEND, {"to": PUP, "message": "ezexe's go is needed for a push of the batch "
                                                                    "fix to main"}), ("", ""),
                         "a matter of ezexe's goes to the puppeteer unflagged")

    # --- the book --------------------------------------------------------------------------------------------------

    def test_the_page_holds_each_live_session_with_its_role_parent_files_issue_and_workers(self):
        t = self.t
        self.tree()
        s = t.session(KID)
        s["issue"] = {"repo": "ezexe/p4", "number": 245, "url": "https://github.com/ezexe/p4/issues/245"}
        relay._write_json(os.path.join(t.dir(KID), "session.json"), s)
        t.say(KID2, "and now?", P4_PHI_NEW_TASK="1")
        page = read(book.page_path(t.p4, KID2))
        self.assertIn(f"\"the flush child\" `{KID}`, worker under `{TOP}`: files src/flush.py; issue ezexe/p4#245",
                      page)
        self.assertIn(f"\"Build the narwhal exporter\" `{TOP}`, orchestrator: workers `{KID}`, `{KID2}`", page)
        self.assertIn(f"`{PUP}`, puppeteer", page)
        self.assertIn(f"work off this session's task goes to its parent \"Build the narwhal exporter\" `{TOP}`", page)
        self.assertIn(f"\"the retry check\" `{KID2}`", page.split("## This session")[1])

    def test_a_later_message_is_handed_only_the_entries_that_changed_and_the_page(self):
        t = self.t
        self.tree()
        again = context(t.say(KID2, "carry on", P4_PHI_NEW_TASK="1"))
        self.assertNotIn("address book", again, "nothing changed: nothing said")
        t.record(KID3, started_by=TOP, title="the writer child")
        t.say(KID3, "Task:\nBuild the writer.\nFiles: src/writer.py")
        changed = context(t.say(KID2, "and now?", P4_PHI_NEW_TASK="1"))
        self.assertIn(f"the address book on {book.page_path(t.p4, KID2)} changed", changed)
        self.assertIn(f"`{KID3}`", changed)
        self.assertIn("writer.py", changed)
        self.assertNotIn("flush.py", changed, "an entry that did not change is not handed again")

    def test_a_session_that_left_is_named_as_no_longer_live(self):
        t = self.t
        self.tree()
        rec = os.path.join(t.app, KID + ".json")
        d = json.loads(read(rec))
        d["isArchived"] = True
        write(rec, json.dumps(d))
        changed = context(t.say(KID2, "and now?", P4_PHI_NEW_TASK="1"))
        self.assertIn(f"no longer live: `{KID}`", changed)
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP3, "message": FINDING}), ("", ""),
                         "an archived session holds nothing")

    def test_a_flag_is_said_once_for_one_message_and_target(self):
        self.tree()
        self.t.say(TOP3, "Build the importer")
        self.assertIn(KID, self.pre(KID2, SEND, {"to": TOP3, "message": FINDING})[0])
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP3, "message": FINDING}), ("", ""), "the resend goes")
        self.assertIn(KID, self.pre(KID2, SEND, {"to": PUP, "message": FINDING})[0], "another target is flagged")

    def test_the_holders_starter_is_an_address_for_its_files(self):
        self.tree()
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP, "message": FINDING}), ("", ""))

    def test_a_message_naming_an_issue_another_session_owns_is_flagged(self):
        t = self.t
        self.tree()
        t.say(TOP3, "Build the importer")
        s = t.session(KID)
        s["issue"] = {"repo": "ezexe/p4", "number": 245}
        relay._write_json(os.path.join(t.dir(KID), "session.json"), s)
        said, decision = self.pre(KID2, SEND, {"to": TOP3, "message": "Is ezexe/p4#245 still waiting on its test?"})
        self.assertEqual(decision, "deny")
        self.assertIn(f"names ezexe/p4#245, which \"the flush child\" `{KID}` holds", said)
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP3, "message": "Is ezexe/p4#999 done?"}), ("", ""),
                         "an issue no live session owns is nobody's")

    def test_a_message_to_the_puppeteer_naming_no_matter_of_ezexes_names_the_parent(self):
        self.tree()
        said, decision = self.pre(KID2, SEND, {"to": PUP, "message": "How far along is the exporter's flush?"})
        self.assertEqual(decision, "deny")
        self.assertIn("not the puppeteer", said)
        self.assertIn(f"its parent \"Build the narwhal exporter\" `{TOP}`", said)

    def test_a_target_the_book_cannot_find_and_a_session_with_no_puppeteer_send_freely(self):
        t = self.t
        self.tree()
        self.assertEqual(self.pre(KID2, SEND, {"to": "fb-archive-guard", "message": FINDING}), ("", ""))
        t.say(TOP3, "Build the importer")
        self.assertEqual(self.pre(TOP3, SEND, {"to": TOP, "message": "How far along is the exporter?"}), ("", ""))

    def test_a_finding_on_a_held_file_is_named_to_its_holder_under_the_parents_reports(self):
        t = self.t
        self.tree()
        t.stop(KID2, "Check the flush's retry and report.", report=f"Checked.\n{FINDING}")
        ctx = context(t.say(TOP, "what came in?"))
        self.assertIn("Send each one straight to the session named under it", ctx)
        self.assertIn(f"to \"the flush child\" `{KID}`, which holds src/flush.py", ctx)
        self.assertNotIn("go up to the puppeteer", ctx, "a held finding goes up for no issue")

    def test_issues_named_reads_slugs_bare_numbers_and_links_and_no_path_or_anchor(self):
        self.assertEqual(book.issues_named("ezexe/p4#245 and #236, https://github.com/ezexe/phi/issues/12 and "
                                           "[a](#local_x) and C#"), [("ezexe/phi", 12), ("ezexe/p4", 245), ("", 236)])


if __name__ == "__main__":
    unittest.main()
