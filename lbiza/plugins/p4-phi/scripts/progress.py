#!/usr/bin/env python3
"""progress.py: a session tree's goals, task lists and plan loops as data, for the pane of `/phi-pane`.

`phi.py progress` writes progress.json into the asking session's folder: a node for that session and for each live
session under it, with its goal as session.json holds it, its task list as plan.json holds it, and the plan file it
works with that plan's sections and its loop log. The hooks module runs the command while its pane is open and draws
the file. `sources` lists the files the nodes were read from, whose times the module watches between two runs, and
`folders` the folders whose list of names it watches, where a new session's folder appears.
`phi.py spend` prints what `spend` reads: the tokens a session and each teammate and subagent under it spent.
"""

import glob
import os
import re

import plans
import puppeteer
import relay
import sections
import starts
import transcript

FILE = "progress.json"
NODES = 64                       # the most sessions one file holds
STEPS = 24                       # the most steps of one session, and the most sections of one plan
SOURCES = 400                    # the most files the module watches
CONDITION = 400                  # the most of a goal's condition that is drawn
GOAL_TAIL = 256 * 1024           # the most of a transcript's end read for a typed goal's row, at every run
# The files of a session's folder a node is read from: its record, its task list, the hooks' log that
# puppeteer.working reads, and its turns, which phi.load_turns reads.
WATCHED = ("session.json", "plan.json", "log.jsonl", "turns.jsonl", "upkeep.json", "team.json")
TEAM = "team.json"               # hooks/register.ts writes it: the teammates `$.agent.list()` answered in the lead
OVER = ("completed", "failed", "killed")

# plan-planner, "The plan loop": "under a last heading `## Loop log`, one line a round as
# `- Round <n>: <k> held, <m> minutes: <what the mends changed>`", and a clean round as
# `- Round <n>: clean, <m> minutes`. The indented lines beneath a round, one a finding, open with no `Round`.
# A line of the earlier shape, `- Round <n> of 5: ...`, still gives its round.
LOG = re.compile(r"(?im)^## +Loop log[ \t]*$")
ROUND = re.compile(r"(?im)^[ \t]*[-*][ \t]+Round[ \t]+(\d+)(?:[ \t]+of[ \t]+\d+)?[ \t]*:[ \t]*(.+?)[ \t]*$")
HELD = re.compile(r"(?i)^(\d+)[ \t]+held\b")
CLEAN = re.compile(r"(?i)^clean\b")
EVIDENCE = sections.EVIDENCE
# A plan a brief names, as sections.brief words it: "of the plan `<path>`", a file directly in a plans folder.
NAMED = re.compile(r"`([^`\n]*[\\/]plan-planner[\\/][^`\\/\n]+\.md)`")
# plan-planner, "The plan loop": where the last round held findings and no round follows, since every group's loop
# has ended, the log closes with `- Ended: <the groups that stopped and the groups that ended clean>`.
ENDED = re.compile(r"(?im)^[ \t]*[-*][ \t]+Ended[ \t]*:[ \t]*(.+?)[ \t]*$")
# A round read by groups holds one indented line for each, `  - group <name>: <k> held, <m> minutes`.
GROUP = re.compile(r"(?im)^[ \t]+[-*][ \t]+group[ \t]+\S+[ \t]*:[ \t]*(?:\d+[ \t]+held|clean)\b")


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
    row = plans.goal_row(s.get("transcript") or "", GOAL_TAIL)
    if row.get("condition"):
        out = {"state": plans.goal_over(row) or "set", "condition": relay._short(row["condition"], CONDITION)}
        return dict(out, reason=relay._short(row["reason"], 300)) if row.get("reason") else out
    return None


def held_of(said):
    """The findings that held in a round, by its line's words: 0 for a clean round, None where the line says none."""
    m = HELD.match(said)
    return 0 if CLEAN.match(said) else int(m.group(1)) if m else None


def loop_of(bare):
    """A plan's loop as its log says it, or None for a plan with no `## Loop log`: the round it is on, `of`, which is
    that same round, since no count of rounds bounds a loop, the findings that held in the last round,
    what that round's line says, and how the loop ended: `clean` at a round with nothing to mend, `stopped` where a
    round held more findings than the round before, and '' while it goes on, as it does at a level count. `bare` is the plan's text with its
    fences blanked, so a log quoted in a fence is no log."""
    m = LOG.search(bare)
    if not m:
        return None
    rows = [(int(n), said) for n, said in ROUND.findall(bare[m.end():])]
    if not rows:
        return {"round": 0, "of": 0, "held": 0, "last": "", "state": "", "ended": False}
    held = [held_of(said) for _, said in rows]
    state = "clean" if held[-1] == 0 else ""
    by_group = bool(GROUP.search(bare[m.end():]))
    if not state and not by_group and len(held) > 1 and None not in held[-2:] and held[-1] > held[-2]:
        state = "stopped"
    if not state and ENDED.search(bare[m.end():]):
        state = "stopped"
    n, said = rows[-1]
    return {"round": n, "of": n, "held": held[-1] or 0, "last": relay._short(said, 200),
            "state": state, "ended": bool(state)}


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


def team_of(home, sid):
    """The teammates of the agent team a session leads, as its hooks module kept them in team.json: each one's name,
    the task its lead gave it, its state as `$.agent.list()` words it, and what it is doing where that is told."""
    rows = relay._read_json(os.path.join(relay._dir(home, sid), TEAM)).get("teammates")
    return [{"name": relay._short(r.get("name"), 60), "task": relay._short(r.get("task"), 120),
             "state": str(r.get("state") or ""), "doing": relay._short(r.get("doing"), 160)}
            for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict)][:STEPS]


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
            "plan": plan_of(s), "team": team_of(home, sid)}


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
    held = {one["sessionId"] for one in nodes}
    for sid, s in sorted(relay._sessions(home).items()):
        # a team's lead typed into a terminal is under no session: it is a row of its own while its team works
        if sid in held or puppeteer.closed(s) or len(nodes) >= NODES:
            continue
        if any(mate["state"] not in OVER for mate in team_of(home, sid)):
            nodes.append(dict(node(home, sid, 0, s), apart=True))
            sources += [os.path.join(relay._dir(home, sid), name) for name in WATCHED]
    return {"top": top, "nodes": nodes, "sources": [p.replace("\\", "/") for p in sources[:SOURCES]],
            "folders": [b.replace("\\", "/") for b in relay.session_bases(home) if os.path.isdir(b)]}


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


# What one API call's `usage` holds, by the key each figure is summed under.
SPENT = (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
         ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens"))


def spend_of(path):
    """What the API calls of one transcript spent: `calls`, the tokens of `input`, `cache_write`, `cache_read` and
    `output`, and the `models` named. An assistant message is written one line per content block, so each is
    counted once, by the last line that carries its id. A message Claude Code wrote itself, whose model is `<synthetic>`,
    is no API call and is left out. Zeros for a file that is not there."""
    last = {}
    for d in transcript.read_lines(path):
        m = d.get("message") or {}
        if d.get("type") == "assistant" and isinstance(m.get("usage"), dict) and m.get("model") != "<synthetic>":
            last[m.get("id") or d.get("uuid")] = m
    out = {"calls": len(last),
           "models": sorted({str(m["model"]) for m in last.values() if str(m.get("model") or "").startswith("claude")})}
    for key, name in SPENT:
        out[key] = sum(int(m["usage"].get(name) or 0) for m in last.values())
    return out


def transcript_of(s):
    """A session's transcript: the path its record keeps where that file is there, else the file Claude Code names by the session's last
    CLI id under a project of its `projects` folder, '' where neither is there."""
    kept = os.path.expanduser(str(s.get("transcript") or ""))
    if kept and os.path.isfile(kept):
        return kept
    ids = [str(x) for x in s.get("cliSessionIds") or [] if x]
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    found = sorted(glob.glob(os.path.join(base, "projects", "*", ids[-1] + ".jsonl"))) if ids else []
    return found[0] if found else ""


def spend(home, who):
    """What a session and each agent under it spent, for `phi.py spend`: a row for the session itself, one for each
    transcript in the `subagents` folder beside its own, a teammate's or a subagent's by the `.meta.json` beside
    it, and a last row for all of them. `who` is a session id of the store, or a session's title, as the name a
    terminal lead was started under is, where the newest session of that title is taken, or a reading team's name,
    whose transcript coworker.kept finds by its node. [] for a session with no transcript, and for no name at all."""
    held = relay._sessions(home) if who else {}
    s = held.get(who) or max((x for x in held.values() if x.get("title") == who),
                             key=lambda x: str(x.get("createdAt") or ""), default={})
    main = transcript_of(s)
    if not main:                                   # a reading team's lead, by the session id of its node
        import coworker
        main = (coworker.kept(who, home, "") or [""])[-1]
    mains = [main] if main else []
    if not mains:
        return []
    rows = []
    for main in mains:
        rows.append(dict(spend_of(main), who="the session itself", kind="session"))
        for path in sorted(glob.glob(os.path.join(os.path.splitext(main)[0], "subagents", "agent-*.jsonl"))):
            meta = relay._read_json(os.path.splitext(path)[0] + ".meta.json")
            kind = "teammate" if meta.get("taskKind") == "in_process_teammate" else "subagent"
            name = str(meta.get("name") or meta.get("agentType") or os.path.basename(path)[6:-6])
            rows.append(dict(spend_of(path), who=f"{kind} {name}", kind=kind))
    rows.append({"who": "all of them", "kind": "all", "calls": sum(r["calls"] for r in rows),
                 "models": sorted({m for r in rows for m in r["models"]}),
                 **{key: sum(r[key] for r in rows) for key, _ in SPENT}})
    return rows
