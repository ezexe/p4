#!/usr/bin/env python3
"""The two plugins on one store: p4-phi writes what it asks for and p4-temportal's keeper copies it.

Each plugin's own tests use a file written by hand as the double for the other side's. This test runs both plugins'
real code on one store, as Claude Code runs a command hook, through `sh` and each plugin's own wrapper script, so
that the two cannot come to read the file differently and each still pass its own tests. It is named so because
tests/p4-phi/test_asks.py is there, and pytest takes two test files of one base name for one module.

    python -m pytest tests/test_two_plugins.py
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
PHI = PLUGINS / "p4-phi"
TEMPORTAL = PLUGINS / "p4-temportal"
START = {"hook_event_name": "SessionStart", "source": "startup"}


class OneStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p4-two-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.config)
        self.assertIsNotNone(shutil.which("sh"), "sh is not found: a command hook starts it")
        self.assertIsNotNone(shutil.which("git"), "git is not found: the store makes a repository")
        self.assertEqual(subprocess.run(["git", "init", "-q", self.proj], capture_output=True).returncode, 0)
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        self.local = os.path.join(self.proj, ".claude", "settings.local.json")

    def hook(self, plugin, wrapper, *args):
        """One command hook as Claude Code runs it: `sh <wrapper> <args>` with the plugin's own root, the project's and
        a configuration folder with nothing in it."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "P4_"))}
        env.update({"CLAUDE_PROJECT_DIR": self.proj, "CLAUDE_PLUGIN_ROOT": str(plugin),
                    "CLAUDE_CONFIG_DIR": self.config, "P4_RECALL_SYNC": "1"})
        r = subprocess.run(["sh", str(plugin / "hooks" / wrapper), *args],
                           input=json.dumps({**START, "cwd": self.proj}), capture_output=True, text=True, env=env,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r

    def make(self):
        self.hook(TEMPORTAL, "run-hook.sh", "store", "make")

    def layout(self):
        self.hook(PHI, "recall-hook.sh", "layout")

    def keep(self):
        self.hook(TEMPORTAL, "run-hook.sh", "store", "keep")

    def asked(self):
        with open(os.path.join(self.p4, "settings.local.json"), encoding="utf-8") as f:
            return json.load(f)["permissions"]["allow"]

    def held(self):
        with open(self.local, encoding="utf-8") as f:
            return json.load(f)["permissions"]["allow"]

    def check_the_local_file(self):
        scripts = (PHI / "scripts").as_posix()
        asked = self.asked()
        self.assertTrue([r for r in asked if f"{scripts}/phi.py" in r], "p4-phi asks for the rule of its own folder")
        held = self.held()
        self.assertTrue([r for r in held if f"{scripts}/phi.py" in r],
                        "the project's local file holds the phi.py rule for p4-phi's scripts folder of this checkout")
        self.assertEqual(sorted(held), sorted(asked), "and what the file asks for, no more")

    def test_make_then_layout_then_keep_copies_the_rule_into_the_local_file(self):
        self.make()
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "p4.json")), "p4-temportal made the store")
        self.layout()
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "settings.local.json")), "p4-phi wrote its file")
        self.keep()
        self.check_the_local_file()

    def test_layout_before_the_store_leaves_no_file_and_the_next_start_leaves_the_rule(self):
        self.layout()
        self.assertFalse(os.path.exists(self.p4), "no store yet: p4-phi writes no file and makes no folder")
        self.make()
        self.layout()
        self.keep()
        self.check_the_local_file()


if __name__ == "__main__":
    unittest.main(verbosity=1)
