#!/usr/bin/env python3
"""scratchpad.py: p4-temportal's notebook part and its two asks. The notebook is the store's folder of notes kept
across sessions, at the place p4conf.LAYOUT gives the key `scratchpad`, `<project>/.claude/p4/temportal/notebook/`,
with its logs, build output and binaries in its `.out/`, which ignores itself. Each session's scratchpad directory is
Claude Code's own: it makes one under the system temp directory for each session and deletes it with the session's
transcript, and no command here moves, links, stages, commits or removes one.

  notebook-out   at SessionStart, seeds the notebook's `.out/.gitignore` with `*`, seeds it again when it is missing
                 or changed, and moves every log, build output and binary found elsewhere in the notebook into `.out/`
                 at the same relative path. A taken name gets the time as a suffix, and nothing is overwritten or
                 removed. It prints one line when it seeded the file again or moved something, and the first seed of a
                 new notebook is silent.

  tmp-unlink     at SessionStart, and by hand as `scratchpad.py tmp-unlink [project]`: every app scratchpad of the
                 project, `<temp>/claude*/<project>/<session>/scratchpad`, that an earlier version made a junction or a
                 symlink into the store's temportal/tmp/ becomes a real folder holding a copy of what the store folder
                 holds, since a write through such a link is a write under .claude/ that asks ezexe in every mode. The
                 link is removed as a link, the store's folder is left as it is, and a real folder is never touched.
                 It prints one line when it unlinked something.

`tmp-link` was the start command that made those links; a session started on 0.3.9 still runs it, and it now unlinks
as tmp-unlink does. `tmp-sweep` and `tmp-close` kept each session's scratchpad in the store; a session started before
they were retired still runs them, so they exit 0 and print nothing.

The two asks are off unless p4.json's scratchpad.asks is true or P4_SCRATCHPAD_ASKS=1:

  repo-uses      at SessionStart, prints one line for each file under `.claude/p4/temportal/src/` that the project
                 repository's tracked code, build, docs or CI names: that file is code the repository uses, so it
                 belongs there. It only reads, with one `git grep`, and is silent outside a git repository or without
                 git.
  ask            at PreToolUse, reads the paths a call writes: a Write's or Edit's file_path, and for a Bash command
                 every path in a write position, a redirect, tee, python's open() in a write mode, or the destination
                 of cp or mv. A code file, by extension or by name, headed for a temp location, the session's
                 scratchpad path or the notebook gets an ask naming where it belongs: the repository if it will use
                 the file, else the session's own scratchpad. A `.ipynb` headed for the notebook gets none, since the
                 notebook is where p4-temportal keeps notebooks. It never denies, and it is silent inside a subagent,
                 whose writer ezexe cannot redirect from the prompt.

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
# the commands that kept each session's scratchpad in the store, which a session started before they were retired
# still runs at its start, its turn ends and its end
RETIRED = ("tmp-sweep", "tmp-close")


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
    out = f".claude/p4/{p4conf.rel('scratchpad', OUT_NAME)}/"
    if reseeded:
        parts.append(f"re-seeded {out}.gitignore with `*`")
    if moved:
        parts.append(f"logs, build output and binaries moved: {len(moved)}, "
                     + ", ".join(moved[:6]) + (", …" if len(moved) > 6 else "") + f", into {out}")
    if tracked:
        parts.append(f"{len(tracked)} of them were tracked by the store and show as deleted there")
    if parts:
        print("p4-temportal: " + "; ".join(parts) + ".")
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
    p, nb = _norm(path), ".claude/p4/" + p4conf.rel("scratchpad").lower() + "/"
    return "/" + nb in p or p.startswith(nb)


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
    reasons, seen = [], set()
    for p in written_paths(payload):
        if p in seen or not is_code(p):
            continue
        seen.add(p)
        own = in_harness_scratchpad(p)
        if own:
            where = "the session's scratchpad, which Claude Code deletes with its transcript"
        elif in_notebook(p):
            if p.lower().endswith(".ipynb"):            # the notebook folder is where p4-temportal keeps notebooks
                continue
            where = f"the notebook .claude/p4/{p4conf.rel('scratchpad')}/, which is for notes, logs and output"
        elif in_temp(p):
            where = "a temp location"
        else:
            continue
        name = os.path.basename(p.replace("\\", "/"))
        reasons.append(f"{name} is code headed for {where}, at {p}; if the repo will use it, it belongs in the repo "
                       "where the repo keeps that kind of code" + ("" if own else ", otherwise in the session's own "
                                                                  "scratchpad"))
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
    if sub in RETIRED:
        return 0
    if sub in ("tmp-unlink", "tmp-link") and (len(sys.argv) > 2 or sys.stdin is None or sys.stdin.isatty()):
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
        if sub == "repo-uses":
            return cmd_repo_uses(payload)
        if sub == "ask":
            return cmd_ask(payload)
        if sub in ("tmp-unlink", "tmp-link"):          # tmp-link: what a session started on 0.3.9 still runs
            return cmd_tmp_unlink(payload)
        print(json.dumps({"systemMessage": f"scratchpad.py: unknown subcommand {sub!r}"}))
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        # a systemMessage reaches ezexe whatever the event, where the ask's plain stdout on PreToolUse reaches nobody
        print(json.dumps({"systemMessage": f"p4-temportal scratchpad {sub} degraded: {type(e).__name__}: {e}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
