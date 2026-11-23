#!/usr/bin/env python3
"""progress.py: a session tree's goals, task lists and plan loops as data, for the pane of `/phi-pane`.

`phi.py progress` writes progress.json into the asking session's folder: a node for that session and for each live
session under it, with its goal as session.json holds it, its task list as plan.json holds it, and the plan file it
works with that plan's sections and its loop log. The hooks module runs the command while its pane is open and draws
the file. `sources` lists the files the nodes were read from, whose times the module watches between two runs, and
`folders` the folders whose list of names it watches, where a new session's folder appears.
"""

import os
import re

import plans
import puppeteer
import relay
import sections
import starts

FILE = "progress.json"
ROUNDS = 5                       # plan-planner, "The plan loop": the loop ends after five rounds
NODES = 64                       # the most sessions one file holds
STEPS = 24                       # the most steps of one session, and the most sections of one plan
SOURCES = 400                    # the most files the module watches
CONDITION = 400                  # the most of a goal's condition that is drawn
# The files of a session's folder a node is read from: its record, its task list, the hooks' log that
# puppeteer.working reads, and its turns, which phi.load_turns reads.
WATCHED = ("session.json", "plan.json", "log.jsonl", "turns.jsonl")

# plan-planner, "The plan loop": "under a last heading `## Loop log`, one line a round as
# `- Round <n> of 5: <what the round changed>`, or `- Round <n> of 5: dry` for a dry round".
LOG = re.compile(r"(?im)^## +Loop log[ \t]*$")
ROUND = re.compile(r"(?im)^[ \t]*[-*][ \t]+Round[ \t]+(\d+)(?:[ \t]+of[ \t]+(\d+))?[ \t]*:[ \t]*(.+?)[ \t]*$")
DRY = re.compile(r"(?i)^dry\b")
EVIDENCE = re.compile(sections.LINE % r"evidence")
# A plan a brief names, as sections.brief words it: "of the plan `<path>`", a file directly in a plans folder.
NAMED = re.compile(r"`([^`\n]*[\\/]plan-planner[\\/][^`\\/\n]+\.md)`")


def goal_of(s):
    """A session's goal as the pane shows it, or None for a session with none. `state` is `asked` while the goal is
    asked for and not set, `set`, or how it ended, `met`, `failed` or `cleared`. p4-phi's own record on session.json
    is read first, phi.goal_ask and phi.goal_due, and for a goal a person typed, which has no such record, the last
    goal row of the transcript, plans.goal_row."""
    ask = s.get("goalAsk") if isinstance(s.get("goalAsk"), dict) else {}
    g = s.get("goal") if isinstance(s.get("goal"), dict) else {}
    if ask.get("condition"):
        return {"state": "asked", "condition": relay._short(ask["condition"], CONDITION)}
    if g.get("condition"):
        state = str(g.get("over") or "") or ("set" if g.get("set") else "asked")
        why = g.get("reason") if g.get("over") else "" if g.get("set") else g.get("failed")
        out = {"state": state, "condition": relay._short(g["condition"], CONDITION)}
        return dict(out, reason=relay._short(why, 300)) if why else out
    row = plans.goal_row(s.get("transcript") or "")
    if row.get("condition"):
        out = {"state": plans.goal_over(row) or "set", "condition": relay._short(row["condition"], CONDITION)}
        return dict(out, reason=relay._short(row["reason"], 300)) if row.get("reason") else out
    return None


def loop_of(bare):
    """A plan's loop as its log says it, or None for a plan with no `## Loop log`: the round it is on, of how many,
    what the last round changed, how many dry rounds stand in a row at the log's end, and whether the loop has ended,
    which it has after two dry rounds in a row or at the last round. `bare` is the plan's text with its fences
    blanked, so a log quoted in a fence is no log."""
    m = LOG.search(bare)
    if not m:
        return None
    rows = [(int(n), int(of or ROUNDS), said) for n, of, said in ROUND.findall(bare[m.end():])]
    if not rows:
        return {"round": 0, "of": ROUNDS, "last": "", "dry": 0, "ended": False}
    dry = 0
    for _, _, said in reversed(rows):
        if not DRY.match(said):
            break
        dry += 1
    n, of, said = rows[-1]
    return {"round": n, "of": of, "last": relay._short(said, 200), "dry": dry, "ended": dry >= 2 or n >= of}


def plan_of(s):
    """The plan a session works, or None: the file its Write and Edit calls kept as `planFile`, phi.keep_plan_file,
    else the plan its brief names. Each `## ` heading but the loop log is a section, with `lands` where it names
    files and `done` where it holds its Evidence. A plan that was sorted away or cleared reads as none."""
    path = str(s.get("planFile") or "")
    if not path:
        named = NAMED.search(str(s.get("task") or ""))
        path = named.group(1).replace("\\", "/") if named else ""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    bare = sections.FENCE.sub(lambda m: " " * len(m.group(0)), text)
    title = sections.TITLE.search(bare)
    marks = list(sections.HEAD.finditer(bare))
    out = []
    for k, m in enumerate(marks):
        if m.group(1).strip().lower() == "loop log":
            continue
        body = bare[m.end():marks[k + 1].start() if k + 1 < len(marks) else len(bare)]
        out.append({"head": relay._short(m.group(1), 90), "lands": bool(starts.files_of(body, "")),
                    "done": bool(EVIDENCE.search(body))})
    return {"path": path, "title": relay._short(title.group(1), 120) if title else os.path.basename(path),
            "sections": out[:STEPS], "loop": loop_of(bare)}


def node(home, sid, depth, s):
    """One session of the tree: its title, whether it is inside a turn, whether its last turn was shown done, its
    goal, its steps with the one in progress and the subagents open under each, and its plan."""
    phi = puppeteer._phi()
    plan = plans.load(home, sid)
    turns = phi.load_turns(home, sid)
    steps = [x for x in plan.get("steps") or [] if isinstance(x, dict)]
    return {"sessionId": sid, "depth": depth, "title": relay._short(phi.title_of(s), 120),
            "working": puppeteer.working(home, sid), "done": bool(turns and turns[-1].get("done")),
            "goal": goal_of(s), "current": str(plan.get("current") or ""),
            "steps": [{"addr": str(x.get("addr") or ""), "content": relay._short(x.get("content"), 120),
                       "status": str(x.get("status") or "pending"),
                       "agents": sum(1 for t in x.get("tasks") or []
                                     if isinstance(t, dict) and t.get("agent") and t.get("status") == "open")}
                      for x in steps[:STEPS]],
            "plan": plan_of(s)}


def build(home, top):
    """The tree of the session `top` as data: a node for it and for each session under it that p4-phi's records do
    not hold as closed, in tree order, the files they were read from, and the folder every session's folder is in."""
    nodes, sources = [], []
    for sid, depth, s in puppeteer.subtree(home, top):
        if depth and puppeteer.closed(s):
            continue
        if len(nodes) >= NODES:
            break
        one = node(home, sid, depth, s)
        nodes.append(one)
        folder = relay._dir(home, sid)
        sources += [os.path.join(folder, name) for name in WATCHED]
        if one["plan"]:
            sources.append(one["plan"]["path"])
    return {"top": top, "nodes": nodes, "sources": [p.replace("\\", "/") for p in sources[:SOURCES]],
            "folders": [os.path.join(home, "phi", "sessions").replace("\\", "/")]}


def write(home, sid):
    """progress.json of the session `sid`, rewritten only when it differs, and what `phi.py progress` prints: the
    file's path and whether it was rewritten. {} for a session with no folder, where nothing is written and no
    folder is made."""
    folder = relay._dir(home, sid) if sid else ""
    if not sid or not os.path.isfile(os.path.join(folder, "session.json")):
        return {}
    path = os.path.join(folder, FILE)
    m = build(home, sid)
    changed = relay._read_json(path) != m
    if changed:
        relay._write_json(path, m)
    return {"path": path.replace("\\", "/"), "changed": changed}
