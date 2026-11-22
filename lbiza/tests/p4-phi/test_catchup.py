#!/usr/bin/env python3
"""catchup.py: what fell behind at a session's start, closed where it may be and named where only ezexe may.

    python -m pytest tests/p4-phi/test_catchup.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import catchup  # noqa: E402

M = "p4-marketplace"


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p4-catchup-")
        self.conf = os.path.join(self.tmp, "config")
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(self.project)
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.conf

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, rows, enabled_user=None, enabled_local=None):
        cache = os.path.join(self.conf, "plugins", "cache", M)
        data = {}
        for name, scope, v, project in rows:
            path = os.path.join(cache, name, v)
            os.makedirs(path, exist_ok=True)
            r = {"scope": scope, "version": v, "installPath": path}
            if project:
                r["projectPath"] = project
            data.setdefault(f"{name}@{M}", []).append(r)
        write(os.path.join(self.conf, "plugins", "installed_plugins.json"), {"version": 2, "plugins": data})
        if enabled_user is not None:
            write(os.path.join(self.conf, "settings.json"),
                  {"enabledPlugins": {f"{n}@{M}": on for n, on in enabled_user.items()}})
        if enabled_local is not None:
            write(os.path.join(self.project, ".claude", "settings.local.json"),
                  {"enabledPlugins": {f"{n}@{M}": on for n, on in enabled_local.items()}})


class Plugins(Base):
    def test_a_plugin_behind_its_marketplace_is_claude_codes_own(self):
        """Marketplace auto-update, by https://code.claude.com/docs/en/plugins/install.md, "Keep plugins updated":
        "Plugins update automatically when the marketplace they came from has auto-update turned on." A plugin behind
        its marketplace and a former name in its renames map get no line from p4."""
        self.install([("p4-recall", "user", "0.9.0", None), ("p4-phi", "user", "0.1.0", None)],
                     {"p4-recall": True, "p4-phi": True})
        self.assertNotIn("claude plugin", catchup.run(self.project, os.path.join(self.project, ".claude", "p4")))

    def test_the_module_says_auto_update_is_on_and_by_which_key(self):
        """https://code.claude.com/docs/en/plugins/loading.md, "Which marketplaces and plugins auto-update": a
        marketplace auto-updates by "`autoUpdate` on its `extraKnownMarketplaces` entry in a settings file" first.
        ezexe's user settings set it for p4-marketplace, so the module no longer speaks of a day it is turned on."""
        self.assertNotIn("once ezexe turns it on", catchup.__doc__)
        said = " ".join(catchup.__doc__.split())
        self.assertIn("marketplace auto-update, which is on for p4-marketplace where a settings file sets "
                      "`autoUpdate` on its `extraKnownMarketplaces` entry, as ezexe's user settings do", said)

    def test_nothing_behind_is_silent(self):
        self.install([("p4-phi", "user", "0.7.0", None), ("p4-temportal", "user", "0.2.0", None)],
                     {"p4-phi": True, "p4-temportal": True, "p4-recall": False})
        self.assertEqual(catchup.run(self.project, os.path.join(self.project, ".claude", "p4")), "")

    def test_old_version_folders_are_claude_codes_own(self):
        """Cleanup of previous versions, by https://code.claude.com/docs/en/plugins/loading.md: Claude Code "removes
        that directory in a background cleanup 14 days later". catchup.py neither counts nor deletes them."""
        self.install([("p4-phi", "user", "0.7.0", None)], {"p4-phi": True})
        old = os.path.join(self.conf, "plugins", "cache", M, "p4-phi", "0.6.0")
        write(os.path.join(old, "a.txt"), "y" * 1024)
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        self.assertEqual(catchup.run(self.project, p4, sync=False), "")
        self.assertTrue(os.path.isdir(old), "nothing is deleted")
        self.assertFalse(os.path.exists(os.path.join(p4, "phi", "catchup.json")))
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "catchup.py"), "prune-cache"],
                           capture_output=True, text=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=self.conf))
        self.assertEqual((r.returncode, r.stdout), (0, ""), "catchup.py runs nothing as a command")
        self.assertTrue(os.path.isdir(old))


class Branch(Base):
    def git(self, cwd, *a):
        return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, check=True).stdout

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("no git")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.git(self.tmp, "init", "-q", "--bare", self.origin)
        self.p4 = os.path.join(self.project, ".claude", "p4")
        write(os.path.join(self.p4, "phi", "store", "facts.md"), "a fact\n")
        self.git(self.p4, "init", "-q", "-b", "win")
        self.git(self.p4, "add", "-A")
        self.git(self.p4, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "one")
        self.git(self.p4, "remote", "add", "origin", self.origin)
        self.git(self.p4, "push", "-q", "origin", "win:main", "win:win")
        self.started = []
        self.saved = catchup.start_sync
        catchup.start_sync = lambda p4: self.started.append(p4) or True

    def tearDown(self):
        catchup.start_sync = self.saved
        super().tearDown()

    def advance_main(self):
        other = os.path.join(self.tmp, "mac")
        self.git(self.tmp, "clone", "-q", "-b", "main", self.origin, other)
        write(os.path.join(other, "phi", "store", "facts.md"), "a fact\nfrom the mac\n")
        self.git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")
        self.git(other, "push", "-q", "origin", "main")

    def test_a_branch_level_with_main_is_silent(self):
        self.assertEqual(catchup.behind(self.p4), ("win", 0))
        self.assertEqual(catchup.run(self.project, self.p4), "")
        self.assertEqual(self.started, [])

    def test_a_branch_behind_main_starts_the_sync_and_says_so(self):
        self.advance_main()
        self.assertEqual(catchup.behind(self.p4), ("win", 1))
        line = catchup.run(self.project, self.p4)
        self.assertIn("the store's branch win is 1 commit(s) behind origin/main", line)
        self.assertEqual(self.started, [self.p4])
        self.assertEqual(self.git(self.p4, "rev-list", "--count", "HEAD..origin/main").strip(), "1",
                         "the hook itself merges nothing")

    def test_a_sync_that_cannot_start_is_given_as_the_whole_command(self):
        """When the background sync cannot start, the line orders the sync with the whole command, as phi.py builds
        it for the line that orders a push: the plugin's p4.py by its path and this store."""
        self.advance_main()
        catchup.start_sync = lambda p4: False
        line = catchup.run(self.project, self.p4)
        p4py = os.path.join(catchup.HERE, "p4.py").replace("\\", "/")
        self.assertIn(f'`python -I -X utf8 "{p4py}" sync --push --p4 "{self.p4}"`'.replace("\\", "/"), line)

    def test_no_origin_means_no_branch_check(self):
        self.git(self.p4, "remote", "remove", "origin")
        self.assertIsNone(catchup.behind(self.p4))

    def test_the_hook_runs_only_at_a_startup(self):
        self.advance_main()
        old = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = self.project
        try:
            self.assertIsNone(catchup.hook({"source": "resume"}))
            self.assertIn("behind origin/main", catchup.hook({"source": "startup"})["systemMessage"])
            os.environ[catchup.ENV] = "0"
            self.assertIsNone(catchup.hook({"source": "startup"}))
        finally:
            os.environ.pop(catchup.ENV, None)
            if old is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old


if __name__ == "__main__":
    unittest.main(verbosity=1)
