#!/usr/bin/env python3
"""test_saved.py: p4-skillex's saved code in `.claude/p4/skillex/src/` and its two asks. With P4_SKILLEX_ASKS=1 the
PreToolUse ask fires, and never denies, before a code file goes to a temp location, the session's scratchpad path or
the notebook, and repo-uses prints one line for each file under `.claude/p4/skillex/src/` the repository names; with
the switch off both are silent. A store whose saved code is still in `temportal/src/` has it moved at the start, and
a p4.json that keeps the asks' keys under `scratchpad` has them moved to `skillex`.

    python -I -X utf8 lbiza/plugins/p4-skillex/hooks/test_saved.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import saved  # noqa: E402
import skillex  # noqa: E402
from test_skillex import Env, put, read  # noqa: E402

SCRATCH = "C:/Users/someone/AppData/Local/Temp/claude/30ad6e18862a20e8/abc123/scratchpad"
MAC_SCRATCH = "/private/tmp/claude-501/-Users-ez-x/f27bc042/scratchpad"
P4_SRC = "E:/projects/x/.claude/p4/skillex/src"
PAD = "E:/projects/x/.claude/p4/temportal/scratchpad"
ON = {"P4_SKILLEX_ASKS": "1"}
X = "E:/projects/x"


def write(path):
    return {"tool_name": "Write", "cwd": X, "tool_input": {"file_path": path, "content": "x"}}


def bash(cmd):
    return {"tool_name": "Bash", "cwd": X, "tool_input": {"command": cmd}}


ASK_CASES = [
    write(f"{SCRATCH}/sweep.py"), write(f"{MAC_SCRATCH}/probe.sh"),
    write(f"{PAD}/probe.py"), write(".claude/p4/temportal/scratchpad/edit.py"),
    bash("cat > .claude/p4/temportal/scratchpad/gen.py <<'EOF'\nprint(1)\nEOF\n"),
    write(f"{PAD}/envtest.cmake"), write(f"{PAD}/probe/CMakeLists.txt"), write(f"{PAD}/probe/Makefile"),
    write(f"{PAD}/harness.html"), write(f"{PAD}/.out/kept.py"),
    bash("cat > /tmp/probe.sh <<'EOF'\necho hi\nEOF\n"),
    bash(f'python - <<\'EOF\'\nopen("{SCRATCH}/gen.py", "w").write("x")\nEOF\n'),
    bash(f"cp tools/x.py {SCRATCH}/x.py"), bash("echo hi | tee -a /tmp/run.sh"),
    {"tool_name": "Edit", "cwd": X,
     "tool_input": {"file_path": f"{SCRATCH}/sweep.py", "old_string": "a", "new_string": "b"}},
]
PASS_CASES = [
    write(f"{SCRATCH}/commit-msg.txt"), write(f"{SCRATCH}/notes.md"),
    write(f"{P4_SRC}/sweep.py"), write(f"{P4_SRC}/CMakeLists.txt"), write(f"{X}/tools/build.py"),
    write(f"{X}/CMakeLists.txt"), write(f"{X}/web/index.html"),
    write(f"{PAD}/notes.md"), write(f"{PAD}/cmdlines.txt"), write(f"{PAD}/run.log"),
    bash("cat > /tmp/out.json <<'EOF'\n{}\nEOF\n"), bash("grep -n def /tmp/probe.sh"),
    bash("cp /tmp/probe.py tools/probe.py"),
    {"tool_name": "Read", "tool_input": {"file_path": f"{SCRATCH}/sweep.py"}},
]

STORE_X = os.path.join(X, ".claude", "p4")


def ask(payload, extra=ON):
    with Env(**{"P4_SKILLEX_ASKS": "", "P4_SCRATCHPAD_ASKS": "", **extra}):
        d = saved.cmd_ask(STORE_X, payload)
    if d is None:
        return None
    d = d["hookSpecificOutput"]
    assert d["hookEventName"] == "PreToolUse" and d["permissionDecision"] == "ask", d   # never a deny
    return d


class Ask(unittest.TestCase):
    def test_code_headed_for_a_temp_place_is_asked_about_and_nothing_else(self):
        for p in ASK_CASES:
            d = ask(p)
            self.assertTrue(d, f"did not ask: {p['tool_input']}")
            reason = d["permissionDecisionReason"].replace("\\", "/")
            self.assertIn("belongs in the repo", reason)
            self.assertIn(".claude/p4/skillex/src", reason)
        for p in PASS_CASES:
            self.assertIsNone(ask(p), f"asked: {p['tool_input']}")

    def test_the_reason_names_the_file_home_in_saved_code(self):
        d = ask(write(f"{SCRATCH}/sweep.py"))
        self.assertIn(f"{P4_SRC}/sweep.py", d["permissionDecisionReason"].replace("\\", "/"))
        self.assertTrue(d["permissionDecisionReason"].startswith("p4-skillex: "))

    def test_a_subagent_is_never_asked(self):
        """ezexe, who answers the prompt, cannot redirect a running agent."""
        for p in ASK_CASES:
            self.assertIsNone(ask(dict(p, agent_id="agent_01ABC", agent_type="Explore")), p["tool_input"])

    def test_the_old_switch_still_turns_the_asks_on_while_the_new_one_is_unset(self):
        self.assertTrue(ask(write(f"{SCRATCH}/sweep.py"), {"P4_SKILLEX_ASKS": "", "P4_SCRATCHPAD_ASKS": "1"}))
        self.assertIsNone(ask(write(f"{SCRATCH}/sweep.py"), {"P4_SKILLEX_ASKS": "0", "P4_SCRATCHPAD_ASKS": "1"}),
                          "the new name wins")

    def test_the_switch_is_off_by_default_and_for_any_value_but_1(self):
        for extra in ({}, {"P4_SKILLEX_ASKS": "0"}, {"P4_SKILLEX_ASKS": ""}, {"P4_SKILLEX_ASKS": "yes"}):
            for p in ASK_CASES:
                self.assertIsNone(ask(p, extra), f"asked with {extra}: {p['tool_input']}")

    def test_the_hook_prints_the_ask_as_json(self):
        root = tempfile.mkdtemp(prefix="p4-skillex-ask-")
        old = sys.argv, sys.stdin, sys.stdout
        try:
            import io
            sys.argv = ["skillex.py", "ask"]
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(write("/tmp/probe.py")).encode()), encoding="utf-8")
            sys.stdout = io.StringIO()
            with Env(CLAUDE_PROJECT_DIR=root, **ON):
                self.assertEqual(skillex.main(), 0)
            out = json.loads(sys.stdout.getvalue())
        finally:
            sys.argv, sys.stdin, sys.stdout = old
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")


class Store(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-skillex-saved-")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        os.makedirs(self.p4)
        self.git = shutil.which("git")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def g(self, *a, cwd=None):
        return subprocess.run([self.git, "-C", cwd or self.p4, *a], capture_output=True, text=True, check=True).stdout

    def test_repo_uses_names_saved_code_the_repository_uses(self):
        if not self.git:
            self.skipTest("no git")
        r = self.root
        put(os.path.join(r, ".claude/p4/skillex/src/port/compdb.py"), "print(1)\n")
        put(os.path.join(r, ".claude/p4/skillex/src/probe_cef.py"), "print(2)\n")
        put(os.path.join(r, ".claude/p4/skillex/src/deploy_mac.sh"), "echo\n")
        put(os.path.join(r, ".claude/p4/skillex/src/go.sh"), "echo\n")
        put(os.path.join(r, ".claude/p4/notes.md"), "compdb.py probe_cef.py\n")      # the store's own files never count
        put(os.path.join(r, ".gitignore"), ".claude/p4/\n")
        put(os.path.join(r, "CMakeLists.txt"), "add_custom_target(compdb COMMAND python3 ${CMAKE_SOURCE_DIR}/scripts/compdb.py)\n")
        put(os.path.join(r, "README.md"), "Run go.sh first.\n")
        put(os.path.join(r, ".github/workflows/ci.yml"), "steps:\n  - run: sh deploy_mac.sh\n")

        def uses(extra=ON):
            with Env(**{"P4_SKILLEX_ASKS": "", **extra}):
                return saved.cmd_repo_uses(self.p4, {"cwd": r})

        self.assertIsNone(uses(), "a project outside git spoke")
        self.g("init", "-q", cwd=r)
        self.g("add", "-A", cwd=r)
        self.assertEqual(uses().splitlines(), [
            "`.claude/p4/skillex/src/deploy_mac.sh` is used by `.github/workflows/ci.yml`; it belongs in the repo.",
            "`.claude/p4/skillex/src/port/compdb.py` is used by `CMakeLists.txt`; it belongs in the repo."])
        self.assertIsNone(uses({}), "repo-uses spoke with the switch off")

    def test_saved_code_in_temportal_moves_to_skillex_at_the_start(self):
        put(os.path.join(self.p4, "temportal", "src", "tool.py"), "print(1)\n")
        put(os.path.join(self.p4, "temportal", "memory", "MEMORY.md"), "- [a](a.md)\n")
        put(os.path.join(self.p4, "temportal", ".layout-conflicts", "memory", "old.md"), "o\n")
        put(os.path.join(self.p4, ".gitignore"), "temportal/src/*.log\ntemportal/scratchpad/.out/\n")
        if self.git:
            self.g("init", "-q")
            self.g("add", "-A")
            self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "saved code in temportal")
        out = skillex.cmd_start(self.p4, {})
        self.assertIn("moved temportal/src/ to skillex/src/", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(read(os.path.join(self.p4, "skillex", "src", "tool.py")), "print(1)\n")
        self.assertFalse(os.path.exists(os.path.join(self.p4, "temportal", "src")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", "memory", "MEMORY.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", ".layout-conflicts", "memory", "old.md")),
                        "temportal's own set-aside copies stay in temportal")
        self.assertFalse(os.path.exists(os.path.join(self.p4, "phi")), "nothing is carried to phi/")
        self.assertEqual(read(os.path.join(self.p4, ".gitignore")), "skillex/src/*.log\ntemportal/scratchpad/.out/\n")
        self.assertEqual(skillex.store_skills(self.p4), [], "saved code is no skill")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude", "skills", "src")), "and is never copied")
        if self.git:
            self.assertIn("R100\ttemportal/src/tool.py\tskillex/src/tool.py",
                          self.g("show", "-M", "--name-status", "--format=", "HEAD"))
            self.assertEqual(self.g("status", "--porcelain", "--", "temportal", "skillex/src").strip(), "")
        self.assertEqual(p4conf.migrate_layout(self.p4), [], "a second start has nothing to move")
        self.assertEqual(skillex.free_name(self.p4, "src"), "src-2", "no skill takes saved code's folder")

    def test_the_asks_keys_move_from_scratchpad_to_skillex_in_p4_json(self):
        old = p4conf.load(self.p4, write=False)          # complete, as p4-temportal's p4conf wrote it
        old.pop("skillex")
        old["scratchpad"].update(asks=True, tmp=False, repo_uses_min_name=6, repo_uses_max=200, repo_uses_lines=3)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump(old, f)
        s = p4conf.load(self.p4)
        self.assertEqual((s["skillex"]["asks"], s["skillex"]["repo_uses_lines"]), (True, 3))
        self.assertNotIn("asks", s["scratchpad"])
        self.assertFalse(s["scratchpad"]["tmp"], "the keys that stay keep their values")
        on_disk = json.loads(read(p4conf.path(self.p4)))
        self.assertNotIn("repo_uses_lines", on_disk["scratchpad"])
        self.assertEqual(on_disk["skillex"]["asks"], True)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"scratchpad": {"asks": True}, "skillex": {"asks": False}}, f)
        self.assertFalse(p4conf.load(self.p4)["skillex"]["asks"], "a value already at the new place wins")
        old = saved.ASKS
        try:
            with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
                json.dump({"skillex": {"asks": True}}, f)
            with Env(P4_SKILLEX_ASKS=""):
                self.assertTrue(ask_in(self.p4, write("/tmp/probe.py")), "p4.json's skillex.asks turns the ask on")
        finally:
            saved.ASKS = old


def ask_in(p4, payload):
    return saved.cmd_ask(p4, payload)


if __name__ == "__main__":
    unittest.main()
