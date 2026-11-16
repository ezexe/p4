#!/usr/bin/env python3
"""test_live_loading.py: a real Claude Code is offered a store skill and loads it, with no model run.

Each case starts `claude -p` in a fresh project with every API call sent to a closed local port, so no model runs and
nothing is spent. The stream's init message lists the skills the session is offered, and a typed `/<name>` that
resolves to a skill fires the UserPromptExpansion hook, which a project settings file records. The run is stopped
at the first API retry.

It starts a real process for several seconds a case, so it runs only when asked:

    P4_SKILLEX_LIVE=1 python -I -X utf8 lbiza/plugins/p4-skillex/hooks/test_live_loading.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import skillex  # noqa: E402

CLAUDE = shutil.which("claude")
LIVE = os.environ.get("P4_SKILLEX_LIVE") == "1" and CLAUDE
CLOSED = "http://127.0.0.1:9"
NAME = "demo-brew"
DUMP = "import sys\nopen(sys.argv[1], 'w', encoding='utf-8').write(sys.stdin.read())\n"
INSTALL = """import json, os, sys, time
d = os.path.join(sys.argv[1], ".claude", "skills", "demo-late")
time.sleep(1.5)
os.makedirs(d, exist_ok=True)
with open(os.path.join(d, "SKILL.md"), "w") as f:
    f.write("---\\nname: demo-late\\ndescription: written by a start hook.\\n---\\nSay late.\\n")
if sys.argv[2] == "1":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}}))
"""


def run_claude(project, prompt, *extra, wait_s=60):
    """Start `claude -p` in `project` with no way out to an API; return the init message and the stream's types."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "P4_", "ANTHROPIC"))}
    env.update(ANTHROPIC_API_KEY="sk-closed-port", ANTHROPIC_BASE_URL=CLOSED, HTTPS_PROXY=CLOSED, HTTP_PROXY=CLOSED,
               MSYS_NO_PATHCONV="1")
    p = subprocess.Popen([CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose", *extra],
                         cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         encoding="utf-8")
    init, kinds, end = None, [], time.monotonic() + wait_s
    try:
        for line in p.stdout:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            kinds.append(m.get("subtype") or m.get("type"))
            if m.get("subtype") == "init":
                init = m
            if m.get("subtype") == "api_retry" or time.monotonic() > end:
                time.sleep(2)                      # a hook started before the request may still be writing
                break
    finally:
        p.kill()
        p.wait()
        p.stdout.close()
    return init, kinds


@unittest.skipUnless(LIVE, "set P4_SKILLEX_LIVE=1 with claude on PATH")
class Live(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-skillex-live-")
        self.git = shutil.which("git")
        if self.git:                                     # a repository, so each copy's .gitignore takes effect
            subprocess.run([self.git, "init", "-q", self.root], check=True)
        self.p4 = os.path.join(self.root, ".claude", "p4")
        os.makedirs(os.path.join(self.p4, "temportal"))     # the watcher acts only beside p4-temportal's folder
        d = os.path.join(self.p4, "skillex", NAME)
        os.makedirs(d)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {NAME}\ndescription: A store skill for the live loading test.\n---\n\nSay demo.\n")
        self.seen = os.path.join(self.root, "expansion.json")
        dump = os.path.join(self.root, "dump.py")
        with open(dump, "w", encoding="utf-8") as f:
            f.write(DUMP)
        py = sys.executable.replace("\\", "/")
        hook = {"type": "command", "command": f'"{py}" -I "{dump.replace(os.sep, "/")}" "{self.seen.replace(os.sep, "/")}"'}
        with open(os.path.join(self.root, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks": {"UserPromptExpansion": [{"hooks": [hook]}]}}, f)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def expansion(self):
        try:
            with open(self.seen, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def test_a_store_skill_copied_before_the_start_is_offered_and_loads(self):
        skillex.cmd_start(self.p4, {})
        if self.git:
            ignored = subprocess.run([self.git, "-C", self.root, "check-ignore", "-q",
                                      f".claude/skills/{NAME}/SKILL.md"])
            self.assertEqual(ignored.returncode, 0, "git ignores the copy")
        init, kinds = run_claude(self.root, f"/{NAME}", "--setting-sources", "project")
        self.assertIsNotNone(init, kinds)
        self.assertIn(NAME, init["skills"], "an ignored copy is still offered")
        got = self.expansion()
        self.assertIsNotNone(got, "the typed /name never expanded")
        self.assertEqual((got["command_name"], got["command_source"], got["expansion_type"]),
                         (NAME, "projectSettings", "slash_command"))

    def test_the_plugin_start_hook_offers_a_store_skill_in_the_same_session(self):
        init, kinds = run_claude(self.root, "x", "--setting-sources", "project", "--plugin-dir", PLUGIN)
        self.assertIsNotNone(init, kinds)
        self.assertIn("p4-skillex", [p["name"] for p in init["plugins"]])
        self.assertIn(NAME, init["skills"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".claude", "skills", NAME, skillex.MARKER)))

    def test_reload_skills_is_what_lists_a_skill_a_start_hook_writes(self):
        """The field p4-skillex's start returns, decided: the hooks reference promises it under "Reload skills that a
        hook installs", and here a start hook that writes a skill a moment after the start shows it at init only
        when it returns `reloadSkills`."""
        install = os.path.join(self.root, "install.py")
        with open(install, "w", encoding="utf-8") as f:
            f.write(INSTALL)
        py = sys.executable.replace("\\", "/")
        listed = {}
        for reload in (False, True):
            shutil.rmtree(os.path.join(self.root, ".claude", "skills"), ignore_errors=True)
            os.makedirs(os.path.join(self.root, ".claude", "skills"))
            hook = {"type": "command", "command": f'"{py}" -I "{install.replace(os.sep, "/")}" '
                                                  f'"{self.root.replace(os.sep, "/")}" {int(reload)}'}
            with open(os.path.join(self.root, ".claude", "settings.json"), "w", encoding="utf-8") as f:
                json.dump({"hooks": {"SessionStart": [{"hooks": [hook]}]}}, f)
            init, kinds = run_claude(self.root, "x", "--setting-sources", "project")
            self.assertIsNotNone(init, kinds)
            listed[reload] = "demo-late" in init["skills"]
        self.assertEqual(listed, {False: False, True: True})

    def test_gap_under_print_the_first_prompt_misses_a_skill_the_start_hook_reloaded(self):
        """A platform gap, kept as a test so a fix shows: the skill is in the init listing after reloadSkills, yet
        the first prompt typed as /name under -p is not expanded. The next session finds the copy at its start."""
        init, kinds = run_claude(self.root, f"/{NAME}", "--setting-sources", "project", "--plugin-dir", PLUGIN)
        self.assertIsNotNone(init, kinds)
        self.assertIn(NAME, init["skills"])
        self.assertIsNone(self.expansion(), "fixed upstream: drop this gap from the report")


if __name__ == "__main__":
    unittest.main()
