#!/usr/bin/env python3
"""sections.py: an approved plan's sections as the starts of the workers that land them, for `phi.py sections`.

A plan is shaped by p4-temportal's skill plan-planner: each section that changes files names them on a line
`**Files:**`, the sections that land before it on a line `**Depends on:**`, and what proves it on a line
`**Checks:**`. Sections that share a file or depend on one another are one worker's run, landed in the plan's order,
and every other section is a run of its own. Each run is one start call, an integrator's, since its fences are
written: the skill sub-agentic's table has the integrator land "written fences".
"""

import re

import plans
import puppeteer
import relay
import starts

FENCE = re.compile(r"(?ms)^(`{3,}|~{3,}).*?^\1[ \t]*$")
TITLE = re.compile(r"(?m)^# +(.+?)\s*$")
HEAD = re.compile(r"(?m)^## +(.+?)\s*$")
NUMBER = re.compile(r"(\d+)\b")
LINE = r"(?im)^[ \t>*-]*(?:\*\*)?%s(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$"
DEPENDS = re.compile(LINE % r"depends\s+on")
CHECKS = re.compile(LINE % r"checks?")
EVIDENCE = re.compile(LINE % r"evidence")      # a landed section holds this line; progress.py reads it for the pane too
# plan-planner, "What every section of a plan holds": `**Assumed:**` stands after `**Observed:**`, with one line for
# each thing the section takes to be so, or the one word `none`.
ASSUMED = re.compile(r"(?im)^[ \t>*-]*\*\*assumed[ \t]*:?[ \t]*\*\*[ \t]*:?[ \t]*(.*?)[ \t]*$")
ITEM = re.compile(r"^[ \t]*[-*][ \t]+(.+?)[ \t]*$")
NOTHING = re.compile(r"^\W*(?:none|nothing)\W*$", re.I)      # the whole of a line, so `None of them waits` is a line
# agent-teams.md, "Choose an appropriate team size": "Having 5-6 tasks per teammate keeps everyone productive", so a
# group of sections is filled to five fences before a team reads it, which is the fill the first plan read by
# groups was read at, on 2026-11-23.
FULL = 5
# what `phi.py sections` says after the calls it prints: each is a start that runs at once, which the app refuses in
# a turn ezexe's own message did not begin, where the same call goes out as a card; a planner another session started
# makes no such call and starts each run as an integrator subagent, which waits on no card
CARD = ("In a turn ezexe's own message did not begin, the app refuses a start that runs at once: send each call there "
        "with `initiation` `own_initiative` and without `wake_when_done`, which shows a card ezexe presses. A planner "
        "another session started sends none of these calls: it starts one `p4-phi:integrator` subagent for each, "
        "with the call's `prompt` as its brief, in a git worktree it makes, as the line at its plan's approval says.")


def assumed_of(body):
    """How many lines stand under a section's `**Assumed:**`: what follows the label on its own line, and each list
    item beneath it up to the first line that is no item. A line that says `none` counts for nothing."""
    m = ASSUMED.search(body)
    if not m:
        return 0
    said = [m.group(1)] if m.group(1) else []
    for line in body[m.end():].split("\n")[1:]:
        item = ITEM.match(line)
        if item:
            said.append(item.group(1))
        elif line.strip() or said:
            break
    return sum(1 for x in said if not NOTHING.match(x))


def parse(text, base=""):
    """(title, sections) of a plan's text. A section is a `## ` heading outside any fence whose body names files on
    a `Files:` line, and is `landed` where it holds an `Evidence:` line; its number is the one its heading opens with, else its place among the sections. Its `fences`
    are the fenced blocks it holds and its `assumed` the lines under its `Assumed:`."""
    raw = str(text or "")
    bare = FENCE.sub(lambda m: " " * len(m.group(0)), raw)
    top = TITLE.search(bare)
    marks = list(HEAD.finditer(bare))
    out = []
    taken = {n.group(1) for n in (NUMBER.match(m.group(1)) for m in marks) if n}   # every number a heading opens with
    for k, m in enumerate(marks):
        end = marks[k + 1].start() if k + 1 < len(marks) else len(bare)
        body = bare[m.end():end]
        files = starts.files_of(body, base)
        if not files:                              # no `Files:` line, or `Files: none`: context, and no worker's
            continue
        n = NUMBER.match(m.group(1))
        after, checks = DEPENDS.search(body), CHECKS.search(body)
        said = starts.LIST_END.split(starts.FILES_LINE.search(body).group(1).strip(), 1)[0].strip().rstrip(".")
        if n:
            num = n.group(1)
        else:                                      # the first number no heading opens with and no section took
            num = next(str(i) for i in range(1, len(marks) + 2) if str(i) not in taken)
            taken.add(num)
        out.append({"n": num, "head": m.group(1), "files": files, "said": said,
                    "after": re.findall(r"\d+", after.group(1)) if after else [],
                    # `Checks: none` names no check, as `Files: none` names no file
                    "checks": checks.group(1).rstrip(".") if checks and not starts.NO_FILES.match(checks.group(1))
                    else "",
                    "fences": len(FENCE.findall(raw[m.end():end])), "assumed": assumed_of(body),
                    "landed": bool(EVIDENCE.search(body))})
    return (top.group(1) if top else "plan"), out


def runs(sections):
    """The sections as runs, each a list in the plan's order: two sections are in one run when one depends on the
    other or they share a file, and so are the sections each of them is joined with. A landed section, one that holds
    its `Evidence:`, is in no run, and a `Depends on:` that names it is met and joins nothing."""
    sections = [s for s in sections if not s.get("landed")]
    run = {s["n"]: k for k, s in enumerate(sections)}
    for i, a in enumerate(sections):
        for b in sections[:i]:
            if b["n"] in a["after"] or any(relay.overlap(p, q) for p in a["files"] for q in b["files"]):
                old, new = run[a["n"]], run[b["n"]]
                run = {n: new if r == old else r for n, r in run.items()}
    out = {}
    for s in sections:
        out.setdefault(run[s["n"]], []).append(s)
    return list(out.values())


def fences(group):
    return sum(s.get("fences", 0) for s in group)


def groups(sections):
    """The runs as the groups one coworker each reads and lands, in the plan's order: runs are joined until a group
    holds FULL fences, and a last group under FULL joins the one before it. No count bounds the groups: a plan has
    as many as its sections' work makes."""
    out = []
    for run in runs(sections):
        if out and fences(out[-1]) < FULL:
            out[-1] = out[-1] + run
        else:
            out.append(list(run))
    if len(out) > 1 and fences(out[-1]) < FULL:
        out[-2:] = [out[-2] + out[-1]]
    return out


def team(group):
    """True where a group earns an agent team: it holds FULL fences, or one of its sections names a check, so the
    lens `checks` has a test to read. Only a plan's one small group of prose is left for one reader."""
    return fences(group) >= FULL or any(s.get("checks") for s in group)


def name(title, run):
    return f"{title}: section{'s' if len(run) > 1 else ''} " + ", ".join(s["n"] for s in run)


def brief(path, title, run, base="", where=None):
    """A run's brief: the plan by its full path, the sections by number, their files, their checks as what done
    looks like, and the two boundaries of a worker that lands a plan. `where` is the lines on where the session
    works, which are the checkout's, puppeteer.checkout_lines(base), where it is None."""
    many = len(run) > 1
    nums = ", ".join(s["n"] for s in run)
    files = list(dict.fromkeys(p.strip() for s in run for p in s["said"].split(",") if p.strip()))
    checks = [s["checks"] for s in run if s["checks"]]
    lines = [f"# {name(title, run)}", "",
             f"Task: land section{'s' if many else ''} {nums} of the plan `{path}`"
             + (", in that order" if many else "") + ", as the fences there say.", "",
             f"Read the plan's Context and {'those sections' if many else 'that section'} whole before the first "
             "edit. ezexe approved the plan, so its fences are the change: where a fence does not fit the tree as "
             "it is, stop and report the fence and why, and write no approach of this session's own.", "",
             "Files: " + ", ".join(files), "",
             *(puppeteer.checkout_lines(base) if where is None else where),
             "This session never edits the plan file. Its report holds, for each fence, the path and the lines it "
             "landed at, and each check's output, which the session that holds the plan writes into the section as "
             "its Evidence.", ""]
    assumed = sum(s.get("assumed", 0) for s in run)
    if assumed:
        lines += [f"{'Those sections hold' if many else 'That section holds'} {assumed} "
                  f"line{'s' * (assumed != 1)} under `Assumed:`, which nobody saw: where the tree shows one wrong, "
                  "stop and report it as a fence that does not fit.", ""]
    if checks:
        lines += ["Checks, and no whole suite: " + "; ".join(checks) + ".", ""]
    lines += [f"Done looks like: every fence of section{'s' if many else ''} {nums} landed"
              + (", those checks passing" if checks else "") + ", committed and reported.", "Report when done."]
    return "\n".join(lines)


def calls(path, base=""):
    """One start call for each run of the plan at `path`, in the plan's order."""
    with open(path, encoding="utf-8") as f:
        title, sections = parse(f.read(), base)
    out = []
    for run in runs(sections):
        level = {**plans.CHILD_LEVELS["static"], "kind": "static"}      # written fences are an integrator's to land
        level["effort"] = plans.capped(level["effort"])
        # the brief names its own level, which plans.child_level lays over the kind call_of would read from its words
        out.append(puppeteer.call_of({
            "title": name(title, run), "context": "fresh", "parent": "plan",
            "brief": plans.level_said(brief(path, title, run, base), level),
            "background": f"ezexe approved the plan `{path}`, and this start lands {name(title, run)}, whose "
                          "every edit is a fence there with its source."}))
    return out
