#!/usr/bin/env python3
"""workerlog.py: what a `claude -p` terminal worker is doing, read from its stream-json log, for the pane's page.

A `-p` worker has no live tab to read: its progress is its log `log-<name>.jsonl` in its node, beside node.json, its
brief and its report. headless.md: "The last line of the stream is a `result` message with the final response text,
cost, and session metadata"; `system/api_retry` carries `error` such as `billing_error`.
`state(log)` reads one log, `workers(home, sid)` the workers of a session and `render(workers)` the page.
"""

import json
import os

import relay

TAIL = 2 * 1024 * 1024           # the most of a log's end that is read
TEXT = 600                       # the most of a worker's latest text that is drawn
INPUT = 120                      # the most of a tool's input that is drawn
ERROR = 300                      # the most of an error that is drawn
WORKERS = 20                     # the most workers one page holds
# the key of a tool's input that says most about the call, in this order
INPUTS = ("command", "file_path", "path", "pattern", "url", "description", "prompt")


def _cut(text, n, flat=True):
    """`text` cut to `n` characters, its white space made single spaces unless `flat` is false."""
    text = " ".join(str(text or "").split()) if flat else str(text or "").strip()
    return text if len(text) <= n else text[:n - 3].rstrip() + "..."


def _rows(log):
    """The JSON objects of the last TAIL bytes of `log`, oldest first; a line that is no object (a stderr line, a BOM,
    a line cut by the tail or still being written) is skipped. OSError where the file cannot be read."""
    with open(log, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL))
        raw = f.read().decode("utf-8", "replace")
    out = []
    for line in raw.splitlines():
        line = line.strip().lstrip("﻿")
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _blocks(row):
    msg = row.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text_of(row):
    """What a row says in words: its text blocks, else its `result` or `text`."""
    said = " ".join(str(b.get("text") or "") for b in _blocks(row) if b.get("type") == "text").strip()
    return said or str(row.get("result") or row.get("text") or "").strip()


def _short(inp):
    if isinstance(inp, dict):
        for k in INPUTS:
            if inp.get(k):
                return _cut(inp[k], INPUT)
        return _cut(json.dumps(inp, ensure_ascii=False), INPUT)
    return _cut(inp, INPUT)


def name_of(log):
    """The worker's name, from the file name `log-<name>.jsonl`."""
    base = os.path.basename(log)
    base = base[len("log-"):] if base.startswith("log-") else base
    return base[:-len(".jsonl")] if base.endswith(".jsonl") else base


def state(log):
    """The state of the worker whose stream-json log is `log`: `name`, `session`, `model`, `turns` (distinct assistant
    message ids), `tool` (the last tool_use with no tool_result after it, as {name, input}, else None), `text` (the
    last assistant text), `cost` and `num_turns` (of the last result row, else None), `goal` (`set` while the run is
    running, `ended` where its last row is a result with no error, `cleared` where that result is an error, "" with no
    goal set: a `-p` log holds no row that marks a goal met or cleared, and its final `result` row comes once the goal's
    loop has ended), `error`, `end` (`done`, `failed` or `running`) and `updated` (the log's mtime). A log that cannot
    be read gives a state whose `error` names that."""
    out = {"name": name_of(log), "session": "", "model": "", "turns": 0, "tool": None, "text": "", "cost": None,
           "num_turns": None, "goal": "", "error": "", "end": "running", "updated": 0.0}
    try:
        out["updated"] = os.path.getmtime(log)
        rows = _rows(log)
    except OSError as e:
        out["error"] = f"its log cannot be read: {e.strerror or e}"
        return out
    ids, pending, error = set(), {}, ""
    for row in rows:
        kind = row.get("type")
        out["session"] = str(row.get("session_id") or out["session"])
        msg = row.get("message") if isinstance(row.get("message"), dict) else {}
        if kind == "system" and row.get("subtype") == "init" and row.get("model"):
            out["model"] = str(row["model"])
        if kind == "system" and row.get("subtype") == "api_retry" and row.get("error"):
            error = str(row["error"])
        said = _text_of(row)
        if kind == "assistant":
            ids.add(str(msg.get("id") or row.get("uuid") or len(ids)))
            out["model"] = str(msg.get("model") or out["model"])
            if row.get("isApiErrorMessage"):
                error = said or "an API error"
            for b in _blocks(row):
                if b.get("type") == "tool_use":
                    pending[str(b.get("id") or len(pending))] = {"name": str(b.get("name") or ""),
                                                                 "input": _short(b.get("input"))}
            if said and not row.get("isApiErrorMessage"):
                out["text"] = _cut(said, TEXT, flat=False)
        elif kind == "user":
            for b in _blocks(row):
                if b.get("type") == "tool_result":
                    pending.pop(str(b.get("tool_use_id") or ""), None)
        local = row.get("local_command_run")
        if isinstance(local, dict) and local.get("command") == "goal":
            out["goal"] = "set"
        if kind == "result":
            out["cost"], out["num_turns"] = row.get("total_cost_usd"), row.get("num_turns")
    last = rows[-1] if rows else {}
    if last.get("type") == "result":
        out["end"] = "failed" if last.get("is_error") else "done"
        if out["goal"]:
            out["goal"] = "cleared" if last.get("is_error") else "ended"
        error = _cut(_text_of(last) or str(last.get("subtype") or "an error"), ERROR) if last.get("is_error") else ""
    out["turns"] = len(ids)
    out["tool"] = list(pending.values())[-1] if pending and out["end"] == "running" else None
    out["error"] = _cut(error, ERROR) if error else ""
    return out


def _task(brief):
    """The first `# ` heading of a brief, "" where there is none."""
    try:
        with open(brief, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


def workers(home, sid):
    """The workers of the session `sid`: each node whose node.json `parent` is `sid` and that holds a `log-<id>.jsonl`,
    as its state with `task`, `log`, `report` and `brief` paths added. The newest WORKERS, by name."""
    out = []
    if not home or not sid:
        return out
    for ident, folder in relay.nodes(home).items():
        if str(relay.node_record(home, ident).get("parent") or "") != sid:
            continue
        log = os.path.join(folder, f"log-{ident}.jsonl")
        if not os.path.isfile(log):
            continue
        brief = os.path.join(folder, f"brief-{ident}.md")
        out.append({**state(log), "name": ident, "task": _task(brief), "log": log.replace("\\", "/"),
                    "report": os.path.join(folder, f"report-{ident}.md").replace("\\", "/"),
                    "brief": brief.replace("\\", "/")})
    out.sort(key=lambda w: -w["updated"])
    return sorted(out[:WORKERS], key=lambda w: w["name"])


def render(found):
    """The page's markdown, one block a worker: its error first and in bold where there is one, then its name and task,
    its end, or its turn and tool, its cost and turns, its goal, its latest text, and its log and report as links.
    "" where there is none."""
    blocks = []
    for w in found:
        lines = []
        if w.get("error"):
            lines.append(f"**{w['error']}**")
        lines.append(f"`{w['name']}`" + (f": {w['task']}" if w.get("task") else ""))
        if w["end"] == "running":
            tool = w.get("tool")
            lines.append(f"running, turn {w['turns']}" + (f", in `{tool['name']}` {tool['input']}".rstrip() if tool else ""))
        else:
            lines.append(w["end"])
        if w.get("cost") is not None or w.get("num_turns") is not None:
            lines.append(f"cost ${w['cost']:.4f}, " if isinstance(w.get("cost"), (int, float)) else "cost unknown, ")
            lines[-1] += f"{w['num_turns']} turns" if w.get("num_turns") is not None else "turns unknown"
        if w.get("goal"):
            lines.append(f"goal {w['goal']}")
        if w.get("text"):
            lines.append("> " + w["text"].replace("\n", "\n> "))
        lines.append(f"[log]({w['log']}) · [report]({w['report']})")
        blocks.append("  \n".join(lines))
    return "# Workers\n\n" + "\n\n".join(blocks) + "\n" if blocks else ""
