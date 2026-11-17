#!/usr/bin/env python3
"""test_scratchpad.py: acceptance tests for p4-temportal's scratchpad part. The notebook's .out/ is seeded,
silently the first time, and seeded again, logs, build output and binaries move into it, and a clean tree prints
nothing at a session start. With P4_SCRATCHPAD_ASKS=1 the PreToolUse ask fires, and never denies, before a code file
goes to a temp location, the session's scratchpad path or the notebook, and repo-uses prints one line for each file
under .claude/p4/temportal/src/ the repository names; with the switch off both are silent. Then each session's
scratchpad, which is the app's: no start, turn end or session end links, stages, commits or removes one. Run it as
`python -I -X utf8 lbiza/plugins/p4-temportal/hooks/test_scratchpad.py` from the checkout, and exit 0 is green; the git
cases skip, saying so, without git on PATH."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_JSON = os.path.join(HERE, "hooks.json")
SCRATCH = "C:/Users/someone/AppData/Local/Temp/claude/30ad6e18862a20e8/abc123/scratchpad"
MAC_SCRATCH = "/private/tmp/claude-501/-Users-ez-x/f27bc042/scratchpad"
P4_SRC = "E:/projects/x/.claude/p4/temportal/src"
PAD = "E:/projects/x/.claude/p4/temportal/notebook"
ON = {"P4_SCRATCHPAD_ASKS": "1"}

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


def env_with(extra=None, **kw):
    env = {k: v for k, v in os.environ.items() if k != "P4_SCRATCHPAD_ASKS"}
    env.update(extra or {})
    env.update(kw)
    return env


def run_sub(sub, payload, extra=None, **kw):
    """scratchpad.py's main() with that subcommand, run in this process the way its own process would run it: its
    argv, the payload on its stdin and the environment given in place of this one -> its stdout, stripped. It saves a
    python start per call, which over the ask cases is most of this file's time."""
    import contextlib
    import io
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import scratchpad
    env = env_with(extra, **kw)                     # built from this environment before it is swapped out
    saved = (dict(os.environ), os.getcwd(), sys.argv, sys.stdin)
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)
    try:
        os.environ.clear()
        os.environ.update(env)
        sys.argv = ["scratchpad.py", sub]
        sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
        with contextlib.redirect_stdout(out):
            code = scratchpad.main()
    finally:
        os.environ.clear()
        os.environ.update(saved[0])
        os.chdir(saved[1])
        sys.argv, sys.stdin = saved[2], saved[3]
    assert code == 0, code
    return out.buffer.getvalue().decode("utf-8", "replace").strip()


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
    write(f"{PAD}/probe.py"), write(".claude/p4/temportal/notebook/edit.py"),
    bash("cat > .claude/p4/temportal/notebook/gen.py <<'EOF'\nprint(1)\nEOF\n"),
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
    pad = os.path.join(root, ".claude", "p4", "temportal", "notebook")

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
            subprocess.run([git, "-C", p4, "add", "temportal/notebook/run.log"], check=True)
        out = sweep()
        assert out.startswith("p4-temportal: ") and "\n" not in out, f"not one line: {out}"
        assert "re-seeded .claude/p4/temportal/notebook/.out/.gitignore" in out and "binaries moved: 3" in out, out
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
            r = subprocess.run([git, "-C", p4, "check-ignore", "-q", "temportal/notebook/.out/x.log"])
            assert r.returncode == 0, "the store does not ignore .out/"
            staged = subprocess.run([git, "-C", p4, "diff", "--cached", "--name-only"], capture_output=True,
                                    text=True).stdout
            assert "temportal/notebook/run.log" in staged, "the hook touched the store's index"
        # a clean notebook is silent; a changed ignore is re-seeded, a deleted one too
        assert sweep() == "", "a clean notebook spoke"
        put(pad, ".out/.gitignore", "!keep\n")
        assert "re-seeded" in sweep(), "a changed .out/ ignore was not re-seeded"
        os.remove(os.path.join(pad, ".out", ".gitignore"))
        assert "re-seeded" in sweep(), "a deleted .out/ ignore was not re-seeded"
    finally:
        wipe(root)
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
        wipe(root)
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
                           env=env_with(extra, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=root,
                                        CLAUDE_CONFIG_DIR=os.path.join(root, ".config")))   # never the real profile
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
    profile = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                           "projects")
    mine = os.path.basename(root).replace("_", "-")

    def left_in_profile():
        try:
            return [n for n in os.listdir(profile) if n.endswith(mine)]
        except OSError:
            return []

    try:
        for extra in ({}, ON):
            assert session_start(root, extra) == "", f"a fresh tree printed (asks {extra or 'off'})"
            with open(os.path.join(root, ".claude", "p4", "temportal", "notebook", ".out", ".gitignore"), encoding="utf-8") as f:
                assert f.read() == "*\n", "the first seed did not happen"
            assert session_start(root, extra) == "", "a second start on a clean tree printed"
        put(root, ".claude/p4/temportal/notebook/plan.md", "- a note\n")
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
        assert left_in_profile() == [], f"the run left folders under {profile}: {left_in_profile()}"
    finally:
        wipe(root)
    print("test_scratchpad.py: clean start green")


def is_link(path):
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda p: False)(path)


def event_hooks(event):
    with open(HOOKS_JSON, encoding="utf-8") as f:
        return [h["command"] for g in json.load(f)["hooks"][event] for h in g["hooks"]]


def parallel_hooks_cases():
    """The SessionStart hooks run at once, as Claude Code runs the hooks of one event, on a store with the older layout
    leave one moved layout, no layout lock and one p4.json that parses; the SessionEnd hooks run at once on that small
    store finish within the 1.5-second budget of a SessionEnd."""
    sh = shutil.which("sh")
    if not sh or not shutil.which("git"):
        print("test_scratchpad.py: parallel hooks cases skipped, no sh or git on PATH")
        return
    root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-parallel-")
    sid = "bbbb2222-0000-4000-8000-00000000000b"
    p4 = os.path.join(root, ".claude", "p4")
    old = {"memory/MEMORY.md": "- [a](a.md) — a\n", "scratchpad/plan.md": "- a plan\n", "src/probe.py": "print(1)\n"}
    try:
        os.makedirs(p4)
        for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
            subprocess.run(["git", "-C", p4] + args, check=True, capture_output=True)
        for rel, text in old.items():
            put(p4, rel, text)
        subprocess.run(["git", "-C", p4, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", p4, "commit", "-q", "-m", "old layout"], check=True, capture_output=True)
        env = env_with(None, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=root,
                       CLAUDE_CONFIG_DIR=os.path.join(root, ".config"))
        stdin = json.dumps({"cwd": root, "session_id": sid, "source": "startup"}).encode()

        def at_once(event):
            procs = [subprocess.Popen([sh, "-c", c], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, env=env) for c in event_hooks(event)]
            for p in procs:
                p.communicate(stdin, timeout=120)
            assert all(p.returncode == 0 for p in procs), [p.returncode for p in procs]

        at_once("SessionStart")
        left = [rel for rel in old if os.path.exists(os.path.join(p4, *rel.split("/")))]
        assert left == [], f"files left in the older layout: {left}"
        new = {"scratchpad": "notebook"}             # the notebook's old name at the store's top, and its folder now
        moved = [rel for rel in old if not os.path.isfile(
            os.path.join(p4, "temportal", new.get(rel.split("/")[0], rel.split("/")[0]), *rel.split("/")[1:]))]
        assert moved == [], f"files missing from the new layout: {moved}"
        assert not os.path.exists(os.path.join(p4, ".layout.lock")), "the layout lock was left"
        with open(os.path.join(p4, "p4.json"), encoding="utf-8") as f:
            json.load(f)
        # the same runner started as often at once with a part that does nothing: what this machine's load costs a hook
        idle = [c.rsplit(" ", 1)[0] + " nothing-here" for c in event_hooks("SessionEnd")]
        start = time.monotonic()
        procs = [subprocess.Popen([sh, "-c", c], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env) for c in idle]
        for p in procs:
            p.communicate(stdin, timeout=120)
        floor = time.monotonic() - start
        start = time.monotonic()
        at_once("SessionEnd")
        took = time.monotonic() - start
        limit = max(1.5, 3 * floor)       # the 1.5 s budget, widened only when even an idle start is slow here
        print(f"test_scratchpad.py: the SessionEnd hooks at once took {took * 1000:.0f} ms, as many idle starts "
              f"{floor * 1000:.0f} ms, limit {limit * 1000:.0f} ms")
        assert took <= limit, f"the SessionEnd hooks took {took:.2f} s, over {limit:.2f} s"
    finally:
        wipe(root)
    print("test_scratchpad.py: parallel hooks cases green")


class Cases(unittest.TestCase):
    """Each case group a test method, so unittest and pytest collect them."""

    def test_asks(self):
        asks()

    def test_notebook_out(self):
        notebook_out()

    def test_repo_uses(self):
        repo_uses()

    def test_parallel_hooks_cases(self):
        parallel_hooks_cases()

    def test_gate2_d(self):
        gate2_d()



class AppScratchpad(unittest.TestCase):
    """ezexe/p4#131: each session's scratchpad is the app's. The hooks hooks.json lists for a start, a turn end and a
    session end leave it a plain folder where Claude Code made it, link nothing into the store, stage nothing, commit
    nothing, and close no folder an earlier version left under the store's temportal/tmp/."""

    SID = "aaaa1111-0000-4000-8000-00000000000a"

    def setUp(self):
        if not shutil.which("sh") or not shutil.which("git"):
            self.skipTest("no sh or git on PATH")
        self.root = tempfile.mkdtemp(prefix="p4-temportal-app-scratchpad-")
        self.temp = tempfile.mkdtemp(prefix="p4-temportal-app-temp-")
        self.addCleanup(wipe, self.temp)
        self.addCleanup(wipe, self.root)
        self.p4 = os.path.join(self.root, ".claude", "p4")
        os.makedirs(self.p4)
        for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"],
                     ["commit", "-q", "--allow-empty", "-m", "store"]):
            subprocess.run(["git", "-C", self.p4] + args, check=True, capture_output=True)
        self.hashdir = os.path.join(self.temp, "claude", "30ad6e18862a20e8")
        self.pad = os.path.join(self.hashdir, self.SID, "scratchpad")
        put(self.pad, "note.md", "a note\n")

    def hooks(self, event, source="startup"):
        """Every command hooks.json lists for the event, with the source as matcher, run one after another."""
        with open(HOOKS_JSON, encoding="utf-8") as f:
            groups = json.load(f)["hooks"].get(event, [])
        cmds = [h["command"] for g in groups
                if g.get("matcher", "") in ("", "*") or source in g["matcher"].split("|") for h in g["hooks"]]
        env = env_with(None, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=self.root,
                       CLAUDE_CONFIG_DIR=os.path.join(self.root, ".config"), TEMP=self.temp, TMP=self.temp,
                       TMPDIR=self.temp)
        stdin = json.dumps({"cwd": self.root, "session_id": self.SID, "scratchpad_dir": self.pad, "source": source,
                            "hook_event_name": event}).encode()
        for c in cmds:
            r = subprocess.run([shutil.which("sh"), "-c", c], input=stdin, capture_output=True, timeout=120, env=env)
            self.assertEqual(r.returncode, 0, r)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.p4, *args], capture_output=True, check=True).stdout.decode().strip()

    def test_a_start_leaves_the_apps_scratchpad_a_plain_folder_with_its_files(self):
        self.hooks("SessionStart")
        self.assertFalse(is_link(self.pad), "the app's scratchpad was made a link")
        self.assertTrue(os.path.isfile(os.path.join(self.pad, "note.md")), "the note left the app's scratchpad")
        self.assertFalse(os.path.exists(os.path.join(self.p4, "temportal", "tmp")), "the store got a tmp/ folder")

    def test_a_start_leaves_another_sessions_scratchpad_as_the_app_made_it(self):
        other = os.path.join(self.hashdir, "bbbb2222-0000-4000-8000-00000000000b", "scratchpad")
        empty = os.path.join(self.hashdir, "cccc3333-0000-4000-8000-00000000000c", "scratchpad")
        put(other, "probe.txt", "probe\n")
        os.makedirs(empty)
        quiet = time.time() - 2 * 3600
        os.utime(empty, (quiet, quiet))
        self.hooks("SessionStart")
        for d in (other, empty):
            self.assertTrue(os.path.isdir(d) and not is_link(d), f"{d} is no longer the app's plain folder")
        self.assertTrue(os.path.isfile(os.path.join(other, "probe.txt")))

    def test_a_turn_end_stages_nothing_in_the_store(self):
        self.hooks("SessionStart")
        self.hooks("Stop")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_a_session_end_commits_and_removes_nothing(self):
        self.hooks("SessionStart")
        self.hooks("Stop")
        head = self.git("rev-parse", "HEAD")
        self.hooks("SessionEnd", "other")
        self.assertEqual(self.git("rev-parse", "HEAD"), head, "a session end made a commit in the store")
        self.assertTrue(os.path.isfile(os.path.join(self.pad, "note.md")), "a session end removed the note")

    def test_a_start_closes_no_folder_of_an_ended_session(self):
        ended = "dddd4444-0000-4000-8000-00000000000d"
        kept = os.path.join(self.p4, "temportal", "tmp", ended)
        put(kept, "old.md", "old\n")
        put(self.p4, f"phi/sessions/local_x/session.json", json.dumps({"sessionId": ended, "archived": True}))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "an ended session's folder")
        long_ago = time.time() - 8 * 86400
        for d, _dirs, names in os.walk(kept):
            for n in [d] + [os.path.join(d, x) for x in names]:
                os.utime(n, (long_ago, long_ago))
        head = self.git("rev-parse", "HEAD")
        self.hooks("SessionStart")
        self.assertTrue(os.path.isfile(os.path.join(kept, "old.md")), "an ended session's folder was closed")
        self.assertEqual(self.git("rev-parse", "HEAD"), head, "a start made a commit in the store")


class InProcess(unittest.TestCase):
    """ezexe/p4#122: the ask cases, over a hundred runs of the hook, run its main() in this process, so they start no
    process and take a fraction of the time one process a case took."""

    def test_the_ask_cases_start_no_process(self):
        import time as clock
        real = (subprocess.run, subprocess.Popen)

        def refuse(*a, **k):
            raise AssertionError(f"a process was started: {a[0] if a else k}")
        start = clock.monotonic()
        try:
            subprocess.run = subprocess.Popen = refuse
            asks()
        finally:
            subprocess.run, subprocess.Popen = real
        print(f"test_scratchpad.py: the ask cases took {(clock.monotonic() - start) * 1000:.0f} ms")


class FailureNotice(unittest.TestCase):
    """ezexe/p4#114: a failure of the ask on PreToolUse, where plain stdout reaches nobody, and an unknown subcommand
    print a systemMessage, which Claude Code shows ezexe on every event."""

    def test_a_degraded_or_unknown_subcommand_prints_a_system_message(self):
        import contextlib
        import io
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import scratchpad as sp
        root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-fail-")
        self.addCleanup(wipe, root)
        old = (sp.cmd_ask, sys.argv, sys.stdin)

        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            sp.cmd_ask = broken
            for sub, want in (("ask", "scratchpad ask degraded: OSError: disk gone"), ("nope", "unknown subcommand")):
                sys.argv = ["scratchpad.py", sub]
                sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(
                    {"cwd": root, "hook_event_name": "PreToolUse"}).encode()), encoding="utf-8")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(sp.main(), 0)
                self.assertIn(want, json.loads(out.getvalue())["systemMessage"])
        finally:
            sp.cmd_ask, sys.argv, sys.stdin = old


class AskPaths(unittest.TestCase):
    """Which written paths the ask names, on scratchpad.py's own functions."""

    @classmethod
    def setUpClass(cls):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)

    def test_the_macos_scratchpad_is_the_scratchpad(self):
        import scratchpad as sp
        self.assertTrue(sp.in_harness_scratchpad("/private/tmp/claude-501/-Users-ez-x/f27bc042/scratchpad/x.py"))
        self.assertTrue(sp.in_harness_scratchpad(MAC_SCRATCH + "/probe.py"))

    def test_a_repositorys_tmp_folder_is_no_temp_location(self):
        import scratchpad as sp
        for p in ("E:/projects/x/tmp/build.py", "src/tmp/gen.py", "/home/u/repo/tmp/a.py",
                  "E:/projects/x/.claude/p4/temportal/tmp/sid/a.py"):
            self.assertFalse(sp.in_temp(p), p)
        for p in ("/tmp/x.py", "/private/tmp/x.py", "/var/folders/ab/T/x.py", "/private/var/folders/ab/T/x.py", "C:/Users/u/AppData/Local/Temp/x.py",
                  "$env:TEMP/x.py", "%TEMP%/x.py", "$TMPDIR/x.py"):
            self.assertTrue(sp.in_temp(p), p)

    def test_a_notebook_in_the_notebook_folder_is_not_asked_about_or_listed(self):
        import scratchpad as sp
        self.assertIsNone(ask(write("E:/projects/x/.claude/p4/temportal/notebook/analysis.ipynb")))
        self.assertIsNotNone(ask(write("C:/Users/u/AppData/Local/Temp/analysis.ipynb")))
        with tempfile.TemporaryDirectory() as root:
            nb = os.path.join(root, ".claude", "p4", "temportal", "notebook")
            os.makedirs(nb)
            open(os.path.join(nb, "analysis.ipynb"), "w").close()
            listed = [p for ps in sp.repo_use_candidates(root).values() for p in ps]
            self.assertFalse([p for p in listed if p.endswith(".ipynb")], listed)

    def test_a_powershell_write_by_a_positional_path_is_asked_about(self):
        for cmd in ("Set-Content $env:TEMP\\x.py 'print(1)'", "'print(1)' | Out-File $env:TEMP\\x.py",
                    "'x' | Out-File -Encoding utf8 $env:TEMP\\x.py", "Set-Content -Value x $env:TEMP\\x.py",
                    "New-Item -ItemType File $env:TEMP\\x.py", "Add-Content -Value x $env:TMP\\x.py",
                    "Set-Content -Value x C:\\Users\\u\\AppData\\Local\\Temp\\x.py"):
            d = ask({"tool_name": "PowerShell", "cwd": "E:/projects/x", "tool_input": {"command": cmd}})
            self.assertIsNotNone(d, cmd)
            self.assertIn("x.py", d["permissionDecisionReason"], cmd)
        for cmd in ("Get-Content $env:TEMP\\x.py", "Get-Content $env:TEMP\\x.py | Select-String print"):
            self.assertIsNone(ask({"tool_name": "PowerShell", "cwd": "E:/projects/x", "tool_input": {"command": cmd}}),
                              cmd)

    def test_powershell_and_notebookedit_writes_are_read(self):
        import scratchpad as sp
        for cmd in ('"print(1)" > $env:TEMP/x.py', 'Set-Content -Path $env:TEMP/x.py -Value "print(1)"',
                    '"print(1)" | Out-File -FilePath $env:TEMP/x.py'):
            got = sp.written_paths({"tool_name": "PowerShell", "tool_input": {"command": cmd}})
            self.assertIn("$env:TEMP/x.py", got, cmd)
        got = sp.written_paths({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/tmp/n.ipynb"}})
        self.assertEqual(got, ["/tmp/n.ipynb"])
        with open(HOOKS_JSON, encoding="utf-8") as f:
            pre = json.load(f)["hooks"]["PreToolUse"]
        ask = [h for h in pre if any("scratchpad ask" in c["command"] for c in h["hooks"])][0]
        for tool in ("Write", "Edit", "Bash", "PowerShell", "NotebookEdit"):
            self.assertIn(tool, ask["matcher"].split("|"))

    def test_the_runner_skips_the_ask_only_when_it_is_off(self):
        """run-hook.sh starts no python for the ask while it is off, and runs it in every form asks_on() reads as
        on: the ask is given exactly when the asks are on."""
        proj = tempfile.mkdtemp(prefix="p4-temportal-runner-ask-")
        self.addCleanup(wipe, proj)
        os.makedirs(os.path.join(proj, ".claude", "p4"))
        payload = json.dumps({"tool_name": "Write", "cwd": proj, "tool_input": {"file_path": "/tmp/x.py"}})
        cases = [('{"scratchpad": {"asks": true}}', None, True), ('{"scratchpad": {"asks" : true}}', None, True),
                 ('{"scratchpad": {"asks": 1}}', None, True), ('{"scratchpad": {"asks": "yes"}}', None, True),
                 ('{\n "scratchpad": {\n  "asks": true\n }\n}', None, True), ("{}", " 1", True),
                 ('{"scratchpad": {"asks": false}}', None, False), ('{"scratchpad": {"asks": 0}}', None, False),
                 ("{}", None, False), ('{"scratchpad": {"asks": true}}', "0", False)]
        for conf, env_val, on in cases:
            with open(os.path.join(proj, ".claude", "p4", "p4.json"), "w", encoding="utf-8") as f:
                f.write(conf)
            env = {k: v for k, v in os.environ.items() if k != "P4_SCRATCHPAD_ASKS"}
            env.update(CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=proj)
            if env_val is not None:
                env["P4_SCRATCHPAD_ASKS"] = env_val
            r = subprocess.run(["sh", os.path.join(HERE, "run-hook.sh"), "scratchpad", "ask"], input=payload.encode(),
                               env=env, capture_output=True, cwd=proj)
            self.assertEqual("permissionDecision" in r.stdout.decode("utf-8", "replace"), on, (conf, env_val))


if __name__ == "__main__":
    unittest.main(verbosity=1)
