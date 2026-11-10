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
