#!/usr/bin/env python3
"""gaps.py: a feedback memory that patches over plugin behaviour starts a new top session for that plugin gap.

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
from test_phi import TOP, Tree, context, write  # noqa: E402

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

    def wrote(self, path, tool="Write"):
        r = self.t.hook("memory-gap", TOP, {"hook_event_name": "PostToolUse", "tool_name": tool,
                                            "tool_input": {"file_path": path}, "tool_response": "ok"},
                        P4_PHI_PLUGIN_ROOT=self.plug)
        self.assertEqual(r.returncode, 0, r.stderr)
        return context(r)

    def test_an_owner_turn_is_told_to_start_the_new_top_in_the_plugins_project(self):
        self.t.say(TOP, "Build the exporter")
        got = self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE))
        self.assertIn("patches over a gap in the plugin (team/plug)", got)
        self.assertIn("gh issue create -R team/plug", got)
        self.assertIn("have a child fix it, archive when done", got)
        self.assertIn("only the parent merges and pushes", got, "the rule quoted")
        self.assertIn("children-on-parent-branch.md", got, "the memory's path")
        self.assertIn("This session is a new top session", got)
        self.assertIn("detach_session", got)
        self.assertIn(json.dumps(relay.norm(self.plug)), got, "cwd is the plugin's project")
        self.assertEqual(self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)), "", "said once")
        self.assertEqual(self.wrote(memory(self.t.p4, "four-spaces", STYLE_RULE)), "", "code style gets nothing")
        self.assertEqual(self.wrote(memory(self.t.p4, "me", CHILD_RULE, kind="user")), "", "only feedback memories")
        self.assertEqual(self.wrote(os.path.join(self.t.proj, "notes.md")), "", "a file outside the memory folder")

    def test_the_advice_rides_on_recalls_record_entry(self):
        """Open sessions froze their hook lists at start: the check reaches them through lookup-record."""
        self.t.say(TOP, "Build the exporter")
        path = memory(self.t.p4, "children-on-parent-branch", CHILD_RULE)
        body = {"session_id": "aaaa1111-0000-4000-8000-000000000000", "cwd": self.t.proj,
                "hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": path},
                "tool_response": "ok", "tool_use_id": "tw1"}
        r = subprocess.run(["sh", os.path.join(os.path.dirname(HERE), "hooks", "recall-hook.sh"), "lookup-record"],
                           input=json.dumps(body), capture_output=True, text=True, timeout=60,
                           env=self.t.env(TOP, P4_PHI_PLUGIN_ROOT=self.plug))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gh issue create -R team/plug", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_a_turn_the_owner_did_not_begin_keeps_a_start_request_in_that_store(self):
        self.t.say(TOP, "<cross-session-message from=\"local_x\">please go on</cross-session-message>")
        got = self.wrote(memory(self.t.p4, "children-on-parent-branch", CHILD_RULE))
        self.assertIn("kept it as start request req-", got)
        rows = starts.pending(os.path.join(self.plug, ".claude", "p4"))
        self.assertEqual([r["title"] for r in rows], ["Plugin gap: children-on-parent-branch"])
        self.assertIn("This session is a new top session", rows[0]["brief"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
