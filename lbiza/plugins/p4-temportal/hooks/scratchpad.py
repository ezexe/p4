#!/usr/bin/env python3
"""scratchpad.py — the p4-temportal plugin's scratchpad part: the notebook lives in `<project>/.claude/p4/temportal/scratchpad/`, tracked by
the p4 repo, and its logs, build results and binaries live in its `.out/`, which ignores itself. A storage move:
nothing here tells the model how to behave unless ezexe turns the two asks on.

  notebook-out (SessionStart)  seeds `.claude/p4/temportal/scratchpad/.out/.gitignore` (`*`), re-seeds it when missing or
                               changed, and moves every ignorable found elsewhere in the notebook into `.out/` at the
                               same relative path (a taken name gets the time as a suffix; nothing overwritten or
                               removed). Silent unless it re-seeded or moved something, then one line. The first seed
                               of a new notebook is silent.

The session's temp directory, ON unless p4.json's scratchpad.tmp is false or P4_SCRATCHPAD_TMP=0:

  tmp-link (SessionStart)      the harness's per-session scratchpad (`%TEMP%/claude/<project>/<session>/scratchpad` on
                               Windows, `/private/tmp/claude-<uid>/<project>/<session>/scratchpad` on macOS) becomes a
                               link (a junction on Windows) to `.claude/p4/temportal/tmp/<session>/`, tracked by the p4 repo, so
                               what the session writes there is kept; what it already held is moved in first (a taken
                               name gets the time as a suffix). One line names the link when it is made. A link
                               left by an older layout or location, one whose target is gone or is
                               `.claude/p4/tmp/<session>`, is repaired: what the old target holds moves in first.
  scratch-sweep (SessionStart) the project's other scratchpads under the same temp folder, quiet for
                               scratchpad.scratch_sweep_minutes: a real one is linked like this session's, or removed
                               when it is empty (sessions that ran no hooks, such as the app's helpers, leave these);
                               a stale link is repaired as above, or removed when its target is gone and nothing in
                               p4 is left to point it at.
  tmp-sweep (Stop)             the same, silent: a scratchpad the start could not link, or that appeared after it, is
                               moved and linked at the turn's close. Then the session's tmp is staged in the p4 repo
                               (`git add`), every turn: never a file the repo ignores, one over
                               scratchpad.tmp_max_file_mb, a clone's or a bare repository's contents, or a directory
                               named in scratchpad.tmp_skip_dirs. A tmp over scratchpad.tmp_max_files has only its
                               tracked files' changes staged, so no file added earlier stays staged after it is gone.
  tmp-close (SessionEnd)       a tmp is deleted only after it is committed: the session's staged tmp is committed
                               alone (whatever else is staged stays staged), the files that commit holds are deleted,
                               and the removal is committed too. A file no commit holds stays on disk. The same is done
                               at a start for another session's tmp nothing has written to for
                               scratchpad.tmp_idle_days (a session that ended without a SessionEnd); an empty one is
                               removed once it and its session's transcript are quiet for
                               scratchpad.tmp_empty_idle_hours, with the scratchpad link that points at it. A session that
                               starts again after its tmp was closed gets its files back from that commit.
                               Nothing is staged, committed or deleted unless `.claude/p4` is a git repository of
                               its own.

Two asks, OFF unless the environment sets P4_SCRATCHPAD_ASKS=1 (design section 3.2, untested until measured):

  repo-uses (SessionStart)     one line per file under `.claude/p4/temportal/src/` that the project repo's tracked code, build,
                               docs or CI names: that file is code the repo uses, so it belongs in the repo. Read-only,
                               one `git grep`; silent outside a git repo or without git.
  ask (PreToolUse)             for a Write or Edit, the file_path; for a Bash command, every write-position path
                               (redirects, tee, python's open() in a write mode, cp / mv destinations). A CODE file
                               (by extension or by name) headed for a temp location, the harness's per-session
                               scratchpad, or `.claude/p4/temportal/scratchpad/` gets an ask (never a deny) naming where it
                               belongs: the repo if the repo will use it, else `.claude/p4/temportal/src/`. Silent inside a
                               subagent, whose writer the human answering the prompt cannot redirect.

Every failure prints a one-line notice and exits 0.
"""

import json
import os
import glob
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402  (the settings file, .claude/p4/p4.json)

ASKS_ENV = "P4_SCRATCHPAD_ASKS"
TMP_ENV = "P4_SCRATCHPAD_TMP"
HARNESS_ENV = "P4_SCRATCHPAD_HARNESS"   # tests and odd installs name the harness's scratchpad themselves
TEMP_ROOTS = ("/tmp", "/private/tmp")   # beside tempfile.gettempdir(): where the harness puts its claude*

CODE_EXT = {"py", "pyw", "sh", "bash", "zsh", "ps1", "psm1", "bat", "cmd", "js", "mjs", "cjs", "ts", "rb", "pl",
            "lua", "php", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "java", "kt", "swift", "sql", "awk",
            "r", "jl", "scala", "groovy", "tcl", "vbs", "cmake", "gn", "gni", "html", "htm"}
# Code by name rather than by extension: by extension alone CMakeLists.txt is a `.txt` note.
CODE_NAMES = {"cmakelists.txt", "makefile", "gnumakefile", "dockerfile", "justfile", "rakefile"}
SCRATCHPAD_MARKERS = ("/temp/claude/", "/tmp/claude/")          # the harness's per-session scratchpad
TEMP_MARKERS = ("/tmp/", "/appdata/local/temp/", "/var/folders/", "/private/tmp/", "%temp%", "%tmp%",
                "$tmpdir", "${tmpdir}", "$env:temp", "$env:tmp")
_PATH = r"(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^\s\"'<>|;&()`]+))"
WRITE_RES = [
    re.compile(r">{1,2}[ \t]*" + _PATH),
    re.compile(r"\btee\b(?:[ \t]+-[A-Za-z]+)*[ \t]+" + _PATH),
    re.compile(r"\bopen\(\s*(?:\"([^\"\n]+)\"|'([^'\n]+)')\s*,\s*[\"'][aw]"),
]
ARGS_RES = [re.compile(r"\b(?:cp|mv)\b([^\n|;&]*)")]
TOKEN_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|\S+")

OUT_NAME = ".out"
OUT_IGNORE = "*\n"
IGNORABLE_EXT = {"log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so", "dylib",
                 "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"}
IGNORABLE_DIRS = {"bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__", ".cache",
                  "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"}

REPO_USES_MIN_NAME = 6     # a basename shorter than this (`a.py`, `run.sh`) matches too much to call it a use
REPO_USES_MAX = 200        # candidate names one git grep carries
REPO_USES_LINES = 10       # lines printed at most; the rest counted on one more


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


ASKS = False                # p4.json scratchpad.asks; P4_SCRATCHPAD_ASKS=1 or 0 wins for one run
TMP = True                  # p4.json scratchpad.tmp; P4_SCRATCHPAD_TMP=1 or 0 wins for one run
TMP_IDLE_DAYS = 7           # another session's tmp untouched this long is committed and deleted at a start
TMP_MAX_FILE_MB = 20        # a larger file is never staged, so never deleted
TMP_MAX_FILES = 5000        # a tmp with more files is left alone: not staged, not deleted
TMP_IDLE_CLOSES = 5         # idle tmps closed at one start, at most
TMP_EMPTY_IDLE_HOURS = 1    # another session's empty tmp quiet this long is removed at a start
SCRATCH_SWEEP_MINUTES = 60  # another session's scratchpad quiet this long is linked, repaired or removed at a start
TMP_SKIP_DIRS = [".pytest_cache", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", "pytest-of-*"]
SID_RE = re.compile(r"[A-Za-z0-9_-]+")


def configure(payload):
    """The scratchpad section of <project>/.claude/p4/p4.json over the constants (the file written when missing)."""
    p4 = os.path.join(project_root(payload), ".claude", "p4")
    p4conf.configure(globals(), p4, "scratchpad", {
        "asks": "ASKS", "tmp": "TMP", "tmp_idle_days": "TMP_IDLE_DAYS", "tmp_max_file_mb": "TMP_MAX_FILE_MB",
        "tmp_max_files": "TMP_MAX_FILES", "tmp_empty_idle_hours": "TMP_EMPTY_IDLE_HOURS",
        "scratch_sweep_minutes": "SCRATCH_SWEEP_MINUTES", "tmp_skip_dirs": "TMP_SKIP_DIRS", "ignorable_ext": "IGNORABLE_EXT", "ignorable_dirs": "IGNORABLE_DIRS",
        "repo_uses_min_name": "REPO_USES_MIN_NAME", "repo_uses_max": "REPO_USES_MAX",
        "repo_uses_lines": "REPO_USES_LINES"})


def layout(payload):
    """A store an older plugin wrote flat in .claude/p4 is moved into each plugin's directory first."""
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
    """True for a notebook path (relative to the notebook) that is a log, a build result or a binary."""
    parts = [s for s in rel.replace("\\", "/").split("/") if s]
    if not parts or parts[0] == OUT_NAME:
        return False
    if any(s.lower() in IGNORABLE_DIRS for s in parts[:-1]):
        return True
    return os.path.splitext(parts[-1])[1].lower().lstrip(".") in IGNORABLE_EXT


def tracked_in_p4(p4, rels):
    """The subset of notebook-relative paths the p4 repo's index holds (read-only; empty without git)."""
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
    """Seed `.out/` and move the notebook's ignorables into it -> (reseeded, [moved rel paths], [tracked rels]).
    `reseeded` is False for the first seed of a new `.out/`, which is silent."""
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
    if moved:   # directories the sweep emptied are removed, the empty ones only
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
        parts.append("re-seeded .claude/p4/temportal/scratchpad/.out/.gitignore (`*`)")
    if moved:
        parts.append(f"moved {len(moved)} log/build/binary file(s) into .claude/p4/temportal/scratchpad/.out/ ("
                     + ", ".join(moved[:6]) + (", …" if len(moved) > 6 else "") + ")")
    if tracked:
        parts.append(f"{len(tracked)} of them were tracked by the p4 repo and now show as deleted there")
    if parts:
        print("p4-temportal: " + "; ".join(parts) + ".")
    return 0


# ---- tmp ------------------------------------------------------------------------------------------------------

def tmp_on():
    env = os.environ.get(TMP_ENV, "").strip()
    return env == "1" if env in ("0", "1") else bool(TMP)


def session_id(payload):
    sid = str(payload.get("session_id") or "")
    return sid if re.fullmatch(r"[A-Za-z0-9_-]+", sid) else ""


def harness_scratchpad(payload):
    """The harness's scratchpad for this session, `<temp>/claude*/<project>/<session>/scratchpad` under the system temp
    directory, /tmp or /private/tmp; it need not exist yet. None without a session id or that session's directory."""
    if os.environ.get(HARNESS_ENV):
        return os.environ[HARNESS_ENV]
    sid = session_id(payload)
    if not sid:
        return None
    seen = set()
    for r in (tempfile.gettempdir(), *TEMP_ROOTS):
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
    """Where a link points, as written in it ('' when it cannot be read)."""
    try:
        t = os.readlink(path)
    except (OSError, ValueError):
        return ""
    return os.path.normpath(t[4:] if t.startswith("\\\\?\\") else t)


def remove_link(path):
    """Remove a link (a junction or a symlink), never what it points at."""
    if os.name == "nt":
        os.rmdir(path)
    else:
        os.unlink(path)


def stale_link(link, target):
    """True for a link to this session's tmp left by an older layout or location: its target is gone and was a
    `.claude/p4/.../<session>` directory, or it is another directory of that name inside the same p4 store."""
    t, sid = link_target(link), os.path.basename(os.path.normpath(target))
    if not t or os.path.basename(t) != sid:
        return False
    if not os.path.exists(link):
        return "/.claude/p4/" in t.replace("\\", "/").lower()
    p4 = os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(target)))))
    return os.path.normcase(t).startswith(p4 + os.sep) and not same_dir(t, target)


def move_into(src, target, stamp):
    """Move every entry of `src` into `target` (a taken name gets the time as a suffix) -> [moved names]."""
    moved = []
    for name in sorted(os.listdir(src)):
        dest = os.path.join(target, name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(dest)
            dest = f"{stem}.{stamp}{ext}"
        try:
            shutil.move(os.path.join(src, name), dest)
            moved.append(name)
        except OSError:
            continue
    return moved


def link_tmp(harness, target, stamp):
    """Make `harness` a link to `target`, moving what it holds into `target` first -> (state, [moved names]):
    "linked" (made now), "kept" (already a link to `target`), "repaired" (a stale link re-pointed, what its old
    target held moved in), "foreign" (a link elsewhere, left as it is) or "failed" (something in it could not move,
    or no link could be made; a plain directory stays in its place)."""
    os.makedirs(target, exist_ok=True)
    if is_link(harness):
        if same_dir(harness, target):
            return "kept", []
        if not stale_link(harness, target):
            return "foreign", []
        old = link_target(harness)
        try:
            remove_link(harness)
        except OSError:
            return "failed", []
        moved = []
        if os.path.isdir(old) and not is_link(old):
            moved = move_into(old, target, stamp)
            try:
                os.rmdir(old)
            except OSError:
                pass
        try:
            make_link(harness, target)
        except OSError:
            os.makedirs(harness, exist_ok=True)
            return "failed", moved
        return "repaired", moved
    moved = []
    if os.path.isdir(harness):
        moved = move_into(harness, target, stamp)
        try:
            os.rmdir(harness)
        except OSError:
            return "failed", moved
    else:
        os.makedirs(os.path.dirname(harness), exist_ok=True)
    try:
        make_link(harness, target)
    except OSError:
        os.makedirs(harness, exist_ok=True)              # the harness still finds a directory to write to
        return "failed", moved
    return "linked", moved


def git_p4(p4, *args, stdin=None, timeout=20):
    """One git command in the p4 repo -> the finished process, or None when git is missing or too slow."""
    try:
        return subprocess.run(["git", "-C", p4, *args], input=stdin, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def git_out(p4, *args, stdin=None):
    r = git_p4(p4, *args, stdin=stdin)
    return r.stdout.decode("utf-8", "replace") if r and r.returncode == 0 else None


def p4_repo(root):
    """`<root>/.claude/p4` when it is a git repository of its own (never the project's repo around it), else None."""
    p4 = os.path.join(root, ".claude", "p4")
    if not os.path.isdir(p4):
        return None
    top = git_out(p4, "rev-parse", "--show-toplevel")
    return p4 if top and same_dir(top.strip(), p4) else None


def tmp_rel(sid):
    return p4conf.rel("tmp", sid)


def tmp_files(target):
    """The files of a tmp that may be staged, as absolute paths: not a link, not over the size cap, not inside a
    clone (a directory with its own .git). None when there are more than TMP_MAX_FILES: such a tmp is left alone."""
    out, cap = [], TMP_MAX_FILE_MB * 1024 * 1024
    for d, dirs, names in os.walk(target):
        if ".git" in dirs or ".git" in names or is_bare_repo(d):
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


def is_bare_repo(d):
    """A bare git repository, such as a test's remote: HEAD, objects/ and refs/ side by side."""
    return (os.path.isfile(os.path.join(d, "HEAD")) and os.path.isdir(os.path.join(d, "objects"))
            and os.path.isdir(os.path.join(d, "refs")))


def skipped_dir(name):
    """A directory named in TMP_SKIP_DIRS, where a trailing * matches a prefix: caches and test temp trees."""
    n = name.lower()
    return any(n.startswith(s[:-1].lower()) if s.endswith("*") else n == s.lower() for s in TMP_SKIP_DIRS)


def nul(paths):
    return "\0".join(paths).encode("utf-8", "surrogateescape")


def stage_tmp(p4, sid):
    """`git add` the session's tmp: every file tmp_files allows that the repo does not ignore, and the removal of a
    tracked file that is gone. False when the tmp is too large to stage: then only its tracked files' changes are
    staged, so a file staged earlier and gone since does not stay staged."""
    target = p4conf.sub(p4, "tmp", sid)
    files = tmp_files(target) if os.path.isdir(target) else []
    git_p4(p4, "add", "-u", "--", tmp_rel(sid), timeout=25)
    if files is None:
        return False
    rels = [os.path.relpath(f, p4).replace("\\", "/") for f in files]
    if rels:
        ignored = git_p4(p4, "check-ignore", "-z", "--stdin", stdin=nul(rels))
        skip = set(ignored.stdout.decode("utf-8", "surrogateescape").split("\0")) if ignored else set()
        rels = [r for r in rels if r not in skip]
    if rels:
        git_p4(p4, "add", "--pathspec-from-file=-", "--pathspec-file-nul", stdin=nul(rels), timeout=25)
    return True


def closed_mark(p4, sid):
    """Where a closed tmp's commit is noted: inside the repo's own git directory, out of the working tree."""
    gd = git_out(p4, "rev-parse", "--absolute-git-dir")
    return os.path.join(gd.strip(), "p4-tmp-closed", sid) if gd else None


def close_tmp(p4, sid):
    """A tmp that is done: staged, committed alone (what else is staged stays staged), and only then deleted, the
    removal committed too. A file no commit holds (ignored, over the cap, changed since) stays on disk. Returns the
    commit that holds the files, or '' when nothing was removed."""
    rel, target = tmp_rel(sid), p4conf.sub(p4, "tmp", sid)
    if not os.path.isdir(target) or stage_tmp(p4, sid) is False:
        return ""
    r = git_p4(p4, "diff", "--cached", "--quiet", "--", rel)
    if r is None:
        return ""
    if r.returncode == 1:
        c = git_p4(p4, "commit", "-q", "-m", f"tmp: session {sid[:8]}, kept before its removal", "--", rel)
        if c is None or c.returncode != 0:
            return ""                                  # not committed: nothing is deleted
    tracked = git_out(p4, "ls-files", "-z", "--", rel)
    changed = git_out(p4, "diff", "--name-only", "-z", "HEAD", "--", rel)
    head = git_out(p4, "rev-parse", "HEAD")
    if not tracked or changed is None or not head:
        return ""
    head = head.strip()
    changed = set(changed.split("\0"))
    removed = 0
    for name in tracked.split("\0"):
        if not name or name in changed:
            continue
        try:
            os.remove(os.path.join(p4, *name.split("/")))
            removed += 1
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
    git_p4(p4, "add", "-u", "--", rel)
    git_p4(p4, "commit", "-q", "-m", f"tmp: session {sid[:8]} removed; its files are in {head[:8]}", "--", rel)
    mark = closed_mark(p4, sid)
    if mark:
        try:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, "w", encoding="utf-8") as f:
                f.write(head + "\n")
        except OSError:
            pass
    return head


def restore_tmp(p4, sid):
    """A session that goes on after its tmp was closed gets the files back from the commit that holds them: each
    one that is not on disk now, staged again. Returns the commit, or ''."""
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


def newest(path):
    """The latest modification time under a directory (its own when it holds nothing)."""
    try:
        t = os.path.getmtime(path)
    except OSError:
        return time.time()
    seen = 0
    for d, _, names in os.walk(path):
        for n in names:
            try:
                t = max(t, os.path.getmtime(os.path.join(d, n)))
            except OSError:
                pass
            seen += 1
            if seen > TMP_MAX_FILES:
                return time.time()                     # too large to judge: not idle
    return t


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


def links_to(hashdir, target):
    """The scratchpad links under the project's temp folder that point at `target`, whether it exists or not."""
    if not hashdir or not os.path.isdir(hashdir):
        return []
    want, out = os.path.normcase(os.path.normpath(target)), []
    for name in os.listdir(hashdir):
        sp = os.path.join(hashdir, name, "scratchpad")
        if is_link(sp) and os.path.normcase(link_target(sp)) == want:
            out.append(sp)
    return out


def close_idle(p4, own, hashdir=None):
    """Other sessions' tmps nothing has written to for TMP_IDLE_DAYS: sessions that ended without a SessionEnd.
    At most TMP_IDLE_CLOSES a start. An empty one, quiet for TMP_EMPTY_IDLE_HOURS with its session's transcript, is
    removed with the scratchpad links under `hashdir` that point at it."""
    base = p4conf.sub(p4, "tmp")
    if TMP_IDLE_DAYS is None or TMP_IDLE_DAYS < 0 or not os.path.isdir(base):
        return 0
    now = time.time()
    limit, done = now - TMP_IDLE_DAYS * 86400, 0
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
        if done >= TMP_IDLE_CLOSES or max(newest(d), transcript_time(sid)) > limit:
            continue
        if close_tmp(p4, sid):
            done += 1
            try:
                os.rmdir(d)                            # when nothing uncommitted is left in it
            except OSError:
                pass
    return done


def sweep_scratchpads(harness, own, p4dir, stamp):
    """The project's other scratchpads, beside this session's under the temp folder, quiet for SCRATCH_SWEEP_MINUTES
    by the folder and the session's transcript -> {"linked": n, "removed": n, "repaired": n}. A real empty one is
    removed, with its session folder when that is left empty; a real one with files is linked into p4's tmp; a stale
    link is repaired, or removed when its target is gone and p4 holds no tmp for that session."""
    out = {"linked": 0, "removed": 0, "repaired": 0}
    if not harness or os.path.basename(os.path.dirname(os.path.normpath(harness))) != own:
        return out                                     # only the harness's own layout: <hash>/<session>/scratchpad
    hashdir = os.path.dirname(os.path.dirname(os.path.normpath(harness)))
    if SCRATCH_SWEEP_MINUTES is None or SCRATCH_SWEEP_MINUTES < 0 or not os.path.isdir(hashdir):
        return out
    quiet = time.time() - SCRATCH_SWEEP_MINUTES * 60
    for sid in sorted(os.listdir(hashdir)):
        sdir = os.path.join(hashdir, sid)
        sp = os.path.join(sdir, "scratchpad")
        if sid == own or not SID_RE.fullmatch(sid) or not os.path.lexists(sp):
            continue
        target = p4conf.sub(p4dir, "tmp", sid)
        if is_link(sp):
            if same_dir(sp, target) or not stale_link(sp, target):
                continue
            old = link_target(sp)
            if os.path.isdir(target) or (os.path.isdir(old) and os.listdir(old)):
                if link_tmp(sp, target, stamp)[0] == "repaired":
                    out["repaired"] += 1
            elif not os.path.exists(sp):
                try:
                    remove_link(sp)
                    out["removed"] += 1
                except OSError:
                    pass
            continue
        if not os.path.isdir(sp) or max(mtime(sp), mtime(sdir), transcript_time(sid)) > quiet:
            continue
        try:
            empty = not os.listdir(sp)
        except OSError:
            continue
        if empty:
            try:
                os.rmdir(sp)
                out["removed"] += 1
            except OSError:
                continue
            try:
                os.rmdir(sdir)                         # only when the scratchpad was all it held
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
    line = {"linked": f"this session's scratchpad {here} is a link to {there}, tracked by the p4 repo",
            "repaired": f"this session's scratchpad {here} was a stale link and now reaches {there}",
            "foreign": f"{here} is a link that does not reach {there}; left as it is",
            "failed": f"{here} could not be linked to {there}; its files move there at each turn's close"}.get(state, "")
    if moved:
        line += ("; " if line else "") + f"moved {len(moved)} file(s) it held into {there}"
    p4, sid = p4_repo(root), session_id(payload)
    if sid:
        swept = sweep_scratchpads(harness, sid, os.path.join(root, ".claude", "p4"), stamp)
        if any(swept.values()):
            line += ("; " if line else "") + "other sessions' scratchpads: " + ", ".join(
                f"{n} {k}" for k, n in swept.items() if n)
    if p4 and sid:
        back = restore_tmp(p4, sid)
        if back:
            line += ("; " if line else "") + f"this session's tmp files were restored from commit {back[:8]} into {there}"
        close_idle(p4, sid, os.path.dirname(os.path.dirname(os.path.normpath(harness))))
    if line:
        print("p4-temportal: " + line + ".")
    return 0


def cmd_tmp_sweep(payload):
    """Stop: a scratchpad that is not the link yet is moved and linked, and the session's tmp is staged in the p4
    repo. Prints nothing."""
    if not tmp_on():
        return 0
    root = project_root(payload)
    harness = harness_scratchpad(payload)
    if harness:          # links a late scratchpad, repairs a stale link, brings back a tmp removed while idle
        link_tmp(harness, p4_tmp(root, payload), time.strftime("%Y%m%d-%H%M%S"))
    p4, sid = p4_repo(root), session_id(payload)
    if p4 and sid:
        restore_tmp(p4, sid)
        stage_tmp(p4, sid)
    return 0


def cmd_tmp_close(payload):
    """SessionEnd: the session's tmp is committed, then deleted. Prints nothing."""
    if not tmp_on():
        return 0
    p4, sid = p4_repo(project_root(payload)), session_id(payload)
    if p4 and sid:
        close_tmp(p4, sid)
    return 0


# ---- repo-uses (opt-in) ---------------------------------------------------------------------------------------

def repo_use_candidates(root):
    """{basename: [project-relative paths]} — every code file under `.claude/p4/temportal/src/` (dot-directories skipped)
    whose name is distinctive enough to look for."""
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
    """[(project-relative path, [repo files that name it])] — one `git grep` over the project repo's tracked files;
    `.claude/p4` is its own repository and excluded, so a file's own notes never count as a use."""
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
        lines.append(f"(+{len(used) - REPO_USES_LINES} more files under .claude/p4/temportal/src/ the repo names)")
    if lines:
        print("\n".join(lines))
    return 0


# ---- ask (opt-in) ---------------------------------------------------------------------------------------------

def _norm(path):
    return path.replace("\\", "/").lower()


def in_harness_scratchpad(path):
    p = _norm(path)
    return any(m in p for m in SCRATCHPAD_MARKERS) and "/scratchpad" in p


def in_temp(path):
    p = _norm(path)
    return any(m in p for m in TEMP_MARKERS)


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
    if tool in ("Write", "Edit"):
        fp = str(inp.get("file_path") or "")
        return [fp] if fp else []
    if tool != "Bash":
        return []
    cmd = str(inp.get("command") or "")
    out = []
    for rx in WRITE_RES:
        out += [_first(m) for m in rx.finditer(cmd)]
    for rx in ARGS_RES:
        for m in rx.finditer(cmd):
            toks = [t.strip("\"'") for t in TOKEN_RE.findall(m.group(1)) if not t.startswith("-")]
            out += toks[-1:]                            # the destination: cp / mv write only their last argument
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
            where = ("the harness's per-session scratchpad, kept in .claude/p4/temportal/tmp/ for notes and output"
                     if tmp_on() else "the harness's per-session scratchpad, which is gone with the session")
        elif in_notebook(p):
            where = "the notebook .claude/p4/temportal/scratchpad/, which is for notes, logs and output"
        elif in_temp(p):
            where = "a temp location"
        else:
            continue
        name = os.path.basename(p.replace("\\", "/"))
        reasons.append(f"{name} is code headed for {where} ({p}); if the repo will use it, it belongs in the repo "
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
        print(f"p4-temportal scratchpad ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
