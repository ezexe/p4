#!/usr/bin/env python3
"""test_frag_gate.py — acceptance tests for the frag gate: anything into the harness scratchpad asks, code
into any other temp location asks, code (by extension or by name) into any project's .claude/scratchpad/
asks (the split and the floor: the notebook is git-ignored, a frag is tracked under src/, and a tool call is
no file), and files under p4/src/, non-code files in the project's scratchpad, or the project tree
pass. Then the SessionStart hook: it seeds src/frags.md and the notebook's own `.gitignore` of `*`,
overwrites neither, and says in one line when the project's root rules ignore src/. Run from anywhere:
python hooks/test_frag_gate.py — exit 0 = green (the hook cases skip, saying so, without sh or git on
PATH)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "frag_gate.py")
SCRATCH = "C:/Users/someone/AppData/Local/Temp/claude/E--projects-x/abc123/scratchpad"
STORE_SRC = "E:/projects/x/.claude/p4/sessions/test-ses/src/sweep-20260903"
PROJECT_PAD = "E:/projects/x/.claude/scratchpad"


def run(payload):
    r = subprocess.run([sys.executable, GATE, "frag-gate"], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.startswith("{"):
            return json.loads(line)["hookSpecificOutput"]
    assert out.strip() == "", f"unexpected non-JSON output: {out}"
    return None


def write(path):
    return {"tool_name": "Write", "cwd": "E:/projects/x", "tool_input": {"file_path": path, "content": "x"}}


def bash(cmd):
    return {"tool_name": "Bash", "cwd": "E:/projects/x", "tool_input": {"command": cmd}}


def main():
    # the harness scratchpad: everything asks, and the reason names the right home
    d = run(write(f"{SCRATCH}/sweep.py"))
    assert d and d["permissionDecision"] == "ask" and "sweep.py" in d["permissionDecisionReason"], d
    assert "p4" in d["permissionDecisionReason"] and "src" in d["permissionDecisionReason"], d
    d = run(write(f"{SCRATCH}/commit-msg.txt"))
    assert d and "scratchpad" in d["permissionDecisionReason"], "text in the harness scratchpad passed"
    assert ".claude" in d["permissionDecisionReason"], d
    assert run(write(f"{SCRATCH}/notes.md")) is not None, "notes in the harness scratchpad passed"
    # the project's own homes pass
    assert run(write(f"{STORE_SRC}/sweep.py")) is None, "store frag asked"
    assert run(write(f"{PROJECT_PAD}/commit-msg.txt")) is None, "project scratchpad asked"
    assert run(write(f"{PROJECT_PAD}/run.log")) is None, "a log in the project scratchpad asked"
    assert run(write("E:/projects/x/tools/build.py")) is None, "project code asked"
    # code in a project scratchpad asks, and the ask carries the floor
    d = run(write(f"{PROJECT_PAD}/probe.py"))
    assert d and d["permissionDecision"] == "ask" and "probe.py" in d["permissionDecisionReason"], "code in the project scratchpad passed"
    assert "tool's own call" in d["permissionDecisionReason"] and "frags.md" in d["permissionDecisionReason"], d
    assert run(write(".claude/scratchpad/edit.py")) is not None, "relative code path in the project scratchpad passed"
    assert run(bash("cat > .claude/scratchpad/gen.py <<'EOF'\nprint(1)\nEOF\n")) is not None, "bash heredoc code into the project scratchpad passed"
    assert run(write("E:/other/.claude/scratchpad/swap.py")) is not None, "code in another project's scratchpad passed"
    assert run(write(f"{PROJECT_PAD}/notes.md")) is None, "notes in the project scratchpad asked"
    # the ask carries the split: the notebook is git-ignored, a frag is tracked
    assert "git-ignored notebook" in d["permissionDecisionReason"] and "tracked" in d["permissionDecisionReason"], d
    # code by a build-language extension or by name asks in a notebook too, and passes under src/
    assert run(write(f"{PROJECT_PAD}/envtest.cmake")) is not None, "a .cmake probe in the project scratchpad passed"
    assert run(write(f"{PROJECT_PAD}/probe/CMakeLists.txt")) is not None, "CMakeLists.txt in the project scratchpad passed"
    assert run(write(f"{PROJECT_PAD}/probe/Makefile")) is not None, "a Makefile in the project scratchpad passed"
    assert run(write(f"{STORE_SRC}/CMakeLists.txt")) is None, "CMakeLists.txt under p4/src asked"
    assert run(write(f"{PROJECT_PAD}/cmdlines.txt")) is None, "a .txt note in the project scratchpad asked"
    # a page is code: a harness page in a notebook asks (the ask says a captured page may proceed), under src/
    # and in the project tree it passes
    d = run(write(f"{PROJECT_PAD}/harness.html"))
    assert d and d["permissionDecision"] == "ask" and "captured" in d["permissionDecisionReason"], "an .html page in the project scratchpad passed"
    assert run(write(f"{STORE_SRC}/latency.html")) is None, "a harness page under p4/src asked"
    assert run(write("E:/projects/x/web/index.html")) is None, "a page in the project tree asked"
    # other temp locations: code asks, data passes
    assert run(bash("cat > /tmp/probe.sh <<'EOF'\necho hi\nEOF\n")) is not None, "bash temp script passed"
    assert run(bash("cat > /tmp/out.json <<'EOF'\n{}\nEOF\n")) is None, "data in /tmp asked"
    assert run(bash(f'python - <<\'EOF\'\nopen("{SCRATCH}/gen.py", "w").write("x")\nEOF\n')) is not None, "python open to the scratchpad passed"
    assert run(bash(f"cp tools/x.py {SCRATCH}/x.py")) is not None, "cp to the scratchpad passed"
    assert run(bash(f"cat > {STORE_SRC}/sweep.py <<'EOF'\nprint(1)\nEOF\n")) is None, "bash store frag asked"
    assert run(bash("grep -n def /tmp/probe.sh")) is None, "read of a temp script asked"
    ps = {"tool_name": "PowerShell", "cwd": "E:/projects/x",
          "tool_input": {"command": f'Set-Content -Path "{SCRATCH}/run.ps1" -Value "echo hi"'}}
    assert run(ps) is not None, "Set-Content to the scratchpad passed"
    edit = {"tool_name": "Edit", "cwd": "E:/projects/x",
            "tool_input": {"file_path": f"{SCRATCH}/sweep.py", "old_string": "a", "new_string": "b"}}
    assert run(edit) is not None, "Edit of a scratchpad script passed"
    assert run({"tool_name": "Read", "tool_input": {"file_path": f"{SCRATCH}/sweep.py"}}) is None

    # a subagent gets no ask: no hook event injects the contract into a spawned subagent, so its writer was
    # never told, and the human who answers the prompt cannot redirect an agent already running
    for p in (write(f"{SCRATCH}/zz_lines.py"), write(f"{PROJECT_PAD}/probe.py"),
              bash("cat > /tmp/probe.sh <<'EOF'\necho hi\nEOF\n")):
        sub = dict(p, agent_id="agent_01ABC", agent_type="Explore")
        assert run(sub) is None, f"subagent write asked: {p['tool_input']}"
    # ...and the same payload without agent_id still asks, so the suppression is the tell, not the path
    assert run(write(f"{SCRATCH}/zz_lines.py")) is not None, "main-loop scratchpad write stopped asking"

    # the floor's mechanical arm: a read/swap/write-back script is an Edit call in costume, wherever it lands
    COSTUME = ('import pathlib\n'
               'p = pathlib.Path("src/thing.cpp")\n'
               's = p.read_text()\n'
               's = s.replace("oldName", "newName")\n'
               'p.write_text(s)\n')
    d = run({"tool_name": "Write", "cwd": "E:/projects/x",
             "tool_input": {"file_path": f"{STORE_SRC}/swap.py", "content": COSTUME}})
    assert d and d["permissionDecision"] == "ask", "a costume swap script under p4/src passed"
    assert "in costume" in d["permissionDecisionReason"], d
    assert "Edit call" in d["permissionDecisionReason"], d
    d = run({"tool_name": "Write", "cwd": "E:/projects/x",
             "tool_input": {"file_path": "E:/projects/x/tools/swap.py", "content": COSTUME}})
    assert d and "in costume" in d["permissionDecisionReason"], "a costume script in the project tree passed"
    # a heredoc carrying the same body is the same costume
    assert run(bash(f"cat > {STORE_SRC}/swap2.py <<'EOF'\n{COSTUME}EOF\n")) is not None, "costume heredoc passed"
    # honest frags are untouched: reads without a swap, writes without a read, and anything long
    assert run({"tool_name": "Write", "cwd": "E:/projects/x",
                "tool_input": {"file_path": f"{STORE_SRC}/scan.py",
                               "content": 'import json\nd = open("a.jsonl").read()\nopen("out.json","w").write(d)\n'}}) is None, \
        "a read-then-write analysis script was called a costume"
    assert run({"tool_name": "Write", "cwd": "E:/projects/x",
                "tool_input": {"file_path": f"{STORE_SRC}/gen.py",
                               "content": 'open("out.txt","w").write("hello")\n'}}) is None, \
        "a plain generator was called a costume"
    assert run({"tool_name": "Write", "cwd": "E:/projects/x",
                "tool_input": {"file_path": f"{STORE_SRC}/big.py",
                               "content": COSTUME + "".join(f"x{i} = {i}\n" for i in range(60))}}) is None, \
        "a long program was called a costume"
    # a costume body under a subagent still says nothing — the ephemeral cases are the subagent's exemption
    assert run({"tool_name": "Write", "cwd": "E:/projects/x", "agent_id": "agent_01ABC",
                "tool_input": {"file_path": f"{STORE_SRC}/swap.py", "content": COSTUME}}) is None, \
        "subagent costume asked"

    # scratch data dropped in the project root asks — and asks for a subagent too, because the file outlives
    # every agent that could have been told and the user is the one who finds it; a drive-letter path is the root's
    # in either spelling, whatever OS the gate runs on
    for payload in (write("E:/projects/x/_rows.json"), write("E:\\projects\\x\\_rows.json"), write("_per.json"),
                    bash("python - <<'EOF'\nopen('E:/projects/x/dump.jsonl','w').write('x')\nEOF\n")):
        d = run(payload)
        assert d and d["permissionDecision"] == "ask", f"root data file passed: {payload['tool_input']}"
        assert "project root" in d["permissionDecisionReason"], d
    d = run(dict(write("E:/projects/x/_rows.json"), agent_id="agent_01ABC", agent_type="Explore"))
    assert d and "project root" in d["permissionDecisionReason"], "subagent root dump passed"
    # the project's own root files are not scratch, and neither is anything in a subdirectory
    for ok in ("E:/projects/x/package.json", "E:/projects/x/settings.json", "E:/projects/x/requirements.txt",
               "E:/projects/x/Ibiza/.claude-plugin/marketplace.json", "E:/projects/x/data/rows.json",
               "E:\\projects\\x\\data\\rows.json",
               "E:/projects/x/README.md", "E:/projects/x/tools/build.py",
               # a build file is code by name, not a .txt dump — the project's own CMakeLists.txt never asks
               "E:/projects/x/CMakeLists.txt", "CMakeLists.txt", "E:/projects/x/Makefile"):
        assert run(write(ok)) is None, f"a legitimate file asked: {ok}"
    edit = {"tool_name": "Edit", "cwd": "E:/projects/x",
            "tool_input": {"file_path": "E:/projects/x/CMakeLists.txt", "old_string": "a", "new_string": "b"}}
    assert run(edit) is None, "an Edit of the project's root CMakeLists.txt asked"
    print("test_frag_gate.py: gate cases green")
    register_lint()
    session_open()
    print("test_frag_gate.py: all green")


def register_lint():
    """The register check: silent on a clean store; one line naming unregistered code under src/ and entries
    whose path is gone — never a non-code file, never a retired entry."""
    root = tempfile.mkdtemp(prefix="src-fragger-lint-")
    src = os.path.join(root, ".claude", "p4", "sessions", "test-ses", "src")
    os.makedirs(os.path.join(src, "sweep-20260903"))
    os.makedirs(os.path.join(src, "claims-20260909"))

    def put(rel, text="x\n"):
        with open(os.path.join(src, rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def lint():
        r = subprocess.run([sys.executable, GATE, "register-lint"], input=b"{}", capture_output=True, timeout=60,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=root))
        return r.stdout.decode("utf-8", "replace").strip()

    with open(os.path.join(HERE, "frags-seed.md"), encoding="utf-8") as f:
        seed = f.read()
    put("sweep-20260903/sweep.py")
    put("claims-20260909/sheets.md")
    put("frags.md", seed + "\n- frag: sweep-20260903/sweep.py\n  time: 2026-09-03 13:13\n  task: t\n  run: r\n  state: live\n"
        "\n- frag: claims-20260909/claims.html\n  time: 2026-09-09 13:01\n  task: t\n  run: r\n"
        "  state: RETIRED AS A FRAG, MOVED NOT DELETED - now under tests/web\n")
    assert lint() == "", "a clean register (a registered frag, an unregistered sheet, a retired entry at a gone path) drifted"
    # the header's own `- frag:` shape line is not an entry: the seed alone is clean too
    put("frags.md", seed)
    os.remove(os.path.join(src, "sweep-20260903", "sweep.py"))
    assert lint() == "", "the seed's shape line was read as an entry"
    # code under a task's out/ is what the frag reads or produced, never an unregistered frag
    os.makedirs(os.path.join(src, "claims-20260909", "out", "docs"))
    put("claims-20260909/out/upstream_tool.py")
    put("claims-20260909/out/docs/patcher.py")
    put("claims-20260909/out/captured.html")
    assert lint() == "", "code under out/ was called unregistered"
    # unregistered code under src/ is named; a live entry whose path is gone is named
    put("sweep-20260903/holder.ps1")
    put("frags.md", seed + "\n- frag: sweep-20260903/gone.py\n  time: 2026-09-03 13:13\n  task: t\n  run: r\n  state: live\n")
    out = lint()
    assert out.startswith("src-fragger: register drift"), out
    assert "sweep-20260903/holder.ps1" in out and "gone.py" in out, out
    assert "sheets.md" not in out, "a non-code file under src/ was called unregistered"
    assert "\n" not in out, "the notice is more than one line"
    # no store at all: silent
    shutil.rmtree(os.path.join(root, ".claude"))
    assert lint() == "", "lint spoke without a store"
    shutil.rmtree(root, ignore_errors=True)
    print("test_frag_gate.py: register-lint cases green")


NOTICE = "src-fragger: .claude/p4/ is not a git repository yet"


def session_open():
    """The SessionStart hook seeds src/frags.md and the notebook's own .gitignore of `*`, overwrites neither
    (a user's edit is a ruling), and says in one line when the project's root rules ignore src/."""
    sh = shutil.which("sh")
    if not sh:
        print("test_frag_gate.py: session-open cases SKIPPED — no sh on PATH")
        return
    root = tempfile.mkdtemp(prefix="src-fragger-test-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE))

    def open_session(*step):
        r = subprocess.run([sh, os.path.join(HERE, "session-open.sh"), *step], env=env, capture_output=True,
                           input=b'{"source": "startup", "session_id": "test-session"}', timeout=60)
        return r.stdout.decode("utf-8", "replace")

    def read(*parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def put(text, *parts):
        with open(os.path.join(*parts), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    out = open_session()
    assert "## src-fragger (always active)" in out, out[:300]
    assert read(root, ".claude", "scratchpad", ".gitignore") == "*\n", "the notebook's .gitignore was not seeded as *"
    assert read(root, ".claude", "p4", "sessions", "test-ses", "src", "frags.md") == read(HERE, "frags-seed.md"), "the register was not seeded"
    # a user's edit to either seed is a ruling: neither is overwritten
    put("# tracked on purpose\n", root, ".claude", "scratchpad", ".gitignore")
    put("# my register\n", root, ".claude", "p4", "sessions", "test-ses", "src", "frags.md")
    open_session()
    assert read(root, ".claude", "scratchpad", ".gitignore") == "# tracked on purpose\n", "the user's .gitignore edit was overwritten"
    assert read(root, ".claude", "p4", "sessions", "test-ses", "src", "frags.md") == "# my register\n", "the user's register was overwritten"
    put("*\n", root, ".claude", "scratchpad", ".gitignore")
    git = shutil.which("git")
    if not git:
        print("test_frag_gate.py: session-open git cases SKIPPED — no git on PATH")
        shutil.rmtree(root, ignore_errors=True)
        return

    def g(*args):
        return subprocess.run([git, "-C", root, *args], capture_output=True, timeout=60).returncode

    assert g("init", "-q") == 0, "git init failed"
    # the seed ignores the notebook by itself, with no root rule — and src/ stays trackable
    assert g("check-ignore", "-q", ".claude/scratchpad/notes.md") == 0, "the notebook does not ignore itself"
    assert g("check-ignore", "-q", ".claude/scratchpad/probe.py") == 0, "code in the notebook is not ignored"
    # with no p4 repo yet, p4/src/ is untracked, and the hook says so in one line
    out = open_session()
    assert out.count(NOTICE) == 1, "the no-p4-repo notice is missing or more than one line"
    assert "## src-fragger (always active)" in out, "the contract was lost behind the notice"
    # the two hook commands: `seed` carries the notice and nothing of the contract, `contract` the reverse, so
    # each rides under the harness's per-hook output cap on its own
    seed_out, contract_out = open_session("seed"), open_session("contract")
    assert NOTICE in seed_out and "## src-fragger" not in seed_out, seed_out[:300]
    assert "## src-fragger (always active)" in contract_out and NOTICE not in contract_out, contract_out[:300]
    assert len(contract_out) < 10000, f"the contract alone is {len(contract_out)} chars — over the hook output cap"
    # once .claude/p4/ is its own repository, p4/src/ is trackable there and the notice stops
    assert subprocess.run([git, "init", "-q", os.path.join(root, ".claude", "p4")], timeout=60).returncode == 0
    assert NOTICE not in open_session(), "notice printed while the p4 repo exists"
    shutil.rmtree(root, ignore_errors=True)
    # a legacy src/ under the old store is copied into the session directory _legacy, the legacy directory is left
    # in place for the user, and this session gets its own seeded register beside it
    root = tempfile.mkdtemp(prefix="frag-legacy-")
    env["CLAUDE_PROJECT_DIR"] = root
    os.makedirs(os.path.join(root, ".claude", "vlds", "src", "t1"))
    legacy_reg = ("# legacy register\n\n---\n\n- frag: t1/run.py\n  time: 2026-09-03 13:13\n  task: t\n  run: r\n"
                  "  state: live\n")
    put(legacy_reg, root, ".claude", "vlds", "src", "frags.md")
    out = open_session("seed")
    assert "copied the legacy .claude/vlds/src/" in out, out[:400]
    assert read(root, ".claude", "p4", "sessions", "_legacy", "src", "frags.md") == legacy_reg, "the legacy register moved wrong"
    assert os.path.isdir(os.path.join(root, ".claude", "p4", "sessions", "_legacy", "src", "t1")), "a legacy task directory was not copied"
    assert read(root, ".claude", "p4", "sessions", "test-ses", "src", "frags.md") == read(HERE, "frags-seed.md"), \
        "this session's own register was not seeded"
    assert read(root, ".claude", "vlds", "src", "frags.md") == legacy_reg, "the legacy directory was disturbed"
    assert "copied the legacy" not in open_session("seed"), "the legacy copy ran twice"
    # the cumulative frag index lists every session's register, and its keys name the frag by session
    sindex = read(root, ".claude", "p4", "sindex", "frags.md")
    assert "## _legacy" in sindex and "- frag: t1/run.py" in sindex and "## test-ses" in sindex, sindex
    keys = read(root, ".claude", "p4", "sindex", "keys.tsv")
    assert "_legacy\tt1/run.py\tlive\t2026-09-03 13:13" in keys, keys
    shutil.rmtree(root, ignore_errors=True)
    # the flat .claude/p4/src/ (vlds 0.0.51 to 0.0.53) is moved, inside the p4 repo, into _legacy
    root = tempfile.mkdtemp(prefix="frag-flat-")
    env["CLAUDE_PROJECT_DIR"] = root
    os.makedirs(os.path.join(root, ".claude", "p4", "src", "t2"))
    put("# flat register\n", root, ".claude", "p4", "src", "frags.md")
    out = open_session("seed")
    assert "moved the flat .claude/p4/src/" in out, out[:400]
    assert not os.path.exists(os.path.join(root, ".claude", "p4", "src")), "the flat src/ is still there"
    assert read(root, ".claude", "p4", "sessions", "_legacy", "src", "frags.md") == "# flat register\n", "flat register lost"
    shutil.rmtree(root, ignore_errors=True)
    print("test_frag_gate.py: session-open cases green")


if __name__ == "__main__":
    main()
