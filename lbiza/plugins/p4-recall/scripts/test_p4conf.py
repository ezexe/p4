#!/usr/bin/env python3
"""p4conf.py: one settings file for every p4 plugin, written when missing, merged over the defaults.

    python3 -I lbiza/plugins/p4-recall/scripts/test_p4conf.py
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
COPIES = [PLUGINS / "p4-memory" / "hooks" / "p4conf.py", PLUGINS / "p4-scratchpad" / "hooks" / "p4conf.py",
          PLUGINS / "p4-plans" / "skills" / "plan-planner" / "scripts" / "p4conf.py"]


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

    def test_a_missing_file_is_written_with_every_default(self):
        s = p4conf.load(self.p4)
        self.assertEqual(s, p4conf.DEFAULTS)
        self.assertEqual(self.read(), p4conf.DEFAULTS)
        self.assertEqual(set(s), {"version", "memory", "scratchpad", "recall", "plans"})

    def test_the_retired_config_json_seeds_it(self):
        os.makedirs(os.path.join(self.p4, "models"))
        with open(os.path.join(self.p4, "models", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"teacher-model": "claude-opus-5-5", "inject": False, "teacher-cutoff": "2026-06"}, f)
        t = p4conf.load(self.p4)["recall"]
        self.assertEqual((t["teacher"]["model"], t["teacher"]["cutoff"], t["inject"]), ("claude-opus-5-5", "2026-06", False))
        self.assertEqual(self.read()["recall"]["teacher"]["model"], "claude-opus-5-5")

    def test_missing_keys_are_added_and_set_values_kept(self):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"plans": {"changelog": "HISTORY.md", "owner_title": "the boss"}, "extra": 1}, f)
        s = p4conf.load(self.p4, warn=False)
        on_disk = self.read()
        self.assertEqual(on_disk["plans"]["changelog"], "HISTORY.md")
        self.assertEqual(on_disk["plans"]["archive_branch"], "plans", "a missing key is added")
        self.assertEqual(on_disk["plans"]["owner_title"], "the boss", "a retired key stays on disk, read by nothing")
        self.assertEqual(on_disk["memory"], p4conf.DEFAULTS["memory"])
        self.assertEqual(on_disk["extra"], 1, "an unknown key survives the rewrite")
        self.assertEqual(s["plans"]["plans_dir"], ".claude/plans")

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
