#!/usr/bin/env python3
"""sections.py: an approved plan's sections as the starts of the workers that land them, for `phi.py sections`.

A plan is shaped by p4-temportal's skill plan-planner: each section that changes files names them on a line
`**Files:**`, the sections that land before it on a line `**Depends on:**`, and what proves it on a line
`**Checks:**`, and its runner on a line `**Runner:**`. For reading, sections that share a file or depend on one
another are one run, runs(), joined into groups of five fences, groups(). For landing, only a shared file joins two
sections, file_runs(), and a `Depends on:` puts the later run in a later wave, waves() and ready(); lint() is what
the plan's three readers check. Each run is one start call, an integrator's, since its fences are
written: the skill sub-agentic's table has the integrator land "written fences".
"""

import re

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
# `Runner: print api`, `print max`, `interactive` or `team`: the kind of worker a section is the brief of
RUNNER = re.compile(LINE % r"runner")
RUNNERS = {"print api": ("print", "api"), "print max": ("print", "max"), "print": ("print", ""),
           "interactive": ("interactive", "max"), "team": ("interactive", "max")}
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


def runner_of(body):
    """The runner a section names on its `Runner:` line, as {"mode", "pool", "team", "said"} with its `Model:` and
    `Effort:` lines as `level`, or {} where it names none: `print api`, `print max`, `print`, `interactive` or
    `team`, read from the line's first words, so `Runner: print max, opus at high` names the Max plan."""
    import plans
    m = RUNNER.search(body)
    out = {}
    if m:
        said = re.sub(r"[`*]", "", m.group(1)).strip().lower()
        for key in sorted(RUNNERS, key=len, reverse=True):
            if re.match(re.escape(key) + r"(?![\w-])", said):
                mode, pool = RUNNERS[key]
                out = {"mode": mode, "pool": pool, "team": key == "team", "said": key}
                break
    level = plans.said_level(body)
    if level:
        out["level"] = level
    return out


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
                    "landed": bool(EVIDENCE.search(body)), "runner": runner_of(body), "body": body})
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


def _join(run, a, b):
    old, new = run[a], run[b]
    return {n: new if r == old else r for n, r in run.items()}


def _split(sections):
    """(the runs of file_runs, the groups of file-joined runs that wait on each other): sections that share a file are
    joined first; then runs whose `Depends on:` make a cycle between them, as 1 writes x, 2 depends on 1 and 3 writes
    x and depends on 2, are joined too, since none of them could start. Each is a list of sections in the plan's
    order; a tangle is a list of the sections it joined."""
    sections = [s for s in sections if not s.get("landed")]
    run = {s["n"]: k for k, s in enumerate(sections)}
    for i, a in enumerate(sections):
        for b in sections[:i]:
            if any(relay.overlap(p, q) for p in a["files"] for q in b["files"]):
                run = _join(run, a["n"], b["n"])
    tangled = []
    while True:
        need = {}
        for s in sections:
            for d in s["after"]:
                if d in run and run[d] != run[s["n"]]:
                    need.setdefault(run[s["n"]], set()).add(run[d])
        found = None
        for r in need:
            back = sorted(d for d in _after(need, r) if r in _after(need, d))
            if back:
                found = [r] + back
                break
        if not found:
            break
        keep = found[0]
        tangled.append([s["n"] for s in sections if run[s["n"]] in found])
        run = {n: keep if r in found else r for n, r in run.items()}
    out = {}
    for s in sections:
        out.setdefault(run[s["n"]], []).append(s)
    return list(out.values()), tangled


def _after(need, start):
    """Every run `start` waits for, directly or through others."""
    seen, todo = set(), list(need.get(start, ()))
    while todo:
        d = todo.pop()
        if d not in seen:
            seen.add(d)
            todo += list(need.get(d, ()))
    return seen


def file_runs(sections):
    """The sections as the runs one worker each lands, in the plan's order: two sections are in one run where they
    share a file, so a `Depends on:` orders runs into waves, waves(), and joins none, except runs that wait on each
    other through their `Depends on:`, which would deadlock and are one run in the plan's order. A landed section is
    in none."""
    return _split(sections)[0]


def needs(run):
    """The section numbers a run waits for: each `Depends on:` of its sections that is no section of the run."""
    own = {s["n"] for s in run}
    return sorted({d for s in run for d in s["after"] if d not in own}, key=lambda x: int(x))


def ready(sections, met=()):
    """The runs of file_runs whose every need is met: a section is met where it holds its `Evidence:` or is in
    `met`, the numbers of sections whose worker reported done. A need that names no section of the plan is met,
    as a landed section's is, so a typo does not hold a run forever; lint() names it."""
    have = {s["n"] for s in sections}
    done = {s["n"] for s in sections if s.get("landed")} | set(met)
    return [run for run in file_runs(sections) if all(d in done or d not in have for d in needs(run))]


def waves(sections):
    """The runs of file_runs as waves, each a list of runs that start together once the waves before it are done:
    wave 1 is every run with no open need. Runs whose needs never close, a cycle, make a last wave of their own."""
    left, done, out = file_runs(sections), {s["n"] for s in sections if s.get("landed")}, []
    have = {s["n"] for s in sections}
    while left:
        now = [r for r in left if all(d in done or d not in have for d in needs(r))]
        if not now:
            out.append(left)
            break
        out.append(now)
        done |= {s["n"] for r in now for s in r}
        left = [r for r in left if r not in now]
    return out


HOT = re.compile(r"(?:^|/)(?:README\.md|SKILL\.md|CHANGELOG\.md|plugin\.json|marketplace\.json)$", re.I)


def _reaches(sections):
    """{n: every section n depends on, directly or through others}."""
    after = {s["n"]: set(s["after"]) for s in sections}
    out = {}
    for n in after:
        seen, todo = set(), list(after[n])
        while todo:
            d = todo.pop()
            if d not in seen:
                seen.add(d)
                todo += list(after.get(d, ()))
        out[n] = seen
    return out


def lint(text, base=""):
    """The three readers' checks of a plan written as pieces, as (lens, line) pairs: `fences` where two sections
    that no `Depends on:` orders write one file, so they would run at once; `sources` where a section names a file
    another section writes and depends on it neither way, or names a section that is not there; `checks` where a
    section has no check of its own."""
    _, found = parse(text, base)
    have = {s["n"] for s in found}
    reach = _reaches(found)
    ordered = lambda a, b: b["n"] in reach[a["n"]] or a["n"] in reach[b["n"]]   # noqa: E731
    out = []
    for i, a in enumerate(found):
        for b in found[:i]:
            if a["landed"] or b["landed"]:         # a landed section runs with nothing
                continue
            shared = sorted({p for p in a["files"] for q in b["files"] if relay.overlap(p, q)})
            if shared and not ordered(a, b):
                out.append(("fences", f"sections {b['n']} and {a['n']} both write {', '.join(shared)} and no "
                                      f"`Depends on:` orders them: put the file in one section or add "
                                      f"`Depends on: {b['n']}` to section {a['n']}"))
    for a in found:
        for d in a["after"]:
            if d not in have:
                out.append(("sources", f"section {a['n']} depends on section {d}, which the plan does not hold"))
        for b in found:
            if a is b or a["landed"] or b["landed"] or ordered(a, b):
                continue
            named = sorted(p for p in b["files"] if not HOT.search(p) and re.search(
                r"(?<![\w/.-])" + re.escape(p) + r"(?![\w/-])", a["body"].replace(a["said"], "")))
            if named:
                out.append(("sources", f"section {a['n']} names {', '.join(named)}, which section {b['n']} writes, "
                                       f"and states no `Depends on: {b['n']}`"))
        if not a["checks"]:
            out.append(("checks", f"section {a['n']} has no `Checks:` line of its own"))
    for tangle in _split(found)[1]:
        out.append(("sources", f"sections {', '.join(tangle)} wait on each other through `Depends on:` and a shared "
                               "file, so none could start: file_runs lands them as one run in the plan's order; "
                               "put the shared file in one section or drop a `Depends on:`"))
    return out


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
