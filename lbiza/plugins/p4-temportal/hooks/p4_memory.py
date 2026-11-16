#!/usr/bin/env python3
"""p4_memory.py: p4-temportal's memory part, which keeps the project's auto memory in the store's
`<project>/.claude/p4/temportal/memory/` and nowhere else. It moves files, and it tells the model only where to write.

Claude Code loads auto memory from the auto memory directory, `~/.claude/projects/<project>/memory/` under the
configuration directory. This part moves every file of that directory into the store's memory folder and leaves one
file there, a pointer `MEMORY.md` that says where the memory is and to write there. The rest of
`~/.claude/projects/<project>/`, transcripts and per-session folders, is never touched. `.claude/p4/` is made as a
plain folder when absent, and p4-phi makes it a git repository.

  migrate    at SessionStart, merges the auto memory directory into `.claude/p4/temportal/memory/` and deletes what
             it merged: a file identical in the store is dropped, a file the store lacks is moved in, and any other is
             kept at `.conflicts/memory/<path>` without overwriting the store's file. A link left in place of the
             directory is removed as a link when it reaches the store's memory folder, never followed, and left as it
             is when it points elsewhere. Then it writes the pointer and prints the store's `MEMORY.md` as Claude Code
             would load it, after one notice line when a file was moved or kept aside. When the store's layout moved
             at this start, that line comes first.
  mirror     at PostToolUse, moves a Write or Edit into the auto memory directory into the store at once: a store
             file it replaces is kept in `.conflicts/replaced/`, index lines added to the pointer are appended to the
             store's `MEMORY.md` and the pointer is restored, and one line says where the file went.
  sweep      at Stop, tries again to delete what the start could not, and prints nothing.

Every failure prints a one-line notice and exits 0.
"""

import filecmp
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json

MEMORY = "memory"
CONFLICTS = ".conflicts"
POINTER_MARK = "<!-- p4-memory: pointer"    # a format the pointer files on disk carry, kept as it is
BUILTIN_LINES = 200          # Claude Code loads the first 200 lines of MEMORY.md or its first 25KB, whichever comes
BUILTIN_BYTES = 25_000       # first, by https://code.claude.com/docs/en/memory, and test_live_memory_limit.py
                             # measures 25KB as 25,000 bytes cut at a whole line
STDOUT_CHARS = 10_000        # a hook's plain stdout past this reaches the session as a file path and a 2,000-character
                             # preview, by https://code.claude.com/docs/en/hooks, section JSON output
RETRIES = 5
RETRY_WAIT_S = 1.0


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def configure(payload):
    """The memory section of <project>/.claude/p4/p4.json over the constants, writing the file when it is missing."""
    p4 = os.path.join(project_root(payload), ".claude", "p4")
    p4conf.configure(globals(), p4, "memory", {"retries": "RETRIES", "retry_wait_s": "RETRY_WAIT_S"})


def layout(payload):
    """Files in an earlier place of the store's layout are moved into each plugin's folder first. -> the line saying
    so, which cmd_migrate prints first and counts in its STDOUT_CHARS."""
    lines = p4conf.migrate_layout(os.path.join(project_root(payload), ".claude", "p4"))
    return ("p4-temportal: " + "; ".join(lines) + ".\n") if lines else ""


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def project_slug(root):
    """Claude Code's folder name for a project under `projects/`: every character outside [A-Za-z0-9] is a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(root))


def repo_root(root):
    """The main checkout of the git repository holding root, read from the `.git` files without running git: a
    worktree's `.git` file names its gitdir, whose `commondir` leads to the main `.git`. Outside a repository, root."""
    d = os.path.abspath(root)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.isdir(dot):
            return d
        if os.path.isfile(dot):
            try:
                with open(dot, encoding="utf-8", errors="replace") as f:
                    gitdir = f.read().strip().split("gitdir:", 1)[1].strip()
                gitdir = os.path.normpath(os.path.join(d, gitdir))
                with open(os.path.join(gitdir, "commondir"), encoding="utf-8", errors="replace") as f:
                    common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
                return os.path.dirname(common)
            except (OSError, IndexError):
                return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.abspath(root)
        d = up


def setting(root, name):
    """A key of Claude Code's settings by its precedence, local over project over user, or None."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    for path in (os.path.join(root, ".claude", "settings.local.json"), os.path.join(root, ".claude", "settings.json"),
                 os.path.join(home, "settings.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and name in data:
            return data[name]
    return None


def not_main_checkout(root, app, mem):
    """A worktree or a subdirectory shares the main checkout's auto memory directory, whose pointer names the main
    checkout's store, so only a session at the main checkout moves files into it or writes its pointer."""
    return norm(repo_root(root)) != norm(root) and norm(app) != norm(mem)


def auto_memory_off(root):
    """Auto memory is off by CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 or
    `autoMemoryEnabled: false`, and CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 forces it on over the setting, as the env-vars
    page and the settings reference, key autoMemoryEnabled, of https://code.claude.com/docs say."""
    if switch("CLAUDE_CODE_DISABLE_CLAUDE_MDS") is True:
        return True
    env = switch("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if env is not None:
        return env
    return setting(root, "autoMemoryEnabled") is False


def switch(name):
    """An on/off variable as the env-vars page reads it: 1, true, yes or on, and 0, false, no or off, in any casing;
    None when unset or anything else."""
    v = os.environ.get(name, "").strip().lower()
    return True if v in ("1", "true", "yes", "on") else False if v in ("0", "false", "no", "off") else None


def appdata_memory(payload, root):
    """The auto memory directory as https://code.claude.com/docs/en/memory sets it: `autoMemoryDirectory` when it is
    an absolute or `~/` path, else `<config>/projects/<project>/memory`, where <project> is
    CLAUDE_CODE_PROJECT_DIR_NAME or the slug of the git repository's main checkout, so worktrees and subdirectories
    share one."""
    if os.environ.get("P4_MEMORY_APPDATA"):          # tests point it at a fixture
        return os.environ["P4_MEMORY_APPDATA"]
    moved = setting(root, "autoMemoryDirectory")
    if isinstance(moved, str) and (moved.startswith("~/") or os.path.isabs(moved)):
        return os.path.normpath(os.path.expanduser(moved))
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    named = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME") if os.environ.get("CLAUDE_CONFIG_DIR") else None
    name = named or project_slug(repo_root(root))      # the env-vars page: ignored without CLAUDE_CONFIG_DIR
    return os.path.join(home, "projects", name, MEMORY)


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
    """Remove a symlink or junction itself, never what it points at, since rmtree would follow a junction."""
    if os.path.islink(path):
        os.unlink(path)
    else:
        os.rmdir(path)                                  # a junction: RemoveDirectory drops the reparse point only


def pointer_text(mem):
    p = os.path.normpath(mem)
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


def write_pointer(app, mem):
    os.makedirs(app, exist_ok=True)
    path = os.path.join(app, "MEMORY.md")
    text = pointer_text(mem)
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


def keep_aside(mem, source, rel, src, stamp):
    """Copy src into the memory folder's .conflicts/<source>/<rel>; an identical copy already there is enough, and
    a different one gets the stamp appended so nothing kept earlier is overwritten."""
    side = os.path.join(mem, CONFLICTS, source, rel)
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
    """Delete everything in the auto memory directory but the pointer. The directory itself stays, since Claude Code
    may hold it open and loads MEMORY.md from it."""
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


def migrate(app, mem, stamp):
    """-> (lines to print, done), done when nothing but the pointer is left in the auto memory directory."""
    lines = []
    os.makedirs(mem, exist_ok=True)
    if norm(app) == norm(mem) or (same_dir(app, mem) and not is_link(app)):   # autoMemoryDirectory is the store
        return lines, True
    if is_link(app):
        if not same_dir(app, mem):                       # a link somewhere else: ezexe's arrangement
            return [f"{app} is a link that does not reach .claude/p4/temportal/memory/; "
                    "left as it is, nothing moved"], False
        if not retry(remove_link, app):
            return [f"{app} is a link to .claude/p4/temportal/memory/ and is busy, retried at turn end"], False
        lines.append(f"removed the link {app} -> .claude/p4/temportal/memory/ and left its target untouched")
    moved, aside, left = [], [], []
    name = os.path.basename(app)
    if os.path.isdir(app) and not all(n == "MEMORY.md" and is_pointer(os.path.join(app, n)) for n in os.listdir(app)):
        for rel in files_in(app, skip_conflicts=False):
            src, dst = os.path.join(app, rel), os.path.join(mem, rel)
            if rel == "MEMORY.md" and is_pointer(src):
                continue
            if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
                pass                                    # identical in the store: dropped
            elif not os.path.exists(dst) and rel.split(os.sep)[0] != CONFLICTS:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                moved.append(rel)
            else:
                keep_aside(mem, name, rel, src, stamp)
                aside.append(f"{name}/{rel}")
        if not empty_live_dir(app):
            left.append(app)
    try:
        write_pointer(app, mem)
    except OSError as e:
        lines.append(f"could not write the pointer MEMORY.md in {app}: {e}")
    if moved:
        lines.append(f"memory files moved from the auto memory directory into "
                     f".claude/p4/temportal/memory/: {len(moved)}")
    if aside:
        lines.append(f"differing files kept: {len(aside)}, "
                     + ", ".join(aside[:5]) + (", …" if len(aside) > 5 else "")
                     + ", in .claude/p4/temportal/memory/.conflicts/")
    if left:
        lines.append(f"{', '.join(map(os.path.basename, left))} busy, retried at turn end")
    return lines, not left


def builtin_index(memdir):
    """-> (kept lines, the index's line count): what Claude Code loads from a memory folder, the first BUILTIN_LINES
    lines of its MEMORY.md or its first BUILTIN_BYTES bytes cut at a whole line, whichever comes first."""
    index = os.path.join(memdir, "MEMORY.md")
    if not os.path.isfile(index):
        return [], 0
    with open(index, "rb") as f:
        lines = f.read().splitlines(keepends=True)
    total = len(lines)
    kept, size = [], 0
    for line in lines[:BUILTIN_LINES]:
        size += len(line)                               # bytes on disk, a CRLF line counted with its CR
        if size > BUILTIN_BYTES:
            break
        kept.append(line.decode("utf-8", errors="replace").rstrip("\r\n") + "\n")
    return kept, total


def notice(parts):
    return ("p4-temportal: " + "; ".join(parts) + ".") if parts else ""


def cmd_migrate(payload, first=""):
    root = project_root(payload)
    app, mem = appdata_memory(payload, root), p4_memory(root)
    parts = [] if not_main_checkout(root, app, mem) else migrate(app, mem, time.strftime("%Y%m%d-%H%M%S"))[0]
    out = notice(parts)
    head = first + (out + "\n" if out else "")
    kept, total = builtin_index(mem)    # Claude Code loaded only the pointer: print what it would have loaded
    path = os.path.normpath(os.path.join(mem, "MEMORY.md"))

    def cut_line(n):
        return f"p4-temportal: MEMORY.md cut here, {total - n} of {total} lines left out; the whole index is {path}.\n"

    room = STDOUT_CHARS - len(head)
    if len(kept) < total or sum(map(len, kept)) > room:
        room -= len(cut_line(0))        # the longest the cut line can be
    shown, size = [], 0
    for line in kept:
        if size + len(line) > room:
            break
        shown.append(line)
        size += len(line)
    text = head + "".join(shown) + (cut_line(len(shown)) if len(shown) < total else "")
    sys.stdout.flush()                  # LF as counted, never the CRLF Windows text mode would write
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    return 0


def norm(path):
    return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))


def added_index_lines(text, mem):
    """Lines a write put into the pointer that the pointer itself does not carry."""
    stock = set(pointer_text(mem).splitlines())
    return [ln for ln in text.splitlines() if ln.strip() and ln not in stock and not ln.startswith(POINTER_MARK)]


def cmd_mirror(payload):
    """PostToolUse: a memory written into the auto memory directory is moved into the store at once. The write
    itself is never refused, and nothing written there stays."""
    inp = payload.get("tool_input") or {}
    fp = str(inp.get("file_path") or "") if isinstance(inp, dict) else ""
    if not fp:
        return 0
    root = project_root(payload)
    app, mem = appdata_memory(payload, root), p4_memory(root)
    if is_link(app) or norm(app) == norm(mem) or not_main_checkout(root, app, mem):
        return 0
    n_app, n_fp = norm(app), norm(fp)
    if not n_fp.startswith(n_app + os.sep) or not os.path.isfile(fp):
        return 0
    rel = os.path.relpath(n_fp, n_app)
    dst = os.path.join(mem, rel)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if rel.lower() == "memory.md":
        with open(fp, encoding="utf-8", errors="replace") as f:
            new = added_index_lines(f.read(), mem)
        old = ""
        if os.path.isfile(dst):
            with open(dst, encoding="utf-8", errors="replace") as f:
                old = f.read()
        have = set(old.splitlines())
        add = [ln for ln in new if ln not in have]
        if add:
            os.makedirs(mem, exist_ok=True)
            with open(dst, "a", encoding="utf-8", newline="\n") as f:
                f.write(("\n" if old and not old.endswith("\n") else "") + "\n".join(add) + "\n")
        write_pointer(app, mem)
        note = (f"p4-temportal: index lines appended: {len(add)}, from the pointer MEMORY.md to "
                f"{os.path.normpath(dst)}; the pointer is restored.")
    else:
        if os.path.isfile(dst) and not filecmp.cmp(fp, dst, shallow=False):
            keep_aside(mem, "replaced", rel, dst, stamp)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(fp, dst)
        retry(os.remove, fp)
        note = f"p4-temportal: {fp} was moved to {os.path.normpath(dst)}."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}))
    return 0


def cmd_sweep(payload):
    """Stop: what the start could not move or delete is tried again at turn end. Prints nothing."""
    root = project_root(payload)
    app, mem = appdata_memory(payload, root), p4_memory(root)
    if not_main_checkout(root, app, mem):
        return 0
    pending = is_link(app) or (
        os.path.isdir(app) and any(n != "MEMORY.md" or not is_pointer(os.path.join(app, n)) for n in os.listdir(app)))
    if pending or not os.path.isdir(app):
        migrate(app, mem, time.strftime("%Y%m%d-%H%M%S"))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        configure(payload)
        if sub in ("migrate", "mirror", "sweep") and auto_memory_off(project_root(payload)):
            return 0                    # auto memory is off: no pointer, no move, no index
        if sub == "migrate":
            return cmd_migrate(payload, layout(payload))
        if sub == "mirror":
            return cmd_mirror(payload)
        if sub == "sweep":
            return cmd_sweep(payload)
        print(f"p4_memory.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-temportal memory {sub} degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
