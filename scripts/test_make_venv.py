"""Offline tests for make_venv.py: where it looks for ezexe/phi, which interpreter it names, --check without a .venv,
a build on a machine with no torch, and the oldest Python ezexe/phi installs on.

    python3 scripts/test_make_venv.py
"""

import contextlib
import io
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
        """Every torch install fails, as on an Intel Mac on Python 3.14: ezexe/phi goes in with --no-deps beside numpy,
        the requirements still install, and the run ends ready rather than failing."""
        v.python_of(v.VENV).parent.mkdir(parents=True)
        v.python_of(v.VENV).write_text("")
        self.phi(self.tmp / "phi")
        calls = []

        def fake_run(*cmd):
            calls.append([str(c) for c in cmd])
            return 1 if "torch" in [str(c) for c in cmd] else 0
        real_run, real_missing, real_sub = v.run, v.missing, v.subprocess
        v.run, v.missing = fake_run, lambda py: ["torch", "phi_prune", "phi_rank"]
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

    def requires(self, spec):
        """An ezexe/phi checkout beside the p4 checkout whose pyproject.toml has the given requires-python line."""
        phi = self.phi(self.tmp / "phi")
        (phi / "pyproject.toml").write_text(f'[project]\nname = "phi-prune"\n{spec}\n', encoding="utf-8")
        return phi

    def faked(self, version, venv=None):
        """main runs on Python `version` with every process faked; with `venv`, .venv exists and its interpreter
        reports that version. Returns the commands main would have run."""
        calls, real = [], (v.run, v.missing, v.subprocess, v.sys)

        def restore():
            v.run, v.missing, v.subprocess, v.sys = real
        self.addCleanup(restore)
        v.run, v.missing = (lambda *cmd: calls.append(cmd) or 0), (lambda py: [])
        answer = " ".join(map(str, venv)) if venv else ""
        v.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=answer))
        v.sys = types.SimpleNamespace(version_info=version, version=".".join(map(str, version)),
                                      executable=sys.executable)
        if venv:
            v.python_of(v.VENV).parent.mkdir(parents=True)
            v.python_of(v.VENV).write_text("")
        return calls

    def test_a_python_older_than_ezexe_phi_needs_stops_before_the_venv(self):
        self.requires('requires-python = ">=3.11"')
        calls = self.faked((3, 10, 14))
        with self.assertRaises(SystemExit) as stop:
            v.main([])
        self.assertIn("ezexe/phi needs Python 3.11 or newer, and this is Python 3.10.14", str(stop.exception))
        self.assertEqual(calls, [], "nothing ran, so no .venv was made")

    def test_the_oldest_python_ezexe_phi_accepts_makes_the_venv(self):
        self.requires('requires-python = ">=3.11"')
        calls = self.faked((3, 11, 0))
        self.assertEqual(v.main([]), 0)
        self.assertIn("venv", [str(c) for c in calls[0]], "the venv was made")

    def test_ezexe_phi_from_github_is_held_to_its_known_floor(self):
        calls = self.faked((3, 9, 18))
        with self.assertRaises(SystemExit) as stop:
            v.main([])
        self.assertIn("ezexe/phi needs Python 3.10 or newer", str(stop.exception))
        self.assertEqual(calls, [])

    def test_a_checkout_that_sets_no_floor_takes_any_python(self):
        self.phi(self.tmp / "phi")
        self.faked((3, 8, 18))
        self.assertEqual(v.main([]), 0)

    def test_the_floor_is_held_against_the_venvs_own_python(self):
        """The Python that runs ezexe/phi is .venv's own once it exists: a 3.9 tops up a 3.12 .venv, and a 3.12
        stops at a 3.9 .venv."""
        self.requires('requires-python = ">=3.10"')
        self.faked((3, 9, 6), venv=(3, 12, 4))
        self.assertEqual(v.main([]), 0)
        calls = self.faked((3, 12, 4), venv=None)
        v.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout="3 9 18"))
        with self.assertRaises(SystemExit) as stop:
            v.main([])
        self.assertIn("and .venv runs Python 3.9.18; remove .venv", str(stop.exception))
        self.assertEqual(calls, [])

    def test_a_python_older_than_this_script_needs_stops_before_anything_runs(self):
        self.phi(self.tmp / "phi")
        calls = self.faked((3, 6, 15))
        for argv in ([], ["--check"]):
            with self.assertRaises(SystemExit) as stop:
                v.main(argv)
            self.assertIn("this script needs Python 3.7 or newer, and this is Python 3.6.15", str(stop.exception))
        self.assertEqual(calls, [])

    def test_the_no_torch_line_names_the_venvs_python(self):
        self.requires('requires-python = ">=3.10"')
        self.faked((3, 9, 6), venv=(3, 13, 1))
        v.run, v.missing = (lambda *cmd: 1 if "torch" in map(str, cmd) else 0), (lambda py: ["torch"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(v.main([]), 0)
        self.assertIn("on Python 3.13, so .venv is finished without it", out.getvalue())

    def test_requires_python_forms(self):
        forms = {'requires-python = ">=3.10,<4"': (3, 10, 0), 'requires-python = ">= 3.10"': (3, 10, 0),
                 'requires-python = "~=3.11"': (3, 11, 0), 'requires-python = "==3.11.*"': (3, 11, 0),
                 'requires-python = ">3.10"': (3, 10, 1), 'requires-python = ">=3.10.2"': (3, 10, 2),
                 "requires-python = '>=3.11'": (3, 11, 0), 'requires-python = "<4"': None,
                 '# requires-python = ">=3.12"\nrequires-python = ">=3.10"': (3, 10, 0), "": None}
        for line, floor in forms.items():
            self.assertEqual(v.python_floor(self.requires(line), True), floor, line)
            (self.tmp / "phi" / "pyproject.toml").unlink()
            (self.tmp / "phi").rmdir()
        self.assertEqual(v.python_floor(v.PHI_GIT, False), v.PHI_PYTHON)

    def test_a_named_path_that_is_not_phi_stops_with_a_checkout_beside(self):
        """--phi names the checkout to install, so a named folder that is no ezexe/phi checkout stops before anything
        runs, even with an ezexe/phi checkout at ../phi."""
        self.phi(self.tmp / "phi")
        (self.tmp / "notphi").mkdir()
        calls = self.faked((3, 12, 4))
        with self.assertRaises(SystemExit) as stop:
            v.main(["--phi", str(self.tmp / "notphi")])
        self.assertIn("is not an ezexe/phi checkout", str(stop.exception))
        self.assertEqual(calls, [], "nothing ran, so no .venv was made")

    def test_the_known_floor_is_that_of_the_ezexe_phi_beside_this_checkout(self):
        phi = self._root.parent / "phi"
        if not (phi / "pyproject.toml").is_file():
            self.skipTest(f"no ezexe/phi checkout at {phi}")
        self.assertEqual(v.python_floor(phi, True), v.PHI_PYTHON)


if __name__ == "__main__":
    unittest.main(verbosity=1)
