#!/usr/bin/env python3
"""test_mind_reader.py — acceptance tests for mind-reader's predict hook over a fixture p4 store: the follower of
a resembling message is predicted, agent messages are left out of the corpus, the direction names the session
whose run resembles this one, the prediction is logged and scored by the next prompt, and a store-less project is
silent. Run from anywhere: python hooks/test_mind_reader.py — exit 0 = green."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "mind_reader.py")
HEAD = "# VLDS Partition — Dispatch\n\nheader\n\n---\n"


def row(fp, t, arrival="turn (stamped by the prompt hook)"):
    return f"\n- fingerprint: \"{fp}\"\n  time: {t}\n  arrival: {arrival}\n  state: FRESH\n  addressed: done\n"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def predict(root, sid, prompt, now):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, MIND_READER_NOW=now)
    r = subprocess.run([sys.executable, HOOK, "predict"], env=env, capture_output=True, timeout=60,
                       input=json.dumps({"prompt": prompt, "session_id": sid + "-rest"}).encode("utf-8"))
    return r.stdout.decode("utf-8", "replace")


def main():
    root = tempfile.mkdtemp(prefix="mind-reader-")
    s = os.path.join(root, ".claude", "p4", "sessions")
    assert predict(root, "aaaaaaaa", "hello", "2026-10-22 19:00") == "", "a store-less project spoke"
    put(os.path.join(s, "old-plugin-work--11111111", "vlds", "dispatch.md"), HEAD
        + row("bump the vlds plugin version and reconcile the cache", "2026-10-01 10:00")
        + row("<agent-message from='x'> report", "2026-10-01 10:01", "agent message")
        + row("restart", "2026-10-01 10:05")
        + row("commit", "2026-10-01 10:20"))
    put(os.path.join(s, "other--22222222", "vlds", "dispatch.md"), HEAD
        + row("write a sweep script for the notebook", "2026-10-02 09:00")
        + row("push it", "2026-10-02 09:10"))
    put(os.path.join(s, "now--33333333", "vlds", "dispatch.md"), HEAD
        + row("bump the src-fragger plugin version and reconcile", "2026-10-22 19:00"))
    out = predict(root, "33333333", "bump the src-fragger plugin version and reconcile the cache", "2026-10-22 19:01")
    assert "## mind-reader (session now--33333333)" in out, out
    assert '"restart" (old-plugin-work--11111111' in out, "the follower of the resembling message was not predicted"
    assert "agent-message" not in out, "an agent message entered the corpus"
    assert "direction: like old-plugin-work--11111111" in out and '"restart"' in out, out
    log = os.path.join(s, "now--33333333", "mind-reader", "predictions.md")
    with open(log, encoding="utf-8") as f:
        text = f.read()
    body = text.split("\n---\n", 1)[1]
    assert "- after: \"bump the src-fragger" in body and "| restart |" in body and "scored:" not in body, text
    # the next prompt scores the last prediction and reports the running rate
    out = predict(root, "33333333", "restart", "2026-10-22 19:05")
    assert "last prediction scored 1.0" in out and "running: 1 of 1" in out, out
    assert '"commit"' in out, "the follower of `restart` was not predicted"
    with open(log, encoding="utf-8") as f:
        text = f.read()
    assert text.count("\n- after: \"") == 2 and text.count("\n  scored: 1.0") == 1, text
    # an agent message as the prompt is never predicted from
    assert predict(root, "33333333", "<agent-message from='y'> hi", "2026-10-22 19:06") == "", "an agent message spoke"
    shutil.rmtree(root, ignore_errors=True)
    print("test_mind_reader.py: all green")


if __name__ == "__main__":
    main()
