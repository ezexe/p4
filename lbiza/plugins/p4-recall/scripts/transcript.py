#!/usr/bin/env python3
"""transcript.py: what a session's transcript says it did with the repository's files (fresh-marketplace.md 5.1a,
8.5). Read-only over Claude Code's `~/.claude/projects/<slug>/<session>.jsonl` files.

A transcript is JSON lines. The ones read here:
  {"type": "user", "message": {"content": "<the owner's prompt>"}, "timestamp", "cwd", "origin": {"kind": "human"}}
  {"type": "assistant", "message": {"id", "content": [{"type": "text"|"tool_use", ...}], "usage": {...}}}
  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id", "content"}]}}
An assistant message is written one line per content block under the same message id; its usage is counted once.

A turn runs from one owner prompt to the next; an owner's /<name> command line (the harness's tags, so not a
prompt) opens a turn too, `/name args` its prompt, and a local command (after its caveat line) does not. For each turn, per repository path (relative to the project):
  edited     an Edit, Write, MultiEdit or NotebookEdit of it, or a Bash write (a redirect into it, sed -i, tee,
             cp/mv onto it)
  read       a Read of it, or a Bash read naming it (cat, head, tail, sed -n, less, wc, grep on it)
  hit        a Grep or Glob result listing it
  invoked    its skill run by a Skill call or the owner's /<name> command: .claude/skills/<name>/SKILL.md, or
             .claude/commands/<name>.md; `dir:name` is dir/.claude/skills/name/SKILL.md (a skill's body reaches the
             context without a Read, so it is a use like a cite)
  cited      after it was read, its path, its distinctive file name or one of its symbols appears in the turn's reply
             text or in a later edit's input
and the label of 5.1a's table: edited 1.0; invoked 0.7; read then cited 0.7; read and dropped -0.3; a search hit never opened -0.2.
"""

import json
import os
import re
import shlex

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read", "NotebookRead")
SEARCH_TOOLS = ("Grep", "Glob")
SKILL_TOOLS = ("Skill",)
BASH_READ = ("cat", "head", "tail", "less", "more", "wc", "grep", "rg", "sed", "awk", "diff", "bat", "nl", "file")
WEIGHTS = {"edited": (1, 1.0), "invoked": (1, 0.7), "cited": (1, 0.7), "dropped": (0, 0.3), "unopened": (0, 0.2)}
COMMAND_RE = re.compile(r"<command-name>\s*/?([\w.:/-]+)\s*</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PATHISH = re.compile(r"(?:[\w.~-]+/)+[\w.-]+|[\w-]+\.[A-Za-z][\w]{0,7}")


def read_lines(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    out.append(json.loads(l))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def prompt_text(d):
    """The owner's prompt on a transcript line, or None: a user line that is not a tool result, not a sidechain,
    from a human (where the transcript says), and not a harness injection (`<...>` first)."""
    if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return None
    origin = d.get("origin") or {}
    if origin and origin.get("kind") not in (None, "human"):
        return None
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str) or not c.strip():
        return None
    if c.lstrip().startswith("<"):
        return None
    return c


def command_text(d):
    """The text of an owner's slash-command line, or '': a user line, not a sidechain or meta, from a human (where
    the transcript says), whose text starts with the command tags (so prompt_text skips it as the harness's)."""
    if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return ""
    if (d.get("origin") or {}).get("kind") not in (None, "human"):
        return ""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str) or not c.lstrip().startswith(("<command-name>", "<command-message>")):
        return ""
    return c if COMMAND_RE.search(c) else ""


def add_commands(turn, text):
    """A Skill call for each /<name> command in the command line's text, as if the turn had run it."""
    for name in COMMAND_RE.findall(text or ""):
        turn["calls"].append({"name": "Skill", "input": {"skill": name}, "id": "", "result": "",
                              "tokens_before": turn["tokens"], "text_index": len(turn["texts"])})


def result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
    return c if isinstance(c, str) else ""


def turns(path_or_lines):
    """[{prompt, time, cwd, calls: [{name, input, id, result, tokens_before}], texts: [str], tokens}] in order.
    `tokens_before` is the input tokens (fresh, cache write and cache read) of the API calls made in this turn
    before the call was issued."""
    lines = read_lines(path_or_lines) if isinstance(path_or_lines, str) else path_or_lines
    out, cur = [], None
    seen_msg = set()
    results = {}
    caveat = False                 # the line before was a local command's caveat: the command is not a skill
    for d in lines:
        p = prompt_text(d)
        cmd = "" if p is not None or caveat else command_text(d)
        if d.get("type") == "user":
            caveat = bool(d.get("isMeta")) and "<local-command-caveat>" in json.dumps(d.get("message") or {})
        if cmd:                    # an owner's /<name> command is a turn of its own: `/name args` its prompt
            args = " ".join(a.strip() for a in ARGS_RE.findall(cmd) if a.strip())
            p = " ".join(["/" + n for n in COMMAND_RE.findall(cmd)[:1]] + ([args] if args else []))
        if p is not None or cmd:
            cur = {"prompt": p, "time": (d.get("timestamp") or "")[:19].replace("T", " "), "cwd": d.get("cwd", ""),
                   "calls": [], "texts": [], "tokens": 0, "uuid": d.get("uuid", "")}
            out.append(cur)
            add_commands(cur, cmd)
            continue
        if cur is None:
            continue
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            mid = m.get("id") or d.get("uuid")
            if mid not in seen_msg:
                seen_msg.add(mid)
                u = m.get("usage") or {}
                cur["tokens"] += sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                  "cache_read_input_tokens"))
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    cur["texts"].append(b["text"])
                elif b.get("type") == "tool_use":
                    call = {"name": b.get("name", ""), "input": b.get("input") or {}, "id": b.get("id", ""),
                            "result": "", "tokens_before": cur["tokens"], "text_index": len(cur["texts"])}
                    cur["calls"].append(call)
                    results[call["id"]] = call
        elif d.get("type") == "user":
            c = m.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in results:
                        results[b["tool_use_id"]]["result"] = result_text(b)[:200000]
    return out


# --- paths -----------------------------------------------------------------------------------------------

EXTERNAL = {}          # {dependency root outside the project: its path prefix} (deps.externals), set by the caller


def rel(path, project, cwd=""):
    """A path relative to the project; under a dependency root outside it, `<prefix>/<path in the root>`; else ''."""
    if not path or not isinstance(path, str):
        return ""
    p = path.strip().strip("'\"")
    if p.startswith("~"):
        p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd or project, p)
    p = os.path.normpath(p)
    proj = os.path.normpath(project)
    if p == proj or not p.startswith(proj + os.sep):
        for root, prefix in EXTERNAL.items():
            if p.startswith(root + os.sep):
                return prefix + "/" + p[len(root) + 1:].replace(os.sep, "/")
        return ""
    return p[len(proj) + 1:].replace(os.sep, "/")


def bash_paths(cmd, project, cwd, known):
    """(read paths, written paths) a Bash command names among the `known` repository paths."""
    reads, writes = set(), set()
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        parts = cmd.split()
    # redirect targets
    for m in re.finditer(r"(?:^|[^\d&])>{1,2}\s*([^\s;&|]+)", cmd):
        r = rel(m.group(1), project, cwd)
        if r in known:
            writes.add(r)
    segs, seg = [], []
    for t in parts:
        if t in ("&&", "||", ";", "|"):
            segs.append(seg)
            seg = []
        else:
            seg.append(t)
    segs.append(seg)
    for seg in segs:
        if not seg:
            continue
        prog = os.path.basename(seg[0])
        args = [a for a in seg[1:] if not a.startswith("-")]
        paths = [r for r in (rel(a, project, cwd) for a in args) if r in known]
        if prog == "git" and len(seg) > 1 and seg[1] == "mv":
            writes.update(paths)
        elif prog in ("cp", "mv", "install") and paths:
            last = rel(args[-1], project, cwd) if args else ""
            if last in known:
                writes.add(last)
            reads.update(p for p in paths if p != last)
        elif prog == "tee":
            writes.update(paths)
        elif prog in ("sed", "perl") and any(a.startswith("-i") or a == "-pi" for a in seg[1:]):
            writes.update(paths)
        else:
            reads.update(paths)
    return reads - writes, writes


def skill_paths(name, known):
    """The repository paths a skill name runs: `dir:name` is dir/.claude/skills/name/SKILL.md, a bare name the
    project's skill or legacy command. A plugin's `plugin:name` resolves to nothing here, as do user skills."""
    if not isinstance(name, str) or not name.strip():
        return []
    name = name.strip().lstrip("/")
    d, _, base = name.rpartition(":")
    pre = d.strip("/") + "/" if d else ""
    cand = [f"{pre}.claude/skills/{base}/SKILL.md", f"{pre}.claude/commands/{base}.md"]
    return [p for p in cand if p in known]


def result_paths(text, project, cwd, known):
    out = []
    for l in (text or "").splitlines():
        l = l.strip()
        if not l:
            continue
        cand = l.split(":", 1)[0] if not os.path.isabs(l) or ":" in l[1:] else l
        r = rel(cand, project, cwd)
        if r in known and r not in out:
            out.append(r)
    return out


# --- the labels of one turn (5.1a) -----------------------------------------------------------------------

def file_events(turn, project, known, symbols=None, reply=""):
    """{path: {"edited", "read", "hit", "cited", "first_open": call index or None, "label": edited|invoked|cited|
    dropped|unopened}} for one turn. `known` is the set of repository paths; `symbols` {path: [symbol names]}."""
    symbols = symbols or {}
    ev = {}
    cwd = turn.get("cwd") or project

    def get(p):
        return ev.setdefault(p, {"edited": False, "read": False, "hit": False, "cited": False, "invoked": False,
                                 "first_open": None, "read_at": None})

    later_inputs = []          # (call index, text) of every edit input and Bash command, to find cites after a read
    for k, c in enumerate(turn["calls"]):
        name, inp = c["name"], c["input"] if isinstance(c["input"], dict) else {}
        if name in EDIT_TOOLS:
            r = rel(inp.get("file_path") or inp.get("notebook_path") or "", project, cwd)
            if r in known:
                e = get(r)
                e["edited"] = True
                if e["first_open"] is None:
                    e["first_open"] = k
            later_inputs.append((k, " ".join(str(inp.get(x, "")) for x in ("new_string", "content", "edits"))))
        elif name in READ_TOOLS:
            r = rel(inp.get("file_path") or inp.get("notebook_path") or "", project, cwd)
            if r in known:
                e = get(r)
                e["read"] = True
                if e["first_open"] is None:
                    e["first_open"] = k
                if e["read_at"] is None:
                    e["read_at"] = k
        elif name in SKILL_TOOLS:
            for r in skill_paths(inp.get("skill") or inp.get("command") or "", known):
                e = get(r)
                e["invoked"] = True
                if e["first_open"] is None:
                    e["first_open"] = k
        elif name in SEARCH_TOOLS:
            for r in result_paths(c.get("result", ""), project, cwd, known):
                get(r)["hit"] = True
        elif name == "Bash":
            cmd = str(inp.get("command", ""))
            reads, writes = bash_paths(cmd, project, cwd, known)
            for r in writes:
                e = get(r)
                e["edited"] = True
                if e["first_open"] is None:
                    e["first_open"] = k
            for r in reads:
                e = get(r)
                e["read"] = True
                if e["first_open"] is None:
                    e["first_open"] = k
                if e["read_at"] is None:
                    e["read_at"] = k
            later_inputs.append((k, cmd))
    texts = turn.get("texts", [])
    for p, e in ev.items():
        if e["edited"] or not e["read"]:
            continue
        at = e["read_at"]
        text_from = turn["calls"][at]["text_index"] if at is not None and at < len(turn["calls"]) else 0
        hay = " ".join(texts[text_from:]) + " " + (reply or "") + " " + " ".join(t for k, t in later_inputs if k > at)
        if cites(p, hay, symbols.get(p, [])):
            e["cited"] = True
    for p, e in ev.items():
        e["label"] = ("edited" if e["edited"] else "invoked" if e["invoked"] else "cited" if e["cited"]
                      else "dropped" if e["read"] else "unopened")
    return ev


def cites(path, hay, syms):
    if not hay:
        return False
    if path in hay:
        return True
    base = path.rsplit("/", 1)[-1]
    if len(base) >= 6 and re.search(r"(?<![\w/.-])" + re.escape(base) + r"(?![\w-])", hay):
        return True
    for s in syms:
        last = s.split("::")[-1].split(".")[-1]
        if len(last) >= 5 and not last.islower() and re.search(r"(?<!\w)" + re.escape(last) + r"(?!\w)", hay):
            return True
    return False


def reply_of(turn):
    return "\n".join(turn.get("texts", [])[-3:])


# --- the re-exploration measure (8.5, the free half) -----------------------------------------------------

def exploration(turn, events, relevant):
    """(calls before the first open of a relevant file, input tokens before it, the path) or None when the turn
    opened no relevant file."""
    best = None
    for p in relevant:
        k = events.get(p, {}).get("first_open")
        if k is not None and (best is None or k < best[0]):
            best = (k, p)
    if best is None:
        return None
    k, p = best
    return k, turn["calls"][k]["tokens_before"], p
