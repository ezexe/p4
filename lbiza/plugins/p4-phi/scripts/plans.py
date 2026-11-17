"""plans.py: each session's task list as numbered steps, the tree of task lists its parent's anchor holds, and the
advice and checks that ride on them.

  task list  the list a session keeps with `mcp__ccd_turn__update_plan`. Each call, a whole new list, an advance, or
             done and start, is applied to <session>/plan.json: its steps with their addresses, statuses and the step
             in progress. The `lookup-record` hook routes each call there after it runs, and a session whose hooks
             lack that route has its calls read back from its transcript at its next message.
  address    an orchestrator's steps are 1, 2, 3. A child started for a step of its parent's task list has that
             step's address as its parent step, so its steps are Y.1, Y.2. The parent step is the address the brief
             names, such as "step 2.3", else the parent's open step whose words the brief matches best, else the
             parent's step in progress.
  tree       the parent's anchor, made by relay.make_anchor, holds every child's task list and its own.
  check      at each step boundary, when a step moves to in progress, a session is told what bears on that step:
               up      its parent step was revised, removed or passed
               across  a sibling's step in progress shares its words, or touches its owned paths
               down    its children's progress on their steps, when it moved since the last check
             and the warnings kept for it. Nothing when nothing bears on it.
  revision   a session that replaces its list revises its task list. A changed or removed step is told on the next
             message, through relay.warn, to the children it is the parent step of, down, to the siblings whose step
             in progress shares its words, across, and to the parent, up. A child whose parent step is removed is
             told so.
  advice     the open steps that can each run on their own are named for children of their own; an orchestrator
             hands each work step out, a step that only reads or only runs a command to a background subagent, and
             keeps orchestration and landing; each start names the model and effort its kind of work gets.
  subagents  a subagent the Agent tool starts is a task of the step in progress, told what changed beside it.
  turns      at Stop, a turn's report is matched against the open steps of the session's children and siblings and
             delivered to those it bears on, and a turn that ends with open steps the session tree can settle is
             sent back to its next step.
  in flight  the Stop input's list of background tasks still running, kept on session.json for the checks that
             run between turns.
"""

import hashlib
import json
import os
import re

import relay

STEP_RE = re.compile(r"\bsteps?\s+(\d+(?:\.\d+)*)\b", re.I)
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
COMMON = frozenset("""the and for with from that this into onto then than when what which each step steps plan run
make add fix test tests check update write read build its their them they any all are was were has have had not
but use used using new old one two first next last""".split())
SHARE = 2                     # content words two steps share before one bears on the other


def _path(home, sid):
    return os.path.join(relay._dir(home, sid), "plan.json")


def load(home, sid):
    return relay._read_json(_path(home, sid)) if sid else {}


def words(text):
    return {w.lower() for w in WORD.findall(str(text or ""))} - COMMON


def bears(a, b):
    return len(words(a) & words(b)) >= SHARE


SIBLING_STOP = frozenset("phi session sessions check checks step steps p4 plugin plugins".split())


def addr(root, i):
    return f"{root}.{i}" if root else str(i)


def root_of(home, s):
    """A session's parent step: the address its brief names, else the parent's open step its brief's words match
    best, else the parent's step in progress now; '' for an orchestrator or a parent with no task list. Siblings
    started in one step for different steps of the task list each get their own."""
    if s.get("rootStep") is not None:
        return str(s.get("rootStep") or "")
    parent = relay._parent(s)
    if not parent:
        return ""
    m = STEP_RE.search(str(s.get("task") or ""))
    if m:
        return m.group(1)
    pp = load(home, parent)
    current = str(pp.get("current") or "")
    mine = words(s.get("task"))

    def fit(st):                                       # shared words, then the share of the step's own words
        theirs = words((st or {}).get("content"))
        n = len(mine & theirs)
        return (n, n / len(theirs)) if theirs and n >= (min(SHARE, len(theirs)) or SHARE) else (0, 0.0)

    best, score = current, fit(step_of(pp, current))
    for st in pp.get("steps") or []:
        if st.get("status") == "completed":
            continue
        if fit(st) > score:                            # the step in progress wins a tie
            best, score = str(st.get("addr") or ""), fit(st)
    return best


def step_of(plan, a):
    for st in plan.get("steps") or []:
        if st.get("addr") == a:
            return st
    return None


def apply(plan, inp, root):
    """Apply one update_plan call. Returns the task list, the address that moved to in progress or '', and the
    revision or None."""
    steps = [dict(x) for x in plan.get("steps") or []]
    before = {x["addr"]: x.get("content", "") for x in steps}
    current = plan.get("current") or ""
    revision = None
    if isinstance(inp.get("items"), list):
        new = []
        for i, it in enumerate(inp["items"], 1):
            if isinstance(it, dict):
                new.append({"addr": addr(root, i), "content": str(it.get("content") or ""),
                            "status": str(it.get("status") or "pending")})
        if before:
            # a step is matched by its words before its address: removing step 2 moves step 3 to 2, unchanged
            after = {x["addr"]: x["content"] for x in new}
            where = {c: a for a, c in after.items()}
            old_texts = set(before.values())
            changed, removed, moved = [], [], {}
            for a, c in before.items():
                if c in where:
                    if where[c] != a:
                        moved[a] = where[c]
                elif a in after and after[a] not in old_texts:
                    changed.append(a)
                else:
                    removed.append(a)
            if changed or removed or moved:
                revision = {"changed": changed, "removed": removed, "moved": moved,
                            "was": {a: before[a] for a in changed + removed}}
        steps = new
    else:
        if inp.get("advance"):
            idx = next((k for k, x in enumerate(steps) if x["status"] == "in_progress"), None)
            if idx is not None:
                steps[idx]["status"] = "completed"
                nxt = next((k for k in range(idx + 1, len(steps)) if steps[k]["status"] == "pending"), None)
                if nxt is not None:
                    steps[nxt]["status"] = "in_progress"
        for n in inp.get("done") or []:
            if isinstance(n, int) and 1 <= n <= len(steps):
                steps[n - 1]["status"] = "completed"
        n = inp.get("start")
        if isinstance(n, int) and 1 <= n <= len(steps):
            for x in steps:
                if x["status"] == "in_progress":
                    x["status"] = "pending"
            steps[n - 1]["status"] = "in_progress"
    now_cur = next((x["addr"] for x in steps if x["status"] == "in_progress"), "")
    started = now_cur if now_cur and now_cur != current else ""
    out = {"root": root, "steps": steps, "current": now_cur, "version": int(plan.get("version") or 0) + 1}
    if plan.get("rootText") is not None:
        out["rootText"] = plan["rootText"]
    return out, started, revision


def summary(home, sid):
    """What the anchor keeps of a session's task list."""
    p = load(home, sid)
    if not p.get("steps"):
        return {}
    return {"root": p.get("root", ""), "current": p.get("current", ""), "version": p.get("version", 0),
            "steps": [{"addr": x["addr"], "content": x.get("content", "")[:200], "status": x.get("status", ""),
                       "tasks": [{"id": t.get("id"), "tool": t.get("tool", ""), "what": t.get("what", "")[:120],
                                  "status": t.get("status"), "heads": t.get("heads") or []} for t in x.get("tasks") or []
                                 if t.get("status") == "open"]}
                      for x in p["steps"]]}


def record(home, s, inp):
    """The work for one update_plan call, at its PostToolUse or read back from the transcript -> the
    additionalContext text, '' for none."""
    sid = s["sessionId"]
    old = load(home, sid)
    root = old.get("root") if old.get("steps") else root_of(home, s)
    parent = relay._parent(s)
    if not old.get("steps") and parent and root:
        ps = step_of(load(home, parent), root)
        old["rootText"] = (ps or {}).get("content", "")
    keep = {st.get("content", ""): st.get("tasks") for st in old.get("steps") or [] if st.get("tasks")}
    at = {st.get("addr"): st.get("content", "") for st in old.get("steps") or [] if st.get("tasks")}
    olds = {st.get("content", "") for st in old.get("steps") or []}
    plan, started, revision = apply(old, inp, root or "")
    placed = set()
    news = {st.get("content", "") for st in plan.get("steps") or []}
    for st in plan.get("steps") or []:            # a task stays with its step's words, not its number
        if st.get("content", "") in keep:
            st["tasks"] = keep[st["content"]]
            placed.add(st["content"])
    for st in plan.get("steps") or []:            # a step reworded in place keeps its tasks by address
        was = at.get(st.get("addr"))
        if was and was not in placed and was not in news and st.get("content", "") not in olds:
            st["tasks"] = list(st.get("tasks") or []) + keep[was]
            placed.add(was)
    plan["loose"] = list(old.get("loose") or []) + [t for c, ts in keep.items() if c not in placed for t in ts]
    if not plan["loose"]:
        plan.pop("loose")
    relay._write_json(_path(home, sid), plan)
    s["rootStep"] = root or ""
    spath = os.path.join(relay._dir(home, sid), "session.json")
    disk = relay._read_json(spath)
    if disk and disk.get("rootStep") != s["rootStep"]:
        disk["rootStep"] = s["rootStep"]
        relay._write_json(spath, disk)
    relay.make_anchor(home, parent, _now())       # the parent's anchor, or the top level's for an orchestrator
    relay.make_anchor(home, sid, _now())
    if revision:
        relay_revision(home, s, plan, revision)
    return boundary(home, s, plan, started) if started else ""


def _now():
    import time
    return time.strftime("%Y-%m-%d %H:%M")


def _siblings(home, s):
    return relay._siblings(home, s)


def _children(home, sid):
    return {k: v for k, v in relay._sessions(home).items() if relay._parent(v) == sid and not relay.gone(home, v)}


def relay_revision(home, s, plan, rev):
    """A revised task list, told on the next message to whoever serves or uses what changed."""
    sid, title = s["sessionId"], relay._title(s)
    stamp = hashlib.sha1(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:10]
    new = {x["addr"]: x["content"] for x in plan.get("steps") or []}
    for kid, ks in _children(home, sid).items():
        r = str(ks.get("rootStep") or "")
        if r in (rev.get("moved") or {}):
            relay.warn(home, kid, f"plan:{sid}:{stamp}:moved",
                       f"your root step {r} in the task list of \"{title}\" is now numbered {rev['moved'][r]}; the "
                       f"step itself is unchanged.")
        if r in rev["removed"]:
            relay.warn(home, kid, f"plan:{sid}:{stamp}:gone",
                       f"your root step {r}, \"{relay._short(rev['was'][r], 160)}\", was removed from the task list "
                       f"of \"{title}\", your parent session. Stop before the next tool and message {sid}: "
                       f"your work may no longer be wanted.")
        elif r in rev["changed"]:
            was, now_ = relay._short(rev["was"][r], 160), relay._short(new[r], 160)
            relay.warn(home, kid, f"plan:{sid}:{stamp}:{r}",
                       f"your root step {r} in the task list of \"{title}\" was revised from \"{was}\" to "
                       f"\"{now_}\". Check whether your steps still serve it.")
    touched = rev["changed"] + rev["removed"]
    for oid, os_ in _siblings(home, s).items() if touched else []:
        cur = step_of(load(home, oid), load(home, oid).get("current") or "")
        if not cur:
            continue
        hits = [a for a in touched if bears(rev["was"][a], cur.get("content")) or bears(new.get(a, ""), cur.get("content"))]
        if hits:
            relay.warn(home, oid, f"plan:{sid}:{stamp}:across",
                       f"\"{title}\" revised its task list at {', '.join(hits)}, which share words with your step "
                       f"{cur['addr']}, \"{relay._short(cur.get('content'), 120)}\": "
                       + "; ".join(f"{a}: \"{relay._short(rev['was'][a], 100)}\" -> "
                                   f"\"{relay._short(new.get(a, 'removed'), 100)}\"" for a in hits) + ".")
    parent = relay._parent(s)
    if parent and touched:
        relay.warn(home, parent, f"plan:{sid}:{stamp}:up",
                   f"\"{title}\", started for " + (f"your step {plan['root']}" if plan.get("root") else
                                                     "a step not in your task list") + ", revised its plan: "
                   + ", ".join(f"{a} {'removed' if a in rev['removed'] else 'changed'}" for a in touched) + ".")


def boundary(home, s, plan, started):
    """What bears on the step that starts now: up, across, down, and the warnings kept for this session."""
    sid = s["sessionId"]
    step = step_of(plan, started) or {}
    text = step.get("content", "")
    lines = []
    path = os.path.join(relay._dir(home, sid), "session.json")
    with relay.locked(path) as lk:                # emptied under the lock relay.warn holds
        return _boundary(home, s, plan, started, text, lines, path, lk.held)


def _boundary(home, s, plan, started, text, lines, path, held):
    sid = s["sessionId"]
    disk = relay._read_json(path)
    if held and disk:                             # not held: the warnings wait for the next boundary or message
        lines.extend(relay.take_warnings(home, sid, disk))
    parent = relay._parent(s)
    root = plan.get("root") or ""
    if parent and root:
        pp = load(home, parent)
        ps = step_of(pp, root)
        if ps is None and pp.get("steps"):
            lines.append(f"up: your root step {root} is no longer in the parent's plan.")
        elif ps is not None:
            relayed = any(f"your root step {root} " in x for x in lines)   # a warning about the revision said it
            if plan.get("rootText") and ps.get("content") != plan.get("rootText") and not relayed:
                lines.append(f"up: the parent revised your root step {root} to \"{relay._short(ps.get('content'), 160)}\" "
                             f"since you started on it.")
            if ps.get("status") == "completed" or (pp.get("current") and pp.get("current") != root
                                                   and _after(pp.get("current"), root)):
                lines.append(f"up: the parent has moved past your root step {root}; "
                             f"it is on {pp.get('current') or 'none'}.")
    shard = relay.shard_of(disk or s)
    for oid, os_ in sorted(_siblings(home, s).items()):
        op = load(home, oid)
        cur = step_of(op, op.get("current") or "")
        if not cur:
            continue
        near = bears(text, cur.get("content")) or any(
            relay.overlap(p, x) for p in relay.paths_in(cur.get("content"), (s.get("cwd") or "")) for x in shard)
        if near:
            lines.append(f"across: \"{relay._title(os_)}\" is on {cur['addr']}, \"{relay._short(cur.get('content'), 140)}\".")
    seen = disk.setdefault("plansSeen", {})
    for kid, ks in sorted(_children(home, sid).items()):
        kp = load(home, kid)
        if not kp.get("steps") or seen.get(kid) == kp.get("version"):
            continue
        seen[kid] = kp.get("version")
        done = sum(1 for x in kp["steps"] if x.get("status") == "completed")
        lines.append(f"down: \"{relay._title(ks)}\" has {done} of {len(kp['steps'])} steps done"
                     + (f", now on {kp['current']}" if kp.get("current") else "") + ".")
    told = disk.setdefault("upTold", [])         # an up line is said once, not at every boundary after
    kept = []
    for x in lines:
        if x in kept:
            continue
        if x.startswith("up: "):
            if x in told:
                continue
            told.append(x)
        kept.append(x)
    lines = kept
    relay._write_json(path, disk)
    if not lines:
        return ""
    return (f"phi (p4-phi): step {started} starts now, \"{relay._short(text, 160)}\". What bears on it, so the step "
            f"may need revising before it runs:\n" + "\n".join(f"- {x}" for x in lines))


# --- the split advice ----------------------------------------------------------------------------------------------
#
# At a task list's first whole list and at each revision, judge() reads the open steps: a step that names a path no
# other step names and that none of judge's reasons keeps here can run as its own worker. Two or more such
# steps are named in one line; the rest stay here as sub-steps.

DEPENDS = re.compile(r"\b(after|then|once|using|uses|based on|depends? on|following|built on|with the results?|"
                     r"results? of|output of|from (?:the )?(?:step|previous|last)|step \d+)\b", re.I)
WAITS = re.compile(r"\b(wait(?:s|ing)?|until|confirm\w*|verif\w*|can go|when\b[^.]*\blands?|tell|notify|relay\w*|"
                   r"send|ask|hand (?:off|over)|report back)\b", re.I)   # a step that waits on or passes on work
QUICK_WORDS = 4               # a step of fewer content words is a quick thing, done here
LANDS = re.compile(r"^\W*(?:run\b[^,.;]*\b(?:tests?|suites?|checks?)|report|wrap)\b"
                   r"|^\W*(?:tests?|verify|check|review)\b(?!\s*#?\d)(?=[^.;:]*\b(?:own (?:work|changes?|commits?|diff|steps?)|landed|merged|committed|"
                   r"pushed|work|changes?|diff|results?|commits?|suites?|tests?|build|outcome|fix(?:es)?|it|them)\b)"
                   r"|\b(?:commit|merge|push|ship|release|land|fast-forward)\b", re.I)
# checks or lands the session's own work. A check of anything else is work, such as "Check 1: nothing hidden in
# AppData", one of the checks an orchestrator's children are for
ORCHESTRATES = re.compile(r"^\W*(?:start|kick\s*off|launch)\s+(?!writing|adding|implementing|making)"
                          r"(?:[\w'’-]+\s+){0,5}?(?:checks?|tests?|sessions?)\b"
                          r"|^\W*(?:run|re-?run)\s+(?:[\w'’-]+\s+){0,5}?(?:sessions?|acceptance\s+(?:checks?|tests?|runs?))\b", re.I)
# starts a check, test or session, which is orchestration, such as "Start ezexe's-eye acceptance check". The doer
# and the object decide: running or re-running checks or tests oneself is work for a child, such as "Re-run failed
# checks 1, 2, 6", while starting a check, test or session, and running a session or the acceptance check, which an
# acceptance session does, stay orchestration.
MANAGES = re.compile(r"\b(?:un)?(?:archiv|relay|messag|start|stop|review|check|brief|spawn|ask|tell|nudg|queu|send|"
                     r"sent|pass|hand|forward)\w*\b"
                     r"[^.;]*?\b(?:(?:child(?:ren)?|(?:sub-?)?sessions?)\b(?!\s+(?:tree|page|record|files?|json|logs?|"
                     r"state|ids?|store))"   # manages a worker: orchestration, not "check phi session tree"
                     # or a worker or a coworker, the tree's lower levels, not "the worker pool" or "worker threads"
                     r"|(?:co-?)?workers?\b(?!\s+(?:pools?|threads?|process(?:es)?|counts?|queues?|types?|config\w*|"
                     r"sizes?|limits?|scripts?|files?|modules?|code)\b))"
                     # queues, sends, passes, hands or forwards something to a session named by its id, its quoted
                     # title or its role, such as "Queue issues #19-#24 to p4-phi fixer"
                     r"|\b(?:queu|send|sent|pass|hand|forward)\w*\b[^.;]*?\b(?:to|for)\s+(?:the\s+)?"
                     r"(?:local_[\w-]+|[\"“'][^\"”']+[\"”']|(?:[\w'’-]+\s+){0,3}?(?:top|parent|orchestrator|fixer|"
                     r"tester|starter|builder|sibling|checker|owner of)(?:s|'s|’s)?\b)", re.I)
# "Hand fixes to sibling's fixers, stop duplicates" is messaging sessions, so it stays with the orchestrator
# tracks what another does: a ledger line, a step whose doer is another session, a fixer, an orchestrator or
# ezexe, or that ezexe decides, such as "Ledger: p4-phi fixer pushes #25" or "ezexe updates the Mac's plugins"
TRACKS = re.compile(r"^\W*(?:ledger|track(?:s|ing)?)\b"
                    r"|^\W*(?:[\w'-]+\s+){0,3}?(?:fixer|top session|other session|another session|parent|"
                    r"orchestrator|builder|tester|ezexe)\s+(?:will\s+|to\s+)?(?:\w+s|decides?|approves?)\b"
                    r"|\bezexe\s+(?:decides|approves|chooses|signs off|rules)\b|\bfor ezexe to\b", re.I)
# compiles, reports or tabulates the other steps' results, such as "Final six-row pass/fail table"
TABULATES = re.compile(r"^\W*(?:final\s+)?(?:[\w/-]+\s+){0,3}?(?:pass/fail\s+)?(?:table|tally|summary|scorecard)\b"
                       r"|\b(?:compil|tabulat|collat|summari[sz]|tall(?:y|ies))\w*\b[^.;]*\b(?:results?|outcomes?|"
                       r"findings|steps?|checks?)\b", re.I)


# a start the app refuses in a turn ezexe did not begin is a suggested task card in the session that asked
CARD_EACH = ("This turn was started by another session, so the app refuses `user_asked`: show each as a suggested "
             "task card, `mcp__ccd_session__start_session` with `initiation` `own_initiative`, which ezexe presses in "
             "this session, so the app's parent and p4-phi's agree. Only where the card is refused too, write it as a "
             "start request, `phi.py request \"<title>\" --brief \"<the whole brief>\"`, which the next turn ezexe "
             "begins in this session starts as this session's child. Each card goes out carrying the `model` and "
             "`effort` named beside its step, as a start does")


def judge(plan, cwd):
    """Judges the open steps. Returns those that can each run on their own, and the address and the reason of each
    step that stays."""
    steps = [st for st in plan.get("steps") or [] if st.get("status") != "completed"]
    paths = {st["addr"]: relay.paths_in(st.get("content"), cwd) for st in steps}
    free, kept = [], []
    for st in steps:
        a, text = st["addr"], st.get("content", "")
        dep = DEPENDS.search(text)
        shared = [(o["addr"], p) for o in steps if o["addr"] != a for p in paths[a]
                  if any(relay.overlap(p, q) for q in paths[o["addr"]])]
        wait = WAITS.search(text)
        if dep:
            kept.append((a, f"leans on another step, \"{dep.group(0)}\""))
        elif wait:
            kept.append((a, f"waits on or passes on other work, \"{wait.group(0)}\""))
        elif LANDS.search(text):
            kept.append((a, "checks or lands the other steps' work"))
        elif ORCHESTRATES.search(text):
            kept.append((a, "starts a check, test or session, which is orchestration"))
        elif MANAGES.search(text):
            kept.append((a, "manages a worker"))
        elif TABULATES.search(text):
            kept.append((a, "compiles or reports the other steps' results"))
        elif TRACKS.search(text):
            kept.append((a, "tracks what another session or ezexe does or decides"))
        elif shared:
            kept.append((a, f"shares {relay.show(shared[0][1], cwd)} with step {shared[0][0]}"))
        elif len(words(text)) < QUICK_WORDS:
            kept.append((a, "a quick thing"))
        elif not paths[a]:
            kept.append((a, "names no file, so it cannot be judged apart from the others"))
        else:
            free.append(st)
    waits = sum(1 for _, why in kept if why.startswith("waits on"))
    if steps and waits * 2 >= len(steps):          # a task list of waits and messages is serial as a whole
        kept += [(st["addr"], "the task list is mostly waits and messages, so serial") for st in free]
        free = []
    return free, kept


def split_advice(home, s, plan, owner_turn, cap):
    """One line naming the steps that can each run as a worker, said once per set; '' when fewer than two."""
    free, kept = judge(plan, s.get("cwd") or "")
    subs = [st for st in free if LEVELS and level_of(st.get("content")) != "session"]
    free = [st for st in free if st not in subs]   # a read or a run goes to its subagent, never a session
    if len(free) < 2:
        return ""
    path = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(path)
    told = [x for x in disk.get("splitAdvised") or [] if isinstance(x, str)]
    new = [st for st in free if st.get("content", "") not in told]
    if not new:
        return ""                                 # a step advised once is never advised again
    disk["splitAdvised"] = s["splitAdvised"] = told + [st.get("content", "") for st in new]
    relay._write_json(path, disk)
    free = new
    named = "; ".join(f"{st['addr']} \"{relay._short(st.get('content'), 90)}\"" for st in free)
    judged = ("Judged by the paths each step names and by its words: a step stays here when it names no path, shares "
              "a path with another step, leans on or waits on other work, passes work on, checks or lands work, "
              "starts a check or session, manages a worker, compiles results, tracks what another does or "
              "ezexe decides, or has fewer than four content words.")
    if cap:
        return (f"phi (p4-phi): steps {named} could each run on their own, but {cap[0].lower() + cap[1:]} "
                f"Every step stays here as a sub-step. {judged}")
    route = ("Start each now with `mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, "
             "`use_worktree: false`, on this session's branch" if owner_turn else
             CARD_EACH)
    stay = ("; ".join(f"{a}, {why}" for a, why in kept)) or "none"
    each = "; ".join(f"{st['addr']} with {level_words(st.get('content'))}" for st in free)
    sub = " ".join(f"Step {st['addr']} \"{relay._short(st.get('content'), 90)}\" "
                   f"{LEVEL_WHAT[level_of(st.get('content'))]}: it goes to the background subagent "
                   f"`p4-phi:{level_of(st.get('content'))}`, not a session." for st in subs)
    return (f"phi (p4-phi): steps {named} can each run on their own: no path another step names, nothing leaning "
            f"on another step, more than a quick thing, and each writes files. {route}; one session per step, its "
            f"brief that step's slice: the step's words, its paths and what it must leave done. Its model and "
            f"effort: {each}. {LEVEL_HOW} " + (sub + " " if sub else "")
            + f"Staying here as sub-steps: {stay}. {judged}")


# --- the orchestrator orchestrates ----------------------------------------------------------------------------
#
# A session with no parent keeps itself free for orchestration: planning, messaging and managing sessions, decisions
# with ezexe, and landing work. Each work step of its task list goes to a fresh child, not only the independent ones,
# and a serial run, work steps that lean on the step before them or share a path with it, goes to one child that does
# them in order. With delegation on, a step that only reads or only runs a command goes to a background subagent
# instead. A step that checks or lands work, such as a test-and-commit, merge, push, release or sync, waits on or
# passes on work, starts a check or session, manages a worker, compiles results or tracks what another does
# stays; top_stays gives the reason for each.

# a step that begins with one of these is read-only work of its own, a child's, such as "Verify phi's session tree
# matches the app", though WAITS matches `verif` and `confirm` anywhere. It stays only when it names a child or a
# sub-session, or checks or lands the work.
CHECK_WORK = re.compile(r"^\W*(?:re-?)?(?:check|verify|validate|audit|inspect|confirm)\w*\b", re.I)
CHILD_WORD = re.compile(r"\b(?:child(?:ren)?(?:'s|’s)?|sub-?sessions?)\b"   # or a worker, as MANAGES reads one
                        r"|\b(?:co-?)?workers?\b(?!\s+(?:pools?|threads?|process(?:es)?|counts?|queues?|types?|"
                        r"config\w*|sizes?|limits?|scripts?|files?|modules?|code)\b)", re.I)
# syncing a store is landing work: the orchestrator is the one that pushes and syncs each store
SYNCS = re.compile(r"^\W*(?:re-?)?sync(?:s|ed|ing|hronis\w+|hroniz\w+)?\b"
                   r"|\bsync(?:s|ed|ing)?\s+(?:[\w'’-]+\s+){0,3}?stores?\b|\bp4\.py\s+sync\b", re.I)


# a step whose doer is another session, or that waits on, awaits, collects or checks other sessions' or trees'
# reports and results, such as "Await reports from Puppeteer, file organization, acceptance". It stays, since a
# child cannot wait on reports addressed to its parent.
AWAITS_TOP = re.compile(r"\b(?:a?wait\w*|until|hold\w*\s+for)\b[^.;]*\b(?:reports?|sessions?|trees?|tops?|results?|"
                        r"answers?|repl(?:y|ies)|word)\b", re.I)
OTHERS = re.compile(r"\b(?:reports?|answers?|repl(?:y|ies)|word)\s+from\b"
                    r"|\b(?:sessions?|trees?|child(?:ren)?|tops?|siblings?|puppeteers?|orchestrators?|(?:co-?)?workers?)"
                    r"(?:'s|s'|’s|s’|')?\s+(?:own\s+|last\s+|final\s+)?(?:reports?|results?|answers?|repl(?:y|ies)|"
                    r"outcomes?|findings)\b", re.I)
BUILDS = re.compile(r"^\W*(?:fix|writ|add|chang|edit|implement|updat|remov|renam|creat|mak|refactor|port|rewrit|"
                    r"replac|patch|build|migrat|delet)\w*\b", re.I)
AWAITS_WHY = "waits on or checks other sessions' reports, which only this session receives"


def awaits_sessions(text):
    """True for a step that waits on, awaits, collects or checks other sessions' or trees' reports or results."""
    text = str(text or "")
    if BUILDS.match(text):                         # "Fix session report truncation" builds something: work
        return False
    return bool(AWAITS_TOP.search(text) or OTHERS.search(text))


def top_stays(text):
    """Why an orchestrator keeps a step itself, or '' for a work step that goes to a child. The one answer for
    top_groups and for phi.nudge_step, so the advice and the nudge never disagree."""
    text = str(text or "")
    if awaits_sessions(text):                      # waiting on other sessions' results wins over the check rule
        return AWAITS_WHY
    if LANDS.search(text) or SYNCS.search(text):
        return "checks or lands the work"
    if ORCHESTRATES.search(text):
        return "starts a check, test or session, which is orchestration"
    checks = CHECK_WORK.match(text)
    if CHILD_WORD.search(text) if checks else MANAGES.search(text):
        return "manages a worker, which is orchestration"
    if TABULATES.search(text):
        return "compiles or reports the other steps' results"
    if TRACKS.search(text):
        return "tracks what another session or ezexe does or decides"
    wait = WAITS.search(text)
    if wait and not checks:
        return f"waits on or passes on work, \"{wait.group(0)}\""
    return ""


def top_groups(plan, cwd):
    """The open steps of an orchestrator's task list, split into the serial runs of work steps, each run one
    child's to do in order, and the address and the reason of each step that stays."""
    steps = [st for st in plan.get("steps") or [] if st.get("status") != "completed"]
    groups, kept, run = [], [], []
    for st in steps:
        text = st.get("content", "")
        why = top_stays(text)
        if why:
            kept.append((st["addr"], why))
        else:
            mine = relay.paths_in(text, cwd)
            serial = run and (DEPENDS.search(text) or any(relay.overlap(p, q) for p in mine for o in run
                                                          for q in relay.paths_in(o.get("content"), cwd)))
            if run and not serial:
                groups.append(run)
                run = []
            run.append(st)
            continue
        if run:
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    return groups, kept


# --- delegation: where a step runs --------------------------------------------------------------------------------
#
# A step that only reads or searches is a background subagent's, `p4-phi:sweep`; one that only runs a command is
# `p4-phi:runner`'s; the rest is a worker's. sub-agents.md says "Background subagents run concurrently while
# you continue working", and plugins/components.md, under "Agents", names a plugin's agent `<plugin>:<name>`.

READS = re.compile(r"^\W*(?:find|search|look\s+(?:for|up|at|into|through)|read|grep|list|locate|survey|scan|map|"
                   r"inventory|explore|trace|identify|count|collect|gather|sweep)\b", re.I)
RUNS = re.compile(r"^\W*(?:run|re-?run|execute)\b", re.I)
WRITES = re.compile(r"\b(?:fix\w*|writ\w*|add\w*|chang\w*|edit\w*|implement\w*|updat\w*|remov\w*|renam\w*|creat\w*|"
                    r"mak\w+|mov\w+|commit\w*|refactor\w*|port\w*|delet\w*|migrat\w*|rewrit\w*|replac\w*|patch\w*|"
                    r"push\w*|merg\w*|land\w*|releas\w*|ship\w*|install\w*)\b", re.I)
LEVELS = True                 # phi.project_conf sets it from p4.json phi.levels
LEVEL_WHAT = {"sweep": "only reads or searches", "runner": "only runs a command"}


def level_of(text):
    """'sweep' for a step that only reads or searches, 'runner' for one that only runs a command, else 'session'."""
    text = str(text or "")
    if WRITES.search(text):
        return "session"
    if READS.search(text):
        return "sweep"
    if RUNS.search(text):
        return "runner"
    return "session"


# --- the model and effort a worker is started with ---------------------------------------------------------
#
# The three background subagents carry a model and an effort in their files, and every start call p4-phi hands out
# carries an `effort`, and a `model` unless it keeps the parent session's. `mcp__ccd_session__start_session` takes
# `model`, the same family or cheaper than the caller's, and `effort`, at or below the caller's, both for a `fresh`
# start only, as its schema says. The kind of a step picks its entry of CHILD_LEVELS, which p4.json's
# phi.child_levels can set; LEVEL_HOW says the rule to the session that makes the call.

CHILD_LEVELS = {"static": {"model": "claude-sonnet-5-5", "effort": "medium"},
                "build": {"model": "inherit", "effort": "high"},
                "design": {"model": "inherit", "effort": "high"}}      # p4.json phi.child_levels sets each kind
CHILD_KINDS = {"static": "static or mechanical work", "build": "a build that changes behaviour",
               "design": "a design or review step"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DESIGNS = re.compile(r"^\W*(?:re-?)?(?:design|review|architect|audit|specif|spec\b|propos|investigat|decid|"
                     r"evaluat|assess|analy[sz]|research|plan\b)\w*", re.I)
CODE = re.compile(r"\.(?:py|js|jsx|ts|tsx|rs|go|c|h|cc|cpp|cs|java|kt|rb|sh|ps1|sql|toml|ya?ml)\b(?!\.)"
                  r"|\b(?:scripts?|src|hooks?|lib)/|\b(?:hook|script|function|module|class|api|test suite|"
                  r"behaviou?r)s?\b|\b(?:fix|implement|build|refactor|port|migrat)\w*\b", re.I)
STATIC = re.compile(r"\b(?:docs?|dox|documentation|readme|changelog|pages?|html|css|markdown|typos?|wording|"
                    r"comments?|renam\w*|version bump|bump\w*|format\w*|static|mechanical|copy\w*|mov\w+)\b"
                    r"|\.(?:md|html|css|txt|svg)\b", re.I)
# a line that is `Model: <id>` or `Effort: <level>` and nothing more: a sentence that begins with either word, such
# as "Model: ranker.pt is rebuilt", names no choice
SAID_LEVEL = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?(model|effort)(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*`?"
                        r"([A-Za-z0-9][\w.-]*?)`?[ \t.]*$")
MODEL_ID = re.compile(r"^(?:claude-[a-z0-9][a-z0-9.-]*|fable|mythos|opus|sonnet|haiku|inherit)$", re.I)
LEVEL_LINE = re.compile(r"(?im)^[ \t>*-]*Model and effort:")
# the one line level_line writes and LEVEL_CARD asks for, `Model and effort: <model> at <effort> effort`, with or
# without a reason after the effort; the parent session's own model is said in words
ONE_LEVEL = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?Model and effort(?:\*\*)?:[ \t]*`?"
                       r"(the parent session's own model|[A-Za-z0-9][\w.-]*?)`?[ \t]+at[ \t]+`?([a-z]+)`?[ \t]+effort\b")


def child_levels(conf):
    """CHILD_LEVELS with a project's `phi.child_levels` laid over it: a kind's `model` and `effort`, each kept
    only when it is a model id or one of the app's efforts."""
    out = {k: dict(v) for k, v in CHILD_LEVELS_DEFAULT.items()}
    for kind, given in (conf.items() if isinstance(conf, dict) else ()):
        if kind in out and isinstance(given, dict):
            if isinstance(given.get("model"), str) and given["model"].strip():
                out[kind]["model"] = given["model"].strip()
            if given.get("effort") in EFFORTS:
                out[kind]["effort"] = given["effort"]
    return out


CHILD_LEVELS_DEFAULT = {k: dict(v) for k, v in CHILD_LEVELS.items()}


def child_kind(text):
    """'design' for a step that designs or reviews, 'static' for docs pages, a rename, a version bump or other
    mechanical work that names no code, else 'build'."""
    text = str(text or "")
    if DESIGNS.search(text):
        return "design"
    if STATIC.search(text) and not CODE.search(text):
        return "static"
    return "build"


def said_level(brief):
    """The `model` and `effort` a brief names itself, in the one line `Model and effort: <model> at <effort> effort`
    or on lines `Model: <id>` and `Effort: <level>`: the parent session's own choice, which wins over its kind's."""
    out = {}
    said = []
    for model, effort in ONE_LEVEL.findall(str(brief or "")):
        said += [("model", "inherit" if model.lower().startswith("the parent") else model), ("effort", effort)]
    for key, value in said + SAID_LEVEL.findall(str(brief or "")):
        key = key.lower()
        if key == "effort" and value.lower() not in EFFORTS:
            continue
        if key == "model" and not MODEL_ID.match(value):
            continue                               # "Model: ranker.pt is rebuilt" names no model to start with
        out.setdefault(key, value.lower())
    return out


def child_level(text, brief=""):
    """{"model", "effort", "kind"} a worker is started with for a step or a brief: its kind's entry of
    CHILD_LEVELS, with what the brief itself names laid over it. `model` is 'inherit' for the parent session's own."""
    kind = child_kind(text if str(text or "").strip() else brief)
    out = {**CHILD_LEVELS.get(kind, CHILD_LEVELS_DEFAULT[kind]), "kind": kind}
    said = said_level(brief or text)
    if said:
        out.update(said, said=True)
    return out


def level_keys(level):
    """The `model` and `effort` keys of a start call: `model` is left out to inherit the parent session's, which is
    how the app's tool takes it, so a call always carries `effort` and never neither."""
    out = {"effort": level["effort"]}
    if str(level.get("model") or "inherit").lower() != "inherit":
        out["model"] = level["model"]
    return out


def level_line(level):
    """The one line a brief says its model and effort in, so the choice is visible to the child and its reader."""
    model = ("the parent session's own model" if str(level.get("model") or "inherit").lower() == "inherit"
             else level["model"])
    why = "named by the parent session" if level.get("said") else f"since this is {CHILD_KINDS[level['kind']]}"
    return f"Model and effort: {model} at {level['effort']} effort, {why}."


def with_level(call, text=""):
    """A start call with the `model` and `effort` its brief's kind of work gets, and the brief saying them in one
    line. A fork takes neither: the app gives a fork its parent session's."""
    if call.get("context") == "fork":
        return call
    brief = str(call.get("prompt") or "")
    level = child_level(text or (str(call.get("title") or "") + "\n" + brief), brief)
    out = {**call, **level_keys(level)}
    if not LEVEL_LINE.search(brief):
        out["prompt"] = level_said(brief, level)
    return out


MARKED = re.compile(r"\n\nphi start request req-[0-9a-f]{10} for \S+\s*$")


def level_said(brief, level):
    """`brief` with its model-and-effort line, before a start request's marker so the marker stays its last line."""
    m = MARKED.search(brief)
    if m:
        return brief[:m.start()] + "\n\n" + level_line(level) + brief[m.start():]
    return brief + "\n\n" + level_line(level)


def level_words(text):
    """The words a line of advice names a step's model and effort in."""
    level = child_level(text)
    model = ("no `model`, so it inherits this session's" if str(level["model"]).lower() == "inherit"
             else f"`model` `{level['model']}`")
    return f"{model}, `effort` `{level['effort']}`"


LEVEL_CARD = ("It carries the `model` and `effort` a start of its kind of work carries, said in one line of its brief, "
              "`Model and effort: <model> at <effort> effort`.")
LEVEL_HOW = ("Each call carries the `model` and `effort` named beside its steps, which the kind of work decides: by "
             "default static or mechanical work runs on a cheaper model at medium effort, and a build that changes "
             "behaviour or a design or review step on this session's own model at high effort. An effort above this "
             "session's own is not accepted, so pass this session's own then. Each brief says them in one line, "
             "`Model and effort: <model> at <effort> effort`; to choose otherwise, pass another `model` or `effort` "
             "and say so in that line.")


def top_advice(home, s, plan, owner_turn, cap, levels=None):
    """The orchestrator's line: each work step, or serial run, to one fresh child, and with delegation on each
    step that only reads or only runs a command to a background subagent; said once per set. '' when no work step
    is new."""
    groups, kept = top_groups(plan, s.get("cwd") or "")
    path = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(path)
    told = [x for x in disk.get("splitAdvised") or [] if isinstance(x, str)]
    new = [g for g in groups if any(st.get("content", "") not in told for st in g)]
    if not new:
        return ""
    disk["splitAdvised"] = s["splitAdvised"] = told + [st.get("content", "") for g in new for st in g
                                                        if st.get("content", "") not in told]
    relay._write_json(path, disk)

    levels = LEVELS if levels is None else levels

    def level(g):
        return level_of(g[0].get("content")) if levels and len(g) == 1 else "session"

    def child(g):
        if level(g) != "session":
            return (f"step {g[0]['addr']} \"{relay._short(g[0].get('content'), 90)}\", which {LEVEL_WHAT[level(g)]}: "
                    f"a background subagent, `p4-phi:{level(g)}`, not a session")
        kinds = [child_kind(st.get("content")) for st in g]      # a run takes the model and effort of its hardest step
        hardest = next(st for k in ("design", "build", "static") for st, kd in zip(g, kinds) if kd == k)
        how = level_words(hardest.get("content"))
        if len(g) == 1:
            return f"step {g[0]['addr']} \"{relay._short(g[0].get('content'), 90)}\", with {how}"
        return (f"steps {', '.join(st['addr'] for st in g)} in order, as one child: "
                + ", ".join(f"\"{relay._short(st.get('content'), 70)}\"" for st in g) + f", with {how}")
    named = "; ".join(f"({chr(97 + k)}) {child(g)}" for k, g in enumerate(new[:26]))
    head = ("phi (p4-phi): this is the orchestrator of its tree, so it keeps itself free for orchestration: "
            "planning, messaging and managing sessions, decisions with ezexe, and landing the work, meaning merge "
            "and push.")
    stay = ("; ".join(f"{a}, {why}" for a, why in kept)) or "none"
    subs = [g for g in new[:26] if level(g) != "session"]
    agents = "" if subs else ""                    # the subagent's name beside its step says enough
    if cap:
        return (f"{head} Its work steps would each go to a child: {named}. But {cap[0].lower() + cap[1:]} "
                f"Staying here meanwhile: every step.{agents}")
    if subs and len(subs) == len(new[:26]):
        return f"{head} Its work steps need no session: {named}.{agents} Staying here: {stay}."
    route = ("Start each now with `mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, "
             "`use_worktree: false`, on this session's branch" if owner_turn else
             CARD_EACH)
    return (f"{head} Hand its work steps to workers, split by the files they write: steps that share a file go "
            f"to one child as a serial run, and steps with disjoint files each get a child: {named}. {route}. Each "
            f"brief is its steps' words, a line `Files: <the paths it may write>`, what they must leave done, and "
            f"\"report when done\", so the child "
            f"leaves its outcome here as a replaces: note and counts as archived when it finishes. {LEVEL_HOW}"
            f"{agents} Staying "
            f"here: {stay}.")


# --- subagents as tasks of the step that launched them -------------------------------------------------------------
#
# A subagent's hook input carries the launching session's `session_id` and its own `agent_id`, as the hooks reference
# documents for every hook inside a subagent. At the Agent call it is a pending task under the step in progress,
# given that step's slice in its prompt; its first tool call binds its id to the task; each later call is warned of
# what changed beside the launching session since; its stop attaches its result. As a task of the step, the anchor
# carries it to the parent like any background task.

PENDING_S = 3600              # a launch no tool call bound within this long is dropped


def _agent(p, agent_id):
    return next((t for _, t in _tasks(p) if t.get("id") == agent_id), None)


def agent_launch(home, s, tool_use_id, inp):
    """The Agent call, before it runs: a pending task under the step in progress -> the text for its prompt."""
    import time as _t
    sid = s["sessionId"]
    p = load(home, sid)
    st = step_of(p, p.get("current") or "") if p.get("steps") else None
    parent = relay._parent(s)
    seen = int(relay._read_json(relay.anchor_path(home, parent)).get("version") or 0)
    prompt = str(inp.get("prompt") or "")
    pend = {k: v for k, v in (p.get("agentsPending") or {}).items()
            if _t.time() - int(v.get("epoch") or 0) < PENDING_S}
    pend[str(tool_use_id or len(pend))] = {"step": (st or {}).get("addr", ""), "stepText": (st or {}).get("content", ""),
                                           "anchorSeen": seen, "epoch": int(_t.time()),
                                           "what": relay._short(inp.get("description") or prompt, 200)}
    p["agentsPending"] = pend
    relay._write_json(_path(home, sid), p)
    if not st:
        return ""
    head = (f"phi (p4-phi): you are a subagent of \"{relay._title(s)}\", launched for its step {st['addr']}, "
            f"\"{relay._short(st.get('content'), 200)}\". Keep to that step; what you find goes back in your result.")
    piece = relay.slice_text(home, {"sessionId": "agent", "spawnedFrom": {"sessionId": parent}, "task": prompt,
                                    "cwd": s.get("cwd") or ""}) if parent else ""
    return "\n".join(x for x in (head, piece) if x)


def agent_bind(home, s, agent_id):
    """A subagent's tool call: its id bound to the oldest pending launch -> True when newly bound."""
    import time as _t
    sid = s["sessionId"]
    p = load(home, sid)
    if not agent_id or _agent(p, agent_id):
        return False
    pend = p.get("agentsPending") or {}
    key = min(pend, key=lambda k: int(pend[k].get("epoch") or 0)) if pend else None
    got = pend.pop(key) if key else {"step": p.get("current") or "", "anchorSeen": 0, "what": "a subagent"}
    if not pend:
        p.pop("agentsPending", None)
    epoch = int(got.get("epoch") or _t.time())
    task = {"id": agent_id, "tool": "Agent", "agent": True, "what": got.get("what", ""), "status": "open",
            "anchorSeen": int(got.get("anchorSeen") or 0), "stepText": got.get("stepText", ""), "heads": [],
            "paths": [], "epoch": epoch, "at": _t.strftime("%Y-%m-%d %H:%M", _t.localtime(epoch))}
    st = step_of(p, got.get("step") or "")
    if st is None:
        p.setdefault("loose", []).append(task)
    else:
        st.setdefault("tasks", []).append(task)
    relay._write_json(_path(home, sid), p)
    parent = relay._parent(s)                     # the anchors carry it, and the parent is told its id
    relay.make_anchor(home, parent, _now())
    relay.make_anchor(home, sid, _now())
    if parent:
        where = f"its step {st['addr']}" if st else "no step of its task list"
        relay.warn(home, parent, f"agent:{sid}:{agent_id}",
                   f"down: \"{relay._title(s)}\" launched subagent {agent_id} for {where}"
                   + (f", \"{relay._short(task['what'], 120)}\"" if task.get("what") else "") + ".")
    return True


def agent_warn(home, s, agent_id):
    """A subagent's next tool call: what changed beside the launching session since it was launched or last told,
    and its step revised or gone; '' when nothing did."""
    sid = s["sessionId"]
    p = load(home, sid)
    t = _agent(p, agent_id)
    if not t or t.get("status") != "open":
        return ""
    anchor = relay._read_json(relay.anchor_path(home, relay._parent(s)))
    v = int(anchor.get("version") or 0)
    lines = []
    seen = int(t.get("anchorSeen") or 0)
    given = t.setdefault("marksGiven", [])
    if v > seen:
        for nid, at in sorted((anchor.get("changedAt") or {}).items()):
            if nid == sid or int(at or 0) <= seen:
                continue
            n = (anchor.get("nodes") or {}).get(nid) or {}
            new = [m for m in n.get("marks") or [] if relay.mark_key(nid, m) not in given]
            given.extend(relay.mark_key(nid, m) for m in new)    # each note told once, however often its session changes
            marks = [m.get("claim") for m in new][-2:]
            files = [] if n.get("marks") else (n.get("files") or [])[:4]
            said = "; ".join(relay._short(x, 200) for x in marks) or (
                "changed " + ", ".join(relay.show(f, s.get("cwd") or "") for f in files) if files else "")
            if said:
                lines.append(f"\"{n.get('title') or nid}\": {said}")
    step = next((st for st in p.get("steps") or [] for x in st.get("tasks") or [] if x is t), None)
    if t.get("stepText") and step is None:
        lines.append("the step you were launched for is no longer in the launching session's task list")
    elif step is not None and t.get("stepText") and step.get("content") != t["stepText"]:
        lines.append(f"the step you were launched for now reads \"{relay._short(step.get('content'), 160)}\"")
        t["stepText"] = step.get("content")
    if v > seen or lines:
        t["anchorSeen"] = v
        relay._write_json(_path(home, sid), p)
    if not lines:
        return ""
    return ("phi (p4-phi): since you were launched, beside the session that launched you:\n"
            + "\n".join(f"- {x}" for x in lines[:6]) + "\nCheck that your work still holds before going on.")


def agent_wrote(home, sid, agent_id, paths):
    """A subagent wrote files: its task keeps them, so the ledger names it a level miss -> True when one is new."""
    p = load(home, sid)
    t = _agent(p, agent_id)
    if not t:
        return False
    had = list(t.get("wrote") or [])
    new = [x for x in paths if x not in had]
    if not new:
        return False
    t["wrote"] = had + new
    relay._write_json(_path(home, sid), p)
    return True


def agent_stop(home, s, agent_id, result):
    """The subagent stopped: its task closed with its result -> True when a task was closed."""
    sid = s["sessionId"]
    agent_bind(home, s, agent_id)                 # one that made no tool call is bound now
    p = load(home, sid)
    t = _agent(p, agent_id)
    if not t or t.get("status") != "open":
        return False
    t["status"], t["result"] = "completed", relay._short(str(result or ""), 300)
    relay._write_json(_path(home, sid), p)
    return True


def _after(a, b):
    """True when address a comes after address b in the parent's task list."""
    def key(x):
        return [int(p) for p in str(x).split(".") if p.isdigit()]
    return key(a) > key(b)


def slice_for(home, s):
    """A fresh child's parent step and its slice of the parent's task list: the steps around it, and the siblings'
    steps in progress that share its words. '' when the child has no parent step."""
    root = root_of(home, s)
    parent = relay._parent(s)
    if not root or not parent:
        return ""
    pp = load(home, parent)
    steps = pp.get("steps") or []
    at = next((k for k, x in enumerate(steps) if x["addr"] == root), None)
    if at is None:
        return f"phi (p4-phi): this session is for step {root} of its parent's task list, which no longer holds it."
    around = steps[max(0, at - 1):at + 2]
    out = [f"phi (p4-phi): this session is for step {root} of its parent's task list, "
           f"\"{relay._short(steps[at]['content'], 200)}\"."
           " Its own steps are numbered under it: " + addr(root, 1) + ", " + addr(root, 2) + ", and so on.",
           "The parent's task list around it:"]
    out += [f"- {x['addr']} [{x.get('status')}] {relay._short(x.get('content'), 140)}" for x in around]
    near = []
    for oid, os_ in sorted(_siblings(home, s).items()):
        op = load(home, oid)
        cur = step_of(op, op.get("current") or "")
        if cur and bears(steps[at]["content"], cur.get("content")):
            near.append(f"- \"{relay._title(os_)}\" is on {cur['addr']}, \"{relay._short(cur.get('content'), 140)}\"")
    if near:
        out += ["Sibling steps in progress that share its words:"] + near
    return "\n".join(out)


# --- a turn is a delta too ---------------------------------------------------------------------------------------------
#
# A turn's report can change a child's or a sibling's step as much as a note or a task-list revision can, so at Stop
# its words are matched against their open steps and delivered to the sessions they bear on.

SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# a report that quotes what p4-phi told the session would be matched and delivered again, growing each round, so
# p4-phi's own lines, and any sentence quoting them, are taken out of a report before it is matched
OWN_LINE = re.compile(r"^\s*(?:[-*>`\"]\s*)*(?:phi \(p4-phi\)|p4-phi[ :(]|p4-temportal:|(?:up|across|down):)", re.I)
OWN_WORDS = ("phi (p4-phi)", "words bear on your open step", "check whether those steps still hold",
             "stop before any tool runs")


# a session link names a session, not a step: the link and its label are never matched against step words. The app
# tells sessions to write a session link as `[title](#local_<id>)`, so that form goes with its label too, and so do
# bare session ids and the paths of sessions' pages under phi/sessions/.
SESSION_LINK = re.compile(r"\[[^\]\n]*\]\(\s*(?:claude://[^)\s]*|#?local_[0-9A-Za-z][\w-]*"
                          r"|#?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{4,})\s*\)|<?claude://[^\s)>]+>?", re.I)
SESSION_PAGE = re.compile(r"`?[^\s`]*phi[\\/]+sessions[\\/][^\s`]*`?", re.I)
SESSION_ID = re.compile(r"\b(?:local_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
                        r"|\blocal_[0-9a-f][0-9a-f-]{5,}\b", re.I)
# A session reciting the rules it was given at its start says nothing about another session's step.
STARTUP = re.compile(r"\b(?:standing rules?|start-?up rules?|rules? from (?:the )?memor(?:y|ies)|memory index|"
                     r"at (?:its|their|session|the session's) start(?:-?up)?\b|session start)", re.I)
RULE_LINE = re.compile(r"^\s*[-*]\s*(?:built-in,\s*)?([a-z0-9][a-z0-9']*(?:-[a-z0-9']+)*):\s")
BUILT_IN_LINE = re.compile(r"^\s*[-*]\s*built-in,\s*[a-z0-9'-]+:\s")
BUILT_INS = ()                # phi.py sets it to the names of the rules it carries itself
MEMORY_RULES = None           # phi.py sets it to phi.memory_rules: the store's feedback and user memories by name


def rule_names(home=""):
    """The names of the rules a session starts with: p4-phi's built-in ones, and the store's feedback and user
    memories, read from the memory folder, so the list stays true as memories change."""
    names = set(BUILT_INS)
    if home and MEMORY_RULES:
        names.update(name for name, _ in MEMORY_RULES(home))
    return {n.lower() for n in names if n}


def recites(sentence, names):
    """True for a sentence that recites the startup rules: it says so, or it names one by its slug."""
    if STARTUP.search(sentence):
        return True
    low = sentence.lower()
    return any("-" in n and re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", low) for n in names)


def rule_bullet(line, names):
    """True for a bullet that is one of the rules: `- built-in, <name>: ...` or `- <a rule's name>: ...`."""
    if BUILT_IN_LINE.match(line):
        return True
    m = RULE_LINE.match(line)
    return bool(m and m.group(1).lower() in names)


def links_removed(text):
    """`text` without session links, a markdown link's label with it, sessions' pages and bare session ids."""
    return SESSION_ID.sub(" ", SESSION_PAGE.sub(" ", SESSION_LINK.sub(" ", str(text or ""))))


def own_removed(text, home=""):
    """`text` without p4-phi's own lines, the sentences that quote them, session links with their labels, session
    ids and pages, the bullets that are startup rules and the sentences that recite them."""
    names = rule_names(home)
    keep = [ln for ln in links_removed(text).splitlines() if not OWN_LINE.match(ln) and not rule_bullet(ln, names)]
    sents = [x for x in SENTENCE.split("\n".join(keep)) if x.strip()]
    return "\n".join(x for x in sents if not any(w in x.lower() for w in OWN_WORDS) and not recites(x, names))


# the words every report uses about the tree never count toward a delivered turn's match, in either direction
RELAY_COMMON = frozenset("""phi p4 session sessions local top tops parent parents child children sibling siblings rule
rules memory memories page pages link links archive archived archives report reports reported done turn
turns""".split())


def relay_bears(a, b):
    """bears() for a turn delivered down to a child: the tree's own vocabulary never counts."""
    return len((words(a) & words(b)) - RELAY_COMMON) >= SHARE


def relay_bears_sibling(a, b):
    """A sibling's turn bears on a step only past the shared vocabulary of the tree: more than two words in common
    outside SIBLING_STOP and RELAY_COMMON, so {phi, session} alone never delivers a sibling's report."""
    return len((words(a) & words(b)) - SIBLING_STOP - RELAY_COMMON) > 2
ADDR_RE = re.compile(r"\b(?:step\s+)?(\d+(?:\.\d+)+|(?<=step )\d+)\b", re.I)


def open_steps(home, sid):
    """The steps of a session's task list not yet completed, each as stored, with its background tasks of every
    status."""
    p = load(home, sid)
    return [x for x in p.get("steps") or [] if x.get("status") != "completed"]


FENCE = re.compile(r"```.*?(?:```|$)", re.S)
DRAWN = re.compile(r"[\u2500-\u257f]")             # box-drawing characters: a tree or table drawn in a report


def prose(text, home=""):
    """`text` without fenced code blocks, drawn lines, session links, ids and pages, and the bullets that are
    startup rules: their addresses and words are no claim about a step."""
    text = links_removed(FENCE.sub("\n", str(text or "")))
    names = rule_names(home)
    return "\n".join(ln for ln in text.splitlines() if not DRAWN.search(ln) and not rule_bullet(ln, names))


def matches(text, steps, shard, base, loose=True, bear=None, home=""):
    """Each step that `text` bears on, with the sentences of `text` that bear on it: a step is matched by its
    address, by a path among the session's owned paths, or by sharing SHARE content words with a sentence. Code blocks
    and drawn trees are left out."""
    text = prose(text, home)
    bear = bear or bears
    names = rule_names(home)
    sents = [x.strip() for x in SENTENCE.split(str(text or "")) if x.strip() and not recites(x, names)]
    named = set(ADDR_RE.findall(str(text or "")))
    out = []
    for st in steps:
        hit = []
        for x in sents:
            if st["addr"] in set(ADDR_RE.findall(x)) or (loose and bear(x, st.get("content"))) or any(
                    relay.overlap(p, sh) for p in relay.paths_in(x, base) for sh in shard):
                hit.append(x)
            for t in st.get("tasks") or []:
                if loose and t.get("status") == "open" and bear(x, t.get("what")) and x not in hit:
                    hit.append(x)
        if st["addr"] in named and not hit:
            hit = [x for x in sents if st["addr"] in x][:2]
        if hit:
            out.append((st, hit[:3]))
    return out


# A parent's report that shares words with a child's step is delivered to the child, but the parent is nagged that it
# sent nothing only when the sentence changes the step: a progress report that names the child's work is no change.
CHANGES = re.compile(r"\b(?:void\w*|replac\w*|deprecat\w*|supersed\w*|no longer|instead|drop(?:s|ped)?|"
                     r"remov\w*|cancel\w*|revis\w*|renam\w*|obsolete|wrong|broke\w*|stop(?:s|ped)?|undo\w*|"
                     r"revert\w*|redo|rework\w*)\b", re.I)


def turn_relay(home, s, row, calls):
    """At Stop: the turn's report and step in progress, matched against the open steps of this session's children,
    down, and of its siblings, across. Each match is delivered with the turn's own words quoted. Returns the
    children a match reached that the turn sent no SendMessage to, each as its id and the addresses, for the parent's
    next message."""
    sid, title = s["sessionId"], relay._title(s)
    report = own_removed(row.get("report"), home)
    mine = load(home, sid)
    step = "\n".join(f"{x['addr']} {x.get('content', '')}" for x in mine.get("steps") or []
                     if x.get("status") == "in_progress")
    if not report.strip():
        return []
    path = os.path.join(relay._dir(home, sid), "session.json")
    disk = relay._read_json(path)
    if step and step == disk.get("stepRelayed"):
        step = ""                                 # an unchanged step is matched once, not again every turn
    elif step:
        disk["stepRelayed"] = s["stepRelayed"] = step
        relay._write_json(path, disk)
    text = report + ("\n" + step if step else "")
    sent = set()
    for c in calls or []:
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        name = str(c.get("name") or "")
        if name.endswith("SendMessage") and inp.get("to"):
            sent.add(str(inp["to"]))
        elif name.endswith("send_message") and (inp.get("session_id") or inp.get("to")):
            sent.add(str(inp.get("session_id") or inp.get("to")))
    stamp = hashlib.sha1((sid + str(row.get("id") or "") + report[:200]).encode()).hexdigest()[:10]
    unsent = []
    targets = [(k, "down") for k in _children(home, sid)] + [(k, "across") for k in _siblings(home, s)]
    for oid, way in targets:
        os_ = relay._session(home, oid)
        if os_.get("stale"):
            continue
        got = matches(text, open_steps(home, oid), relay.shard_of(os_), os_.get("cwd") or s.get("cwd") or "",
                      bear=relay_bears if way == "down" else relay_bears_sibling, home=home)
        if not got:
            continue
        lines = [f"{st['addr']} \"{relay._short(st.get('content'), 100)}\": " +
                 " ".join(f"\"{relay._short(q, 220)}\"" for q in quotes) for st, quotes in got]
        who = "your parent session" if way == "down" else "a session beside you"
        relay.warn(home, oid, f"turn:{sid}:{stamp}",
                   f"\"{title}\", {who}, ended a turn whose words bear on your open steps: " + "; ".join(lines)
                   + ". Check whether those steps still hold.")
        strict = {st["addr"] for st, _ in matches(text, open_steps(home, oid), relay.shard_of(os_),
                                                  os_.get("cwd") or s.get("cwd") or "", loose=False, home=home)}
        named = [st["addr"] for st, quotes in got
                 if st["addr"] in strict or any(CHANGES.search(q) for q in quotes)]
        if way == "down" and named and oid not in sent and ("local_" + oid.removeprefix("local_")) not in sent:
            unsent.append((oid, named))   # a step named by address or path, or words that change it, not progress
    parent = relay._parent(s)
    ask = waiting_on(report)
    if parent and ask:
        relay.warn(home, parent, f"wait:{sid}:{stamp}",
                   f"\"{title}\", your worker, ended its turn on a question: \"{relay._short(ask, 240)}\". "
                   f"It names no matter of ezexe's authority, so answer it with SendMessage to {sid} "
                   f"from what the session tree knows, rather than leaving it waiting.")
    return unsent


AUTHORITY = re.compile(r"\b(push|force|merge|publish|post|deploy|release|credential|password|token|secret|api key|"
                       r"permission|sign[ -]?in|log[ -]?in|spend|pay|purchase|billing|delete|destroy|drop|"
                       r"irreversible|cannot be undone|restart|install)\w*", re.I)


def waiting_on(report):
    """The question a turn's report ends on, when it is not a matter of ezexe's authority; '' otherwise."""
    tail = str(report or "").strip()[-600:]
    qs = [q.strip() for q in re.findall(r"[^.!?\n]*\?", tail) if len(q.strip()) > 8]
    if not qs or not tail.rstrip().endswith("?") and tail.rfind("?") < len(tail) - 200:
        return ""
    q = qs[-1]
    return "" if AUTHORITY.search(q) else q


# --- a turn that ends with open steps the session tree can settle ----------------------------------------------------
#
# A session that ends its turn with steps of its task list still open, none of them waiting on ezexe's authority,
# would cost ezexe a message just to restart agreed work, so at Stop it is sent back with its next open step, at most
# KEEP_GOING_MAX times a turn.

KEEP_GOING_MAX = 2             # times one turn is sent back, under hooks.md's 8-consecutive-continuation cap
WAITS_ON_OWNER = re.compile(r"\b(?:wait\w*|blocked|need\w*|until)\b[^.\n]{0,80}\b(?:user|owner|boss|ezexe|your|you)\b|"
                            r"\b(?:your|ezexe's|the (?:user|owner)'s?) (?:go|ok|okay|approval|answer|decision|sign-?off)\b", re.I)


AWAITS = re.compile(r"\b(?:a?wait\w*|collect\w*|until|hold\w*\s+for)\b[^.;]*\b(?:reports?|sessions?|trees?|tops?|"
                    r"results?|finish\w*|done|land\w*|answers?|repl(?:y|ies)|word)\b", re.I)
# a step that waits on other sessions' reports: nothing can be done on it until one arrives, and the arrival starts
# the next turn


def waiting_step(home, sid):
    """The next open step of a session's task list when it waits on other sessions' reports, else None."""
    steps = [x for x in load(home, sid).get("steps") or [] if x.get("status") != "completed"]
    if not steps:
        return None
    nxt = next((x for x in steps if x.get("status") == "in_progress"), steps[0])
    return nxt if awaits_sessions(nxt.get("content")) or AWAITS.search(str(nxt.get("content") or "")) else None


def keep_going(home, s, report, calls, turn_id, active=False, waits=(), background=()):
    """The Stop hook's reason to send the session back to its next open step; '' when the turn may end: no open
    step, the turn wrapped up or asked ezexe a matter of authority, the next step is one, the Stop input lists a
    background task still running, since its notice starts the next turn, this turn was sent back KEEP_GOING_MAX times already, or the
    next step waits on other sessions' reports while `waits` names sessions not yet complete."""
    p = load(home, s["sessionId"])
    steps = [x for x in p.get("steps") or [] if x.get("status") != "completed"]
    if not steps:
        return ""
    names = {str(c.get("name") or "") for c in calls or [] if isinstance(c, dict)}
    if "mcp__ccd_turn__wrap_up" in names:
        return ""                                  # the turn wrapped up: its recap says what is left and why
    if any(isinstance(t, dict) and str(t.get("status") or "running").lower() == "running" for t in background or ()):
        return ""                                  # hooks.md, Stop input: a running task's end wakes the session
    nxt = next((x for x in steps if x.get("status") == "in_progress"), steps[0])
    if waits and (AWAITS.search(str(nxt.get("content") or "")) or awaits_sessions(nxt.get("content"))):
        return ""                                  # nothing can be done on it until a report arrives
    tail = str(report or "").strip()[-600:]
    asks = [q for q in re.findall(r"[^.!?\n]*\?", tail) if len(q.strip()) > 8]
    if AUTHORITY.search(str(nxt.get("content") or "")) or any(AUTHORITY.search(q) for q in asks) \
            or WAITS_ON_OWNER.search(tail) and AUTHORITY.search(tail):
        return ""
    path = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(path)
    sent = disk.get("keptGoing") if isinstance(disk.get("keptGoing"), dict) else {}
    key = str(turn_id or "")
    n = int(sent.get("n") or 0) if sent.get("turn") == key else 0
    if n >= KEEP_GOING_MAX or (active and not key):
        return ""                                  # a turn with no id cannot be counted: never sent back twice
    disk["keptGoing"] = {"turn": key, "n": n + 1}
    relay._write_json(path, disk)
    others = len(steps) - 1
    return (f"phi (p4-phi): step {nxt.get('addr')} \"{relay._short(nxt.get('content'), 120)}\" is still "
            f"{nxt.get('status') or 'pending'}" + (f", with {others} more open after it" if others else "") +
            ", and this turn's end names no matter of ezexe's authority. Carry on with it now. If it truly waits "
            "on a matter of ezexe's authority, permissions or security settings, credentials, spending, or an action "
            "that cannot be undone or publishes outward, end the turn with `mcp__ccd_turn__wrap_up` whose question "
            "names it in one line and whose first button is ezexe's go; if the step is done or dropped, update the "
            "task list.")


# --- the work in flight, as the Stop input lists it -------------------------------------------------------------------
#
# hooks.md, "Stop input": `background_tasks` lists each task still in flight, with its `id`, `type`, `status`,
# `description` and, for a shell task, its `command`, and is present when the task registry is reachable. p4-phi
# records no launch of its own: the Stop hook keeps that list on session.json, and the checks that run between turns,
# such as the restart check and the archive checks, read it there, since PreToolUse input lists no running task.
# An entry leaves the kept list once its completion notice arrives as a message or a TaskStop or KillShell call stops
# it, so nothing names it as running after its end. A step's subagents stay in its task list, as agent_bind puts
# them, so _tasks reads them.

IN_FLIGHT_FIELDS = ("id", "type", "status", "description", "command")
NOTICE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>.*?<status>\s*([^<\s]+)\s*</status>", re.S)
STOPPED = re.compile(r'"name"\s*:\s*"(?:TaskStop|KillShell)"\s*,\s*"input"\s*:\s*\{[^{}]*?'
                     r'"(?:task_id|shell_id|id)"\s*:\s*"([A-Za-z0-9_-]{6,})"')


def keep_in_flight(s, payload):
    """The Stop input's `background_tasks` kept on the session as `backgroundTasks`, with the time they were read ->
    True when kept. An input with no list, as when the registry was not reachable or the call is the Stop a
    self-archive makes, leaves the last list read as it was."""
    tasks = payload.get("background_tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        return False
    s["backgroundTasks"] = [{k: t[k] for k in IN_FLIGHT_FIELDS if k in t} for t in tasks if isinstance(t, dict)][:50]
    s["backgroundAt"] = _now()
    return True


def clear_in_flight(s, text):
    """The kept entries whose completion notice, or whose TaskStop or KillShell call, `text` holds, taken off the
    session -> the ids taken off."""
    ended = {m.group(1) for m in NOTICE.finditer(str(text or ""))} | {
        m.group(1) for m in STOPPED.finditer(str(text or ""))}
    kept = s.get("backgroundTasks") if isinstance(s.get("backgroundTasks"), list) else []
    gone = [t.get("id") for t in kept if isinstance(t, dict) and t.get("id") in ended]
    if gone:
        s["backgroundTasks"] = [t for t in kept if not (isinstance(t, dict) and t.get("id") in ended)]
    return gone


def in_flight(s):
    """The background tasks a session's last Stop input listed as still running, each with its id."""
    tasks = s.get("backgroundTasks") if isinstance(s, dict) else None
    return [t for t in tasks or [] if isinstance(t, dict) and t.get("id")
            and str(t.get("status") or "running").lower() == "running"]


def _tasks(p):
    """The subagent tasks of a task list, each with its step, None for a loose one."""
    for st in p.get("steps") or []:
        for t in st.get("tasks") or []:
            yield st, t
    for t in p.get("loose") or []:
        yield None, t
