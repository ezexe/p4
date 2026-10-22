#!/usr/bin/env python3
"""p4_memory.py — the p4-memory plugin's mechanical half: the built-in per-project memory (the base class the
vlds override wraps) is stored in the p4 repo, `<project>/.claude/p4/memory/`, never only on the device.

The harness writes and loads base memories at `~/.claude/projects/<project-slug>/memory/` — the device's local
AppData on Windows — and that path is fixed by the system prompt. This plugin keeps the harness's path working
and moves what lives behind it:

  migrate (SessionStart)  every file of the AppData memory directory is copied into `.claude/p4/memory/` — absent
                          there → copied; identical → nothing; different → the AppData copy is kept beside it as
                          `.conflicts/<name>` and the link waits. Once every AppData file is in p4 byte for byte,
                          the AppData directory is renamed `memory.pre-p4-<time>` (kept whole, the owner's to
                          dispose) and replaced by a link to `.claude/p4/memory/` — a directory junction on
                          Windows, a symlink elsewhere — so the harness reads and writes the p4 copy through its
                          own path. A link already in place is checked and left. When the link cannot be made, the
                          p4 MEMORY.md is printed, so the session still loads what p4 holds.
                          The harness can hold the directory open while a session starts, so the rename is
                          retried, and on failure left to the next hook.
  mirror (PostToolUse)    while the AppData directory is not the link, a Write or Edit into it is copied into p4 at
                          once — the harness's own memory write is never refused, and none stays local only.
  relink (Stop)           a link the start could not make is tried again at the turn's close.

Every failure prints a one-line notice and exits 0 — a hook that crashes the call it guards is worse than none.
"""

import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time

MEMORY = "memory"
RENAME_TRIES = 5
RENAME_WAIT_S = 1.0


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


def linked(app, p4):
    return os.path.isdir(app) and is_link(app) and same_dir(app, p4)


def make_link(app, p4):
    if os.name == "nt":
        # the payload's cwd can carry forward slashes, which mklink reads as switches ("Invalid switch")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", os.path.normpath(app), os.path.normpath(p4)],
                           capture_output=True, timeout=20)
        return r.returncode == 0 and linked(app, p4)
    os.symlink(p4, app, target_is_directory=True)
    return linked(app, p4)


def files_under(base):
    out = []
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x != ".conflicts"]
        for name in files:
            out.append(os.path.relpath(os.path.join(d, name), base))
    return sorted(out)


def migrate(app, p4, stamp):
    """-> (lines to print, linked now?)"""
    lines = []
    if linked(app, p4):
        return lines, True
    if is_link(app):                                    # a link somewhere else: the owner's arrangement
        return [f"p4-memory: {app} is a link that does not reach {p4} — left as it is; base memories are not in p4 "
                f"until it does."], False
    os.makedirs(p4, exist_ok=True)
    copied, conflicts = [], []
    if os.path.isdir(app):
        for rel in files_under(app):
            src, dst = os.path.join(app, rel), os.path.join(p4, rel)
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(rel)
            elif not filecmp.cmp(src, dst, shallow=False):
                side = os.path.join(p4, ".conflicts", rel)
                os.makedirs(os.path.dirname(side), exist_ok=True)
                shutil.copy2(src, side)
                conflicts.append(rel)
    if copied:
        lines.append(f"p4-memory: copied {len(copied)} base memory file(s) from {app} into .claude/p4/memory/.")
    if conflicts:
        lines.append(f"p4-memory: {len(conflicts)} file(s) differ between AppData and p4 ("
                     + ", ".join(conflicts[:5]) + ") — the AppData copies sit in .claude/p4/memory/.conflicts/; "
                     "merge them into the p4 file, then the next start links the directory.")
        return lines, False
    if os.path.isdir(app):
        kept = f"{app}.pre-p4-{stamp}"
        # the harness may hold the directory open while a session starts: retry, then leave it to the next hook
        for attempt in range(RENAME_TRIES):
            try:
                os.rename(app, kept)
                break
            except OSError:
                if attempt == RENAME_TRIES - 1:
                    lines.append(f"p4-memory: {app} is busy and was not linked yet — writes into it are mirrored into "
                                 f".claude/p4/memory/ meanwhile, and the next turn's close tries the link again.")
                    return lines, False
                time.sleep(RENAME_WAIT_S)
    else:
        kept = None
        os.makedirs(os.path.dirname(app), exist_ok=True)
    try:
        ok = make_link(app, p4)
    except OSError:
        ok = False
    if ok:
        lines.append(f"p4-memory: {app} is now a link to .claude/p4/memory/ — base memories are read and written in "
                     f"the p4 repo" + (f"; the original directory is kept whole at {kept}, the owner's to dispose."
                                       if kept else "."))
        return lines, True
    if kept and not os.path.exists(app):
        os.rename(kept, app)
    lines.append(f"p4-memory: could not link {app} to .claude/p4/memory/ — the AppData directory is restored; the "
                 f"p4 copy is current and its MEMORY.md follows.")
    return lines, False


def cmd_migrate(payload):
    root = project_root(payload)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")):
        return 0                                        # no p4 repo here: nothing to store into
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    lines, ok = migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    if lines:
        print("\n".join(lines))
    index = os.path.join(p4, "MEMORY.md")
    app_index = os.path.join(app, "MEMORY.md")
    stale = not os.path.isfile(app_index) or not filecmp.cmp(app_index, index, shallow=False)
    if not ok and os.path.isfile(index) and stale:      # the harness loaded no index, or one p4 has moved past
        with open(index, encoding="utf-8", errors="replace") as f:
            print(f"\n### p4 base memory index ({index}) — the harness did not load it; read it as the session's "
                  f"MEMORY.md\n\n" + f.read()[:8000])
    return 0


def norm(path):
    return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))


def cmd_mirror(payload):
    """PostToolUse: while the AppData directory is not yet the link, a memory written there is copied into p4 at
    once — the harness's own write is never refused, and nothing it writes stays local only."""
    inp = payload.get("tool_input") or {}
    fp = str(inp.get("file_path") or "") if isinstance(inp, dict) else ""
    if not fp:
        return 0
    root = project_root(payload)
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")) or linked(app, p4):
        return 0
    n_app, n_fp = norm(app), norm(fp)
    if not n_fp.startswith(n_app + os.sep) or not os.path.isfile(fp):
        return 0
    dst = os.path.join(p4, os.path.relpath(n_fp, n_app))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(fp, dst)
    return 0


def cmd_relink(payload):
    """Stop: when the start could not link (the directory was busy), try again at the turn's close — silent unless
    it links now."""
    root = project_root(payload)
    if not os.path.isdir(os.path.join(root, ".claude", "p4")):
        return 0
    app, p4 = appdata_memory(payload, root), p4_memory(root)
    if linked(app, p4):
        return 0
    lines, ok = migrate(app, p4, time.strftime("%Y%m%d-%H%M%S"))
    if ok:
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
        if sub == "relink":
            return cmd_relink(payload)
        print(f"p4_memory.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-memory ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
