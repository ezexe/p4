#!/usr/bin/env python3
"""saved.py: p4-skillex's saved code, `<project>/.claude/p4/skillex/src/`, code a project keeps for reuse that its
repository does not use, and the two asks about where code belongs.

The two asks are off unless p4.json's skillex.asks is true or P4_SKILLEX_ASKS=1, or, while that is unset, the name
p4-temportal used, P4_SCRATCHPAD_ASKS=1:

  repo-uses      at SessionStart, prints one line for each file under `.claude/p4/skillex/src/` that the project
                 repository's tracked code, build, docs or CI names: that file is code the repository uses, so it
                 belongs there. It only reads, with one `git grep`, and is silent outside a git repository or without
                 git.
  ask            at PreToolUse, reads the paths a call writes: a Write's or Edit's file_path, and for a Bash command
                 every path in a write position, a redirect, tee, python's open() in a write mode, or the destination
                 of cp or mv. A code file, by extension or by name, headed for a temp location, the session's
                 scratchpad path or the notebook gets an ask naming where it belongs: the repository if it will use
                 the file, else `.claude/p4/skillex/src/`. It never denies, and it is silent inside a subagent,
                 whose writer ezexe cannot redirect from the prompt.

skillex.py runs both, `repo-uses` returning its lines and `ask` the PreToolUse output.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json

ASKS_ENV = "P4_SKILLEX_ASKS"
OLD_ASKS_ENV = "P4_SCRATCHPAD_ASKS"      # the switch's name while p4-temportal held the asks, read when the new one is unset
TMP_ENV = "P4_SCRATCHPAD_TMP"            # p4-temportal's switch for the session scratchpad directory

CODE_EXT = {"py", "pyw", "sh", "bash", "zsh", "ps1", "psm1", "bat", "cmd", "js", "mjs", "cjs", "ts", "rb", "pl",
            "lua", "php", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "java", "kt", "swift", "sql", "awk",
            "r", "jl", "scala", "groovy", "tcl", "vbs", "cmake", "gn", "gni", "html", "htm"}
# Code by name rather than by extension: by extension alone CMakeLists.txt is a `.txt` note.
CODE_NAMES = {"cmakelists.txt", "makefile", "gnumakefile", "dockerfile", "justfile", "rakefile"}
SCRATCHPAD_MARKERS = ("/temp/claude/", "/tmp/claude/")          # the scratchpad paths Claude Code gives
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

ASKS = False                # p4.json skillex.asks; P4_SKILLEX_ASKS=1 or 0 wins for one run
REPO_USES_MIN_NAME = 6      # a basename shorter than this, such as `a.py`, matches too much to call it a use
REPO_USES_MAX = 200         # candidate names one git grep carries
REPO_USES_LINES = 10        # lines printed at most; the rest counted on one more


def configure(p4, write=True):
    """The skillex section of p4.json over the constants, writing the file when it is missing unless `write` is
    False."""
    p4conf.configure(globals(), p4, "skillex", {
        "asks": "ASKS", "repo_uses_min_name": "REPO_USES_MIN_NAME", "repo_uses_max": "REPO_USES_MAX",
        "repo_uses_lines": "REPO_USES_LINES"}, write=write)


def asks_on():
    env = os.environ.get(ASKS_ENV, "").strip() or os.environ.get(OLD_ASKS_ENV, "").strip()
    return env == "1" if env in ("0", "1") else bool(ASKS)


def tmp_on(p4):
    """Whether p4-temportal keeps the session scratchpad directory in the store: its scratchpad.tmp setting."""
    env = os.environ.get(TMP_ENV, "").strip()
    return env == "1" if env in ("0", "1") else bool(p4conf.section(p4, "scratchpad", write=False).get("tmp", True))


def is_code(path):
    return (os.path.splitext(path)[1].lower().lstrip(".") in CODE_EXT
            or os.path.basename(path).lower() in CODE_NAMES)


# ---- repo-uses, one of the two asks ---------------------------------------------------------------------------

def repo_use_candidates(root):
    """{basename: [project-relative paths]} of every code file under `.claude/p4/skillex/src/`, skipping dot
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


def cmd_repo_uses(p4, payload):
    """The lines repo-uses prints, or None. It runs beside skillex.py's start, so it moves an earlier layout first,
    as start does, and whichever runs first moves it."""
    lines = ["p4-skillex: " + "; ".join(moved) + "."] if (moved := p4conf.migrate_layout(p4)) else []
    configure(p4)
    if not asks_on():
        return "\n".join(lines) or None
    root = os.path.dirname(os.path.dirname(os.path.abspath(p4)))
    used = repo_uses(root)
    for path, users in used[:REPO_USES_LINES]:
        named = ", ".join(f"`{u}`" for u in users[:2]) + (" …" if len(users) > 2 else "")
        lines.append(f"`{path}` is used by {named}; it belongs in the repo.")
    if len(used) > REPO_USES_LINES:
        lines.append(f"{len(used) - REPO_USES_LINES} more files under .claude/p4/skillex/src/ are named by the repo.")
    return "\n".join(lines) or None


# ---- ask, one of the two asks ---------------------------------------------------------------------------------

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


def cmd_ask(p4, payload):
    """The PreToolUse output asking where a code file belongs, or None."""
    configure(p4)
    if not asks_on() or payload.get("agent_id"):
        return None
    src = p4conf.sub(p4, "src")
    reasons, seen = [], set()
    for p in written_paths(payload):
        if p in seen or not is_code(p):
            continue
        seen.add(p)
        if in_harness_scratchpad(p):
            where = ("the session's scratchpad, kept in .claude/p4/temportal/tmp/ for notes and output"
                     if tmp_on(p4) else "the session's scratchpad, which Claude Code deletes with its transcript")
        elif in_notebook(p):
            where = "the notebook .claude/p4/temportal/scratchpad/, which is for notes, logs and output"
        elif in_temp(p):
            where = "a temp location"
        else:
            continue
        name = os.path.basename(p.replace("\\", "/"))
        reasons.append(f"{name} is code headed for {where}, at {p}; if the repo will use it, it belongs in the repo "
                       f"where the repo keeps that kind of code, otherwise in {os.path.join(src, name)}")
    if not reasons:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": "p4-skillex: " + "; ".join(reasons[:3]) + "."}}
