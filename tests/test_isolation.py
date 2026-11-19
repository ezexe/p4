"""What conftest.py gives every test: a temp folder, a home and git settings of its own, and none of the caller's
session, API or GitHub variables."""
import os
import subprocess
import tempfile
import unittest

import conftest


class Isolation(unittest.TestCase):
    def test_no_variable_of_the_callers_session_or_account_reaches_a_test(self):
        """A session's ids, an API key, a GitHub token and every P4_ switch are removed, in any case of letters, and a
        variable that only points a test at fixtures passes through. A switch a test file sets for itself when it
        is imported, as test_phi.py sets P4_PHI, is that file's own."""
        names = ["PATH", "CLAUDE_CODE_SESSION_ID", "claude_x", "ANTHROPIC_API_KEY", "P4_LIVE", "P4_FIXTURES",
                 "P4_MAC_STORE", "P4_PHI_TEST_TMP", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACTIONS", "HOME", "OTHER"]
        self.assertEqual([n for n in names if not conftest.is_the_callers(n)],
                         ["PATH", "P4_FIXTURES", "P4_MAC_STORE", "P4_PHI_TEST_TMP", "GITHUB_ACTIONS", "HOME", "OTHER"])

    def test_the_temp_folder_is_the_working_folder_and_is_named_as_the_file_system_holds_it(self):
        """A caller's temp folder spelled by an 8.3 short name on Windows, as a GitHub runner's TEMP is
        C:\\Users\\RUNNER~1\\AppData\\Local\\Temp, or through a link elsewhere, reaches no test: git and
        os.path.realpath name a folder in full, so a test that compares a path it made with one the code under test
        resolved would meet two spellings of one folder."""
        tmp = tempfile.gettempdir()
        self.assertEqual(os.environ["TEMP"], conftest.TEMP)
        self.assertEqual((os.environ["TMP"], os.environ["TMPDIR"]), (conftest.TEMP, conftest.TEMP))
        self.assertEqual(conftest.TEMP, os.path.realpath(conftest.TEMP))
        self.assertEqual(os.path.normcase(os.getcwd()), os.path.normcase(conftest.TEMP))
        self.assertTrue(os.path.normcase(os.path.realpath(tmp)).startswith(os.path.normcase(conftest.TEMP)),
                        "tempfile makes its folders in the worker's own temp folder")

    def test_the_home_folder_is_the_workers_own(self):
        home = os.environ["HOME"]
        self.assertEqual(os.path.dirname(home), os.path.dirname(conftest.TEMP))
        self.assertEqual(os.path.normcase(os.path.expanduser("~")), os.path.normcase(home))
        if os.name == "nt":
            self.assertEqual(os.environ["USERPROFILE"], home)
            self.assertTrue(os.environ["APPDATA"].startswith(home) and os.environ["LOCALAPPDATA"].startswith(home))
            self.assertTrue(os.path.isdir(os.environ["APPDATA"]) and os.path.isdir(os.environ["LOCALAPPDATA"]))

    def test_git_reads_the_workers_settings_alone(self):
        r = subprocess.run(["git", "config", "--show-origin", "--list"], capture_output=True, text=True)
        rows = [line.split("\t", 1) for line in r.stdout.splitlines()]
        # git prints a Windows path quoted, with its backslashes doubled
        origins = {os.path.normcase(os.path.normpath(o[len("file:"):].strip('"').replace("\\\\", "\\")))
                   for o, _ in rows}
        self.assertEqual(origins, {os.path.normcase(os.path.normpath(os.environ["GIT_CONFIG_GLOBAL"]))},
                         r.stdout + r.stderr)
        got = dict(kv.split("=", 1) for _, kv in rows)
        self.assertEqual((got["core.autocrlf"], got["user.name"]), ("false", "tests"))
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        self.assertNotEqual(top.returncode, 0, "the temp folder has no repository above it: " + top.stdout)


class PutBack(unittest.TestCase):
    """Two tests that each leave state behind and each find none: whichever runs second in a process proves the
    first one's was put back, and each proves it of every test that ran before it there."""
    LEFT = "LEFT_BY_A_TEST"

    def leave_and_find_none(self, name):
        self.assertNotIn(self.LEFT, os.environ)
        self.assertEqual([n for n in os.listdir(conftest.TEMP) if n.startswith("left-by-a-test-")], [])
        self.assertEqual(os.path.normcase(os.getcwd()), os.path.normcase(conftest.TEMP))
        os.environ[self.LEFT] = name
        folder = tempfile.mkdtemp(prefix="left-by-a-test-", dir=conftest.TEMP)
        os.chdir(folder)

    def test_a_first_test_leaves_state_and_finds_none(self):
        self.leave_and_find_none("first")

    def test_a_second_test_leaves_state_and_finds_none(self):
        self.leave_and_find_none("second")


if __name__ == "__main__":
    unittest.main()
