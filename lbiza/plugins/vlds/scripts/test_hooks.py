#!/usr/bin/env python3
"""test_hooks.py — acceptance tests for the hooks' mechanics: the `pre-write` gate, the `[STRAY]` scan, the `now:`
clock in every hook output, the widened post-write trigger and its unchanged-verdict delta, the owner-voice digest,
the session title, the pooled recall mode (directive, silent slots, first-prompt nudge, compact re-inject, the
`pool: inject` fallback), and the turn-close light sweep (pour, expire, attach, index rewrite, the report at the
next prompt, the lock).

Run from anywhere:  python scripts/test_hooks.py
Each test seeds a throwaway project under a temp dir (a `.claude/p4/sessions/test-ses/vlds/` store with the dispatch seed, a ledger,
a local-storage file), points CLAUDE_PROJECT_DIR at it, and runs the hook or phi.py as the harness would —
a subprocess with the JSON payload on stdin. Exit 0 = every test green; the first failing assertion names
the test. Nothing here touches a real store.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOKS = os.path.join(PLUGIN, "hooks", "vlds_hooks.py")
PHI = os.path.join(HERE, "phi.py")
SEED = os.path.join(PLUGIN, "hooks", "dispatch-seed.md")
NOW_RE = re.compile(r"^(?:- )?now: \d{4}-\d{2}-\d{2} \d{2}:\d{2}$", re.M)

LEDGER_HEADER = """# VLDS Guide — Ledger

Append-only config audit.

```yaml
- correction: [the mis-matched key]
  time: [YYYY-MM-DD HH:MM]
  match: [what was assumed]
  meant: [what was actually wanted]
  delta: [the fix applied]
```

---
"""

LOCAL_STORAGE = """# VLDS Partition — localStorage

The user's stated preferences and rulings, in their words.

```yaml
- ruling: [the ruling, distilled]
  time: [YYYY-MM-DD HH:MM]
  owner-words: "[the user's actual words, verbatim]"
  scope: [what it governs, and for how long]
  status: LIVE | SPENT | FREED
  form: [optional — fence | file | artifact | message]
```

---

- ruling: "the plan goes in the reply as one fenced block"
  time: 2026-09-03 10:00
  owner-words: "should have just been the md fence in the reply for the text box"
  scope: durable
  status: LIVE
  form: fence

- ruling: "go"
  time: 2026-09-03 10:05
  owner-words: "go"
  scope: this turn
  status: SPENT
"""

# the incident fence, in shape: a python heredoc, a correctly homed dispatch append, and a ledger append whose
# path is spelled bare (true under an earlier fence's `cd .claude/p4/sessions/test-ses/vlds`, false at the repo root) with a hedged
# minute digit
INCIDENT = (
    'cd "{root}" && python - <<\'EOF\'\n'
    'print("the by-value fix")\n'
    'EOF\n'
    'cat >> .claude/p4/sessions/test-ses/vlds/dispatch.md <<\'EOF\'\n'
    '  addressed: the by-value fix landed\n'
    'EOF\n'
    'cat >> ledger.md <<\'EOF\'\n'
    '\n'
    '- correction: the first build after the handoff carried a dangling callback reference; two runs were read as a window cause\n'
    '  time: 2026-09-02 12:4x\n'
    'EOF\n'
)


CURRENT_SID = ["test-session"]   # the session a test's store belongs to; run_hook stamps it on an id-less payload


def store_of(root, sid=None):
    """A test project's session store, as the hooks resolve it: <root>/.claude/p4/sessions/<name>/vlds, <name> the
    session's `<title-slug>--<s8>` once named, `<s8>` until then (scripts/partition.py)."""
    import partition  # noqa: E402 — beside this file
    return partition.session_store(os.path.join(root, ".claude", "p4"), sid or CURRENT_SID[0])


def seed_project(sid="test-session"):
    CURRENT_SID[0] = sid
    root = tempfile.mkdtemp(prefix="vlds-test-")
    store = store_of(root, sid)
    os.makedirs(store)
    shutil.copy(SEED, os.path.join(store, "dispatch.md"))
    with open(os.path.join(store, "ledger.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LEDGER_HEADER)
    with open(os.path.join(store, "local-storage.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LOCAL_STORAGE)
    return root, store


def run_hook(sub, payload, root):
    # one store per test: every payload is the seeded session's, unless a test keeps a second session on purpose
    if isinstance(payload, dict) and not payload.pop("_keep_sid", False):
        payload = dict(payload, session_id=CURRENT_SID[0])
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
    r = subprocess.run([sys.executable, HOOKS, sub], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=env, timeout=60)
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")   # Windows text-mode stdout is CRLF


def run_check(store):
    r = subprocess.run([sys.executable, PHI, "--store", store, "check"], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def decision(out):
    for line in out.splitlines():
        if line.startswith("{"):
            return json.loads(line)["hookSpecificOutput"]
    return None


def bash(cmd, cwd):
    return {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": cmd}}


def write(path, content, cwd):
    return {"tool_name": "Write", "cwd": cwd, "tool_input": {"file_path": path, "content": content}}


def stamped(v, cwd):
    """A homed ledger append carrying one `time:` value — the gate's clock cases."""
    return bash(f'cat >> .claude/p4/sessions/test-ses/vlds/ledger.md <<\'EOF\'\n- correction: x\n  time: {v}\nEOF\n', cwd)


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def test_pre_write():
    root, store = seed_project()
    try:
        # (a) the incident fence: ask, naming <root>/ledger.md — and the hedged minute
        d = decision(run_hook("pre-write", bash(INCIDENT.format(root=root.replace("\\", "/")), root), root))
        assert d and d["permissionDecision"] == "ask", "(a) no ask on the incident fence"
        reason = d["permissionDecisionReason"]
        assert norm(os.path.join(root, "ledger.md")) in norm(reason), f"(a) stray path not named: {reason}"
        assert "12:4x" in reason, f"(a) placeholder time not named: {reason}"
        assert "dispatch.md resolves to" not in reason, "(a) the homed dispatch append was reported as stray"
        # (b) the same fence homed: nothing for the path, ask for the time
        homed = INCIDENT.format(root=root.replace("\\", "/")).replace("cat >> ledger.md", "cat >> .claude/p4/sessions/test-ses/vlds/ledger.md")
        d = decision(run_hook("pre-write", bash(homed, root), root))
        assert d and "12:4x" in d["permissionDecisionReason"], "(b) placeholder time not asked about"
        assert "outside the store" not in d["permissionDecisionReason"], "(b) homed path reported as stray"
        # (c) time corrected: silence
        fixed = homed.replace("12:4x", "11:27")
        assert run_hook("pre-write", bash(fixed, root), root).strip() == "", "(c) clean fence produced output"
        # (d) a Write to <root>/docs/index.md: ask
        d = decision(run_hook("pre-write", write(os.path.join(root, "docs", "index.md"), "# docs\n", root), root))
        assert d and d["permissionDecision"] == "ask", "(d) docs/index.md not asked about"
        # (e) a Write to the store's index.md: silence
        out = run_hook("pre-write", write(os.path.join(store, "index.md"), "- key: x\n  decision: rule\n", root), root)
        assert out.strip() == "", f"(e) homed Write produced output: {out}"
        # (f) the cd-into-store spelling is homed; a bare spelling with no cd resolves to the root
        out = run_hook("pre-write", bash('cd .claude/p4/sessions/test-ses/vlds && cat >> ledger.md <<\'EOF\'\n- key: x\nEOF\n', root), root)
        assert out.strip() == "", f"(f) cd-into-store spelling reported: {out}"
        d = decision(run_hook("pre-write", bash('cat >> ledger.md <<\'EOF\'\n- key: x\nEOF\n', root), root))
        assert d and "outside the store" in d["permissionDecisionReason"], "(f) bare spelling not asked about"
        # (g) a peer store's file is homed; a Git Bash /e/ spelling resolves; a PowerShell cmdlet is matched
        peer = os.path.join(root, "peer", ".claude", "p4", "sessions", "other-se", "vlds", "ledger.md").replace("\\", "/")
        assert run_hook("pre-write", bash(f'cat >> "{peer}" <<\'EOF\'\n- key: x\nEOF\n', root), root).strip() == "", \
            "(g) peer store write reported as stray"
        ps = {"tool_name": "PowerShell", "cwd": root,
              "tool_input": {"command": 'Add-Content -Path ledger.md -Value "- key: x"'}}
        d = decision(run_hook("pre-write", ps, root))
        assert d and "outside the store" in d["permissionDecisionReason"], "(g) Add-Content to a bare path not asked about"
        # (h) a runtime placeholder in a generating script is exempt
        gen = 'python - <<\'EOF\'\nwith open(".claude/p4/sessions/test-ses/vlds/ledger.md", "a") as f:\n    f.write(f"  time: {now:%Y-%m-%d %H:%M}\\n")\nEOF\n'
        assert run_hook("pre-write", bash(gen, root), root).strip() == "", "(h) runtime placeholder was flagged"
        # (i) a stamp guessed ahead of the clock: ask, naming the value and the latest now:; a stamp behind the
        # clock and today's date alone are silent; a date past today's asks
        now = datetime.datetime.now()
        ahead = (now + datetime.timedelta(minutes=50)).strftime("%Y-%m-%d %H:%M")
        d = decision(run_hook("pre-write", stamped(ahead, root), root))
        assert d and "guessed-ahead" in d["permissionDecisionReason"] and ahead in d["permissionDecisionReason"], \
            f"(i) a stamp 50 minutes ahead not asked about: {d}"
        assert re.search(r"now: \d{4}-\d{2}-\d{2} \d{2}:\d{2}", d["permissionDecisionReason"]), \
            "(i) the latest now: not named in the ask"
        behind = (now - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
        assert run_hook("pre-write", stamped(behind, root), root).strip() == "", "(i) a stamp behind the clock was flagged"
        assert run_hook("pre-write", stamped(now.strftime("%Y-%m-%d"), root), root).strip() == "", \
            "(i) today's date alone was flagged"
        tomorrow = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        d = decision(run_hook("pre-write", stamped(tomorrow, root), root))
        assert d and "guessed-ahead" in d["permissionDecisionReason"], "(i) a date past today's not asked about"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pre-write: green")


def test_stray_scan():
    root, store = seed_project()
    try:
        with open(os.path.join(root, "ledger.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n- correction: a reading that landed wrong\n  time: 2026-09-02 11:27\n")
        os.makedirs(os.path.join(root, "docs"))
        with open(os.path.join(root, "docs", "index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# Documentation index\n\nPlain prose here.\n")
        out = run_check(store)
        strays = [l for l in out.splitlines() if l.startswith("[STRAY]")]
        assert len(strays) == 1 and "ledger.md" in strays[0], f"expected one [STRAY] for ledger.md, got: {strays}"
        assert re.search(r"phi\.py check: \d+ corruption, \d+ debt, 1 stray, \d+ notes", out), out.splitlines()[-1]
        # re-homed: the entry appended into the store's ledger, the root file gone
        with open(os.path.join(root, "ledger.md"), encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(store, "ledger.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write(body)
        os.remove(os.path.join(root, "ledger.md"))
        out = run_check(store)
        assert not [l for l in out.splitlines() if l.startswith("[STRAY]")], "stray still reported after re-home"
        assert "0 stray" in out, out.splitlines()[-1]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("stray scan: green")


def test_clock_and_post_write():
    root, store = seed_project()
    try:
        out = run_hook("session-open", {"source": "startup", "session_id": "test-session"}, root)
        assert NOW_RE.search(out), f"session-open carries no now: line:\n{out}"
        out = run_hook("prompt-open", {"session_id": "test-session", "prompt": "hello"}, root)
        assert NOW_RE.search(out), f"prompt-open carries no now: line:\n{out}"
        # post-write on the incident fence: the widened trigger runs the check, and [STRAY] names the file
        with open(os.path.join(root, "ledger.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n- correction: a reading that landed wrong\n  time: 2026-09-02 11:27\n")
        out = run_hook("post-write", bash(INCIDENT.format(root=root.replace("\\", "/")), root), root)
        ctx = decision(out)["additionalContext"]
        assert ctx.startswith("now: "), f"post-write context lacks the clock prefix:\n{ctx}"
        assert "[STRAY]" in ctx and "ledger.md" in ctx, f"post-write context lacks the [STRAY] line:\n{ctx}"
        assert "OUTSIDE the store" in ctx, ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("clock + post-write: green")


TOMBSTONES = """# VLDS GC — Tombstones

```yaml
- freed: [the decision that was disposed]
  time: [YYYY-MM-DD HH:MM]
  cause: retraction | superseded | fixed-cause | world-drift
  owner-words: "[the user's words]"
  swept: [what went with it]
```

---
"""

INDEX = """# VLDS Guide — Index

```yaml
- key: [need-shape + claim-kind]
  decision: [the rule]
  time: [YYYY-MM-DD HH:MM]
```

---

- key: integration tests
  decision: "stub the suite — the plan goes in the reply as one fenced block, so nothing runs locally"
  time: 2026-09-03 10:20

- key: say the clock line once in every reply, at its top
  decision: "the now: line, copied"
  time: 2026-09-03 10:21
"""


def test_gc_trace():
    root, store = seed_project()
    ls, tomb = os.path.join(store, "local-storage.md"), os.path.join(store, "tombstones.md")

    def append(path, text):
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def ctx_of(out):
        d = decision(out)
        return d["additionalContext"] if d else ""
    try:
        with open(os.path.join(store, "index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(INDEX)
        # (a) the first trace on a store records a baseline and reports nothing
        out = run_hook("post-write", write(ls, "x", root), root)
        assert "gc:" not in ctx_of(out), f"(a) the baseline reported:\n{out}"
        assert os.path.exists(os.path.join(store, ".gc-heads")), "(a) no remembered set"
        # (b) a free: the tombstone masks the fence ruling, and the index rule quoting its opening holds a handle —
        # its pre-finalizer is owed this turn; the unrelated rule is not named
        with open(tomb, "w", encoding="utf-8", newline="\n") as f:
            f.write(TOMBSTONES + '\n- freed: "the plan goes in the reply as one fenced block"\n  time: 2026-10-01 09:00\n'
                    '  cause: retraction\n  owner-words: "drop the fence rule"\n  swept: []\n')
        ctx = ctx_of(run_hook("post-write", write(tomb, "x", root), root))
        assert "gc: a free (tombstones.md:" in ctx and "reaches local-storage.md:" in ctx, f"(b) the reach:\n{ctx}"
        assert "held by index.md:" in ctx and "pre-finalizer is owed this turn" in ctx, f"(b) the holder:\n{ctx}"
        assert ctx.count("index.md:") == 1, f"(b) the unrelated rule was named:\n{ctx}"
        # (c) nothing new since: no gc: line
        ctx = ctx_of(run_hook("post-write", write(ls, "x", root), root))
        assert "gc:" not in ctx, f"(c) a trace with nothing new reported:\n{ctx}"
        # (d) the freed ruling written again after the free is a re-allocation; the same text dated before the free
        # (an old line returned) is freed history, not reported
        append(ls, '\n- ruling: "the plan goes in the reply as one fenced block"\n  time: 2026-10-02 11:00\n'
                   '  owner-words: "fence it"\n  scope: durable\n  status: LIVE\n'
                   '\n- ruling: "the plan goes in the reply as one fenced block"\n  time: 2026-08-02 11:00\n'
                   '  owner-words: "fence it, old"\n  scope: durable\n  status: LIVE\n')
        ctx = ctx_of(run_hook("post-write", write(ls, "x", root), root))
        assert ctx.count("is new and masked by tombstones.md:") == 1, f"(d) the re-allocation:\n{ctx}"
        assert "local-storage.md:29 (" in ctx, f"(d) the wrong entry named:\n{ctx}"
        # (e) a write no post-write saw (a hand edit) is traced at the turn's close and printed at the next prompt
        append(tomb, '\n- freed: "say the clock line once in every reply, at its top"\n  time: 2026-10-02 12:00\n  cause: superseded\n'
                     '  owner-words: "no clock line"\n  swept: [the index rule]\n')
        out = run_hook("turn-close", {"session_id": "trace-session", "cwd": root}, root)
        assert "turn-close: gc: a free (tombstones.md:" in out and "no live entry holds a handle" in out, \
            f"(e) the close's trace:\n{out}"
        out = run_hook("prompt-open", {"session_id": "trace-session", "prompt": "next"}, root)
        assert "- turn-close (" in out and "gc: a free" in out, f"(e) the report not printed at the next prompt:\n{out}"
        # (f) a free whose target is not in the hot tier says so; phi.py trace --dry records nothing
        append(tomb, '\n- freed: "a memory file outside the store that said to warn before audio tests"\n'
                     '  time: 2026-10-02 12:10\n  cause: retraction\n  owner-words: "that gate was a hallucination"\n')
        r = subprocess.run([sys.executable, PHI, "--store", store, "trace", "--dry"], capture_output=True, timeout=60)
        dry = r.stdout.decode("utf-8", "replace")
        assert "masks no hot entry" in dry, f"(f) the out-of-tier free:\n{dry}"
        r = subprocess.run([sys.executable, PHI, "--store", store, "trace", "--json"], capture_output=True, timeout=60)
        assert len(json.loads(r.stdout.decode("utf-8"))["findings"]) == 1, "(f) --dry recorded the heads"
        # (g) the always-on block: its own SessionStart output, under the hook cap, registered in hooks.json
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        r = subprocess.run(["sh", os.path.join(PLUGIN, "hooks", "session-open.sh"), "--gc"], capture_output=True,
                           env=env, timeout=60)
        block = r.stdout.decode("utf-8", "replace")
        assert block.startswith("## VLDS gc (always on)") and len(block) < 9500, \
            f"(g) the block: {len(block)} chars"
        with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as f:
            hooks = json.load(f)
        assert any(h["command"].endswith("session-open.sh\" --gc") for h in hooks["hooks"]["SessionStart"][0]["hooks"]), \
            "(g) the block is not registered"
        with open(os.path.join(PLUGIN, "skills", "gc", "SKILL.md"), encoding="utf-8") as f:
            front = f.read().split("\n---\n", 1)[0]
        assert "disable-model-invocation" not in front, "(g) the gc skill is still direct-invoke only"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("gc trace: green")


def test_owner_voice():
    root, store = seed_project()
    try:
        with open(os.path.join(store, "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# index\n\n## recall\n\ninject: local-storage.md\ndigest: ledger.md\n")
        with open(os.path.join(store, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
            for msg in ("go", "go", "y", "land it", "verify it", "fix this and re-emit the whole plan as one fence"):
                f.write(f'\n- fingerprint: "{msg}"\n  time: 2026-09-03 10:10\n  arrival: turn\n  state: FRESH\n')
        out = run_hook("session-open", {"source": "startup", "session_id": "voice-session"}, root)
        assert "### owner voice" in out, f"no owner-voice block:\n{out}"
        block = out.split("### owner voice", 1)[1].split("### phi.py check", 1)[0]
        assert len(block) <= 1300, f"voice block over the cap: {len(block)}"
        assert '"go" ×3' in block, block   # two dispatch fingerprints plus one local-storage owner-words
        assert "form=fence" in block, block
        assert "median message length" in block, block
        held = run_hook("session-open", {"source": "resume", "session_id": "voice-session"}, root)
        assert "### owner voice" not in held, "voice block printed on a held source"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("owner voice: green")


def test_conductor_owed():
    """The Stop hook's one block: with operator-via set and no pool of this session's own, the first stop is blocked
    with the conductor launch spelled out; the next stop passes, as does a stop the hook already continued; a session
    whose pool is built, and a config with no conductor, are never blocked."""
    root, store = seed_project("owed-session")
    try:
        vindex = os.path.join(root, ".claude", "p4", "vindex")
        os.makedirs(vindex)
        with open(os.path.join(vindex, "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\n## recall\n\noperator-via: mister:roboto\n")
        out = run_hook("turn-close", {"cwd": root, "stop_hook_active": True}, root)
        assert '"decision": "block"' not in out, f"(a) a continued stop was blocked:\n{out}"
        out = run_hook("turn-close", {"cwd": root}, root)
        d = json.loads(next(l for l in out.splitlines() if l.startswith("{")))
        assert d["decision"] == "block" and "subagent_type mister:roboto" in d["reason"] \
            and "conductor: launch the operator" in d["reason"] and "operator-prompt.md" in d["reason"], d
        out = run_hook("turn-close", {"cwd": root}, root)
        assert '"decision": "block"' not in out, f"(b) the second stop was blocked:\n{out}"
        root2, store2 = seed_project("pooled-session")
        try:
            os.makedirs(os.path.join(root2, ".claude", "p4", "vindex"))
            shutil.copy(os.path.join(vindex, "phi-index.md"), os.path.join(root2, ".claude", "p4", "vindex", "phi-index.md"))
            with open(os.path.join(store2, "recall-pool.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write("# VLDS Recall Pool\n\nsession: pooled-s\n")
            out = run_hook("turn-close", {"cwd": root2}, root2)
            assert '"decision": "block"' not in out, f"(c) a pooled session was blocked:\n{out}"
        finally:
            shutil.rmtree(root2, ignore_errors=True)
        root3, _store3 = seed_project("plain-session")
        try:
            out = run_hook("turn-close", {"cwd": root3}, root3)
            assert '"decision": "block"' not in out, f"(d) a config with no conductor was blocked:\n{out}"
        finally:
            shutil.rmtree(root3, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("conductor owed: green")


def test_cross_session_reads():
    """The p4 layout's reads: a ruling one session recorded is a standing rule in another session's start and its
    barrier; another session's inferences and dispatch rows never reach this one; the barrier's virtual lines map back
    to the session that holds each entry; the cumulative index lists every session store."""
    root, first = seed_project("first-session")
    try:
        second = store_of(root, "second-session")
        os.makedirs(second)
        shutil.copy(SEED, os.path.join(second, "dispatch.md"))
        with open(os.path.join(second, "local-storage.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(LOCAL_STORAGE.replace('"go"', '"the second session ruled this"'))
        with open(os.path.join(first, "virtual.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(VIRTUAL_HEADER + "\n- inference: the first session's own inference\n  time: 2026-09-03 10:30\n"
                    "  basis: a reading\n  minted: session first-se, turn 1\n  disposition: pending\n")
        out = run_hook("session-open", {"source": "resume", "session_id": "second-session", "_keep_sid": True}, root)
        assert "local-storage.md — 4 entries across 2 sessions" in out, f"(a) the rulings not read across sessions:\n{out}"
        assert "virtual.md — absent" in out, f"(a) another session's inferences reached this one:\n{out}"
        r = subprocess.run([sys.executable, PHI, "--store", second, "barrier", "--session", "second-se"],
                           capture_output=True, timeout=60)
        bar = r.stdout.decode("utf-8", "replace")
        assert "the second session ruled this" in bar and '"go"' in bar, f"(b) the barrier lacks a session's ruling:\n{bar}"
        assert "first session's own inference" not in bar, f"(b) another session's inference in the barrier:\n{bar}"
        assert "sessions (virtual lines → session directory): local-storage.md 1-" in bar, f"(b) no session map:\n{bar}"
        run_hook("turn-close", {"session_id": "second-session", "cwd": root, "_keep_sid": True}, root)
        with open(os.path.join(root, ".claude", "p4", "vindex", "sessions.tsv"), encoding="utf-8") as f:
            listed = f.read()
        assert "first-se\t" in listed and "second-s\t" in listed, f"(c) vindex lacks a session:\n{listed}"
        # (d) the close writes into a file the new session store lacks: created from another session's header
        rec = os.path.join(root, "rec.md")
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            f.write("## ledger.md\n- correction: a lesson in a new store\n  time: 2026-09-03 10:00\n  match: a\n"
                    "  meant: b\n")
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", second, "--session",
                            "second-session", "--now", "2026-09-03 10:00", "--record", rec], capture_output=True,
                           timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert "written: ledger.md" in out and "refused: nothing" in out, f"(d) the record refused:\n{out}"
        with open(os.path.join(second, "ledger.md"), encoding="utf-8") as f:
            text = f.read()
        assert text.startswith(LEDGER_HEADER.split("\n")[0]) and "a lesson in a new store" in text, text[:300]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("cross-session reads: green")


def test_session_title():
    root, store = seed_project("first-session")
    seed_register(store)    # the φ road names its stage: a store with no index now starts on the keyspace (test_idb.py)
    try:
        # (a) the chat title comes from the transcript's LAST custom-title record and names the session, beside
        # its short id, in the prompt hook's header and in the stamp; (b) the session's own .sessions carries it
        transcript = os.path.join(root, "first.jsonl")
        with open(transcript, "w", encoding="utf-8", newline="\n") as f:
            f.write('{"type":"custom-title","customTitle":"Old name","sessionId":"first-session"}\n'
                    '{"type":"user","message":"a line that is not a title"}\n'
                    '{"type":"custom-title","customTitle":"First  session:  the real title","sessionId":"first-session"}\n')
        out = run_hook("prompt-open", {"session_id": "first-session", "prompt": "hello", "transcript_path": transcript}, root)
        assert 'session first-se "First session: the real title"' in out, f"(a) id + title not in the prompt-hook header:\n{out}"
        # (a2) the session directory is named by that first title, once, and the stamp lands in the named store
        store = store_of(root, "first-session")
        assert os.path.basename(os.path.dirname(store)) == "first-session-the-real-title--first-se", store
        assert "session directory named by its first title" in out, f"(a2) the rename not announced:\n{out}"
        with open(transcript, "a", encoding="utf-8", newline="\n") as f:
            f.write('{"type":"custom-title","customTitle":"A later name","sessionId":"first-session"}\n')
        run_hook("prompt-open", {"session_id": "first-session", "prompt": "again", "transcript_path": transcript}, root)
        assert store_of(root, "first-session") == store, "(a2) a later title renamed the directory"
        with open(os.path.join(store, "dispatch.md"), encoding="utf-8") as f:
            assert 'session first-se "First session: the real title"' in f.read(), "(a) id + title not in the stamp"
        with open(os.path.join(store, ".sessions"), encoding="utf-8") as f:
            ledger = f.read()
        assert ledger.strip().endswith("A later name"), f"(b) .sessions lacks the latest title: {ledger}"
        # (c) a second session writes its own store — seeded, stamped there, named by its short id alone — and
        # nothing is poured or dated anywhere: the first session's record stays whole in its own directory
        first_rows = open(os.path.join(store, "dispatch.md"), encoding="utf-8").read()
        out = run_hook("prompt-open", {"session_id": "second-session", "prompt": "hi", "_keep_sid": True}, root)
        assert "session second-s" in out and '"' not in out.split("\n")[0], f"(c) short id alone expected:\n{out}"
        second = store_of(root, "second-session")
        assert '- fingerprint: "hi"' in open(os.path.join(second, "dispatch.md"), encoding="utf-8").read(), \
            "(c) the second session's row not in its own store"
        assert open(os.path.join(store, "dispatch.md"), encoding="utf-8").read() == first_rows, \
            "(c) the first session's record changed"
        for d in (store, second):
            assert not os.path.isdir(os.path.join(d, "idb", "blobs", "dispatch")), f"(c) a dated pour in {d}"
            arc = os.path.join(d, "arc")
            assert not (os.path.isdir(arc) and [f for f in os.listdir(arc) if f.startswith("dispatch-")]), \
                f"(c) a dated pour in {arc}"
        # (e) the transcript lags (no title record yet) but the session's .sessions already holds its title — the
        # ledger's title is used; (f) with neither, the prompt hook says so
        empty = os.path.join(root, "empty.jsonl")
        with open(empty, "w", encoding="utf-8", newline="\n") as f:
            f.write('{"type":"mode","mode":"normal","sessionId":"third-session"}\n')
        third = store_of(root, "third-session")
        os.makedirs(third)
        with open(os.path.join(third, ".sessions"), "a", encoding="utf-8", newline="\n") as f:
            f.write("third-session 2026-09-03 20:00 Ledger title\n")
        out = run_hook("prompt-open", {"session_id": "third-session", "prompt": "hey", "transcript_path": empty,
                                       "_keep_sid": True}, root)
        assert 'session third-se "Ledger title"' in out, f"(e) the ledger's title not used when the transcript lags:\n{out}"
        assert "title: none yet" not in out, "(e) the none-yet line printed although the ledger had a title"
        out = run_hook("prompt-open", {"session_id": "fourth-session", "prompt": "yo", "transcript_path": empty,
                                       "_keep_sid": True}, root)
        assert "session fourth-s" in out and "title: none yet" in out, f"(f) the none-yet line missing:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("session title: green")


INDEX_HEAD = """# VLDS φ-Register — Index

Derived — recomputable; an edit to this file is a ruling.

register: 0

## positions

| pos | weight-kb | segment | bytes | pours | span | attached |
| --- | --- | --- | --- | --- | --- | --- |

## hot

| file | live | at-sweep | bytes | budget | watermark | pressure |
| --- | --- | --- | --- | --- | --- | --- |
| local-storage.md | 2 | 2 | 100 | 21 | — | ok |
| logger.md | 0 | 0 | 0 | 34 | — | ok |
| virtual.md | 0 | 0 | 0 | 13 | — | ok |

## recall

inject: local-storage.md
digest: logger.md
index-engine: phi
{recall}
## epochs

| file | k | a | b |
| --- | --- | --- | --- |

updated: 2026-09-03 10:00 by seed
"""

LOGGER_HEADER = "# VLDS Looper — Logger\n\nTagged entries.\n\n---\n"
VIRTUAL_HEADER = """# VLDS Partition — Virtual

Load-bearing inferences minted this turn.

```yaml
- inference: [the inference]
  time: [YYYY-MM-DD HH:MM]
  basis: [what it was inferred from]
  minted: [session + turn]
  disposition: pending | promoted -> <file> | expired
```

---
"""


def seed_register(store, recall="", logger_entries=0, virtual=()):
    """A bootstrapped-but-empty register plus a logger and a virtual file — what the light sweep reads."""
    with open(os.path.join(store, "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(INDEX_HEAD.replace("{recall}", recall))
    with open(os.path.join(store, "logger.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LOGGER_HEADER)
        for i in range(logger_entries):
            f.write(f"\n- `[gc]` 2026-09-03 {10 + i // 60:02d}:{i % 60:02d} — **Entry {i + 1}.** A logged decision, number {i + 1}.\n")
    with open(os.path.join(store, "virtual.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(VIRTUAL_HEADER)
        for sid, txt in virtual:
            f.write(f"\n- inference: {txt}\n  time: 2026-09-03 10:30\n  basis: a reading\n  minted: session {sid}, turn 1\n  disposition: pending\n")
    os.makedirs(os.path.join(store, "arc"), exist_ok=True)


def count_entries(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    return sum(1 for l in lines[lines.index("---") + 1:] if l.startswith("- "))


def test_pool_mode():
    root, store = seed_project("pool-session")
    try:
        seed_register(store)
        # (a) the default is the pooled mode: the directive, no hot-file text, silent slots
        out = run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root)
        assert "the operator subagent, never this context" in out, f"(a) no operator directive:\n{out}"
        assert "operator-prompt.md" in out and "pool-prompt.md" in out and "record.py" in out, \
            f"(a) a brief or the record script missing:\n{out}"
        assert "by the index's road, children (skeleton:" in out and "one judged pass on sonnet" in out \
            and "one reader per file on haiku" in out and "on sonnet)" in out and "at most 4 continuations" in out, \
            f"(a) the per-moment models, the road, or the continuation bound missing:\n{out}"
        assert "Launch it once" in out and "SendMessage" in out, f"(a) the one-per-session continuation missing:\n{out}"
        assert "CONDUCTED" not in out and "; via " not in out, f"(a) a conductor named with no operator-via set:\n{out}"
        assert "`operator-via:` an agent that conducts the operator" in out, f"(a) the operator-via key unlisted:\n{out}"
        assert "pool: subagent (operator sonnet, pool sonnet, children haiku, sweep sonnet; road children; 4 continuations)" \
            in out, f"(a) the mode line missing:\n{out}"
        assert "the plan goes in the reply" not in out, "(a) a hot-file entry was injected in the pooled mode"
        assert "register: 0" in out and "hot (live/budget)" in out, f"(a) the index digest missing:\n{out}"
        assert "### owner voice" in out, "(a) the owner voice missing in the pooled mode"
        assert run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root) and \
            run_hook_slot(0, root).strip() == "", "(a) slot 0 printed in the pooled mode"
        # (b) the first prompt carries the nudge; the second does not
        out = run_hook("prompt-open", {"session_id": "pool-session", "prompt": "hello"}, root)
        assert "not yet pooled" in out, f"(b) no nudge on the first prompt:\n{out}"
        out = run_hook("prompt-open", {"session_id": "pool-session", "prompt": "again"}, root)
        assert "not yet pooled" not in out, f"(b) nudge repeated on the second prompt:\n{out}"
        # (c) a compact re-injects this session's pool, and names another session's as not this one's
        with open(os.path.join(store, "recall-pool.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# VLDS Recall Pool\n\nsession: pool-ses \"A title\"\ntask: test the pool\npooled: 2026-09-03 10:00\n\n## steering\n\n- [local-storage 2026-09-03 10:00 LIVE] the plan goes in the reply as one fence\n")
        out = run_hook("session-open", {"source": "compact", "session_id": "pool-session"}, root)
        assert "re-injected after the compact" in out and "task: test the pool" in out, f"(c) pool not re-injected:\n{out}"
        out = run_hook("session-open", {"source": "compact", "session_id": "other-session", "_keep_sid": True}, root)
        assert "task: test the pool" not in out, f"(c) another session's pool re-injected:\n{out}"
        out = run_hook("session-open", {"source": "resume", "session_id": "pool-session"}, root)
        assert "re-injected" not in out, "(c) a resume re-injected the pool"
        # (d) `pool: inject` restores the slot injection; `operator-model:` (or the older `pool-model:`) picks the model
        seed_register(store, recall="pool: inject\n")
        out = run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root)
        assert "### inject —" in out and "the operator subagent" not in out, f"(d) inject mode not restored:\n{out}"
        assert "the plan goes in the reply" in run_hook_slot(0, root), "(d) slot 0 silent in the inject mode"
        seed_register(store, recall="operator-model: opus\npool-model: haiku\npool-child-model: sonnet\nsweep-model: opus\n"
                                    "pool-road: skeleton\noperator-moments: 2\n")
        out = run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root)
        assert "by the index's road, skeleton (skeleton:" in out and "one judged pass on haiku" in out \
            and "one reader per file on sonnet" in out and "on opus)" in out and "at most 2 continuations" in out, \
            f"(d) the model keys, the road, or the continuation bound not honoured:\n{out}"
        assert "operator opus, pool haiku, children sonnet, sweep opus; road skeleton; 2 continuations" in out, \
            f"(d) the mode line lacks the models or the road:\n{out}"
        # (e) `operator-via:` hands every operator moment to a conducting agent, named in the directive and the mode line
        seed_register(store, recall="operator-via: mister:roboto\n")
        out = run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root)
        assert "CONDUCTED — the index's `operator-via:` names mister:roboto" in out \
            and "subagent_type mister:roboto, in the foreground" in out and "DERIVED UNDERSTANDING" in out \
            and "the response stays yours" in out and "launch the operator directly and say so" in out, \
            f"(e) the conducted hand-off missing:\n{out}"
        assert "road children; 4 continuations; via mister:roboto)" in out, f"(e) the mode line lacks the conductor:\n{out}"
        seed_register(store, recall="operator-via:\n")
        out = run_hook("session-open", {"source": "startup", "session_id": "pool-session"}, root)
        assert "CONDUCTED" not in out, f"(e) an empty operator-via still named a conductor:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pool mode: green")


def run_hook_slot(slot, root):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
    payload = {"source": "startup", "session_id": CURRENT_SID[0]}
    r = subprocess.run([sys.executable, HOOKS, "session-open", "--slot", str(slot)],
                       input=json.dumps(payload).encode("utf-8"), capture_output=True, env=env, timeout=60)
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def test_turn_close():
    root, store = seed_project()
    try:
        seed_register(store, logger_entries=40, virtual=[("other-session", "an inference another session minted"),
                                                          ("test-session", "an inference this session minted")])
        arc = os.path.join(store, "arc")
        with open(os.path.join(arc, "dispatch-20260903-100000-other-se.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# VLDS Partition — Dispatch\n\n---\n\n- fingerprint: \"hello\"\n  time: 2026-09-03 10:00\n  arrival: turn\n")
        # (a) the Stop hook: the logger past its budget pours its oldest down to the low-water mark, the other
        # session's virtual entry expires and pours with them, the record attaches to the child — one child,
        # register 100000 = Zeckendorf(13): 12 logger + 1 virtual (15, 14, 13 would open two positions)
        out = run_hook("turn-close", {"session_id": "test-session", "cwd": root}, root)
        assert out.startswith("turn-close: poured 13 (1 virtual.md, 12 logger.md) into arc-6-a.md"), f"(a) report:\n{out}"
        assert "attached dispatch-20260903-100000-other-se.md to arc-6-a.md" in out, f"(a) the record not attached:\n{out}"
        assert count_entries(os.path.join(store, "logger.md")) == 29, "(a) logger: 40 - 12 poured + the sweep's own entry"
        assert count_entries(os.path.join(store, "virtual.md")) == 1, "(a) this session's virtual entry was poured"
        with open(os.path.join(store, "virtual.md"), encoding="utf-8") as f:
            assert "other session" not in f.read(), "(a) the other session's entry still hot"
        with open(os.path.join(arc, "arc-6-a.md"), encoding="utf-8") as f:
            seg = f.read()
        assert "disposition: expired (turn close" in seg and "Entry 1." in seg and "Entry 12." in seg and "Entry 13." not in seg, \
            "(a) the child holds the wrong entries"
        assert "attached: dispatch-20260903-100000-other-se.md" in seg and "verified: " in seg, "(a) child header incomplete"
        check = run_check(store)
        assert "0 corruption, 0 debt" in check, f"(a) check after the sweep:\n{check}"
        with open(os.path.join(store, "phi-index.md"), encoding="utf-8") as f:
            index = f.read()
        assert "register: 100000" in index and "| logger.md | 29 | 29 |" in index and "| logger.md | 1 | 2 | 3 |" in index, \
            f"(a) index not rewritten:\n{index}"
        assert "inject: local-storage.md" in index, "(a) the recall section was lost in the rewrite"
        # (b) the next prompt prints the report and takes it; a second Stop with nothing to move is silent
        out = run_hook("prompt-open", {"session_id": "test-session", "prompt": "next"}, root)
        assert "- turn-close (" in out and "poured 13" in out, f"(b) report not printed at the next prompt:\n{out}"
        assert not os.path.getsize(os.path.join(store, ".turn-close")), "(b) the report was not taken"
        out = run_hook("turn-close", {"session_id": "test-session", "cwd": root}, root)
        assert out.strip() == "", f"(b) a Stop with nothing to move printed:\n{out}"
        # (c) another session's Stop runs on its own store and touches nothing in this one: this session's entry
        # stays hot, and the cumulative index lists both session stores
        run_hook("turn-close", {"session_id": "third-session", "cwd": root, "_keep_sid": True}, root)
        assert count_entries(os.path.join(store, "virtual.md")) == 1, "(c) another session's Stop reached this store"
        with open(os.path.join(root, ".claude", "p4", "vindex", "sessions.tsv"), encoding="utf-8") as f:
            listed = f.read()
        assert "test-ses\t" in listed, f"(c) vindex lacks this session:\n{listed}"
        # (d) a fresh lock held by another session skips the sweep and says so
        seed_register(store, logger_entries=40)
        with open(os.path.join(arc, ".sweep-lock"), "w", encoding="utf-8", newline="\n") as f:
            f.write("holder-session 2026-09-03 10:00:00\n")
        out = run_hook("turn-close", {"session_id": "test-session", "cwd": root}, root)
        assert "skipped" in out and "holder-session" in out, f"(d) lock not honoured:\n{out}"
        assert count_entries(os.path.join(store, "logger.md")) == 40, "(d) the sweep ran under another session's lock"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("turn-close: green")


def test_barrier():
    root, store = seed_project()
    dispatch = os.path.join(store, "dispatch.md")
    try:
        # (a) a first message resembles no row: FRESH written by the hook, addressed left to the operator
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": "run the acceptance tests again"}, root)
        assert "no earlier row resembles it" in out and "state: FRESH written" in out, f"(a) barrier line:\n{out}"
        with open(dispatch, encoding="utf-8") as f:
            assert f.read().count("  state: FRESH\n") == 1, "(a) FRESH not written into the row"   # the header's shape line reads 'FRESH | ECHO …'
        # (b) a near-repeat: the candidate is named, state left open for the operator
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": "run the acceptance tests again please"}, root)
        assert "resembles 1 earlier row" in out and "state: left open" in out, f"(b) candidate not named:\n{out}"
        with open(dispatch, encoding="utf-8") as f:
            assert f.read().count("  state: FRESH\n") == 1, "(b) FRESH written despite a candidate"
        # (c) a short, unknown message: FRESH, called short and unknown; the identical short message next is a
        # candidate (seen once — not yet a known command); by its third arrival it is a known command: no
        # candidate, FRESH written, the derivation printed from the last row that carried it
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": "ship"}, root)
        assert "short message (1 word), not a known command" in out and "no earlier row resembles it" in out, f"(c) short line:\n{out}"
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": "ship"}, root)
        assert "resembles 1 earlier row" in out and 'latest: "ship"' in out, f"(c) identical short message not a candidate:\n{out}"
        with open(dispatch, "a", encoding="utf-8", newline="\n") as f:
            f.write("  state: FRESH\n  addressed: shipped the build to staging\n")
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": "ship"}, root)
        assert 'short message, known: "ship" ×2' in out and "shipped the build to staging" in out, f"(c) known command not derived:\n{out}"
        assert "state: FRESH written" in out and "state: left open" not in out, \
            f"(c) a known command was treated as a candidate:\n{out}"
        with open(dispatch, encoding="utf-8") as f:
            assert f.read().count("  state: FRESH\n") == 4, "(c) FRESH not written for the known command"   # rows a, c1, the manual c2 completion, c3
        # (d) a task notification is stamped complete on arrival — no barrier, no short line, nothing for the operator
        note = "<task-notification> <task-id>abc</task-id> <status>completed</status> <result>done</result> </task-notification>"
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": note}, root)
        assert "a task notification: its row is complete on arrival" in out, f"(d) notification line missing:\n{out}"
        assert "barrier:" not in out and "short message" not in out, f"(d) barrier or short line printed for a notification:\n{out}"
        with open(dispatch, encoding="utf-8") as f:
            text = f.read()
        assert "  arrival: task notification (stamped" in text and "  addressed: a task notification" in text, \
            "(d) the notification's row not stamped complete"
        # (e) a message from the session's own agent — the operator's stream line — is stamped complete the same way
        msg = "<agent-message from=\"a567fef5349c11851\"> pool stream: index.md — 4 picks; 2 of 9 in </agent-message>"
        out = run_hook("prompt-open", {"session_id": "barrier-session", "prompt": msg}, root)
        assert "an agent message: its row is complete on arrival" in out, f"(e) agent-message line missing:\n{out}"
        assert "barrier:" not in out and "short message" not in out, f"(e) barrier or short line printed for an agent message:\n{out}"
        with open(dispatch, encoding="utf-8") as f:
            text = f.read()
        assert "  arrival: agent message (stamped" in text and "  addressed: an agent's message" in text, \
            "(e) the agent message's row not stamped complete"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("barrier: green")


RECORD = """# the turn's record

## dispatch.md
- fingerprint: "run the acceptance tests"
  state: FRESH
  addressed: run, nine groups green

## local-storage.md
- ruling: "the record script closes the turn"
  time: 2026-09-03 10:20
  owner-words: "close it by script"
  scope: durable
  status: LIVE

## local-storage.md
- ruling: "go"
  status: FREED

## logger.md
- `[gc]` 2026-09-03 10:20 — **The record script's first close.** Applied by the test.

## ledger.md
- correction: (a + b)
  time: 2026-09-03 10:2x
  match: x
  meant: y
  delta: z

## ledger.md
- key: (c + d)
  event: surfaced
  outcome: done. 2026-09-03 10:20
  verdict: not a field

## data-store.md
- claim: "nothing"
  time: 2026-09-03 10:20
"""


def test_record():
    root, store = seed_project()
    try:
        with open(os.path.join(store, "logger.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(LOGGER_HEADER)
        run_hook("prompt-open", {"session_id": "record-session", "prompt": "run the acceptance tests"}, root)
        rec = os.path.join(root, "record.md")
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            f.write(RECORD)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", store, "--session", "record-session",
                            "--now", "2026-09-03 10:21", "--record", rec], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert out.startswith("derivation — close, session record-s, 2026-09-03 10:21 (mechanical: scripts/record.py)"), out
        # appended: the ruling and the logger line; updated: the SPENT 'go' ruling's status and the dispatch row
        assert 'local-storage.md — - ruling: "the record script closes the turn" — 2026-09-03 10:20' in out, out
        assert "logger.md — - `[gc]` 2026-09-03 10:20" in out, out
        assert 'local-storage.md — - ruling: "go" — status' in out, f"upsert by head did not update the 'go' ruling:\n{out}"
        assert 'dispatch.md — - fingerprint: "run the acceptance tests" — state, addressed' in out, out
        # refused: the placeholder time, the field outside the ledger's shape, the file with no header shape match
        assert "placeholder time `2026-09-03 10:2x`" in out, out
        assert "not in the header shape:" in out and "verdict" in out, out   # the seed's ledger header declares the correction shape only
        assert "data-store.md — - claim" in out and "file absent" in out, out
        assert r.returncode == 1, "refusals must exit 1"
        with open(os.path.join(store, "local-storage.md"), encoding="utf-8") as f:
            ls = f.read()
        assert ls.count("- ruling:") == 4 and "  status: FREED" in ls and "  status: SPENT" not in ls, ls[-600:]
        with open(os.path.join(store, "dispatch.md"), encoding="utf-8") as f:
            d = f.read()
        assert "  addressed: run, nine groups green" in d and d.count("  state: FRESH\n") == 1, d[-400:]
        with open(os.path.join(store, "ledger.md"), encoding="utf-8") as f:
            assert "- correction:" not in f.read().split("---", 1)[1], "a refused block was written"
        assert "check: " in out and "phi.py check:" in out, out
        # a dry run writes nothing
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", store, "--session", "record-session",
                            "--now", "2026-09-03 10:21", "--record", rec, "--dry"], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        assert "dry run — nothing written" in out, out
        with open(os.path.join(store, "local-storage.md"), encoding="utf-8") as f:
            assert f.read().count("- ruling:") == 4, "the dry run wrote"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("record: green")


def test_record_seeds_session_local():
    # a session-local file (virtual.md) is read from this store alone, so the record script seeds its header from
    # another session's copy under the layout; before that, the block was refused "file absent" in every new store
    root, store = seed_project()
    try:
        peer = store_of(root, "peer-session")
        os.makedirs(peer)
        with open(os.path.join(peer, "virtual.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(VIRTUAL_HEADER + "\n- inference: the peer's own\n  time: 2026-09-03 10:00\n  basis: the peer\n"
                    "  minted: peer-session turn 1\n  disposition: pending\n")
        rec = os.path.join(root, "record.md")
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            f.write("# the turn's record\n\n## virtual.md\n- inference: seeded from the peer's header\n"
                    "  time: 2026-09-03 10:20\n  basis: the test\n  minted: test-session turn 1\n  disposition: pending\n")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", store, "--session", "test-session",
                            "--now", "2026-09-03 10:21", "--record", rec], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert "virtual.md — - inference: seeded from the peer's header" in out and "file absent" not in out, out
        with open(os.path.join(store, "virtual.md"), encoding="utf-8") as f:
            v = f.read()
        assert v.startswith("# VLDS Partition — Virtual"), v[:80]
        assert "- inference: seeded from the peer's header" in v and "the peer's own" not in v, v
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("record seeds session-local: green")


def test_pour():
    root, store = seed_project()
    try:
        seed_register(store, logger_entries=10)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        norm = os.path.join(HERE, "normalize.py")
        # (a) 4 pours from an empty register: Zeckendorf(4) = [3, 1] opens two positions — refused, the counts
        # that open one named; (b) 3 pours → position 3, accepted and run; (c) a wrong head line is refused
        base = [sys.executable, norm, "--store", store, "--session", "pour-session", "--now", "2026-09-03 10:30"]
        r = subprocess.run(base + ["--pour", "logger.md:7,9,11,13", "--dry"], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        assert "would open 2 positions" in out and "counts that open exactly one: [1, 2, 3, 5, 8" in out, out
        r = subprocess.run(base + ["--pour", "logger.md:7,9,11"], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        assert "sweep: poured 3 (3 logger.md) into arc-3-a.md" in out and "register 100" in out, out
        assert count_entries(os.path.join(store, "logger.md")) == 8, "7 left + the sweep's own entry"
        assert "0 corruption, 0 debt" in run_check(store), run_check(store)
        with open(os.path.join(arc_path := os.path.join(store, "arc"), "arc-3-a.md"), encoding="utf-8") as f:
            seg = f.read()
        assert "Entry 1." in seg and "Entry 2." in seg and "Entry 3." in seg and "Entry 4." not in seg, seg
        r = subprocess.run(base + ["--pour", "logger.md:8", "--dry"], capture_output=True, env=env, timeout=120)
        out = r.stdout.decode("utf-8", "replace")
        assert "line 8 is not an entry head" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pour: green")


def test_check_delta():
    root, store = seed_project()
    try:
        payload = bash('cat >> .claude/p4/sessions/test-ses/vlds/ledger.md <<\'EOF\'\n- correction: x\n  time: 2026-09-02 11:27\nEOF\n', root)
        payload["session_id"] = "delta-session"
        first = decision(run_hook("post-write", payload, root))["additionalContext"]
        second = decision(run_hook("post-write", payload, root))["additionalContext"]
        assert "unchanged since the last check" not in first, first
        assert "unchanged since the last check" in second and "phi.py check:" in second, second
        payload["session_id"] = "another-session"
        payload["_keep_sid"] = True
        third = decision(run_hook("post-write", payload, root))["additionalContext"]
        assert "unchanged" not in third, "(delta) another session's first check came back short"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("check delta: green")


def _transcript(root, records):
    path = os.path.join(root, "transcript.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def _asst(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


WIDGET_USE = {"type": "tool_use", "name": "mcp__visualize__show_widget",
              "input": {"title": "release_acts_picker", "widget_code": "<form class=\"elicit\"></form>"}}
PANEL_USE = {"type": "tool_use", "name": "AskUserQuestion",
             "input": {"questions": [{"header": "Road", "question": "Which road?", "options": []}]}}
BASH_USE = {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}
BRIEFS_SEED = os.path.join(PLUGIN, "hooks", "briefs-seed.md")


def _prompt(root, text, transcript):
    return {"session_id": "detail-test", "cwd": root, "prompt": text, "transcript_path": transcript}


def test_detail_ask():
    """The recorder: a question right after a served picker is stamped kind: detail-ask / on: <picker>; the
    shell's submit and skip are not; a submit whose textbox carries a question is submit+detail-ask; a later
    tool call or a later prompt means the picker was not the turn's close; a picker's submit resembling an
    addressed row is FRESH by construction; an old dispatch header gains kind:/on: once."""
    root, store = seed_project()
    try:
        dispatch = os.path.join(store, "dispatch.md")
        # an old header, written before the recorder existed: the hook adds the two fields once
        with open(dispatch, encoding="utf-8") as f:
            old = "\n".join(l for l in f.read().split("\n") if not l.startswith("  kind:") and not l.startswith("  on:"))
        with open(dispatch, "w", encoding="utf-8", newline="\n") as f:
            f.write(old)
        t = _transcript(root, [_user("fix the widget"), _asst({"type": "text", "text": "done"}, WIDGET_USE),
                               _asst({"type": "text", "text": "the picker carries the acts"})])
        out = run_hook("prompt-open", _prompt(root, "what are the diffs of each selection?", t), root)
        assert "detail-ask on widget «release_acts_picker»" in out, out
        assert "header: `kind:` and `on:` added" in out, out
        rows = open(dispatch, encoding="utf-8").read()
        assert "  kind: detail-ask\n" in rows.replace("\r\n", "\n") and "  on: widget «release_acts_picker»" in rows, rows[-600:]
        assert "  kind: [detail-ask" in rows.split("---")[0], "(detail-ask) the header did not gain the fields"
        out2 = run_hook("prompt-open", _prompt(root, "and the second question?", t), root)
        assert "header:" not in out2, "(detail-ask) the header migration ran twice"
        # the shell's submit line and its skip are not detail-asks
        out = run_hook("prompt-open", _prompt(root, "Release acts details — Acts: Commit, Push", t), root)
        assert "detail-ask" not in out, out
        out = run_hook("prompt-open", _prompt(root, "(Skipped the form — proceed with defaults or ask me in plain text)", t), root)
        assert "detail-ask" not in out, out
        # a question riding in a submitted textbox
        out = run_hook("prompt-open", _prompt(root, "Release acts details — Acts: Commit · Notes: why is push separate?", t), root)
        assert "detail-ask on widget «Release acts»" in out and "riding on the submit" in out, out
        assert "  kind: submit+detail-ask" in open(dispatch, encoding="utf-8").read(), "(detail-ask) submit+detail-ask not stamped"
        # a later tool call: the picker was not the turn's close
        t2 = _transcript(root, [_user("fix it"), _asst(WIDGET_USE), _asst(BASH_USE), _asst({"type": "text", "text": "ok"})])
        out = run_hook("prompt-open", _prompt(root, "what about the diffs?", t2), root)
        assert "detail-ask" not in out, out
        # a later prompt: the picker belongs to an earlier turn
        t3 = _transcript(root, [_user("fix it"), _asst(WIDGET_USE), _user("thanks"), _asst({"type": "text", "text": "welcome"})])
        out = run_hook("prompt-open", _prompt(root, "what about the diffs?", t3), root)
        assert "detail-ask" not in out, out
        # the native panel as the turn's last act
        t4 = _transcript(root, [_user("fix it"), _asst(PANEL_USE)])
        out = run_hook("prompt-open", _prompt(root, "what do the roads cost?", t4), root)
        assert "detail-ask on panel «Road»" in out, out
        # a picker's submit resembling an ADDRESSED row is FRESH by construction; resembling an OPEN one is this context's call
        with open(dispatch, "a", encoding="utf-8", newline="\n") as f:
            f.write('\n- fingerprint: "Acts details — Acts: All of the above"\n  time: 2026-09-22 05:08\n  arrival: turn\n'
                    "  state: FRESH\n  addressed: both acts done\n")
        out = run_hook("prompt-open", _prompt(root, "Acts details — Acts: All of the above", t), root)
        assert "FRESH by construction" in out and "state: FRESH written" in out and "hand the message to the operator" not in out, out
        with open(dispatch, "a", encoding="utf-8", newline="\n") as f:
            f.write('\n- fingerprint: "Acts details — Acts: Other"\n  time: 2026-09-22 05:09\n  arrival: turn\n')
        out = run_hook("prompt-open", _prompt(root, "Acts details — Acts: Other", t), root)
        assert "judged HERE" in out and "never by the operator" in out, out
        # a plain resembling message still goes to the operator
        with open(dispatch, "a", encoding="utf-8", newline="\n") as f:
            f.write('\n- fingerprint: "please rebuild the whole tree now"\n  time: 2026-09-22 05:10\n  arrival: turn\n  state: FRESH\n  addressed: rebuilt\n')
        out = run_hook("prompt-open", _prompt(root, "please rebuild the whole tree now", t), root)
        assert "hand the message to the operator" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("detail-ask recorder: green")


def test_record_truncated_head():
    """A record block that gives a long message whole completes the row the hook stamped with a fingerprint capped
    at 200 characters and closed with `…` — never a second row beside it."""
    root, store = seed_project()
    try:
        long_prompt = ("Barrier ruling and next build details — Barrier: Main context judges a fresh picker's submit "
                       "(recommended) · Acts: Start the 0.0.36 AI-note-triggers build · Notes: i thought this was just "
                       "worked on and finalized? - what changed?")
        assert len(long_prompt) > 200
        run_hook("prompt-open", {"session_id": "trunc", "cwd": root, "prompt": long_prompt}, root)
        dispatch = open(os.path.join(store, "dispatch.md"), encoding="utf-8").read()
        assert "…\"" in dispatch and long_prompt not in dispatch, "(truncated head) the hook did not cap the fingerprint"
        rec = os.path.join(root, "rec.md")
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            f.write(f'## dispatch.md\n- fingerprint: "{long_prompt}"\n  addressed: answered whole\n')
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", store, "--session", "trunc",
                            "--now", now, "--record", rec], capture_output=True, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert "rows: dispatch.md" in out and "written: nothing" in out, out
        dispatch = open(os.path.join(store, "dispatch.md"), encoding="utf-8").read()
        assert dispatch.count("- fingerprint: \"Barrier ruling") == 1 and "  addressed: answered whole" in dispatch, dispatch[-500:]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("record truncated head: green")


def _widget(title, briefs):
    pills = "".join(f'<button type="button" class="elicit-pill" data-value="{o}"><span>{o}</span><br>'
                    f'<span>{b}</span></button>' for o, b in briefs)
    pills += '<button type="button" class="elicit-pill" data-value="Other" data-other>Other</button>'
    return {"tool_name": "mcp__visualize__show_widget", "cwd": "", "tool_input": {"title": title, "widget_code": f'<form class="elicit"><div class="elicit-pills">{pills}</div></form>'}}


def _panel(question, options):
    return {"tool_name": "AskUserQuestion", "cwd": "",
            "tool_input": {"questions": [{"header": "Acts", "question": question,
                                          "options": [{"label": o, "description": d} for o, d in options]}]}}


def test_pre_agent():
    """The conductor gate: silent with no `operator-via:`; with one, a main-context Agent call carrying the
    operator brief to another agent type is denied once, naming the conductor, and its re-issue passes; the
    hand-off to the conductor passes with its conductor line and is denied once without it; a call inside a
    subagent and a call without the brief pass."""
    root, store = seed_project()
    try:
        brief = "Read C:/x/vlds/hooks/operator-prompt.md and do what it says. store: s | session: a | now: n | moment: open"

        def agent(kind, prompt, sub=None):
            p = {"tool_name": "Agent", "cwd": root, "tool_input": {"subagent_type": kind, "prompt": prompt}}
            if sub:
                p["agent_id"] = sub
            return run_hook("pre-agent", p, root)

        seed_register(store)
        assert agent("general-purpose", brief).strip() == "", "(pre-agent) spoke with no operator-via"
        seed_register(store, recall="operator-via: mister:roboto\n")
        d = decision(agent("general-purpose", brief))
        assert d and d["permissionDecision"] == "deny" and "mister:roboto" in d["permissionDecisionReason"], d
        assert agent("general-purpose", brief).strip() == "", "(pre-agent) the re-issue did not pass"
        conducted = brief + "\nconductor: launch the operator with this message on sonnet, and return a derived understanding"
        assert agent("mister:roboto", conducted).strip() == "", "(pre-agent) the conducted hand-off was bounced"
        assert agent("roboto", conducted + " ").strip() == "", "(pre-agent) the bare agent name was not matched"
        d = decision(agent("mister:roboto", brief + " | facts"))
        assert d and "conductor line" in d["permissionDecisionReason"], d
        assert agent("general-purpose", brief + " | inside", sub="abc123").strip() == "", "(pre-agent) spoke in a subagent"
        assert agent("general-purpose", "explore the repo").strip() == "", "(pre-agent) spoke without the brief"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pre-agent: green")


def test_pre_ask():
    """The applier: silent with no briefs.md or no standing label; a picker whose option briefs lack a standing
    label is denied once, naming the label and the options; the same picker passes on re-issue; briefs that
    carry the label pass; meta options carry no brief; the panel is checked like the widget."""
    root, store = seed_project()
    try:
        payload = _widget("release_acts", [("Commit", "one commit of the eight files"), ("Push", "main to origin")])
        payload["cwd"] = root
        assert run_hook("pre-ask", payload, root).strip() == "", "(pre-ask) spoke with no briefs.md"
        shutil.copy(BRIEFS_SEED, os.path.join(store, "briefs.md"))
        with open(os.path.join(store, "briefs.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write('\n- asked: "what are the diffs of each selection i made?"\n  time: 2026-09-22 04:46\n'
                    "  on: widget «closing_popup_fix_picker»\n  at: closing\n  omitted: diff\n")
        assert run_hook("pre-ask", payload, root).strip() == "", "(pre-ask) spoke with no standing label"
        with open(os.path.join(store, "briefs.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write('\n- asked: "show me each option\'s diff"\n  time: 2026-09-22 06:00\n  on: widget «release_acts»\n'
                    "  at: closing\n  omitted: diff\n  standing: 2026-09-22 06:05\n")
        out = run_hook("prompt-open", {"session_id": "s", "cwd": root, "prompt": "hello there friend"}, root)
        assert "standing brief lines: `diff:` (×2)" in out, out
        d = decision(run_hook("pre-ask", payload, root))
        assert d and d["permissionDecision"] == "deny", d
        assert "`diff:`" in d["permissionDecisionReason"] and "Commit lacks diff" in d["permissionDecisionReason"], d
        assert run_hook("pre-ask", payload, root).strip() == "", "(pre-ask) the same picker was bounced twice"
        good = _widget("release_acts_2", [("Commit", "diff: eight files, +78/-21"), ("Push", "diff: none, a push")])
        good["cwd"] = root
        assert run_hook("pre-ask", good, root).strip() == "", "(pre-ask) bounced a picker that carries the label"
        p = _panel("Which acts?", [("Commit", "one commit"), ("Push", "to origin")])
        p["cwd"] = root
        d = decision(run_hook("pre-ask", p, root))
        assert d and d["permissionDecision"] == "deny" and "Push lacks diff" in d["permissionDecisionReason"], d
        p2 = _panel("Which acts, with diffs?", [("Commit", "Diff: eight files"), ("Push", "diff: none")])
        p2["cwd"] = root
        assert run_hook("pre-ask", p2, root).strip() == "", "(pre-ask) bounced a panel that carries the label"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pre-ask gate: green")


def test_pool_skeleton():
    """phi.py pool prints the pool's skeleton from the barrier's rows: form and every-turn lines first under standing,
    the briefs line with its counts, live tasks and this session's inferences under open, the expired and masked
    entries under surfaced with their reasons, an empty steering section for the judged pass, the header from the
    arguments; a store too large for one line per entry is grouped by file under the cap."""
    root, store = seed_project()
    try:
        def put(name, text):
            with open(os.path.join(store, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        ls_head = "# LS\n\n```yaml\n- ruling: [x]\n  time: [t]\n  owner-words: [w]\n  status: LIVE | SPENT | FREED\n  form: [f]\n```\n\n---\n\n"
        put("local-storage.md", ls_head
            + '- ruling: "keep two forms"\n  time: 2026-09-16 10:44\n  owner-words: "keep two forms"\n  status: LIVE\n  form: picker\n\n'
            + '- ruling: "the widget stays reusable after a submit"\n  time: 2026-09-16 10:40\n  owner-words: "reopen and reuse the widget"\n  status: LIVE\n\n'
            + '- ruling: "commit only on the word"\n  time: 2026-09-03 11:00\n  owner-words: "never commit unless i say"\n  status: LIVE\n')
        put("tombstones.md", "# TS\n\n```yaml\n- freed: [x]\n  time: [t]\n  owner-words: [w]\n```\n\n---\n\n"
            '- freed: "the closing picker stays reusable after a submit"\n  time: 2026-09-16 10:50\n  cause: retraction\n'
            '  owner-words: "reopen and reuse the widget"\n')
        put("virtual.md", "# V\n\n```yaml\n- inference: [x]\n  time: [t]\n  minted: [s]\n  disposition: pending\n```\n\n---\n\n"
            '- inference: "mine"\n  time: 2026-09-22 13:36\n  basis: b\n  minted: bbcf63ab turn 1\n  disposition: pending\n\n'
            '- inference: "theirs"\n  time: 2026-09-16 19:35\n  basis: b\n  minted: session fd5d84f4 turn 3\n  disposition: pending\n')
        put("session-storage.md", "# S\n\n```yaml\n- task: [x]\n  time: [t]\n  state: [s]\n```\n\n---\n\n"
            "- task: open one\n  time: 2026-09-22 13:00\n  state: started\n\n- task: done one\n  time: 2026-09-22 13:00\n  state: completed\n")
        put("index.md", "# IX\n\n```yaml\n- key: [k]\n  decision: rule | opt-out\n  directive: [d]\n```\n\n---\n\n"
            "- key: (closing + popup)\n  decision: rule\n  directive: at every closing serve the popup, never prose\n\n"
            "- key: (edits + check)\n  decision: rule\n  directive: check the user's edits first\n")
        put("briefs.md", "# BR\n\n```yaml\n- asked: [a]\n  time: [t]\n  on: [o]\n  at: closing | fork\n  omitted: [l]\n  standing: [s]\n```\n\n---\n\n"
            '- asked: "why?"\n  time: 2026-09-22 10:00\n  on: widget «x»\n  at: closing\n  omitted: why\n\n'
            '- asked: "diff?"\n  time: 2026-09-22 10:05\n  on: widget «x»\n  at: closing\n  omitted: diff\n  standing: 2026-09-22 10:10\n')
        put("logger.md", LOGGER_HEADER + "- `[gc]` 2026-09-22 13:46 — **A sweep.** placed.\n")
        put("data-store.md", "# DS\n\n```yaml\n- claim: [c]\n  time: [t]\n  verified: [v]\n  source: [s]\n```\n\n---\n\n"
            '- claim: "nesting goes three deep"\n  time: 2026-09-22 13:36\n  verified: 2026-09-22 13:36\n  source: the docs\n\n'
            '- claim: "a bare claim"\n  time: 2026-09-22 13:40\n')
        base = [sys.executable, PHI, "--store", store, "pool", "--session", "bbcf63ab", "--title", "T", "--task", "t",
                "--now", "2026-09-22 15:30"]
        out = subprocess.run(base, capture_output=True, timeout=60).stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert out.startswith("pool-road: children; pool ") and "\n# VLDS Recall Pool" in out \
            and 'session: bbcf63ab "T"' in out and "task: t" in out and "pooled: 2026-09-22 15:30" in out, out[:400]
        out = out.split("\n", 2)[2]     # the road and summary lines, then the skeleton
        assert "(the judged pass writes this section" in out, out
        standing = out.split("## standing")[1].split("## open")[0]
        form_i = standing.index("- [local-storage.md 2026-09-16 10:44 LIVE, form: picker] keep two forms")
        every_i = standing.index("- [index.md (no time) LIVE] (closing + popup)")
        plain_i = standing.index("- [index.md (no time) LIVE] (edits + check)")
        briefs_i = standing.index("- [briefs.md standing] standing: `diff:` ×1; not standing: why ×1")
        assert form_i < briefs_i and every_i < briefs_i < plain_i, standing
        assert "- [local-storage.md 2026-09-03 11:00 LIVE] commit only on the word" in standing, standing
        assert "(closing + popup): at every closing serve the popup, never prose" in standing, standing
        assert "nesting goes three deep (sourced)" in standing and "a bare claim (unsourced)" in standing, standing
        assert "the widget stays reusable" not in standing, standing
        opened = out.split("## open")[1].split("## surfaced")[0]
        assert "- [session-storage.md 2026-09-22 13:00 LIVE] open one" in opened and "done one" not in opened \
            and "- [virtual.md 2026-09-22 13:36 LIVE] mine" in opened, opened
        surfaced = out.split("## surfaced")[1].split("## read on demand")[0]
        assert "- [virtual.md 2026-09-16 19:35 EXPIRED] theirs — minted by another session (fd5d84f4)" in surfaced \
            and "FREED] the widget stays reusable after a submit — masked by tombstones.md:" in surfaced \
            and "masks: the closing picker stays reusable after a submit" in surfaced \
            and "- [session-storage.md 2026-09-22 13:00 EXPIRED] done one" in surfaced, surfaced
        assert "grouped" not in out and "over its budget" not in out and len(out) <= 6000, len(out)
        # the children's picks fold into steering by script: the picked entries move, a form line stays standing too,
        # a malformed line is counted and ignored, and the pool file carries the pool alone
        bj = subprocess.run([sys.executable, PHI, "--store", store, "barrier", "--session", "bbcf63ab", "--json"],
                            capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        lines = {e["head"][:40]: e["line"] for e in json.loads(bj)["entries"]}
        commit_line = lines['- ruling: "commit only on the word"'[:40]]
        form_line = lines['- ruling: "keep two forms"'[:40]]
        picks_path = os.path.join(root, "picks.txt")
        with open(picks_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"picks — local-storage.md, 2 of 3 entries bear on the task\nlocal-storage.md:{commit_line} || bears: the word rule\n"
                    f"local-storage.md:{form_line} || bears: the form rule\nthis line is not a pick\n")
        pool_out = os.path.join(root, "pool.md")
        out = subprocess.run(base + ["--picks", picks_path, "--out", pool_out], capture_output=True, timeout=60) \
            .stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert out.startswith("pool-road: children; pool ") and "2 of 2 steering picks kept, 1 pick line(s) ignored" in out, out[:300]
        steering = out.split("## steering")[1].split("## standing")[0]
        assert "- [local-storage.md 2026-09-03 11:00 LIVE] commit only on the word; bears: the word rule" in steering \
            and "LIVE, form: picker] keep two forms; bears: the form rule" in steering, steering
        standing = out.split("## standing")[1].split("## open")[0]
        assert "commit only on the word" not in standing and "form: picker] keep two forms" in standing, standing
        with open(pool_out, encoding="utf-8") as f:
            written = f.read()
        assert written.startswith("# VLDS Recall Pool") and "## appendix" not in written and "(child)" not in written \
            and "local-storage.md (3, child)" in written, written[:400]
        assert "nesting goes three deep (sourced)" in written, written     # the tag survives the width
        # a FREED entry is never a pick, whatever a child says
        freed_line = next(v for k, v in lines.items() if k.startswith('- ruling: "the widget stays reusable'))
        with open(picks_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"local-storage.md:{commit_line} || bears: the word rule\n"
                    f"local-storage.md:{freed_line} || bears: freed, never picked\n")
        out = subprocess.run(base + ["--picks", picks_path], capture_output=True, timeout=60) \
            .stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert "1 of 1 steering picks kept" in out and "the widget stays reusable" not in out.split("## standing")[0], out[:300]
        # a tombstone is a mask, never a steering line, whatever a child says
        mask_line = next(v for k, v in lines.items() if k.startswith('- freed: "the closing picker'))
        with open(picks_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"local-storage.md:{commit_line} || bears: the word rule\n"
                    f"tombstones.md:{mask_line} || bears: a mask, never picked\n")
        out = subprocess.run(base + ["--picks", picks_path], capture_output=True, timeout=60) \
            .stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        steering = out.split("## steering")[1].split("## standing")[0]
        assert "1 of 1 steering picks kept" in out and "closing picker stays reusable" not in steering \
            and "commit only on the word; bears: the word rule" in steering, out[:600]
        # who picked each file: a `picks —` head is a child's, a `picks (pass) —` head the operator's own pass, and a
        # file no block names landed nothing — the read: line credits each, never a child the file did not have
        popup_line = next(v for k, v in lines.items() if k.startswith("- key: (closing + popup)"))
        with open(picks_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"picks — local-storage.md, 1 of 3 entries bear on the task\nlocal-storage.md:{commit_line} || bears: the word rule\n"
                    f"picks (pass) — index.md, 1 of 2 entries bear on the task\nindex.md:{popup_line} || bears: the popup rule\n"
                    "picks — virtual.md, 0 of 2 entries bear on the task\n")
        out = subprocess.run(base + ["--picks", picks_path], capture_output=True, timeout=60) \
            .stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        summary, read_line = out.split("\n", 1)[0], next(l for l in out.split("\n") if l.startswith("read: "))
        assert "local-storage.md (3, child)" in read_line and "index.md (2, pass)" in read_line \
            and "virtual.md (2, child)" in read_line and "data-store.md (2, none landed)" in read_line, read_line
        assert "2 of 2 steering picks kept" in summary and "ignored" not in summary \
            and "; picks per file: child 2, pass 1, none landed " in summary, summary
        steering = out.split("## steering")[1].split("## standing")[0]
        assert "(closing + popup)" in steering and "bears: the popup rule" in steering, steering
        # a store too large for one line per entry: grouped by file, still under the budget
        put("local-storage.md", ls_head + "".join(
            f'- ruling: "ruling number {i} about a matter long enough to weigh in the skeleton\'s count of characters"\n'
            f"  time: 2026-09-{1 + i % 20:02d} 10:00\n  owner-words: \"words {i}\"\n  status: LIVE\n\n" for i in range(80)))
        out = subprocess.run(base, capture_output=True, timeout=60).stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        assert "- [local-storage.md, 80 LIVE, grouped, 2026-09-01 10:00→2026-09-20 10:00]" in out, out[:2000]
        out = out.split("\n", 2)[2]
        pool_part, _sep, appendix = out.partition("## appendix")
        assert "over its budget" not in out and len(pool_part) <= 6000, len(pool_part)
        assert appendix and "- local-storage.md:" in appendix and "ruling number 79 about a matter" in appendix, appendix[:300]
        assert "- [local-storage.md 2026-09-16 10:44 LIVE, form: picker]" not in out    # the form ruling is gone with the rewrite
        # too many picks for the cap: a file's weakest go back to standing and its strongest are kept, in the
        # child's order — the first pick listed is the first kept — and the count says so
        import re as _re
        bj = subprocess.run([sys.executable, PHI, "--store", store, "barrier", "--session", "bbcf63ab", "--json"],
                            capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        rl = {e["head"]: e["line"] for e in json.loads(bj)["entries"] if e["file"] == "local-storage.md"}
        ordered = [rl[h] for h in sorted(rl, key=lambda h: int(_re.search(r"number (\d+)", h).group(1)))][:20]
        with open(picks_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(f"local-storage.md:{n} || bears: reason {i}\n" for i, n in enumerate(ordered)))
        out = subprocess.run(base + ["--picks", picks_path, "--cap", "4000"], capture_output=True, timeout=60) \
            .stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        m = _re.search(r"(\d+) of 20 steering picks kept", out)
        assert m and 0 < int(m.group(1)) < 20 and "over its budget" not in out, out[:300]
        steering = out.split("## steering")[1].split("## standing")[0]
        assert "ruling number 0 about" in steering and "ruling number 19 about" not in steering, steering
        pool_part = out.split("\n", 2)[2].partition("## appendix")[0]
        assert len(pool_part) <= 4000, len(pool_part)
        # an index updated: line longer than a pool line is cut with its cut shown, never mid-word in silence
        with open(os.path.join(store, "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\nregister: 0\n\n## recall\n\npool-road: children\n\nupdated: 2026-09-22 15:30 by test via the "
                    "sweep moment, placed by scripts/normalize.py" + " through the register's gates" * 8 + " — the end\n")
        out = subprocess.run(base, capture_output=True, timeout=60).stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        opened = out.split("## open")[1].split("## surfaced")[0]
        upd = next(l for l in opened.split("\n") if l.startswith("- updated:"))
        assert upd.endswith("…") and len(upd) <= 150 and "the end" not in upd, upd
        # the index names another road: the first line says so, and the skeleton follows all the same
        with open(os.path.join(store, "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\nregister: 0\n\n## recall\n\npool-road: skeleton\n\nupdated: 2026-09-22 15:30 by test\n")
        out = subprocess.run(base, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        assert out.startswith("pool-road: skeleton; pool ") and "\n# VLDS Recall Pool" in out, out[:200]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pool skeleton: green")


def test_move():
    """normalize.py --move relocates an attached dispatch record between live segments — the one move the light
    attacher cannot make: refused when the target position has no live segment or no room; otherwise run through
    both headers, the logger and the index, the check clean after."""
    root, store = seed_project()
    try:
        seed_register(store, logger_entries=10)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        norm = os.path.join(HERE, "normalize.py")
        base = [sys.executable, norm, "--store", store, "--session", "move-session", "--now", "2026-09-03 10:40"]
        arc = os.path.join(store, "arc")

        def run(*extra):
            r = subprocess.run(base + list(extra), capture_output=True, env=env, timeout=120)
            return r.stdout.decode("utf-8", "replace")
        assert "into arc-3-a.md" in run("--pour", "logger.md:7,9,11"), "register [3] not opened"
        assert "into arc-1-a.md" in run("--pour", "logger.md:7"), "register [3, 1] not opened"
        big, small = "dispatch-20260903-103000-bigrec.md", "dispatch-20260903-103100-small.md"
        with open(os.path.join(arc, big), "w", encoding="utf-8", newline="\n") as f:
            f.write("# big\n" + ("x" * 78 + "\n") * 12)       # fits position 3 (3,072 B), never position 1 (1,024 B)
        with open(os.path.join(arc, small), "w", encoding="utf-8", newline="\n") as f:
            f.write("# small\n" + ("y" * 38 + "\n") * 4)
        out = run("--light")
        assert "attached" in out and big in out and small in out and "arc-3-a.md" in out, out
        assert "no live segment at position 4" in run("--move", f"{small}:4")
        assert "more room than position 1 has" in run("--move", f"{big}:1")
        assert "is attached to no live segment" in run("--move", "dispatch-20260903-103200-none.md:1")
        out = run("--move", f"{small}:1", "--dry")
        assert f"{small}" in out and "to arc-1-a.md (position 1:" in out and "dry run" in out, out
        out = run("--move", f"{small}:1")
        assert f"move: moved {small}" in out and "from arc-3-a.md to arc-1-a.md" in out and "0 corruption" in out, out
        with open(os.path.join(arc, "arc-1-a.md"), encoding="utf-8") as f:
            one = f.read()
        with open(os.path.join(arc, "arc-3-a.md"), encoding="utf-8") as f:
            three = f.read()
        assert f"attached: {small}" in one and small not in three and f"attached: {big}" in three, (one, three)
        with open(os.path.join(store, "phi-index.md"), encoding="utf-8") as f:
            index = f.read()
        row1 = next(l for l in index.split("\n") if "| arc-1-a.md |" in l)
        row3 = next(l for l in index.split("\n") if "| arc-3-a.md |" in l)
        assert small in row1 and small not in row3 and big in row3, (row1, row3)
        assert "attachment move" in index and "Attachment moved" in open(os.path.join(store, "logger.md"), encoding="utf-8").read()
        assert "0 corruption, 0 debt" in run_check(store), run_check(store)
        # the swap: --detach unregisters the big record from position 3 (owed registration again, a debt, never a
        # corruption) and, in the same call, --move brings the small one back there
        assert "is attached to no live segment" in run("--detach", "dispatch-20260903-103200-none.md")
        out = run("--detach", big, "--move", f"{small}:3")
        assert f"detach: detached {big}" in out and f"move: moved {small}" in out and "to arc-3-a.md" in out, out
        with open(os.path.join(arc, "arc-3-a.md"), encoding="utf-8") as f:
            three = f.read()
        with open(os.path.join(arc, "arc-1-a.md"), encoding="utf-8") as f:
            one = f.read()
        assert f"attached: {small}" in three and big not in three and "attached:" not in one, (three, one)
        assert os.path.exists(os.path.join(arc, big)), "the detached record must stay in arc/"
        check = run_check(store)
        assert "0 corruption" in check and f"arc/{big}" in check and "attachment registration owed" in check, check
        assert "Attachment detached" in open(os.path.join(store, "logger.md"), encoding="utf-8").read()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("move: green")


def test_record_bare_head():
    """A record block that gives the fingerprint's opening BARE — no quote — completes the row the hook stamped
    quoted, never a second row beside it: the head match ignores the value's quotes on both sides."""
    root, store = seed_project()
    try:
        prompt = "what if we kept the base agent as is but gave it child agents per partition"
        run_hook("prompt-open", {"session_id": "bare", "cwd": root, "prompt": prompt}, root)
        rec = os.path.join(root, "rec.md")
        with open(rec, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"## dispatch.md\n- fingerprint: {prompt[:40]}\n  addressed: assessed\n")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        r = subprocess.run([sys.executable, os.path.join(HERE, "record.py"), "--store", store, "--session", "bare",
                            "--now", now, "--record", rec], capture_output=True, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert "rows: dispatch.md" in out and "written: nothing" in out, out
        dispatch = open(os.path.join(store, "dispatch.md"), encoding="utf-8").read()
        assert dispatch.count('- fingerprint: "what if we kept') == 1 and "  addressed: assessed" in dispatch, dispatch[-500:]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("record bare head: green")


def test_barrier_states():
    """phi.py barrier stamps by rule alone: a status field is the entry's word; a tombstone masks the ruling that
    shares its owner-words; a virtual entry minted by another session is EXPIRED and this session's is LIVE; a
    cleared task is EXPIRED; tombstones are the mask, never masked; the logger's bullets are entries; a file the
    read list names but the store lacks is reported absent."""
    root, store = seed_project()
    try:
        def put(name, text):
            with open(os.path.join(store, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        put("local-storage.md", "# LS\n\n```yaml\n- ruling: [x]\n  time: [t]\n  owner-words: [w]\n  status: LIVE | SPENT | FREED\n```\n\n---\n\n"
            '- ruling: "keep two forms"\n  time: 2026-09-16 10:44\n  owner-words: "keep two forms"\n  status: LIVE\n\n'
            '- ruling: "the widget stays reusable after a submit"\n  time: 2026-09-16 10:40\n  owner-words: "reopen and reuse the widget"\n  status: LIVE\n\n'
            '- ruling: "hold the review"\n  time: 2026-09-03 13:13\n  owner-words: "hold the review"\n  status: SPENT\n')
        put("tombstones.md", "# TS\n\n```yaml\n- freed: [x]\n  time: [t]\n  owner-words: [w]\n```\n\n---\n\n"
            '- freed: "the closing picker stays reusable after a submit"\n  time: 2026-09-16 10:50\n  cause: retraction\n'
            '  owner-words: "reopen and reuse the widget"\n')
        put("virtual.md", "# V\n\n```yaml\n- inference: [x]\n  time: [t]\n  minted: [s]\n  disposition: pending\n```\n\n---\n\n"
            '- inference: "mine"\n  time: 2026-09-22 13:36\n  basis: b\n  minted: bbcf63ab turn 1\n  disposition: pending\n\n'
            '- inference: "theirs"\n  time: 2026-09-16 19:35\n  basis: b\n  minted: session fd5d84f4 turn 3\n  disposition: pending\n')
        put("session-storage.md", "# S\n\n```yaml\n- task: [x]\n  time: [t]\n  state: [s]\n```\n\n---\n\n"
            "- task: open one\n  time: 2026-09-22 13:00\n  state: started\n\n- task: done one\n  time: 2026-09-22 13:00\n  state: completed\n")
        put("logger.md", LOGGER_HEADER + "- `[gc]` 2026-09-22 13:46 — **A sweep.** placed.\n")
        r = subprocess.run([sys.executable, PHI, "--store", store, "barrier", "--session", "bbcf63ab", "--json"],
                           capture_output=True, timeout=60)
        data = json.loads(r.stdout.decode("utf-8", "replace"))

        def state_of(prefix):
            return next(e["state"] for e in data["entries"] if e["head"].startswith(prefix))
        assert state_of('- ruling: "keep two forms"') == "LIVE"
        assert state_of('- ruling: "the widget stays reusable') == "FREED", data["entries"]
        assert state_of('- ruling: "hold the review"') == "SPENT"
        assert state_of('- freed: "the closing picker') == "LIVE"
        assert state_of('- inference: "mine"') == "LIVE" and state_of('- inference: "theirs"') == "EXPIRED"
        assert state_of("- task: open one") == "LIVE" and state_of("- task: done one") == "EXPIRED"
        assert state_of("- `[gc]` 2026-09-22 13:46") == "LIVE"
        assert "index.md" in data["missing"] and "local-storage.md" in data["files"], data["missing"]
        r = subprocess.run([sys.executable, PHI, "--store", store, "barrier", "--session", "bbcf63ab"],
                           capture_output=True, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert out.startswith("barrier — store") and "\nbarrier: " in out and "masked by tombstones.md:" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("barrier states: green")


def run_hook_standing(part, root):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
    payload = {"source": "resume", "session_id": CURRENT_SID[0]}
    r = subprocess.run([sys.executable, HOOKS, "session-open", "--standing", str(part)],
                       input=json.dumps(payload).encode("utf-8"), capture_output=True, env=env, timeout=60)
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def test_standing_rules():
    """The standing block prints every LIVE form ruling and every-turn index rule whole — a long one uncut, past
    every width the pool cuts to — in the pooled mode only and on a resume too; a plain ruling, a plain rule and a
    FREED form ruling stay out; the rules split into parts when they outgrow one output; a part past the end and
    the inject mode print nothing."""
    root, store = seed_project()
    try:
        seed_register(store, recall="inject: local-storage.md, index.md\n")   # the block follows the read list
        long_ruling = "keep " + "the whole rule " * 40
        long_directive = "at every closing serve the popup, never prose, " + "and name every act " * 15
        with open(os.path.join(store, "local-storage.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# LS\n\n```yaml\n- ruling: [x]\n  time: [t]\n  owner-words: [w]\n  status: LIVE | SPENT | FREED\n"
                    "  form: [f]\n```\n\n---\n\n"
                    f'- ruling: "{long_ruling.strip()}"\n  time: 2026-09-16 10:44\n  owner-words: "w"\n  status: LIVE\n'
                    "  form: picker\n\n"
                    '- ruling: "a plain ruling with no form"\n  time: 2026-09-16 10:45\n  owner-words: "p"\n  status: LIVE\n\n'
                    '- ruling: "a freed form ruling"\n  time: 2026-09-16 10:46\n  owner-words: "f"\n  status: FREED\n'
                    "  form: fence\n")
        with open(os.path.join(store, "index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# IX\n\n```yaml\n- key: [k]\n  decision: rule | opt-out\n  directive: [d]\n```\n\n---\n\n"
                    f"- key: (closing + popup)\n  decision: rule\n  directive: {long_directive.strip()}\n\n"
                    "- key: (edits + check)\n  decision: rule\n  directive: check the user's edits first\n")
        out = run_hook_standing(0, root)
        assert out.startswith("### standing rules — the owner's 2 form rulings and every-turn rules, whole "
                              "(SessionStart hook;"), out[:300]
        assert long_ruling.strip() in out and long_directive.strip() in out, f"a rule was cut:\n{out}"
        assert "form: picker]" in out and "a plain ruling" not in out and "a freed form ruling" not in out \
            and "check the user's edits first" not in out, out
        assert run_hook_standing(1, root).strip() == "", "a part past the end printed"
        # outgrowing one output: the rules split into parts, each headed with its place
        parts = [subprocess.run([sys.executable, PHI, "--store", store, "standing", "--budget", "700", "--part", str(n)],
                                capture_output=True, timeout=60).stdout.decode("utf-8", "replace").replace("\r\n", "\n")
                 for n in (0, 1, 2)]
        assert "part 1 of 2" in parts[0] and long_ruling.strip() in parts[0], parts[0][:300]
        assert "part 2 of 2" in parts[1] and long_directive.strip() in parts[1], parts[1][:300]
        assert parts[2].strip() == "", parts[2]
        # the inject mode's slots carry the files whole already: no standing block
        seed_register(store, recall="pool: inject\n")
        assert run_hook_standing(0, root).strip() == "", "the standing block printed in the inject mode"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("standing rules: green")


def test_p4_gitignore():
    """p4-layout.sh seeds .claude/p4/.gitignore from hooks/p4-gitignore when the store has none — audio, images,
    builds and caches ignored by type, a run's text kept — and never touches one the owner has."""
    root, store = seed_project()
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        layout = os.path.join(PLUGIN, "hooks", "p4-layout.sh")
        r = subprocess.run(["sh", layout], capture_output=True, env=env, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        gi = os.path.join(root, ".claude", "p4", ".gitignore")
        with open(os.path.join(PLUGIN, "hooks", "p4-gitignore"), encoding="utf-8") as f:
            template = f.read()
        assert os.path.exists(gi) and "seeded .claude/p4/.gitignore" in out, out
        ga = os.path.join(root, ".claude", "p4", ".gitattributes")
        with open(ga, encoding="utf-8") as f:
            assert "models/*.pt filter=lfs" in f.read() and "seeded .claude/p4/.gitattributes" in out, out
        if subprocess.run(["git", "lfs", "version"], capture_output=True).returncode == 0:
            with open(os.path.join(root, ".claude", "p4", ".git", "hooks", "pre-push"), encoding="utf-8") as f:
                assert "git lfs" in f.read(), "git lfs install --local did not run"
        with open(gi, encoding="utf-8") as f:
            assert f.read() == template
        p4 = os.path.join(root, ".claude", "p4")
        if shutil.which("git"):
            for rel, data in (("scratchpad/runs/r1/take.wav", b"RIFF\0\0"), ("scratchpad/runs/r1/run.log", b"ok\n"),
                              ("scratchpad/runs/r1/GPUCache/data_1", b"\0"), ("scratchpad/shot.png", b"\x89PNG")):
                os.makedirs(os.path.dirname(os.path.join(p4, rel)), exist_ok=True)
                with open(os.path.join(p4, rel), "wb") as f:
                    f.write(data)
            kept = subprocess.run(["git", "-C", p4, "ls-files", "-co", "--exclude-standard", "scratchpad"],
                                  capture_output=True).stdout.decode().split()
            assert kept == ["scratchpad/runs/r1/run.log"], kept
            # the checkpoints are kept (the chain in LFS); the models' runtime files and the local build are not
            os.makedirs(os.path.join(p4, "models"), exist_ok=True)
            for name in ("ranker.pt", "ranker-anchor.pt", "ranker.r001.phid", "ranker-oof.json", "pick-model.json",
                         "ranker.server.json", "train.log", ".retrain", "x.123.tmp"):
                with open(os.path.join(p4, "models", name), "wb") as f:
                    f.write(b"x")
            kept = subprocess.run(["git", "-C", p4, "ls-files", "-co", "--exclude-standard", "models"],
                                  capture_output=True).stdout.decode().split()
            assert kept == ["models/pick-model.json", "models/ranker-anchor.pt", "models/ranker-oof.json",
                            "models/ranker.r001.phid"], kept
            attr = subprocess.run(["git", "-C", p4, "check-attr", "filter", "models/ranker-anchor.pt",
                                   "models/ranker.r001.phid"],
                                  capture_output=True).stdout.decode()
            assert attr.count("filter: lfs") == 2, attr
        # an owner's .gitignore is never replaced
        with open(gi, "w", encoding="utf-8") as f:
            f.write("# mine\n")
        r = subprocess.run(["sh", layout], capture_output=True, env=env, timeout=60)
        with open(gi, encoding="utf-8") as f:
            assert f.read() == "# mine\n" and "seeded" not in r.stdout.decode()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("p4 gitignore: green")


if __name__ == "__main__":
    test_pre_write()
    test_stray_scan()
    test_clock_and_post_write()
    test_gc_trace()
    test_owner_voice()
    test_conductor_owed()
    test_cross_session_reads()
    test_session_title()
    test_pool_mode()
    test_turn_close()
    test_barrier()
    test_record()
    test_record_seeds_session_local()
    test_pour()
    test_check_delta()
    test_detail_ask()
    test_pre_ask()
    test_pre_agent()
    test_record_truncated_head()
    test_record_bare_head()
    test_barrier_states()
    test_move()
    test_pool_skeleton()
    test_standing_rules()
    test_p4_gitignore()
    print("test_hooks.py: all green")
