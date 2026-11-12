#!/usr/bin/env python3
"""test_scratchpad.py — acceptance tests for p4-temportal's scratchpad part: the notebook's .out/ is seeded (the first time
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
P4_SRC = "E:/projects/x/.claude/p4/temportal/src"
PAD = "E:/projects/x/.claude/p4/temportal/scratchpad"
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
    write(f"{PAD}/probe.py"), write(".claude/p4/temportal/scratchpad/edit.py"),
    bash("cat > .claude/p4/temportal/scratchpad/gen.py <<'EOF'\nprint(1)\nEOF\n"),
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
        assert "belongs in the repo" in reason and ".claude/p4/temportal/src" in reason.replace("\\", "/"), reason
    for p in PASS_CASES:
        assert ask(p) is None, f"asked: {p['tool_input']}"
    # the reason names the file's home under .claude/p4/src/
    d = ask(write(f"{SCRATCH}/sweep.py"))
    assert "E:/projects/x/.claude/p4/temportal/src/sweep.py" in d["permissionDecisionReason"].replace("\\", "/"), d
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
    pad = os.path.join(root, ".claude", "p4", "temportal", "scratchpad")

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
            subprocess.run([git, "-C", p4, "add", "temportal/scratchpad/run.log"], check=True)
        out = sweep()
        assert out.startswith("p4-temportal: ") and "\n" not in out, f"not one line: {out}"
        assert "re-seeded .claude/p4/temportal/scratchpad/.out/.gitignore" in out and "moved 3" in out, out
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
            r = subprocess.run([git, "-C", p4, "check-ignore", "-q", "temportal/scratchpad/.out/x.log"])
            assert r.returncode == 0, "the p4 repo does not ignore .out/"
            staged = subprocess.run([git, "-C", p4, "diff", "--cached", "--name-only"], capture_output=True,
                                    text=True).stdout
            assert "temportal/scratchpad/run.log" in staged, "the hook touched the p4 index"
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
        put(root, ".claude/p4/temportal/src/port/compdb.py", "print(1)\n")
        put(root, ".claude/p4/temportal/src/probe_cef.py", "print(2)\n")
        put(root, ".claude/p4/temportal/src/deploy_mac.sh", "echo\n")
        put(root, ".claude/p4/temportal/src/go.sh", "echo\n")
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
        assert out == ["`.claude/p4/temportal/src/deploy_mac.sh` is used by `.github/workflows/ci.yml`; it belongs in the repo.",
                       "`.claude/p4/temportal/src/port/compdb.py` is used by `CMakeLists.txt`; it belongs in the repo."], out
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
            with open(os.path.join(root, ".claude", "p4", "temportal", "scratchpad", ".out", ".gitignore"), encoding="utf-8") as f:
                assert f.read() == "*\n", "the first seed did not happen"
            assert session_start(root, extra) == "", "a second start on a clean tree printed"
        put(root, ".claude/p4/temportal/scratchpad/plan.md", "- a note\n")
        put(root, ".claude/p4/temportal/src/oneoff_probe.py", "print(1)\n")
        put(root, "main.c", "int main(void) { return 0; }\n")
        if shutil.which("git"):
            subprocess.run(["git", "-C", root, "init", "-q"], check=True)
            subprocess.run(["git", "-C", root, "add", "main.c"], check=True)
        for extra in ({}, ON):
            assert session_start(root, extra) == "", f"a clean tree with notes printed (asks {extra or 'off'})"
        # and the runner exits 0 when the script is broken or missing
        r = subprocess.run([shutil.which("sh"), os.path.join(HERE, "run-hook.sh"), "scratchpad", "notebook-out"], input=b"{}",
                           capture_output=True, env=env_with(CLAUDE_PLUGIN_ROOT=root, CLAUDE_PROJECT_DIR=root))
        assert r.returncode == 0, r
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("test_scratchpad.py: gate 2 (d) green")


def tmp_cases():
    """tmp-link: the harness's scratchpad, found under the temp directory by the session id, becomes a link into
    .claude/p4/tmp/<session>/ with what it held moved in; a second start is silent; a write through the old path lands
    in p4; a link elsewhere is left; P4_SCRATCHPAD_TMP=0 does nothing; tmp-sweep links a scratchpad made after the start."""
    root = tempfile.mkdtemp(prefix="p4-scratchpad-tmp-")
    temp = tempfile.mkdtemp(prefix="p4-scratchpad-temp-")
    sid = "d419de0b-c6f0-4894-899a-bdbe514efa5d"
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp}
    try:
        harness = os.path.join(temp, "claude", "30ad6e18862a20e8", sid, "scratchpad")
        target = os.path.join(root, ".claude", "p4", "temportal", "tmp", sid)
        put(harness, "notes.md", "- a note\n")
        put(harness, "sub/part.md", "part\n")
        payload = {"cwd": root, "session_id": sid}

        def run(sub, extra=None):
            return run_sub(sub, payload, dict(tmp_env, **(extra or {})), CLAUDE_PROJECT_DIR=root)

        assert run("tmp-link", {"P4_SCRATCHPAD_TMP": "0"}) == "", "the switch off still spoke"
        assert not os.path.exists(target), "the switch off still made .claude/p4/temportal/tmp/"
        out = run("tmp-link")
        assert "is a link to" in out and "moved 2 file(s)" in out, out
        with open(os.path.join(target, "notes.md"), encoding="utf-8") as f:
            assert f.read() == "- a note\n", "the scratchpad's note did not move"
        assert os.path.isfile(os.path.join(target, "sub", "part.md")), "a subdirectory did not move"
        put(harness, "later.md", "later\n")
        assert os.path.isfile(os.path.join(target, "later.md")), "a write through the link did not land in p4"
        assert run("tmp-link") == "", "a second start spoke"
        assert run("tmp-sweep") == "", "the sweep spoke"
        assert run_sub("tmp-link", {"cwd": root}, tmp_env, CLAUDE_PROJECT_DIR=root) == "", "no session id spoke"

        # a scratchpad made after the start (the link removed, a plain directory in its place) is linked at the close
        os.rmdir(harness) if os.name == "nt" else os.unlink(harness)
        put(harness, "after.md", "after\n")
        assert run("tmp-sweep") == "", "the sweep spoke"
        assert os.path.isfile(os.path.join(target, "after.md")), "the sweep did not move a late file"
        put(harness, "after2.md", "again\n")
        assert os.path.isfile(os.path.join(target, "after2.md")), "the sweep did not link the scratchpad again"

        # a link elsewhere is the owner's: left as it is
        other = tempfile.mkdtemp(prefix="p4-scratchpad-other-")
        try:
            os.rmdir(harness) if os.name == "nt" else os.unlink(harness)
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(other, harness)
            else:
                os.symlink(other, harness, target_is_directory=True)
            assert "does not reach" in run("tmp-link"), "a foreign link was not named"
            assert os.path.samefile(harness, other), "a foreign link was changed"
        finally:
            os.rmdir(harness) if os.name == "nt" else os.unlink(harness)
            shutil.rmtree(other, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(temp, ignore_errors=True)
    print("test_scratchpad.py: tmp cases green")


def tmp_keep_cases():
    """The tmp is always staged, and deleted only after it is committed: tmp-sweep stages the session's files in the
    p4 repo (never an ignored file, never one over the size cap) and says nothing; tmp-close commits them alone,
    leaving what else is staged as it was, deletes what the commit holds, and commits the removal; a file no commit
    holds stays on disk; the link still works; a session that starts again gets its files back; another session's
    tmp left idle past the limit is closed the same way at a start; without a git repository nothing is deleted."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp keep cases skipped (no git on PATH)")
        return
    root = tempfile.mkdtemp(prefix="p4-scratchpad-keep-")
    temp = tempfile.mkdtemp(prefix="p4-scratchpad-temp-")
    sid, old, live = "aaaa1111-0000-4000-8000-000000000001", "bbbb2222-0000-4000-8000-000000000002", \
        "cccc3333-0000-4000-8000-000000000003"
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp}
    p4 = os.path.join(root, ".claude", "p4")

    def git(*args):
        r = subprocess.run(["git", "-C", p4] + list(args), capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    try:
        harness = os.path.join(temp, "claude", "30ad6e18862a20e8", sid, "scratchpad")
        target = os.path.join(p4, "temportal", "tmp", sid)
        payload = {"cwd": root, "session_id": sid}

        def run(sub, extra=None):
            return run_sub(sub, payload, dict(tmp_env, **(extra or {})), CLAUDE_PROJECT_DIR=root)

        # no git repository at .claude/p4: nothing is staged, nothing is deleted
        put(harness, "notes.md", "- a note\n")
        run("tmp-link")
        assert run("tmp-sweep") == "" and run("tmp-close") == "", "no repository, and a hook spoke"
        assert os.path.isfile(os.path.join(target, "notes.md")), "a file was deleted with no commit to hold it"

        os.makedirs(p4, exist_ok=True)
        subprocess.run(["git", "init", "-q", p4], check=True)
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        put(p4, ".gitignore", "*.pyc\n")
        put(p4, "p4.json", json.dumps({"version": 1, "scratchpad": {"tmp_max_file_mb": 0.001}}))
        put(p4, "store/first.md", "first\n")
        git("add", ".gitignore", "store/first.md")
        git("commit", "-q", "-m", "first")
        put(p4, "store/other.md", "another session's work, staged\n")
        git("add", "store/other.md")
        put(harness, "sub/part.md", "part\n")
        put(harness, "big.bin", "x" * 5000)                       # over the cap of 0.001 MB
        put(harness, "mod.pyc", "ignored\n")

        assert run("tmp-sweep") == "", "the sweep spoke"
        staged = set(git("diff", "--cached", "--name-only").split())
        assert {f"temportal/tmp/{sid}/notes.md", f"temportal/tmp/{sid}/sub/part.md"} <= staged, staged
        assert not any(n.endswith(("big.bin", "mod.pyc")) for n in staged), staged

        commits = int(git("rev-list", "--count", "HEAD"))
        assert run("tmp-close") == "", "the close spoke"
        assert int(git("rev-list", "--count", "HEAD")) == commits + 2, "not one commit to keep and one to remove"
        kept = git("show", "--name-only", "--format=", "HEAD~1").split()
        assert sorted(kept) == [f"temportal/tmp/{sid}/notes.md", f"temportal/tmp/{sid}/sub/part.md"], kept
        assert git("show", f"HEAD~1:temportal/tmp/{sid}/notes.md") == "- a note\n", "the commit does not hold the note"
        assert git("ls-files", "temportal/tmp").strip() == "", "the removal is not committed"
        assert git("diff", "--cached", "--name-only").split() == ["store/other.md"], "another staged file was swept in"
        assert not os.path.exists(os.path.join(target, "notes.md")), "the committed note is still on disk"
        assert not os.path.exists(os.path.join(target, "sub")), "an emptied directory is still there"
        for name in ("big.bin", "mod.pyc"):
            assert os.path.isfile(os.path.join(target, name)), f"{name} was deleted though no commit holds it"
        put(harness, "after.md", "after\n")
        assert os.path.isfile(os.path.join(target, "after.md")), "the link no longer reaches the tmp"

        # the session starts again: what the close removed is back, and staged
        out = run("tmp-link")
        assert "restored" in out, out
        with open(os.path.join(target, "notes.md"), encoding="utf-8") as f:
            assert f.read() == "- a note\n", "the note did not come back"
        assert os.path.isfile(os.path.join(target, "sub", "part.md")), "a subdirectory did not come back"
        assert run("tmp-link") == "", "a second start spoke"

        # another session's tmp, idle past the limit, is closed at a start; one written today is left
        put(os.path.join(p4, "temportal", "tmp", old), "old.md", "old\n")
        put(os.path.join(p4, "temportal", "tmp", live), "live.md", "live\n")
        long_ago = os.path.getmtime(os.path.join(p4, "temportal", "tmp", old, "old.md")) - 30 * 86400
        os.utime(os.path.join(p4, "temportal", "tmp", old, "old.md"), (long_ago, long_ago))
        os.utime(os.path.join(p4, "temportal", "tmp", old), (long_ago, long_ago))
        run("tmp-link")
        assert not os.path.exists(os.path.join(p4, "temportal", "tmp", old, "old.md")), "an idle tmp was not removed"
        assert "old\n" == git("show", f"HEAD~1:temportal/tmp/{old}/old.md"), "an idle tmp was removed without its commit"
        assert os.path.isfile(os.path.join(p4, "temportal", "tmp", live, "live.md")), "a tmp written today was removed"
        assert os.path.isfile(os.path.join(target, "notes.md")), "the session's own tmp was removed at its start"

        with open(HOOKS_JSON, encoding="utf-8") as f:
            ends = json.load(f)["hooks"]["SessionEnd"][0]["hooks"]
        assert ends[0]["command"].split()[-1] == "tmp-close", ends
    finally:
        if os.path.lexists(harness):
            try:
                os.rmdir(harness) if os.name == "nt" else os.unlink(harness)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(temp, ignore_errors=True)
    print("test_scratchpad.py: tmp keep cases green")


def main():
    asks()
    notebook_out()
    repo_uses()
    tmp_cases()
    tmp_keep_cases()
    gate2_d()
    print("test_scratchpad.py: all green")


if __name__ == "__main__":
    main()
