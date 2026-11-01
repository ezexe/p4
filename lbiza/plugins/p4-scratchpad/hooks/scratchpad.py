#!/usr/bin/env python3
"""scratchpad.py — the p4-scratchpad plugin: the notebook lives in `<project>/.claude/p4/scratchpad/`, tracked by
the p4 repo, and its logs, build results and binaries live in its `.out/`, which ignores itself. A storage move:
nothing here tells the model how to behave unless the owner turns the two asks on.

  notebook-out (SessionStart)  seeds `.claude/p4/scratchpad/.out/.gitignore` (`*`), re-seeds it when missing or
                               changed, and moves every ignorable found elsewhere in the notebook into `.out/` at the
                               same relative path (a taken name gets the time as a suffix; nothing overwritten or
                               removed). Silent unless it re-seeded or moved something, then one line. The first seed
                               of a new notebook is silent.

Two asks, OFF unless the environment sets P4_SCRATCHPAD_ASKS=1 (design section 3.2, untested until measured):

  repo-uses (SessionStart)     one line per file under `.claude/p4/src/` that the project repo's tracked code, build,
                               docs or CI names: that file is code the repo uses, so it belongs in the repo. Read-only,
                               one `git grep`; silent outside a git repo or without git.
  ask (PreToolUse)             for a Write or Edit, the file_path; for a Bash command, every write-position path
                               (redirects, tee, python's open() in a write mode, cp / mv destinations). A CODE file
                               (by extension or by name) headed for a temp location, the harness's per-session
                               scratchpad, or `.claude/p4/scratchpad/` gets an ask (never a deny) naming where it
                               belongs: the repo if the repo will use it, else `.claude/p4/src/`. Silent inside a
                               subagent, whose writer the human answering the prompt cannot redirect.

Every failure prints a one-line notice and exits 0.
"""

import json
import os
import re
import subprocess
import sys
import time

ASKS_ENV = "P4_SCRATCHPAD_ASKS"

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


def asks_on():
    return os.environ.get(ASKS_ENV, "").strip() == "1"


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
        r = subprocess.run(["git", "-C", p4, "ls-files", "-z", "--", "scratchpad"], capture_output=True, timeout=15)
    except Exception:
        return set()
    listed = {s.decode("utf-8", "replace")[len("scratchpad/"):] for s in r.stdout.split(b"\0") if s}
    return {rel for rel in rels if rel in listed}


def sweep_notebook(root, now_tag):
    """Seed `.out/` and move the notebook's ignorables into it -> (reseeded, [moved rel paths], [tracked rels]).
    `reseeded` is False for the first seed of a new `.out/`, which is silent."""
    p4 = os.path.join(root, ".claude", "p4")
    pad = os.path.join(p4, "scratchpad")
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
        parts.append("re-seeded .claude/p4/scratchpad/.out/.gitignore (`*`)")
    if moved:
        parts.append(f"moved {len(moved)} log/build/binary file(s) into .claude/p4/scratchpad/.out/ ("
                     + ", ".join(moved[:6]) + (", …" if len(moved) > 6 else "") + ")")
    if tracked:
        parts.append(f"{len(tracked)} of them were tracked by the p4 repo and now show as deleted there")
    if parts:
        print("p4-scratchpad: " + "; ".join(parts) + ".")
    return 0


# ---- repo-uses (opt-in) ---------------------------------------------------------------------------------------

def repo_use_candidates(root):
    """{basename: [project-relative paths]} — every code file under `.claude/p4/src/` (dot-directories skipped)
    whose name is distinctive enough to look for."""
    src = os.path.join(root, ".claude", "p4", "src")
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
        lines.append(f"(+{len(used) - REPO_USES_LINES} more files under .claude/p4/src/ the repo names)")
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
    return "/.claude/p4/scratchpad/" in p or p.startswith(".claude/p4/scratchpad/")


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
    src = os.path.join(root, ".claude", "p4", "src")
    reasons, seen = [], set()
    for p in written_paths(payload):
        if p in seen or not is_code(p):
            continue
        seen.add(p)
        if in_harness_scratchpad(p):
            where = "the harness's per-session scratchpad, which is gone with the session"
        elif in_notebook(p):
            where = "the notebook .claude/p4/scratchpad/, which is for notes, logs and output"
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
                                             "permissionDecisionReason": "p4-scratchpad: " + "; ".join(reasons[:3])
                                             + "."}}))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        if sub == "notebook-out":
            return cmd_notebook_out(payload)
        if sub == "repo-uses":
            return cmd_repo_uses(payload)
        if sub == "ask":
            return cmd_ask(payload)
        print(f"scratchpad.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"p4-scratchpad ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
