#!/usr/bin/env python3
"""conf.py, the command `phi.py conf`: a setting of p4.json is written as its reader takes it and read back.

    python -m pytest tests/p4-phi/test_conf.py
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import conf  # noqa: E402
import p4conf  # noqa: E402


class Conf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self._tmp.name, "proj", ".claude", "p4")
        os.makedirs(self.store)
        config = os.path.join(self._tmp.name, "claude-config")
        os.makedirs(config)
        self._env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config})
        self._env.start()
        for k in [k for k in os.environ if k.startswith("P4_")]:
            os.environ.pop(k)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def held(self, key):
        with open(p4conf.path(self.store), encoding="utf-8") as f:
            return p4conf._get(json.load(f), key)

    def test_a_key_is_written_as_its_reader_takes_it_and_read_back(self):
        status, lines = conf.put(self.store, "phi.new_issues", "false")
        self.assertEqual((status, lines), (0, ["phi.new_issues = false"]))
        self.assertIs(self.held("phi.new_issues"), False)
        self.assertEqual(conf.put(self.store, "phi.worktree_python", ".venv/Scripts/python.exe")[0], 0)
        self.assertEqual(self.held("phi.worktree_python"), ".venv/Scripts/python.exe")
        self.assertEqual(conf.show(self.store, "phi.max_depth"), ["phi.max_depth = 3"])
        self.assertEqual(conf.unset(self.store, "phi.new_issues")[0], 0)
        self.assertIs(self.held("phi.new_issues"), True)

    def test_what_does_not_fit_or_is_not_its_to_write_changes_nothing(self):
        p4conf.load(self.store)
        with open(p4conf.path(self.store), encoding="utf-8") as f:
            before = f.read()
        for key, text in (("phi.max_depth", "deep"), ("phi.cards", "0123456789"), ("phi.upkeep", "true"),
                          ("permissions.allow", "[]"), ("claude.plansDirectory", "x")):
            self.assertEqual(conf.put(self.store, key, text)[0], 2, key)
        with open(p4conf.path(self.store), encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertIn("phi.worktree_python = unset", conf.show(self.store))
