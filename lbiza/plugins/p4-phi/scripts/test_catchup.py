#!/usr/bin/env python3
"""catchup.py: what fell behind at a session's start, closed where it may be and named where only the owner may.

    python3 -I lbiza/plugins/p4-phi/scripts/test_catchup.py
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
import catchup  # noqa: E402

M = catchup.MARKET


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p4-catchup-")
        self.conf = os.path.join(self.tmp, "config")
        self.project = os.path.join(self.tmp, "proj")
        self.market = os.path.join(self.tmp, "market")
        os.makedirs(self.project)
        self.old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self.conf
        write(os.path.join(self.conf, "plugins", "known_marketplaces.json"),
              {M: {"source": {"source": "directory", "path": self.market}, "installLocation": self.market}})
        write(os.path.join(self.market, ".claude-plugin", "marketplace.json"), {"name": M, "plugins": [
            {"name": "p4-phi", "source": "./plugins/p4-phi", "version": "0.7.0"},
            {"name": "p4-temportal", "source": "./plugins/p4-temportal", "version": "0.2.0"}]})
        for name, v in (("p4-phi", "0.7.0"), ("p4-temportal", "0.2.0")):
            write(os.path.join(self.market, "plugins", name, ".claude-plugin", "plugin.json"), {"name": name, "version": v})

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
    def test_nothing_behind_is_silent(self):
        self.install([("p4-phi", "user", "0.7.0", None), ("p4-temportal", "user", "0.2.0", None)],
                     {"p4-phi": True, "p4-temportal": True, "p4-recall": False})
        self.assertEqual(catchup.plugin_commands(self.project), [])
        self.assertEqual(catchup.run(self.project, os.path.join(self.project, ".claude", "p4")), "")

    def test_a_retired_plugin_and_an_old_version_get_their_commands(self):
        self.install([("p4-recall", "user", "0.9.0", None), ("p4-phi", "local", "0.5.0", self.project),
                      ("p4-phi", "local", "0.4.0", os.path.join(self.tmp, "other")),
                      ("p4-temportal", "user", "0.2.0", None)],
                     {"p4-recall": True, "p4-temportal": True, "p4-memory": False}, {"p4-phi": True})
        other = os.path.join(self.tmp, "other")
        self.assertEqual(catchup.plugin_commands(self.project), [
            f"claude plugin marketplace update {M}",
            f"claude plugin uninstall p4-recall@{M} --scope user",
            f"claude plugin uninstall p4-phi@{M} --scope local",
            f"claude plugin uninstall p4-phi@{M} --scope local (in {other})",
            f"claude plugin install p4-phi@{M} --scope user"],
            "p4-recall was on for the whole user: p4-phi moves to the user, each project's own install removed "
            "first in its project, so it is never installed twice (C1), and nothing is updated that is removed")

    def test_the_owners_config_retires_disabled_plugins_too(self):
        """The tester's isolated copy of the owner's config (C1, C2): p4-memory and p4-scratchpad installed and
        disabled, p4-recall and p4-temportal for the user, p4-phi in two projects."""
        ap = os.path.join(self.tmp, "AudioPlugin")
        self.install([("p4-memory", "user", "0.1.10", None), ("p4-scratchpad", "user", "0.1.12", None),
                      ("p4-recall", "user", "0.9.0", None), ("p4-temportal", "user", "0.2.0", None),
                      ("p4-phi", "local", "0.5.0", self.project), ("p4-phi", "local", "0.5.0", ap)],
                     {"p4-memory": False, "p4-scratchpad": False, "p4-recall": True, "p4-temportal": True},
                     {"p4-phi": True})
        cmds = catchup.plugin_commands(self.project)
        self.assertEqual(cmds, [
            f"claude plugin marketplace update {M}",
            f"claude plugin uninstall p4-recall@{M} --scope user",
            f"claude plugin uninstall p4-memory@{M} --scope user",
            f"claude plugin uninstall p4-scratchpad@{M} --scope user",
            f"claude plugin uninstall p4-phi@{M} --scope local",
            f"claude plugin uninstall p4-phi@{M} --scope local (in {ap})",
            f"claude plugin install p4-phi@{M} --scope user"])
        self.assertEqual(sum(c.startswith(f"claude plugin install p4-phi@{M}") for c in cmds), 1)
        line = catchup.run(self.project, os.path.join(self.project, ".claude", "p4"), sync=False)
        self.assertIn(f"`claude plugin uninstall p4-phi@{M} --scope local` in {ap}", line)

    def test_a_retired_plugin_whose_successor_is_missing_gets_an_install(self):
        self.install([("p4-memory", "user", "0.1.10", None), ("p4-scratchpad", "user", "0.1.12", None)],
                     {"p4-memory": True, "p4-scratchpad": True})
        cmds = catchup.plugin_commands(self.project)
        self.assertEqual(cmds[0], f"claude plugin marketplace update {M}")
        self.assertIn(f"claude plugin uninstall p4-memory@{M} --scope user", cmds)
        self.assertIn(f"claude plugin uninstall p4-scratchpad@{M} --scope user", cmds)
        self.assertEqual(cmds.count(f"claude plugin install p4-temportal@{M} --scope user"), 1)

    def test_a_plugin_the_marketplace_still_offers_is_not_retired(self):
        mj = os.path.join(self.market, ".claude-plugin", "marketplace.json")
        with open(mj, encoding="utf-8") as f:
            m = json.load(f)
        m["plugins"].append({"name": "p4-recall", "source": "./plugins/p4-recall", "version": "0.9.0"})
        write(mj, m)
        self.install([("p4-recall", "user", "0.9.0", None), ("p4-phi", "user", "0.7.0", None)],
                     {"p4-recall": True, "p4-phi": True})
        self.assertEqual(catchup.plugin_commands(self.project), [], "no uninstall before p4-phi carries recall")

    def test_old_cache_folders_are_counted_and_never_deleted(self):
        self.install([("p4-phi", "user", "0.7.0", None)], {"p4-phi": True})
        cache = os.path.join(self.conf, "plugins", "cache", M)
        write(os.path.join(cache, "p4-recall", "0.8.21", "scripts", "big.py"), "x" * 2048)
        write(os.path.join(cache, "p4-phi", "0.6.0", "a.txt"), "y" * 1024)
        n, size = catchup.old_cache()
        self.assertEqual((n, size), (2, 3072))
        line = catchup.run(self.project, os.path.join(self.project, ".claude", "p4"), sync=False)
        self.assertIn("2 old version folder(s)", line)
        self.assertIn("3.0 KB", line)
        self.assertTrue(os.path.isdir(os.path.join(cache, "p4-recall", "0.8.21")), "nothing is deleted")
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4, exist_ok=True)
        self.assertIn("prune-cache", catchup.run(self.project, p4, sync=False))
        self.assertEqual(catchup.run(self.project, p4, sync=False), "", "told once per count (C3)")
        write(os.path.join(cache, "p4-phi", "0.5.0", "b.txt"), "z")
        self.assertIn("3 old version folder(s)", catchup.run(self.project, p4, sync=False))
        removed = catchup.prune_cache()
        self.assertEqual(len(removed), 3)
        self.assertTrue(os.path.isdir(os.path.join(cache, "p4-phi", "0.7.0")), "the folder an install uses stays")

    def test_versions_compare_as_numbers(self):
        self.assertLess(catchup.version("0.9.0"), catchup.version("0.10.0"))
        self.assertEqual(catchup.size_text(-2048), "at least 2.0 KB")


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
