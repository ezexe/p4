#!/usr/bin/env python3
"""test_p4_memory.py: acceptance tests for p4-temportal's memory part. The auto memory directory, or a link left in
its place, is merged into .claude/p4/temportal/memory/ and deleted, a differing file is kept in .conflicts/ and never
overwrites the store's, the auto memory directory keeps only the pointer MEMORY.md, a write into it is moved into the
store, a busy folder is left to turn end, and .claude/p4/ is made as a plain folder when absent. Then what a session
is given: the SessionStart output equals what Claude Code loads from a memory folder holding the same files, after at
most one notice line, and the pointer has no imperative sentence but the one that says where to write. Run from
anywhere: python3 hooks/test_p4_memory.py, and exit 0 is green."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "p4_memory.py")
RUNNER = os.path.join(HERE, "run-hook.sh")
MARK = "<!-- p4-memory: pointer"
BUILTIN_LINES = 200         # the reference of what Claude Code loads, kept apart from p4_memory.py's constants so
BUILTIN_BYTES = 25_000      # that a change there fails here


def run(sub, root, app, payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
    r = subprocess.run([sys.executable, "-I", HOOK, sub], input=json.dumps(payload).encode("utf-8"), env=env,
                       capture_output=True, timeout=90)
    assert r.returncode == 0, r
    return r.stdout.decode("utf-8", "replace").strip()


def run_raw(sub, root, app):
    """The SessionStart output unstripped, as Claude Code receives it."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
    r = subprocess.run([sys.executable, "-I", HOOK, sub], input=b"{}", env=env, capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", "replace")


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


def builtin_print(memdir):
    """The reference: what Claude Code loads from a memory folder, cut at BUILTIN_LINES lines or BUILTIN_BYTES
    bytes, whichever comes first."""
    path = os.path.join(memdir, "MEMORY.md")
    if not os.path.isfile(path):
        return []
    kept, size = [], 0
    for line in read(path).splitlines(keepends=True)[:BUILTIN_LINES]:
        size += len(line.encode("utf-8"))
        if size > BUILTIN_BYTES:
            break
        kept.append(line)
    return "".join(kept).splitlines()


def behavior():
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-")
    root = os.path.join(base, "proj")
    app = os.path.join(base, "appdata", "projects", "slug", "memory")
    p4mem = os.path.join(root, ".claude", "p4", "temportal", "memory")
    transcript = os.path.join(os.path.dirname(app), "session.jsonl")
    put(transcript, "{}\n")
    # no .claude/p4 yet: the hook makes it as a plain folder, not a git repository, and moves the memory in
    root0 = os.path.join(base, "proj0")
    app0 = os.path.join(base, "appdata0", "projects", "slug", "memory")
    os.makedirs(root0)
    put(os.path.join(app0, "MEMORY.md"), "- [a](a.md) — a\n")
    out = run("migrate", root0, app0, {})
    p4mem0 = os.path.join(root0, ".claude", "p4", "temportal", "memory")
    assert read(os.path.join(p4mem0, "MEMORY.md")) == "- [a](a.md) — a\n", "the memory was not moved without .claude/p4"
    assert not os.path.exists(os.path.join(root0, ".claude", "p4", ".git")), "p4-temportal initialized a git repository"
    assert only_pointer(app0) and "temportal/memory/: 1" in out, out
    # the main fixture
    os.makedirs(os.path.join(root, ".claude", "p4"))
    put(os.path.join(app, "MEMORY.md"), "- [a](a.md) — a\n")
    put(os.path.join(app, "a.md"), "fact a\n")
    put(os.path.join(app, "b.md"), "fact b\n")
    put(os.path.join(p4mem, "a.md"), "fact a, edited elsewhere\n")
    put(os.path.join(p4mem, "b.md"), "fact b\n")
    out = run("migrate", root, app, {})
    # moved, kept aside, dropped, deleted
    assert read(os.path.join(p4mem, "MEMORY.md")) == "- [a](a.md) — a\n", "an absent file was not moved in"
    assert read(os.path.join(p4mem, "a.md")) == "fact a, edited elsewhere\n", "the store file was overwritten"
    assert read(os.path.join(p4mem, ".conflicts", "memory", "a.md")) == "fact a\n", "differing copy not kept"
    assert only_pointer(app), os.listdir(app)
    assert os.path.normpath(p4mem) in read(os.path.join(app, "MEMORY.md")), "the pointer names no memory folder"
    assert os.path.isfile(transcript), "Claude Code's own files were touched"
    lines = out.splitlines()
    assert lines[0].startswith("p4-temportal: ") and "memory/: 1" in lines[0] and ".conflicts/" in lines[0], out
    assert lines[1:] == ["- [a](a.md) — a"], out
    # a second start moves nothing and prints the index alone
    assert run("migrate", root, app, {}) == "- [a](a.md) — a", "an idle start printed more than the index"
    # turn end has nothing to do: silent
    assert run("sweep", root, app, {}) == "", "an idle turn end spoke"
    # a write into the auto memory directory is moved into the store, and the session is told in one line
    put(os.path.join(app, "c.md"), "fact c\n")
    w = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "c.md"), "content": "fact c\n"}}
    note = json.loads(run("mirror", root, app, w))["hookSpecificOutput"]["additionalContext"]
    assert "moved to" in note and "\n" not in note and read(os.path.join(p4mem, "c.md")) == "fact c\n", note
    assert only_pointer(app), "the written file stayed in the auto memory directory"
    # a write that replaces a different store file: the write wins, and the file it replaced is kept aside
    put(os.path.join(app, "b.md"), "fact b, rewritten\n")
    w2 = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "b.md"), "content": ""}}
    run("mirror", root, app, w2)
    assert read(os.path.join(p4mem, "b.md")) == "fact b, rewritten\n"
    assert read(os.path.join(p4mem, ".conflicts", "replaced", "b.md")) == "fact b\n", "the replaced file was lost"
    # an index line written into the pointer goes to the store's MEMORY.md, and the pointer is restored
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
    # a busy folder in the auto memory directory: its content reaches the store, its deletion waits for turn end
    held = os.path.join(app, "held")
    put(os.path.join(held, "y.md"), "fact y\n")
    if os.name == "nt":
        busy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"], cwd=held)
        try:
            out = run("migrate", root, app, {})
            assert "busy" in out and os.path.isdir(held), out
        finally:
            busy.kill()
            busy.wait()
    assert run("sweep", root, app, {}) == "", "turn end printed"
    assert not os.path.exists(held), "turn end did not delete the busy folder"
    assert read(os.path.join(p4mem, "held", "y.md")) == "fact y\n"
    assert only_pointer(app), os.listdir(app)
    assert run("sweep", root, app, {}) == "", "a clean turn end spoke"
    # a project dir with forward slashes, as a hook payload's cwd carries it
    root3 = os.path.join(base, "proj3")
    os.makedirs(os.path.join(root3, ".claude", "p4"))
    app3 = os.path.join(base, "appdata3", "projects", "slug", "memory")
    put(os.path.join(app3, "MEMORY.md"), "- [a](a.md) — a\n")
    run("migrate", root3.replace("\\", "/"), app3.replace("\\", "/"), {})
    assert read(os.path.join(root3, ".claude", "p4", "temportal", "memory", "MEMORY.md")) == "- [a](a.md) — a\n"
    assert only_pointer(app3)
    # the runner exits 0 on an unknown subcommand and on a missing script
    sh = shutil.which("sh")
    if sh:
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=root3,
                   P4_MEMORY_APPDATA=app3)
        assert subprocess.run([sh, RUNNER, "memory", "nope"], input=b"{}", env=env, capture_output=True).returncode == 0
        env["CLAUDE_PLUGIN_ROOT"] = base
        assert subprocess.run([sh, RUNNER, "memory", "migrate"], input=b"{}", env=env, capture_output=True).returncode == 0
    shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: behavior green")


def gate2_a():
    """The SessionStart output equals what Claude Code loads from a memory folder holding the same files, after at
    most one notice line: with nothing to move, with a move and a conflict, and with an index past the cut."""
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-start-")
    try:
        index = "".join(f"- [t{i}](t{i}.md) — topic {i}\n" for i in range(250))
        cases = {
            "quiet": ({}, {"MEMORY.md": "- [a](a.md) — a\n", "a.md": "fact a\n"}),
            "moved": ({"MEMORY.md": "- [a](a.md) — a\n- [b](b.md) — b\n", "b.md": "fact b\n", "a.md": "other a\n"},
                      {"a.md": "fact a\n"}),
            "long": ({}, {"MEMORY.md": index}),
            # under 200 lines but over 25KB: the byte cut decides
            "wide": ({}, {"MEMORY.md": "".join(f"- [w{i}](w{i}.md) — {'x' * 300}\n" for i in range(150))}),
            "empty": ({}, {}),
        }
        for name, (in_app, in_p4) in cases.items():
            root = os.path.join(base, name, "proj")
            app = os.path.join(base, name, "appdata", "memory")
            os.makedirs(app)
            os.makedirs(root, exist_ok=True)
            for rel, text in in_app.items():
                put(os.path.join(app, rel), text)
            for rel, text in in_p4.items():
                put(os.path.join(root, ".claude", "p4", "temportal", "memory", rel), text)
            out = run_raw("migrate", root, app).splitlines()
            # the same files in a plain memory folder, as Claude Code would load them after the move
            ref_dir = os.path.join(base, name, "builtin")
            shutil.copytree(os.path.join(root, ".claude", "p4", "temportal", "memory"), ref_dir,
                            ignore=shutil.ignore_patterns(".conflicts"))
            ref = builtin_print(ref_dir)
            extra = len(out) - len(ref)
            assert extra in (0, 1), f"{name}: {extra} extra lines\n" + "\n".join(out[:5])
            if extra:
                assert out[0].startswith("p4-temportal: ") and out[1:] == ref, \
                    f"{name}: the notice is not one line\n{out[:3]}"
            else:
                assert out == ref, f"{name}: output differs from what Claude Code loads\n{out[:3]}"
            if name == "quiet":
                assert extra == 0, "a start with nothing to move printed a notice"
            if name == "moved":
                assert extra == 1 and "moved" in out[0] and "differing files kept: 1" in out[0], out[0]
            if name == "long":
                assert len(out) == BUILTIN_LINES, len(out)
            if name == "wide":
                assert len("\n".join(out).encode("utf-8")) <= BUILTIN_BYTES and len(out) < 150, len(out)
            if name == "empty":
                assert out == [], out
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: start output green")


IMPERATIVE = re.compile(r"^(?:please\s+)?(?:do|don't|never|always|read|write|use|save|remember|keep|check|edit|"
                        r"update|store|put|load|consult|follow|make|ask|avoid|add|delete|move|see|note|ensure)\b", re.I)
MODAL = re.compile(r"\b(?:must|should|shall|have to|need to|never|always|do not|don't)\b", re.I)


def gate2_b():
    """The pointer says where the memory is and to write there, and has no other imperative sentence."""
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-pointer-")
    try:
        root, app = os.path.join(base, "proj"), os.path.join(base, "appdata", "memory")
        os.makedirs(root)
        run("migrate", root, app, {})
        p4 = os.path.normpath(os.path.join(root, ".claude", "p4", "temportal", "memory"))
        text = read(os.path.join(app, "MEMORY.md"))
        body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("<!--") and not ln.startswith("#")]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(body)) if s.strip()]
        imperative = [s for s in sentences if IMPERATIVE.match(s) or MODAL.search(s)]
        assert len(imperative) == 1, f"imperative sentences: {imperative}"
        only = imperative[0]
        assert only.lower().startswith("write ") and p4 in only, f"the one imperative is not where to write: {only}"
        assert any(p4 in s and s not in imperative for s in sentences), "the pointer does not say where the memory is"
        assert len(sentences) == 2, f"the pointer says more than where and to write there: {sentences}"
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: pointer words green")


def crlf_cut():
    """An index saved with CRLF lines is cut where its bytes on disk pass BUILTIN_BYTES: 151-byte lines keep 165."""
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-crlf-")
    try:
        root, app = os.path.join(base, "proj"), os.path.join(base, "appdata", "memory")
        os.makedirs(app)
        line = "- [c](c.md) " + "x" * (149 - 12) + "\r\n"
        assert len(line.encode("utf-8")) == 151
        path = os.path.join(root, ".claude", "p4", "temportal", "memory", "MEMORY.md")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(line * 190)
        out = [ln for ln in run_raw("migrate", root, app).splitlines() if ln.startswith("- [c]")]
        assert len(out) == BUILTIN_BYTES // 151, f"{len(out)} CRLF lines kept, {len(out) * 151} bytes on disk"
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("test_p4_memory.py: CRLF cut green")


def main():
    crlf_cut()
    behavior()
    gate2_a()
    gate2_b()
    print("test_p4_memory.py: all green")


if __name__ == "__main__":
    main()
