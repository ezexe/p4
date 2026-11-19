"""What conftest.py gives every test: a temp folder, a home and git settings of its own, and none of the caller's
session, API or GitHub variables, nor a git setting the caller hands by environment."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import conftest

# What a child python runs after its caller handed it a git setting by environment: it takes what conftest.py gives a
# process that runs tests, under the folder named second, and prints what it then holds and what git then does.
CHILD = """
import json, os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import conftest
conftest.isolate(sys.argv[2], "child")
bare = os.path.join(conftest.TEMP, "bare.git")
made = subprocess.run(["git", "init", "-q", "--bare", bare], capture_output=True, text=True)
inside = subprocess.run(["git", "rev-parse", "--is-bare-repository"], cwd=bare, capture_output=True, text=True)
listed = subprocess.run(["git", "config", "--show-origin", "--list"], capture_output=True, text=True)
print(json.dumps({"held": sorted(k for k in os.environ if k.upper().startswith("GIT_CONFIG_")),
                  "settings": os.environ["GIT_CONFIG_GLOBAL"], "listed": listed.stdout, "said": listed.stderr,
                  "made": [made.returncode, made.stderr],
                  "inside": [inside.returncode, inside.stdout.strip(), inside.stderr]}))
"""


def origins(listed):
    """The origin of each row `git config --show-origin --list` printed, a file's as its path in one spelling: git
    prints a Windows path quoted, with its backslashes doubled."""
    rows = [line.split("\t", 1) for line in listed.splitlines()]
    return {os.path.normcase(os.path.normpath(o[len("file:"):].strip('"').replace("\\\\", "\\")))
            if o.startswith("file:") else o for o, _ in rows}


class Isolation(unittest.TestCase):
    def test_no_variable_of_the_callers_session_or_account_reaches_a_test(self):
        """A session's ids, an API key, a GitHub token, a git setting handed by environment and every P4_ switch are
        removed, in any case of letters, and a variable that only points a test at fixtures passes through. A switch
        a test file sets for itself when it is imported, as test_phi.py sets P4_PHI, is that file's own."""
        names = ["PATH", "CLAUDE_CODE_SESSION_ID", "claude_x", "ANTHROPIC_API_KEY", "P4_LIVE", "P4_FIXTURES",
                 "P4_MAC_STORE", "P4_PHI_TEST_TMP", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACTIONS", "HOME", "OTHER",
                 "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_EDITOR"]
        self.assertEqual([n for n in names if not conftest.is_the_callers(n)],
                         ["PATH", "P4_FIXTURES", "P4_MAC_STORE", "P4_PHI_TEST_TMP", "GITHUB_ACTIONS", "HOME", "OTHER",
                          "GIT_EDITOR"])

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
        self.assertEqual(origins(r.stdout), {os.path.normcase(os.path.normpath(os.environ["GIT_CONFIG_GLOBAL"]))},
                         r.stdout + r.stderr)
        got = dict(line.split("\t", 1)[1].split("=", 1) for line in r.stdout.splitlines())
        self.assertEqual((got["core.autocrlf"], got["user.name"]), ("false", "tests"))
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        self.assertNotEqual(top.returncode, 0, "the temp folder has no repository above it: " + top.stdout)

    def test_no_git_setting_the_caller_hands_by_environment_reaches_a_test(self):
        """The case above sees only the environment its own run was started in, so on a clean shell it proves nothing
        of a caller that holds a git setting. Here a child python is started with GIT_CONFIG_PARAMETERS set as git
        itself writes it for `git -c safe.bareRepository=explicit`, and again with the same setting as
        GIT_CONFIG_COUNT with its key and value, and takes what conftest.py gives a process that runs tests. The
        variables are gone, git reads the child's own file alone, and a command inside a bare repository runs, which
        that setting refuses."""
        key, value = "safe.bareRepository", "explicit"
        handed = ({"GIT_CONFIG_PARAMETERS": f"'{key}'='{value}'"},
                  {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": key, "GIT_CONFIG_VALUE_0": value})
        tests = os.path.dirname(os.path.abspath(conftest.__file__))
        for env in handed:
            with self.subTest(handed=sorted(env)):
                base = os.path.realpath(tempfile.mkdtemp(prefix="isolation-"))
                self.addCleanup(conftest.remove, base)          # the child's folders, its bare repository included
                r = subprocess.run([sys.executable, "-c", CHILD, tests, base], env={**os.environ, **env},
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                saw = json.loads(r.stdout)
                own = os.path.join(base, "child", "h", ".gitconfig")
                self.assertEqual(saw["held"], ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"])
                self.assertEqual(os.path.normcase(saw["settings"]), os.path.normcase(own))
                self.assertEqual(origins(saw["listed"]), {os.path.normcase(os.path.normpath(own))},
                                 saw["listed"] + saw["said"])
                self.assertEqual(saw["made"][0], 0, saw["made"][1])
                self.assertEqual(saw["inside"][:2], [0, "true"], saw["inside"][2])


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
