"""Offline tests for make_venv.py: it holds no build of its own, runs p4-phi's `p4.py venv` for this checkout with
the arguments it was given, returns that command's code, and names an environment it built before at the checkout's
root without removing it. Each test's tree is removed after it.

    python -m pytest tests/scripts/test_make_venv.py
"""

import contextlib
import io
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_venv as m  # noqa: E402


class Script(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.calls = []
        self.addCleanup(setattr, m, "subprocess", m.subprocess)
        self.addCleanup(setattr, m, "OLD", m.OLD)
        m.subprocess = types.SimpleNamespace(call=lambda cmd: self.calls.append(cmd) or 3)
        m.OLD = self.tmp / ".venv"

    def test_it_is_in_lbiza_scripts_and_names_the_plugins_p4_py(self):
        """The script is in lbiza/scripts/, and its ROOT is the checkout's root, the folder that holds the catalog
        .claude-plugin/marketplace.json, so the p4.py it runs is this checkout's own."""
        self.assertTrue((m.ROOT / ".claude-plugin" / "marketplace.json").is_file(), m.ROOT)
        self.assertEqual(Path(m.__file__).resolve(), m.ROOT / "lbiza" / "scripts" / "make_venv.py")
        self.assertTrue(m.P4PY.is_file(), m.P4PY)
        self.assertIn('argv[0] == "venv"', m.P4PY.read_text(encoding="utf-8"))

    def test_it_runs_p4_py_venv_for_this_checkout_and_returns_its_code(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(m.main(["--check", "--no-torch"]), 3)
        self.assertEqual(self.calls, [[sys.executable, "-I", "-X", "utf8", str(m.P4PY), "venv", "--p4", str(m.ROOT),
                                       "--check", "--no-torch"]])
        self.assertEqual(out.getvalue(), "", "no environment at the root from before: nothing more is said")

    def test_an_environment_at_the_root_from_before_is_named_and_left(self):
        m.OLD.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(m.main([]), 3)
        self.assertIn(str(m.OLD), out.getvalue())
        self.assertIn("remove that folder by hand", out.getvalue())
        self.assertTrue(m.OLD.is_dir(), "nothing is removed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
