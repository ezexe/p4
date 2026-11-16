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

    def read(self):
        with open(p4conf.path(self.p4), encoding="utf-8") as f:
            return json.load(f)

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

    def test_a_missing_file_is_written_with_every_default(self):
        s = p4conf.load(self.p4)
        self.assertEqual(s, p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(set(s), {"memory", "scratchpad", "phi", "temportal", "recall"})

    def test_the_retired_config_json_seeds_it(self):
        os.makedirs(p4conf.sub(self.p4, "models"))
        with open(p4conf.sub(self.p4, "models", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"teacher-model": "claude-opus-5-5", "inject": False, "teacher-cutoff": "2026-06"}, f)
        t = p4conf.load(self.p4)["recall"]
        self.assertEqual((t["teacher"]["model"], t["teacher"]["cutoff"], t["inject"]), ("claude-opus-5-5", "2026-06", False))
        self.assertEqual(self.read()["recall"]["teacher"]["model"], "claude-opus-5-5")

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

    def test_configure_sets_only_values_that_differ_from_the_default(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"recall": {"query": {"max_lines": 9}}, "scratchpad": {"ignorable_ext": ["log"]}}, f)
        g = {"MAX_LINES": 5, "PER_FILE": 3}
        p4conf.configure(g, self.p4, "recall.query", {"max_lines": "MAX_LINES", "per_file": "PER_FILE"})
        self.assertEqual(g, {"MAX_LINES": 9, "PER_FILE": 3}, "per_file at its default leaves the patched 3")
        g = {"IGNORABLE_EXT": {"log", "tmp"}}
        p4conf.configure(g, self.p4, "scratchpad", {"ignorable_ext": "IGNORABLE_EXT"})
        self.assertEqual(g["IGNORABLE_EXT"], {"log"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
