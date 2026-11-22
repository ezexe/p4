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
# what `phi.py sections` says after the calls it prints: each is a start that runs at once, which the app refuses in
# a turn ezexe's own message did not begin, where the same call goes out as a card
CARD = ("In a turn ezexe's own message did not begin, the app refuses a start that runs at once: send each call there "
        "with `initiation` `own_initiative` and without `wake_when_done`, which shows a card ezexe presses.")


def parse(text, base=""):
    """(title, sections) of a plan's text. A section is a `## ` heading outside any fence whose body names files on
    a `Files:` line; its number is the one its heading opens with, else its place among the sections."""
    bare = FENCE.sub(lambda m: " " * len(m.group(0)), str(text or ""))
    top = TITLE.search(bare)
    marks = list(HEAD.finditer(bare))
    out = []
    taken = {n.group(1) for n in (NUMBER.match(m.group(1)) for m in marks) if n}   # every number a heading opens with
    for k, m in enumerate(marks):
        body = bare[m.end():marks[k + 1].start() if k + 1 < len(marks) else len(bare)]
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
                    "checks": checks.group(1).rstrip(".") if checks else ""})
    return (top.group(1) if top else "plan"), out


def runs(sections):
    """The sections as runs, each a list in the plan's order: two sections are in one run when one depends on the
    other or they share a file, and so are the sections each of them is joined with."""
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


def name(title, run):
    return f"{title}: section{'s' if len(run) > 1 else ''} " + ", ".join(s["n"] for s in run)


def brief(path, title, run):
    """A run's brief: the plan by its full path, the sections by number, their files, their checks as what done
    looks like, and the two boundaries of a worker that lands a plan."""
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
             puppeteer.WORKTREE_LINE, "",
             "This session never edits the plan file. Its report holds, for each fence, the path and the lines it "
             "landed at, and each check's output, which the session that holds the plan writes into the section as "
             "its Evidence.", ""]
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
        call = {"initiation": "user_asked", "title": name(title, run), "context": "fresh",
                "prompt": plans.level_said(brief(path, title, run), level), "wake_when_done": True,
                "use_worktree": True,
                "background": f"ezexe approved the plan `{path}`, and this start lands {name(title, run)}, whose "
                              "every edit is a fence there with its source."}
        out.append({**call, **plans.level_keys(level)})
    return out
