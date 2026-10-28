#!/usr/bin/env python3
"""p4_memory.py — the p4-memory plugin's mechanical half: the built-in per-project memory (the base class the
vlds override wraps) is stored in the p4 repo, `<project>/.claude/p4/memory/`, and nowhere else.

The harness loads and names base memories at `~/.claude/projects/<project-slug>/memory/` — the device's local
AppData on Windows — and that path is fixed by the system prompt. This plugin empties it: every memory moves into
p4, and the AppData directory keeps one file, a pointer `MEMORY.md` telling the session where its memory is and
where to write it. The rest of `~/.claude/projects/<project-slug>/` (the harness's transcripts and per-session
directories) is the harness's own and is never touched.

  migrate (SessionStart)  every AppData memory source — the `memory/` directory, a junction or symlink an earlier
                          version left there, and every `memory.pre-p4-<time>` directory it renamed aside — is
                          merged into `.claude/p4/memory/` and then deleted: a file identical in p4 → dropped; a
                          file of the live `memory/` absent in p4 → moved in; any other (a differing file, or one a
                          renamed-aside directory still holds that p4 no longer does) → kept in p4 at
                          `.conflicts/<source>/<path>` for the owner's merge, never overwriting the p4 file. A link
                          to p4 is removed as a link (its target untouched). Then the pointer `MEMORY.md` is written
                          in AppData and the p4 `MEMORY.md` is printed, since the harness loaded only the pointer.
                          The harness can hold the directory open while a session starts, so a deletion is retried,
                          and on failure left to the turn's close.
  mirror (PostToolUse)    a Write or Edit into the AppData memory directory is moved into p4 at once — the
                          harness's own write is never refused: a memory file lands at the same path in p4 (a p4
                          file it replaces kept in `.conflicts/`), lines added to the pointer are appended to the
                          p4 `MEMORY.md`, and the pointer is restored; the session is told where the file went.
  sweep (Stop)            whatever the start could not delete is tried again at the turn's close — silent unless
                          it moved something. `relink`, its name before 0.0.4, is still accepted.

Every failure prints a one-line notice and exits 0 — a hook that crashes the call it guards is worse than none.
"""

import filecmp
import glob
import json
import os
import re
import shutil
import sys
import time

MEMORY = "memory"
CONFLICTS = ".conflicts"
POINTER_MARK = "<!-- p4-memory: pointer"
RETRIES = 5
RETRY_WAIT_S = 1.0


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def project_slug(root):
    """The harness's directory name for a project: every character outside [A-Za-z0-9] becomes a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(root))


def appdata_memory(payload, root):
    """`~/.claude/projects/<slug>/memory` — read from the transcript's own directory when the payload names it."""
    if os.environ.get("P4_MEMORY_APPDATA"):          # tests and odd installs point it elsewhere
        return os.environ["P4_MEMORY_APPDATA"]
    tp = str(payload.get("transcript_path") or "")
    if tp:
        return os.path.join(os.path.dirname(tp), MEMORY)
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(home, "projects", project_slug(root), MEMORY)


def p4_memory(root):
    return os.path.join(root, ".claude", "p4", MEMORY)


def same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def is_link(path):
    """A symlink or a Windows junction."""
    if os.path.islink(path):
        return True
    isj = getattr(os.path, "isjunction", None)        # 3.12+
    if isj:
        return isj(path)
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)   # FILE_ATTRIBUTE_REPARSE_POINT
    except (OSError, AttributeError):
        return False


def remove_link(path):
    """Remove a symlink or junction itself — never what it points at (rmtree would follow a junction)."""
    if os.path.islink(path):
        os.unlink(path)
    else:
        os.rmdir(path)                                  # a junction: RemoveDirectory drops the reparse point only


def pointer_text(p4):
    p = os.path.normpath(p4)
    return (f"{POINTER_MARK} — rewritten at every session start; anything written in this directory is moved into "
            f"the p4 store -->\n"
            f"# This project's memory lives in the p4 repo\n\n"
            f"This directory is not the memory store; it holds only this pointer.\n"
            f"The memory store is `{p}` — its `MEMORY.md` index is printed by the p4-memory SessionStart hook, and "
            f"every memory file is read there.\n"
            f"Write every memory file and its `MEMORY.md` index line in `{p}`, never in this directory.\n"
            f"A file written here anyway is moved into `{p}` by the p4-memory PostToolUse hook, and this pointer is "
            f"restored.\n")


def is_pointer(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(len(POINTER_MARK)) == POINTER_MARK
    except OSError:
        return False


def write_pointer(app, p4):
    os.makedirs(app, exist_ok=True)
    path = os.path.join(app, "MEMORY.md")
    text = pointer_text(p4)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def files_in(base, skip_conflicts):
    out = []
    for d, dirs, files in os.walk(base):
        if skip_conflicts:
            dirs[:] = [x for x in dirs if x != CONFLICTS]
        for name in files:
            out.append(os.path.relpath(os.path.join(d, name), base))
    return sorted(out)


def keep_aside(p4, source, rel, src, stamp):
    """Copy src into p4's .conflicts/<source>/<rel>; an identical copy already there is enough, a different one
    gets the stamp appended so nothing kept earlier is overwritten."""
    side = os.path.join(p4, CONFLICTS, source, rel)
    if os.path.isfile(side):
        if filecmp.cmp(src, side, shallow=False):
            return side
        side = f"{side}.{stamp}"
    os.makedirs(os.path.dirname(side), exist_ok=True)
    shutil.copy2(src, side)
    return side


def retry(fn, *args):
    for attempt in range(RETRIES):
        try:
            fn(*args)
            return True
        except OSError:
            if attempt == RETRIES - 1:
                return False
            time.sleep(RETRY_WAIT_S)
    return False


def empty_live_dir(app):
    """Delete everything in the live AppData memory directory but the pointer — the directory itself stays, since
    the harness may hold it open and loads MEMORY.md from it."""
    ok = True
    for name in os.listdir(app):
        path = os.path.join(app, name)
        if name == "MEMORY.md" and is_pointer(path):
            continue
        if os.path.isdir(path) and not is_link(path):
            ok = retry(shutil.rmtree, path) and ok
        elif is_link(path):
            ok = retry(remove_link, path) and ok
        else:
            ok = retry(os.remove, path) and ok
    return ok


def migrate(app, p4, stamp):
    """-> (lines to print, done?) — done when no AppData memory source is left but the pointer."""
    lines = []
    os.makedirs(p4, exist_ok=True)
    if is_link(app):
        if not same_dir(app, p4):                       # a link somewhere else: the owner's arrangement
            return [f"p4-memory: {app} is a link that does not reach {p4} — left as it is; base memories are not "
                    f"moved into p4 until it is removed."], False
        if not retry(remove_link, app):
            return [f"p4-memory: {app} is a link to the p4 store and is busy — the turn's close removes it."], False
        lines.append(f"p4-memory: removed the link {app} → .claude/p4/memory/ (its target untouched).")
    sources = [app] if os.path.isdir(app) else []
    sources += sorted(d for d in glob.glob(glob.escape(app) + ".pre-p4-*") if os.path.isdir(d) and not is_link(d))
    moved, aside, dropped, left, emptied = [], [], 0, [], []
    for src_dir in sources:
        live = src_dir == app
        name = os.path.basename(src_dir)
        if live and all(n == "MEMORY.md" and is_pointer(os.path.join(app, n)) for n in os.listdir(app)):
            continue                                    # only the pointer: nothing to move
        for rel in files_in(src_dir, skip_conflicts=False):
            src, dst = os.path.join(src_dir, rel), os.path.join(p4, rel)
            if live and rel == "MEMORY.md" and is_pointer(src):
                continue
            if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
                dropped += 1
            elif live and not os.path.exists(dst) and rel.split(os.sep)[0] != CONFLICTS:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                moved.append(rel)
            else:
                keep_aside(p4, name, rel, src, stamp)
                aside.append(f"{name}/{rel}")
        ok = empty_live_dir(src_dir) if live else retry(shutil.rmtree, src_dir)
        (emptied if ok else left).append(src_dir)
    if moved:
        lines.append(f"p4-memory: moved {len(moved)} base memory file(s) from AppData into .claude/p4/memory/.")
    if aside:
        lines.append(f"p4-memory: {len(aside)} file(s) differ from p4 or are no longer in it ("
                     + ", ".join(aside[:5]) + (", …" if len(aside) > 5 else "")
                     + ") — kept in .claude/p4/memory/.conflicts/ for the owner's merge; the p4 files were not "
                       "overwritten.")
    if emptied:
        lines.append(f"p4-memory: emptied the AppData memory ({', '.join(map(os.path.basename, emptied))}; {dropped} file(s) already "
                     f"identical in p4) — it now holds only the pointer MEMORY.md.")
    if left:
        lines.append(f"p4-memory: {', '.join(left)} could not be deleted (busy) — its content is in p4; the turn's "
                     f"close tries again.")
    try:
        write_pointer(app, p4)
    except OSError as e:
        lines.append(f"p4-memory: could not write the pointer MEMORY.md in {app}: {e}")
        return lines, False
    return lines, not left


def cmd_migrate(payload):
    root = project_root(payload)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")):
        return 0                                        # no p4 repo here: nothing to store into
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    lines, _ = migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    if lines:
        print("\n".join(lines))
    index = os.path.join(p4, "MEMORY.md")
    if os.path.isfile(index):                           # the harness loaded only the pointer
        with open(index, encoding="utf-8", errors="replace") as f:
            print(f"\n### p4 base memory index ({os.path.normpath(index)}) — the session's MEMORY.md; the harness "
                  f"loaded only the AppData pointer. Read and write memories in {os.path.normpath(p4)}.\n\n"
                  + f.read()[:8000])
    return 0


def norm(path):
    return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))


def added_index_lines(text, p4):
    """Lines a write put into the pointer that the pointer itself does not carry."""
    stock = set(pointer_text(p4).splitlines())
    return [ln for ln in text.splitlines() if ln.strip() and ln not in stock and not ln.startswith(POINTER_MARK)]


def cmd_mirror(payload):
    """PostToolUse: a memory written into the AppData directory is moved into p4 at once — the harness's own write
    is never refused, and nothing it writes stays there."""
    inp = payload.get("tool_input") or {}
    fp = str(inp.get("file_path") or "") if isinstance(inp, dict) else ""
    if not fp:
        return 0
    root = project_root(payload)
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")) or is_link(app):
        return 0
    n_app, n_fp = norm(app), norm(fp)
    if not n_fp.startswith(n_app + os.sep) or not os.path.isfile(fp):
        return 0
    rel = os.path.relpath(n_fp, n_app)
    dst = os.path.join(p4, rel)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if rel.lower() == "memory.md":
        with open(fp, encoding="utf-8", errors="replace") as f:
            new = added_index_lines(f.read(), p4)
        old = ""
        if os.path.isfile(dst):
            with open(dst, encoding="utf-8", errors="replace") as f:
                old = f.read()
        have = set(old.splitlines())
        add = [ln for ln in new if ln not in have]
        if add:
            os.makedirs(p4, exist_ok=True)
            with open(dst, "a", encoding="utf-8", newline="\n") as f:
                f.write(("\n" if old and not old.endswith("\n") else "") + "\n".join(add) + "\n")
        write_pointer(app, p4)
        note = (f"p4-memory: {len(add)} index line(s) written into the AppData pointer were appended to "
                f"{os.path.normpath(dst)} and the pointer restored — edit that MEMORY.md, never the AppData one.")
    else:
        if os.path.isfile(dst) and not filecmp.cmp(fp, dst, shallow=False):
            keep_aside(p4, "replaced", rel, dst, stamp)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(fp, dst)
        retry(os.remove, fp)
        note = (f"p4-memory: {fp} was moved to {os.path.normpath(dst)} — the memory store is "
                f"{os.path.normpath(p4)}; read and edit it there.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}))
    return 0


def cmd_sweep(payload):
    """Stop: whatever the start could not move or delete is tried again at the turn's close — silent unless it
    did something."""
    root = project_root(payload)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")):
        return 0
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    pending = is_link(app) or glob.glob(glob.escape(app) + ".pre-p4-*") or (
        os.path.isdir(app) and any(n != "MEMORY.md" or not is_pointer(os.path.join(app, n)) for n in os.listdir(app)))
    if not pending and os.path.isdir(app):
        return 0
    lines, _ = migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    if lines:
        print("\n".join(lines))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        if sub == "migrate":
            return cmd_migrate(payload)
        if sub == "mirror":
            return cmd_mirror(payload)
        if sub in ("sweep", "relink"):
            return cmd_sweep(payload)
        print(f"p4_memory.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-memory ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
