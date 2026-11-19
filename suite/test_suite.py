"""Tests of suite/run.py: which files it loads and how, the environment of its workers, its report and its verdict,
and runs of the real command on small repositories made in the temp folder."""
import collections
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run.py")
_spec = importlib.util.spec_from_file_location("suite_run", RUN)
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


def put(root, rel, src):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(textwrap.dedent(src).lstrip("\n"))
    return path


def command(root, *args, **env):
    """The command run on `root` as a process, as a session runs it, with `env` added to the environment."""
    r = subprocess.run([sys.executable, "-X", "utf8", RUN, "--root", root, *args], capture_output=True,
                       encoding="utf-8", errors="replace", env={**os.environ, **env}, timeout=120)
    return r.returncode, r.stdout, r.stderr


def lines_of(out):
    """Each test's id, outcome and seconds, from the line the command prints for it."""
    found = {}
    for m in re.finditer(r"^ *([\d.]+) s  (\S+) +(\S+)$", out, re.M):
        found[m.group(3)] = (m.group(2), float(m.group(1)))
    return found


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="suite-repo-")
        self.addCleanup(run.remove, self.root)


class Files(Repo):
    def test_every_test_file_is_found_and_each_is_loaded_its_way(self):
        put(self.root, "a/test_unit.py", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n")
        put(self.root, "b/test_functions.py", "def test_y():\n    pass\n")
        put(self.root, "c/test_script.py", "def main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n")
        put(self.root, "d/test_nothing.py", "X = 1\n")
        put(self.root, "d/helper.py", "Y = 2\n")
        put(self.root, ".hidden/test_hidden.py", "def test_z():\n    pass\n")
        files = run.test_files(self.root)
        self.assertEqual(files, ["a/test_unit.py", "b/test_functions.py", "c/test_script.py", "d/test_nothing.py"])
        self.assertEqual([run.kind_of(os.path.join(self.root, f)) for f in files], ["unit", "unit", "script", "none"])

    def test_what_a_files_main_block_runs_decides_how_the_command_loads_it(self):
        main = 'if __name__ == "__main__":\n'
        cases = {
            "test_script_with_a_class.py": ("import sys, unittest\n\nclass T(unittest.TestCase):\n"
                                            "    def test_x(self):\n        pass\n\ndef main():\n    assert True\n\n"
                                            + main + "    sys.exit(main())\n", "script"),
            "test_script_with_mock.py": ("from unittest import mock\n\ndef main():\n    assert mock\n\n"
                                         + main + "    main()\n", "script"),
            "test_script_with_a_test_function.py": ("def test_a():\n    pass\n\ndef main():\n    test_a()\n\n"
                                                    + main + "    main()\n", "script"),
            "test_unit_main.py": ("import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                                  "        pass\n\n" + main + "    unittest.main(verbosity=2)\n", "unit"),
            "test_functions_only.py": ("def test_a():\n    pass\n", "unit"),
            "test_nothing.py": ("X = 1\n", "none"),
        }
        for name, (src, kind) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(run.kind_of(put(self.root, name, src)), kind)

    def test_in_a_checkout_the_files_are_what_git_holds_and_not_what_it_ignores(self):
        for args in (["init", "-q"], ["config", "core.autocrlf", "false"]):
            subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)
        put(self.root, ".gitignore", "build/\n")
        put(self.root, "kept/test_tracked.py", "def test_a():\n    pass\n")
        put(self.root, "new/test_untracked.py", "def test_b():\n    pass\n")
        put(self.root, "build/test_ignored.py", "def test_c():\n    pass\n")
        subprocess.run(["git", "-C", self.root, "add", "kept"], check=True, capture_output=True)
        self.assertEqual(run.test_files(self.root), ["kept/test_tracked.py", "new/test_untracked.py"])

    def test_every_test_file_of_this_repository_is_one_the_command_loads(self):
        root = os.path.dirname(HERE)
        files = run.test_files(root)
        self.assertIn("suite/test_suite.py", files)
        none = [f for f in files if run.kind_of(os.path.join(root, f)) == "none"]
        self.assertEqual(none, [], "test files the command cannot load")
        names = collections.Counter(f.rsplit("/", 1)[-1][:-3] for f in files)
        shared = sorted(n for n, c in names.items() if c > 1)
        if shared:
            by_name = re.compile(r"^[ \t]*(?:from|import)[ \t]+(?:%s)\b" % "|".join(map(re.escape, shared)), re.M)
            users = []
            for f in files:
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    if by_name.search(fh.read()):
                        users.append(f)
            self.assertEqual(users, [], f"test files that import one of {shared} by a name two test files share")
        modules = collections.defaultdict(list)
        for folder in sorted({os.path.dirname(f) for f in files}):
            for n in os.listdir(os.path.join(root, folder)):
                if n.endswith(".py") and not n.startswith("test_"):
                    modules[n].append(os.path.join(root, folder, n))
        differ = []
        for n, paths in sorted(modules.items()):
            with open(paths[0], "rb") as fh:
                first = fh.read()
            for p in paths[1:]:
                with open(p, "rb") as fh:
                    if fh.read() != first:
                        differ.append(f"{n}: {paths[0]} and {p}")
        self.assertEqual(differ, [], "folders of tests that hold modules of one name with other contents")


class Definition(unittest.TestCase):
    def test_suite_json_names_the_budget_and_every_setting_with_its_reason(self):
        d = run.definition()
        self.assertGreater(d["budget"], 0)
        self.assertGreaterEqual(d["workers"], 1)
        self.assertGreater(d["timeout"], 0)
        self.assertEqual(d["pattern"], "test_*.py")
        self.assertTrue({"CLAUDE", "ANTHROPIC", "P4_"} <= set(d["strip"]))
        with open(run.DEFINITION, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual([k for k, v in raw.items() if not v.get("why")], [], "settings without a reason")


class Environment(Repo):
    BASE = {"PATH": "/bin", "CLAUDE_CODE_SESSION_ID": "s", "claude_x": "1", "ANTHROPIC_API_KEY": "k", "P4_LIVE": "1",
            "P4_FIXTURES": "/fixtures", "GH_TOKEN": "g", "GITHUB_TOKEN": "g", "HOME": "/real/home", "OTHER": "kept"}
    STRIP = ["CLAUDE", "ANTHROPIC", "P4_", "GH_TOKEN", "GITHUB_TOKEN"]

    def env(self, windows):
        return run.worker_env(self.BASE, os.path.join(self.root, "0"), self.STRIP, ["P4_FIXTURES"], self.root,
                              windows=windows)

    def test_a_worker_has_its_own_temp_home_and_git_settings_and_none_of_the_callers_switches_or_tokens(self):
        tmp, home = os.path.join(self.root, "0", "t"), os.path.join(self.root, "0", "h")
        for windows in (True, False):
            with self.subTest(windows=windows):
                env = self.env(windows)
                self.assertEqual(sorted(k for k in env if k.upper().startswith(tuple(self.STRIP))), ["P4_FIXTURES"])
                self.assertEqual((env["TEMP"], env["TMP"], env["TMPDIR"]), (tmp, tmp, tmp))
                self.assertEqual(env["HOME"], home, "git reads no settings of the caller's home")
                self.assertEqual((env["GIT_CONFIG_GLOBAL"], env["GIT_CONFIG_NOSYSTEM"]),
                                 (os.path.join(home, ".gitconfig"), "1"))
                self.assertEqual((env["GIT_CEILING_DIRECTORIES"], env["OTHER"]), (self.root, "kept"))
                self.assertTrue(os.path.isdir(tmp))
                if windows:
                    self.assertEqual(env["USERPROFILE"], home)
                    self.assertTrue(env["APPDATA"].startswith(home) and env["LOCALAPPDATA"].startswith(home))
                    self.assertTrue(os.path.isdir(env["APPDATA"]) and os.path.isdir(env["LOCALAPPDATA"]))
                else:
                    self.assertNotIn("USERPROFILE", env)

    def test_git_in_a_worker_reads_its_own_settings_alone(self):
        env = self.env(os.name == "nt")
        env["PATH"] = os.environ["PATH"]
        r = subprocess.run(["git", "config", "--show-origin", "--list"], capture_output=True, text=True, env=env,
                           cwd=env["TEMP"])
        rows = [line.split("\t", 1) for line in r.stdout.splitlines()]
        # git prints a Windows path quoted, with its backslashes doubled
        origins = {os.path.normcase(os.path.normpath(o[len("file:"):].strip('"').replace("\\\\", "\\")))
                   for o, _ in rows}
        self.assertEqual(origins, {os.path.normcase(os.path.normpath(env["GIT_CONFIG_GLOBAL"]))}, r.stdout + r.stderr)
        got = dict(kv.split("=", 1) for _, kv in rows)
        self.assertEqual((got["core.autocrlf"], got["user.name"]), ("false", "suite"))


Row = run.Row


class Verdict(unittest.TestCase):
    def rows(self, *outcomes):
        return [Row(f"f/test_x.py::T::test_{i}", "f/test_x.py", f"T::test_{i}", o, 0.5, "", 0)
                for i, o in enumerate(outcomes)]

    def test_a_run_within_its_budget_passes_and_one_past_it_fails_with_its_own_status(self):
        lines, status = run.report(self.rows("ok", "skip"), [], 2, 4.0, 0.1, 10)
        self.assertEqual(status, run.OK)
        self.assertEqual(lines[-1], "budget 10 s from suite/suite.json: the run took 4.0 s, under it by 6.0 s")
        lines, status = run.report(self.rows("ok"), [], 2, 12.5, 0.1, 10)
        self.assertEqual(status, run.OVER_BUDGET)
        self.assertEqual(lines[-1], "budget 10 s from suite/suite.json: the run took 12.5 s, over it by 2.5 s")

    def test_a_failed_test_outranks_the_budget_and_a_subset_has_none(self):
        self.assertEqual(run.report(self.rows("ok", "FAIL"), [], 2, 12.5, 0.1, 10)[1], run.FAILED)
        lines, status = run.report(self.rows("ok", "TIMEOUT"), [], 2, 1.0, 0.1, None)
        self.assertEqual(status, run.FAILED)
        self.assertEqual(lines[-1], "budget: not checked, since only some tests ran")
        self.assertEqual(run.report([], [], 2, 1.0, 0.1, 10)[1], run.FAILED, "a run of no test fails")

    def test_the_totals_say_the_lower_bound_the_workers_give(self):
        lines, _ = run.report(self.rows("ok", "ok", "ok", "ok"), [], 4, 1.0, 0.0, 10, quiet=True)
        self.assertIn("lower bound for these tests on 4 workers: 0.5 s, the longest test 0.5 s", lines)
        self.assertIn("test time 2.0 s, imports 0.0 s, wall 1.0 s", lines)


MIXED = {
    "a/test_alpha.py": '''
        import os, tempfile, unittest

        class Shared(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.tmp = tempfile.mkdtemp(prefix="class-")
                os.environ["ALPHA_CLASS"] = "1"

            @classmethod
            def tearDownClass(cls):
                os.rmdir(cls.tmp)
                del os.environ["ALPHA_CLASS"]

            def test_a_sees_what_the_class_made(self):
                self.assertTrue(os.path.isdir(self.tmp) and os.environ.get("ALPHA_CLASS") == "1")

            def test_b_sees_it_too(self):
                self.assertTrue(os.path.isdir(self.tmp) and os.environ.get("ALPHA_CLASS") == "1")

        class Mixed(unittest.TestCase):
            def test_fails(self):
                print("printed by the failing test")
                self.assertEqual(1, 2)

            def test_raises(self):
                raise RuntimeError("boom")

            @unittest.skip("not on this machine")
            def test_skipped(self):
                pass

            def test_subtests(self):
                for i in range(3):
                    with self.subTest(i=i):
                        self.assertLess(i, 2)

            def test_leaves_state(self):
                os.environ["LEFT_BY_A_TEST"] = "1"
                tempfile.mkdtemp(prefix="left-")

        class BrokenSetup(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("no fixture")

            def test_one(self):
                pass

            def test_two(self):
                pass

        class BrokenTeardown(unittest.TestCase):
            @classmethod
            def tearDownClass(cls):
                raise RuntimeError("no cleanup")

            def test_passes(self):
                pass
    ''',
    "b/test_beta.py": '''
        import os

        def test_sees_none_of_the_callers_switches():
            assert not [k for k in os.environ if k.upper().startswith(("CLAUDE", "ANTHROPIC", "P4_"))]

        def test_sees_no_state_another_test_left():
            assert "LEFT_BY_A_TEST" not in os.environ
            assert not [n for n in os.listdir(os.environ["TEMP"]) if n.startswith("left-")]
    ''',
    "c/test_gamma.py": '''
        import sys

        def main():
            assert sum([1, 1]) == 2
            return 0

        if __name__ == "__main__":
            sys.exit(main())
    ''',
    "d/test_delta.py": "X = 1\n",
}


class Command(Repo):
    def make(self, files):
        for rel, src in files.items():
            put(self.root, rel, src)

    def test_each_test_gets_its_line_and_outcome_and_a_failure_fails_the_run(self):
        self.make(MIXED)
        code, out, err = command(self.root, "a", "b", "c", "d", "e/test_nowhere.py", "--workers", "2",
                                 CLAUDE_CODE_SESSION_ID="s", ANTHROPIC_API_KEY="k", P4_LIVE="1")
        self.assertEqual(code, run.FAILED, out + err)
        got = {k: v[0] for k, v in lines_of(out).items()}
        self.assertEqual(got, {
            "a/test_alpha.py::Mixed::test_fails": "FAIL", "a/test_alpha.py::Mixed::test_leaves_state": "ok",
            "a/test_alpha.py::Mixed::test_raises": "ERROR", "a/test_alpha.py::Mixed::test_skipped": "skip",
            "a/test_alpha.py::Mixed::test_subtests": "FAIL", "a/test_alpha.py::Shared::test_a_sees_what_the_class_made":
            "ok", "a/test_alpha.py::Shared::test_b_sees_it_too": "ok",
            "a/test_alpha.py::BrokenSetup::test_one": "ERROR", "a/test_alpha.py::BrokenSetup::test_two": "ERROR",
            "a/test_alpha.py::BrokenTeardown::test_passes": "ok",
            "a/test_alpha.py::BrokenTeardown::tearDownClass": "ERROR",
            "b/test_beta.py::test_sees_none_of_the_callers_switches": "ok",
            "b/test_beta.py::test_sees_no_state_another_test_left": "ok", "c/test_gamma.py": "ok",
            "d/test_delta.py": "ERROR", "e/test_nowhere.py": "ERROR"}, out)
        self.assertIn("printed by the failing test", out)
        self.assertIn("(i=2)", out)
        self.assertEqual(out.count("RuntimeError: no fixture"), 2, "each test of a class that cannot be set up fails")
        self.assertIn("RuntimeError: no cleanup", out)
        self.assertRegex(out, r"a/test_alpha.py::Mixed::test_leaves_state: os.environ: set LEFT_BY_A_TEST; "
                              r"left in the temp folder: left-\w+")
        self.assertNotIn("Shared", out.split("left changed")[1].split("slowest:")[0], "a class that cleans up left nothing")
        self.assertIn("budget: not checked, since only some tests ran", out)

    def test_a_run_past_its_budget_fails_and_its_rows_go_to_the_tsv(self):
        self.make({"a/test_slow.py": '''
            import time, unittest

            class Slow(unittest.TestCase):
                def test_sleeps(self):
                    time.sleep(0.2)
        '''})
        tsv = os.path.join(self.root, "timings.tsv")
        code, out, err = command(self.root, "--budget", "0.05", "--tsv", tsv, "--label", "L", "--workers", "1")
        self.assertEqual(code, run.OVER_BUDGET, out + err)
        self.assertRegex(out, r"budget 0.05 s from the command line: the run took [\d.]+ s, over it by [\d.]+ s")
        with open(tsv, encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f]
        self.assertEqual(rows[0], ["label", "file", "test", "seconds", "result"])
        self.assertEqual(rows[1][:3] + rows[1][4:], ["L", "a/test_slow.py", "Slow::test_sleeps", "PASSED"])
        self.assertGreaterEqual(float(rows[1][3]), 0.2)
        self.assertEqual(rows[2][:3], ["L", "<suite>", "<wall>"])
        self.assertTrue(rows[2][4].endswith("exit=3"), rows[2])

    def test_one_test_named_runs_alone(self):
        self.make({"a/test_two.py": '''
            import unittest

            class Two(unittest.TestCase):
                def test_named(self):
                    pass

                def test_other(self):
                    raise AssertionError("not asked for")
        '''})
        code, out, err = command(self.root, "a/test_two.py::Two::test_named")
        self.assertEqual(code, run.OK, out + err)
        self.assertEqual(list(lines_of(out)), ["a/test_two.py::Two::test_named"])

    def test_the_folder_a_caller_names_for_test_phis_fixtures_reaches_the_worker(self):
        # test_phi.py makes the folder P4_PHI_TEST_TMP names when it is imported and sets tempfile.tempdir to it, so
        # the folder exists after a run only when the variable reached the worker that imported the file
        fixtures = os.path.join(self.root, "phi-fixtures")
        test = "lbiza/plugins/p4-phi/scripts/test_phi.py::Background::test_a_note_needs_its_source"
        code, out, err = command(os.path.dirname(HERE), "--workers", "1", test, P4_PHI_TEST_TMP=fixtures)
        self.assertEqual(code, run.OK, out + err)
        self.assertEqual(lines_of(out)[test][0], "ok", out)
        self.assertTrue(os.path.isdir(fixtures),
                        "test_phi.py's fixtures did not go to the folder P4_PHI_TEST_TMP names")

    def test_a_workers_temp_folder_is_named_as_the_file_system_holds_it(self):
        """A caller's temp folder spelled another way than the file system holds it reaches no test: by an 8.3 short
        name on Windows, as a GitHub runner's TEMP is C:\\Users\\RUNNER~1\\AppData\\Local\\Temp, or through a link
        elsewhere. git and os.path.realpath name a folder in full, so a test that compares a path it made with one the
        code under test resolved would meet two spellings of one folder."""
        held = os.path.join(os.path.realpath(tempfile.mkdtemp(prefix="suite-temp-")), "a temp folder with a long name")
        self.addCleanup(run.remove, os.path.dirname(held))
        os.mkdir(held)
        if os.name == "nt":
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.windll.kernel32.GetShortPathNameW(held, buf, len(buf))
            other = buf.value if 0 < n < len(buf) else held
            if os.path.normcase(other) == os.path.normcase(held):
                self.skipTest("this volume makes no 8.3 short names")
        else:
            other = os.path.join(os.path.dirname(held), "link")
            os.symlink(held, other)
        self.make({"a/test_temp.py": '''
            import os, tempfile, unittest

            class Temp(unittest.TestCase):
                def test_named_in_full(self):
                    tmp = tempfile.gettempdir()
                    self.assertEqual(tmp, os.path.realpath(tmp))
                    self.assertEqual(os.getcwd(), tmp)
        '''})
        code, out, err = command(self.root, "--workers", "1", TEMP=other, TMP=other, TMPDIR=other)
        self.assertEqual(code, run.OK, out + err)
        self.assertEqual(lines_of(out)["a/test_temp.py::Temp::test_named_in_full"][0], "ok", out)

    def test_two_files_of_one_name_both_run_and_a_module_of_other_contents_by_one_name_fails_its_folder(self):
        pad = "# " + "x" * 60 + "\n"
        self.make({"a/test_same.py": "def test_from_a():\n    pass\n",
                   "b/test_same.py": "def test_from_b():\n    pass\n",
                   "c/helper.py": "X = 1\n", "e/helper.py": "X = 1\n", "d/helper.py": "X = 2\n",
                   "c/test_c.py": pad * 6 + "import helper\n\ndef test_c():\n    assert helper.X == 1\n",
                   "e/test_e.py": pad * 3 + "import helper\n\ndef test_e():\n    assert helper.X == 1\n",
                   "d/test_d.py": "import helper\n\ndef test_d():\n    assert helper.X == 2\n"})
        code, out, err = command(self.root, "--workers", "1")
        self.assertEqual(code, run.FAILED, out + err)
        got = {k: v[0] for k, v in lines_of(out).items()}
        self.assertEqual(got, {"a/test_same.py::test_from_a": "ok", "b/test_same.py::test_from_b": "ok",
                               "c/test_c.py::test_c": "ok", "e/test_e.py::test_e": "ok",
                               "d/test_d.py::<import>": "ERROR"}, out)
        self.assertRegex(out, r"holds a module of this file's folder from another folder, with other contents: "
                              r"helper is \S+[\\/]c[\\/]helper\.py")

    def test_a_file_that_does_not_parse_is_a_failing_row_and_the_run_leaves_no_folder(self):
        self.make({"a/test_broken.py": "def test_x(:\n    pass\n", "b/test_fine.py": "def test_fine():\n    pass\n"})
        tmp = os.path.join(self.root, "tmp")
        os.makedirs(tmp)
        temp = {"TEMP": tmp, "TMP": tmp, "TMPDIR": tmp}
        code, out, err = command(self.root, "--workers", "1", **temp)
        self.assertEqual(code, run.FAILED, out + err)
        self.assertEqual({k: v[0] for k, v in lines_of(out).items()},
                         {"a/test_broken.py": "ERROR", "b/test_fine.py::test_fine": "ok"}, out + err)
        self.assertIn("SyntaxError", out)
        self.assertEqual(os.listdir(tmp), [], "the run's folder is removed")
        code, out, err = command(self.root, "--files", **temp)
        self.assertEqual(code, run.FAILED, out + err)
        self.assertRegex(out, r"broken +a/test_broken\.py  it does not parse: SyntaxError")
        self.assertEqual(os.listdir(tmp), [])

    def test_a_worker_that_dies_mid_test_and_a_script_that_exits_nonzero_fail_the_run(self):
        self.make({"a/test_dies.py": '''
            import os, unittest

            class Dies(unittest.TestCase):
                def test_dies(self):
                    os._exit(7)
        ''', "b/test_after.py": "def test_after():\n    pass\n",
            "c/test_script.py": 'import sys\n\nif __name__ == "__main__":\n    sys.exit(4)\n'})
        code, out, err = command(self.root, "--workers", "1")
        self.assertEqual(code, run.FAILED, out + err)
        got = {k: v[0] for k, v in lines_of(out).items()}
        self.assertEqual(got, {"a/test_dies.py::Dies::test_dies": "ERROR", "b/test_after.py::test_after": "ok",
                               "c/test_script.py": "FAIL"}, out)
        self.assertIn("exited with code 7", out)
        self.assertIn("exit code 4", out)

    def test_a_worker_lost_in_its_last_teardown_fails_the_run(self):
        for how, args, said in (("os._exit(5)", [], "exited with code 5"),
                                ("time.sleep(60)", ["--timeout", "1"], "did not end within 1 s")):
            with self.subTest(how=how):
                root = tempfile.mkdtemp(prefix="suite-repo-")
                self.addCleanup(run.remove, root)
                put(root, "a/test_last.py", f'''
                    import os, time, unittest

                    class Last(unittest.TestCase):
                        @classmethod
                        def tearDownClass(cls):
                            {how}

                        def test_passes(self):
                            pass
                ''')
                code, out, err = command(root, "--workers", "1", *args)
                self.assertEqual(code, run.FAILED, out + err)
                got = {k: v[0] for k, v in lines_of(out).items()}
                self.assertEqual(got.get("a/test_last.py::Last::test_passes"), "ok", out)
                self.assertEqual(got.get("<worker-0>::<end>"), "ERROR", out)
                self.assertIn(said, out)

    def test_a_hung_test_is_stopped_with_its_stack_and_another_worker_runs_the_rest(self):
        self.make({"a/test_hangs.py": '''
            import time, unittest

            class Hangs(unittest.TestCase):
                def test_hangs(self):
                    time.sleep(60)
        ''', "b/test_after.py": '''
            def test_runs_after_the_hung_one():
                pass
        '''})
        # the worker writes its stack a quarter of the timeout before the stop: a second, which a worker that a busy
        # machine starts late on its test still keeps, where the quarter second of a timeout of 1 was lost on a runner
        code, out, err = command(self.root, "--workers", "1", "--timeout", "4")
        self.assertEqual(code, run.FAILED, out + err)
        got = lines_of(out)
        self.assertEqual(got["a/test_hangs.py::Hangs::test_hangs"][0], "TIMEOUT", out)
        self.assertEqual(got["b/test_after.py::test_runs_after_the_hung_one"][0], "ok", out)
        self.assertIn("was stopped after 4 s on this test", out)
        self.assertIn('in test_hangs', out, "the stack written shortly before the stop")


if __name__ == "__main__":
    unittest.main(verbosity=1)
