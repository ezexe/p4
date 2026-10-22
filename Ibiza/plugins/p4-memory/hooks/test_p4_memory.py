#!/usr/bin/env python3
"""test_p4_memory.py — acceptance tests for p4-memory: the AppData memory directory is copied into
.claude/p4/memory/, renamed aside whole and replaced by a link to it; a differing file holds the link and lands in
.conflicts/; a link already in place is left; the gate denies a write into an unlinked AppData directory and
passes once linked. Run from anywhere: python hooks/test_p4_memory.py — exit 0 = green."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "p4_memory.py")


def run(sub, root, app, payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
    r = subprocess.run([sys.executable, HOOK, sub], input=json.dumps(payload).encode("utf-8"), env=env,
                       capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "replace").strip()


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    base = tempfile.mkdtemp(prefix="p4-memory-")
    root = os.path.join(base, "proj")
    app = os.path.join(base, "appdata", "projects", "slug", "memory")
    p4mem = os.path.join(root, ".claude", "p4", "memory")
    # no p4 repo directory: silent, nothing created
    os.makedirs(root)
    put(os.path.join(app, "MEMORY.md"), "- [a](a.md) — a\n")
    assert run("migrate", root, app, {}) == "", "migrate spoke without .claude/p4"
    assert not os.path.exists(p4mem), "p4 memory created without .claude/p4"
    os.makedirs(os.path.join(root, ".claude", "p4"))
    put(os.path.join(app, "a.md"), "fact a\n")
    put(os.path.join(p4mem, "a.md"), "fact a, edited elsewhere\n")
    # a differing file: copied aside, no link
    out = run("migrate", root, app, {})
    assert "differ" in out and "a.md" in out, out
    assert read(os.path.join(p4mem, ".conflicts", "a.md")) == "fact a\n", "the AppData copy was not kept aside"
    assert read(os.path.join(p4mem, "a.md")) == "fact a, edited elsewhere\n", "the p4 file was overwritten"
    assert read(os.path.join(p4mem, "MEMORY.md")) == "- [a](a.md) — a\n", "an absent file was not copied"
    assert not os.path.islink(app) and "p4 base memory index" not in out, "an index the harness loaded was re-printed"
    # a write into the unlinked AppData directory is never refused: it is mirrored into p4 at once
    put(os.path.join(app, "b.md"), "fact b\n")
    w = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "b.md"), "content": "fact b\n"}}
    assert run("mirror", root, app, w) == "" and read(os.path.join(p4mem, "b.md")) == "fact b\n", "b.md not mirrored"
    put(os.path.join(root, "x.md"), "x\n")
    other = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(root, "x.md"), "content": "x"}}
    assert run("mirror", root, app, other) == "" and not os.path.exists(os.path.join(p4mem, "x.md")), "mirrored x.md"
    # the owner merges: identical now — but the directory is busy (a process sits in it): not linked, said so
    put(os.path.join(p4mem, "a.md"), "fact a\n")
    if os.name == "nt":
        busy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(12)"], cwd=app)
        try:
            out = run("migrate", root, app, {})
            assert "is busy and was not linked yet" in out and not os.path.samefile(app, p4mem), out
        finally:
            busy.kill()
            busy.wait()
    # the turn's close tries again and links, saying so
    out = run("relink", root, app, {})
    assert "is now a link" in out, out
    assert run("relink", root, app, {}) == "", "a linked close spoke"
    kept = [n for n in os.listdir(os.path.dirname(app)) if n.startswith("memory.pre-p4-")]
    assert len(kept) == 1 and read(os.path.join(os.path.dirname(app), kept[0], "a.md")) == "fact a\n", kept
    assert os.path.samefile(app, p4mem), "the AppData path does not reach p4"
    # writes through the AppData path land in p4, and the gate passes
    put(os.path.join(app, "c.md"), "fact c\n")
    assert read(os.path.join(p4mem, "c.md")) == "fact c\n", "a write through the link missed p4"
    assert run("mirror", root, app, w) == "", "the mirror spoke on a linked directory"
    # a second start is silent
    assert run("migrate", root, app, {}) == "", "a linked start spoke"
    # a fresh device with no AppData memory yet: the link is made straight away
    app2 = os.path.join(base, "appdata2", "projects", "slug", "memory")
    out = run("migrate", root, app2, {})
    assert "is now a link" in out and os.path.samefile(app2, p4mem), out
    # unlink the junctions before removal so rmtree never walks into p4 through them
    for a in (app, app2):
        (os.rmdir if os.name == "nt" else os.unlink)(a)
    shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: all green")


if __name__ == "__main__":
    main()
