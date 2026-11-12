"""plans.py: each session's plan as numbered steps, and the plan tree its parent's anchor holds.

The user's words, 2026-11-12: "i plan to do this in xyz steps ... step x becomes something you split into 'x' num
steps ... and then for each step of x in xyz double check your parent to relay up accross or down if that step needs
to be revised based on where there currently up to in there x of xyz".

  plan     a session's plan is the list it keeps with `mcp__ccd_turn__update_plan`. A PostToolUse hook on that tool
           applies each call (a whole new list, an advance, done and start) to <session>/plan.json: its steps with
           their addresses, statuses and the step in progress.
  address  a top session's steps are 1, 2, 3. A session started for a step of its parent's plan has that step's
           address as its root, so its steps are Y.1, Y.2. The root is the address the brief names ("step 2.3"),
           else the parent's step in progress when the child first spoke.
  tree     the parent's anchor (relay.make_anchor) holds every child's plan and its own.
  check    at each step boundary, when a step moves to in progress, a session is told what bears on that step:
             up      the parent's step it owns was revised, removed or passed
             across  a sibling's step in progress that shares its words, or touches its shard
             down    its children's progress on their steps, when it moved since the last check
           and the warnings kept for it. Nothing when nothing bears on it.
  revision a session that replaces its list revises its plan. A changed or removed step is relayed on the next
           message (relay.warn) to the children rooted at it, down, to the siblings whose step in progress shares
           its words, across, and to the parent, up. A child whose root step is removed is told its root is gone.
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


def addr(root, i):
    return f"{root}.{i}" if root else str(i)


def root_of(home, s):
    """A session's root step: the address its brief names, else the parent's open step its brief's words match
    best, else the parent's step in progress now; '' for a top session or a parent with no plan. Siblings started
    in one step for different steps of the plan each get their own root."""
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
    """Apply one update_plan call -> (plan, the address that moved to in progress or '', the revision or None)."""
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
    """What the anchor keeps of a session's plan."""
    p = load(home, sid)
    if not p.get("steps"):
        return {}
    return {"root": p.get("root", ""), "current": p.get("current", ""), "version": p.get("version", 0),
            "steps": [{"addr": x["addr"], "content": x.get("content", "")[:200], "status": x.get("status", ""),
                       "tasks": [{"id": t.get("id"), "tool": t.get("tool", ""), "what": t.get("what", "")[:120],
                                  "status": t.get("status"), "heads": t.get("heads") or []} for t in x.get("tasks") or []
                                 if t.get("status") == "open"]}
                      for x in p["steps"]]}


def record(home, s, inp, transcript=""):
    """The PostToolUse hook's work for one update_plan call -> the additionalContext text, '' for none."""
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
    for st in plan.get("steps") or []:            # a task stays with its step's words, not its number (P6)
        if st.get("content", "") in keep:
            st["tasks"] = keep[st["content"]]
            placed.add(st["content"])
    for st in plan.get("steps") or []:            # SA1: a step reworded in place keeps its tasks by address
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
    relay.make_anchor(home, parent, _now())       # the parent's anchor, or the root's for a top session
    relay.make_anchor(home, sid, _now())
    if revision:
        relay_revision(home, s, plan, revision)
    return boundary(home, s, plan, started, transcript) if started else ""


def _now():
    import time
    return time.strftime("%Y-%m-%d %H:%M")


def _siblings(home, s):
    return relay._siblings(home, s)


def _children(home, sid):
    return {k: v for k, v in relay._sessions(home).items() if relay._parent(v) == sid and not relay.gone(home, v)}


def relay_revision(home, s, plan, rev):
    """A revised plan, told on the next message to whoever owns or uses what changed."""
    sid, title = s["sessionId"], relay._title(s)
    stamp = hashlib.sha1(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:10]
    new = {x["addr"]: x["content"] for x in plan.get("steps") or []}
    for kid, ks in _children(home, sid).items():
        r = str(ks.get("rootStep") or "")
        if r in (rev.get("moved") or {}):
            relay.warn(home, kid, f"plan:{sid}:{stamp}:moved",
                       f"your root step {r} in the plan of \"{title}\" is now numbered {rev['moved'][r]}; the step "
                       f"itself is unchanged.")
        if r in rev["removed"]:
            relay.warn(home, kid, f"plan:{sid}:{stamp}:gone",
                       f"your root step {r}, \"{relay._short(rev['was'][r], 160)}\", was removed from the plan of "
                       f"\"{title}\", the session that started you. Stop before the next tool and message {sid}: "
                       f"your work may no longer be wanted.")
        elif r in rev["changed"]:
            was, now_ = relay._short(rev["was"][r], 160), relay._short(new[r], 160)
            relay.warn(home, kid, f"plan:{sid}:{stamp}:{r}",
                       f"your root step {r} in the plan of \"{title}\" was revised from \"{was}\" to \"{now_}\". "
                       f"Check whether your steps still serve it.")
    touched = rev["changed"] + rev["removed"]
    for oid, os_ in _siblings(home, s).items() if touched else []:
        cur = step_of(load(home, oid), load(home, oid).get("current") or "")
        if not cur:
            continue
        hits = [a for a in touched if bears(rev["was"][a], cur.get("content")) or bears(new.get(a, ""), cur.get("content"))]
        if hits:
            relay.warn(home, oid, f"plan:{sid}:{stamp}:across",
                       f"\"{title}\" revised step(s) {', '.join(hits)} of its plan, which share words with your step "
                       f"{cur['addr']}, \"{relay._short(cur.get('content'), 120)}\": "
                       + "; ".join(f"{a}: \"{relay._short(rev['was'][a], 100)}\" -> "
                                   f"\"{relay._short(new.get(a, 'removed'), 100)}\"" for a in hits) + ".")
    parent = relay._parent(s)
    if parent and touched:
        relay.warn(home, parent, f"plan:{sid}:{stamp}:up",
                   f"\"{title}\", started for " + (f"your step {plan['root']}" if plan.get("root") else
                                                     "a step you have no plan for") + ", revised its plan: "
                   + ", ".join(f"{a} {'removed' if a in rev['removed'] else 'changed'}" for a in touched) + ".")


def boundary(home, s, plan, started, transcript=""):
    """What bears on the step that starts now: up, across, down, the background tasks something moved under, and
    the warnings kept for this session."""
    sid = s["sessionId"]
    if transcript:
        pickup(home, sid, transcript_tail(transcript))
        plan = load(home, sid) or plan
    step = step_of(plan, started) or {}
    text = step.get("content", "")
    task_lines, moved = check_tasks(home, s, plan)     # flagged first, so a step just closed over one is caught
    lines = [f"task: {x}" for x in task_lines]
    for st in plan.get("steps") or []:
        if st.get("status") == "completed" and st["addr"] != started:
            for t in flagged_open(plan, st["addr"]):
                if not t.get("doneSaid"):
                    t["doneSaid"] = True
                    lines.append(f"step {st['addr']} was marked done while task {t['id']} under it is flagged and "
                                 f"still open; say so in that step's report, or stop the task.")
    if moved or any(t.get("doneSaid") for _, t in _tasks(plan)):
        relay._write_json(_path(home, sid), plan)
    path = os.path.join(relay._dir(home, sid), "session.json")
    disk = relay._read_json(path)
    for w in disk.get("relayPending") or []:
        if isinstance(w, dict):
            lines.append(w["text"])
            disk.setdefault("relayWarned", []).append(w.get("key"))
    disk["relayPending"] = []
    parent = relay._parent(s)
    root = plan.get("root") or ""
    if parent and root:
        pp = load(home, parent)
        ps = step_of(pp, root)
        if ps is None and pp.get("steps"):
            lines.append(f"up: your root step {root} is no longer in the parent's plan.")
        elif ps is not None:
            relayed = any(f"your root step {root} " in x for x in lines)   # P1: the relayed revision said it
            if plan.get("rootText") and ps.get("content") != plan.get("rootText") and not relayed:
                lines.append(f"up: the parent revised your root step {root} to \"{relay._short(ps.get('content'), 160)}\" "
                             f"since you started on it.")
            if ps.get("status") == "completed" or (pp.get("current") and pp.get("current") != root
                                                   and _after(pp.get("current"), root)):
                lines.append(f"up: the parent has moved past your root step {root}; it is on {pp.get('current') or 'none'}.")
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
    told = disk.setdefault("upTold", [])         # P1: an up line is said once, not at every boundary after
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
# At a plan's first whole list and at each revision, the open steps are judged: a step that names no path another
# step names, has no wording that leans on another step and is more than a quick thing can run as its own child
# session. Two or more such steps are named in one line; the rest stay here as sub-steps.

DEPENDS = re.compile(r"\b(after|then|once|using|uses|based on|depends? on|following|built on|with the results?|"
                     r"results? of|output of|from (?:the )?(?:step|previous|last)|step \d+)\b", re.I)
WAITS = re.compile(r"\b(wait(?:s|ing)?|until|confirm\w*|verif\w*|can go|when\b[^.]*\blands?|tell|notify|relay\w*|"
                   r"send|ask|hand (?:off|over)|report back)\b", re.I)   # SP2: a step that waits on or relays work
QUICK_WORDS = 4               # a step of fewer content words is a quick thing, done here
LANDS = re.compile(r"^\W*(?:run\b[^,.;]*\b(?:tests?|suites?|checks?)|report|wrap)\b"
                   r"|^\W*(?:tests?|verify|check|review)\b(?!\s*#?\d)(?=[^.;:]*\b(?:own|landed|merged|committed|"
                   r"pushed|work|changes?|diff|results?|commits?|suites?|tests?|build|outcome|fix(?:es)?|it|them)\b)"
                   r"|\b(?:commit|merge|push|ship|release|land|fast-forward)\b", re.I)
# checks or lands the session's own work. A check of anything else is work: "Check 1: nothing hidden in AppData" was
# kept on a top session as landing work, though it was one of the checks its children were for
ORCHESTRATES = re.compile(r"^\W*(?:start|run|kick\s*off|launch)\s+(?!writing|adding|implementing|making)"
                          r"(?:[\w'’-]+\s+){0,5}?(?:checks?|tests?|sessions?)\b", re.I)
# starts a check, test or session, which is orchestration: "Start the owner's-eye acceptance check" was advised as work
MANAGES = re.compile(r"\b(?:un)?(?:archiv|relay|messag|start|stop|review|check|brief|spawn|ask|tell|nudg|queu|send|"
                     r"sent|pass|hand)\w*\b"
                     r"[^.;]*?\b(?:child(?:ren)?|(?:sub-?)?sessions?)\b", re.I)   # manages a child session: orchestration


def judge(plan, cwd):
    """The open steps -> (those that can each run on their own, [(address, why it stays)])."""
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
            kept.append((a, f"leans on another step (\"{dep.group(0)}\")"))
        elif wait:
            kept.append((a, f"waits on or relays other work (\"{wait.group(0)}\")"))
        elif LANDS.search(text):
            kept.append((a, "checks or lands the other steps' work"))
        elif ORCHESTRATES.search(text):
            kept.append((a, "starts a check, test or session, which is orchestration"))
        elif MANAGES.search(text):
            kept.append((a, "manages a child session"))
        elif shared:
            kept.append((a, f"shares {relay.show(shared[0][1], cwd)} with step {shared[0][0]}"))
        elif len(words(text)) < QUICK_WORDS:
            kept.append((a, "a quick thing"))
        elif not paths[a]:
            kept.append((a, "names no file, so it cannot be judged apart from the others"))
        else:
            free.append(st)
    waits = sum(1 for _, why in kept if why.startswith("waits on"))
    if steps and waits * 2 >= len(steps):          # SP2: a plan of waits and relays is serial as a whole
        kept += [(st["addr"], "the plan is mostly waits and relays, so serial") for st in free]
        free = []
    return free, kept


def split_advice(home, s, plan, owner_turn, cap):
    """One line naming the steps that can each run as a child session, said once per set; '' when fewer than two."""
    free, kept = judge(plan, s.get("cwd") or "")
    if len(free) < 2:
        return ""
    path = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(path)
    told = [x for x in disk.get("splitAdvised") or [] if isinstance(x, str)]
    new = [st for st in free if st.get("content", "") not in told]
    if not new:
        return ""                                 # SP1: a step advised once is never advised again
    disk["splitAdvised"] = s["splitAdvised"] = told + [st.get("content", "") for st in new]
    relay._write_json(path, disk)
    free = new
    named = "; ".join(f"{st['addr']} \"{relay._short(st.get('content'), 90)}\"" for st in free)
    judged = ("Judged by the paths each step names, and a step naming none stays; wording that leans on another "
              "step (after, then, once, using, the result of, step N) or waits on or relays work; and size: fewer "
              "than four content words is a quick thing.")
    if cap:
        return (f"phi (p4-phi): steps {named} could each run on their own, but {cap[0].lower() + cap[1:]} "
                f"Every step stays here as a sub-step. {judged}")
    route = ("Start each now with `mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, "
             "`use_worktree: false`, on this session's branch" if owner_turn else
             "This turn was started by another session, so the app refuses `user_asked`: write each as a start "
             "request, `phi.py request \"<title>\" --brief \"<the whole brief>\"`, which the next turn the user "
             "begins, in any session of this store, starts as this session's child; ask the user nothing")
    stay = ("; ".join(f"{a} ({why})" for a, why in kept)) or "none"
    return (f"phi (p4-phi): steps {named} can each run on their own: no path another step names, nothing leaning "
            f"on another step, more than a quick thing. {route}; one child per step, its brief that step's slice: "
            f"the step's words, its paths and what it must leave done. Staying here as sub-steps: {stay}. {judged}")


# --- the top session orchestrates ----------------------------------------------------------------------------------
#
# A session with no parent keeps itself free for orchestration: planning, relaying between sessions, decisions with
# the user, and landing work. Every work step of its plan goes to a fresh child, not only the independent ones; a run
# of serial work steps (one leaning on the step before it, or sharing a path with it) is one child that does them in
# order. A step that checks or lands work (test-and-commit, merge, push, release), waits on and relays work, or
# manages a child session (archives, relays to, messages, starts, reviews or checks one) stays.

def top_groups(plan, cwd):
    """The open steps of a top session's plan -> ([[work steps one child does in order]], [(address, why it stays)])."""
    steps = [st for st in plan.get("steps") or [] if st.get("status") != "completed"]
    groups, kept, run = [], [], []
    for st in steps:
        text = st.get("content", "")
        wait = WAITS.search(text)
        if LANDS.search(text):
            kept.append((st["addr"], "checks or lands the work"))
        elif ORCHESTRATES.search(text):
            kept.append((st["addr"], "starts a check, test or session, which is orchestration"))
        elif MANAGES.search(text):
            kept.append((st["addr"], "manages a child session, which is orchestration"))
        elif wait:
            kept.append((st["addr"], f"waits on or relays work (\"{wait.group(0)}\")"))
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


def top_advice(home, s, plan, owner_turn, cap):
    """The top session's line: each work step, or run of serial ones, to one fresh child; said once per set. ''
    when no work step is new."""
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

    def child(g):
        if len(g) == 1:
            return f"step {g[0]['addr']} \"{relay._short(g[0].get('content'), 90)}\""
        return (f"steps {', '.join(st['addr'] for st in g)} in order, as one child: "
                + ", ".join(f"\"{relay._short(st.get('content'), 70)}\"" for st in g))
    named = "; ".join(f"({chr(97 + k)}) {child(g)}" for k, g in enumerate(new[:26]))
    head = ("phi (p4-phi): this is the top session of its tree, so it keeps itself free for orchestration: "
            "planning, relaying between sessions, decisions with the user, and landing the work, meaning merge and push.")
    stay = ("; ".join(f"{a} ({why})" for a, why in kept)) or "none"
    if cap:
        return (f"{head} Its work steps would each go to a child: {named}. But {cap[0].lower() + cap[1:]} "
                f"Staying here meanwhile: every step.")
    route = ("Start each now with `mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, "
             "`use_worktree: false`, on this session's branch" if owner_turn else
             "This turn was started by another session, so the app refuses `user_asked`: write each as a start "
             "request, `phi.py request \"<title>\" --brief \"<the whole brief>\"`, which the next turn the user "
             "begins, in any session of this store, starts as this session's child; ask the user nothing")
    return (f"{head} Hand its work steps to child sessions, one child each: {named}. {route}. Each brief is its "
            f"steps' words, their paths and what they must leave done, and says \"archive when done\", so the child "
            f"leaves its outcome here as a replaces: note and is named for archiving when it finishes. Staying "
            f"here: {stay}.")


# --- sub-agents as child nodes of the step that launched them ------------------------------------------------------
#
# A sub-agent's hook payloads carry the launching session's session_id and the sub-agent's own agent_id (measured
# by the marketplace test session, 2026-11-12). At the Agent call it is a pending node under the step in progress,
# given that step's slice in its prompt; its first tool call binds its id to the node; each later call is warned of
# what changed beside the launching session since; its stop attaches its result. The node is a task of the step, so
# the anchor carries it to the parent like any background task.

PENDING_S = 3600              # a launch no tool call bound within this long is dropped


def _agent(p, agent_id):
    return next((t for _, t in _tasks(p) if t.get("id") == agent_id), None)


def agent_launch(home, s, tool_use_id, inp):
    """The Agent call, before it runs: a pending node under the step in progress -> the text for its prompt."""
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
    head = (f"phi (p4-phi): you are a sub-agent of \"{relay._title(s)}\", launched for its step {st['addr']}, "
            f"\"{relay._short(st.get('content'), 200)}\". Keep to that step; what you find goes back in your result.")
    piece = relay.slice_text(home, {"sessionId": "agent", "spawnedFrom": {"sessionId": parent}, "task": prompt,
                                    "cwd": s.get("cwd") or ""}) if parent else ""
    return "\n".join(x for x in (head, piece) if x)


def agent_bind(home, s, agent_id):
    """A sub-agent's tool call: its id bound to the oldest pending launch -> True when newly bound."""
    import time as _t
    sid = s["sessionId"]
    p = load(home, sid)
    if not agent_id or _agent(p, agent_id):
        return False
    pend = p.get("agentsPending") or {}
    key = min(pend, key=lambda k: int(pend[k].get("epoch") or 0)) if pend else None
    got = pend.pop(key) if key else {"step": p.get("current") or "", "anchorSeen": 0, "what": "a sub-agent"}
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
    parent = relay._parent(s)                     # SA2: the anchors carry it now, and the parent is told its id
    relay.make_anchor(home, parent, _now())
    relay.make_anchor(home, sid, _now())
    if parent:
        where = f"its step {st['addr']}" if st else "no step of its plan"
        relay.warn(home, parent, f"agent:{sid}:{agent_id}",
                   f"down: \"{relay._title(s)}\" launched sub-agent {agent_id} for {where}"
                   + (f", \"{relay._short(task['what'], 120)}\"" if task.get("what") else "") + ".")
    return True


def agent_warn(home, s, agent_id):
    """A sub-agent's next tool call: what changed beside the launching session since it was launched or last told,
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
    if v > seen:
        for nid, at in sorted((anchor.get("changedAt") or {}).items()):
            if nid == sid or int(at or 0) <= seen:
                continue
            n = (anchor.get("nodes") or {}).get(nid) or {}
            marks = [m.get("claim") for m in n.get("marks") or []][-2:]
            files = (n.get("files") or [])[:4]
            said = "; ".join(relay._short(x, 200) for x in marks) or (
                "changed " + ", ".join(relay.show(f, s.get("cwd") or "") for f in files) if files else "")
            if said:
                lines.append(f"\"{n.get('title') or nid}\": {said}")
    step = next((st for st in p.get("steps") or [] for x in st.get("tasks") or [] if x is t), None)
    if t.get("stepText") and step is None:
        lines.append("the step you were launched for is no longer in the launching session's plan")
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


def agent_stop(home, s, agent_id, result):
    """The sub-agent stopped: its node closed with its result -> True when a node was closed."""
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
    """True when address a comes after address b in the parent's plan."""
    def key(x):
        return [int(p) for p in str(x).split(".") if p.isdigit()]
    return key(a) > key(b)


def slice_for(home, s):
    """A fresh child's root step and its slice of the parent's plan tree: the steps around the root, and the
    siblings' steps in progress that share its words. '' when the child has no root."""
    root = root_of(home, s)
    parent = relay._parent(s)
    if not root or not parent:
        return ""
    pp = load(home, parent)
    steps = pp.get("steps") or []
    at = next((k for k, x in enumerate(steps) if x["addr"] == root), None)
    if at is None:
        return f"phi (p4-phi): this session is for step {root} of its parent's plan, which no longer holds it."
    around = steps[max(0, at - 1):at + 2]
    out = [f"phi (p4-phi): this session is for step {root} of its parent's plan, \"{relay._short(steps[at]['content'], 200)}\"."
           " Its own steps are numbered under it: " + addr(root, 1) + ", " + addr(root, 2) + ", and so on.",
           "The parent's plan around it:"]
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
# The miss of 2026-11-12 that this closes: a parent told the user which of a child's checks its new design would void,
# in a plain turn report, and never told the child. Notes and plan changes were relayed; the report was not.

SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# R6: a report that quotes what phi told the session would be matched again and relayed again, growing each round.
# phi's own lines, and any sentence quoting them, are taken out of a report before it is matched.
OWN_LINE = re.compile(r"^\s*(?:[-*>`\"]\s*)*(?:phi \(p4-phi\)|p4-phi[ :(]|p4-temportal:|(?:up|across|down):)", re.I)
OWN_WORDS = ("phi (p4-phi)", "words bear on your open step", "check whether those steps still hold",
             "stop before any tool runs")


def own_removed(text):
    """`text` without phi's own relay lines and the sentences that quote them."""
    keep = [ln for ln in str(text or "").splitlines() if not OWN_LINE.match(ln)]
    sents = [x for x in SENTENCE.split("\n".join(keep)) if x.strip()]
    return "\n".join(x for x in sents if not any(w in x.lower() for w in OWN_WORDS))
ADDR_RE = re.compile(r"\b(?:step\s+)?(\d+(?:\.\d+)+|(?<=step )\d+)\b", re.I)


def open_steps(home, sid):
    """The steps of a session's plan not yet completed, with the background checks still open under them."""
    p = load(home, sid)
    return [x for x in p.get("steps") or [] if x.get("status") != "completed"]


FENCE = re.compile(r"```.*?(?:```|$)", re.S)
DRAWN = re.compile(r"[\u2500-\u257f]")             # box-drawing characters: a tree or table drawn in a report


def prose(text):
    """`text` without fenced code blocks and drawn lines, whose addresses and words are no claim about a step."""
    text = FENCE.sub("\n", str(text or ""))
    return "\n".join(ln for ln in text.splitlines() if not DRAWN.search(ln))


def matches(text, steps, shard, base, loose=True):
    """[(step, the sentences of `text` that bear on it)]: a step is matched by its address, by a path in the
    session's shard, or by sharing SHARE content words with a sentence. Code blocks and drawn trees are left out."""
    text = prose(text)
    sents = [x.strip() for x in SENTENCE.split(str(text or "")) if x.strip()]
    named = set(ADDR_RE.findall(str(text or "")))
    out = []
    for st in steps:
        hit = []
        for x in sents:
            if st["addr"] in set(ADDR_RE.findall(x)) or (loose and bears(x, st.get("content"))) or any(
                    relay.overlap(p, sh) for p in relay.paths_in(x, base) for sh in shard):
                hit.append(x)
            for t in st.get("tasks") or []:
                if loose and t.get("status") == "open" and bears(x, t.get("what")) and x not in hit:
                    hit.append(x)
        if st["addr"] in named and not hit:
            hit = [x for x in sents if st["addr"] in x][:2]
        if hit:
            out.append((st, hit[:3]))
    return out


# A parent's report that shares words with a child's step is relayed to the child, but the parent is nagged that it
# sent nothing only when the sentence changes the step: a progress report that names the child's work is no change.
CHANGES = re.compile(r"\b(?:void\w*|replac\w*|deprecat\w*|supersed\w*|no longer|instead|drop(?:s|ped)?|"
                     r"remov\w*|cancel\w*|revis\w*|renam\w*|obsolete|wrong|broke\w*|stop(?:s|ped)?|undo\w*|"
                     r"revert\w*|redo|rework\w*)\b", re.I)


def turn_relay(home, s, row, calls):
    """At Stop: the turn's report and plan, matched against the open steps of this session's children (down) and of
    its siblings (across). Each match is relayed with the turn's own words quoted. Returns the children a match
    reached that the turn sent no SendMessage to, as [(child id, addresses)], for the parent's next message."""
    sid, title = s["sessionId"], relay._title(s)
    report = own_removed(row.get("report"))
    mine = load(home, sid)
    step = "\n".join(f"{x['addr']} {x.get('content', '')}" for x in mine.get("steps") or []
                     if x.get("status") == "in_progress")
    if not report.strip():
        return []
    path = os.path.join(relay._dir(home, sid), "session.json")
    disk = relay._read_json(path)
    if step and step == disk.get("stepRelayed"):
        step = ""                                 # R7: an unchanged step was matched and relayed again every turn
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
        got = matches(text, open_steps(home, oid), relay.shard_of(os_), os_.get("cwd") or s.get("cwd") or "")
        if not got:
            continue
        lines = [f"{st['addr']} \"{relay._short(st.get('content'), 100)}\": " +
                 " ".join(f"\"{relay._short(q, 220)}\"" for q in quotes) for st, quotes in got]
        who = "the session that started you" if way == "down" else "a session beside you"
        relay.warn(home, oid, f"turn:{sid}:{stamp}",
                   f"\"{title}\", {who}, ended a turn whose words bear on your open step(s): " + "; ".join(lines)
                   + ". Check whether those steps still hold.")
        strict = {st["addr"] for st, _ in matches(text, open_steps(home, oid), relay.shard_of(os_),
                                                  os_.get("cwd") or s.get("cwd") or "", loose=False)}
        named = [st["addr"] for st, quotes in got
                 if st["addr"] in strict or any(CHANGES.search(q) for q in quotes)]
        if way == "down" and named and oid not in sent and ("local_" + oid.removeprefix("local_")) not in sent:
            unsent.append((oid, named))   # a step named by address or path, or words that change it, not progress
    parent = relay._parent(s)
    ask = waiting_on(report)
    if parent and ask:
        relay.warn(home, parent, f"wait:{sid}:{stamp}",
                   f"\"{title}\", a session you started, ended its turn on a question: \"{relay._short(ask, 240)}\". "
                   f"It names no matter of the user's authority, so answer it with SendMessage (`to`: {sid}) "
                   f"from what the chain knows, rather than leaving it waiting.")
    return unsent


AUTHORITY = re.compile(r"\b(push|force|merge|publish|post|deploy|release|credential|password|token|secret|api key|"
                       r"permission|sign[ -]?in|log[ -]?in|spend|pay|purchase|billing|delete|destroy|drop|"
                       r"irreversible|cannot be undone|restart|install)\w*", re.I)


def waiting_on(report):
    """The question a turn's report ends on, when it is not a matter of the user's authority; '' otherwise."""
    tail = str(report or "").strip()[-600:]
    qs = [q.strip() for q in re.findall(r"[^.!?\n]*\?", tail) if len(q.strip()) > 8]
    if not qs or not tail.rstrip().endswith("?") and tail.rfind("?") < len(tail) - 200:
        return ""
    q = qs[-1]
    return "" if AUTHORITY.search(q) else q


# --- background tasks under a step -------------------------------------------------------------------------------------
#
# A step's background work, a Bash run in the background, a Monitor, an Agent or a Workflow, is recorded under the step
# in progress with what it ran against: the heads of the repositories its command names, its paths and its words. At
# each step boundary an open task is checked against what moved since it started. Found 2026-11-12 in this session's
# own transcript and phi's log: a completion notice that arrives while the session is idle starts a turn, and
# UserPromptSubmit fires with the notice as its message; one that arrives during a turn is queued as an attachment and
# no hook fires. So completions are read from the message at UserPromptSubmit, and from the transcript's tail at Stop
# and at each step boundary.

TASK_ID = re.compile(r"(?:background with ID|task[_ -]?id|agentId|ID)[\"':\s=]+([A-Za-z0-9_-]{6,})"
                     r"|\(task\s+([A-Za-z0-9_-]{6,})", re.I)      # M1: "Monitor started (task bz4dv0pvj, ..."
NOTICE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>.*?<status>\s*([^<\s]+)\s*</status>"
                    r"(?:.*?<summary>(.*?)</summary>)?", re.S)
NEAR_DONE_S = 600             # a task older than this may be near done: finish and record rather than stop
JOB_GAP_S = 3600              # the job-gap budget: an open task this far past its own timeout with no notice read is
                              # taken as unknown, never flagged (a stopped task, an expired Monitor, a lost notice)
STOPPED = re.compile(r'"name"\s*:\s*"(?:TaskStop|KillShell)"\s*,\s*"input"\s*:\s*\{[^{}]*?'
                     r'"(?:task_id|shell_id|id)"\s*:\s*"([A-Za-z0-9_-]{6,})"')
BACKGROUND_AGENT = re.compile(r"(?:launched|running|runs) in the background|async agent|run_in_background", re.I)


def register(home, s, tool, inp, response, cwd, at_epoch=None):
    """Record a background task under the step in progress -> the task, or None when the call ran in the
    foreground or names no task id."""
    if tool == "Bash" and not inp.get("run_in_background"):
        return None
    if tool == "Agent" and not inp.get("run_in_background") and not BACKGROUND_AGENT.search(str(response)):
        return None                               # a foreground agent has finished by its result
    text = response if isinstance(response, str) else json.dumps(response, default=str)
    m = TASK_ID.search(text)
    if not m:
        return None
    what = str(inp.get("command") or inp.get("prompt") or inp.get("description") or inp.get("name") or tool)
    paths = relay.paths_in(what, cwd)
    repos = {relay.repo_of(p) for p in paths} | ({relay.repo_of(cwd)} if cwd else set())
    task = {"id": m.group(1) or m.group(2), "tool": tool, "what": relay._short(what, 200), "heads": relay.heads(repos),
            "paths": paths, "status": "open"}
    limit = inp.get("timeout_ms") or inp.get("timeout")
    if isinstance(limit, (int, float)) and limit > 0:
        task["timeoutS"] = int(limit / 1000) if inp.get("timeout_ms") or limit > 100000 else int(limit)
    import time as _t
    epoch = int(at_epoch or _t.time())
    task["epoch"], task["at"] = epoch, _t.strftime("%Y-%m-%d %H:%M", _t.localtime(epoch))
    if any(t.get("id") == task["id"] for _, t in _tasks(load(home, s["sessionId"]))):
        return None                               # the same launch read twice
    sid = s["sessionId"]
    p = load(home, sid)
    st = step_of(p, p.get("current") or "") if p.get("steps") else None
    if st is None:
        p.setdefault("loose", []).append(task)
    else:
        st.setdefault("tasks", []).append(task)
    relay._write_json(_path(home, sid), p)
    return task


def _tasks(p):
    for st in p.get("steps") or []:
        for t in st.get("tasks") or []:
            yield st, t
    for t in p.get("loose") or []:
        yield None, t


def pickup(home, sid, text):
    """Completion notices in `text`, a message or a transcript's tail, closed on their tasks -> the ids closed."""
    p = load(home, sid)
    closed = []
    found = {m.group(1): (m.group(2).lower(), (m.group(3) or "").strip()) for m in NOTICE.finditer(str(text or ""))}
    for m in STOPPED.finditer(str(text or "")):   # RB1: a TaskStop sends no notice; its call closes the task
        found.setdefault(m.group(1), ("stopped", "stopped by TaskStop"))
    if not found:
        return closed
    for st, t in _tasks(p):
        if t.get("id") in found and t.get("status") == "open":
            t["status"], t["result"] = found[t["id"]][0], relay._short(found[t["id"]][1], 300)
            closed.append(t["id"])
    if closed:
        relay._write_json(_path(home, sid), p)
    return closed


def transcript_tail(path, size=200000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - size))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def check_tasks(home, s, plan):
    """The open tasks something moved under since they started -> lines with the id and what to do."""
    import time as _t
    lines, changed = [], False
    parent = relay._parent(s)
    anchor = relay._read_json(relay.anchor_path(home, parent)) if parent else {}
    marks = [(nid, n.get("title") or nid, m) for nid, n in (anchor.get("nodes") or {}).items()
             if nid != s["sessionId"] for m in n.get("marks") or []]
    for st, t in _tasks(plan):
        if t.get("status") != "open":
            continue
        if _t.time() - int(t.get("epoch") or 0) > int(t.get("timeoutS") or 0) + JOB_GAP_S:
            t["status"] = "unknown"               # past its budget with no notice read: finished, stopped or expired
            changed = True
            continue
        if st is None:
            continue                              # a loose task has no step to be checked against
        why = []
        for h in t.get("heads") or []:
            repo, _, rest = h.partition("@")
            now_h = next(iter(relay.heads({repo})), "")
            if now_h and now_h != h:
                why.append(f"the head it ran against moved: {relay.show_head(h, s.get('cwd') or '')} is now "
                           f"{relay.show_head(now_h, s.get('cwd') or '')}")
        for nid, title, m in marks:
            if str(m.get("time") or "") < str(t.get("at") or ""):
                continue
            if any(relay.overlap(a, b) for a in m.get("paths") or [] for b in t.get("paths") or []) or \
                    bears(m.get("claim"), t.get("what")):
                why.append(f"\"{title}\" wrote \"{relay._short(m.get('claim'), 200)}\"")
        if not why:
            continue
        key = hashlib.sha1("|".join(why).encode()).hexdigest()[:10]
        if key in (t.get("flags") or []):
            continue
        t.setdefault("flags", []).append(key)
        changed = True
        age = _t.time() - int(t.get("epoch") or 0)
        advice = (f"it has run {int(age // 60)} min and may be near done: let it finish and record its result as "
                  f"against the old head" if age > NEAR_DONE_S else
                  f"`TaskStop {t['id']}`, then re-run it against the new head if it is still wanted")
        lines.append(f"task {t['id']} ({t.get('tool')}: {relay._short(t.get('what'), 80)}): " + "; ".join(why)
                     + f". {advice}.")
    return lines, changed


def flagged_open(plan, addr):
    st = step_of(plan, addr) or {}
    return [t for t in st.get("tasks") or [] if t.get("status") == "open" and t.get("flags")]
