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

        # a link elsewhere is ezexe's: left as it is
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


def link(path, target):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(path))
    else:
        os.symlink(os.path.abspath(target), path, target_is_directory=True)


def unlink(path):
    os.rmdir(path) if os.name == "nt" else os.unlink(path)


def points_at(path):
    t = os.readlink(path)
    return os.path.normcase(os.path.normpath(t[4:] if t.startswith("\\\\?\\") else t))


def age(*paths, hours=2):
    for p in paths:
        t = os.path.getmtime(p) - hours * 3600
        os.utime(p, (t, t))


def sweep_cases():
    """tmp-link sweeps the project's other scratchpads under the same temp folder: a real empty one quiet past the
    limit is removed with a session folder it leaves empty, a fresh one or one whose transcript is fresh is left, a
    real one with files is linked into p4 with its files moved, a dangling link to the old `.claude/p4/tmp/<session>`
    is re-pointed at that session's tmp, one with nothing in p4 to point at is removed, a foreign link is left;
    this session's own stale link is repaired and named."""
    root = tempfile.mkdtemp(prefix="p4-scratchpad-sweep-")
    temp = tempfile.mkdtemp(prefix="p4-scratchpad-temp-")
    cfg = tempfile.mkdtemp(prefix="p4-scratchpad-cfg-")
    other = tempfile.mkdtemp(prefix="p4-scratchpad-other-")
    sids = {k: f"{k * 8}-0000-4000-8000-00000000000{i}" for i, k in enumerate("sabcdefgh")}
    tmp_env = {"TEMP": temp, "TMP": temp, "TMPDIR": temp, "CLAUDE_CONFIG_DIR": cfg}
    hashdir = os.path.join(temp, "claude", "ffccc31c49e17720")
    p4 = os.path.join(root, ".claude", "p4")
    pad = {k: os.path.join(hashdir, s, "scratchpad") for k, s in sids.items()}
    new = {k: os.path.join(p4, "temportal", "tmp", s) for k, s in sids.items()}
    old = {k: os.path.join(p4, "tmp", s) for k, s in sids.items()}
    links = []
    try:
        # s: this session, its link left by the old layout, whose target is gone
        os.makedirs(old["s"])
        link(pad["s"], old["s"]); links.append(pad["s"])
        os.rmdir(old["s"])
        # a: an app helper's real empty scratchpad, quiet two hours; its session folder holds nothing else
        os.makedirs(pad["a"]); age(pad["a"], os.path.dirname(pad["a"]))
        # b: the same, made a minute ago
        os.makedirs(pad["b"])
        # c: a real scratchpad with a note, quiet two hours
        put(pad["c"], "note.md", "kept\n"); age(os.path.join(pad["c"], "note.md"), pad["c"], os.path.dirname(pad["c"]))
        # d: a dangling link to the old layout, nothing in p4 for it
        os.makedirs(old["d"]); link(pad["d"], old["d"]); links.append(pad["d"]); os.rmdir(old["d"])
        # e: a dangling link to the old layout, and p4 holds that session's tmp at the new place
        put(new["e"], "new.md", "new\n")
        os.makedirs(old["e"]); link(pad["e"], old["e"]); links.append(pad["e"])
        shutil.rmtree(os.path.join(p4, "tmp"))
        # f: a link elsewhere, ezexe's
        link(pad["f"], other); links.append(pad["f"])
        # g: an empty real scratchpad quiet two hours whose transcript was written now
        os.makedirs(pad["g"]); age(pad["g"], os.path.dirname(pad["g"]))
        put(os.path.join(cfg, "projects", "E--x"), sids["g"] + ".jsonl", "{}\n")
        # h: an empty real scratchpad beside the harness's tasks folder, quiet two hours
        os.makedirs(pad["h"]); os.makedirs(os.path.join(os.path.dirname(pad["h"]), "tasks"))
        age(pad["h"], os.path.dirname(pad["h"]))

        out = run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, tmp_env, CLAUDE_PROJECT_DIR=root)
        assert "was a stale link and now reaches" in out, out
        assert "other sessions' scratchpads: 1 linked, 3 removed, 1 repaired" in out, out
        assert points_at(pad["s"]) == os.path.normcase(new["s"]), "this session's stale link was not repaired"
        assert not os.path.exists(os.path.dirname(pad["a"])), "a quiet empty scratchpad was not removed"
        assert os.path.isdir(pad["b"]) and os.path.isdir(pad["g"]), "a fresh scratchpad was removed"
        with open(os.path.join(new["c"], "note.md"), encoding="utf-8") as f:
            assert f.read() == "kept\n", "a quiet scratchpad's note did not move into p4"
        assert points_at(pad["c"]) == os.path.normcase(new["c"]), "a quiet scratchpad with files was not linked"
        assert not os.path.lexists(pad["d"]), "a dangling link with nothing to point at was left"
        assert points_at(pad["e"]) == os.path.normcase(new["e"]), "a link to the old layout was not repaired"
        assert os.path.isfile(os.path.join(pad["e"], "new.md")), "the repaired link does not reach the tmp"
        assert os.path.samefile(pad["f"], other), "a foreign link was changed"
        assert not os.path.exists(pad["h"]) and os.path.isdir(os.path.join(os.path.dirname(pad["h"]), "tasks")), \
            "the empty scratchpad beside tasks/ was not removed alone"
        assert run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, tmp_env, CLAUDE_PROJECT_DIR=root) == "", \
            "a second start spoke"
        # the switch off leaves the folder alone
        os.makedirs(pad["a"]); age(pad["a"], os.path.dirname(pad["a"]))
        run_sub("tmp-link", {"cwd": root, "session_id": sids["s"]}, dict(tmp_env, P4_SCRATCHPAD_TMP="0"),
                CLAUDE_PROJECT_DIR=root)
        assert os.path.isdir(pad["a"]), "the switch off still swept"
    finally:
        for k in sids:
            if os.path.lexists(pad[k]) and (os.path.islink(pad[k]) or getattr(os.path, "isjunction", lambda p: False)(pad[k])):
                unlink(pad[k])
        for d in (root, temp, cfg, other):
            shutil.rmtree(d, ignore_errors=True)
    print("test_scratchpad.py: sweep cases green")


def tmp_empty_and_cap_cases():
    """An empty tmp of another session, quiet past tmp_empty_idle_hours with its transcript, is removed at a start
    with the scratchpad link that points at it, and comes back at that session's next turn close; an empty one written
    now stays. A bare repository, a skipped directory, a clone of a store, a store copied alone and a git work tree
    are never staged; an ordinary folder beside them is. A tmp over tmp_max_files has only its
    tracked files' changes staged: a file staged earlier and deleted since leaves the index, and no new file is added."""
    if not shutil.which("git"):
        print("test_scratchpad.py: tmp empty and cap cases skipped (no git on PATH)")
        return
    root = tempfile.mkdtemp(prefix="p4-scratchpad-empty-")
    temp = tempfile.mkdtemp(prefix="p4-scratchpad-temp-")
    cfg = tempfile.mkdtemp(prefix="p4-scratchpad-cfg-")
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
        put(p4, "p4.json", json.dumps({"version": 1, "scratchpad": {"tmp_max_files": 3}}))
        put(p4, "first.md", "first\n")
        git("add", "first.md")
        git("commit", "-q", "-m", "first")
        os.makedirs(os.path.join(hashdir, own, "scratchpad"))
        for sid in (gone, fresh):
            os.makedirs(os.path.join(tmp, sid))
            link(os.path.join(hashdir, sid, "scratchpad"), os.path.join(tmp, sid))
        age(os.path.join(tmp, gone))
        run("tmp-link", own)
        assert not os.path.exists(os.path.join(tmp, gone)), "a quiet empty tmp was not removed"
        assert not os.path.lexists(os.path.join(hashdir, gone, "scratchpad")), "the link to a removed tmp was left"
        assert os.path.isdir(os.path.join(tmp, fresh)), "an empty tmp written now was removed"
        # that session, if it goes on, gets its tmp back at its turn's close
        run("tmp-sweep", gone)
        assert os.path.isdir(os.path.join(tmp, gone)), "the tmp did not come back"

        mine = os.path.join(tmp, own)
        put(mine, "a.md", "a\n")
        put(mine, "b.md", "b\n")
        subprocess.run(["git", "init", "-q", "--bare", os.path.join(mine, "remote.git")], check=True)
        put(os.path.join(mine, "suite", "pytest-of-someone", "t0"), "x.txt", "x\n")
        put(os.path.join(mine, ".pytest_cache"), "v.txt", "v\n")
        # a clone of the store (no .git, holding .claude/p4), a store copied alone (p4.json beside phi/) and a git
        # work tree (a .git file) are never staged; an ordinary folder beside them is
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


def main():
    asks()
    notebook_out()
    repo_uses()
    tmp_cases()
    tmp_keep_cases()
    sweep_cases()
    tmp_empty_and_cap_cases()
    gate2_d()
    print("test_scratchpad.py: all green")


if __name__ == "__main__":
    main()
