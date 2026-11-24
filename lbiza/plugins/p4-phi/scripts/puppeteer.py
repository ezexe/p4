#!/usr/bin/env python3
"""puppeteer.py: the four steps p4-phi takes for an orchestrator, after the four diagrams of ezexe/p4's README.md.

It acts for an orchestrator with a task, or any session that started sessions. Its steps are routing, the
start draft, the gate and the watcher, which the functions `prompty`, `prompter`, `pioneer` and `look` run:

  linear     Routing reads ezexe's message against the records the ledger is built from: the area it names and the
             live session that is that area's code owner. The start draft is the exact next session: its topic, a
             brief written as its own instruction, its parent session and the issue it closes, started fresh, a
             worker in this checkout. The gate checks the draft: the issue it names is open, or it
             names none, p4-phi files none and the child's findings go up in its report; the parent session is the
             right orchestrator. A clean draft is handed as the exact start_session call; one whose area has a
             live code owner is routed there with SendMessage; one the depth or count cap holds starts no session.
             No draft waits on a running writer's files: every session works in the one checkout, on its own paths. The
             watcher is one look at a time over an orchestrator's subtree, which the
             plugin's hooks module runs inside Claude Code at a turn's end, at a message's arrival and on its
             timer: a look writes <session>/ledger.md from p4-phi's records and the app's session records, only
             when one of them changed, with a reconcile line for each divergence between the two. A puppeteer's
             slow look also lists the open issues of the repositories its controlled sessions work in, and keeps
             the ones no live session holds in <session>/open-issues.json for the line controls.py hands it.
  recursive  a landed topic registers its route in <session>/routes.jsonl beside the ledger, only when the records
             back what the reports claimed: the issue is closed, a commit that closes it is pushed, and the session
             and its children are archived with their outcome kept. Routing scores a message against the registered
             routes before a start draft is made; a route whose issue was reopened or whose commit was reverted is
             withdrawn.
  parallel   an under-determined message leaves two or more distinct readings open. Routing writes the readings, and
             the session is told to run the workflow the plugin ships, workflows/readings.js, as `/p4-phi:readings`:
             one agent for each reading, their results compared in the script, and either the one result they
             came to or the fork with its options and a default. Claude Code runs the agents and holds their
             results, by workflows.md, so p4-phi keeps no group of readings, starts no session for one and merges
             nothing itself. A run takes no input from a person, by the same page's "Behavior and limits", so only
             a fork goes to ezexe, as one question the session asks after the run.
  meta       the orchestrator that receives ezexe's message first runs a meta pass over every
             orchestrator's ledger and writes <home>/phi/meta-ledger.md: duplicate topics, orchestrators in conflict
             over the same files or issue, stale topics, and what is left open for the next generation.

The hooks that hand a session its lines are command hooks, which start no session and send no message, so the gate's
verdict is the exact call for the session to make, and the session, which can tell a question from work, makes it or
leaves it.

Commands, through phi.py: `ledger`, `look`, `draft "<words>"`, `pioneer <draft id>`, `routes`, `meta`,
`settle <session> "<what took it up>"`.
Settings: `puppeteer` set to false in phi/phi.json turns off the watcher and the prompt hook's steps, and
P4_PHI_PUPPETEER=0 or 1 overrides it for one run. P4_PHI_WATCH=0 runs no look, P4_PHI_WATCH_S sets the
watcher's tick in seconds, P4_PHI_WATCH_NET=0 keeps a look from reading GitHub, and P4_PHI_APP_SESSIONS names
the folder of the app's session records.
"""

import hashlib
import itertools
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import relay  # noqa: E402
import p4conf  # noqa: E402
import plans  # noqa: E402
import starts  # noqa: E402
import issues  # noqa: E402
import shared  # noqa: E402

PHI = None                       # phi.py's running module, which phi.py sets when it imports this one
WATCH_S = 5.0                    # the watcher's tick: the least seconds between two looks
WATCH_SLOW_S = 30.0              # its tick once nothing changed for WATCH_CALM_S
WATCH_CALM_S = 600.0
ISSUE_TTL_S = 120.0              # how long an issue's state read from GitHub is believed
GH_S = 6                         # one gh call of this module's, which a prompt hook may be waiting on
ROUTE_CHECK_S = 600.0            # how often registered routes are checked for a reopen or a revert
ROUTE_MIN = 4                    # content words a message shares with a route before it can match
ROUTE_CLOSE = 0.6                # of the smaller side's content words
OWNER_WORDS = 8                  # content words a message shares with a live session's task before that session is
#                                  named the area's code owner
TOPIC_WORDS = 3                  # content words a message shares with this session's task to be part of its topic
QUICK_WORDS = 6                  # a message of fewer content words is a quick thing, never drafted
STALE_S = 24 * 3600.0            # an orchestrator with open work and no turn this long is stale
WORDS_CHARS = 1500               # of a message and of a task, kept on a registered route for scoring
STOP = frozenset("""phi session sessions p4 plugin plugins please make sure also just now then when with that this
there their them they have has should would could will want need like into from about your you our out get got use
using one two all any each every not and for the are was were been being its it's can may must more most some such
than too very what which who how why where while after before over under again new old""".split())
DRAFT_RE = re.compile(r"phi draft (drf-[0-9a-f]{10}) for (\S+?)\.?(?:\s|$)")
READINGS = "p4-phi:readings"     # the workflow the plugin ships in workflows/readings.js, which runs as /p4-phi:readings
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


REPLACE_S = 5.0                  # seconds a write waits out readers that hold its file open


_LOOKED = [""]                   # the session folder the look in this process runs over, and '' outside a look


def _make(folder):
    """The folder a file goes in, made with what is above it. While a look runs, its own session folder is never
    made: once that folder is deleted the look writes nothing more, and no write of it brings the folder back,
    ezexe/p4#206. A folder below it is made one level at a time, which fails where the session folder is gone."""
    held = _LOOKED[0]
    if not held:
        os.makedirs(folder, exist_ok=True)
        return
    if not os.path.isdir(held):
        raise FileNotFoundError(f"{held}: the session folder of this look is gone")
    at, below = os.path.abspath(folder), []
    while os.path.normcase(at) != held and os.path.dirname(at) != at:
        below.append(at)
        at = os.path.dirname(at)
    if os.path.normcase(at) != held:               # a file of the store, outside the session folder
        os.makedirs(folder, exist_ok=True)
        return
    for d in reversed(below):
        try:
            os.mkdir(d)
        except FileExistsError:
            pass


def _write(path, text):
    """`text` written to `path` by the kit's one writer, which waits out the readers that hold the file open for
    REPLACE_S and leaves no temp where it gives up."""
    _make(os.path.dirname(path))
    p4conf.write_whole(path, text, wait=REPLACE_S)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _write_json(path, d):
    """`d` written to `path` as relay writes a file that is no session's record."""
    _write(path, json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _append(path, row):
    _make(os.path.dirname(path))
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def words(text):
    return plans.words(text) - STOP


def share(a, b):
    """The count of content words two texts share, and that count's share of the smaller side's content words."""
    wa, wb = words(a), words(b)
    both = wa & wb
    return len(both), (len(both) / min(len(wa), len(wb)) if wa and wb else 0.0)


# --- the tree ---------------------------------------------------------------------------------------------------------

def closed(s):
    """True when p4-phi's own records hold a session as closed: stale, counted as archived, or archived. Nothing is
    read from the app here, so a divergence between the two stays visible until it is reconciled."""
    return not isinstance(s, dict) or bool(s.get("stale") or s.get("doneRetired") or s.get("archived"))


def subtree(home, top, every=None):
    """The sessionId, depth and session.json of a session and of every session under it, in tree order."""
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
    """True for a session that orchestrates: one nobody started that has a task, or any session another session
    started, since below an orchestrator every worker is a terminal session with no record here."""
    if not isinstance(s, dict) or not s.get("sessionId"):
        return False
    return bool(relay._parent(s)) or bool(str(s.get("task") or "").strip())


def working(home, sid):
    """True while a session is inside a turn: its last prompt hook ran after its last Stop hook."""
    last = ""
    for r in _phi().read_rows(os.path.join(relay._dir(home, sid), "log.jsonl"), 256 * 1024):
        if r.get("hook") in ("user-prompt-submit", "stop"):
            last = r["hook"]
    return last == "user-prompt-submit"


# --- the app's records ------------------------------------------------------------------------------------------------

_APP = {}                        # each record's path to its mtime_ns and row, kept for one process


def app_roots(home, top):
    root = str(relay._session(home, top).get("appRoot") or "")
    if os.environ.get("P4_PHI_APP_SESSIONS"):
        return [os.environ["P4_PHI_APP_SESSIONS"]]
    return [root] if root and os.path.isdir(root) else _phi().app_roots()


LOOK_S = 1.0                     # how long one look at the app's folder is believed: a hook's whole run, a fifth of a tick
_LOOKS = {}                      # the roots to when they were looked at and each record's path, mtime_ns and size


def app_look(roots):
    """The path, mtime_ns and size of each of the app's session records, sorted by path. One look serves every
    ledger a hook builds or signs for LOOK_S, so the app's folder is listed and its records stat-ed once."""
    key = tuple(roots)
    held = _LOOKS.get(key)
    at = time.time()
    if held and 0 <= at - held[0] < LOOK_S:
        return held[1]
    out = []
    for root in roots:
        try:
            accounts = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            continue
        for a in accounts:
            try:
                orgs = sorted(os.scandir(a.path), key=lambda e: e.name) if a.is_dir() else []
            except OSError:
                continue
            for o in orgs:
                try:
                    files = list(os.scandir(o.path)) if o.is_dir() else []
                except OSError:
                    continue
                for f in files:
                    if f.name.startswith("local_") and f.name.endswith(".json"):
                        try:
                            st = f.stat()
                        except OSError:
                            continue
                        out.append((f.path, st.st_mtime_ns, st.st_size))
    out.sort()
    _LOOKS[key] = (at, out)
    return out


def app_cache_path(home):
    return os.path.join(home, "phi", ".cache", "app-index.json")


def app_cached(home):
    """Loads what the last hook or look read from the app's records, kept in the store as each record's path to
    its mtime_ns and row, so the next process reads one file and not every record. Only a record whose time changed
    is opened again."""
    if home and home not in _APP_LOADED:
        _APP_LOADED.add(home)
        try:
            with open(app_cache_path(home), encoding="utf-8") as f:
                d = json.load(f)
            for p, v in (d.items() if isinstance(d, dict) else ()):
                if isinstance(v, list) and len(v) == 2 and p not in _APP:
                    _APP[p] = (v[0], v[1])
        except (OSError, ValueError):
            pass


_APP_LOADED = set()


def app_index(roots, home=""):
    """Each session of the app's records by its sessionId, with its parent, whether it is archived, whether the app
    detached it to top level, its title and its name; each record file is read once after each change."""
    out = {}
    app_cached(home)
    read = 0
    for p, m, _ in app_look(roots):
        held = _APP.get(p)
        if not held or held[0] != m or (held[1] and "detached" not in held[1]):   # a row kept without that field
            read += 1
            d = relay._read_json(p)
            sp = d.get("spawnedFrom") if isinstance(d.get("spawnedFrom"), dict) else {}
            held = _APP[p] = (m, {"sessionId": str(d.get("sessionId") or ""), "parent": str(sp.get("sessionId") or ""),
                                  "archived": bool(d.get("isArchived")), "title": str(d.get("title") or "")[:120],
                                  "detached": bool(d.get("lineageDetached")),
                                  "name": str(sp.get("name") or "")} if d.get("sessionId") else None)
        if held[1]:
            out[held[1]["sessionId"]] = held[1]
    if read and home:
        try:
            keep = {p for p, _, _ in app_look(roots)}
            _write(app_cache_path(home), json.dumps({p: [v[0], v[1]] for p, v in _APP.items() if p in keep},
                                                    ensure_ascii=False))
        except OSError:
            pass
    return out


# --- issues -----------------------------------------------------------------------------------------------------------

def topic_issue(s, base=""):
    """The slug, number and repository path of the issue a session's work closes: the one p4-phi took for it, else
    the first `owner/name#N` its task names, and an empty slug, 0 and an empty path for none. No git runs here: a
    ledger is built from this for every session of a subtree on every change, and closing_pushed looks for the
    repository only once a route's other records back it."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if iss and iss.get("repo") and iss.get("number"):
        return str(iss["repo"]), int(iss["number"]), str(iss.get("path") or "")
    m = re.search(r"\b([\w.-]+/[\w.-]+)#(\d+)\b", str(s.get("task") or ""))
    return (m.group(1), int(m.group(2)), "") if m else ("", 0, "")


def states_path(home):
    return os.path.join(home, "phi", ".issue-states.json")


_CHECKED = {}                    # each issue's slug#n to when this process last read it from GitHub


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
            _write_json(states_path(home), kept)
    return got


# --- the open issues no session holds --------------------------------------------------------------------------------
# An open issue of a repository a puppeteer's controlled sessions work in is the puppeteer's to resolve. No page of
# the Claude Code docs and no tool of the app hands a session a repository's open issues, so a slow look of the
# puppeteer's own watcher lists them, one `gh issue list` a repository, and keeps the ones no live session holds in
# its folder's open-issues.json, which controls.open_issues_text reads. No hook reads GitHub for it.

OPEN_FILE = "open-issues.json"
OPEN_MOST = 100                  # the open issues one listing asks a repository for
OPEN_REPOS = 12                  # the repositories one puppeteer's looks list
LIST_S = 20                      # one `gh issue list` of a look, which no hook waits on


def open_path(home, sid):
    return os.path.join(relay._dir(home, sid), OPEN_FILE)


def held_issues(home, s):
    """Each issue a live session's record holds as `issue`, as `owner/name#N` in lower case, over a puppeteer's own
    store and the stores of the sessions it controls."""
    c, held, stores = _phi().controls, set(), {}
    for where in [home] + [str(e.get("store") or "") for e in c.controlled(s)]:
        if where:                                  # each store once, however its path is spelled
            stores.setdefault(os.path.normcase(os.path.abspath(where)), where)
    for store in stores.values():
        for k in relay._sessions(store).values():
            iss = k.get("issue") if isinstance(k.get("issue"), dict) else {}
            if iss.get("repo") and str(iss.get("number") or "").isdigit() and not c.out_of_tree(k):
                held.add(f"{str(iss['repo']).lower()}#{int(iss['number'])}")
    return held


def controlled_repos(home, s):
    """The GitHub repositories the sessions a puppeteer controls work in, each as its `owner/name`, OPEN_REPOS at
    most: the repository of each issue a session of a controlled tree holds, then the repository of each controlled
    session's folder and those nested one or two folders under it."""
    held, at = [], []
    for e in _phi().controls.controlled(s, home):
        store = str(e.get("store") or "")
        if not store:
            continue
        every = relay._sessions(store)
        for _, _, k in subtree(store, e["sessionId"], every):
            iss = k.get("issue") if isinstance(k.get("issue"), dict) else {}
            held.append(str(iss.get("repo") or ""))
        folder = str((every.get(e["sessionId"]) or {}).get("cwd") or "") \
            or os.path.dirname(os.path.dirname(os.path.abspath(store)))
        if folder not in at:
            at.append(folder)
    out = []
    for slug in itertools.chain(held, (slug for folder in at for _, slug in issues.repos_at(folder))):
        if len(out) >= OPEN_REPOS:
            break                                  # the folders past it are not asked for their repositories
        if slug and slug.lower() not in [x.lower() for x in out]:
            out.append(slug)
    return out


def list_open(home, sid):
    """A puppeteer's slow look at GitHub: the open issues of the repositories its controlled sessions work in, with
    each one a live session's record holds as `issue` dropped, kept in open-issues.json in the puppeteer's folder.
    Each repository is listed with one `gh issue list`, and never one listed less than ISSUE_TTL_S ago; one gh
    could not list keeps what was last listed. A session that is no puppeteer or controls none lists nothing, and
    nothing is listed with the issue loop off. Returns what the file holds."""
    c = _phi().controls
    s = relay._session(home, sid)
    if not issues.on(home) or not c.controlled(s) or not c.is_puppeteer(s, conf_store(home, sid)):
        return {}
    path = open_path(home, sid)
    kept = relay._read_json(path).get("repos")
    kept = kept if isinstance(kept, dict) else {}
    held, at, repos = held_issues(home, s), time.time(), {}
    for slug in controlled_repos(home, s):
        row = kept.get(slug) if isinstance(kept.get(slug), dict) else {}
        last = row.get("at") if isinstance(row.get("at"), (int, float)) else 0
        if at - last > ISSUE_TTL_S:
            r = issues.gh(["issue", "list", "-R", slug, "--state", "open", "--limit", str(OPEN_MOST), "--json",
                           "number,title"], timeout=LIST_S)
            try:
                listed = json.loads(r.stdout) if r is not None and r.returncode == 0 else None
            except ValueError:
                listed = None
            if isinstance(listed, list):
                row = {"at": at, "time": now(),
                       "issues": [{"number": int(x["number"]), "title": _short(x.get("title"), 200)} for x in listed
                                  if isinstance(x, dict) and str(x.get("number") or "").isdigit()]}
        if row:
            repos[slug] = dict(row, issues=[x for x in row.get("issues") or [] if isinstance(x, dict)
                                            and f"{slug.lower()}#{x.get('number')}" not in held])
    if repos != kept:
        _write_json(path, {"repos": repos})
    return {"repos": repos}


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
    read, and the app's session records."""
    import progress                                # it imports this module at its head, so it is read here
    parts = [_stat(starts.path_of(home)), _stat(states_path(home))]
    parts.append(_stat(os.path.join(home, "phi", "sessions")))     # a new flat session's folder
    for d in relay.session_dirs(home):             # the root's flat sessions and those of each node's folder
        parts.append(_stat(os.path.join(d, "session.json")))
        parts.append(_stat(os.path.join(d, progress.TEAM)))        # a lead can stand outside the subtree
    ids = set()
    for sid, _, _ in subtree(home, top):
        ids.add(sid)
        d = relay._dir(home, sid)
        parts += [_stat(os.path.join(d, f)) for f in SOURCES[1:]]
    # of the app's records: those of the subtree's sessions as they change, and the others by name, so a new one
    # counts once and another tree's activity leaves this ledger alone
    for p, m, size in app_look(roots):
        parts.append(f"{p}|{m}|{size}" if os.path.basename(p)[:-5] in ids else p)
    return hashlib.sha1("\n".join(parts).encode("utf-8", "replace")).hexdigest()


def outcome_kept(home, parent, sid):
    """True when the parent session holds a closed child's outcome as a `replaces:` note."""
    mark = f"({sid})"
    return any(str(r.get("claim") or "").lstrip().startswith("replaces:") and mark in str(r.get("claim"))
               for r in relay._rows(os.path.join(relay._dir(home, parent), "notes.jsonl")))


def build(home, top, net=False):
    """The ledger of an orchestrator as data: its reconcile lines, a row for each session of its subtree, their open
    background tasks, the start requests waiting, the issues tied to them, and the work closed sessions left
    unfinished. A subagent that wrote files is a level miss."""
    phi = _phi()
    every = relay._sessions(home)
    tree = subtree(home, top, every)
    roots = app_roots(home, top)
    app = app_index(roots, home)
    ids = {sid for sid, _, _ in tree}
    rows, shut, tasks, tied, reconcile, misses = [], [], [], {}, [], []
    for sid, depth, s in tree:
        title = phi.title_of(s)
        parent = relay._parent(s)
        rec = app.get(sid)
        if closed(s):
            if depth:
                how = ("stale" if s.get("stale") else "finished and counted as archived" if s.get("doneRetired")
                       else "archived")
                shut.append({"sessionId": sid, "title": title, "parent": parent, "how": how,
                             "kept": outcome_kept(home, parent, sid)})
            continue
        root = str(s.get("appRoot") or "")
        if sid.startswith("local_") and root and os.path.isdir(root) and root in roots:
            if rec is None:
                reconcile.append(f"p4-phi lists \"{title}\" `{sid}` as live, and the app holds no record of it.")
            elif rec["archived"]:
                reconcile.append(f"p4-phi lists \"{title}\" `{sid}` as live, and the app has archived it.")
        held = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
        if rec and depth and rec["parent"] and rec["parent"] != parent \
                and held.get("source") not in ("detached", "reparented"):
            reconcile.append(f"the app shows \"{title}\" `{sid}` started by `{rec['parent']}`, and p4-phi holds it "
                             f"under `{parent}`.")
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
                     "status": (relay.default_status(title, relay.asks_ezexe_in(last.get("report")))
                                if relay.asks_ezexe_in(last.get("report")) else ""),
                     "step": {"addr": cur.get("addr"), "content": _short(cur.get("content"), 90)} if cur else None,
                     "stepsDone": sum(1 for x in steps if x.get("status") == "completed"), "steps": len(steps),
                     "open": [_short(x.get("content"), 90) for x in steps if x.get("status") != "completed"][:8],
                     "issue": f"{slug}#{n}" if n else "", "issueState": state,
                     "shard": relay.shard_of(s)[:6], "files": relay.edited_files(home, sid)[:40],
                     "task": _short(s.get("task"), 300)})
        for st, t in plans._tasks(plan):
            wrote = list(t.get("wrote") or [])
            if t.get("agent") and wrote:
                misses.append({"id": str(t.get("id")), "sessionId": sid, "title": title,
                               "step": (st or {}).get("addr", ""), "wrote": wrote[:8]})
        for t in plans.in_flight(s):               # hooks.md, Stop input: still running at its last turn's end
            tasks.append({"id": str(t.get("id")), "tool": str(t.get("type") or ""), "sessionId": sid,
                          "title": title, "step": "", "what": _short(t.get("description") or t.get("command"), 120),
                          "at": str(s.get("backgroundAt") or "")})
    live = {r["sessionId"] for r in rows}
    for aid, rec in sorted(app.items()):
        if rec["parent"] in live and not rec["archived"] and aid not in every:
            reconcile.append(f"the app shows \"{rec['title'] or aid}\" `{aid}` started by `{rec['parent']}`, and p4-phi "
                             f"holds no session for it.")
    asked = []
    at = time.time()
    for r in starts.state(home).values():
        if r.get("requester") not in ids or r.get("started") or at - float(r.get("at") or 0) > starts.EXPIRE_S:
            continue
        how = ("shown as a suggested task card" if (r.get("claimed") or {}).get("card")
               else "claimed" if r.get("claimed") else "pending")
        asked.append({"id": r["id"], "title": r.get("title", ""), "requester": r.get("requester"), "state": how})
    left =[{"sessionId": sid, "title": phi.title_of(s), "time": s["unfinishedAtArchive"].get("time", ""),
             "items": list(s["unfinishedAtArchive"].get("items") or [])}
            for sid, depth, s in tree if depth and isinstance(s.get("unfinishedAtArchive"), dict)
            and not s["unfinishedAtArchive"].get("settled")]            # read from the records, with no git here
    import progress                                # it imports this module at its head, so it is read here
    teams = []
    for sid, s in sorted(every.items()):           # a lead typed into a terminal is under no session of the tree
        mates = [] if closed(s) else progress.team_of(home, sid)
        if any(x["state"] not in progress.OVER for x in mates):
            where = ("" if sid in ids else "in another tree" if relay._parent(s)
                     else "a terminal session outside this tree")
            teams.append({"sessionId": sid, "title": phi.title_of(s), "where": where,
                          "teammates": [{"name": x["name"], "state": x["state"], "task": x["task"]} for x in mates]})
    return {"top": top, "title": phi.title_of(every.get(top, {})), "parent": relay._parent(every.get(top, {})),
            "reconcile": reconcile, "rows": rows, "closed": shut, "tasks": tasks, "misses": misses, "requests": asked,
            "issues": tied, "unfinished": left, "teams": teams}


def render(m):
    """A ledger's data as ledger.md. It carries no clock, so the same records give the same page."""
    where = f"started by `{m['parent']}`" if m["parent"] else "an orchestrator"
    out = [f"# Ledger: {m['title']}", "",
           f"Orchestrator `{m['top']}`, {where}.",
           "Written by p4-phi from its own records and the app's session records, by its watcher, its prompt hook, its "
           "meta pass and its `ledger` command alike, and rewritten only when what it shows changes.",
           "Edit nothing here: change the records.", ""]
    if m.get("unfinished"):
        out += ["## Unfinished at archive", ""]
        for u in m["unfinished"]:
            out.append(f"- \"{u['title']}\" `{u['sessionId']}`, checked {u['time']}:")
            out += [f"  - {x}" for x in u["items"]]
        out.append("")
    out += ["## Reconcile", ""]
    out += [f"- {x}" for x in m["reconcile"]] or ["- Nothing diverges: p4-phi's records and the app's records agree."]
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
            bits.append("owned paths " + ", ".join(r["shard"]))
        if r.get("status"):                        # a call its own context covers: a status line, not a question card
            bits.append(r["status"])
        elif r["report"]:
            bits.append(f"reported \"{r['report']}\"")
        name = f", {r['name']}" if r["name"] else ""
        out.append(f"{'  ' * r['depth']}- \"{r['title']}\" `{r['sessionId']}`{name}: " + "; ".join(bits))
    if m["closed"]:
        out += ["", "## Closed", ""]
        out += [f"- \"{c['title']}\" `{c['sessionId']}`: {c['how']}, its outcome "
                + ("kept as a replaces: note" if c["kept"] else "not kept") + f" on `{c['parent']}`" for c in m["closed"]]
    if m["tasks"]:
        out += ["", "## Background tasks", ""]
        out += [f"- {t['id']}, {t['tool'] or 'a task'} of \"{t['title']}\""
                + (f" under step {t['step']}" if t["step"] else "") + f", running at {t['at']}: {t['what']}"
                for t in m["tasks"]]
    if m.get("misses"):
        out += ["", "## Level misses", ""]
        out += [f"- subagent {x['id']} of \"{x['title']}\" `{x['sessionId']}`"
                + (f" under step {x['step']}" if x["step"] else "") + " wrote " + ", ".join(x["wrote"])
                + ": a part that writes files runs in a session of its own, never in a subagent" for x in m["misses"]]
    if m.get("teams"):
        out += ["", "## Agent teams", ""]
        for t in m["teams"]:
            out.append(f"- led by \"{t['title']}\" `{t['sessionId']}`"
                       + (f", {t['where']}" if t["where"] else "") + ":")
            out += [f"  - teammate {x['name']}, {x['state']}" + (f": {x['task']}" if x["task"] else "")
                    for x in t["teammates"]]
    if m["requests"]:
        out += ["", "## Start requests", ""]
        out += [f"- {r['id']} \"{r['title']}\" for {r['requester']}: {r['state']}" for r in m["requests"]]
    if m["issues"]:
        out += ["", "## Issues", ""]
        out += [f"- {k}: {v['state'] or 'state not read'}, of {', '.join(v['sessions'])}"
                for k, v in sorted(m["issues"].items())]
    return "\n".join(out) + "\n"


_NET = {}                        # each orchestrator to when this process last rebuilt its ledger with GitHub read


def refresh(home, top, net=False, force=False):
    """ledger.md and ledger.json of an orchestrator, rebuilt only when a source changed, or when the issues' states
    are due to be read again, and rewritten only when the page differs. Returns the page and True when it was
    rewritten."""
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
        _write_json(model_path(home, top), m)
    after = signature(home, top, roots) if net else sig      # an issue state read now is a source too
    if _read(sig_path).strip() != after:
        _write(sig_path, after + "\n")
    return text, changed


def model(home, top):
    """An orchestrator's ledger as data, refreshed first."""
    refresh(home, top)
    return relay._read_json(model_path(home, top)) or build(home, top)


# --- the watcher ------------------------------------------------------------------------------------------------------
# The watcher runs from the plugin's hooks module, hooks/register.ts, inside Claude Code. The module starts
# `phi.py look` at the events of its session that change what the ledger shows, a turn's end and a message's
# arrival, and on its timer for what no event of that session shows: the sessions below it, the app's records and
# GitHub. A look is one pass and ends. The module keeps one look in flight at most, and paces itself by what a look
# answers.

def tick(home, top, net=True, slow=True):
    """One look of the watcher: the closed sessions checked for unfinished work, the ledger, and, when the ledger
    changed or the look is a slow one, the landed topics registered as routes and the registered routes checked.
    `net` lets the look read GitHub, and a slow look that reads it lists, for a puppeteer, the open issues no live
    session holds."""
    try:
        archive_checks(home, top)                   # once for each session, when it closes
    except Exception:  # noqa: BLE001
        pass
    _, changed = refresh(home, top, net=net)
    if changed or slow:
        try:
            if register_routes(home, top, net=net):
                refresh(home, top)
            check_routes(home, net=net)
        except Exception:  # noqa: BLE001
            pass
    if net and slow:
        try:
            list_open(home, top)                    # a puppeteer's open issues, as often as its slow reads of GitHub
        except Exception:  # noqa: BLE001
            pass
    return changed


def conf_store(home, top):
    """The store whose p4.json sets an orchestrator's caps: its project's own, found from the folder it runs in, as
    phi.Me reads them for its hooks; `home` when that folder holds none. `home` can be the shared store phi.home
    names, whose p4.json is another project's."""
    s = relay._session(home, top)
    return _phi().store_at(str(s.get("cwd") or "")) or home


def pace(home, top="", watching=False):
    """What the hooks module paces a session's looks by, in seconds: `watch_s`, the least time between two looks,
    `wait_s`, how long its timer waits after this one, and `net_s`, how often a look reads GitHub and checks the
    routes. P4_PHI_WATCH_S sets both ticks for one run. Without it the least time is WATCH_S, and the wait is WATCH_S
    while the orchestrator's sources change and WATCH_SLOW_S once they stood still for WATCH_CALM_S, which the time
    of ledger.sig tells, a file written only when a source changed. A session with no look to run waits WATCH_SLOW_S,
    and the module doubles that wait at each such answer."""
    try:
        quick = max(float(os.environ.get("P4_PHI_WATCH_S") or 0), 0.0)
    except ValueError:
        quick = 0.0
    calm = not watching
    if watching:
        try:
            calm = time.time() - os.path.getmtime(os.path.join(relay._dir(home, top), "ledger.sig")) >= WATCH_CALM_S
        except OSError:
            calm = False
    return {"watch_s": quick or WATCH_S, "wait_s": quick or (WATCH_SLOW_S if calm else WATCH_S), "net_s": ISSUE_TTL_S}


def look(home, sid, net=False, folder_only=False):
    """One look over the subtree of the session `sid`, run by the hooks module, and what the module reads of it.
    The answer holds `dir`, the session's folder, where it has one; `starter`, the session that started it as
    phi.starter_cli answers it, where the module sends the report of each of its turns; `watching`, True when the
    session is an orchestrator and the look went over its subtree; `why`, what kept the look from running; `off`,
    True when P4_PHI or P4_PHI_WATCH is 0, where the module runs no look at all; `changed`, True when the ledger was
    rewritten; `net`, True when the look read GitHub; `upkeep`, the prompt upkeep.wake answers for a turn the
    module starts, asked for only at a look that rewrote the ledger or is a slow one; and the three times of `pace`.
    `net` asks for a slow look, which reads GitHub unless P4_PHI_WATCH_NET is 0 and checks the routes.
    `folder_only` answers the folder and does nothing else.
    A session whose folder was never made, or was deleted, gets no look: nothing is written and no folder is made,
    and a folder deleted while the look runs stays gone, ezexe/p4#206."""
    sid = _phi().safe_id(sid)
    folder = relay._dir(home, sid) if sid else ""
    if not sid or not os.path.isfile(os.path.join(folder, "session.json")):
        return {"watching": False, "why": "no session folder", **pace(home)}
    out = {"watching": False, "dir": folder.replace("\\", "/")}
    try:                                            # where the module sends the report of a worker's turn
        starter = _phi().starter_cli(home, relay._session(home, sid))
    except Exception:  # noqa: BLE001
        starter = ""
    if starter:
        out["starter"] = starter
    if folder_only:
        return out
    if os.environ.get("P4_PHI") == "0" or os.environ.get("P4_PHI_WATCH") == "0":
        return dict(out, off=True, why="off")
    if not on(home):
        return dict(out, why="the puppeteer steps are off", **pace(home))
    if not orchestrator(home, relay._session(home, sid)):
        return dict(out, why="no orchestrator", **pace(home))
    try:                                            # the project's caps, WATCH_S and STALE_S among them, from the
        _phi().project_conf(conf_store(home, sid))  # orchestrator's own store, as its hooks read them
    except Exception:  # noqa: BLE001
        pass
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")      # no git or gh call of a look ever waits on a person
    os.environ.setdefault("GH_PROMPT_DISABLED", "1")
    reads = bool(net) and os.environ.get("P4_PHI_WATCH_NET") != "0"
    changed = False
    _LOOKED[0] = os.path.normcase(os.path.abspath(folder))
    try:
        changed = tick(home, sid, net=reads, slow=bool(net))
    except Exception:  # noqa: BLE001
        pass
    finally:
        _LOOKED[0] = ""
    if not os.path.isdir(folder):
        return {"watching": False, "why": "no session folder", **pace(home)}
    if relay.gone(home, relay._session(home, sid)):       # the look that shows its end, then none
        return dict(out, why="closed", changed=changed, **pace(home))
    if changed or net:                              # upkeep that is due while every started session is idle
        try:
            due = _phi().upkeep.wake(home, sid, conf_store(home, sid))
        except Exception:  # noqa: BLE001
            due = ""
        if due:
            out["upkeep"] = due
    return dict(out, watching=True, changed=changed, net=reads, **pace(home, sid, True))


# --- routes: the loop that recurses -----------------------------------------------------------------------------------

def routes_path(home, sid):
    return os.path.join(relay._dir(home, sid), "routes.jsonl")


def all_routes(home):
    """{route id: route row} of every route registered in the store and not withdrawn since."""
    out = {}
    for p in sorted(os.path.join(d, "routes.jsonl") for d in relay.session_dirs(home)
                    if os.path.isfile(os.path.join(d, "routes.jsonl"))):
        for r in relay._rows(p):
            rid = r.get("id")
            if r.get("kind") == "route" and rid:
                out[rid] = dict(r, file=p)
            elif r.get("kind") == "withdrawn":
                out.pop(rid, None)
    return out


def closing_pushed(home, s, slug, n, repo):
    """The short sha, subject and repository of a pushed commit that closes the issue, made since the session began,
    and three empty strings for none."""
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
    """Returns True and the closing commit when the records back a landed topic's reports: the session and its
    workers are archived with their outcome kept, its issue is closed, and a commit that closes it is pushed.
    Returns False and what is missing otherwise."""
    sid = s["sessionId"]
    slug, n, repo = topic_issue(s)
    if not n:
        return False, "its work names no issue"
    parent = relay._parent(s)
    if not (closed(s) or relay.gone(home, s)):
        return False, "the session is not archived"
    if parent and not outcome_kept(home, parent, sid):
        return False, "its outcome is not kept on its parent session"
    for kid, depth, k in subtree(home, sid)[1:]:
        if not (closed(k) or relay.gone(home, k)):
            return False, f"the session {kid} under it is not archived"
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
            "shape": {"parent": "a child of an orchestrator" if parent and not relay._parent(above) else
                      "an orchestrator" if not parent else "a child of an orchestrator",
                      "children": len(subtree(home, sid)) - 1, "archiveWhenDone": bool(s.get("disposable")),
                      "steps": [_short(x.get("content"), 100) for x in plan.get("steps") or []][:12]},
            "slice": {"brief": _short(s.get("task"), WORDS_CHARS),
                      "paths": [p for p in relay.child_paths(home, s) if not relay.names_nothing(p, home, base)][:12]},
            "context": "fork" if s.get("forked") else "fresh", "issue": f"{slug}#{n}", "session": sid,
            "registeredBy": parent or sid, "commit": commit}


def register_routes(home, top, net=False):
    """Registers each landed topic under an orchestrator once, beside the ledger, when its records back it. Returns
    the routes this call registered."""
    rows = [r for d in relay.session_dirs(home) for r in relay._rows(os.path.join(d, "routes.jsonl"))
            if r.get("kind") == "route"]
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
    """Withdraws the registered routes whose issue was reopened or whose commit was reverted, and returns those this
    call withdrew. The routes are looked at once every ROUTE_CHECK_S."""
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
    """The score, the count of shared words and the route of each registered route a message matches closely, the
    best first, by shared content words at ROUTE_MIN and ROUTE_CLOSE."""
    out = []
    rows = list(all_routes(home).values())
    texts = [f"{r.get('words', '')} {r.get('topic', '')}" for r in rows]
    for k, r in enumerate(rows):
        n, part = share(req, texts[k])
        if n >= ROUTE_MIN and part >= ROUTE_CLOSE:
            out.append((round(part, 2), n, r))
    return sorted(out, key=lambda x: (-x[0], -x[1], str(x[2].get("id"))))


# a message that asks about earlier work: it names an earlier session or conversation, asks whether something was
# done before, or asks what was decided, concluded, landed or settled
EARLIER = re.compile(r"\b(?:earlier|previous|prior|past|older|last|another|other)\s+(?:sessions?|conversations?|"
                     r"chats?|transcripts?)\b|"
                     r"\b(?:did|have|had|didn't|haven't)\s+(?:we|you|i)\b[^.?!\n]*\b(?:before|earlier|already|"
                     r"previously|yesterday|ago|last\s+(?:time|week|month))\b|"
                     r"\b(?:what|which|where|when|why)\b[^.?!\n]*\b(?:did|had|have)\s+(?:we|you|i)\b[^.?!\n]*"
                     r"\b(?:decided?|concluded?|land(?:ed)?|settled?)\b", re.I)
SEARCH_TOOL = "mcp__ccd_session_mgmt__search_session_transcripts"


def earlier_text(home, req):
    """The one line for a message of ezexe's that asks about earlier work and matches no registered route: the
    desktop app's own tool that searches the transcripts of its sessions by words, which p4-phi builds no copy of.
    '' for any other message, and where routing is off. Whose message it is and whether the app hosts the session,
    which alone has the tool, are the caller's to tell."""
    if not on(home) or not EARLIER.search(str(req or "")) or score_routes(home, req):
        return ""
    return (f"phi (p4-phi): this message of ezexe's asks about earlier work and matches no registered route, and "
            f"p4-phi finds no earlier turn by a message's words: search the app's transcripts for it with "
            f"`{SEARCH_TOOL}`.")


# --- routing: the message read against the tree's records -------------------------------------------------------------

def readings_of(req):
    """The distinct readings a message names itself, as in "either A or B" or "A, or maybe B", and an empty list
    when it names one."""
    m = EITHER.search(req) or OR_MAYBE.search(req)
    if not m:
        return []
    a, b = (" ".join(x.split()).strip(" ,.;:") for x in m.groups())
    return [a, b] if a and b and a.lower() != b.lower() else []


# the app's marks of a message that is not ezexe's, for a prompt whose origin does not say whose it is, rows.whose,
# at the start of its body once the leading reminders are off:
# another session's message, a side-sessions event, a task notification, a system notification, a hook's words
# given back to the session, or a slash command's wrapper, which rows.HARNESS_RE takes for the harness's too, and
# the prompt of a turn the plugin's hooks module started, which opens with plans.WAKE_MARK, or of the sweep a
# schedule fires, which opens with plans.SWEEP_MARK. A paste that holds such a tag further in is still ezexe's.
SESSION_MARK = re.compile(r"\A\s*(?:" + re.escape(plans.WAKE_MARK) + "|" + re.escape(plans.UPKEEP_MARK)
                          + "|" + re.escape(plans.SWEEP_MARK) + r"|Another Claude session sent a message:|"
                          r"<cross-session-message\b|"
                          r"<side-sessions-event\b|<task-notification\b|<command-name\b|<command-message\b|"
                          r"<local-command|\[SYSTEM NOTIFICATION\b|\[MESSAGE FROM NON-USER SOURCE\b|"
                          r"\[Cross-session (?:delivery|idle) notice\]|"
                          r"(?:Stop|SubagentStop|UserPromptSubmit) hook (?:feedback|blocking))", re.I)


def from_session(prompt, by=""):
    """True for a message that is not ezexe's own. `by` is whose words it is by the origin Claude Code stamped on
    the prompt, rows.whose, and it settles the answer where it says: another session's message, a plugin's prompt,
    a background task's notification and a prompt a schedule fired are not ezexe's, and ezexe's own message is,
    whatever it opens with.
    Where the origin does not say, the app's marks tell: the body, past its leading reminders, opens with a
    cross-session message, a side-sessions event, a task notification, a system notification, a hook's feedback or
    a slash command's wrapper. Every other message a puppeteer is given is ezexe's, and only those are read for
    work or kept as requests."""
    if by:
        return by != "user"
    text = str(prompt or "")
    reminder = _phi().REMINDER
    while reminder.match(text):
        text = reminder.sub("", text, count=1)
    return bool(SESSION_MARK.match(text))


def own_message(home, s, req):
    """True for a message of ezexe's to a puppeteer that controls.route_down sends to a controlled session's topic:
    the puppeteer sends it there, and drafts no start for it (#230). Its own orchestration and wrap-up reach it as
    other sessions' messages, which from_session tells by the app's marks, never by ezexe's words."""
    return bool(_phi().controls.route_down(s, str(req or "")))


def prompty(home, s, req, base):
    """Routing: ezexe's message read against the records the ledger is built from. It returns the paths and words
    the message carries, whether it is work at all, the live session that is its area's code owner, the registered
    routes it matches, and the readings it leaves open. Whether the message is within this session's own topic is
    read against its own scope, relay.scope_of, which holds no other session's path. The owner by path is found by
    the address book, book.holders, over the owned paths of every live session that is not this one or above it:
    it reads each path from its own repository's root and so finds a worker in a git worktree of its own, where the
    absolute path a message names and the one a worker owns never meet."""
    phi = _phi()
    sid = s["sessionId"]
    every = relay._sessions(home)
    named = [p for p in relay.paths_in(req, base) if not relay.names_nothing(p, home, base)]
    read = {"words": req, "paths": named, "work": issues.writing(req) and len(words(req)) >= QUICK_WORDS,
            "owner": None, "routes": [], "readings": readings_of(req), "own": False,
            "within": True}
    if not read["work"]:
        return read
    read["own"] = any(plans.bears(req, st.get("content")) for st in plans.open_steps(home, sid))
    first = not phi.load_turns(home, sid) and " ".join(req.split())[:200] in " ".join(str(s.get("task") or "").split())
    read["within"] = first or read["own"] or share(req, s.get("task"))[0] >= TOPIC_WORDS or any(
        relay.overlap(p, q) for p in named for q in relay.scope_of(home, sid) if not relay.names_nothing(q, home, base))
    above = set(phi.chain_of(home, sid))
    best = None
    others = [(oid, o, f"{o.get('task', '')} " + " ".join(str(x.get("content") or "")
                                                         for x in plans.open_steps(home, oid)))
              for oid, o in every.items()
              if not (oid == sid or oid in above or closed(o) or relay.gone(home, o))]
    try:                                            # it reads the app's records: a failure costs the path arm alone
        import book
        owned = {e["id"]: what for e, what in book.holders(home, s if s.get("cwd") else {**s, "cwd": base}, req,
                                                           conf_store(home, sid), below=False, owned=True)}
    except Exception:  # noqa: BLE001
        owned = {}
    for k, (oid, o, text) in enumerate(others):
        hit = owned.get(oid, "")
        n, _ = share(req, text)
        if hit:
            cand = (2, len(hit), oid, f"its owned paths hold {hit}")
        elif n >= OWNER_WORDS:
            cand = (1, n, oid, f"its task shares {n} content words with the message")
        else:
            cand = None
        if cand and (best is None or cand[:2] > best[:2]):
            best = cand
    if best:
        read["owner"] = {"sessionId": best[2], "title": phi.title_of(every[best[2]]), "why": best[3]}
    read["routes"] = [{"score": sc, "shared": n, "id": r["id"], "topic": r.get("topic"), "context": r.get("context"),
                       "shape": r.get("shape"), "slice": r.get("slice"), "issue": r.get("issue")}
                      for sc, n, r in score_routes(home, req)[:3]]
    return read


# --- the start draft: the exact next session --------------------------------------------------------------------------

def drafts_dir(home, sid):
    return os.path.join(relay._dir(home, sid), "drafts")


def load_draft(home, sid, did):
    return relay._read_json(os.path.join(drafts_dir(home, sid), f"{did}.json")) if sid and did else {}


def arrived(s, prompt):
    """A started session's first message: the draft its brief names is kept on it, which changes s."""
    m = DRAFT_RE.search(str(prompt or ""))
    if m and not s.get("draft"):
        s["draft"] = m.group(1)
    return bool(s.get("draft"))


# the lines a worker's brief carries, since its start passes `use_worktree: false`: where it works, what it may change
# and how it commits, as a terminal worker's brief says them
CHECKOUT_LINES = [
    "This session works in the checkout it is started in, on the branch checked out there, beside other sessions. It "
    "makes no worktree and no branch, and runs no `git stash`, `git reset`, `git switch` or `git checkout <branch>`.",
    "It changes only the paths of its `Files:` line. p4-phi refuses an edit outside them: a path it needs beyond them "
    "is asked of the session that started it, by SendMessage.",
    "It commits only by `{cmd} commit -m \"<message>\" -- <path> ...`, naming every path it changed, added or "
    "removed and no other, and never by `git add` or `git commit`. It pushes and merges nothing: its tree's "
    "orchestrator pushes.",
]


def checkout_lines(base=""):
    """A worker's brief on where it works, what it may change and how it commits, then one empty line."""
    cmd = _phi().commands()
    return [line.replace("{cmd}", cmd) for line in CHECKOUT_LINES] + [""]


def topic_of(req):
    first = re.split(r"(?<=[.!?])\s+|\n+", " ".join(str(req).split()), maxsplit=1)[0]
    first = re.sub(r"^\W*(?:(?:please|now that|now|also|and|so|ok|okay|can you|could you)\s+)+", "", first, flags=re.I)
    return relay.clause_cut(first, 58).strip(" .,;:")


TESTS_MOST = 6                   # the test files one brief names
TESTS_SCANNED = 60               # the test files of one folder read for an import
TESTS_WALKED = 2000              # the files of one `tests` folder looked at for a test file's name
TEST_BYTES = 64 * 1024           # of each, the part read


def _above(base, folder):
    """`folder` and each folder above it up to `base`, nearest first, each as (how the brief's path spells it, where
    it is). A folder outside `base` is climbed no further than itself."""
    if not os.path.isabs(folder):
        bits = [b for b in folder.split("/") if b]
        for i in range(len(bits), -1, -1):
            spelled = "/".join(bits[:i])
            yield spelled, os.path.join(base or "", spelled)
        return
    top = os.path.normcase(os.path.normpath(base)) if base else ""
    at = folder.rstrip("/") or folder
    while True:
        yield at, at
        here, up = os.path.normcase(os.path.normpath(at)), os.path.dirname(at)
        if not top or up == at or here == top or not here.startswith(top + os.sep):
            return
        at = up


def _tests_under(folder):
    """The test files under a `tests` folder, as paths from it with forward slashes, sorted, with TESTS_WALKED files
    looked at at most and no folder whose name starts with a dot."""
    found, seen = [], 0
    for d, dirs, files in os.walk(folder):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in ("__pycache__", "node_modules"))
        for f in sorted(files):
            seen += 1
            if f.startswith("test_") and f.endswith(".py"):
                found.append(os.path.relpath(os.path.join(d, f), folder).replace("\\", "/"))
        if seen >= TESTS_WALKED:
            break
    return sorted(found)


def test_files(base, paths):
    """The test files of the paths a brief covers, TESTS_MOST at most, each as the brief's own path spells its
    folder: for a python file, `test_<name>.py` and the test files that import it, beside it and in the `tests`
    folder of its folder and of each folder above it up to `base`, nearest first and the one named after it first.
    A `tests` folder at a project's top or beside the code is where pytest's good practices lay a project's tests,
    https://docs.pytest.org/en/stable/explanation/goodpractices.html. A brief names these, and never a whole suite,
    so its worker runs the tests its change touches, ezexe/p4#234."""
    out = []
    for p in paths:
        p = str(p).replace("\\", "/")
        folder, name = os.path.split(p)
        stem, ext = os.path.splitext(name)
        if ext != ".py" or name.startswith("test_"):
            continue
        imports = re.compile(rf"^\s*(?:import|from)\s+{re.escape(stem)}\b", re.M)
        for nearest, (spelled, at) in enumerate(_above(base, folder)):
            held = []                                   # (how it is spelled, where it is, its test files)
            if not nearest:
                try:
                    held.append((spelled, at, sorted(n for n in os.listdir(at)
                                                     if n.startswith("test_") and n.endswith(".py"))))
                except OSError:
                    pass
            tests = os.path.join(at, "tests")
            if os.path.isdir(tests):
                held.append((f"{spelled}/tests" if spelled else "tests", tests, _tests_under(tests)))
            for where, root, names in held:
                hits = [n for n in names if n.rsplit("/", 1)[-1] == f"test_{stem}.py"]
                for n in names[:TESTS_SCANNED]:
                    if n in hits:
                        continue
                    try:
                        with open(os.path.join(root, n), encoding="utf-8", errors="replace") as f:
                            if imports.search(f.read(TEST_BYTES)):
                                hits.append(n)
                    except OSError:
                        pass
                for n in hits:
                    named = f"{where}/{n}" if where else n
                    if named not in out:
                        out.append(named)
                    if len(out) >= TESTS_MOST:
                        return out
    return out


def spelled(p):
    """A path as it is spelled on disk where it is there, with forward slashes; else `p` as given. Each part is
    matched against the names its folder lists, so a case-insensitive file system gives the spelling it holds, and
    no link is followed: os.path.realpath fixes no case on macOS and turns /var into /private/var there."""
    try:
        if not os.path.lexists(p):
            return p
        drive, rest = os.path.splitdrive(os.path.abspath(p))
        parts = [x for x in rest.replace("\\", "/").split("/") if x]
        at = drive.upper() + "/" if drive else "/"
        for part in parts:
            names = os.listdir(at)
            got = part if part in names else next((n for n in names if n.lower() == part.lower()), part)
            at = os.path.join(at, got)
        return at.replace("\\", "/")
    except (OSError, ValueError):
        return p


def prompter(home, s, req, read, base):
    """The start draft for a message, the exact next session: its topic, a brief written as an instruction to that
    session, its parent session and the issue it closes when the message names one. The brief states the task by
    its title, its files, what done looks like, and the model and effort the call adds; it quotes no sentence of the
    message and says nothing of who asked or how the request travelled. A close registered route gives the starting
    shape. Every draft is `fresh`, and its call passes `use_worktree: false`; the start
    tool's own text gives `use_worktree` as "\"fresh\" only (rejected with \"fork\")"."""
    phi = _phi()
    sid = s["sessionId"]
    parent = sid if read["within"] or relay._parent(s) else ""
    route = read["routes"][0] if read["routes"] else None
    title = topic_of(req)
    repo = next(iter(issues.repos_named(req, base)), ("", ""))
    here = relay.repo_of(base) if base else ""
    slug = repo[1] or (issues.github_of(here) if here else "")
    named = issues.named_issue(req, slug) if slug else 0
    full = re.search(r"\b([\w.-]+/[\w.-]+)#(\d+)\b", req)
    if full and not named:                          # the words name the issue whole, in whichever repository
        slug, named = full.group(1), int(full.group(2))
    lines = [f"# {title}", "", f"Task: {title}.", ""]
    if route:
        lines += [f"A route that landed before fits this task: \"{route['topic']}\", {route['issue']}, a "
                  f"{route['context']} session, {(route.get('shape') or {}).get('parent', 'a child')}.",
                  "Its steps were: " + "; ".join((route.get("shape") or {}).get("steps") or ["none kept"]) + ".", ""]
    paths = read["paths"] or ((route or {}).get("slice") or {}).get("paths") or []
    if paths:
        lines += ["Area: " + ", ".join(f"`{spelled(p)}`" for p in paths[:8]) + ".", ""]
    if paths:                                       # what a worker's brief says it covers; one that names none has none
        lines += ["Files: " + ", ".join(f"`{spelled(p)}`" for p in paths[:8]), ""]
    if named:
        lines += [f"This closes {slug}#{named}: every commit says `Closes #{named}`.", ""]
    elif slug:
        lines += [f"It names no issue in {slug}, and p4-phi files none: each finding goes into the report as one "
                  f"`Finding:` line, which the parent session passes up unchanged.", ""]
    if parent:
        lines += checkout_lines(base)
    tests = test_files(base, paths)
    if tests:                                       # the tests the change touches, and no whole suite
        lines += ["Run these test files, and no whole suite: "
                  + ", ".join(f"`{spelled(t) if os.path.isabs(t) else t}`" for t in tests) + ".",
                  "Done looks like: the change made, those test files passing, committed and reported.",
                  "Report when done."]
    else:
        lines += ["Done looks like: the change made, its regression test passing, committed and reported.",
                  "Report when done."]
    if not parent:
        lines += ["", starts.ORCHESTRATOR_BRIEF]
    context = "fresh"
    did = "drf-" + hashlib.sha1(f"{sid}\n{req}\n".encode("utf-8", "replace")).hexdigest()[:10]
    lines += ["", f"phi draft {did} for {parent or 'root'}."]
    background = (f"The session \"{phi.title_of(s)}\" `{sid}` drafted this start; its ledger is "
                  f"{ledger_path(home, sid)}.")
    return {"id": did, "time": now(), "words": req, "title": title, "brief": "\n".join(lines), "parent": parent,
            "context": context, "issue": f"{slug}#{named}" if named else "", "repo": slug, "paths": paths,
            "route": (route or {}).get("id", ""), "background": starts.background_of(home, sid, background),
            "drafter": sid}


def call_of(d):
    """The exact start_session input that starts a draft. Every draft passes `use_worktree: false`, as
    starts.use_worktree says: the session works in this checkout, on the paths of its `Files:` line."""
    # the start tool's schema, of `wake_when_done`: true "also continues you if this session never gets its task
    # some other way, such as a brief that is not sent; default false; not with own_initiative". Every call here
    # runs at once, as `user_asked`, and no card is built here.
    call = {"initiation": "user_asked", "title": d["title"], "context": d["context"], "prompt": d["brief"],
            "wake_when_done": True}
    if d["context"] == "fresh":
        call.update(use_worktree=starts.use_worktree(call["prompt"]), background=d["background"])
    # a fresh draft names its model and effort, judged by the message it came from as well as its brief
    brief = d["brief"]
    return plans.with_level(call, d["title"] + "\n" + str(d.get("words") or "") + "\n" + brief)


# --- the gate, then the dispatch --------------------------------------------------------------------------------------

def pioneer(home, s, d, read, net=True):
    """The gate: a draft checked for the state of the issue it names and that its parent session is the right
    orchestrator. The verdict is start, route, or here when the depth or count cap holds, with what the gate saw;
    the draft is kept. No draft waits on a running writer here: every start passes `use_worktree: false`, and
    the partition of its `Files:` line is held at the start, in phi.py."""
    phi = _phi()
    sid = s["sessionId"]
    gate = []
    slug, _, n = d["issue"].rpartition("#")
    if n:
        state = issue_state(home, slug, int(n), net)
        gate.append(f"{d['issue']} is {state.lower()}" if state else f"gh could not read {d['issue']}")
        if state == "CLOSED":
            gate[-1] += ", so the child takes no issue, p4-phi files none, and its findings go up in its report"
    elif d["repo"]:
        gate.append(f"it names no issue in {d['repo']}, and p4-phi files none: the child's findings go up in its "
                    f"report")
    else:
        gate.append("its files are in no GitHub repository, so it carries no issue")
    cap = phi.caps_text(home, s)
    owner = read.get("owner")
    if owner:
        verdict = "route"
        gate.append(f"its area has a live code owner, \"{owner['title']}\" `{owner['sessionId']}`: {owner['why']}")
    elif cap:
        verdict = "here"
        gate.append(cap)
    else:
        verdict = "start"
    gate.append("its parent is this session, the orchestrator of its topic" if d["parent"] else
                "it is outside this session's topic, so it is a new orchestrator")
    d.update(verdict=verdict, gate=gate, owner=owner)
    relay._write_json(os.path.join(drafts_dir(home, sid), f"{d['id']}.json"), d)
    return d


def verdict_text(home, s, d):
    """What the gate hands the session: the exact call, the exact message, or that no session is started."""
    phi = _phi()
    head = (f"phi (p4-phi): routing read this message of ezexe's as work for a session of its own"
            + (f", and it closely matches the registered route \"{d['route']}\"" if d.get("route") else "")
            + f"; its start draft is \"{d['title']}\", draft {d['id']}; the gate found: "
            + "; ".join(d["gate"]) + ". ")
    tail = (" If the message is this session's own orchestration instead, a question, a decision or a message to pass "
            "to another session, leave the draft and answer it here.")
    if d["verdict"] == "route":
        o = d["owner"]
        return (head + f"Route it: SendMessage with `to` {o['sessionId']}, holding {phi.RESTATE}, then tell ezexe in "
                f"one line that \"{o['title']}\" has it. Start no session for it." + tail)
    if d["verdict"] == "here":
        return head + "No session is started for it." + tail
    if d.get("parent"):
        return (head + f"Start it in the Terminal panel: run `{phi.commands()} draft --start {d['id']}`, which gives "
                "the worker its node, writes its brief and start file there and prints the "
                "`mcp__terminal__open_terminal_tab` call that shows its tab and the `mcp__terminal__run_in_terminal` "
                "call that starts it there; make both, then wait for its report with the "
                "`coworkers --wait --report` line it prints, as one background command." + tail)
    return (head + "Start it now: `mcp__ccd_session__start_session` with "
            + json.dumps(call_of(d), ensure_ascii=False) + ". It is an orchestrator under this session and stays "
            "there. Its brief states the task by its title: before the call, restate the rest of the task under "
            "that line as your own instruction to the new session, what it is to do and why, from its side, quoting "
            "no message and saying nothing of who asked or how the request travelled." + tail)


TASK_CHARS_MOST = 20000            # of a task file draft --start puts into a worker's brief


def task_text(path):
    """The task a starter wrote for its worker, from the file `path`, stripped. ValueError where the file is not
    there, is empty or holds more than TASK_CHARS_MOST characters."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as e:
        raise ValueError(f"no task file at {path}: {e}")
    if not text:
        raise ValueError(f"the task file {path} is empty")
    if len(text) > TASK_CHARS_MOST:
        raise ValueError(f"the task file {path} holds more than {TASK_CHARS_MOST} characters")
    return text


def with_task(brief, task):
    """The drafted brief with the starter's task under `## The task`, before its closing `phi draft` line, and with
    the drafted `Done looks like:` line dropped where the task holds one."""
    lines = brief.split("\n")
    if plans.done_line(task):
        lines = [x for x in lines if not plans.DONE_LINE.match(x)]
    at = next((k for k in range(len(lines) - 1, -1, -1) if lines[k].startswith("phi draft ")), len(lines))
    return "\n".join(lines[:at] + ["## The task", "", task, ""] + lines[at:])


def free_name(home, name):
    """The name a drafted worker starts under: `name` where no node holds it, else the first `<name>-<k>` with none,
    k from 2, where the worker that holds each earlier name is through, its report written or its log ended on a
    final result, so a draft can be started again with a new task. ValueError where one still runs."""
    import coworker
    nodes = relay.nodes(home)
    k = 1
    while True:
        at = name if k == 1 else f"{name}-{k}"
        folder = nodes.get(at)
        if not folder:
            return at
        folder = folder.replace("\\", "/")
        through = (os.path.exists(f"{folder}/report-{at}.md")
                   or coworker.last_result(f"{folder}/{coworker.LOG.format(at)}", final=True))
        if not through:
            raise ValueError(f"a session named `{at}` was started already, from its node {folder}, and still runs: "
                             "wait for its report, or continue it with its resume file")
        k += 1


def start_draft(home, s, did, base, task=""):
    """`draft --start`: the terminal worker of a kept draft. It claims the worker's node in the store nested in this
    session's, writes its brief, settings and start file there, and returns the lines to print: the worker's name and
    its report, the `mcp__terminal__run_in_terminal` call and the wait for its report. A draft with no parent is an
    orchestrator's and raises ValueError. `task` is a file of the task in the starter's own words, which the brief
    carries under `## The task`."""
    import coworker
    phi = _phi()
    d = load_draft(home, s["sessionId"], did)
    if not d:
        raise ValueError(f"no draft {did} in this session")
    if not d.get("parent"):
        raise ValueError("an orchestrator's draft is started with the call the draft printed")
    text = task_text(task) if task else ""
    brief = with_task(d["brief"], text) if text else d["brief"]
    # the brief with the task in it is what routes: a planner's plan-mode lines can come from the task alone
    planner = plans.is_planner(d["title"], text) or plans.child_kind(d["title"] + "\n" + brief) == "plan"
    settings = phi.worker_settings(home, s["sessionId"], d["title"] + "\n" + brief)
    level = plans.own_level("\n".join([str(d.get("words") or ""), d["brief"], text]))
    name = free_name(home, coworker.draft_name(d["title"], d["id"]))
    headless = settings["mode"] == "print"
    plan_file = (os.path.join(home, *p4conf.PLANS.split("/"), f"{name}.md").replace("\\", "/")
                 if planner and headless else "")
    if plan_file:
        done = f"The plan of the brief is written to {plan_file} and read in rounds by its three readers"
    elif planner:
        done = "The plan of the brief is written and put to ezexe"
    else:
        done = plans.done_line(text) or "The task of the brief is done and its checks pass"
    one = coworker.worker(name, brief, done, base, home, s["sessionId"],
                          team=planner and not headless,
                          mode="plan" if planner and not headless else coworker.LAND_MODE,
                          prompt=coworker.planner_task(d["title"], plan_file) if planner else "",
                          profile=settings["profile"], plan_file=plan_file, headless=headless, level=level)
    if one.get("started"):
        raise ValueError(f"a session named `{name}` was started already, from its node {one['started']}")
    coworker.write([one], base, home)
    checkout = base.replace("\\", "/")
    out = [phi.worker_start(home, settings, name, s["sessionId"], "plan" if planner else "work", one.get("log") or "",
                            one["report"]),
           f"worker `{name}`: " + (f"`claude -p`, session {one['session']}, its report {one['report']}, its log "
                                  f"{one['log']}" if headless else
                                  f"session {one['session']}, its report {one['report']}"),
           *([f"model and effort: {', '.join(f'{k} {v}' for k, v in sorted(level.items()))}, from the draft's own "
                "lines"] if level else []),
           phi.tab_lines(name, checkout, one["typed"]),
           *([phi.trust_line()] if settings["mode"] == "interactive" else []),
           f"Then wait for it, as one background command: `{phi.commands()} coworkers --wait --report "
           f"{one['report']}`",
           f"Where it ends with no report, continue it in a Terminal-panel tab with `{one['resume_typed']}`"]
    if plan_file:
        out.append(f"Its plan is {plan_file}: once the report is there, read it and put the plan to ezexe; on "
                   f"approval land it with `{phi.commands()} coworkers \"{plan_file}\" --checkout \"{checkout}\" "
                   "--land`")
    if not task:
        out.append("Its brief holds only the drafted title and paths: write the task in your own words to a file and "
                   "pass `--task <file>` to give the worker its steps.")
    return out


# --- parallel: the readings of an under-determined message, as one workflow run ------------------------------------------
#
# Routing still finds the message under-determined and writes its readings: no docs page offers that. What works the
# readings is Claude Code's own. The opening of workflows.md names drafting a hard plan from several independent
# angles, before committing to one, as a use of a dynamic workflow, and its "Distribute a workflow in a plugin" has a
# script in a plugin's `workflows/` folder run as `/<plugin>:<name>`. So the plugin ships workflows/readings.js and
# this module hands the session one line that names it. What the workflow lacks is stated on the same page,
# "Behavior and limits": "No mid-run user input". A reading that cannot go on without ezexe therefore returns its
# question as data, and the session asks once, after the run.
#
# Seen in a desktop session on Claude Code 2.1.326: the session listed `p4-phi:readings` among its skills and ran it
# by the Workflow tool with that `name`; SubagentStart and SubagentStop fired for each agent of the run with
# `agent_type` `workflow-subagent`, so plans.agent_bind made each a task of the step in progress, and no PreToolUse
# of the Agent tool came before one, so hook.py held no lines for its start. No reading changes a file: the chosen
# reading is started as an ordinary session or worker that writes in the one checkout.

def readings_run(texts):
    """How a session runs the readings workflow on `texts`: the tool, the workflow's name and the `args` it takes.
    The message is the session's to pass whole."""
    args = json.dumps({"words": "<the message, whole>", "readings": list(texts)}, ensure_ascii=False)
    return (f"run the plugin's workflow `/{READINGS}`, the `Workflow` tool with `name` `{READINGS}` and `args` "
            f"{args}; no reading changes a file")


def readings_after():
    """The one line for after a readings run: what each state it returns asks of the session."""
    return (f"After the run: `collapsed` carries its `result` on as the answer, with no question to ezexe; `forked` "
            f"puts its one `question` to ezexe with `AskUserQuestion`, an option for each of its `options` and its "
            f"`default` first, and the chosen reading then goes on as an ordinary child session, by the call "
            f"`{_phi().commands()} draft \"<the chosen reading>\"` prints.")


def readings_text(texts):
    """What the session is handed for a message routing found under-determined: the workflow to run, in place of
    one start_session call for each reading, and the line for after the run."""
    lines = "\n".join(f"- reading {k}: \"{_short(t, 200)}\"" for k, t in enumerate(texts, 1))
    return (f"phi (p4-phi): this message of ezexe's is under-determined, with {len(texts)} distinct readings, and one "
            f"draft would have to guess between them:\n{lines}\nStart no session for it: {readings_run(texts)}. The "
            f"run works each reading in an agent of its own and compares what they came to. {readings_after()}")


# --- at a session's archive: what it left unfinished ------------------------------------------------------------------
#
# A session can be archived, or counted as archived when it finishes, while work it started is still unfinished. So
# when a session under an orchestrator closes, what it started is reconciled once against what finished, from the
# background tasks of its task list, its turns and the store's start requests. A clean session leaves nothing.
# Otherwise the items are kept on its session.json as `unfinishedAtArchive`, shown at the head of its orchestrator's
# ledger, and its parent session is told once, beside its next message, one sentence an item.
#
# Running work is the archive's own to settle. The archive tool's description says "Archiving stops the session's
# process" and "A session that is still working (mid-turn, or with live background work) is not archived and the
# call says so", and desktop.md, "Archive a session", says "Cloud sessions and sessions that are still running don't
# archive themselves." So p4-phi reads no process list of the machine, and names no background task of a session the
# app holds archived. What that refusal lacks is a session p4-phi only counts as archived, which no archive call
# closed: its process still runs, so a background task its last Stop listed is still named.

ARCHIVE_LOOK_S = 24 * 3600.0     # a session closed longer ago than this is stamped as checked, not looked at


def unfinished(home, sid):
    """What a session started and did not finish, one sentence an item, and an empty list for a clean session."""
    phi = _phi()
    s = relay._session(home, sid)
    if not s:
        return []
    items = []
    for t in [] if relay.archived_in_app(s) else plans.in_flight(s):
        items.append(f"background task {t.get('id')}, {t.get('type') or 'a task'} "
                     f"\"{_short(t.get('description') or t.get('command'), 100)}\", was still running at its last "
                     f"turn's end, {s.get('backgroundAt') or 'earlier'}, and may still be running")
    try:
        files, _, commits, still = relay.outcome(home, sid, s)
    except Exception:  # noqa: BLE001
        files, commits, still = [], [], []
    items += [f"plan {x}" for x in still if x.startswith("step ")]
    items += [x for x in still if x.startswith("uncommitted:")]
    repos = {relay.repo_of(f) for f in files} - {""}
    for repo in sorted(repos):
        ahead = issues.git(repo, "log", "--oneline", "@{u}..HEAD")
        if ahead.strip():
            n = len(ahead.strip().splitlines())
            items.append(f"{n} commit{'s' if n != 1 else ''} in {relay.show(repo, s.get('cwd') or '')} not pushed: "
                         + _short("; ".join(ahead.strip().splitlines()[:4]), 200))
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if iss and not iss.get("closed"):
        state = issue_state(home, iss.get("repo"), iss.get("number"))
        if state != "CLOSED":
            items.append(f"the issue it was to close, {iss.get('repo')}#{iss.get('number')}, is "
                         + ("still open" if state == "OPEN" else "not known to be closed"))
    at = time.time()
    for r in starts.state(home).values():
        if r.get("requester") == sid and not r.get("started") and at - float(r.get("at") or 0) <= starts.EXPIRE_S:
            items.append(f"start request {r.get('id')} \"{_short(r.get('title'), 80)}\" that it filed was never "
                         f"started")
    return items


def archive_check(home, sid):
    """Checks once a session counted as archived or archived, and returns its unfinished items, which are kept on its
    session.json and told once to its parent session. Returns an empty list for a clean session and for one checked
    before."""
    path = os.path.join(relay._dir(home, sid), "session.json")
    s = relay._read_json(path)
    if not s or s.get("archiveChecked"):
        return []
    items = unfinished(home, sid)
    s = relay._read_json(path) or s
    s["archiveChecked"] = now()
    if items:
        s["unfinishedAtArchive"] = {"time": now(), "items": items}
    relay._write_json(path, s)
    parent = relay._parent(s)
    if items and parent:
        relay.warn(home, parent, f"unfinished:{sid}", unfinished_text(s, items))
    return items


def unfinished_text(s, items):
    return (f"\"{_phi().title_of(s)}\" `{s.get('sessionId')}` was archived with {len(items)} thing"
            f"{'s' if len(items) != 1 else ''} unfinished. " + " ".join(f"{x[0].upper()}{x[1:]}." for x in items)
            + f" Take each up here or hand it to a successor, then `{_phi().commands()} settle {s.get('sessionId')} "
              f"\"<what took it up>\"` clears its row from the ledger.")


def archive_checks(home, top):
    """The watcher's look: each session of an orchestrator's subtree that closed since the last look is checked
    once. One closed longer ago than ARCHIVE_LOOK_S is stamped as checked without a look."""
    out = []
    for sid, depth, s in subtree(home, top):
        if not depth or not closed(s) or s.get("archiveChecked"):
            continue
        mark = s.get("doneRetired") or s.get("stale")
        when = str((mark.get("time") if isinstance(mark, dict) else "") or (s.get("archived") if isinstance(
            s.get("archived"), str) else "") or "")
        try:
            old = time.time() - time.mktime(time.strptime(when[:16], "%Y-%m-%d %H:%M")) > ARCHIVE_LOOK_S
        except (ValueError, OverflowError):
            old = True
        if old:
            d = relay._read_json(os.path.join(relay._dir(home, sid), "session.json"))
            if d:
                d["archiveChecked"] = "before #47"
                relay._write_json(os.path.join(relay._dir(home, sid), "session.json"), d)
            continue
        if archive_check(home, sid):
            out.append(sid)
    return out


def held_tasks(home, sid):
    """The background tasks still running at a session's last turn's end, by the Stop input, and not ended since by
    a completion notice or a stop, each as its id and its quoted words."""
    return [f"{t.get('id')} \"{_short(t.get('description') or t.get('command'), 80)}\""
            for t in plans.in_flight(relay._session(home, sid))]


def restart_text(home, sid, command):
    """The line for a session about to start a background command that the Stop input at its last turn's end listed
    as still running, and an empty string when none runs or it was told of this copy already; a second try goes
    through. PreToolUse input lists no running task, hooks.md, so the list the Stop hook kept is read."""
    path = os.path.join(relay._dir(home, sid), "session.json")
    s = relay._read_json(path)
    said = " ".join(str(command or "").split())
    first = next((t for t in plans.in_flight(s) if t.get("type") == "shell" and (
        " ".join(str(t.get("command") or "").split()) == said
        or len(str(t.get("command") or "")) >= 1000 and said.startswith(" ".join(str(t["command"]).split())))), None)
    if not first:
        return ""
    told = [x for x in s.get("restartTold") or [] if isinstance(x, str)]
    if not s or first["id"] in told:
        return ""
    s["restartTold"] = (told + [first["id"]])[-50:]
    relay._write_json(path, s)
    return (f"phi (p4-phi): this command was still running in the background as {first['id']} at this session's "
            f"last turn's end, {s.get('backgroundAt') or 'earlier'}, by the app's own list, so a second copy is not "
            f"started. Wait for the completion notification of {first['id']}, or read its output. If it has ended and "
            f"its notification was missed, start it again: p4-phi lets the next start through.")


# --- meta: the orchestrators' ledgers reconciled -----------------------------------------------------------------

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
    """The meta pass over every live orchestrator's ledger. Returns meta-ledger.md's text, its findings, and
    True when the page was rewritten. The findings: duplicate topics, orchestrators in conflict over the same
    issue or the same files, stale topics, and what is left open, which seeds the next generation of topics."""
    phi = _phi()
    at = time.time() if at is None else at
    every = relay._sessions(home)
    tops = sorted((sid for sid, s in every.items() if not relay._parent(s) and not closed(s)
                   and not relay.gone(home, s) and str(s.get("task") or "").strip()),
                  key=lambda k: (str(every[k].get("createdAt") or ""), k))
    led = {t: model(home, t) for t in tops}
    name = {t: f"\"{phi.title_of(every[t])}\" `{t}`" for t in tops}
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
    out = ["# Meta-ledger", "",
           "Written by p4-phi's meta pass, which the orchestrator that receives ezexe's message runs over every "
           "orchestrator's ledger before it reads the message.",
           "Rewritten only when what it finds changes. An orchestrator told of a finding settles it with the other "
           "orchestrator through SendMessage, and puts to ezexe, as one `AskUserQuestion` with an option for each "
           "side, only a conflict the two cannot settle.", "",
           "## Orchestrators", ""]
    out += [f"- {name[t]}: live sessions {len(led[t].get('rows') or [])}, open steps "
            f"{sum(len(r.get('open') or []) for r in led[t].get('rows') or [])}, ledger "
            f"{ledger_path(home, t)}" for t in tops] or ["- None."]
    for head, items, none in (("Duplicate topics", dup, "No two orchestrators carry one topic."),
                              ("Conflicts between orchestrators", clash,
                               "No two orchestrators hold the same issue or the same files."),
                              ("Stale or landed topics", stale, "No orchestrator is stale."),
                              ("Next generation", seeds, "Nothing is left open without a session at work on it.")):
        out += ["", f"## {head}", ""] + ([f"- {x}" for x in items] or [f"- {none}"])
    text = "\n".join(out) + "\n"
    changed = _read(meta_path(home)) != text
    if changed:
        _write(meta_path(home), text)
    return text, {"duplicates": dup, "conflicts": clash, "stale": stale, "seeds": seeds, "keys": findings}, changed


def meta_text(home, s, found):
    """The findings of a meta pass this orchestrator was not told yet, in a few lines. It changes s."""
    told = [x for x in s.get("metaTold") or [] if isinstance(x, str)]
    new = [k for k in found["keys"] if k not in told and s["sessionId"] in k]
    if not new:
        return ""
    s["metaTold"] = (told + new)[-200:]
    mine = [x for x in found["duplicates"] + found["conflicts"] + found["stale"] if s["sessionId"] in x]
    return ("phi (p4-phi): the meta pass over every orchestrator's ledger, written to "
            f"{meta_path(home)}, found for this session: " + " ".join(mine[:4])
            + " Settle what can be settled without ezexe: a duplicate or a conflict with another orchestrator "
              "goes to that session with SendMessage, and a session whose work is over is named to ezexe as a link to "
              "open and archive; only a conflict the two sessions cannot settle goes to ezexe, as one "
              "`AskUserQuestion` with an option for each side.")


# --- the prompt hook ----------------------------------------------------------------------------------------------------

def on_prompt(home, s, req, base):
    """A message of ezexe's in an orchestrator: the meta pass when it is an orchestrator, its ledger made
    current, then routing, the start draft and the gate. Returns the text for the session and the verdict, which is
    empty when no draft was made. It changes `s` and never saves it."""
    if not on(home) or not req or not orchestrator(home, s):
        return "", ""
    parts = []
    if not relay._parent(s):
        _, found, _ = meta_pass(home)
        parts.append(meta_text(home, s, found))
    refresh(home, s["sessionId"])
    if _phi().controls.controlled(s, home) and own_message(home, s, req):
        return "\n\n".join(p for p in parts if p), ""   # the puppeteer's own orchestration: no start draft
    read = prompty(home, s, req, base)
    if not read["work"] or (read["own"] and not read["owner"] and not read["readings"]) \
            or (relay._parent(s) and not read["within"]):       # a child hands another topic up; it drafts none
        return "\n\n".join(p for p in parts if p), ""
    if len(read["readings"]) >= 2 and not read["owner"]:
        parts.append(readings_text(read["readings"]))
        return "\n\n".join(p for p in parts if p), "readings"
    d = pioneer(home, s, prompter(home, s, req, read, base), read)
    parts.append(verdict_text(home, s, d))
    if d["verdict"] == "start":
        parts.append(f"If one draft would have to guess between distinct readings of the message, start none of it: "
                     + readings_run(["<reading one>", "<reading two>"]) + ". " + readings_after())
    return "\n\n".join(p for p in parts if p), d["verdict"]


# --- the commands -----------------------------------------------------------------------------------------------------

COMMANDS = ("ledger", "look", "draft", "pioneer", "routes", "meta", "settle")


def command(a, me):
    """One of this module's commands, run through phi.py: `a` holds its parsed arguments and `me` the session it runs
    for."""
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
    if a.cmd == "look":                            # ahead of ensure_session: a look makes no session's folder
        sys.stdout.write(json.dumps(look(home, me.id, net=a.net, folder_only=a.folder), ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return 0
    if not me.id:
        print("phi: this is not a session, since the environment holds no session id; pass --session", file=sys.stderr)
        return 2
    s = phi.ensure_session(home, me.id, me.rec, "" if a.session else me.cli)
    sid = s["sessionId"]
    base = s.get("cwd") or os.getcwd()
    if a.cmd == "ledger":
        text, changed = refresh(home, sid, net=a.net, force=a.net)
        sys.stdout.write(text)
        print(f"phi: {ledger_path(home, sid)} " + ("rewritten" if changed else "unchanged"), file=sys.stderr)
        return 0
    if a.cmd == "draft" and a.start:
        where = os.path.abspath(a.checkout) if a.checkout else base
        for line in start_draft(home, s, a.start, where, a.task):
            print(line)
        return 0
    if a.cmd == "draft":
        if not a.text:
            raise ValueError("give the words to draft, or `--start <draft id>`")
        read = prompty(home, s, a.text, base)
        if len(read["readings"]) >= 2 and not read["owner"]:
            print(readings_text(read["readings"]))
            return 0
        d = pioneer(home, s, prompter(home, s, a.text, read, base), read)
        print(verdict_text(home, s, d))
        return 0
    if a.cmd == "pioneer":
        d = load_draft(home, sid, a.draft)
        if not d:
            raise ValueError(f"no draft {a.draft} in this session")
        print(verdict_text(home, s, d))            # the gate's verdict for a kept draft, as it was handed
        return 0
    if a.cmd == "settle":
        path = os.path.join(relay._dir(home, a.child), "session.json")
        d = relay._read_json(path)
        if not isinstance(d.get("unfinishedAtArchive"), dict):
            raise ValueError(f"{a.child} left nothing unfinished at its archive")
        if len(" ".join(a.text.split())) < 8:
            raise ValueError("say what took the unfinished work up")
        d["unfinishedAtArchive"].update(settled=" ".join(a.text.split())[:300], settledBy=sid, settledAt=now())
        relay._write_json(path, d)
        print(f"{a.child}: its unfinished work is settled, and its row leaves the ledger")
        return 0
    return 2


def add_parsers(sub, common):
    """This module's commands, added to phi.py's parser."""
    for name in COMMANDS:
        p = sub.add_parser(name)
        common(p)
        if name == "look":
            p.add_argument("--net", action="store_true", help="a slow look: read GitHub and check the routes")
            p.add_argument("--folder", action="store_true", help="only answer where the session's folder is")
        if name == "ledger":
            p.add_argument("--net", action="store_true", help="read the issues' states from GitHub now")
        if name == "draft":
            p.add_argument("text", nargs="?", default="", help="the words to run routing, the start draft and the "
                                                               "gate on")
            p.add_argument("--start", default="", metavar="DRAFT",
                           help="start the terminal worker of a kept draft that has a parent: its node, brief and "
                                "start file, and the call that opens its tab")
            p.add_argument("--checkout", default="", metavar="REPO",
                           help="with --start: the repository the worker runs and commits in; without it, the "
                                "session's folder")
            p.add_argument("--task", default="", metavar="FILE",
                           help="with --start: a file holding the task in your own words, which the worker's brief "
                                "carries under `## The task`")
        if name == "pioneer":
            p.add_argument("draft", help="the draft's id")
        if name == "routes":
            p.add_argument("--register", action="store_true", help="register every landed topic the records back")
            p.add_argument("--why", default="", help="a sessionId: say what its route still lacks")
        if name == "settle":
            p.add_argument("child", help="the session whose unfinished work was taken up")
            p.add_argument("text", help="what took it up")
