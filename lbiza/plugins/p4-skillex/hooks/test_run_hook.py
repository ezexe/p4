"""test_run_hook.py: run-hook.sh, run with sh against a stub plugin root.

    python -I -X utf8 lbiza/plugins/p4-skillex/hooks/test_run_hook.py
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("sh"), "no sh on PATH")
class RunHook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p4-skillex-runner-"))
        self.root = self.tmp / "root"
        (self.root / "hooks").mkdir(parents=True)
        shutil.copy(HERE / "run-hook.sh", self.root / "hooks" / "run-hook.sh")
        (self.root / "hooks" / "skillex.py").write_text("print('ran')\n")
        self.data = self.tmp / "data"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, *args):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=self.root.as_posix(), CLAUDE_PLUGIN_DATA=self.data.as_posix(),
                   OS="Windows_NT")
        return subprocess.run(["sh", (self.root / "hooks" / "run-hook.sh").as_posix(), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def test_the_proven_python_is_kept_in_the_plugin_data_folder(self):
        out = self.run_hook("start")
        self.assertIn("ran", out.stdout)
        self.assertEqual(out.returncode, 0)
        self.assertTrue((self.data / ".python").is_file(), "kept across updates, outside the checkout")
        self.assertFalse((self.root / ".python").exists())
        self.assertIn("ran", self.run_hook("start").stdout, "the second run uses the kept interpreter")


if __name__ == "__main__":
    unittest.main()
