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
    """A session's root step: the address its brief names, else its parent's step in progress now; '' for a top
    session or a parent with no plan."""
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
                       "tasks": [{"id": t.get("id"), "what": t.get("what", "")[:120], "status": t.get("status"),
                                  "heads": t.get("heads") or []} for t in x.get("tasks") or []
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
    keep = {st["addr"]: st.get("tasks") for st in old.get("steps") or [] if st.get("tasks")}
    plan, started, revision = apply(old, inp, root or "")
    for st in plan.get("steps") or []:            # a step's background tasks stay with it across a call
        if st["addr"] in keep:
            st["tasks"] = keep[st["addr"]]
    if old.get("loose"):
        plan["loose"] = old["loose"]
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
    return {k: v for k, v in relay._sessions(home).items() if relay._parent(v) == sid}


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
                   f"\"{title}\", started for your step {plan.get('root') or '?'}, revised its plan: "
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
            if plan.get("rootText") and ps.get("content") != plan.get("rootText"):
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
    relay._write_json(path, disk)
    if not lines:
        return ""
    return (f"phi (p4-phi): step {started} starts now, \"{relay._short(text, 160)}\". What bears on it, so the step "
            f"may need revising before it runs:\n" + "\n".join(f"- {x}" for x in lines))


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
ADDR_RE = re.compile(r"\b(?:step\s+)?(\d+(?:\.\d+)+|(?<=step )\d+)\b", re.I)


def open_steps(home, sid):
    """The steps of a session's plan not yet completed, with the background checks still open under them."""
    p = load(home, sid)
    return [x for x in p.get("steps") or [] if x.get("status") != "completed"]


def matches(text, steps, shard, base):
    """[(step, the sentences of `text` that bear on it)]: a step is matched by its address, by a path in the
    session's shard, or by sharing SHARE content words with a sentence."""
    sents = [x.strip() for x in SENTENCE.split(str(text or "")) if x.strip()]
    named = set(ADDR_RE.findall(str(text or "")))
    out = []
    for st in steps:
        hit = []
        for x in sents:
            if st["addr"] in set(ADDR_RE.findall(x)) or bears(x, st.get("content")) or any(
                    relay.overlap(p, sh) for p in relay.paths_in(x, base) for sh in shard):
                hit.append(x)
            for t in st.get("tasks") or []:
                if t.get("status") == "open" and bears(x, t.get("what")) and x not in hit:
                    hit.append(x)
        if st["addr"] in named and not hit:
            hit = [x for x in sents if st["addr"] in x][:2]
        if hit:
            out.append((st, hit[:3]))
    return out


def turn_relay(home, s, row, calls):
    """At Stop: the turn's report and plan, matched against the open steps of this session's children (down) and of
    its siblings (across). Each match is relayed with the turn's own words quoted. Returns the children a match
    reached that the turn sent no SendMessage to, as [(child id, addresses)], for the parent's next message."""
    sid, title = s["sessionId"], relay._title(s)
    report = str(row.get("report") or "")
    mine = load(home, sid)
    text = report + "\n" + "\n".join(f"{x['addr']} {x.get('content', '')}" for x in mine.get("steps") or []
                                      if x.get("status") == "in_progress")
    if not report.strip():
        return []
    sent = set()
    for c in calls or []:
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        if str(c.get("name") or "").endswith("SendMessage") and inp.get("to"):
            sent.add(str(inp["to"]))
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
        if way == "down" and oid not in sent and ("local_" + oid.removeprefix("local_")) not in sent:
            unsent.append((oid, [st["addr"] for st, _ in got]))
    return unsent


# --- background tasks under a step -------------------------------------------------------------------------------------
#
# A step's background work, a Bash run in the background, a Monitor, an Agent or a Workflow, is recorded under the step
# in progress with what it ran against: the heads of the repositories its command names, its paths and its words. At
# each step boundary an open task is checked against what moved since it started. Found 2026-11-12 in this session's
# own transcript and phi's log: a completion notice that arrives while the session is idle starts a turn, and
# UserPromptSubmit fires with the notice as its message; one that arrives during a turn is queued as an attachment and
# no hook fires. So completions are read from the message at UserPromptSubmit, and from the transcript's tail at Stop
# and at each step boundary.

TASK_ID = re.compile(r"(?:background with ID|task[_ -]?id|agentId|ID)[\"':\s=]+([A-Za-z0-9_-]{6,})", re.I)
NOTICE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>.*?<status>\s*([^<\s]+)\s*</status>"
                    r"(?:.*?<summary>(.*?)</summary>)?", re.S)
NEAR_DONE_S = 600             # a task older than this may be near done: finish and record rather than stop


def register(home, s, tool, inp, response, cwd):
    """Record a background task under the step in progress -> the task, or None when the call ran in the
    foreground or names no task id."""
    if tool == "Bash" and not inp.get("run_in_background"):
        return None
    if tool == "Agent" and not inp.get("run_in_background") and "background" not in str(response).lower():
        return None
    text = response if isinstance(response, str) else json.dumps(response, default=str)
    m = TASK_ID.search(text)
    if not m:
        return None
    what = str(inp.get("command") or inp.get("prompt") or inp.get("description") or inp.get("name") or tool)
    paths = relay.paths_in(what, cwd)
    repos = {relay.repo_of(p) for p in paths} | ({relay.repo_of(cwd)} if cwd else set())
    task = {"id": m.group(1), "tool": tool, "what": relay._short(what, 200), "heads": relay.heads(repos),
            "paths": paths, "at": _now(), "epoch": int(__import__("time").time()), "status": "open"}
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
