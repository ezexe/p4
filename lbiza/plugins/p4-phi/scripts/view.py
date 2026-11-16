#!/usr/bin/env python3
"""view.py: what a session has in view, rebuilt from its transcript at every turn end.

A session's record holds names and sizes, never content:
    files     each file a tool call read or edited: the turn it was last touched in, how often, whether edited
    entries   each document a retrieval line showed the session with a handle, and the turn it was shown in
    commits   each `git commit` a command made: the repository's folder name and the subject git printed
    marks     where the context was compacted: the turn, and how many files were in view before it, set by
              SessionStart's `compact` source through compacted, or read from a transcript's summary text
    size      how big the context was at every step, what it began at and what filled it, as sizes() counts it

The Stop hook `close` calls refresh at every turn end, which rebuilds the record from the session's transcript;
nothing runs on a tool call. `p4.py view --backfill` calls backfill, which refreshes the record of every
transcript of the project on this machine. The record is `phi/models/view/<s8>.json`, named by the first eight
characters of the session id, so two sessions whose ids share those eight characters share one record; the store's
seeded .gitignore leaves the folder out.

What reads it: describe, which `p4.py view` prints for another session to read, and stats_line, which `p4.py check`
prints. Only describe calls in_view(v) and dropped(v), which take a loaded record:
    in_view(v)        the paths and document ids in view now, touched or shown since the last compaction
    dropped(v)        what was in view before the last compaction and has not been touched since
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402

VERSION = 1
COMMIT_RE = re.compile(r"\bgit\b(?:\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+))?[^|;&\n]*?\bcommit\b")
PRINTED_RE = re.compile(r"^\[(\S+?)(?: \(root-commit\))? ([0-9a-f]{7,40})\] (.+)$", re.M)
COMPACT_RE = re.compile(r"(?i)this session is being continued from a previous conversation|<summary>|conversation (?:was )?compacted")
MAX_FILES = 2000


def path(p4, session):
    return p4conf.sub(p4, "models", "view", re.sub(r"[^\w.-]", "_", (session or "")[:8]) + ".json")


def empty():
    return {"version": VERSION, "turns": 0, "files": {}, "entries": {}, "commits": [], "marks": []}


def build(turns, project, served=None):
    """The record of one session from its transcript turns, as transcript.turns gives them, oldest first. `served`
    is {turn index: [document ids]} for the documents the retrieval lines showed, when the caller has them;
    refresh passes none and carries them over itself."""
    import transcript as tr
    v = empty()
    for k, turn in enumerate(turns):
        if COMPACT_RE.search(turn.get("prompt") or "") and v["files"]:
            v["marks"].append({"turn": k, "files": len(v["files"])})
        cwd = turn.get("cwd") or project
        for c in turn.get("calls", []):
            inp = c.get("input") if isinstance(c.get("input"), dict) else {}
            name = c.get("name")
            if name in tr.READ_TOOLS + tr.EDIT_TOOLS:
                raw = inp.get("file_path") or inp.get("notebook_path") or ""
                p = tr.rel(raw, project, cwd) or (os.path.normpath(raw).replace(os.sep, "/") if raw else "")
                if p:
                    f = v["files"].setdefault(p, {"turn": k, "n": 0, "edited": False})
                    f["turn"], f["n"] = k, f["n"] + 1
                    f["edited"] = f["edited"] or name in tr.EDIT_TOOLS
            elif name in tr.SHELL_TOOLS and COMMIT_RE.search(str(inp.get("command", ""))):
                m = COMMIT_RE.search(str(inp.get("command", "")))
                where = (m.group(1) or "").strip("\"'") or cwd
                for _b, sha, subject in PRINTED_RE.findall(c.get("result") or ""):
                    v["commits"].append({"turn": k, "repo": os.path.basename(where.rstrip("/\\")), "sha": sha[:8],
                                         "subject": subject[:200]})
        for e in (served or {}).get(k, []):
            v["entries"][e] = k
    v["turns"] = len(turns)
    if len(v["files"]) > MAX_FILES:                    # the most recently touched stay
        keep = sorted(v["files"], key=lambda p: -v["files"][p]["turn"])[:MAX_FILES]
        v["files"] = {p: v["files"][p] for p in keep}
    return v


def refresh(p4, project, session, transcript_path, served_now=None):
    """Bring a session's record up to date with its transcript and write it; returns the record. The documents
    shown are carried over from the record on disk, and `served_now` adds the current turn's. A transcript with no
    turn and no call writes nothing and returns the record on disk, or an empty one."""
    import transcript as tr
    old = load(p4, session) or empty()
    try:
        turns = tr.turns(transcript_path) if transcript_path else []
    except (OSError, ValueError):
        turns = []
    if not turns and transcript_path:
        # a transcript with no message from ezexe, such as a child session's, has a context all the same: its
        # calls are read as one turn
        try:
            lines = tr.read_lines(transcript_path)
        except (OSError, ValueError):
            lines = []
        if any(d.get("type") == "assistant" for d in lines):
            turns = tr.turns([{"type": "user", "message": {"role": "user", "content": "(not started by ezexe)"}}] + lines)
    if not turns:
        return old
    v = build(turns, project)
    try:
        v["size"] = sizes(transcript_path)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    v["entries"] = dict(old.get("entries", {}))
    for e in served_now or []:
        v["entries"][e] = len(turns) - 1
    # a mark SessionStart's `compact` source set is carried on, beside those read from the transcript
    have = {m["turn"] for m in v["marks"]}
    v["marks"] = sorted(v["marks"] + [m for m in old.get("marks", []) if m.get("signal") and m["turn"] not in have],
                        key=lambda m: m["turn"])
    os.makedirs(os.path.dirname(path(p4, session)), exist_ok=True)
    ranker.write_atomic(path(p4, session), json.dumps(v, separators=(",", ":"), ensure_ascii=False))
    return v


def compacted(p4, project, session, transcript_path):
    """SessionStart's `compact` source: the context was compacted after the session's last turn. The record is
    brought up to date with the transcript and marked at its next turn, a mark every later refresh keeps; returns the
    record."""
    v = refresh(p4, project, session, transcript_path) or empty()
    turn = v.get("turns", 0)
    if turn not in {m["turn"] for m in v["marks"]}:
        v["marks"].append({"turn": turn, "files": len(v["files"]), "signal": True})
        os.makedirs(os.path.dirname(path(p4, session)), exist_ok=True)
        ranker.write_atomic(path(p4, session), json.dumps(v, separators=(",", ":"), ensure_ascii=False))
    return v


def load(p4, session):
    try:
        with open(path(p4, session), encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) and v.get("version") == VERSION else None


def last_mark(v):
    return v["marks"][-1]["turn"] if v.get("marks") else -1


def in_view(v):
    """`(paths, document ids)` the session holds now: touched or shown at or after its last compaction."""
    if not v:
        return set(), set()
    cut = last_mark(v)
    return ({p for p, f in v["files"].items() if f["turn"] >= cut}, {e for e, k in v["entries"].items() if k >= cut})


def dropped(v):
    """`(paths, document ids)` that were in view before the last compaction and have not been touched or shown
    since."""
    if not v or not v.get("marks"):
        return set(), set()
    cut = last_mark(v)
    return ({p for p, f in v["files"].items() if f["turn"] < cut}, {e for e, k in v["entries"].items() if k < cut})


def describe(p4, session="", limit=12):
    """Lines saying what a session has in view, for another session to read: its newest files in view, the edited
    ones marked, its commits, how many of the documents retrieval showed it with a handle are in view, and the size of its context.
    With no session, one line for each session the store has a record of."""
    d = p4conf.sub(p4, "models", "view")
    try:
        names = sorted(n[:-5] for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        names = []
    if not session:
        out = []
        for n in names:
            v = load(p4, n) or empty()
            files, _ = in_view(v)
            out.append(f"{n}: {v['turns']} turns, {len(files)} files in view, {len(v['commits'])} commits, {len(v['marks'])} compactions")
        return out or ["no session has a record yet"]
    v = load(p4, session)
    if not v:
        return [f"no record for session {session[:8]}" + (f"; records: {', '.join(names)}" if names else "")]
    files, entries = in_view(v)
    gone, _ = dropped(v)
    newest = sorted(files, key=lambda p: (-v["files"][p]["turn"], p))[:limit]
    out = [f"session {session[:8]}: {v['turns']} turns, {len(files)} files in view, {len(gone)} dropped at a compaction"]
    out += [f"  {'edited' if v['files'][p]['edited'] else 'read  '} turn {v['files'][p]['turn']:3}  {p}" for p in newest]
    if len(files) > limit:
        out.append(f"  ... and {len(files) - limit} more")
    out += [f"  commit turn {c['turn']:3}  {c['repo']} {c['sha']}  {c['subject']}" for c in v["commits"][-limit:]]
    if entries:
        out.append(f"  documents shown with a handle: {len(entries)}")
    return out + size_lines(v.get("size"))


def stats_line(p4):
    """The line `p4.py check` prints: the sessions with a record and the files, commits and compactions their
    records hold; '' when the store has no records folder."""
    d = p4conf.sub(p4, "models", "view")
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except OSError:
        return ""
    files = commits = marks = 0
    for n in names:
        v = load(p4, n[:-5]) or empty()
        files, commits, marks = files + len(v["files"]), commits + len(v["commits"]), marks + compactions(v)
    return f"view: {len(names)} sessions, {files} files in their records, {commits} commits, {marks} compactions"


# --- the size of the context, as the transcript records it ---------------------------------------------------

DROP = 0.7            # a call whose context is under this share of the one before it follows a compaction
TURNS_KEPT = 300


def sizes(path_or_lines):
    """How big a session's context was at every step, from the usage each API call reports, its input tokens fresh,
    cache write and cache read: numbers only.
        baseline     the first call's context: the system prompt, the tools, the skills and the memory files a
                     session starts with, and its first message
        last, peak   the context at the latest call, and the largest it has been
        calls        the API calls that reported input tokens
        compactions  how often it fell to under DROP of the call before
        by_tool      the tokens the context grew by after each tool's calls, the twelve largest first: what filled it
        turns        [[turn, context when the turn began, context when it ended]], the last TURNS_KEPT
    It reads the usage numbers alone, so the baseline stays whole, without the split `/context` shows inside it
    into system tools, MCP tools, skills and memory. Claude Code's local transcripts record each API request's
    system prompt, tools and parameters, but its documentation gives no line format for them."""
    import transcript as tr
    lines = tr.read_lines(path_or_lines) if isinstance(path_or_lines, str) else path_or_lines
    seen, series, turn = set(), [], -1
    for d in lines:
        if tr.prompt_text(d) is not None:
            turn += 1
            continue
        m = d.get("message") or {}
        if d.get("type") != "assistant":
            continue
        mid = m.get("id") or d.get("uuid")
        u = m.get("usage") or {}
        size = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        tools = [b.get("name", "") for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if mid in seen:
            if series:
                series[-1][2] += tools                       # the same call, streamed in parts
            continue
        seen.add(mid)
        if size:
            series.append([max(turn, 0), size, tools])
    out = {"baseline": 0, "last": 0, "peak": 0, "calls": len(series), "compactions": 0, "by_tool": {}, "turns": []}
    if not series:
        return out
    out.update({"baseline": series[0][1], "last": series[-1][1], "peak": max(s[1] for s in series)})
    by, spans = {}, {}
    for i, (t, size, tools) in enumerate(series):
        spans.setdefault(t, [size, size])[1] = size
        if i + 1 < len(series):
            nxt = series[i + 1][1]
            if nxt < DROP * size:
                out["compactions"] += 1
            elif nxt > size and tools:
                for name in tools:
                    by[name] = by.get(name, 0) + (nxt - size) // len(tools)
    out["by_tool"] = dict(sorted(by.items(), key=lambda kv: -kv[1])[:12])
    out["turns"] = [[t, a, b] for t, (a, b) in sorted(spans.items())][-TURNS_KEPT:]
    return out


def size_lines(s):
    """What sizes() found, in words."""
    if not s or not s.get("calls"):
        return []
    grew = [b - a for _t, a, b in s["turns"] if b > a]
    grew.sort()
    med = grew[len(grew) // 2] if grew else 0
    top = ", ".join(f"{k} {v // 1000}k" for k, v in list(s["by_tool"].items())[:5])
    return [f"  context: {s['last'] // 1000}k tokens now, {s['baseline'] // 1000}k when it began, peak {s['peak'] // 1000}k, "
            f"{s['compactions']} compactions over {s['calls']} calls; a turn that grew it added {med // 1000}k at the median",
            f"  what filled it: {top or 'nothing recorded'}"]


def compactions(v):
    """How often a session's context was compacted: the larger of the two counts, the marks build sets at a
    continuation message and the falls in size sizes() finds, so every count of it agrees."""
    return max(len(v.get("marks") or []), (v.get("size") or {}).get("compactions", 0))


def slug_dirs_of(project):
    """A project's transcript folder and those of its worktrees, whose names are its own followed by
    `--claude-worktrees-`."""
    base = slug_dir(project)
    try:
        sibs = [os.path.join(os.path.dirname(base), n) for n in os.listdir(os.path.dirname(base))
                if n.startswith(os.path.basename(base) + "--claude-worktrees-")]
    except OSError:
        sibs = []
    return [base] + sorted(sibs)


def slug_dir(project):
    """Where Claude Code keeps a project's transcripts: `~/.claude/projects/<slug>`, the slug being the project's
    absolute path with every character but a letter or a digit made a dash."""
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project)))


def backfill(p4, project, slug_dirs=None):
    """Refresh the record of every session whose transcript is in `slug_dirs`, by default the project's transcript
    folders on this machine. Returns {sessions, files, commits, compactions} over the records with a turn."""
    out = {"sessions": 0, "files": 0, "commits": 0, "compactions": 0}
    for d in slug_dirs or slug_dirs_of(project):
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
        except OSError:
            continue
        for n in names:
            v = refresh(p4, project, n[:-6], os.path.join(d, n))
            if v.get("turns"):
                out["sessions"] += 1
                out["files"] += len(v["files"])
                out["commits"] += len(v["commits"])
                out["compactions"] += compactions(v)
    return out
