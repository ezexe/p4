#!/usr/bin/env python3
"""scratchpad.py: p4-temportal's scratchpad part, which keeps each session's scratchpad directory in
`<project>/.claude/p4/temportal/tmp/<session>/` and the notebook in `<project>/.claude/p4/temportal/scratchpad/`, with
the notebook's logs, build output and binaries in its `.out/`, which ignores itself. It moves files, and it tells the
model only where a session's temporary files go and what it did, unless ezexe turns the two asks on.

  notebook-out   at SessionStart, seeds `.claude/p4/temportal/scratchpad/.out/.gitignore` with `*`, seeds it again
                 when it is missing or changed, and moves every log, build output and binary found elsewhere in the
                 notebook into `.out/` at the same relative path. A taken name gets the time as a suffix, and nothing
                 is overwritten or removed. It prints one line when it seeded the file again or moved something, and
                 the first seed of a new notebook is silent.

The scratchpad directory is on unless p4.json's scratchpad.tmp is false or P4_SCRATCHPAD_TMP=0:

  tmp-link       at SessionStart, makes the scratchpad path Claude Code gives the session,
                 `%TEMP%/claude/<project>/<session>/scratchpad` on Windows and
                 `/private/tmp/claude-<uid>/<project>/<session>/scratchpad` on macOS, a link to
                 `.claude/p4/temportal/tmp/<session>/`: a junction on Windows and a symlink elsewhere. What the path
                 already held is moved in first, a taken name getting the time as a suffix, and a clone's read-only
                 git objects move too, across drives. One line names the link when it is made. It then links the
                 project's other scratchpad folders, beside this session's under the temp directory and in the folder
                 named after the project's path, where Claude Code put them before it named that folder by a hash.
                 Claude Code makes one for an id that never runs a hook, such as the id a session holds before it
                 takes up the one it resumes or one of the app's helpers, so no start of its own links it. An empty
                 one quiet for scratchpad.scratch_sweep_minutes is removed instead, and so is a link to a folder of
                 that session inside a store when that folder is gone and the store holds nothing for the session.
  tmp-sweep      at Stop, silently, links a scratchpad folder the start could not link or that appeared after it,
                 this session's or another's. Then it stages the session's scratchpad directory in the store with
                 `git add`, at every turn end: never a file git ignores, one over scratchpad.tmp_max_file_mb, the
                 contents of a clone, a work tree, a bare repository, a folder holding .claude/p4 or a store with
                 p4.json beside phi/, a copy or export of a repository, which is a folder below the directory's top
                 holding .gitignore, .gitattributes or .claude-plugin/, or a folder named in scratchpad.tmp_skip_dirs.
                 A file that an earlier turn end staged in such a repository, store or copy leaves the index again,
                 while one a commit holds keeps that commit's version there, so no deletion of it is staged. A
                 scratchpad directory over scratchpad.tmp_max_files has only its tracked files' changes staged, so
                 no file added earlier stays staged after it is gone.
  tmp-close      at SessionEnd, commits the session's scratchpad directory and only then removes its files: its
                 staged files are committed alone, leaving whatever else is staged, the files that commit holds are
                 deleted with the folders they leave empty, and the removal is committed too. A file no commit holds
                 stays on disk. A session that starts again after its files were removed gets them back from that
                 commit. Nothing is staged, committed or removed unless `.claude/p4` is a git repository of its own.

A session has ended when p4-phi's record of it says archived, or when its scratchpad directory and its transcript are
quiet for scratchpad.tmp_idle_days, as when it ended without a SessionEnd. At a start, tmp-link commits and removes the
scratchpad directory of an ended session as SessionEnd would, staged and untracked files alike, and removes an empty
one quiet with its transcript for scratchpad.tmp_empty_idle_hours, with the scratchpad link that points at it. A
scratchpad directory over scratchpad.tmp_max_files cannot be committed, so nothing of it is removed: it is named once
at a start with its file count and size, and removing it is ezexe's to choose.

  ended-sweep    run by hand, never by a hook, and reads no stdin:
                 `scratchpad.py ended-sweep [--dry-run] [--idle-days N] [--root <project>]`. It commits and removes
                 every ended session's scratchpad directory and lists what was committed, removed and left.
                 `--dry-run` changes nothing, not the index and not p4.json, and lists what would be committed and
                 removed: the counts and the top folders of each.

The two asks are off unless p4.json's scratchpad.asks is true or P4_SCRATCHPAD_ASKS=1:

  repo-uses      at SessionStart, prints one line for each file under `.claude/p4/temportal/src/` that the project
                 repository's tracked code, build, docs or CI names: that file is code the repository uses, so it
                 belongs there. It only reads, with one `git grep`, and is silent outside a git repository or without
                 git.
  ask            at PreToolUse, reads the paths a call writes: a Write's or Edit's file_path, and for a Bash command
                 every path in a write position, a redirect, tee, python's open() in a write mode, or the destination
                 of cp or mv. A code file, by extension or by name, headed for a temp location, the session's
                 scratchpad path or the notebook gets an ask naming where it belongs: the repository if it will use
                 the file, else `.claude/p4/temportal/src/`. It never denies, and it is silent inside a subagent,
                 whose writer ezexe cannot redirect from the prompt.

Every failure prints a one-line notice and exits 0."""

import json
import os
import glob
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json
import hookio  # noqa: E402 - the hook input and link helpers p4-temportal's scripts share

ASKS_ENV = "P4_SCRATCHPAD_ASKS"
TMP_ENV = "P4_SCRATCHPAD_TMP"
TEMP_ROOTS = ("/tmp", "/private/tmp")   # beside tempfile.gettempdir(): where Claude Code makes its claude* folders

CODE_EXT = {"py", "pyw", "sh", "bash", "zsh", "ps1", "psm1", "bat", "cmd", "js", "mjs", "cjs", "ts", "rb", "pl",
            "lua", "php", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "java", "kt", "swift", "sql", "awk",
            "r", "jl", "scala", "groovy", "tcl", "vbs", "cmake", "gn", "gni", "html", "htm",
            "ipynb"}
# Code by name rather than by extension: by extension alone CMakeLists.txt is a `.txt` note.
CODE_NAMES = {"cmakelists.txt", "makefile", "gnumakefile", "dockerfile", "justfile", "rakefile"}
# the scratchpad paths Claude Code gives: under the temp folder on Windows and Linux, and /private/tmp/claude-<uid>/ on
# macOS
SCRATCHPAD_MARKERS = ("/temp/claude/", "/tmp/claude/", "/tmp/claude-")
# temp folders only where a path starts with one
ROOT_TEMP = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
TEMP_MARKERS = ("/appdata/local/temp/", "%temp%", "%tmp%",
                "$tmpdir", "${tmpdir}", "$env:temp", "$env:tmp")
_PATH = r"(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^\s\"'<>|;&()`]+))"
WRITE_RES = [
    re.compile(r">{1,2}[ \t]*" + _PATH),
    re.compile(r"\btee\b(?:[ \t]+-[A-Za-z]+)*[ \t]+" + _PATH),
    re.compile(r"\bopen\(\s*(?:\"([^\"\n]+)\"|'([^'\n]+)')\s*,\s*[\"'][aw]"),
    # PowerShell's writers, by their path parameter
    re.compile(r"(?i)\b(?:Set-Content|Add-Content|Out-File|New-Item)\b[^\n|;]*?-(?:Path|FilePath|LiteralPath)[ \t]+"
               + _PATH),
]
ARGS_RES = [re.compile(r"\b(?:cp|mv)\b([^\n|;&]*)")]
# PowerShell's writers by a positional path, wherever it stands among the parameters, as in
# `'x' | Out-File -Encoding utf8 $env:TEMP\x.py`: every argument that is no parameter is read as a path, and one that
# names no code file in a temp place is passed over by the ask. A reader such as Get-Content is never matched.
PS_WRITER_ARGS = re.compile(r"(?i)\b(?:Set-Content|Add-Content|Out-File|New-Item)\b([^\n|;]*)")
TOKEN_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|\S+")

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


ASKS = False                # p4.json scratchpad.asks; P4_SCRATCHPAD_ASKS=1 or 0 wins for one run
TMP = True                  # p4.json scratchpad.tmp; P4_SCRATCHPAD_TMP=1 or 0 wins for one run
TMP_IDLE_DAYS = 7           # another session's quiet scratchpad directory is committed and removed at a start
TMP_MAX_FILE_MB = 20        # a larger file is never staged, so never deleted
TMP_MAX_FILES = 5000        # a scratchpad directory with more files is never committed or removed
TMP_IDLE_CLOSES = 5         # ended scratchpad directories committed and removed at one start, at most
TMP_EMPTY_IDLE_HOURS = 1    # another session's empty scratchpad directory quiet this long is removed
SCRATCH_SWEEP_MINUTES = 60  # another session's empty scratchpad folder quiet this long is removed, not linked
TMP_ENDED_QUIET_HOURS = 1   # an ended session's scratchpad directory is removed only when quiet this long
TMP_TOP_FOLDERS = 5         # folders named for one scratchpad directory in ended-sweep's list
TMP_SKIP_DIRS = [".pytest_cache", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", "pytest-of-*"]
SID_RE = re.compile(r"[A-Za-z0-9_-]+")


def configure(payload, write=True, root=None):
    """The scratchpad section of <project>/.claude/p4/p4.json over the constants, writing the file when it is
    missing unless `write` is False."""
    p4 = os.path.join(root or project_root(payload), ".claude", "p4")
    p4conf.configure(globals(), p4, "scratchpad", {
        "asks": "ASKS", "tmp": "TMP", "tmp_idle_days": "TMP_IDLE_DAYS", "tmp_max_file_mb": "TMP_MAX_FILE_MB",
        "tmp_max_files": "TMP_MAX_FILES", "tmp_empty_idle_hours": "TMP_EMPTY_IDLE_HOURS",
        "scratch_sweep_minutes": "SCRATCH_SWEEP_MINUTES", "tmp_skip_dirs": "TMP_SKIP_DIRS", "ignorable_ext": "IGNORABLE_EXT", "ignorable_dirs": "IGNORABLE_DIRS",
        "repo_uses_min_name": "REPO_USES_MIN_NAME", "repo_uses_max": "REPO_USES_MAX",
        "repo_uses_lines": "REPO_USES_LINES"}, write=write)


def layout(payload):
    """Files in an earlier place of the store's layout are moved into each plugin's folder first."""
    lines = p4conf.migrate_layout(os.path.join(project_root(payload), ".claude", "p4"))
    if lines:
        print("p4-temportal: " + "; ".join(lines) + ".")


def asks_on():
    env = os.environ.get(ASKS_ENV, "").strip()
    return env == "1" if env in ("0", "1") else bool(ASKS)


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


def cmd_notebook_out(payload):
    root = project_root(payload)
    reseeded, moved, tracked = sweep_notebook(root, time.strftime("%Y%m%d-%H%M%S"))
    parts = []
    if reseeded:
        parts.append("re-seeded .claude/p4/temportal/scratchpad/.out/.gitignore with `*`")
    if moved:
        parts.append(f"logs, build output and binaries moved: {len(moved)}, "
                     + ", ".join(moved[:6]) + (", …" if len(moved) > 6 else "")
                     + ", into .claude/p4/temportal/scratchpad/.out/")
    if tracked:
        parts.append(f"{len(tracked)} of them were tracked by the store and show as deleted there")
    if parts:
        print("p4-temportal: " + "; ".join(parts) + ".")
    return 0


# ---- the scratchpad directory ---------------------------------------------------------------------------------

def tmp_on():
    env = os.environ.get(TMP_ENV, "").strip()
    return env == "1" if env in ("0", "1") else bool(TMP)


def session_id(payload):
    sid = str(payload.get("session_id") or "")
    return sid if re.fullmatch(r"[A-Za-z0-9_-]+", sid) else ""


def harness_scratchpad(payload):
    """The scratchpad path Claude Code gives this session, `<temp>/claude*/<project>/<session>/scratchpad` under the
    system temp directory, /tmp or /private/tmp; it need not exist yet. None without a session id or that session's
    folder."""
    sid = session_id(payload)
    if not sid:
        return None
    given = payload.get("scratchpad_dir")              # on every hook's stdin from Claude Code 2.1.257
    if isinstance(given, str) and os.path.isabs(given):
        norm_given = os.path.normpath(given)
        if os.path.basename(norm_given) == "scratchpad" and os.path.basename(os.path.dirname(norm_given)) == sid:
            return given                               # only this session's own scratchpad is ever emptied
    seen = set()
    moved = os.environ.get("CLAUDE_CODE_TMPDIR")      # where Claude Code's temp tree was moved, before 2.1.257
    for r in ((moved,) if moved else ()) + (tempfile.gettempdir(), *TEMP_ROOTS):
        key = os.path.normcase(os.path.realpath(r))
        if key in seen or not os.path.isdir(r):
            continue
        seen.add(key)
        hits = sorted(glob.glob(os.path.join(glob.escape(r), "claude*", "*", sid)))
        if hits:
            return os.path.join(hits[0], "scratchpad")
    return None


def p4_tmp(root, payload):
    return p4conf.sub(os.path.join(root, ".claude", "p4"), "tmp", session_id(payload) or "session")


is_link = p4conf.is_link


def same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def make_link(link, target):
    """`link` -> `target`: a junction on Windows, which needs no privilege; a directory symlink elsewhere."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))
    else:
        os.symlink(os.path.abspath(target), link, target_is_directory=True)


def link_target(path):
    """Where a link points, as written in it, or '' when it cannot be read."""
    try:
        t = os.readlink(path)
    except (OSError, ValueError):
        return ""
    return os.path.normpath(t[4:] if t.startswith("\\\\?\\") else t)


remove_link = hookio.remove_link


def dangling(link, sid):
    """True for a link whose target is gone and was a `<sid>` folder inside a store: what is left of a session's
    scratchpad directory once it was removed."""
    t = link_target(link)
    return (bool(t) and not os.path.exists(link) and os.path.basename(t) == sid
            and "/.claude/p4/" in t.replace("\\", "/").lower())


def move_into(src, target, stamp):
    """Move every entry of `src` into `target`, a taken name getting the time as a suffix -> [moved names]."""
    moved = []
    for name in sorted(os.listdir(src)):
        dest = os.path.join(target, name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(dest)
            dest = f"{stem}.{stamp}{ext}"
        try:
            move_entry(os.path.join(src, name), dest)
            moved.append(name)
        except OSError:
            continue
    return moved


def move_entry(src, dest):
    """Move one file or folder. A folder that cannot be renamed, as from the temp drive to the project's, is copied
    and then removed with its read-only files, such as a clone's git objects: shutil.move stops at the first of
    those, after the copy, and leaves the folder in both places. A copy that fails is taken back."""
    try:
        os.rename(src, dest)
        return
    except OSError:
        pass
    if is_link(src) or not os.path.isdir(src):
        shutil.move(src, dest)
        return
    try:
        shutil.copytree(src, dest, symlinks=True)
    except OSError:
        try:
            remove_tree(dest)
        except OSError:
            pass
        raise
    remove_tree(src)


def remove_tree(path):
    """Remove a folder with all it holds, read-only files too; a link inside is removed, never followed."""
    with os.scandir(path) as entries:
        found = list(entries)
    for e in found:
        if is_link(e.path):
            if os.name == "nt" and os.path.isdir(e.path):
                os.rmdir(e.path)
            else:
                os.unlink(e.path)
        elif e.is_dir(follow_symlinks=False):
            remove_tree(e.path)
        else:
            try:
                os.unlink(e.path)
            except PermissionError:
                os.chmod(e.path, stat.S_IWRITE)
                os.unlink(e.path)
    os.rmdir(path)


def link_tmp(harness, target, stamp):
    """Make `harness` a link to `target`, moving what it holds into `target` first -> (state, [moved names]).
    The state is "linked" when the link is made, "kept" when it already reaches `target`, "foreign" when it is a link
    elsewhere, which is left as it is, or "failed" when something in it could not move or no link could be made, and a
    plain folder then stays in its place."""
    os.makedirs(target, exist_ok=True)
    if is_link(harness) and own_dangling(harness, target):
        try:
            remove_link(harness)                       # this session's link into an older layout: made again
        except OSError:
            return "failed", []
    if is_link(harness):
        return ("kept" if same_dir(harness, target) else "foreign"), []
    moved = []
    if os.path.isdir(harness):
        moved = move_into(harness, target, stamp)
        try:
            os.rmdir(harness)
        except OSError:
            return ("kept" if linked_to(harness, target) else "failed"), moved
    else:
        os.makedirs(os.path.dirname(harness), exist_ok=True)
    try:
        make_link(harness, target)
    except OSError:
        if linked_to(harness, target):                   # another session linked it in the same moment
            return "kept", moved
        os.makedirs(harness, exist_ok=True)              # Claude Code still finds a folder to write to
        return "failed", moved
    return "linked", moved


def own_dangling(harness, target):
    """A link that reaches nothing and names this session's folder in an earlier place of the store's layout,
    `.claude/p4/tmp/<sid>`, while `target` is its place now."""
    if os.path.exists(harness):
        return False
    try:
        dest = os.readlink(harness)
    except (OSError, ValueError):
        return False
    if dest.startswith("\\\\?\\"):
        dest = dest[4:]
    p4 = os.path.dirname(os.path.dirname(os.path.dirname(target)))
    older = [os.path.join(p4, *o.split("/"), os.path.basename(target)) for o in p4conf.OLDER["tmp"]]
    return any(os.path.normcase(os.path.normpath(dest)) == os.path.normcase(os.path.normpath(o)) for o in older)


def linked_to(harness, target):
    return is_link(harness) and same_dir(harness, target)


def git_p4(p4, *args, stdin=None, timeout=20):
    """One git command in the store -> the finished process, or None when git is missing or too slow."""
    try:
        return subprocess.run(["git", "-C", p4, *args], input=stdin, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def git_out(p4, *args, stdin=None):
    r = git_p4(p4, *args, stdin=stdin)
    return r.stdout.decode("utf-8", "replace") if r and r.returncode == 0 else None


def p4_repo(root):
    """`<root>/.claude/p4` when it is a git repository of its own, never the project's repository around it, else
    None."""
    p4 = os.path.join(root, ".claude", "p4")
    if not os.path.isdir(p4):
        return None
    top = git_out(p4, "rev-parse", "--show-toplevel")
    return p4 if top and same_dir(top.strip(), p4) else None


def tmp_rel(sid):
    return p4conf.rel("tmp", sid)


def tmp_files(target, copies=None):
    """The files of a scratchpad directory that may be staged, as absolute paths: not a link, not over the size cap,
    and not inside a copy of a repository or a store, by nested_repo. Each folder below the top that nested_repo leaves
    out is added to `copies` when it is a list. None when there are more than TMP_MAX_FILES, and stage_tmp then stages
    only the tracked files' changes."""
    out, cap = [], TMP_MAX_FILE_MB * 1024 * 1024
    for d, dirs, names in os.walk(target):
        if nested_repo(d, dirs, names, top=d == target):
            if copies is not None and d != target:
                copies.append(d)
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if not skipped_dir(x)]
        for n in names:
            p = os.path.join(d, n)
            try:
                if os.path.islink(p) or os.path.getsize(p) > cap:
                    continue
            except OSError:
                continue
            out.append(p)
            if len(out) > TMP_MAX_FILES:
                return None
    return out


def nested_repo(d, dirs, names, top=False):
    """A folder holding a repository or a store, which a scratchpad directory never stages: a clone or work tree with
    a .git folder or file, a bare repository, a project or copy holding .claude/p4, or a store itself, with p4.json
    beside phi/. Below the scratchpad directory's top, a copy or export of a repository without its .git too: a folder
    whose top holds .gitignore or .gitattributes, files a repository keeps, or .claude-plugin/, the folder of a
    plugin's or a marketplace's manifest. Such a copy duplicates thousands of files into the store's history, and it is
    the working copy of the session that made it. A .gitignore a session writes in a folder of its own leaves that
    folder on disk and out of every commit too, while one at the scratchpad directory's top keeps out only what it
    names."""
    return (".git" in dirs or ".git" in names or is_bare_repo(d)
            or os.path.isdir(os.path.join(d, ".claude", "p4"))
            or ("p4.json" in names and "phi" in dirs)
            or not top and (".gitignore" in names or ".gitattributes" in names or ".claude-plugin" in dirs))


def is_bare_repo(d):
    """A bare git repository, such as a test's remote: HEAD, objects/ and refs/ side by side."""
    return (os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects"))
            and os.path.isdir(os.path.join(d, "refs")))


def skipped_dir(name):
    """A folder named in TMP_SKIP_DIRS, where a trailing * matches a prefix: caches and test temp trees."""
    n = name.lower()
    return any(n.startswith(s[:-1].lower()) if s.endswith("*") else n == s.lower() for s in TMP_SKIP_DIRS)


def nul(paths):
    return "\0".join(paths).encode("utf-8", "surrogateescape")


def stage_tmp(p4, sid):
    """`git add` the session's scratchpad directory: every file tmp_files allows that git does not ignore, and the
    removal of a tracked file that is gone. A file that an earlier turn end staged in a folder nested_repo leaves out
    is taken out of the index again, while one a commit holds keeps that commit's version there, so no deletion of it
    is staged. False when the directory is too large to stage: then only its tracked files' changes are staged, so a
    file staged earlier and gone since does not stay staged."""
    target = p4conf.sub(p4, "tmp", sid)
    copies = []
    files = tmp_files(target, copies) if os.path.isdir(target) else []
    git_p4(p4, "add", "-u", "--", tmp_rel(sid), timeout=25)
    if files is None:
        return False
    if copies:
        git_p4(p4, "--literal-pathspecs", "reset", "-q", "--pathspec-from-file=-", "--pathspec-file-nul",
               stdin=nul([os.path.relpath(c, p4).replace("\\", "/") for c in copies]), timeout=25)
    rels = [os.path.relpath(f, p4).replace("\\", "/") for f in files]
    if rels:
        ignored = git_p4(p4, "check-ignore", "-z", "--stdin", stdin=nul(rels))
        skip = set(ignored.stdout.decode("utf-8", "surrogateescape").split("\0")) if ignored else set()
        rels = [r for r in rels if r not in skip]
    if rels:
        git_p4(p4, "add", "--pathspec-from-file=-", "--pathspec-file-nul", stdin=nul(rels), timeout=25)
    return True


def commit_flags(p4):
    """`git commit` as close_tmp runs it: literal pathspecs, past a failing pre-commit hook, and under the identity
    p4conf's own commits use when the store has none, so a close never fails on either."""
    known = all((git_out(p4, "config", key) or "").strip() for key in ("user.name", "user.email"))
    ident = [] if known else ["-c", "user.name=p4", "-c", "user.email=p4@localhost"]
    return ["--literal-pathspecs", *ident, "commit", "--no-verify"]


def closed_mark(p4, sid):
    """Where the commit of a removed scratchpad directory is noted: inside the store's git directory, out of the
    working tree."""
    gd = git_out(p4, "rev-parse", "--absolute-git-dir")
    return os.path.join(gd.strip(), "p4-tmp-closed", sid) if gd else None


def close_tmp(p4, sid):
    """A scratchpad directory that is done: staged, committed alone while whatever else is staged stays staged, and
    only then deleted, the removal committed too. A file no commit holds, because git ignores it, it is over the cap or
    it changed since, stays on disk. Returns the commit that holds the files, or '' when nothing was removed."""
    rel, target = tmp_rel(sid), p4conf.sub(p4, "tmp", sid)
    if not os.path.isdir(target) or stage_tmp(p4, sid) is False:
        return ""
    r = git_p4(p4, "diff", "--cached", "--quiet", "--", rel)
    if r is None:
        return ""
    if r.returncode == 1:
        # the staged paths alone: a pathspec commit takes every tracked path's working copy, a copy's edit included
        staged = [n for n in (git_out(p4, "diff", "--cached", "--no-renames", "--name-only", "-z", "--", rel) or "").split("\0") if n]
        c = git_p4(p4, *commit_flags(p4), "-q", "-m", f"tmp: session {sid[:8]}, kept before its removal",
                   "--pathspec-from-file=-", "--pathspec-file-nul", stdin=nul(staged)) if staged else None
        if c is None or c.returncode != 0:
            return ""                                  # not committed: nothing is deleted
    tracked = git_out(p4, "ls-files", "-z", "--", rel)
    changed = git_out(p4, "diff", "--name-only", "-z", "HEAD", "--", rel)
    head = git_out(p4, "rev-parse", "HEAD")
    if not tracked or changed is None or not head:
        return ""
    head = head.strip()
    changed = set(changed.split("\0"))
    mark = closed_mark(p4, sid)                        # written before any deletion, so a cut close is restored
    if mark:
        try:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, "w", encoding="utf-8") as f:
                f.write(head + "\n")
        except OSError:
            return ""                                  # no mark: nothing is deleted
    removed = []
    for name in tracked.split("\0"):
        if not name or name in changed:
            continue
        try:
            os.remove(os.path.join(p4, *name.split("/")))
            removed.append(name)
        except OSError:
            continue
    if not removed:
        return ""
    for d, _, _ in sorted(os.walk(target), key=lambda t: -len(t[0])):
        if not same_dir(d, target):
            try:
                os.rmdir(d)                            # only when emptied
            except OSError:
                pass
    git_p4(p4, *commit_flags(p4), "-q", "-m", f"tmp: session {sid[:8]} removed; its files are in "
           f"{head[:8]}", "--pathspec-from-file=-", "--pathspec-file-nul", stdin=nul(removed))   # the removals alone
    return head


def restore_tmp(p4, sid):
    """A session that goes on after its scratchpad directory was removed gets the files back from the commit that
    holds them: each one that is not on disk, staged again. Returns the commit, or ''."""
    mark = closed_mark(p4, sid)
    if not mark or not os.path.isfile(mark):
        return ""
    try:
        with open(mark, encoding="utf-8") as f:
            head = f.read().strip()
    except OSError:
        return ""
    names = git_out(p4, "ls-tree", "-r", "-z", "--name-only", head, "--", tmp_rel(sid))
    if names is None:
        return ""
    missing = [n for n in names.split("\0") if n and not os.path.exists(os.path.join(p4, *n.split("/")))]
    if missing:
        r = git_p4(p4, "checkout", head, "--pathspec-from-file=-", "--pathspec-file-nul", stdin=nul(missing))
        if r is None or r.returncode != 0:
            return ""
    try:
        os.remove(mark)
    except OSError:
        pass
    return head if missing else ""


def transcript_time(sid):
    """The last write to the session's transcript, `<config>/projects/*/<session>.jsonl`, or 0 when none is found."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    t = 0.0
    for f in glob.glob(os.path.join(glob.escape(cfg), "projects", "*", glob.escape(sid) + ".jsonl")):
        t = max(t, mtime(f))
    return t


def mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def links_to(hashdirs, target):
    """The scratchpad links under the project's temp folders that point at `target`, whether it exists or not."""
    want, out = os.path.normcase(os.path.normpath(target)), []
    for hashdir in ([hashdirs] if isinstance(hashdirs, str) else hashdirs or []):
        if not os.path.isdir(hashdir):
            continue
        for name in os.listdir(hashdir):
            sp = os.path.join(hashdir, name, "scratchpad")
            if is_link(sp) and os.path.normcase(link_target(sp)) == want:
                out.append(sp)
    return out


def temp_dirs(harness, own, root):
    """The project's folders of session folders under the temp directory: the one this session's scratchpad path is
    in, `<temp>/claude/<hash>`, and beside it the folder named after the project's path, every character but letters
    and digits a dash as in `E--projects-x`, where Claude Code put scratchpads before it named the folder by a hash.
    Empty when `harness` is not in Claude Code's layout, `<hash>/<session>/scratchpad`."""
    if not harness or not own or os.path.basename(os.path.dirname(os.path.normpath(harness))) != own:
        return []
    hashdir = os.path.dirname(os.path.dirname(os.path.normpath(harness)))
    out = [hashdir]
    if root:
        legacy = os.path.join(os.path.dirname(hashdir), re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(root)))
        if os.path.isdir(legacy) and not same_dir(legacy, hashdir):
            out.append(legacy)
    return out


def archived_ids(p4):
    """The session ids p4-phi's records hold as archived: the `sessionId` and every `cliSessionIds` entry of a
    `phi/sessions/*/session.json` whose `archived` is set. Read-only, and empty where p4-phi keeps nothing."""
    out = set()
    for f in glob.glob(os.path.join(glob.escape(p4), "phi", "sessions", "*", "session.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not rec.get("archived"):
            continue
        ids = rec.get("cliSessionIds")
        for i in [rec.get("sessionId"), *(ids if isinstance(ids, list) else [])]:
            if isinstance(i, str) and i:
                out.add(i)
    return out


def measure(path, cap=None):
    """A scratchpad directory as it is on disk -> (files, bytes, latest write, {top entry: files}, over). Every
    file counts, a clone's and an ignored one too, and a link is never followed. A file in the directory itself counts
    under ''. With `cap` the walk stops past that many files and `over` is True: the numbers are then a lower bound."""
    files, size, last, tops = 0, 0, mtime(path), {}
    for d, dirs, names in os.walk(path):
        dirs[:] = [x for x in dirs if not is_link(os.path.join(d, x))]
        rel = os.path.relpath(d, path)
        top = "" if rel == "." else rel.replace("\\", "/").split("/")[0] + "/"
        for n in names:
            try:
                st = os.lstat(os.path.join(d, n))
            except OSError:
                continue
            files += 1
            size += st.st_size
            last = max(last, st.st_mtime)
            tops[top] = tops.get(top, 0) + 1
            if cap is not None and files > cap:
                return files, size, last, tops, True
    return files, size, last, tops, False


def ended(sid, d, now, idle_days, archived, cap=None):
    """Why another session's scratchpad directory counts as ended, or '': "archived" by p4-phi's record, or "idle N
    days" when the directory and the session's transcript are quiet for `idle_days`. Either way nothing wrote to it for
    TMP_ENDED_QUIET_HOURS. A directory with more than `cap` files is judged by its transcript alone, and has not ended
    when no transcript is found."""
    _files, _size, last, _tops, over = measure(d, cap)
    seen = transcript_time(sid)
    last = (seen or now) if over else max(last, seen)
    if last > now - TMP_ENDED_QUIET_HOURS * 3600:
        return ""
    if sid in archived:
        return "archived"
    if idle_days is not None and idle_days >= 0 and last <= now - idle_days * 86400:
        return f"idle {int((now - last) // 86400)} days"
    return ""


def named_mark(p4, sid):
    """Where it is noted that an ended scratchpad directory over the cap was named: in the store's git directory,
    as closed_mark."""
    gd = git_out(p4, "rev-parse", "--absolute-git-dir")
    return os.path.join(gd.strip(), "p4-tmp-named", sid) if gd else None


def tops_text(tops):
    """The folders of a scratchpad directory holding the most files, most first: `runs/ 5000, smoke/ 3691, its own
    files 12`."""
    order = sorted(tops.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{k or 'its own files'} {n}" for k, n in order[:TMP_TOP_FOLDERS]) or "none"


def over_line(sid, why, d):
    """An ended session's scratchpad directory over the file cap, named with its file count and size: it is left
    as it is."""
    files, size, _last, tops, _over = measure(d)
    return (f"{tmp_rel(sid)}/ of an ended session, {why}, holds {files} files and {size / 1048576:.1f} MB, over the "
            f"cap of {TMP_MAX_FILES} files, so it is not committed and nothing of it is removed: removing it is "
            f"ezexe's to choose; top folders: {tops_text(tops)}")


def close_idle(p4, own, hashdir=None, named=None):
    """Other sessions' scratchpad directories whose session has ended, by ended: archived in p4-phi's record, or
    nothing written for TMP_IDLE_DAYS, a session that ended without a SessionEnd. Each is committed and removed as
    SessionEnd would, staged and untracked files alike, at most TMP_IDLE_CLOSES a start. One over TMP_MAX_FILES is left
    whole, and a line naming it is added to `named`, once. An empty one, quiet for TMP_EMPTY_IDLE_HOURS with its
    session's transcript, is removed with the scratchpad links under `hashdir`, one folder or several, that point at
    it."""
    base = p4conf.sub(p4, "tmp")
    if TMP_IDLE_DAYS is None or TMP_IDLE_DAYS < 0 or not os.path.isdir(base):
        return 0
    now = time.time()
    done, archived = 0, archived_ids(p4)
    for sid in sorted(os.listdir(base)):
        d = os.path.join(base, sid)
        if sid == own or not os.path.isdir(d) or is_link(d) or not SID_RE.fullmatch(sid):
            continue
        if not os.listdir(d):
            if TMP_EMPTY_IDLE_HOURS is None or TMP_EMPTY_IDLE_HOURS < 0:
                continue
            if max(mtime(d), transcript_time(sid)) > now - TMP_EMPTY_IDLE_HOURS * 3600:
                continue
            for sp in links_to(hashdir, d):
                try:
                    remove_link(sp)
                except OSError:
                    pass
            try:
                os.rmdir(d)
            except OSError:
                pass
            continue
        if done >= TMP_IDLE_CLOSES:
            continue
        why = ended(sid, d, now, TMP_IDLE_DAYS, archived, TMP_MAX_FILES)
        if not why:
            continue
        if tmp_files(d) is None:                       # over the cap: left whole, and named once
            mark = named_mark(p4, sid)
            if named is not None and mark and not os.path.exists(mark):
                named.append(over_line(sid, why, d))
                try:
                    os.makedirs(os.path.dirname(mark), exist_ok=True)
                    with open(mark, "w", encoding="utf-8") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M") + "\n")
                except OSError:
                    pass
            continue
        if close_tmp(p4, sid):
            done += 1
            try:
                os.rmdir(d)                            # when nothing uncommitted is left in it
            except OSError:
                pass
    return done


def plan_tmp(p4, sid):
    """What committing and removing a scratchpad directory would do, changing nothing, the index included ->
    {"files", "bytes", "tops", "over", "commit", "remove", "left"}. `remove` is every file a commit would hold
    afterwards: the files stage_tmp would add and those the index already tracks. Of those, a file in a folder
    nested_repo leaves out that HEAD does not hold is not counted, since stage_tmp takes it out of the index. `commit`
    is those of them HEAD does not hold as they are. `left` counts the files no commit would hold, which stay on disk.
    Over the cap, `commit` and `remove` are empty and `left` counts every file."""
    d, rel = p4conf.sub(p4, "tmp", sid), tmp_rel(sid)
    files, size, _last, tops, _over = measure(d)
    out = {"files": files, "bytes": size, "tops": tops, "over": False, "commit": [], "remove": [], "left": files}
    copies = []
    stage = tmp_files(d, copies)
    if stage is None:
        out["over"] = True
        return out
    rels = [os.path.relpath(f, p4).replace("\\", "/") for f in stage]
    if rels:
        ignored = git_p4(p4, "check-ignore", "-z", "--stdin", stdin=nul(rels))
        skip = set(ignored.stdout.decode("utf-8", "surrogateescape").split("\0")) if ignored else set()
        rels = [r for r in rels if r not in skip]
    held = {}
    tree = git_out(p4, "ls-tree", "-r", "-z", "HEAD", "--", rel) or ""
    for row in tree.split("\0"):
        meta, _, name = row.partition("\t")
        if name:
            held[name] = meta.split()[-1]
    left_out = tuple(os.path.relpath(c, p4).replace("\\", "/") + "/" for c in copies)
    tracked = git_out(p4, "ls-files", "-z", "--", rel) or ""
    remove = sorted(set(rels) | {t for t in tracked.split("\0")
                                 if t and os.path.isfile(os.path.join(p4, *t.split("/")))
                                 and (t in held or not t.startswith(left_out))})
    now_is = {}
    if remove and held:
        r = git_p4(p4, "hash-object", "--stdin-paths", stdin="\n".join(remove).encode("utf-8", "surrogateescape"),
                   timeout=120)
        got = r.stdout.decode("ascii", "replace").split() if r and r.returncode == 0 else []
        if len(got) == len(remove):
            now_is = dict(zip(remove, got))
    # a committed file of a copy is never staged, so close_tmp removes it only while it is as committed
    copied = [r for r in remove if r in held and left_out and r.startswith(left_out)]
    remove = [r for r in remove if r not in copied or now_is.get(r, held[r]) == held[r]]
    out["remove"] = remove
    out["commit"] = [r for r in remove if r not in copied and (r not in held or now_is.get(r) != held[r])]
    out["left"] = max(0, files - len(remove))
    return out


def sweep_ended(p4, dry, idle_days=None):
    """Every ended session's scratchpad directory in the store, committed and removed as SessionEnd would, or with
    `dry` only planned -> (rows of {"sid", "why", "plan", "head", "removed"}, the fullest first; the count of session
    folders looked at). One over the cap is never committed or removed."""
    base, now, rows = p4conf.sub(p4, "tmp"), time.time(), []
    if not os.path.isdir(base):
        return rows, 0
    days = TMP_IDLE_DAYS if idle_days is None else idle_days
    archived, seen = archived_ids(p4), 0
    for sid in sorted(os.listdir(base)):
        d = os.path.join(base, sid)
        if not os.path.isdir(d) or is_link(d) or not SID_RE.fullmatch(sid) or not os.listdir(d):
            continue
        seen += 1
        why = ended(sid, d, now, days, archived)
        if not why:
            continue
        plan = plan_tmp(p4, sid)
        row = {"sid": sid, "why": why, "plan": plan, "head": "", "removed": 0}
        if not dry and not plan["over"]:
            row["head"] = close_tmp(p4, sid)
            row["removed"] = sum(1 for r in plan["remove"] if not os.path.exists(os.path.join(p4, *r.split("/"))))
            try:
                os.rmdir(d)                            # when nothing uncommitted is left in it
            except OSError:
                pass
        rows.append(row)
    rows.sort(key=lambda r: (-r["plan"]["files"], r["sid"]))
    return rows, seen


def cmd_ended_sweep(args):
    """`ended-sweep [--dry-run] [--idle-days N] [--root <project>]`, run by hand: see the module's text."""
    dry, days, root, k = False, None, None, 0
    while k < len(args):
        a = args[k]
        if a == "--dry-run":
            dry = True
        elif a in ("--idle-days", "--root") and k + 1 < len(args):
            k += 1
            if a == "--root":
                root = args[k]
            else:
                try:
                    days = float(args[k])
                except ValueError:
                    print(f"p4-temportal: --idle-days takes a number, not {args[k]!r}; nothing was done.")
                    return 0
        else:
            print(f"p4-temportal: ended-sweep does not know {a!r}; nothing was done. "
                  "Usage: scratchpad.py ended-sweep [--dry-run] [--idle-days N] [--root <project>]")
            return 0
        k += 1
    root = os.path.abspath(root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    configure({}, write=not dry, root=root)
    p4 = p4_repo(root)
    if not p4:
        print(f"p4-temportal: {os.path.join(root, '.claude', 'p4')} is not a git repository of its own; "
              "nothing was done.")
        return 0
    rows, seen = sweep_ended(p4, dry, days)
    closing = [r for r in rows if not r["plan"]["over"]]
    over = [r for r in rows if r["plan"]["over"]]
    will = "would commit" if dry else "committed"
    gone = "would remove" if dry else "removed"
    n_commit = sum(len(r["plan"]["commit"]) for r in closing if dry or r["head"])
    n_remove = sum(len(r["plan"]["remove"]) if dry else r["removed"] for r in closing)
    print(f"p4-temportal: ended sessions' scratchpad directories in {os.path.normpath(p4)}"
          + (", a dry run that changed nothing" if dry else "")
          + f": session folders ended: {len(rows)} of {seen}; {will} files: {n_commit}, {gone}: {n_remove}; "
          + f"folders left on disk over the cap: {len(over)}, the cap being {TMP_MAX_FILES} files.")
    for r in rows:
        plan, rel = r["plan"], tmp_rel(r["sid"]) + "/"
        tail = f"{plan['files']} files, {plan['bytes'] / 1048576:.1f} MB; top folders: {tops_text(plan['tops'])}"
        if plan["over"]:
            print(f"- {rel} {r['why']}: over the cap, so not committed and nothing removed, and removing it is "
                  f"ezexe's to choose; {tail}")
        elif dry:
            print(f"- {rel} {r['why']}: would commit {len(plan['commit'])}, would remove {len(plan['remove'])}, "
                  f"would leave {plan['left']} that no commit would hold; {tail}")
        elif r["head"]:
            print(f"- {rel} {r['why']}: committed {len(plan['commit'])}, removed {r['removed']}, its files are in "
                  f"{r['head'][:8]}, left {plan['files'] - r['removed']} that no commit holds; {tail}")
        else:
            print(f"- {rel} {r['why']}: nothing removed, since no commit holds its files; {tail}")
    return 0


def sweep_scratchpads(harness, own, p4dir, stamp, root=None):
    """The project's other scratchpad folders, beside this session's under the temp directory and in the folder named
    after the project's path, by temp_dirs -> {"linked": n, "removed": n}. A real one is linked to its scratchpad
    directory in the store at once, its files moved in, so none stays a plain folder: Claude Code makes one for an id
    that never runs a hook, and no start of its own would link it. An empty one quiet for SCRATCH_SWEEP_MINUTES by the
    folder and the session's transcript is removed instead, with its session folder when that is left empty. A link
    to a folder of that session inside a store is removed when that folder is gone and the store holds no scratchpad
    directory for the session."""
    out = {"linked": 0, "removed": 0}
    if SCRATCH_SWEEP_MINUTES is None or SCRATCH_SWEEP_MINUTES < 0:
        return out
    quiet = time.time() - SCRATCH_SWEEP_MINUTES * 60
    for hashdir in temp_dirs(harness, own, root):
        try:
            sids = sorted(os.listdir(hashdir))
        except OSError:
            continue
        for sid in sids:
            sdir = os.path.join(hashdir, sid)
            sp = os.path.join(sdir, "scratchpad")
            if sid == own or not SID_RE.fullmatch(sid) or not os.path.lexists(sp):
                continue
            target = p4conf.sub(p4dir, "tmp", sid)
            if is_link(sp):
                if dangling(sp, sid) and not os.path.isdir(target):
                    try:
                        remove_link(sp)
                        out["removed"] += 1
                    except OSError:
                        pass
                continue
            if not os.path.isdir(sp):
                continue
            try:
                empty = not os.listdir(sp)
            except OSError:
                continue
            if empty and max(mtime(sp), mtime(sdir), transcript_time(sid)) <= quiet:
                try:
                    os.rmdir(sp)
                    out["removed"] += 1
                except OSError:
                    continue
                try:
                    os.rmdir(sdir)                     # only when the scratchpad was all it held
                except OSError:
                    pass
            elif link_tmp(sp, target, stamp)[0] == "linked":
                out["linked"] += 1
    return out


def cmd_tmp_link(payload):
    if not tmp_on():
        return 0
    harness = harness_scratchpad(payload)
    if not harness:
        return 0
    root = project_root(payload)
    target = p4_tmp(root, payload)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    state, moved = link_tmp(harness, target, stamp)
    here, there = os.path.normpath(harness), os.path.normpath(target)
    line = {"foreign": f"{here} is a link that does not reach {there}; left as it is",
            "failed": f"{here} could not be linked to {there}; its files move there at each turn end"}.get(state, "")
    if moved and state == "linked":                   # a new link alone is said by the skill, not at every start
        line = f"this session's scratchpad {here} is a link to {there}, where its temporary files go"
    if moved:
        line += ("; " if line else "") + f"files it held moved: {len(moved)}, into {there}"
    p4, sid = p4_repo(root), session_id(payload)
    if sid:
        swept = sweep_scratchpads(harness, sid, os.path.join(root, ".claude", "p4"), stamp, root)
        if any(swept.values()):
            line += ("; " if line else "") + "other sessions' scratchpads: " + ", ".join(
                f"{n} {k}" for k, n in swept.items() if n)
    if p4 and sid:
        back = restore_tmp(p4, sid)
        if back:
            line += ("; " if line else "") + f"this session's files were restored from commit {back[:8]} into {there}"
        named = []
        close_idle(p4, sid, temp_dirs(harness, sid, root), named)
        for n in named:
            line += ("; " if line else "") + n
    if line:
        print("p4-temportal: " + line + ".")
    return 0


def cmd_tmp_sweep(payload):
    """Stop: a scratchpad folder that is not a link yet, this session's or another's in the project, is moved and
    linked, and the session's scratchpad directory is staged in the store. Prints nothing."""
    if not tmp_on():
        return 0
    root = project_root(payload)
    harness = harness_scratchpad(payload)
    p4, sid = p4_repo(root), session_id(payload)
    if harness:          # links a late scratchpad folder, brings back a scratchpad directory removed while idle
        stamp = time.strftime("%Y%m%d-%H%M%S")
        link_tmp(harness, p4_tmp(root, payload), stamp)
        if sid:
            sweep_scratchpads(harness, sid, os.path.join(root, ".claude", "p4"), stamp, root)
    if p4 and sid:
        restore_tmp(p4, sid)
        stage_tmp(p4, sid)
    return 0


def cmd_tmp_close(payload):
    """SessionEnd: the session's scratchpad directory is committed, then its files are removed. Prints nothing."""
    if not tmp_on():
        return 0
    p4, sid = p4_repo(project_root(payload)), session_id(payload)
    if p4 and sid:
        close_tmp(p4, sid)
    return 0


# ---- repo-uses, one of the two asks ---------------------------------------------------------------------------

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


# ---- ask, one of the two asks ---------------------------------------------------------------------------------

def _norm(path):
    return path.replace("\\", "/").lower()


def in_harness_scratchpad(path):
    p = _norm(path)
    return any(m in p for m in SCRATCHPAD_MARKERS) and "/scratchpad" in p


def in_temp(path):
    """True for a path in a temp folder of the system: /tmp/ only at the root, since a repository's own tmp/ folder,
    or the store's temportal/tmp/, is no temp location."""
    p = _norm(path)
    return p.startswith(ROOT_TEMP) or any(m in p for m in TEMP_MARKERS)


def in_notebook(path):
    p = _norm(path)
    return "/.claude/p4/temportal/scratchpad/" in p or p.startswith(".claude/p4/temportal/scratchpad/")


def _first(m):
    return next((g for g in m.groups() if g), "")


def written_paths(payload):
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return []
    if tool in ("Write", "Edit", "NotebookEdit"):
        fp = str(inp.get("file_path") or inp.get("notebook_path") or "")
        return [fp] if fp else []
    if tool not in ("Bash", "PowerShell"):
        return []
    cmd = str(inp.get("command") or "")
    out = []
    for rx in WRITE_RES:
        out += [_first(m) for m in rx.finditer(cmd)]
    for rx in ARGS_RES:
        for m in rx.finditer(cmd):
            toks = [t.strip("\"'") for t in TOKEN_RE.findall(m.group(1)) if not t.startswith("-")]
            out += toks[-1:]                            # the destination: cp / mv write only their last argument
    for m in PS_WRITER_ARGS.finditer(cmd):
        out += [t.strip("\"'") for t in TOKEN_RE.findall(m.group(1)) if not t.startswith("-")]
    return [p for p in out if p]


def cmd_ask(payload):
    if not asks_on() or payload.get("agent_id"):
        return 0
    root = project_root(payload)
    src = p4conf.sub(os.path.join(root, ".claude", "p4"), "src")
    reasons, seen = [], set()
    for p in written_paths(payload):
        if p in seen or not is_code(p):
            continue
        seen.add(p)
        if in_harness_scratchpad(p):
            where = ("the session's scratchpad, kept in .claude/p4/temportal/tmp/ for notes and output"
                     if tmp_on() else "the session's scratchpad, which Claude Code deletes with its transcript")
        elif in_notebook(p):
            if p.lower().endswith(".ipynb"):            # the notebook folder is where p4-temportal keeps notebooks
                continue
            where = "the notebook .claude/p4/temportal/scratchpad/, which is for notes, logs and output"
        elif in_temp(p):
            where = "a temp location"
        else:
            continue
        name = os.path.basename(p.replace("\\", "/"))
        reasons.append(f"{name} is code headed for {where}, at {p}; if the repo will use it, it belongs in the repo "
                       f"where the repo keeps that kind of code, otherwise in {os.path.join(src, name)}")
    if not reasons:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": "p4-temportal: " + "; ".join(reasons[:3])
                                             + "."}}))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub == "ended-sweep":                           # run by hand: no payload on stdin to wait for
        try:
            return cmd_ended_sweep(sys.argv[2:])
        except Exception as e:  # noqa: BLE001
            print(f"p4-temportal scratchpad {sub} degraded: {type(e).__name__}: {e}")
            return 0
    payload = payload_from_stdin()
    try:
        configure(payload)
        if sub in ("notebook-out", "repo-uses", "tmp-link"):
            layout(payload)
        if sub == "notebook-out":
            return cmd_notebook_out(payload)
        if sub == "repo-uses":
            return cmd_repo_uses(payload)
        if sub == "ask":
            return cmd_ask(payload)
        if sub == "tmp-link":
            return cmd_tmp_link(payload)
        if sub == "tmp-sweep":
            return cmd_tmp_sweep(payload)
        if sub == "tmp-close":
            return cmd_tmp_close(payload)
        print(f"scratchpad.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-temportal scratchpad {sub} degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
