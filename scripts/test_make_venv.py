"""Offline tests for make_venv.py: where it looks for phi, which interpreter it names, --check without a .venv.

    python3 scripts/test_make_venv.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_venv as v  # noqa: E402


class Venv(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "p4"
        self.root.mkdir()
        self._root, self._venv = v.ROOT, v.VENV
        v.ROOT, v.VENV = self.root, self.root / ".venv"

    def tearDown(self):
        v.ROOT, v.VENV = self._root, self._venv

    def phi(self, where):
        where.mkdir(parents=True)
        (where / "pyproject.toml").write_text('[project]\nname = "phi-prune"\n', encoding="utf-8")
        return where

    def test_phi_from_the_sibling_checkout_else_github(self):
        self.assertEqual(v.phi_source(None), (v.PHI_GIT, False))
        sib = self.phi(self.tmp / "phi")
        self.assertEqual(v.phi_source(None), (sib.resolve(), True))
        other = self.phi(self.tmp / "elsewhere" / "phi")
        self.assertEqual(v.phi_source(str(other)), (other.resolve(), True))

    def test_a_named_path_that_is_not_phi_stops(self):
        (self.tmp / "notphi").mkdir()
        with self.assertRaises(SystemExit):
            v.phi_source(str(self.tmp / "notphi"))

    def test_interpreter_path_per_platform(self):
        py = v.python_of(Path("x"))
        self.assertEqual(py, Path("x/Scripts/python.exe") if os.name == "nt" else Path("x/bin/python"))

    def test_check_without_a_venv_says_so(self):
        self.assertEqual(v.main(["--check"]), 1)
        self.assertFalse(v.VENV.exists(), "--check never creates .venv")

    def test_the_module_is_this_folders_script(self):
        self.assertTrue(hasattr(v, "phi_source"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
