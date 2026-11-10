#!/usr/bin/env python3
"""view.py: what a session has in view, kept up to date as its context changes.

Recall and its ranker were built around the owner's messages: they wake on a prompt and at a turn's end and know
nothing of what the session already holds. Measured on one store (2026-11-10), 73% of the files a task was
labelled with were ones its session had already opened: recalling them scores well and tells the session nothing,
so near.py had to leave a whole session's own history out by rule.

This keeps, per session, a record of what is in view: names and sizes, never content.
    files     each file a tool call read or edited: the turn it was last touched in, how often, whether edited
    entries   each store line recall showed it, and the turn
    commits   each `git commit` a command made: the repository's folder name and the subject git printed
    marks     where the context was compacted: the turn, and how many files were in view before it
    size      how big the context was at every step, what it began at and what filled it (sizes, below)

It is rebuilt from the session's transcript, which already records every change, at the two moments the plugin
wakes anyway; nothing new runs on a tool call. `models/view/<session>.json` is a cache the store ignores.

What it answers:
    in_view(p4, session)        the paths and entry ids in view now (touched since the last compaction)
    dropped(p4, session)        what was in view before the last compaction and has not been touched since
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402

VERSION = 1
COMMIT_RE = re.compile(r"\bgit\b(?:\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+))?[^|;&\n]*?\bcommit\b")
PRINTED_RE = re.compile(r"^\[(\S+?)(?: \(root-commit\))? ([0-9a-f]{7,40})\] (.+)$", re.M)
COMPACT_RE = re.compile(r"(?i)this session is being continued from a previous conversation|<summary>|conversation (?:was )?compacted")
MAX_FILES = 2000


def path(p4, session):
    return os.path.join(p4, "models", "view", re.sub(r"[^\w.-]", "_", (session or "")[:8]) + ".json")


def empty():
    return {"version": VERSION, "turns": 0, "files": {}, "entries": {}, "commits": [], "marks": []}


def build(turns, project, served=None):
    """The record of one session from its transcript turns (transcript.turns), oldest first. `served` is
    {turn index: [entry ids]} for the store lines recall showed, when the caller has them."""
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
    """Bring a session's record up to date with its transcript and write it; returns the record. The store lines a
    turn was shown are carried over from the record on disk, and `served_now` adds the current turn's."""
    import transcript as tr
    old = load(p4, session) or empty()
    try:
        turns = tr.turns(transcript_path) if transcript_path else []
    except (OSError, ValueError):
        turns = []
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
    """(paths, entry ids) the session holds now: touched or shown at or after its last compaction."""
    if not v:
        return set(), set()
    cut = last_mark(v)
    return ({p for p, f in v["files"].items() if f["turn"] >= cut}, {e for e, k in v["entries"].items() if k >= cut})


def dropped(v):
    """(paths, entry ids) that were in view before the last compaction and have not been touched or shown since."""
    if not v or not v.get("marks"):
        return set(), set()
    cut = last_mark(v)
    return ({p for p, f in v["files"].items() if f["turn"] < cut}, {e for e, k in v["entries"].items() if k < cut})


def describe(p4, session="", limit=12):
    """Lines saying what a session has in view, for another session to read: its newest files (edited ones
    marked), its commits and its compactions. With no session, one line for each session the store has a record of."""
    d = os.path.join(p4, "models", "view")
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
        return [f"no record for session {session[:8]}" + (f" (records: {', '.join(names)})" if names else "")]
    files, entries = in_view(v)
    gone, _ = dropped(v)
    newest = sorted(files, key=lambda p: (-v["files"][p]["turn"], p))[:limit]
    out = [f"session {session[:8]}: {v['turns']} turns, {len(files)} files in view, {len(gone)} dropped at a compaction"]
    out += [f"  {'edited' if v['files'][p]['edited'] else 'read  '} turn {v['files'][p]['turn']:3}  {p}" for p in newest]
    if len(files) > limit:
        out.append(f"  ... and {len(files) - limit} more")
    out += [f"  commit turn {c['turn']:3}  {c['repo']} {c['sha']}  {c['subject']}" for c in v["commits"][-limit:]]
    if entries:
        out.append(f"  store lines shown: {len(entries)}")
    return out + size_lines(v.get("size"))


def stats_line(p4):
    d = os.path.join(p4, "models", "view")
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except OSError:
        return ""
    files = commits = marks = 0
    for n in names:
        v = load(p4, n[:-5]) or empty()
        files, commits, marks = files + len(v["files"]), commits + len(v["commits"]), marks + len(v["marks"])
    return f"view: {len(names)} sessions, {files} files in their records, {commits} commits, {marks} compactions"


# --- the size of the context, as the transcript records it ---------------------------------------------------

DROP = 0.7            # a call whose context is under this share of the one before it follows a compaction
TURNS_KEPT = 300


def sizes(path_or_lines):
    """How big a session's context was at every step, from the usage each API call reports (its input tokens:
    fresh, cache write and cache read): numbers only.
        baseline     the first call's context: the system prompt, the tools, the skills and the memory files a
                     session starts with, and its first message
        last, peak   the context at the latest call, and the largest it has been
        compactions  how often it fell to under DROP of the call before
        by_tool      the tokens the context grew by after each tool's calls, the largest first: what filled it
        turns        [[turn, context when the turn began, context when it ended]], the last TURNS_KEPT
    The split the app's context panel shows inside the baseline (system tools, MCP tools, skills, memory) is the
    app's own count and is not in a transcript; the whole baseline is."""
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


def slug_dir(project):
    """Where Claude Code keeps a project's transcripts: ~/.claude/projects/<the path, every other character a dash>."""
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project)))


def backfill(p4, project, slug_dirs=None):
    """The record of every session whose transcript is on this machine, built as refresh builds it: the sessions
    that ran before the plugin kept records. Returns {sessions, files, commits, compactions}."""
    out = {"sessions": 0, "files": 0, "commits": 0, "compactions": 0}
    for d in slug_dirs or [slug_dir(project)]:
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
                out["compactions"] += max(len(v["marks"]), (v.get("size") or {}).get("compactions", 0))
    return out
