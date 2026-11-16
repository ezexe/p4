#!/usr/bin/env python3
"""transcript.py: what a session's transcript says it did with the repository's files. Read-only over Claude
Code's `~/.claude/projects/<slug>/<session>.jsonl` files, whose line format Claude Code's documentation does not give.

A transcript is JSON lines. The ones read here:
  {"type": "user", "message": {"content": "<ezexe's prompt>"}, "timestamp", "cwd", "uuid", "origin": {"kind": "human"}}
  {"type": "assistant", "message": {"id", "content": [{"type": "text"|"tool_use", ...}], "usage": {...}}}
  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id", "content"}]}}
An assistant message is written one line per content block under the same message id; its usage is counted once.

A turn runs from one prompt of ezexe's to the next. ezexe's /<name> command line opens a turn too, with `/name args`
as its prompt, though prompt_text skips its text as Claude Code's tags; a local command, whose line follows a caveat
line, does not. turns() gives each turn's prompt, time, cwd, uuid, calls, texts and tokens, and each call's name,
input, id, result, tokens_before and text_index. file_events() gives, per repository path relative to the project:
  edited      a call of a tool in EDIT_TOOLS on it, such as Edit, Write or NotebookEdit, or a shell command that
              writes it: a `>` or `>>` into it, the last path of cp, mv or install, or any path of tee, git mv,
              sed -i or perl -i
  read        a call of a tool in READ_TOOLS on it, such as Read, or a shell command that names it as an argument of
              a program and does not write it, whatever the program: `pytest src/a.py -q` reads src/a.py
  hit         a Grep or Glob result listing it
  invoked     its skill run by a Skill call or ezexe's /<name> command: .claude/skills/<name>/SKILL.md, or
              .claude/commands/<name>.md; `dir:name` is dir/.claude/skills/name/SKILL.md. A skill's body reaches
              the context without a Read, so it is a use like a cite
  cited       after it was read, its path, its file name or one of its symbols, as cites() matches them, appears in
              the turn's texts from the read on, in its reply, or in an edit's input or a shell command after the read
  first_open  the index of the first call that edited, read or invoked it, and `read_at` that of the first that read it
  label       edited, invoked or cited, the first that holds; else dropped for a path read, unopened for a search hit
WEIGHTS maps each label to its training row's label and weight: 1 for edited, invoked and cited, 0 for dropped and
unopened.
"""

import json
import os
import re
import shlex

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
READ_TOOLS = ("Read", "NotebookRead")
SHELL_TOOLS = ("Bash", "PowerShell")     # a command's paths are read the same way, whichever shell ran it
SEARCH_TOOLS = ("Grep", "Glob")
SKILL_TOOLS = ("Skill",)
WEIGHTS = {"edited": (1, 1.0), "invoked": (1, 0.7), "cited": (1, 0.7), "dropped": (0, 0.3), "unopened": (0, 0.2)}
COMMAND_RE = re.compile(r"<command-name>\s*/?([\w.:/-]+)\s*</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)


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
    """ezexe's prompt on a transcript line, or None: a user line that is not a tool result, a sidechain or meta,
    whose origin, when the line has one, is a human, and whose text does not begin with `<`, as text Claude Code
    injects does."""
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
    """The text of ezexe's slash-command line, or '': a user line, not a sidechain or meta, whose origin, when it
    has one, is a human, and whose text starts with the command tags, which prompt_text skips as Claude Code's."""
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
    """`[{prompt, time, cwd, uuid, calls: [{name, input, id, result, tokens_before, text_index}], texts: [str],
    tokens}]` in order. `time` is the prompt line's timestamp to the second and `uuid` its id; `texts` are Claude's
    text blocks of the turn; `tokens` is the input tokens of the turn's API calls, fresh, cache write and cache
    read. A call's `tokens_before` is that sum up to the API call that issued it, `text_index` how many of the
    turn's texts came before it, and `result` its tool result's text, cut to 200,000 characters."""
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
        if cmd:                    # ezexe's /<name> command is a turn of its own: `/name args` its prompt
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

EXTERNAL = {}          # {dependency root outside the project: its path prefix}, set by the caller from deps.externals


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
    """`(read paths, written paths)` a shell command names among the `known` repository paths, by the rules of the
    module docstring's edited and read rows. The command is split as a POSIX shell splits it, at whitespace when its
    quotes do not balance, or, on Windows with a backslash in it, without POSIX escapes and with matching quotes
    dropped; its words are then cut into commands at `&&`, `||`, `;` and `|`."""
    reads, writes = set(), set()
    try:
        if os.sep == "\\" and "\\" in cmd:
            # a Windows path: POSIX splitting would eat its backslashes, so split without it and drop the quotes
            parts = [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "'\"" else t
                     for t in shlex.split(cmd, posix=False)]
        else:
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
        drive = l[:2] if re.match(r"^[A-Za-z]:[\\/]", l) else ""     # a drive's colon is not the one before a line number
        rest = l[len(drive):]
        cand = drive + (rest.split(":", 1)[0] if not os.path.isabs(l) or ":" in rest[1:] else rest)
        r = rel(cand, project, cwd)
        if r in known and r not in out:
            out.append(r)
    return out


# --- the labels of one turn ------------------------------------------------------------------------------

def file_events(turn, project, known, symbols=None, reply=""):
    """`{path: {"edited", "read", "hit", "cited", "invoked", "first_open", "read_at", "label"}}` for one turn, each
    key as the module docstring's table gives it; `first_open` and `read_at` are call indices or None. `known` is the
    set of repository paths, `symbols` {path: [symbol names]} and `reply` the turn's reply text."""
    symbols = symbols or {}
    ev = {}
    cwd = turn.get("cwd") or project

    def get(p):
        return ev.setdefault(p, {"edited": False, "read": False, "hit": False, "cited": False, "invoked": False,
                                 "first_open": None, "read_at": None})

    later_inputs = []          # every edit input and shell command with its call index, to find cites after a read
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
        elif name in SHELL_TOOLS:
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
    """Whether `hay` names `path`: the path itself, its file name when six characters or longer, or one of `syms`
    whose last part is five characters or longer and not all lower case."""
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
    """The turn's reply: its last three texts."""
    return "\n".join(turn.get("texts", [])[-3:])


# --- what a turn spent before it opened a relevant file, which labels.reexploration totals ---------------

def exploration(turn, events, relevant):
    """`(k, tokens, path)` for the relevant file the turn opened first: k calls came before the one that opened it,
    `tokens` is that call's tokens_before, and `path` the file's; None when the turn opened no relevant file."""
    best = None
    for p in relevant:
        k = events.get(p, {}).get("first_open")
        if k is not None and (best is None or k < best[0]):
            best = (k, p)
    if best is None:
        return None
    k, p = best
    return k, turn["calls"][k]["tokens_before"], p
