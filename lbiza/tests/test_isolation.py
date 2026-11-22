"""What conftest.py gives every test: a temp folder, a home and git settings of its own, none of the caller's
session, API or GitHub variables, nor a git setting the caller hands by environment, and on Windows Git Bash's `sh`
where the caller's PATH finds none."""
import json
import os
import shutil
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

# What a child python runs whose caller's PATH finds no `sh`: it takes what conftest.py gives a process that runs
# tests, under the folder named second, and prints the `sh` it found before and after, and what that `sh` then ran.
SHELL_CHILD = """
import json, os, shutil, subprocess, sys
sys.path.insert(0, sys.argv[1])
import conftest
before = shutil.which("sh")
conftest.isolate(sys.argv[2], "child")
sh = shutil.which("sh")
ran = subprocess.run(["sh", "-c", "mkdir -p made/here && echo ran"], capture_output=True, text=True) if sh else None
print(json.dumps({"before": before, "sh": sh, "ran": ran and [ran.returncode, ran.stdout.strip(), ran.stderr],
                  "made": os.path.isdir(os.path.join(conftest.TEMP, "made", "here")),
                  "held": sorted(k for k in os.environ if k.upper().startswith("CLAUDE"))}))
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


def same(a, b):
    """Whether two paths name one file or folder, in whatever case and with whichever slashes."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class Shell(unittest.TestCase):
    """A command hook of the plugins is a shell command that starts `sh`, and the tests start `sh` as Claude Code
    does. PowerShell's PATH finds no `sh` on Windows, so a run started there gets Git Bash's, which is looked for as
    https://code.claude.com/docs/en/env-vars.md has Claude Code look for it. Before conftest.py did that, a run of
    every test from PowerShell ended with 63 failed and 98 skipped where the run from Git Bash had none failed and
    one skipped: 62 of the 63 at a `subprocess.run(["sh", ...])` with "[WinError 2] The system cannot find the file
    specified", and the skipped ones at a `shutil.which("sh")` that found nothing."""

    def git(self, root):
        """A folder laid out as Git for Windows lays its own out, with empty files -> its `usr\\bin`."""
        for folder, name in (("usr/bin", "sh.exe"), ("usr/bin", "bash.exe"), ("bin", "bash.exe"), ("cmd", "git.exe")):
            os.makedirs(os.path.join(root, *folder.split("/")), exist_ok=True)
            open(os.path.join(root, *folder.split("/"), name), "w").close()
        return os.path.join(root, "usr", "bin")

    def test_a_test_finds_sh_whichever_shell_started_the_run(self):
        """On every system, and on one that is not Windows the `sh` is the system's own, so none is looked for."""
        self.assertTrue(shutil.which("sh"), "no sh on PATH: " + os.environ.get("PATH", ""))
        if os.name != "nt":
            self.assertIsNone(conftest.git_bash_tools({"CLAUDE_CODE_GIT_BASH_PATH": shutil.which("sh"), "PATH": ""}))

    @unittest.skipUnless(os.name == "nt", "Git Bash is looked for on Windows alone")
    def test_git_bash_is_taken_from_the_variable_first_then_from_git_on_path_then_from_where_git_installs(self):
        """Each case is a folder laid out as Git for Windows lays its own out, so the order holds on a machine
        whatever Git it has. The variable counts where its file is there and is named as a shell the docs list, the
        `git` on PATH counts next, and the folders Git for Windows installs to count last."""
        base = os.path.realpath(tempfile.mkdtemp(prefix="shell-"))
        self.addCleanup(conftest.remove, base)
        named, on_path = (self.git(os.path.join(base, n, "Git")) for n in ("named", "on path"))
        self.git(os.path.join(base, "installed", "Git"))
        rest = {"PATH": os.path.join(base, "on path", "Git", "cmd"), "ProgramFiles": os.path.join(base, "installed")}
        for bash in (os.path.join(named, "bash.exe"), os.path.join(named, "sh.exe"),
                     os.path.join(base, "named", "Git", "bin", "bash.exe")):
            with self.subTest(named=bash):
                got = conftest.git_bash_tools({"CLAUDE_CODE_GIT_BASH_PATH": bash, **rest})
                self.assertTrue(got and same(got, named), got)
        other = os.path.join(named, "zsh.exe")          # a file that is there, named as no shell the docs list
        open(other, "w").close()
        for ignored in (other, os.path.join(base, "nowhere", "bash.exe"), ""):
            with self.subTest(ignored=ignored):
                got = conftest.git_bash_tools({"CLAUDE_CODE_GIT_BASH_PATH": ignored, **rest})
                self.assertTrue(got and same(got, on_path), got)
        nowhere = os.path.join(base, "nowhere")
        for var, under in (("ProgramFiles", ()), ("ProgramW6432", ()), ("ProgramFiles(x86)", ()),
                           ("LOCALAPPDATA", ("Programs",))):
            with self.subTest(installed_under=var):
                tools = self.git(os.path.join(base, var, *under, "Git"))
                got = conftest.git_bash_tools({"PATH": nowhere, var: os.path.join(base, var)})
                self.assertTrue(got and same(got, tools), got)
        self.assertIsNone(conftest.git_bash_tools({"PATH": nowhere}), "no Git Bash anywhere")

    @unittest.skipUnless(os.name == "nt", "Git Bash is looked for on Windows alone")
    def test_a_run_whose_callers_path_finds_no_sh_gets_git_bashs_and_its_tools(self):
        """A child python is started with a PATH that holds no folder with an `sh` in it, as PowerShell's holds none,
        and takes what conftest.py gives a process that runs tests. It then finds Git Bash's `sh`, and a script that
        `sh` runs finds `mkdir` beside it. Once the child is handed where Git Bash is by CLAUDE_CODE_GIT_BASH_PATH,
        which is read before the caller's CLAUDE variables are removed, and once it is handed nothing and finds the
        Git of this machine."""
        tools = os.path.dirname(shutil.which("sh"))
        path = os.pathsep.join(d for d in os.environ["PATH"].split(os.pathsep) if d and not shutil.which("sh", path=d))
        self.assertIsNone(shutil.which("sh", path=path))
        tests = os.path.dirname(os.path.abspath(conftest.__file__))
        found = conftest.git_bash_tools({**os.environ, "PATH": path})
        self.assertTrue(found, "no Git Bash found from git on PATH or where Git for Windows installs")
        for handed, expected in (({"CLAUDE_CODE_GIT_BASH_PATH": os.path.join(tools, "bash.exe")}, tools), ({}, found)):
            with self.subTest(handed=sorted(handed)):
                base = os.path.realpath(tempfile.mkdtemp(prefix="shell-"))
                self.addCleanup(conftest.remove, base)
                r = subprocess.run([sys.executable, "-c", SHELL_CHILD, tests, base],
                                   env={**os.environ, "PATH": path, **handed}, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                saw = json.loads(r.stdout)
                self.assertIsNone(saw["before"])
                self.assertTrue(saw["sh"] and same(os.path.dirname(saw["sh"]), expected), saw["sh"])
                self.assertEqual(saw["ran"][:2], [0, "ran"], saw["ran"])
                self.assertTrue(saw["made"])
                self.assertEqual(saw["held"], [])


class OwnModules(unittest.TestCase):
    """Both plugins hold a p4conf.py, which their files and their tests import by that one name. A test file gets
    its own plugin's copy whichever folder of tests/ pytest was given first."""
    # One case of each folder, which holds the `p4conf` of its file and of the plugin's file beside it to that
    # plugin's own copy, and to what only that copy does.
    CASES = ("tests/p4-temportal/test_lifetime.py::OwnCopy::test_these_tests_run_the_copy_in_p4_temportals_hooks",
             "tests/p4-phi/test_p4conf.py::P4Conf::test_these_tests_run_the_copy_beside_phi_py")

    def test_a_test_file_gets_its_own_plugins_module_in_either_order_of_the_folders(self):
        """A child pytest runs the two cases in one process, once in each order. It imports both test files whole,
        in the order given, before it runs either case, as a run of both folders does. Before conftest.py kept each
        folder's modules, the second file took the first one's p4conf: with tests/p4-temportal first, five cases of
        test_p4conf.py found no allow rules, and in the suite's own order test_lifetime.py ran p4-phi's copy."""
        lbiza = os.path.dirname(os.path.dirname(os.path.abspath(conftest.__file__)))
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTEST_")}     # this run's own
        for order in (self.CASES, self.CASES[::-1]):
            with self.subTest(first=order[0].split("/")[1]):
                r = subprocess.run([sys.executable, "-m", "pytest", "-n", "0", "-p", "no:cacheprovider", "-q", *order],
                                   cwd=lbiza, env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("2 passed", r.stdout)


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
