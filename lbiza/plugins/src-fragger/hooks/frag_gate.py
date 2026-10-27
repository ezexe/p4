#!/usr/bin/env python3
"""frag_gate.py — src-fragger's mechanical arms: a PreToolUse ask before agent-written files land where they die,
and a SessionStart check of the register against src/.

Subcommand `register-lint`, run at SessionStart: one line when src/ holds code the register does not name, or the
register names a path that is gone without a retired / superseded / moved / deleted state; silent otherwise.

Subcommand `frag-gate`, reading the harness's JSON payload on stdin (decoded as UTF-8): for a Write or Edit,
the file_path; for a Bash or PowerShell command, every write-position path (redirects, tee, the PowerShell
content cmdlets, python's open() in a write mode, cp / mv destinations). Three cases ask — never deny:

  the harness scratchpad   ANY file written into the per-session temp directory the system prompt names
                           (`.../Temp/claude/<project>/<session>/scratchpad/`): code belongs under
                           `.claude/p4/sessions/<s8>/src/<task>/` as a frag; everything else belongs under the notebook,
                           `.claude/p4/scratchpad/` (the p4 repo tracks it), which the user can see and which outlives
                           the session
  any other temp location  a CODE file (by extension or by name) written to /tmp, the user's temp directory,
                           and their spellings — a frag belongs under `.claude/p4/sessions/<s8>/src/<task>/`
  a project scratchpad     a CODE file (by extension or by name) written under a notebook (`.claude/p4/scratchpad/` or an older `.claude/scratchpad/`) —
                           where a swap script lands once it has stopped calling itself a frag; the ask
                           carries the split and the floor: the notebook is git-ignored and holds notes,
                           logs and caches; a program whose job no single tool call does is a frag under
                           `.claude/p4/sessions/<s8>/src/<task>/`, tracked in the p4 repo, what it reads or produced that
                           is worth keeping lives in that task's out/, and an edit, an append, a whole-file
                           write, or one shell command is the tool's own call and no file

Silent for everything else: files under the project tree are the project's; a notebook's notes, logs, and
fixtures are working files; data a tool drops in /tmp is normal. Every failure prints a one-line notice and
exits 0 — a gate that crashes the call it guards is worse than no gate.
"""

import json
import os
import re
import subprocess
import sys

CODE_EXT = {"py", "pyw", "sh", "bash", "zsh", "ps1", "psm1", "bat", "cmd", "js", "mjs", "cjs", "ts", "rb", "pl",
            "lua", "php", "go", "rs", "c", "cc", "cpp", "h", "hpp", "cs", "java", "kt", "swift", "sql", "awk",
            "r", "jl", "scala", "groovy", "tcl", "vbs", "cmake", "gn", "gni", "html", "htm"}
# Code by name rather than by extension: a probe project's build file is a program the build runs, and by
# extension alone CMakeLists.txt is a `.txt` note.
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
ARGS_RES = [
    re.compile(r"\b(?:Set-Content|Add-Content|Out-File)\b([^\n|;]*)"),
    re.compile(r"\b(?:cp|mv|Copy-Item|Move-Item)\b([^\n|;&]*)"),
]
TOKEN_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|\S+")


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def session_src(root, payload):
    """This session's frag home: <project>/.claude/p4/sessions/<s8>/src — the p4 layout, one directory per session."""
    sid = (str(payload.get("session_id") or "").strip() or "unknown")[:8]
    base = os.path.join(root, ".claude", "p4", "sessions")
    try:   # the directory is `<title-slug>--<s8>` once named by the session's first title, `<s8>` until then
        name = next((n for n in os.listdir(base) if n == sid or n.endswith("--" + sid)), sid)
    except OSError:
        name = sid
    return os.path.join(base, name, "src")


def all_session_srcs(root):
    """[(s8, src)] for every session directory holding a src/, by name."""
    base = os.path.join(root, ".claude", "p4", "sessions")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [(n, os.path.join(base, n, "src")) for n in names if os.path.isdir(os.path.join(base, n, "src"))]


def is_code(path):
    return (os.path.splitext(path)[1].lower().lstrip(".") in CODE_EXT
            or os.path.basename(path).lower() in CODE_NAMES)


# The floor's mechanical arm. A frag is code whose job no single tool call does; a program that reads one
# file, swaps a span, and writes it back is an Edit call in costume — it keys on text that moves, lands twice
# when its new text contains its old, and carries a register entry the call never needed. Detected by shape,
# not by location: the costume is just as wrong under `p4/src/` as in a scratchpad, and location was the
# only thing the gate could see before. Conservative by construction — all three of read, swap and write-back
# must be present in a short body, so a script that merely writes an output file is untouched. It asks, never
# denies: a false positive costs one prompt, and the honest throwaway proceeds.
_C_READ = re.compile(r"\.read_text\s*\(|\.read\s*\(\s*\)|\.readlines\s*\(\s*\)")
_C_SWAP = re.compile(r"\.replace\s*\(|\bre\.sub\s*\(")
_C_WRITE = re.compile(r"\.write_text\s*\(|\.write\s*\(|\bopen\s*\([^)]*[\"'][aw]")
COSTUME_MAX_LINES = 40


def costume_kind(body):
    if not body:
        return None
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if len(lines) > COSTUME_MAX_LINES:
        return None
    if _C_READ.search(body) and _C_SWAP.search(body) and _C_WRITE.search(body):
        return "an Edit call"
    return None


def _norm(path):
    return path.replace("\\", "/").lower()


def in_scratchpad(path):
    p = _norm(path)
    return any(m in p for m in SCRATCHPAD_MARKERS) and "/scratchpad" in p


def in_temp(path):
    p = _norm(path)
    return any(m in p for m in TEMP_MARKERS)


def in_project_pad(path):
    p = _norm(path)
    # the notebook: .claude/p4/scratchpad/ (tracked by the p4 repo), or an older .claude/scratchpad/ (git-ignored)
    return any(m in p or p.startswith(m[1:]) for m in ("/.claude/p4/scratchpad/", "/.claude/scratchpad/"))


# Scratch data dropped straight into the project root: untracked, unswept, and found by the user long after the
# agent that wrote it is gone. The known root manifests are exempt by name — those are the project's own.
DATA_EXT = {"json", "jsonl", "ndjson", "csv", "tsv", "txt", "log", "out", "tmp", "dat", "dump"}
KNOWN_ROOT = {"package.json", "package-lock.json", "tsconfig.json", "jsconfig.json", "composer.json",
              "composer.lock", "deno.json", "deno.lock", "biome.json", "angular.json", "nx.json", "turbo.json",
              "renovate.json", "manifest.json", "marketplace.json", "plugin.json", "settings.json",
              "settings.local.json", "requirements.txt", "constraints.txt", "changelog.txt", "license.txt",
              "readme.txt", "notice.txt", "authors.txt", "codeowners.txt", "bun.lockb", "pnpm-lock.yaml"}


def is_data(path):
    return os.path.splitext(path)[1].lower().lstrip(".") in DATA_EXT


# The notebook's ignorables. The p4 repo tracks the notebook, so a run's log, a build tree or a binary written
# there lands in the p4 repo's status and, at the next commit, in its history. Those go to the notebook's `.out/`,
# a directory whose own `.gitignore` of `*` keeps it ignored whatever any other rule says; the SessionStart sweep
# (`notebook-out`) re-seeds that file and moves any ignorable found elsewhere in the notebook into it.
OUT_NAME = ".out"
IGNORABLE_EXT = {"log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so", "dylib",
                 "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"}
IGNORABLE_DIRS = {"bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__", ".cache",
                  "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"}


def is_ignorable(rel):
    """True for a notebook path (relative to the notebook) that is a log, a build result or a binary."""
    parts = [s for s in rel.replace("\\", "/").split("/") if s]
    if not parts or parts[0] == OUT_NAME:
        return False
    if any(s.lower() in IGNORABLE_DIRS for s in parts[:-1]):
        return True
    return os.path.splitext(parts[-1])[1].lower().lstrip(".") in IGNORABLE_EXT


def pad_relative(path):
    """The path relative to the p4 notebook (`.claude/p4/scratchpad/`), or None when it is not under it."""
    p = path.replace("\\", "/")
    m = re.search(r"(?:^|/)\.claude/p4/scratchpad/(.+)$", p, re.IGNORECASE)
    return m.group(1) if m else None


# A drive-letter path is absolute on every OS, and its backslashes are separators: the owner works on Windows, and a
# payload's paths keep that form wherever the gate runs — off Windows, os.path alone reads `E:/projects/x/_rows.json`
# as relative and joins it under the root a second time.
DRIVE_RE = re.compile(r"^[A-Za-z]:/")


def in_project_root(path, root):
    if not path or not root:
        return False
    try:
        path, root = path.replace("\\", "/"), root.replace("\\", "/")
        full = path if os.path.isabs(path) or DRIVE_RE.match(path) else os.path.join(root, path)
        return _norm(os.path.normpath(os.path.dirname(full))) == _norm(os.path.normpath(root))
    except Exception:
        return False


def _first(m):
    return next((g for g in m.groups() if g), "")


def written_paths(payload):
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return []
    if tool in ("Write", "Edit", "NotebookEdit"):
        fp = str(inp.get("file_path") or "")
        return [fp] if fp else []
    if tool not in ("Bash", "PowerShell"):
        return []
    cmd = str(inp.get("command") or "")
    out = []
    for rx in WRITE_RES:
        out += [_first(m) for m in rx.finditer(cmd)]
    for rx in ARGS_RES:
        for m in rx.finditer(cmd):
            out += [t.strip("\"'") for t in TOKEN_RE.findall(m.group(1)) if not t.startswith("-")]
    return [p for p in out if p]


def code_body(payload, path):
    """The text about to become `path`, for the costume check: a Write's content, or the whole command for a
    shell write (a heredoc's body lives inside it)."""
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return ""
    tool = str(payload.get("tool_name") or "")
    if tool == "Write":
        return str(inp.get("content") or "")
    if tool in ("Bash", "PowerShell"):
        return str(inp.get("command") or "")
    return ""


def cmd_frag_gate(payload):
    # A subagent never receives the SessionStart contracts — no hook event injects text into a spawned
    # subagent's context (SubagentStart's stdout goes to the debug log, not the agent), so its writer was
    # never told a frag belongs under `p4/src/`. The gate's ask, though, is answered by the human, who
    # cannot redirect an agent that is already running. Asking anyway produces a prompt with no actionable
    # recipient — one per scratch file, which is a stream, not a gate. `agent_id` is present only inside a
    # subagent call, so it is the tell.
    #
    # The silence is scoped to the IGNORED cases, not to the subagent. A harness-scratchpad, temp, or notebook
    # file reaches neither the project's history nor its status, so an unanswerable prompt buys nothing; a
    # file dropped in the project root lands in status, outlives every agent that could have been told, and
    # the human who finds it is exactly the right person to ask. That asymmetry — not the writer's identity —
    # is what decides. When an injection channel for subagents exists, the contract should reach them and this
    # scoping should go.
    is_sub = bool(payload.get("agent_id"))
    root = project_root(payload)
    src = session_src(root, payload)
    pad = os.path.join(root, ".claude", "p4", "scratchpad")
    reasons = []
    seen = set()
    for p in written_paths(payload):
        if p in seen:
            continue
        seen.add(p)
        name = os.path.basename(p)
        # A build file is code by name, never a `.txt` dump: the project's own CMakeLists.txt is not scratch.
        if in_project_root(p, root) and is_data(p) and not is_code(p) and name.lower() not in KNOWN_ROOT:
            home = (f"{pad}{os.sep}{OUT_NAME}{os.sep}, the notebook's always-ignored directory" if is_ignorable(name)
                    else f"{pad}{os.sep}, the notebook the p4 repo tracks")
            reasons.append(f"{name} is a data file headed for the project root ({p}) — scratch data belongs under "
                           f"{home}, not beside the project's own manifests where "
                           f"it lands untracked and is found later by the user rather than by whoever wrote it")
        elif (pad_relative(p) or "") and is_ignorable(pad_relative(p)):
            # a log, build result or binary outside the notebook's .out/ lands in the p4 repo's status; asked of a
            # subagent too, since it reaches the p4 repo's history like a root file reaches the project's
            reasons.append(f"{name} is a log, build result or binary headed for the notebook outside its ignored "
                           f"directory ({p}) — the p4 repo tracks the notebook, so it belongs under "
                           f"{pad}{os.sep}{OUT_NAME}{os.sep}{pad_relative(p).replace('/', os.sep)}, which its own "
                           f".gitignore of * keeps out of every commit")
        elif is_sub:
            continue
        elif in_scratchpad(p):
            home = (f"{src}{os.sep}<task>{os.sep} as a registered frag, tracked in the p4 repo" if is_code(p)
                    else f"{pad}{os.sep}, the notebook, which the p4 repo tracks")
            reasons.append(f"{name} is headed for the harness's per-session scratchpad ({p}) — it belongs under {home}: "
                           f"that directory is named after a session id, invisible to the user, and gone with the session")
        elif in_temp(p) and is_code(p):
            reasons.append(f"{name} is code headed for a temp location ({p}) — a frag belongs under {src}{os.sep}<task>{os.sep} "
                           f"and in src{os.sep}frags.md")
        elif in_project_pad(p) and is_code(p):
            reasons.append(f"{name} is code headed for a project's notebook ({p}) — the notebook is "
                           f"for notes, logs, output and copies kept for reading; code worth keeping is "
                           f"not a note: a program whose job no single tool call does is a frag under {src}{os.sep}<task>{os.sep} "
                           f"registered in src{os.sep}frags.md and tracked in the p4 repo, and an edit, an append, a "
                           f"whole-file write, or one shell command is the tool's own call and no file; a page or source "
                           f"captured from elsewhere belongs in the task's out{os.sep} under src{os.sep}, beside the frag that "
                           f"reads it")
        elif is_code(p):
            kind = costume_kind(code_body(payload, p))
            if kind:
                reasons.append(f"{name} reads a file, swaps a span in it and writes it back — that is {kind} in costume "
                               f"({p}). The floor is the job, not the length: an edit is an Edit call, an append or a "
                               f"whole-file write is a Write call, and one shell command is a Bash call — none of them "
                               f"becomes a file. A swap script keys on text that moves, lands twice when its new text "
                               f"contains its old, and needs a header, a register entry and a retirement the call never "
                               f"needed. If a heredoc tripped on the text, the fallback is the dedicated tool")
    if not reasons:
        return 0
    reason = "src-fragger: " + "; ".join(reasons[:3]) + ". Proceed only if this file is truly throwaway."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    return 0


# The register's mechanical check, run at SessionStart: a frag under src/ the register does not name is code
# that survives the session with nothing saying what it does or how it runs; an entry whose path is gone is a
# register that lies. Entries whose state says the frag was retired, superseded, moved or deleted are not drift —
# a retired entry keeps the path it had. Non-code files under src/ (a README, a sheet, a design page's data) are
# the task directory's own and are never expected in the register, and neither is anything under a task's
# out/ — what its frags read (a fetched spec, a captured page, a downloaded source, code included) and what they
# produced that is worth keeping. Entries begin after the header's `---` separator: the header's own yaml shape
# starts with the same `- frag:` prefix and must not be read as one.
GONE_STATES = ("retired", "superseded", "moved", "deleted")
OUT_DIR = "out"


def in_out(rel):
    return OUT_DIR in rel.split("/")[:-1]


def register_entries(text):
    """[(path, state)] from a register's body — the lines after the first `---`."""
    lines = text.split("\n")
    try:
        sep = lines.index("---")
    except ValueError:
        return []
    out, path, state = [], None, ""
    for ln in lines[sep + 1:]:
        if ln.startswith("- frag:"):
            if path:
                out.append((path, state))
            path, state = ln[len("- frag:"):].strip(), ""
        elif path and ln.startswith("  state:"):
            state = ln[len("  state:"):].strip()
    if path:
        out.append((path, state))
    return out


def register_drift(src):
    """(unregistered code under src/, registered paths that are gone) — both as paths relative to src/."""
    reg_path = os.path.join(src, "frags.md")
    if not os.path.isdir(src) or not os.path.isfile(reg_path):
        return [], []
    with open(reg_path, encoding="utf-8", errors="replace") as f:
        entries = register_entries(f.read())
    registered = {p.replace("\\", "/") for p, _ in entries}
    on_disk = []
    for root_dir, _dirs, files in os.walk(src):
        for name in files:
            rel = os.path.relpath(os.path.join(root_dir, name), src).replace("\\", "/")
            if rel != "frags.md":
                on_disk.append(rel)
    unregistered = sorted(p for p in on_disk if is_code(p) and not in_out(p) and p not in registered)
    gone = sorted(p for p, state in entries
                  if not os.path.exists(os.path.join(src, p)) and not any(g in state.lower() for g in GONE_STATES))
    return unregistered, gone


def cmd_register_lint(payload):
    root = project_root(payload)
    unregistered, gone = [], []
    for name, src in all_session_srcs(root):
        u, g = register_drift(src)
        unregistered += [f"{name}/{p}" for p in u]
        gone += [f"{name}/{p}" for p in g]
    if not unregistered and not gone:
        return 0
    parts = []
    if unregistered:
        parts.append("code under src/ the register does not name: " + ", ".join(unregistered[:8])
                     + (f" (+{len(unregistered) - 8} more)" if len(unregistered) > 8 else ""))
    if gone:
        parts.append("entries whose path is gone and not retired: " + ", ".join(gone[:8])
                     + (f" (+{len(gone) - 8} more)" if len(gone) > 8 else ""))
    print("src-fragger: register drift — " + "; ".join(parts) + ". Register the frag, or mark the entry retired.")
    return 0


# The notebook's `.out/`, kept at every session start: its `.gitignore` of `*` is re-seeded whenever it is missing
# or changed (the directory always stays ignored), and every ignorable found in the notebook outside it — what an
# older version wrote beside the notes, before `.out/` existed — is moved into it at the same relative path. A
# name already taken there gets the move's time as a suffix; nothing is overwritten or removed. A moved file the
# p4 repo already tracked shows as deleted in its status: the commit that drops it is the owner's word, never the
# hook's, so the line says how many there were and touches no index. An older `.claude/scratchpad/` is ignored
# whole by its own `*` and left as it was, the user's to dispose.
OUT_IGNORE = "*\n"


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
    """Seed `.out/` and move the notebook's ignorables into it -> (reseeded, [moved rel paths], [tracked rels])."""
    p4 = os.path.join(root, ".claude", "p4")
    pad = os.path.join(p4, "scratchpad")
    out = os.path.join(pad, OUT_NAME)
    os.makedirs(out, exist_ok=True)
    ign = os.path.join(out, ".gitignore")
    try:
        with open(ign, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = None
    reseeded = current != OUT_IGNORE
    if reseeded:
        with open(ign, "w", encoding="utf-8", newline="\n") as f:
            f.write(OUT_IGNORE)
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
    # directories the sweep emptied are removed, the empty ones only
    for d, dirs, files in os.walk(pad, topdown=False):
        if os.path.normcase(d) in (os.path.normcase(pad), os.path.normcase(out)) or \
                os.path.normcase(d).startswith(os.path.normcase(out) + os.sep):
            continue
        try:
            os.rmdir(d)
        except OSError:
            pass
    return reseeded, moved, sorted(tracked & set(moved))


def cmd_notebook_out(payload):
    root = project_root(payload)
    if not os.path.isdir(os.path.join(root, ".claude")):
        return 0
    import time
    reseeded, moved, tracked = sweep_notebook(root, time.strftime("%Y%m%d-%H%M%S"))
    lines = []
    if reseeded:
        lines.append("src-fragger: seeded .claude/p4/scratchpad/.out/.gitignore (`*`) — logs, build results and "
                     "binaries go there and never reach the p4 repo.")
    if moved:
        lines.append(f"src-fragger: moved {len(moved)} log/build/binary file(s) from the notebook into "
                     f".claude/p4/scratchpad/.out/: " + ", ".join(moved[:6]) + (" …" if len(moved) > 6 else "") + ".")
    if tracked:
        lines.append(f"src-fragger: {len(tracked)} of them were tracked by the p4 repo and now show as deleted in its "
                     f"status — dropping them is a commit, the owner's word.")
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
        if sub == "frag-gate":
            return cmd_frag_gate(payload)
        if sub == "register-lint":
            return cmd_register_lint(payload)
        if sub == "notebook-out":
            return cmd_notebook_out(payload)
        print(f"frag_gate.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a gate degrades, never raises
        print(f"src-fragger ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
