#!/usr/bin/env python3
"""test_scratchpad.py: acceptance tests for p4-temportal's scratchpad part. The notebook's .out/ is seeded,
silently the first time, and seeded again, logs, build output and binaries move into it, and a clean tree prints
nothing at a session start. With P4_SCRATCHPAD_ASKS=1 repo-uses prints one line for each file under
.claude/p4/temportal/src/ the repository names, and with the switch off it is silent. The PreToolUse ask is gone for
Claude Code's own ask rules on Edit paths: hooks.json runs no PreToolUse hook, and a session that still runs
`scratchpad ask` gets nothing. Then each session's scratchpad, which is the app's: no start, turn end or session end
links, stages, commits or removes one. Run it as
`python -m pytest tests/p4-temportal/test_scratchpad.py` from the checkout, and exit 0 is green; the git
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

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "lbiza", "plugins", "p4-temportal", "hooks"))
HOOKS_JSON = os.path.join(SRC, "hooks.json")
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
    python start per call."""
    import contextlib
    import io
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
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
                           env=env_with(extra, CLAUDE_PLUGIN_ROOT=os.path.dirname(SRC), CLAUDE_PROJECT_DIR=root,
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
        r = subprocess.run([shutil.which("sh"), os.path.join(SRC, "run-hook.sh"), "scratchpad", "notebook-out"], input=b"{}",
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
    leave one moved layout, no layout lock and one p4.json that parses. No command hook runs at SessionEnd, where
    such hooks share 1.5 seconds: the hooks module starts the last sweep in a process let go of, which
    test_lifetime.py runs."""
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
        env = env_with(None, CLAUDE_PLUGIN_ROOT=os.path.dirname(SRC), CLAUDE_PROJECT_DIR=root,
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
        with open(HOOKS_JSON, encoding="utf-8") as f:
            assert "SessionEnd" not in json.load(f)["hooks"], "a SessionEnd command hook shares 1.5 s with every other"
    finally:
        wipe(root)
    print("test_scratchpad.py: parallel hooks cases green")


class Cases(unittest.TestCase):
    """Each case group a test method, so unittest and pytest collect them."""

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
        env = env_with(None, CLAUDE_PLUGIN_ROOT=os.path.dirname(SRC), CLAUDE_PROJECT_DIR=self.root,
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
        """No command hook runs at a session's end, and the sweep the hooks module starts there, `lifetime.py tick`,
        has nothing to clear in a store with no cookie and no file past a cache rule."""
        self.hooks("SessionStart")
        self.hooks("Stop")
        head = self.git("rev-parse", "HEAD")
        self.hooks("SessionEnd", "other")
        env = env_with(None, CLAUDE_PROJECT_DIR=self.root, TEMP=self.temp, TMP=self.temp, TMPDIR=self.temp)
        tick = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "lifetime.py"), "tick"],
                              capture_output=True, timeout=120, env=env)
        self.assertEqual((tick.returncode, json.loads(tick.stdout)["said"]), (0, []), tick)
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


class FailureNotice(unittest.TestCase):
    """ezexe/p4#114: a failure of a subcommand, and an unknown subcommand, print a systemMessage, which Claude Code
    shows ezexe on every event, where plain stdout reaches nobody on most."""

    def test_a_degraded_or_unknown_subcommand_prints_a_system_message(self):
        import contextlib
        import io
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        import scratchpad as sp
        root = tempfile.mkdtemp(prefix="p4-temportal-scratchpad-fail-")
        self.addCleanup(wipe, root)
        old = (sp.cmd_notebook_out, sys.argv, sys.stdin)

        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            sp.cmd_notebook_out = broken
            for sub, want in (("notebook-out", "scratchpad notebook-out degraded: OSError: disk gone"), ("nope", "unknown subcommand")):
                sys.argv = ["scratchpad.py", sub]
                sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(
                    {"cwd": root, "hook_event_name": "SessionStart"}).encode()), encoding="utf-8")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(sp.main(), 0)
                self.assertIn(want, json.loads(out.getvalue())["systemMessage"])
        finally:
            sp.cmd_notebook_out, sys.argv, sys.stdin = old


class Unlink(unittest.TestCase):
    """ezexe/p4#131: a session started on 0.3.9 has its app scratchpad as a link into the store's temportal/tmp/, and
    every write through it is a protected write under .claude/. tmp-unlink, at a start and by hand, makes each such
    link a real folder holding a copy of the store folder's files, keeps the store folder, and leaves a real folder
    and a link elsewhere as they are."""

    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh on PATH")
        self.temp = tempfile.mkdtemp(prefix="p4-temportal-unlink-temp-")
        self.root = tempfile.mkdtemp(prefix="p4-temportal-unlink-")
        self.elsewhere = tempfile.mkdtemp(prefix="p4-temportal-unlink-else-")
        for d in (self.temp, self.root, self.elsewhere):
            self.addCleanup(wipe, d)
        self.hashdir = os.path.join(self.temp, "claude", "30ad6e18862a20e8")
        self.store_tmp = os.path.join(self.root, ".claude", "p4", "temportal", "tmp")

    def linked(self, sid, files):
        target = os.path.join(self.store_tmp, sid)
        for rel, text in files.items():
            put(target, rel, text)
        sp = os.path.join(self.hashdir, sid, "scratchpad")
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        make_link(sp, target)
        self.addCleanup(lambda: is_link(sp) and unlink(sp))
        return sp, target

    def env(self):
        return env_with(None, CLAUDE_PLUGIN_ROOT=os.path.dirname(SRC), CLAUDE_PROJECT_DIR=self.root,
                        CLAUDE_CONFIG_DIR=os.path.join(self.root, ".config"), TEMP=self.temp, TMP=self.temp,
                        TMPDIR=self.temp)

    def assert_unlinked(self, sp, target, files):
        self.assertFalse(is_link(sp), f"{sp} is still a link")
        self.assertTrue(os.path.isdir(sp))
        for rel, text in files.items():
            with open(os.path.join(sp, *rel.split("/")), encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"{rel} was not copied")
            with open(os.path.join(target, *rel.split("/")), encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"{rel} left the store")

    def test_a_start_and_a_hand_run_unlink_and_leave_the_rest(self):
        files = {"a.md": "a\n", "sub/b.md": "b\n"}
        linked, target = self.linked("aaaa1111-0000-4000-8000-00000000000a", files)
        real = os.path.join(self.hashdir, "bbbb2222-0000-4000-8000-00000000000b", "scratchpad")
        put(real, "c.md", "c\n")
        other = os.path.join(self.hashdir, "cccc3333-0000-4000-8000-00000000000c", "scratchpad")
        os.makedirs(os.path.dirname(other))
        make_link(other, self.elsewhere)
        self.addCleanup(lambda: is_link(other) and unlink(other))
        with open(HOOKS_JSON, encoding="utf-8") as f:
            cmd = [h["command"] for g in json.load(f)["hooks"]["SessionStart"] for h in g["hooks"]
                   if "scratchpad tmp-unlink" in h["command"]]
        self.assertEqual(len(cmd), 1, "no SessionStart hook runs tmp-unlink")
        stdin = json.dumps({"cwd": self.root, "session_id": "bbbb2222-0000-4000-8000-00000000000b",
                            "scratchpad_dir": real, "source": "startup"}).encode()
        r = subprocess.run([shutil.which("sh"), "-c", cmd[0]], input=stdin, capture_output=True, timeout=60,
                           env=self.env())
        self.assertEqual(r.returncode, 0, r)
        self.assertIn("unlinked from the store: 1", r.stdout.decode("utf-8", "replace"))
        self.assert_unlinked(linked, target, files)
        self.assertEqual(os.listdir(real), ["c.md"], "a real scratchpad was touched")
        self.assertTrue(is_link(other) and os.path.samefile(other, self.elsewhere), "a link elsewhere was touched")
        # by hand, naming the project, for a link a session started on 0.3.9 still holds
        late, late_target = self.linked("dddd4444-0000-4000-8000-00000000000d", {"n.md": "n\n"})
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "scratchpad.py"), "tmp-unlink",
                            self.root], stdin=subprocess.DEVNULL, capture_output=True, timeout=60, env=self.env())
        self.assertEqual(r.returncode, 0, r)
        self.assert_unlinked(late, late_target, {"n.md": "n\n"})
        self.assertTrue(is_link(other), "a hand run touched a link elsewhere")


def make_link(link, target):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))
    else:
        os.symlink(os.path.abspath(target), link, target_is_directory=True)


def unlink(link):
    os.unlink(link) if os.path.islink(link) else os.rmdir(link)


class RetiredAsk(unittest.TestCase):
    """The PreToolUse ask on code headed for a temp folder or the notebook is Claude Code's own ask rule on an Edit
    path, by https://code.claude.com/docs/en/permissions.md: "`Edit` rules apply to all built-in tools that edit
    files." p4-temportal runs no copy of it."""

    def test_hooks_json_runs_no_pretooluse_hook(self):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        self.assertNotIn("PreToolUse", hooks)
        self.assertEqual([c for e in hooks for c in event_hooks(e) if "scratchpad ask" in c], [])

    def test_scratchpad_py_has_no_ask(self):
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        import scratchpad as sp
        for name in ("cmd_ask", "written_paths", "in_temp", "in_notebook", "in_harness_scratchpad", "WRITE_RES"):
            self.assertFalse(hasattr(sp, name), name)

    def test_the_commands_of_the_copies_are_gone(self):
        """`ask`, `tmp-sweep`, `tmp-close` and `tmp-link` were kept for sessions of older versions, which run the
        scripts of their own folder in Claude Code's plugin cache and never reach this file. Each is an unknown
        subcommand now, said in a systemMessage with exit 0 as every other is, and the runner holds no line for one."""
        payload = {"tool_name": "Write", "cwd": "E:/projects/x", "tool_input": {"file_path": "/tmp/x.py", "content": "x"}}
        for sub in ("ask", "tmp-sweep", "tmp-close", "tmp-link"):
            said = json.loads(run_sub(sub, payload, ON))
            self.assertEqual(said, {"systemMessage": f"scratchpad.py: unknown subcommand {sub!r}"}, sub)
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        import scratchpad as sp
        self.assertFalse(hasattr(sp, "RETIRED"))
        with open(os.path.join(SRC, "run-hook.sh"), encoding="utf-8") as f:
            runner = f.read()
        self.assertNotIn("ask", runner)
        with open(os.path.join(SRC, "scratchpad.py"), encoding="utf-8") as f:
            code = f.read().split('"""', 2)[2]
        for sub in ("tmp-sweep", "tmp-close", "tmp-link"):
            self.assertNotIn(sub, code, sub)

    def test_repo_uses_lists_no_notebook(self):
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        import scratchpad as sp
        with tempfile.TemporaryDirectory() as root:
            nb = os.path.join(root, ".claude", "p4", "temportal", "notebook")
            os.makedirs(nb)
            open(os.path.join(nb, "analysis.ipynb"), "w").close()
            listed = [p for ps in sp.repo_use_candidates(root).values() for p in ps]
            self.assertFalse([p for p in listed if p.endswith(".ipynb")], listed)


if __name__ == "__main__":
    unittest.main(verbosity=1)
