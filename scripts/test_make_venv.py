"""Offline tests for make_venv.py: where it looks for phi, which interpreter it names, --check without a .venv.

    python3 scripts/test_make_venv.py
"""

import os
import sys
import tempfile
import types
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

    def test_no_torch_build_finishes_the_venv_without_it(self):
        """Every torch install fails (an Intel Mac on Python 3.14): phi goes in with --no-deps beside numpy, the
        requirements still install, and the run ends ready rather than failing."""
        v.python_of(v.VENV).parent.mkdir(parents=True)
        v.python_of(v.VENV).write_text("")
        self.phi(self.tmp / "phi")
        calls = []

        def fake_run(*cmd):
            calls.append([str(c) for c in cmd])
            return 1 if "torch" in [str(c) for c in cmd] else 0
        real_run, real_missing, real_sub = v.run, v.missing, v.subprocess
        v.run, v.missing = fake_run, lambda py: ["torch", "phi_prune", "phi_rank", "phi_serve"]
        v.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout="3.14.10"))
        try:
            self.assertEqual(v.main([]), 0)
        finally:
            v.run, v.missing, v.subprocess = real_run, real_missing, real_sub
        torch_tries = [c for c in calls if "torch" in c]
        self.assertEqual(len(torch_tries), 2, "the CPU wheels, then PyPI")
        phi = [c for c in calls if "-e" in c]
        self.assertEqual(len(phi), 1)
        self.assertIn("--no-deps", phi[0])
        self.assertTrue(any(c[-1] == "numpy" for c in calls))
        self.assertTrue(any(str(v.REQUIREMENTS) in c for c in calls))

    def test_the_module_is_this_folders_script(self):
        self.assertTrue(hasattr(v, "phi_source"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
