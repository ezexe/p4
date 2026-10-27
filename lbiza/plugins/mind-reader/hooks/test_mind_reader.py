#!/usr/bin/env python3
"""test_mind_reader.py — acceptance tests for the mind-reader side agent over a fixture p4 store and transcript:
`start` prints nothing and records the turn; the watcher writes a rotating draft from the owner's history and the
turn's progress; `finalize` freezes it and writes gc holds; the next `start` scores the frozen prediction, appends
it to the session's vlds partition, logs the history and moves the learned weights; agent messages are never the
owner's; a detached watcher outlives the hook that spawned it and stops at the next start. Run from anywhere:
python hooks/test_mind_reader.py — exit 0 = green."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "mind_reader.py")
HEAD = "# VLDS Partition — Dispatch\n\nheader\n\n---\n"


def row(fp, t, arrival="turn (stamped by the prompt hook)"):
    return f"\n- fingerprint: \"{fp}\"\n  time: {t}\n  arrival: {arrival}\n  state: FRESH\n  addressed: done\n"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run(root, sub, payload, **env):
    e = dict(os.environ, CLAUDE_PROJECT_DIR=root, MIND_READER_NOW="2026-10-22 20:00", **env)
    r = subprocess.run([sys.executable, HOOK, sub], env=e, capture_output=True, timeout=60,
                       input=json.dumps(payload).encode("utf-8"))
    return r.stdout.decode("utf-8", "replace")


def tool_use(name, **inp):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


def main():
    root = tempfile.mkdtemp(prefix="mind-reader-")
    s = os.path.join(root, ".claude", "p4", "sessions")
    tr = os.path.join(root, "transcript.jsonl")
    put(tr, '{"type":"user"}\n')
    assert run(root, "start", {"prompt": "hi", "session_id": "x"}) == "", "a store-less project spoke"
    put(os.path.join(s, "old--11111111", "vlds", "dispatch.md"), HEAD
        + row("bump the vlds plugin version and reconcile the cache", "2026-10-01 10:00")
        + row("<agent-message from='x'> report", "2026-10-01 10:01", "agent message")
        + row("restart", "2026-10-01 10:05") + row("commit it", "2026-10-01 10:20") + row("commit it", "2026-10-02 10:20"))
    put(os.path.join(s, "old--11111111", "vlds", "local-storage.md"),
        "# h\n\n---\n\n- ruling: bump the plugin version and reconcile the cache before restart\n  time: 2026-10-01 10:00\n"
        "\n- ruling: italics use underscores\n  time: 2026-10-01 10:00\n")
    now = os.path.join(s, "now--33333333")
    put(os.path.join(now, "vlds", "dispatch.md"), HEAD + row("bump the src-fragger plugin version and reconcile", "2026-10-22 19:00"))
    payload = {"prompt": "bump the src-fragger plugin version and reconcile the cache", "session_id": "33333333-x",
               "transcript_path": tr}
    # start: silent, records the turn at the transcript's current end
    assert run(root, "start", payload, MIND_READER_NO_SPAWN="1") == "", "start spoke into the session"
    state = json.loads(read(os.path.join(now, "mind-reader", "state.json")))
    assert state["offset"] == os.path.getsize(tr), state
    # the turn progresses: an edit, no commit → the owner's own word for commit is predicted
    with open(tr, "a", encoding="utf-8") as f:
        f.write(tool_use("Edit", file_path="E:/x/plugin.json") + "\n")
    subprocess.run([sys.executable, HOOK, "watch", "--root", root, "--name", "now--33333333"],
                   env=dict(os.environ, MIND_READER_ONCE="1", MIND_READER_NOW="2026-10-22 20:01"), timeout=60)
    draft = read(os.path.join(now, "mind-reader", "draft.md"))
    assert "draft, session now--33333333" in draft and "revision: 1" in draft, draft
    line = next((l for l in draft.split("\n") if '"commit it"' in l), "")
    assert "progress" in line, f"the progress source did not predict the owner's commit word: {draft}"
    assert '"restart"' in draft, "the follower of the resembling message was not predicted"
    assert "agent-message" not in draft, "an agent message entered the corpus"
    # finalize: frozen, and holds written for the entries the predicted direction leans on
    assert run(root, "finalize", payload) == "", "finalize spoke"
    assert "FROZEN" in read(os.path.join(now, "mind-reader", "draft.md")), "the draft did not freeze"
    holds = read(os.path.join(root, ".claude", "p4", "vindex", "holds.tsv"))
    assert "old--11111111/local-storage.md\tbump the plugin version and reco" in holds, holds
    assert "italics" not in holds, "an unrelated entry was held"
    # the owner's next message: scored, appended to the vlds partition, history logged, weights moved
    nxt = dict(payload, prompt="commit it")
    assert run(root, "start", nxt, MIND_READER_NO_SPAWN="1") == "", "the scoring start spoke"
    part = read(os.path.join(now, "vlds", "mind-reader.md"))
    assert part.startswith("# VLDS Partition — Mind-reader") and '\n  actual: "commit it"' in part, part
    assert "\n  score: 1.0" in part, part
    model = json.loads(read(os.path.join(root, ".claude", "p4", "mrindex", "model.json")))
    w = model["weights"]
    assert model["updates"] == 1 and w["progress"] > w["direction"], w
    assert "\t1.0\t" in read(os.path.join(root, ".claude", "p4", "mrindex", "history.tsv")), "history not logged"
    # a frozen prediction is scored once
    run(root, "start", nxt, MIND_READER_NO_SPAWN="1")
    assert read(os.path.join(now, "vlds", "mind-reader.md")).count("\n- predicted: \"") == 1, "scored twice"
    # an agent message is never the owner's: nothing recorded
    before = read(os.path.join(now, "mind-reader", "state.json"))
    assert run(root, "start", dict(payload, prompt="<agent-message from='y'> hi")) == ""
    assert read(os.path.join(now, "mind-reader", "state.json")) == before, "an agent message started a turn"
    # status prints the draft and the history for the owner
    st = run(root, "status", {"session_id": "33333333"})
    assert "mind-reader" in st and "history: 1 scored" in st, st
    # a bare status (no session given) reports the session whose side agent wrote last
    st = run(root, "status", {})
    assert "session now--33333333" in st and "scored predictions in this session's partition: 1" in st, st
    # a detached watcher outlives the spawning hook (run through sh, as the harness does) and the next start stops it
    sh = shutil.which("sh")
    if sh:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE))
        subprocess.run([sh, os.path.join(HERE, "run-hook.sh"), "start"], env=env, timeout=60,
                       input=json.dumps(payload).encode("utf-8"), capture_output=True)
        logp = os.path.join(root, ".claude", "p4", "scratchpad", ".out", "mind-reader", "now--33333333.log")
        pid = int(read(logp).strip().split("pid=")[-1])
        time.sleep(4)
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout \
            if os.name == "nt" else ("x" if os.path.exists(f"/proc/{pid}") else "")
        assert str(pid) in alive or (os.name != "nt" and alive), f"the watcher {pid} died with its hook"
        put(os.path.join(now, "mind-reader", "stop"), "x\n")
        for _ in range(20):
            time.sleep(0.5)
            gone = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout \
                if os.name == "nt" else ""
            if str(pid) not in gone:
                break
        else:
            raise AssertionError(f"the watcher {pid} ignored its stop")
        print("test_mind_reader.py: detached watcher case green")
    shutil.rmtree(root, ignore_errors=True)
    print("test_mind_reader.py: all green")


if __name__ == "__main__":
    main()
