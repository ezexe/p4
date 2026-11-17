#!/usr/bin/env python3
"""test_p4_memory.py: acceptance tests for p4-temportal's memory part. Claude Code writes and loads the project's
auto memory itself, in the store's .claude/p4/temportal/memory/ once `autoMemoryDirectory` names it, so a start moves
no file, writes no pointer and prints no index, with the key or without it. What is left is the line a start prints
when a write block would keep Claude Code from saving memory in the store, and `chosen_by_user`, which tells a
folder ezexe chose from one a repository chose. Run from anywhere: python3 hooks/test_p4_memory.py, and exit 0 is
green."""

import atexit
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run-hook.sh")
sys.path.insert(0, HERE)
import p4_memory  # noqa: E402

SWITCHES = ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_PROJECT_DIR_NAME")
CONFIG = tempfile.mkdtemp(prefix="p4-temportal-memory-config-")
atexit.register(lambda: wipe(CONFIG))


def wipe(path):
    """Remove a test's tree, a git repository's read-only objects included, which rmtree alone leaves on Windows."""
    def again(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def clean_env(**kw):
    """The environment without ezexe's auto memory switches, and with a config dir of the test's own, so neither the
    real settings nor the real environment decide a result."""
    env = {k: v for k, v in os.environ.items() if k not in SWITCHES}
    env["CLAUDE_CONFIG_DIR"] = CONFIG
    env["P4_MANAGED_SETTINGS"] = os.path.join(CONFIG, "no-managed-settings.json")
    env.update(kw)
    return env


@contextlib.contextmanager
def environ(env):
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def hook(sub, payload, env):
    """p4_memory.py's main() with that subcommand, run in this process as its own process would run it -> stdout."""
    saved = (os.getcwd(), sys.argv, sys.stdin)
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)
    try:
        sys.argv = ["p4_memory.py", sub]
        sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
        with environ(env), contextlib.redirect_stdout(out):
            code = p4_memory.main()
    finally:
        os.chdir(saved[0])
        sys.argv, sys.stdin = saved[1], saved[2]
    assert code == 0, code
    return out.buffer.getvalue().decode("utf-8", "replace")


def run(sub, root, app, payload=None, **kw):
    return hook(sub, payload or {}, clean_env(CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app, **kw))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def tree(base):
    """Every file under a folder with its text, so a test can say nothing in it changed."""
    out = {}
    for d, _dirs, names in os.walk(base):
        for n in names:
            p = os.path.join(d, n)
            out[os.path.relpath(p, base)] = read(p)
    return out


def git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)


class NativeMemory(unittest.TestCase):
    """ezexe/p4#92: the auto memory is Claude Code's to write and load, so a start, a write and a turn end move no
    file, write no pointer and print no index."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="p4-temportal-memory-")
        self.addCleanup(wipe, self.base)
        self.root = os.path.join(self.base, "proj")
        self.store = os.path.join(self.root, ".claude", "p4", "temportal", "memory")
        self.app = os.path.join(self.base, "config", "projects", "slug", "memory")
        put(os.path.join(self.store, "MEMORY.md"), "- [s](s.md) — s\n")
        put(os.path.join(self.store, "s.md"), "fact s\n")

    def test_a_start_without_the_key_moves_nothing_and_writes_no_pointer(self):
        """Until autoMemoryDirectory names the store, Claude Code's own folder and the store are left as they are."""
        put(os.path.join(self.app, "MEMORY.md"), "- [a](a.md) — a\n")
        put(os.path.join(self.app, "a.md"), "fact a\n")
        app_before, store_before = tree(self.app), tree(self.store)
        out = run("migrate", self.root, self.app)
        self.assertEqual(out, "", "a start printed the index or a notice")
        self.assertEqual(tree(self.app), app_before, "the auto memory directory was changed")
        self.assertEqual(tree(self.store), store_before, "the store's memory was changed")

    def test_a_start_with_the_key_prints_nothing_and_leaves_the_store(self):
        before = tree(self.store)
        self.assertEqual(run("migrate", self.root, self.store), "", "a start printed what Claude Code loads natively")
        self.assertEqual(tree(self.store), before)

    def test_a_session_started_before_this_change_calls_mirror_and_sweep_in_silence(self):
        """An open session keeps the hooks it started with, so the two retired commands still exit 0 and say
        nothing, and change nothing."""
        put(os.path.join(self.app, "b.md"), "fact b\n")
        w = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.app, "b.md")}}
        app_before, store_before = tree(self.app), tree(self.store)
        for sub, payload in (("mirror", w), ("sweep", {})):
            self.assertEqual(run(sub, self.root, self.app, payload), "", sub)
        self.assertEqual((tree(self.app), tree(self.store)), (app_before, store_before))

    def test_the_runner_exits_0_on_an_unknown_subcommand_and_on_a_missing_script(self):
        sh = shutil.which("sh")
        if not sh:
            self.skipTest("no sh on PATH")
        env = clean_env(CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=self.root, P4_MEMORY_APPDATA=self.app)
        self.assertEqual(subprocess.run([sh, RUNNER, "memory", "nope"], input=b"{}", env=env,
                                        capture_output=True).returncode, 0)
        env["CLAUDE_PLUGIN_ROOT"] = self.base
        self.assertEqual(subprocess.run([sh, RUNNER, "memory", "migrate"], input=b"{}", env=env,
                                        capture_output=True).returncode, 0)


class ChosenByUser(unittest.TestCase):
    """By permissions.md, a local settings file git does not track is the user's own, and a tracked one, one outside
    a git repository or one under a `.claude` that is a link is the repository's."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git on PATH")
        self.root = tempfile.mkdtemp(prefix="p4-temportal-memory-chosen-")
        self.addCleanup(wipe, self.root)
        self.local = os.path.join(self.root, ".claude", "settings.local.json")
        put(self.local, json.dumps({"autoMemoryDirectory": "~/elsewhere"}))
        self.env = clean_env()

    def chosen(self):
        with environ(self.env):
            return p4_memory.chosen_by_user(self.root)

    def test_an_untracked_local_file_counts_as_the_users_choice(self):
        git(self.root, "init", "-q")
        self.assertTrue(self.chosen(), "an untracked local file was counted as the repository's")
        git(self.root, "add", "-f", ".claude/settings.local.json")
        self.assertFalse(self.chosen(), "a tracked local file was counted as the user's")

    def test_a_local_file_outside_a_git_repository_is_the_repositorys(self):
        self.env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(self.root)
        self.assertFalse(self.chosen())

    def test_a_project_file_is_the_repositorys_and_a_user_file_the_users(self):
        git(self.root, "init", "-q")
        os.remove(self.local)
        put(os.path.join(self.root, ".claude", "settings.json"), json.dumps({"autoMemoryDirectory": "~/elsewhere"}))
        self.assertFalse(self.chosen(), "the project file was counted as the user's")
        os.remove(os.path.join(self.root, ".claude", "settings.json"))
        put(os.path.join(CONFIG, "settings.json"), json.dumps({"autoMemoryDirectory": "~/elsewhere"}))
        self.addCleanup(os.remove, os.path.join(CONFIG, "settings.json"))
        self.assertTrue(self.chosen(), "the user file was counted as the repository's")
        put(os.path.join(self.root, ".claude", "settings.json"), json.dumps({"autoMemoryDirectory": "~/other"}))
        self.assertFalse(self.chosen(), "the project file wins over the user file, and was not counted")


class WriteBlock(unittest.TestCase):
    """A worktree whose autoMemoryDirectory names the main checkout's store is told once at its start when
    blockWritesOutsideWorkingDirectories would keep Claude Code from saving memory there."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="p4-temportal-memory-block-")
        self.addCleanup(wipe, self.base)
        self.main = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(self.main, ".git", "worktrees", "wt"))
        put(os.path.join(self.main, ".git", "worktrees", "wt", "commondir"), "../..\n")
        self.wt = os.path.join(self.base, "wt")
        put(os.path.join(self.wt, ".git"), f"gitdir: {os.path.join(self.main, '.git', 'worktrees', 'wt')}\n")
        self.sub = os.path.join(self.main, "src")
        os.makedirs(self.sub)
        self.store = os.path.normpath(os.path.join(self.main, ".claude", "p4", "temportal", "memory"))
        put(os.path.join(self.store, "MEMORY.md"), "- [m](m.md) — m\n")
        self.user = os.path.join(CONFIG, "settings.json")
        self.addCleanup(lambda: os.path.exists(self.user) and os.remove(self.user))

    def warned(self, out, where):
        return any(ln.startswith("p4-temportal: ") and self.store in ln and f"outside {where}" in ln and
                   "blockWritesOutsideWorkingDirectories" in ln for ln in out.splitlines())

    def test_a_block_is_said_where_the_store_is_outside_the_working_directory(self):
        put(self.user, json.dumps({"permissions": {"blockWritesOutsideWorkingDirectories": True}}))
        for where in (self.wt, self.sub):
            put(os.path.join(where, ".claude", "settings.local.json"), json.dumps({"autoMemoryDirectory": self.store}))
        self.assertTrue(self.warned(run("migrate", self.wt, self.store), "this checkout"))
        self.assertTrue(self.warned(run("migrate", self.sub, self.store), "this working directory"))
        self.assertEqual(run("migrate", self.main, self.store), "", "the main checkout holds its store")

    def test_no_block_no_word(self):
        self.assertEqual(run("migrate", self.wt, self.store), "")

    def test_a_folder_the_user_chose_or_added_stays_writable(self):
        block = {"blockWritesOutsideWorkingDirectories": True}
        put(self.user, json.dumps({"permissions": block, "autoMemoryDirectory": self.store}))
        self.assertEqual(run("migrate", self.wt, self.store), "", "a user-chosen folder warned")
        for added in (self.main, self.store):
            put(self.user, json.dumps({"permissions": dict(block, additionalDirectories=[added])}))
            self.assertEqual(run("migrate", self.wt, self.store), "", f"{added} was outside")

    def test_claude_codes_own_folder_is_never_warned_about(self):
        """Without the key Claude Code writes its own folder under the profile, which the block leaves writable."""
        put(self.user, json.dumps({"permissions": {"blockWritesOutsideWorkingDirectories": True}}))
        app = os.path.join(self.base, "config", "projects", "slug", "memory")
        self.assertEqual(run("migrate", self.wt, app), "")

    def test_an_unreadable_managed_file_fails_closed(self):
        managed = os.path.join(self.base, "managed-settings.json")
        put(managed, "{not json")
        out = run("migrate", self.wt, self.store, P4_MANAGED_SETTINGS=managed)
        self.assertTrue(self.warned(out, "this checkout"), out)

    def test_memory_switched_off_says_nothing(self):
        put(self.user, json.dumps({"permissions": {"blockWritesOutsideWorkingDirectories": True}}))
        self.assertEqual(run("migrate", self.wt, self.store, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1"), "")


class AutoMemoryDirectory(unittest.TestCase):
    """The auto memory directory is keyed by the git repository, so a worktree and a subdirectory find the main
    checkout's; CLAUDE_CODE_PROJECT_DIR_NAME names it instead, and autoMemoryDirectory moves it."""

    def test_the_folder_claude_code_writes(self):
        base = tempfile.mkdtemp(prefix="p4-temportal-memory-key-")
        self.addCleanup(wipe, base)
        config = os.path.join(base, "config")
        env = {k: v for k, v in os.environ.items()
               if k not in ("P4_MEMORY_APPDATA", "CLAUDE_CODE_PROJECT_DIR_NAME", "CLAUDE_PROJECT_DIR")}
        env["CLAUDE_CONFIG_DIR"] = config
        main_ = os.path.join(base, "repo")
        os.makedirs(os.path.join(main_, ".git", "worktrees", "wt"))
        put(os.path.join(main_, ".git", "worktrees", "wt", "commondir"), "../..\n")
        wt = os.path.join(base, "wt")
        put(os.path.join(wt, ".git"), f"gitdir: {os.path.join(main_, '.git', 'worktrees', 'wt')}\n")
        sub = os.path.join(main_, "src")
        os.makedirs(sub)
        want = os.path.join(config, "projects", p4_memory.project_slug(main_), "memory")
        with environ(env):
            for where in (main_, sub, wt):
                self.assertEqual(os.path.normpath(p4_memory.appdata_memory({}, where)), os.path.normpath(want), where)
            os.environ["CLAUDE_CODE_PROJECT_DIR_NAME"] = "named"
            self.assertEqual(os.path.normpath(p4_memory.appdata_memory({}, wt)),
                             os.path.join(config, "projects", "named", "memory"))
            del os.environ["CLAUDE_CONFIG_DIR"]             # without it Claude Code ignores the name
            got = p4_memory.appdata_memory({}, wt)
            self.assertEqual(os.path.basename(os.path.dirname(got)), p4_memory.project_slug(main_))
            os.environ["CLAUDE_CONFIG_DIR"] = config
            del os.environ["CLAUDE_CODE_PROJECT_DIR_NAME"]
            put(os.path.join(wt, ".claude", "settings.local.json"), json.dumps({"autoMemoryDirectory": "~/moved"}))
            self.assertEqual(os.path.normpath(p4_memory.appdata_memory({}, wt)),
                             os.path.join(os.path.expanduser("~"), "moved"))


class FailureNotice(unittest.TestCase):
    """A failure, which a start would otherwise swallow, is a systemMessage."""

    def test_a_degraded_or_unknown_subcommand_prints_a_system_message(self):
        root = tempfile.mkdtemp(prefix="p4-temportal-memory-fail-")
        self.addCleanup(wipe, root)
        old = p4_memory.cmd_migrate

        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            p4_memory.cmd_migrate = broken
            for sub, want in (("migrate", "memory migrate degraded: OSError: disk gone"), ("nope", "unknown subcommand")):
                out = hook(sub, {"cwd": root, "hook_event_name": "SessionStart"}, clean_env(CLAUDE_PROJECT_DIR=root))
                self.assertIn(want, json.loads(out)["systemMessage"])
        finally:
            p4_memory.cmd_migrate = old


if __name__ == "__main__":
    unittest.main(verbosity=1)
