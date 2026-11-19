#!/usr/bin/env python3
"""scratchpad.py: p4-temportal's notebook part and its repo-uses line. The notebook is the store's folder of notes kept
across sessions, at the place p4conf.LAYOUT gives the key `scratchpad`, `<project>/.claude/p4/temportal/notebook/`,
with its logs, build output and binaries in its `.out/`, which ignores itself. Each session's scratchpad directory is
Claude Code's own: it makes one under the system temp directory for each session and deletes it with the session's
transcript, and no command here moves, links, stages, commits or removes one.

  notebook-out   at SessionStart, seeds the notebook's `.out/.gitignore` with `*`, seeds it again when it is missing
                 or changed, and moves every log, build output and binary found elsewhere in the notebook into `.out/`
                 at the same relative path. A taken name gets the time as a suffix, and nothing is overwritten or
                 removed. It says one line when it seeded the file again or moved something, and the first seed of a
                 new notebook is silent. What it prints is the hook's JSON: the line as `additionalContext`, and the
                 notebook's folder as `watchPaths`, so Claude Code raises FileChanged for a file in it.

  notebook-changed  at FileChanged, which Claude Code raises for a file added or changed in the watched notebook:
                 when that file is a log, a build output or a binary outside `.out/`, the same move runs at once,
                 and the line it says is a `systemMessage`, which ezexe reads. Any other path moves nothing.

  tmp-unlink     at SessionStart, and by hand as `scratchpad.py tmp-unlink [project]`: every app scratchpad of the
                 project, `<temp>/claude*/<project>/<session>/scratchpad`, that an earlier version made a junction or a
                 symlink into the store's temportal/tmp/ becomes a real folder holding a copy of what the store folder
                 holds, since a write through such a link is a write under .claude/ that asks ezexe in every mode. The
                 link is removed as a link, the store's folder is left as it is, and a real folder is never touched.
                 It prints one line when it unlinked something.

`tmp-link`, the start command of 0.3.9 that made those links, is gone, and so are `tmp-sweep` and `tmp-close`, which
kept each session's scratchpad in the store: an installed version runs the scripts of its own folder in Claude Code's
plugin cache, so no session of an older version reaches this file.

repo-uses is off unless p4.json's scratchpad.asks is true or a person set P4_SCRATCHPAD_ASKS to 1 or true:

  repo-uses      at SessionStart, prints one line for each file under `.claude/p4/temportal/src/` that the project
                 repository's tracked code, build, docs or CI names: that file is code the repository uses, so it
                 belongs there. It only reads, with one `git grep`, and is silent outside a git repository or without
                 git.

`ask`, a PreToolUse ask on code written to a temp folder or the notebook, is gone. Claude Code does that itself with
an ask rule on an `Edit` path, which covers Write, Edit and NotebookEdit, as
https://code.claude.com/docs/en/permissions.md says: "`Edit` rules apply to all built-in tools that edit files."

Every failure prints a one-line systemMessage and exits 0."""

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json
import hookio  # noqa: E402 - the hook input and link helpers p4-temportal's scripts share

ASKS_ENV = "P4_SCRATCHPAD_ASKS"

CODE_EXT = {"py", "pyw", "sh", "bash", "zsh", "ps1", "psm1", "bat", "cmd", "js", "mjs", "cjs", "ts", "rb", "pl",
            "lua", "php", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "java", "kt", "swift", "sql", "awk",
            "r", "jl", "scala", "groovy", "tcl", "vbs", "cmake", "gn", "gni", "html", "htm",
            "ipynb"}
# Code by name rather than by extension: by extension alone CMakeLists.txt is a `.txt` note.
CODE_NAMES = {"cmakelists.txt", "makefile", "gnumakefile", "dockerfile", "justfile", "rakefile"}

OUT_NAME = ".out"
OUT_IGNORE = "*\n"
IGNORABLE_EXT = {"log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so", "dylib",
                 "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"}
IGNORABLE_DIRS = {"bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__", ".cache",
                  "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"}

REPO_USES_MIN_NAME = 6     # a basename shorter than this, such as `a.py`, matches too much to call it a use
REPO_USES_MAX = 200        # candidate names one git grep carries
REPO_USES_LINES = 10       # lines printed at most; the rest counted on one more


payload_from_stdin = hookio.payload_from_stdin


project_root = hookio.project_root


ASKS = False                # p4.json scratchpad.asks, with P4_SCRATCHPAD_ASKS ahead of it by p4conf.configure


def configure(payload, write=True, root=None):
    """The scratchpad section of <project>/.claude/p4/p4.json over the constants, writing the file when it is
    missing unless `write` is False."""
    p4 = os.path.join(root or project_root(payload), ".claude", "p4")
    p4conf.configure(globals(), p4, "scratchpad", {
        "asks": "ASKS", "ignorable_ext": "IGNORABLE_EXT", "ignorable_dirs": "IGNORABLE_DIRS",
        "repo_uses_min_name": "REPO_USES_MIN_NAME", "repo_uses_max": "REPO_USES_MAX",
        "repo_uses_lines": "REPO_USES_LINES"}, write=write)


def layout(payload):
    """Files in an earlier place of the store's layout are moved into each plugin's folder first."""
    lines = p4conf.migrate_layout(os.path.join(project_root(payload), ".claude", "p4"))
    if lines:
        print("p4-temportal: " + "; ".join(lines) + ".")


def asks_on():
    """ASKS as configure set it: P4_SCRATCHPAD_ASKS read as p4conf reads every variable, 1, 0, true and false alike,
    for the session's own store and only when a person set it, ahead of p4.json."""
    return bool(ASKS)


def is_code(path):
    return (os.path.splitext(path)[1].lower().lstrip(".") in CODE_EXT
            or os.path.basename(path).lower() in CODE_NAMES)


# ---- notebook-out ---------------------------------------------------------------------------------------------

def is_ignorable(rel):
    """True for a path in the notebook, relative to it, that is a log, a build output or a binary."""
    parts = [s for s in rel.replace("\\", "/").split("/") if s]
    if not parts or parts[0] == OUT_NAME:
        return False
    if any(s.lower() in IGNORABLE_DIRS for s in parts[:-1]):
        return True
    return os.path.splitext(parts[-1])[1].lower().lstrip(".") in IGNORABLE_EXT


def tracked_in_p4(p4, rels):
    """The notebook paths, relative to it, that the store's index holds. It only reads, and is empty without
    git."""
    if not rels or not os.path.isdir(os.path.join(p4, ".git")):
        return set()
    try:
        r = subprocess.run(["git", "-C", p4, "ls-files", "-z", "--", p4conf.rel("scratchpad")], capture_output=True,
                           timeout=15)
    except Exception:
        return set()
    cut = len(p4conf.rel("scratchpad")) + 1
    listed = {s.decode("utf-8", "replace")[cut:] for s in r.stdout.split(b"\0") if s}
    return {rel for rel in rels if rel in listed}


def sweep_notebook(root, now_tag):
    """Seed `.out/` and move the notebook's logs, build output and binaries into it -> (reseeded, [moved rel
    paths], [tracked rels]). `reseeded` is False for the first seed of a new `.out/`, which is silent."""
    p4 = os.path.join(root, ".claude", "p4")
    pad = p4conf.sub(p4, "scratchpad")
    out = os.path.join(pad, OUT_NAME)
    first = not os.path.isdir(out)
    os.makedirs(out, exist_ok=True)
    ign = os.path.join(out, ".gitignore")
    try:
        with open(ign, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = None
    reseeded = False
    if current != OUT_IGNORE:
        with open(ign, "w", encoding="utf-8", newline="\n") as f:
            f.write(OUT_IGNORE)
        reseeded = not first
    found = []
    for d, dirs, files in os.walk(pad):
        rel_d = os.path.relpath(d, pad).replace("\\", "/")
        if rel_d == OUT_NAME or rel_d.startswith(OUT_NAME + "/"):
            dirs[:] = []
            continue
        if rel_d == ".":
            dirs[:] = [x for x in dirs if x != OUT_NAME]
        for name in files:
            rel = name if rel_d == "." else f"{rel_d}/{name}"
            if is_ignorable(rel):
                found.append(rel)
    tracked = tracked_in_p4(p4, found)
    moved = []
    for rel in sorted(found):
        dest = os.path.join(out, *rel.split("/"))
        if os.path.exists(dest):
            stem, ext = os.path.splitext(dest)
            dest = f"{stem}.{now_tag}{ext}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            os.replace(os.path.join(pad, *rel.split("/")), dest)
            moved.append(rel)
        except OSError:
            continue
    if moved:   # folders the move emptied are removed, only the empty ones
        for d, _dirs, _files in os.walk(pad, topdown=False):
            nd = os.path.normcase(d)
            if nd in (os.path.normcase(pad), os.path.normcase(out)) or nd.startswith(os.path.normcase(out) + os.sep):
                continue
            try:
                os.rmdir(d)
            except OSError:
                pass
    return reseeded, moved, sorted(tracked & set(moved))


def moved_line(root):
    """Run the notebook's move for the project at `root` -> the one line that says what it did, '' for nothing."""
    reseeded, moved, tracked = sweep_notebook(root, time.strftime("%Y%m%d-%H%M%S"))
    parts = []
    out = f".claude/p4/{p4conf.rel('scratchpad', OUT_NAME)}/"
    if reseeded:
        parts.append(f"re-seeded {out}.gitignore with `*`")
    if moved:
        parts.append(f"logs, build output and binaries moved: {len(moved)}, "
                     + ", ".join(moved[:6]) + (", …" if len(moved) > 6 else "") + f", into {out}")
    if tracked:
        parts.append(f"{len(tracked)} of them were tracked by the store and show as deleted there")
    return "p4-temportal: " + "; ".join(parts) + "." if parts else ""


def cmd_notebook_out(payload):
    """At SessionStart: the move, and the notebook's folder as a path Claude Code watches. hooks.md, "SessionStart
    decision control", gives `watchPaths` as "Array of absolute paths to watch for FileChanged events during this
    session". Seen on Claude Code 2.1.328 in a `claude -p` run: a folder there raised FileChanged with the event
    `add` for a new file in it and in a folder under it, and `change` for a file in it that was appended to."""
    root = project_root(payload)
    line = moved_line(root)
    pad = p4conf.sub(os.path.join(os.path.abspath(root), ".claude", "p4"), "scratchpad")
    out = {"hookEventName": "SessionStart", "watchPaths": [pad]}
    if line:
        out["additionalContext"] = line
    print(json.dumps({"hookSpecificOutput": out}))
    return 0


def cmd_notebook_changed(payload):
    """At FileChanged: the move, when the file that was added or changed is one the move takes. A file under
    `.out/`, a note, a deleted file and a path outside the notebook move nothing, so the move's own writes into
    `.out/` start no second move."""
    path = payload.get("file_path")
    if payload.get("event") not in ("add", "change") or not isinstance(path, str) or not path:
        return 0
    root = project_root(payload)
    pad = p4conf.sub(os.path.join(os.path.abspath(root), ".claude", "p4"), "scratchpad")
    try:
        rel = os.path.relpath(os.path.abspath(path), pad)
    except ValueError:                                  # another drive
        return 0
    if rel.split(os.sep)[0] == os.pardir or os.path.isabs(rel) or not is_ignorable(rel):
        return 0
    line = moved_line(root)
    if line:
        print(json.dumps({"systemMessage": line}))
    return 0


# ---- tmp-unlink: the links earlier versions made into the store ---------------------------------------------

TEMP_ROOTS = ("/tmp", "/private/tmp")   # beside the system temp directory: where Claude Code makes its claude* folders


def temp_roots(payload):
    """The folders that hold Claude Code's claude* temp folders: the one above this session's scratchpad_dir, then
    CLAUDE_CODE_TMPDIR, TMPDIR, TEMP, TMP, the system temp directory, /tmp and /private/tmp."""
    import tempfile
    out = []
    given = payload.get("scratchpad_dir") if isinstance(payload, dict) else None
    if isinstance(given, str) and os.path.isabs(given):
        out.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(given))))))
    out += [os.environ.get(k) for k in ("CLAUDE_CODE_TMPDIR", "TMPDIR", "TEMP", "TMP")]
    out += [tempfile.gettempdir(), *TEMP_ROOTS]
    seen, roots = set(), []
    for r in out:
        if not r or not os.path.isdir(r):
            continue
        key = os.path.normcase(os.path.realpath(r))
        if key not in seen:
            seen.add(key)
            roots.append(r)
    return roots


def link_target(path):
    """Where a link points, as written in it, or '' when it cannot be read."""
    try:
        t = os.readlink(path)
    except (OSError, ValueError):
        return ""
    return os.path.normpath(t[4:] if t.startswith("\\\\?\\") else t)


def into_store_tmp(target, root):
    """True when `target` lies in this project's store under temportal/tmp/ or the older tmp/ at its top."""
    store = os.path.normcase(os.path.normpath(os.path.join(root, ".claude", "p4")))
    t = os.path.normcase(os.path.normpath(target))
    return any(t.startswith(os.path.join(store, *place) + os.sep) for place in (("temportal", "tmp"), ("tmp",)))


def unlink_scratchpad(link, target):
    """Replace the link `link` by a real folder holding a copy of `target` -> True when done. The copy is made beside
    the link first; the link is then removed as a link, never followed, and the copy takes its name. The store's
    folder is never touched. On any failure the link stays as it was and the partial copy goes."""
    import shutil
    staging = f"{link}.p4-unlinking-{os.getpid()}"
    try:
        if os.path.isdir(target):
            shutil.copytree(target, staging, symlinks=True)
        else:
            os.makedirs(staging)                       # the store folder is gone: an empty folder takes the link's place
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return False
    try:
        if os.path.islink(link):
            os.unlink(link)
        else:
            os.rmdir(link)                             # a junction: RemoveDirectory drops the reparse point only
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return False
    try:
        os.rename(staging, link)
    except OSError:
        return False                                   # the copy stays beside the link's old name, with its files
    return True


def cmd_tmp_unlink(payload, root=None):
    """Every app scratchpad, `<temp>/claude*/<project>/<session>/scratchpad`, that an earlier version made a junction
    or a symlink into this project's store becomes a real folder with a copy of what the store folder holds. A real
    folder is left as it is, and so is a link that points anywhere else."""
    import glob
    root = root or project_root(payload)
    done, left = [], []
    for r in temp_roots(payload):
        for sp in sorted(glob.glob(os.path.join(glob.escape(r), "claude*", "*", "*", "scratchpad"))):
            if not p4conf.is_link(sp):
                continue
            target = link_target(sp)
            if not target or not into_store_tmp(target, root):
                continue
            (done if unlink_scratchpad(sp, target) else left).append(sp)
    parts = []
    if done:
        parts.append(f"session scratchpads unlinked from the store: {len(done)}, each now a folder of its own with a "
                     "copy of its files")
    if left:
        parts.append(f"{len(left)} could not be unlinked and are still links: " + ", ".join(left[:3]))
    if parts:
        print("p4-temportal: " + "; ".join(parts) + ".")
    return 0


# ---- repo-uses ------------------------------------------------------------------------------------------------

def repo_use_candidates(root):
    """{basename: [project-relative paths]} of every code file under `.claude/p4/temportal/src/`, skipping dot
    folders, whose name is distinctive enough to look for."""
    src = p4conf.sub(os.path.join(root, ".claude", "p4"), "src")
    found = {}
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for name in sorted(files):
            path = os.path.join(d, name)
            if not is_code(path) or len(name) < REPO_USES_MIN_NAME:
                continue
            found.setdefault(name, []).append(os.path.relpath(path, root).replace("\\", "/"))
    return dict(sorted(found.items())[:REPO_USES_MAX])


def repo_uses(root):
    """[(project-relative path, [repository files that name it])] by one `git grep` over the project repository's
    tracked files; `.claude/p4` is its own repository and is excluded, so a file's own notes never count as a use."""
    cands = repo_use_candidates(root)
    if not cands:
        return []
    args = ["git", "-C", root, "grep", "-I", "-F", "-l", "-z"]
    for name in cands:
        args += ["-e", name]
    try:
        r = subprocess.run(args + ["--", ".", ":(exclude).claude/p4"], capture_output=True, timeout=15)
    except Exception:
        return []
    if r.returncode not in (0, 1):
        return []
    files = sorted(f.decode("utf-8", "replace") for f in r.stdout.split(b"\0") if f)
    out = []
    for name, paths in cands.items():
        users = []
        rx = re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])")
        for f in files:
            try:
                with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                    if rx.search(fh.read()):
                        users.append(f)
            except OSError:
                continue
        if users:
            out += [(p, users) for p in paths]
    return sorted(out)


def cmd_repo_uses(payload):
    if not asks_on():
        return 0
    root = project_root(payload)
    used = repo_uses(root)
    lines = []
    for path, users in used[:REPO_USES_LINES]:
        named = ", ".join(f"`{u}`" for u in users[:2]) + (" …" if len(users) > 2 else "")
        lines.append(f"`{path}` is used by {named}; it belongs in the repo.")
    if len(used) > REPO_USES_LINES:
        lines.append(f"{len(used) - REPO_USES_LINES} more files under .claude/p4/temportal/src/ are named by the repo.")
    if lines:
        print("\n".join(lines))
    return 0



def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub == "tmp-unlink" and (len(sys.argv) > 2 or sys.stdin is None or sys.stdin.isatty()):
        try:                                           # run by hand: the project named or the working folder, no stdin
            return cmd_tmp_unlink({}, os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.getcwd())
        except Exception as e:  # noqa: BLE001
            print(f"p4-temportal scratchpad {sub} degraded: {type(e).__name__}: {e}")
            return 0
    payload = payload_from_stdin()
    try:
        configure(payload)
        if sub in ("notebook-out", "repo-uses"):
            layout(payload)
        if sub == "notebook-out":
            return cmd_notebook_out(payload)
        if sub == "notebook-changed":
            return cmd_notebook_changed(payload)
        if sub == "repo-uses":
            return cmd_repo_uses(payload)
        if sub == "tmp-unlink":
            return cmd_tmp_unlink(payload)
        print(json.dumps({"systemMessage": f"scratchpad.py: unknown subcommand {sub!r}"}))
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        # a systemMessage reaches ezexe whatever the event, where plain stdout reaches nobody on most events
        print(json.dumps({"systemMessage": f"p4-temportal scratchpad {sub} degraded: {type(e).__name__}: {e}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
