#!/usr/bin/env python3
"""puppeteer.py: p4's four P's on the session tree (#38), built to the four diagrams of ezexe/p4's README.md.

p4 is named for prompty, prompter, pioneer and puppeteer. Here each is a step phi takes for an orchestrator, a top
session or any session that started sessions:

  linear     prompty reads ezexe's message against the ledger: the area it names, the live session that owns that
             area, the writer that holds its files. prompter drafts the exact next session: its topic, a brief built
             from ezexe's words, its parent, fork or fresh, the issue it closes. pioneer gate-checks the draft: the
             issue exists or will be filed, no running writer holds the same files, the parent is the right
             orchestrator. A clean draft is handed as the exact start_session call; one whose area has a live owner
             is routed there with SendMessage; one whose writer is busy is queued as a start request behind it.
             The puppeteer is the watcher: one background process an orchestrator, writing <session>/ledger.md from
             phi's files and the app's session records, only when one of them changed, with a reconcile line at its
             top for each divergence between the two.
  recursive  a landed topic registers its route in <session>/routes.jsonl beside the ledger, only when the records
             back what the reports claimed: the issue is closed, a commit that closes it is pushed, and the session
             and its children are archived with their outcome kept. prompty scores a message against the registered
             routes before prompter drafts anything new; a route whose issue was reopened or whose commit was
             reverted is withdrawn.
  parallel   an under-determined message becomes one child a distinct reading. Each ends its report with a
             `Result:` line; the puppeteer merges them: readings that converge collapse to one result, and only a
             fork that survives the merge goes to ezexe, as one question with options and a default.
  meta       the top session that receives ezexe's message runs a meta pass over every top's ledger first and writes
             <home>/phi/meta-ledger.md: duplicate topics, tops in conflict over the same files or issue, stale
             topics, and what is left open for the next generation.

A hook cannot start a session or send a message, so pioneer's verdict is the exact call for the session to make,
and the session, which can tell a question from work, makes it or leaves it.

Commands, through phi.py: `ledger`, `watch`, `draft "<words>"`, `pioneer <draft id>`, `routes`, `readings "<a>"
"<b>" ... --words "<the message>"`, `merge <group> --result "<text>"`, `meta`.
Settings: phi.json `puppeteer` (false: off); P4_PHI_PUPPETEER=0 or 1 for one run; P4_PHI_WATCH=0 starts no watcher.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import relay  # noqa: E402
import plans  # noqa: E402
import starts  # noqa: E402
import issues  # noqa: E402

PHI = None                       # the running phi module, set by phi.py at import
WATCH_S = 5.0                    # the watcher's tick
WATCH_SLOW_S = 30.0              # its tick once nothing changed for WATCH_CALM_S
WATCH_CALM_S = 600.0
WATCH_QUIT_S = 24 * 3600.0       # a watcher whose sources stood still this long ends; the next hook starts another
BEAT_S = 30.0                    # how often a watcher says it is alive
BEAT_DEAD_S = 100.0              # a watcher silent this long is taken as gone
ISSUE_TTL_S = 120.0              # how long an issue's state read from GitHub is believed
GH_S = 6                         # one gh call of the puppeteer's, which a prompt hook may be waiting on
ROUTE_CHECK_S = 600.0            # how often registered routes are checked for a reopen or a revert
ROUTE_MIN = 4                    # content words a message shares with a route before it can match
ROUTE_CLOSE = 0.6                # of the smaller side's content words
OWNER_WORDS = 4                  # content words a message shares with a live session's task before that session owns it
TOPIC_WORDS = 3                  # content words a message shares with this session's task to be part of its topic
QUICK_WORDS = 6                  # a message of fewer content words is a quick thing, never drafted
STALE_S = 24 * 3600.0            # a top session with open work and no turn this long is stale
WORDS_CHARS = 1500               # of ezexe's words, quoted in a brief
STOP = frozenset("""phi session sessions p4 plugin plugins please make sure also just now then when with that this
there their them they have has should would could will want need like into from about your you our out get got use
using one two all any each every not and for the are was were been being its it's can may must more most some such
than too very what which who how why where while after before over under again new old""".split())
DRAFT_RE = re.compile(r"phi draft (drf-[0-9a-f]{10}) for (\S+?)\.?(?:\s|$)")
READING_RE = re.compile(r"phi reading (grp-[0-9a-f]{10}) (\d+) of (\d+) for (\S+?)\.?(?:\s|$)")
RESULT_RE = re.compile(r"(?im)^\W*result\W*:\s*(.+?)\s*$")
EITHER = re.compile(r"\beither\b\s+(.{6,200}?)\s*,?\s+\bor\b\s+(.{6,200}?)(?=[.?!;\n]|$)", re.I | re.S)
OR_MAYBE = re.compile(r"([^.?!;\n]{6,200}?)\s*,?\s+\bor (?:maybe|perhaps|else|instead)\b\s+([^.?!;\n]{6,200})", re.I)


def _phi():
    global PHI
    if PHI is None:
        import phi
        PHI = phi
    return PHI


def on(home=""):
    env = os.environ.get("P4_PHI_PUPPETEER")
    if env in ("0", "1"):
        return env == "1"
    return relay._read_json(os.path.join(home, "phi", "phi.json")).get("puppeteer") is not False if home else True


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def _short(s, n):
    return relay._short(s, n)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _append(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def words(text):
    return plans.words(text) - STOP


def share(a, b):
    """(shared content words, their share of the smaller side) of two texts."""
    wa, wb = words(a), words(b)
    both = wa & wb
    return len(both), (len(both) / min(len(wa), len(wb)) if wa and wb else 0.0)


# --- the tree ---------------------------------------------------------------------------------------------------------

def closed(s):
    """True when phi's own files hold a session as out of the live tree. Nothing is read from the app here, so a
    divergence between the two stays visible until it is reconciled."""
    return not isinstance(s, dict) or bool(s.get("stale") or s.get("doneRetired") or s.get("archived"))


def subtree(home, top, every=None):
    """[(sessionId, depth, session.json)] of a session and every session under it, in tree order."""
    every = relay._sessions(home) if every is None else every
    kids = {}
    for sid, s in every.items():
        kids.setdefault(relay._parent(s), []).append(sid)
    out, seen = [], set()

    def walk(sid, depth):
        if sid in seen or sid not in every or depth > 12:
            return
        seen.add(sid)
        out.append((sid, depth, every[sid]))
        for k in sorted(kids.get(sid, []), key=lambda k: (str(every[k].get("createdAt") or ""), k)):
            walk(k, depth + 1)
    walk(top, 0)
    return out


def orchestrator(home, s, every=None):
    """True for a session that pulls strings: a top session with a task, or any session that started sessions."""
    if not isinstance(s, dict) or not s.get("sessionId"):
        return False
    if not relay._parent(s):
        return bool(str(s.get("task") or "").strip())
    every = relay._sessions(home) if every is None else every
    return any(relay._parent(v) == s["sessionId"] for v in every.values())


def working(home, sid):
    """True while a session is inside a turn: its last prompt hook ran after its last Stop hook."""
    last = ""
    for r in _phi().read_rows(os.path.join(relay._dir(home, sid), "log.jsonl"), 256 * 1024):
        if r.get("hook") in ("user-prompt-submit", "stop"):
            last = r["hook"]
    return last == "user-prompt-submit"


def busy(home, sid):
    """True while a session is a running writer: live, and inside a turn or on a step in progress."""
    s = relay._session(home, sid)
    if not s or closed(s) or relay.gone(home, s):
        return False
    if working(home, sid):
        return True
    return any(x.get("status") == "in_progress" for x in plans.load(home, sid).get("steps") or [])


# --- the app's records ------------------------------------------------------------------------------------------------

_APP = {}                        # record path -> (mtime_ns, row), kept while a watcher runs


def app_roots(home, top):
    root = str(relay._session(home, top).get("appRoot") or "")
    if os.environ.get("P4_PHI_APP_SESSIONS"):
        return [os.environ["P4_PHI_APP_SESSIONS"]]
    return [root] if root and os.path.isdir(root) else _phi().app_roots()


def app_files(roots):
    out = []
    for root in roots:
        out += glob.glob(os.path.join(root, "*", "*", "local_*.json"))
    return sorted(out)


def app_index(roots):
    """{sessionId: {parent, archived, title, name}} of the app's session records, each file read once a change."""
    out = {}
    for p in app_files(roots):
        try:
            m = os.stat(p).st_mtime_ns
        except OSError:
            continue
        held = _APP.get(p)
        if not held or held[0] != m:
            d = relay._read_json(p)
            sp = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
            held = _APP[p] = (m, {"sessionId": str(d.get("sessionId") or ""), "parent": str(sp.get("sessionId") or ""),
                                  "archived": bool(d.get("isArchived")), "title": str(d.get("title") or "")[:120],
                                  "name": str(sp.get("name") or "")} if d.get("sessionId") else None)
        if held[1]:
            out[held[1]["sessionId"]] = held[1]
    return out


# --- issues -----------------------------------------------------------------------------------------------------------

def topic_issue(s, base=""):
    """(slug, number, repo path) of the issue a session's work closes: the one phi took for it, else the first its
    task names; ('', 0, '') for none."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if iss and iss.get("repo") and iss.get("number"):
        return str(iss["repo"]), int(iss["number"]), str(iss.get("path") or "")
    task = str(s.get("task") or "")
    m = re.search(r"\b([\w.-]+/[\w.-]+)#(\d+)\b", task)
    if m:
        repo = next((r for r, slug in issues.repos_named(task, base or s.get("cwd") or "")
                     if slug.lower() == m.group(1).lower()), "")
        return m.group(1), int(m.group(2)), repo
    for repo, slug in issues.repos_named(task, base or s.get("cwd") or "")[:1]:
        n = issues.named_issue(task, slug)
        if n:
            return slug, n, repo
    return "", 0, ""


def states_path(home):
    return os.path.join(home, "phi", ".issue-states.json")


_CHECKED = {}                    # "slug#n" -> when this process last read it from GitHub


def issue_state(home, slug, n, net=False):
    """An issue's state, 'OPEN', 'CLOSED' or '' when not known. Read from GitHub when `net` and this process read
    it more than ISSUE_TTL_S ago; otherwise what was last read. The kept file changes only when a state does, so
    it is a source a ledger can be rebuilt on."""
    key = f"{slug}#{n}"
    got = str(relay._read_json(states_path(home)).get(key) or "")
    if net and time.time() - _CHECKED.get(key, 0) > ISSUE_TTL_S:
        _CHECKED[key] = time.time()
        r = issues.gh(["issue", "view", str(n), "-R", slug, "--json", "state", "-q", ".state"], timeout=GH_S)
        state = (r.stdout or "").strip().upper() if r is not None and r.returncode == 0 else ""
        state = state if state in ("OPEN", "CLOSED") else ""
        if state and state != got:
            kept = relay._read_json(states_path(home))
            kept[key] = got = state
            relay._write_json(states_path(home), kept)
    return got


# --- the ledger -------------------------------------------------------------------------------------------------------

SOURCES = ("session.json", "plan.json", "turns.jsonl", "notes.jsonl", "reports.jsonl", "log.jsonl", "routes.jsonl")


def ledger_path(home, top):
    return os.path.join(relay._dir(home, top), "ledger.md").replace("\\", "/")


def model_path(home, top):
    return os.path.join(relay._dir(home, top), "ledger.json")


def _stat(p):
    try:
        st = os.stat(p)
        return f"{p}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        return f"{p}|-"


def signature(home, top, roots):
    """One hash over the modification times of everything a ledger is made from: every session.json, since any of
    them can join the subtree, the other files of the sessions in it, the start requests, the issue states last
    read, the readings, and the app's session records."""
    base = os.path.join(home, "phi", "sessions")
    parts = [_stat(base), _stat(starts.path_of(home)), _stat(states_path(home))]
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    parts += [_stat(os.path.join(base, n, "session.json")) for n in names]
    ids = set()
    for sid, _, _ in subtree(home, top):
        ids.add(sid)
        d = relay._dir(home, sid)
        parts += [_stat(os.path.join(d, f)) for f in SOURCES[1:]]
        parts += [_stat(p) for p in sorted(glob.glob(os.path.join(d, "readings", "*.json")))]
    # of the app's records: those of the subtree's sessions as they change, and the others by name, so a new one
    # counts once and another tree's activity leaves this ledger alone
    for p in app_files(roots):
        parts.append(_stat(p) if os.path.basename(p)[:-5] in ids else p)
    return hashlib.sha1("\n".join(parts).encode("utf-8", "replace")).hexdigest()


def outcome_kept(home, parent, sid):
    """True when the session above holds a closed child's outcome as a `replaces:` note."""
    mark = f"({sid})"
    return any(str(r.get("claim") or "").lstrip().startswith("replaces:") and mark in str(r.get("claim"))
               for r in relay._rows(os.path.join(relay._dir(home, parent), "notes.jsonl")))


def build(home, top, net=False):
    """The ledger of an orchestrator as data: its reconcile lines, a row a session of its subtree, their open
    background tasks, the start requests waiting, the issues tied to them, and the readings being merged."""
    phi = _phi()
    every = relay._sessions(home)
    tree = subtree(home, top, every)
    roots = app_roots(home, top)
    app = app_index(roots)
    ids = {sid for sid, _, _ in tree}
    rows, shut, tasks, tied, reconcile = [], [], [], {}, []
    for sid, depth, s in tree:
        title = phi.title_of(s)
        parent = relay._parent(s)
        rec = app.get(sid)
        if closed(s):
            if depth:
                how = "stale" if s.get("stale") else "finished and retired" if s.get("doneRetired") else "archived"
                shut.append({"sessionId": sid, "title": title, "parent": parent, "how": how,
                             "kept": outcome_kept(home, parent, sid)})
            continue
        root = str(s.get("appRoot") or "")
        if sid.startswith("local_") and root and os.path.isdir(root) and root in roots:
            if rec is None:
                reconcile.append(f"phi lists \"{title}\" ({sid}) as live, and the app holds no record of it.")
            elif rec["archived"]:
                reconcile.append(f"phi lists \"{title}\" ({sid}) as live, and the app has archived it.")
        held = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
        if rec and depth and rec["parent"] and rec["parent"] != parent \
                and held.get("source") not in ("detached", "reparented", "requested"):
            reconcile.append(f"the app shows \"{title}\" ({sid}) started by {rec['parent']}, and phi holds it under "
                             f"{parent}.")
        plan = plans.load(home, sid)
        steps = plan.get("steps") or []
        cur = next((x for x in steps if x.get("status") == "in_progress"), None)
        turns = phi.load_turns(home, sid)
        last = turns[-1] if turns else {}
        slug, n, _ = topic_issue(s)
        state = issue_state(home, slug, n, net) if n else ""
        if n:
            tied.setdefault(f"{slug}#{n}", {"state": state, "sessions": []})["sessions"].append(sid)
        rows.append({"sessionId": sid, "depth": depth, "title": title, "parent": parent,
                     "name": (rec or {}).get("name", ""), "working": working(home, sid),
                     "turns": len(turns), "lastTurn": str(last.get("time") or ""), "done": bool(last.get("done")),
                     "report": _short(last.get("report"), 160),
                     "result": (RESULT_RE.findall(str(last.get("report") or "")) or [""])[-1],
                     "step": {"addr": cur.get("addr"), "content": _short(cur.get("content"), 90)} if cur else None,
                     "stepsDone": sum(1 for x in steps if x.get("status") == "completed"), "steps": len(steps),
                     "open": [_short(x.get("content"), 90) for x in steps if x.get("status") != "completed"][:8],
                     "issue": f"{slug}#{n}" if n else "", "issueState": state,
                     "shard": relay.shard_of(s)[:6], "files": relay.edited_files(home, sid)[:40],
                     "task": _short(s.get("task"), 300), "reading": s.get("reading") or None})
        for st, t in plans._tasks(plan):
            if t.get("status") == "open":
                tasks.append({"id": str(t.get("id")), "tool": str(t.get("tool") or ""), "sessionId": sid,
                              "title": title, "step": (st or {}).get("addr", ""), "what": _short(t.get("what"), 120),
                              "at": str(t.get("at") or "")})
    live = {r["sessionId"] for r in rows}
    for aid, rec in sorted(app.items()):
        if rec["parent"] in live and not rec["archived"] and aid not in every:
            reconcile.append(f"the app shows \"{rec['title'] or aid}\" ({aid}) started by {rec['parent']}, and phi "
                             f"holds no session for it.")
    asked = []
    at = time.time()
    for r in starts.state(home).values():
        if r.get("requester") not in ids or r.get("started") or at - float(r.get("at") or 0) > starts.EXPIRE_S:
            continue
        behind = str(r.get("after") or "")
        how = (f"waits behind \"{phi.title_of(every.get(behind, {}))}\" ({behind})" if behind and busy(home, behind)
               else "claimed" if r.get("claimed") else "pending")
        asked.append({"id": r["id"], "title": r.get("title", ""), "requester": r.get("requester"), "state": how})
    groups = [g for sid in sorted(live) for g in load_groups(home, sid)]
    return {"top": top, "title": phi.title_of(every.get(top, {})), "parent": relay._parent(every.get(top, {})),
            "reconcile": reconcile, "rows": rows, "closed": shut, "tasks": tasks, "requests": asked,
            "issues": tied, "groups": groups}


def render(m):
    """A ledger's data as ledger.md. It carries no clock, so the same records give the same page."""
    where = f"started by `{m['parent']}`" if m["parent"] else "a top session"
    out = [f"# Ledger: {m['title']}", "",
           f"Puppeteer `{m['top']}`, {where}.",
           "Written by p4-phi's watcher from phi's files and the app's session records, and rewritten only when one "
           "of them changes.",
           "Edit nothing here: change the records.", ""]
    out += ["## Reconcile", ""]
    out += [f"- {x}" for x in m["reconcile"]] or ["- Nothing diverges: phi's files and the app's records agree."]
    out += ["", "## Sessions", ""]
    for r in m["rows"]:
        bits = ["working" if r["working"] else "idle"]
        if r["turns"]:
            bits.append(f"{r['turns']} turn{'s' * (r['turns'] != 1)}, the last at {r['lastTurn']}, "
                        + ("shown done" if r["done"] else "not shown done"))
        else:
            bits.append("no turn yet")
        if r["step"]:
            bits.append(f"step {r['step']['addr']} \"{r['step']['content']}\" in progress")
        if r["steps"]:
            bits.append(f"{r['stepsDone']} of {r['steps']} steps done")
        if r["issue"]:
            bits.append(f"issue {r['issue']} {r['issueState'] or 'state not read'}")
        if r["shard"]:
            bits.append("shard " + ", ".join(r["shard"]))
        if r["reading"]:
            bits.append(f"reading {r['reading'].get('k')} of {r['reading'].get('group')}")
        if r["report"]:
            bits.append(f"reported \"{r['report']}\"")
        name = f", {r['name']}" if r["name"] else ""
        out.append(f"{'  ' * r['depth']}- \"{r['title']}\" ({r['sessionId']}{name}): " + "; ".join(bits))
    if m["closed"]:
        out += ["", "## Closed", ""]
        out += [f"- \"{c['title']}\" ({c['sessionId']}): {c['how']}, its outcome "
                + ("kept as a replaces: note" if c["kept"] else "not kept") + f" on {c['parent']}" for c in m["closed"]]
    if m["tasks"]:
        out += ["", "## Background tasks", ""]
        out += [f"- {t['id']}, {t['tool'] or 'a task'} of \"{t['title']}\""
                + (f" under step {t['step']}" if t["step"] else "") + f", open since {t['at']}: {t['what']}"
                for t in m["tasks"]]
    if m["requests"]:
        out += ["", "## Start requests", ""]
        out += [f"- {r['id']} \"{r['title']}\" for {r['requester']}: {r['state']}" for r in m["requests"]]
    if m["issues"]:
        out += ["", "## Issues", ""]
        out += [f"- {k}: {v['state'] or 'state not read'}, of {', '.join(v['sessions'])}"
                for k, v in sorted(m["issues"].items())]
    if m["groups"]:
        out += ["", "## Readings", ""]
        for g in m["groups"]:
            out.append(f"- {g['id']} \"{_short(g.get('words'), 100)}\": {group_line(g)}")
    return "\n".join(out) + "\n"


_NET = {}                        # orchestrator -> when this process last rebuilt its ledger with GitHub read


def refresh(home, top, net=False, force=False):
    """ledger.md and ledger.json of an orchestrator, rebuilt only when a source changed, or when the issues' states
    are due to be read again, and rewritten only when the page differs -> (the page, True when it was rewritten)."""
    roots = app_roots(home, top)
    sig_path = os.path.join(relay._dir(home, top), "ledger.sig")
    sig = signature(home, top, roots)
    path = ledger_path(home, top)
    due = net and time.time() - _NET.get(top, 0) > ISSUE_TTL_S
    if not force and not due and _read(sig_path).strip() == sig and os.path.exists(path):
        return _read(path), False
    m = build(home, top, net)
    if net:
        _NET[top] = time.time()
    text = render(m)
    changed = _read(path) != text
    if changed:
        _write(path, text)
    if changed or not os.path.exists(model_path(home, top)):
        relay._write_json(model_path(home, top), m)
    after = signature(home, top, roots) if net else sig      # an issue state read now is a source too
    if _read(sig_path).strip() != after:
        _write(sig_path, after + "\n")
    return text, changed


def model(home, top):
    """An orchestrator's ledger as data, refreshed first."""
    refresh(home, top)
    return relay._read_json(model_path(home, top)) or build(home, top)


# --- the watcher ------------------------------------------------------------------------------------------------------

def watcher_path(home, top):
    return os.path.join(relay._dir(home, top), "watcher.json")


def watcher_alive(home, top):
    w = relay._read_json(watcher_path(home, top))
    return bool(w.get("pid")) and time.time() - float(w.get("beat") or 0) < BEAT_DEAD_S


def ensure_watcher(home, s):
    """One background watcher an orchestrator: started when none has said it is alive lately -> True when started."""
    if os.environ.get("P4_PHI_WATCH") == "0" or not on(home) or not orchestrator(home, s) or closed(s):
        return False
    top = s["sessionId"]
    if watcher_alive(home, top):
        return False
    relay._write_json(watcher_path(home, top), {"pid": -1, "beat": time.time(), "started": now()})   # the claim
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "phi.py"), "watch", "--p4", home,
                          "--session", top], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt",
                         close_fds=True, cwd=HERE)
    except OSError:
        return False
    return True


_ROUTES = {}                     # orchestrator -> when this process last looked for landed topics


def code_stamp():
    """The modification times of the scripts a watcher runs."""
    out = []
    for f in ("puppeteer.py", "phi.py", "relay.py", "plans.py", "starts.py", "issues.py"):
        try:
            out.append(os.stat(os.path.join(HERE, f)).st_mtime_ns)
        except OSError:
            out.append(0)
    return out


def tick(home, top, net=True):
    """One look of the watcher: the readings merged, the ledger, the landed topics registered as routes."""
    try:
        merge_all(home, top)
    except Exception:  # noqa: BLE001
        pass
    _, changed = refresh(home, top, net=net)
    if changed or time.time() - _ROUTES.get(top, 0) > ISSUE_TTL_S:
        _ROUTES[top] = time.time()
        try:
            if register_routes(home, top, net=net):
                refresh(home, top)
            check_routes(home, net=net)
        except Exception:  # noqa: BLE001
            pass
    return changed


def watch(home, top, once=False, max_s=None, interval=None):
    """The puppeteer's watch over one orchestrator's subtree, until the orchestrator is closed, another watcher
    took over, nothing changed for a day, or the plugin's own scripts changed under it: the marketplace runs from
    its checkout, so a watcher on yesterday's code ends and the next hook starts one on today's."""
    me = os.getpid()
    code = code_stamp()
    started = last_beat = time.time()
    last_change, last_sig = started, ""
    relay._write_json(watcher_path(home, top), {"pid": me, "beat": started, "started": now()})
    while True:
        if not os.path.isdir(relay._dir(home, top)):
            return 0
        s = relay._session(home, top)
        try:
            tick(home, top, net=os.environ.get("P4_PHI_WATCH_NET") != "0")
        except Exception:  # noqa: BLE001
            pass
        if once or closed(s) or relay.gone(home, s):
            break
        at = time.time()
        sig = _read(os.path.join(relay._dir(home, top), "ledger.sig")).strip()
        if sig != last_sig:
            last_sig, last_change = sig, at
        if at - last_change > WATCH_QUIT_S or (max_s and at - started > max_s) or code_stamp() != code:
            break
        w = relay._read_json(watcher_path(home, top))
        if w.get("pid") not in (me, -1):
            return 0                                # another watcher took this orchestrator
        if at - last_beat >= BEAT_S or w.get("pid") == -1:
            relay._write_json(watcher_path(home, top), {"pid": me, "beat": at, "started": w.get("started") or now()})
            last_beat = at
        try:
            quick = float(os.environ.get("P4_PHI_WATCH_S") or 0)
        except ValueError:
            quick = 0
        time.sleep(interval or quick or (WATCH_S if at - last_change < WATCH_CALM_S else WATCH_SLOW_S))
    w = relay._read_json(watcher_path(home, top))
    if w.get("pid") == me:
        try:
            os.remove(watcher_path(home, top))
        except OSError:
            pass
    return 0


# --- routes: the loop that recurses -----------------------------------------------------------------------------------

def routes_path(home, sid):
    return os.path.join(relay._dir(home, sid), "routes.jsonl")


def all_routes(home):
    """{route id: route row} of every route registered in the store and not withdrawn since."""
    out = {}
    for p in sorted(glob.glob(os.path.join(home, "phi", "sessions", "*", "routes.jsonl"))):
        for r in relay._rows(p):
            rid = r.get("id")
            if r.get("kind") == "route" and rid:
                out[rid] = dict(r, file=p)
            elif r.get("kind") == "withdrawn":
                out.pop(rid, None)
    return out


def closing_pushed(home, s, slug, n, repo):
    """(short sha, subject) of a pushed commit that closes the issue, made since the session began; ('', '') for
    none."""
    repos = [repo] if repo else []
    for r, sl in issues.repos_named(str(s.get("task") or ""), s.get("cwd") or ""):
        if sl.lower() == slug.lower() and r not in repos:
            repos.append(r)
    here = relay.repo_of(s.get("cwd") or "")
    if here and here not in repos and issues.github_of(here).lower() == slug.lower():
        repos.append(here)
    since = str(s.get("createdAt") or "")
    for r in repos:
        out = issues.git(r, "log", "-200", f"--since={since}", "--format=%h%x1f%s%x1f%B%x1e") if since else ""
        for rec in out.split("\x1e"):
            parts = rec.strip().split("\x1f")
            if len(parts) >= 3 and issues.closes(parts[2], slug, n) and issues._pushed(r, parts[0]):
                return parts[0], parts[1], r
    return "", "", ""


def backed(home, s, net=False):
    """(True, the closing commit) when the records back a landed topic's reports: the session and the sessions it
    started are archived with their outcome kept, its issue is closed, and a commit that closes it is pushed; else
    (False, what is missing)."""
    sid = s["sessionId"]
    slug, n, repo = topic_issue(s)
    if not n:
        return False, "its work names no issue"
    parent = relay._parent(s)
    if not (closed(s) or relay.gone(home, s)):
        return False, "the session is not archived"
    if parent and not outcome_kept(home, parent, sid):
        return False, "its outcome is not kept on the session that started it"
    for kid, depth, k in subtree(home, sid)[1:]:
        if not (closed(k) or relay.gone(home, k)):
            return False, f"a session it started, {kid}, is not archived"
        if depth == 1 and not outcome_kept(home, sid, kid):
            return False, f"the outcome of {kid} is not kept"
    state = issue_state(home, slug, n, net)
    if state != "CLOSED":
        return False, f"{slug}#{n} is {state.lower() or 'not read'}, not closed"
    sha, subject, where = closing_pushed(home, s, slug, n, repo)
    if not sha:
        return False, f"no pushed commit closes {slug}#{n}"
    return True, {"sha": sha, "subject": subject, "repo": where}


def route_of(home, s, commit):
    """A landed topic as a route row: the request's words, the topic, the session shape that worked, the brief's
    slice, fork or fresh, and the issue."""
    phi = _phi()
    sid, parent = s["sessionId"], relay._parent(s)
    slug, n, _ = topic_issue(s)
    above = relay._session(home, parent) if parent else {}
    draft = load_draft(home, parent, s.get("draft")) if parent and s.get("draft") else {}
    said = draft.get("words") or (above.get("task") if above and not relay._parent(above) else "") or s.get("task")
    plan = plans.load(home, sid)
    base = s.get("cwd") or above.get("cwd") or ""
    return {"kind": "route", "id": "rt-" + hashlib.sha1(f"{sid}\n{slug}#{n}".encode()).hexdigest()[:10],
            "time": now(), "at": time.time(), "words": _short(said, WORDS_CHARS), "topic": phi.title_of(s),
            "shape": {"parent": "a child of a top session" if parent and not relay._parent(above) else
                      "a top session" if not parent else "a child of an orchestrator",
                      "children": len(subtree(home, sid)) - 1, "archiveWhenDone": bool(s.get("disposable")),
                      "steps": [_short(x.get("content"), 100) for x in plan.get("steps") or []][:12]},
            "slice": {"brief": _short(s.get("task"), WORDS_CHARS),
                      "paths": [p for p in relay.child_paths(home, s) if not relay.names_nothing(p, home, base)][:12]},
            "context": "fork" if s.get("forked") else "fresh", "issue": f"{slug}#{n}", "session": sid,
            "registeredBy": parent or sid, "commit": commit}


def register_routes(home, top, net=False):
    """Each landed topic under an orchestrator registered once, beside the ledger, when its records back it -> the
    routes registered now."""
    rows = [r for p in glob.glob(os.path.join(home, "phi", "sessions", "*", "routes.jsonl"))
            for r in relay._rows(p) if r.get("kind") == "route"]
    held, taken = {r.get("session") for r in rows}, {r.get("issue") for r in rows}
    new = []
    for sid, depth, s in subtree(home, top):
        slug, n, _ = topic_issue(s)
        if sid in held or not n or f"{slug}#{n}" in taken or not (depth or not relay._parent(s)):
            continue                                # a child orchestrator's own route is its parent's to register
        if not (closed(s) or relay.archived_in_app(s)):
            continue                                # still live: nothing landed to check
        ok, got = backed(home, s, net)
        if not ok:
            continue
        row = route_of(home, s, got)
        _append(routes_path(home, relay._parent(s) or sid), row)
        taken.add(row["issue"])
        new.append(row)
    return new


def reverted(repo, sha):
    """True when a later commit reverts this one."""
    full = issues.git(repo, "rev-parse", sha) if repo and sha else ""
    if not full:
        return False
    return bool(issues.git(repo, "log", "-5", "--format=%h", f"--grep=This reverts commit {full}"))


def check_routes(home, net=False, force=False):
    """Registered routes whose issue was reopened or whose commit was reverted are withdrawn -> those withdrawn
    now. Looked at once every ROUTE_CHECK_S."""
    mark = os.path.join(home, "phi", ".routes-checked")
    try:
        if not force and time.time() - os.path.getmtime(mark) < ROUTE_CHECK_S:
            return []
    except OSError:
        pass
    out = []
    for rid, r in all_routes(home).items():
        slug, _, n = str(r.get("issue") or "").rpartition("#")
        why = ""
        if net and slug and n.isdigit() and issues.issue_state(slug, int(n)) == "OPEN":
            why = f"{r['issue']} was reopened"
        c = r.get("commit") if isinstance(r.get("commit"), dict) else {}
        if not why and reverted(c.get("repo"), c.get("sha")):
            why = f"its commit {c.get('sha')} was reverted"
        if why:
            _append(r["file"], {"kind": "withdrawn", "id": rid, "time": now(), "why": why})
            out.append((rid, why))
    if net or force:
        _write(mark, now() + "\n")
    return out


def score_routes(home, req):
    """[(score, shared words, route)] of the registered routes a message matches closely, the best first."""
    out = []
    for r in all_routes(home).values():
        n, part = share(req, f"{r.get('words', '')} {r.get('topic', '')}")
        if n >= ROUTE_MIN and part >= ROUTE_CLOSE:
            out.append((round(part, 2), n, r))
    return sorted(out, key=lambda x: (-x[0], -x[1], str(x[2].get("id"))))


# --- prompty: the message read against the ledger ---------------------------------------------------------------------

def readings_of(req):
    """The distinct readings a message names itself: "either A or B", "A, or maybe B"; [] when it names one."""
    m = EITHER.search(req) or OR_MAYBE.search(req)
    if not m:
        return []
    a, b = (" ".join(x.split()).strip(" ,.;:") for x in m.groups())
    return [a, b] if a and b and a.lower() != b.lower() else []


def prompty(home, s, req, base):
    """ezexe's message read against the ledger: the paths and words it carries, whether it is work at all, the
    live session that owns its area, the running writer that holds its files, the registered routes it matches, and
    the readings it leaves open."""
    phi = _phi()
    sid = s["sessionId"]
    every = relay._sessions(home)
    named = [p for p in relay.paths_in(req, base) if not relay.names_nothing(p, home, base)]
    read = {"words": req, "paths": named, "work": issues.writing(req) and len(words(req)) >= QUICK_WORDS,
            "owner": None, "busy": None, "routes": [], "readings": readings_of(req), "own": False,
            "within": True}
    if not read["work"]:
        return read
    read["own"] = any(plans.bears(req, st.get("content")) for st in plans.open_steps(home, sid))
    first = not phi.load_turns(home, sid) and " ".join(req.split())[:200] in " ".join(str(s.get("task") or "").split())
    read["within"] = first or read["own"] or share(req, s.get("task"))[0] >= TOPIC_WORDS or any(
        relay.overlap(p, q) for p in named for q in relay.scope_of(home, sid) if not relay.names_nothing(q, home, base))
    above = set(phi.chain_of(home, sid))
    best = None
    for oid, o in every.items():
        if oid == sid or oid in above or closed(o) or relay.gone(home, o):
            continue
        shard = [p for p in relay.shard_of(o) if not relay.names_nothing(p, home, base)]
        hit = next((p for p in shard if any(relay.covers(p, n) or relay.covers(n, p) for n in named)), "")
        n, _ = share(req, f"{o.get('task', '')} " + " ".join(str(x.get("content") or "")
                                                             for x in plans.open_steps(home, oid)))
        if hit:
            cand = (2, len(relay._root(hit)), oid, f"its shard holds {hit}")
        elif n >= OWNER_WORDS:
            cand = (1, n, oid, f"its task shares {n} content words with the message")
        else:
            cand = None
        if cand and (best is None or cand[:2] > best[:2]):
            best = cand
        if not cand and read["busy"] is None and named and busy(home, oid):
            files = set(relay.edited_files(home, oid)) | set(relay.paths_in(o.get("task") or "", o.get("cwd") or base))
            held = next((f for f in sorted(files) if not relay.names_nothing(f, home, base)
                         and any(relay.overlap(f, x) for x in named)), "")
            if held:
                read["busy"] = {"sessionId": oid, "title": phi.title_of(o), "why": f"it is a running writer on {held}"}
    if best:
        read["owner"] = {"sessionId": best[2], "title": phi.title_of(every[best[2]]), "why": best[3]}
    read["routes"] = [{"score": sc, "shared": n, "id": r["id"], "topic": r.get("topic"), "context": r.get("context"),
                       "shape": r.get("shape"), "slice": r.get("slice"), "issue": r.get("issue")}
                      for sc, n, r in score_routes(home, req)[:3]]
    return read


# --- prompter: the exact next session ---------------------------------------------------------------------------------

def drafts_dir(home, sid):
    return os.path.join(relay._dir(home, sid), "drafts")


def load_draft(home, sid, did):
    return relay._read_json(os.path.join(drafts_dir(home, sid), f"{did}.json")) if sid and did else {}


def topic_of(req):
    first = re.split(r"(?<=[.!?])\s+|\n+", " ".join(str(req).split()), maxsplit=1)[0]
    first = re.sub(r"^\W*(?:(?:please|now that|now|also|and|so|ok|okay|can you|could you)\s+)+", "", first, flags=re.I)
    if len(first) > 58:
        first = first[:58].rsplit(" ", 1)[0]
    return first.strip(" .,;:")


def prompter(home, s, req, read, base, transcript_bytes=0, reading=None):
    """The exact next session for a message: its topic, a brief built from ezexe's words, its parent, fork or
    fresh, and the issue it closes or the one to file. A close registered route gives the starting shape."""
    phi = _phi()
    sid = s["sessionId"]
    parent = sid if read["within"] or relay._parent(s) else ""
    route = read["routes"][0] if read["routes"] else None
    title = topic_of(reading["title"] if reading else req)
    if reading:
        title = f"Reading {reading['k']}: " + (title if len(title) <= 46 else title[:46].rsplit(" ", 1)[0])
    repo = next(iter(issues.repos_named(req, base)), ("", ""))
    here = relay.repo_of(base) if base else ""
    slug = repo[1] or (issues.github_of(here) if here else "")
    named = issues.named_issue(req, slug) if slug else 0
    full = re.search(r"\b([\w.-]+/[\w.-]+)#(\d+)\b", req)
    if full and not named:                          # the words name the issue whole, in whichever repository
        slug, named = full.group(1), int(full.group(2))
    lines = [f"# {title}", "", "ezexe's words:", "", "> " + _short(req, WORDS_CHARS).replace("\n", "\n> "), ""]
    if reading:
        lines += [f"This session takes one reading of those words, reading {reading['k']} of {reading['n']}: "
                  f"{reading['text']}",
                  "Work only that reading, and end your report with one line `Result: <what this reading comes to>`, "
                  "which the session that started this one merges with the other readings.", ""]
    if route:
        lines += [f"A route that landed before fits these words: \"{route['topic']}\", {route['issue']}, a "
                  f"{route['context']} session, {(route.get('shape') or {}).get('parent', 'a child')}.",
                  "Its steps were: " + "; ".join((route.get("shape") or {}).get("steps") or ["none kept"]) + ".",
                  "Its brief began: " + _short((route.get("slice") or {}).get("brief"), 500), ""]
    paths = read["paths"] or ((route or {}).get("slice") or {}).get("paths") or []
    if paths:
        lines += ["Area: " + ", ".join(f"`{p}`" for p in paths[:8]) + ".", ""]
    if reading:
        lines += ["A reading explores: change no tracked file and commit nothing, since the readings beside this one "
                  "share the checkout. The session that started this one lands the reading that survives the merge.",
                  "Done looks like: the reading worked through, and its `Result:` line reported.", "Archive when done."]
    else:
        if named:
            lines += [f"This closes {slug}#{named}: every commit says `Closes #{named}`.", ""]
        elif slug:
            lines += [f"phi files the issue for this in {slug} at your first message, and every commit closes it.", ""]
        lines += ["Done looks like: the change made, its proving test passing, committed on the parent's branch with "
                  "no worktree and no branch of your own, and reported.", "Archive when done."]
    if not parent:
        lines += ["", f"{phi.NEW_TOP_BRIEF} {phi.new_top_first_act()}"]
    context = "fresh"
    if parent and not reading:
        context = (route or {}).get("context") or relay.advise_start(home, sid, {"prompt": "\n".join(lines)},
                                                                     transcript_bytes)[0]
    did = "drf-" + hashlib.sha1(f"{sid}\n{req}\n{(reading or {}).get('text', '')}".encode("utf-8", "replace")
                                ).hexdigest()[:10]
    lines += ["", f"phi draft {did} for {parent or 'root'}."]
    if reading:
        lines += [f"phi reading {reading['group']} {reading['k']} of {reading['n']} for {sid}."]
    task = _short(" ".join(str(s.get("task") or "").split()), 500)
    background = (f"Drafted by p4-phi's prompter in the session \"{phi.title_of(s)}\" ({sid}) from ezexe's message, "
                  f"read against that session's ledger at {ledger_path(home, sid)}."
                  + (f" That session's task: {task}" if task else ""))
    return {"id": did, "time": now(), "words": req, "title": title, "brief": "\n".join(lines), "parent": parent,
            "context": context, "issue": f"{slug}#{named}" if named else "", "repo": slug, "paths": paths,
            "route": (route or {}).get("id", ""), "background": starts.background_of(home, sid, background),
            "reading": reading or None, "drafter": sid}


def call_of(d):
    """The exact start_session input that starts a draft."""
    call = {"initiation": "user_asked", "title": d["title"], "context": d["context"], "prompt": d["brief"]}
    if d["context"] == "fresh":
        call.update(use_worktree=False, background=d["background"])
    return call


# --- pioneer: the gate, then the dispatch ----------------------------------------------------------------------------

def pioneer(home, s, d, read, net=True):
    """A draft gate-checked: the issue exists or is to be filed, no running writer holds the same files, the parent
    is the right orchestrator. The verdict is start, route or queue, with what the gate saw; the draft is kept."""
    phi = _phi()
    sid = s["sessionId"]
    gate = []
    slug, _, n = d["issue"].rpartition("#")
    if n:
        state = issue_state(home, slug, int(n), net)
        gate.append(f"{d['issue']} is {state.lower()}" if state else f"gh could not read {d['issue']}")
        if state == "CLOSED":
            gate[-1] += ", so the issue loop files a new one at the child's first message"
    elif d["repo"]:
        gate.append(f"it names no issue, so the issue loop files one in {d['repo']} at the child's first message")
    else:
        gate.append("its files are in no GitHub repository, so it carries no issue")
    cap = phi.caps_text(home, s)
    owner, held = read.get("owner"), read.get("busy")
    if owner and not d.get("reading"):
        verdict = "route"
        gate.append(f"its area has a live owner, \"{owner['title']}\" ({owner['sessionId']}): {owner['why']}")
    elif cap:
        verdict = "here"
        gate.append(cap)
    elif held:
        verdict = "queue"
        gate.append(f"\"{held['title']}\" ({held['sessionId']}) holds its files: {held['why']}")
    else:
        verdict = "start"
        gate.append("no running writer holds its files")
    gate.append("its parent is this session, the orchestrator of its topic" if d["parent"] else
                "it is outside this session's topic, so it is a new top session in the root")
    if d.get("reading") and verdict == "queue":
        verdict = "start"                           # a reading changes no file, so no writer is in its way
    d.update(verdict=verdict, gate=gate, owner=owner, busy=held)
    relay._write_json(os.path.join(drafts_dir(home, sid), f"{d['id']}.json"), d)
    return d


def queue(home, d):
    """A draft whose writer is busy, kept as a start request behind that writer -> (request id, True when new)."""
    behind = (d.get("busy") or {}).get("sessionId", "")
    return starts.add(home, d["parent"] or d["drafter"], d["title"], d["brief"], d["context"],
                      background=d["background"], after=behind)


def verdict_text(home, s, d):
    """What pioneer hands the session: the exact call, the exact message, or the exact command."""
    phi = _phi()
    head = (f"phi (p4-phi) puppeteer: prompty read this message of ezexe's as work for a session of its own"
            + (f", and it closely matches the registered route \"{d['route']}\"" if d.get("route") else "")
            + f"; prompter drafted it as \"{d['title']}\" (draft {d['id']}); pioneer's gate: "
            + "; ".join(d["gate"]) + ". ")
    tail = (" If the message is this session's own orchestration instead, a question, a decision or a relay, leave "
            "the draft and answer it here.")
    if d["verdict"] == "route":
        o = d["owner"]
        return (head + f"Route it: SendMessage (`to`: {o['sessionId']}) with ezexe's words quoted, and tell ezexe in "
                f"one line that \"{o['title']}\" has it. Start no session for it." + tail)
    if d["verdict"] == "queue":
        return (head + f"Queue it behind that writer: `{phi.commands()} pioneer {d['id']}` keeps it as a start request "
                f"that is handed out, with its exact call, at the first turn ezexe begins once the writer is no "
                f"longer busy." + tail)
    if d["verdict"] == "here":
        return head + "No session is started for it." + tail
    return (head + "Start it now: `mcp__ccd_session__start_session` with "
            + json.dumps(call_of(d), ensure_ascii=False) + tail)


# --- parallel: one child a reading, merged ----------------------------------------------------------------------------

def groups_dir(home, sid):
    return os.path.join(relay._dir(home, sid), "readings")


def load_groups(home, sid):
    return [g for g in (relay._read_json(p) for p in sorted(glob.glob(os.path.join(groups_dir(home, sid), "*.json"))))
            if g.get("id")]


def save_group(home, g):
    relay._write_json(os.path.join(groups_dir(home, g["parent"]), f"{g['id']}.json"), g)


def explore(home, s, req, texts, base, transcript_bytes=0):
    """An under-determined message drafted as one sibling child a distinct reading -> (the group, its drafts). The
    depth and count caps still hold: no more readings than this session may still start."""
    phi = _phi()
    sid = s["sessionId"]
    texts = list(dict.fromkeys(" ".join(str(t).split()) for t in texts if str(t).strip()))
    if len(texts) < 2:
        raise ValueError("an under-determined message has two or more distinct readings")
    if phi.depth_of(home, s) >= phi.MAX_DEPTH:
        raise ValueError(phi.caps_text(home, s))
    room = phi.MAX_CHILDREN - len(plans._children(home, sid))
    if room < 2:
        raise ValueError(phi.caps_text(home, s) or "this session has no room for two more sessions")
    texts = texts[:room]
    gid = "grp-" + hashlib.sha1(f"{sid}\n{req}\n{'|'.join(texts)}".encode("utf-8", "replace")).hexdigest()[:10]
    read = prompty(home, s, req, base)
    read["owner"] = None                            # the readings are this puppeteer's to merge: none is routed away
    drafts = []
    for k, t in enumerate(texts, 1):
        d = prompter(home, s, req, read, base, transcript_bytes,
                     reading={"group": gid, "k": k, "n": len(texts), "text": t, "title": t})
        d["parent"] = sid
        drafts.append(pioneer(home, s, d, read, net=False))
    g = {"id": gid, "parent": sid, "time": now(), "words": req, "state": "open",
         "readings": [{"k": k, "text": t, "draft": d["id"], "child": ""} for (k, t), d in
                      zip(enumerate(texts, 1), drafts)]}
    held = next((x for x in load_groups(home, sid) if x["id"] == gid), None)
    if held:
        return held, drafts
    save_group(home, g)
    return g, drafts


def explore_text(home, s, g, drafts):
    lines = [f"- reading {r['k']}, \"{_short(r['text'], 120)}\": `mcp__ccd_session__start_session` with "
             + json.dumps(call_of(d), ensure_ascii=False) for r, d in zip(g["readings"], drafts)]
    return (f"phi (p4-phi) puppeteer: this message of ezexe's is under-determined, with {len(drafts)} distinct "
            f"readings, and one draft would have to guess between them. Pioneer starts one child a reading, "
            f"siblings under this session, each with exactly the call given; this session merges their `Result:` "
            f"lines as the puppeteer (group {g['id']}), and only a fork that survives the merge goes to ezexe:\n"
            + "\n".join(lines))


def arrived(home, s, prompt):
    """A started session's first message: the draft and the reading its brief names are kept on it (s is changed)."""
    text = str(prompt or "")
    m = DRAFT_RE.search(text)
    if m and not s.get("draft"):
        s["draft"] = m.group(1)
    m = READING_RE.search(text)
    if m and not s.get("reading"):
        s["reading"] = {"group": m.group(1), "k": int(m.group(2)), "n": int(m.group(3)), "parent": m.group(4)}
        g = relay._read_json(os.path.join(groups_dir(home, m.group(4)), f"{m.group(1)}.json"))
        for r in g.get("readings") or []:
            if r.get("k") == int(m.group(2)) and not r.get("child"):
                r["child"] = s["sessionId"]
                save_group(home, g)
    return bool(s.get("draft") or s.get("reading"))


def result_of(home, sid):
    """The `Result:` line of a reading's last finished turn, '' while it has none."""
    for t in reversed(_phi().load_turns(home, sid)):
        got = RESULT_RE.findall(f"{t.get('said') or ''}\n{t.get('report') or ''}")
        if got:
            return " ".join(got[-1].split())
    return ""


def same_result(a, b):
    if " ".join(a.lower().split()).strip(" .") == " ".join(b.lower().split()).strip(" ."):
        return True
    n, part = share(a, b)
    return n >= 2 and part >= 0.8 and abs(len(words(a)) - len(words(b))) <= 2


def merge(home, g):
    """One group of readings merged once every reading has a result: readings that converge collapse to one
    result; a fork becomes one question with options and a default -> True when its state changed."""
    if g.get("state") != "open":
        return False
    got = []
    for r in g["readings"]:
        res = result_of(home, r["child"]) if r.get("child") else ""
        if not res:
            return False
        r["result"] = res
        got.append(res)
    if all(same_result(got[0], x) for x in got[1:]):
        g.update(state="collapsed", result=got[0], mergedAt=now())
    else:
        shown = [k for k, r in enumerate(g["readings"]) if (_phi().load_turns(home, r["child"]) or [{}])[-1].get("done")]
        g.update(state="forked", default=g["readings"][shown[0] if shown else 0]["k"], mergedAt=now(),
                 question=f"Which reading of \"{_short(g['words'], 160)}\" is meant?")
    save_group(home, g)
    return True


def group_line(g):
    if g.get("state") == "collapsed":
        return f"{len(g['readings'])} readings converged on \"{_short(g.get('result'), 160)}\"; their rows are closed"
    if g.get("state") == "forked":
        return (f"the readings fork, so one question goes to ezexe, default reading {g.get('default')}: "
                + "; ".join(f"reading {r['k']} \"{_short(r['text'], 60)}\" came to \"{_short(r.get('result'), 80)}\""
                            for r in g["readings"]))
    started = sum(1 for r in g["readings"] if r.get("child"))
    return f"open, {started} of {len(g['readings'])} readings started, results awaited"


def merge_text(g):
    if g.get("state") == "collapsed":
        return (f"phi (p4-phi) puppeteer: the {len(g['readings'])} readings of \"{_short(g['words'], 120)}\" "
                f"converged on one result: \"{_short(g.get('result'), 300)}\". They collapse to it: carry it on as "
                f"the answer, put no question to ezexe, and archive the reading sessions.")
    opts = "; ".join(f"reading {r['k']} \"{_short(r['text'], 80)}\", which came to \"{_short(r.get('result'), 140)}\""
                     for r in g["readings"])
    return (f"phi (p4-phi) puppeteer: the readings of \"{_short(g['words'], 120)}\" fork after the merge. If the "
            f"chain can settle it, settle it and say why in one line, then `{_phi().commands()} merge {g['id']} "
            f"--result \"<the result>\"`. Otherwise put one question to ezexe, \"{g.get('question')}\", with these "
            f"options and reading {g.get('default')} as the default: {opts}.")


def merge_all(home, sid):
    """Every open group of a puppeteer merged where it can be; the puppeteer is told once at its next message."""
    out = []
    for g in load_groups(home, sid):
        if merge(home, g):
            relay.warn(home, sid, f"merge:{g['id']}:{g['state']}", merge_text(g))
            out.append(g)
    return out


# --- meta: the puppeteers reconciled ----------------------------------------------------------------------------------

def meta_path(home):
    return os.path.join(home, "phi", "meta-ledger.md").replace("\\", "/")


def last_moved(home, sid):
    """The time of the last thing a session's files record, in epoch seconds."""
    out = 0.0
    for f in ("turns.jsonl", "plan.json", "session.json"):
        try:
            out = max(out, os.path.getmtime(os.path.join(relay._dir(home, sid), f)))
        except OSError:
            pass
    return out


def meta_pass(home, at=None):
    """The meta-puppeteer's pass over every live top session's ledger -> (meta-ledger.md's text, its findings,
    True when the page was rewritten). The findings: duplicate topics, tops in conflict over the same issue or the
    same files, stale topics, and what is left open, which seeds the next generation of topics."""
    phi = _phi()
    at = time.time() if at is None else at
    every = relay._sessions(home)
    tops = sorted((sid for sid, s in every.items() if not relay._parent(s) and not closed(s)
                   and not relay.gone(home, s) and str(s.get("task") or "").strip()),
                  key=lambda k: (str(every[k].get("createdAt") or ""), k))
    led = {t: model(home, t) for t in tops}
    name = {t: f"\"{phi.title_of(every[t])}\" ({t})" for t in tops}
    dup, clash, stale, seeds, findings = [], [], [], [], []
    for i, a in enumerate(tops):
        for b in tops[i + 1:]:
            n, part = share(every[a].get("task"), every[b].get("task"))
            if n >= ROUTE_MIN and part >= ROUTE_CLOSE:
                dup.append(f"{name[a]} and {name[b]} carry one topic: their tasks share {n} content words.")
                findings.append(f"dup:{a}:{b}")
            same = sorted(set(led[a].get("issues") or {}) & set(led[b].get("issues") or {}))
            for k in same:
                clash.append(f"{name[a]} and {name[b]} both hold {k}.")
                findings.append(f"issue:{a}:{b}:{k}")
            fa = {f for r in led[a].get("rows") or [] for f in (r.get("shard") or []) + (r.get("files") or [])}
            fb = {f for r in led[b].get("rows") or [] for f in (r.get("shard") or []) + (r.get("files") or [])}
            both = sorted(x for x in fa if not relay.names_nothing(x, home) and "/.claude/" not in x + "/"
                          and any(relay.overlap(x, y) for y in fb if not relay.names_nothing(y, home)))
            if both:
                clash.append(f"{name[a]} and {name[b]} both changed or hold {', '.join(both[:4])}"
                             + (f" and {len(both) - 4} more" if len(both) > 4 else "") + ".")
                findings.append(f"files:{a}:{b}:{both[0]}")
    for t in tops:
        rows = led[t].get("rows") or []
        live_work = any(r.get("working") for r in rows)
        still = [x for r in rows for x in r.get("open") or []]
        moved = max([last_moved(home, r["sessionId"]) for r in rows] or [0.0])
        landed = bool(led[t].get("issues")) and all(v.get("state") == "CLOSED" for v in led[t]["issues"].values())
        if landed and not still:
            stale.append(f"{name[t]} has landed: every issue it holds is closed and no step is open, so it can be "
                         f"archived.")
            findings.append(f"landed:{t}")
        elif not live_work and moved and at - moved > STALE_S:
            days = (at - moved) / 86400
            stale.append(f"{name[t]} has not moved for {days:.1f} days"
                         + (f", with {len(still)} steps still open." if still else ", and shows no open step."))
            findings.append(f"stale:{t}")
            seeds += [f"\"{x}\", left open by {name[t]}." for x in still[:4]]
        for k, v in sorted((led[t].get("issues") or {}).items()):
            if v.get("state") == "OPEN" and not any(r.get("issue") == k and (r.get("working") or r.get("step"))
                                                    for r in rows):
                seeds.append(f"{k} is open and no session under {name[t]} is at work on it.")
    for r in starts.pending(home, at):
        seeds.append(f"start request {r['id']} \"{r.get('title')}\" for {r.get('requester')} waits for a turn ezexe "
                     f"begins.")
    out = ["# Meta-ledger", "",
           "Written by p4-phi's meta pass: the top session that receives ezexe's message reconciles every top "
           "session's ledger before it reads the message.",
           "Rewritten only when what it finds changes.", "", "## Top sessions", ""]
    out += [f"- {name[t]}: live sessions {len(led[t].get('rows') or [])}, open steps "
            f"{sum(len(r.get('open') or []) for r in led[t].get('rows') or [])}, ledger "
            f"{ledger_path(home, t)}" for t in tops] or ["- None."]
    for head, items, none in (("Duplicate topics", dup, "No two top sessions carry one topic."),
                              ("Conflicts between top sessions", clash,
                               "No two top sessions hold the same issue or the same files."),
                              ("Stale or landed topics", stale, "No top session is stale."),
                              ("Next generation", seeds, "Nothing is left open without a session at work on it.")):
        out += ["", f"## {head}", ""] + ([f"- {x}" for x in items] or [f"- {none}"])
    text = "\n".join(out) + "\n"
    changed = _read(meta_path(home)) != text
    if changed:
        _write(meta_path(home), text)
    return text, {"duplicates": dup, "conflicts": clash, "stale": stale, "seeds": seeds, "keys": findings}, changed


def meta_text(home, s, found):
    """The findings of a meta pass this top session was not told yet, in a few lines (s is changed)."""
    told = [x for x in s.get("metaTold") or [] if isinstance(x, str)]
    new = [k for k in found["keys"] if k not in told and s["sessionId"] in k]
    if not new:
        return ""
    s["metaTold"] = (told + new)[-200:]
    mine = [x for x in found["duplicates"] + found["conflicts"] + found["stale"] if s["sessionId"] in x]
    return ("phi (p4-phi) meta-puppeteer: the meta pass over every top session's ledger, written to "
            f"{meta_path(home)}, found for this session: " + " ".join(mine[:4])
            + " Settle what the chain can: relay to the other top session with SendMessage, or archive the one that "
              "is over; only a conflict the chain cannot settle goes to ezexe.")


# --- the prompt hook ----------------------------------------------------------------------------------------------------

def on_prompt(home, s, req, base, transcript_bytes=0, owner_turn=True, net=True):
    """An ezexe message in an orchestrator: the meta pass when it is a top session, its ledger made current, then
    prompty, prompter and pioneer -> (the text for the session, the verdict or ''). `s` is changed, never saved."""
    if not on(home) or not req or not owner_turn or not orchestrator(home, s):
        return "", ""
    parts = []
    if not relay._parent(s):
        _, found, _ = meta_pass(home)
        parts.append(meta_text(home, s, found))
    refresh(home, s["sessionId"])
    read = prompty(home, s, req, base)
    if not read["work"] or (read["own"] and not read["owner"] and not read["readings"]) \
            or (relay._parent(s) and not read["within"]):       # a child hands another topic up; it drafts none
        return "\n\n".join(p for p in parts if p), ""
    if len(read["readings"]) >= 2 and not read["owner"]:
        try:
            g, drafts = explore(home, s, req, read["readings"], base, transcript_bytes)
            parts.append(explore_text(home, s, g, drafts))
            return "\n\n".join(p for p in parts if p), "explore"
        except ValueError:
            pass
    d = pioneer(home, s, prompter(home, s, req, read, base, transcript_bytes), read, net)
    parts.append(verdict_text(home, s, d))
    if d["verdict"] == "start":
        parts.append(f"If one draft would have to guess between distinct readings of the message, start none of it: "
                     f"`{_phi().commands()} readings \"<reading one>\" \"<reading two>\" --words \"<the message>\"` "
                     f"drafts one child a reading for this session to merge.")
    return "\n\n".join(p for p in parts if p), d["verdict"]


# --- the commands -----------------------------------------------------------------------------------------------------

COMMANDS = ("ledger", "watch", "draft", "pioneer", "routes", "readings", "merge", "meta")


def command(a, me):
    """A puppeteer command run through phi.py: `a` its parsed arguments, `me` the session it runs for."""
    phi = _phi()
    home = me.home
    if a.cmd == "meta":
        text, found, changed = meta_pass(home)
        sys.stdout.write(text)
        print(f"phi: {meta_path(home)} " + ("rewritten" if changed else "unchanged"), file=sys.stderr)
        return 0
    if a.cmd == "routes":
        if a.register:
            every = relay._sessions(home)
            for sid in sorted(s for s, v in every.items() if orchestrator(home, v, every)):
                for r in register_routes(home, sid, net=True):
                    print(f"registered {r['id']}: \"{r['topic']}\", {r['issue']}, commit {r['commit']['sha']}")
            for rid, why in check_routes(home, net=True, force=True):
                print(f"withdrawn {rid}: {why}")
        if a.why:
            s = relay._session(home, phi.safe_id(a.why))
            ok, got = backed(home, s, net=True) if s else (False, "no such session")
            print(f"{a.why}: " + (f"backed, by commit {got['sha']} \"{got['subject']}\"" if ok else
                                  f"not registered: {got}"))
        for r in all_routes(home).values():
            print(f"{r['id']} \"{r.get('topic')}\" {r.get('issue')} {r.get('context')}: {_short(r.get('words'), 160)}")
        return 0
    if not me.id:
        print("phi: this is not a session (no session id in the environment); pass --session", file=sys.stderr)
        return 2
    s = phi.ensure_session(home, me.id, me.rec, "" if a.session else me.cli)
    sid = s["sessionId"]
    base = s.get("cwd") or os.getcwd()
    if a.cmd == "watch":
        return watch(home, sid, once=a.once, max_s=a.max_s or None, interval=a.interval or None)
    if a.cmd == "ledger":
        text, changed = refresh(home, sid, net=a.net, force=a.net)
        sys.stdout.write(text)
        print(f"phi: {ledger_path(home, sid)} " + ("rewritten" if changed else "unchanged") + "; watcher "
              + ("alive" if watcher_alive(home, sid) else "not running"), file=sys.stderr)
        return 0
    if a.cmd == "draft":
        read = prompty(home, s, a.text, base)
        if len(read["readings"]) >= 2 and not read["owner"]:
            g, drafts = explore(home, s, a.text, read["readings"], base)
            print(explore_text(home, s, g, drafts))
            return 0
        d = pioneer(home, s, prompter(home, s, a.text, read, base), read)
        print(verdict_text(home, s, d))
        return 0
    if a.cmd == "pioneer":
        d = load_draft(home, sid, a.draft)
        if not d:
            raise ValueError(f"no draft {a.draft} in this session")
        if d.get("verdict") == "queue":
            rid, new = queue(home, d)
            print((f"queued as start request {rid}" if new else f"start request {rid} was already kept")
                  + f" behind {(d.get('busy') or {}).get('sessionId')}: it is handed out at the first turn ezexe "
                    f"begins once that writer is no longer busy.")
        elif a.request and d.get("verdict") == "start":
            rid, new = queue(home, d)               # a turn ezexe did not begin: the app refuses the start itself
            print(starts.requested_text(rid, new))
        else:
            print(verdict_text(home, s, d))
        return 0
    if a.cmd == "readings":
        g, drafts = explore(home, s, a.words or " / ".join(a.texts), a.texts, base)
        print(explore_text(home, s, g, drafts))
        return 0
    if a.cmd == "merge":
        g = next((x for x in load_groups(home, sid) if x["id"] == a.group), None)
        if not g:
            raise ValueError(f"no group {a.group} in this session")
        if a.result:
            g.update(state="collapsed", result=" ".join(a.result.split()), mergedAt=now(), settledBy="the puppeteer")
            save_group(home, g)
        else:
            merge(home, g)
        print(f"{g['id']}: {group_line(g)}")
        return 0
    return 2


def add_parsers(sub, common):
    """The puppeteer's commands, added to phi.py's parser."""
    for name in COMMANDS:
        p = sub.add_parser(name)
        common(p)
        if name == "watch":
            p.add_argument("--once", action="store_true")
            p.add_argument("--max-s", type=float, default=0)
            p.add_argument("--interval", type=float, default=0)
        if name == "ledger":
            p.add_argument("--net", action="store_true", help="read the issues' states from GitHub now")
        if name == "draft":
            p.add_argument("text", help="the words to run prompty, prompter and pioneer on")
        if name == "pioneer":
            p.add_argument("draft", help="the draft's id")
            p.add_argument("--request", action="store_true",
                           help="keep a clean draft as a start request, for a turn ezexe did not begin")
        if name == "routes":
            p.add_argument("--register", action="store_true", help="register every landed topic the records back")
            p.add_argument("--why", default="", help="a sessionId: say what its route still lacks")
        if name == "readings":
            p.add_argument("texts", nargs="+", help="each distinct reading")
            p.add_argument("--words", default="", help="ezexe's message")
        if name == "merge":
            p.add_argument("group")
            p.add_argument("--result", default="", help="the result the chain settled the fork on")
