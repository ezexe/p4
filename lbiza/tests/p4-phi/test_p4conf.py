#!/usr/bin/env python3
"""p4conf.py: one settings file for every p4 plugin, written when missing, merged over the defaults.

    python -m pytest tests/p4-phi/test_p4conf.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "plugins" / "p4-phi" / "scripts"
sys.path.insert(0, str(SRC))
import p4conf  # noqa: E402

PLUGINS = SRC.parents[1]


class P4Conf(unittest.TestCase):
    def setUp(self):
        self.p4 = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.p4, True)

    def read(self, record=False):
        """p4.json as written, without load's record of the defaults it wrote unless `record`."""
        with open(p4conf.path(self.p4), encoding="utf-8") as f:
            d = json.load(f)
        if not record:
            d.pop(p4conf.WRITTEN, None)
        return d

    def test_these_tests_run_the_copy_beside_phi_py(self):
        """Both plugins hold a file named p4conf.py, each its own, and import it by that one name. Whichever test file
        was imported before this one, as the files of tests/p4-temportal/ are when pytest is given that folder first,
        `p4conf` here is the file in p4-phi's scripts/: the one that asks for the allow rules, since phi.py is beside
        it, and has no keeper. test_isolation.py runs this case after the like case of test_lifetime.py, and before
        it."""
        self.assertEqual(Path(p4conf.__file__).resolve(), (SRC / "p4conf.py").resolve())
        self.assertIs(sys.modules["p4conf"], p4conf)
        self.assertIsNotNone(p4conf.allow_rules(sys.platform))
        self.assertTrue(hasattr(p4conf, "want_settings"))
        self.assertFalse(hasattr(p4conf, "keep_settings"))

    def test_a_key_read_when_set_is_not_called_unknown(self):
        """phi.child_levels, phi.puppeteer_section and phi.clear_at are read when a project sets them and are
        never written by default, so a later change to the code's values reaches every store."""
        import contextlib
        import io
        for key in ("child_levels", "puppeteer_section", "clear_at"):
            self.assertNotIn(key, p4conf.DEFAULTS["phi"])
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": {"puppeteer_section": "", "clear_at": 9, "child_levels": {}}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(s["phi"]["clear_at"], 9)

    def test_what_a_worktree_shares_is_read_when_set_and_has_its_variables(self):
        """phi.worktree_python and phi.worktree_lines are a project's own, never written by default."""
        import contextlib
        import io
        for key in ("worktree_python", "worktree_lines"):
            self.assertNotIn(key, p4conf.DEFAULTS["phi"])
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": {"worktree_python": ".venv/Scripts/python.exe", "worktree_lines": ["a line"]}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(s["phi"]["worktree_python"], ".venv/Scripts/python.exe")
        self.assertEqual(s["phi"]["worktree_lines"], ["a line"])
        self.assertIn("phi.worktree_python", p4conf.env_keys())
        self.assertIn("phi.worktree_lines", p4conf.env_keys())

    def copy_of(self, gen, **phi):
        """A second copy of p4conf.py, as another installed plugin would carry, at generation `gen` with
        phi defaults changed by `phi`."""
        import copy
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"p4conf_gen{gen}", SRC / "p4conf.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.DEFAULTS = copy.deepcopy(mod.DEFAULTS)
        mod.DEFAULTS["phi"].update(phi)
        mod.GEN = gen
        return mod

    def test_a_changed_default_reaches_a_store_load_wrote_it_into(self):
        """A value load wrote follows a newer generation's default; a value set by hand stays as it is."""
        p4conf.load(self.p4)
        d = self.read(record=True)
        d["phi"]["max_children"] = 7
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(d, f)
        s = self.copy_of(p4conf.GEN + 1, max_depth=9, max_children=4).load(self.p4)
        self.assertEqual(s["phi"]["max_depth"], 9, "written by load: follows the new default")
        self.assertEqual(s["phi"]["max_children"], 7, "set by hand: kept")
        self.assertEqual(self.read()["phi"]["max_depth"], 9)

    def test_two_copies_that_differ_on_a_default_settle_on_the_newer(self):
        """Two copies, both with the record, that differ on a default write p4.json at most twice in turn and settle
        on the newer generation's value."""
        old, new = self.copy_of(1, max_depth=5), self.copy_of(2, max_depth=9)
        writes = []
        for c in (old, new):
            real = c._write
            c._write = lambda p4, data, real=real: (writes.append(1), real(p4, data))
        for c in (old, new, old, new, old, new):
            c.load(self.p4, warn=False)
        self.assertLessEqual(len(writes), 2, "written by the first load, moved once by the newer")
        self.assertEqual(self.read()["phi"]["max_depth"], 9)
        self.assertEqual(old.load(self.p4)["phi"]["max_depth"], 9, "the older copy reads the newer value")

    def test_the_sections_of_p4_temportal_are_kept_as_they_are_and_a_key_nobody_reads_is_named(self):
        """A p4.json that holds `scratchpad`, `temportal` and `claude`: load keeps each as it is, names none of them
        on stderr and writes no default into them. A top-level key that neither plugin reads is named."""
        import contextlib
        import io
        held = {"scratchpad": {"asks": True, "once_was": 1}, "temportal": {"cache": {"x": {"max_age_days": 1}}},
                "claude": {"keep": False}}
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(held, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            p4conf.load(self.p4)
            p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "")
        on_disk = self.read()
        for name, value in held.items():
            self.assertEqual(on_disk[name], value, name)
        self.assertEqual(on_disk["phi"], p4conf.DEFAULTS["phi"], "its own defaults are written")
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({**held, "nobody": {"reads": "this"}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            p4conf.load(self.p4)
        self.assertIn("nobody", err.getvalue())
        for name in held:
            self.assertNotIn(name, err.getvalue().split("kept as they are:")[-1], name)

    def test_a_store_gains_the_tree_caps_a_project_sets(self):
        """ezexe/p4#125: the nine caps of the session tree are phi keys of p4.json, written into a store that lacks
        them with the values the code had, and a value set by hand stays."""
        caps = {"max_depth": 3, "max_children": 8, "sibling_turns": 5, "own_turns": 3, "chain_max": 8,
                "turn_steps": 12, "keep_going_max": 2, "watch_s": 5.0, "stale_s": 86400.0}
        d = json.loads(json.dumps(p4conf.DEFAULTS))
        for k in caps:
            d["phi"].pop(k)
        d["phi"]["max_depth"] = 4
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(d, f)
        got = p4conf.load(self.p4)["phi"]
        self.assertEqual({k: got[k] for k in caps}, dict(caps, max_depth=4))
        self.assertEqual({k: self.read()["phi"][k] for k in caps}, dict(caps, max_depth=4), "written into the file")
        self.assertNotIn("max_depth", json.dumps(p4conf.read_json(p4conf.record_path(self.p4))),
                         "nothing of the settings record")

    def test_gen_is_raised_with_every_change_of_defaults(self):
        """DEFAULTS is pinned to its GEN: a change of a default fails here until GEN is raised and the pin below
        updated."""
        import hashlib
        pins = {1: "cc7604892f2635f2", 2: "13977bb862fc1973", 3: "6f131c04ed9bacca", 4: "857fe1fd14a29f6a", 5: "52f39f39f1f34c83", 6: "80d9cae8899e4527", 7: "58861a65cec942df", 8: "aac06d8c3ca8f985", 9: "a3effadd1ed36009", 10: "909dddd3e3552f7c",
                11: "909dddd3e3552f7c", 12: "909dddd3e3552f7c", 13: "b5e6072e9ec3eb7c", 14: "db03b4ae71345a63", 15: "95656cb9ae6e2f7f", 16: "b5d9965d5d399131",
                17: "6a45398a0838bc56", 18: "90cd6fc0182885a7", 19: "84674b30334aba51"}
        # append only: one more for each GEN. 11 came with a key of the keeper, 12 with the plans folder's move,
        # 13 with the default phi.plan_mode, and 14 with the default phi.goal_review
        # and 15 with the default phi.new_issues, and 16 with the removal of the group recall, and 17 with the
        # defaults of p4.json held by the plugin that reads them: this file's are the `phi` section's, 18 with the
        # removal of the default phi.act_dont_wait, and 19 with the removal of the defaults phi.top_orchestrates,
        # phi.levels and phi.tree_checks
        got = hashlib.sha256(json.dumps(p4conf.DEFAULTS, sort_keys=True).encode()).hexdigest()[:16]
        self.assertEqual(p4conf.GEN, max(pins))
        self.assertEqual(p4conf.GEN, len(pins), "no generation is skipped or replaced")
        self.assertEqual(pins[p4conf.GEN], got, "DEFAULTS changed: raise GEN and pin it")

    def test_a_missing_file_is_written_with_every_default(self):
        s = p4conf.load(self.p4)
        self.assertEqual(s, p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(set(s), {"phi"}, "no group of the removed retrieval")

    def test_the_retired_config_json_seeds_nothing(self):
        os.makedirs(p4conf.sub(self.p4, "models"))
        with open(p4conf.sub(self.p4, "models", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"teacher-model": "claude-opus-5-5", "inject": False, "teacher-cutoff": "2026-06"}, f)
        self.assertEqual(p4conf.load(self.p4), p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)

    def test_missing_keys_are_added_and_set_values_kept(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": {"max_depth": 4, "once_was": "kept"}, "extra": 1}, f)
        s = p4conf.load(self.p4, warn=False)
        on_disk = self.read()
        self.assertEqual(on_disk["phi"]["max_depth"], 4)
        self.assertEqual(on_disk["phi"]["max_children"], p4conf.DEFAULTS["phi"]["max_children"], "a missing key is added")
        self.assertEqual(on_disk["phi"]["once_was"], "kept", "an unknown key stays on disk, read by nothing")
        self.assertNotIn("scratchpad", on_disk, "a section of p4-temportal's is no default of this file")
        self.assertEqual(on_disk["extra"], 1, "an unknown key survives the rewrite")
        self.assertEqual(s["phi"]["max_depth"], 4)

    def test_a_store_that_still_holds_the_recall_group_keeps_it_and_names_no_key_of_it(self):
        """The group `recall` is no part of DEFAULTS since the retrieval left p4-phi. A store whose p4.json still
        holds it keeps it whole through every rewrite, and load prints no line about keys this plugin does not read."""
        import contextlib
        import io
        held = {"inject": False, "learn": True, "once_was": "kept"}
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"recall": held, "phi": {"max_depth": 4}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            p4conf.load(self.p4)
            p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn("recall", p4conf.DEFAULTS)
        self.assertIn("recall", p4conf.OTHERS)
        self.assertEqual(self.read()["recall"], held, "kept as it was")
        self.assertEqual(self.read()["phi"]["max_children"], p4conf.DEFAULTS["phi"]["max_children"], "the rest is filled")

    def test_a_writer_holding_a_temp_file_does_not_block_another(self):
        """Two hooks of one event load at once: a temp file another writer still holds does not stop this write."""
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": p4conf.DEFAULTS["phi"]}, f)
        os.mkdir(p4conf.path(self.p4) + ".tmp")          # the name the other writer would hold
        p4conf.load(self.p4, warn=False)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(sorted(os.listdir(self.p4)), sorted(["p4.json", "p4.json.tmp"]), "no temp file is left")

    def test_an_older_and_a_newer_copy_in_turn_rewrite_at_most_once(self):
        """An installed copy from before `version` was retired adds it back, and this copy must not drop it again at
        each load, or the two rewrite p4.json in turn."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("p4conf_older", SRC / "p4conf.py")
        older = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(older)
        older.DEFAULTS = {**older.DEFAULTS, "version": 1}
        writes = []
        for copy in (p4conf, older):
            real = copy._write
            copy._write = lambda p4, data, real=real: (writes.append(1), real(p4, data))
        try:
            for copy in (older, p4conf, older, p4conf, older, p4conf):
                copy.load(self.p4, warn=False)
        finally:
            p4conf._write = p4conf._write.__defaults__[0]
        self.assertEqual(self.read()["version"], 1, "the older copy's key stays until a rewrite for a missing key")
        self.assertLessEqual(len(writes), 1 + 1, "the first write creates the file, at most one more rewrites it")

    def test_a_broken_file_is_never_overwritten(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(p4conf.load(self.p4, warn=False), p4conf.DEFAULTS)
        with open(p4conf.path(self.p4), encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")

    def test_a_test_leaves_no_temp_folder(self):
        t = P4Conf("test_no_directory_no_file")
        t.run(unittest.TestResult())
        self.assertFalse(os.path.exists(t.p4), "setUp's folder is removed after the test")

    def test_no_directory_no_file(self):
        gone = os.path.join(self.p4, "absent")
        self.assertEqual(p4conf.load(gone), p4conf.DEFAULTS)
        self.assertFalse(os.path.exists(gone))


def fake_phi(scripts):
    """A scripts folder laid out as the plugin p4-phi: a phi.py in it and the manifest above it."""
    Path(scripts).mkdir(parents=True, exist_ok=True)
    Path(scripts, "phi.py").write_text("", encoding="utf-8")
    manifest = Path(scripts).parent / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": "p4-phi"}), encoding="utf-8")


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


class SettingsVariables(unittest.TestCase):
    """Every p4 setting a project changes from its default is a P4_* variable under `env` of the project's local
    settings file, read ahead of p4.json."""

    def setUp(self):
        from unittest import mock
        self.tmp = tempfile.mkdtemp(prefix="p4-settings-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(self.project)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "config")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        os.environ.pop("CLAUDE_PID", None)

    def store(self, conf=None):
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4, exist_ok=True)
        if conf is not None:
            _write(p4conf.path(p4), conf)
        return p4

    def test_every_setting_has_one_variable_of_its_own(self):
        """Each setting of DEFAULTS, and each phi key read when set, has a name of its own, and no name is an older
        variable of another meaning: the older switch that shares a name means what its setting means."""
        import re
        keys = p4conf.env_keys()
        leaves = {k for k, _v in p4conf._leaves(p4conf.DEFAULTS)} - set(p4conf.ENV_SKIP)
        self.assertEqual(set(keys) - set(p4conf.ENV_SET_ONLY), leaves)
        names = [p4conf.env_name(k) for k in keys]
        self.assertEqual(len(names), len(set(names)), "two settings share a name")
        self.assertTrue(all(re.fullmatch(r"P4_[A-Z0-9_]+", n) for n in names), names)
        older = set()
        for path in PLUGINS.rglob("*.py"):
            if path.name != "p4conf.py" and not path.name.startswith("test_"):
                older |= set(re.findall(r"P4_[A-Z0-9_]+", path.read_text(encoding="utf-8", errors="replace")))
        self.assertEqual(older & set(names), {"P4_PHI_ISSUES"})
        self.assertEqual(p4conf.env_name("phi.watch_s"), "P4_PHI_WATCH_SECONDS", "P4_PHI_WATCH_S is puppeteer's tick")

    def test_a_variable_wins_over_p4_json_and_a_bad_one_falls_back_to_it(self):
        """A variable that fits its key wins over p4.json; an empty one is unset; one that does not fit is passed
        over with one stderr line, so the setting takes p4.json's value, the default where p4.json keeps it; p4.json
        never takes a variable's value."""
        import contextlib
        import io
        from unittest import mock
        p4 = self.store({"phi": {"max_depth": 5}})
        cases = [("7", 7), ("", 5), ("deep", 5), ("1.5", 5), ("true", 5)]
        for text, want in cases:
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"P4_PHI_MAX_DEPTH": text}), contextlib.redirect_stderr(err):
                self.assertEqual(p4conf.load(p4)["phi"]["max_depth"], want, f"P4_PHI_MAX_DEPTH={text!r}")
            self.assertEqual(bool(err.getvalue()), want == 5 and text != "", err.getvalue())
        with mock.patch.dict(os.environ, {"P4_PHI_GOAL_REVIEW": "0", "P4_PHI_WATCH_SECONDS": "10",
                                          "P4_PHI_TRACK": "1", "P4_PHI_ISSUES": "yes"}):
            got = p4conf.load(p4, warn=False)
        self.assertIs(got["phi"]["goal_review"], False)
        self.assertEqual(got["phi"]["watch_s"], 10)
        self.assertIs(got["phi"]["track"], True)
        self.assertIs(got["phi"]["issues"], True, "yes is no bool: the default")
        with open(p4conf.path(p4), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["phi"]["max_depth"], 5, "p4.json keeps its own value")
        with mock.patch.dict(os.environ, {"P4_PHI_MAX_DEPTH": "7"}):
            self.assertEqual(p4conf.load(p4, env=False)["phi"]["max_depth"], 5)

    def test_a_variable_applies_to_its_own_projects_store_only(self):
        """A session's variables come from its own project's settings, so a shared home store keeps its p4.json."""
        from unittest import mock
        mine = self.store({})
        other = os.path.join(self.tmp, "home", ".claude", "p4")
        os.makedirs(other)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.project, "P4_PHI_TRACK": "1"}):
            self.assertIs(p4conf.section(mine, "phi")["track"], True)
            self.assertIs(p4conf.section(other, "phi")["track"], False)

    def test_the_caps_reader_takes_a_variable_and_keeps_the_default_out_of_range(self):
        """phi.project_conf reads the tree caps through load, so a variable sets them, and apply_caps keeps the
        default for a value of the right type out of its range."""
        from unittest import mock
        import phi
        p4 = self.store({"phi": {"max_children": 6}})
        try:
            with mock.patch.dict(os.environ, {"P4_PHI_MAX_DEPTH": "4", "P4_PHI_TURN_STEPS": "999"}):
                phi.project_conf(p4)
                self.assertEqual((phi.MAX_DEPTH, phi.MAX_CHILDREN, phi.TURN_STEPS), (4, 6, 12))
        finally:
            phi.project_conf(None)

    def test_a_value_is_checked_as_its_reader_takes_it(self):
        """Each variable is checked against what its reader takes, items included, and a value that cannot be read at
        all falls back, never raising."""
        import contextlib
        import io
        from unittest import mock
        p4 = self.store({})
        bad = {"P4_PHI_CHILD_LEVELS": "[1]", "P4_PHI_CLEAR_AT": "true",
               "P4_PHI_WATCH_SECONDS": '"high"', "P4_PHI_GOAL_REVIEW": "loud",
               "P4_PHI_TRACK": "all", "P4_PHI_MAX_DEPTH": "[" * 20000}
        plain = json.dumps(p4conf.load(p4, write=False, env=False), sort_keys=True)
        for name, text in bad.items():
            with mock.patch.dict(os.environ, {name: text}), contextlib.redirect_stderr(io.StringIO()):
                got = p4conf.load(p4, write=False)
            self.assertEqual(json.dumps(got, sort_keys=True), plain, name)
        with mock.patch.dict(os.environ, {"P4_PHI_CHILD_LEVELS": '{"worker": {"model": "m", "effort": "low"}}',
                                          "P4_PHI_HOME": "5", "P4_PHI_MAX_CHILDREN": "7"}):
            got = p4conf.load(p4, write=False)
        self.assertEqual(got["phi"]["child_levels"], {"worker": {"model": "m", "effort": "low"}})
        self.assertEqual((got["phi"]["home"], got["phi"]["max_children"]), ("5", 7))

    def test_the_raw_readers_read_a_variable_as_p4conf_does(self):
        """issues.on follows p4.json for the store it is given, a person's variable wins, 1, 0, true and false
        alike, and a call with no store answers true."""
        from unittest import mock
        import issues
        p4 = self.store({"phi": {"issues": False, "new_issues": False}})
        self.assertIs(issues.on(p4), False)
        self.assertIs(issues.new_on(p4), False)
        for text, want in (("0", False), ("false", False), ("1", True), ("true", True)):
            with mock.patch.dict(os.environ, {"P4_PHI_ISSUES": text}):
                self.assertIs(issues.on(p4), want, text)
        self.assertIs(issues.on(""), True)
        self.assertIs(issues.new_on(""), True)


class WantSettings(unittest.TestCase):
    """What p4-phi asks the keeper for: the store's settings.local.json, written by want_settings alone."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p4-asks-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(self.project)

    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def store_of(self, project=None):
        p4 = os.path.join(project or self.project, ".claude", "p4")
        os.makedirs(p4, exist_ok=True)
        return p4

    def rules(self, scripts):
        s = os.path.abspath(scripts).replace("\\", "/")
        cmd = f'python -I -X utf8 "{s}/phi.py" *'
        return [f"Bash({cmd})", f"PowerShell({cmd})"]

    def cached(self, *versions):
        """Version folders of p4-phi as Claude Code's plugin cache holds them, `cache/<marketplace>/<plugin>/
        <version>/`, each with a phi.py -> their scripts folders."""
        out = []
        for v in versions:
            s = os.path.join(self.tmp, "plugins", "cache", "p4-marketplace", "p4-phi", v, "scripts")
            os.makedirs(s, exist_ok=True)
            fake_phi(s)
            out.append(s)
        return out

    def test_want_settings_writes_the_rules_for_this_folder_each_cached_version_and_the_set(self):
        """What p4-phi asks for: the phi.py rules for this folder and each cached version folder; with the set in
        force the tool rules and the general rules too; with phi.upkeep on as well, p4.adopt. The file is not
        rewritten where only its order differs, and a copy with no phi.py beside it asks for nothing."""
        from unittest import mock
        p4 = self.store_of()
        old, new = self.cached("0.11.96", "0.11.97")
        os.makedirs(os.path.join(os.path.dirname(os.path.dirname(new)), "0.11.95"))     # no phi.py: no copy
        with mock.patch.object(p4conf, "PHI_SCRIPTS", new):
            got = p4conf.want_settings(p4, "win32")
            self.assertEqual(sorted(got["permissions"]["allow"]), sorted(self.rules(new) + self.rules(old)))
            self.assertNotIn("p4", got)
            self.assertEqual(got, self.read(os.path.join(p4, p4conf.ASKS)), "the file holds what is returned")
            p4conf.set_key(p4, p4conf.CARDS_KEY, p4conf.card_set_id())
            self.assertTrue(p4conf.cards_yes(p4, session="local_top", call="toolu_yes"))
            got = p4conf.want_settings(p4, "win32")
            self.assertEqual(sorted(got["permissions"]["allow"]),
                             sorted(self.rules(new) + self.rules(old) + list(p4conf.CARD_TOOLS)
                                    + list(p4conf.GENERAL_RULES) + list(p4conf.GENERAL_WIN)))
            self.assertNotIn("p4", got, "upkeep is off")
            got = p4conf.want_settings(p4, "linux")
            self.assertFalse([r for r in got["permissions"]["allow"] if r in p4conf.GENERAL_WIN])
            p4conf.set_key(p4, "phi.upkeep", True)
            got = p4conf.want_settings(p4, "win32")
            self.assertEqual(got["p4"], {"adopt": list(p4conf.ASK_RETIRED)})
            file = os.path.join(p4, p4conf.ASKS)
            flipped = self.read(file)
            flipped["permissions"]["allow"].reverse()
            _write(file, json.dumps(flipped, indent=2) + "\n")
            os.utime(file, (1, 1))
            before = Path(file).read_bytes()
            self.assertEqual(p4conf.want_settings(p4, "win32"), got)
            self.assertEqual((Path(file).read_bytes(), os.stat(file).st_mtime), (before, 1), "not rewritten")
            nowhere = os.path.join(self.tmp, "nowhere")
            self.assertIsNone(p4conf.want_settings(nowhere, "win32"), "no store folder")
            self.assertFalse(os.path.exists(nowhere))
        bare = os.path.join(self.tmp, "bare", "scripts")
        os.makedirs(bare)
        other = self.store_of(os.path.join(self.tmp, "other"))
        with mock.patch.object(p4conf, "PHI_SCRIPTS", bare):
            self.assertIsNone(p4conf.want_settings(other, "win32"), "no phi.py beside the copy")
        self.assertFalse(os.path.exists(os.path.join(other, p4conf.ASKS)))

    def test_a_copy_outside_the_plugin_cache_keeps_one_folders_rules(self):
        """A checkout is no version folder: its rules follow it, and no folder beside it is read as a version."""
        beside = os.path.join(self.tmp, "repo", "lbiza", "plugins", "other", "scripts")
        here = os.path.join(self.tmp, "repo", "lbiza", "plugins", "p4-phi", "scripts")
        for s in (beside, here):
            os.makedirs(s)
            fake_phi(s)
        self.assertEqual(p4conf.version_folders(here), [])

    def test_the_folders_of_the_other_versions_are_the_ones_the_cache_holds_with_a_phi_py(self):
        """The scripts folders of the other versions beside the running copy's: the one that has a phi.py, and none
        for the folder of a version that has none."""
        old, new = self.cached("0.11.46", "0.11.48")
        os.makedirs(os.path.join(os.path.dirname(os.path.dirname(new)), "0.11.47"))   # no phi.py: no copy to cover
        self.assertEqual(p4conf.version_folders(new), [os.path.abspath(old).replace("\\", "/")])


class ReadDuringAReplace(unittest.TestCase):
    """A file p4 keeps is written whole to a temp file and moved over the old one with os.replace. On Windows a read
    that meets the move fails with PermissionError, errno 13, for as long as the move takes. Measured on Windows 11
    with one process replacing a file in a loop and another reading it: 1250 of 4922 reads failed so, and none with
    any other error. p4conf.load_json waits the move out, and each reader of such a file reads through it:
    p4conf.read_json, relay._read_json, phi.read_json and node._read_json."""

    RECORD = {"state": "passed", "code": 0}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "proof.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.RECORD, f)

    def refused(self, times):
        """`open` as a reader meets it while a move is under way: refused `times` times, and then as it is. Returns
        the paths it was asked for and the patch that puts it in p4conf's place."""
        from unittest import mock
        asked = []

        def opened(path, *args, **kw):
            asked.append(path)
            if len(asked) <= times:
                raise PermissionError(13, "Permission denied", path)
            return open(path, *args, **kw)
        return asked, mock.patch.object(p4conf, "open", opened, create=True)

    def test_a_read_that_meets_a_replace_and_then_succeeds_answers_the_record(self):
        import phi
        import relay
        for read in (p4conf.read_json, relay._read_json, phi.read_json):
            asked, patch = self.refused(3)
            with patch:
                self.assertEqual(read(self.path), self.RECORD, read.__module__)
            self.assertEqual(len(asked), 4, f"{read.__module__}: refused three times and read at the fourth")

    def test_a_missing_file_answers_at_once_and_one_that_stays_refused_answers_once_the_wait_is_over(self):
        import time
        from unittest import mock
        import relay
        asked, patch = self.refused(0)
        with patch:
            self.assertEqual(p4conf.read_json(os.path.join(self._tmp.name, "none.json")), {})
            self.assertEqual(relay._read_json(os.path.join(self._tmp.name, "none.json")), {})
        self.assertEqual(len(asked), 2, "no file is no move under way: each read tried once")
        asked, patch = self.refused(10 ** 9)
        with patch, mock.patch.object(p4conf, "READ_WAIT_S", 0.05):
            began = time.monotonic()
            self.assertIsNone(p4conf.read_json(self.path), "there, and no JSON object was read")
            self.assertEqual(relay._read_json(self.path), {})
            took = time.monotonic() - began
        self.assertGreaterEqual(took, 0.09, "each read waited its wait out")
        self.assertLess(took, 5)
        self.assertGreater(len(asked), 2, "and tried again meanwhile")

    @unittest.skipUnless(os.name == "nt", "a read meets a move as PermissionError on Windows")
    def test_no_read_takes_another_processs_replace_for_no_record(self):
        """The race itself, for a second: a process replaces the file in a loop, as a run in the background does
        with its proof.json, and every read here answers a record."""
        import subprocess
        import relay
        writer = ("import json, os, sys, time\n"
                  "path, n, end = sys.argv[1], 0, time.time() + 1.0\n"
                  "while time.time() < end:\n"
                  "    with open(path + '.tmp', 'w', encoding='utf-8') as f:\n"
                  "        json.dump({'state': 'running', 'n': n}, f)\n"
                  "    while True:\n"
                  "        try:\n"
                  "            os.replace(path + '.tmp', path)\n"
                  "            break\n"
                  "        except PermissionError:\n"
                  "            pass\n"
                  "    n += 1\n")
        process = subprocess.Popen([sys.executable, "-I", "-c", writer, self.path])
        self.addCleanup(process.wait)               # before the folder goes, whatever the test met
        reads = lost = 0
        while process.poll() is None:
            reads += 1
            lost += not relay._read_json(self.path)
        self.assertEqual(process.returncode, 0)
        self.assertGreater(reads, 50)
        self.assertEqual(lost, 0, f"{lost} of {reads} reads took a move under way for no record")


class WriteDuringARead(unittest.TestCase):
    """The other side of ReadDuringAReplace. A file is written whole to a temp file and moved over the old one with
    os.replace, and on Windows that move fails with PermissionError, WinError 5, while another process has the file
    open, as a reader that takes no lock has for the length of its read. Seen on 2026-11-22: three
    `session.json.<pid>.tmp` beside the records of two sessions, each a whole hook that died at a move made once.
    Measured on Windows 11 with two processes reading one file in a loop and a third writing it: 11455 of 12014 single
    moves failed, and with the move made again, none of 127. p4conf.write_whole is the kit's one writer, and its move,
    p4conf.move_over, the one move."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def refused(self, times):
        """os.replace as a writer meets it while a reader has the file open: refused `times` times, and then as it
        is. Returns the files it was asked to move over and the patch that puts it in os.replace's place."""
        from unittest import mock
        real, asked = os.replace, []

        def replace(src, dst, **kw):
            asked.append(dst)
            if len(asked) <= times:
                raise PermissionError(13, "Access is denied", dst)
            return real(src, dst, **kw)
        return asked, mock.patch.object(p4conf.os, "replace", replace)

    def temps(self):
        return sorted(x for x in os.listdir(self.folder) if x.endswith(".tmp"))

    def held(self, name, text='{"n": 0}\n'):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return path

    def writers(self):
        """Each writer that moves a temp over a file, as a call that writes {"n": 1} to a path."""
        import issues
        import phi
        import puppeteer
        import relay
        return (("phi.write_atomic", lambda p: phi.write_atomic(p, '{"n": 1}\n')),
                ("relay._write_raw", lambda p: relay._write_raw(p, {"n": 1})),
                ("puppeteer._write", lambda p: puppeteer._write(p, '{"n": 1}\n')),
                ("issues._write", lambda p: issues._write(p, '{"n": 1}\n')),
                ("p4conf.write_whole of bytes", lambda p: p4conf.write_whole(p, b'{"n": 1}\n')))

    def test_a_write_that_meets_a_reader_and_then_succeeds_lands_and_leaves_no_temp(self):
        for k, (name, write) in enumerate(self.writers()):
            path = self.held(f"record-{k}.json")
            asked, patch = self.refused(3)
            with patch:
                write(path)
            self.assertEqual(len(asked), 4, f"{name}: refused three times and moved at the fourth")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"n": 1}, name)
            self.assertEqual(self.temps(), [], name)
        # p4.json's own writer, whose file every hook of every session reads
        asked, patch = self.refused(3)
        with patch:
            p4conf._write(self.folder, {"phi": {"upkeep": True}})
        self.assertEqual(len(asked), 4)
        self.assertEqual(p4conf.read_json(p4conf.path(self.folder)), {"phi": {"upkeep": True}})
        self.assertEqual(self.temps(), [])

    def test_a_write_that_stays_refused_says_so_once_its_wait_is_over_and_leaves_no_temp(self):
        import contextlib
        import time
        from unittest import mock
        for k, (name, write) in enumerate(self.writers()):
            path = self.held(f"record-{k}.json")
            asked, patch = self.refused(10 ** 9)
            waits = [mock.patch.object(p4conf, "WRITE_WAIT_S", 0.05)]
            if name == "relay._write_raw":
                import relay
                waits.append(mock.patch.object(relay, "REPLACE_WAIT_S", 0.05))
            if name == "puppeteer._write":
                import puppeteer
                waits.append(mock.patch.object(puppeteer, "REPLACE_S", 0.05))
            began = time.monotonic()
            with contextlib.ExitStack() as stack:
                for one in [patch] + waits:
                    stack.enter_context(one)
                with self.assertRaises(PermissionError, msg=name):
                    write(path)
            took = time.monotonic() - began
            self.assertGreaterEqual(took, 0.04, f"{name}: the wait was waited out")
            self.assertLess(took, 5, name)
            self.assertGreater(len(asked), 2, f"{name}: and the move made again meanwhile")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"n": 0}, f"{name}: the file is as it was")
            self.assertEqual(self.temps(), [], name)

    def test_a_temp_an_earlier_write_left_is_removed_at_the_next_write_of_its_file(self):
        """The three temps seen were each `<path>.<pid>.tmp` of a hook that had died hours before. The next write of
        that file removes a temp older than p4conf.TEMP_OLD_S, by any name the kit's writers gave one. A young one
        is another writer's, under way, and a temp of another file waits for that file's own next write."""
        import time
        import phi
        path = self.held("session.json")
        long_ago = time.time() - p4conf.TEMP_OLD_S - 5
        dead = [self.held(name) for name in ("session.json.12228.tmp", "session.json.33692.7044.tmp",
                                             "session.json.tmp", "session.json.k3x9q2ab.tmp")]
        elsewhere = self.held("ledger.json.12228.tmp")
        for old in dead + [elsewhere]:
            os.utime(old, (long_ago, long_ago))
        under_way = self.held("session.json.4321.tmp")
        phi.write_atomic(path, '{"n": 1}\n')
        self.assertEqual(self.temps(), ["ledger.json.12228.tmp", "session.json.4321.tmp"])
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"n": 1})
        self.assertTrue(os.path.exists(under_way) and os.path.exists(elsewhere))

    @unittest.skipUnless(os.name == "nt", "a move meets a reader as PermissionError on Windows")
    def test_no_write_is_lost_to_a_reader_that_has_the_file_open(self):
        """The race itself, for a second: a process reads the file in a loop, as the hooks of other sessions read a
        session's record, and every write here lands."""
        import subprocess
        import phi
        path = self.held("session.json")
        reader = ("import sys, time\n"
                  "path, end = sys.argv[1], time.time() + 1.0\n"
                  "while time.time() < end:\n"
                  "    try:\n"
                  "        with open(path, encoding='utf-8') as f:\n"
                  "            f.read()\n"
                  "    except OSError:\n"
                  "        pass\n")
        process = subprocess.Popen([sys.executable, "-I", "-c", reader, path])
        self.addCleanup(process.wait)               # before the folder goes, whatever the test met
        writes = 0
        while process.poll() is None:
            phi.write_atomic(path, json.dumps({"n": writes}) + "\n")
            writes += 1
        self.assertEqual(process.returncode, 0)
        self.assertGreater(writes, 3)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"n": writes - 1}, "the last write is the one the file holds")
        self.assertEqual(self.temps(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Names(unittest.TestCase):
    """What a plugin's files read of p4conf is in the p4conf.py of that plugin: each plugin holds a file of its own,
    so a name the split took from a plugin that still uses it fails here and not in a session."""

    def test_every_name_a_file_of_the_plugin_reads_of_p4conf_is_in_its_own(self):
        """Every .py file of the plugin is parsed with ast. Each attribute read from the name `p4conf` and from
        `PHI.p4conf`, an import inside a function included, and each `getattr(p4conf, "<text>")` is a name of the
        plugin's own p4conf. No file holds `from p4conf import` or `import p4conf as`, which this would not follow."""
        import ast
        plugin = SRC.parent
        wanted, followed = {}, []
        for path in sorted(plugin.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    base = node.value
                    if (isinstance(base, ast.Name) and base.id == "p4conf") or (
                            isinstance(base, ast.Attribute) and base.attr == "p4conf"
                            and isinstance(base.value, ast.Name) and base.value.id == "PHI"):
                        wanted.setdefault(node.attr, []).append(f"{path.name}:{node.lineno}")
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                      and len(node.args) > 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "p4conf"
                      and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
                    wanted.setdefault(node.args[1].value, []).append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom) and node.module == "p4conf":
                    followed.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Import) and any(a.name == "p4conf" and a.asname for a in node.names):
                    followed.append(f"{path.name}:{node.lineno}")
        self.assertTrue(wanted, "the plugin's files read p4conf")
        self.assertEqual(followed, [], "an import this case does not follow")
        self.assertEqual({n: at for n, at in wanted.items() if not hasattr(p4conf, n)}, {})

    def test_every_global_a_function_of_the_plugins_p4conf_reads_is_a_name_of_it(self):
        """The plugin's own p4conf.py is read with symtable: every name a function of it reads as a global is a name of
        the module or of builtins, so a name the split took from a function that still reads it fails here."""
        import builtins
        import symtable
        path = SRC / "p4conf.py"
        top = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
        known = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
        known |= {"__file__", "__name__"}
        missing = []

        def walk(table):
            for s in table.get_symbols():
                if s.is_global() and s.is_referenced() and s.get_name() not in known                         and not hasattr(builtins, s.get_name()):
                    missing.append(f"{s.get_name()} in {table.get_name()}")
            for child in table.get_children():
                walk(child)
        for child in top.get_children():
            walk(child)
        self.assertEqual(missing, [])
