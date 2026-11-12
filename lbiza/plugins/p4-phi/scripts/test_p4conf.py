#!/usr/bin/env python3
"""p4conf.py: one settings file for every p4 plugin, written when missing, merged over the defaults.

    python3 -I lbiza/plugins/p4-phi/scripts/test_p4conf.py
"""

import json
import os
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
        self.assertEqual(set(s), {"version", "memory", "scratchpad", "phi", "temportal", "recall"})

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
        """No plugin reads `plans` any more (the two skills went back to their repositories): a p4.json that still
        holds the section loses it at the next load, and nothing writes it again."""
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({**p4conf.DEFAULTS, "plans": {"plans_dir": ".claude/plans", "owner_title": "the boss"}}, f)
        s = p4conf.load(self.p4, warn=False)
        self.assertNotIn("plans", s)
        self.assertNotIn("plans", self.read())
        self.assertNotIn("plans", p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)

    def test_a_broken_file_is_never_overwritten(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(p4conf.load(self.p4, warn=False), p4conf.DEFAULTS)
        with open(p4conf.path(self.p4), encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")

    def test_no_directory_no_file(self):
        gone = os.path.join(self.p4, "absent")
        self.assertEqual(p4conf.load(gone), p4conf.DEFAULTS)
        self.assertFalse(os.path.exists(gone))

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
