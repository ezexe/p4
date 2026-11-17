#!/usr/bin/env python3
"""catchup.py: what fell behind at a session's start, closed where it may be and named where only ezexe may.

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
            {"name": "p4-temportal", "source": "./plugins/p4-temportal", "version": "0.2.0"}],
            "renames": {"p4-memory": "p4-temportal", "p4-scratchpad": "p4-temportal", "p4-recall": "p4-phi"}})
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
    def test_a_name_the_marketplace_renames_is_retired(self):
        """ezexe/p4#185: the retired plugins are the marketplace's `renames`, row P14 of the platform page, so a name
        only that map holds is uninstalled in favour of the plugin it names, and a name mapped to null is not."""
        path = os.path.join(self.market, ".claude-plugin", "marketplace.json")
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        m["renames"].update({"p4-old-name": "p4-phi", "p4-gone": None})
        write(path, m)
        self.install([("p4-old-name", "user", "0.1.0", None), ("p4-gone", "user", "0.1.0", None),
                      ("p4-phi", "user", "0.7.0", None)], {"p4-old-name": True, "p4-gone": True, "p4-phi": True})
        cmds = catchup.plugin_commands(self.project)
        self.assertIn(f"claude plugin uninstall p4-old-name@{M} --scope user", cmds)
        self.assertFalse(any("p4-gone" in c for c in cmds), cmds)

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
            "p4-recall was on at user scope: p4-phi moves to user scope, each project's own install removed "
            "first in its project, so it is never installed twice, and nothing removed is updated")

    def test_ezexes_config_retires_disabled_plugins_too(self):
        """Every former plugin installed at user scope, p4-memory and p4-scratchpad disabled and p4-recall on,
        beside p4-temportal at user scope and p4-phi in two projects: each former plugin is uninstalled, each
        project's p4-phi is removed in its project, and p4-phi is installed once, at user scope."""
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
        self.assertEqual(catchup.plugin_commands(self.project), [], "no uninstall before p4-phi carries retrieval")

    def test_old_cache_folders_are_counted_and_deleted_only_by_prune_cache(self):
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
        self.assertEqual(catchup.run(self.project, p4, sync=False), "", "told once per count")
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


class Watcher(Base):
    """ezexe/p4#246: the running Claude Code binary, read through CLAUDE_PID, sets off the whole settings check."""

    def stub(self, version):
        """A stand-in binary that prints `version` for --version and counts its runs."""
        self.count = os.path.join(self.tmp, "runs.txt")
        if os.name == "nt":
            p = os.path.join(self.tmp, "bin", "claude.cmd")
            write(p, f'@echo off\r\necho x>>"{self.count}"\r\necho {version} (Claude Code)\r\n')
        else:
            p = os.path.join(self.tmp, "bin", "claude")
            write(p, f'#!/bin/sh\necho x >> "{self.count}"\necho "{version} (Claude Code)"\n')
            os.chmod(p, 0o755)
        return p

    def runs(self):
        try:
            with open(self.count, encoding="utf-8") as f:
                return len(f.read().split())
        except OSError:
            return 0

    def test_a_new_claude_code_binary_runs_the_whole_check(self):
        from unittest import mock
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        local = os.path.join(self.project, ".claude", "settings.local.json")
        mem = os.path.abspath(os.path.join(p4, "temportal", "memory")).replace("\\", "/")
        stub = self.stub("2.1.400")
        # a record from an earlier start: the key p4 owns, which is now missing from the file, and an older binary
        write(os.path.join(p4, "claude-settings.json"), {
            "files": {os.path.abspath(local).replace("\\", "/"): {"autoMemoryDirectory": {"v": mem, "gen": 1}}},
            "claude": {"path": stub, "size": 1, "mtime": 1.0, "version": "2.1.300"}})
        write(local, {"spinnerTipsEnabled": False})
        started = []
        env = {"CLAUDE_PID": "4242"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(catchup, "exe_of_pid", lambda pid: stub if pid == 4242 else None), \
                mock.patch.object(catchup, "start_changelog", lambda *a: started.append(a[1:])):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            catchup.settings_hook({"cwd": self.project, "source": "resume", "hook_event_name": "SessionStart"})
            self.assertEqual(self.runs(), 1, "a changed binary is asked its version")
            with open(local, encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("autoMemoryDirectory"), mem, "the whole check wrote the key again")
            with open(os.path.join(p4, "claude-settings.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["claude"]["version"], "2.1.400")
            self.assertEqual(started, [("2.1.300", "2.1.400")], "the changelog between the two is read")
            catchup.settings_hook({"cwd": self.project, "source": "startup", "hook_event_name": "SessionStart"})
            self.assertEqual(self.runs(), 1, "the same binary: no --version runs")

    def test_the_process_claude_pid_names_is_read_from_the_system(self):
        p = catchup.exe_of_pid(os.getpid())
        self.assertTrue(p and os.path.isfile(p), p)
        self.assertTrue(os.path.basename(p).lower().startswith("python"), p)

    def test_a_config_change_by_hand_leaves_the_record_and_never_blocks(self):
        import p4conf
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        local = os.path.join(self.project, ".claude", "settings.local.json")
        p4conf.keep_settings(self.project)
        with open(local, encoding="utf-8") as f:
            d = json.load(f)
        d["autoMemoryDirectory"] = "D:/mine"
        write(local, d)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        out = catchup.settings_hook({"cwd": self.project, "hook_event_name": "ConfigChange",
                                     "source": "local_settings", "file_path": local})
        self.assertIsNone(out, "a ConfigChange hook never blocks")
        with open(local, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["autoMemoryDirectory"], "D:/mine")
        self.assertNotIn("autoMemoryDirectory", json.dumps(p4conf.read_record(p4).get("files") or {}))

    def test_a_watched_term_in_a_newer_version_reaches_the_next_prompt_once(self):
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        text = ("# Changelog\n\n## 2.1.402\n\n- Fixed the spinner\n\n## 2.1.401\n\n- `ConfigChange` hooks now get a"
                " new field\n\n## 2.1.300\n\n- `autoMemoryDirectory` added\n")
        hits = catchup.read_changelog(p4, "2.1.300", "2.1.401", text=text)
        self.assertEqual([(t, v, i) for t, v, i, _ in hits], [("ConfigChange", "2.1.401", "ezexe/p4#246")],
                         "only the sections after the recorded version up to the new one")
        with open(os.path.join(p4, *catchup.WATCH_PAGE), encoding="utf-8") as f:
            self.assertIn("`ConfigChange` in 2.1.401", f.read())
        got = catchup.claim_watch(p4)
        self.assertEqual(len(got), 1)
        self.assertIn("ConfigChange", got[0])
        self.assertIn("2.1.401", got[0])
        self.assertIn("ezexe/p4#246", got[0])
        self.assertEqual(catchup.claim_watch(p4), [], "one session gets the line once")

    def test_the_issues_workers_terms_are_watched_when_their_file_is_there(self):
        from unittest import mock
        path = os.path.join(self.tmp, "limits.json")
        write(path, [{"repo": "ezexe/p4", "issue": 999, "title": "t", "behaviour": "b", "source": "s",
                      "changes_when": "c", "terms": ["fooSetting"]}])
        with mock.patch.object(catchup, "LIMITS", path):
            self.assertEqual(catchup.watched_terms()["fooSetting"], "ezexe/p4#999")
        with mock.patch.object(catchup, "LIMITS", os.path.join(self.tmp, "none.json")):
            self.assertEqual(catchup.watched_terms(), catchup.WATCHED)


if __name__ == "__main__":
    unittest.main(verbosity=1)
