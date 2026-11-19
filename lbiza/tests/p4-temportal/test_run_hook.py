"""Deciding tests for run-hook.sh: run it with sh against a stub plugin root."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "plugins" / "p4-temportal" / "hooks"


class RunHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        (self.root / "hooks").mkdir(parents=True)
        shutil.copy(SRC / "run-hook.sh", self.root / "hooks" / "run-hook.sh")
        shutil.copy(SRC / "find-python.sh", self.root / "hooks" / "find-python.sh")
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

    def test_a_missing_finder_ends_in_the_message_and_exit_0(self):
        (self.root / "hooks" / "find-python.sh").unlink()
        out = self.run_hook("lifetime", "sweep")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("no working python found", json.loads(out.stdout)["systemMessage"])

    def test_an_unknown_part_prints_a_system_message(self):
        out = self.run_hook("nosuch", "sweep")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("unknown part 'nosuch'", json.loads(out.stdout)["systemMessage"])

    def test_the_compact_part_says_a_failure_on_stderr_and_prints_nothing(self):
        """At PreCompact a hook's stdout is the summary's instructions, by https://code.claude.com/docs/en/hooks.md,
        "PreCompact output", so a runner that finds no python prints nothing there and says so on stderr."""
        (self.root / "hooks" / "find-python.sh").unlink()
        out = self.run_hook("compact", "keep")
        self.assertEqual((out.returncode, out.stdout), (0, ""), out.stderr)
        self.assertIn("no working python found", out.stderr)

    def test_find_python_equals_p4_phis(self):
        phi = SRC.parent.parent / "p4-phi" / "hooks" / "find-python.sh"
        if not phi.is_file():
            self.skipTest("p4-phi is not beside this plugin")
        self.assertEqual((SRC / "find-python.sh").read_bytes(), phi.read_bytes())
        self.assertNotIn("for c in $order", (SRC / "run-hook.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
