#!/usr/bin/env python3
"""test_scratchpad.py: acceptance tests for p4-temportal's scratchpad part. The notebook's .out/ is seeded,
silently the first time, and seeded again, logs, build output and binaries move into it, and a clean tree prints
nothing at a session start. With P4_SCRATCHPAD_ASKS=1 the PreToolUse ask fires, and never denies, before a code file
goes to a temp location, the session's scratchpad path or the notebook, and repo-uses prints one line for each file
under .claude/p4/temportal/src/ the repository names; with the switch off both are silent. Then the session's
scratchpad directory: linked, staged, committed and removed, and restored, and the other sessions' scratchpad folders
linked or removed. Run from anywhere: python3 hooks/test_scratchpad.py, and exit 0 is green; the git cases skip,
saying so, without git on PATH."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "scratchpad.py")
HOOKS_JSON = os.path.join(HERE, "hooks.json")
SCRATCH = "C:/Users/someone/AppData/Local/Temp/claude/30ad6e18862a20e8/abc123/scratchpad"
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
    # the reason names the file's home under .claude/p4/temportal/src/
    d = ask(write(f"{SCRATCH}/sweep.py"))
    assert "E:/projects/x/.claude/p4/temportal/src/sweep.py" in d["permissionDecisionReason"].replace("\\", "/"), d
    # a subagent is never asked: ezexe, who answers the prompt, cannot redirect a running agent
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
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-out-")
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
        assert "re-seeded .claude/p4/temportal/scratchpad/.out/.gitignore" in out and "binaries moved: 3" in out, out
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
            assert "1 of them were tracked by the store" in out, out
            r = subprocess.run([git, "-C", p4, "check-ignore", "-q", "temportal/scratchpad/.out/x.log"])
            assert r.returncode == 0, "the store does not ignore .out/"
            staged = subprocess.run([git, "-C", p4, "diff", "--cached", "--name-only"], capture_output=True,
                                    text=True).stdout
            assert "temportal/scratchpad/run.log" in staged, "the hook touched the store's index"
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
        print("test_scratchpad.py: repo-uses cases SKIPPED, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-uses-")
    try:
        put(root, ".claude/p4/temportal/src/port/compdb.py", "print(1)\n")
        put(root, ".claude/p4/temportal/src/probe_cef.py", "print(2)\n")
        put(root, ".claude/p4/temportal/src/deploy_mac.sh", "echo\n")
        put(root, ".claude/p4/temportal/src/go.sh", "echo\n")
        put(root, ".claude/p4/notes.md", "compdb.py probe_cef.py\n")      # the store's own files never count
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
    """Every SessionStart command of hooks.json, each run through `sh -c`, one after another; their output
    joined."""
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
    """SessionStart prints nothing on a clean tree: a fresh project, whose notebook is seeded silently, the same
    project again, and a git project with notes in the notebook and an unused file in src/, with the asks off and on."""
    if not shutil.which("sh"):
        print("test_scratchpad.py: clean start SKIPPED, no sh on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-clean-")
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
    print("test_scratchpad.py: clean start green")


def tmp_cases():
    """tmp-link: the scratchpad path Claude Code gives, found under the temp directory by the session id, becomes
    a link into .claude/p4/temportal/tmp/<session>/ with what it held moved in; a second start is silent; a write
    through the scratchpad path lands in the store; a link elsewhere is left; P4_SCRATCHPAD_TMP=0 does nothing;
    tmp-sweep links a scratchpad folder made after the start."""
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-tmp-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
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
        assert "is a link to" in out and "files it held moved: 2" in out, out
        with open(os.path.join(target, "notes.md"), encoding="utf-8") as f:
            assert f.read() == "- a note\n", "the scratchpad's note did not move"
        assert os.path.isfile(os.path.join(target, "sub", "part.md")), "a subdirectory did not move"
        put(harness, "later.md", "later\n")
        assert os.path.isfile(os.path.join(target, "later.md")), "a write through the link did not land in the store"
        assert run("tmp-link") == "", "a second start spoke"
        assert run("tmp-sweep") == "", "tmp-sweep spoke"
        assert run_sub("tmp-link", {"cwd": root}, tmp_env, CLAUDE_PROJECT_DIR=root) == "", "no session id spoke"

        # a scratchpad folder made after the start, the link removed and a plain folder in its place, is linked at
        # turn end
        os.rmdir(harness) if os.name == "nt" else os.unlink(harness)
        put(harness, "after.md", "after\n")
        assert run("tmp-sweep") == "", "tmp-sweep spoke"
        assert os.path.isfile(os.path.join(target, "after.md")), "tmp-sweep did not move a late file"
        put(harness, "after2.md", "again\n")
        assert os.path.isfile(os.path.join(target, "after2.md")), "tmp-sweep did not link the scratchpad again"

        # a link elsewhere is ezexe's: left as it is
        other = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-other-")
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
    """The scratchpad directory is staged at every turn end and removed only after it is committed: tmp-sweep
    stages the session's files in the store, never an ignored file or one over the size cap, and says nothing; tmp-close
    commits them alone, leaving what else is staged as it was, deletes what the commit holds, and commits the removal; a
    file no commit holds stays on disk; the link still works; a session that starts again gets its files back; another
    session's scratchpad directory left idle past the limit is committed and removed the same way at a start; without a
    git repository nothing is deleted."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp keep cases skipped, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-keep-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
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
        put(p4, "p4.json", json.dumps({"scratchpad": {"tmp_max_file_mb": 0.001}}))
        put(p4, "store/first.md", "first\n")
        git("add", ".gitignore", "store/first.md")
        git("commit", "-q", "-m", "first")
        put(p4, "store/other.md", "another session's work, staged\n")
        git("add", "store/other.md")
        put(harness, "sub/part.md", "part\n")
        put(harness, "big.bin", "x" * 5000)                       # over the cap of 0.001 MB
        put(harness, "mod.pyc", "ignored\n")

        assert run("tmp-sweep") == "", "tmp-sweep spoke"
        staged = set(git("diff", "--cached", "--name-only").split())
        assert {f"temportal/tmp/{sid}/notes.md", f"temportal/tmp/{sid}/sub/part.md"} <= staged, staged
        assert not any(n.endswith(("big.bin", "mod.pyc")) for n in staged), staged

        commits = int(git("rev-list", "--count", "HEAD"))
        assert run("tmp-close") == "", "tmp-close spoke"
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
        assert os.path.isfile(os.path.join(target, "after.md")), "the link does not reach the scratchpad directory"

        # the session starts again: what tmp-close removed is back, and staged
        out = run("tmp-link")
        assert "restored" in out, out
        with open(os.path.join(target, "notes.md"), encoding="utf-8") as f:
            assert f.read() == "- a note\n", "the note did not come back"
        assert os.path.isfile(os.path.join(target, "sub", "part.md")), "a subdirectory did not come back"
        assert run("tmp-link") == "", "a second start spoke"

        # another session's scratchpad directory, idle past the limit, is committed and removed at a start, and one
        # written today is left
        put(os.path.join(p4, "temportal", "tmp", old), "old.md", "old\n")
        put(os.path.join(p4, "temportal", "tmp", live), "live.md", "live\n")
        long_ago = os.path.getmtime(os.path.join(p4, "temportal", "tmp", old, "old.md")) - 30 * 86400
        os.utime(os.path.join(p4, "temportal", "tmp", old, "old.md"), (long_ago, long_ago))
        os.utime(os.path.join(p4, "temportal", "tmp", old), (long_ago, long_ago))
        run("tmp-link")
        assert not os.path.exists(os.path.join(p4, "temportal", "tmp", old, "old.md")), \
            "an idle scratchpad directory was not removed"
        assert "old\n" == git("show", f"HEAD~1:temportal/tmp/{old}/old.md"), \
            "an idle scratchpad directory was removed without its commit"
        assert os.path.isfile(os.path.join(p4, "temportal", "tmp", live, "live.md")), \
            "a scratchpad directory written today was removed"
        assert os.path.isfile(os.path.join(target, "notes.md")), \
            "the session's own scratchpad directory was removed at its start"

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


def link(path, target):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(path))
    else:
        os.symlink(os.path.abspath(target), path, target_is_directory=True)


def unlink(path):
    os.rmdir(path) if os.name == "nt" else os.unlink(path)


def is_link(path):
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda p: False)(path)


def points_at(path):
    t = os.readlink(path)
    return os.path.normcase(os.path.normpath(t[4:] if t.startswith("\\\\?\\") else t))


def age(*paths, hours=2):
    for p in paths:
        t = os.path.getmtime(p) - hours * 3600
        os.utime(p, (t, t))


def sweep_cases():
    """tmp-link links or removes the project's other scratchpad folders under the same temp directory: a real
    empty one quiet past the limit is removed with a session folder it leaves empty, a fresh one or one whose transcript
    is fresh is linked though it is empty, a real one with files is linked into the store with its files moved, a
    dangling link with nothing in the store to point at is removed, a foreign link is left; this session's own
    scratchpad is linked and named. The folder named after the project's path, where Claude Code put scratchpads before
    it named the folder by a hash, is handled the same way. After the start no scratchpad folder of the project is a
    plain folder, and one made after it, for an id that runs no hook, is linked at turn end, silently."""
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-sweep-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    cfg = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-cfg-")
    other = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-other-")
    sids = {k: f"{k * 8}-0000-4000-8000-00000000000{i}" for i, k in enumerate("sabcdfgh")}
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": cfg}
    hashdir = os.path.join(temp, "claude", "ffccc31c49e17720")
    p4 = os.path.join(root, ".claude", "p4")
    legacy = os.path.join(temp, "claude", re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(root)))
    sids.update(i="iiiiiiii-0000-4000-8000-000000000011", j="jjjjjjjj-0000-4000-8000-000000000012",
                k="kkkkkkkk-0000-4000-8000-000000000013")
    pad = {k: os.path.join(legacy if k in "ij" else hashdir, s, "scratchpad") for k, s in sids.items()}
    new = {k: os.path.join(p4, "temportal", "tmp", s) for k, s in sids.items()}
    old = {k: os.path.join(p4, "tmp", s) for k, s in sids.items()}
    links = []
    try:
        # s: this session, a real empty scratchpad
        os.makedirs(pad["s"])
        # a: an app helper's real empty scratchpad, quiet two hours; its session folder holds nothing else
        os.makedirs(pad["a"]); age(pad["a"], os.path.dirname(pad["a"]))
        # b: the same, made a minute ago
        os.makedirs(pad["b"])
        # c: a real scratchpad with a note, quiet two hours
        put(pad["c"], "note.md", "kept\n"); age(os.path.join(pad["c"], "note.md"), pad["c"], os.path.dirname(pad["c"]))
        # d: a dangling link into the store, nothing in the store for it
        os.makedirs(old["d"]); link(pad["d"], old["d"]); links.append(pad["d"]); os.rmdir(old["d"])
        shutil.rmtree(os.path.join(p4, "tmp"))
        # f: a link elsewhere, ezexe's
        link(pad["f"], other); links.append(pad["f"])
        # g: an empty real scratchpad quiet two hours whose transcript was written now
        os.makedirs(pad["g"]); age(pad["g"], os.path.dirname(pad["g"]))
        put(os.path.join(cfg, "projects", "E--x"), sids["g"] + ".jsonl", "{}\n")
        # h: an empty real scratchpad beside Claude Code's tasks folder, quiet two hours
        os.makedirs(pad["h"]); os.makedirs(os.path.join(os.path.dirname(pad["h"]), "tasks"))
        age(pad["h"], os.path.dirname(pad["h"]))
        # i, j: in the folder named after the project's path: one with a note written now, one empty and quiet two
        # hours
        put(pad["i"], "old.md", "old harness\n")
        os.makedirs(pad["j"]); age(pad["j"], os.path.dirname(pad["j"]))

        def real_folders():
            return sorted(k for k in sids if os.path.isdir(pad[k]) and not is_link(pad[k]))

        assert real_folders() == ["a", "b", "c", "g", "h", "i", "j", "s"], real_folders()
        out = run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, tmp_env, CLAUDE_PROJECT_DIR=root)
        assert "this session's scratchpad" in out and "is a link to" in out, out
        assert "other sessions' scratchpads: 4 linked, 4 removed" in out, out
        assert real_folders() == [], f"plain scratchpad folders left after a start: {real_folders()}"
        assert points_at(pad["s"]) == os.path.normcase(new["s"]), "this session's scratchpad was not linked"
        assert not os.path.exists(os.path.dirname(pad["a"])), "a quiet empty scratchpad was not removed"
        for k in "bg":
            assert points_at(pad[k]) == os.path.normcase(new[k]), "a fresh empty scratchpad was not linked"
        with open(os.path.join(new["i"], "old.md"), encoding="utf-8") as f:
            assert f.read() == "old harness\n", "a note in the path-named folder did not move into the store"
        assert points_at(pad["i"]) == os.path.normcase(new["i"]), "a scratchpad in the path-named folder was not linked"
        assert not os.path.exists(os.path.dirname(pad["j"])), "a quiet empty one in the path-named folder was left"
        with open(os.path.join(new["c"], "note.md"), encoding="utf-8") as f:
            assert f.read() == "kept\n", "a quiet scratchpad's note did not move into the store"
        assert points_at(pad["c"]) == os.path.normcase(new["c"]), "a quiet scratchpad with files was not linked"
        assert not os.path.lexists(pad["d"]), "a dangling link with nothing to point at was left"
        assert os.path.samefile(pad["f"], other), "a foreign link was changed"
        assert not os.path.exists(pad["h"]) and os.path.isdir(os.path.join(os.path.dirname(pad["h"]), "tasks")), \
            "the empty scratchpad beside tasks/ was not removed alone"
        assert run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, tmp_env, CLAUDE_PROJECT_DIR=root) == "", \
            "a second start spoke"
        # k: made after the start for an id that runs no hook, with a file: linked at this session's turn end
        put(pad["k"], "late.md", "late\n")
        assert run_sub("tmp-sweep", {"cwd": root, "session_id": sids["s"]}, tmp_env, CLAUDE_PROJECT_DIR=root) == "", \
            "turn end spoke"
        assert points_at(pad["k"]) == os.path.normcase(new["k"]), "a scratchpad made after the start was not linked"
        assert os.path.isfile(os.path.join(new["k"], "late.md")), "its file did not move into the store"
        assert real_folders() == [], f"plain scratchpad folders left after turn end: {real_folders()}"
        # the switch off leaves the folder alone
        os.makedirs(pad["a"]); age(pad["a"], os.path.dirname(pad["a"]))
        run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, dict(tmp_env, P4_SCRATCHPAD_TMP="0"),
                CLAUDE_PROJECT_DIR=root)
        assert os.path.isdir(pad["a"]), "the switch off still swept"
    finally:
        for k in sids:
            if os.path.lexists(pad[k]) and is_link(pad[k]):
                unlink(pad[k])
        for d in (root, temp, cfg, other):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: sweep cases green")


def tmp_empty_and_cap_cases():
    """An empty scratchpad directory of another session, quiet past tmp_empty_idle_hours with its transcript, is
    removed at a start with the scratchpad link that points at it, and comes back at that session's next turn end; an
    empty one written now stays. A bare repository, a skipped folder, a clone of a store, a store copied alone and a git
    work tree are never staged; an ordinary folder beside them is. A scratchpad directory over tmp_max_files has only
    its tracked files' changes staged: a file staged earlier and deleted since leaves the index, and no new file is
    added."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp empty and cap cases skipped, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-empty-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    cfg = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-cfg-")
    own, gone, fresh = ("1111aaaa-0000-4000-8000-000000000001", "2222bbbb-0000-4000-8000-000000000002",
                        "3333cccc-0000-4000-8000-000000000003")
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": cfg}
    hashdir = os.path.join(temp, "claude", "30ad6e18862a20e8")
    p4 = os.path.join(root, ".claude", "p4")
    tmp = os.path.join(p4, "temportal", "tmp")

    def git(*args):
        r = subprocess.run(["git", "-C", p4] + list(args), capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def run(sub, sid):
        return run_sub(sub, {"cwd": root, "session_id": sid}, tmp_env, CLAUDE_PROJECT_DIR=root)

    try:
        os.makedirs(p4)
        subprocess.run(["git", "init", "-q", p4], check=True)
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        put(p4, "p4.json", json.dumps({"scratchpad": {"tmp_max_files": 3}}))
        put(p4, "first.md", "first\n")
        git("add", "first.md")
        git("commit", "-q", "-m", "first")
        os.makedirs(os.path.join(hashdir, own, "scratchpad"))
        for sid in (gone, fresh):
            os.makedirs(os.path.join(tmp, sid))
            link(os.path.join(hashdir, sid, "scratchpad"), os.path.join(tmp, sid))
        age(os.path.join(tmp, gone))
        run("tmp-link", own)
        assert not os.path.exists(os.path.join(tmp, gone)), "a quiet empty scratchpad directory was not removed"
        assert not os.path.lexists(os.path.join(hashdir, gone, "scratchpad")), \
            "the link to a removed scratchpad directory was left"
        assert os.path.isdir(os.path.join(tmp, fresh)), "an empty scratchpad directory written now was removed"
        # that session, if it goes on, gets its scratchpad directory back at its turn end
        run("tmp-sweep", gone)
        assert os.path.isdir(os.path.join(tmp, gone)), "the scratchpad directory did not come back"

        mine = os.path.join(tmp, own)
        put(mine, "a.md", "a\n")
        put(mine, "b.md", "b\n")
        subprocess.run(["git", "init", "-q", "--bare", os.path.join(mine, "remote.git")], check=True)
        put(os.path.join(mine, "suite", "pytest-of-someone", "t0"), "x.txt", "x\n")
        put(os.path.join(mine, ".pytest_cache"), "v.txt", "v\n")
        # a clone of the store holding .claude/p4 and no .git, a store copied alone with p4.json beside phi/, and a
        # git work tree with a .git file are never staged; an ordinary folder beside them is
        put(os.path.join(mine, "storeclone", ".claude", "p4", "phi"), "rules.md", "r\n")
        put(os.path.join(mine, "storeclone"), "top.md", "t\n")
        put(os.path.join(mine, "storecopy"), "p4.json", "{}\n")
        put(os.path.join(mine, "storecopy", "phi"), "rules.md", "r\n")
        put(os.path.join(mine, "worktree"), ".git", "gitdir: elsewhere\n")
        put(os.path.join(mine, "worktree"), "w.md", "w\n")
        put(os.path.join(mine, "plain"), "b.md", "b\n")
        os.remove(os.path.join(mine, "b.md"))
        run("tmp-sweep", own)
        staged = git("diff", "--cached", "--name-only").split()
        assert staged == [f"temportal/tmp/{own}/a.md", f"temportal/tmp/{own}/plain/b.md"], staged
        for d in ("storeclone", "storecopy", "worktree"):
            shutil.rmtree(os.path.join(mine, d))
        git("rm", "-q", "--cached", f"temportal/tmp/{own}/plain/b.md")
        shutil.rmtree(os.path.join(mine, "plain"))
        put(mine, "b.md", "b\n")
        run("tmp-sweep", own)
        staged = git("diff", "--cached", "--name-only").split()
        assert staged == [f"temportal/tmp/{own}/a.md", f"temportal/tmp/{own}/b.md"], staged
        # over the cap: b.md is deleted and three files are added; b.md leaves the index, nothing new is added
        os.remove(os.path.join(mine, "b.md"))
        for n in ("c", "d", "e"):
            put(mine, f"{n}.md", n + "\n")
        run("tmp-sweep", own)
        staged = git("diff", "--cached", "--name-only").split()
        assert staged == [f"temportal/tmp/{own}/a.md"], staged
    finally:
        for sid in (own, gone, fresh):
            p = os.path.join(hashdir, sid, "scratchpad")
            if os.path.lexists(p) and not os.path.isdir(p) or os.path.islink(p) or \
                    getattr(os.path, "isjunction", lambda q: False)(p):
                unlink(p)
        for d in (root, temp, cfg):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: tmp empty and cap cases green")


def tmp_export_cases():
    """A copy or export of a repository below the top of a scratchpad directory is never staged, so tmp-close never
    commits or removes it: an export made by `git archive`, whose top holds the repository's .gitignore, a copy whose
    top holds .gitattributes, and a copied plugin whose top holds .claude-plugin/. An ordinary folder of notes beside
    each is staged, and so is a .gitignore at the scratchpad directory's own top, which keeps out only what it names."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp export cases skipped, no git on PATH")
        return
    import zipfile
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-export-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    sid = "4444dddd-0000-4000-8000-000000000004"
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp}
    p4, repo = os.path.join(root, ".claude", "p4"), os.path.join(root, "repo")
    mine, rel = os.path.join(p4, "temportal", "tmp", sid), f"temportal/tmp/{sid}"

    def git(where, *args):
        r = subprocess.run(["git", "-C", where, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                           capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def run(sub):
        return run_sub(sub, {"cwd": root, "session_id": sid}, tmp_env, CLAUDE_PROJECT_DIR=root)

    try:
        for d in (p4, repo):
            os.makedirs(d)
            git(d, "init", "-q")
        put(p4, "first.md", "first\n")
        git(p4, "add", "first.md")
        git(p4, "commit", "-q", "-m", "first")
        put(repo, ".gitignore", "__pycache__/\n*.pyc\n")
        put(repo, "README.md", "a repository\n")
        put(repo, "pkg/mod.py", "x = 1\n")
        put(repo, "pkg/data.json", "{}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "repo")
        rev = git(repo, "rev-parse", "--short", "HEAD").strip()
        git(repo, "archive", "--format=zip", "-o", os.path.join(root, "repo.zip"), "HEAD")
        with zipfile.ZipFile(os.path.join(root, "repo.zip")) as z:
            z.extractall(os.path.join(mine, "work", f"at-{rev}"))
        put(mine, ".gitignore", "*.log\n")
        put(mine, "plan.md", "- a plan\n")
        put(mine, "run.log", "a log\n")
        put(mine, "notes/findings.md", "- a finding\n")
        put(mine, "notes/runs/r1.tsv", "a\t1\n")
        put(mine, "work/summary.md", "what the export showed\n")
        put(mine, "lfs/.gitattributes", "*.pt filter=lfs diff=lfs merge=lfs -text\n")
        put(mine, "lfs/model.md", "a model card\n")
        put(mine, "models/plugin/p4-x/.claude-plugin/plugin.json", json.dumps({"name": "p4-x"}))
        put(mine, "models/plugin/p4-x/hooks/hooks.json", "{}\n")
        put(mine, "models/plugin/p4-x/README.md", "a plugin\n")
        put(mine, "models/notes.md", "- which model\n")
        notes = [f"{rel}/{n}" for n in (".gitignore", "models/notes.md", "notes/findings.md", "notes/runs/r1.tsv",
                                        "plan.md", "work/summary.md")]
        copies = sorted(f"{rel}/{n}" for n in ("lfs/.gitattributes", "lfs/model.md", f"work/at-{rev}/.gitignore",
                                              f"work/at-{rev}/README.md", f"work/at-{rev}/pkg/mod.py",
                                              f"work/at-{rev}/pkg/data.json", "models/plugin/p4-x/README.md",
                                              "models/plugin/p4-x/.claude-plugin/plugin.json",
                                              "models/plugin/p4-x/hooks/hooks.json"))

        assert run("tmp-sweep") == "", "tmp-sweep spoke"
        staged = git(p4, "diff", "--cached", "--name-only").split()
        print(f"test_scratchpad.py: staged after tmp-sweep: {len(staged)} paths, "
              f"{len(set(staged) & set(copies))} of them files of a copy or export of a repository")
        assert staged == notes, staged
        # tmp-close commits the notes alone and removes them; the copies stay on disk, in no commit
        assert run("tmp-close") == "", "tmp-close spoke"
        assert sorted(git(p4, "show", "--name-only", "--format=", "HEAD~1").split()) == notes, "the kept commit"
        assert all(os.path.isfile(os.path.join(p4, *c.split("/"))) for c in copies), "a copy was removed"
        assert not os.path.exists(os.path.join(mine, "plan.md")), "a committed note is still on disk"
    finally:
        for d in (root, temp):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: tmp export cases green")


def tmp_staged_copy_cases():
    """Files of a copy or export of a repository that an earlier turn end staged leave the index again, so tmp-close
    commits and removes the notes alone and the copy stays on disk in no commit. Before tmp-sweep left such a copy out
    it staged the copy whole, and here the copy is what kept the scratchpad directory over tmp_max_files. The dry run of
    ended-sweep counts the notes alone too. A file of a copy that a commit already holds stays in the index at a turn
    end, so no deletion of it is staged."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp staged copy cases skipped, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-staged-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    sid, other = "5555eeee-0000-4000-8000-000000000005", "6666ffff-0000-4000-8000-000000000006"
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": temp}
    p4 = os.path.join(root, ".claude", "p4")
    mine, rel = os.path.join(p4, "temportal", "tmp", sid), f"temportal/tmp/{sid}"
    theirs, orel = os.path.join(p4, "temportal", "tmp", other), f"temportal/tmp/{other}"

    def git(*args):
        r = subprocess.run(["git", "-C", p4, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                           capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def run(sub, s):
        return run_sub(sub, {"cwd": root, "session_id": s}, tmp_env, CLAUDE_PROJECT_DIR=root)

    try:
        os.makedirs(p4)
        git("init", "-q")
        put(p4, "p4.json", json.dumps({"scratchpad": {"tmp_max_files": 3}}))
        put(p4, "first.md", "first\n")
        git("add", "first.md")
        git("commit", "-q", "-m", "first")
        # with the three files of the export the five files are over the cap of three, and the two notes are under it
        put(mine, "plan.md", "- a plan\n")
        put(mine, "notes/findings.md", "- a finding\n")
        put(mine, "work/export/.gitignore", "__pycache__/\n")
        put(mine, "work/export/README.md", "a repository\n")
        put(mine, "work/export/pkg/mod.py", "x = 1\n")
        notes = [f"{rel}/{n}" for n in ("notes/findings.md", "plan.md")]
        copy = [f"{rel}/work/export/{n}" for n in (".gitignore", "README.md", "pkg/mod.py")]
        git("add", "--", *copy)                 # an earlier turn end staged the export whole
        # the session is archived and quiet, so the dry run of ended-sweep plans its close first
        put(os.path.join(p4, "phi", "sessions", "local_5"), "session.json",
            json.dumps({"sessionId": "local_5", "cliSessionIds": [sid], "archived": "2026-11-16 20:00"}))
        for d, _dirs, names in os.walk(mine):
            age(d, *[os.path.join(d, n) for n in names])
        dry = subprocess.run([sys.executable, "-I", SCRIPT, "ended-sweep", "--dry-run", "--root", root],
                             capture_output=True, stdin=subprocess.DEVNULL, timeout=120, env=env_with(tmp_env))
        row = "".join(x for x in dry.stdout.decode("utf-8", "replace").splitlines() if x.startswith(f"- {rel}/ "))
        planned = re.search(r"would commit \d+, would remove \d+", row)
        shown = planned.group(0) if planned else f"no plan in {row!r}"
        assert run("tmp-close", sid) == "", "tmp-close spoke"
        kept = git("log", "--format=", "--name-only", "--grep", "kept before its removal").split()
        print(f"test_scratchpad.py: ended-sweep --dry-run: {shown}; committed by tmp-close: {len(kept)} paths, "
              f"{len(set(kept) & set(copy))} of them files of the copy an earlier turn end staged")
        assert git("log", "--all", "--format=", "--name-only", "--", *copy).split() == [], "a commit holds the copy"
        assert all(os.path.isfile(os.path.join(p4, *c.split("/"))) for c in copy), "a file of the copy was removed"
        assert git("ls-files", "--", *copy) == "", "the copy is still in the index"
        assert sorted(kept) == notes, kept
        assert not os.path.exists(os.path.join(mine, "plan.md")), "a committed note is still on disk"
        assert planned and planned.group(0) == "would commit 2, would remove 2", row

        # a file of a copy that a commit holds keeps its place in the index, and only the staged ones leave it
        put(theirs, "export/.gitattributes", "*.pt filter=lfs\n")
        put(theirs, "export/held.md", "held by a commit\n")
        git("add", "--", f"{orel}/export/held.md")
        git("commit", "-q", "-m", "held")
        put(theirs, "export/new.md", "staged by an earlier turn end\n")
        git("add", "--", f"{orel}/export/.gitattributes", f"{orel}/export/new.md")
        put(theirs, "note.md", "a note\n")
        assert run("tmp-sweep", other) == "", "tmp-sweep spoke"
        assert git("diff", "--cached", "--name-status", "--", orel).splitlines() == [f"A\t{orel}/note.md"], \
            git("diff", "--cached", "--name-status", "--", orel)
        assert git("ls-files", "--", f"{orel}/export").split() == [f"{orel}/export/held.md"], "held.md left the index"
        # that held file edited on disk: tmp-close removes the note and commits no change to the file of the copy
        put(theirs, "export/held.md", "edited on disk\n")
        # the dry run of ended-sweep names the same removals the real close makes: the note alone
        put(os.path.join(p4, "phi", "sessions", "local_6"), "session.json",
            json.dumps({"sessionId": "local_6", "cliSessionIds": [other], "archived": "2026-11-16 20:00"}))
        for d, _dirs, names in os.walk(theirs):
            age(d, *[os.path.join(d, n) for n in names])
        dry = subprocess.run([sys.executable, "-I", SCRIPT, "ended-sweep", "--dry-run", "--root", root],
                             capture_output=True, stdin=subprocess.DEVNULL, timeout=120, env=env_with(tmp_env))
        row = "".join(x for x in dry.stdout.decode("utf-8", "replace").splitlines() if x.startswith(f"- {orel}/ "))
        on_disk = {n for n in os.listdir(theirs)} | {"export/" + n for n in os.listdir(os.path.join(theirs, "export"))}
        assert run("tmp-close", other) == "", "tmp-close spoke"
        gone = sorted(n for n in on_disk if not os.path.exists(os.path.join(theirs, *n.split("/"))))
        assert f"would remove {len(gone)}" in row, f"the dry run planned {row!r}, the close removed {gone}"
        changes = git("log", "--format=%s", "--", f"{orel}/export/held.md").splitlines()
        assert changes == ["held"], f"tmp-close changed the copy's file in history: {changes}"
        assert git("show", f"HEAD:{orel}/export/held.md") == "held by a commit\n", "tmp-close committed the edit"
        assert not os.path.exists(os.path.join(theirs, "note.md")), "the note was not removed"
    finally:
        for d in (root, temp):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: tmp staged copy cases green")


def tmp_close_bare_store_cases():
    """tmp-close commits and removes a session's files in a store with no git identity and a pre-commit hook that
    exits 1."""
    if not shutil.which("git"):
        print("test_scratchpad.py: bare store cases skipped, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-bare-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    sid = "7777aaaa-0000-4000-8000-000000000007"
    empty = os.path.join(temp, "empty.gitconfig")
    put(temp, "empty.gitconfig", "")
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": temp, "GIT_CONFIG_GLOBAL": empty,
               "GIT_CONFIG_NOSYSTEM": "1"}
    p4 = os.path.join(root, ".claude", "p4")
    mine = os.path.join(p4, "temportal", "tmp", sid)
    try:
        os.makedirs(p4)
        subprocess.run(["git", "-C", p4, "init", "-q"], check=True, capture_output=True)
        put(p4, "first.md", "first\n")
        subprocess.run(["git", "-C", p4, "add", "first.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", p4, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first"],
                       check=True, capture_output=True)
        put(os.path.join(p4, ".git", "hooks"), "pre-commit", "#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(p4, ".git", "hooks", "pre-commit"), 0o755)
        put(mine, "plan.md", "- a plan\n")
        assert run_sub("tmp-close", {"cwd": root, "session_id": sid}, tmp_env, CLAUDE_PROJECT_DIR=root) == ""
        log = subprocess.run(["git", "-C", p4, "log", "--format=%s"], capture_output=True, text=True).stdout
        assert not os.path.exists(os.path.join(mine, "plan.md")), f"the note was not closed\n{log}"
        assert "kept before its removal" in log, log
    finally:
        for d in (root, temp):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: bare store cases green")


def snapshot(root):
    """Every file under a folder with its size, time and bytes, the git index and refs included."""
    out = {}
    for d, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = (os.path.getmtime(p), f.read())
    return out


def ended_cases():
    """The scratchpad directory of an ended session, one p4-phi's record says is archived or one idle past the
    limit, is committed and removed as SessionEnd would, staged and untracked files alike: committed, then gone from the
    work tree, every file readable from the commit; an ignored file is left alone. One over the file cap stays on disk
    whole, and is named with its file count and size by ended-sweep and once at a start. A session written to recently
    has not ended, archived or not. `ended-sweep --dry-run` changes nothing, the index and p4.json included, and lists
    what it would commit and remove with the counts and the top folders. A start commits and removes an archived
    session's scratchpad directory too."""
    if not shutil.which("git"):
        print("test_scratchpad.py: ended cases skipped, no git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-ended-")
    temp = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-temp-")
    cfg = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-cfg-")
    names = ("arch", "idle", "live", "busy", "big", "late", "own")
    ids = {k: f"{i}{i}{i}{i}eeee-0000-4000-8000-00000000000{i}" for i, k in enumerate(names, 1)}
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": cfg}
    hashdir = os.path.join(temp, "claude", "30ad6e18862a20e8")
    p4 = os.path.join(root, ".claude", "p4")
    tmp = {k: os.path.join(p4, "temportal", "tmp", s) for k, s in ids.items()}
    rel = {k: f"temportal/tmp/{s}" for k, s in ids.items()}

    def git(*args):
        r = subprocess.run(["git", "-C", p4] + list(args), capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def old(k, hours=2):
        for d, _dirs, files in os.walk(tmp[k]):
            age(d, *[os.path.join(d, n) for n in files], hours=hours)

    def sweep(*args):
        r = subprocess.run([sys.executable, "-I", SCRIPT, "ended-sweep", *args, "--root", root], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=120, env=env_with(tmp_env))
        assert r.returncode == 0, r
        return r.stdout.decode("utf-8", "replace").strip().splitlines()

    def row(lines, k):
        hit = [x for x in lines if x.startswith(f"- {rel[k]}/ ")]
        return hit[0] if hit else ""

    try:
        os.makedirs(p4)
        subprocess.run(["git", "init", "-q", p4], check=True)
        git("config", "user.name", "t")
        git("config", "user.email", "t@t")
        put(p4, ".gitignore", "*.pyc\n")
        put(p4, "p4.json", json.dumps({"scratchpad": {"tmp_max_files": 6}}))
        put(tmp["idle"], "held.md", "held already\n")
        git("add", ".gitignore", rel["idle"] + "/held.md")
        git("commit", "-q", "-m", "first")
        put(p4, "store/other.md", "another session's work, staged\n")
        git("add", "store/other.md")
        # p4-phi's records: arch, busy, big and late are archived; idle and live have no record
        for n, k in enumerate(("arch", "busy", "big", "late")):
            put(os.path.join(p4, "phi", "sessions", f"local_{n}"), "session.json",
                json.dumps({"sessionId": f"local_{n}", "cliSessionIds": [ids[k]], "archived": "2026-11-12 20:07"}))
        # arch: a staged file, two untracked and one the repo ignores, quiet two hours
        put(tmp["arch"], "s.md", "staged\n")
        git("add", rel["arch"] + "/s.md")
        put(tmp["arch"], "u.md", "untracked\n")
        put(tmp["arch"], "sub/deep.md", "deep\n")
        put(tmp["arch"], "mod.pyc", "ignored\n")
        old("arch")
        # idle: no record, nothing written for thirty days; one file committed, one staged, one untracked
        put(tmp["idle"], "s.md", "idle staged\n")
        git("add", rel["idle"] + "/s.md")
        put(tmp["idle"], "u.md", "idle untracked\n")
        old("idle", hours=30 * 24)
        # live has no record and busy is archived, and both were written to now: neither has ended
        put(tmp["live"], "now.md", "live\n")
        put(tmp["busy"], "now.md", "busy\n")
        # big: archived, ten files against a cap of six, its transcript quiet two hours
        for n in range(8):
            put(tmp["big"], f"runs/r{n}.md", "run\n")
        for n in range(2):
            put(tmp["big"], f"smoke/s{n}.md", "smoke\n")
        old("big")
        put(os.path.join(cfg, "projects", "E--x"), ids["big"] + ".jsonl", "{}\n")
        age(os.path.join(cfg, "projects", "E--x", ids["big"] + ".jsonl"))

        # the dry run changes nothing and lists what it would do
        before, head = snapshot(root), git("rev-parse", "HEAD")
        lines = sweep("--dry-run")
        assert snapshot(root) == before and git("rev-parse", "HEAD") == head, "the dry run changed something"
        assert "a dry run that changed nothing" in lines[0], lines[0]
        assert "session folders ended: 3 of 5" in lines[0], lines[0]
        assert "would commit files: 5, would remove: 6" in lines[0], lines[0]
        assert "folders left on disk over the cap: 1, the cap being 6 files" in lines[0], lines[0]
        assert len(lines) == 4 and lines[1] == row(lines, "big"), f"not the fullest folder first: {lines}"
        line = row(lines, "arch")
        assert " archived: would commit 3, would remove 3, would leave 1 that no commit would hold" in line, line
        assert "4 files" in line and "top folders: its own files 3, sub/ 1" in line, line
        line = row(lines, "idle")
        assert re.search(r" idle (29|30) days: would commit 2, would remove 3, would leave 0 ", line), line
        line = row(lines, "big")
        assert " archived: over the cap" in line and "nothing removed" in line and "ezexe" in line, line
        assert "10 files" in line and "top folders: runs/ 8, smoke/ 2" in line, line
        assert not row(lines, "live") and not row(lines, "busy"), "a session written to now was listed as ended"

        # ended-sweep: committed, then gone from the work tree, every file readable from the commit
        lines = sweep()
        assert ("session folders ended: 3 of 5; committed files: 5, removed: 6; folders left on disk over the cap: 1"
                in lines[0]), lines[0]
        want = {"arch": {"s.md": "staged\n", "u.md": "untracked\n", "sub/deep.md": "deep\n"},
                "idle": {"held.md": "held already\n", "s.md": "idle staged\n", "u.md": "idle untracked\n"}}
        for k, files in want.items():
            kept = re.search(r"its files are in ([0-9a-f]{8})", row(lines, k))
            assert kept, f"{k}: no commit named in {row(lines, k)!r}"
            for name, text in files.items():
                assert not os.path.exists(os.path.join(tmp[k], *name.split("/"))), f"{k}/{name} is still on disk"
                assert git("show", f"{kept.group(1)}:{rel[k]}/{name}") == text, f"{k}/{name} is not in the commit"
        assert sorted(os.listdir(tmp["arch"])) == ["mod.pyc"], "an ignored file was not left alone"
        assert not os.path.exists(tmp["idle"]), "an emptied scratchpad directory was left"
        assert git("ls-files", rel["arch"], rel["idle"]).strip() == "", "the removal is not committed"
        assert git("diff", "--cached", "--name-only").split() == ["store/other.md"], "another staged file was swept in"
        assert "over the cap" in row(lines, "big") and "10 files" in row(lines, "big"), row(lines, "big")
        assert sum(len(f) for _d, _s, f in os.walk(tmp["big"])) == 10, "a folder over the cap lost a file"
        assert git("ls-files", rel["big"]).strip() == "", "a folder over the cap was staged"
        for k in ("live", "busy"):
            assert os.path.isfile(os.path.join(tmp[k], "now.md")), f"{k}: a session written to now was swept"
        assert "session folders ended: 1 of 4; would commit files: 0, would remove: 0" in sweep("--dry-run")[0], \
            "after ended-sweep only the folder over the cap is left to name"
        assert "does not know '--bogus'" in sweep("--bogus")[0], "an unknown argument was not refused"

        # a start commits and removes an archived session's scratchpad directory too, and names the folder over the
        # cap once
        put(tmp["late"], "s.md", "late staged\n")
        git("add", rel["late"] + "/s.md")
        put(tmp["late"], "u.md", "late untracked\n")
        old("late")
        os.makedirs(os.path.join(hashdir, ids["own"], "scratchpad"))
        payload = {"cwd": root, "session_id": ids["own"]}
        out = run_sub("tmp-link", payload, tmp_env, CLAUDE_PROJECT_DIR=root)
        assert not os.path.exists(tmp["late"]), "a start left an archived session's scratchpad directory"
        assert git("show", f"HEAD~1:{rel['late']}/u.md") == "late untracked\n", "its untracked file is in no commit"
        assert git("show", f"HEAD~1:{rel['late']}/s.md") == "late staged\n", "its staged file is in no commit"
        assert out.count(rel["big"] + "/ of an ended session, archived, holds 10 files") == 1, out
        assert "over the cap of 6 files" in out and "ezexe" in out and "runs/ 8, smoke/ 2" in out, out
        again = run_sub("tmp-link", payload, tmp_env, CLAUDE_PROJECT_DIR=root)
        assert rel["big"] not in again, f"a folder over the cap was named twice: {again}"
        assert sum(len(f) for _d, _s, f in os.walk(tmp["big"])) == 10, "a start removed from a folder over the cap"
    finally:
        p = os.path.join(hashdir, ids["own"], "scratchpad")
        if os.path.lexists(p) and is_link(p):
            unlink(p)
        for d in (root, temp, cfg):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: ended cases green")


def move_cases():
    """A folder that cannot be renamed into the scratchpad directory, as from the temp drive to the project's, is
    copied and removed with its read-only files, so a scratchpad holding a clone still ends as the link; a copy that
    fails is taken back and the folder stays where it was."""
    import stat
    sys.path.insert(0, HERE)
    import scratchpad as sp
    base = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-move-")
    rename, copytree = os.rename, shutil.copytree

    def no_rename(*_a, **_k):
        raise OSError("another drive")

    def half_copy(src, dest, **_k):
        os.makedirs(dest)
        raise shutil.Error("the copy stopped")

    try:
        harness, target = os.path.join(base, "temp", "sid", "scratchpad"), os.path.join(base, "p4", "tmp", "sid")
        obj = os.path.join(harness, "clone", ".git", "objects", "08")
        put(obj, "609f44", "object\n")
        os.chmod(os.path.join(obj, "609f44"), stat.S_IREAD)
        put(harness, "note.md", "a note\n")
        os.makedirs(target)
        os.rename = no_rename
        try:
            shutil.copytree = half_copy
            assert sp.move_into(harness, target, "t") == ["note.md"], "a folder whose copy failed counted as moved"
            assert os.path.isfile(os.path.join(obj, "609f44")), "a folder whose copy failed did not stay"
            assert not os.path.exists(os.path.join(target, "clone")), \
                "a failed copy was left in the scratchpad directory"
            shutil.copytree = copytree
            state, moved = sp.link_tmp(harness, target, "t")
        finally:
            os.rename, shutil.copytree = rename, copytree
        assert (state, moved) == ("linked", ["clone"]), (state, moved)
        with open(os.path.join(target, "clone", ".git", "objects", "08", "609f44"), encoding="utf-8") as f:
            assert f.read() == "object\n", "a read-only file did not move"
        assert is_link(harness) and os.path.samefile(harness, target), "a scratchpad holding a clone was not linked"
        assert sorted(os.listdir(target)) == ["clone", "note.md"], os.listdir(target)
    finally:
        if os.path.lexists(harness) and is_link(harness):
            unlink(harness)
        for d, _dirs, names in os.walk(base):
            for n in names:
                os.chmod(os.path.join(d, n), stat.S_IWRITE)
        shutil.rmtree(base, ignore_errors=True)
    print("test_scratchpad.py: move cases green")


def main():
    asks()
    notebook_out()
    repo_uses()
    tmp_cases()
    tmp_keep_cases()
    sweep_cases()
    move_cases()
    tmp_empty_and_cap_cases()
    tmp_export_cases()
    tmp_staged_copy_cases()
    tmp_close_bare_store_cases()
    ended_cases()
    gate2_d()
    print("test_scratchpad.py: all green")


if __name__ == "__main__":
    main()
