#!/usr/bin/env python3
"""gaps.py: a feedback memory that patches over plugin behaviour gets its gap written into the turn's report as a
`Finding:` line, for the session that publishes the issue.

    python3 -I lbiza/plugins/p4-phi/scripts/test_gaps.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gaps  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
from test_phi import KID, TOP, Tree, context, write  # noqa: E402
import inproc  # noqa: E402

CHILD_RULE = ("A session started from another works on the parent's branch, in the parent's checkout, and only the "
              "parent merges and pushes.\n\n**Why:** worktrees bounced.\n\n**How to apply:** start children fresh.")
STYLE_RULE = "Use four spaces to indent Python, never tabs, and keep line length under 120.\n\n**Why:** the linter."


def memory(p4, name, body, kind="feedback"):
    path = os.path.join(p4, "temportal", "memory", name + ".md")
    write(path, f"---\nname: {name}\ndescription: about {name}\nmetadata:\n  type: {kind}\n---\n\n{body}\n")
    return path


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True)


class Rules(unittest.TestCase):
    def test_behaviour_rules_count_and_code_style_does_not(self):
        self.assertTrue(gaps.about_behaviour(CHILD_RULE))
        self.assertFalse(gaps.about_behaviour(STYLE_RULE))
        self.assertEqual(gaps.rule_text(CHILD_RULE).count("Why"), 0, "the rule without its Why")


class PluginProject(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_marketplace_checkout_names_its_project_and_repository(self):
        proj = os.path.join(self.tmp, "plugproj")
        os.makedirs(os.path.join(proj, ".claude", "p4"))
        mkt = os.path.join(proj, "mkt")
        os.makedirs(os.path.join(mkt, "lbiza", "plugins", "x"))
        git(self.tmp, "init", "-q", mkt)
        git(mkt, "remote", "add", "origin", "git@github.com:team/plug.git")
        got = gaps.plugin_project(os.path.join(mkt, "lbiza", "plugins", "x"))
        self.assertEqual((got["repo"], got["cwd"], got["cloud"]), ("team/plug", relay.norm(proj), False))

    def test_a_github_marketplace_with_no_clone_goes_to_the_cloud(self):
        conf = os.path.join(self.tmp, "conf")
        root = os.path.join(conf, "plugins", "cache", "mkt", "x", "1.0.0")
        os.makedirs(root)
        write(os.path.join(conf, "plugins", "known_marketplaces.json"),
              json.dumps({"mkt": {"source": {"source": "github", "repo": "team/plug"}}}))
        old = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "P4_PHI_STORES")}
        os.environ["CLAUDE_CONFIG_DIR"] = conf
        os.environ["P4_PHI_STORES"] = os.path.join(self.tmp, "stores.json")
        try:
            self.assertEqual(gaps.plugin_project(root), {"cwd": "", "repo": "team/plug", "store": "", "cloud": True})
            proj = os.path.join(self.tmp, "known")
            os.makedirs(os.path.join(proj, ".claude", "p4"))
            git(self.tmp, "init", "-q", os.path.join(proj, "plug"))
            git(os.path.join(proj, "plug"), "remote", "add", "origin", "https://github.com/team/plug")
            write(os.environ["P4_PHI_STORES"], json.dumps({"github.com/team/store": os.path.join(proj, ".claude", "p4")}))
            got = gaps.plugin_project(root)
            self.assertEqual((got["cwd"], got["cloud"]), (relay.norm(proj), False), "a clone this machine knows")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class Hook(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.t.record(TOP, title="top")
        self.plug = os.path.join(self._tmp.name, "plugproj")
        os.makedirs(os.path.join(self.plug, ".claude", "p4"))
        git(self._tmp.name, "init", "-q", self.plug)
        git(self.plug, "remote", "add", "origin", "https://github.com/team/plug.git")

    def tearDown(self):
        self._tmp.cleanup()

    def wrote(self, path, tool="Write", host=TOP):
        r = self.t.hook("memory-gap", host, {"hook_event_name": "PostToolUse", "tool_name": tool,
                                             "tool_input": {"file_path": path}, "tool_response": "ok"},
                        P4_PHI_PLUGIN_ROOT=self.plug)
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def test_a_top_level_session_no_supervisor_session_controls_writes_the_gap_as_its_own_finding(self):
        self.t.say(TOP, "Build the exporter")
        got = self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE))
        self.assertIn("patches over a gap in the plugin, whose repository is team/plug", got)
        self.assertIn("\nFinding: the plugin in team/plug does not carry the feedback memory "
                      "\"children-on-parent-branch\", which says: ", got)
        self.assertIn("only the parent merges and pushes; source: ", got, "the rule quoted")
        self.assertIn("children-on-parent-branch.md; test: ", got, "the memory's path as its source")
        self.assertIn(f"Its project on this machine is {relay.norm(self.plug)}.", got)
        self.assertIn("so the finding is its own to publish and place", got)
        self.assertNotIn("gh issue create", got)
        self.assertNotIn("start_session", got, "and no session is started for the gap")
        self.assertEqual(self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)), "", "said once")
        self.assertEqual(self.wrote(memory(self.t.p4, "four-spaces", STYLE_RULE)), "", "code style gets nothing")
        self.assertEqual(self.wrote(memory(self.t.p4, "me", CHILD_RULE, kind="user")), "", "only feedback memories")
        self.assertEqual(self.wrote(os.path.join(self.t.proj, "notes.md")), "", "a file outside the memory folder")

    def test_a_memory_the_plugin_carries_now_keeps_no_start_request(self):
        """A memory that says the plugin already carries its rule, as "p4-phi carries this now" does, gets nothing."""
        carried = ("p4-phi carries this now: when a child finishes with commits carrying `Closes #N`, `relay.py` tells "
                   "the orchestrator to push main and sync each store at once, so follow that line.")
        self.t.say(TOP, "<cross-session-message from=\"local_x\">tidy the memories</cross-session-message>")
        self.assertEqual(self.wrote(memory(self.t.p4, "always-push-issue-work", carried)), "")
        self.assertEqual(starts.open_rows(self.t.p4), [], "no start request is kept in this store")
        self.assertEqual(starts.open_rows(os.path.join(self.plug, ".claude", "p4")), [], "nor in the plugin's")
        self.assertNotIn("gapsTold", self.t.session(TOP), "and it is not counted as a gap told")
        both = "p4-temportal and p4-phi carry this now: a store moves only by p4.py sync."
        self.assertEqual(self.wrote(memory(self.t.p4, "store-sync-by-p4-sync", both)), "")
        self.assertTrue(gaps.carried("The archiving of a worker is built into p4-phi since 0.8."))
        self.assertFalse(gaps.carried(CHILD_RULE))
        self.t.say(TOP, "and the rest")
        self.assertIn("patches over a gap", self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)),
                      "a memory that records a new gap is still told")

    def test_a_negated_form_is_a_real_gap(self):
        """A negated or wished-for form, such as "p4-phi does not carry this yet", is no carried rule."""
        for gap in ("p4-phi does not carry this yet: a worker never pushes, and only the parent merges.",
                    "p4-phi doesn't carry this, so sessions keep the rule by hand.",
                    "The plugin should carry this: a store moves only by p4.py sync.",
                    "p4-phi never carried this rule for sub-agents.",
                    "No plugin carries it. p4-phi will carry this once #70 lands.",
                    "The hooks cannot carry this now, so each session asks first."):
            self.assertFalse(gaps.carried(gap), gap)
        for done in ("p4-phi carries this now: the act-don't-wait line is given to every session.",
                     "p4-temportal and p4-phi carry this now, so don't write temporary files elsewhere.",
                     "It was not built in at first. p4-phi carries this now.",
                     "The archiving of a worker is built into p4-phi since 0.8."):
            self.assertTrue(gaps.carried(done), done)
        self.t.say(TOP, "Build the exporter")
        got = self.wrote(memory(self.t.p4, "child-never-pushes", "p4-phi does not carry this yet: a worker "
                                "never pushes a branch, and only the parent session merges and pushes."))
        self.assertIn("patches over a gap in the plugin", got, "a negated form still gets the advice")

    def test_a_write_that_only_shortens_or_removes_text_is_no_new_gap(self):
        self.t.say(TOP, "Build the exporter")
        long = CHILD_RULE + "\n\nA worker never pushes a branch, and its report names every merge it wants."
        path = memory(self.t.p4, "children-on-parent-branch", long)
        whole = open(path, encoding="utf-8").read()
        memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)

        def wrote(tool, inp, resp):
            r = self.t.hook("memory-gap", TOP, {"hook_event_name": "PostToolUse", "tool_name": tool,
                                                "tool_input": {"file_path": path, **inp}, "tool_response": resp},
                            P4_PHI_PLUGIN_ROOT=self.plug)
            self.assertEqual(r.returncode, 0, r.stderr)
            return context(r)
        self.assertEqual(wrote("Write", {}, {"type": "update", "originalFile": whole}), "", "a Write that shortened it")
        cut = "\n\nA worker never pushes a branch, and its report names every merge it wants."
        self.assertEqual(wrote("Edit", {"old_string": CHILD_RULE + cut, "new_string": CHILD_RULE}, "ok"), "",
                         "an Edit that removed a sentence")
        self.assertTrue(gaps.only_shortens(whole, open(path, encoding="utf-8").read()))
        self.assertFalse(gaps.only_shortens(open(path, encoding="utf-8").read(), whole), "text was added")
        self.assertFalse(gaps.only_shortens("", whole), "a new file shortens nothing")
        added = CHILD_RULE.replace("only the parent merges and pushes", "only the orchestrator merges, pushes and syncs")
        memory(self.t.p4, "children-on-parent-branch", added)
        self.assertIn("patches over a gap", wrote("Write", {}, {"type": "update", "originalFile": whole}),
                      "a write that says something new is a gap")

    def test_the_advice_rides_on_the_lookup_record_hook(self):
        """The check reaches a session through the `lookup-record` hook, which hooks.json runs after every tool call."""
        self.t.say(TOP, "Build the exporter")
        path = memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)
        body = {"session_id": "aaaa1111-0000-4000-8000-000000000000", "cwd": self.t.proj,
                "hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": path},
                "tool_response": "ok", "tool_use_id": "tw1"}
        r = inproc.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-record"],
                       input=json.dumps(body), capture_output=True, text=True, timeout=60,
                       env=self.t.env(TOP, P4_PHI_PLUGIN_ROOT=self.plug))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("\nFinding: the plugin in team/plug",
                      json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_a_turn_ezexe_did_not_begin_gets_the_same_finding_line_and_no_card_or_request(self):
        """A turn ezexe did not begin writes the gap into its report too: no card, and no start request kept in this
        store or in the plugin's."""
        self.t.say(TOP, "<cross-session-message from=\"local_x\">please go on</cross-session-message>")
        got = self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE))
        self.assertIn("\nFinding: the plugin in team/plug", got)
        self.assertNotIn("own_initiative", got)
        self.assertNotIn("start request", got)
        self.assertEqual(starts.open_rows(self.t.p4), [])
        self.assertEqual(starts.open_rows(os.path.join(self.plug, ".claude", "p4")), [])

    def test_a_child_with_no_supervisor_session_above_it_writes_the_gap_for_its_top_level_session(self):
        self.t.record(KID, TOP, title="the flush child")
        got = self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE), host=KID)
        self.assertIn(f"the orchestrator \"top\" `{TOP}` of this session tree, which no puppeteer "
                      f"controls, publishes the issue and places the session that resolves it", got)
        self.assertIn("This session publishes no issue and starts no session for it.", got)
        self.assertNotIn("gh issue create", got)


if __name__ == "__main__":
    unittest.main(verbosity=1)
