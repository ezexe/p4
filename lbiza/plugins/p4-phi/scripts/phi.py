#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

Each session has a folder <home>/phi/sessions/<sessionId>/ in the store its tree lives in: the store of its
orchestrator's project, or the shared store that p4.json's `phi.home` names. The folder holds session.json, the
app's fields for the session with its task; turns.jsonl, a line for each finished turn; notes.jsonl; reports.jsonl,
the reports of its workers; log.jsonl, a line for each hook call; and session.md, the session as one page.
The reports of orchestrators are in <home>/phi/reports.jsonl.

A hook's payload does not say which session started this one. The app's record says it in `spawnedFrom.sessionId`,
but for a fresh child the app may write it only after the first message, so the notes folder that message names is
read first and the record corrects it. `detach` and `reparent` rewrite it in session.json.

The hooks, each in its h_ function:
- SessionStart gives the built-in rules, as rules_text says, and the start background to a fork, after a clear,
  with the session's own turns and the address book whole, and to a session no app runs. After a compaction the
  summary keeps the conversation, so it gives the address book's changed entries with the path of book.md.
- UserPromptSubmit keeps the first request as the task and gives the start background with the first message when
  the start did not, then the reports of the workers that finished a turn since the last look, the address book's
  changes and what the sessions beside it changed. A start and a first message pass whole, the lines that ask
  the session to act first, past the app's cap to its own file; at a later message what does not fit in PROMPT_CHARS
  is held whole on held.md.
- Stop keeps the turn and appends it to the parent session's reports, sends the turn back while steps the session
  tree can settle are open, runs a writing child's issue gate, counts a child marked report when done as archived,
  tells the orchestrator to push issue-closing commits and makes the anchors.
- The checks before and after a tool call ride on the retrieval hooks' entries, through `routed`.

Commands: note, done, task, shard, files, show, tree, background, detach, reparent, disposable, request, proof and
controls, with the watcher's commands from puppeteer.py; `--help` gives the arguments of each.

Settings: <home>/phi/phi.json, every key optional: `background`, `reports`, `turns`, `book`, `rules`,
`background_chars`, `reports_chars`, `prompt_chars` and `wait_s`, and `puppeteer`, which puppeteer.on reads. The `phi`
section of p4.json: `act_dont_wait`, `levels`, `top_orchestrates`, `file_sets` and `child_levels`, read from the
session's own store, `home`, which names a shared store for the session tree, and `puppeteer_section`, which
controls.py reads. P4_PHI=0 turns the plugin off, P4_PHI_BOOK=0 the address book beside a
message and P4_PHI_RULES=0 the rules. P4_PHI_WAIT sets how long a first message waits for the app's
record, and P4_PHI_APP_SESSIONS the folder of the app's records.
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
import node as nd  # noqa: E402  a session's place in the tree, which retrieval reads too
import p4conf  # noqa: E402  the store's layout, each plugin's files in .claude/p4/<plugin>/
import plans  # noqa: E402  each session's task list with step addresses, which its parent's anchor holds
import relay  # noqa: E402  owned paths, deltas and anchors, which keep linked sessions in step while they work
import starts  # noqa: E402  write sets, and the starts a card cannot hold: behind a busy writer, or to a puppeteer
import issues  # noqa: E402  a writing child's issue, its Closes #N commit, regression test, push and archive
import puppeteer  # noqa: E402  the watcher's ledger, routing, start drafts, the gate, routes, readings, meta pass

puppeteer.PHI = sys.modules[__name__]   # phi.py runs as a script, so puppeteer.py is handed this module, not a copy
import controls  # noqa: E402  a puppeteer filed in the sidebar section, and the sessions it controls

controls.PHI = sys.modules[__name__]

BACKGROUND = True
REPORTS = True
TURNS = True
BOOK = True
RULES = True
# hooks.md, "additionalContext": a hook's text past 10,000 characters is written "to a file in the session directory"
# and Claude is passed "the file path with a preview of up to the first 2,000 characters instead". p4-phi leaves
# that cap and its overflow file to the app and cuts no text of its own at a session's start or first message: it
# puts the lines that ask the session to act first, so they fall inside the app's preview, and the rest follows
# whole.
HELD_HEAD = 90                   # of a piece that did not fit, shown beside the prompt so it is known for what it is
PHI_LEAD = re.compile(r"^phi \(p4-phi\)[^:]*:\s*")
PROMPT_CHARS = 4000              # the ceiling on what p4-phi adds beside one prompt; the rest is held on a page
BACKGROUND_CHARS = 3000
REPORTS_CHARS = 6000
REPORT_CHARS = 4000              # of one report, kept
FINDINGS_SHOWN = 12              # `Finding:` lines listed under a session's child reports
TASK_CHARS = 1200
TURN_STEPS = 12
CHAIN_MAX = 8                    # sessions followed upward from a session
OTHERS = 5
OWN = 3
TAIL_BYTES = 256 * 1024          # of a reports file, for a start background
TRANSCRIPT_BYTES = 8 * 1024 * 1024
WAIT_S = 2.0                     # how long a handed-over first message waits for the app's record
SCAN_RECORDS = 60                # the newest records searched for a CLI session id, when the host id is missing
SETTINGS = {"background": "BACKGROUND", "reports": "REPORTS", "turns": "TURNS", "book": "BOOK",
            "rules": "RULES", "background_chars": "BACKGROUND_CHARS", "reports_chars": "REPORTS_CHARS", "wait_s": "WAIT_S",
            "prompt_chars": "PROMPT_CHARS"}
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
# what a person pasted into the message box: the app wraps it, and a message may be nothing but the block
PASTED = re.compile(r"<pasted_content\b[^>]*>\n?(.*?)\n?</pasted_content\b[^>]*>", re.S)
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
    """The reports of the workers of `sid`; with no `sid`, of the orchestrators."""
    return os.path.join(session_dir(home, sid), "reports.jsonl") if sid else os.path.join(home, "phi", "reports.jsonl")


def page_path(home, sid):
    p = os.path.join(session_dir(home, sid), "session.md") if sid else os.path.join(home, "phi", "sessions.md")
    return p.replace("\\", "/")


def setting_fits(value, default):
    """True when a phi.json value can stand for a setting: of the default's type, or an integer for a float
    setting, as JSON writes 3 for 3.0. A bool is never taken for a number, nor a number for a bool."""
    if isinstance(default, float) and not isinstance(value, bool):
        return isinstance(value, (int, float))
    return type(value) is type(default)


def configure(home):
    d = read_json(os.path.join(home, "phi", "phi.json"))
    for key, name in SETTINGS.items():
        if key in d and setting_fits(d[key], globals()[name]):
            globals()[name] = d[key]
    if os.environ.get("P4_PHI_RULES") in ("0", "1"):
        globals()["RULES"] = os.environ["P4_PHI_RULES"] == "1"
    if "book" not in d and isinstance(d.get("new_task"), bool):   # the key's name before book, read as an alias
        globals()["BOOK"] = d["new_task"]
    for name in ("P4_PHI_BOOK", "P4_PHI_NEW_TASK"):  # P4_PHI_BOOK first; the older name as its alias
        if os.environ.get(name) in ("0", "1"):
            globals()["BOOK"] = os.environ[name] == "1"
            break


# --- the app's records: which session started which ----------------------------------------------------------------

def app_roots():
    """The folders that may hold the app's session records, each named claude-code-sessions, likeliest first."""
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
# sessionId -> the custom title SessionStart and UserPromptSubmit carry as `session_title`, hooks.md: "present when
# one is set, for example with `--name`, `/rename`"; it titles a session that has no app record to title it
GIVEN_TITLES = {}


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
    """The app's record of a session in one app folder, {} when it is not there. A session archived in the app keeps
    its record, with `isArchived`; a deleted session's is gone."""
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
    """The sessionId in a record's or a session.json's `spawnedFrom`, '' for an orchestrator."""
    s = d.get("spawnedFrom") if isinstance(d, dict) else None
    return safe_id(s.get("sessionId")) if isinstance(s, dict) and s.get("sessionId") else ""


def store_at(folder):
    if not folder:
        return ""
    p = os.path.join(folder, ".claude", "p4")
    return p if os.path.isdir(p) else ""


def home_of_record(rec, depth=0):
    """The store a session's tree lives in: that of its parent session, and its own folder's for an
    orchestrator."""
    if not rec or depth > CHAIN_MAX:
        return ""
    above = spawned_from(rec)
    if above:
        h = home_of_record(app_record(above), depth + 1)
        if h:
            return h
    return store_at(rec.get("cwd")) or store_at(rec.get("originCwd"))


def own_store(rec, sid, project=""):
    """The store of a session's own folder when it holds the session as an orchestrator, '' otherwise. A
    orchestrator that a puppeteer started in another environment lives in that environment's store,
    not in the puppeteer's."""
    own = store_at(project) or store_at((rec or {}).get("cwd")) or store_at((rec or {}).get("originCwd"))
    if not own or not sid:
        return ""
    s = load_session(own, sid)
    return own if s.get("sessionId") and not spawned_from(s) else ""


def same_store(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class Me:
    """The session a hook or a command is running for: its sessionId, its CLI session, the app's record, its home."""

    def __init__(self, payload=None, session="", p4="", hint=""):
        payload = payload or {}
        self.hint = ""
        self.cli = str(payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
        self.title = clean(payload.get("session_title"))[:120]
        host = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
        # A CLI id equal to the host id without "local_" is normal: the app gives many workers that pair of
        # ids, so it is no stray id.
        self.rec = app_record(session or host) if (session or host) else record_of_cli(self.cli)
        self.id = session or host or str(self.rec.get("sessionId") or "") or self.cli
        project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        self.home = p4 or ""
        self.store = store_at(project) or p4 or ""     # this project's own store: its memory, rules and retrieval
        self.home_missing = ""
        if not self.home:
            above = spawned_from(self.rec)
            if not above and hint and hint != self.id:
                above = self.hint = hint
            self.home = (home_of_record(app_record(above)) if above else "") or store_at(project) \
                or home_of_record(self.rec)
            if above:
                self.home = own_store(self.rec, self.id, project) or self.home
            self.home, self.home_missing = relay.tree_home(self.home)   # a shared store, when p4.json names one
        self.store = self.store or self.home
        if self.title and self.id:
            GIVEN_TITLES[self.id] = self.title
        project_conf(self.store)
        plans.PARENT_EFFORT = own_effort(self, payload, other=bool(session))


def own_effort(me, payload, other=False):
    """The effort level the session of this hook or command runs at, which plans.child_level holds every start's
    effort to: the hook input's `effort.level`, else CLAUDE_EFFORT, which Claude Code sets for hook commands and
    Bash subprocesses, else the last level the session's record kept. hooks.md, "Common input fields": `effort` is
    an "Object whose `level` is the effort level setting when the hook runs, including a skill's, subagent's, or
    `ultrathink` level", so a subagent's call names the subagent's level and is not read, and a command run for
    another session names its caller's. A level that differs from the record's is kept there. '' where nothing
    names one."""
    level = ""
    if not other and not payload.get("agent_id"):
        given = payload.get("effort")
        level = str((given.get("level") if isinstance(given, dict) else "") or os.environ.get("CLAUDE_EFFORT") or "")
        level = level.strip().lower()
        level = level if level in plans.EFFORTS else ""
    if not me.home or not me.id:
        return level
    held = load_session(me.home, me.id)
    kept = str(held.get("effort") or "")
    if level and level != kept and held.get("sessionId"):   # a session with no record yet keeps none: a later hook does
        path = os.path.join(session_dir(me.home, me.id), "session.json")
        with relay.locked(path):
            s = load_session(me.home, me.id)
            if s.get("sessionId"):
                s["effort"] = level
                _save_session(me.home, s)
    return level or (kept if kept in plans.EFFORTS else "")


# --- sessions --------------------------------------------------------------------------------------------------------

def archived_already(home, sid):
    """True when a child named for archiving is archived already: archived in the app, which sets `isArchived` in
    its record, deleted in the app, which leaves no record, or counted as archived in its session.json."""
    c = load_session(home, sid) if sid else {}
    if not c:
        return False
    return bool(c.get("archived")) or relay.archived_in_app(c)


def load_session(home, sid):
    s = read_json(os.path.join(session_dir(home, sid), "session.json")) if sid else {}
    if isinstance(s.get("backgroundGivenFor"), dict):
        s["backgroundGivenFor"].pop("", None)     # an empty key names no CLI session
    return s


def save_session(home, s):
    """session.json written from `s`, keeping what another hook wrote into it meanwhile: a sibling's Stop marks a
    session stale or queues a warning while this hook holds the copy it read at its start. The read and the write
    run under the session's lock, the one relay.warn holds, so a warning written between them is never dropped."""
    path = os.path.join(session_dir(home, s.get("sessionId")), "session.json")
    if relay._held(path):
        return _save_session(home, s)
    with relay.locked(path):
        return _save_session(home, s)


def _save_session(home, s):
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
    for k in ("othersGiven", "plansSeen", "requestAnswers"):
        if isinstance(disk.get(k), dict):
            s[k] = {**disk[k], **(s.get(k) or {})}
    for k in ("rootStep", "shard", "disposable", "doneRetired", "archived", "appRoot", "nudged", "issue",
              "issueLooked", "findingsTold", "controls", "puppeteerSeen", "handedTo",
              "handedFrom", "effort"):
        if k in disk and k not in s:
            s[k] = disk[k]
    if not s.pop("_controlsSet", None) and isinstance(disk.get("controls"), list):
        s["controls"] = disk["controls"]          # only `controls` and a puppeteer's own start change it
    if int(disk.get("anchorSeen") or 0) > int(s.get("anchorSeen") or 0):
        s["anchorSeen"] = disk["anchorSeen"]
    if str(disk.get("fileSetAt") or "") > str(s.get("fileSetAt") or ""):
        for k in ("fileSet", "fileSetAt", "fileSets"):    # `phi.py files` ran while this hook held an older copy
            if k in disk:
                s[k] = disk[k]
    moved = disk.get("spawnedFrom") if isinstance(disk.get("spawnedFrom"), dict) else {}
    mine = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
    if moved.get("source") in ("detached", "reparented", "requested") \
            and str(moved.get("time") or "") > str(mine.get("time") or ""):
        s["spawnedFrom"] = moved                  # a detach to top level or a reparent made while this hook ran
    write_atomic(os.path.join(session_dir(home, s["sessionId"]), "session.json"),
                 json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def own_clis(sid, rec, cli):
    """The transcript a hook reports, as a list, unless the app's records give it to another session, as when a
    starter's process handles its child's record; the app's record of this session itself is trusted. p4-temportal's
    archived_ids reads every id on a record, so a stray one there closes the other session's folder when this one is
    archived, ezexe/p4#191."""
    if not cli:
        return []
    if isinstance(rec, dict) and rec.get("cliSessionId") == cli:
        return [cli]
    other = record_of_cli(cli).get("sessionId")
    return [cli] if not other or safe_id(other) == sid else []


def ensure_session(home, sid, rec=None, cli="", depth=0, hint=""):
    """session.json, made if new, with those of the sessions above it made too: a session this plugin never ran in
    gets its file from the app's record. `spawnedFrom` there is what the tree is read from: the record sets it for
    a new session, for one that looked like an orchestrator before its record said otherwise, and for one read
    from the notes folder. One detached to top level or reparented is left as set."""
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
        if root and root != s.get("appRoot"):        # where relay.gone looks for an archive or a deletion later
            s["appRoot"] = root
            changed = True
        title = clean(rec.get("title"))[:120]
        if title and title != s.get("title"):      # the app titles a session after it has started
            s["title"] = title
            changed = True
        if rec.get("cwd") and rec.get("cwd") != s.get("cwd"):
            s["cwd"] = rec["cwd"]
            changed = True
    if GIVEN_TITLES.get(sid) and not s.get("title"):   # no app record titled it: the hook's session_title
        s["title"] = GIVEN_TITLES[sid]
        changed = True
    for c in own_clis(sid, rec, cli):
        if c not in s.setdefault("cliSessionIds", []):
            s["cliSessionIds"].append(c)
            changed = True
    if changed:
        save_session(home, s)
    above = spawned_from(s)
    if above and depth < CHAIN_MAX and not load_session(home, above).get("sessionId"):
        ensure_session(home, above, depth=depth + 1)
    return s


def title_of(s):
    return s.get("title") or cut(clean(s.get("task")), 60) or str(s.get("sessionId") or "")[:14]


def name_of(s, row=None):
    """A session as another session is shown it, by book.title: the app's title, else the one p4-phi holds, else
    its id, never a cut of the prompt it was sent, which title_of falls back to. `row`, a report row, gives the id
    where the session file is gone."""
    import book
    s = s if isinstance(s, dict) else {}
    sid = str(s.get("sessionId") or (row or {}).get("sessionId") or "")
    return book.title(sid, s) or "a session"


def chain_of(home, sid):
    """The sessionIds above a session, nearest first: its parent session, that session's parent, and so on."""
    out, cur = [], spawned_from(load_session(home, sid))
    while cur and cur not in out and len(out) < CHAIN_MAX:
        out.append(cur)
        cur = spawned_from(load_session(home, cur))
    return out


def load_turns(home, sid):
    """A session's turns, oldest first, each turn once, as it last finished."""
    by = {}
    for r in read_rows(os.path.join(session_dir(home, sid), "turns.jsonl")):
        if r.get("id"):
            by[r["id"]] = r
    return list(by.values())


def load_notes(home, sid):
    return read_rows(os.path.join(session_dir(home, sid), "notes.jsonl"))


def load_reports(home, sid, tail=None):
    return read_rows(reports_path(home, sid), tail)


USAGE_FILE = "usage.json"        # in a session's folder: what Claude Code measured of it, written by hooks/register.ts


def usage_of(home, sid):
    """What Claude Code last measured of a session's usage, read from usage.json in the session's folder. The
    plugin's hooks module writes that file at the session's start and at every whole point a figure moves, from
    `$.session.usage()`, whose `context` "has `tokens`, `window`, and `percent`" and whose `rateLimits` "is a list of
    `{ kind, percentUsed, resetsAt }`", https://code.claude.com/docs/en/plugins/mods/reference.md.
    Returns {} where there is no record to read: no hooks module ran for the session, or the file holds no context
    window. Else a dict of three keys:
      `at`          when the record was written, in seconds since the epoch;
      `context`     `tokens`, the input tokens the last response was answered over, `window`, the model's context
                    window in tokens, and `percent`, tokens over window as a whole percentage. `tokens` and `percent`
                    are None until the first response of the live window, at a session's start and after a
                    compaction;
      `rateLimits`  a list, empty off a subscription, each entry with `kind`, such as five_hour or seven_day,
                    `percentUsed`, 0 to 100 with one decimal at most, and `resetsAt`, an ISO 8601 time, or '' where
                    Claude Code gave none.
    The module's write is not atomic, so a file that does not parse is read once more."""
    if not sid:
        return {}
    path = os.path.join(session_dir(home, sid), USAGE_FILE)
    d = read_json(path)
    if not d and os.path.exists(path):
        time.sleep(0.02)
        d = read_json(path)

    def number(v):
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    window = number(ctx.get("window"))
    if not window or window <= 0:
        return {}
    limits = []
    for r in d.get("rateLimits") if isinstance(d.get("rateLimits"), list) else []:
        if isinstance(r, dict) and isinstance(r.get("kind"), str) and number(r.get("percentUsed")) is not None:
            limits.append({"kind": r["kind"], "percentUsed": float(r["percentUsed"]),
                           "resetsAt": r["resetsAt"] if isinstance(r.get("resetsAt"), str) else ""})
    return {"at": (number(d.get("at")) or 0) / 1000.0,
            "context": {"tokens": number(ctx.get("tokens")), "window": int(window),
                        "percent": number(ctx.get("percent"))},
            "rateLimits": limits}


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
    """The request inside a message. A worker gets its task under leading <system-reminder> blocks and a
    `Background ... Task:` wrapper, and a forked one under the app's line `Task (from the session that started this
    one):`; this takes those off. A `<pasted_content id="..">` block is what a person pasted, so its inner text is
    the request, also when the message is nothing but the block. '' when nothing is left or what is left is Claude
    Code speaking."""
    text = prompt if isinstance(prompt, str) else ""
    while REMINDER.match(text):
        text = REMINDER.sub("", text, count=1)
    m = TASK_MARK.search(text)
    if m and text.lstrip().startswith("Background"):
        text = text[m.end():]
    text = FORK_HEAD.sub("", text, count=1)
    text = NOTES_TAIL.sub("", text).strip()
    if text.startswith("<") and not PASTED.match(text):
        return ""                                  # Claude Code speaking, whatever its body quotes
    # A paste is the person's message whatever it holds, but only where the message itself begins with the block or
    # with their own words: a notification or another session's message that quotes a pasted block stays Claude Code's.
    return PASTED.sub(lambda m: m.group(1), text).strip()


def handed_over(prompt):
    """Does a message look like a task another session handed over: the wrapper, the linked-sessions reminder, or
    the shared notes folder. Such a session is a worker, whether or not the app has recorded it yet."""
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


def read_transcript(path, tail=None):
    """A transcript's lines as objects; of a very long one, its last TRANSCRIPT_BYTES, or its last `tail` bytes."""
    return read_rows(path, tail or TRANSCRIPT_BYTES) if path and os.path.exists(path) else []


def read_from(path, start, partial=False):
    """The lines of a .jsonl file from byte `start`. Returns each line as the byte it starts at and the line as an
    object, and the byte past the last whole line. A last line with no newline yet is still being written and is
    left for the next read; with `partial`, `start` may fall inside a line, which is skipped."""
    try:
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read()
    except OSError:
        return [], start
    out, pos = [], start
    pieces = data.split(b"\n")[:-1]
    for k, raw in enumerate(pieces):
        at, pos = pos, pos + len(raw) + 1
        if partial and k == 0:
            continue
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append((at, d))
    return out, pos


TURN_WINDOWS = (512 * 1024, 2 * 1024 * 1024)     # a turn is looked for in the transcript's end first, then further back


def last_turn(path):
    """The transcript's last turn whoever asked for it: the last message that carries a request, and every tool
    call after it. A message from Claude Code, such as a session's report delivered or a notification, opens no turn.
    The last request is nearly always near the end, so the end is parsed first and the megabytes before it only when
    no request lies there: the turn found is the same, since it starts at the last line that carries one."""
    try:
        size = os.path.getsize(path) if path else 0
    except OSError:
        size = 0
    for window in TURN_WINDOWS:
        if window < min(size, TRANSCRIPT_BYTES):
            cur = turn_in(read_transcript(path, window))
            if cur is not None:
                return cur
    return turn_in(read_transcript(path))


def turn_in(rows):
    """The last turn among a transcript's lines, None when no line carries a request."""
    cur, calls = None, {}
    for d in rows:
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
    steps, failed, offered, ask = [], [], [], ""

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
        elif name == "mcp__ccd_turn__wrap_up" and clean(inp.get("ask")):
            # the question put to ezexe and its reply buttons, whose label the app sends back as ezexe's message, so
            # each is kept whole; a question with no reply button waits on typed text
            ask = cut(clean(inp.get("ask")), 300)
            offered = [clean(a.get("label")) for a in inp.get("actions") or []
                       if isinstance(a, dict) and clean(a.get("label")) and not a.get("action")]
    prompt = cut(turn.get("prompt") or "", TASK_CHARS)
    uuid = turn.get("uuid") or ""
    row = {"id": uuid or "turn-" + hashlib.sha1(prompt.encode("utf-8", "replace")).hexdigest()[:12],
           "prompt": prompt, "steps": steps[:TURN_STEPS], "failed": failed[:4],
           "report": (report or "").strip()[:REPORT_CHARS], "done": ""}
    if ask:
        row.update(ask=ask, offered=offered[:6])
    return row


def said_of(turn, report):
    """Every message the turn wrote, joined and cut from the front to REPORT_CHARS, for a turn whose findings came in
    a message before its last, which may say no more than that the work is done. '' when the last message is all
    the turn wrote."""
    texts = [t for t in turn.get("texts") or [] if isinstance(t, str) and t.strip()]
    if not texts or (len(texts) == 1 and texts[0].strip() == (report or "").strip()):
        return ""
    whole = "\n\n".join(texts)
    if whole.strip() == (report or "").strip():
        return ""
    return whole[-REPORT_CHARS:]


# --- what a session is given -----------------------------------------------------------------------------------------

def turn_lines(title, t, report=300, prompt=0):
    """A turn as lines: its session's title, whether it was shown done, its steps, workers, failures and report. Its
    prompt, cut to `prompt` characters, only where the reader is the session it was sent to: no session is handed
    a run of the words of a prompt sent to another."""
    how = "done: " + cut(clean(t["done"]), 160) if t.get("done") else "not shown done"
    said = f": {cut(clean(t.get('prompt')), prompt)}" if prompt and t.get("prompt") else ""
    out = [f"- \"{title}\", {how}, {t.get('time', '')}{said}"]
    if t.get("steps"):
        out.append("  steps: " + cut("; ".join(t["steps"]), 400))
    if t.get("sessions"):
        out.append("  workers: " + cut("; ".join(t["sessions"]), 300))
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
    """The start background a session is given: the sessions above it by title, their notes, the last turn of
    each of its siblings, which for an orchestrator are the orchestrators before it, and with `own` its own
    turns, as after a clear, which keeps nothing of them. With `slim` the notes and the siblings' turns are left out,
    for a fresh child whose slice of its parent's anchor holds what bears on its paths, and for a background first
    given after a compaction. '' when none of that exists. It quotes no prompt
    of another session: a task above is named by its session's title, a sibling's turn by its steps and report, and
    the brief this session was handed says what it is to do."""
    sid, above = s["sessionId"], spawned_from(s)
    chain = [load_session(home, x) for x in chain_of(home, sid)]
    body = []
    if chain:
        body += ["The sessions above this one, nearest first, by title; this session's task is part of the "
                 "first's: " + ", ".join(f"\"{name_of(n)}\"" for n in chain) + "."]
    own_task = clean(s.get("task"))
    notes = []
    for n in chain:
        for r in load_notes(home, n["sessionId"]):
            kind = f"{r['kind']}; " if r.get("kind") else ""
            room = relay.FINDINGS_CHARS + 2000 if clean(r.get("claim")).startswith("replaces:") else 300
            notes.append(f"- {cut(clean(r.get('claim')), room)}; {kind}source: {cut(clean(r.get('source')), 120)}")
    notes = [] if slim else nd.by_overlap(notes, own_task)   # nearest the task first; a fresh child gets its slice
    if notes:
        body += ["Notes of the sessions above, already checked, so do not work these out again:"] + notes[:12]
    others = [r for r in latest_reports(load_reports(home, above, TAIL_BYTES), skip=sid)[:OTHERS * 3]
              if spawned_from(load_session(home, r["sessionId"])) == above
              and not relay.gone(home, load_session(home, r["sessionId"]))][:OTHERS]
    others = [] if slim else nd.by_overlap(others, own_task,
                                           key=lambda r: f"{r.get('title', '')} {r.get('turn', {}).get('prompt', '')}")
    if others:
        who = f"the other workers of \"{name_of(chain[0])}\"" if chain else \
            "the orchestrators in this project before this one"
        body += [f"The last turn of {who}:"]
        for r in others:
            body += turn_lines(name_of(load_session(home, r["sessionId"]), r), r["turn"])
    if own:
        mine = load_turns(home, sid)[-OWN:]
        if mine:
            body += ["This session's own turns so far:"]
            for t in reversed(mine):
                body += turn_lines(title_of(s), t, prompt=200)     # its own prompts, sent to it
    if not body:
        return ""
    if chain:
        head = (f"phi (p4-phi): background for this session, \"{title_of(s)}\", from its parent session, "
                f"\"{name_of(chain[0])}\", and the sessions linked to it. Use what is here where it fits; do not "
                f"work it out again.")
    else:
        head = ("phi (p4-phi): background for this session from the sessions in this project before it. Use what "
                "is here where it fits; do not work it out again.")
    tail = (f"The page this comes from: {page_path(home, above)}. Keep a finding the next session would have to "
            f"work out again: `{commands()} note \"<claim>\" --source \"<the file and line it was checked at>\"`. When something "
            f"shows the task done: `{commands()} done \"<what was run and what it showed>\"`. Each turn's report "
            f"is kept either way" + (" and reaches the parent session beside its next message." if chain else "."))
    room = BACKGROUND_CHARS - len(head) - len(tail) - 2
    text = "\n".join(body)
    if len(text) > room:
        text = text[:max(0, room - 4)].rsplit("\n", 1)[0] + "\n..."
    return "\n".join((head, text, tail))[:BACKGROUND_CHARS]


def findings_text(home, s, new, store=""):
    """The line under the reports of a session's workers that carry `Finding:` lines, '' when none does. A
    worker passes them up unchanged in its own report; an orchestrator that a puppeteer controls
    leaves them to that puppeteer, whose board lists them; any other orchestrator publishes and places
    them itself. A finding on a file or an issue another live session holds goes straight to that session, named
    beside it by the address book, book.py; only the rest go up for an issue."""
    import book
    found, held, own, bk = [], [], [], {}
    for r in reversed(new):
        t = r.get("turn") if isinstance(r.get("turn"), dict) else {}
        by = str(r.get("sessionId") or "")
        for line in issues.findings(f"{t.get('report') or ''}\n{t.get('said') or ''}"):
            if line in found or line in own or any(line == h[0] for h in held):
                continue
            try:                                   # the reporter and those above it hold nothing it found
                if "all" not in bk:
                    bk["all"] = book.entries(home, s["sessionId"], store)
                tree = book.tree_issue(home, s, line, by, store, bk["all"]) if by else ""
                who = (f"\"{book.title(tree)}\" `{tree}`, the orchestrator of the tree whose issue it names"
                       if tree else book.holder_line(home, s, line, store,
                                                     skip=[by, *chain_of(home, by)] if by else (), book=bk["all"]))
            except Exception:  # noqa: BLE001
                tree = who = ""
            if tree and tree == s["sessionId"]:
                own.append(line)                   # the issue this session's tree holds: its own to place
            elif who:
                held.append((line, who))
            else:
                found.append(line)
    mine = ("phi (p4-phi): these reports carry `Finding:` lines on the issue this session's tree already holds, so "
            "this session places each in its own tree and no new issue is published for it:\n"
            + "\n".join(f"- {cut(x, 400)}" for x in own[:FINDINGS_SHOWN])) if own else ""
    if not found and not held:
        return mine
    straight = ("phi (p4-phi): these reports carry `Finding:` lines on a file or an issue a live session holds. "
                "Send each one straight to the session named under it with SendMessage, and nowhere else; it "
                "goes up for no issue:\n" + "\n".join(f"- {cut(x, 400)}\n  to {who}" for x, who in
                                                     held[:FINDINGS_SHOWN])
                + (f"\n- and {len(held) - FINDINGS_SHOWN} more, each whole in its session's report"
                   if len(held) > FINDINGS_SHOWN else "")) if held else ""
    if not found:
        return "\n\n".join(x for x in (mine, straight) if x)
    n = len(found)
    head = f"phi (p4-phi): these reports carry {n} `Finding:` line{'s' if n != 1 else ''} no live session holds"
    listed = "\n".join(f"- {cut(x, 400)}" for x in found[:FINDINGS_SHOWN]) + (
        f"\n- and {n - FINDINGS_SHOWN} more, each whole in its session's report" if n > FINDINGS_SHOWN else "")
    if spawned_from(s):
        rest = (f"{head}. Pass each one up unchanged in this session's own report, and publish no issue for it:\n"
                + listed)
    elif controls.puppeteer_of(s, store)[0]:
        pid = controls.puppeteer_of(s, store)[0]
        rest = (f"{head}. They go up to the puppeteer \"{controls.full_title(pid)}\" `{pid}`, whose board "
                f"lists them, and it publishes the issues they need and places the session that resolves each: this "
                f"session publishes none.")
    else:
        rest = (f"{head}, and no puppeteer controls this session tree, so the findings in them are this "
                f"session's to publish and place. Check each against the open issues and the running sessions, and "
                f"send one a running session covers to that session; for the rest, publish the issue and place the "
                f"session that resolves it, as a child of the session in this tree that holds its files or as a new "
                f"orchestrator:\n" + listed)
    return "\n\n".join(x for x in (mine, straight, rest) if x)


def reports_text(home, s, room=None, store=""):
    """The reports of this session's workers that finished a turn since it last looked, and how many rows
    that covers. Each report is shown as kept, up to REPORT_CHARS, where it fits in `room`, and cut with ... where
    it does not; the ones there is no room for at all are named by count with their pages. The `Finding:` lines they
    carry come last, with what becomes of them, as findings_text says."""
    rows = load_reports(home, s["sessionId"])
    seen = s.get("reportsSeen") if isinstance(s.get("reportsSeen"), int) else 0
    new = latest_reports(rows[seen:])
    if not new:
        return "", len(rows)
    room = REPORTS_CHARS if room is None else min(REPORTS_CHARS, room)
    found = findings_text(home, s, new, store)
    room -= (len(found) + 1) if found else 0
    out = ["phi (p4-phi): reports of this session's workers that finished a turn since it last looked, each "
           "as kept or cut with ... where room runs short, with its page named under it. Name each session to "
           "ezexe by its whole title as a link, [its whole title](#its session id), as the sidebar lists it."]
    shown = list(reversed(new))[:max(1, (room - len(out[0])) // 700)]
    rest = [r for r in reversed(new) if r not in shown]
    each = max(500, (room - len(out[0]) - 110 * len(rest)) // len(shown) - 140)
    for r in shown:
        lines = turn_lines(name_of(load_session(home, r["sessionId"]), r), r["turn"], report=REPORT_CHARS)
        out += [cut("\n".join(lines), each), f"  its page: {page_path(home, r['sessionId'])}"]
    if rest:
        out.append(f"Not shown here for want of room, {len(rest)} more, each on its page: " + ", ".join(
            f"\"{r.get('title') or r['sessionId']}\" {page_path(home, r['sessionId'])}"
            for r in rest[:6]) + (f", and {len(rest) - 6} more listed on {page_path(home, s['sessionId'])}"
                                  if len(rest) > 6 else "") + ".")
    if found:
        out.append(found)
    return "\n".join(out), len(rows)


# --- a session's write set, narrowed or released ---------------------------------------------------------------------

def set_files(home, s, paths, base):
    """Replace a session's declared write set. Returns the new set and what it released. The set before it is kept
    on the record, and the start guard reads the new one at once, since it reads each record as it runs."""
    new = []
    for p in paths:
        name = str(p or "").strip().strip("`'\"").rstrip(".")
        if not name:
            continue
        entry = relay.norm(name, base) if re.search(r"[\\/]", name) else name.lower()
        if entry not in new:
            new.append(entry)
    old = [x for x in s.get("fileSet") or [] if isinstance(x, str)] if isinstance(s.get("fileSet"), list) else []
    if isinstance(s.get("fileSet"), list):
        kept = [x for x in s.get("fileSets") or [] if isinstance(x, dict)]
        s["fileSets"] = (kept + [{"files": old, "until": now()}])[-20:]
    s["fileSet"], s["fileSetAt"] = new, now_exact()
    s.pop("filesHeldTold", None)
    save_session(home, s)
    return new, [x for x in old if x not in new]


def now_exact():
    """A time that orders two writes of one minute."""
    return time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def files_held_text(home, s, closing=None, pushed=None):
    """The line a session is given once when its issue-closing commit is on a remote branch and it still holds
    files: the files, and the command that releases them. '' otherwise. The caller saves the record."""
    files = [x for x in s.get("fileSet") or [] if isinstance(x, str)] if isinstance(s.get("fileSet"), list) else []
    if not files:
        return ""
    try:
        closing = relay.closing_commits(home, s["sessionId"], s) if closing is None else closing
        pushed = pushed or issues._pushed
        done = [(sha, closes) for path, sha, _, closes in closing if pushed(path, sha)]
    except Exception:  # noqa: BLE001
        return ""
    key = ",".join(sha for sha, _ in done)
    if not done or s.get("filesHeldTold") == key:
        return ""
    s["filesHeldTold"] = key
    sha, closes = done[-1]
    base = s.get("cwd") or ""
    shown = ", ".join(f"`{relay.show(f, base) if '/' in f else f}`" for f in files[:8]) + (
        f" and {len(files) - 8} more" if len(files) > 8 else "")
    return (f"phi (p4-phi): this session's commit {sha}, which closes #{', #'.join(closes)}, is on a remote branch, "
            f"and it still holds {len(files)} file{'s' if len(files) != 1 else ''}: {shown}. No other session can "
            f"be started on them until this one reports done. If its work on them is landed, release them with "
            f"`{commands()} files --release`, or keep only what it still writes with `{commands()} files <path> ...`.")


MAX_DEPTH = 3                 # a session this deep in the tree starts no session of its own
MAX_CHILDREN = 8              # nor one that has this many live children already
# The act-don't-wait rule. How a question to ezexe is laid out is the app's own text, so the rule names the tools and
# holds no sentence on it:
# - tools-reference.md, "AskUserQuestion tool behavior": "Claude uses `AskUserQuestion` to ask you multiple-choice
#   questions when it needs a decision or a clarification."
# - the desktop app's turn-end tool, `mcp__ccd_turn__wrap_up`, whose own text puts a decision that waits on ezexe as
#   one question with buttons, the pick first.
# Every other sentence stays. Some are what that text lacks: the decisions file, the session tree as what settles a
# next step, the push of green issue-closing commits, a child's question to its parent session, the go a project's
# rules ask for, and a worker's closing line to a starter that waits on it, which works around the limit
# claude_code_limits.json logs under ezexe/p4#157. The rest only the desktop app's text states, and no docs page
# does for a session in its default style, so a session outside the app would lose it: that a question research can
# settle is not asked, and that only a matter of ezexe's authority is. output-styles.md states the like for the
# Proactive style alone, "It makes reasonable assumptions about routine decisions rather than stopping to ask", and
# that style is ezexe's to choose.
DECISIONS = "its decisions file, the one its brief names or decisions.md in the scratchpad directory the app names"
DECIDE = ("A question that the code, the history, the issues or the current outside documentation can answer is "
          f"researched and decided by this session, which logs the decision with its source in {DECISIONS}; a "
          "question reaches ezexe only once those cannot settle it.")
BUILT_IN = ("built-in, act-don't-wait: " + DECIDE + " A next step that the task, the parent's task list and notes, "
            "siblings' work and the project's rules can settle is decided and done, with one line saying what was "
            "chosen and why. "
            "Only a matter of ezexe's authority goes to ezexe, by the app's own `mcp__ccd_turn__wrap_up` or "
            "`AskUserQuestion`: permissions or security settings, credentials, spending, and actions that cannot be "
            "undone or publish outward, but for the push of green issue-closing commits, which p4-phi orders at "
            "once. A child asks its parent "
            "session with SendMessage, and never ends its turn waiting on a question the session tree can settle. "
            "A worker whose starter waits on it ends each turn with one SendMessage line to the starter, since a "
            "report reaches an idle session only beside its next message. "
            "Where the project's rules ask for ezexe's go before a kind of step, such as a plan's edits, that go is "
            "ezexe's to give, by a button: wait for it on those steps, and act on the rest.")
ACT_DONT_WAIT = True          # p4.json phi.act_dont_wait: false leaves this built-in rule out of a project
# The delegation rule. Each mechanism it names is Claude Code's own, as the docs say:
# - sub-agents.md, "Run subagents in foreground or background": "Foreground subagents block the main conversation
#   until complete." and "Background subagents run concurrently while you continue working."; in its frontmatter
#   table, `background`: "Set to `true` to keep this subagent in the background even when Claude asks to wait for it."
# - The rule says nothing of waiting, sleeping or polling: the Agent tool's and the shell tools' own descriptions
#   tell a session that a background subagent or command notifies it when it ends, and sub-agents.md says "A
#   background subagent's results reach Claude as a completion notification in a later turn."
# - sub-agents.md, "Built-in subagents", Explore: "A fast, read-only agent optimized for searching and analyzing
#   codebases." Its model is "the parent conversation's model", so the rule names a small one on the call: "The
#   per-invocation `model` parameter" is first in the page's model order, and "On an Agent tool call, the parameter
#   takes a model alias, not a full model ID or `inherit`."
# - code-review-local.md: "`/code-review` is a bundled skill", "Claude can start `/code-review` on its own, without
#   you typing the command", "In a terminal session, the review runs as a background subagent with its own context
#   window", and "without `--fix`, the review's instructions ask Claude for a report only." The page calls that run
#   "a forked subagent", of which skills.md, "Run skills in a subagent", says "The subagent doesn't see your
#   conversation history". So a code change is reviewed by that skill. Its target "can be a pull request number, a
#   branch name, a file path, or a Git revision range", so a result that is no code change has none, and the page's
#   route past the skill is "Build your own reviewer: write a reviewer subagent or a review skill": that is
#   agents/check.md.
# - plugins/components.md, "Agents": "The name form is `<plugin>:<name>`", so agents/check.md is `p4-phi:check`.
# - The read of the plan limits is the app's own tool, `mcp__ccd_session_mgmt__get_usage`, which plans.LIMITS_FIRST
#   names: a command hook calls no session tool, so the rule asks the session for the read.
# - tools-reference.md, "Background commands": "Claude can set `run_in_background: true` to start the command as a
#   background task and continue working while it runs." interactive-mode.md, "How backgrounding works": "Output is
#   written to a file and Claude can retrieve it using the Read tool". So a long command needs no agent to run it.
# - tools-reference.md, "Foreground commands that move to the background": "When a foreground command reaches its
#   timeout without finishing, Claude Code moves it to the background instead of stopping it, unless the command
#   starts with `sleep`." The default is `BASH_DEFAULT_TIMEOUT_MS`, "two minutes out of the box".
REVIEW = ("the bundled skill `code-review`, run with the Skill tool on that change's commits or paths and without "
          "`--fix`, so it reports and changes no file")
# workflows.md, "Cost": "Claude Code picks each workflow agent's model in the same order it uses for subagents. A
# model the script names for a stage counts as the per-invocation model in that order. When nothing else assigns one,
# the agent runs on your session's model." No line of that page gives a workflow agent an effort of its own.
WORKFLOW = ("A Workflow script names a model for each stage, since by the workflows page of the Claude Code docs \"A "
            "model the script names for a stage counts as the per-invocation model\" and an agent with none \"runs "
            "on your session's model\".")
LEVELS = ("built-in, levels: work is delegated to where Claude Code runs it best, so this session's own turn is "
          "never held by it. A search or a read across more than a couple of files goes to " + plans.EXPLORE + "; "
          "a command expected to run long, such as a test file, a test suite or a build, goes to " + plans.BACKGROUND
          + "; a review of a code change that should not lean on this session's own view goes to " + REVIEW + "; "
          "such a read of a result that is no code change goes to the subagent `p4-phi:check`. "
          + plans.LIMITS_FIRST + " A worker is "
          "started with a `model` and an `effort` that fit its step, as the advice that hands out each start call "
          "names them; an effort above this session's own is not accepted. " + WORKFLOW)
plans.BUILT_INS = tuple(x.split(": ", 1)[0].replace("built-in, ", "") for x in (BUILT_IN, LEVELS))   # plans.py's names
LEVELS_ON = True              # p4.json phi.levels: false leaves the delegation rule and its checks out
TOP_ORCHESTRATES = True       # p4.json phi.top_orchestrates: false keeps an orchestrator's work in it
FILE_SETS = True              # p4.json phi.file_sets: false starts sessions whose briefs declare no write set


def project_conf(store):
    """The project's own keys of p4.json's `phi` section, read from the store where the session runs, not from a
    shared store, each with its P4_* variable ahead of it, by p4conf.load."""
    global ACT_DONT_WAIT, TOP_ORCHESTRATES, FILE_SETS, LEVELS_ON
    try:
        d = p4conf.section(store, "phi", write=False) if store else {}
    except Exception:  # noqa: BLE001
        d = {}
    if not isinstance(d, dict):                    # a `phi` that is no section sets every key back to its default
        d = {}
    ACT_DONT_WAIT = d.get("act_dont_wait") is not False
    TOP_ORCHESTRATES = d.get("top_orchestrates") is not False
    FILE_SETS = d.get("file_sets") is not False
    LEVELS_ON = d.get("levels") is not False
    plans.LEVELS = LEVELS_ON
    plans.CHILD_LEVELS = plans.child_levels(d.get("child_levels"))   # one key sets each kind's model and effort
    apply_caps(d)


# The caps a project sets in p4.json's `phi` section: each key, the module and constant it sets, and the least and most
# value it takes.
CAPS = {"max_depth": ("phi", "MAX_DEPTH", 1, 20), "max_children": ("phi", "MAX_CHILDREN", 1, 50),
        "sibling_turns": ("phi", "OTHERS", 0, 50), "own_turns": ("phi", "OWN", 0, 50),
        "chain_max": ("phi", "CHAIN_MAX", 1, 50), "turn_steps": ("phi", "TURN_STEPS", 1, 100),
        "tree_checks": ("phi", "TREE_CHECKS", 0, 100),
        "keep_going_max": ("plans", "KEEP_GOING_MAX", 0, 7),       # under hooks.md's 8 consecutive continuations
        "watch_s": ("puppeteer", "WATCH_S", 1.0, 600.0), "stale_s": ("puppeteer", "STALE_S", 60.0, 30 * 86400.0)}
# Each cap's default is the one p4conf.py declares for the key, not whatever the constant holds when apply_caps first
# runs, which a caller may have set.
CAP_DEFAULTS = {k: p4conf.DEFAULTS["phi"][k] for k in CAPS}


def apply_caps(d):
    """Sets each cap from the `phi` section `d`, or back to its default where `d` holds no fitting value, one of the
    wrong type or out of range, whether p4.json or a P4_* variable gave it: a hook run in process keeps module
    globals, so a store that sets none gets the defaults again."""
    mods = {"phi": sys.modules[__name__], "plans": plans, "puppeteer": puppeteer}
    for key, (mod, name, least, most) in CAPS.items():
        default = CAP_DEFAULTS[key]
        v = d.get(key, default) if isinstance(d, dict) else default
        ok = setting_fits(v, default) and least <= v <= most
        setattr(mods[mod], name, type(default)(v) if ok else default)


NEW_TOP = re.compile(r"\b(?:this|it) (?:session )?is a new top session\b", re.I)
NEW_TOP_BRIEF = "This session is a new top session, orchestrating its own topic."
RESTATE = ("the task restated as your own instruction to the session that receives it: what it is to do and why, "
           "from its side, a line `Files: <paths>` and what done looks like, with no message quoted and nothing "
           "of who asked or how the request travelled")


def new_top_first_act():
    """What a new orchestrator does first: detach to top level from its parent session in the app, then in
    p4-phi."""
    return (f"Its first act: `mcp__ccd_session_mgmt__detach_session` with `\"self\"`, so the app stops nesting it and "
            f"its reports stop going to its parent session, then `{commands()} detach`.")


ASK_ROUTE = ""                # set for a controlled session, which starts no new orchestrator itself


def asks(s):
    """Kept for this hook's run: how a controlled session gets a new orchestrator from its
    puppeteer."""
    globals()["ASK_ROUTE"] = controls.ask_route(s) if isinstance(s, dict) and not spawned_from(s) else ""


def new_top_route(owner_turn=True):
    """How an orchestrator starts a new orchestrator for a topic outside its task: what the start tool's own text
    lacks, the write set on the brief's `Files:` line and the two moves that detach the session to top level. In a
    turn ezexe did not begin it names no `initiation`: what such a turn may start, and the card it proposes, are that
    tool's own text."""
    if ASK_ROUTE:
        return ASK_ROUTE
    how = ("Start it with `mcp__ccd_session__start_session`, `initiation` `user_asked`" if owner_turn else
           "Give it to `mcp__ccd_session__start_session`")
    return (f"{how}, `context` `fresh`, `use_worktree: false`, with the `model` and `effort` its kind of work gets, "
            f"said in one line of the brief; its brief: {RESTATE}, and "
            f"the lines \"{NEW_TOP_BRIEF} {new_top_first_act()}\" Both moves are needed: the app's detach to top "
            f"level, else it stays nested under this session and reports here, and p4-phi's, which p4-phi also makes "
            f"at the new session's first hook on that line. If it is still nested under this session at its first "
            f"report, call `mcp__ccd_session_mgmt__detach_session` with its id yourself. Orchestrators are "
            f"siblings, so each is told what the others change.")


def depth_of(home, s):
    """How many sessions lie above this one: 0 for an orchestrator."""
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
        return (f"This session is {depth} deep in the session tree, the most p4-phi allows: start no session; do the "
                f"work here, or send it to your parent session with SendMessage.")
    kids = len(plans._children(home, s["sessionId"]))
    if kids >= MAX_CHILDREN:
        return (f"This session has {kids} live sessions of its own, the most p4-phi allows: start no session; send "
                f"the work to the one whose task it fits with SendMessage.")
    return ""


FIRST_SPLIT = ("phi (p4-phi): this is this session's first message. In these sessions the app has let a started "
               "session start others in its first turn and in the turns ezexe's own messages open, though no doc "
               "states it. Plan its split now, before other work: every part of its task that writes files or makes a "
               "decision gets a session of its own, one per disjoint set of files, started in this turn with "
               "`mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, `use_worktree: false`, "
               "each brief holding its `Files:` line; where the app refuses that start, the part is shown as a "
               "suggested task card, the start tool's `initiation` `own_initiative`, which ezexe presses in this "
               "session. Subagents keep reads, "
               "searches, single command runs and independent checks, which return a result and hold no files. A "
               "part that writes files and comes up after this turn is shown as a suggested task card, the start "
               "tool's `initiation` `own_initiative`, which ezexe presses in this session. It never runs in a "
               "subagent. A task that is one part with one set of files stays here whole.")


RESEARCH = ("Before it creates anything new, such as a module, a page, a format or a kind of test, this session finds "
            "the documented terms for what it creates, from Anthropic's docs, the platform's docs or the field's "
            "published sources, and a published implementation guide for that kind of work. It logs both, each with "
            f"its source, in {DECISIONS}, "
            "and builds by them. A name only this project uses stays only where no published source names the thing, "
            "and the decisions file says where it looked.")
RESEARCH_STEP_HEAD = ("phi (p4-phi): this task list creates something new with no step before it that finds the "
                      "documented terms and an implementation guide:")
CREATES = re.compile(r"^\W*(?:create|add|build|write|make|scaffold|introduce|design)\b[^.;]*?\b(?:modules?|plugins?|"
                     r"skills?|pages?|formats?|hooks?|commands?|subcommands?|class(?:es)?|scripts?|schemas?|agents?)\b",
                     re.I)
RESEARCHES = re.compile(r"\b(?:find|research|look\s+up|read|survey)\b[^.;]*\b(?:terms?|names?|guides?|docs|"
                        r"documentation)\b", re.I)


def research_text(home, s):
    """A writing worker's or coworker's first message: the line to find the documented terms and an
    implementation guide before it creates anything. '' for an orchestrator, a later message, and a session that
    writes nothing."""
    if not spawned_from(s) or not clean(s.get("task")) or load_turns(home, s["sessionId"]):
        return ""
    files = s.get("fileSet")
    if not (files if isinstance(files, list) else issues.writing(s.get("task"))):
        return ""
    RAN["research"] = True
    return "phi (p4-phi): " + RESEARCH


def research_step_text(home, s, plan):
    """The line for a task list whose first step that creates something has no research step before it, said once
    for that step; '' otherwise."""
    steps = [st for st in plan.get("steps") or [] if st.get("status") != "completed"]
    at = next((k for k, st in enumerate(steps) if CREATES.search(str(st.get("content") or ""))), None)
    if at is None or any(RESEARCHES.search(str(st.get("content") or "")) for st in steps[:at]):
        return ""
    st = steps[at]
    path = os.path.join(session_dir(home, s["sessionId"]), "session.json")
    disk = read_json(path)
    told = [x for x in disk.get("researchAdvised") or [] if isinstance(x, str)]
    if st.get("content") in told:
        return ""
    disk["researchAdvised"] = s["researchAdvised"] = told + [st.get("content", "")]
    write_atomic(path, json.dumps(disk, indent=1, ensure_ascii=False))
    RAN["research_step"] = st.get("addr")
    return (f"{RESEARCH_STEP_HEAD} step {st.get('addr')} \"{cut(clean(st.get('content')), 120)}\". Put a step before "
            f"it that does so. {RESEARCH}")


def first_split_text(home, s):
    """A worker's or a coworker's first message: the line to plan its split while the app still lets it start
    sessions. '' for an orchestrator, a later message, a session with no task, and one a cap holds."""
    if not LEVELS_ON or not spawned_from(s) or not clean(s.get("task")) or load_turns(home, s["sessionId"]):
        return ""
    if caps_text(home, s):
        return ""
    RAN["first_split"] = True
    return FIRST_SPLIT


def split_text(home, s, prompt):
    """A turn another session's message started. What such a turn may start, and the card it proposes, are the start
    tool's own text, so this line holds only what that text lacks: the caps, the write set a brief declares, and
    for an orchestrator the brief line that detaches a new orchestrator to top level. It is short and keeps no
    state, so every such turn carries it whole. '' for ezexe's own turns, the app's events and a session with no
    task."""
    if not clean(s.get("task")) or not re.search(r"<cross-session-message\b", str(prompt or "")):
        return ""
    cap = caps_text(home, s)
    RAN["split"] = "cap" if cap else "brief"
    return "phi (p4-phi): " + cap if cap else _split_full(home, s)


def _split_full(home, s):
    """What a brief written in a turn another session began holds beyond what the start tool asks of it: a
    child's, its `Files:` line and its level line; a new orchestrator's, those and the line on which it is detached
    to top level, or for a controlled orchestrator the request to its puppeteer."""
    if spawned_from(s):
        return ("phi (p4-phi): a task of its own in this turn, outside this session's task, goes out by "
                "`mcp__ccd_session__start_session` with a brief that declares its write set on a line "
                f"`Files: <paths>`. {plans.LEVEL_CARD}")
    head = "phi (p4-phi): a topic in this turn outside this orchestrator's task gets a new orchestrator of its own. "
    if ASK_ROUTE:
        ask = PHI_LEAD.sub("", controls.ask_text(s))
        return head + ask[:1].upper() + ask[1:]
    return (head + "It goes out by `mcp__ccd_session__start_session`, `context` `fresh`, `use_worktree: false`, "
            "with the `model` and `effort` its kind of work gets, said in one line of its brief, which declares "
            f"its write set on a line `Files: <paths>` and carries the line \"{NEW_TOP_BRIEF}\": on that line "
            "p4-phi detaches it to top level at its first message and has it call "
            "`mcp__ccd_session_mgmt__detach_session` with `\"self\"`, so the app stops nesting it under this "
            "session.")


FEATURE_STEP = re.compile(r"\bnew feature\b|^\W*(?:build|implement|design|introduce)\b[^.;]*\b(?:feature|loop|"
                          r"lifecycle|mode|command|system|plugin|workflow)\b", re.I)


def book_text(home, s, store, whole=False, named=False):
    """The address book beside a message, as book.line gives it: whole after a clear, since the session keeps none
    of it, else the entries that changed since it last looked. With `named`, after a compaction, whose summary keeps
    the conversation and no exact id or path, the page's path comes even when no entry changed. '' with no task."""
    if not BOOK or not clean(s.get("task")):
        return ""
    import book                                    # the address book: who holds each file, issue and piece of work
    try:
        return book.line(home, s, store, whole=whole, named=named)
    except Exception:  # noqa: BLE001  a book it cannot write never costs the message its other lines
        return ""


def feature_steps_text(home, s, plan, owner_turn):
    """An orchestrator's own steps that are new features: each gets a new orchestrator, once per step."""
    if spawned_from(s):
        return ""
    path = os.path.join(session_dir(home, s["sessionId"]), "session.json")
    disk = read_json(path)
    told = [x for x in disk.get("featureAdvised") or [] if isinstance(x, str)]
    new = [st for st in plan.get("steps") or [] if st.get("status") != "completed"
           and FEATURE_STEP.search(str(st.get("content") or "")) and st.get("content") not in told]
    if not new:
        return ""
    if disk:
        disk["featureAdvised"] = (told + [st.get("content") for st in new])[-50:]
        write_atomic(path, json.dumps(disk, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    named = "; ".join(f"step {st.get('addr')} \"{cut(clean(st.get('content')), 90)}\"" for st in new)
    return (f"phi (p4-phi): {named} is a new feature, and a feature is a new topic even within this task: it gets a "
            f"new orchestrator of its own, not a child or a step here. {new_top_route(owner_turn)}")


def render_page(home, sid):
    """session.md: a session as one page, with its title, files, notes, turns and workers, rewritten from its files.
    With no `sid`, sessions.md: the orchestrators of the project. A page quotes no prompt, its own session's or
    another's, since a child is pointed to its parent's page and a parent to its worker's: each session is named by
    its title, and each turn by its steps and its report."""
    out = []
    if sid:
        s = load_session(home, sid)
        if not s.get("sessionId"):
            return
        above = spawned_from(s)
        out = [f"# {name_of(s)}", "",
               f"Session `{sid}`, started by `{above}`." if above else f"Session `{sid}`, an orchestrator.", ""]
        if isinstance(s.get("fileSet"), list):
            out += ["## Files", "", "The write set its brief declares:",
                    ""] + ([f"- `{f}`" for f in s["fileSet"]] or ["- none: it writes no file"]) + [""]
        notes = load_notes(home, sid)
        if notes:
            out += ["## Notes", ""]
            out += [f"- {clean(r.get('claim'))}; source: {clean(r.get('source'))}; {r.get('time', '')}" for r in notes]
            out.append("")
        turns = load_turns(home, sid)
        if turns:
            out += ["## Turns", ""]
            for t in turns:
                out += turn_lines(name_of(s), t, report=1200)
            out.append("")
    else:
        out = ["# Orchestrators of this project", ""]
    rows = latest_reports(load_reports(home, sid, TAIL_BYTES))[:40]
    if rows:
        if sid:
            out += ["## Workers, newest first", ""]
        for r in rows:
            out += turn_lines(name_of(load_session(home, r["sessionId"]), r), r["turn"], report=600)
            out.append(f"  session: `{r['sessionId']}`")
        out.append("")
    write_atomic(page_path(home, sid), "\n".join(out))


# --- the store's feedback and user memories ---------------------------------------------------------------------------

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
INDEX_LINK = re.compile(r"\]\(([^)]+\.md)\)")
WHY = re.compile(r"\A\s*\*\*Why")


def memory_rules(home):
    """The store's feedback and user memories in <home>/temportal/memory, each as its name and body, in the order
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


plans.MEMORY_RULES = memory_rules   # the names plans.rule_names reads, for reports that recite them


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


def builtin_text():
    """The rules p4-phi carries itself, so they hold in every project, with memories or none, a store or none; ''
    where the project's p4.json turns both off."""
    own = built_in()
    if not own:
        return ""
    head = "a rule built into p4-phi" if len(own) == 1 else "the rules built into p4-phi"
    return f"phi (p4-phi): {head}, for every session:\n" + "\n".join("- " + x for x in own)


def built_in():
    """The built-in rules that are on, each as its line."""
    return ([BUILT_IN] if ACT_DONT_WAIT else []) + ([LEVELS] if LEVELS_ON else [])


def rules_text():
    """The rules p4-phi hands a session at its start: the rules built into p4-phi, whole. The store's feedback and
    user memories are not handed: memory.md, "Auto memory", says the app loads the first 200 lines of MEMORY.md at
    the start of every conversation, and CLAUDE.md is read again after a compaction, so live_rules hands a line only
    for a memory that changes after the start."""
    if not RULES:
        return ""
    RAN["rules"] = 0
    return builtin_text()


# --- a memory another session changes mid-session ---------------------------------------------------------------------
#
# memory.md: the app loads the memory index at the start of every conversation and reads CLAUDE.md again after a
# compaction, and no page says a memory written during a session reaches the other sessions already working. A
# feedback or user memory ezexe or another session changes during the day must reach them, or they keep writing the
# old wording into notes, issues and code. So each message compares the memories the session last saw with what is
# on disk now, and gives the changed or added ones once and the removed ones as a list. CLAUDE.md is left to the app.

LIVE_RULES_CHARS = 3000          # of the changes given at one message
LIVE_RULES_LINES = 400           # kept of what a session last saw


def live_rules(s, store):
    """The store's feedback and user memories that changed since this session last looked, a line each, once; ''
    when nothing changed or nothing was seen before. Records what is on disk now in `s`."""
    if not RULES:
        return ""
    new = [f"memory {name}\t{name}: {rule_of(body)}"
           for name, body in (memory_rules(store) if store else [])][:LIVE_RULES_LINES]
    key = hashlib.sha1("\n".join(new).encode("utf-8", "replace")).hexdigest()[:16]
    seen = s.get("rulesSeen") if isinstance(s.get("rulesSeen"), dict) else {}
    s["rulesSeen"] = {"hash": key, "lines": new}
    if not seen or seen.get("hash") == key:
        return ""
    old = [x for x in seen.get("lines") or [] if str(x).startswith("memory ")]   # an earlier copy kept CLAUDE.md's too
    added = [x for x in new if x not in set(old)]
    gone = [x for x in old if x not in set(new)]
    if not added and not gone:
        return ""
    RAN["rules_changed"] = len(added) + len(gone)

    def shown(x):
        src, _, line = x.partition("\t")
        return f"- {src}: {line}"

    parts = ["phi (p4-phi): the store's feedback and user memories changed since this session last looked; these "
             "hold from now on."]
    if added:
        parts.append("Changed or added:\n" + "\n".join(shown(x) for x in added))
    if gone:
        parts.append("Removed, no longer rules:\n" + "\n".join(shown(x) for x in gone))
    return cut("\n".join(parts), LIVE_RULES_CHARS)


# --- the hooks -------------------------------------------------------------------------------------------------------

def given(s, me, home, own=False, brief=False):
    """The start background, when this CLI session has not been given it under its parent session; marks it
    given."""
    if not BACKGROUND or not me.cli:
        return ""                                  # a call with no session id is no new CLI session
    told = s.setdefault("backgroundGivenFor", {})
    if not isinstance(told, dict):
        told = s["backgroundGivenFor"] = {}
    told.pop("", None)                             # an empty key names no CLI session
    above = spawned_from(s)
    if not own and told.get(me.cli) == above:
        return ""
    fresh = bool(above) and not s.get("forked") and not own
    if fresh and not clean(s.get("task")):
        return ""                                  # its brief comes with its first message: built then
    told[me.cli] = above
    # a fresh child starts with exactly what the parent has for it: the tasks above it, its parent step and the
    # parent's task list around it, and the parent's anchor cut to its paths, never the parent's whole background
    cut_to = relay.child_paths(home, s) if fresh else []
    text = background_text(home, s, own=own, slim=bool(cut_to) or brief)   # brief: after a compaction
    if fresh:
        step = plans.slice_for(home, s)
        piece = relay.slice_text(home, s) if cut_to else ""
        text = "\n\n".join(p for p in (text, step, piece) if p)
    if above and "anchorSeen" not in s:
        # the start is the child's base: a fresh child's slice or a fork's inherited conversation already holds the
        # anchor as it is now, so the rebase check hands over only what changes after it
        s["anchorSeen"] = relay.anchor_version(home, above)
        s["marksGiven"] = relay.mark_keys(home, above)
    return text


def pin_of(home, s):
    """A forked child's own task, owned paths and parent step, above the conversation it inherited; '' for others."""
    if not s.get("forked"):
        return ""
    line = relay.pin_text(s)
    root = plans.root_of(home, s)
    return (line + f" It is for step {root} of its parent's task list; its own steps are {root}.1, {root}.2, "
                   f"and so on.") if line and root else line


def h_plan(payload):
    """PostToolUse on mcp__ccd_turn__update_plan: the session's plan.json, the parent's anchor, a revision warned to
    the sessions it bears on, and at a step boundary what bears on the step starting now, all in plans.py."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    save_session(me.home, s)
    asks(s)
    text = plans.record(me.home, s, inp)
    if isinstance(inp.get("items"), list):        # the task list's first whole list, or a revision of it
        s = load_session(me.home, me.id) or s
        cap = caps_text(me.home, s)
        advise = plans.split_advice if spawned_from(s) else plans.top_advice if TOP_ORCHESTRATES else None
        if advise is plans.top_advice and controls.is_puppeteer(s, me.store):
            advise = None                          # a puppeteer's steps are its own; it hands none out
            RAN["pair"] = "puppeteer"
        advice = advise(me.home, s, plans.load(me.home, me.id), s.get("turnBy", "user") == "user", cap)             if advise else ""                      # none where the orchestrator does its own steps
        RAN["split"] = "advised" if advice else ""
        feat = feature_steps_text(me.home, s, plans.load(me.home, me.id), s.get("turnBy", "user") == "user")
        research = research_step_text(me.home, s, plans.load(me.home, me.id))
        text = "\n\n".join(p for p in (feat, research, advice, text) if p)
    if spawned_from(s) and any(k in inp for k in ("advance", "start", "done", "items")):
        s = load_session(me.home, me.id) or s      # the issue or the findings line, then the commits' check
        cwd = payload.get("cwd") or s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
        line = issues.ensure(me.home, s, issues.plan_lines(me.home, me.id), cwd, "plan") \
            if isinstance(inp.get("items"), list) and not load_turns(me.home, me.id) else ""
        flag = issues.unclosed_text(me.home, s, cwd)
        save_session(me.home, s)
        RAN["issue"] = (s.get("issue") or {}).get("number", "")
        text = "\n\n".join(p for p in (line, flag, text) if p)
    nudge_arm(me, load_session(me.home, me.id) or s)
    RAN["plan"] = len(text)
    return text or None


# --- the nudge: an orchestrator doing a work step itself ------------------------------------------------------
#
# The marker <store>/phi/.nudge/<CLI session id> exists while an orchestrator's step in progress is a work step it
# has not been nudged on; recall-hook.sh lets an Edit, Write or shell call through to python only while a marker names
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
    """The orchestrator's step in progress when it is a work step not nudged on yet, else None."""
    if not s or spawned_from(s) or not TOP_ORCHESTRATES or controls.is_puppeteer(s, store_at(s.get("cwd"))):
        return None
    plan = plans.load(home, s["sessionId"])
    st = plans.step_of(plan, plan.get("current") or "") if plan.get("steps") else None
    text = str((st or {}).get("content") or "")
    if not st or st.get("status") == "completed" or plans.top_stays(text):    # the advice's own answer
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
    commands, and p4-phi's own commands: any that runs phi.py, directly or through a variable bound to it."""
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
            # the subcommand is the first word past the options, so `git -C <path> log` is a read
            words = [w for w in re.sub(r"\s(?:-C|-c|--git-dir|--work-tree)\s+\S+", " ", part).split()[1:]
                     if not w.startswith("-")]
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


TREE_CHECKS = 6               # read-only checks of its trees an orchestrator runs in one work step as orchestration
TREE_CHECK = re.compile(r"(?:^|[\s;&|(])(?:git\s+(?:-C\s+\S+\s+)?(?:log|status|diff|show|branch|fetch|rev-parse|"
                        r"ls-files)\b|gh\s+(?:issue|pr|run|api|repo)\b|\S*phi\.py[\"']?\s+(?:tree|show|controls|"
                        r"background)\b)", re.I)


def tree_checked(me, s, st):
    """An orchestrator's read-only check of its trees in a work step, such as a session list, `git log`,
    `gh issue list` or `gh issue view`: counted, and never handed off while they are few. Past TREE_CHECKS in one
    step it is told once that the rest is a read for the built-in Explore subagent. None while they are few."""
    key = nudge_key(st)
    held = s.get("treeChecks") if isinstance(s.get("treeChecks"), dict) else {}
    n = (int(held.get("n") or 0) if held.get("key") == key else 0) + 1
    s["treeChecks"] = {"key": key, "n": n}
    save_session(me.home, s)
    if n != TREE_CHECKS + 1:
        return None
    RAN["tree_checks"] = n
    return (f"phi (p4-phi): step {st.get('addr')} has now run {n} read-only checks of its trees here. A few, such as "
            f"a session list, `git log`, `gh issue list` or `gh issue view`, are this orchestrator's own "
            f"orchestration; past {TREE_CHECKS} the rest is a read across the trees: hand it to "
            f"{plans.EXPLORE}. Said once for this step.")


def h_puppeteer_tool(payload):
    """PreToolUse on a shell command or a file edit: a puppeteer's turns hold messages only, so the task goes to its
    standing worker. A subagent's call and a call that runs phi.py itself, such as `note` or `controls`, get
    nothing."""
    me = Me(payload)
    if not me.home or not me.id or payload.get("agent_id"):
        return ""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if "phi.py" in str(inp.get("command") or ""):
        return ""
    line = controls.tool_line(load_session(me.home, me.id), me.store)
    RAN["puppeteer_tool"] = bool(line)
    return line


def h_wrap_up(payload):
    """PostToolUse on wrap_up: a session that keeps a state page is told to bring it up to date, to read its context
    with the app's own count and, past the line, to clear its idle coworkers and then itself."""
    me = Me(payload)
    if not me.home or not me.id:
        return ""
    line = controls.clear_line(me.home, load_session(me.home, me.id), me.store)
    RAN["clear"] = bool(line)
    return line


def h_nudge(payload):
    """PreToolUse on Edit, Write and shell commands in an orchestrator with a task list: one line, once per
    step, that the work goes to a worker. Never a block; reading, git's reading and landing commands are never
    nudged."""
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
        if str(payload.get("tool_name") or "") in SHELL_TOOLS and TREE_CHECK.search(str(inp.get("command") or "")):
            return tree_checked(me, s, st)         # a few read-only checks of its trees are orchestration
        return None
    level = plans.level_of(st.get("content")) if LEVELS_ON else "session"
    if level == "run" and inp.get("run_in_background") is True:
        return None                                # the step's command already runs where the rule sends it
    s["nudged"] = (list(s.get("nudged") or []) + [nudge_key(st)])[-50:]
    save_session(me.home, s)
    nudge_arm(me, s)
    RAN["nudge"] = st.get("addr")
    if level != "session":                         # a step that only reads or only runs a command needs no session
        return (f"phi (p4-phi): this is the orchestrator, kept free for orchestration, and step "
                f"{st.get('addr')}, \"{cut(clean(st.get('content')), 120)}\", {plans.LEVEL_WHAT[level]}: hand it to "
                f"{plans.LEVEL_WHERE[level]}. "
                f"Said once for this step.")
    return (f"phi (p4-phi): this is the orchestrator, kept free for orchestration, and step {st.get('addr')}, "
            f"\"{cut(clean(st.get('content')), 120)}\", is work: hand it to a worker with "
            f"`mcp__ccd_session__start_session`, `context` `fresh`, `use_worktree: false`, "
            f"{plans.level_words(st.get('content'))}, its brief that step, a "
            f"line `Files: <the paths it may write>`, the line `{plans.level_line(plans.child_level(st.get('content')))}` "
            f"and \"report when done\", and keep this session for planning, messaging and landing. Said once for this "
            f"step.")


def h_memory_gap(payload):
    """PostToolUse on Write and Edit: a feedback memory written into the project's store whose rule describes
    session or plugin behaviour gets the line of gaps.py that writes that plugin gap into this turn's report as a
    `Finding:` line, for the session that publishes the issue."""
    me = Me(payload)
    if not me.home or not me.id or not me.store:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    path = str(inp.get("file_path") or "")
    if not path:
        return None
    import gaps
    s = load_session(me.home, me.id) or ensure_session(me.home, me.id, me.rec, me.cli)
    text = gaps.advice(me.home, me.store, s, path,
                       before=gaps.before_write(path, inp, payload.get("tool_response")))   # what the file held
    RAN["memory_gap"] = bool(text)
    return text or None


def h_self_archive(payload):
    """PreToolUse on mcp__ccd_session_mgmt__archive_session. Whether the call runs is ezexe's: the settings keeper
    writes an ask rule on the tool, which the app asks about in every permission mode, and the tool itself refuses a
    session with live background work. What no native step does: a child that archives itself may never reach its Stop
    hook, so its turn and its last report are kept now, read from the transcript, it is counted as archived as at
    Stop, and an unproven or open issue keeps it from archiving."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = str(inp.get("session_id") or inp.get("sessionId") or inp.get("id") or "self")
    if target not in ("self", me.id, me.cli, me.id.removeprefix("local_")) or not spawned_from(s):
        return None
    turn = last_turn(payload.get("transcript_path") or "")
    texts = [t for t in (turn or {}).get("texts") or [] if isinstance(t, str) and t.strip()]
    h_stop({**payload, "hook_event_name": "Stop", "last_assistant_message": texts[-1] if texts else "",
            "_atArchive": True})
    RAN["self_archive"] = True
    held = RAN.get("issue_open")
    if held:                                       # an unproven or open issue keeps the child from archiving
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": held}}
    return None


def h_restart_check(payload):
    """PreToolUse on a shell command run in the background: one this session's own records show as still running
    is not started a second time; the session is told the id to wait on, once for that copy."""
    me = Me(payload)
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not me.home or not me.id or not inp.get("run_in_background") or not inp.get("command"):
        return None
    why = puppeteer.restart_text(me.home, me.id, str(inp.get("command")))
    if not why:
        return None
    RAN["restart"] = "held"
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": why}}


def h_task_stop(payload):
    """PostToolUse on TaskStop, or KillShell in an older session: the stopped task's entry leaves the list the last
    Stop kept, since a stop sends no completion notice. Prints nothing."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    tid = inp.get("task_id") or inp.get("shell_id") or inp.get("id")
    if s and tid and plans.clear_in_flight(s, json.dumps({"name": "TaskStop", "input": {"task_id": str(tid)}})):
        save_session(me.home, s)
        RAN["task_stop"] = str(tid)
    return None


def mark_fork(s, me, payload):
    """A session the app records as a fork, that SessionStart says began as one, its `source` "fork" as hooks.md's
    SessionStart input names it, or whose first message is a fork's, is kept as one."""
    if s.get("forked"):
        return
    if (me.rec or {}).get("forkedFromSessionId") or payload.get("source") == "fork" \
            or FORK_HEAD.match(str(payload.get("prompt") or "")):
        s["forked"] = True


def ran_for(s, me):
    held = s.get("spawnedFrom") if isinstance(s.get("spawnedFrom"), dict) else {}
    RAN.update(home=me.home, session=s["sessionId"], spawnedFrom=held.get("sessionId", ""),
               source=held.get("source", ""), cli=me.cli)


def tracked(home):
    """True where the store's p4.json sets phi.track, as relay.track reads it."""
    try:
        return bool((p4conf.section(home, "phi", write=False) or {}).get("track"))
    except Exception:  # noqa: BLE001
        return False


def h_session_start(payload):
    me = Me(payload)
    if not me.home or not me.id:
        # a project with no .claude/p4 yet still gets the rules p4-phi carries itself; the SessionStart hooks run
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
    asks(s)
    lost = source in ("compact", "clear")
    text = book_line = ""
    if not (source == "startup" and not spawned_from(s) and not s.get("task")
            and os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")):
        # with a host id and nothing recorded, the app has not yet written this session's parent session, and the
        # first message tells.
        # context-window.md, "What survives compaction": "When a long session compacts, Claude Code summarizes the
        # conversation history to fit the context window", and "Context that hooks added earlier" is "Summarized with
        # the rest of the conversation". So after a compaction the summary carries the session's own turns and the
        # book it was handed: p4-phi hands neither again, only the book's entries that changed since, with the path
        # of book.md, since a summary keeps no exact id or path. A clear keeps nothing, so it gets both whole.
        cleared, compacted = source == "clear", source == "compact"
        own = cleared or (not compacted and len(s.get("cliSessionIds") or []) > 1)
        text = given(s, me, me.home, own=own, brief=compacted)
        book_line = book_text(me.home, s, me.store, whole=cleared, named=compacted) if lost else ""
    pin = pin_of(me.home, s)
    text = "\n\n".join(p for p in (pin, text) if p)
    live_rules(s, me.store)                        # what it starts with
    relay.remember_store(me.store)
    notices = []
    if tracked(me.home):                           # a failed first commit, said once; no git call while untracked
        notices.append(relay.track_notice(me.home))
    if me.home_missing:
        notices.append(f"phi (p4-phi): this project's p4.json names the shared store {me.home_missing} for the "
                       f"session tree, and this machine has not seen it; the tree stays in this project's store.")
    first = ""
    if source == "compact" and controls.is_puppeteer(s, me.store):
        first = controls.compacted(me.home, s)     # a puppeteer's board path before anything else
        RAN["pair"] = "compacted"
    elif source in ("compact", "clear"):
        first = controls.state_first(me.home, s)   # a standing worker's or coworker's state page first
    rules = rules_text() if source != "resume" else ""
    save_session(me.home, s)
    # past the app's cap of 10,000 characters Claude sees a preview of the first 2,000 and the file's path, so what
    # asks the session to act comes first: the page to resume from and the notices, then the built-in rules and the
    # background, and last the address book, which is whole on its page as well
    return "\n\n".join(p for p in (first, *notices, rules, text, book_line) if p) or None


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


def fit(parts, room, home, sid, keep=()):
    """The parts that fit in `room`, in their order, each whole; with no `room`, every part, the ones in `keep`
    first, so past the app's own cap they fall inside its preview. What does not fit in a room is kept whole on the
    session's held.md and named by count, by that page and by how each begins. No piece is shown cut, since a cut
    piece, such as a list of start requests, is of no use in part. A piece in `keep` asks the session to act at this
    message, so it is never held: the room goes to those first, and the other pieces fit in what is left."""
    parts = [p for p in parts if p]
    kept = {id(p) for p in keep if p}
    if room is None:                               # the app's own cap and file: the notices first, then the rest
        return "\n\n".join([p for p in parts if id(p) in kept] + [p for p in parts if id(p) not in kept])
    if sum(len(p) + 2 for p in parts) - 2 <= room:
        return "\n\n".join(parts)
    tail = 260 + len(relay.held_path(home, sid)) + 3 * (HELD_HEAD + 8)    # the lines that name what is held
    free = room - tail - sum(len(p) + 2 for p in parts if id(p) in kept)
    out, over, used = [], [], 0
    for p in parts:
        if id(p) in kept:
            out.append(p)
        elif used + len(p) + 2 <= free:
            out.append(p)
            used += len(p) + 2
        else:
            over.append(p)
    page = relay.hold(home, sid, over, now())
    RAN["held"] = len(over)
    heads = ['"' + cut(clean(PHI_LEAD.sub("", p)), HELD_HEAD) + '"' for p in over[:3]]
    line = (f"phi (p4-phi): {len(over)} of the pieces p4-phi had for this prompt, {sum(len(p) for p in over)} "
            f"characters, did not fit in its {room} beside one prompt and are whole on {page}. Read that page "
            f"before going on when one of them asks something of this session. They begin: " + "; ".join(heads)
            + (f"; and {len(over) - 3} more" if len(over) > 3 else "") + ".")
    out.append(line)
    return "\n\n".join(out)


def touches_of(home, s):
    """What tells whether a sibling's note bears on this session: its words against the task and the open steps."""
    own = [clean(s.get("task"))] + [str(st.get("content") or "") for st in plans.open_steps(home, s["sessionId"])]
    own = [plans.words(o) - plans.SIBLING_STOP for o in own if o]

    def touches(text):
        got = plans.words(text)                    # three shared content words, or all of a two-word task
        return any(len(o) >= 2 and len(o & got) >= min(3, len(o)) for o in own)
    return touches


def h_user_prompt_submit(payload):
    me = started_by(Me(payload), payload)
    if not me.home or not me.id:
        return None
    if me.store and not same_store(me.store, me.home) and NEW_TOP.search(str(payload.get("prompt") or "")) \
            and not load_session(me.home, me.id).get("sessionId"):
        me.home = me.store                         # a new orchestrator from another environment's session
        RAN["own_store"] = True
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli, hint=me.hint)
    ran_for(s, me)
    detached_now = False
    if spawned_from(s) and NEW_TOP.search(str(payload.get("prompt") or "")) and not load_turns(me.home, s["sessionId"]):
        reparent(me.home, s["sessionId"], "", "detached")     # its brief marks it a new orchestrator
        s = load_session(me.home, s["sessionId"])
        RAN["new_top"] = True
        detached_now = True
    rid, asker = starts.requester_of(me.home, payload.get("prompt")) if not load_turns(me.home, s["sessionId"]) \
        else ("", "")
    if rid:                                        # a start request's child: the asking session's, not the caller's
        if not detached_now and asker != s["sessionId"] and spawned_from(s) != asker:
            try:
                reparent(me.home, s["sessionId"], asker, "requested")
                RAN["requested_by"] = asker
            except ValueError:
                pass
            s = load_session(me.home, s["sessionId"])
        starts.started(me.home, rid, s["sessionId"])
    if not load_turns(me.home, s["sessionId"]) and puppeteer.arrived(me.home, s, payload.get("prompt")):
        RAN["drafted"] = s.get("draft") or (s.get("reading") or {}).get("group", "")   # its start draft or reading
    req = request_of(payload.get("prompt"))
    s["turnBy"] ="user" if req else (
        "session" if re.search(r"<cross-session-message\b", str(payload.get("prompt") or "")) else "event")
    plans.clear_in_flight(s, payload.get("prompt"))   # a completion notice ends its entry
    mark_fork(s, me, payload)
    if not s.get("disposable") and relay.DISPOSABLE.search(str(payload.get("prompt") or "")) \
            and not load_turns(me.home, s["sessionId"]):
        s["disposable"] = True                     # its brief or its first message: report when done
        RAN["disposable"] = True
    if "fileSet" not in s and not load_turns(me.home, s["sessionId"]):
        declared = starts.files_of(payload.get("prompt"), s.get("cwd") or payload.get("cwd") or "")
        if declared is not None:                   # the write set its brief declares, kept and shown on its page
            s["fileSet"] = declared
            RAN["files"] = len(declared)
    if s.get("doneRetired") or s.get("archived"):
        s["doneRetired"] = s["archived"] = False   # messaged again: a live session once more
        s["reopened"] = now()
        s.pop("archiveChecked", None)              # checked again at its next archive
        s.pop("unfinishedAtArchive", None)
        RAN["reopened"] = True
        save_session(me.home, s)
        relay.reopened(me.home, s, s["reopened"])   # named as reopened, so the mark hides no live work
    if req and not s.get("task"):
        s["task"] = cut(req, TASK_CHARS)
        s["taskAt"] = now()
    issue_line = ""
    if spawned_from(s) and not load_turns(me.home, s["sessionId"]) and not s.get("issue"):
        issue_line = issues.ensure(me.home, s, req or str(payload.get("prompt") or ""),
                                   s.get("cwd") or payload.get("cwd") or "", "brief")   # from its brief
        RAN["issue"] = (s.get("issue") or {}).get("number", "")
    handed = given(s, me, me.home)
    room = None if handed else PROMPT_CHARS       # the first message passes whole, past the app's cap to its file
    parts = [live_rules(s, me.store),
             pin_of(me.home, s), handed]
    if REPORTS:
        text, seen = reports_text(me.home, s, room * 3 // 5 if room else None, me.store)
        s["reportsSeen"] = seen
        parts.append(text)
    save_session(me.home, s)
    step = replay(me, s, payload.get("transcript_path") or "")
    s = load_session(me.home, s["sessionId"]) or s
    if step:
        parts.append(step)
    keep = []                                      # the notices that ask the session to act now: never held

    def notice(text):
        keep.append(text)
        return text
    pend = (s.pop("staleChildren", None) or []) + relay.drain_archive(me.home, s["sessionId"])
    pend = [x for x in pend if isinstance(x, dict) and not archived_already(me.home, x.get("id"))]
    stale = relay.stale_text(pend)                # children to archive, said once; one archived in the app is not named
    s["staleTold"] = (list(s.get("staleTold") or []) + [x.get("id") for x in pend if isinstance(x, dict)])[-50:]
    if stale:
        parts.insert(0, notice(stale))
    began = bool(req) and not handed_over(payload.get("prompt"))     # ezexe began this turn
    freed = starts.freed_text(me.home, s["sessionId"], began)
    if freed:                                      # the starts it queued behind a writer that is free: a start at
        parts.insert(0, notice(freed))             # ezexe's turn, the app's suggested task card at any other
        RAN["queued_starts"] = freed.count("\n- ")
    if issue_line:
        parts.insert(0, notice(issue_line))
    pad = str(payload.get("scratchpad_dir") or "").replace("\\", "/").rstrip("/")
    if pad and not s.get("scratchpadDir"):        # the app's scratchpad of the first turn: a clear's new
        s["scratchpadDir"] = pad                  # conversation still finds the state page written there
    stand = (controls.worker_first(me.home, s, payload.get("prompt"), me.store)
             if spawned_from(s) and not load_turns(me.home, s["sessionId"]) else "")
    first_split = first_split_text(me.home, s)
    if first_split:
        parts.insert(0, notice(first_split))
    if stand:                                      # a puppeteer's standing worker or coworker: what it is
        RAN["standing"] = s.get("standingKind")
        parts.insert(0, notice(stand))
    usage = controls.usage_line(me.home, s, payload.get("prompt"), me.store)
    if usage:                                      # a puppeteer watches its worker's and coworkers' context
        RAN["usage"] = True
        parts.insert(0, notice(usage))
    research = research_text(me.home, s)
    if research:
        parts.insert(0, notice(research))
    if FILE_SETS and s.get("fileSet") and load_turns(me.home, s["sessionId"]):
        held_line = files_held_text(me.home, s)    # its closing commit is pushed and it still holds files
        if held_line:
            parts.insert(0, notice(held_line))
            RAN["files_held"] = len(s["fileSet"])
            save_session(me.home, s)
    if detached_now:
        parts.insert(0, notice("phi (p4-phi): this session's brief marks it a new orchestrator, so p4-phi detached it "
                        "to top level at this first message. Now call `mcp__ccd_session_mgmt__detach_session` with "
                        "`\"self\"` before anything else, so the app stops nesting it under its parent session and its "
                        "reports stop going there; it orchestrates its own topic, and the other orchestrators are "
                        "its siblings."))
    # ezexe's own message: a handed-over task is none, and to a puppeteer, neither is one the app marks as another
    # session's; an orchestrator's routing still reads the work another session hands it
    ezexes = req if req and not handed_over(payload.get("prompt")) else ""
    if ezexes and puppeteer.from_session(payload.get("prompt")) and controls.is_puppeteer(s, me.store):
        ezexes = ""
    if not spawned_from(s):
        try:                                       # a puppeteer and the sessions it controls
            parts[0:0] = pair_parts(me, s, ezexes, parts[0], notice)
        except Exception:  # noqa: BLE001
            pass
    unsent = [u for u in s.pop("unsentRelay", None) or [] if isinstance(u, dict)]
    if unsent:
        parts.insert(0, notice("phi (p4-phi): " + " ".join(
            f"your last turn changed {', '.join(u.get('steps') or [])} in the work of "
            f"\"{relay._title(load_session(me.home, u['child']))}\" "
            f"and sent it nothing; send it the change with SendMessage to `{u['child']}`." for u in unsent)))
    pup = verdict = ""
    if ezexes:
        try:                                       # meta pass and ledger, then routing, start draft and gate
            size = os.path.getsize(payload.get("transcript_path") or "")
        except OSError:
            size = 0
        try:
            pup, verdict = puppeteer.on_prompt(me.home, s, req, s.get("cwd") or payload.get("cwd") or "", size)
        except Exception:  # noqa: BLE001
            pup = verdict = ""
        RAN["puppeteer"] = verdict or bool(pup)
    try:                                           # it reads the app's records: a failure costs only its own line
        route = relay.route_text(me.home, s["sessionId"], req, s.get("cwd") or "") if req and not verdict else ""
    except Exception:  # noqa: BLE001
        route = ""
    book_line = "" if route else book_text(me.home, s, me.store)
    parts.append(pup)
    split = split_text(me.home, s, payload.get("prompt")) if not route else ""
    last = route or "\n\n".join(x for x in (book_line, split) if x)
    save_session(me.home, s)
    # the rebase check, on every message: what the sessions beside this one changed, and the warnings, first
    used = sum(len(p) + 2 for p in parts + [last] if p)
    share = max(room // 3, room - used) if room else PROMPT_CHARS
    text, _ = relay.rebase(me.home, s["sessionId"], share, fair_cut, touches_of(me.home, s))
    RAN["relay"] = len(text)
    lead = [text] if room is None else []        # with no room the rebase's stop warnings still lead
    return fit([text, last] + parts, room, me.home, s["sessionId"], lead + keep)


def pair_parts(me, s, req, changed="", notice=lambda text: text):
    """Beside an orchestrator's message. A puppeteer gets what it is, once; the orchestrators it
    started, now controlled; an orchestrator ezexe started beside them; the controlled sessions' reports by reference; at a
    turn ezexe began, the requests addressed to it and where ezexe's message belongs; the sessions of the controlled
    trees that hold start requests, as links; each start it made on another session's behalf, to detach to top
    level; a boundary; and its board rewritten. Any other orchestrator gets its puppeteer, once, and
    what became of the requests it sent it."""
    out = []
    if not controls.is_puppeteer(s, me.store):
        told = controls.pair_text(s, me.store)
        if told:
            RAN["pair"] = "controlled"
        asks(s)
        answers = controls.answers_text(me.home, s) if s.get("puppeteer") else ""
        return [p for p in (told, answers) if p]
    RAN["pair"] = "puppeteer"
    controls.mark_puppeteer(me.store or me.home, me.cli)   # so the hook's gate hands phi.py each of its tool calls
    if not s.get("puppeteerSeen"):
        s["puppeteerSeen"] = now()                 # said once, and kept, so a filing is never silent
        out.append("phi (p4-phi): " + controls.rule_text(me.home, s))
    controls.rules_changed(s, changed)
    lines = controls.take_started(me.home, s) + controls.announce(me.home, s)
    if lines:
        out.append("phi (p4-phi): " + " ".join(lines))
    import asks as requests                        # ezexe's requests, a row each, on asks.md beside the board
    try:
        turns = load_turns(me.home, s["sessionId"])
        requests.on_message(me.home, s, req, turns[-1] if turns else None)
        ledger = requests.line(me.home, s, me.store)
    except Exception:  # noqa: BLE001  a ledger it cannot write never costs the message its other lines
        ledger = ""
    if ledger:
        RAN["asks"] = ledger.count("\n- ")
        out.append(ledger)
    rows = []
    seen = controls.reports(s, rows)
    if seen:
        out.append("phi (p4-phi): the sessions this puppeteer controls ended turns. Each is one line and its "
                   "page, which holds up to 1,200 characters of the report; read a page only when its detail is "
                   "needed:\n" + "\n".join(seen))
    tune = controls.effort_text(rows)
    if tune:
        RAN["effort"] = tune.count("\n- ")
        out.append(tune)
    if req:
        out += [p for p in (controls.requests_text(me.home, s), controls.route_down(s, req)) if p]
    out += [p for p in (controls.holders_text(s, req), controls.behalf_text(me.home, s)) if p]
    edge = controls.boundary(me.home, s)
    if edge:
        RAN["boundary"] = True
        pieces = edge.split("\n\n")               # the complete sessions, kept, and the boundary, which fits or is held
        if not pieces[0].startswith("phi (p4-phi): a boundary: "):
            pieces[0] = notice(pieces[0])
        out += pieces
    controls.board(me.home, s)
    return out


def h_stop(payload):
    me = Me(payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    if isinstance(payload.get("background_tasks"), list):   # hooks.md, Stop input: kept before any return
        kept = ensure_session(me.home, me.id, me.rec, me.cli)
        if plans.keep_in_flight(kept, payload):
            save_session(me.home, kept)
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
    row.update({"time": now(), "at": now_exact(), "sessionId": s["sessionId"], "cliSessionId": me.cli})
    earlier_ = load_turns(me.home, s["sessionId"])
    if earlier_ and earlier_[-1].get("atArchive") and earlier_[-1].get("id") == row["id"]:
        return None                                # kept already when this session archived itself
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
    row["sessions"] = [f"\"{name_of(load_session(me.home, r['sessionId']), r)}\": "
                       f"{'done' if r['turn'].get('done') else 'not shown done'}"
                       for r in latest_reports(load_reports(me.home, s["sessionId"]))][:TURN_STEPS]
    append_line(os.path.join(session_dir(me.home, s["sessionId"]), "turns.jsonl"), row)
    above = spawned_from(s)
    append_line(reports_path(me.home, above),
                {"time": row["time"], "sessionId": s["sessionId"], "title": name_of(s), "turn": row})
    s.pop("done", None)
    if not s.get("task"):
        s["task"], s["taskAt"] = row["prompt"], row["time"]
    save_session(me.home, s)
    if above and isinstance(s.get("reading"), dict):
        try:                                       # a reading reported: the orchestrator above merges its group
            RAN["merged"] = len(puppeteer.merge_all(me.home, above))
        except Exception:  # noqa: BLE001
            pass
    replay(me, s, payload.get("transcript_path") or "")
    s = load_session(me.home, s["sessionId"]) or s
    if isinstance(s.get("stale"), dict) and s["stale"].get("told"):
        s.pop("stale", None)                       # told what superseded it, and a turn of its own ended since
        s["unstaled"] = now()
    unsent = plans.turn_relay(me.home, s, row, turn.get("calls") or [])
    if unsent:                                     # what this turn changed for a child and did not tell it
        s["unsentRelay"] = [{"child": c, "steps": a, "time": row["time"]} for c, a in unsent]
    save_session(me.home, s)
    steps = plans.load(me.home, s["sessionId"]).get("steps") or []
    finished = bool(row.get("done") or (steps and all(x.get("status") == "completed" for x in steps)))
    proved, held, note = True, "", ""
    if above and finished and isinstance(s.get("issue"), dict):
        cur = load_session(me.home, s["sessionId"]) or s     # the regression test re-run on the final head
        proved, held, note = issues.gate(me.home, cur, payload.get("cwd") or cur.get("cwd") or "")
        save_session(me.home, cur)
        s = cur
        RAN["issue_gate"] = "ok" if proved else (held[:60] or "held")
        if not proved:
            RAN["issue_open"] = held or (f"phi (p4-phi): {cur['issue']['repo']}#{cur['issue']['number']} is not "
                                         f"yet proven and closed, so this session is not counted as archived.")
    # a child that archives itself is over whether or not its turn was shown done or its task list completed, so
    # it is counted as archived on its parent as it goes, its open steps named; one held by an unproven issue is not
    left = bool(payload.get("_atArchive")) and not finished
    if above and proved and ((s.get("disposable") and finished) or left):
        if relay.retire_done(me.home, above, s["sessionId"], row["time"], extra=note, archived=left):
            RAN["retired"] = "archived" if left else "done"
            try:                                   # what it started and did not finish, checked as it is archived
                RAN["unfinished"] = len(puppeteer.archive_check(me.home, s["sessionId"]))
            except Exception:  # noqa: BLE001
                pass
    if above and finished and (proved or issues.proven_now(s)):   # with an issue, once its test passed
        cur = load_session(me.home, s["sessionId"]) or s
        told = list(cur.get("closesTold") or [])
        new = [c for c in issues.closing_commits(me.home, cur, payload.get("cwd") or "") if c[1] not in told]
        if new:                                    # the orchestrator pushes issue-closing work at once
            top = (chain_of(me.home, s["sessionId"]) or [above])[-1]
            relay.warn(me.home, top, "push:" + s["sessionId"] + ":" + ",".join(c[1] for c in new),
                       relay.push_text(title_of(cur), s["sessionId"], new,
                                       relay.owed(list(dict.fromkeys(c[0] for c in new)))))   # what each still owes
            RAN["push_owes"] = True
            cur["closesTold"] = (told + [c[1] for c in new])[-100:]
            save_session(me.home, cur)
            RAN["push_told"] = len(new)
    for node in (above, s["sessionId"]):           # the parent's anchor, and this session's own for its children
        a = relay.make_anchor(me.home, node, row["time"])
        if a and node == above:
            RAN["anchor"] = a.get("version")
    render_page(me.home, s["sessionId"])
    render_page(me.home, above)
    try:                                           # a memory whose issue landed is cut back to its pointer
        RAN["memories_cut"] = len(issues.cut_back(me.home, payload.get("cwd") or s.get("cwd") or "", [
            c["input"].get("command") for c in turn.get("calls") or []
            if c.get("name") in SHELL_TOOLS and isinstance(c.get("input"), dict)]))
    except Exception:  # noqa: BLE001
        pass
    relay.track(me.home)                           # staged for the store's next commit, so it reaches the others
    RAN.update(turn=row["id"], done=bool(row["done"]))
    now_s = load_session(me.home, s["sessionId"]) or s
    if now_s.get("doneRetired") or now_s.get("archived"):
        return None
    waits = []
    if not spawned_from(now_s) and controls.is_puppeteer(now_s, me.store):
        waits = controls.waited_on(now_s)          # its turn may end on a step that waits on its controlled sessions
        RAN["waits_on"] = len(waits)
        controls.board(me.home, now_s)
    named = ""
    if not waits and not spawned_from(now_s):      # a plain orchestrator waiting on the sessions of its tree
        step = plans.waiting_step(me.home, now_s["sessionId"])
        waits = waited_on(me.home, now_s, turn.get("calls") or []) if step else []
        if waits:
            RAN["waits_on"] = len(waits)
            named = (f"phi (p4-phi): this turn ends on step {step.get('addr')}, "
                     f"\"{cut(clean(step.get('content')), 100)}\", which waits on "
                     + ", ".join(f"\"{w}\"" for w in waits[:6])
                     + (f" and {len(waits) - 6} more" if len(waits) > 6 else "")
                     + ": the turn is not sent back, and a report's arrival starts the next one.")
    why = plans.keep_going(me.home, now_s, row["report"], turn.get("calls") or [], row["id"],
                           bool(payload.get("stop_hook_active")), waits=waits,
                           background=payload.get("background_tasks") if isinstance(payload.get("background_tasks"),
                                                                                     list) else plans.in_flight(now_s))
    why = "\n\n".join(p for p in (held, why) if p)   # the regression test's verdict, then the open steps
    if why:                                        # open steps the session tree can settle send the turn back
        RAN["kept_going"] = True
        return {"decision": "block", "reason": why}
    if named:
        return {"systemMessage": named}            # one line to ezexe naming the sessions waited on; never a block
    return None


def h_turn_end(payload):
    """A turn that ended with no Stop. Claude Code runs StopFailure in place of Stop when a turn ends on an API error,
    by https://code.claude.com/docs/en/hooks#stopfailure, ezexe/p4#161, and SessionEnd when the session ends, an
    exit in a turn among them, ezexe/p4#151. The hook logs one line as `stop`, with the event and the error or the
    reason, so puppeteer.working reads the session as out of its turn. It keeps no turn row, since the transcript
    Claude Code keeps holds the turn, and it writes nothing more, since SessionEnd hooks share 1.5 seconds."""
    me = Me(payload)
    if not me.home or not me.id or not load_session(me.home, me.id).get("sessionId"):
        return None
    RAN.update(home=me.home, session=me.id, cli=me.cli, event=clean(payload.get("hook_event_name")),
               ended=clean(payload.get("error") or payload.get("reason"))[:40])
    return None


def messaged(calls):
    """The sessions a turn's calls sent a message to."""
    out = []
    for c in calls or []:
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        name = str(c.get("name") or "")
        to = inp.get("to") if name.endswith("SendMessage") else (
            inp.get("session_id") or inp.get("to") if name.endswith("send_message") else "")
        if to and str(to) not in out:
            out.append(str(to))
    return out


def waited_on(home, s, calls=()):
    """The titles of the sessions an orchestrator's waiting step still waits on: each worker or session it
    messaged that is inside a turn, or whose report it has not been handed yet. The sessions it messaged are kept on
    its record."""
    sid = s["sessionId"]
    sent = [x for x in s.get("messaged") or [] if isinstance(x, str)]
    new = [safe_id(x) for x in messaged(calls) if safe_id(x) not in sent]
    if new:
        s["messaged"] = (sent + new)[-40:]
        save_session(home, s)
    rows = load_reports(home, sid)
    seen = s.get("reportsSeen") if isinstance(s.get("reportsSeen"), int) else 0
    unread = {r["sessionId"] for r in latest_reports(rows[seen:])}
    ids = list(plans._children(home, sid)) + [x for x in sent + new if x != sid]
    out = []
    for k in dict.fromkeys(ids):
        ks = load_session(home, k)
        if not ks.get("sessionId") or relay.gone(home, ks):
            continue
        if puppeteer.working(home, k) or k in unread:
            out.append(title_of(ks))
    return out


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


def h_go_guard(payload):
    """PreToolUse on a message one session sends another, for every sender. A message that names a file or an
    issue another live session holds, sent to neither that session nor the session that started it, or a message
    to the puppeteer that names no matter of ezexe's, is held by a `deny` whose reason names the session it belongs
    to, from book.flag, once for that message and target, so a resend goes through. A puppeteer's go to a waiting
    writer is warned about while another session it controls still holds a file in that writer's write set."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not s.get("sessionId"):
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = str(inp.get("to") or inp.get("session_id") or inp.get("sessionId") or "")
    message = str(inp.get("message") or inp.get("content") or inp.get("text") or "")
    import book
    try:
        held = book.flag(me.home, s, target, message, me.store)
    except Exception:  # noqa: BLE001  a book it cannot read never stops a send
        held = ""
    text = ""
    if not spawned_from(s) and controls.is_puppeteer(s, me.store):
        text = controls.go_text(me.home, s, target, message)
        if text:
            RAN["go_held"] = target[:40]
            save_session(me.home, s)
        if not held:                               # the request this turn opened goes to the session messaged
            import asks as requests
            try:
                requests.on_send(me.home, s, target, message)
            except Exception:  # noqa: BLE001
                pass
    if held:
        RAN["send_flagged"] = target[:40]
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "\n\n".join(x for x in (held, text) if x)}}
    return text or None


def h_start_advice(payload):
    """PreToolUse on mcp__ccd_session__start_session. It denies three starts: a controlled session's new
    orchestrator, which its puppeteer starts instead; a start whose brief declares no write set; and a start
    whose write set a live session holds. For the rest it advises fork or fresh by relay.advise_start, from the
    parent's transcript size and how much of the parent's scope the brief's paths cover, and asks before a worktree
    or a branch of the child's own: silent when the call already does what is advised, else a permission `ask` with
    the reason, so ezexe sees it and decides. A PreToolUse `permissionDecision` is `allow`, `deny`, `ask` or `defer`;
    where `permissions.denyInsteadOfPrompting` is set, a call that would wait on a prompt is denied. The input is
    never rewritten with `updatedInput`, since a fresh start needs a brief and background only the caller can
    write. A start of another session's start request, a puppeteer's or any other session's, goes through, claimed
    as made on that session's behalf, with the line that has the new session detached to top level. A call that
    proposes a start request as a suggested task card claims it for good, since the card holds it from then on."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if inp.get("proposal_id") and not inp.get("prompt"):
        return None                                 # starting a card already made: nothing to decide
    caller = load_session(me.home, me.id)
    card = inp.get("initiation") == "own_initiative"
    made = controls.behalf(me.home, caller, inp.get("prompt"), me.store)
    if made:                                        # a start of another session's start request, by any session
        starts.claim(made[1], inp.get("prompt"), me.id, card=card)
        RAN["behalf"] = made[0]["id"]
        return controls.behalf_line(made[0], controls.is_puppeteer(caller, me.store))
    why = controls.start_refused(me.home, load_session(me.home, me.id), inp.get("prompt"), me.store)
    if why is None:                                 # a puppeteer's standing worker, the first one
        RAN["standing_start"] = True
        return None
    if why:                                         # a second while the first is live
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": why}}
    if starts.claim(me.home, inp.get("prompt"), me.id, card=card):
        RAN["claimed"] = "card" if card else True   # a start request's call, given exactly: the asker decided it
        return None
    brief = str(inp.get("prompt") or "")
    if brief and NEW_TOP.search(brief):
        mine = load_session(me.home, me.id)
        if not spawned_from(mine) and controls.ask_text(mine) and controls.puppeteer_of(mine, me.store)[0]:
            RAN["asked_of_puppeteer"] = True       # asked of its puppeteer, never started here
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": (
                                               "phi (p4-phi): this start is refused: "
                                               + PHI_LEAD.sub("", controls.ask_text(mine)))}}
    if brief and not NEW_TOP.search(brief) and FILE_SETS:
        s = load_session(me.home, me.id)
        files = starts.files_of(brief, s.get("cwd") or payload.get("cwd") or "")
        why = ""
        if files is None:                           # every brief declares its write set
            why = "phi (p4-phi): this start is refused: " + starts.FILES_WANTED
        else:
            who, hit = starts.held_by(me.home, me.id, files)
            if who:
                why = (f"phi (p4-phi): this start is held: its write set shares {', '.join(hit[:5])} with {who}, "
                       f"which is live and has not reported done. "
                       f"Send this work to that session as the next task of its serial run, or "
                       f"start it once that session reports done.")
        if why:
            RAN["files"] = "none" if files is None else "held"
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": why}}
    wanted = "fork" if str(inp.get("context") or "fresh") == "fork" else "fresh"
    try:
        size = os.path.getsize(payload.get("transcript_path") or "")
    except OSError:
        size = 0
    advised, why = relay.advise_start(me.home, me.id, inp, size)
    RAN.update(advice=advised, wanted=wanted, transcript=size)
    reasons = []
    if advised != wanted:
        reasons.append(f"phi (p4-phi) advises context \"{advised}\" here, not \"{wanted}\": {why}.")
    if inp.get("use_worktree") is True or inp.get("branch_name") or inp.get("source_branch"):
        reasons.append("phi (p4-phi): a child works on this session's branch in this checkout, with no worktree or "
                       "branch of its own: pass `use_worktree: false` and leave out branch_name and "
                       "source_branch.")
    if not reasons:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": " ".join(reasons)}}


QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
BRANCH_MOVE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b[^\n|;&]*?\b(switch\b|checkout\s+(?!--)(?!-[^bB])(?![\w./-]*\.\w{1,6}\s*$)[\w./-]+\s*$)")
BRANCHING = re.compile(r"\bgit\b[^\n|;&]*?\b(worktree\s+add|switch\s+(-c|--create|-C)|checkout\s+(-b|-B)|"
                       r"branch\s+(?!-)[\w./-]+\s*$|branch\s+(?!-)[\w./-]+\s+[\w./-]+)")


def h_branch_guard(payload):
    """PreToolUse on EnterWorktree and shell calls in a worker: making a worktree or a branch of its own is
    asked first, since a child works on its parent's branch. So is landing work, a git push, merge, rebase or pull,
    whatever the child's record, brief or parent says: only the tree's orchestrator lands and pushes. Silent
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
    elif name in SHELL_TOOLS and issues.landing(inp.get("command")):
        verb = issues.landing(inp.get("command"))
        RAN["branch_guard"] = verb
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                       "permissionDecisionReason": f"phi (p4-phi): this session is a child, and `"
                                                                   f"{verb}` lands work, which only the tree's "
                                                                   f"orchestrator does: a child commits on its "
                                                                   f"parent's branch and reports, a `Closes #N` "
                                                                   f"commit included, and the tree's orchestrator "
                                                                   f"merges and pushes. Ask its parent session, "
                                                                   f"{spawned_from(s)}, with SendMessage instead."}}
    else:
        return None
    RAN["branch_guard"] = what
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": f"phi (p4-phi): this session is a child, and {what} is "
                                                               f"asked first: a child works on its "
                                                               f"parent's branch in the parent's checkout, so its work "
                                                               f"needs no merge."}}


STORE_MOVE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b([^\n|;&]*?)\b(push|pull)(?![\w-])([^\n|;&]*)")
DASH_C = re.compile(r"(?:^|\s)-C\s+(\S+)")
CD = re.compile(r"(?:^|&&|;|\n)\s*(?:cd|pushd|Set-Location)\s+(\S+)\s*(?=&&|;|\n|$)")


def store_root(path):
    """The store a folder is in: its `.claude/p4`, when the folder's git checkout is the store itself; '' for any
    other folder, among them a clone kept under the store's temportal/tmp."""
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
    """PreToolUse on a shell call: a hand `git pull`, `git push` or force-push in a store is asked first, and
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
                                   "permissionDecisionReason": f"phi (p4-phi): this is {what} in the store {store}. "
                                                               f"A store moves only by `{sync}`, since two machines "
                                                               f"write the same files and a plain merge or a "
                                                               f"line-union damages them. Then check each entry the "
                                                               f"sync names as changed."}}


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


REPLAY_HOLD = 2 * 1024 * 1024    # how far behind the transcript's end a call with no result still holds the place


def resume_at(waiting, end, hold=None):
    """Where the next replay starts: at the first call still without a result, so no call is passed before its
    result is in, whatever lines lie between the two, such as a subagent's rows, a notification or a message that
    arrived while the call ran. A call that far behind the end was cut off and will get none, so it holds nothing."""
    hold = REPLAY_HOLD if hold is None else hold
    live = [w for w in waiting if end - w <= hold]
    return min(live) if live else end


def replay(me, s, transcript):
    """The task-list calls of the transcript that no hook handled, applied in order, at each message and each Stop,
    each once by its tool_use_id. Returns the step boundary text of the last one, ''
    for none. A session takes a plugin's hooks when it loads the plugin, and `/reload-plugins` applies later edits,
    so a session whose hook list lacks the retrieval hooks' entries has only phi.py's own, and its calls are read
    back here."""
    if not transcript or not os.path.exists(transcript):
        return ""
    # Read from where the last replay stopped, kept beside the per-call markers, so a message or a Stop parses only
    # the lines written since, not megabytes of transcript. The place kept is the first call still without a result,
    # so a call is never passed before its result is in.
    state_path = os.path.join(session_dir(me.home, me.id), ".calls", "replay.json")
    state = read_json(state_path)
    try:
        size = os.path.getsize(transcript)
    except OSError:
        return ""
    start = state.get("offset") if state.get("path") == transcript else None
    known = isinstance(start, int) and 0 < start <= size
    if not known:
        start = max(0, size - TRANSCRIPT_BYTES)
    rows, end = read_from(transcript, start, partial=not known and start > 0)
    calls, results, where = [], {}, {}
    for at, d in rows:
        c = (d.get("message") or {}).get("content")
        for b in c if isinstance(c, list) else []:
            if not isinstance(b, dict):
                continue
            if d.get("type") == "assistant" and b.get("type") == "tool_use" \
                    and b.get("name") == "mcp__ccd_turn__update_plan":
                calls.append(b)
                where[b.get("id")] = at
            elif d.get("type") == "user" and b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = result_text(b)
    resume = resume_at([where[b.get("id")] for b in calls if b.get("id") not in results], end)
    if state.get("path") != transcript or state.get("offset") != resume:
        try:
            write_atomic(state_path, json.dumps({"path": transcript, "offset": resume}) + "\n")
        except OSError:
            pass
    text = ""
    last_list = max((k for k, b in enumerate(calls) if b["name"] == "mcp__ccd_turn__update_plan"
                     and isinstance((b.get("input") or {}).get("items"), list)), default=0)
    for b in calls[last_list:][-200:]:            # an earlier task list is replaced whole by the latest list
        tid = b.get("id")
        if tid not in results:
            continue                                # still running, or its result not written yet
        payload = {"tool_name": b["name"], "tool_input": b.get("input") or {}, "tool_response": results[tid],
                   "tool_use_id": tid, "transcript_path": transcript}
        if not once(me.home, me.id, "plan", payload):
            continue
        text = plans.record(me.home, load_session(me.home, me.id) or s, payload["tool_input"]) or text
    RAN["replayed"] = len(calls)
    return text


def routed(name, payload):
    """A phi.py handler run from a retrieval hook's entry, with the hook output phi.py would give and its log
    line."""
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
    """PreToolUse on Agent, from the retrieval hook's entry: the text for the subagent's start, its step and its
    slice. It keeps no record of the launch."""
    me = Me(payload)
    if not me.home or not me.id:
        return ""
    s = load_session(me.home, me.id)
    if not s:
        return ""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    text = plans.agent_launch(me.home, s, inp)
    RAN["agent"] = "launch"
    return text


def h_agent_start(payload):
    """SubagentStart, from the retrieval hook's entry: the subagent bound by the `agent_id` the input carries to the
    launching session's step in progress, and its marker opened under phi/.agents/ for recall-hook.sh's gate. An
    input with no `agent_type` is no subagent the Agent tool started and is left alone."""
    agent_id = str(payload.get("agent_id") or "")
    me = Me(payload)
    if not agent_id or not payload.get("agent_type") or not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not s or not plans.agent_bind(me.home, s, agent_id, str(payload.get("agent_type"))):
        return None
    try:
        os.makedirs(os.path.dirname(agent_marker(me, agent_id)), exist_ok=True)
        with open(agent_marker(me, agent_id), "w", encoding="utf-8") as f:
            f.write(me.id + "\n")
    except OSError:
        pass
    RAN["agent"] = "bound"
    return None


def agent_transcript(payload):
    """The path of a subagent's own transcript, from a hook input inside the subagent, '' when the input leads to
    none. The input's `transcript_path` is the session's, and sub-agents.md puts the subagent's beside it, in
    "`~/.claude/projects/{project}/{sessionId}/subagents/`. Each transcript is stored as `agent-{agentId}.jsonl`"."""
    main, agent_id = str(payload.get("transcript_path") or ""), str(payload.get("agent_id") or "")
    if not main or not agent_id:
        return ""
    main, name = os.path.expanduser(main), f"agent-{agent_id}.jsonl"
    if os.path.basename(main) == name:
        return main
    under = [os.path.join(os.path.dirname(main), str(payload.get("session_id") or ""), "subagents", name),
             os.path.join(os.path.splitext(main)[0], "subagents", name)]
    return next((x for x in under if os.path.isfile(x)), under[-1])


def h_agent_call(payload):
    """A subagent's tool call, before it runs, routed from the retrieval hook's check: warned of what changed beside
    the launching session, held against its own transcript for when it started and what it has heard already.
    recall-hook.sh lets a subagent's check through only while phi/.agents/ names it."""
    agent_id = str(payload.get("agent_id") or "")
    me = Me(payload)
    if not agent_id or not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not s:
        return None
    text = plans.agent_warn(me.home, s, agent_id, agent_transcript(payload))
    RAN["agent"] = "warned" if text else "checked"
    return text or None


WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def transcript_calls(path):
    """The tool calls of a transcript, each as its name and input, in order; none when it cannot be read."""
    out = []
    for d in read_rows(path) if path else []:
        content = (d.get("message") or {}).get("content") if d.get("type") == "assistant" else None
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append({"name": b.get("name"), "input": b.get("input")})
    return out


def agent_writes(calls):
    """The files a subagent's calls wrote, by Edit, Write, MultiEdit or NotebookEdit, each once."""
    out = []
    for c in calls:
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if c.get("name") in WRITE_TOOLS and path and path not in out:
            out.append(path)
    return out


def h_agent_stop(payload):
    """SubagentStop, from the retrieval hook's entry: the subagent's entry closed, and the files its own transcript
    shows it wrote kept on it for the ledger. The input names that transcript as `agent_transcript_path`."""
    agent_id = str(payload.get("agent_id") or "")
    me = Me(payload)
    if not agent_id or not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if s and plans.agent_stop(me.home, s, agent_id):
        RAN["agent"] = "stopped"
    wrote = agent_writes(transcript_calls(payload.get("agent_transcript_path") or ""))
    if s and wrote and plans.agent_wrote(me.home, me.id, agent_id, wrote):
        RAN["agent_wrote"] = len(wrote)
    try:
        os.remove(agent_marker(me, agent_id))
    except OSError:
        pass
    return None


HOOKS = {"session-start": ("SessionStart", h_session_start),
         "user-prompt-submit": ("UserPromptSubmit", h_user_prompt_submit),
         "stop": ("Stop", h_stop),
         "stop-failure": ("StopFailure", h_turn_end),
         "session-end": ("SessionEnd", h_turn_end),
         "start-advice": ("PreToolUse", h_start_advice),
         "branch-guard": ("PreToolUse", h_branch_guard),
         "store-guard": ("PreToolUse", h_store_guard),
         "plan": ("PostToolUse", h_plan),
         "memory-gap": ("PostToolUse", h_memory_gap),
         "task-stop": ("PostToolUse", h_task_stop),
         "self-archive": ("PreToolUse", h_self_archive)}
ROUTED.update({k: HOOKS[k] for k in ("start-advice", "branch-guard", "store-guard", "plan", "memory-gap",
                                     "self-archive", "task-stop")})
ROUTED["nudge"] = ("PreToolUse", h_nudge)
ROUTED["puppeteer-tool"] = ("PreToolUse", h_puppeteer_tool)
ROUTED["wrap-up"] = ("PostToolUse", h_wrap_up)
HOOKS["go-guard"] = ROUTED["go-guard"] = ("PreToolUse", h_go_guard)
HOOKS["restart-check"] = ROUTED["restart-check"] = ("PreToolUse", h_restart_check)
ROUTED.update({"agent-launch": ("PreToolUse", h_agent_launch), "agent-start": ("SubagentStart", h_agent_start),
               "agent-pre": ("PreToolUse", h_agent_call), "agent-stop": ("SubagentStop", h_agent_stop)})


def hook_main(name):
    """A hook never fails a call and says nothing without something to say; a handler that raises leaves one line
    naming the hook and the error in its session's log.jsonl."""
    payload = {}
    try:
        if os.environ.get("P4_PHI") == "0" or name not in HOOKS:
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        event, fn = HOOKS[name]
        started = time.time()
        if name in ROUTED:                          # a dedicated entry for a routed check: once, as routed
            me = Me(payload)
            if me.home and me.id and not once(me.home, me.id, name, payload):
                return 0
            RAN.update(home=me.home, session=me.id)
        text = fn(payload)
        if isinstance(text, dict):                  # a hook that answers with its own JSON, such as start-advice
            log_run(name, json.dumps(text), started)
            sys.stdout.write(json.dumps(text))
            return 0
        log_run("stop" if fn is h_turn_end else name, text, started)   # a turn's end, as a Stop logs it
        if text:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    except Exception as e:  # noqa: BLE001
        log_failure(name, payload, e)
    return 0


def log_failure(name, payload, error):
    """One line in the session's log.jsonl for a hook whose handler raised, so that no failure is silent; it writes
    nothing when no session can be told from the call, and never raises itself."""
    try:
        home, sid = RAN.get("home"), RAN.get("session")
        if not home or not sid:
            me = Me(payload if isinstance(payload, dict) else {})
            home, sid = me.home, me.id
        if home and sid:
            append_line(os.path.join(session_dir(home, sid), "log.jsonl"),
                        {"time": now(), "hook": name, "error": f"{type(error).__name__}: {error}"[:300]})
    except Exception:  # noqa: BLE001
        pass


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
    """Put a session under another one, or with no `under` detach it to top level: session.json's `spawnedFrom` is
    rewritten, its latest turn is handed to where it now belongs, and the reports it left behind note that it left.
    The app's own nesting does not follow, and the app's record does not move it back."""
    sid, under = safe_id(sid), safe_id(under)
    s = load_session(home, sid)
    if not s.get("sessionId"):
        raise ValueError(f"no session {sid}")
    if under:
        ensure_session(home, under)
        if under == sid or sid in chain_of(home, under):
            raise ValueError("a session cannot be put under itself or under a session below it")
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
                    {"time": now(), "sessionId": sid, "title": name_of(s), "turn": turns[-1]})
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
                walk(s["sessionId"], depth)          # no record and no turns: an empty entry, its children kept
                continue
            state = ("done" if turns[-1].get("done") else "not shown done") if turns else "no turn yet"
            out.append(f"{'  ' * depth}- \"{title_of(s)}\" `{s['sessionId']}`: {state}, "
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
    ap = argparse.ArgumentParser(description="phi.py: what linked sessions hand each other")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("note", "done", "task", "show", "tree", "background", "detach", "reparent", "shard", "disposable",
                 "request", "proof", "controls", "files"):
        p = sub.add_parser(name)
        p.add_argument("--p4", default="", help="the store the sessions' files live in, this session's when left out")
        p.add_argument("--session", default="", help="the sessionId, this session's when left out")
        if name == "note":
            p.add_argument("claim")
            p.add_argument("--source", default="")
            p.add_argument("--kind", default="", help="free text, such as ruled-out, decision, machine or code")
        if name in ("done", "task"):
            p.add_argument("text")
        if name == "proof":
            p.add_argument("command", help="the regression test that proves this session's issue fixed, run from here")
        if name == "show":
            p.add_argument("which", nargs="?", default="")
        if name == "detach":
            p.add_argument("moved", nargs="?", default="", help="the session to detach to top level, this one when "
                                                                "left out")
        if name == "reparent":
            p.add_argument("moved")
        if name == "shard":
            p.add_argument("paths", nargs="*", help="the owned paths, paths or globs this session alone may change; "
                                                    "none shows them")
        if name == "reparent":
            p.add_argument("under")
        if name == "files":
            p.add_argument("paths", nargs="*", help="the paths this session still writes, replacing its declared "
                                                    "write set; none shows it")
            p.add_argument("--release", action="store_true", help="hold no file any more")
        if name == "request":
            p.add_argument("title", nargs="?", default="", help="the new orchestrator's title")
            p.add_argument("--withdraw", default="", metavar="REQUEST",
                           help="withdraw a pending start request by its id, so it is never handed out")
            p.add_argument("--brief", default="", help="the new orchestrator's whole brief")
            p.add_argument("--brief-file", default="", help="a file holding the brief")
            p.add_argument("--background", default="", help="the start background, one built from this session's "
                                                              "title and the project when left out")
            p.add_argument("--to-puppeteer", action="store_true",
                           help="ask this session's puppeteer for a new orchestrator, and start none; any other "
                                "start this session may not make is a suggested task card, not a request")
        if name == "controls":
            p.add_argument("ids", nargs="*", help="orchestrators this puppeteer controls; none prints "
                                                  "where each stands")
            p.add_argument("--drop", action="append", default=[], help="a session it no longer controls")
            p.add_argument("--hand", default="", help="the fresh puppeteer this one hands over to")
            p.add_argument("--from", dest="take", default="", help="the puppeteer that handed over to "
                                                                   "this one")
            p.add_argument("--decline", nargs=2, metavar=("REQUEST", "WHY"), help="a request addressed to it")

    def common(p):
        p.add_argument("--p4", default="", help="the store the sessions' files live in, this session's when left out")
        p.add_argument("--session", default="", help="the sessionId, this session's when left out")
    puppeteer.add_parsers(sub, common)
    a = ap.parse_args(argv)
    me = Me(session=a.session, p4=a.p4)
    if not me.home or not os.path.isdir(me.home):
        print("phi: no store found; pass --p4 <repository>/.claude/p4", file=sys.stderr)
        return 2
    configure(me.home)
    try:
        if a.cmd in puppeteer.COMMANDS:
            return puppeteer.command(a, me)
        if a.cmd == "tree":
            print(tree_text(me.home) or "no sessions yet")
            return 0
        if a.cmd == "detach":
            if not a.moved and not me.id:
                print("phi: name the session to detach to top level, or run this from inside it", file=sys.stderr)
                return 2
            a.moved = a.moved or me.id
            print("detached to top level: it is an orchestrator now" if reparent(me.home, a.moved, "", "detached")
                  else "already an orchestrator")
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
            print("phi: this is not a session, since the environment holds no session id; pass --session",
                  file=sys.stderr)
            return 2
        s = ensure_session(me.home, me.id, me.rec, me.cli)
        if a.cmd == "shard":
            save_session(me.home, s)
            if not a.paths:
                print("\n".join(relay.shard_of(s)) or "this session declared no owned paths")
                return 0
            lines = relay.set_shard(me.home, s["sessionId"], a.paths, os.getcwd())
            print("kept as this session's owned paths: "
                  + ", ".join(relay.shard_of(load_session(me.home, s["sessionId"]))))
            for line in lines:
                print("phi: " + line)
            return 0
        if a.cmd == "files":
            if a.release and a.paths:
                raise ValueError("pass the paths this session still writes, or --release for none, not both")
            if not a.paths and not a.release:
                held = s.get("fileSet") if isinstance(s.get("fileSet"), list) else None
                print("this session declared no write set" if held is None else
                      "this session holds no file" if not held else "\n".join(held))
                return 0
            new, freed = set_files(me.home, s, a.paths, os.getcwd())
            render_page(me.home, s["sessionId"])
            print("this session holds no file now" if not new else "kept as this session's write set: "
                  + ", ".join(new))
            if freed:
                print("released: " + ", ".join(freed) + ". A start on them is no longer held by this session.")
            return 0
        if a.cmd == "controls":
            if not controls.is_puppeteer(s, me.store):
                held = controls.section_of(s["sessionId"])
                raise ValueError(f"this session is not a puppeteer: that is an orchestrator ezexe filed "
                                 f"in the sidebar section \"{controls.section_name(me.store) or controls.SECTION}\", "
                                 f"and the app's file shows this one in " + (f"\"{held}\"" if held else "no section")
                                 + (", started by another session" if spawned_from(s) else ""))
            if a.hand:
                print(controls.hand(me.home, s, a.hand))
            if a.take:
                print(controls.take(me.home, s, a.take))
            if a.decline:
                print(controls.decline(me.home, s, a.decline[0], a.decline[1]))
            for line in controls.control(me.home, s, a.ids, a.drop):
                print(line)
            s = load_session(me.home, s["sessionId"])
            controls.board(me.home, s)
            print(controls.controls_text(me.home, s))
            return 0
        if a.cmd == "request" and a.withdraw:      # a request nobody should start any more
            if a.title or a.brief or a.brief_file:
                raise ValueError("--withdraw takes a request's id and nothing else")
            print(starts.withdraw(me.home, a.withdraw.strip(), s["sessionId"]))
            return 0
        if a.cmd == "request":
            if not a.to_puppeteer:                 # the app's suggested task card holds any other start
                raise ValueError(starts.CARD + "; `request` keeps only a request to this session's puppeteer, "
                                               "with `--to-puppeteer`")
            brief = a.brief
            if a.brief_file:
                with open(a.brief_file, encoding="utf-8") as f:
                    brief = f.read()
            save_session(me.home, s)
            pid, _ = controls.puppeteer_of(s, me.store)    # a new orchestrator is asked of the puppeteer
            if not pid:
                raise ValueError("this session has no puppeteer: no session filed in the sidebar "
                                 "section lists it under `controls`")
            rid, new = starts.add(me.home, s["sessionId"], a.title, brief, "fresh", background=a.background,
                                  declared=True, to=pid)
            print(starts.asked_text(rid, new, clean(a.title), pid, controls.full_title(pid)))
            return 0
        if a.cmd == "proof":
            if not isinstance(s.get("issue"), dict):
                raise ValueError("this session has no issue to prove: a writing child's issue is taken at its "
                                 "first message or its first task list")
            s["issue"]["test"] = {"cmd": a.command.strip(), "cwd": os.getcwd(), "step": "phi.py proof"}
            save_session(me.home, s)
            print(f"kept: p4-phi re-runs `{a.command.strip()}` here at Stop on the final head, before "
                  f"{s['issue']['repo']}#{s['issue']['number']} lets this session be counted as archived")
            return 0
        if a.cmd == "disposable":
            s["disposable"] = True
            save_session(me.home, s)
            print("this session is counted as archived when its work is done: its outcome is kept as a replaces: "
                  "note on its parent session")
            return 0
        if a.cmd == "note":
            print("kept" if note_add(me.home, s["sessionId"], a.claim, a.source, a.kind, me.cli) else "already kept")
        elif a.cmd == "done":
            if len(clean(a.text)) < 8:
                raise ValueError("say what was run and what it showed")
            s["done"] = {"text": clean(a.text)[:400], "time": now()}
            save_session(me.home, s)
            print("this turn will be kept as done")
            if spawned_from(s):                    # the button is for an orchestrator only
                print(relay.CHILD_DONE)
            else:
                print(relay.BUTTON)
            try:                                   # the issue it closes, and what that still owes
                line = issues.done_text(me.home, s, os.getcwd()) if spawned_from(s) else ""
            except Exception:  # noqa: BLE001
                line = ""
            if line:
                print(line)
        elif a.cmd == "task":
            task = cut(a.text.strip(), TASK_CHARS)
            if len(clean(task)) < 12:
                raise ValueError("a task is a whole sentence")
            if s.get("task"):
                s.setdefault("earlierTasks", []).append({"task": s["task"], "until": now()})
            s["task"], s["taskAt"] = task, now()
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
