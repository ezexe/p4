#!/usr/bin/env python3
"""phi.py: what linked sessions hand each other, kept on the app's own session tree.

Each session has a folder phi/sessions/<sessionId>/ in the tree its store lives in, whose root store is that of its
orchestrator's project, or the shared store that p4.json's `phi.home` names. A session another session started has
it in a store of its own nested in its starter's, `.claude/p4` under it, with its phi/node.json; a top session, and
one whose folder was made before nodes, has it in the root store, relay._dir. The folder holds session.json, the
app's fields for the session with its task; turns.jsonl, a line for each finished turn; notes.jsonl; reports.jsonl,
the reports of its workers; log.jsonl, a line for each hook call; and session.md, the session as one page.
The reports of orchestrators are in <home>/phi/reports.jsonl.

A hook's payload does not say which session started this one. The app's record says it in `spawnedFrom.sessionId`,
but for a fresh child the app may write it only after the first message, so the notes folder that message names is
read first and the record corrects it. `detach` and `reparent` rewrite it in session.json.

The hooks, each in its h_ function:
- SessionStart gives the start background to a fork, after a clear, with the session's own turns and the address
  book whole, and to a session no app runs. After a compaction the summary keeps the conversation, so it gives the
  address book's changed entries with the path of book.md. It hands no rule, and p4-phi adds no section to
  the system prompt: `phi.py rules` answers the hooks module which tools the session is not offered.
- UserPromptSubmit keeps the first request as the task and gives the start background with the first message when
  the start did not, then the reports of the workers that finished a turn since the last look, the address book's
  changes and what the sessions beside it changed. A start and every message pass whole, the lines that ask
  the session to act first, past the app's cap to its own file.
- Stop keeps the turn and appends it to the parent session's reports, sends the turn back while steps the session
  tree can settle are open, runs a writing child's issue gate, counts a child marked report when done as archived,
  tells the orchestrator to push issue-closing commits and makes the anchors.
- The checks before a tool call are run by the plugin's hooks module, through `hook.py lookup-check`, and the
  records after one ride on hook.py's entries, both through `routed`.

Commands: note, done, task, shard, show, tree, background, detach, reparent, disposable, request, proof and controls,
with the watcher's commands from puppeteer.py; `--help` gives the arguments of each. `rules` is the hooks module's
own: it prints the text of the system prompt's section as one JSON line. `goal` prints how a session's native goal
stands, `goal on` and `goal off` write the setting, `goal ask` keeps the condition a session states as the goal it
asks for, and `goal set` is the hooks module's word that the goal command set it.

Settings: <home>/phi/phi.json, every key optional: `background`, `reports`, `turns`, `book`, `rules`,
`background_chars`, `reports_chars` and `wait_s`, `goal`, which gives a worker Claude Code's own goal unasked and is
off unless set true or P4_PHI_GOAL is 1, and `puppeteer`, which puppeteer.on reads. The `phi`
section of p4.json: `plan_mode` and `child_levels`, read from the
session's own store, `home`, which names a shared store for the session tree. P4_PHI=0 turns the plugin off, P4_PHI_BOOK=0 the address book beside a
message and P4_PHI_RULES=0 the memory lines. P4_PHI_WAIT sets how long a first message waits for the app's
record, and P4_PHI_APP_SESSIONS the folder of the app's records.
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
import node as nd  # noqa: E402  the content words two texts share
import p4conf  # noqa: E402  the store's layout, each plugin's files in .claude/p4/<plugin>/
import plans  # noqa: E402  each session's task list with step addresses, which its parent's anchor holds
import relay  # noqa: E402  owned paths, deltas and anchors, which keep linked sessions in step while they work
import starts  # noqa: E402  the files a brief covers, a start's checkout, and a start request to a puppeteer
import sections  # noqa: E402  an approved plan's sections as the starts of the workers that land them
import shared  # noqa: E402  what a worktree's session takes from its main checkout, and the links a worktree holds
import issues  # noqa: E402  a writing child's issue, its Closes #N commit, regression test, push and archive
import puppeteer  # noqa: E402  the watcher's ledger, routing, start drafts, the gate, routes, the meta pass
import rows  # noqa: E402  whose message a prompt is, by the origin the hooks module kept of it

puppeteer.PHI = sys.modules[__name__]   # phi.py runs as a script, so puppeteer.py is handed this module, not a copy
import controls  # noqa: E402  a puppeteer, and the sessions it controls

controls.PHI = sys.modules[__name__]
import upkeep  # noqa: E402  the upkeep of a session tree: archive calls, follow-through, waits and leftovers
import cards  # noqa: E402  the approval cards that can stop a started session, and what is settled before its start

upkeep.PHI = sys.modules[__name__]

BACKGROUND = True
REPORTS = True
TURNS = True
BOOK = True
RULES = True
GOAL = False                     # phi.json `goal`: true has a worker's line `Done looks like:` set as its native goal
WORKER_PROFILE = "p4-workers"    # phi.json `worker_profile`: the Anthropic profile a terminal worker names; "" is off
WORKER_MODE = "print"            # phi.json `worker_mode`: `print` starts a terminal worker as `claude -p`, `interactive` as a tab
WORKER_MODES = ("print", "interactive")
WORKER_PAIRS = {"print": "p4-workers", "interactive": ""}   # the profile a mode pairs with where nothing sets one
APP_TOOLS = True                 # phi.json `app_tools`: false keeps the hooks module from asking the app's own tools for sessions
# hooks.md, "JSON output": "A hook's `additionalContext`, `systemMessage`, and `initialUserMessage` strings, and its
# plain stdout, are capped at 10,000 characters", each string "measured separately", and over the limit "Claude Code
# saves the output to a file in the session directory. It replaces the output with the file path and a preview of up
# to the first 2,000 characters." p4-phi leaves that cap and its overflow file to the app: it keeps no ceiling of its
# own on what it adds beside a start or a prompt and no page for what would pass one. The same section says "Claude
# Code doesn't ask Claude to read the file, so keep anything Claude must always see within the cap", which is what
# the app's cut at a character count lacks. So acting_first puts the lines that ask the session to act first, inside
# the preview, and the rest follows whole.
APP_CAP = 10000
APP_PREVIEW = 2000
RELAY_CHARS = 4000               # of what the sessions beside this one changed, beside one prompt: relay.rebase's room
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
            "goal": "GOAL", "app_tools": "APP_TOOLS", "worker_profile": "WORKER_PROFILE",
            "worker_mode": "WORKER_MODE"}
SHELL_TOOLS = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
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
    """The JSON object at `path`, {} where there is none, with another process's replace of the file waited out."""
    d, _ = p4conf.load_json(path)
    return d if isinstance(d, dict) else {}


def write_atomic(path, text):
    """`text` written to `path` whole or not at all, by the kit's one writer, which waits out a reader that has
    the file open and leaves no temp: a move made once lost a session's whole save, and the hook with it."""
    p4conf.write_whole(path, text)


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
    """A session's folder: in its node's store where it has one, else the flat folder of the root store."""
    return relay._dir(home, sid)


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
    if os.environ.get("P4_PHI_GOAL") in ("0", "1"):
        globals()["GOAL"] = os.environ["P4_PHI_GOAL"] == "1"
    if os.environ.get("P4_PHI_APP_TOOLS") in ("0", "1"):
        globals()["APP_TOOLS"] = os.environ["P4_PHI_APP_TOOLS"] == "1"
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


# --- the app's own tools for sessions, asked by the hooks module -----------------------------------------------------
#
# The record files below are the desktop app's own, and no docs page describes them. The app has tools that answer a
# session, `mcp__ccd_session_mgmt__get_session` and `mcp__ccd_session_mgmt__list_sessions`, which a command hook
# cannot call and the plugin's hooks module can, by `$.tool.call`. Unless phi.json turns `app_tools` off, the module
# asks both after a look and writes what they answered to APP_FILE: `self`, the session's own answer, and
# `sessions`, the sessions linked to it. A session is read from that file first, and from its record file where the
# file is absent, older than APP_FRESH_S or does not hold the session: a session the app did not start has no such
# tool, as a `claude -p` run or a terminal worker, and a hook can run before the module's first look.
#
# The tools answer less than a record holds, so AppRow answers a key the tools gave and reads the record file, once,
# for any other. They name no CLI session, so `cliSessionId` and `lastAssistantCliSessionId`, which own_host and
# own_clis read, are the record's. APP_SAME are the keys both give under one name, and `parentSessionId` of
# `get_session` and `startedBy` of `list_sessions` are the record's `spawnedFrom.sessionId`. Held against the record
# files of this machine, the starter 186 answers of `get_session` and 936 rows of `list_sessions` named was the
# record's in each. An answer that names no starter leaves `spawnedFrom` to the record: a row of `list_sessions`
# names none for a session moved to top level, where the record still does, in 170 rows, and started_by waits on
# the record of a session just started, which the app writes its starter into after the session's first hook.
# `worktreePath` differed in 11 answers of 13 and is left to the record too.
APP_FILE = "app.json"            # in rows.origin_dir of the CLI session, else in the session's folder in the tree's store
APP_FRESH_S = 300.0              # how long the file is believed after the module wrote it
APP_SAME = ("sessionId", "title", "cwd", "originCwd", "isArchived", "permissionMode", "branch")
APP_AT = {"cli": "", "project": "", "folder": ""}   # whose file is read: Me sets it, and the environment says it before
ANSWERS = {}                     # APP_FILE's path -> (its sessions by id, the id of `self`), read once a process


class AppRow(dict):
    """A session as the app's tools answered it, under the names its record file gives the same things. A key the
    tools did not answer is read from the record file, which is opened once and only then."""

    def __init__(self, sid, given):
        super().__init__(given)
        self.sid, self.rest = sid, None

    def record(self):
        if self.rest is None:
            self.rest = read_record(safe_id(self.sid) + ".json")
        return self.rest

    def get(self, key, default=None):
        return dict.get(self, key, default) if dict.__contains__(self, key) else self.record().get(key, default)

    def __missing__(self, key):
        return self.record()[key]

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self.record()


def from_tools(row):
    """A tool's answer of one session under its record's names. An answer with no starter says nothing of one."""
    out = {k: row[k] for k in APP_SAME if row.get(k) is not None}
    above = row.get("parentSessionId") or row.get("startedBy")
    if above:
        out["spawnedFrom"] = {"sessionId": above, **({"name": row["name"]} if row.get("name") else {})}
    return out


def app_files():
    """Where the hooks module may have written the app's answers for this process's CLI session."""
    cli = APP_AT["cli"] or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    project = APP_AT["project"] or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    served = rows.origin_dir(project, cli) if cli else ""
    return [os.path.join(d, APP_FILE) for d in (served, APP_AT["folder"]) if d]


def app_answers():
    """What the app's tools answered the hooks module, from the first file that is there and fresh: each session it
    holds by its id, as the tool gave it, and the id of the session the file is of. ({}, '') where no such file is."""
    for path in app_files():
        if path not in ANSWERS:
            held, own = {}, ""
            try:
                fresh = 0 <= time.time() - os.path.getmtime(path) <= APP_FRESH_S
            except OSError:
                fresh = False
            d = read_json(path) if fresh else {}
            mine = d.get("self") if isinstance(d.get("self"), dict) else {}
            for row in [mine] + [r for r in (d.get("sessions") if isinstance(d.get("sessions"), list) else [])
                                 if isinstance(r, dict)]:
                sid = str(row.get("sessionId") or "")
                if sid.startswith("local_") and sid not in held:
                    held[sid] = row
            ANSWERS[path] = (held, str(mine.get("sessionId") or "") if mine.get("sessionId") in held else "")
        if ANSWERS[path][0]:
            return ANSWERS[path]
    return {}, ""


def app_answer(sid):
    """A session as the app's tools answered it, an AppRow, or None where the module left no fresh answer of it."""
    row = app_answers()[0].get(str(sid or ""))
    return AppRow(sid, from_tools(row)) if row else None


RECORDS = {}


def app_record(sid):
    """The app's record of a session, {} when there is none to read: what the app's tools answered the hooks module
    of it, where they did, else its record file. Read once a process."""
    name = safe_id(sid) + ".json"
    if not sid or not name.startswith("local_"):
        return {}
    if sid not in RECORDS:
        RECORDS[sid] = app_answer(sid) or read_record(name)
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
    if cli == (APP_AT["cli"] or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""):
        own = app_answers()[1]                     # the module of this CLI session asked the app which session it is
        if own:
            return app_record(own)
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


class Me:
    """The session a hook or a command is running for: its sessionId, its CLI session, the app's record, its home."""

    def __init__(self, payload=None, session="", p4="", hint="", host=None):
        payload = payload or {}
        self.hint = ""
        self.cli = str(payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
        APP_AT.update(cli=self.cli, folder="",       # whose answers of the app's tools app_record reads first
                      project=os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
        self.title = clean(payload.get("session_title"))[:120]
        host = (os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or "") if host is None else host
        # A CLI id equal to the host id without "local_" is normal: the app gives many workers that pair of
        # ids, so it is no stray id.
        self.rec = app_record(session or host) if (session or host) else record_of_cli(self.cli)
        self.id = session or host or str(self.rec.get("sessionId") or "") or self.cli
        project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        self.home = p4 or ""
        self.store = store_at(project) or p4 or ""     # this project's own store: its memory and rules
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
        if self.home and self.id and not session:  # where the module writes them for a project with no store
            APP_AT["folder"] = session_dir(self.home, self.id)
            # That file was not known while the records above were read, so this session's and its starter's came
            # from their record files. Seen in the desktop app: a session in a worktree, whose project has no store,
            # read all three sessions above it from the files beside a fresh answer of each. So what the answers
            # hold is read from them from here on, as in a project whose served folder is known from the start.
            held = app_answers()[0]
            for sid in [k for k, v in RECORDS.items() if k in held and not isinstance(v, AppRow)]:
                del RECORDS[sid]
            if self.id in held:
                self.rec = app_record(self.id)
        if self.title and self.id:
            GIVEN_TITLES[self.id] = self.title
        if host and not session and not own_host(self, host, payload):
            RAN["host"] = "inherited"
            self.__init__(payload, session, p4, hint, host="")     # the session this process is, by its CLI id
            return
        project_conf(self.store)
        plans.PARENT_EFFORT = own_effort(self, payload, other=bool(session))


def own_host(me, host, payload):
    """Does the host session id of the environment name this process. The desktop app sets
    CLAUDE_CODE_HOST_SESSION_ID for the Claude Code process it starts, and every process that one starts inherits
    it: a scripted run, `claude -p` from a session's shell, carries its starter's id and is no such session. The
    app's record of a session names its CLI session, `cliSessionId`, so a host id is the process's own where that
    record names this process's CLI id, where the record names none to hold it against, or where the CLI id is the
    host id without its prefix. A session goes on under a new CLI id after a /clear or a resume, and the
    SessionStart that says so is the host's own; phi's record of the session, which keeps every CLI id it ran
    under, then answers for each hook after it while the app's record is behind. A scripted run starts with the
    source `startup` under an id neither record names, so it is the CLI session it is and no session of the app."""
    cli = me.cli
    if not cli or safe_id(host) == "local_" + cli:
        return True
    if me.home and cli in (load_session(me.home, host).get("cliSessionIds") or []):
        return True                                # phi's own record answers before the app's record file is opened
    named = {str(me.rec.get(k) or "") for k in ("cliSessionId", "lastAssistantCliSessionId")} - {""}
    if not named or cli in named:
        return True
    if payload.get("hook_event_name") == "SessionStart" and payload.get("source") in ("clear", "resume"):
        return True
    return bool(me.home) and cli in (load_session(me.home, host).get("cliSessionIds") or [])


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
    for k in ("plansSeen", "requestAnswers"):
        if isinstance(disk.get(k), dict):
            s[k] = {**disk[k], **(s.get(k) or {})}
    for k in ("rootStep", "rootLeft", "shard", "disposable", "doneRetired", "archived", "appRoot", "issue",
              "issueLooked", "findingsTold", "puppeteerTold", "effort", "kidCommits", "planMode",
              "planFile"):
        if k in disk and k not in s:
            s[k] = disk[k]
    if not s.pop("_goalSet", None):                # only the goal commands change the goal and the ask, save_goal:
        for k in ("goal", "goalAsk"):              # a hook that read the session before one ran keeps its word
            if k in disk:
                s[k] = disk[k]
            else:
                s.pop(k, None)
    if int(disk.get("anchorSeen") or 0) > int(s.get("anchorSeen") or 0):
        s["anchorSeen"] = disk["anchorSeen"]
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
    for c in ([] if cli and cli in (s.get("cliSessionIds") or []) else own_clis(sid, rec, cli)):   # held already: no read
        if c not in s.setdefault("cliSessionIds", []):
            s["cliSessionIds"].append(c)
            changed = True
    above = spawned_from(s)
    if above and depth < CHAIN_MAX and not load_session(home, above).get("sessionId"):
        ensure_session(home, above, depth=depth + 1)
    if changed and above and load_session(home, above).get("sessionId"):
        claim_node(home, sid, above)
    if changed:
        save_session(home, s)
    return s


def claim_node(home, sid, starter):
    """The store of a session that `starter` started, claimed in the store that holds the starter's folder where
    the session has neither a node nor a flat folder yet; a flat starter is in the root, so its child is the root's.
    A session whose flat folder is there, as one a hook that failed before ensure_session made, stays flat. The
    folder this process reads the app's answers from follows the session's, where it named the flat one."""
    if relay.nodes(home).get(sid) or os.path.isdir(relay.flat(home, sid)):
        return ""
    starter = safe_id(starter)
    store = relay.nodes(home).get(starter) or home
    made = relay.claim(home, store, sid, "session", starter)
    if made and APP_AT.get("folder") == relay.flat(home, sid):
        APP_AT["folder"] = session_dir(home, sid)
    return made


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

def request_of(prompt, by=""):
    """The request inside a message. A worker gets its task under leading <system-reminder> blocks and a
    `Background ... Task:` wrapper, and a forked one under the app's line `Task (from the session that started this
    one):`; this takes those off. A `<pasted_content id="..">` block is what a person pasted, so its inner text is
    the request, also when the message is nothing but the block. '' when nothing is left or what is left is Claude
    Code speaking. `by` is whose words the prompt is by its origin, rows.whose: a background task's notification,
    a plugin's prompt and a prompt a schedule fired hold no request, ezexe's own message is one whatever it opens
    with, and where the origin does not say, the opening of the text tells, the sweep's own prompt by
    plans.SWEEP_MARK among them. A message that opens with a slash command holds none whoever sent
    it, relay.command_word: `/goal <condition>` reaches the prompt hooks as typed, Claude Code runs it, and routing
    drafted a session from its condition, titled `/goal For each of the three sessions`."""
    text = prompt if isinstance(prompt, str) else ""
    while REMINDER.match(text):
        text = REMINDER.sub("", text, count=1)
    m = TASK_MARK.search(text)
    if m and text.lstrip().startswith("Background"):
        text = text[m.end():]
    text = FORK_HEAD.sub("", text, count=1)
    text = NOTES_TAIL.sub("", text).strip()
    first = text.split(None, 1)[0] if text else ""
    if relay.command_word(first, relay.norm(first)):
        return ""                                  # a slash command, whoever typed or ran it: Claude Code runs it
    if by in ("event", "plugin", "schedule"):
        return ""                                  # Claude Code, a plugin's module or a schedule, by the origin
    if by != "user":
        if text.startswith("<") and not PASTED.match(text):
            return ""                              # Claude Code speaking, whatever its body quotes
        if plans.woken(text):
            return ""                              # the plugin's hooks module speaking: the prompt of a turn it started
        if text.startswith(plans.SWEEP_MARK):
            return ""                              # p4-phi's own sweep, which a schedule fires: nobody typed it
        if plans.app_notice(text):
            return ""                              # the app speaking: its notice about a message this session sent
        if plans.system_note(text):
            return ""                              # Claude Code speaking: the frame of a background task's event
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
                f"\"{name_of(chain[0])}\", and the sessions linked to it.")
    else:
        head = "phi (p4-phi): background for this session from the sessions in this project before it."
    tail = f"The page this comes from: {page_path(home, above)}."
    room = BACKGROUND_CHARS - len(head) - len(tail) - 2
    text = "\n".join(body)
    if len(text) > room:
        text = text[:max(0, room - 4)].rsplit("\n", 1)[0] + "\n..."
    return "\n".join((head, text, tail))[:BACKGROUND_CHARS]


def findings_text(home, s, new, store=""):
    """The line under the reports of a session's workers that carry `Finding:` lines, '' when none does. A
    session another session started passes them up unchanged in its own report; the session nobody started at
    the top of the tree publishes and places them itself. A finding on a file or an issue another live session holds goes straight to that session, named
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
    else:
        rest = (f"{head}, and no session started this one, so the findings in them are this "
                f"session's to publish and place. Check each against the open issues and the running sessions, and "
                f"send one a running session covers to that session; for the rest, publish the issue and place the "
                f"session that resolves it, as a child of the session in this tree that holds its files or as a new "
                f"orchestrator:\n" + listed)
    return "\n\n".join(x for x in (mine, straight, rest) if x)


def in_message(report, said):
    """True when the message a turn began with holds a report's opening words, as when the plugin's hooks module
    sent the report itself to this session at its worker's turn end."""
    head = " ".join(str(report or "").split())[:300]
    return len(head) >= 40 and head in " ".join(str(said or "").split())


def reports_text(home, s, room=None, store="", said=""):
    """The reports of this session's workers that finished a turn since it last looked, and how many rows
    that covers. Each report is shown as kept, up to REPORT_CHARS, where it fits in `room`, and cut with ... where
    it does not; the ones there is no room for at all are named by count with their pages. A report that `said`,
    the message this turn began with, already holds is named there and not repeated. The `Finding:` lines they
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
        turn = r["turn"]
        sent = in_message(turn.get("report"), said)
        lines = turn_lines(name_of(load_session(home, r["sessionId"]), r), dict(turn, report="") if sent else turn,
                           report=REPORT_CHARS)
        if sent:
            lines.append("  reported: in the message this turn began with")
        out += [cut("\n".join(lines), each), f"  its page: {page_path(home, r['sessionId'])}"]
    if rest:
        out.append(f"Not shown here for want of room, {len(rest)} more, each on its page: " + ", ".join(
            f"\"{r.get('title') or r['sessionId']}\" {page_path(home, r['sessionId'])}"
            for r in rest[:6]) + (f", and {len(rest) - 6} more listed on {page_path(home, s['sessionId'])}"
                                  if len(rest) > 6 else "") + ".")
    if found:
        out.append(found)
    return "\n".join(out), len(rows)


def now_exact():
    """A time that orders two writes of one minute. Its seconds and its thousandths come from one read of the clock:
    read apart, a stamp in a second's first thousandths took the second before and sorted almost a second early,
    ezexe/p4#248."""
    t = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"


MAX_DEPTH = 3                 # a session this deep in the tree starts no session of its own
MAX_CHILDREN = 8              # nor one that has this many live children already
PLANS_DIR = p4conf.PLANS            # from the store's root, as the keeper has it: no line names a place under the app's own folder
PLAN_MODE = True              # p4.json phi.plan_mode: false withholds no plan tool from a started session
GOAL_REVIEW = True            # p4.json phi.goal_review: false leaves the review of the change out of a worker's goal
UPKEEP = False                # p4.json phi.upkeep: true has a session that started others keep them by itself


def project_conf(store):
    """The project's own keys of p4.json's `phi` section, read from the store where the session runs, not from a
    shared store, each with its P4_* variable ahead of it, by p4conf.load."""
    global PLAN_MODE, GOAL_REVIEW, UPKEEP
    try:
        d = p4conf.section(store, "phi", write=False) if store else {}
    except Exception:  # noqa: BLE001
        d = {}
    if not isinstance(d, dict):                    # a `phi` that is no section sets every key back to its default
        d = {}
    PLAN_MODE = d.get("plan_mode") is not False
    GOAL_REVIEW = d.get("goal_review") is not False
    UPKEEP = d.get("upkeep") is True
    relay.UPKEEP = controls.UPKEEP = UPKEEP     # the words that leave an archive to ezexe go with it on
    plans.CHILD_LEVELS = plans.child_levels(d.get("child_levels"))   # one key sets each kind's model and effort
    apply_caps(d)


# The caps a project sets in p4.json's `phi` section: each key, the module and constant it sets, and the least and most
# value it takes.
CAPS = {"max_depth": ("phi", "MAX_DEPTH", 1, 20), "max_children": ("phi", "MAX_CHILDREN", 1, 50),
        "sibling_turns": ("phi", "OTHERS", 0, 50), "own_turns": ("phi", "OWN", 0, 50),
        "chain_max": ("phi", "CHAIN_MAX", 1, 50), "turn_steps": ("phi", "TURN_STEPS", 1, 100),
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


RESTATE = ("the task restated as your own instruction to the session that receives it: what it is to do and why, "
           "from its side, a line `Files: <paths>` and what done looks like, with no message quoted and nothing "
           "of who asked or how the request travelled")


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


def from_peer(prompt, by=""):
    """True for another session's message: by its origin, rows.whose, and where the origin does not say, by the
    wrapper Claude Code puts around one."""
    return by == "session" or (not by and bool(re.search(r"<cross-session-message\b", str(prompt or ""))))


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
            out += ["## Files", "", "The files its brief says it covers:",
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


def memory_rules(home, rules_only=False):
    """The store's feedback and user memories in <home>/temportal/memory, each as its name and body, in the order
    MEMORY.md lists them, then the ones it does not list. With `rules_only`, a memory that holds no rule of its own
    is left out: one cut back to a pointer once its issue landed, whose front matter holds `landed:`, and one whose
    body says the plugin carries its rule, ezexe/p4#226."""
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
        if rules_only:
            import gaps
            if issues.LANDED_KEY.search(m.group(1)) or gaps.carried(m.group(2)):
                continue                           # the plugin carries the rule: a pointer, not a rule to hand
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


PLAN_TOOL = "EnterPlanMode"


def withheld_tools(started):
    """The tools the model of a session is not offered: `EnterPlanMode` where another session started this one and
    `phi.plan_mode` is on, since no person answers a plan's approval there. Where Claude Code has the event
    `tool.offer`, from 2.1.328 on, the hooks module answers it for this tool, so the model is not shown what it
    cannot use. `ExitPlanMode` stays offered, so the session still plans where ezexe enters plan mode there with
    `/plan`."""
    return [PLAN_TOOL] if started and PLAN_MODE else []


def rules_main():
    """`phi.py rules`: one JSON line for the hooks module, `{"withholds": <the tools the session's model is not
    offered>}`. A failure prints nothing, so the module withholds nothing, and leaves its line in the session's
    log. The command keeps its name, since the hooks module of a session started before an update asks for it."""
    try:
        withholds = []
        if os.environ.get("P4_PHI") != "0":
            me = Me()                                  # reads the project's p4.json, so `phi.plan_mode` is set
            above = spawned_from(me.rec)               # the app's record says so with a store or none
            if not above and me.home and me.id:
                above = spawned_from(load_session(me.home, me.id))
            withholds = withheld_tools(bool(above))
        sys.stdout.write(json.dumps({"withholds": withholds}) + chr(10))
    except Exception as e:  # noqa: BLE001
        log_failure("rules", {}, e)
    return 0


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
    new = [f"memory {name}\t{name}: {rule_of(body)}"       # a pointer and a carried rule are no rules to hand
           for name, body in (memory_rules(store, rules_only=True) if store else [])][:LIVE_RULES_LINES]
    key = hashlib.sha1("\n".join(new).encode("utf-8", "replace")).hexdigest()[:16]
    seen = s.get("rulesSeen") if isinstance(s.get("rulesSeen"), dict) else {}
    s["rulesSeen"] = {"hash": key, "lines": new}
    if not seen or seen.get("hash") == key:
        return ""
    old = list(seen.get("lines") or [])
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
    text = plans.record(me.home, s, inp)
    if spawned_from(s) and any(k in inp for k in ("advance", "start", "done", "items")):
        s = load_session(me.home, me.id) or s      # the issue or the findings line, then the commits' check
        cwd = payload.get("cwd") or s.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
        line = issues.ensure(me.home, s, issues.plan_lines(me.home, me.id), cwd, "plan") \
            if isinstance(inp.get("items"), list) and not load_turns(me.home, me.id) else ""
        flag = issues.unclosed_text(me.home, s, cwd)
        save_session(me.home, s)
        RAN["issue"] = (s.get("issue") or {}).get("number", "")
        text = "\n\n".join(p for p in (line, flag, text) if p)
    RAN["plan"] = len(text)
    return text or None


def h_plan_mode(payload):
    """PostToolUse on EnterPlanMode and ExitPlanMode: whether this session plans, kept for mode_now, since no hook
    event tells of a change of the permission mode and the two tools change it inside a turn. It returns nothing."""
    me = Me(payload)
    if not me.home or not me.id or payload.get("agent_id") or payload.get("hook_event_name") != "PostToolUse":
        return None                                # a subagent's call, or one that failed, such as a plan sent
                                                   # back, changed no mode here
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    s["planMode"] = str(payload.get("tool_name") or "") == "EnterPlanMode"
    save_session(me.home, s)
    RAN["pair"] = "planning" if s["planMode"] else "approved"
    return None


PHI_PY = re.compile(r"(?:^|[\/'\"\s])phi\.py\b")
PYTHONS = ("python", "python3", "py", "uv", "pythonw")


def h_wrap_up(payload):
    """PostToolUse on wrap_up: a session that keeps a state page is told to bring it up to date, to read its context
    with the app's own count and, past the line, to clear its idle coworkers and then itself."""
    me = Me(payload)
    if not me.home or not me.id:
        return ""
    line = controls.clear_line(me.home, load_session(me.home, me.id), me.store)
    RAN["clear"] = bool(line)
    return line


def keep_plan_file(me, path, payload=None):
    """The first file a session's own Write or Edit writes directly in the store's folder of plan files is the plan
    it works: its path is kept on session.json as `planFile`, where progress.py reads the plan's sections and its
    loop log for the pane, and stays kept while that file is there. A subagent's call is not the session's, and a
    file of one of that folder's subfolders is a sorted plan. True when a path was kept anew."""
    if (payload or {}).get("agent_id"):
        return False
    try:
        folder = os.path.normcase(os.path.realpath(os.path.join(me.store, *PLANS_DIR.split("/"))))
        full = os.path.realpath(path)
        if os.path.normcase(os.path.dirname(full)) != folder or not full.lower().endswith(".md"):
            return False
        kept = full.replace("\\", "/")
        s = load_session(me.home, me.id) or ensure_session(me.home, me.id, me.rec, me.cli)
        held = str(s.get("planFile") or "")
        if held == kept or (held and os.path.isfile(held)):
            return False
        s["planFile"] = kept
        save_session(me.home, s)
        return True
    except (OSError, ValueError):
        return False


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
    keep_plan_file(me, path, payload)
    import gaps
    s = load_session(me.home, me.id) or ensure_session(me.home, me.id, me.rec, me.cli)
    text = gaps.advice(me.home, me.store, s, path,
                       before=gaps.before_write(path, inp, payload.get("tool_response")))   # what the file held
    RAN["memory_gap"] = bool(text)
    return text or None


def h_issue_tie(payload):
    """PostToolUse on Bash and PowerShell: a `gh issue create` that carried a behaviour memory's `Finding:` line and
    answered with the new issue's address ties that memory to the issue, by one `issue:` line in its front matter,
    ezexe/p4#226. It says nothing: the tie is a write, and the publisher that made the call is told nothing more."""
    me = Me(payload)
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cmd = str(inp.get("command") or "")
    if not me.store or "issue" not in cmd or "create" not in cmd:
        return None
    import gaps
    resp = payload.get("tool_response")
    tied = gaps.tie(me.store, cmd, resp if isinstance(resp, str) else json.dumps(resp or ""))
    RAN["issue_tied"] = len(tied)
    return None


def h_self_archive(payload):
    """PreToolUse on mcp__ccd_session_mgmt__archive_session. Whether the call runs is the app's: it shows ezexe its
    approval card before an archive, except in Auto mode and Bypass permissions mode, and the tool itself refuses a
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


# permissions.md, "Manage permissions": the `/permissions` dialog "lists all permission rules and the `settings.json`
# file each rule comes from", and "Settings precedence": "Permission rules follow the same settings precedence as all
# other Claude Code settings". A rule names a tool and a pattern and holds in every session that reads its file, so
# an ask or deny rule on `gh issue create` cannot tell the session that publishes for a tree from any other. The
# same page, "Extend permissions with hooks": hooks "evaluate permissions at runtime", and "The hook output can deny
# the tool call". So the part a rule lacks, which session runs the call, is this PreToolUse check.

def h_issue_guard(payload):
    """PreToolUse on a shell call that runs `gh issue create`: refused in every session but the one that publishes
    for its tree, which controls.publisher names, with one line naming the `Finding:` form and that session by full
    title. Silent in that session, in a session p4-phi holds no record of, and with the issue loop off."""
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not issues.publishes(inp.get("command")):
        return None
    me = Me(payload)
    if not me.home or not me.id or not issues.on(me.home):
        return None
    if not issues.new_on(me.home):
        RAN["issue_guard"] = "no new issue"
        return cards.raised(cards_on(me), spawned_from(load_session(me.home, me.id)),
                            "phi (p4-phi): this project files no new GitHub issue, by `phi.new_issues` false in "
                            "its p4.json, so `gh issue create` is ezexe's to allow.")
    s = load_session(me.home, me.id)
    why = controls.create_refused(me.home, s, me.store) if s.get("sessionId") else ""
    if not why:
        return None
    RAN["issue_guard"] = "refused"
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": why}}


def h_task_stop(payload):
    """PostToolUse on TaskStop: the stopped task's entry leaves the list the last
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


def share_notice(payload):
    """What a session whose folder is a linked worktree runs on, in words, whichever tool made the worktree."""
    share = shared.start_text(str((payload or {}).get("cwd") or ""))
    return ("phi (p4-phi): this session's folder is a git worktree. " + share) if share else ""


def h_session_start(payload):
    me = Me(payload)
    if not me.home or not me.id:
        # a project with no .claude/p4 yet has nothing to hand
        RAN["start"] = "no store"
        return share_notice(payload) or None       # read from the main checkout's store, which needs none here
    relay.track(me.home, first_only=True)  # the session tree, committed on its own the first time
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    ran_for(s, me)
    mark_fork(s, me, payload)
    source = payload.get("source") or "startup"
    RAN["start"] = source
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
    share = share_notice(payload)
    if share:
        notices.append(share)
    first = ""
    if source == "compact" and controls.is_puppeteer(s, me.home):
        first = controls.compacted(me.home, s)     # a puppeteer's board path before anything else
        RAN["pair"] = "compacted"
    elif source in ("compact", "clear"):
        first = controls.state_first(me.home, s)   # the state page of any session that keeps one, first
    save_session(me.home, s)
    # past the app's cap of 10,000 characters Claude sees a preview of the first 2,000 and the file's path, so what
    # asks the session to act comes first: the page to resume from and the notices, then the background, and last
    # the address book, which is whole on its page as well
    return "\n\n".join(p for p in (first, *notices, text, book_line) if p) or None


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


def acting_first(parts, keep=()):
    """Every part whole, the ones in `keep` first and the rest in their order. A part in `keep` asks the session to
    act at this message, so it leads: past the app's cap of APP_CAP characters Claude is passed only the first
    APP_PREVIEW of them with the path of the file that holds the text. No part is cut or kept back, since that file
    is the app's to write."""
    parts = [p for p in parts if p]
    kept = {id(p) for p in keep if p}
    first = [p for p in parts if id(p) in kept]
    return "\n\n".join(first + [p for p in parts if id(p) not in kept])


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
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli, hint=me.hint)
    ran_for(s, me)
    rid, asker = starts.requester_of(me.home, payload.get("prompt")) if not load_turns(me.home, s["sessionId"]) \
        else ("", "")
    if rid:                                        # a start request's child: the asking session's, not the caller's
        if asker != s["sessionId"] and spawned_from(s) != asker \
                and not starts.ORCHESTRATOR.search(str(payload.get("prompt") or "")):   # an orchestrator stays
            try:                                   # under the session that started it
                reparent(me.home, s["sessionId"], asker, "requested")
                RAN["requested_by"] = asker
            except ValueError:
                pass
            s = load_session(me.home, s["sessionId"])
        starts.started(me.home, rid, s["sessionId"])
    if not load_turns(me.home, s["sessionId"]) and puppeteer.arrived(s, payload.get("prompt")):
        RAN["drafted"] = s.get("draft")             # its start draft
    # whose words the prompt is, by the origin Claude Code stamped on it, which the hooks module kept for this hook
    origin = rows.origin_of(payload, session_dir(me.home, s["sessionId"]))
    by = rows.whose(origin)
    RAN["origin"] = by
    req = request_of(payload.get("prompt"), by)
    s["turnBy"] = "session" if by == "session" else "user" if req or by == "user" else (
        "session" if from_peer(payload.get("prompt"), by) else "event")
    s["toldBy"] = by                               # '' where the origin did not say and the text's opening told
    s["toldFrom"] = upkeep.teller(by, origin, payload.get("prompt"))   # the session or the plugin that sent them
    if s["turnBy"] == "user":
        s["inputAt"] = now_exact()                 # a person's own input, which lifts what a stop refuses: goal_again
    if payload.get("permission_mode"):             # hooks.md: the mode the session is in, kept for mode_now
        s["permissionMode"] = str(payload["permission_mode"])
        s["planMode"] = s["permissionMode"] == "plan"   # a prompt's own mode, over what a plan mode tool said before
    if not plans.woken(payload.get("prompt")):
        s.pop("woke", None)                        # a turn no wake started: the hooks module's count starts over
    plans.clear_in_flight(s, payload.get("prompt"))   # a completion notice ends its entry
    mark_fork(s, me, payload)
    if not s.get("disposable") and relay.DISPOSABLE.search(str(payload.get("prompt") or "")) \
            and not load_turns(me.home, s["sessionId"]):
        s["disposable"] = True                     # its brief or its first message: report when done
        RAN["disposable"] = True
    if "fileSet" not in s and not load_turns(me.home, s["sessionId"]):
        declared = starts.files_of(payload.get("prompt"), s.get("cwd") or payload.get("cwd") or "")
        if declared is not None:                   # the files its brief says it covers, kept and shown on its page
            s["fileSet"] = declared
            RAN["files"] = len(declared)
            save_session(me.home, s)
            relay.mark_paths(me.home, me.store or me.home)
    if "pushes" not in s and spawned_from(s) and not load_turns(me.home, s["sessionId"]):
        s["pushes"] = cards.brief_pushes(payload.get("prompt"))   # its brief, whole: the branch guard reads it
        RAN["pushes"] = s["pushes"]
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
        if GOAL and spawned_from(s) and plans.done_line(req):   # the whole line, which the cut task may not hold
            s["doneLine"] = plans.done_line(req)
            keep_review(s, req)
    issue_line = ""
    if spawned_from(s) and not load_turns(me.home, s["sessionId"]) and not s.get("issue"):
        issue_line = issues.ensure(me.home, s, req or str(payload.get("prompt") or ""),
                                   s.get("cwd") or payload.get("cwd") or "", "brief")   # from its brief
        RAN["issue"] = (s.get("issue") or {}).get("number", "")
    handed = given(s, me, me.home)
    parts = [live_rules(s, me.store),
             pin_of(me.home, s), handed]
    if REPORTS:
        text, seen = reports_text(me.home, s, None, me.store, said=str(payload.get("prompt") or ""))
        s["reportsSeen"] = seen
        parts.append(text)
    save_session(me.home, s)
    step = replay(me, s, payload.get("transcript_path") or "")
    s = load_session(me.home, s["sessionId"]) or s
    if step:
        parts.append(step)
    keep = []                                      # the notices that ask the session to act now: they lead

    def notice(text):
        keep.append(text)
        return text
    if UPKEEP:
        try:                                       # the acts due for the sessions this one started, at every turn
            kept_up = upkeep.text(me.home, s, s.get("turnBy") or "user", me.store)
        except Exception:  # noqa: BLE001  a record it cannot read never costs the message its other lines
            kept_up = ""
        if kept_up:
            RAN["upkeep"] = kept_up.count("\n- ")
            parts.insert(0, notice(kept_up))
    pend = (s.pop("staleChildren", None) or []) + relay.drain_archive(me.home, s["sessionId"])
    pend = [x for x in pend if isinstance(x, dict) and not archived_already(me.home, x.get("id"))]
    stale = relay.stale_text(pend)                # children to archive, said once; one archived in the app is not named
    s["staleTold"] = (list(s.get("staleTold") or []) + [x.get("id") for x in pend if isinstance(x, dict)])[-50:]
    if stale:
        parts.insert(0, notice(stale))
    if issue_line:
        parts.insert(0, notice(issue_line))
    pad = str(payload.get("scratchpad_dir") or "").replace("\\", "/").rstrip("/")
    if pad and not s.get("scratchpadDir"):        # the app's scratchpad of the first turn: a clear's new
        s["scratchpadDir"] = pad                  # conversation still finds the state page written there
    # ezexe's own message: a handed-over task is none, and to a puppeteer, neither is one the app marks as another
    # session's; an orchestrator's routing still reads the work another session hands it
    ezexes = req if req and not handed_over(payload.get("prompt")) else ""
    if ezexes and puppeteer.from_session(payload.get("prompt"), by) and controls.is_puppeteer(s, me.home):
        ezexes = ""
    try:                                           # a puppeteer, and a session it started
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
            pup, verdict = puppeteer.on_prompt(me.home, s, req, s.get("cwd") or payload.get("cwd") or "")
        except Exception:  # noqa: BLE001
            pup = verdict = ""
        RAN["puppeteer"] = verdict or bool(pup)
    # ezexe's own message about earlier work, in a session the app holds a record of, which alone has the tool
    if ezexes and me.rec and not verdict and not puppeteer.from_session(payload.get("prompt"), by):
        try:
            parts.append(puppeteer.earlier_text(me.home, req))
        except Exception:  # noqa: BLE001
            pass
    try:                                           # it reads the app's records: a failure costs only its own line
        route = relay.route_text(me.home, s, req, me.store) if req and not verdict else ""
    except Exception:  # noqa: BLE001
        route = ""
    book_line = "" if route else book_text(me.home, s, me.store)
    parts.append(pup)
    last = route or book_line
    save_session(me.home, s)
    # the rebase check, on every message: its warnings lead, then the notices, then what the sessions beside this
    # one changed and the rest, whole
    text, _ = relay.rebase(me.home, s["sessionId"], RELAY_CHARS, fair_cut, touches_of(me.home, s))
    RAN["relay"] = len(text)
    stop, changed = relay.stop_line(text)
    return acting_first([stop, changed, last] + parts, [stop] + keep)


def pair_parts(me, s, req, changed="", notice=lambda text: text):
    """Beside an orchestrator's message. A puppeteer gets what it is, once; the controlled sessions' reports by reference; at a
    turn ezexe began, the requests addressed to it and where ezexe's message belongs; a boundary; once a controlled
    tree closed or reported done, the open issues no live session holds, each to route or start; and its board
    rewritten. Any other orchestrator gets its puppeteer, once, and what became of the requests it sent it."""
    out = []
    if not controls.is_puppeteer(s, me.home):
        told = controls.pair_text(s, me.store)
        if told:
            RAN["pair"] = "controlled"
        answers = controls.answers_text(me.home, s) if s.get("puppeteer") else ""
        return [p for p in (told, answers) if p]
    RAN["pair"] = "puppeteer"
    if not s.get("puppeteerTold"):
        s["puppeteerTold"] = now()                 # said once, and kept
        out.append("phi (p4-phi): " + controls.rule_text(me.home, s))
    controls.rules_changed(s, changed)
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
    if req:
        out += [p for p in (controls.requests_text(me.home, s), controls.route_down(s, req, me.home)) if p]
    edge = controls.boundary(me.home, s)
    if edge:
        RAN["boundary"] = True
        pieces = edge.split("\n\n")               # the complete sessions, kept, and the boundary, which fits or is held
        if not pieces[0].startswith("phi (p4-phi): a boundary: "):
            pieces[0] = notice(pieces[0])
        out += pieces
    watch = controls.idle_watch(me.home, s)
    if watch:
        out.append(watch)
    try:
        unheld = controls.open_issues_text(me.home, s)
    except Exception:  # noqa: BLE001  a listing it cannot read never costs the message its other lines
        unheld = ""
    if unheld:                                     # a tree closed or reported done: the open issues no session holds
        RAN["open_issues"] = unheld.count("\n- ")
        out.append(notice(unheld))
    controls.board(me.home, s)
    return out


def h_stop(payload):
    me = Me(payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    relay.mark_paths(me.home, me.store or me.home)
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
    if upkeep.keep_sweep(s, turn.get("calls")):    # the sweep's schedule, or a worker asked for its idle notice
        RAN["schedule"] = upkeep.schedule_runs(s)
    if UPKEEP:
        try:                                       # the app's answer to an archive call that failed, kept as it is
            if upkeep.keep_refused(me.home, s, turn.get("calls")):
                RAN["refused"] = True
        except Exception as e:  # noqa: BLE001  a record it cannot write never costs the turn its end
            log_failure("refused", {}, e)
    if s.get("toldBy"):
        row["by"] = s["toldBy"]                    # whose words began the turn, where the prompt's origin said
        if s.get("toldFrom"):
            row["from"] = s["toldFrom"]            # and who sent them, which upkeep reads before an archive
    if UPKEEP and spawned_from(s):                 # the row keeps a report cut to REPORT_CHARS, and a list of what
        left = upkeep.left_of(report if isinstance(report, str) else "")   # is left often ends a long one
        if left:
            row["left"] = left
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
        # No prompt hook saw this session's brief, as where the plugin was loaded after the session's first message:
        # seen in the desktop app, where a copy loaded from the mods folder kept the task here and no done line, so
        # the worker got no goal. The line is taken where the task is, from the turn's whole request.
        if GOAL and spawned_from(s) and plans.done_line(turn.get("prompt")):
            s["doneLine"] = plans.done_line(turn.get("prompt"))
            keep_review(s, turn.get("prompt"))
    if (GOAL or s.get("goal") or s.get("goalAsk")) and payload.get("transcript_path"):
        s["transcript"] = str(payload["transcript_path"])   # where goal_verdict reads the goal's last row
    save_session(me.home, s)
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
                                       relay.owed(list(dict.fromkeys(c[0] for c in new))),   # what each still owes
                                       relay.worktree_branches(s["sessionId"], cur, new),    # the branch to merge
                                       relay.green_notes(me.home, [s["sessionId"]] + chain_of(me.home, s["sessionId"]),
                                                         new),                                # a verdict kept by hash
                                       relay.push_workflows(c[0] for c in new)))              # its own tests on a push
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
    if not spawned_from(now_s) and controls.is_puppeteer(now_s, me.home):
        RAN["waits_on"] = len(controls.waited_on(now_s, me.home))   # the sessions it controls that its task list waits on
        controls.board(me.home, now_s)
    if held:                                       # the issue loop's regression test did not pass: the turn goes back
        return {"decision": "block", "reason": held}
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
    relay.mark_paths(me.home, me.store or me.home)
    return None


# --- what the hooks module is answered: a worker's starter --------------------------------------------------------
#
# hooks/register.ts runs `phi.py look` for a session and acts on the key `starter` of its answer, which no command
# hook could. `starter` is where the report of a worker's turn goes, by `$.session.send`: plugins/mods/api.md, "Send
# and receive messages between sessions", says the call "makes the same delivery the SendMessage tool makes", and
# cross-session-messaging.md, "Message delivery", that "When the receiving session is idle, Claude Code starts a new
# turn with the message." A live probe between two desktop sessions on Claude Code 2.1.326 showed it, as ezexe/p4#157
# records.

TURN_TAIL = 65536             # bytes from the end of a turns.jsonl that hold its latest row


def starter_cli(home, s):
    """The session that started `s`, as the address `$.session.send({ to: { sessionId } })` takes: the CLI session
    id on the app's record of the starter, which is what `$.session.id()` answers there, else the last one its
    session.json holds. '' for a session nobody started and for a starter no record names a CLI session of."""
    above = spawned_from(s)
    if not above:
        return ""
    cli = str(app_record(above).get("cliSessionId") or "")
    if not cli:
        held = [c for c in load_session(home, above).get("cliSessionIds") or [] if isinstance(c, str) and c]
        cli = held[-1] if held else ""
    return cli


def last_turn_row(home, sid):
    """A session's latest turn row, read from the end of its turns.jsonl, or {}."""
    rows = read_rows(os.path.join(session_dir(home, sid), "turns.jsonl"), TURN_TAIL)
    return rows[-1] if rows else {}


# --- a session's native goal: the condition the hooks module sets, and the verdict Claude Code leaves ------------------

GOAL_ASKED = ("kept: p4-phi sets this condition as this session's goal once the session is idle, by Claude Code's "
              "own command, and a goal that is already set is replaced. Claude Code then starts a turn with the "
              "condition as its directive and has a model check it after every turn, which sends the session back "
              "until the condition holds. End this turn, and let each later turn show in its own words what the "
              "condition names, since that model reads the conversation alone and runs nothing.")
GOAL_SHORT = "state the goal's condition as a whole sentence: what holds when the work is done, and what shows it"
GOAL_LONG = "a goal's condition holds 4,000 characters at most"
GOAL_STARTER = ("This condition is judged by its own words, and no part of it waits on a message from another "
                "session: a part that names a message this session sends is met once this conversation shows that "
                "message sent, with no reply to it. The session that started this one is `{sid}`. One more way a "
                "part is met, and never a requirement: a message from that session in this conversation says that "
                "session does that part itself or takes that part or the whole work as done.")


def keep_review(s, brief):
    """Keeps on a session, beside its done line, whether its goal carries the review of the change: `doneReview`,
    where p4.json's `phi.goal_review` is on and the brief asks for changes, as issues.writing tells a brief that
    changes files from a check, an audit or a question."""
    if GOAL_REVIEW and issues.writing(brief):
        s["doneReview"] = True
    else:
        s.pop("doneReview", None)


def goal_condition(s, line, cut_to_fit=True, review=False):
    """A condition as it is set for the session `s`: `line`, and for a session another session started the
    sentences of GOAL_STARTER after it, which name the starter by the id its messages carry. With `review`, the
    review of the change, plans.REVIEW_PART, stands between the two, for a brief that changes files. goal.md, "Write an
    effective condition": "The evaluator judges your condition against what Claude has surfaced in the conversation."
    So a brief's line that its starter later changes by a message cannot be met as worded unless the condition says
    that such a message counts. Seen in the desktop app on 2026-11-19, on Claude Code 2.1.326: a worker's line named
    "a session you start" and a push, its starter then made that start and that push itself and wrote that the work
    was taken as done, and the evaluator answered "it did not change the wording of the condition" and sent the
    worker back nine times at the end of every turn, until its starter stopped the turn. Seen there on 2026-11-23,
    with those sentences worded as a rule, "counts as met once a message from that session": the evaluator took the
    message as required, and a planner whose line ended at its own report was answered "only the starter's
    acceptance is missing" at three turn ends, until its starter wrote. So the sentences say first that no part
    waits on such a message, and give it as one more way a part is met. A brief's line is cut to
    leave the sentences room in the 4,000 characters a condition holds. With `cut_to_fit` false, for a condition the
    session stated itself, one that leaves them no room is set as it was stated."""
    line = str(line or "")
    above = spawned_from(s)
    if not above or not line:
        return line
    tail = (plans.REVIEW_PART + " " if review else "") + GOAL_STARTER.format(sid=above)
    room = plans.GOAL_CHARS - len(tail) - 1
    if len(line) > room:
        if not cut_to_fit or room < plans.GOAL_LEAST:
            return line
        line = line[:room].rstrip()
    return line + " " + tail


def goal_ask(home, s, condition):
    """`phi.py goal ask <condition>`, which the tool `mcp__p4-phi__goal` runs: keeps the condition a session states
    as the goal it asks for, on session.json as `goalAsk`, for the next look to answer. Any session may ask, one no
    session started too, and whatever phi.json's `goal` says, since that key is for the goal a worker is given
    unasked. A later ask takes the place of one not yet answered. goal.md, "Write an effective condition": "The
    condition can be up to 4,000 characters." A condition shorter than plans.GOAL_LEAST is refused, so `clear` or
    one of its aliases is never sent as one."""
    line = " ".join(str(condition or "").split())
    if len(line) < plans.GOAL_LEAST:
        raise ValueError(GOAL_SHORT)
    if len(line) > plans.GOAL_CHARS:
        raise ValueError(GOAL_LONG)
    s["goalAsk"] = {"condition": line, "asked": now()}
    save_goal(home, s)
    return GOAL_ASKED


# The most looks a condition is answered to while its goal is not set: the first, and two more. The hooks module sets
# a goal by `$.command.run`, which the API types of Claude Code 2.1.326 give as "queued and run once the session is
# idle", rejecting "past a Stop or a host's limit". plugins/mods/api.md, "Work your mod started before the
# interruption": a command still in the queue when a turn is stopped is "Dropped. The call rejects with an error
# whose message includes `the command was removed from the queue before it ran`", and after the stop "Calls stay
# refused until the user's next input, and nothing queues or repeats them for you". So a condition answered to one
# look alone was lost at a stop. Seen on 2026-11-19: a session's own ask stood as asked and never set after a
# stop_session, and another worker's command waited four minutes in the queue behind a turn a queued message began
# and then set the goal, so a turn that begins at once loses nothing.
GOAL_TRIES = 3
# How Claude Code names a command a stop took, which costs no look. plugins/mods/api.md, "Calls and background work
# after the user interrupts a turn": "The reason `the session was stopped and nobody has sent input since` in a
# result or error means the user stopped a running turn", and "After that interruption, calls that start new work
# in the session are refused until the user's next input, such as a message at the prompt". "Retry a refused or
# dropped call" gives that reason for a call that "was refused", and `was removed from the queue before it ran` for
# one that "left the queue without running and was dropped, for example when the user stopped the turn".
# Seen on 2026-11-22 in the desktop app on Claude Code 2.1.326, in a session whose starter ended its turn with
# `mcp__ccd_session_mgmt__stop_session`: the command in the queue was dropped, a message from the starter began a
# turn, and the command of the look at that turn's end was refused with the first reason, so a message from
# another session is not that input. Each counted as a look then, and one more such turn would have spent the
# last, with the goal never set unless a person typed there first. Seen there too, once: a person's own message
# lifted the refusal, and the command of the look at the end of the turn it began set the goal.
STOP_REFUSED = "the session was stopped and nobody has sent input since"
STOP_DROPPED = "was removed from the queue before it ran"


def save_goal(home, s):
    """Saves a session whose goal or ask a goal command changed. Those commands run beside the session's hooks, as
    the word of a command a stop dropped runs beside the prompt hook of the message that stop let through, and a
    hook saves the copy it read at its start. So _save_session keeps the goal and the ask of the file for every
    save but this one."""
    s["_goalSet"] = True
    save_session(home, s)


def same_condition(row, kept):
    """Whether the condition of a transcript's goal row is the one kept for the session. Claude Code writes the row,
    so it is compared as that row can hold it: with other spaces between its words, or cut short, where the row's
    words open the kept condition and are 40 characters at least."""
    a, b = " ".join(str(row or "").split()), " ".join(str(kept or "").split())
    cut = a.rstrip(".…").rstrip()
    return bool(a) and (a == b or (len(cut) >= 40 and b.startswith(cut)))


def goal_again(home, s, flying=False):
    """The condition of a goal that was asked for and is not set, answered to one more look, or ''. Where the
    transcript's last goal row shows the condition set, the module's word of it was lost: the goal is marked set
    and nothing is answered. Nothing is answered either while the module says its command has not answered yet,
    `flying`, once GOAL_TRIES looks were answered, or before a turn has ended since the last answer, so a look on
    the timer spends no try. And nothing is answered while Claude Code refuses the command for a stop, which
    goal_failed keeps as `stopped`: the refusal lasts until a person's own words begin a turn, `inputAt`, so the
    look at that turn's end is the first that answers, and no look before it is spent."""
    g = s.get("goal")
    if not isinstance(g, dict) or not g.get("condition") or g.get("set") or g.get("over"):
        return ""
    row = plans.goal_row(s.get("transcript") or "")
    if same_condition(row.get("condition"), g["condition"]) and not plans.goal_over(row):
        g["set"] = now()                           # Claude Code holds it as set
        for k in ("failed", "stopped", "answered"):
            g.pop(k, None)
        save_goal(home, s)
        return ""
    tries = g.get("tries") if isinstance(g.get("tries"), int) else 1
    last = last_turn_row(home, s["sessionId"])
    ended = str(last.get("id") or "")
    if flying or tries >= GOAL_TRIES or not ended or ended == g.get("turn"):
        return ""
    if g.get("stopped"):
        said = str(s.get("inputAt") or "")
        if not (said >= str(g["stopped"]) and str(last.get("at") or "") >= said):
            return ""                              # refused until a person's own words begin a turn and it ends
        g.pop("stopped")
    g.update(tries=tries + 1, turn=ended, answered=now_exact())
    save_goal(home, s)
    return g["condition"]


def goal_due(home, sid, flying=False):
    """The condition the hooks module sets as the session's native goal, or ''. First the condition the session
    asked for itself, goal_ask, which any session gets whatever phi.json says, and which takes the place of a goal
    it has. Else the line `Done looks like:` of the brief of a session another session started, once its first turn
    has ended, where phi.json turns `goal` on. Either is kept on session.json as `goal` with when it was asked for,
    how many looks it was answered to and the turn that had ended last by then, and one the session asked for with
    `own`. Either is set as goal_condition words it, so a session another session started is given a condition its
    starter's later message can settle. A condition that was answered and is not set is answered again by
    goal_again, to GOAL_TRIES looks in all, with `answered` the exact time of the last such look, which goal_failed
    reads for a command a stop took. `flying` is the hooks module's word that a goal command of its own has not
    answered yet."""
    s = load_session(home, sid) if sid else {}
    if not s.get("sessionId") or s.get("doneRetired") or s.get("archived"):
        return ""
    ended = str(last_turn_row(home, s["sessionId"]).get("id") or "")
    ask = s.get("goalAsk") if isinstance(s.get("goalAsk"), dict) else {}
    if ask.get("condition") and not flying:
        s.pop("goalAsk", None)
        condition = goal_condition(s, ask["condition"], cut_to_fit=False)
        s["goal"] = {"condition": condition, "asked": ask.get("asked") or now(), "own": True, "tries": 1,
                     "turn": ended, "answered": now_exact()}
        save_goal(home, s)
        return condition
    if ask.get("condition"):
        return ""                                  # the command in flight answers first, then the new ask
    if s.get("goal"):
        return goal_again(home, s, flying)
    if not GOAL or not spawned_from(s) or not s.get("doneLine") or not ended or flying:
        return ""
    condition = goal_condition(s, s["doneLine"], review=bool(s.get("doneReview")))
    s["goal"] = {"condition": condition, "asked": now(), "tries": 1, "turn": ended, "answered": now_exact()}
    save_goal(home, s)
    return condition


def goal_set(home, sid):
    """The hooks module's word that the goal command answered `Goal set`: from here the Stop hook sends no turn of
    the session back, by plans.goal_on. True when a goal that was asked for is marked set."""
    s = load_session(home, sid) if sid else {}
    g = s.get("goal")
    if not isinstance(g, dict) or g.get("set"):
        return False
    g["set"] = now()
    for k in ("failed", "stopped", "answered"):
        g.pop(k, None)
    save_goal(home, s)
    return True


def goal_failed(home, sid, reason):
    """The hooks module's word that the goal command did not set the goal, with what the command answered or why the
    call was rejected, kept on the goal as `failed` for `phi.py goal` to print. goal_due counted the look it
    answered, and the look stays counted but for a stop: where the reason holds STOP_DROPPED or STOP_REFUSED the
    look is given back, since no command could have worked. A refusal, STOP_REFUSED, is kept as `stopped` too,
    with when that look was answered, and goal_again answers nothing until a person's own input later than that
    has begun a turn. Input on record from after the look came after the refusal, which names none before it, so
    nothing is held then. True when a goal that is not set took the word."""
    s = load_session(home, sid) if sid else {}
    g = s.get("goal")
    if not isinstance(g, dict) or g.get("set") or g.get("over"):
        return False
    why = str(reason or "")
    g.update(failed=cut(clean(why), 300) or "no answer", failedAt=now())
    answered = str(g.pop("answered", None) or "")  # the look this word answers, counted and not settled yet
    g.pop("stopped", None)
    if STOP_REFUSED in why or STOP_DROPPED in why:
        if answered and isinstance(g.get("tries"), int):
            g["tries"] = max(0, g["tries"] - 1)    # the look a stop took costs nothing
        at = answered or now_exact()
        if STOP_REFUSED in why and str(s.get("inputAt") or "") < at:
            g["stopped"] = at
    save_goal(home, s)
    return True


def goal_verdict(home, sid):
    """Reads how a session's native goal stands from the last goal row of its transcript. Claude Code writes that row
    after the Stop hooks of its Stop have answered, so no Stop hook reads it, and the look a turn's end asks for
    does. A goal met marks the session's latest turn done with the evaluator's reason, on its own row and on the row
    its starter reads. A goal met, judged impossible or cleared is over, and the Stop hook sends turns back again.
    Returns how it ended, '' while it is still set or where the session has none."""
    s = load_session(home, sid) if sid else {}
    if not plans.goal_on(s):
        return ""
    row = plans.goal_row(s.get("transcript") or "")
    over = plans.goal_over(row)
    if not over:
        return ""
    reason = cut(clean(row.get("reason")), 300)
    s["goal"].update({"over": over, "overAt": now()}, **({"reason": reason} if reason else {}))
    save_goal(home, s)
    last = last_turn_row(home, s["sessionId"]) if over == "met" else {}
    if last and not last.get("done"):
        last["done"] = cut(clean("goal met: " + (reason or str(s["goal"].get("condition") or ""))), 400)
        append_line(os.path.join(session_dir(home, s["sessionId"]), "turns.jsonl"), last)
        above = spawned_from(s)
        append_line(reports_path(home, above),
                    {"time": last.get("time") or now(), "sessionId": s["sessionId"], "title": name_of(s), "turn": last})
        for node in (above, s["sessionId"]):       # the parent's anchor and both pages say done from here
            relay.make_anchor(home, node, last.get("time") or now())
        render_page(home, s["sessionId"])
        if above:                                  # a session nobody started has no page above it
            render_page(home, above)
    return over


def goal_look(a, me):
    """`phi.py look`: puppeteer.look's answer, and with it `goal`, the condition the hooks module sets as the
    session's native goal, where one is due, and `app_tools`, which has the module ask the app's own tools for
    sessions unless phi.json turns them off. The verdict of a goal already set is read first, at every look, whatever phi.json's `goal` says,
    since a session may have asked for its own, goal_ask."""
    out = puppeteer.look(me.home, me.id, net=a.net, folder_only=False)
    due = ""
    if APP_TOOLS and not out.get("off"):
        out["app_tools"] = True
    if not out.get("off"):
        try:
            goal_verdict(me.home, safe_id(me.id))
            due = goal_due(me.home, safe_id(me.id), flying=bool(getattr(a, "goal_flying", False)))
        except Exception as e:  # noqa: BLE001
            log_failure("goal", {}, e)
    if due:
        out["goal"] = due
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def goal_switch(home, on):
    """`phi.py goal on` and `goal off`: writes `goal` in the store's phi/phi.json, where configure reads it, keeping
    the file's other keys, and returns the line that says how it stands as read back. A session writes nothing under
    `.claude` with its own tools, so this command is how the key is set. A file that does not parse is left as it is."""
    stands, path = switch(home, "goal", on)
    return f"goal is {stands} in {path}"


def switch(home, key, on):
    """Writes one true-or-false key of the store's phi/phi.json, keeping the file's other keys, and returns how the
    key stands as read back, `on` or `off`, with the file's path. A file that does not parse is left as it is."""
    path = os.path.join(home, "phi", "phi.json")
    d = read_json(path)
    if not d and os.path.exists(path) and os.path.getsize(path) > 2:
        raise ValueError(f"{path} does not parse as JSON, so it is left as it is")
    d[key] = bool(on)
    write_atomic(path, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return "on" if read_json(path).get(key) is True else "off", path.replace(chr(92), "/")


def worker_settings(home, sid="", text=""):
    """The mode and profile a terminal worker of the session `sid` starts with, for the piece of work `text`, as
    {"mode", "profile", "mode_from", "profile_from", "reason"}. The mode: the session's `workerMode`, else phi.json's
    `worker_mode`, else plans.worker_mode_for(text), else WORKER_MODE. The profile: the session's `workerProfile`,
    else phi.json's `worker_profile` where the key is set, else the mode's pair, WORKER_PAIRS."""
    conf = read_json(os.path.join(home, "phi", "phi.json")) if home else {}
    rec = load_session(home, safe_id(sid)) if home and sid else {}
    reason = ""
    if rec.get("workerMode") in WORKER_MODES:
        mode, mode_from = rec["workerMode"], "the session's workerMode"
    elif conf.get("worker_mode") in WORKER_MODES:
        mode, mode_from = conf["worker_mode"], "phi.json worker_mode"
    elif text:
        mode, reason = plans.worker_mode_for(text)
        mode_from = "the piece of work"
    else:
        mode, mode_from = WORKER_MODE, "the default"
    if isinstance(rec.get("workerProfile"), str):
        profile, profile_from = rec["workerProfile"], "the session's workerProfile"
    elif isinstance(conf.get("worker_profile"), str):
        profile, profile_from = conf["worker_profile"], "phi.json worker_profile"
    else:
        profile, profile_from = WORKER_PAIRS[mode], f"the pair of {mode}"
    return {"mode": mode, "profile": profile, "mode_from": mode_from, "profile_from": profile_from,
            "reason": reason}


def worker_line(settings):
    """The one line a start prints for its settings."""
    return (f"mode {settings['mode']} ({settings['mode_from']}), profile {settings['profile'] or 'off'} "
            f"({settings['profile_from']})")


def worker_record(home, row):
    """One row of `<home>/phi/worker-starts.jsonl`: a start or the outcome of a wait."""
    append_line(os.path.join(home, "phi", "worker-starts.jsonl"), {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **row})


def worker_start(home, settings, name, starter, kind, log, report):
    """The row a start of a terminal worker appends, and the line it prints."""
    worker_record(home, {"event": "start", "name": name, "starter": starter, "kind": kind, "mode": settings["mode"],
                         "profile": settings["profile"], "mode_from": settings["mode_from"],
                         "profile_from": settings["profile_from"], "reason": settings["reason"],
                         "log": log, "report": report})
    return worker_line(settings)


def worker_outcome(home, name, how, result):
    """The row a `--wait --report` appends when its wait ends, with the cost and turns of the log's last result."""
    row = {"event": "outcome", "name": name, "how": how}
    for k in ("total_cost_usd", "num_turns", "is_error", "subtype", "duration_ms"):
        if k in result:
            row[k] = result[k]
    worker_record(home, row)


def worker_balance(home):
    """`phi.py balance`: per mode, the starts, the done and failed counts, the total and mean cost and the mean turns,
    from the rows of worker-starts.jsonl, and a line for all."""
    rows_ = read_rows(os.path.join(home, "phi", "worker-starts.jsonl"))
    mode_of_ = {r.get("name"): r.get("mode") for r in rows_ if r.get("event") == "start"}
    out = []
    for mode in WORKER_MODES + ("all",):
        starts_ = [r for r in rows_ if r.get("event") == "start" and mode in ("all", r.get("mode"))]
        outs = [r for r in rows_ if r.get("event") == "outcome" and (mode == "all" or mode_of_.get(r.get("name")) == mode)]
        costs = [r["total_cost_usd"] for r in outs if isinstance(r.get("total_cost_usd"), (int, float))]
        turns = [r["num_turns"] for r in outs if isinstance(r.get("num_turns"), (int, float))]
        failed = sum(1 for r in outs if r.get("is_error") is True or r.get("how") == "ended")
        done = sum(1 for r in outs if r.get("how") == "done" and r.get("is_error") is not True)
        out.append(f"{mode}: {len(starts_)} starts, {done} done, {failed} failed, cost {sum(costs):.4f} total"
                   f" {sum(costs) / len(costs) if costs else 0:.4f} mean, turns {sum(turns) / len(turns) if turns else 0:.1f} mean")
    return "\n".join(out)


def worker_for(home, sid, mode=None, profile=None):
    """`phi.py worker_for`: with no mode and profile it prints; with them it writes the session `sid`'s `workerMode`
    and `workerProfile` (`default` removes the key, `off` for a profile is the empty string). The lines say the
    effective mode and profile and where each came from. ValueError on a bad word or an unknown session."""
    rec = load_session(home, safe_id(sid))
    if not rec:
        raise ValueError(f"no session {sid} in this store")
    if mode is not None and mode != "default" and mode not in WORKER_MODES:
        raise ValueError("a worker mode is print, interactive or default")
    if profile is not None and profile not in ("off", "default") and not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise ValueError("a worker profile's name holds letters, digits, _ and - only")
    if mode is not None or profile is not None:
        if mode is not None:
            rec.pop("workerMode", None)
            if mode != "default":
                rec["workerMode"] = mode
        if profile is not None:
            rec.pop("workerProfile", None)
            if profile != "default":
                rec["workerProfile"] = "" if profile == "off" else profile
        save_session(home, rec)
    s = worker_settings(home, sid)
    return f"worker settings of {sid}: " + worker_line(s)


def worker_profile(home):
    """The Anthropic profile a terminal worker names where no session sets one: `worker_profile` of the store's
    phi/phi.json where it is a string, an empty one for off, else the pair of worker_mode(home), WORKER_PAIRS."""
    return worker_settings(home)["profile"]


def worker_profile_set(home, name=None):
    """`phi.py worker_profile`: with no name it writes nothing and says how the key stands; with a name it writes it
    to the store's phi/phi.json, and `off` writes the empty string, keeping the file's other keys. Returns the line
    that says how the key stands as read back."""
    path = os.path.join(home, "phi", "phi.json")
    if name is not None:
        want = "" if name == "off" else name
        if want and not re.fullmatch(r"[A-Za-z0-9_-]+", want):
            raise ValueError("a worker profile's name holds letters, digits, _ and - only")
        d = read_json(path)
        if not d and os.path.exists(path) and os.path.getsize(path) > 2:
            raise ValueError(f"{path} does not parse as JSON, so it is left as it is")
        d["worker_profile"] = want
        write_atomic(path, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    now_ = worker_profile(home)
    return (f"worker_profile is {now_ or 'off'} in {path.replace(chr(92), '/')}"
            + (f": ezexe runs `ant auth login --profile {now_}` once" if now_ else ""))


def worker_mode(home):
    """How a terminal worker runs: `worker_mode` of the store's phi/phi.json where it is one of WORKER_MODES, else
    WORKER_MODE."""
    v = read_json(os.path.join(home, "phi", "phi.json")).get("worker_mode") if home else None
    return v if v in WORKER_MODES else WORKER_MODE


def worker_mode_set(home, mode=None):
    """`phi.py worker_mode`: with no mode it writes nothing and says how the key stands; with `print` or
    `interactive` it writes it to the store's phi/phi.json, keeping the file's other keys. The line read back."""
    path = os.path.join(home, "phi", "phi.json")
    if mode is not None:
        if mode not in WORKER_MODES:
            raise ValueError("a worker mode is print or interactive")
        d = read_json(path)
        if not d and os.path.exists(path) and os.path.getsize(path) > 2:
            raise ValueError(f"{path} does not parse as JSON, so it is left as it is")
        d["worker_mode"] = mode
        write_atomic(path, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    now_ = worker_mode(home)
    return (f"worker_mode is {now_} in {path.replace(chr(92), '/')}: a terminal worker runs as "
            + ("`claude -p`" if now_ == "print" else "an interactive `claude` tab"))


def app_tools_switch(home, on=None):
    """`phi.py app_tools on` and `app_tools off`: writes `app_tools` in the store's phi/phi.json, as `goal on` writes
    its key, and returns the line that says how it stands as read back. With neither it writes nothing and says how
    the key stands, which is on for a file that does not set it false, and whether P4_PHI_APP_TOOLS sets it for this
    run."""
    path = os.path.join(home, "phi", "phi.json")
    if on is None:
        stands, path = "off" if read_json(path).get("app_tools") is False else "on", path.replace(chr(92), "/")
    else:
        stands, path = switch(home, "app_tools", on)
    run = os.environ.get("P4_PHI_APP_TOOLS")
    return f"app_tools is {stands} in {path}" + (f", and P4_PHI_APP_TOOLS is {run} for this run"
                                                  if run in ("0", "1") else "")


def goal_text(s):
    """What `phi.py goal` prints: how the session's native goal stands, with its condition."""
    g = s.get("goal") if isinstance(s.get("goal"), dict) else None
    ask = s.get("goalAsk") if isinstance(s.get("goalAsk"), dict) else {}
    if ask.get("condition"):                       # asked for by the session, and no look has answered it yet
        g = {"condition": ask["condition"]}
    if not g:
        return "no goal was set for this session" + ("" if GOAL else ": `goal` is off in the store's phi.json")
    state = f"over, {g['over']}" if g.get("over") else ("set" if g.get("set") else "asked for and not set")
    tries = g.get("tries") if isinstance(g.get("tries"), int) else 0
    why = ""
    if not g.get("set") and not g.get("over") and (g.get("failed") or tries):
        left = max(0, GOAL_TRIES - tries)
        failed = str(g.get("failed") or "")
        why = ("\n" + (f"the command did not set it: {failed}. " if failed else "")
               + ("A stop of this session's turn took that command, which counts as no look. "
                  if STOP_REFUSED in failed or STOP_DROPPED in failed else "")
               + f"{tries} of {GOAL_TRIES} looks count against the condition"
               + (", and Claude Code refuses the command until a person types in this session, which a message "
                  "from another session does not lift: the look at the end of the turn a person's own words "
                  "begin answers the condition again." if g.get("stopped") and left else
                  ", and the look after a later turn's end answers it again." if left else
                  ", so no look answers it again: ask for it anew with the tool `mcp__p4-phi__goal`."))
    return f"goal {state}: {g.get('condition')}" + (f"\n{g['reason']}" if g.get("reason") else "") + why


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
    to, from book.flag, once for that message and target, so a resend goes through. A puppeteer's message that
    goes out takes the request its turn opened to the session messaged. No message is warned about for the files
    another session holds: each session works in the one checkout, on its own paths, so a go waits on no file."""
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
    if held:
        RAN["send_flagged"] = target[:40]
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": held}}
    if not spawned_from(s) and controls.is_puppeteer(s, me.home):
        import asks as requests                    # the request this turn opened goes to the session messaged
        try:
            requests.on_send(me.home, s, target, message)
        except Exception:  # noqa: BLE001
            pass
    return None


def h_start_advice(payload):
    """PreToolUse on mcp__ccd_session__start_session. It denies the starts that break a cap, MAX_DEPTH or
    MAX_CHILDREN, a controlled session's new orchestrator, which its puppeteer starts instead, a brief that changes files
    and names none, and one whose files a running session holds. For
    the rest it advises fork or fresh by relay.advise_start, from the parent's transcript size and how much of the parent's scope
    the brief's paths cover, for a writer's start as for any. It is silent when the call already does what is
    advised, else a permission `ask` with the reason, so ezexe sees it and decides. A start that passes
    `use_worktree: true` is asked about once: every session p4-phi starts works in its starter's checkout, on the
    paths of its `Files:` line, and a worktree's branch waits on a merge. A PreToolUse `permissionDecision` is `allow`,
    `deny`, `ask` or `defer`;
    where `permissions.denyInsteadOfPrompting` is set, a call that would wait on a prompt is denied. The input is
    never rewritten with `updatedInput`, since a fresh start needs a brief and background only the caller can
    write. A call that carries the marker of a start request to a puppeteer claims it, and is advised nothing."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if inp.get("proposal_id") and not inp.get("prompt"):
        return None                                 # starting a card already made: nothing to decide
    card = inp.get("initiation") == "own_initiative"
    mine = load_session(me.home, me.id)
    if spawned_from(mine):                          # only a session nobody started adds a desktop session
        RAN["terminal_only"] = True
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": (
                                           "phi (p4-phi): this start is refused: a session another session started "
                                           "starts its workers in the Terminal panel. Run `" + commands()
                                           + " draft \"<the task>\"` and then the `draft --start` line it prints. "
                                           "A new orchestrator is asked of the session above with `request "
                                           "... --to-puppeteer`.")}}
    cap = caps_text(me.home, mine) if mine.get("sessionId") else ""
    if cap:                                         # as deep, or with as many live sessions, as p4-phi allows
        RAN["caps"] = True
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "phi (p4-phi): this start is refused: " + cap}}
    if starts.claim(me.home, inp.get("prompt"), me.id, card=card):
        RAN["claimed"] = "card" if card else True   # a start request's call, given exactly: the asker decided it
        return None
    base = str(payload.get("cwd") or load_session(me.home, me.id).get("cwd") or "")
    here = str(inp.get("target") or "local") == "local" and not any(inp.get(k) for k in relay.ELSEWHERE)
    brief = str(inp.get("prompt") or "")
    if brief and here and not starts.ORCHESTRATOR.search(brief) and starts.writes(brief, base):
        files = starts.files_of(brief, base)
        if not files:
            RAN["partition"] = "no files"
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": (
                                               "phi (p4-phi): this start is refused: its brief changes files and "
                                               "names none. Give it a line `Files: <path>, <path>` with the paths or "
                                               "globs it alone may change, since every session works in the one "
                                               "checkout and is held to its paths.")}}
        ups = set(relay.above(me.home, me.id)) | {me.id}
        held = [h for h in relay.holders(me.home, "", files, base) if h[0] not in ups]
        if held:
            oid, title, theirs, _ = held[0]
            RAN["partition"] = oid
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": (
                                               f"phi (p4-phi): this start is refused: `{theirs}` is held by "
                                               f"\"{title}\" `{oid}`, which is still running. Narrow the `Files:` "
                                               f"line, or start this once that session has ended.")}}
    mine = load_session(me.home, me.id)
    parent, on = spawned_from(mine), cards_on(me)
    if on and parent:                               # the step before a start: nothing left for its session to ask
        why = cards.before_start(inp, mode_now(me, mine, payload), parent, issues.lander(me.home, mine),
                                 str(payload.get("cwd") or mine.get("cwd") or ""))
        if why:
            RAN["before_start"] = True
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": why}}
    wanted = "fork" if str(inp.get("context") or "fresh") == "fork" else "fresh"
    try:
        size = os.path.getsize(payload.get("transcript_path") or "")
    except OSError:
        size = 0
    advised, why = relay.advise_start(me.home, me.id, inp, size)
    RAN.update(advice=advised, wanted=wanted, transcript=size)
    if inp.get("use_worktree") is True:             # a worktree leaves the partition, and its branch waits on a merge
        return cards.raised(on, parent, "phi (p4-phi) advises `use_worktree: false` here: every session p4-phi "
                            "starts works in its starter's checkout, on the paths of its `Files:` line, and a "
                            "worktree's branch waits on a merge.")
    if advised == wanted:
        return None
    return cards.raised(on, parent, f"phi (p4-phi) advises context \"{advised}\" here, not \"{wanted}\": {why}.")


def cards_on(me):
    """Whether the set of what p4-phi settles with no approval card is in force for this session's project, by
    p4conf.cards_on: ezexe's yes to the set as this copy has it stands in the store's p4.json."""
    return p4conf.cards_on(me.store or me.home)


def mode_now(me, s, payload):
    """The permission mode this session is in, or '' where nothing says: as the hook's own input gives it, hooks.md's
    `permission_mode`, else as the app's record holds it, else as h_user_prompt_submit kept it at the session's last
    prompt. The app's record holds none for a session it did not start and for one whose record is not read, and
    the hooks module's check hands a PreToolUse input with no mode. Both of those were read before a call of
    `EnterPlanMode` or `ExitPlanMode` inside the turn, so the yes or no h_plan_mode kept at that call comes ahead of
    them: a yes is `plan`, and a no takes `plan` out of what they said."""
    said = str(payload.get("permission_mode") or "")
    if said:
        return said
    kept = str(upkeep.mode_of(me.id) or s.get("permissionMode") or "")
    if isinstance(s.get("planMode"), bool):
        return "plan" if s["planMode"] else "" if kept == "plan" else kept
    return kept


def first_message(path):
    """The first message a transcript holds, a session's brief, as (its text, False), or ('', True) where the
    transcript opens with a compaction's summary: a row Claude Code marks `isCompactSummary` comes before any
    message, so the brief was written before the rows this file holds and the next message is a later one. A meta
    row and a subagent's row are no message."""
    for d in read_rows(path):
        if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
            continue
        if d.get("isCompactSummary"):
            return "", True
        content = (d.get("message") or {}).get("content")
        if isinstance(content, list):
            content = "\n".join(str(b.get("text") or "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(content, str) and content.strip():
            return content, False
    return "", False


def brief_pushes(me, s, payload):
    """Whether this session's brief tells it to push, as kept at its first message. A session that began before the
    key existed has none, so its first message is read from its transcript once and kept. Where that transcript
    opens with a compaction's summary the summary is no brief: the brief is read from the transcript of an earlier
    CLI session id of the session, in the same folder, oldest first as session.json's cliSessionIds holds them, and
    where none holds it, from the task kept at the session's first message."""
    if "pushes" not in s:
        path = str(payload.get("transcript_path") or "")
        first, summed = first_message(path)
        for cli in (s.get("cliSessionIds") or []) if summed else []:
            older = os.path.join(os.path.dirname(path), f"{safe_id(cli)}.jsonl")
            if relay.norm(older) != relay.norm(path):
                first = first_message(older)[0]
            if first:
                break
        s["pushes"] = cards.brief_pushes(first or s.get("task"))
        save_session(me.home, s)
    return s["pushes"] is True


QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
# a git command that moves the checkout it runs in to another branch: `git switch`, `git checkout -b` and `git
# checkout <branch>`. Restoring a file, as `git checkout -- <path>` or `git checkout <file>`, moves nothing, and
# neither does `git branch <name>` or `git worktree add`.
BRANCH_MOVE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git\b[^\n|;&]*?\b(switch\b|checkout\s+-[bB]\b|"
                         r"checkout\s+(?!-)(?![\w./-]*\.\w{1,6}\s*$)[\w./-]+\s*$)")
# a git command that stages or commits by itself, or sets work aside: in a checkout other sessions share it takes
# their changes with it. Read as BRANCH_MOVE is, on the line with its quoted parts taken out.
SHARED_TAKE = re.compile(r"(?:^|&&|\|\||;|\||\n)\s*git(?:\s+(?:-[Cc]\s+\S+|--[\w-]+(?:=\S+)?))*\s+"
                         r"(commit|add(?!\s+(?:-n|--dry-run)\b)|stash(?!\s+(?:list|show)\b)|rm|mv)(?![\w-])")


def shared_repo(home, s, folders):
    """True when one of `folders` lies in a repository another running session works in, by that session's `cwd`: a
    repository this session made for itself, as a test's fixture, is shared with nobody and takes nobody's changes.
    The folders are those the line names with `cd` or `git -C`, where git then runs, else the hook's own. Where the
    record of the session that started this one holds no folder, nothing shows the repository is this session's
    alone, and it is taken as shared."""
    if not load_session(home, spawned_from(s)).get("cwd"):
        return True
    theirs = {relay.repo_of(relay.norm(str(o.get("cwd") or ""))) for oid, o in relay._sessions(home).items()
              if oid != s.get("sessionId") and o.get("cwd") and not relay.gone(home, o)} - {""}
    found = [relay.repo_of(f) for f in folders if f]     # a folder in no repository found shows nothing either
    return not found or any(not r or r in theirs for r in found)


def own_checkout(home, s, cwd):
    """True when a started session works in a git worktree of its own. worktrees.md, "What worktrees share with the
    main checkout": for a worktree session started from the desktop app, "To reach the files Claude is working on,
    read the worktree's path from the hook's `cwd` input field." So the folder `cwd` lies in is read: it is a linked
    worktree, by its `.git` file, and it is not the checkout the session's starter works in, by that session's
    record. A session started with `use_worktree: false` works in its starter's checkout, a worktree or not, and
    gets False."""
    here = relay.repo_of(cwd) if cwd else ""
    if not here:
        return False
    main, found = p4conf.main_root(here)
    if not found or relay.norm(os.path.realpath(main)) == here:
        return False                               # the main checkout, which the sessions started without one share
    above = load_session(home, spawned_from(s))
    return relay.repo_of(str(above.get("cwd") or "")) != here


def h_branch_guard(payload):
    """PreToolUse on a shell call in a session another session started. Landing work, a git push, merge, rebase or
    pull, is asked first, whatever the child's record, brief or parent says: only the tree's orchestrator lands and
    pushes. A child that shares its starter's checkout, as one started with `use_worktree: false` does, is asked
    before it moves that checkout to another branch, since the move is its starter's too. A session in a git
    worktree of its own, as own_checkout reads it, is asked about no branch it makes or moves to and no worktree it
    makes or enters, since its checkout is its own. Silent otherwise. No check is routed here for the
    EnterWorktree tool, which is Claude Code's own way into a worktree."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    if not spawned_from(s):
        return None
    name = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if name not in SHELL_TOOLS:
        return None
    on, parent = cards_on(me), spawned_from(s)
    text = QUOTED.sub("''", str(inp.get("command") or ""))
    moves = BRANCH_MOVE.search(text)
    takes = SHARED_TAKE.search(text)
    if not moves and not takes and not issues.landing(inp.get("command")):
        return None
    # a worktree of its own is judged where the command runs: the hook's folder, and each folder the line names
    # with `cd` or `git -C`, so a line aimed at a checkout the session shares is never read as its own
    here = str(payload.get("cwd") or s.get("cwd") or "")
    line = str(inp.get("command") or "")
    named = [m.group(1).strip("'" + '"') for m in list(CD.finditer(line)) + list(DASH_C.finditer(line))]
    own = all(own_checkout(me.home, s, relay.norm(p, relay.norm(here)) if here else p) for p in [here] + named)
    if takes and not own and shared_repo(me.home, s, [relay.norm(p, relay.norm(here)) if here else p
                                                      for p in (named or [here])]):
        command = str(inp.get("command") or "").strip()
        RAN["branch_guard"] = command
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": (
                                           f"phi (p4-phi): this session shares its checkout with other sessions, and "
                                           f"`{command}` takes or sets aside whatever is changed there, theirs too. "
                                           f"Commit with `{commands()} commit -m \"<message>\" -- <path> ...`, "
                                           f"which takes only the paths it is given. A rename is an add of the new "
                                           f"path and a removal of the old, both named there.")}}
    if moves and not own:
        what = "moving the checkout to another branch, which in a shared checkout moves the parent's too"
    elif issues.landing(inp.get("command")):
        verbs = issues.landings(inp.get("command"))
        if on and own:                             # the set: a worktree's own branch, and a push its brief names
            left = [v for v in verbs if v not in cards.OWN_BRANCH
                    and not (v == "git push" and brief_pushes(me, s, payload))]
            if not left:
                RAN["branch_guard"] = "unasked: " + ", ".join(verbs)
                return None
            verbs = left
        verb = verbs[0]
        RAN["branch_guard"] = verb
        return cards.raised(on, parent, f"phi (p4-phi): this session is a child, and `{verb}` lands work, which "
                                        f"only the tree's orchestrator does: a child commits by "
                                        f"`phi.py commit` and reports, a `Closes #N` commit included, and the tree's "
                                        f"orchestrator merges and pushes. Ask its "
                                        f"parent session, {parent}, with SendMessage instead.")
    else:
        return None
    RAN["branch_guard"] = what
    return cards.raised(on, parent, f"phi (p4-phi): this session is a child, and {what} is asked first: this "
                                    f"session works in the checkout of the session that started it.")


def _deny(why, key):
    RAN["path_guard"] = key
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": why}}


def h_path_guard(payload):
    """PreToolUse on Edit, Write and NotebookEdit: an edit outside the paths a started session holds is refused
    before it runs, as is an edit in a repository where a session this one started holds paths and still runs, and
    one on a path another running session holds. hooks.md, "PreToolUse decision control": `deny` prevents the tool
    call. A path under `.claude/` and a file in no git repository are let through."""
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    raw = inp.get("notebook_path") if str(payload.get("tool_name") or "") == "NotebookEdit" else inp.get("file_path")
    if not raw:
        return None
    cwd = relay.norm(str(payload.get("cwd") or s.get("cwd") or ""))
    file = relay.norm(str(raw), cwd)
    repo = relay.repo_of(file) if file else ""
    if not repo or file[len(repo):].lstrip("/").startswith(".claude/"):
        return None
    for kid, k in relay.running_children(me.home, me.id):
        theirs = [relay.norm(p, k.get("cwd") or cwd) for p in relay.paths_of(k)]
        if any(t and relay.repo_of(t) == repo for t in theirs):
            return _deny(f"phi (p4-phi): this edit is refused: \"{k.get('title') or kid}\" `{kid}`, which this "
                         f"session started, is still running in this checkout and holds {', '.join(theirs)}. A "
                         f"session edits nothing here while a session it started works. Send it the change by "
                         f"SendMessage, or make it once it has ended.", "child")
    mine = relay.paths_of(s)
    if spawned_from(s) and mine and not any(relay.overlap(file, relay.norm(m, cwd)) for m in mine):
        return _deny(f"phi (p4-phi): this edit is refused: {file} is outside this session's paths, "
                     f"{', '.join(mine)}. Ask the session that started it, {spawned_from(s)}, by SendMessage: it "
                     f"holds the path or gives it.", "outside")
    held = relay.holders(me.home, me.id, [file], cwd)
    if held:
        oid, title, _, _ = held[0]
        return _deny(f"phi (p4-phi): this edit is refused: {file} is held by \"{title}\" `{oid}`, which is still "
                     f"running.", "held")
    return None


def _commit_paths_of(cmd):
    """The paths a `phi.py commit` line names after its `--`: that command changes no file."""
    if not re.search(r"phi\.py\b.*\bcommit\b", cmd) or " -- " not in cmd:
        return []
    return [x.strip("'\"") for x in cmd.split(" -- ", 1)[1].split("&&")[0].split()]


def h_path_seen(payload):
    """PostToolUse on a shell call: the paths Claude Code listed as changed by it, `tool_response.bashEditDiff.
    changedFiles`, absolute, which lie outside the paths a started session holds, are named to it beside the result.
    hooks.md: the list is best effort, to find what to review and no policy to enforce, so it is said and not
    enforced. A PowerShell call has no such field, and a path under `.claude/` or one a `phi.py commit` line names is
    left out."""
    resp = payload.get("tool_response")
    diff = resp.get("bashEditDiff") if isinstance(resp, dict) else None
    changed = diff.get("changedFiles") if isinstance(diff, dict) else None
    if not isinstance(changed, list) or not changed:
        return None
    me = Me(payload)
    if not me.home or not me.id:
        return None
    s = load_session(me.home, me.id)
    mine = relay.paths_of(s)
    if not spawned_from(s) or not mine:
        return None
    cwd = relay.norm(str(payload.get("cwd") or s.get("cwd") or ""))
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    named = {relay.norm(p, cwd) for p in _commit_paths_of(str(inp.get("command") or ""))}
    top = relay.repo_of(cwd) if cwd else ""
    stray = []
    for f in changed:
        n = relay.norm(str(f))
        if not n or n in named or any(relay.overlap(n, relay.norm(m, cwd)) for m in mine):
            continue
        if (n[len(top):] if top and n.startswith(top + "/") else n).lstrip("/").startswith(".claude/"):
            continue
        stray.append(n)
    if not stray:
        return None
    RAN["path_seen"] = len(stray)
    shown = ", ".join(stray[:12]) + (f" and {len(stray) - 12} more" if len(stray) > 12 else "")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
        f"phi (p4-phi): that command changed {shown}, outside this session's paths, {', '.join(mine)}. Put each "
        f"back unless a session beside this one changed it at the same moment: `git restore -- <path>` for a file "
        f"git tracks, and delete one that is new. `phi.py commit` takes none of them. A file the job must change "
        f"beyond its paths is asked of {spawned_from(s)} by SendMessage.")}}


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
    """PreToolUse on a shell call: a hand `git pull`, `git push` or force-push in a store is asked first, since two
    machines write the same files and a plain merge or a line-union damages them. A session another session started
    is also told which session moves the store: its tree's orchestrator, the one session that lands and pushes.
    hook.py runs this guard ahead of the branch guard, so a started session's pull or push inside a store hears of
    the store and not only of its parent's landing."""
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
    me = Me(payload)
    s = load_session(me.home, me.id) if me.home and me.id else {}
    top, title = issues.lander(me.home, s) if spawned_from(s) else ("", "")
    whose = (f" This session is a child, and a move of the store is its tree's orchestrator's to make, \"{title}\" `{top}`, "
             f"the one session that lands and pushes: ask that session with SendMessage, and run neither here."
             if top else "")
    return cards.raised(cards_on(me) if me.home else False, top,
                        f"phi (p4-phi): this is {what} in the store {store}. Two machines write the same "
                        f"files, and a plain merge or a line-union damages them, so it is asked first.{whose}")


def h_force_guard(payload):
    """PreToolUse on a shell call, with the set of p4conf.CARD_SET in force: a git command the general part never
    covers, as issues.risks reads the whole line, is asked of ezexe in a session no session started and refused in
    a started one, by cards.raised. Two pass unasked where the command runs in the hook's own folder, since the
    check is the go: a hard reset in a worktree that holds no uncommitted change and no commit the default branch
    lacks, and a forced deletion of branches whose every commit is on the default branch by hash or by patch.
    Silent with the set off."""
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    line = str(inp.get("command") or "")
    found = issues.risks(line)
    if not found:
        return None
    me = Me(payload)
    if not me.home or not cards_on(me):
        return None
    here = str(payload.get("cwd") or "")
    # a check of the tree holds only for a line that is one command run where the hook says: behind `cd`, `-C` or
    # an earlier command of the same line the tree is another by the time the command runs
    plain = bool(here) and not CD.search(line) and not DASH_C.search(line) \
        and not re.search(r"&&|\|\||[;|\n]", QUOTED.sub("''", line))

    def spared(kind, names):
        if not plain:
            return False
        if kind == "reset":                        # no uncommitted change, and each commit is on the default branch
            return upkeep.dirty(here) == 0 and upkeep.landed(here, "HEAD") is True
        if kind == "branch":                       # each commit is on the default branch, by hash or by patch
            return bool(names) and all(upkeep.landed(here, n) is True for n in names)
        return False
    left = [(what, kind) for what, kind, names in found if not spared(kind, names)]
    if not left:
        return None
    what, kind = left[0]
    s = load_session(me.home, me.id) if me.id else {}
    RAN["force_guard"] = kind
    return cards.raised(True, spawned_from(s),
                        f"phi (p4-phi): this is {what}, which the set of what p4-phi settles with no approval card "
                        f"never covers: a force, a deletion of work found nowhere else and a stored login stay "
                        f"ezexe's.")


def h_cards_guard(payload):
    """PreToolUse on a shell call that runs `phi.py cards on`: the one approval card the set has. What p4-phi
    settles with no card is a permission, so the yes is ezexe's own press on Claude Code's card, which a hook's
    `ask` raises in every permission mode, and the card's text is the set whole. The call is marked as asked about,
    with the store and the set the card names, for h_cards_yes to read once the call has run. A session another
    session started is refused the command: the top session brings the set to ezexe."""
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not cards.CARDS_ON.search(str(inp.get("command") or "")):
        return None
    me = Me(payload)
    s = load_session(me.home, me.id) if me.home and me.id else {}
    RAN["cards_guard"] = True
    if spawned_from(s):
        top, title = issues.lander(me.home, s)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": (
                                           f"phi (p4-phi): `phi.py cards on` is refused in a session another "
                                           f"session started. What p4-phi settles with no approval card is "
                                           f"ezexe's to decide, in the top session \"{title}\" `{top}`: send it "
                                           f"the set with SendMessage, as `phi.py cards` prints it.")}}
    store = me.store or me.home
    mark = cards_mark(me.home, me.id, payload)
    if mark:
        write_atomic(mark, json.dumps({"store": store, "set": p4conf.card_set_id(), "time": now()}) + "\n")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": cards.approval(store)}}


def cards_mark(home, sid, payload):
    """The file that says p4-phi raised the set's approval card for a call, by the call's id, in the session's
    folder beside the marks of once; '' for a call with no id or a hook with no session."""
    tid = SAFE.sub("_", str(payload.get("tool_use_id") or ""))[:80]
    return os.path.join(session_dir(home, sid), ".calls", f"cards-asked-{tid}") if tid and home and sid else ""


def h_cards_yes(payload):
    """PostToolUse on a shell call that ran `phi.py cards on`: ezexe's yes to the set, kept. The command writes the
    key and no more, so a key written any other way leaves the set off, p4conf.cards_on. hooks.md gives PostToolUse
    as fired "after a tool has already executed successfully", and a call h_cards_guard answered `ask` for runs
    only once ezexe has pressed its card, so this hook's run for a call that guard marked is the press. The yes is
    kept for the store the card named, and only where that store's key names the set the card showed. A call that
    failed raises PostToolUseFailure and keeps none, and so does a call no card was raised for, as one made while
    another copy of the plugin was loaded. Says how the set stands, beside the call's result."""
    if str(payload.get("hook_event_name") or "") != "PostToolUse":
        return None
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return None
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not cards.CARDS_ON.search(str(inp.get("command") or "")):
        return None
    me = Me(payload)
    mark = cards_mark(me.home, me.id, payload)
    asked = read_json(mark) if mark else {}
    if not asked.get("store") or asked.get("set") != p4conf.card_set_id():
        return None
    try:
        os.remove(mark)                            # one press keeps one yes
    except OSError:
        pass
    if spawned_from(load_session(me.home, me.id)):
        return None
    store, call = str(asked["store"]), str(payload.get("tool_use_id") or "")
    lines = cards.kept(store, me.id, call) or cards.kept(store, me.id, call)   # once more where the lock was held
    RAN["cards_yes"] = bool(lines)
    if not lines and p4conf.cards_asked(store) == p4conf.card_set_id():
        # the key names the set and the yes is not in the record: the press is not lost with no word
        return ("phi (p4-phi): ezexe's yes to the set is not kept: the store's settings lock was held by another run "
                "of the keeper for the whole of two waits. The set is not in force. Run the command again, which asks "
                "once more.")
    return "phi (p4-phi): " + " ".join(lines) if lines else None


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
    so a session whose hook list lacks hook.py's entries has only phi.py's own, and its calls are read
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
    """A phi.py handler run from hook.py, at hook.py's entry or at the hooks module's check before a tool
    call, with the hook output phi.py would give and its log line."""
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
    """PreToolUse on Agent, from hook.py's entry: the text for the subagent's start, its step and its
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
    """SubagentStart, from hook.py's entry: the subagent bound by the `agent_id` the input carries to the
    launching session's step in progress, and its marker opened under phi/.agents/ for the plugin's hooks module,
    which checks each call of a subagent a marker names. An input with no `agent_type` is no subagent the Agent
    tool started and is left alone."""
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
    """A subagent's tool call, before it runs, routed from hook.py's `lookup-check`: warned of what changed beside
    the launching session, held against its own transcript for when it started and what it has heard already.
    The plugin's hooks module runs a subagent's check, at any tool, only while phi/.agents/ names it."""
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


WRITE_TOOLS = ("Edit", "Write", "NotebookEdit")


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
    """The files a subagent's calls wrote, by Edit, Write or NotebookEdit, each once."""
    out = []
    for c in calls:
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if c.get("name") in WRITE_TOOLS and path and path not in out:
            out.append(path)
    return out


def h_agent_stop(payload):
    """SubagentStop, from hook.py's entry: the subagent's entry closed, and the files its own transcript
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
         "cards-guard": ("PreToolUse", h_cards_guard),
         "plan": ("PostToolUse", h_plan),
         "memory-gap": ("PostToolUse", h_memory_gap),
         "task-stop": ("PostToolUse", h_task_stop),
         "self-archive": ("PreToolUse", h_self_archive)}
ROUTED.update({k: HOOKS[k] for k in ("start-advice", "branch-guard", "store-guard", "cards-guard", "plan",
                                     "memory-gap", "self-archive", "task-stop")})
ROUTED["wrap-up"] = ("PostToolUse", h_wrap_up)
HOOKS["go-guard"] = ROUTED["go-guard"] = ("PreToolUse", h_go_guard)
HOOKS["restart-check"] = ROUTED["restart-check"] = ("PreToolUse", h_restart_check)
ROUTED.update({"agent-launch": ("PreToolUse", h_agent_launch), "agent-start": ("SubagentStart", h_agent_start),
               "agent-pre": ("PreToolUse", h_agent_call), "agent-stop": ("SubagentStop", h_agent_stop)})
HOOKS["path-guard"] = ROUTED["path-guard"] = ("PreToolUse", h_path_guard)
HOOKS["path-seen"] = ROUTED["path-seen"] = ("PostToolUse", h_path_seen)
HOOKS["issue-guard"] = ROUTED["issue-guard"] = ("PreToolUse", h_issue_guard)
HOOKS["force-guard"] = ROUTED["force-guard"] = ("PreToolUse", h_force_guard)
HOOKS["issue-tie"] = ROUTED["issue-tie"] = ("PostToolUse", h_issue_tie)
HOOKS["cards-yes"] = ROUTED["cards-yes"] = ("PostToolUse", h_cards_yes)
HOOKS["plan-mode"] = ROUTED["plan-mode"] = ("PostToolUse", h_plan_mode)


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
        controls.one_hook(True)                     # each controlled session is read once in this hook
        try:
            text = fn(payload)
        finally:
            controls.one_hook(False)
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
    save_session(home, s)                            # it keeps the store it has: nothing is moved
    append_line(reports_path(home, old), {"time": now(), "left": sid, "to": under})
    turns = load_turns(home, sid)
    if turns:
        append_line(reports_path(home, under),
                    {"time": now(), "sessionId": sid, "title": name_of(s), "turn": turns[-1]})
    for x in (sid, old, under):
        render_page(home, x)
    return True


def tree_text(home):
    sessions = relay._sessions(home)               # the flat sessions and those of every node's store
    gone_ = {k for k, d in sessions.items() if d.get("archived") or relay.archived_in_app(d)}
    started = {}
    for s in sorted(sessions.values(), key=lambda s: s.get("createdAt", "")):
        above = spawned_from(s)
        if s["sessionId"] in gone_ or above in gone_:
            continue                                 # an archived session, and what hangs under it, is not printed
        started.setdefault(above if above in sessions else "", []).append(s)
    out = []
    where = nd.addresses(home, sessions)

    def walk(above, depth):
        for s in started.get(above, []):
            turns = load_turns(home, s["sessionId"])
            if not turns and not clean(s.get("title")) and not clean(s.get("task")):
                walk(s["sessionId"], depth)          # no record and no turns: an empty entry, its children kept
                continue
            state = ("done" if turns[-1].get("done") else "not shown done") if turns else "no turn yet"
            rec = nd.record(home, s["sessionId"], sessions)
            address = nd.short(where[s["sessionId"]], rec["places"]) if s["sessionId"] in where else "-"
            out.append(f"{'  ' * depth}- {address} {rec['level']} \"{title_of(s)}\" `{s['sessionId']}`: {state}, "
                       f"{len(turns)} turn{'s' * (len(turns) != 1)}")
            out.extend(f"{'  ' * depth}  - {x['level']} {x['name']}: {x['state']}" for x in rec["leaves"])
            if depth < 30:
                walk(s["sessionId"], depth + 1)
    walk("", 0)
    return "\n".join(out)


def shared_main(argv):
    """`phi.py shared [folder]`: what a worktree of that folder's checkout shares, as a brief's lines."""
    print(shared.text(os.path.abspath(argv[0] if argv else os.getcwd())) or shared.NONE)
    return 0


def unlink_main(argv):
    """`phi.py unlink <worktree>`: each link the linked worktree holds among what git does not track is taken away
    and its target left, and the removal that follows is printed."""
    tree = os.path.abspath(argv[0]) if argv else ""
    top, main = shared.tree_of(tree) if tree else ("", "")
    same = lambda a, b: os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))  # noqa: E731
    if not top or not same(top, tree) or same(top, main):
        print(f"phi: {tree or 'no folder'} is not the top folder of a linked worktree, so nothing is unlinked",
              file=sys.stderr)
        return 2
    found = upkeep.links(tree)
    if found is None:
        print(f"phi: git could not list what it ignores in {tree}, so nothing is unlinked", file=sys.stderr)
        return 2
    for p in found:
        print(("unlinked " if shared.unlink(p) else "left, since it could not be unlinked: ") + p)
    if upkeep.links(tree) == []:
        print(f"no link is left there: `git -C \"{main}\" worktree remove \"{tree}\"`, with no force and run from a "
              "folder outside the worktree, removes it now".replace("\\", "/"))
    return 0


def remove_main(argv):
    """`phi.py remove <worktree>`: upkeep.remove for the folder, from where this command was run."""
    status, lines = upkeep.remove(argv[0] if argv else "", os.getcwd())
    for line in lines:
        print(line, file=sys.stderr if status else sys.stdout)
    return status


COMMIT_TRIES = 100                             # repeats of a git call whose output names index.lock
COMMIT_WAIT = 0.1                              # seconds between them


def git_again(args, cwd, tries=COMMIT_TRIES, wait=COMMIT_WAIT):
    """`git <args>` in `cwd`, run again after `wait` seconds while its output names index.lock, up to `tries` times:
    (the finished process, True where the lock was still there after the last repeat)."""
    for k in range(tries + 1):
        ran = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        if ran.returncode == 0 or "index.lock" not in ran.stdout + ran.stderr:
            return ran, False
        if k < tries:
            time.sleep(wait)
    return ran, True


def commit_paths(checkout, message, paths, tries=COMMIT_TRIES, wait=COMMIT_WAIT):
    """The commit of exactly `paths` in `checkout`, as (status, lines): each path must be inside the checkout and
    outside `.claude`, then `git add` and `git commit --only` take each as a literal pathspec, so what a sibling has
    staged stays out. Git's own words end it on any failure but the lock, which is waited for."""
    top = os.path.realpath(checkout)
    specs, bad = [], []
    for p in paths:
        try:
            rel = os.path.relpath(os.path.realpath(os.path.join(top, p)), top).replace("\\", "/")
        except ValueError:                         # another drive
            rel = ".."
        parts = rel.split("/")
        if rel == "." or parts[0] == ".." or ".claude" in parts:
            bad.append(p)
        specs.append(":(literal)" + rel)
    if not paths or bad:
        return 2, [f"phi: {', '.join(bad) if bad else 'no path'} " + ("is not a path inside the checkout and outside "
                                                                    ".claude, so nothing is committed" if bad else
                                                                    "was given to commit")]
    trailer = subprocess.run(["git", "log", "-1", "--format=%(trailers:only,unfold)"], cwd=top, capture_output=True,
                             text=True, encoding="utf-8", errors="replace").stdout.strip()
    kept = [l for l in trailer.splitlines() if l.strip() and l not in message]
    text = message.rstrip() + ("\n\n" + "\n".join(kept) if kept else "")
    for args in (["add", "--", *specs], ["commit", "--only", "-m", text, "--", *specs]):
        ran, locked = git_again(args, top, tries, wait)
        if locked:
            return 1, [f"phi: git's index.lock was still there after {tries} repeats of `git {args[0]}`: "
                       "nothing is committed"]
        if ran.returncode:
            return ran.returncode, [(ran.stderr or ran.stdout).strip()]
    short = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=top, capture_output=True, text=True).stdout
    shown = subprocess.run(["git", "show", "--name-status", "--format=", "HEAD"], cwd=top, capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout
    return 0, [short.strip(), *shown.strip().splitlines()]


def commit_main(argv):
    """`phi.py commit -m <message> [--checkout <dir>] -- <path> ...`: commit_paths, which needs no store."""
    import argparse
    ap = argparse.ArgumentParser(prog="phi.py commit")
    ap.add_argument("-m", "--message", required=True)
    ap.add_argument("--checkout", default="")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args(argv)
    checkout = os.path.abspath(a.checkout or os.getcwd())
    if os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") and a.paths:
        try:
            me = Me()
            rec = load_session(me.home, me.id) if me.home and me.id else {}
            mine = relay.paths_of(rec) if spawned_from(rec) else []
        except Exception:  # noqa: BLE001
            mine = []
        base = relay.norm(str(rec.get("cwd") or checkout)) if mine else ""   # where its paths were kept from
        for p in a.paths if mine else ():
            n = relay.norm(p, relay.norm(checkout))
            if not any(relay.overlap(n, relay.norm(m, base)) for m in mine):
                print(f"phi: {p} is outside this session's paths, {', '.join(mine)}: nothing is committed",
                      file=sys.stderr)
                return 2
    status, lines = commit_paths(checkout, a.message, a.paths)
    for line in lines:
        print(line, file=sys.stderr if status else sys.stdout)
    return status


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["commit"]:                     # a worker runs with the p4 plugins off and has no session record
        return commit_main(argv[1:])
    if argv[:1] == ["hook"]:
        return hook_main(argv[1] if len(argv) > 1 else "")
    if argv[:1] == ["rules"]:                      # the hooks module's own, which needs no store
        return rules_main()
    if argv[:1] == ["shared"]:                     # read from the main checkout's store, wherever it is run
        return shared_main(argv[1:])
    if argv[:1] == ["unlink"]:
        return unlink_main(argv[1:])
    if argv[:1] == ["remove"]:                     # a worktree's removal, which needs no store either
        return remove_main(argv[1:])
    import argparse
    ap = argparse.ArgumentParser(description="phi.py: what linked sessions hand each other")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("note", "done", "task", "show", "tree", "background", "detach", "reparent", "shard", "disposable",
                 "request", "proof", "controls", "gaps", "upkeep", "goal", "app_tools", "worker_profile", "worker_mode", "worker_for", "balance", "cards", "conf", "sections",
                 "coworkers", "progress", "spend", "node"):
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
        if name == "sections":
            p.add_argument("plan", help="the plan file ezexe approved, whose runs of sections are printed, each "
                                        "as the terminal call that starts the worker that lands it")
        if name == "coworkers":
            p.add_argument("plan", nargs="?", default="",
                           help="the plan file whose groups of sections are printed, each with its coworker; "
                                "left out with --wait --report")
            p.add_argument("--checkout", default="", help="the repository the coworkers and workers run in, the "
                                                          "folder this is run from when left out")
            p.add_argument("--land", action="store_true",
                           help="give the terminal worker that lands each group not landed a node, write its start "
                                "file, brief and settings file there with its report's name, and print the "
                                "terminal call that starts each: for after the approval, from a session in auto or "
                                "bypass mode")
            p.add_argument("--report", default="", metavar="FILE",
                           help="with --wait: wait for this terminal worker's report file instead of for coworkers")
            p.add_argument("--wait", nargs="*", default=None, metavar="NAME",
                           help="wait until no coworker wrote a line for a while, then name each one an error of "
                                "the API stopped: the coworkers named, or the plan's own where none is named")
        if name == "spend":
            p.add_argument("who", nargs="?", default="",
                           help="a session id of the store or the name a terminal session was started under, this "
                                "session when left out")
        if name == "goal":
            p.add_argument("act", nargs="?", default="", choices=("", "on", "off", "set", "failed", "ask"),
                           help="on and off write `goal` in the store's phi.json; set is the hooks module's word "
                                "that the goal command set the goal, and failed its word that it did not; ask "
                                "keeps the condition this session states as the goal it asks for; none prints how "
                                "the session's native goal stands")
            p.add_argument("condition", nargs="?", default="", help="with ask: what holds when the work is done; "
                                                                    "with failed: what the command answered")
        if name == "app_tools":
            p.add_argument("act", nargs="?", default="", choices=("", "on", "off"),
                           help="on and off write `app_tools` in the store's phi.json, which is on unless set off "
                                "and has the hooks module ask the desktop app's own tools for sessions; none "
                                "prints how the key stands")
        if name == "worker_profile":
            p.add_argument("name", nargs="?", default=None,
                           help="the Anthropic profile a terminal worker names in its tab, which `ant auth login "
                                "--profile <name>` wrote, or `off` for none; left out it prints how the key stands")
        if name == "worker_mode":
            p.add_argument("mode", nargs="?", default=None,
                           help="print starts a terminal worker as `claude -p` with a stream-json log, "
                                "interactive as an interactive tab; left out it prints how the key stands")
        if name == "worker_for":
            p.add_argument("--mode", default=None, help="print, interactive or default (removes the key) for the "
                                                         "session; left out it is not changed")
            p.add_argument("--profile", default=None, help="a profile name, off or default (removes the key) for "
                                                            "the session; left out it is not changed")
        if name == "cards":
            p.add_argument("act", nargs="?", default="", choices=("", "on", "off"),
                           help="on puts the set of what p4-phi settles with no approval card in force for the "
                                "store, behind one approval card that is ezexe's yes to the set whole; off takes "
                                "it out; none prints the set, its id, how it stands and every kind of card")
            p.add_argument("set", nargs="?", default="", help="with on: the id of the set, as `phi.py cards` prints it")
        if name == "node":
            p.add_argument("moved", nargs="?", default="", help="the session whose node is printed, this one when "
                                                                "left out")
        if name == "detach":
            p.add_argument("moved", nargs="?", default="", help="the session to detach to top level, this one when "
                                                                "left out")
        if name == "conf":
            p.add_argument("key", nargs="?", default="", help="a setting of p4.json by its dotted path, such as "
                                                              "phi.worktree_python; none lists every setting")
            p.add_argument("value", nargs="?", default=None, help="what to set it to, as its variable would hold "
                                                                  "it; none prints the key")
            p.add_argument("--unset", action="store_true", help="put the key back at its default")
        if name == "reparent":
            p.add_argument("moved")
        if name == "shard":
            p.add_argument("paths", nargs="*", help="the owned paths, paths or globs this session alone may change; "
                                                    "none shows them")
        if name == "reparent":
            p.add_argument("under")
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
        if name == "upkeep":
            p.add_argument("act", nargs="?", default="", choices=("", "on", "off", "close", "wait"),
                           help="on or off sets phi.upkeep in the store's p4.json; close closes an open item or "
                                "wait; wait keeps a step that waits on a session, with --on, or on a time when no "
                                "session may be open, with --at; none prints what is due")
            p.add_argument("what", nargs="?", default="", help="for close, the item's or wait's id; for wait, the "
                                                               "step that waits")
            p.add_argument("--on", dest="waits_on", default="", help="for wait: the session the step waits on")
            p.add_argument("--at", dest="waits_at", default="",
                           help="for wait: when the step falls due, as `tomorrow at 9am` or `every weekday at 7am`; "
                                "it prints the scheduled run of Claude Code that fits, for ezexe to make")
            p.add_argument("--local", action="store_true",
                           help="for wait --at: the step needs the project's local store or other files of this "
                                "machine, which a cloud run's clone does not hold")
            p.add_argument("--commit", default="", help="for close: a commit on the remote's default branch")
            p.add_argument("--note", default="", help="for close: why it is left")
            p.add_argument("--ezexe", default="", help="for close: ezexe's own words, in a turn ezexe began")
        if name == "controls":
            p.add_argument("--decline", nargs=2, metavar=("REQUEST", "WHY"), help="a request addressed to it")

    def common(p):
        p.add_argument("--p4", default="", help="the store the sessions' files live in, this session's when left out")
        p.add_argument("--session", default="", help="the sessionId, this session's when left out")
    puppeteer.add_parsers(sub, common)
    # the look's own flag for the native goal, which goal_look reads: puppeteer.py holds the look's other arguments
    sub.choices["look"].add_argument("--goal-flying", action="store_true",
                                     help="the hooks module's goal command has not answered yet, so the look "
                                          "answers no condition")
    a = ap.parse_args(argv)
    me = Me(session=a.session, p4=a.p4)
    if not me.home or not os.path.isdir(me.home):
        print("phi: no store found; pass --p4 <repository>/.claude/p4", file=sys.stderr)
        return 2
    configure(me.home)
    try:
        if a.cmd == "look" and not a.folder:       # a session's native goal rides its look's answer
            return goal_look(a, me)
        if a.cmd == "goal" and a.act == "ask":     # the session's own ask, which the tool `mcp__p4-phi__goal` runs
            if not me.id:
                print("phi: this is not a session, since the environment holds no session id; pass --session",
                      file=sys.stderr)
                return 2
            print(goal_ask(me.home, ensure_session(me.home, me.id, me.rec, "" if a.session else me.cli),
                           a.condition))
            return 0
        if a.cmd == "goal":                        # ahead of ensure_session: it makes no session's folder either
            if a.act in ("on", "off"):             # the project's setting, which needs no session
                print(goal_switch(me.home, a.act == "on"))
            elif a.act == "set":
                sys.stdout.write(json.dumps({"set": goal_set(me.home, safe_id(me.id))}) + "\n")
            elif a.act == "failed":
                sys.stdout.write(json.dumps({"failed": goal_failed(me.home, safe_id(me.id), a.condition)}) + "\n")
            else:
                print(goal_text(load_session(me.home, safe_id(me.id)) if me.id else {}))
            return 0
        if a.cmd == "worker_profile":              # the project's setting, which needs no session
            print(worker_profile_set(me.home, a.name))
            return 0
        if a.cmd == "worker_mode":                 # the project's setting, which needs no session
            print(worker_mode_set(me.home, a.mode))
            return 0
        if a.cmd == "worker_for":                  # a session's own override, this one's or the named one's
            try:
                print(worker_for(me.home, me.id, a.mode, a.profile))
            except ValueError as e:
                print(f"phi: {e}", file=sys.stderr)
                return 2
            return 0
        if a.cmd == "balance":                     # the starts and outcomes of the terminal workers, per mode
            print(worker_balance(me.home))
            return 0
        if a.cmd == "app_tools":                   # the project's setting, which needs no session and makes no folder
            print(app_tools_switch(me.home, a.act == "on" if a.act else None))
            return 0
        if a.cmd in puppeteer.COMMANDS:
            return puppeteer.command(a, me)
        if a.cmd == "progress":                    # the pane's data, which the hooks module asks for while it is open
            import progress
            sys.stdout.write(json.dumps(progress.write(me.home, safe_id(me.id)), ensure_ascii=False, sort_keys=True)
                             + "\n")
            return 0
        if a.cmd == "spend":                       # what a session and the agents under it spent, by their transcripts
            import progress
            rows = progress.spend(me.home, a.who or safe_id(me.id))
            if not rows:
                print(f"phi: no transcript is found for {a.who or me.id}, so its spend is not read", file=sys.stderr)
                return 2
            for r in rows:
                print(f"{r['who']}: {r['calls']} API calls, {r['input'] + r['cache_write'] + r['cache_read']} tokens "
                      f"in, of them {r['cache_read']} read from the cache, and {r['output']} tokens out, on "
                      f"{', '.join(r['models']) or 'no model named'}")
            return 0
        if a.cmd == "tree":
            print(tree_text(me.home) or "no sessions yet")
            return 0
        if a.cmd == "node":                        # one node whole: its address, level, paths and leaves
            sid = safe_id(a.moved or me.id)
            if not sid:
                print("phi: name the session, or run this from inside it", file=sys.stderr)
                return 2
            every = relay._sessions(me.home)
            if sid not in every:
                print(f"phi: no session {sid} in this store", file=sys.stderr)
                return 2
            print(json.dumps(nd.record(me.home, sid, every), ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "cards":                       # the project's setting, which needs no session
            store = a.p4 or me.store or me.home
            if not a.act:
                for line in cards.text(store):
                    print(line)
                return 0
            if a.act == "on" and spawned_from(load_session(me.home, safe_id(me.id)) if me.id else {}):
                print("phi: `cards on` is refused in a session another session started: the top session brings "
                      "the set to ezexe", file=sys.stderr)
                return 2
            status, lines = cards.switch(store, a.act == "on", a.set)
            for line in lines:
                print(line, file=sys.stderr if status else sys.stdout)
            return status
        if a.cmd == "conf":                        # a setting of p4.json, which needs no session
            import conf
            store = a.p4 or me.store or me.home
            if a.value is None and not a.unset:
                lines = conf.show(store, a.key)
                for line in lines:
                    print(line)
                if not lines:
                    print(f"phi: {a.key} is no setting of p4.json that p4 reads: `phi.py conf` lists them",
                          file=sys.stderr)
                return 0 if lines else 2
            if spawned_from(load_session(me.home, safe_id(me.id)) if me.id else {}):
                print("phi: a setting is written by the top session, where ezexe is: ask it with SendMessage",
                      file=sys.stderr)
                return 2
            status, lines = conf.unset(store, a.key) if a.unset else conf.put(store, a.key, a.value)
            for line in lines:
                print(line, file=sys.stderr if status else sys.stdout)
            return status
        if a.cmd == "upkeep" and a.act in ("on", "off"):   # the project's setting, which needs no session
            store = a.p4 or me.store or me.home
            for line in upkeep.set_on(store, a.act == "on"):
                print(line)
            return 0
        if a.cmd == "sections":                    # an approved plan's runs: what `coworkers --land` prints
            a.cmd, a.checkout, a.land, a.wait, a.report = "coworkers", "", True, None, ""
        if a.cmd == "coworkers":                   # a plan's groups, each as the coworker that reads and lands it
            import coworker
            if a.wait is not None and a.report:    # a terminal worker's one sign is its report file
                report = os.path.abspath(a.report).replace("\\", "/")
                tab = os.path.basename(report)[len("report-"):].rsplit(".", 1)[0]
                log = os.path.join(os.path.dirname(report), coworker.LOG.format(tab)).replace("\\", "/")
                how, waited = coworker.wait_report(report, me.home, tab, log=log)
                worker_outcome(me.home, tab, how, coworker.last_result(log))
                if how == "ended":
                    r = coworker.last_result(log)
                    print(f"ended: `{tab}` ended after {waited} seconds with no report {report}: "
                          f"{r.get('subtype') or ''}{' error' if r.get('is_error') else ''}: "
                          f"{str(r.get('result') or '')[:400]} (its log {log}; continue it with its resume file)")
                    return 0
                print(f"done: {report} is there, after {waited} seconds" if how == "done" else
                      f"long: {report} is not there after {waited} seconds: look at the terminal tab `{tab}`")
                return 0
            plan = os.path.abspath(a.plan) if a.plan else ""
            if a.wait is not None and not a.land:  # a round's wait on named coworkers, which only reads
                who = str((load_session(me.home, safe_id(me.id)) or {}).get("title") or me.id) if me.id else ""
                names = a.wait
                if not names:
                    print("phi: name each coworker to wait for", file=sys.stderr)
                    return 2
                checkout = os.path.abspath(a.checkout or os.getcwd()).replace("\\", "/")
                how, waited = coworker.watch(names, me.home, checkout)
                print({"quiet": f"phi: no coworker wrote a line for {coworker.QUIET} seconds, after {waited} seconds",
                       "silent": f"phi: no coworker wrote a line in {waited} seconds, so the round did not begin: "
                                 "ask each coworker once for its list",
                       "long": f"phi: a coworker still writes after {waited} seconds, so the watch ends"}[how])
                for name in names:
                    if coworker.stopped(name, me.home, checkout):
                        print(f"phi: an error of the API stopped `{name}`: send it one message to carry on with "
                              "its round from where it stopped")
                for name in names:                 # a message held between two modes loses nothing
                    said = coworker.last_list(name, who, me.home, checkout)
                    if said:
                        head, _, body = said.partition("\n")
                        print(f"phi: the last list `{name}` sent, at {head}:\n{body}")
                return 0
            if not plan or not os.path.isfile(plan):
                print(f"phi: no plan file at {plan}", file=sys.stderr)
                return 2
            checkout = os.path.abspath(a.checkout or os.getcwd()).replace("\\", "/")
            mode = upkeep.mode_of(safe_id(me.id)) if me.id else ""
            if a.land:                             # a terminal worker for each group not landed, in LAND_MODE
                # each terminal session is a node nested in the store that holds this session's folder
                node_of = {"home": me.home, "starter": safe_id(me.id),
                           "store": relay.nodes(me.home).get(safe_id(me.id)) or me.home}
                try:
                    found = coworker.land(plan, checkout, "", mode, claim=True,
                                          # landing is headless work by the rule, so a section's own words, which
                                          # may name modes, pick no mode: only a set mode does
                                          settings=lambda text: worker_settings(me.home, me.id, ""), **node_of)
                except ValueError as e:
                    print(f"phi: {e}", file=sys.stderr)
                    return 2
                if not found:
                    print("phi: no section of that plan is left to land: each names no files or holds its "
                          "`Evidence:`", file=sys.stderr)
                    return 2
                new = [one for one in found if one.get("folder")]
                coworker.write(new, checkout, me.home)
                for one in found:
                    if one.get("started"):
                        print(f"phi: a session named `{one['name']}` was started already, from its node "
                              f"{one['started']}, so nothing is written for it", file=sys.stderr)
                if not new:
                    return 2
                for one in new:
                    print(f"worker `{one['name']}`: sections {', '.join(one['sections'])}, its report "
                          f"{one['report']}")
                    print(f"  session {one['session']}"
                          + (f", its log {one['log']}" if one["settings"]["mode"] == "print" else ""))
                    print("  " + worker_start(me.home, one["settings"], one["name"], safe_id(me.id), "land",
                                              one.get("log") or "", one["report"]))
                    print("`mcp__terminal__run_in_terminal` with " + json.dumps(
                        {"title": one["name"], "cwd": checkout, "command": one["typed"]}, ensure_ascii=False))
                    print(f"  continue it, where it ends with no report, in a Terminal-panel tab with "
                          f"`{one['resume_typed']}`")
                return 0
            try:
                found = coworker.drafts(plan, checkout)
            except ValueError as e:
                print(f"phi: {e}", file=sys.stderr)
                return 2
            if not found:
                print("phi: no section of that plan names files on a `Files:` line, so it has no group to read",
                      file=sys.stderr)
                return 2
            for one in found:
                nums = ", ".join(one["sections"])
                if one["team"]:
                    print(f"sections {nums}, {one['fences']} fences: a team of three reads them")
                else:
                    print(f"sections {nums}, {one['fences']} fences and no check: one `p4-phi:check` reads them")
            return 0
        if a.cmd == "gaps":                        # the behaviour memories no landed feature carries yet
            import gaps
            print(gaps.unlanded_text(me.store or me.home))
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
            try:
                relay.set_shard(me.home, s["sessionId"], a.paths, os.getcwd())
            except ValueError as e:
                print(f"phi: {e}", file=sys.stderr)
                return 2
            relay.mark_paths(me.home, me.store or me.home)
            print("kept as this session's owned paths: "
                  + ", ".join(relay.shard_of(load_session(me.home, s["sessionId"]))))
            return 0
        if a.cmd == "upkeep":
            if a.act == "close":
                print(upkeep.close(me.home, s, a.what.strip(), a.commit.strip(), a.note, a.ezexe, os.getcwd()))
            elif a.act == "wait" and a.waits_at:
                if a.waits_on:
                    raise ValueError("a step waits on a session, with --on, or on a time, with --at, and not on both")
                print(upkeep.later(me.home, s, a.what, a.waits_at, a.local))
            elif a.act == "wait":
                print(upkeep.wait(me.home, s, a.what, a.waits_on))
            else:
                print(upkeep.status(me.home, s, me.store))
            return 0
        if a.cmd == "controls":
            if a.decline:
                print(controls.decline(me.home, s, a.decline[0], a.decline[1]))
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
            if not a.to_puppeteer:                 # a worker is drafted and started in the Terminal panel
                raise ValueError("`request` keeps only a request to this session's puppeteer, with "
                                 "`--to-puppeteer`; a worker is started with `draft` and its `draft --start` line")
            brief = a.brief
            if a.brief_file:
                with open(a.brief_file, encoding="utf-8") as f:
                    brief = f.read()
            save_session(me.home, s)
            pid, _ = controls.puppeteer_of(s, me.store)    # a new orchestrator is asked of the puppeteer
            if not pid:
                raise ValueError("this session has no puppeteer: no session started it")
            rid, new = starts.add(me.home, s["sessionId"], a.title, brief, "fresh", background=a.background, to=pid)
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
