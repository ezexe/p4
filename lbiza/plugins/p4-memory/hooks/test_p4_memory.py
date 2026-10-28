#!/usr/bin/env python3
"""test_p4_memory.py — acceptance tests for p4-memory: every AppData memory source (the memory/ directory, a link
an earlier version left, a memory.pre-p4-* directory) is merged into .claude/p4/memory/ and deleted, a differing
file kept in .conflicts/ and never overwriting p4; AppData keeps only the pointer MEMORY.md; a write into AppData
is moved into p4; a busy directory is left to the turn's close. Run from anywhere: python hooks/test_p4_memory.py
— exit 0 = green."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "p4_memory.py")
MARK = "<!-- p4-memory: pointer"


def run(sub, root, app, payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
    r = subprocess.run([sys.executable, HOOK, sub], input=json.dumps(payload).encode("utf-8"), env=env,
                       capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", "replace").strip()


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def only_pointer(app):
    return os.listdir(app) == ["MEMORY.md"] and read(os.path.join(app, "MEMORY.md")).startswith(MARK)


def link(app, target):
    os.makedirs(os.path.dirname(app), exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", app, target], capture_output=True, check=True)
    else:
        os.symlink(target, app, target_is_directory=True)


def main():
    base = tempfile.mkdtemp(prefix="p4-memory-")
    root = os.path.join(base, "proj")
    app = os.path.join(base, "appdata", "projects", "slug", "memory")
    p4mem = os.path.join(root, ".claude", "p4", "memory")
    transcript = os.path.join(os.path.dirname(app), "session.jsonl")
    put(transcript, "{}\n")
    # no p4 repo directory: silent, nothing created or deleted
    os.makedirs(root)
    put(os.path.join(app, "MEMORY.md"), "- [a](a.md) — a\n")
    assert run("migrate", root, app, {}) == "", "migrate spoke without .claude/p4"
    assert not os.path.exists(p4mem) and os.path.isfile(os.path.join(app, "MEMORY.md")), "acted without .claude/p4"
    os.makedirs(os.path.join(root, ".claude", "p4"))
    put(os.path.join(app, "a.md"), "fact a\n")
    put(os.path.join(app, "b.md"), "fact b\n")
    put(os.path.join(p4mem, "a.md"), "fact a, edited elsewhere\n")
    put(os.path.join(p4mem, "b.md"), "fact b\n")
    backup = app + ".pre-p4-20260101-000000"
    put(os.path.join(backup, "b.md"), "fact b\n")
    put(os.path.join(backup, "z.md"), "fact z, retired in p4\n")
    out = run("migrate", root, app, {})
    # moved, kept aside, dropped, deleted
    assert read(os.path.join(p4mem, "MEMORY.md")) == "- [a](a.md) — a\n", "an absent file was not moved in"
    assert read(os.path.join(p4mem, "a.md")) == "fact a, edited elsewhere\n", "the p4 file was overwritten"
    assert read(os.path.join(p4mem, ".conflicts", "memory", "a.md")) == "fact a\n", "differing copy not kept"
    assert read(os.path.join(p4mem, ".conflicts", os.path.basename(backup), "z.md")) == "fact z, retired in p4\n"
    assert not os.path.exists(os.path.join(p4mem, "z.md")), "a retired file was resurrected into p4"
    assert not os.path.exists(backup), "the renamed-aside directory was not deleted"
    assert only_pointer(app), os.listdir(app)
    assert os.path.normpath(p4mem) in read(os.path.join(app, "MEMORY.md")), "the pointer does not name p4"
    assert os.path.isfile(transcript), "the harness's own files were touched"
    assert "moved 1" in out and "kept in .claude/p4/memory/.conflicts/" in out and "p4 base memory index" in out, out
    # a second start moves nothing, and still prints the index (the harness loaded only the pointer)
    out = run("migrate", root, app, {})
    assert out.startswith("### p4 base memory index"), out
    # the turn's close has nothing to do: silent
    assert run("sweep", root, app, {}) == "", "an idle close spoke"
    # a write into AppData is moved into p4, and the session is told
    put(os.path.join(app, "c.md"), "fact c\n")
    w = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "c.md"), "content": "fact c\n"}}
    note = json.loads(run("mirror", root, app, w))["hookSpecificOutput"]["additionalContext"]
    assert "moved to" in note and read(os.path.join(p4mem, "c.md")) == "fact c\n", note
    assert only_pointer(app), "the written file stayed in AppData"
    # a write that replaces a different p4 file: the write wins, the p4 file it replaced is kept aside
    put(os.path.join(app, "b.md"), "fact b, rewritten\n")
    w2 = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "b.md"), "content": ""}}
    run("mirror", root, app, w2)
    assert read(os.path.join(p4mem, "b.md")) == "fact b, rewritten\n"
    assert read(os.path.join(p4mem, ".conflicts", "replaced", "b.md")) == "fact b\n", "the replaced file was lost"
    # an index line written into the pointer goes to the p4 MEMORY.md, and the pointer is restored
    ptr = os.path.join(app, "MEMORY.md")
    put(ptr, read(ptr) + "- [c](c.md) — c\n")
    e = {"tool_name": "Edit", "tool_input": {"file_path": ptr}}
    assert "appended" in run("mirror", root, app, e)
    assert read(os.path.join(p4mem, "MEMORY.md")) == "- [a](a.md) — a\n- [c](c.md) — c\n"
    assert only_pointer(app) and "- [c]" not in read(ptr), "the pointer was not restored"
    # a write elsewhere is not the mirror's
    put(os.path.join(root, "x.md"), "x\n")
    other = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(root, "x.md"), "content": "x"}}
    assert run("mirror", root, app, other) == "" and not os.path.exists(os.path.join(p4mem, "x.md")), "mirrored x.md"
    # a link an earlier version left: removed as a link, its target untouched, the pointer written
    app2 = os.path.join(base, "appdata2", "projects", "slug", "memory")
    link(app2, p4mem)
    before = sorted(os.listdir(p4mem))
    out = run("migrate", root, app2, {})
    assert "removed the link" in out and sorted(os.listdir(p4mem)) == before, out
    assert only_pointer(app2) and not os.path.samefile(app2, p4mem), "the link was not replaced by the pointer"
    # a busy renamed-aside directory: its content reaches p4, the deletion waits for the close
    backup3 = app + ".pre-p4-20260202-000000"
    put(os.path.join(backup3, "y.md"), "fact y\n")
    if os.name == "nt":
        busy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"], cwd=backup3)
        try:
            out = run("migrate", root, app, {})
            assert "could not be deleted (busy)" in out and os.path.isdir(backup3), out
        finally:
            busy.kill()
            busy.wait()
    out = run("sweep", root, app, {})
    assert "emptied the AppData memory" in out and not os.path.exists(backup3), out
    assert read(os.path.join(p4mem, ".conflicts", os.path.basename(backup3), "y.md")) == "fact y\n"
    assert run("sweep", root, app, {}) == "", "a clean close spoke"
    # a project dir with forward slashes, as a hook payload's cwd carries it
    root3 = os.path.join(base, "proj3")
    os.makedirs(os.path.join(root3, ".claude", "p4"))
    app3 = os.path.join(base, "appdata3", "projects", "slug", "memory")
    put(os.path.join(app3, "MEMORY.md"), "- [a](a.md) — a\n")
    run("migrate", root3.replace("\\", "/"), app3.replace("\\", "/"), {})
    assert read(os.path.join(root3, ".claude", "p4", "memory", "MEMORY.md")) == "- [a](a.md) — a\n"
    assert only_pointer(app3)
    shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: all green")


if __name__ == "__main__":
    main()
