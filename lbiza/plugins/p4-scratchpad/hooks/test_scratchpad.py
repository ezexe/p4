#!/usr/bin/env python3
"""test_scratchpad.py — acceptance tests for p4-scratchpad: the notebook's .out/ is seeded (the first time
silently) and re-seeded, ignorables move into it, a clean tree prints nothing at session start (gate 2 (d) of
.docs/p4/fresh-marketplace.md 8.1); with P4_SCRATCHPAD_ASKS=1 the PreToolUse ask fires (never a deny) before a code
file goes to a temp location, the harness scratchpad or the notebook, and repo-uses prints one line per file under
.claude/p4/src/ the repo names; with the switch off both are silent. Run from anywhere:
python3 hooks/test_scratchpad.py — exit 0 = green (git cases skip, saying so, without git on PATH)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "scratchpad.py")
HOOKS_JSON = os.path.join(HERE, "hooks.json")
SCRATCH = "C:/Users/someone/AppData/Local/Temp/claude/E--projects-x/abc123/scratchpad"
MAC_SCRATCH = "/private/tmp/claude-501/-Users-ez-x/f27bc042/scratchpad"
P4_SRC = "E:/projects/x/.claude/p4/src"
PAD = "E:/projects/x/.claude/p4/scratchpad"
ON = {"P4_SCRATCHPAD_ASKS": "1"}


def env_with(extra=None, **kw):
    env = {k: v for k, v in os.environ.items() if k != "P4_SCRATCHPAD_ASKS"}
    env.update(extra or {})
    env.update(kw)
    return env


def run_sub(sub, payload, extra=None, **kw):
    r = subprocess.run([sys.executable, "-I", SCRIPT, sub], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, timeout=60, env=env_with(extra, **kw))
    assert r.returncode == 0, r
    return r.stdout.decode("utf-8", "replace").strip()


def ask(payload, extra=ON):
    out = run_sub("ask", payload, extra)
    if not out:
        return None
    d = json.loads(out)["hookSpecificOutput"]
    assert d["hookEventName"] == "PreToolUse" and d["permissionDecision"] == "ask", d   # never a deny
    return d


def write(path):
    return {"tool_name": "Write", "cwd": "E:/projects/x", "tool_input": {"file_path": path, "content": "x"}}


def bash(cmd):
    return {"tool_name": "Bash", "cwd": "E:/projects/x", "tool_input": {"command": cmd}}


ASK_CASES = [
    write(f"{SCRATCH}/sweep.py"), write(f"{MAC_SCRATCH}/probe.sh"),
    write(f"{PAD}/probe.py"), write(".claude/p4/scratchpad/edit.py"),
    bash("cat > .claude/p4/scratchpad/gen.py <<'EOF'\nprint(1)\nEOF\n"),
    write(f"{PAD}/envtest.cmake"), write(f"{PAD}/probe/CMakeLists.txt"), write(f"{PAD}/probe/Makefile"),
    write(f"{PAD}/harness.html"), write(f"{PAD}/.out/kept.py"),
    bash("cat > /tmp/probe.sh <<'EOF'\necho hi\nEOF\n"),
    bash(f'python - <<\'EOF\'\nopen("{SCRATCH}/gen.py", "w").write("x")\nEOF\n'),
    bash(f"cp tools/x.py {SCRATCH}/x.py"), bash("echo hi | tee -a /tmp/run.sh"),
    {"tool_name": "Edit", "cwd": "E:/projects/x",
     "tool_input": {"file_path": f"{SCRATCH}/sweep.py", "old_string": "a", "new_string": "b"}},
]
PASS_CASES = [
    write(f"{SCRATCH}/commit-msg.txt"), write(f"{SCRATCH}/notes.md"),
    write(f"{P4_SRC}/sweep.py"), write(f"{P4_SRC}/CMakeLists.txt"), write("E:/projects/x/tools/build.py"),
    write("E:/projects/x/CMakeLists.txt"), write("E:/projects/x/web/index.html"),
    write(f"{PAD}/notes.md"), write(f"{PAD}/cmdlines.txt"), write(f"{PAD}/run.log"),
    bash("cat > /tmp/out.json <<'EOF'\n{}\nEOF\n"), bash("grep -n def /tmp/probe.sh"),
    bash("cp /tmp/probe.py tools/probe.py"),
    {"tool_name": "Read", "tool_input": {"file_path": f"{SCRATCH}/sweep.py"}},
]


def asks():
    for p in ASK_CASES:
        d = ask(p)
        assert d, f"did not ask: {p['tool_input']}"
        reason = d["permissionDecisionReason"]
        assert "belongs in the repo" in reason and ".claude/p4/src" in reason.replace("\\", "/"), reason
    for p in PASS_CASES:
        assert ask(p) is None, f"asked: {p['tool_input']}"
    # the reason names the file's home under .claude/p4/src/
    d = ask(write(f"{SCRATCH}/sweep.py"))
    assert "E:/projects/x/.claude/p4/src/sweep.py" in d["permissionDecisionReason"].replace("\\", "/"), d
    # a subagent is never asked: the human answering cannot redirect a running agent
    for p in ASK_CASES:
        assert ask(dict(p, agent_id="agent_01ABC", agent_type="Explore")) is None, f"subagent asked: {p['tool_input']}"
    # the switch: off by default and for any value but 1
    for extra in ({}, {"P4_SCRATCHPAD_ASKS": "0"}, {"P4_SCRATCHPAD_ASKS": ""}, {"P4_SCRATCHPAD_ASKS": "yes"}):
        for p in ASK_CASES:
            assert ask(p, extra) is None, f"asked with {extra}: {p['tool_input']}"
    print("test_scratchpad.py: ask cases green")


def put(base, rel, text="x\n"):
    path = os.path.join(base, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def notebook_out():
    root = tempfile.mkdtemp(prefix="p4-scratchpad-out-")
    pad = os.path.join(root, ".claude", "p4", "scratchpad")

    def sweep():
        return run_sub("notebook-out", {}, CLAUDE_PROJECT_DIR=root)

    def exists(rel):
        return os.path.exists(os.path.join(pad, *rel.split("/")))

    try:
        put(pad, "notes.md")
        put(pad, "run.log", "old\n")
        put(pad, "probe/build/CMakeCache.txt")
        put(pad, "probe/main.txt")
        put(pad, "bin/tool.exe")
        put(pad, ".out/run.log", "kept\n")
        git = shutil.which("git")
        p4 = os.path.join(root, ".claude", "p4")
        if git:
            subprocess.run([git, "init", "-q", p4], check=True)
            subprocess.run([git, "-C", p4, "add", "scratchpad/run.log"], check=True)
        out = sweep()
        assert out.startswith("p4-scratchpad: ") and "\n" not in out, f"not one line: {out}"
        assert "re-seeded .claude/p4/scratchpad/.out/.gitignore" in out and "moved 3" in out, out
        with open(os.path.join(pad, ".out", ".gitignore"), encoding="utf-8") as f:
            assert f.read() == "*\n", "the .out/ ignore is not `*`"
        assert exists("notes.md") and exists("probe/main.txt"), "a note was moved"
        assert not exists("run.log") and not exists("probe/build") and not exists("bin"), "an ignorable stayed"
        assert exists(".out/probe/build/CMakeCache.txt") and exists(".out/bin/tool.exe"), "an ignorable missed .out/"
        with open(os.path.join(pad, ".out", "run.log"), encoding="utf-8") as f:
            assert f.read() == "kept\n", "an existing .out/ file was overwritten"
        taken = [n for n in os.listdir(os.path.join(pad, ".out")) if n.startswith("run.") and n != "run.log"]
        assert len(taken) == 1, os.listdir(os.path.join(pad, ".out"))
        if git:
            assert "1 of them were tracked by the p4 repo" in out, out
            r = subprocess.run([git, "-C", p4, "check-ignore", "-q", "scratchpad/.out/x.log"])
            assert r.returncode == 0, "the p4 repo does not ignore .out/"
            staged = subprocess.run([git, "-C", p4, "diff", "--cached", "--name-only"], capture_output=True,
                                    text=True).stdout
            assert "scratchpad/run.log" in staged, "the hook touched the p4 index"
        # a clean notebook is silent; a changed ignore is re-seeded, a deleted one too
        assert sweep() == "", "a clean notebook spoke"
        put(pad, ".out/.gitignore", "!keep\n")
        assert "re-seeded" in sweep(), "a changed .out/ ignore was not re-seeded"
        os.remove(os.path.join(pad, ".out", ".gitignore"))
        assert "re-seeded" in sweep(), "a deleted .out/ ignore was not re-seeded"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_scratchpad.py: notebook-out cases green")


def repo_uses():
    git = shutil.which("git")
    if not git:
        print("test_scratchpad.py: repo-uses cases SKIPPED — no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-scratchpad-uses-")
    try:
        put(root, ".claude/p4/src/port/compdb.py", "print(1)\n")
        put(root, ".claude/p4/src/probe_cef.py", "print(2)\n")
        put(root, ".claude/p4/src/deploy_mac.sh", "echo\n")
        put(root, ".claude/p4/src/go.sh", "echo\n")
        put(root, ".claude/p4/notes.md", "compdb.py probe_cef.py\n")      # the p4 repo's own files never count
        put(root, ".gitignore", ".claude/p4/\n")
        put(root, "CMakeLists.txt", "add_custom_target(compdb COMMAND python3 ${CMAKE_SOURCE_DIR}/scripts/compdb.py)\n")
        put(root, "README.md", "Run go.sh first.\n")
        put(root, ".github/workflows/ci.yml", "steps:\n  - run: sh deploy_mac.sh\n")

        def uses(extra=ON):
            return run_sub("repo-uses", {"cwd": root}, extra, CLAUDE_PROJECT_DIR=root)

        assert uses() == "", "a project outside git spoke"
        subprocess.run([git, "-C", root, "init", "-q"], check=True)
        subprocess.run([git, "-C", root, "add", "-A"], check=True)
        out = uses().splitlines()
        assert out == ["`.claude/p4/src/deploy_mac.sh` is used by `.github/workflows/ci.yml`; it belongs in the repo.",
                       "`.claude/p4/src/port/compdb.py` is used by `CMakeLists.txt`; it belongs in the repo."], out
        assert uses({}) == "", "repo-uses spoke with the switch off"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_scratchpad.py: repo-uses cases green")


def session_start(root, extra):
    """Every SessionStart command of hooks.json, run as the harness runs it; their output joined."""
    sh = shutil.which("sh")
    with open(HOOKS_JSON, encoding="utf-8") as f:
        cmds = [h["command"] for g in json.load(f)["hooks"]["SessionStart"] for h in g["hooks"]]
    out = []
    for c in cmds:
        r = subprocess.run([sh, "-c", c], input=json.dumps({"cwd": root, "source": "startup"}).encode(),
                           capture_output=True, timeout=60,
                           env=env_with(extra, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=root))
        assert r.returncode == 0, r
        out.append(r.stdout.decode("utf-8", "replace"))
    return "".join(out)


def gate2_d():
    """(d) SessionStart prints nothing on a clean tree: a fresh project (the notebook is seeded silently), the same
    project again, and a git project with notes in the notebook and an unused file in src/ — asks off and on."""
    if not shutil.which("sh"):
        print("test_scratchpad.py: gate 2 (d) SKIPPED — no sh on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-scratchpad-clean-")
    try:
        for extra in ({}, ON):
            assert session_start(root, extra) == "", f"a fresh tree printed (asks {extra or 'off'})"
            with open(os.path.join(root, ".claude", "p4", "scratchpad", ".out", ".gitignore"), encoding="utf-8") as f:
                assert f.read() == "*\n", "the first seed did not happen"
            assert session_start(root, extra) == "", "a second start on a clean tree printed"
        put(root, ".claude/p4/scratchpad/plan.md", "- a note\n")
        put(root, ".claude/p4/src/oneoff_probe.py", "print(1)\n")
        put(root, "main.c", "int main(void) { return 0; }\n")
        if shutil.which("git"):
            subprocess.run(["git", "-C", root, "init", "-q"], check=True)
            subprocess.run(["git", "-C", root, "add", "main.c"], check=True)
        for extra in ({}, ON):
            assert session_start(root, extra) == "", f"a clean tree with notes printed (asks {extra or 'off'})"
        # and the runner exits 0 when the script is broken or missing
        r = subprocess.run([shutil.which("sh"), os.path.join(HERE, "run-hook.sh"), "notebook-out"], input=b"{}",
                           capture_output=True, env=env_with(CLAUDE_PLUGIN_ROOT=root, CLAUDE_PROJECT_DIR=root))
        assert r.returncode == 0, r
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_scratchpad.py: gate 2 (d) green")


def main():
    asks()
    notebook_out()
    repo_uses()
    gate2_d()
    print("test_scratchpad.py: all green")


if __name__ == "__main__":
    main()
