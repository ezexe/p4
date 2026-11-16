"""Deciding tests for run-hook.sh: run it with sh against a stub plugin root."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class RunHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        (self.root / "hooks").mkdir(parents=True)
        shutil.copy(HERE / "run-hook.sh", self.root / "hooks" / "run-hook.sh")
        (self.root / "hooks" / "lifetime.py").write_text("print('ran')\n")
        self.data = self.tmp / "data"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, *args):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=self.root.as_posix(), CLAUDE_PLUGIN_DATA=self.data.as_posix(), OS="Windows_NT")
        return subprocess.run(["sh", (self.root / "hooks" / "run-hook.sh").as_posix(), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_python_cached_in_plugin_data(self):
        out = self.run_hook("lifetime", "sweep")
        self.assertIn("ran", out.stdout)
        self.assertTrue((self.data / ".python").is_file())
        self.assertFalse((self.root / ".python").exists())


if __name__ == "__main__":
    unittest.main()
