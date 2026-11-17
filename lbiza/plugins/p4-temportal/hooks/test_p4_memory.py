#!/usr/bin/env python3
"""test_p4_memory.py: acceptance tests for p4-temportal's memory part. The auto memory directory, or a link left in
its place, is merged into .claude/p4/temportal/memory/ and deleted, a differing file is kept in .conflicts/ and never
overwrites the store's, the auto memory directory keeps only the pointer MEMORY.md, a write into it is moved into the
store, a busy folder is left to turn end, and .claude/p4/ is made as a plain folder when absent. Then what a session
is given: the SessionStart output equals what Claude Code loads from a memory folder holding the same files, after at
most one notice line, and the pointer has no imperative sentence but the one that says where to write. Run from
anywhere: python3 hooks/test_p4_memory.py, and exit 0 is green."""

import atexit
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "p4_memory.py")
RUNNER = os.path.join(HERE, "run-hook.sh")
MARK = "<!-- p4-memory: pointer"
BUILTIN_LINES = 200         # the reference of what Claude Code loads, kept apart from p4_memory.py's constants so
BUILTIN_BYTES = 25_000      # that a change there fails here
STDOUT_CHARS = 10_000       # a hook's plain stdout past this reaches the session as a 2,000-character preview


SWITCHES = ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_PROJECT_DIR_NAME")
CONFIG = tempfile.mkdtemp(prefix="p4-temportal-memory-config-")
atexit.register(lambda: wipe(CONFIG))

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


def clean_env(**kw):
    """The environment without ezexe's auto memory switches, and with a config dir of the test's own, so neither the
    real settings nor the real environment decide a result."""
    env = {k: v for k, v in os.environ.items() if k not in SWITCHES}
    env["CLAUDE_CONFIG_DIR"] = CONFIG
    env["P4_MANAGED_SETTINGS"] = os.path.join(CONFIG, "no-managed-settings.json")
    env.update(kw)
    return env


def run(sub, root, app, payload):
    env = clean_env(CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
    r = subprocess.run([sys.executable, "-I", HOOK, sub], input=json.dumps(payload).encode("utf-8"), env=env,
                       capture_output=True, timeout=90)
    assert r.returncode == 0, r
    return r.stdout.decode("utf-8", "replace").strip()


def run_raw(sub, root, app):
    """The SessionStart output unstripped, as Claude Code receives it."""
    env = clean_env(CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
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
        env = clean_env(CLAUDE_PLUGIN_ROOT=os.path.dirname(HERE), CLAUDE_PROJECT_DIR=root3,
                   P4_MEMORY_APPDATA=app3)
        assert subprocess.run([sh, RUNNER, "memory", "nope"], input=b"{}", env=env, capture_output=True).returncode == 0
        env["CLAUDE_PLUGIN_ROOT"] = base
        assert subprocess.run([sh, RUNNER, "memory", "migrate"], input=b"{}", env=env, capture_output=True).returncode == 0
    wipe(base)
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
            # under both of Claude Code's cuts but over the 10,000 characters a hook's stdout reaches the session with
            "between": ({}, {"MEMORY.md": "".join(f"- [m{i}](m{i}.md) — {'y' * 100}\n" for i in range(120))}),
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
            raw = run_raw("migrate", root, app)
            assert len(raw) <= STDOUT_CHARS, f"{name}: {len(raw)} characters reach the session as a preview"
            out = raw.splitlines()
            cut = [ln for ln in out if ln.startswith("p4-temportal: MEMORY.md cut")]
            if cut:                                     # the cut is said once, after the index
                assert out[-1] == cut[0] and len(cut) == 1, f"{name}: the cut line is not last\n{out[-2:]}"
                out = out[:-1]
            # the same files in a plain memory folder, as Claude Code would load them after the move
            ref_dir = os.path.join(base, name, "builtin")
            shutil.copytree(os.path.join(root, ".claude", "p4", "temportal", "memory"), ref_dir,
                            ignore=shutil.ignore_patterns(".conflicts"))
            ref = builtin_print(ref_dir)
            extra = 1 if out and out[0].startswith("p4-temportal: ") else 0
            body = out[extra:]
            total = len(read(os.path.join(ref_dir, "MEMORY.md")).splitlines()) if ref else 0
            assert body == ref[:len(body)], f"{name}: output differs from what Claude Code loads\n{out[:3]}"
            index = os.path.normpath(os.path.join(root, ".claude", "p4", "temportal", "memory", "MEMORY.md"))
            if len(body) < total:
                assert cut and f"{total - len(body)} of {total} lines left out" in cut[0] and index in cut[0], \
                    f"{name}: {total - len(body)} lines left out without a word: {cut}"
            else:
                assert not cut, f"{name}: a whole index was said to be cut: {cut}"
            if name == "quiet":
                assert extra == 0, "a start with nothing to move printed a notice"
            if name == "moved":
                assert extra == 1 and "moved" in out[0] and "differing files kept: 1" in out[0], out[0]
            if name == "long":
                assert len(out) == BUILTIN_LINES, len(out)
            if name == "wide":
                assert len("\n".join(out).encode("utf-8")) <= BUILTIN_BYTES and len(out) < 150, len(out)
            if name == "between":
                assert len(body) < 120 and cut, len(body)
            if name == "empty":
                assert out == [], out
    finally:
        wipe(base)
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
        wipe(base)
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
        sys.path.insert(0, HERE)
        import p4_memory
        out, _ = p4_memory.builtin_index(os.path.dirname(path))
        assert len(out) == BUILTIN_BYTES // 151, f"{len(out)} CRLF lines kept, {len(out) * 151} bytes on disk"
    finally:
        wipe(base)
    print("test_p4_memory.py: CRLF cut green")


def repo_key():
    """The auto memory directory is keyed by the git repository, so a worktree and a subdirectory find the main
    checkout's; CLAUDE_CODE_PROJECT_DIR_NAME names it instead, and autoMemoryDirectory moves it."""
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-key-")
    keys = ("P4_MEMORY_APPDATA", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_PROJECT_DIR_NAME", "CLAUDE_PROJECT_DIR")
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        sys.path.insert(0, HERE)
        import p4_memory
        config = os.path.join(base, "config")
        os.environ["CLAUDE_CONFIG_DIR"] = config
        main_ = os.path.join(base, "repo")
        os.makedirs(os.path.join(main_, ".git", "worktrees", "wt"))
        put(os.path.join(main_, ".git", "worktrees", "wt", "commondir"), "../..\n")
        wt = os.path.join(base, "wt")
        put(os.path.join(wt, ".git"), f"gitdir: {os.path.join(main_, '.git', 'worktrees', 'wt')}\n")
        sub = os.path.join(main_, "src")
        os.makedirs(sub)
        want = os.path.join(config, "projects", p4_memory.project_slug(main_), "memory")
        wt_transcript = os.path.join(config, "projects", p4_memory.project_slug(wt), "s.jsonl")
        for where, payload in ((main_, {}), (sub, {}), (wt, {}), (wt, {"transcript_path": wt_transcript})):
            got = p4_memory.appdata_memory(payload, where)
            assert os.path.normpath(got) == os.path.normpath(want), f"{where} {payload}: {got}, not {want}"
        os.environ["CLAUDE_CODE_PROJECT_DIR_NAME"] = "named"
        got = p4_memory.appdata_memory({}, wt)
        assert os.path.normpath(got) == os.path.join(config, "projects", "named", "memory"), got
        del os.environ["CLAUDE_CONFIG_DIR"]             # without it Claude Code ignores the name
        got = p4_memory.appdata_memory({}, wt)
        assert os.path.basename(os.path.dirname(got)) == p4_memory.project_slug(main_), f"the name was used: {got}"
        os.environ["CLAUDE_CONFIG_DIR"] = config
        del os.environ["CLAUDE_CODE_PROJECT_DIR_NAME"]
        put(os.path.join(wt, ".claude", "settings.local.json"), json.dumps({"autoMemoryDirectory": "~/moved"}))
        got = p4_memory.appdata_memory({}, wt)
        assert os.path.normpath(got) == os.path.join(os.path.expanduser("~"), "moved"), got
        # the main checkout writes the shared folder's pointer; a subdirectory and a worktree leave it and its files
        shared = os.path.join(base, "shared", "memory")
        put(os.path.join(main_, ".claude", "p4", "temportal", "memory", "MEMORY.md"), "- [m](m.md) — m\n")
        run("migrate", main_, shared, {})
        pointer = read(os.path.join(shared, "MEMORY.md"))
        assert os.path.normpath(os.path.join(main_, ".claude", "p4", "temportal", "memory")) in pointer, pointer
        put(os.path.join(shared, "n.md"), "fact n\n")
        for other in (sub, wt):
            run("migrate", other, shared, {})
            w = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(shared, "n.md")}}
            run("mirror", other, shared, w)
            run("sweep", other, shared, {})
            assert read(os.path.join(shared, "MEMORY.md")) == pointer, f"{other} rewrote the main checkout's pointer"
            assert os.path.isfile(os.path.join(shared, "n.md")), f"{other} moved a file into its own store"
        os.remove(os.path.join(shared, "n.md"))
        # a worktree start prints the store its pointer names, the main checkout's, not a store of its own
        put(os.path.join(wt, ".claude", "p4", "temportal", "memory", "MEMORY.md"), "- [w](w.md) — w\n")
        out = run("migrate", wt, shared, {})
        assert "- [m](m.md) — m" in out and "- [w]" not in out, f"a worktree start printed another store\n{out}"
        assert not out.startswith("p4-temportal: "), f"a warning with the block off\n{out}"
        put(os.path.join(sub, ".claude", "p4", "temportal", "memory", "MEMORY.md"), "- [s](s.md) — s\n")
        out = run("migrate", sub, shared, {})
        assert out == "- [m](m.md) — m", f"a subdirectory start printed another store, or warned\n{out}"
        main_store = os.path.normpath(os.path.join(main_, ".claude", "p4", "temportal", "memory"))

        def warned(out, where):
            return any(ln.startswith("p4-temportal: ") and main_store in ln and f"outside {where}" in ln and
                       "blockWritesOutsideWorkingDirectories" in ln for ln in out.splitlines())

        # the block set in the user file, under a local file holding only allow rules, is still said
        user = os.path.join(CONFIG, "settings.json")
        put(user, json.dumps({"permissions": {"blockWritesOutsideWorkingDirectories": True}}))
        for where in (wt, sub):
            put(os.path.join(where, ".claude", "settings.local.json"), json.dumps({"permissions": {"allow": ["Read"]}}))
        try:
            assert warned(run("migrate", wt, shared, {}), "this checkout"), "a user block under a local file was missed"
            assert warned(run("migrate", sub, shared, {}), "this working directory"), "a subdirectory was not named"
            # a store under, or exactly at, a user additional directory is inside
            for added in (main_, main_store):
                put(user, json.dumps({"permissions": {"blockWritesOutsideWorkingDirectories": True,
                                                      "additionalDirectories": [added]}}))
                assert not run("migrate", wt, shared, {}).startswith("p4-temportal: "), f"{added} was outside"
            # autoMemoryDirectory naming the main store from user settings: its .md files stay writable, no warning;
            # the same choice made by a repository file is refused, so it is said
            block = {"blockWritesOutsideWorkingDirectories": True}
            put(user, json.dumps({"permissions": block, "autoMemoryDirectory": main_store}))
            assert not run("migrate", wt, main_store, {}).startswith("p4-temportal: "), "a user-chosen folder warned"
            put(os.path.join(wt, ".claude", "settings.local.json"), json.dumps({"autoMemoryDirectory": main_store}))
            assert warned(run("migrate", wt, main_store, {}), "this checkout"), "a repository-chosen folder was not said"
            os.remove(user)
            # a managed file that cannot be read fails closed
            managed = os.path.join(base, "managed-settings.json")
            put(managed, "{not json")
            env = clean_env(CLAUDE_PROJECT_DIR=wt, P4_MEMORY_APPDATA=shared, P4_MANAGED_SETTINGS=managed)
            r = subprocess.run([sys.executable, "-I", HOOK, "migrate"], input=b"{}", env=env, capture_output=True)
            assert warned(r.stdout.decode("utf-8", "replace"), "this checkout"), "an unreadable managed file was missed"
        finally:
            if os.path.exists(user):
                os.remove(user)
            for where in (wt, sub):
                os.remove(os.path.join(where, ".claude", "settings.local.json"))
        # autoMemoryDirectory set to the store itself: the index stays, no pointer is written over it
        store = os.path.join(main_, ".claude", "p4", "temportal", "memory")
        put(os.path.join(store, "MEMORY.md"), "- [a](a.md) — a\n")
        assert run("migrate", main_, store, {}) == "- [a](a.md) — a" and read(os.path.join(store, "MEMORY.md")) == \
            "- [a](a.md) — a\n", "the store's index was replaced by the pointer"
        run("sweep", main_, store, {})
        assert read(os.path.join(store, "MEMORY.md")) == "- [a](a.md) — a\n", "turn end wrote over the store's index"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        wipe(base)
    print("test_p4_memory.py: repository key green")


def switched_off():
    """With autoMemoryEnabled false, CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 or CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 the memory
    part writes no pointer, moves nothing and prints no index; CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 turns it on over
    the setting."""
    base = tempfile.mkdtemp(prefix="p4-temportal-memory-off-")
    try:
        for how in ("env", "mds", "settings", "forced on"):
            root, app = os.path.join(base, how, "proj"), os.path.join(base, how, "appdata", "memory")
            put(os.path.join(app, "a.md"), "fact a\n")
            put(os.path.join(root, ".claude", "p4", "temportal", "memory", "MEMORY.md"), "- [a](a.md) — a\n")
            env = clean_env(CLAUDE_PROJECT_DIR=root, P4_MEMORY_APPDATA=app)
            if how == "env":
                env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "True"
            elif how == "mds":
                env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "YES"
            else:
                put(os.path.join(root, ".claude", "settings.local.json"), json.dumps({"autoMemoryEnabled": False}))
            if how == "forced on":
                env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "off"
            for sub in ("migrate", "sweep"):
                r = subprocess.run([sys.executable, "-I", HOOK, sub], input=b"{}", env=env, capture_output=True,
                                   timeout=90)
                out = r.stdout.decode("utf-8", "replace")
                assert r.returncode == 0, r
                if how == "forced on" and sub == "migrate":
                    assert "- [a]" in out, f"{how}: the index was not printed\n{out}"
                elif how != "forced on":
                    assert "- [a]" not in out, f"{how} {sub}: the index was printed\n{out}"
            if how == "forced on":
                assert only_pointer(app), f"{how}: the auto memory directory was not migrated: {os.listdir(app)}"
            else:
                assert os.listdir(app) == ["a.md"], f"{how}: the auto memory directory was touched: {os.listdir(app)}"
    finally:
        wipe(base)
    print("test_p4_memory.py: switched off green")


class FailureNotice(unittest.TestCase):
    """A failure on Stop, PreToolUse or PostToolUse, where plain stdout reaches nobody, is a systemMessage."""

    def test_a_degraded_or_unknown_subcommand_prints_a_system_message(self):
        import contextlib
        import io
        sys.path.insert(0, HERE)
        import p4_memory
        root = tempfile.mkdtemp(prefix="p4-temportal-memory-fail-")
        old = (p4_memory.cmd_sweep, p4_memory.auto_memory_off, sys.argv, sys.stdin)
        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            p4_memory.cmd_sweep, p4_memory.auto_memory_off = broken, lambda *a: False
            for sub, want in (("sweep", "memory sweep degraded: OSError: disk gone"), ("nope", "unknown subcommand")):
                sys.argv = ["p4_memory.py", sub]
                sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps({"cwd": root, "hook_event_name": "Stop"}).encode()))
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(p4_memory.main(), 0)
                self.assertIn(want, json.loads(out.getvalue())["systemMessage"])
        finally:
            p4_memory.cmd_sweep, p4_memory.auto_memory_off, sys.argv, sys.stdin = old
            wipe(root)


class Cases(unittest.TestCase):
    """Each case group a test method, so unittest and pytest collect them."""

    def test_switched_off(self):
        switched_off()

    def test_repo_key(self):
        repo_key()

    def test_crlf_cut(self):
        crlf_cut()

    def test_behavior(self):
        behavior()

    def test_gate2_a(self):
        gate2_a()

    def test_gate2_b(self):
        gate2_b()


if __name__ == "__main__":
    unittest.main(verbosity=1)
