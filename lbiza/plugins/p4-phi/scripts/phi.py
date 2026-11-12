#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

The words here are the Claude Code desktop app's, as it uses them: a session; the session that started it
(`spawnedFrom.sessionId` in the app's record); the sessions it started; a top session, which nobody started; a
session's task; a turn; the report a session gives when it finishes a turn; the background a started session is
given; notes. Nothing is renamed.

  session  <home>/phi/sessions/<sessionId>/: session.json (the app's fields for it: sessionId, cliSessionIds,
           title, cwd, spawnedFrom, startChain; and its task), turns.jsonl (a line a finished turn),
           notes.jsonl, reports.jsonl (the reports of the sessions it started), log.jsonl (a line a hook call)
           and session.md, the same as one page. The sessionId is the app's (CLAUDE_CODE_HOST_SESSION_ID, in a
           hook's environment), or the CLI's session id where no app runs it. The reports of top sessions are
           in <home>/phi/reports.jsonl.
  started  a hook's payload does not say which session started this one. The app's record of a session,
  by       claude-code-sessions/<account>/<organization>/<sessionId>.json, says it in `spawnedFrom.sessionId`.
           For a session started "fresh" the app writes that field after the session exists: it was absent at
           SessionStart in 3 of 3 live sessions and at the first message in 2 of 3. Such a session's first
           message ends with the shared notes folder, which the app names after the session that started it
           (3 of 3), so that is read first and the record corrects it when it comes. A forked session's record
           has the field at its SessionStart. A handed-over message that names no folder waits for the record
           (`wait_s`). session.json then holds it; `detach` and `reparent` rewrite it there, whatever the app
           shows.
  home     the store the linked sessions' files live in: the top session's <project>/.claude/p4. A session in a
           worktree or another folder has no store of its own and uses that of the session that started it.
  session- SessionStart: session.json is made if new. A forked session, a session after a compaction or a
  start    clear, and a session no app runs are given their background here. Every session, except on a resume,
           is given the store's rules: each feedback and user memory in <home>/memory without its **Why:**, a
           line each, the long ones cut evenly so the hook stays under the 10,000 characters Claude Code keeps,
           and <home>/phi/rules.md holds them all in full. Sessions had opened those memories one by one before
           their work; the index alone did not say enough.
  user-    UserPromptSubmit: the first request becomes the session's task. The session is given its background
  prompt-  if the start did not give it: the tasks of the sessions above it, their notes, the last turn of each
  submit   other session started by the same session (for a top session, of the top sessions before it), and
           after a compaction its own turns. It is given, in full, the reports of the sessions it started that
           finished a turn since it last looked (the app relays the first 400 characters). And ezexe's
           standing instruction for a message about something else (`new_task`): start a forked session for it
           and stay with the task; once in full, then a line beside each of ezexe's messages.
  stop     Stop: the turn is kept in turns.jsonl whether or not the task is done: the prompt, the files edited,
           the commands that worked, the sessions started, what failed, the report. It is appended to the
           reports of the session that started this one.

Commands for a session: `note "<claim>" --source "<where checked>"`, `done "<what was run and what it showed>"`,
`task "<the new task>"`, `shard <paths or globs>`, `show [sessionId]`, `tree`, `background`, `detach <sessionId>`,
`reparent <sessionId> <under sessionId>`.

The relay (relay.py), modelled on phi_rank/tree.py's node tree: a session's shard is what it alone may change; each
turn keeps its delta, the heads, files and `deprecates:`/`replaces:` notes; a parent's anchor.json merges its
children's latest deltas under a version; every message a session gets, side-session events too, carries what a
newer anchor changed, deprecations first and in full, and a warning before any tool runs when its uncommitted files
or shard meet a deprecated path or another node's shard; a message about another node's shard is routed there.

Settings: <home>/phi/phi.json, every key optional: `background`, `reports`, `turns`, `new_task` (false: off),
`rules`, `background_chars`, `reports_chars`, `wait_s`. P4_PHI=0 turns the plugin off, P4_PHI_NEW_TASK=0 the
standing instruction, P4_PHI_RULES=0 the rules.

Nothing here matches a request to an earlier turn by its words: that was built in p4-recall 0.8.17 to 0.8.20,
measured (the nearest earlier turn's files touched again 0.06 to 0.13 of the time) and removed.
"""

import glob
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import node as nd  # noqa: E402  (a session's place in the tree, which recall reads too)
import p4conf  # noqa: E402  (the store's layout: each plugin's files in .claude/p4/<plugin>/)
import plans  # noqa: E402  (each session's plan with step addresses; the parent's anchor is the plan tree)
import relay  # noqa: E402  (shards, deltas, anchors: linked sessions kept in step while they work)
import starts  # noqa: E402  (start requests: children a session wants but cannot start, carried by the store)

BACKGROUND = True
REPORTS = True
TURNS = True
NEW_TASK = True
RULES = True
HOOK_CHARS = 9500                # Claude Code keeps 10,000 characters of a hook's context and files the rest away
BACKGROUND_CHARS = 3000
REPORTS_CHARS = 6000
REPORT_CHARS = 4000              # of one report, kept
TASK_CHARS = 1200
RULE_TASK = 400                  # of the task, in the standing instruction
LINE_TASK = 160                  # of the task, in the line beside a message
TURN_STEPS = 12
CHAIN_MAX = 8                    # sessions followed upward from a session
OTHERS = 5
OWN = 3
TAIL_BYTES = 256 * 1024          # of a reports file, for a background
TRANSCRIPT_BYTES = 8 * 1024 * 1024
WAIT_S = 2.0                     # how long a handed-over first message waits for the app's record
SCAN_RECORDS = 60                # the newest records searched for a CLI session id, when the host id is missing
SETTINGS = {"background": "BACKGROUND", "reports": "REPORTS", "turns": "TURNS", "new_task": "NEW_TASK",
            "rules": "RULES", "background_chars": "BACKGROUND_CHARS", "reports_chars": "REPORTS_CHARS", "wait_s": "WAIT_S"}
SHELL_TOOLS = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
LOOKING = frozenset("""cat head tail sed grep rg ls find wc awk echo cd for printf date sleep tr file which where test
export mkdir true diff sort cut pwd if while until get-content select-string get-childitem dir findstr start-sleep
set-location write-output write-host get-item test-path""".split()) | {""}

# the kinds of failure that are the machine's, not the script's own, and what to do instead
KINDS = (
    ("quote", re.compile(r"unexpected EOF while looking for matching|unterminated string literal|"
                         r"f-string expression part cannot include a backslash|TerminatorExpectedAtEndOfString|"
                         r"unterminated quoted string"),
     "an inline script broke on its own quotes: write the script to a file and run the file"),
    ("encoding", re.compile(r"Unicode(?:En|De)codeError|codec can't (?:en|de)code"),
     "python used the machine's code page: run it as `python -X utf8` and open files with encoding=\"utf-8\""),
    ("module", re.compile(r"No module named '?([\w.]+)'?"),
     "the default python lacks {name}: use the project's own interpreter"),
    ("program", re.compile(r"(?:: |^)([\w.+-]+): command not found|'([\w.+-]+)' is not recognized|"
                           r"The term '([\w.+-]+)' is not recognized", re.M),
     "{name} is not on PATH: call it by its full path"),
    ("too-long", re.compile(r"ENAMETOOLONG|Argument list too long|command line is too long"),
     "a command was too long to start: put large text in a file, not in the command"),
)
REMINDER = re.compile(r"\A\s*<system-reminder>.*?</system-reminder>\s*", re.S)
TASK_MARK = re.compile(r"(?m)^Task:\s*$")
FORK_HEAD = re.compile(r"\A\s*Task \(from the session that started this one\):\s*")
NOTES_TAIL = re.compile(r"\n\s*Shared notes folder for this group of sessions.*\Z", re.S)
NOTES_ID = re.compile(r"side-session-notes[\\/]+(local_[0-9A-Za-z-]+)")
LEAD = re.compile(r"^(?:cd\s+\S+\s*(?:&&|;)\s*)+")
WS = re.compile(r"\s+")
SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def clean(s):
    return WS.sub(" ", str(s or "").strip())


def cut(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:max(0, n - 4)].rstrip() + " ..."


# --- files ---------------------------------------------------------------------------------------------------

def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def append_line(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_rows(path, tail=None):
    """The rows of a .jsonl file, oldest first; a line that is not a JSON object is skipped. With `tail`, only
    the rows of the file's last `tail` bytes."""
    try:
        with open(path, "rb") as f:
            if tail:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - tail))
                data = f.read()
                if size > tail:
                    data = data.split(b"\n", 1)[-1]
            else:
                data = f.read()
    except OSError:
        return []
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def safe_id(sid):
    return SAFE.sub("_", str(sid or ""))[:80]


def session_dir(home, sid):
    return os.path.join(home, "phi", "sessions", safe_id(sid))


def reports_path(home, sid):
    """The reports of the sessions `sid` started; with no `sid`, of the top sessions."""
    return os.path.join(session_dir(home, sid), "reports.jsonl") if sid else os.path.join(home, "phi", "reports.jsonl")


def page_path(home, sid):
    p = os.path.join(session_dir(home, sid), "session.md") if sid else os.path.join(home, "phi", "sessions.md")
    return p.replace("\\", "/")


def configure(home):
    d = read_json(os.path.join(home, "phi", "phi.json"))
    for key, name in SETTINGS.items():
        if key in d and type(d[key]) is type(globals()[name]):
            globals()[name] = d[key]
    if os.environ.get("P4_PHI_RULES") in ("0", "1"):
        globals()["RULES"] = os.environ["P4_PHI_RULES"] == "1"
    for env in ("P4_PHI_NEW_TASK", "P4_PHI_STEER"):
        if os.environ.get(env) in ("0", "1"):
            globals()["NEW_TASK"] = os.environ[env] == "1"
            break


# --- the app's records: which session started which ----------------------------------------------------------------

def app_roots():
    """The folders that may hold the app's session records (claude-code-sessions), likeliest first."""
    given = os.environ.get("P4_PHI_APP_SESSIONS")
    if given:
        return [given]
    out = []
    d = os.path.dirname(os.environ.get("CLAUDE_CODE_EXECPATH") or "")
    for _ in range(6):
        if not d or d == os.path.dirname(d):
            break
        if os.path.isdir(os.path.join(d, "claude-code-sessions")):
            out.append(os.path.join(d, "claude-code-sessions"))
            break
        d = os.path.dirname(d)
    home = os.path.expanduser("~")
    pats = [os.path.join(home, "Library", "Application Support", "Claude", "claude-code-sessions"),
            os.path.join(home, ".config", "Claude", "claude-code-sessions")]
    if os.environ.get("LOCALAPPDATA"):
        pats.insert(0, os.path.join(os.environ["LOCALAPPDATA"], "Claude-Data", "*", "claude-code-sessions"))
    if os.environ.get("APPDATA"):
        pats.insert(1, os.path.join(os.environ["APPDATA"], "Claude", "claude-code-sessions"))
    for pat in pats:
        for p in glob.glob(pat):
            if p not in out and os.path.isdir(p):
                out.append(p)
    return out


RECORDS = {}


def app_record(sid):
    """The app's record of a session, {} when there is none to read. Read once a process."""
    name = safe_id(sid) + ".json"
    if not sid or not name.startswith("local_"):
        return {}
    if sid not in RECORDS:
        RECORDS[sid] = read_record(name)
    return RECORDS[sid]


FOUND_IN = {}       # sessionId -> the app folder its record was read from, kept in session.json as appRoot


def read_record(name):
    acct, org = os.environ.get("CLAUDE_CODE_ACCOUNT_UUID") or "", os.environ.get("CLAUDE_CODE_ORGANIZATION_UUID") or ""
    for root in app_roots():
        if acct and org:
            d = read_json(os.path.join(root, acct, org, name))
            if d:
                FOUND_IN[name[:-5]] = root
                return d
        for p in glob.glob(os.path.join(root, "*", "*", name)):
            d = read_json(p)
            if d:
                FOUND_IN[name[:-5]] = root
                return d
    return {}


def record_in(root, sid):
    """The app's record of a session in one app folder, {} when it is not there (archived sessions keep theirs, with
    `isArchived`; a deleted session's is gone)."""
    acct, org = os.environ.get("CLAUDE_CODE_ACCOUNT_UUID") or "", os.environ.get("CLAUDE_CODE_ORGANIZATION_UUID") or ""
    if acct and org:
        d = read_json(os.path.join(root, acct, org, safe_id(sid) + ".json"))
        if d:
            return d
    for p in glob.glob(os.path.join(root, "*", "*", safe_id(sid) + ".json")):
        d = read_json(p)
        if d:
            return d
    return {}


relay.RECORD, relay.ROOTED = app_record, record_in     # relay.gone reads the app's records through these


def record_of_cli(cli):
    """The app's record whose CLI session is this one: for a hook whose environment carries no host id. Only the
    newest records are searched."""
    if not cli:
        return {}
    for root in app_roots():
        files = glob.glob(os.path.join(root, "*", "*", "local_*.json"))
        try:
            files.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            pass
        for p in files[:SCAN_RECORDS]:
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            if cli in text:
                d = read_json(p)
                if d.get("cliSessionId") == cli and d.get("sessionId"):
                    return d
    return {}


def spawned_from(d):
    """The sessionId in a record's or a session.json's `spawnedFrom`, '' for a top session."""
    s = d.get("spawnedFrom") if isinstance(d, dict) else None
    return safe_id(s.get("sessionId")) if isinstance(s, dict) and s.get("sessionId") else ""


def store_at(folder):
    if not folder:
        return ""
    p = os.path.join(folder, ".claude", "p4")
    return p if os.path.isdir(p) else ""


def home_of_record(rec, depth=0):
    """The store a session's linked sessions live in: that of the session that started it, and its own folder's
    for a top session."""
    if not rec or depth > CHAIN_MAX:
        return ""
    above = spawned_from(rec)
    if above:
        h = home_of_record(app_record(above), depth + 1)
        if h:
            return h
    return store_at(rec.get("cwd")) or store_at(rec.get("originCwd"))


class Me:
    """The session a hook or a command is running for: its sessionId, its CLI session, the app's record, its home."""

    def __init__(self, payload=None, session="", p4="", hint=""):
        payload = payload or {}
        self.hint = ""
        self.cli = str(payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
        host = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
        # FB1: a CLI id equal to the host id without "local_" is normal: the app gives many started sessions that pair
        # (58 of 396 records, the newest children among them). Treating it as a stray id took their background away.
        self.rec = app_record(session or host) if (session or host) else record_of_cli(self.cli)
        self.id = session or host or str(self.rec.get("sessionId") or "") or self.cli
        project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        self.home = p4 or ""
        self.store = store_at(project) or p4 or ""     # this project's own store: its memory, rules and recall
        self.home_missing = ""
        if not self.home:
            above = spawned_from(self.rec)
            if not above and hint and hint != self.id:
                above = self.hint = hint
            self.home = (home_of_record(app_record(above)) if above else "") or store_at(project) \
                or home_of_record(self.rec)
            self.home, self.home_missing = relay.tree_home(self.home)   # a shared home store, when one is named
        self.store = self.store or self.home
        project_conf(self.store)


# --- sessions --------------------------------------------------------------------------------------------------------

def archived_already(home, sid):
    """True when a child named for archiving is archived already: by hand in the app (`isArchived` in its record,
    or its record gone), or marked so in its session.json."""
    c = load_session(home, sid) if sid else {}
    if not c:
        return False
    return bool(c.get("archived")) or relay.archived_in_app(c)


def load_session(home, sid):
    s = read_json(os.path.join(session_dir(home, sid), "session.json")) if sid else {}
    if isinstance(s.get("backgroundGivenFor"), dict):
        s["backgroundGivenFor"].pop("", None)     # R8: an empty key stored before the fix
    return s


def save_session(home, s):
    """session.json written from `s`, keeping what another hook wrote into it meanwhile: a sibling's Stop marks a
    session stale or queues a warning while this hook holds the copy it read at its start (ST1, ST2)."""
    disk = load_session(home, s.get("sessionId"))
    if "relayPending" in disk:                    # queued and consumed on disk only, by relay.warn and the checks
        s["relayPending"] = disk["relayPending"]
    told = set(s.get("staleTold") or [])
    s["staleChildren"] = [x for x in disk.get("staleChildren") or [] if isinstance(x, dict) and x.get("id") not in told]
    if not s["staleChildren"]:
        s.pop("staleChildren", None)
    st = disk.get("stale")
    if isinstance(st, dict) and "stale" not in s and str(st.get("time") or "") > str(s.get("unstaled") or ""):
        s["stale"] = st                           # marked stale by a sibling's Stop while this hook ran
    elif isinstance(st, dict) and isinstance(s.get("stale"), dict) and st.get("told"):
        s["stale"]["told"] = True
    for k in ("relayWarned", "marksGiven", "upTold", "splitAdvised"):
        if isinstance(disk.get(k), list):
            s[k] = list(s.get(k) or []) + [x for x in disk[k] if x not in (s.get(k) or [])]
    for k in ("othersGiven", "plansSeen"):
        if isinstance(disk.get(k), dict):
            s[k] = {**disk[k], **(s.get(k) or {})}
    for k in ("rootStep", "shard", "disposable", "doneRetired", "archived", "appRoot", "nudged", "landingGiven"):
        if k in disk and k not in s:
            s[k] = disk[k]
    if int(disk.get("anchorSeen") or 0) > int(s.get("anchorSeen") or 0):
        s["anchorSeen"] = disk["anchorSeen"]
    moved = disk.get("spawnedFrom") if isinstance(disk.get("spawnedFrom"), dict) else {}
    mine = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
    if moved.get("source") in ("detached", "reparented", "requested") \
            and str(moved.get("time") or "") > str(mine.get("time") or ""):
        s["spawnedFrom"] = moved                  # a detach or reparent made while this hook held an older copy
    write_atomic(os.path.join(session_dir(home, s["sessionId"]), "session.json"),
                 json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def ensure_session(home, sid, rec=None, cli="", depth=0, hint=""):
    """session.json, made if new, with those of the sessions above it made too (a session this plugin never ran
    in gets its file from the app's record). `spawnedFrom` there is what the tree is read from: the record sets
    it for a new session, for one that looked like a top session before its record said otherwise, and for one
    read from the notes folder. One that was detached or reparented is left as set."""
    sid = safe_id(sid)
    s = load_session(home, sid)
    changed = False
    if not s.get("sessionId"):
        s = {"sessionId": sid, "title": "", "createdAt": now(), "cliSessionIds": [], "task": "", "reportsSeen": 0}
        changed = True
    held = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
    source = held.get("source", "")
    if rec is None and (not held or source == "notes folder"):
        rec = app_record(sid)
    if source not in ("detached", "reparented", "requested") and (not held or source == "notes folder"):
        above, src = spawned_from(rec or {}), "record"
        if not above and source == "notes folder":
            above, src = spawned_from(s), "notes folder"
        if not above and hint:
            above, src = safe_id(hint), "notes folder"
        if above == sid:
            above = ""
        new = {"sessionId": above, "source": src} if above else None
        if new != (held or None):
            if new:
                s["spawnedFrom"] = new
                chain = (rec or {}).get("startChain")
                if isinstance(chain, dict):
                    s["startChain"] = {k: chain.get(k) for k in ("firstSessionId", "depth")}
            else:
                s.pop("spawnedFrom", None)
            changed = True
    if rec:
        root = FOUND_IN.get(sid, "")
        if root and root != s.get("appRoot"):        # where an archive or a deletion is looked for later (relay.gone)
            s["appRoot"] = root
            changed = True
        title = clean(rec.get("title"))[:120]
        if title and title != s.get("title"):      # the app titles a session after it has started
            s["title"] = title
            changed = True
        if rec.get("cwd") and rec.get("cwd") != s.get("cwd"):
            s["cwd"] = rec["cwd"]
            changed = True
    if cli and cli not in s.setdefault("cliSessionIds", []):
        s["cliSessionIds"].append(cli)
        changed = True
    if changed:
        save_session(home, s)
    above = spawned_from(s)
    if above and depth < CHAIN_MAX and not load_session(home, above).get("sessionId"):
        ensure_session(home, above, depth=depth + 1)
    return s


def title_of(s):
    return s.get("title") or cut(clean(s.get("task")), 60) or str(s.get("sessionId") or "")[:14]


def chain_of(home, sid):
    """The sessionIds above a session, nearest first: the session that started it, the one that started that."""
    out, cur = [], spawned_from(load_session(home, sid))
    while cur and cur not in out and len(out) < CHAIN_MAX:
        out.append(cur)
        cur = spawned_from(load_session(home, cur))
    return out


def load_turns(home, sid):
    """A session's turns, oldest first, each turn once (as it last finished)."""
    by = {}
    for r in read_rows(os.path.join(session_dir(home, sid), "turns.jsonl")):
        if r.get("id"):
            by[r["id"]] = r
    return list(by.values())


def load_notes(home, sid):
    return read_rows(os.path.join(session_dir(home, sid), "notes.jsonl"))


def load_reports(home, sid, tail=None):
    return read_rows(reports_path(home, sid), tail)


def latest_reports(rows, skip=""):
    """From the rows of a reports file, each session's latest turn, newest first. A session that left is dropped."""
    by = {}
    for r in rows:
        sid = r.get("sessionId") or r.get("left")
        if not sid:
            continue
        by.pop(sid, None)
        if r.get("sessionId") and isinstance(r.get("turn"), dict):
            by[sid] = r
    return [r for c, r in reversed(list(by.items())) if c != skip]


# --- requests and turns ----------------------------------------------------------------------------------------------

def request_of(prompt):
    """The request inside a message. A session started by another session gets its task under leading
    <system-reminder> blocks and a `Background ... Task:` wrapper, and a forked one under the line `Task (from the
    session that started this one):`; this takes those off. '' when nothing is left or what is left is the
    harness speaking."""
    text = prompt if isinstance(prompt, str) else ""
    while REMINDER.match(text):
        text = REMINDER.sub("", text, count=1)
    m = TASK_MARK.search(text)
    if m and text.lstrip().startswith("Background"):
        text = text[m.end():]
    text = FORK_HEAD.sub("", text, count=1)
    text = NOTES_TAIL.sub("", text).strip()
    return "" if text.startswith("<") else text


def handed_over(prompt):
    """Does a message look like a task another session handed over: the wrapper, the linked-sessions reminder, or
    the shared notes folder. Such a session was started by one, whether or not the app has recorded it yet."""
    text = prompt if isinstance(prompt, str) else ""
    body = text
    while REMINDER.match(body):
        body = REMINDER.sub("", body, count=1)
    return bool(body.lstrip().startswith("Background") and TASK_MARK.search(body) or FORK_HEAD.match(body)
                or NOTES_ID.search(text) or "Linked sessions now" in text[:4000])


def result_text(block):
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_transcript(path):
    """A transcript's lines as objects; of a very long one, its last TRANSCRIPT_BYTES."""
    return read_rows(path, TRANSCRIPT_BYTES) if path and os.path.exists(path) else []


def last_turn(path):
    """The transcript's last turn whoever asked for it: the last message that carries a request, and every tool
    call after it. A message of the harness (a session's report relayed, a notification) opens no turn."""
    cur, calls = None, {}
    for d in read_transcript(path):
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        c = (d.get("message") or {}).get("content")
        if d.get("type") == "user":
            if isinstance(c, list):
                got = False
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        got = True
                        call = calls.get(b.get("tool_use_id"))
                        if call:
                            call["result"] = result_text(b)[-4000:]
                            call["failed"] = bool(b.get("is_error"))
                if got:
                    continue
                c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            req = request_of(c)
            if req:
                cur = {"prompt": req, "uuid": str(d.get("uuid") or ""), "calls": [], "texts": [],
                       "time": str(d.get("timestamp") or "")[:16].replace("T", " ")}
        elif d.get("type") == "assistant" and cur is not None:
            if isinstance(c, str) and c.strip():
                cur["texts"].append(c.strip())
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text") or "").strip():
                    cur["texts"].append(str(b["text"]).strip())
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    call = {"name": str(b.get("name") or ""), "result": "", "failed": False,
                            "input": b.get("input") if isinstance(b.get("input"), dict) else {}}
                    cur["calls"].append(call)
                    calls[b.get("id")] = call
    return cur


def path_key(p):
    parts = [x for x in str(p or "").replace("\\", "/").split("/") if x]
    return "/".join(parts[-2:])


def run_shape(cmd):
    """A command as a turn's step: past its `cd x &&`, up to its first pipe."""
    c = LEAD.sub("", clean(cmd))
    c = re.split(r"\s*(?:2>&1\s*)?\|\s*", c)[0]
    return re.sub(r"\s*2>&1\s*$", "", c).strip()[:200]


def program(cmd):
    c = LEAD.sub("", clean(cmd))
    word = c.split(" ", 1)[0] if c else ""
    return re.sub(r"\.exe$", "", word.replace("\\", "/").rsplit("/", 1)[-1].lower())


def failure_note(cmd, result):
    for _, rx, advice in KINDS:
        m = rx.search(result or "")
        if m:
            name = next((g for g in m.groups() if g), "") if m.groups() else ""
            return advice.format(name=name or "something")
    last = next((x.strip() for x in reversed((result or "").splitlines()) if x.strip()), "")
    return f"`{cut(run_shape(cmd), 80)}` failed: {cut(last, 160)}"


def turn_of(turn, report):
    """A transcript's turn as the row kept for it: the prompt, the files edited and the commands that worked and
    the sessions started, in order, what failed, and the report."""
    steps, failed = [], []

    def add(to, s):
        if s and s not in to:
            to.append(s)
    for c in turn.get("calls") or []:
        name, inp = c["name"], c["input"]
        if name in EDIT_TOOLS:
            add(steps, "edited " + path_key(inp.get("file_path") or inp.get("notebook_path")))
        elif name in SHELL_TOOLS:
            cmd = str(inp.get("command") or "")
            if c.get("failed"):
                add(failed, failure_note(cmd, c.get("result")))
            elif program(cmd) not in LOOKING and "<<" not in cmd and len(cmd) <= 400:
                add(steps, f"ran `{run_shape(cmd)}`")
        elif name.endswith("start_session"):
            add(steps, f"started the session \"{cut(clean(inp.get('title') or inp.get('name')), 80)}\"")
        elif name in ("Agent", "Task"):
            add(steps, f"ran a subagent: {cut(clean(inp.get('description')), 80)}")
    prompt = cut(turn.get("prompt") or "", TASK_CHARS)
    uuid = turn.get("uuid") or ""
    return {"id": uuid or "turn-" + hashlib.sha1(prompt.encode("utf-8", "replace")).hexdigest()[:12],
            "prompt": prompt, "steps": steps[:TURN_STEPS], "failed": failed[:4],
            "report": (report or "").strip()[:REPORT_CHARS], "done": ""}


def said_of(turn, report):
    """Every message the turn wrote, joined and cut from the front to REPORT_CHARS, for when its findings came in a
    message before its last. Check 2's kept report was only "Check 2 is done and reported", and its findings were in
    the message before. '' when the last message is all the turn wrote."""
    texts = [t for t in turn.get("texts") or [] if isinstance(t, str) and t.strip()]
    if not texts or (len(texts) == 1 and texts[0].strip() == (report or "").strip()):
        return ""
    whole = "\n\n".join(texts)
    if whole.strip() == (report or "").strip():
        return ""
    return whole[-REPORT_CHARS:]


# --- what a session is given -----------------------------------------------------------------------------------------

def turn_lines(title, t, report=300, prompt=200):
    how = "done: " + cut(clean(t["done"]), 160) if t.get("done") else "not shown done"
    out = [f"- \"{title}\" ({how}; {t.get('time', '')}): {cut(clean(t.get('prompt')), prompt)}"]
    if t.get("steps"):
        out.append("  steps: " + cut("; ".join(t["steps"]), 400))
    if t.get("sessions"):
        out.append("  sessions it started: " + cut("; ".join(t["sessions"]), 300))
    if t.get("failed"):
        out.append("  failed: " + cut("; ".join(t["failed"]), 300))
    if t.get("report"):
        text = t["report"] if report >= REPORT_CHARS else clean(t["report"])
        out.append("  reported: " + cut(text, report))
    return out


def commands():
    script = os.path.abspath(__file__).replace("\\", "/")
    return f'python -I -X utf8 "{script}"'


def background_text(home, s, own=False, slim=False):
    """The background a session is given: the tasks of the sessions above it, their notes, the last turn of each
    other session the same session started (for a top session, of the top sessions before it), and with `own`
    its own turns. '' when none of that exists."""
    sid, above = s["sessionId"], spawned_from(s)
    chain = [load_session(home, x) for x in chain_of(home, sid)]
    body = []
    tasks = [f"- \"{title_of(n)}\": {cut(clean(n.get('task')), 500 if k == 0 else 200)}"
             for k, n in enumerate(chain) if n.get("task")]
    if tasks:
        body += ["Tasks of the sessions above this one, nearest first (this session's task is part of the first):"]
        body += tasks
    own_task = clean(s.get("task"))
    notes = []
    for n in chain:
        for r in load_notes(home, n["sessionId"]):
            kind = f"{r['kind']}; " if r.get("kind") else ""
            room = relay.FINDINGS_CHARS + 2000 if clean(r.get("claim")).startswith("replaces:") else 300
            notes.append(f"- {cut(clean(r.get('claim')), room)} ({kind}source: {cut(clean(r.get('source')), 120)})")
    notes = [] if slim else nd.by_overlap(notes, own_task)   # nearest the task first; a fresh child gets its slice
    if notes:
        body += ["Notes of the sessions above (already checked; do not work these out again):"] + notes[:12]
    others = [r for r in latest_reports(load_reports(home, above, TAIL_BYTES), skip=sid)[:OTHERS * 3]
              if spawned_from(load_session(home, r["sessionId"])) == above
              and not relay.gone(home, load_session(home, r["sessionId"]))][:OTHERS]
    others = [] if slim else nd.by_overlap(others, own_task,
                                           key=lambda r: f"{r.get('title', '')} {r.get('turn', {}).get('prompt', '')}")
    if others:
        who = f"the other sessions \"{title_of(chain[0])}\" started" if chain else \
            "the top sessions in this project before this one"
        body += [f"The last turn of {who}:"]
        for r in others:
            body += turn_lines(r.get("title") or r["sessionId"][:14], r["turn"])
    if own:
        mine = load_turns(home, sid)[-OWN:]
        if mine:
            body += ["This session's own turns so far:"]
            for t in reversed(mine):
                body += turn_lines(title_of(s), t)
    if not body:
        return ""
    if chain:
        head = (f"phi (p4-phi): background for this session, \"{title_of(s)}\", from the session that started it, "
                f"\"{title_of(chain[0])}\", and the sessions linked to it. Use what is here where it fits; do not "
                f"work it out again.")
    else:
        head = ("phi (p4-phi): background for this session from the sessions in this project before it. Use what "
                "is here where it fits; do not work it out again.")
    tail = (f"The page this comes from: {page_path(home, above)}. Keep a finding the next session would have to "
            f"work out again: `{commands()} note \"<claim>\" --source \"<where it was checked>\"`. When something "
            f"shows the task done: `{commands()} done \"<what was run and what it showed>\"`. Each turn's report "
            f"is kept either way" + (" and reaches the session that started this one in full." if chain else "."))
    room = BACKGROUND_CHARS - len(head) - len(tail) - 2
    text = "\n".join(body)
    if len(text) > room:
        text = text[:max(0, room - 4)].rsplit("\n", 1)[0] + "\n..."
    return "\n".join((head, text, tail))[:BACKGROUND_CHARS]


def reports_text(home, s):
    """The reports of the sessions this session started that finished a turn since it last looked, in full, and
    how many rows that covers."""
    rows = load_reports(home, s["sessionId"])
    seen = s.get("reportsSeen") if isinstance(s.get("reportsSeen"), int) else 0
    new = latest_reports(rows[seen:])
    if not new:
        return "", len(rows)
    out = ["phi (p4-phi): reports of the sessions this session started that finished a turn since it last looked. "
           "The app relays the first 400 characters of a report; these are in full."]
    each = max(600, (REPORTS_CHARS - len(out[0])) // len(new))
    for r in reversed(new):
        lines = turn_lines(r.get("title") or r["sessionId"][:14], r["turn"], report=REPORT_CHARS, prompt=300)
        out += [cut("\n".join(lines), each), f"  its page: {page_path(home, r['sessionId'])}"]
    return "\n".join(out), len(rows)


MAX_DEPTH = 3                 # a session this deep in the tree starts no session of its own
MAX_CHILDREN = 8              # nor one that has this many live children already
BUILT_IN = ("built-in, act-don't-wait: a next step the chain can settle (the task, the parent's plan and notes, "
            "siblings' work, the project's rules) is decided and done, with one line saying what was chosen and why. "
            "Only a matter of ezexe's authority goes to ezexe: permissions or security settings, credentials, "
            "spending, and actions that cannot be undone or publish outward. A child asks the session that started it "
            "with SendMessage, and never ends its turn waiting on a question the chain can settle. Where the project's "
            "rules ask for ezexe's go before a kind of step, such as a plan's edits, that go is ezexe's to give: "
            "wait for it on those steps, and act on the rest.")
ACT_DONT_WAIT = True          # p4.json phi.act_dont_wait: false leaves the built-in rule out in a project (#23)
TOP_ORCHESTRATES = True       # p4.json phi.top_orchestrates: false keeps a top session's work in it (#24)


def project_conf(store):
    """The project's own phi keys in p4.json, read where the session runs, not from a shared home store."""
    global ACT_DONT_WAIT, TOP_ORCHESTRATES
    try:
        d = p4conf.section(store, "phi", write=False) if store else {}
    except Exception:  # noqa: BLE001
        d = {}
    ACT_DONT_WAIT = d.get("act_dont_wait") is not False
    TOP_ORCHESTRATES = d.get("top_orchestrates") is not False


TOP_RULE = ("This is the top session of its tree, so it keeps itself free for orchestration: planning, relaying "
            "between sessions, decisions with ezexe, and landing the work, meaning merge and push. Its work "
            "steps go to fresh child sessions, a run of serial ones to one child, each brief saying \"archive when "
            "done\"; the steps that test-and-commit, merge, push or release stay here.")


NEW_TOP = re.compile(r"\b(?:this|it) (?:session )?is a new top session\b", re.I)
NEW_TOP_BRIEF = "This session is a new top session, orchestrating its own topic."


def new_top_first_act():
    """What a new top session does first: leave the starter in the app, then in phi."""
    return (f"Its first act: `mcp__ccd_session_mgmt__detach_session` with `\"self\"`, so the app stops nesting it and "
            f"its reports stop going to the starter, then `{commands()} detach`.")


def new_top_route(owner_turn=True):
    """How a top session starts a new top session for a topic outside its task."""
    how = ("Start it with `mcp__ccd_session__start_session`, `initiation` `user_asked`" if owner_turn else
           f"This turn was started by another session, so the app refuses `user_asked`: write it as a start request, "
           f"{request_cmd()}, which the next turn ezexe begins in any session of this store starts, without "
           f"asking ezexe anything")
    return (f"{how}, `context` `fresh`, `use_worktree: false`; its brief: the topic, ezexe's words quoted, and "
            f"the lines \"{NEW_TOP_BRIEF} {new_top_first_act()}\" Both moves are needed: the app's detach, else it "
            f"stays nested under this session and reports here, and phi's, which phi also makes at its first hook "
            f"on that line. If it has not left this session's family by its first report, call "
            f"`mcp__ccd_session_mgmt__detach_session` with its id yourself. In the root every top session relays to "
            f"the others as siblings.")


def request_cmd():
    """The command that keeps a start request, as the lines that advise it give it."""
    return f'`{commands()} request "<title>" --brief "<the whole brief>"`'


def depth_of(home, s):
    """How many sessions lie above this one: 0 for a top session."""
    n, seen, cur = 0, set(), s
    while spawned_from(cur) and spawned_from(cur) not in seen and n < 20:
        seen.add(spawned_from(cur))
        cur = load_session(home, spawned_from(cur)) or {}
        n += 1
    return n


def caps_text(home, s):
    """'' while this session may start sessions; else the one line saying where the work goes instead."""
    depth = depth_of(home, s)
    if depth >= MAX_DEPTH:
        return (f"This session is {depth} deep in the session tree, the most phi allows: start no session; do the "
                f"work here, or send it to the session that started you with SendMessage.")
    kids = len(plans._children(home, s["sessionId"]))
    if kids >= MAX_CHILDREN:
        return (f"This session has {kids} live sessions of its own, the most phi allows: start no session; send the "
                f"work to the one whose task it fits with SendMessage, or archive a finished one first.")
    return ""


def split_text(home, s, prompt):
    """A turn another session's message started: the app refuses `user_asked` there, so a split is a card ezexe
    starts. '' for ezexe's own turns, the app's events and a session with no task."""
    if not clean(s.get("task")) or not re.search(r"<cross-session-message\b", str(prompt or "")):
        return ""
    cap = caps_text(home, s)
    RAN["split"] = "cap" if cap else "card"
    if cap:
        return "phi (p4-phi): this turn was started by another session, not ezexe. " + cap
    if not spawned_from(s):
        return ("phi (p4-phi): this turn was started by another session, not ezexe, so the app refuses "
                "`mcp__ccd_session__start_session` with `user_asked`. A topic in it outside this top session's task "
                "gets a new top session of its own. " + new_top_route(False) + " Do the rest here; a question the "
                "chain can settle is answered, not waited on.")
    return ("phi (p4-phi): this turn was started by another session, not ezexe, so the app refuses "
            "`mcp__ccd_session__start_session` with `user_asked`. Work in it that is a task of its own, outside "
            f"this session's task, is written as a start request, {request_cmd()}: the next turn ezexe begins, "
            "in any session of this store, starts it as this session's child. Do not ask ezexe to type anything "
            "or click a card. Do the rest here; a question the chain can settle is answered, not waited on.")


def new_task_text(home, s, me, user=True, again=False):
    """ezexe's standing instruction for a message about something else: once in full for a CLI session that
    has a task (and again after a compaction), then a line with the task beside each of ezexe's messages.
    '' with no task, and beside the harness's messages."""
    task = clean(s.get("task"))
    if not NEW_TASK or not task:
        return ""
    told = s.setdefault("newTaskToldAt", {})
    if not isinstance(told, dict):
        told = s["newTaskToldAt"] = {}
    if again or not told.get(me.cli):
        told[me.cli] = now()
        listed = relay.shards_line(home, s["sessionId"])
        shards = f" (shards now: {listed})" if listed else ""
        RAN["new_task"] = "instruction"
        parent = spawned_from(s)
        if parent:
            elsewhere = (f"do not turn this session to it, and start no session for it: hand it up to the session "
                         f"that started this one with SendMessage (`to`: {parent}), ezexe's words quoted, tell "
                         f"ezexe in one line that it went up, and stay with the task. Only a top session starts "
                         f"a session for a new topic. A message about a path inside another session's shard is that "
                         f"session's: send it there with SendMessage instead{shards}. This is ezexe's standing "
                         f"instruction for this project. A quick thing (a ")
        else:
            elsewhere = (f"do not turn this session to it. A new topic gets a new top session of its own, a sibling "
                         f"of this one, so this session stays orchestrating its topic. {new_top_route(True)} Tell "
                         f"ezexe in one line which session has it, and stay with the task. A message about a path "
                         f"inside another session's shard is that session's: send it there with SendMessage instead, "
                         f"and start a new session only for what no shard covers{shards}. This is ezexe's standing "
                         f"instruction for this project, so the session is started, not offered as a card. Its "
                         f"report comes back here in full. A quick thing (a ")
        return (f"phi (p4-phi): this session's task: \"{cut(task, RULE_TASK)}\" When a message from ezexe is "
                f"about something else, " + elsewhere +
                f"question, a few tool calls) stays here. When ezexe says the task itself has changed: "
                f"`{commands()} task \"<the new task>\"`. This session's page: {page_path(home, s['sessionId'])}."
                + (" " + TOP_RULE if not spawned_from(s) and TOP_ORCHESTRATES else "")
                + (" " + caps_text(home, s) if caps_text(home, s) else ""))
    if not user:
        return ""
    RAN["new_task"] = "line"
    parent = spawned_from(s)
    if parent:
        return (f"phi (p4-phi): this session's task is \"{cut(task, LINE_TASK)}\" If this message is about something "
                f"else, hand it up to {parent} with SendMessage, ezexe's words quoted, and stay with the task; "
                f"otherwise carry on.")
    return (f"phi (p4-phi): this session's task is \"{cut(task, LINE_TASK)}\" If this message is about something "
            f"else, start a new top session for it (`context` `fresh`, its brief ending \"{NEW_TOP_BRIEF}\") and stay "
            f"with the task; otherwise carry on.")


def render_page(home, sid):
    """session.md: a session as one page (its task, notes, turns and the sessions it started), rewritten from its
    files. With no `sid`, sessions.md: the top sessions of the project."""
    out = []
    if sid:
        s = load_session(home, sid)
        if not s.get("sessionId"):
            return
        above = spawned_from(s)
        out = [f"# {title_of(s)}", "",
               f"Session `{sid}`, started by `{above}`." if above else f"Session `{sid}`, a top session.", ""]
        if s.get("task"):
            out += ["## Task", "", s["task"].strip(), ""]
        notes = load_notes(home, sid)
        if notes:
            out += ["## Notes", ""]
            out += [f"- {clean(r.get('claim'))} (source: {clean(r.get('source'))}; {r.get('time', '')})" for r in notes]
            out.append("")
        turns = load_turns(home, sid)
        if turns:
            out += ["## Turns", ""]
            for t in turns:
                out += turn_lines(title_of(s), t, report=1200, prompt=400)
            out.append("")
    else:
        out = ["# Top sessions of this project", ""]
    rows = latest_reports(load_reports(home, sid, TAIL_BYTES))[:40]
    if rows:
        if sid:
            out += ["## Sessions this session started, newest first", ""]
        for r in rows:
            out += turn_lines(r.get("title") or r["sessionId"][:14], r["turn"], report=600, prompt=300)
            out.append(f"  session: `{r['sessionId']}`")
        out.append("")
    write_atomic(page_path(home, sid), "\n".join(out))


# --- the store's rules -----------------------------------------------------------------------------------------------

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
INDEX_LINK = re.compile(r"\]\(([^)]+\.md)\)")
WHY = re.compile(r"\A\s*\*\*Why")


def memory_rules(home):
    """The store's rules: (name, body) for each memory of type feedback or user in <home>/temportal/memory, in the order
    MEMORY.md lists them, then the ones it does not list."""
    mem = p4conf.sub(home, "memory")
    try:
        files = sorted(f for f in os.listdir(mem) if f.endswith(".md") and f != "MEMORY.md")
    except OSError:
        return []
    try:
        with open(os.path.join(mem, "MEMORY.md"), encoding="utf-8") as f:
            listed = [os.path.basename(m) for m in INDEX_LINK.findall(f.read())]
    except (OSError, UnicodeDecodeError):
        listed = []
    out = []
    for f in [f for f in dict.fromkeys(listed) if f in files] + [f for f in files if f not in listed]:
        try:
            with open(os.path.join(mem, f), encoding="utf-8") as h:
                m = FRONT.match(h.read().replace("\r\n", "\n"))
        except (OSError, UnicodeDecodeError):
            continue
        kind = re.search(r"(?m)^\s*type:\s*(\w+)", m.group(1)) if m else None
        if not kind or kind.group(1) not in ("feedback", "user"):
            continue
        name = re.search(r"(?m)^name:\s*(.+)$", m.group(1))
        out.append((name.group(1).strip() if name else f[:-3], m.group(2).strip()))
    return out


def rule_of(body):
    """A rule on one line: its body without the **Why:** paragraph."""
    return clean(" ".join(p for p in re.split(r"\n\s*\n|\n(?=\*\*)", body) if p.strip() and not WHY.match(p)))


def fair_cut(texts, room):
    """Each text cut so that all fit in `room`: the short ones whole, the long ones sharing what is left evenly."""
    n, left, out = len(texts), room, {}
    for k, t in sorted(enumerate(texts), key=lambda kt: len(kt[1])):
        share = left // max(1, n)
        out[k] = t if len(t) <= share else cut(t, max(40, share))
        left -= len(out[k])
        n -= 1
    return [out[k] for k in range(len(texts))]


def rules_page(home, rules):
    """<home>/phi/rules.md: every rule in full on one page, written only when a memory changed."""
    path = os.path.join(home, "phi", "rules.md")
    mem = p4conf.sub(home, "memory").replace("\\", "/")
    text = "\n".join([f"# The store's rules, in full", "",
                      f"Written by p4-phi from the feedback and user memories in {mem}. Edit those files, not this "
                      f"page.", ""] + [f"## {name}\n\n{body}\n" for name, body in rules])
    try:
        with open(path, encoding="utf-8") as f:
            same = f.read() == text
    except (OSError, UnicodeDecodeError):
        same = False
    if not same:
        write_atomic(path, text)
    return path.replace("\\", "/")


def builtin_text():
    """The rule p4-phi carries itself, so it holds in every project, with memories or none; '' where the project's
    p4.json turns it off."""
    if not ACT_DONT_WAIT:
        return ""
    return "phi (p4-phi): a rule built into p4-phi, for every session:\n- " + BUILT_IN


def rules_text(home, room, fork=False):
    """The store's rules for a session's start, a line each, in at most `room` characters, led by the built-in
    rule. The built-in rule alone in a project with no rules, and for a fork, whose inherited conversation already
    holds the store's rules."""
    if not RULES:
        return ""
    rules = memory_rules(home) if home and not fork else []
    if not rules or room < 600:
        RAN["rules"] = 0
        return builtin_text() if room >= len(builtin_text()) else ""     # '' when the project turned it off
    page = rules_page(home, rules)
    mem = p4conf.sub(home, "memory").replace("\\", "/")
    head = (f"phi (p4-phi): this project's standing rules, from the feedback and user memories in {mem}. They are "
            f"in your context now, as are CLAUDE.md and the memory index, so do not open the memory files or "
            f"CLAUDE.md to learn the rules before the work. A rule cut short with ... is whole, with its Why, on "
            f"one page: {page}. Read that page, not the files, when a rule's reason matters. A session you start "
            f"with `mcp__ccd_session__start_session` is given these same rules, CLAUDE.md and the memory index at "
            f"its start, and your task and notes beside its first message, so its brief does not tell it to read "
            f"CLAUDE.md, MEMORY.md or any memory file: the brief names only what this task needs, such as a skill, "
            f"a plan or source files.")
    rules = ([tuple(BUILT_IN.split(": ", 1))] if ACT_DONT_WAIT else []) + list(rules)
    names = [f"- {name}: " for name, _ in rules]
    room -= len(head) + sum(len(x) + 1 for x in names) + 2
    RAN["rules"] = len(rules)
    return "\n".join([head] + [a + b for a, b in zip(names, fair_cut([rule_of(b) for _, b in rules], room))])


# --- the hooks -------------------------------------------------------------------------------------------------------

def given(s, me, home, own=False):
    """The background, when this CLI session has not been given it under the session that started it; marks it
    given."""
    if not BACKGROUND or not me.cli:
        return ""                                  # R8: a call with no session id is no new CLI session
    told = s.setdefault("backgroundGivenFor", {})
    if not isinstance(told, dict):
        told = s["backgroundGivenFor"] = {}
    told.pop("", None)                             # an empty key stored before R8
    above = spawned_from(s)
    if not own and told.get(me.cli) == above:
        return ""
    fresh = bool(above) and not s.get("forked") and not own
    if fresh and not clean(s.get("task")):
        return ""                                  # its brief comes with its first message: built then (F1)
    told[me.cli] = above
    # a fresh child starts with exactly what the parent has for it (F2): the tasks above it, its root step and the
    # parent's plan around it, and the parent's anchor cut to its paths, never the parent's whole background
    cut_to = relay.child_paths(home, s) if fresh else []
    text = background_text(home, s, own=own, slim=bool(cut_to))   # nothing to cut by: the parent's whole background
    if fresh:
        step = plans.slice_for(home, s)
        piece = relay.slice_text(home, s) if cut_to else ""
        text = "\n\n".join(p for p in (text, step, piece) if p)
    if above:
        text = "\n\n".join(p for p in (text, relay.scratch_line(home, me.cli, s.get("cwd") or "")) if p)
    if above and "anchorSeen" not in s:
        # the start is the child's base: a fresh child's slice or a fork's inherited conversation already holds the
        # anchor as it is now, so the rebase check hands over only what changes after it
        s["anchorSeen"] = relay.anchor_version(home, above)
        s["marksGiven"] = relay.mark_keys(home, above)
    return text


def pin_of(home, s):
    """A forked child's own task, shard and root step, above the conversation it inherited; '' for others."""
    if not s.get("forked"):
        return ""
    line = relay.pin_text(s)
    root = plans.root_of(home, s)
    return (line + f" It is for step {root} of its parent's plan; its own steps are {root}.1, {root}.2, and so on.") \
        if line and root else line


def h_plan(payload):
    """PostToolUse on mcp__ccd_turn__update_plan: the session's plan.json, the parent's plan tree, a revision
    relayed, and at a step boundary what bears on the step starting now (plans.py)."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    save_session(me.home, s)
    text = plans.record(me.home, s, inp, payload.get("transcript_path") or "")
    if isinstance(inp.get("items"), list):        # a plan's first whole list, or a revision of it
        s = load_session(me.home, me.id) or s
        cap = caps_text(me.home, s)
        advise = plans.split_advice if spawned_from(s) else plans.top_advice if TOP_ORCHESTRATES else None
        advice = advise(me.home, s, plans.load(me.home, me.id), s.get("turnBy", "user") == "user", cap)             if advise else ""                      # #24: a project whose top session lands its plan itself
        RAN["split"] = "advised" if advice else ""
        text = "\n\n".join(p for p in (advice, text) if p)
    if not spawned_from(s) and any(k in inp for k in ("advance", "start", "done", "items")):
        wt = relay.worktrees_text(me.home, me.id, relay.repo_of(s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
                                                                or ""))
        if wt:                                     # #22: at the top's step boundary, merged worktrees to remove
            RAN["worktrees"] = wt.count("git worktree remove")
            text = "\n\n".join(p for p in (text, wt) if p)
    nudge_arm(me, load_session(me.home, me.id) or s)
    RAN["plan"] = len(text)
    return text or None


# --- the nudge: a top session doing a work step itself ------------------------------------------------------------
#
# The marker <store>/phi/.nudge/<CLI session id> exists while a top session's step in progress is a work step it has
# not been nudged on; recall-hook.sh lets an Edit, Write or shell call through to python only while a marker names
# the call's session, so every other call pays nothing.

NUDGE_LOOKING = (LOOKING | frozenset("""uniq basename dirname realpath stat du df env type command jq less more nl
column od xxd sha1sum sha256sum md5sum cmp comm false read set ps tasklist whoami hostname uname history
select-object where-object foreach-object measure-object format-table format-list out-string sort-object
get-process get-command resolve-path join-path split-path get-date get-location convertfrom-json get-filehash
compare-object""".split())) - {"mkdir"}
GIT_READ = frozenset("status log diff show branch rev-parse remote fetch ls-files blame shortlog describe reflog "
                     "config grep cat-file show-ref ls-tree".split())
GIT_LANDS = frozenset("add commit merge push pull tag rebase cherry-pick stash notes".split())
REDIRECT = re.compile(r"(?<![0-9&>])>>?\s*(?!&|/dev/null|\$null|nul\b)\S", re.I)


def nudge_marker(me):
    return os.path.join(me.store or me.home, "phi", ".nudge", SAFE.sub("_", str(me.cli))[:80])


def nudge_key(step):
    return f"{step.get('addr')}:" + hashlib.sha1(str(step.get("content") or "").encode("utf-8")).hexdigest()[:10]


def nudge_step(home, s):
    """The top session's step in progress when it is a work step not nudged on yet, else None."""
    if not s or spawned_from(s) or not TOP_ORCHESTRATES:
        return None
    plan = plans.load(home, s["sessionId"])
    st = plans.step_of(plan, plan.get("current") or "") if plan.get("steps") else None
    text = str((st or {}).get("content") or "")
    if (not st or st.get("status") == "completed" or plans.LANDS.search(text) or plans.ORCHESTRATES.search(text) or plans.WAITS.search(text)
            or plans.MANAGES.search(text) or plans.TABULATES.search(text)):
        return None
    return None if nudge_key(st) in (s.get("nudged") or []) else st


def nudge_arm(me, s):
    """The marker made while a nudge is owed, removed otherwise."""
    if not me.cli:
        return
    path = nudge_marker(me)
    try:
        if nudge_step(me.home, s):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(s["sessionId"] + "\n")
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


ASSIGN = re.compile(r"^(?:export\s+|set\s+)?\$?([A-Za-z_]\w*)\s*=\s*('[^']*'|\"[^\"]*\"|\S*)\s*(.*)$", re.S)
PHI_PY = re.compile(r"(?:^|[\/'\"\s])phi\.py\b")
PYTHONS = ("python", "python3", "py", "uv", "pythonw")


def runs_phi(part, phi_vars):
    """True when one shell command runs phi.py: python with phi.py, or a variable bound to it, among its words, or
    phi.py itself, or that variable, as the program."""
    p = re.sub(r"^&\s*", "", clean(part))
    first = p.split(" ", 1)[0].strip("'\"") if p else ""
    refs = [rf"\$\{{?(?:env:)?{re.escape(v)}\b" for v in phi_vars]
    def names_phi(x):
        return bool(PHI_PY.search(" " + x) or any(re.search(r, x, re.I) for r in refs))
    if names_phi(first):
        return True
    return program(p) in PYTHONS and names_phi(p)


def work_command(cmd):
    """True when a shell command builds, tests or changes files: anything past reading, git's reading and landing
    commands, and phi's own commands: any that runs phi.py, directly or through a variable bound to it."""
    raw = str(cmd or "")
    quoted = []

    def hold(m):
        quoted.append(m.group(0))
        return f"'\x00{len(quoted) - 1}\x00'"
    c = QUOTED.sub(hold, raw)
    if REDIRECT.search(QUOTED.sub("''", raw)):
        return True
    phi_vars = set()
    for part in re.split(r"&&|\|\||;|\n|\|", c):
        part = part.strip()
        whole = re.sub(r"'\x00(\d+)\x00'", lambda m: quoted[int(m.group(1))], part)
        bind = ASSIGN.match(whole)
        if bind:                                   # VAR=value, or export / set / $VAR = value: no effect of its own
            if PHI_PY.search(bind.group(2)):
                phi_vars.add(bind.group(1))
            if not bind.group(3).strip():
                continue
            whole = bind.group(3).strip()
            part = whole
        if runs_phi(whole, phi_vars):
            continue
        part = re.sub(r"'\x00\d+\x00'", "''", part)
        prog = program(part)
        if prog in NUDGE_LOOKING:
            if prog == "sed" and re.search(r"\s-i", part):
                return True
            continue
        if prog == "git":
            words = [w for w in part.split()[1:] if not w.startswith("-")]
            sub = words[0] if words else ""
            if not sub or sub in GIT_READ or sub in GIT_LANDS:
                continue
            return True
        if prog == "gh":
            continue
        return True
    return False


def work_call(s, name, inp):
    """True for an Edit or Write to the project's own files, outside its .claude folder, or a working command."""
    if name in EDIT_TOOLS:
        f = relay.norm(inp.get("file_path") or inp.get("notebook_path") or "")
        proj = relay.norm(s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "")
        if not f or "/.claude/" in f + "/":
            return False
        return not proj or relay.covers(proj, f)
    if name in SHELL_TOOLS:
        return work_command(inp.get("command"))
    return False


def h_nudge(payload):
    """PreToolUse on Edit, Write and shell commands in a top session with a plan: one line, once per step, that the
    work goes to a child session. Never a block; reading, git's reading and landing commands are never nudged."""
    me = Me(payload)
    if not me.home or not me.id or not me.cli or not os.path.exists(nudge_marker(me)):
        return None
    s = load_session(me.home, me.id)
    st = nudge_step(me.home, s)
    if not st:
        try:
            os.remove(nudge_marker(me))
        except OSError:
            pass
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not work_call(s, str(payload.get("tool_name") or ""), inp):
        return None
    s["nudged"] = (list(s.get("nudged") or []) + [nudge_key(st)])[-50:]
    save_session(me.home, s)
    nudge_arm(me, s)
    RAN["nudge"] = st.get("addr")
    return (f"phi (p4-phi): this is the top session, kept free for orchestration, and step {st.get('addr')}, "
            f"\"{cut(clean(st.get('content')), 120)}\", is work: hand it to a child session with "
            f"`mcp__ccd_session__start_session`, `context` `fresh`, `use_worktree: false`, its brief that step and "
            f"\"archive when done\", and keep this session for planning, relaying and landing. Said once for this "
            f"step.")


def h_memory_gap(payload):
    """PostToolUse on Write and Edit: a feedback memory written into the project's store whose rule describes
    session or plugin behaviour gets the advice to start a new top session for that plugin gap (gaps.py)."""
    me = Me(payload)
    if not me.home or not me.id or not me.store:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    path = str(inp.get("file_path") or "")
    if not path:
        return None
    import gaps
    s = load_session(me.home, me.id) or ensure_session(me.home, me.id, me.rec, me.cli)
    text = gaps.advice(me.home, me.store, s, path, s.get("turnBy", "user") == "user", commands(),
                       NEW_TOP_BRIEF + " " + new_top_first_act())
    RAN["memory_gap"] = bool(text)
    return text or None


def h_self_archive(payload):
    """PreToolUse on mcp__ccd_session_mgmt__archive_session: a child archiving itself may never reach its Stop
    hook, so its turn and its last report are kept now, read from the transcript, and it is retired onto its parent
    as at Stop (#30: such a child's report was lost)."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not spawned_from(s):
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = str(inp.get("session_id") or inp.get("sessionId") or inp.get("id") or "self")
    if target not in ("self", me.id, me.cli, me.id.removeprefix("local_")):
        return None
    turn = last_turn(payload.get("transcript_path") or "")
    texts = [t for t in (turn or {}).get("texts") or [] if isinstance(t, str) and t.strip()]
    h_stop({**payload, "hook_event_name": "Stop", "last_assistant_message": texts[-1] if texts else "",
            "_atArchive": True})
    RAN["self_archive"] = True
    return None


def h_task(payload):
    """PostToolUse on Bash, Monitor, Agent and Workflow: a background task recorded under the step in progress,
    with the heads, paths and words it runs against (plans.register). Prints nothing."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not s:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if str(payload.get("tool_name") or "") in ("TaskStop", "KillShell"):
        tid = inp.get("task_id") or inp.get("shell_id") or inp.get("id")
        RAN["task"] = ",".join(plans.pickup(me.home, me.id, json.dumps({"name": "TaskStop", "input": {"task_id": tid}})))
        return None
    t = plans.register(me.home, s, str(payload.get("tool_name") or ""), inp, payload.get("tool_response") or "",
                       s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "")
    RAN["task"] = (t or {}).get("id", "")
    return None


def mark_fork(s, me, payload):
    """A session the app records as a fork, or whose first message is a fork's, is kept as one."""
    if s.get("forked"):
        return
    if (me.rec or {}).get("forkedFromSessionId") or FORK_HEAD.match(str(payload.get("prompt") or "")):
        s["forked"] = True


def ran_for(s, me):
    held = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
    RAN.update(home=me.home, session=s["sessionId"], spawnedFrom=held.get("sessionId", ""),
               source=held.get("source", ""), cli=me.cli)


def h_session_start(payload):
    me = Me(payload)
    if not me.home or not me.id:
        # AW1: a project with no .claude/p4 yet still gets the rule phi carries itself; the SessionStart hooks run
        # side by side, so p4-temportal making the folder first is not to be counted on
        RAN["start"] = "no store"
        return (builtin_text() or None) if RULES and payload.get("source") != "resume" else None
    p4conf.migrate_layout(me.store)       # the memory read below is where the other plugins will have moved it
    relay.track(me.home, first_only=True)  # the session tree, committed on its own the first time
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    ran_for(s, me)
    mark_fork(s, me, payload)
    source = payload.get("source") or "startup"
    RAN["start"] = source
    lost = source in ("compact", "clear")
    text = rule = ""
    if not (source == "startup" and not spawned_from(s) and not s.get("task")
            and os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")):
        # with a host id and nothing recorded, the app has not yet written which session started this one, and
        # the first message tells
        text = given(s, me, me.home, own=lost or len(s.get("cliSessionIds") or []) > 1)
        rule = new_task_text(me.home, s, me, user=False, again=lost) if lost else ""
    pin = pin_of(me.home, s)
    text = "\n\n".join(p for p in (pin, text) if p)
    rules = rules_text(me.store, HOOK_CHARS - len(text) - len(rule) - 4,
                       fork=bool(s.get("forked"))) if source != "resume" else ""
    relay.remember_store(me.store)
    if me.home_missing:
        rule = "\n\n".join(p for p in (rule, f"phi (p4-phi): this project's p4.json names the home store "
                                               f"{me.home_missing}, which this machine has not seen; the session "
                                               f"tree stays in this project's store.") if p)
    save_session(me.home, s)
    return "\n\n".join(p for p in (rules, text, rule) if p) or None


def started_by(me, payload):
    """A handed-over message whose session has no recorded `spawnedFrom` yet: read it from the message's notes
    folder, and where the message names none wait for the app to write the record. Returns the Me to go on with."""
    prompt = payload.get("prompt")
    if spawned_from(me.rec) or not me.id.startswith("local_") or not handed_over(prompt):
        return me
    if me.home:
        s = load_session(me.home, me.id)
        if s.get("task") or s.get("spawnedFrom"):
            return me
    m = NOTES_ID.search(prompt if isinstance(prompt, str) else "")
    if m and m.group(1) != me.id:
        return Me(payload, hint=m.group(1))
    wait = WAIT_S
    try:
        wait = float(os.environ.get("P4_PHI_WAIT", wait))
    except ValueError:
        pass
    started = time.time()
    while time.time() - started < wait:
        time.sleep(0.1)
        RECORDS.clear()
        if spawned_from(app_record(me.id)):
            RAN["waited_ms"] = round((time.time() - started) * 1000)
            return Me(payload)
    RAN["waited_ms"] = round((time.time() - started) * 1000)
    return me


def within(parts, room=None):
    """The parts joined, cut evenly to the hook's room: Claude Code files away a hook's text past 10,000 characters
    (RF1: a first look once gave 11.4 KB)."""
    room = HOOK_CHARS if room is None else room
    parts = [p for p in parts if p]
    if sum(len(p) + 2 for p in parts) <= room:
        return "\n\n".join(parts)
    return "\n\n".join(fair_cut(parts, room - 2 * len(parts)))


def h_user_prompt_submit(payload):
    me = started_by(Me(payload), payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli, hint=me.hint)
    ran_for(s, me)
    detached_now = False
    if spawned_from(s) and NEW_TOP.search(str(payload.get("prompt") or "")) and not load_turns(me.home, s["sessionId"]):
        reparent(me.home, s["sessionId"], "", "detached")     # its brief marks it a new top: into the root
        s = load_session(me.home, s["sessionId"])
        RAN["new_top"] = True
        detached_now = True
    rid, asker = starts.requester_of(me.home, payload.get("prompt")) if not load_turns(me.home, s["sessionId"]) \
        else ("", "")
    if rid:                                        # a start request's child: the requester's, not the starter's
        if not detached_now and asker != s["sessionId"] and spawned_from(s) != asker:
            try:
                reparent(me.home, s["sessionId"], asker, "requested")
                RAN["requested_by"] = asker
            except ValueError:
                pass
            s = load_session(me.home, s["sessionId"])
        starts.started(me.home, rid, s["sessionId"])
    req = request_of(payload.get("prompt"))
    said = str(payload.get("prompt") or "")
    if spawned_from(s) and not s.get("landingGiven") and LANDING_GIVEN.search(said) \
            and f'<cross-session-message from="{spawned_from(s)}"' in said:
        s["landingGiven"] = True                   # #19: the parent let this child land its own work
    s["turnBy"] ="user" if req else (
        "session" if re.search(r"<cross-session-message\b", str(payload.get("prompt") or "")) else "event")
    plans.pickup(me.home, s["sessionId"], payload.get("prompt") or "")
    mark_fork(s, me, payload)
    if not s.get("disposable") and relay.DISPOSABLE.search(str(payload.get("prompt") or "")) \
            and not load_turns(me.home, s["sessionId"]):
        s["disposable"] = True                     # its brief or its first message: archive when done
        RAN["disposable"] = True
    if s.get("doneRetired") or s.get("archived"):
        s["doneRetired"] = s["archived"] = False   # messaged again: a live node once more
    if req and not s.get("task"):
        s["task"] = cut(req, TASK_CHARS)
        s["taskAt"] = now()
    parts = [pin_of(me.home, s), given(s, me, me.home)]
    if REPORTS:
        text, seen = reports_text(me.home, s)
        s["reportsSeen"] = seen
        parts.append(text)
    save_session(me.home, s)
    step = replay(me, s, payload.get("transcript_path") or "")
    s = load_session(me.home, s["sessionId"]) or s
    if step:
        parts.append(step)
    pend = (s.pop("staleChildren", None) or []) + relay.drain_archive(me.home, s["sessionId"])
    pend = [x for x in pend if isinstance(x, dict) and not archived_already(me.home, x.get("id"))]
    stale = relay.stale_text(pend)                # children to archive, said once; one archived by hand is not named
    s["staleTold"] = (list(s.get("staleTold") or []) + [x.get("id") for x in pend if isinstance(x, dict)])[-50:]
    if stale:
        parts.insert(0, stale)
        if not spawned_from(s):                    # #22: a child retired or archived: merged worktrees to remove
            wt = relay.worktrees_text(me.home, s["sessionId"], relay.repo_of(s.get("cwd") or ""))
            if wt:
                parts.insert(1, wt)
    asked = starts.hand_text(me.home, s["sessionId"]) if req and not handed_over(payload.get("prompt")) else ""
    if asked:                                      # ezexe began this turn: it carries the sessions' start requests
        parts.insert(0, asked)
        RAN["start_requests"] = asked.count("\n- ")
    if detached_now:
        parts.insert(0, "phi (p4-phi): this session's brief marks it a new top session, so phi detached it into the "
                        "root at this first message. Now call `mcp__ccd_session_mgmt__detach_session` with `\"self\"` "
                        "before anything else, so the app stops nesting it under its starter and its reports stop "
                        "going there; it orchestrates its own topic, and the other top sessions relay to it as "
                        "siblings.")
    unsent = [u for u in s.pop("unsentRelay", None) or [] if isinstance(u, dict)]
    if unsent:
        parts.insert(0, "phi (p4-phi): " + " ".join(
            f"your last turn changed step(s) {', '.join(u.get('steps') or [])} of \"{relay._title(load_session(me.home, u['child']))}\" "
            f"and sent it nothing; relay it with SendMessage (`to`: {u['child']})." for u in unsent))
    route = relay.route_text(me.home, s["sessionId"], req, s.get("cwd") or "") if req else ""
    parts.append(route or new_task_text(me.home, s, me, user=bool(req)) or split_text(me.home, s, payload.get("prompt")))
    save_session(me.home, s)
    # the rebase check, on every message: what the nodes beside this one changed, and the warnings, first
    used = sum(len(p) for p in parts if p)
    text, _ = relay.rebase(me.home, s["sessionId"], HOOK_CHARS - used, fair_cut)
    RAN["relay"] = len(text)
    return within([text] + parts)


def h_stop(payload):
    me = Me(payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    if not TURNS:
        return None
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    ran_for(s, me)
    report = payload.get("last_assistant_message") or ""
    turn = last_turn(payload.get("transcript_path") or "")
    if not turn and s.get("task"):
        turn = {"prompt": s["task"], "uuid": "", "calls": []}
    if not turn:
        return None
    row = turn_of(turn, report if isinstance(report, str) else "")
    row.update({"time": now(), "sessionId": s["sessionId"], "cliSessionId": me.cli})
    earlier_ = load_turns(me.home, s["sessionId"])
    if earlier_ and earlier_[-1].get("atArchive") and earlier_[-1].get("id") == row["id"]:
        return None                                # #30: kept already when this session archived itself
    if payload.get("_atArchive"):
        row["atArchive"] = True
    said = said_of(turn, row["report"])
    if said:
        row["said"] = said
    done = s.get("done") if isinstance(s.get("done"), dict) else None
    if done and clean(done.get("text")):
        row["done"] = clean(done["text"])[:400]
    files = [c["input"].get("file_path") or c["input"].get("notebook_path") for c in turn.get("calls") or []
             if c.get("name") in EDIT_TOOLS and isinstance(c.get("input"), dict)]
    earlier = load_turns(me.home, s["sessionId"])
    row["delta"] = relay.delta(me.home, s, [f for f in files if f],
                               s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
                               since=str(earlier[-1].get("time") or "") if earlier else "")
    row["sessions"] = [f"\"{r.get('title') or r['sessionId'][:14]}\": "
                       f"{'done' if r['turn'].get('done') else 'not shown done'}"
                       for r in latest_reports(load_reports(me.home, s["sessionId"]))][:TURN_STEPS]
    append_line(os.path.join(session_dir(me.home, s["sessionId"]), "turns.jsonl"), row)
    above = spawned_from(s)
    append_line(reports_path(me.home, above),
                {"time": row["time"], "sessionId": s["sessionId"], "title": title_of(s), "turn": row})
    s.pop("done", None)
    if not s.get("task"):
        s["task"], s["taskAt"] = row["prompt"], row["time"]
    save_session(me.home, s)
    replay(me, s, payload.get("transcript_path") or "")
    s = load_session(me.home, s["sessionId"]) or s
    plans.pickup(me.home, s["sessionId"], plans.transcript_tail(payload.get("transcript_path") or ""))
    if isinstance(s.get("stale"), dict) and s["stale"].get("told"):
        s.pop("stale", None)                       # told what superseded it, and a turn of its own ended since
        s["unstaled"] = now()
    unsent = plans.turn_relay(me.home, s, row, turn.get("calls") or [])
    if unsent:                                     # what this turn changed for a child and did not tell it
        s["unsentRelay"] = [{"child": c, "steps": a, "time": row["time"]} for c, a in unsent]
    save_session(me.home, s)
    steps = plans.load(me.home, s["sessionId"]).get("steps") or []
    if s.get("disposable") and above and (row.get("done") or (steps and all(x.get("status") == "completed"
                                                                              for x in steps))):
        if relay.retire_done(me.home, above, s["sessionId"], s, row["time"]):
            RAN["retired"] = "done"
    if above and (row.get("done") or (steps and all(x.get("status") == "completed" for x in steps))):
        cur = load_session(me.home, s["sessionId"]) or s
        told = list(cur.get("closesTold") or [])
        new = [c for c in relay.closing_commits(me.home, s["sessionId"], cur) if c[1] not in told]
        if new:                                    # #27: the top session pushes issue-closing work at once
            top = (chain_of(me.home, s["sessionId"]) or [above])[-1]
            relay.warn(me.home, top, "push:" + s["sessionId"] + ":" + ",".join(c[1] for c in new),
                       relay.push_text(title_of(cur), s["sessionId"], new))
            cur["closesTold"] = (told + [c[1] for c in new])[-100:]
            save_session(me.home, cur)
            RAN["push_told"] = len(new)
    for node in (above, s["sessionId"]):           # the anchor of the node above, and this node's own for its children
        a = relay.make_anchor(me.home, node, row["time"])
        if a and node == above:
            RAN["anchor"] = a.get("version")
    render_page(me.home, s["sessionId"])
    render_page(me.home, above)
    relay.track(me.home)                           # staged for the store's next commit, so it reaches the others
    RAN.update(turn=row["id"], done=bool(row["done"]))
    now_s = load_session(me.home, s["sessionId"]) or s
    if now_s.get("doneRetired") or now_s.get("archived"):
        return None
    why = plans.keep_going(me.home, now_s, row["report"], turn.get("calls") or [], row["id"],
                           bool(payload.get("stop_hook_active")))
    if why:                                        # #20: open steps the chain can settle send the turn back
        RAN["kept_going"] = True
        return {"decision": "block", "reason": why}
    return None


RAN = {}       # what the running hook learned, for its line in the session's log


def log_run(name, text, started):
    """One line a hook call in <session>/log.jsonl: what ran, for which session, how much it said and how long
    it took. This is what the plugin is measured from."""
    if not RAN.get("home") or not RAN.get("session"):
        return
    row = {"time": now(), "hook": name, "said": len(text or ""), "ms": round((time.time() - started) * 1000),
           "host_in_env": bool(os.environ.get("CLAUDE_CODE_HOST_SESSION_ID"))}
    row.update({k: v for k, v in RAN.items() if k not in ("home", "session")})
    append_line(os.path.join(session_dir(RAN["home"], RAN["session"]), "log.jsonl"), row)


def h_start_advice(payload):
    """PreToolUse on mcp__ccd_session__start_session: fork or fresh, advised from the parent's transcript size and
    how much of the parent's scope the brief's paths cover (relay.advise_start). Silent when the call already does
    what is advised; otherwise a permission "ask" with the reason, so the person sees it and decides, never a
    block. The hooks documentation read for p4-recall (2026-11-01) gives PreToolUse `permissionDecision` allow,
    deny or ask with a reason, and `updatedInput`; the input is never rewritten here, since a fresh start needs a
    brief and background only the caller can write. How an ask shows in a mode that asks for no permission was
    not measured."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if inp.get("proposal_id") and not inp.get("prompt"):
        return None                                 # starting a proposal already made: nothing to decide
    if starts.claim(me.home, inp.get("prompt"), me.id):
        RAN["claimed"] = True                       # a start request's call, given exactly: the requester decided
        return None
    wanted = "fork" if str(inp.get("context") or "fresh") == "fork" else "fresh"
    try:
        size = os.path.getsize(payload.get("transcript_path") or "")
    except OSError:
        size = 0
    advised, why = relay.advise_start(me.home, me.id, inp, size)
    RAN.update(advice=advised, wanted=wanted, transcript=size)
    reasons = []
    if advised != wanted:
        reasons.append(f"p4-phi advises context \"{advised}\" here, not \"{wanted}\": {why}.")
    if inp.get("use_worktree") is True or inp.get("branch_name") or inp.get("source_branch"):
        # ezexe's rule: a child works on the parent's branch in the parent's checkout
        reasons.append("p4-phi: ezexe's rule is no worktrees and no branches of a child's own; pass "
                       "`use_worktree: false`, leave out branch_name and source_branch, and let the child work on "
                       "this session's branch in this checkout.")
    if not reasons:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": " ".join(reasons)}}


QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
BRANCH_MOVE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b[^\n|;&]*?\b(switch\b|checkout\s+(?!--)(?!-[^bB])(?![\w./-]*\.\w{1,6}\s*$)[\w./-]+\s*$)")
BRANCHING = re.compile(r"\bgit\b[^\n|;&]*?\b(worktree\s+add|switch\s+(-c|--create|-C)|checkout\s+(-b|-B)|"
                       r"branch\s+(?!-)[\w./-]+\s*$|branch\s+(?!-)[\w./-]+\s+[\w./-]+)")
LANDING = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b[^\n|;&]*?\b(push|merge|rebase|pull)(?![\w-])")
# a brief that hands the child the landing itself: "then push main yourself", "you merge and push"
LANDING_GIVEN = re.compile(r"\b(?:push|merg|land)\w*\b[^.\n]{0,60}\byourself\b|\byou (?:may |can |then )?"
                           r"(?:merge|push|land)\b"
                           # a fixer closing issues lands its own green issue commits, by ezexe's push-at-once rule
                           r"|\b(?:clos|fix|resolv)\w*\b[^.\n]{0,40}\bissues?\b|\bCloses #\d+|\bissues? #\d+", re.I)


def h_branch_guard(payload):
    """PreToolUse on EnterWorktree and Bash in a session another one started: making a worktree or a branch of its
    own is asked first, ezexe's rule being that a child works on its parent's branch. So is landing work, a git
    push, merge, rebase or pull, which the parent does, unless the child's brief handed it the landing. Silent
    otherwise."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not spawned_from(s):
        return None
    name = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if name == "EnterWorktree":
        what = "entering a worktree of its own"
    elif name in SHELL_TOOLS and BRANCHING.search(QUOTED.sub("''", str(inp.get("command") or ""))) \
            and re.search(r"(?:^|&&|\|\||;|\||\n)\s*git\b", QUOTED.sub("''", str(inp.get("command") or ""))):
        what = "making a worktree or branch of its own"
    elif name in SHELL_TOOLS and BRANCH_MOVE.search(QUOTED.sub("''", str(inp.get("command") or ""))):
        what = "moving the checkout to another branch, which in a shared checkout moves the parent's too"
    elif name in SHELL_TOOLS and LANDING.search(QUOTED.sub("''", str(inp.get("command") or ""))) \
            and not LANDING_GIVEN.search(str(s.get("task") or "")) and not s.get("landingGiven"):
        verb = LANDING.search(QUOTED.sub("''", str(inp.get("command") or ""))).group(1)
        RAN["branch_guard"] = f"git {verb}"
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                       "permissionDecisionReason": f"p4-phi: this session is a child, and `git {verb}` "
                                                                   f"lands work, which its parent does: a child commits "
                                                                   f"on its parent's branch and reports, and the "
                                                                   f"session that started it ({spawned_from(s)}) "
                                                                   f"merges and pushes. Ask it with SendMessage "
                                                                   f"instead, unless its brief gave this session the "
                                                                   f"landing."}}
    else:
        return None
    RAN["branch_guard"] = what
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": f"p4-phi: this session is a child, and {what} goes "
                                                               f"against ezexe's rule: a child works on its "
                                                               f"parent's branch in the parent's checkout, so its work "
                                                               f"needs no merge."}}


STORE_MOVE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b([^\n|;&]*?)\b(push|pull)(?![\w-])([^\n|;&]*)")
DASH_C = re.compile(r"(?:^|\s)-C\s+(\S+)")
CD = re.compile(r"(?:^|&&|;|\n)\s*(?:cd|pushd|Set-Location)\s+(\S+)\s*(?=&&|;|\n|$)")


def store_root(path):
    """The p4 store a folder is in: its `.claude/p4`, when the folder's git checkout is the store itself; '' for
    any other folder, a clone kept under the store's temportal/tmp among them."""
    p = relay.norm(path)
    m = re.search(r"^(.*?/\.claude/p4)(?=/|$)", p, re.I)
    if not m:
        return ""
    root = m.group(1)
    rest = p[len(root):].lstrip("/")
    if os.path.isdir(p):
        r = relay._git(p, "rev-parse", "--show-toplevel")
        top = relay.norm(r.stdout.strip()) if r is not None and r.returncode == 0 else ""
        return root if top == root else ""
    return "" if rest.lower().startswith(("temportal/tmp", "phi/sessions")) else root


def h_store_guard(payload):
    """PreToolUse on a shell call (#21): a hand `git pull`, `git push` or force-push in a p4 store is asked first, and
    `p4.py sync --push --p4 <store>` named as the way, since two machines write the same files and a plain merge or
    a line-union damages them."""
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cmd = QUOTED.sub(lambda m: m.group(0) if re.match(r"^['\"][^'\"\s]*['\"]$", m.group(0)) else "''",
                     str(inp.get("command") or ""))
    m = STORE_MOVE.search(cmd)
    if not m:
        return None
    base = str(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "")
    places = [x.group(1) for x in CD.finditer(cmd[:m.start()])][-1:] or [base]
    dash = DASH_C.search(m.group(1))
    if dash:
        places = [relay.norm(dash.group(1), relay.norm(places[0]))]
    store = ""
    for p in places:
        store = store_root(relay.norm(p, relay.norm(base)) if p else "")
        if store:
            break
    if not store:
        return None
    force = bool(re.search(r"(?:^|\s)(?:-f|--force(?:-with-lease)?)\b|\s\+\S", m.group(3) + m.group(1)))
    what = "a force-push" if force and m.group(2) == "push" else f"a hand `git {m.group(2)}`"
    RAN["store_guard"] = what
    sync = f"python -I -X utf8 \"{os.path.join(HERE, 'p4.py')}\" sync --push --p4 \"{store}\"".replace("\\", "/")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": f"p4-phi: this is {what} in the p4 store {store}. A "
                                                               f"store moves only by `{sync}`: two machines write the "
                                                               f"same files, and a plain merge or a line-union damages "
                                                               f"them. Then check each entry the sync names as "
                                                               f"changed."}}


def once(home, sid, kind, payload):
    """True the first time this tool call reaches this handler: a session whose hook list holds both the routed
    entry and the dedicated one runs each check once. An atomic file per call; True when the call names no id."""
    tid = SAFE.sub("_", str(payload.get("tool_use_id") or ""))[:80]
    if not tid or not home or not sid:
        return True
    d = os.path.join(session_dir(home, sid), ".calls")
    try:
        os.makedirs(d, exist_ok=True)
        fd = os.open(os.path.join(d, f"{kind}-{tid}"), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return False
    except OSError:
        return True
    try:
        old = time.time() - 86400
        for n in os.listdir(d)[:500]:
            p = os.path.join(d, n)
            if os.path.getmtime(p) < old:
                os.remove(p)
    except OSError:
        pass
    return True


ROUTED = {}


def epoch_of(stamp):
    """Epoch seconds of a transcript timestamp, None when there is none."""
    if not stamp:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def replay(me, s, transcript):
    """The plan calls and background launches of the transcript that no hook handled, applied in order -> the step
    boundary text of the last one, '' for none. A session whose hook list was frozen before recall's lookup entries
    reached it (one started before 13:30 on 2026-11-12 holds a p4-recall entry whose folder is gone) has only phi's
    own entries, so its calls are read back here, at each message and each Stop, each once by its tool_use_id."""
    if not transcript or not os.path.exists(transcript):
        return ""
    calls, results, notices, when, stops = [], {}, [], {}, []
    for d in read_transcript(transcript):
        c = (d.get("message") or {}).get("content")
        if d.get("type") == "user" and "<task-notification>" in json.dumps(c, default=str):
            notices.append(json.dumps(c, default=str))
        for b in c if isinstance(c, list) else []:
            if not isinstance(b, dict):
                continue
            if d.get("type") == "assistant" and b.get("type") == "tool_use" and b.get("name") in ("TaskStop",
                                                                                                "KillShell"):
                stops.append(json.dumps({"name": "TaskStop", "input": b.get("input") or {}}))
            elif d.get("type") == "assistant" and b.get("type") == "tool_use" and b.get("name") in (
                    "mcp__ccd_turn__update_plan", "Bash", "PowerShell", "Monitor", "Agent", "Workflow"):
                calls.append(b)
                when[b.get("id")] = str(d.get("timestamp") or "")
            elif d.get("type") == "user" and b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = result_text(b)
    text = ""
    last_list = max((k for k, b in enumerate(calls) if b["name"] == "mcp__ccd_turn__update_plan"
                     and isinstance((b.get("input") or {}).get("items"), list)), default=0)
    for b in calls[last_list:][-200:]:            # an earlier plan is replaced whole by the latest list (RB1)
        tid = b.get("id")
        if tid not in results:
            continue                                # still running, or its result not written yet
        name = "plan" if b["name"] == "mcp__ccd_turn__update_plan" else "task"
        payload = {"tool_name": b["name"], "tool_input": b.get("input") or {}, "tool_response": results[tid],
                   "tool_use_id": tid, "transcript_path": transcript}
        if name == "task" and not (b["name"] != "Bash" or (b.get("input") or {}).get("run_in_background")):
            continue
        if not once(me.home, me.id, name, payload):
            continue
        if name == "plan":
            text = plans.record(me.home, load_session(me.home, me.id) or s, payload["tool_input"], transcript) or text
        else:
            plans.register(me.home, load_session(me.home, me.id) or s, b["name"], payload["tool_input"],
                           payload["tool_response"], s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "",
                           at_epoch=epoch_of(when.get(tid)))
    notices += stops                               # RB1: a stop sends no notice; its call closes the task
    if notices:                                    # every completion notice of the transcript, not only its tail
        plans.pickup(me.home, me.id, "\n".join(notices))
    RAN["replayed"] = len(calls)
    return text


def routed(name, payload):
    """A phi handler run from another hook's entry (recall's lookup hooks), with the hook output phi would give and
    its log line."""
    if os.environ.get("P4_PHI") == "0":
        return None
    event, fn = ROUTED[name]
    started = time.time()
    RAN.clear()
    me = Me(payload)
    if not me.home or not me.id or not once(me.home, me.id, name, payload):
        return None
    RAN.update(home=me.home, session=me.id, routed=True)
    out = fn(payload)
    log_run(name, json.dumps(out) if isinstance(out, dict) else out, started)
    if isinstance(out, dict) or not out:
        return out or None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": out}}


def agent_marker(me, agent_id):
    return os.path.join(me.store or me.home, "phi", ".agents", SAFE.sub("_", str(agent_id))[:80])


def h_agent_launch(payload):
    """PreToolUse on Agent (recall's entry): a pending entry under the step in progress -> its slice, for its prompt."""
    me = Me(payload)
    if not me.home or not me.id:
        return ""
    s = load_session(me.home, me.id)
    if not s:
        return ""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    text = plans.agent_launch(me.home, s, payload.get("tool_use_id"), inp)
    RAN["agent"] = "launch"
    return text


def h_agent_call(payload):
    """A sub-agent's tool call, routed from recall's lookup hooks: bound to its entry after the call, warned before
    it. The shell lets a sub-agent's check through only while phi/.agents/ names an open sub-agent."""
    agent_id = str(payload.get("agent_id") or "")
    me = Me(payload)
    if not agent_id or not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not s:
        return None
    if payload.get("hook_event_name") == "PreToolUse":
        text = plans.agent_warn(me.home, s, agent_id)
        RAN["agent"] = "warned" if text else "checked"
        return text or None
    if plans.agent_bind(me.home, s, agent_id):
        try:
            os.makedirs(os.path.dirname(agent_marker(me, agent_id)), exist_ok=True)
            with open(agent_marker(me, agent_id), "w", encoding="utf-8") as f:
                f.write(me.id + "\n")
        except OSError:
            pass
        RAN["agent"] = "bound"
    return None


def h_agent_stop(payload):
    """SubagentStop (recall's entry): the sub-agent's entry closed with its last message."""
    agent_id = str(payload.get("agent_id") or "")
    me = Me(payload)
    if not agent_id or not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if s and plans.agent_stop(me.home, s, agent_id, payload.get("last_assistant_message") or ""):
        RAN["agent"] = "stopped"
    try:
        os.remove(agent_marker(me, agent_id))
    except OSError:
        pass
    return None


HOOKS = {"session-start": ("SessionStart", h_session_start),
         "user-prompt-submit": ("UserPromptSubmit", h_user_prompt_submit),
         "stop": ("Stop", h_stop),
         "start-advice": ("PreToolUse", h_start_advice),
         "branch-guard": ("PreToolUse", h_branch_guard),
         "store-guard": ("PreToolUse", h_store_guard),
         "plan": ("PostToolUse", h_plan),
         "memory-gap": ("PostToolUse", h_memory_gap),
         "self-archive": ("PreToolUse", h_self_archive),
         "task": ("PostToolUse", h_task)}
ROUTED.update({k: HOOKS[k] for k in ("start-advice", "branch-guard", "store-guard", "plan", "task", "memory-gap",
                                                     "self-archive")})
ROUTED["nudge"] = ("PreToolUse", h_nudge)
ROUTED.update({"agent-launch": ("PreToolUse", h_agent_launch), "agent-pre": ("PreToolUse", h_agent_call),
               "agent-post": ("PostToolUse", h_agent_call), "agent-stop": ("SubagentStop", h_agent_stop)})
OLD_NAMES = {"arrive": "session-start", "prompt": "user-prompt-submit", "exit": "stop"}   # hooks.json of 0.1 and 0.2,
#                                                                         still loaded in sessions that began then


def hook_main(name):
    """A hook never fails a call and says nothing without something to say."""
    try:
        name = OLD_NAMES.get(name, name)
        if os.environ.get("P4_PHI") == "0" or name not in HOOKS:
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        event, fn = HOOKS[name]
        started = time.time()
        if name in ROUTED:                          # a dedicated entry a newer hook list holds: once, as routed
            me = Me(payload)
            if me.home and me.id and not once(me.home, me.id, name, payload):
                return 0
            RAN.update(home=me.home, session=me.id)
        text = fn(payload)
        if isinstance(text, dict):                  # a hook that answers with its own JSON (start-advice)
            log_run(name, json.dumps(text), started)
            sys.stdout.write(json.dumps(text))
            return 0
        log_run(name, text, started)
        if text:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    except Exception:  # noqa: BLE001
        pass
    return 0


# --- the commands ----------------------------------------------------------------------------------------------------

def note_add(home, sid, claim, source, kind="", cli=""):
    claim, source = clean(claim), clean(source)
    if len(claim) < 12:
        raise ValueError("a note is a whole sentence")
    if not source:
        raise ValueError("a note needs its source: the file and line, the command, or the measurement that showed it")
    if any(clean(r.get("claim")).lower() == claim.lower() for r in load_notes(home, sid)):
        return False
    append_line(os.path.join(session_dir(home, sid), "notes.jsonl"),
                {"time": now(), "claim": claim[:600], "source": source[:300], "kind": clean(kind),
                 "cliSessionId": cli})
    render_page(home, sid)
    return True


def reparent(home, sid, under, source="reparented"):
    """Put a session under another one, or with no `under` detach it to a top session: session.json's
    `spawnedFrom` is rewritten, its latest turn is handed to where it now belongs, and the reports it left behind
    note that it left. The app's own nesting does not follow, and the app's record does not move it back."""
    sid, under = safe_id(sid), safe_id(under)
    s = load_session(home, sid)
    if not s.get("sessionId"):
        raise ValueError(f"no session {sid}")
    if under:
        ensure_session(home, under)
        if under == sid or sid in chain_of(home, under):
            raise ValueError("a session cannot be put under itself or under a session it started")
    old = spawned_from(s)
    if old == under:
        return False
    s["spawnedFrom"] = {"sessionId": under, "source": source, "from": old, "time": now()}
    s.pop("backgroundGivenFor", None)
    save_session(home, s)
    append_line(reports_path(home, old), {"time": now(), "left": sid, "to": under})
    turns = load_turns(home, sid)
    if turns:
        append_line(reports_path(home, under),
                    {"time": now(), "sessionId": sid, "title": title_of(s), "turn": turns[-1]})
    for x in (sid, old, under):
        render_page(home, x)
    return True


def tree_text(home):
    sessions = {}
    for p in glob.glob(os.path.join(home, "phi", "sessions", "*", "session.json")):
        d = read_json(p)
        if d.get("sessionId"):
            sessions[d["sessionId"]] = d
    gone_ = {k for k, d in sessions.items() if d.get("archived") or relay.archived_in_app(d)}
    started = {}
    for s in sorted(sessions.values(), key=lambda s: s.get("createdAt", "")):
        above = spawned_from(s)
        if s["sessionId"] in gone_ or above in gone_:
            continue                                 # an archived session, and what hangs under it, is not printed
        started.setdefault(above if above in sessions else "", []).append(s)
    out = []

    def walk(above, depth):
        for s in started.get(above, []):
            turns = load_turns(home, s["sessionId"])
            if not turns and not clean(s.get("title")) and not clean(s.get("task")):
                walk(s["sessionId"], depth)          # no record and no turns: an empty node, its children kept
                continue
            state = ("done" if turns[-1].get("done") else "not shown done") if turns else "no turn yet"
            out.append(f"{'  ' * depth}- {title_of(s)} ({s['sessionId']}): {state}, "
                       f"{len(turns)} turn{'s' * (len(turns) != 1)}")
            if depth < 30:
                walk(s["sessionId"], depth + 1)
    walk("", 0)
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        return hook_main(argv[1] if len(argv) > 1 else "")
    import argparse
    ap = argparse.ArgumentParser(description="phi: what linked sessions hand each other")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("note", "done", "task", "show", "tree", "background", "detach", "reparent", "shard", "disposable",
                 "request"):
        p = sub.add_parser(name)
        p.add_argument("--p4", default="", help="the store the sessions' files live in (default: this session's)")
        p.add_argument("--session", default="", help="the sessionId (default: this session's)")
        if name == "note":
            p.add_argument("claim")
            p.add_argument("--source", default="")
            p.add_argument("--kind", default="", help="ruled-out, decision, machine, code")
        if name in ("done", "task"):
            p.add_argument("text")
        if name == "show":
            p.add_argument("which", nargs="?", default="")
        if name == "detach":
            p.add_argument("moved", nargs="?", default="", help="the session to detach (default: this one)")
        if name == "reparent":
            p.add_argument("moved")
        if name == "shard":
            p.add_argument("paths", nargs="*", help="paths or globs this session alone may change; none shows it")
        if name == "reparent":
            p.add_argument("under")
        if name == "request":
            p.add_argument("title", help="the child's title")
            p.add_argument("--brief", default="", help="the child's whole brief")
            p.add_argument("--brief-file", default="", help="a file holding the brief")
            p.add_argument("--context", default="fresh", choices=("fresh", "fork"))
    a = ap.parse_args(argv)
    me = Me(session=a.session, p4=a.p4)
    if not me.home or not os.path.isdir(me.home):
        print("phi: no store found; pass --p4 <repository>/.claude/p4", file=sys.stderr)
        return 2
    configure(me.home)
    try:
        if a.cmd == "tree":
            print(tree_text(me.home) or "no sessions yet")
            return 0
        if a.cmd == "detach":
            if not a.moved and not me.id:
                print("phi: name the session to detach, or run this from inside it", file=sys.stderr)
                return 2
            a.moved = a.moved or me.id
            print("detached: it is a top session now" if reparent(me.home, a.moved, "", "detached")
                  else "already a top session")
            return 0
        if a.cmd == "reparent":
            print("reparented" if reparent(me.home, a.moved, a.under) else "already there")
            return 0
        if a.cmd == "show":
            sid = safe_id(a.which or me.id)
            render_page(me.home, sid)
            if not os.path.exists(page_path(me.home, sid)):
                print(f"phi: no session {sid}", file=sys.stderr)
                return 2
            with open(page_path(me.home, sid), encoding="utf-8") as f:
                sys.stdout.write(f.read())
            return 0
        if not me.id:
            print("phi: this is not a session (no session id in the environment); pass --session", file=sys.stderr)
            return 2
        s = ensure_session(me.home, me.id, me.rec, me.cli)
        if a.cmd == "shard":
            save_session(me.home, s)
            if not a.paths:
                print("\n".join(relay.shard_of(s)) or "this session declared no shard")
                return 0
            lines = relay.set_shard(me.home, s["sessionId"], a.paths, os.getcwd())
            print("kept as this session's shard: " + ", ".join(relay.shard_of(load_session(me.home, s["sessionId"]))))
            for line in lines:
                print("phi: " + line)
            return 0
        if a.cmd == "request":
            brief = a.brief
            if a.brief_file:
                with open(a.brief_file, encoding="utf-8") as f:
                    brief = f.read()
            save_session(me.home, s)
            rid, new = starts.add(me.home, s["sessionId"], a.title, brief, a.context)
            print(starts.requested_text(rid, new))
            if a.context == "fork":
                print("phi: a start request is always fresh: a fork would carry the starter's conversation, not "
                      "this session's, so the brief must say all the child needs.")
            return 0
        if a.cmd == "disposable":
            s["disposable"] = True
            save_session(me.home, s)
            print("this session is retired when its work is done: its outcome kept as a replaces: note on the "
                  "session that started it, which is told to archive it")
            return 0
        if a.cmd == "note":
            print("kept" if note_add(me.home, s["sessionId"], a.claim, a.source, a.kind, me.cli) else "already kept")
        elif a.cmd == "done":
            if len(clean(a.text)) < 8:
                raise ValueError("say what was run and what it showed")
            s["done"] = {"text": clean(a.text)[:400], "time": now()}
            save_session(me.home, s)
            print("this turn will be kept as done")
        elif a.cmd == "task":
            task = cut(a.text.strip(), TASK_CHARS)
            if len(clean(task)) < 12:
                raise ValueError("a task is a whole sentence")
            if s.get("task"):
                s.setdefault("earlierTasks", []).append({"task": s["task"], "until": now()})
            s["task"], s["taskAt"] = task, now()
            s.pop("newTaskToldAt", None)
            save_session(me.home, s)
            render_page(me.home, s["sessionId"])
            print("this session's task is changed; the task before it is kept in session.json")
        else:
            print(background_text(me.home, s, own=True) or "the sessions above this one have kept nothing yet")
    except ValueError as e:
        print(f"phi: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
