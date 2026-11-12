#!/usr/bin/env python3
"""p4_memory.py — the p4-temportal plugin's memory part: Claude Code's built-in per-project memory is stored in the p4 repo,
`<project>/.claude/p4/temportal/memory/`, and nowhere else. A storage move only: nothing here tells the model how to behave.

The harness loads and names memories at `~/.claude/projects/<project-slug>/memory/` (AppData). This plugin empties
that directory into p4 and leaves one file there, a pointer `MEMORY.md` that says where the memory is and to write
there. The rest of `~/.claude/projects/<project-slug>/` (transcripts, per-session directories) is never touched.
`.claude/p4/` is created when absent (a plain directory; p4-recall's layout hook makes it a git repository).

  migrate (SessionStart)  every AppData memory source (the `memory/` directory, a junction or symlink an earlier
                          version left, every `memory.pre-p4-<time>` directory) is merged into `.claude/p4/temportal/memory/`
                          and deleted: identical in p4 -> dropped; a live file absent in p4 -> moved in; any other ->
                          kept at `.conflicts/<source>/<path>`, never overwriting the p4 file. A link to p4 is removed
                          as a link. Then the pointer is written and the p4 `MEMORY.md` is printed as the built-in
                          prints its own (the first BUILTIN_LINES lines), plus at most one notice line when a file
                          was moved or a conflict kept.
  mirror (PostToolUse)    a Write or Edit into the AppData memory directory is moved into p4 at once (a p4 file it
                          replaces kept in `.conflicts/replaced/`; index lines added to the pointer appended to the
                          p4 `MEMORY.md`, the pointer restored); one line says where it went.
  sweep (Stop)            whatever the start could not delete is tried again; prints nothing. `relink` is accepted
                          as its old name.

Every failure prints a one-line notice and exits 0.
"""

import filecmp
import glob
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402  (the settings file, .claude/p4/p4.json)

MEMORY = "memory"
CONFLICTS = ".conflicts"
POINTER_MARK = "<!-- p4-memory: pointer"
BUILTIN_LINES = 200          # the built-in loads the first 200 lines of MEMORY.md, or the first 25KB, whichever
BUILTIN_BYTES = 25_000       # comes first (docs: memory); "25KB" is 25,000 bytes cut at whole lines, as measured
                             # twice on Claude Code 2.1.309 by test_live_memory_limit.py (2026-11-01: M166 both runs)
RETRIES = 5
RETRY_WAIT_S = 1.0


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def configure(payload):
    """The memory section of <project>/.claude/p4/p4.json over the constants (the file written when missing)."""
    p4 = os.path.join(project_root(payload), ".claude", "p4")
    p4conf.configure(globals(), p4, "memory", {"retries": "RETRIES", "retry_wait_s": "RETRY_WAIT_S"})


def layout(payload):
    """A store an older plugin wrote flat in .claude/p4 is moved into each plugin's directory first."""
    lines = p4conf.migrate_layout(os.path.join(project_root(payload), ".claude", "p4"))
    if lines:
        print("p4-temportal: " + "; ".join(lines) + ".")


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
    return p4conf.sub(os.path.join(root, ".claude", "p4"), "memory")


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
    return (f"{POINTER_MARK} -->\n"
            f"# Memory location\n\n"
            f"This project's memory is stored in `{p}`.\n"
            f"Write memory files and their `MEMORY.md` index lines in `{p}`.\n")


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
            return [f"{app} is a link that does not reach .claude/p4/temportal/memory/; left as it is, nothing moved"], False
        if not retry(remove_link, app):
            return [f"{app} is a link to .claude/p4/temportal/memory/ and is busy, retried at the turn's close"], False
        lines.append(f"removed the link {app} -> .claude/p4/temportal/memory/ (its target untouched)")
    sources = [app] if os.path.isdir(app) else []
    sources += sorted(d for d in glob.glob(glob.escape(app) + ".pre-p4-*") if os.path.isdir(d) and not is_link(d))
    moved, aside, left = [], [], []
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
                pass                                    # identical in p4: dropped
            elif live and not os.path.exists(dst) and rel.split(os.sep)[0] != CONFLICTS:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                moved.append(rel)
            else:
                keep_aside(p4, name, rel, src, stamp)
                aside.append(f"{name}/{rel}")
        ok = empty_live_dir(src_dir) if live else retry(shutil.rmtree, src_dir)
        if not ok:
            left.append(src_dir)
    try:
        write_pointer(app, p4)
    except OSError as e:
        lines.append(f"could not write the pointer MEMORY.md in {app} ({e})")
    if moved:
        lines.append(f"moved {len(moved)} memory file(s) from AppData into .claude/p4/temportal/memory/")
    if aside:
        lines.append(f"kept {len(aside)} differing file(s) in .claude/p4/temportal/memory/.conflicts/ ("
                     + ", ".join(aside[:5]) + (", …" if len(aside) > 5 else "") + ")")
    if left:
        lines.append(f"{', '.join(map(os.path.basename, left))} busy, retried at the turn's close")
    return lines, not left


def builtin_index(memdir):
    """What the built-in prints from a memory directory: the first BUILTIN_LINES lines of its MEMORY.md, or the first
    BUILTIN_BYTES cut at a whole line, whichever comes first (https://code.claude.com/docs/en/memory: "The first 200
    lines of `MEMORY.md`, or the first 25KB, whichever comes first"; the byte value and the whole-line cut are measured
    by test_live_memory_limit.py)."""
    index = os.path.join(memdir, "MEMORY.md")
    if not os.path.isfile(index):
        return ""
    with open(index, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[:BUILTIN_LINES]
    kept, size = [], 0
    for line in lines:
        size += len(line.encode("utf-8"))
        if size > BUILTIN_BYTES:
            break
        kept.append(line)
    return "".join(kept)


def notice(parts):
    return ("p4-temportal: " + "; ".join(parts) + ".") if parts else ""


def cmd_migrate(payload):
    root = project_root(payload)
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    parts, _ = migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    out = notice(parts)
    if out:
        print(out)
    index = builtin_index(p4)          # the harness loaded only the pointer: print what it would have printed
    if index:
        sys.stdout.write(index if index.endswith("\n") else index + "\n")
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
    if is_link(app):
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
        note = (f"p4-temportal: {len(add)} index line(s) written to the AppData MEMORY.md were appended to "
                f"{os.path.normpath(dst)}; the AppData file is the pointer again.")
    else:
        if os.path.isfile(dst) and not filecmp.cmp(fp, dst, shallow=False):
            keep_aside(p4, "replaced", rel, dst, stamp)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(fp, dst)
        retry(os.remove, fp)
        note = f"p4-temportal: {fp} was moved to {os.path.normpath(dst)}."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}))
    return 0


def cmd_sweep(payload):
    """Stop: whatever the start could not move or delete is tried again at the turn's close. Prints nothing."""
    root = project_root(payload)
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    pending = is_link(app) or glob.glob(glob.escape(app) + ".pre-p4-*") or (
        os.path.isdir(app) and any(n != "MEMORY.md" or not is_pointer(os.path.join(app, n)) for n in os.listdir(app)))
    if pending or not os.path.isdir(app):
        migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        configure(payload)
        if sub == "migrate":
            layout(payload)
            return cmd_migrate(payload)
        if sub == "mirror":
            return cmd_mirror(payload)
        if sub in ("sweep", "relink"):
            return cmd_sweep(payload)
        print(f"p4_memory.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-temportal memory ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
