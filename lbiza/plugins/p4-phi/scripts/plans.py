"""plans.py: each session's task list as numbered steps, the tree of task lists its parent's anchor holds, and the
checks that ride on them.

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
  level      each start names the model and effort its kind of work gets.
  subagents  a subagent the Agent tool starts is a task of the step in progress, told what changed beside it.
  turns      at Stop, a turn's report is matched against the open steps of the session's children and siblings and
             delivered to those it bears on.
  in flight  the Stop input's list of background tasks still running, kept on session.json for the checks that
             run between turns.
"""

import hashlib
import json
import os
import re

import relay
import starts

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
    """A session's parent step: the address its brief names, else the parent's step in progress when the session
    started; '' for an orchestrator or a parent with no task list. A brief that names no step is bound to no step
    by its words: a worker whose brief spoke of a native goal was bound to the step "Give this session a native
    goal" of its parent, which another session was started for, and was told of that step's every change. Siblings
    started in one step for different steps of the task list each get their own where their briefs name them."""
    if s.get("rootStep") is not None:
        return str(s.get("rootStep") or "")
    parent = relay._parent(s)
    if not parent:
        return ""
    m = STEP_RE.search(str(s.get("task") or ""))
    if m:
        return m.group(1)
    return str(load(home, parent).get("current") or "")


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
                if isinstance(it.get("session"), str) and it["session"].strip():
                    new[-1]["session"] = it["session"].strip()[:80]    # the session this step was handed to
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
                       "tasks": [{"id": t.get("id"), "tool": t.get("tool", ""), "status": t.get("status"),
                                  "heads": t.get("heads") or []} for t in x.get("tasks") or []
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
        left = s.get("rootLeft") if isinstance(s.get("rootLeft"), dict) else None
        ps = None if left else step_of(load(home, parent), root)
        # a step that left the parent's list before this first list is read from the words it had, plans.leave
        old["rootText"] = str(left.get("was") or "") if left else (ps or {}).get("content", "")
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


# The words by which a step of a task list says it is dropped. A worker is bound to its parent's step by that step's
# number, and a parent that sends a new list for a new request, or the same list again after a compaction, moves and
# replaces numbers with no word on the worker's task. So only these words, in the step that was the worker's or in a
# step that bears on it, tell a worker to stop; a number that went away or now names another step tells it nothing.
DROPPED = re.compile(r"\b(dropped|cancell?ed|withdrawn|abandoned|scrapped|called off|no longer wanted|not wanted)\b",
                     re.I)
DROP_WORDS = frozenset("dropped cancelled canceled withdrawn abandoned scrapped called off longer wanted".split())


def dropped(was, at, new):
    """The words of the new list that say the step `was` is dropped, or '': the step now at its address, where
    that says so of it or says nothing else, and else a step anywhere in the list that says so and bears on it."""
    if at and DROPPED.search(at) and (bears(was, at) or len(words(at) - DROP_WORDS) <= 1):
        return at
    return next((c for c in new.values() if DROPPED.search(c) and bears(was, c)), "")


def renumber(home, sid, old, new, depth=0):
    """A worker follows its parent's step to the step's new number: its `rootStep`, the root of its own task list
    and each address under it, and the same in the sessions it started, which are bound to its steps."""
    def swap(a):
        a = str(a or "")
        return new + a[len(old):] if a == old or a.startswith(old + ".") else a
    spath = os.path.join(relay._dir(home, sid), "session.json")
    disk = relay._read_json(spath)
    if disk and disk.get("rootStep") and swap(disk["rootStep"]) != disk["rootStep"]:
        disk["rootStep"] = swap(disk["rootStep"])
        relay._write_json(spath, disk)
    p = load(home, sid)
    if p.get("steps"):
        p["root"], p["current"] = swap(p.get("root")), swap(p.get("current"))
        for st in p["steps"]:
            st["addr"] = swap(st.get("addr"))
        relay._write_json(_path(home, sid), p)
    for kid in _children(home, sid) if depth < 8 else ():
        renumber(home, kid, old, new, depth + 1)


def leave(home, kid, r, was):
    """Marks a worker whose parent step is in its parent's list no more, with no word that it was dropped: its task
    stands as its brief gave it, and from here nothing of its parent's list is read as that step."""
    spath = os.path.join(relay._dir(home, kid), "session.json")
    disk = relay._read_json(spath)
    if disk and not disk.get("rootLeft"):
        disk["rootLeft"] = {"step": r, "was": str(was or "")[:300], "time": _now()}
        relay._write_json(spath, disk)


def relay_revision(home, s, plan, rev):
    """A revised task list, told on the next message to whoever serves or uses what changed. A worker whose step
    was renumbered is told its new number and follows it. One whose step was reworded is told the new words. One
    whose step the list drops in words, DROPPED, is told to stop. One whose step is gone or now holds other words,
    as when the parent sent a new list for a new request, is told nothing, leave: its task stands."""
    sid, title = s["sessionId"], relay._title(s)
    stamp = hashlib.sha1(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:10]
    new = {x["addr"]: x["content"] for x in plan.get("steps") or []}
    for kid, ks in _children(home, sid).items():
        r = str(ks.get("rootStep") or "")
        if not r or ks.get("rootLeft"):
            continue
        if r in (rev.get("moved") or {}):
            relay.warn(home, kid, f"plan:{sid}:{stamp}:moved",
                       f"your root step {r} in the task list of \"{title}\" is now numbered {rev['moved'][r]}; the "
                       f"step itself is unchanged.")
            renumber(home, kid, r, rev["moved"][r])
        if r not in rev["removed"] and r not in rev["changed"]:
            continue
        was = rev["was"][r]
        at = new.get(r, "") if r in rev["changed"] else ""
        said = dropped(was, at, new)
        if said:
            relay.warn(home, kid, f"plan:{sid}:{stamp}:gone",
                       f"your root step {r}, \"{relay._short(was, 160)}\", was dropped from the task list of "
                       f"\"{title}\", your parent session, which now says \"{relay._short(said, 160)}\". Stop before "
                       f"the next tool and message {sid}: your work may no longer be wanted.")
        elif at and bears(was, at):
            relay.warn(home, kid, f"plan:{sid}:{stamp}:{r}",
                       f"your root step {r} in the task list of \"{title}\" was revised from "
                       f"\"{relay._short(was, 160)}\" to \"{relay._short(at, 160)}\". Check whether your steps still "
                       f"serve it.")
        else:
            leave(home, kid, r, was)
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
    if parent and root and not (disk or s).get("rootLeft"):   # a step its parent's list holds no more says nothing
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


# --- the words that keep a step with its session ------------------------------------------------------------------

DEPENDS = re.compile(r"\b(after|then|once|using|uses|based on|depends? on|following|built on|with the results?|"
                     r"results? of|output of|from (?:the )?(?:step|previous|last)|step \d+)\b", re.I)
WAITS = re.compile(r"\b(wait(?:s|ing)?|until|confirm\w*|verif\w*|can go|when\b[^.]*\blands?|tell|notify|relay\w*|"
                   r"send|ask|hand (?:off|over)|report back)\b", re.I)   # a step that waits on or passes on work
QUICK_WORDS = 4               # a step of fewer content words is a quick thing, done here
LANDS = re.compile(r"^\W*(?:run\b[^,.;]*\b(?:tests?|suites?|checks?)|report|wrap)\b"
                   r"|^\W*(?:tests?|verify|check|review)\b(?!\s*#?\d)(?=(?:(?!\bpass(?:es|ed)?\b)[^.;:])*\b(?:own (?:work|changes?|commits?|diff|steps?)|landed|merged|committed|"
                   r"pushed|work|changes?|diff|results?|commits?|suites?|tests?|build|outcome|fix(?:es)?|it|them)\b)"
                   r"|\b(?:commit|merge|push|ship|release|land|fast-forward)\b", re.I)
# checks or lands the session's own work. A check of anything else is work, such as "Check 1: nothing hidden in
# AppData", one of the checks an orchestrator's children are for. The checked thing is named before any "pass":
# in "Check the data pipeline passes the schema test" the test is the measure, and the pipeline is code of the
# repository, which is work for a child
ORCHESTRATES = re.compile(r"^\W*(?:start|kick\s*off|launch)\s+(?!writing|adding|implementing|making)"
                          r"(?:[\w'’-]+\s+){0,5}?(?:checks?|tests?|sessions?|runs?)\b"
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


def handed(st):
    """Why a step is handed out to nobody, or '': its item names the session it was delegated to. The app's own
    text gives an item of `update_plan` the field `session`, "When you delegated this step to a session you started:
    that session's short name", and the app shows that session's state on the step. Such a step is a session's
    already, so no line of p4-phi's asks for one to be started for it."""
    name = str((st or {}).get("session") or "").strip()
    return f"its `session` field names the session doing it, `{name}`" if name else ""


# --- the steps an orchestrator keeps ----------------------------------------------------------------------------
#
# A session with no parent keeps itself free for orchestration: planning, messaging and managing sessions, decisions
# with ezexe, and landing work. A step that checks or lands work, such as a test-and-commit, merge, push, release or
# sync, or the watch of the run on what was pushed, waits on or passes on work, starts a check or session, manages a
# worker, compiles results or tracks what another does stays; top_stays gives the reason for each.

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
# Seeing landed work through is landing too. The orchestrator pushed the work, so the workflow run, the CI run or
# the release run on it is its own to watch, and so is bringing the installed plugins up to the release that run
# made: a child in a worktree of its own would wait on what its starter has to read anyway. The object decides: a watch of anything else, as
# of a lock file or of how a hook runs on one system, is work, and so is a change to a plugin's own files.
# The run is a noun here. In "Confirm this runs on Windows" and "Verify the actions run correctly" it is a verb, and
# the step is work. Only CI is read as a run when a verb follows it, as in "CI passed": a workflow or a pipeline that
# passes or finishes may be code of the repository, so it takes a preposition, a result or the end of the step.
RUN_OF = (r"(?:(?:workflow|ci|release|action|pipeline|github(?:'s|’s)?(?:\s+actions?)?)\s+runs?\b"
          r"|(?:the|its|each|every)\s+runs?\s+on\b|this\s+run\s+on\b"
          r"|ci(?:\s+(?:on|for|to|until|through|pass\w*|finish\w*|end\w*|go\w*|results?|green|red)\b|\W*$)"
          r"|(?:workflows?|pipelines?)(?:\s+(?:on|for|to|until|through|results?|green|red)\b|\W*$))")
WATCHES_RUN = re.compile(r"\b(?:watch|follow|monitor|poll|a?wait|check|verify|confirm)\w*\b[^.;]*?\b" + RUN_OF, re.I)
# The installed plugins end the object, so "the installed plugin loader code" is code of a plugin, and work.
INSTALLS = re.compile(r"\b(?:updat|upgrad|reinstall|refresh)\w*\b[^.;]*?\binstalled\s+(?:[\w-]+\s+){0,2}?plugins?"
                      r"(?=\s*(?:$|[.;,:!?)])|\s+(?:from|to|for|with|in|on|at|and|of|after|before|via|by|once|then|"
                      r"using|so|when|until)\b)|\bplugin\s+update\b", re.I)


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
# Planning is the orchestrator's own: a plan file has one writer, the session that holds it. The opening verb decides, with the plan as its object and a few small words between them at
# most, so "Write the docs for plan mode" and "Put the fixtures under tests/plan/" are work. A step that builds code
# or a page about plans is work too, which the noun after the plan or a file named plan tells: "Write the plan
# parser in src/plan.py".
PLAN_OBJECT = (r"(?:(?:the|a|an|this|that|its|each|every|whole|new|next|first|final|how|development|build"
               r"|up|together|out|and|write|draft|revise|refine)\s+){0,3}"
               r"plans?\b")
PLANNING = re.compile(r"^\W*(?:enter\s+plan\s+mode\b|plan\b"
                      r"|(?:research|write|draft|loop|revise|refine|put|present|submit)\s+" + PLAN_OBJECT + ")", re.I)
PLAN_CODE = re.compile(r"\bplans?[\s-]+(?:file\s+)?(?:parser|reader|writer|loader|renderer|module|code|command|script|"
                       r"tests?|docs?|pages?|rules?|hooks?|skills?|folders?|director(?:y|ies)|formats?)\b"
                       r"|\bplan[\s-]+mode[\s-]+(?:nudge|rule|docs?|hook|check|tests?|code|page|line|sentence|advice)\b"
                       r"|\bplans?\.\w+", re.I)
PLANNING_WHY = "plans, which stays with the session that holds the plan until ezexe approves it"


def awaits_sessions(text):
    """True for a step that waits on, awaits, collects or checks other sessions' or trees' reports or results."""
    text = str(text or "")
    if BUILDS.match(text):                         # "Fix session report truncation" builds something: work
        return False
    return bool(AWAITS_TOP.search(text) or OTHERS.search(text))


def top_stays(text):
    """Why an orchestrator keeps a step itself, or '' for a work step that goes to a child."""
    text = str(text or "")
    if awaits_sessions(text):                      # waiting on other sessions' results wins over the check rule
        return AWAITS_WHY
    if PLANNING.search(text) and not PLAN_CODE.search(text):   # one writer, and nothing built before the approval
        return PLANNING_WHY
    if LANDS.search(text) or SYNCS.search(text) or WATCHES_RUN.search(text) or INSTALLS.search(text):
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


# --- delegation: where a step runs --------------------------------------------------------------------------------
#
# A step that only reads or searches is the subagent p4-phi:finder's, the skill sub-agentic's evidence finder; one
# that only runs a command is a background command of the session's own; one that asks for one question from several
# sides is an agent team's; the rest is a worker's. sub-agents.md gives
# the built-in Explore "the parent conversation's model", and puts "The `model` field in the subagent's definition"
# in its model order, so agents/finder.md carries `model: haiku` and `effort: low` and no call has to. The page also says "With nothing configured, a subagent
# that Claude spawns from your main conversation starts in the background." tools-reference.md, "Background
# commands", says "Claude can set `run_in_background: true` to start the command as a background task and continue
# working while it runs.", and interactive-mode.md says "Output is written to a file and Claude can retrieve it using
# the Read tool".

READS = re.compile(r"^\W*(?:find|search|look\s+(?:for|up|at|into|through)|read|grep|list|locate|survey|scan|map|"
                   r"inventory|explore|trace|identify|count|collect|gather|sweep|research)\b", re.I)
RUNS = re.compile(r"^\W*(?:run|re-?run|execute)\b", re.I)
WRITES = re.compile(r"\b(?:fix\w*|writ\w*|add\w*|chang\w*|edit\w*|implement\w*|updat\w*|remov\w*|renam\w*|creat\w*|"
                    r"mak\w+|mov\w+|commit\w*|refactor\w*|port\w*|delet\w*|migrat\w*|rewrit\w*|replac\w*|patch\w*|"
                    r"push\w*|merg\w*|land\w*|releas\w*|ship\w*|install\w*)\b", re.I)
# agent-teams.md, "Compare with subagents": "Use agent teams when teammates need to share findings, challenge each
# other, and coordinate on their own." A step asks for one by its own words: several sides or lenses, competing
# hypotheses, or a team named as the means. One that only names agent teams as its subject asks for none.
TEAMS = re.compile(r"\b(?:with|by) an? agent[- ]team\b"
                   r"|\bfrom (?:several|multiple|many|different|opposing|competing|two|three|four|all) "
                   r"(?:sides|angles|perspectives|viewpoints|lenses)\b"
                   r"|\b(?:with|by) competing (?:hypothes[ie]s|theories|explanations)\b", re.I)
# A step that opens on a word of making is a writer's, whatever sides it names: WRITES holds no such word of its own.
TEAM_NOT = re.compile(r"^\W*(?:build|draft|develop|generat|convert|extract|document)\w*\b", re.I)


# --- the model and effort a worker is started with ---------------------------------------------------------
#
# The skill sub-agentic, rule 5: "Set model and effort on every agent by its role; nothing inherits by default." Each
# kind of step is a role of that skill's table: static or mechanical work lands what is written, its integrator, on
# Sonnet at medium; a build or a design writes what the tree does not hold yet, its writer, on Opus at medium; a
# review re-reads another's work, its cross-check, on Sonnet at medium; and a new top session is an orchestrator, on
# the session's own model and effort, which the start tool gives a call that names neither. A plugin agent carries a
# model and an effort in its file, and every start call p4-phi hands out carries an `effort`, and a `model` unless
# it keeps the parent session's, but for an orchestrator's, which carries neither. `mcp__ccd_session__start_session` takes
# `model`, the same family or cheaper than the caller's, and `effort`, at or below the caller's, both for a `fresh`
# start only, as its schema says. The kind of a step picks its entry of CHILD_LEVELS, which p4.json's
# phi.child_levels can set. The caller's own effort is the hook input's `effort.level`, "the effort level setting when the hook runs" by hooks.md, "Common input fields",
# where "`$CLAUDE_EFFORT` holds the same level.": phi.own_effort reads it into PARENT_EFFORT, and child_level names
# no effort above it.

# start_session's `model` takes a model id, "Same family or cheaper than yours; anything higher is ignored", where an
# Agent call takes an alias: so each entry names the id of the newest model of its family
CHILD_LEVELS = {"static": {"model": "claude-sonnet-5-5", "effort": "medium"},
                "build": {"model": "claude-opus-5-5", "effort": "medium"},
                "design": {"model": "claude-opus-5-5", "effort": "medium"},
                "review": {"model": "claude-sonnet-5-5", "effort": "medium"},
                "plan": {"model": "claude-fable-5-2", "effort": "inherit"},
                "top": {"model": "inherit", "effort": "inherit"}}      # p4.json phi.child_levels sets each kind
CHILD_KINDS = {"static": "static or mechanical work, an integrator's",
               "build": "a build that changes behaviour, a writer's",
               "design": "a design or a decision with its sources, a writer's",
               "review": "a review or check of another's work, a cross-check's",
               "plan": "a plan held and written in plan mode, a planner's",
               "top": "a new top session, an orchestrator's"}
ROLES = {"static": "integrator", "build": "writer", "design": "writer", "review": "cross-check", "plan": "planner",
         "top": "orchestrator"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DESIGNS = re.compile(r"^\W*(?:re-?)?(?:design|architect|specif|spec\b|propos|investigat|decid|analy[sz]|research|"
                     r"plan\b)\w*", re.I)
# a planner's brief says so on a line of its own, as a new orchestrator's does for starts.ORCHESTRATOR: the session starts in plan
# mode, where it holds and writes the plan
PLANNER = re.compile(r"(?im)^[ \t>*-]*(?:this session|it) starts in plan mode\b")
REVIEWS = re.compile(r"^\W*(?:re-?)?(?:review|audit|evaluat|assess|verif|cross-check|check|judg|grad)\w*", re.I)
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
# the one line level_line writes, `Model and effort: <model> at <effort> effort`, with or
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
            if given.get("effort") in EFFORTS + ("inherit",):
                out[kind]["effort"] = given["effort"]
    return out


CHILD_LEVELS_DEFAULT = {k: dict(v) for k, v in CHILD_LEVELS.items()}


def child_kind(text):
    """'top' for a new orchestrator's brief, 'plan' for a brief that says its session starts in plan mode and for a
    step that plans, as top_stays reads one, 'review' for a step that reviews or checks, 'design' for one that
    designs or decides, 'static' for docs pages, a rename, a version bump or other mechanical work that names no
    code, else 'build'."""
    text = str(text or "")
    if starts.ORCHESTRATOR.search(text):
        return "top"
    if PLANNER.search(text) or (PLANNING.search(text) and not PLAN_CODE.search(text)):
        return "plan"
    if REVIEWS.search(text):
        return "review"
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


PARENT_EFFORT = ""            # phi.Me sets it: the effort the session of this hook runs at, '' where nothing names it


def capped(effort):
    """`effort`, or PARENT_EFFORT when that is the lower of the two: the app starts no session above its starter's
    effort, a limit no docs page states and p4-temportal's hooks/claude_code_limits.json logs."""
    if PARENT_EFFORT in EFFORTS and effort in EFFORTS and EFFORTS.index(effort) > EFFORTS.index(PARENT_EFFORT):
        return PARENT_EFFORT
    return effort


def child_level(text, brief=""):
    """{"model", "effort", "kind"} a worker is started with for a step or a brief: its kind's entry of
    CHILD_LEVELS, with what the brief itself names laid over it, and the effort held to PARENT_EFFORT. `model` is
    'inherit' for the parent session's own."""
    kind = "top" if starts.ORCHESTRATOR.search(str(brief or "")) else child_kind(text if str(text or "").strip() else brief)
    out = {**CHILD_LEVELS.get(kind, CHILD_LEVELS_DEFAULT[kind]), "kind": kind}
    said = said_level(brief or text)
    if said:
        out.update(said, said=True)
    if capped(out["effort"]) != out["effort"]:
        out.update(effort=capped(out["effort"]), capped=True)
    return out


def level_keys(level):
    """The `model` and `effort` keys of a start call: each is left out to inherit the parent session's, which is
    how the app's tool takes it, "Omit to inherit"; only an orchestrator's start carries neither."""
    out = {} if str(level.get("effort") or "").lower() == "inherit" else {"effort": level["effort"]}
    if str(level.get("model") or "inherit").lower() != "inherit":
        out["model"] = level["model"]
    return out


def level_line(level):
    """The one line a brief says its model and effort in, so the choice is visible to the child and its reader."""
    model = ("the parent session's own model" if str(level.get("model") or "inherit").lower() == "inherit"
             else level["model"])
    why = ("named by the parent session" if level.get("said") else
           f"since this is {CHILD_KINDS[level['kind']]}, as the skill sub-agentic gives it")
    if level.get("capped"):
        why += ", held to the parent session's own effort"
    effort = "its own" if str(level["effort"]).lower() == "inherit" else level["effort"]
    return f"Model and effort: {model} at {effort} effort, {why}."


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


# --- subagents as tasks of the step that launched them -------------------------------------------------------------
#
# The hook inputs carry the subagent's id, so its task is bound by that id and nothing is guessed. hooks.md,
# "SubagentStart input": "SubagentStart hooks receive `agent_id` with the unique identifier for the subagent and
# `agent_type` with the agent name that the matcher filters on", beside the launching session's `session_id`. So at
# its start the subagent is a task of the step in progress then, with the version the parent's anchor has then. Each
# tool call of the subagent carries the same `agent_id` and is warned of what changed beside the launching session
# since, and its SubagentStop, which carries it too, closes the task. As a task of the step, the anchor carries it
# to the parent. The Agent call itself makes no record here: agent_launch only writes the text for the subagent's
# start, which hook.py hands over by the one order rule it keeps.
#
# The task holds what no record of Claude Code's holds: the step the subagent serves, with its words at the launch,
# and the version the parent's anchor had then. Claude Code keeps the rest, so the task holds no copy of it:
#   description  `tool_input.description` of the Agent call, and `description` of the subagent's entry in the Stop
#                input's `background_tasks`, which turn_relay reads from the list keep_in_flight kept
#   start        the first row of the subagent's own transcript, `subagents/agent-<agent_id>.jsonl`
#   result       `last_assistant_message` of the SubagentStop input, and that transcript's last message
#   files        the Edit, Write and NotebookEdit calls of that transcript, which the SubagentStop input
#                names as `agent_transcript_path`
# Two things stay beside them. `status` says whether the SubagentStop has come: summary reads it when an anchor is
# made, with no hook input and no transcript at hand. `wrote` is the files a stopped subagent's transcript shows it
# wrote, read once at its stop: the ledger reads it with no transcript path at hand.


def _agent(p, agent_id):
    return next((t for _, t in _tasks(p) if t.get("id") == agent_id), None)


def agent_launch(home, s, inp):
    """The Agent call, before it runs -> the text for the subagent's start: the step in progress it is launched for
    and what the parent's anchor holds for its paths; '' with no step in progress. It writes nothing."""
    p = load(home, s["sessionId"])
    st = step_of(p, p.get("current") or "") if p.get("steps") else None
    if not st:
        return ""
    parent = relay._parent(s)
    head = (f"phi (p4-phi): you are a subagent of \"{relay._title(s)}\", launched for its step {st['addr']}, "
            f"\"{relay._short(st.get('content'), 200)}\". Keep to that step; what you find goes back in your result.")
    piece = relay.slice_text(home, {"sessionId": "agent", "spawnedFrom": {"sessionId": parent},
                                    "task": str(inp.get("prompt") or ""), "cwd": s.get("cwd") or ""}) if parent else ""
    return "\n".join(x for x in (head, piece) if x)


def agent_bind(home, s, agent_id, kind=""):
    """The subagent's start: the `agent_id` its SubagentStart input carries, made a task of the step in progress,
    with the version the parent's anchor has -> True when the task is made. `kind` is the input's `agent_type`,
    which the line for the parent names. An id that has its task already, as at a resume, makes none."""
    sid = s["sessionId"]
    p = load(home, sid)
    if not agent_id or _agent(p, agent_id):
        return False
    parent = relay._parent(s)
    st = step_of(p, p.get("current") or "") if p.get("steps") else None
    task = {"id": agent_id, "tool": "Agent", "agent": True, "status": "open",
            "anchorSeen": int(relay._read_json(relay.anchor_path(home, parent)).get("version") or 0),
            "stepText": (st or {}).get("content", "")}
    if st is None:
        p.setdefault("loose", []).append(task)
    else:
        st.setdefault("tasks", []).append(task)
    relay._write_json(_path(home, sid), p)        # the anchors carry it, and the parent is told its id
    relay.make_anchor(home, parent, _now())
    relay.make_anchor(home, sid, _now())
    if parent:
        where = f"its step {st['addr']}" if st else "no step of its task list"
        relay.warn(home, parent, f"agent:{sid}:{agent_id}",
                   f"down: \"{relay._title(s)}\" launched subagent {agent_id} for {where}"
                   + (f", agent type `{relay._short(kind, 80)}`" if kind else "") + ".")
    return True


HEARD_TAIL = 4 * 1024 * 1024  # bytes of a subagent's transcript, from its end, read for what hooks told it
HEARD_ROWS = 5                # rows from its top looked through for the first one that carries a time


def agent_heard(path):
    """What a subagent's own transcript says of it -> its start, as the minute a note carries, and each line a hook
    added to its context within the file's last HEARD_TAIL bytes; None when the file cannot be read or dates no row.
    hooks.md, "Add context for Claude": "Claude Code saves the injected text in the session transcript", and
    claude-directory.md keeps a subagent's transcript "in the same format as the session transcript": a row of type
    `attachment` whose attachment has the type `hook_additional_context` and the text under `content`."""
    import time as _t
    from datetime import datetime
    start = None
    try:
        with open(path, "rb") as f:
            for _ in range(HEARD_ROWS):
                try:
                    stamp = str(json.loads(f.readline()).get("timestamp")).replace("Z", "+00:00")
                    start = datetime.fromisoformat(stamp).timestamp()
                    break
                except (ValueError, AttributeError, TypeError):
                    continue
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - HEARD_TAIL))
            tail = f.read().split(b"\n")[1 if size > HEARD_TAIL else 0:]
    except OSError:
        return None
    if start is None:
        return None
    told = set()
    for raw in tail:
        if b"hook_additional_context" not in raw:
            continue
        try:
            a = json.loads(raw).get("attachment")
        except (ValueError, AttributeError):
            continue
        if isinstance(a, dict) and a.get("type") == "hook_additional_context":
            content = a.get("content")
            for item in content if isinstance(content, list) else [content]:
                told.update(x.strip() for x in str(item or "").splitlines())
    return _t.strftime("%Y-%m-%d %H:%M", _t.localtime(start)), told


def agent_warn(home, s, agent_id, transcript=""):
    """A subagent's next tool call: what changed beside the launching session since it was launched or last told,
    and its step revised or gone; '' when nothing did. `transcript` is the subagent's own, which says when it
    started and what it has heard, so the task keeps neither: a sibling's note is told when it was written after the
    start, a note carrying its minute and one of the start's own minute counting as there before it, and a line is
    told when the transcript does not hold it already. No file a sibling changed is named: the anchor holds none,
    since a sibling's files lie in its own worktree and not under the subagent's hands. While the transcript cannot
    be read, the siblings' notes wait."""
    sid = s["sessionId"]
    p = load(home, sid)
    t = _agent(p, agent_id)
    if not t or t.get("status") != "open":
        return ""
    anchor = relay._read_json(relay.anchor_path(home, relay._parent(s)))
    v = int(anchor.get("version") or 0)
    lines = []
    seen = int(t.get("anchorSeen") or 0)
    heard = agent_heard(transcript) if v > seen else None
    if heard:
        since, told = heard
        for nid, at in sorted((anchor.get("changedAt") or {}).items()):
            if nid == sid or int(at or 0) <= seen:
                continue
            n = (anchor.get("nodes") or {}).get(nid) or {}
            said = [relay._short(m.get("claim"), 200) for m in n.get("marks") or [] if str(m.get("time") or "") > since]
            said = [f"\"{n.get('title') or nid}\": {x}" for x in said]
            lines += [x for x in said if f"- {x}" not in told][-2:]     # the two newest it has not heard
    step = next((st for st in p.get("steps") or [] for x in st.get("tasks") or [] if x is t), None)
    if t.get("stepText") and step is None:
        lines.append("the step you were launched for is no longer in the launching session's task list")
    elif step is not None and t.get("stepText") and step.get("content") != t["stepText"]:
        lines.append(f"the step you were launched for now reads \"{relay._short(step.get('content'), 160)}\"")
        t["stepText"] = step.get("content")
    if heard or lines:
        if heard:
            t["anchorSeen"] = v
        relay._write_json(_path(home, sid), p)
    if not lines:
        return ""
    return ("phi (p4-phi): since you were launched, beside the session that launched you:\n"
            + "\n".join(f"- {x}" for x in lines[:6]) + "\nCheck that your work still holds before going on.")


def agent_wrote(home, sid, agent_id, paths):
    """The files a stopped subagent's transcript shows it wrote: its task keeps them, so the ledger names it a level
    miss -> True when one is new."""
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


def agent_stop(home, s, agent_id):
    """The subagent stopped: its task closed -> True when a task was closed. Its result stays where Claude Code keeps
    it, in the SubagentStop input's `last_assistant_message` and the subagent's transcript. An id no start bound has
    no task and gets none here."""
    sid = s["sessionId"]
    p = load(home, sid)
    t = _agent(p, agent_id)
    if not t or t.get("status") != "open":
        return False
    t["status"] = "completed"
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
    if not root or not parent or s.get("rootLeft"):
        return ""
    if s.get("rootStep") is None:                 # kept from its start, so the parent's next step does not take it
        s["rootStep"] = root
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
MEMORY_RULES = None           # phi.py sets it to phi.memory_rules: the store's feedback and user memories by name


def rule_names(home=""):
    """The names of the rules a session starts with: the store's feedback and user memories, read from the memory
    folder, so the list stays true as memories change."""
    names = set()
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
    """The steps of a session's task list not yet completed, each as stored, with its subagents of every status."""
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


def matches(text, steps, shard, base, loose=True, bear=None, home="", flying=()):
    """Each step that `text` bears on, with the sentences of `text` that bear on it: a step is matched by its
    address, by a path among the session's owned paths, or by sharing SHARE content words with a sentence. Code blocks
    and drawn trees are left out. `flying` is the descriptions of the session's subagents still running, as the Stop
    input lists them: a sentence that bears on one counts for the step in progress, or the first step when none is."""
    text = prose(text, home)
    bear = bear or bears
    names = rule_names(home)
    sents = [x.strip() for x in SENTENCE.split(str(text or "")) if x.strip() and not recites(x, names)]
    named = set(ADDR_RE.findall(str(text or "")))
    serves = next((st for st in steps if st.get("status") == "in_progress"), steps[0] if steps else None)
    out = []
    for st in steps:
        hit = []
        for x in sents:
            if st["addr"] in set(ADDR_RE.findall(x)) or (loose and bear(x, st.get("content"))) or any(
                    relay.overlap(p, sh) for p in relay.paths_in(x, base) for sh in shard):
                hit.append(x)
            elif loose and st is serves and any(bear(x, d) for d in flying):
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
                      bear=relay_bears if way == "down" else relay_bears_sibling, home=home, flying=flying(os_))
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


# --- the turns the hooks module starts ------------------------------------------------------------------------------
#
# The plugin's hooks module starts a turn for upkeep with `$.prompt.submit`, of which plugins/mods/api.md, "Start a
# turn from a background job", says "The call waits until the session is idle and then starts a new turn." The prompt
# of such a turn opens with UPKEEP_MARK, which a UserPromptSubmit hook is given as submitted, so it is told from
# ezexe's words by its opening. Each wake is counted on session.json as `woke`, until a turn begins that no wake
# started, and upkeep stops at KEEP_GOING_MAX of them in a row.

KEEP_GOING_MAX = 2             # turns the hooks module starts for upkeep in a row, under hooks.md's 8-in-a-row cap

WAKE_MARK = "phi (p4-phi): the turn before this one ended on"
# The prompt of a turn the module starts for upkeep, upkeep.wake, opens with this one. No prompt opens with it while
# `phi.upkeep` is off.
UPKEEP_MARK = "phi (p4-phi): upkeep is due"
# The sweep's prompt, upkeep.SWEEP, opens with this one. The module submits no such prompt: p4-phi hands a session
# one `CronCreate` with it, and Claude Code's schedule fires it, so no wake is counted for it. Its words are
# p4-phi's own all the same, and no message of ezexe's to route.
SWEEP_MARK = "Sweep the sessions this one started, as p4-phi's upkeep has it."


def woken(prompt):
    """True for the prompt of a turn the hooks module started: for upkeep, or one that opens with WAKE_MARK."""
    return str(prompt or "").lstrip().startswith((WAKE_MARK, UPKEEP_MARK))


# The app's own notice about a message this session sent to another session: that it is held, released, denied or
# expired, or that the other session went idle. The SendMessage tool's text names both, "a `[Cross-session delivery
# notice]` tells you when that happens" and "exactly one `[Cross-session idle notice]` arrives", and each reaches a
# session as a prompt that opens with its mark, with no tag around it. Its words are the app's, never ezexe's.
APP_NOTICE = re.compile(r"\A\s*(?:\[MESSAGE FROM NON-USER SOURCE\b[^\]\n]*\]\s*)?"
                        r"\[Cross-session (?:delivery|idle) notice\]")


def app_notice(prompt):
    """True for a prompt that is the app's notice about a message this session sent to another session."""
    return bool(APP_NOTICE.match(str(prompt or "")))


# The frame Claude Code puts at the head of a background task's event that reaches a session as a prompt, such as a
# background subagent's report: "[SYSTEM NOTIFICATION - NOT USER INPUT]", then "This is an automated background-task
# event, NOT a message from the user." hooks.md, "UserPromptSubmit", has the hooks run on "A background subagent
# reporting back to the session that started it", and the desktop app stamps such a prompt with a kind rows.whose
# names nobody for. Its words are Claude Code's, never ezexe's.
SYSTEM_NOTE = re.compile(r"\A\s*\[SYSTEM NOTIFICATION\b")


def system_note(prompt):
    """True for a prompt that opens with the frame of a background task's event."""
    return bool(SYSTEM_NOTE.match(str(prompt or "")))


def wakes(disk):
    """How many turns in a row the hooks module started for a session, by its session.json."""
    w = disk.get("woke") if isinstance(disk, dict) else None
    return int(w.get("n") or 0) if isinstance(w, dict) else 0


# --- a worker's native goal -------------------------------------------------------------------------------------------
#
# Claude Code has a goal of its own, https://code.claude.com/docs/en/goal.md: one completion condition a session works
# toward, which a small model judges after each turn from the transcript alone, and while it is not met the turn is
# sent back. Where a store's phi.json sets `goal` true, a worker's brief line `Done looks like:` becomes its goal. The
# plugin's hooks module sets it once the worker's first turn has ended, with `$.command.run`, the one call seen to set
# a goal with no dialog, in the desktop app on Claude Code 2.1.326. The goal's evaluator sends the turn back, and the
# Stop hook sends none for open steps. The checks the evaluator cannot make stay phi.py's Stop hook, since it runs nothing and reads no file.

DONE_LINE = re.compile(r"^[ \t>*_-]*Done looks like[*_]*[ \t]*:[*_]*[ \t]*(\S.*)$", re.I | re.M)
GOAL_CHARS = 4000             # goal.md, "Write an effective condition": "The condition can be up to 4,000 characters."
GOAL_LEAST = 12               # a shorter line is no condition, so `/goal clear` or one of its aliases is never sent
GOAL_TAIL = 1 << 20           # the bytes from a transcript's end read for the goal's last row
# The part of a goal that has a worker's change read by a reader that has not seen the conversation, where the work
# changes files and p4.json's `phi.goal_review` is on. It is kept here alone and both goals p4-phi sets carry it: the
# one from a brief's line `Done looks like:`, by phi.goal_condition. That goal is typed into a shell by a coworker's
# start script, so these words hold no backtick, quote or bracket.
# best-practices.md, "Give Claude a check to run": "A fresh reviewer does help, because it hasn't seen your
# reasoning", and "A reviewer that's asked to find problems will always find something. If you fix every finding,
# you end up with extra abstraction layers and tests for cases that can't happen." goal.md, "Write an effective
# condition": the evaluator "doesn't run commands or read files independently, so write the condition as something
# Claude's own output can demonstrate."
# Seen on 2026-11-22 in scripted runs of Claude Code 2.1.328 whose whole prompt was `/goal`, on a change of twenty
# lines with two faults its own tests missed:
# - Worded "leaves no finding it confirmed unmended, with two rounds of review at most", the run stalled. Two
#   reviews raised four findings and the session mended all four, and the goal's check then judged it not met ten
#   times: at `low` the skill gives a severity and no verdict, so "confirmed" named nothing the transcript held, no
#   review had come back clean, and the cap forbade the round that could. Claude Code ended the loop after eight
#   passes with no tool call, the goal unmet.
# - Worded as below, the check judged it met at its first pass: two reviews of three findings each, of which two
#   were mended and one answered as no fault each time, and no third. Its reason quoted each finding as mended or
#   answered and the line that no third review was run.
# - With no level named the skill raised nine and then eight findings on those twenty lines, and at `low` three and
#   three, so the level is named.
# So the words say what the transcript can show, name no verdict of the skill, let a finding be answered, and say
# outright that no review has to come back clean and that there is no third. A worker in the Terminal panel runs
# with p4-phi off, so they name a plain subagent where the session has no `p4-phi:check`.
REVIEW_PART = ("It is met only when this conversation also shows a review of the change by a reader that has not seen "
               "this conversation: the skill code-review at the level low and without --fix for a change to code, and "
               "for anything else the agent p4-phi:check, or a subagent handed the change and none of this "
               "conversation where this session has no such agent. Each finding of the review is mended, or answered "
               "here with the reason it is no fault, and this conversation says which for each. Where a finding led "
               "to a mend, one second review reads the mended change, and its findings are mended or answered the "
               "same way. Then this part is met: no review has to come back without a finding, and there is no third "
               "review.")


def done_line(text):
    """What a brief says done looks like: the words after its first line `Done looks like:`, cut to what a goal's
    condition holds, or '' where it has no such line or the line is too short to be a condition."""
    m = DONE_LINE.search(text if isinstance(text, str) else "")
    line = " ".join(m.group(1).split()) if m else ""
    return line[:GOAL_CHARS] if len(line) >= GOAL_LEAST else ""


def goal_on(s):
    """True while a session's native goal is set: the hooks module set it, and no row of the transcript has shown it
    met, judged impossible or cleared since."""
    g = s.get("goal") if isinstance(s, dict) else None
    return isinstance(g, dict) and bool(g.get("set")) and not g.get("over")


def goal_row(path, tail=GOAL_TAIL):
    """The last goal row of the transcript at `path`, read from its end, or {}: the attachment of type goal_status
    Claude Code writes when a goal is set, at each evaluation and when the goal is over. Seen with Claude Code 2.1.326
    and 2.1.328: `met` false with `sentinel` true as the goal is set, `met` false with a `reason` while it is not yet
    met, `met` true with the reason once achieved, `failed` true once judged impossible, and `met` true with
    `sentinel` true when the command clears it."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - tail))
            lines = f.read().split(b"\n")
    except (OSError, TypeError, ValueError):
        return {}
    for raw in reversed(lines[1:] if size > tail else lines):   # a read from the middle opens on part of a line
        if b'"goal_status"' not in raw:
            continue
        try:
            att = json.loads(raw.decode("utf-8", "replace")).get("attachment")
        except (ValueError, AttributeError):
            continue
        if isinstance(att, dict) and att.get("type") == "goal_status":
            return att
    return {}


def goal_over(row):
    """How a goal row says its goal ended: 'met' once the evaluator judged the condition to hold, 'failed' once it
    judged it impossible, 'cleared' where the command cleared it, and '' while the goal is still set."""
    if not isinstance(row, dict) or not row:
        return ""
    if row.get("failed") is True:
        return "failed"
    if row.get("met") is True:
        return "cleared" if row.get("sentinel") is True else "met"
    return ""


# --- the work in flight, as the Stop input lists it -------------------------------------------------------------------
#
# hooks.md, "Stop input": `background_tasks` lists each task still in flight, with its `id`, `type`, `status`,
# `description` and, for a shell task, its `command`, and is present when the task registry is reachable. p4-phi
# records no launch of its own: the Stop hook keeps that list on session.json, and the checks that run between turns,
# such as the restart check and the archive checks, read it there, since PreToolUse input lists no running task.
# An entry leaves the kept list once its completion notice arrives as a message or a TaskStop call stops
# it, so nothing names it as running after its end. A step's subagents stay in its task list, as agent_bind puts
# them, so _tasks reads them.

IN_FLIGHT_FIELDS = ("id", "type", "status", "description", "command")
NOTICE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>.*?<status>\s*([^<\s]+)\s*</status>", re.S)
STOPPED = re.compile(r'"name"\s*:\s*"TaskStop"\s*,\s*"input"\s*:\s*\{[^{}]*?'
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
    """The kept entries whose completion notice, or whose TaskStop call, `text` holds, taken off the
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


def flying(s):
    """The descriptions of a session's subagents its last Stop input listed as still running: hooks.md, "Stop
    input", gives each `subagent` entry of `background_tasks` its `description`."""
    return [str(t["description"]) for t in in_flight(s) if t.get("type") == "subagent" and t.get("description")]


def _tasks(p):
    """The subagent tasks of a task list, each with its step, None for a loose one."""
    for st in p.get("steps") or []:
        for t in st.get("tasks") or []:
            yield st, t
    for t in p.get("loose") or []:
        yield None, t
