#!/usr/bin/env python3
"""p4conf.py: one settings file for every p4 plugin, written when missing, merged over the defaults.

    python3 -I lbiza/plugins/p4-phi/scripts/test_p4conf.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p4conf  # noqa: E402

PLUGINS = HERE.parents[1]
COPIES = [PLUGINS / "p4-temportal" / "hooks" / "p4conf.py", PLUGINS / "p4-phi" / "scripts" / "p4conf.py"]


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

    def test_every_plugin_carries_the_same_copy(self):
        src = (HERE / "p4conf.py").read_bytes()
        for c in COPIES:
            self.assertEqual(c.read_bytes(), src, c)

    def test_every_setting_scratchpad_reads_has_its_default(self):
        """Each key temportal's scratchpad.py maps to a constant is in DEFAULTS, at the constant's own value, so a
        store's p4.json is never told it holds an unknown key."""
        import ast
        import re
        text = (PLUGINS / "p4-temportal" / "hooks" / "scratchpad.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                  if isinstance(t, ast.Name)}
        for key in ("scratch_sweep_minutes", "tmp_empty_idle_hours", "tmp_skip_dirs"):
            const = re.search(rf'"{key}": "(\w+)"', text).group(1)
            self.assertEqual(p4conf.DEFAULTS["scratchpad"][key], ast.literal_eval(consts[const]), key)

    def test_a_key_read_when_set_is_not_called_unknown(self):
        """phi.child_levels, phi.puppeteer_section and phi.puppeteer_chars are read when a project sets them and are
        never written by default, so a later change to the code's values reaches every store."""
        import contextlib
        import io
        for key in ("child_levels", "puppeteer_section", "puppeteer_chars"):
            self.assertNotIn(key, p4conf.DEFAULTS["phi"])
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": {"puppeteer_section": "", "puppeteer_chars": 9, "child_levels": {}}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(s["phi"]["puppeteer_chars"], 9)

    def test_every_query_setting_p4_reads_has_its_default(self):
        """Each key QUERY_SETTINGS in p4.py maps from recall.query is in DEFAULTS, at the constant's own value."""
        import ast
        tree = ast.parse((HERE / "p4.py").read_text(encoding="utf-8"))
        consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                  if isinstance(t, ast.Name)}
        names = ast.literal_eval(consts["QUERY_SETTINGS"])
        query = p4conf.DEFAULTS["recall"]["query"]
        self.assertEqual(sorted(names), sorted(query))
        for key, const in names.items():
            self.assertEqual(query[key], ast.literal_eval(consts[const]), key)

    def test_a_migration_archives_under_phi_and_nothing_stays_flat(self):
        """migrate --apply writes archive/ by its LAYOUT key, so after it and the layout move the top of .claude/p4
        holds no archive/."""
        import migrate
        from test_migrate import old_tree
        from test_store import NOW
        p4 = old_tree(self.p4)
        migrate.run(p4, None, apply=True, now=NOW)
        p4conf.migrate_layout(p4, commit=False)
        self.assertNotIn("archive", os.listdir(p4))
        self.assertTrue(os.path.isdir(p4conf.sub(p4, "archive")))

    def test_an_archive_at_the_top_moves_under_phi_at_a_start(self):
        """A store with archive/ at the top, one of its files differing from phi/archive/'s, is moved by a start:
        the older copy is set aside in phi/.layout-conflicts/archive/ and the move is committed."""
        import subprocess
        import time
        git = lambda *a: subprocess.run(["git", "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout
        top, new = os.path.join(self.p4, "archive", "x.md"), p4conf.sub(self.p4, "archive", "x.md")
        other = os.path.join(self.p4, "archive", "y.md")
        for f, text, age in ((top, "old", 100), (new, "new", 0), (other, "y", 0)):
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8") as h:
                h.write(text)
            os.utime(f, (time.time() - age, time.time() - age))
        git("init", "-q")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "before")
        lines = p4conf.migrate_layout(self.p4)
        self.assertTrue(any("archive" in l for l in lines), lines)
        self.assertNotIn("archive", os.listdir(self.p4))
        with open(new, encoding="utf-8") as h:
            self.assertEqual(h.read(), "new")
        self.assertTrue(os.path.isfile(p4conf.sub(self.p4, "archive", "y.md")))
        aside = os.path.join(self.p4, "phi", p4conf.LAYOUT_CONFLICTS, "archive", "x.md")
        with open(aside, encoding="utf-8") as h:
            self.assertEqual(h.read(), "old")
        self.assertEqual(git("status", "--porcelain", "--", "archive", "phi/archive"), "")
        self.assertIn("layout", git("log", "-1", "--format=%s"))

    def store(self, places=("archive",), n=20):
        """A git store with `n` tracked files in each earlier place -> a git function on it."""
        import subprocess
        git = lambda *a: subprocess.run(["git", "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout
        for place in places:
            for i in range(n):
                f = os.path.join(self.p4, place, f"a{i}.md")
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f, "w", encoding="utf-8") as h:
                    h.write(str(i))
        with open(os.path.join(self.p4, ".gitignore"), "w", encoding="utf-8") as h:
            h.write("archive/*.tmp\n")
        git("init", "-q")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "before")
        return git

    def cut(self, name, at=1):
        """Run a start whose `name` is cut at its `at`-th call, as a hook's timeout cuts it."""
        real, calls = getattr(p4conf, name), []

        def killed(*a, **k):
            calls.append(1)
            if len(calls) >= at:
                raise KeyboardInterrupt("the hook's timeout")
            return real(*a, **k)
        setattr(p4conf, name, killed)
        try:
            with self.assertRaises(KeyboardInterrupt):
                p4conf.migrate_layout(self.p4)
        finally:
            setattr(p4conf, name, real)

    def test_a_move_cut_before_its_commit_is_committed_at_the_next_start(self):
        """A start hook killed after the renames and before the commit leaves the move for the next start, which finds
        nothing left to move and still commits it."""
        git = self.store()
        self.cut("_commit_journal")
        self.assertNotIn("archive", os.listdir(self.p4), "the renames were done")
        self.assertNotEqual(git("status", "--porcelain"), "", "and not committed")
        p4conf.migrate_layout(self.p4)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertIn("layout", git("log", "-1", "--format=%s"))
        self.assertEqual(len(git("ls-files", "phi/archive").split()), 20)
        self.assertFalse(os.path.exists(p4conf._pending_path(self.p4)))

    def test_a_commit_that_returns_without_committing_keeps_the_record(self):
        git = self.store()
        real = p4conf.subprocess.run

        def no_ref(cmd, *a, **k):
            if "update-ref" in cmd:
                return p4conf.subprocess.CompletedProcess(cmd, 1, b"", b"cannot lock ref")
            return real(cmd, *a, **k)
        p4conf.subprocess.run = no_ref
        try:
            p4conf.migrate_layout(self.p4)
        finally:
            p4conf.subprocess.run = real
        self.assertTrue(os.path.isfile(p4conf._pending_path(self.p4)), "kept until the commit is in HEAD")
        self.assertNotIn("layout", git("log", "-1", "--format=%s"))
        p4conf.migrate_layout(self.p4)
        self.assertIn("layout", git("log", "-1", "--format=%s"))
        self.assertEqual(git("status", "--porcelain"), "")

    def test_an_edit_between_two_starts_stays_out_of_the_layout_commit(self):
        """The commit holds what the move wrote: a file edited at its new place and a .gitignore edited after the
        rewrite, between the cut start and the next, stay uncommitted."""
        git = self.store()
        self.cut("_commit_journal")
        moved = p4conf.sub(self.p4, "archive", "a3.md")
        with open(moved, "w", encoding="utf-8") as h:
            h.write("edited after the move")
        with open(os.path.join(self.p4, ".gitignore"), "a", encoding="utf-8") as h:
            h.write("edited.tmp\n")
        p4conf.migrate_layout(self.p4)
        self.assertIn("layout", git("log", "-1", "--format=%s"))
        self.assertEqual(git("show", "HEAD:phi/archive/a3.md"), "3")
        self.assertEqual(git("show", "HEAD:.gitignore"), "phi/archive/*.tmp\n")
        self.assertEqual(sorted(git("status", "--porcelain").split()), [".gitignore", "M", "M", "phi/archive/a3.md"])

    def test_a_start_cut_in_its_renames_is_finished_and_committed_at_the_next(self):
        git = self.store(places=("archive", "store"))
        self.cut("_move", at=2)
        self.assertNotIn("store", os.listdir(self.p4), "the first place moved")
        self.assertIn("archive", os.listdir(self.p4), "the second not")
        p4conf.migrate_layout(self.p4)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertEqual(len(git("ls-files", "phi/archive", "phi/store").split()), 40)
        self.assertEqual(git("ls-files", "archive", "store"), "")

    def test_a_failed_ignore_check_commits_no_untracked_file_and_keeps_the_record(self):
        git = self.store()
        with open(os.path.join(self.p4, "archive", "cache.bin"), "w", encoding="utf-8") as h:
            h.write("never tracked")
        real = p4conf.subprocess.run

        def broken(cmd, *a, **k):
            if "check-ignore" in cmd:
                return p4conf.subprocess.CompletedProcess(cmd, 128, b"", b"fatal")
            return real(cmd, *a, **k)
        p4conf.subprocess.run = broken
        try:
            p4conf.migrate_layout(self.p4)
        finally:
            p4conf.subprocess.run = real
        self.assertTrue(os.path.isfile(p4conf._pending_path(self.p4)))
        self.assertNotIn("layout", git("log", "-1", "--format=%s"))
        p4conf.migrate_layout(self.p4)
        self.assertIn("phi/archive/cache.bin", git("ls-files", "phi/archive").split())

    def test_an_edit_to_gitignore_before_the_start_stays_out_of_the_layout_commit(self):
        git = self.store()
        with open(os.path.join(self.p4, ".gitignore"), "a", encoding="utf-8") as h:
            h.write("mine.tmp" + chr(10))
        p4conf.migrate_layout(self.p4)
        self.assertEqual(git("show", "HEAD:.gitignore"), "phi/archive/*.tmp" + chr(10))
        self.assertEqual(git("status", "--porcelain"), " M .gitignore" + chr(10))
        with open(os.path.join(self.p4, ".gitignore"), encoding="utf-8") as h:
            self.assertEqual(h.read(), "phi/archive/*.tmp" + chr(10) + "mine.tmp" + chr(10))

    def test_a_record_with_a_half_written_last_line_is_still_committed(self):
        git = self.store()
        self.cut("_commit_journal")
        with open(p4conf._pending_path(self.p4), "a", encoding="utf-8") as h:
            h.write('{"m": ["archive/a1')
        p4conf.migrate_layout(self.p4)
        self.assertFalse(os.path.exists(p4conf._pending_path(self.p4)))
        self.assertEqual(git("status", "--porcelain"), "")

    def test_a_worktree_records_its_move_in_its_own_git_directory(self):
        import subprocess
        self.store()
        wt = os.path.join(self.p4, "..", os.path.basename(self.p4) + "-wt")
        self.addCleanup(shutil.rmtree, wt, True)
        subprocess.run(["git", "-C", self.p4, "worktree", "add", "-q", wt], capture_output=True, check=True)
        gd = subprocess.run(["git", "-C", wt, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True,
                            check=True).stdout.strip()
        self.assertEqual(os.path.normcase(os.path.normpath(p4conf._pending_path(wt))),
                         os.path.normcase(os.path.normpath(os.path.join(gd, p4conf.PENDING))))
        self.p4 = wt
        git = lambda *a: subprocess.run(["git", "-C", wt, *a], capture_output=True, text=True, check=True).stdout
        self.cut("_commit_journal")
        p4conf.migrate_layout(wt)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertEqual(len(git("ls-files", "phi/archive").split()), 20)

    def copy_of(self, gen, **query):
        """A second copy of p4conf.py, as another installed plugin would carry, at generation `gen` with
        recall.query defaults changed by `query`."""
        import copy
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"p4conf_gen{gen}", HERE / "p4conf.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.DEFAULTS = copy.deepcopy(mod.DEFAULTS)
        mod.DEFAULTS["recall"]["query"].update(query)
        mod.GEN = gen
        return mod

    def test_a_changed_default_reaches_a_store_load_wrote_it_into(self):
        """A value load wrote follows a newer generation's default; a value set by hand stays as it is."""
        p4conf.load(self.p4)
        d = self.read(record=True)
        d["recall"]["query"]["per_file"] = 7
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(d, f)
        s = self.copy_of(p4conf.GEN + 1, max_lines=9, per_file=4).load(self.p4)
        self.assertEqual(s["recall"]["query"]["max_lines"], 9, "written by load: follows the new default")
        self.assertEqual(s["recall"]["query"]["per_file"], 7, "set by hand: kept")
        self.assertEqual(self.read()["recall"]["query"]["max_lines"], 9)

    def test_two_copies_that_differ_on_a_default_settle_on_the_newer(self):
        """Two copies, both with the record, that differ on a default write p4.json at most twice in turn and settle
        on the newer generation's value."""
        old, new = self.copy_of(1, max_lines=5), self.copy_of(2, max_lines=9)
        writes = []
        for c in (old, new):
            real = c._write
            c._write = lambda p4, data, real=real: (writes.append(1), real(p4, data))
        for c in (old, new, old, new, old, new):
            c.load(self.p4, warn=False)
        self.assertLessEqual(len(writes), 2, "written by the first load, moved once by the newer")
        self.assertEqual(self.read()["recall"]["query"]["max_lines"], 9)
        self.assertEqual(old.load(self.p4)["recall"]["query"]["max_lines"], 9, "the older copy reads the newer value")

    def test_a_store_from_before_the_record_follows_today_s_default(self):
        """A store with no record, as this project's own, counts a value equal to a past default in HISTORY as
        written, so it moves to today's; a value no default ever had stays."""
        d = json.loads(json.dumps(p4conf.DEFAULTS))
        d["recall"]["teacher"]["model"] = "claude-fable-5-1"
        d["recall"]["query"]["per_file"] = 7
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(d, f)
        s = p4conf.load(self.p4)
        self.assertEqual(s["recall"]["teacher"]["model"], p4conf.DEFAULTS["recall"]["teacher"]["model"])
        self.assertEqual(s["recall"]["query"]["per_file"], 7)
        self.assertNotIn("recall.query.per_file", self.read(record=True)[p4conf.WRITTEN])

    def test_a_store_holding_the_old_web_default_moves_to_note(self):
        """ezexe/p4#243, row D1: a store load wrote at GEN 1 and a store from before the record both move from
        "answer" to "note"; a value set by hand stays."""
        stores = {}
        for name, value, record in (("written", "answer", True), ("no record", "answer", False),
                                    ("by hand", "shadow", True)):
            p4 = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, p4, True)
            d = json.loads(json.dumps(p4conf.DEFAULTS))
            d["recall"]["lookups"]["web"] = value
            if record:
                d[p4conf.WRITTEN] = {"recall.lookups.web": {"v": "answer", "gen": 1}}
            with open(p4conf.path(p4), "w", encoding="utf-8") as f:
                json.dump(d, f)
            stores[name] = p4conf.load(p4)["recall"]["lookups"]["web"]
        self.assertEqual(stores, {"written": "note", "no record": "note", "by hand": "shadow"})

    def test_gen_is_raised_with_every_change_of_defaults(self):
        """DEFAULTS is pinned to its GEN: a change of a default fails here until GEN is raised, the old value added to
        HISTORY and the pin below updated."""
        import hashlib
        pins = {1: "cc7604892f2635f2", 2: "13977bb862fc1973"}                     # append only: one more line for each GEN
        got = hashlib.sha256(json.dumps(p4conf.DEFAULTS, sort_keys=True).encode()).hexdigest()[:16]
        self.assertEqual(p4conf.GEN, max(pins))
        self.assertEqual(p4conf.GEN, len(pins), "no generation is skipped or replaced")
        self.assertEqual(pins[p4conf.GEN], got, "DEFAULTS changed: raise GEN, add the old value to HISTORY, pin it")

    def test_a_missing_file_is_written_with_every_default(self):
        s = p4conf.load(self.p4)
        self.assertEqual(s, p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(set(s), {"memory", "scratchpad", "phi", "temportal", "recall"})

    def test_the_retired_config_json_seeds_nothing(self):
        os.makedirs(p4conf.sub(self.p4, "models"))
        with open(p4conf.sub(self.p4, "models", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"teacher-model": "claude-opus-5-5", "inject": False, "teacher-cutoff": "2026-06"}, f)
        self.assertEqual(p4conf.load(self.p4), p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)

    def test_missing_keys_are_added_and_set_values_kept(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"recall": {"pinned_chars": 900, "once_was": "kept"}, "extra": 1}, f)
        s = p4conf.load(self.p4, warn=False)
        on_disk = self.read()
        self.assertEqual(on_disk["recall"]["pinned_chars"], 900)
        self.assertEqual(on_disk["recall"]["inject"], "rules-facts", "a missing key is added")
        self.assertEqual(on_disk["recall"]["once_was"], "kept", "an unknown key stays on disk, read by nothing")
        self.assertEqual(on_disk["memory"], p4conf.DEFAULTS["memory"])
        self.assertEqual(on_disk["extra"], 1, "an unknown key survives the rewrite")
        self.assertEqual(s["recall"]["pinned_chars"], 900)

    def test_a_retired_section_is_dropped_from_the_file(self):
        """A key of RETIRED, such as `plans` or `version`, leaves a p4.json that holds it at the next rewrite, with no
        unknown-key line, and nothing writes it again."""
        old = {k: v for k, v in p4conf.DEFAULTS.items() if k != "memory"}
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({**old, "plans": {"plans_dir": ".claude/plans", "owner_title": "ezexe"}, "version": 1}, f)
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s = p4conf.load(self.p4)
        self.assertEqual(err.getvalue(), "", "a retired key is dropped without an unknown-key line")
        for key in ("plans", "version"):
            self.assertNotIn(key, s)
            self.assertNotIn(key, self.read())
            self.assertNotIn(key, p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)

    def test_a_writer_holding_a_temp_file_does_not_block_another(self):
        """Two hooks of one event load at once: a temp file another writer still holds does not stop this write."""
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"memory": p4conf.DEFAULTS["memory"]}, f)
        os.mkdir(p4conf.path(self.p4) + ".tmp")          # the name the other writer would hold
        p4conf.load(self.p4, warn=False)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(sorted(os.listdir(self.p4)), sorted(["p4.json", "p4.json.tmp"]), "no temp file is left")

    def test_an_older_and_a_newer_copy_in_turn_rewrite_at_most_once(self):
        """An installed copy from before `version` was retired adds it back, and this copy must not drop it again at
        each load, or the two rewrite p4.json in turn."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("p4conf_older", HERE / "p4conf.py")
        older = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(older)
        older.DEFAULTS = {**older.DEFAULTS, "version": 1}
        older.RETIRED = ("plans",)
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

    def test_a_held_layout_lock_is_given_up_within_a_hook_timeout(self):
        import time
        lock = os.path.join(self.p4, "lock")
        open(lock, "w").close()
        t = time.monotonic()
        self.assertFalse(p4conf._take(lock))
        self.assertLess(time.monotonic() - t, 10, "recall gives up the lock within its own 10-second hook timeout")

    def test_set_aside_copies_moved_at_a_start_outlive_that_starts_sweep(self):
        """An old recall/.layout-conflicts/ moved whole to phi/.layout-conflicts/recall keeps its files' old times
        through the rename, so a 30-day sweep run by the same start would clear them unreported. Every file a move
        lands in a set-aside folder takes the move's time."""
        import time
        old = time.time() - 60 * 86400
        for rel in (("recall", "store", "a.txt"), ("recall", ".layout-conflicts", "store", "kept.txt")):
            f = os.path.join(self.p4, *rel)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8") as h:
                h.write("x")
            os.utime(f, (old, old))
        p4conf.migrate_layout(self.p4, commit=False)
        kept = os.path.join(self.p4, "phi", p4conf.LAYOUT_CONFLICTS, "recall", "store", "kept.txt")
        self.assertTrue(os.path.isfile(kept))
        cutoff = time.time() - 30 * 86400                # the sweep's rule for .layout-conflicts, faked
        self.assertGreater(os.path.getmtime(kept), cutoff, "the start that moved it would clear it")

    def test_configure_sets_only_values_that_differ_from_the_default(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"recall": {"query": {"max_lines": 9}}, "scratchpad": {"ignorable_ext": ["log"]}}, f)
        g = {"MAX_LINES": 5, "PER_FILE": 3}
        p4conf.configure(g, self.p4, "recall.query", {"max_lines": "MAX_LINES", "per_file": "PER_FILE"})
        self.assertEqual(g, {"MAX_LINES": 9, "PER_FILE": 3}, "per_file at its default leaves the patched 3")
        g = {"IGNORABLE_EXT": {"log", "tmp"}}
        p4conf.configure(g, self.p4, "scratchpad", {"ignorable_ext": "IGNORABLE_EXT"})
        self.assertEqual(g["IGNORABLE_EXT"], {"log"})


def _git(cwd, *args):
    import subprocess
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=60)


class ClaudeSettings(unittest.TestCase):
    """ezexe/p4#246: the store keeps the Claude Code settings it relies on in the project's local settings file."""

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

    def local(self, root=None):
        return os.path.join(root or self.project, ".claude", "settings.local.json")

    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def memory(self, root=None):
        return os.path.abspath(os.path.join(root or self.project, ".claude", "p4", "temportal", "memory")).replace(
            "\\", "/")

    def record(self, root=None):
        return os.path.join(root or self.project, ".claude", "p4", "claude-settings.json")

    def test_a_stores_first_start_writes_autoMemoryDirectory_and_leaves_a_users_key(self):
        """A fresh git repository whose local file holds only a key of the user's: the layout hook's first start
        adds autoMemoryDirectory naming the store's memory folder after it, keeps the user's key, and records only
        its own key in the store's ignored record."""
        import hook
        _git(self.project, "init", "-q")
        os.makedirs(os.path.dirname(self.local()))
        with open(self.local(), "w", encoding="utf-8") as f:
            json.dump({"spinnerTipsEnabled": False}, f)
        hook.init_layout(self.project)
        got = self.read(self.local())
        self.assertEqual({k: got[k] for k in ("spinnerTipsEnabled", "autoMemoryDirectory")},
                         {"spinnerTipsEnabled": False, "autoMemoryDirectory": self.memory()})
        self.assertEqual(list(got), ["spinnerTipsEnabled", "autoMemoryDirectory", "permissions"],
                         "the user's keys keep their order")
        self.assertTrue(os.path.isfile(self.record()), "the record is .claude/p4/claude-settings.json")
        rec = Path(self.record()).read_text(encoding="utf-8")
        self.assertIn("autoMemoryDirectory", rec)
        self.assertNotIn("spinnerTipsEnabled", rec)
        gi = Path(self.project, ".claude", "p4", ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("claude-settings.json", gi, "the record stays on this machine")
        before = (Path(self.local()).read_bytes(), os.stat(self.local()).st_mtime_ns)
        p4conf.keep_settings(self.project)
        self.assertEqual((Path(self.local()).read_bytes(), os.stat(self.local()).st_mtime_ns), before,
                         "a check that changes nothing writes nothing")

    def test_a_key_changed_by_hand_leaves_the_record_and_is_never_written_again(self):
        import hook
        hook.init_layout(self.project)
        self.assertEqual(self.read(self.local())["autoMemoryDirectory"], self.memory())
        d = self.read(self.local())
        d["autoMemoryDirectory"] = "D:/elsewhere/memory"
        with open(self.local(), "w", encoding="utf-8") as f:
            json.dump(d, f)
        p4conf.keep_settings(self.project)
        p4conf.keep_settings(self.project)
        self.assertEqual(self.read(self.local())["autoMemoryDirectory"], "D:/elsewhere/memory")
        self.assertNotIn("autoMemoryDirectory", Path(self.record()).read_text(encoding="utf-8"))

    def test_the_local_file_is_written_beside_the_project_file_on_windows(self):
        """On Windows Claude Code reads the local file in the session's own folder, so a session started in a
        worktree gets the key in that worktree's file, naming the main checkout's store."""
        main = self.project
        _git(main, "init", "-q")
        with open(os.path.join(main, "a.txt"), "w", encoding="utf-8") as f:
            f.write("a\n")
        _git(main, "add", "a.txt")
        _git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a")
        wt = os.path.join(self.tmp, "wt")
        self.assertEqual(_git(main, "worktree", "add", "-q", wt, "-b", "wt").returncode, 0)
        os.makedirs(os.path.join(main, ".claude", "p4"))
        p4conf.keep_settings(wt, platform="win32")
        self.assertEqual(self.read(self.local(wt))["autoMemoryDirectory"], self.memory(main))
        self.assertFalse(os.path.exists(self.local(main)), "the main checkout's file is not the one Windows reads")
        self.assertEqual(_git(wt, "check-ignore", "-q", ".claude/settings.local.json").returncode, 0,
                         "the file p4 created is kept out of git")
        p4conf.keep_settings(wt, platform="linux")
        self.assertEqual(self.read(self.local(main))["autoMemoryDirectory"], self.memory(main),
                         "elsewhere the main checkout's root holds it")

    def test_another_folder_named_by_the_user_is_left_to_win(self):
        """A user file naming another folder: no local key, which would override that choice."""
        conf = os.environ["CLAUDE_CONFIG_DIR"]
        os.makedirs(conf)
        with open(os.path.join(conf, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"autoMemoryDirectory": "D:/mine"}, f)
        os.makedirs(os.path.join(self.project, ".claude", "p4"))
        p4conf.keep_settings(self.project)
        self.assertNotIn("autoMemoryDirectory", self.read(self.local()))

    def test_a_key_of_the_security_class_is_named_and_never_written(self):
        """ezexe/p4#246: a permission key a store wants is named with its value and not written; the commit
        attribution is written only when the store gives a text."""
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        with open(p4conf.path(p4), "w", encoding="utf-8") as f:
            json.dump({"claude": {"attribution.commit": "Co-Authored-By: x <x@x>",
                                  "permissions.allow": ["Bash(ls *)"]}}, f)
        out = p4conf.keep_settings(self.project, tell=True)
        got = self.read(self.local())
        self.assertEqual(got["attribution"], {"commit": "Co-Authored-By: x <x@x>"})
        self.assertNotIn("Bash(ls *)", got["permissions"]["allow"], "a store's own permission key is never written")
        self.assertTrue(any("permissions.allow" in a and "Bash(ls *)" in a for a in out["asks"]), out)
        self.assertEqual(p4conf.keep_settings(self.project, tell=True)["asks"], [], "named once for one value")

    def rules(self, scripts):
        s = os.path.abspath(scripts).replace("\\", "/")
        cmds = [f'python -I -X utf8 "{s}/phi.py" *', f'python -I -X utf8 "{s}/p4.py" sync *']
        return [f"Bash({c})" for c in cmds] + [f"PowerShell({c})" for c in cmds]

    def test_the_two_allow_rules_are_p4s_own_entries_beside_the_users(self):
        """ezexe approved two allow rules, phi.py and p4.py sync, as Bash and on Windows PowerShell: after two checks
        each is in permissions.allow once, the user's own allow, ask and deny rules are untouched and in order, and
        no rule names catchup.py prune-cache."""
        os.makedirs(os.path.join(self.project, ".claude", "p4"))
        mine = {"allow": ["Bash(npm test)", "Read(./docs/**)"], "ask": ["Bash(git push *)"], "deny": ["Bash(rm *)"]}
        with open(self.local(), "w", encoding="utf-8") as f:
            json.dump({"permissions": mine}, f)
        for _ in range(2):
            p4conf.keep_settings(self.project, platform="win32")
        got = self.read(self.local())["permissions"]
        self.assertEqual(got["allow"], mine["allow"] + self.rules(HERE), "the user's rules first, each of p4's once")
        self.assertEqual((got["ask"], got["deny"]), (mine["ask"], mine["deny"]))
        self.assertFalse([r for r in got["allow"] if "prune-cache" in r or "catchup.py" in r])
        rec = json.loads(Path(self.record()).read_text(encoding="utf-8"))
        self.assertEqual(sorted(list(rec["rules"].values())[0]["entries"]), sorted(self.rules(HERE)))

    def test_the_rules_follow_the_plugin_folder_and_an_entry_deleted_by_hand_stays_gone(self):
        from unittest import mock
        os.makedirs(os.path.join(self.project, ".claude", "p4"))
        with open(self.local(), "w", encoding="utf-8") as f:
            json.dump({"permissions": {"allow": ["Bash(npm test)"]}}, f)
        p4conf.keep_settings(self.project, platform="win32")
        moved = os.path.join(self.tmp, "plugins", "p4-phi", "scripts")
        os.makedirs(moved)
        Path(moved, "phi.py").write_text("", encoding="utf-8")
        with mock.patch.object(p4conf, "PHI_SCRIPTS", moved):
            p4conf.keep_settings(self.project, platform="win32")
            allow = self.read(self.local())["permissions"]["allow"]
            self.assertEqual(allow, ["Bash(npm test)"] + self.rules(moved), "the old entries replaced by the new")
            d = self.read(self.local())
            d["permissions"]["allow"].remove(self.rules(moved)[0])
            with open(self.local(), "w", encoding="utf-8") as f:
                json.dump(d, f)
            p4conf.keep_settings(self.project, platform="win32")
            self.assertNotIn(self.rules(moved)[0], self.read(self.local())["permissions"]["allow"],
                             "deleted by hand: not written back")

    def test_the_users_autoMemoryEnabled_is_never_touched(self):
        """autoMemoryEnabled is ezexe's switch: a local `false` stays after two checks and the record never names it,
        while autoMemoryDirectory beside it stays p4's."""
        os.makedirs(os.path.join(self.project, ".claude", "p4"))
        with open(self.local(), "w", encoding="utf-8") as f:
            json.dump({"autoMemoryDirectory": self.memory(), "autoMemoryEnabled": False}, f)
        for _ in range(2):
            p4conf.keep_settings(self.project)
        got = self.read(self.local())
        self.assertIs(got["autoMemoryEnabled"], False)
        self.assertEqual(got["autoMemoryDirectory"], self.memory())
        rec = Path(self.record()).read_text(encoding="utf-8")
        self.assertNotIn("autoMemoryEnabled", rec)
        self.assertIn("autoMemoryDirectory", rec)

    def test_a_file_that_is_not_json_is_left_as_it_is(self):
        os.makedirs(os.path.join(self.project, ".claude", "p4"))
        with open(self.local(), "w", encoding="utf-8") as f:
            f.write("{not json")
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            p4conf.keep_settings(self.project)
        self.assertEqual(Path(self.local()).read_text(encoding="utf-8"), "{not json")
        self.assertIn("settings.local.json", err.getvalue())


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


class Watcher(unittest.TestCase):
    """ezexe/p4#246: the running Claude Code binary, read through CLAUDE_PID, sets off the whole settings check."""

    setUp = ClaudeSettings.setUp

    def stub(self, version):
        """A stand-in binary that prints `version` for --version and counts its runs."""
        self.count = os.path.join(self.tmp, "runs.txt")
        if os.name == "nt":
            p = os.path.join(self.tmp, "bin", "claude.cmd")
            _write(p, f'@echo off\r\necho x>>"{self.count}"\r\necho {version} (Claude Code)\r\n')
        else:
            p = os.path.join(self.tmp, "bin", "claude")
            _write(p, f'#!/bin/sh\necho x >> "{self.count}"\necho "{version} (Claude Code)"\n')
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
        _write(os.path.join(p4, "claude-settings.json"), {
            "files": {os.path.abspath(local).replace("\\", "/"): {"autoMemoryDirectory": {"v": mem, "gen": 1}}},
            "claude": {"path": stub, "size": 1, "mtime": 1.0, "version": "2.1.300"}})
        _write(local, {"spinnerTipsEnabled": False})
        env = {"CLAUDE_PID": "4242"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(p4conf, "exe_of_pid", lambda pid: stub if pid == 4242 else None):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            got = p4conf.watch(self.project, {"source": "resume", "hook_event_name": "SessionStart"})
            self.assertEqual(self.runs(), 1, "a changed binary is asked its version")
            with open(local, encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("autoMemoryDirectory"), mem, "the whole check wrote the key again")
            with open(os.path.join(p4, "claude-settings.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["claude"]["version"], "2.1.400")
            self.assertEqual(got["newer"], ("2.1.300", "2.1.400"), "the changelog between the two is read")
            p4conf.watch(self.project, {"source": "startup", "hook_event_name": "SessionStart"})
            self.assertEqual(self.runs(), 1, "the same binary: no --version runs")

    def test_the_process_claude_pid_names_is_read_from_the_system(self):
        p = p4conf.exe_of_pid(os.getpid())
        self.assertTrue(p and os.path.isfile(p), p)
        self.assertTrue(os.path.basename(p).lower().startswith("python"), p)

    def test_a_config_change_by_hand_leaves_the_record_and_never_blocks(self):
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        local = os.path.join(self.project, ".claude", "settings.local.json")
        p4conf.keep_settings(self.project)
        with open(local, encoding="utf-8") as f:
            d = json.load(f)
        d["autoMemoryDirectory"] = "D:/mine"
        _write(local, d)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        out = p4conf.watch(self.project, {"hook_event_name": "ConfigChange", "source": "local_settings",
                                          "file_path": local})
        self.assertEqual(out, {"asks": [], "newer": None}, "a ConfigChange check never blocks")
        with open(local, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["autoMemoryDirectory"], "D:/mine")
        self.assertNotIn("autoMemoryDirectory", json.dumps(p4conf.read_record(p4).get("files") or {}))

    def test_a_watched_term_in_a_newer_version_reaches_the_next_prompt_once(self):
        p4 = os.path.join(self.project, ".claude", "p4")
        os.makedirs(p4)
        text = ("# Changelog\n\n## 2.1.402\n\n- Fixed the spinner\n\n## 2.1.401\n\n- `ConfigChange` hooks now get a"
                " new field\n\n## 2.1.300\n\n- `autoMemoryDirectory` added\n")
        hits = p4conf.read_changelog(p4, "2.1.300", "2.1.401", text=text)
        self.assertEqual([(t, v, i) for t, v, i, _ in hits], [("ConfigChange", "2.1.401", "ezexe/p4#246")],
                         "only the sections after the recorded version up to the new one")
        with open(os.path.join(p4, *p4conf.WATCH_PAGE), encoding="utf-8") as f:
            self.assertIn("`ConfigChange` in 2.1.401", f.read())
        got = p4conf.claim_watch(p4)
        self.assertEqual(len(got), 1)
        self.assertIn("ConfigChange", got[0])
        self.assertIn("2.1.401", got[0])
        self.assertIn("ezexe/p4#246", got[0])
        self.assertEqual(p4conf.claim_watch(p4), [], "one session gets the line once")

    def test_the_issues_workers_terms_are_watched_when_their_file_is_there(self):
        from unittest import mock
        path = os.path.join(self.tmp, "limits.json")
        _write(path, [{"repo": "ezexe/p4", "issue": 999, "title": "t", "behaviour": "b", "source": "s",
                      "changes_when": "c", "terms": ["fooSetting"]}])
        self.assertEqual(p4conf.watched_terms(path)["fooSetting"], "ezexe/p4#999")
        self.assertEqual(p4conf.watched_terms(os.path.join(self.tmp, "none.json")), p4conf.WATCHED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
