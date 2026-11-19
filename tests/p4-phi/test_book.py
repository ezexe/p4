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

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "lbiza", "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
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

    def tree(self, handed="1"):
        """The puppeteer over TOP, KID holding src/flush.py, and KID2's first message, whose context is returned."""
        t = self.t
        t.say(TOP, "Build the narwhal exporter")
        t.say(PUP, "Control the trees")
        self.assertEqual(t.cli(PUP, "controls", TOP).returncode, 0)
        t.say(KID, "Task:\nBuild the flush's batching.\nFiles: src/flush.py")
        return context(t.say(KID2, "Task:\nCheck the flush's retry and report.\nFiles: none",
                             P4_PHI_BOOK=handed))

    def pre(self, host, tool, inp):
        """One PreToolUse call through `recall-hook.sh lookup-check`, as hooks.json runs it: the reason or the
        context it hands, '' for none, and the decision."""
        t = self.t
        self._pre = getattr(self, "_pre", 0) + 1
        body = {"session_id": CLI[host], "cwd": t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": inp, "tool_use_id": f"toolu_book{self._pre:04d}"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), "lookup-check"],
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
        t.say(KID2, "and now?", P4_PHI_BOOK="1")
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
        again = context(t.say(KID2, "carry on", P4_PHI_BOOK="1"))
        self.assertNotIn("address book", again, "nothing changed: nothing said")
        t.record(KID3, started_by=TOP, title="the writer child")
        t.say(KID3, "Task:\nBuild the writer.\nFiles: src/writer.py")
        changed = context(t.say(KID2, "and now?", P4_PHI_BOOK="1"))
        self.assertIn(f"the address book on {book.page_path(t.p4, KID2)} changed", changed)
        self.assertIn(f"`{KID3}`", changed)
        self.assertIn("writer.py", changed)
        self.assertNotIn("flush.py", changed, "an entry that did not change is not handed again")

    def test_a_session_that_left_is_named_as_no_longer_live(self):
        t = self.t
        self.tree()
        t.say(TOP3, "Build the importer")
        self.assertIn(KID, self.pre(KID2, SEND, {"to": TOP3, "message": "Is src/flush.py ready?"})[0],
                      "held while KID is live")
        rec = os.path.join(t.app, KID + ".json")
        d = json.loads(read(rec))
        d["isArchived"] = True
        write(rec, json.dumps(d))
        changed = context(t.say(KID2, "and now?", P4_PHI_BOOK="1"))
        self.assertIn(f"no longer live: `{KID}`", changed)
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP3, "message": FINDING}), ("", ""),
                         "an archived session holds nothing")

    def test_a_finding_naming_its_issue_by_slug_to_the_puppeteer_is_still_held(self):
        t = self.t
        self.tree()
        s = t.session(KID)
        s["issue"] = {"repo": "ezexe/p4", "number": 245}
        relay._write_json(os.path.join(t.dir(KID), "session.json"), s)
        said, decision = self.pre(KID2, SEND, {"to": PUP, "message": "Finding: ezexe/p4#245 src/flush.py drops the "
                                                                    "last batch; source: https://github.com/ezexe/p4"
                                                                    "/issues/245; files: src/flush.py"})
        self.assertEqual(decision, "deny", "a repository name or a link is no matter of ezexe's")
        self.assertIn(KID, said)

    def test_an_untitled_session_is_named_by_its_id_and_never_by_its_brief(self):
        t = self.t
        self.tree()
        t.record(KID3, started_by=TOP, title="")
        d = json.loads(read(os.path.join(t.app, KID3 + ".json")))
        d.pop("title", None)
        write(os.path.join(t.app, KID3 + ".json"), json.dumps(d))
        t.say(KID3, "Task:\nPort the secret writer of the narwhal exporter.\nFiles: src/writer.py")
        t.say(KID2, "and now?", P4_PHI_BOOK="1")
        page = read(book.page_path(t.p4, KID2))
        self.assertIn(f"\"{KID3}\" `{KID3}`", page)
        self.assertNotIn("secret writer", page)

    def test_a_brief_naming_a_siblings_file_is_not_routed_away(self):
        t = self.t
        self.tree()
        t.record(KID3, started_by=TOP, title="the flush reviewer")
        first = context(t.say(KID3, "Task:\nReview src/flush.py and report what it drops.\nFiles: none"))
        self.assertNotIn("Send it there", first, "a worker's brief is its own work, not a message to route")

    def test_a_controlled_tree_in_another_store_is_in_the_book(self):
        t = self.t
        other = os.path.join(t.tmp, "other")
        os.makedirs(os.path.join(other, ".claude", "p4"))
        TOP2, KID4 = "local_top00002", "local_kid00004"
        CLI.setdefault(TOP2, "66660000-0000-4000-8000-000000000000")
        CLI.setdefault(KID4, "66661000-0000-4000-8000-000000000000")
        t.record(TOP2, title="Build the importer elsewhere", cwd=other)
        t.record(KID4, started_by=TOP2, title="the parser child", cwd=other)
        t.say(TOP2, "Build the importer", proj=other)
        t.say(KID4, "Task:\nBuild the quote parser.\nFiles: src/parse.py", proj=other)
        self.tree()
        self.assertEqual(t.cli(PUP, "controls", TOP, TOP2).returncode, 0)
        t.say(KID2, "and now?", P4_PHI_BOOK="1")
        page = read(book.page_path(t.p4, KID2))
        self.assertIn(f"\"the parser child\" `{KID4}`, worker under `{TOP2}`: files src/parse.py", page)

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

    def test_a_session_speaks_for_its_own_workers_and_a_holder_among_several_takes_the_message(self):
        t = self.t
        self.tree()
        t.say(TOP3, "Build the importer")
        self.assertEqual(self.pre(TOP, SEND, {"to": TOP3, "message": "My worker is changing src/flush.py, so hold "
                                                                    "off on it."}), ("", ""),
                         "an orchestrator's message about its own worker's file is its own")
        t.record(KID3, started_by=TOP3, title="the writer child")
        t.say(KID3, "Task:\nBuild the writer.\nFiles: src/writer.py")
        self.assertEqual(self.pre(KID2, SEND, {"to": KID3, "message": "src/flush.py now calls src/writer.py, "
                                                                     "whose rows it reads."}), ("", ""),
                         "the target holds one of the files the message names")

    def test_an_issue_the_senders_tree_shares_and_an_outcome_for_the_puppeteer_go(self):
        t = self.t
        self.tree()
        t.say(TOP3, "Build the importer")
        for k in (KID, KID2):
            s = t.session(k)
            s["issue"] = {"repo": "ezexe/p4", "number": 245}
            relay._write_json(os.path.join(t.dir(k), "session.json"), s)
        self.assertEqual(self.pre(KID2, SEND, {"to": TOP3, "message": "ezexe/p4#245 step 3 is green."}), ("", ""),
                         "the sender's own issue is its tree's")
        self.assertEqual(self.pre(TOP, SEND, {"to": PUP, "message": "The flush batching is done and its suite "
                                                                   "ran green."}), ("", ""),
                         "an outcome ezexe should hear goes to the puppeteer")

    def test_a_path_from_inside_the_repository_finds_its_holder(self):
        t = self.t
        self.tree()
        t.say(TOP3, "Build the importer")
        said, decision = self.pre(KID2, SEND, {"to": TOP3, "message": "Does flush/../src/flush.py still drop rows? "
                                                                     "I mean `src/flush.py` as the batch sees it."})
        self.assertIn(KID, said)
        t.record(KID3, started_by=TOP, title="the export child")
        t.say(KID3, "Task:\nBuild the export flush.\nFiles: src/export/flush.py")
        said, _ = self.pre(KID2, SEND, {"to": TOP3, "message": "Is export/flush.py still dropping its last batch?"})
        self.assertIn(KID3, said, "a path from deeper in the repository names the same file")

    def test_a_decision_of_ezexes_goes_to_the_puppeteer_though_it_names_a_held_file(self):
        self.tree()
        self.assertEqual(self.pre(KID2, SEND, {"to": PUP, "message": "ezexe must approve deleting src/flush.py "
                                                                   "before the batch work goes on."}), ("", ""))

    def test_a_finding_on_the_trees_own_issue_stays_with_the_tree(self):
        t = self.t
        self.tree()
        t.record(KID3, started_by=TOP, title="the export child")
        t.say(KID3, "Task:\nBuild the export flush.\nFiles: none")
        for k in (KID, KID2, KID3):
            s = t.session(k)
            s["issue"] = {"repo": "ezexe/p4", "number": 245}
            relay._write_json(os.path.join(t.dir(k), "session.json"), s)
        t.stop(KID2, "Check the flush's retry and report.",
               report="Checked.\nFinding: ezexe/p4#245 misses the retry of the second batch; source: its brief; "
                      "test: test_flush; files: none")
        ctx = context(t.say(TOP, "what came in?"))
        self.assertIn("on the issue this session's tree already holds", ctx)
        self.assertNotIn("go up to the puppeteer", ctx, "the tree's own issue is no new issue")

    def test_the_books_text_never_goes_into_the_log(self):
        t = self.t
        self.tree()
        for source in ("compact", "clear"):          # a start after which the standing instruction is handed again
            r = t.hook("session-start", KID2, {"hook_event_name": "SessionStart", "source": source},
                       P4_PHI_BOOK="1")
            self.assertEqual(r.returncode, 0, r.stderr)
        t.say(KID2, "and now?", P4_PHI_BOOK="1")
        rows = read(os.path.join(t.dir(KID2), "log.jsonl"))
        self.assertIn("session-start", rows, "the starts ran and were logged")
        self.assertNotIn("address book", rows)
        self.assertNotIn("book_line", rows)

    def test_a_clear_hands_the_book_whole_and_a_compaction_only_what_changed_with_the_page(self):
        """https://code.claude.com/docs/en/context-window.md, "What survives compaction", row "Context that hooks
        added earlier": "Summarized with the rest of the conversation". So after a compaction the book the session
        was handed is in the summary: the start hands only the entries that changed since it last looked, with the
        path of book.md, since a summary keeps no exact id or path. A clear keeps nothing, so the book comes
        whole."""
        t = self.t
        self.tree()                                  # KID2's first look: the book whole

        def start(source):
            r = t.hook("session-start", KID2, {"hook_event_name": "SessionStart", "source": source},
                       P4_PHI_BOOK="1")
            return context(r).rsplit("\n\nphi (p4-phi): ", 1)[-1]        # the book comes last

        page = book.page_path(t.p4, KID2)
        same = start("compact")
        self.assertTrue(same.startswith(f"this session's address book, unchanged since it last looked, is whole on "
                                        f"{page}"), same[:300])
        self.assertNotIn(f"`{KID}`", same, "an entry that did not change is not handed again")
        self.assertNotIn("flush.py", same)
        self.assertEqual(t.cli(KID, "shard", "src/batch.py").returncode, 0)     # its owned paths: the entry changes
        changed = start("compact")
        self.assertTrue(changed.startswith(f"the address book on {page} changed since this session last looked:"),
                        changed[:300])
        self.assertIn(f"`{KID}`", changed)
        self.assertIn("batch.py", changed)
        self.assertEqual(changed.count("\n- "), 1, "only the entry that changed")
        whole = start("clear")                      # the session keeps none of the entries it was handed
        self.assertTrue(whole.startswith("this session's address book, whole"), whole[:300])
        self.assertIn(f"`{KID}`", whole)
        self.assertIn("flush.py", whole)
        self.assertNotIn("unchanged since it last looked", whole)
        self.assertGreater(whole.count("\n- "), 1)

    def test_a_repository_name_or_a_finding_never_passes_for_a_matter_of_ezexes(self):
        t = self.t
        self.tree()
        said, decision = self.pre(KID2, SEND, {"to": PUP, "message": "The flush in ezexe/p4 drops rows on retry."})
        self.assertEqual(decision, "deny", "a repository's name is no matter of ezexe's")
        said, decision = self.pre(KID2, SEND, {"to": PUP, "message": "Finding: the permission check in src/flush.py "
                                                                    "skips the second batch; files: src/flush.py"})
        self.assertEqual(decision, "deny")
        self.assertIn(KID, said, "a finding goes to the holder of its file, whatever words it holds")
        self.assertFalse(book.decides("Read approvals.py, release.py and merge.py for the batch rules"))

    def test_a_path_in_another_repository_names_another_file(self):
        t = self.t
        repo_a, repo_b = os.path.join(t.tmp, "repo-a"), os.path.join(t.tmp, "repo-b")
        for r in (repo_a, repo_b):
            os.makedirs(os.path.join(r, ".git"))
        t.record(KID3, started_by=TOP, title="the other flush", cwd=repo_a)
        t.say(KID3, "Task:\nPort the flush.\nFiles: src/flush.py", proj=repo_a)
        t.record(KID2, started_by=TOP, title="the retry check", cwd=repo_b)
        self.tree()
        t.say(TOP3, "Build the importer")
        said, _ = self.pre(KID2, SEND, {"to": TOP3, "message": "Does vendor/src/flush.py drop rows?"})
        self.assertNotIn(KID3, said, "a longer path is not the held one")
        self.assertNotIn(KID3, book.holder_line(t.p4, t.session(KID2), "src/flush.py drops rows", "", ()) or "",
                         "the same path in another repository is another file")

    def worktree(self, repo, folder, name):
        """A linked worktree of `repo` at `folder`, as `git worktree add` leaves it: a `.git` file naming its gitdir,
        whose `commondir` leads back to the main checkout's `.git`."""
        gitdir = os.path.join(repo, ".git", "worktrees", name)
        write(os.path.join(gitdir, "commondir"), "../..\n")
        write(os.path.join(gitdir, "HEAD"), f"ref: refs/heads/{name}\n")
        write(os.path.join(folder, ".git"), f"gitdir: {gitdir}\n")
        return folder

    def test_a_session_in_a_worktree_finds_the_holder_of_a_file_of_its_repository(self):
        t = self.t
        repo = os.path.join(t.tmp, "narwhal")
        write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
        beside = self.worktree(repo, os.path.join(t.tmp, "narwhal-retry"), "retry")
        inside = self.worktree(repo, os.path.join(repo, ".claude", "worktrees", "batch"), "batch")
        t.say(TOP, "Build the narwhal exporter")
        t.say(PUP, "Control the trees")
        self.assertEqual(t.cli(PUP, "controls", TOP).returncode, 0)
        t.record(KID, started_by=TOP, title="the flush child", cwd=repo)
        t.say(KID, "Task:\nBuild the flush's batching.\nFiles: src/flush.py", proj=repo)
        t.record(KID3, started_by=TOP, title="the batch child", cwd=inside)
        t.say(KID3, "Task:\nBuild the batch writer.\nFiles: src/batch.py", proj=inside)
        t.record(KID2, started_by=TOP, title="the retry check", cwd=beside)
        t.say(KID2, "Task:\nCheck the flush's retry and report.\nFiles: none", proj=beside)
        t.say(TOP3, "Build the importer")
        said, decision = self.pre(KID2, SEND, {"to": TOP3, "message": "Does src/flush.py still drop rows?"})
        self.assertIn(KID, said, "a session in a worktree names a file of its repository's main checkout")
        self.assertEqual(decision, "deny")
        said, _ = self.pre(KID2, SEND, {"to": TOP3, "message": "Does src/batch.py write the last batch?"})
        self.assertIn(KID3, said, "and a file a session in another worktree of it holds")
        flush = os.path.join(inside, "src", "flush.py").replace("\\", "/")
        self.assertIn(KID, book.holder_line(t.p4, t.session(KID3), f"Finding: {flush} drops rows", "", ()) or "",
                      "a path inside a worktree is its repository's file")
        self.assertNotIn(KID, book.holder_line(t.p4, t.session(KID2), "vendor/src/flush.py drops rows", "", ()) or "",
                         "a longer path is still not the held one")

    def test_a_finding_on_an_issue_above_the_reporter_stays_with_its_tree(self):
        t = self.t
        self.tree()
        s = t.session(TOP)
        s["issue"] = {"repo": "ezexe/p4", "number": 247}
        relay._write_json(os.path.join(t.dir(TOP), "session.json"), s)
        t.stop(KID2, "Check the flush's retry and report.",
               report="Checked.\nFinding: ezexe/p4#247 misses the ledger's closed rows; source: its brief; "
                      "test: test_asks; files: none")
        ctx = context(t.say(TOP, "what came in?"))
        self.assertIn("on the issue this session's tree already holds", ctx)
        self.assertNotIn("go up to the puppeteer", ctx)

    def test_the_route_line_names_the_owner_by_its_whole_title(self):
        t = self.t
        long = "Build the narwhal exporter's flush, retry and batch writer, and land each with its suite green"
        t.record(KID3, started_by=TOP, title=long)
        t.say(KID3, "Task:\nBuild the writer.\nFiles: src/writer.py")
        self.assertEqual(t.cli(KID3, "shard", os.path.join(t.proj, "src", "writer")).returncode, 0)
        t.say(TOP, "Build the narwhal exporter")
        t.record(TOP3, title="An orchestrator nobody put under the puppeteer")
        t.say(TOP3, "Build the importer")
        ctx = context(t.say(TOP3, f"please look at {os.path.join(t.proj, 'src', 'writer', 'rows.py')}"))
        self.assertIn(f"\"{long}\" `{KID3}`", ctx)

    LONG = "Port the narwhal exporter's flush batching and its retry to the new writer"     # 74 characters

    def test_a_title_of_70_characters_is_kept_whole_where_a_session_is_named(self):            # ezexe/p4#233
        t = self.t
        self.assertGreaterEqual(len(self.LONG), 70)
        t.record(KID3, started_by=TOP, title=self.LONG)
        t.say(TOP, "Build the narwhal exporter")
        t.say(KID3, "Task:\nPort the flush batching. Report when done.\nFiles: src/batch.py")
        self.assertEqual(t.cli(KID3, "done", "its suite ran green").returncode, 0)
        t.stop(KID3, "Port the flush batching. Report when done.", report="Ported; its suite ran green.")
        notes = " ".join(str(n.get("claim")) for n in phi.load_notes(t.p4, TOP))
        self.assertIn(self.LONG, notes, "the replaces: note on its parent")
        ctx = context(t.say(TOP, "what came in?"))
        self.assertIn(self.LONG, ctx, "the parent's line names it whole")
        self.assertIn(self.LONG, read(relay.ready_path(t.p4)), "the ready page names it whole")

    def test_the_reports_line_says_to_name_each_session_by_its_whole_title_as_a_link(self):   # ezexe/p4#233
        t = self.t
        t.record(KID3, started_by=TOP, title=self.LONG)
        t.say(TOP, "Build the narwhal exporter")
        t.say(KID3, "Task:\nPort the flush batching.\nFiles: src/batch.py")
        t.stop(KID3, "Port the flush batching.", report="Ported the batching; the retry is next.")
        ctx = context(t.say(TOP, "what came in?"))
        self.assertIn(self.LONG, ctx)
        self.assertIn("Name each session to ezexe by its whole title as a link", ctx)

    def test_ezexes_words_are_read_without_links_and_paths_but_slash_joined_words_count(self):
        self.assertTrue(book.decides("Needs ezexe's approval of the flush fix"))
        self.assertTrue(book.decides("This needs ezexe to approve/merge the flush fix"))
        self.assertTrue(book.ezexes("The retry landed/pushed this morning"))
        self.assertTrue(book.ezexes("The `flush` helper landed; its `flag` is next"), "words between two spans stay")
        self.assertFalse(book.ezexes("See ezexe/p4#245 and https://github.com/ezexe/p4/issues/245 about the flush"))
        self.assertFalse(book.ezexes("Read E:/work/push/flush.py and src/merge/rows.py about the rows"))

    def test_a_starts_book_line_keeps_to_its_cap(self):
        t = self.t
        self.tree()
        for k in range(12):
            sid = f"local_cap{k:05d}"
            CLI.setdefault(sid, f"4444{k:04d}-0000-4000-8000-000000000000")
            t.record(sid, started_by=TOP, title=f"the capped writer number {k} of the narwhal exporter's batches")
            t.say(sid, f"Task:\nWrite batch {k}.\nFiles: src/batch{k}/rows.py, src/batch{k}/flush.py")
        self.assertLessEqual(len(book.line(t.p4, t.session(KID2))), book.LINE_CHARS + 200)
        again = book.line(t.p4, t.session(KID2), named=True)
        self.assertIn(f"unchanged since it last looked, is whole on {book.page_path(t.p4, KID2)}", again,
                      "a start names the page even with nothing changed")

    def test_issues_named_reads_slugs_bare_numbers_and_links_and_no_path_or_anchor(self):
        self.assertEqual(book.issues_named("ezexe/p4#245 and #236, https://github.com/ezexe/phi/issues/12 and "
                                           "[a](#local_x) and C#"), [("ezexe/phi", 12), ("ezexe/p4", 245), ("", 236)])


if __name__ == "__main__":
    unittest.main()
