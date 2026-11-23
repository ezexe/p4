#!/usr/bin/env python3
"""test_store.py: tests of p4-temportal's hooks/store.py, the one maker of the project's store, `.claude/p4/`.

Run: python -m pytest tests/p4-temportal/test_store.py

`make` runs as Claude Code runs it, `store.py make` isolated with -I and the hook's JSON on stdin, with
CLAUDE_PROJECT_DIR set. Checked: the store a new project gets, with its p4.json, .gitignore and git repository, and no
`phi/store` and no `phi/models`; the `.git/info/exclude` line never added twice; the store's .gitignore seeded under
its marker. These cases moved from tests/p4-phi/test_hooks.py with the functions.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-temportal", "hooks"))
STORE = os.path.join(SRC, "store.py")
sys.path.insert(0, SRC)
import p4conf  # noqa: E402
import store  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def run_make(proj, payload=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["CLAUDE_PROJECT_DIR"] = proj
    return subprocess.run([sys.executable, "-I", "-X", "utf8", STORE, "make"],
                          input=json.dumps(payload or {"hook_event_name": "SessionStart", "source": "startup",
                                                       "cwd": proj}),
                          capture_output=True, text=True, env=env, timeout=60)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proj = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.proj)
        git(self.proj, "init", "-q")
        self.p4 = os.path.join(self.proj, ".claude", "p4")

    def tearDown(self):
        self.tmp.cleanup()


class Make(Base):
    def test_silent_and_idempotent(self):
        self.assertTrue(os.path.normcase(store.__file__).startswith(os.path.normcase(SRC)),
                        "store.py loads from this checkout")
        r = run_make(self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "SessionStart prints nothing for a store made now")
        for name in (".git", ".gitignore", "p4.json"):
            self.assertTrue(os.path.exists(os.path.join(self.p4, name)), name)
        run_make(self.proj, {"source": "resume", "cwd": self.proj})
        with open(os.path.join(self.proj, ".git", "info", "exclude"), encoding="utf-8") as f:
            self.assertEqual(f.read().count(".claude/p4/"), 1, "the exclude line added once")
        status = subprocess.run(["git", "-C", self.proj, "status", "--porcelain"], capture_output=True, text=True)
        self.assertNotIn(".claude", status.stdout,
                         "the store, a git repository of its own, stays out of the project's git status")

    def snapshot(self):
        out = {}
        for base, dirs, files in os.walk(self.proj):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                p = os.path.join(base, f)
                with open(p, "rb") as h:
                    out[os.path.relpath(p, self.proj)] = (h.read(), os.stat(p).st_mtime_ns)
        with open(os.path.join(self.proj, ".git", "info", "exclude"), "rb") as h:
            out["exclude"] = h.read()
        return out

    def test_make_leaves_the_store_its_text_and_the_one_import_line_and_a_second_make_changes_no_file(self):
        r = run_make(self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("p4.json", ".gitignore", ".git", "CLAUDE.md"):
            self.assertTrue(os.path.exists(os.path.join(self.p4, name)), name)
        with open(os.path.join(self.p4, "CLAUDE.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("p4 plugins' text for this project", text)
        self.assertIn("See more: https://code.claude.com/docs/en/memory.md", text)
        with open(os.path.join(self.proj, "CLAUDE.local.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "@.claude/p4/CLAUDE.md\n")
        before = self.snapshot()
        run_make(self.proj)
        self.assertEqual(self.snapshot(), before, "a second make changes no file")

    def test_a_store_text_that_is_there_is_never_touched(self):
        os.makedirs(self.p4)
        write(os.path.join(self.p4, "CLAUDE.md"), "# mine\n")
        run_make(self.proj)
        with open(os.path.join(self.p4, "CLAUDE.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# mine\n")

    def test_unkeep_leaves_no_settings_file_no_claude_local_md_and_no_exclude_line_of_the_keepers_and_make_writes_none_again(self):
        run_make(self.proj)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["CLAUDE_PROJECT_DIR"] = self.proj
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", STORE, "unkeep"], input="{}", capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("p4-temportal: ", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude", "settings.local.json")))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "CLAUDE.local.md")))
        with open(os.path.join(self.proj, ".git", "info", "exclude"), encoding="utf-8") as f:
            rows = [l.strip() for l in f.read().splitlines() if l.strip() and not l.startswith("#")]
        self.assertEqual(rows, [".claude/p4/"])
        run_make(self.proj)
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude", "settings.local.json")))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "CLAUDE.local.md")))
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", STORE, "keep"], input="{}", capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.proj, ".claude", "settings.local.json")))
        self.assertTrue(os.path.exists(os.path.join(self.proj, "CLAUDE.local.md")))

    def test_the_project_is_the_inputs_cwd_where_no_variable_is_set(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", STORE, "make"], input=json.dumps({"cwd": self.proj}),
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "p4.json")))

    def test_init_layout_makes_no_phi_store_and_no_phi_models(self):
        self.assertEqual(store.init_layout(self.proj), [], "nothing to move in a store made now")
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "p4.json")))
        for sub in ("store", "models"):
            self.assertFalse(os.path.exists(p4conf.sub(self.p4, sub)), sub)
        run_make(self.proj)
        self.assertFalse(os.path.exists(p4conf.sub(self.p4, "store")), "the hook makes none either")
        self.assertFalse(os.path.exists(p4conf.sub(self.p4, "models")))
        self.assertFalse(os.path.exists(os.path.join(self.p4, ".github")), "no sync workflow is seeded")

    def test_an_unknown_command_exits_0_and_says_so(self):
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", STORE, "nosuch"], input="{}", capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", r.stdout)


class Gitignore(Base):
    def gitignore(self, text=None):
        os.makedirs(self.p4, exist_ok=True)
        gi = os.path.join(self.p4, ".gitignore")
        if text is not None:
            write(gi, text)
        run_make(self.proj)
        with open(gi, encoding="utf-8") as f:
            return f.read()

    def test_gitignore_missing_seeded_lines_are_appended_under_a_marker(self):
        old = "# seeded once by p4-recall; your edits win\ntemportal/scratchpad/.out/\n__pycache__/\n*.png\n*.jpg\n" \
              "*.zip\n*.gz\n# mine\nbuild/\n"
        got = self.gitignore(old)
        self.assertTrue(got.startswith(old), "what was there is untouched and in its order")
        tail = got[len(old):].splitlines()
        self.assertRegex(tail[0], r"^# seeded by p4-recall \d{4}-\d{2}-\d{2}$")
        self.assertEqual(tail[1:], ["temportal/notebook/.out/", "phi/served/", ".layout.lock",
                                    ".settings.lock", "claude-settings.json", "phi/claude-code-watch.pending.json*",
                                    "phi/sessions/*/log.jsonl", "phi/sessions/*/session.md", "phi/sessions.md",
                                    "phi/rules.md", "phi/catchup.json", "phi/**/*.tmp", "phi/**/*.lock",
                                    "phi/sessions/*/.calls/", "phi/.agents/", "phi/.nudge/", ".venv/", "*.pyc"])
        self.assertNotIn("phi/models", got, "no line of the removed models folder is seeded")
        self.assertEqual(self.gitignore(), got, "a second run adds nothing")
        self.assertEqual(store.seed_gitignore(os.path.join(self.p4, ".gitignore")), [])

    def test_gitignore_vlds_header_counts_as_a_marker(self):
        got = self.gitignore("# Seeded by the vlds plugin (hooks/p4-layout.sh) when the repository has no .gitignore; "
                             "ezexe's edits win.\n*.wav\nphi/served/\n")
        self.assertIn("\n# seeded by p4-recall ", got)
        self.assertTrue(got.endswith("*.gz\n"))
        self.assertIn("temportal/notebook/.out/\n", got)
        self.assertEqual(got.count("phi/served/\n"), 1, "a line the file already holds is never appended again")

    def test_gitignore_without_marker_is_ezexes(self):
        theirs = "*.wav\nphi/served/\nbuild/\n"
        self.assertEqual(self.gitignore(theirs), theirs, "a seeded line present and no marker: ezexe's edits win")
        own = "# my rules\nbuild/\n*.log\n"
        got = self.gitignore(own)
        self.assertTrue(got.startswith(own) and "# seeded by p4-recall " in got and got.endswith("*.gz\n"),
                        "no seeded line at all: the whole block, under the marker")
        # ezexe deletes the marker block: nothing comes back
        cut = got[:got.index("# seeded by p4-recall")] + "*.gz\n"
        self.assertEqual(self.gitignore(cut), cut)


class ExcludeLine(Base):
    def test_the_line_is_added_once_and_a_line_naming_the_store_counts(self):
        self.assertTrue(store.exclude_line(self.proj))
        self.assertFalse(store.exclude_line(self.proj))
        shutil.rmtree(os.path.join(self.proj, ".git", "info"))
        write(os.path.join(self.proj, ".git", "info", "exclude"), "/.claude/p4\n")
        self.assertFalse(store.exclude_line(self.proj), "a line that names .claude/p4 is enough")


if __name__ == "__main__":
    unittest.main()
