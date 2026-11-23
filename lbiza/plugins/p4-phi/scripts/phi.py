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
  address book's changed entries with the path of book.md. It hands no rule: the rules built into p4-phi are a
  section of the system prompt, which the plugin's hooks module sets from `phi.py rules`, as rules_section says.
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
section of p4.json: `act_dont_wait`, `plan_mode`, `levels`, `top_orchestrates` and `child_levels`, read from the
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
import controls  # noqa: E402  a puppeteer filed in the sidebar section, and the sessions it controls

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
APP_TOOLS = True                 # phi.json `app_tools`: false keeps the hooks module from asking the app's own tools for sessions
# hooks.md, "JSON output": "A hook's `additionalContext`, `systemMessage`, and `initialUserMessage` strings, and its
# plain stdout, are capped at 10,000 characters", each string "measured separately", and over the limit "Claude Code
# saves the output to a file in the session directory. It replaces the output with the file path and a preview of up
# to the first 2,000 characters." p4-phi leaves that cap and its overflow file to the app: it keeps no ceiling of its
# own on what it adds beside a start or a prompt and no page for what would pass one. The same section says "Claude
# Code doesn't ask Claude to read the file, so keep anything Claude must always see within the cap", which is what
# the app's cut at a character count lacks. So acting_first puts the lines that ask the session to act first, inside
# the preview, the rest follows whole, and READ_ALL leads when those lines alone pass the preview.
APP_CAP = 10000
APP_PREVIEW = 2000
READ_ALL = ("phi (p4-phi): the lines below that ask this session to act run past the 2,000 characters the app shows "
            "of a hook's text over its cap of 10,000. Read the file the app names for this text before going on.")
RELAY_CHARS = 4000               # of what the sessions beside this one changed, beside one prompt: relay.rebase's room
PHI_LEAD = re.compile(r"^phi \(p4-phi\)[^:]*:\s*")
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
            "goal": "GOAL", "app_tools": "APP_TOOLS"}
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
#
# Both tools answer a session's sidebar `group`, and for a puppeteer the module asks the sidebar's own tools too,
# `mcp__ccd_sidebar__list_sections` and, where that answers nothing, `mcp__ccd_sidebar__list_groups`, kept as
# `sections`. controls.py reads a filing from app_group and section_id first, and from the app's
# `claude_desktop_config.json` for a session the answers do not hold.
APP_FILE = "app.json"            # in rows.origin_dir of the CLI session, else in the session's folder in the tree's store
APP_FRESH_S = 300.0              # how long the file is believed after the module wrote it
APP_SAME = ("sessionId", "title", "cwd", "originCwd", "isArchived", "permissionMode", "branch")
APP_AT = {"cli": "", "project": "", "folder": ""}   # whose file is read: Me sets it, and the environment says it before
ANSWERS = {}                     # APP_FILE's path -> (its sessions by id, the id of `self`, its sections), read once a process


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
    holds by its id, as the tool gave it, the id of the session the file is of, and the sidebar's sections where
    the module asked for them. ({}, '', []) where no such file is."""
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
            listed = [r for r in (d.get("sections") if isinstance(d.get("sections"), list) else [])
                      if isinstance(r, dict)]
            ANSWERS[path] = (held, str(mine.get("sessionId") or "") if mine.get("sessionId") in held else "", listed)
        if ANSWERS[path][0] or ANSWERS[path][2]:
            return ANSWERS[path]
    return {}, "", []


def app_answer(sid):
    """A session as the app's tools answered it, an AppRow, or None where the module left no fresh answer of it."""
    row = app_answers()[0].get(str(sid or ""))
    return AppRow(sid, from_tools(row)) if row else None


def app_group(sid):
    """The sidebar section a session is filed in, as the app's tools answered the hooks module: its `id` and `name`,
    both '' for a session filed in none. None where they did not say: no fresh answer of the session, or one with no
    `group`, which the tools leave out "while the app window has not reported groups yet"."""
    row = app_answers()[0].get(str(sid or ""))
    if not row or "group" not in row:
        return None
    g = row["group"] if isinstance(row["group"], dict) else {}
    return {"id": str(g.get("id") or ""), "name": str(g.get("name") or "")}


def section_id(name, sid=""):
    """The id `mcp__ccd_sidebar__move_sessions` takes for the section named `name`, or '': that of the group the
    session `sid` is filed in where the tools answered it under that name, else that of the section of that name
    in what `list_sections` or `list_groups` answered, where a built-in section has no name and a custom one is of
    the kind `manual`."""
    want = str(name or "").strip().lower()
    held = app_group(sid) if sid else None
    if want and held and held["name"].strip().lower() == want:
        return held["id"]
    for row in app_answers()[2] if want else []:
        if str(row.get("name") or "").strip().lower() == want and row.get("kind", "manual") == "manual":
            return str(row.get("id") or "")
    return ""


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


def same_store(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


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
    for k in ("rootStep", "rootLeft", "shard", "disposable", "doneRetired", "archived", "appRoot", "nudged", "issue",
              "issueLooked", "findingsTold", "controls", "puppeteerSeen", "handedTo",
              "handedFrom", "effort", "kidCommits", "planMode", "planFile"):
        if k in disk and k not in s:
            s[k] = disk[k]
    if not s.pop("_controlsSet", None) and isinstance(disk.get("controls"), list):
        s["controls"] = disk["controls"]          # only `controls` and a puppeteer's own start change it
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
        by, by_title, kind = controls.publisher(home, s, store)
        does = ("it publishes the issues they need and places" if by == pid else
                f"{controls.PUBLISHER[kind].replace('its puppeteer', 'that puppeteer')}, \"{by_title}\" `{by}`, "
                f"publishes the issues they need, while the puppeteer places")
        rest = (f"{head}. They go up to the puppeteer \"{controls.full_title(pid)}\" `{pid}`, whose board "
                f"lists them, and {does} the session that resolves each: this "
                f"session publishes none.")
    else:
        rest = (f"{head}, and no puppeteer controls this session tree, so the findings in them are this "
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
# The act-don't-wait rule. How a question to ezexe is laid out is the app's own text, so the rule names the tools and
# holds no sentence on it:
# - tools-reference.md, "AskUserQuestion tool behavior": "Claude uses `AskUserQuestion` to ask you multiple-choice
#   questions when it needs a decision or a clarification."
# - the desktop app's turn-end tool, `mcp__ccd_turn__wrap_up`, whose own text puts a decision that waits on ezexe as
#   one question with buttons, the pick first.
# - headless.md, "Turn off permission prompts in unattended runs": "Claude Code removes the tools that need an answer
#   from a person, such as `AskUserQuestion`, so Claude can't call them." A `claude -p` run and an eval run have
#   neither tool, and what leaves such a run is its reply, "the text result in the `result` field" of the same page,
#   so the rule names the reply for a session that has neither.
# Every other sentence stays. Some are what that text lacks: the decisions file, the session tree as what settles a
# next step, the push of green issue-closing commits, a child's question to its parent session, and the go a
# project's rules ask for. The rule asks a worker for no line to its starter at a turn's end: the plugin's hooks
# module sends the starter the turn's report with `$.session.send`, which by plugins/mods/api.md "makes the same
# delivery the SendMessage tool makes", ezexe/p4#157. The rest only the desktop app's text states, and no docs page
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
            "`AskUserQuestion`, or in the reply of a session that has neither tool: permissions or security "
            "settings, credentials, spending, and actions that cannot be "
            "undone or publish outward, but for the push of green issue-closing commits, which p4-phi orders at "
            "once. A step only a turn of ezexe's can make is that one question with its button, never a sentence "
            "about ezexe's next message. ezexe is asked to type no command this session can run, and a setting "
            "ezexe settled is written into its file in that turn and read back, by `phi.py conf` for a key of "
            "p4.json. A started session's turn note goes on to ezexe only where ezexe must act on it or it changes "
            "what ezexe knows, and a message goes to a session only for what that session needs. A child asks its "
            "parent session with SendMessage, and never ends its turn waiting on a question the session tree can "
            "settle. "
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
# - sub-agents.md, "Built-in subagents", Explore: its model is "the parent conversation's model", so it ran small only
#   while each call named `haiku`. "The `model` field in the subagent's definition" is second in the page's model
#   order, so agents/finder.md, the skill sub-agentic's evidence finder, carries `model: haiku` and `effort: low`,
#   and agents/writer.md and agents/integrator.md carry that table's writer and integrator: the right model runs
#   with nothing a call or a project has to name.
# - code-review-local.md: "`/code-review` is a bundled skill", "Claude can start `/code-review` on its own, without
#   you typing the command", "In a terminal session, the review runs as a background subagent with its own context
#   window", and "without `--fix`, the review's instructions ask Claude for a report only." The page calls that run
#   "a forked subagent", of which skills.md, "Run skills in a subagent", says "The subagent doesn't see your
#   conversation history". So a code change is reviewed by that skill. Its target "can be a pull request number, a
#   branch name, a file path, or a Git revision range", so a result that is no code change has none, and the page's
#   route past the skill is "Build your own reviewer: write a reviewer subagent or a review skill": that is
#   agents/check.md.
# - plugins/components.md, "Agents": "The name form is `<plugin>:<name>`", so agents/check.md is `p4-phi:check`.
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
# the agent runs on your session's model." No line of that page gives a workflow agent an effort of its own, but the
# workflow-authoring reference Claude Code 2.1.330 ships gives `agent(prompt, opts)` the options `model?` and
# `effort?`, where "opts.effort overrides the reasoning effort", so the skill sub-agentic's `agent(prompt, {model,
# effort})` is a call the runtime takes.
WORKFLOW = ("A Workflow script names a `model` and an `effort` for each stage, `agent(prompt, {model, effort})`, by "
            "the role the skill `p4-phi:sub-agentic` gives it, since by the workflows page of the Claude Code docs \"A "
            "model the script names for a stage counts as the per-invocation model\" and an agent with none \"runs "
            "on your session's model\".")
# The round a subagent's writing goes through before it counts, which the skill sub-agentic holds as its rule 11:
# - best-practices.md, in the table of habits to drop: "A fresh reviewer does help, because it hasn't seen your
#   reasoning, which is a different thing from delegating." And "Give Claude a check to run": "A reviewer that's
#   asked to find problems will always find something. If you fix every finding, you end up with extra abstraction
#   layers and tests for cases that can't happen." So a finding may be answered, and the rounds are capped.
# - building-effective-agents, the evaluator-optimizer: "one LLM call generates a response while another provides
#   evaluation and feedback in a loop", with "stopping conditions" such as "a maximum number of iterations".
# - The Agent tool's own text: "Use SendMessage with the agent's ID or name to continue a previously spawned agent
#   with its context intact". So the findings go back to the agent that wrote, which knows why it wrote so.
# - A subagent cannot loop by itself: sub-agents.md, "Available tools", takes `ScheduleWakeup` from every subagent.
# Seen on 2026-11-22 in a scripted run of Claude Code 2.1.328: a session sent each of two reviewing subagents a
# message by its id, the tool answered "Resuming agent", and each read the commit against its own findings.
# A session's goal has the same round for its own change, in plans.REVIEW_PART.
ROUND = ("What a subagent wrote is read before it counts as done, by `p4-phi:check` or, for a code change, by the "
         "skill `code-review` without `--fix`, and what the read finds goes back to the same agent with "
         "`SendMessage`, which continues it with what it knows. A finding is mended or answered with the reason it "
         "is no fault, one second read follows a mend, and there is no third.")
LEVELS = ("built-in, levels: work is delegated to where Claude Code runs it best, so this session's own turn is "
          "never held by it. Before an Agent call, a fork, a Workflow call or a session start, the skill "
          "`p4-phi:sub-agentic` decides whether to delegate at all, how many agents, and each one's type, `model` "
          "and `effort` by its role, and the reply's first line says that shape ahead of the call. "
          "A search or a read across more than a couple of files goes to " + plans.EXPLORE + "; "
          "a command expected to run long, such as a test file, a test suite or a build, goes to " + plans.BACKGROUND
          + "; a review of a code change that should not lean on this session's own view goes to " + REVIEW + "; "
          "such a read of a result that is no code change goes to the subagent `p4-phi:check`, on `sonnet` at "
          "`medium` effort as its file says; one question whose step asks in its own words for several sides at "
          "once, where the readers must challenge each other, goes to " + plans.TEAM + ", and every other review "
          "or read stays with `code-review` or `p4-phi:check` as said; a subagent that writes new content or "
          "changes behaviour is "
          "`p4-phi:writer`, on `opus` at `medium`, and one that lands written work or verified findings is "
          "`p4-phi:integrator`, on `sonnet` at `medium`. " + ROUND + " "
          "A worker is started with the `model` and the `effort` of its step's "
          "role, as the advice that hands out each start call names them; an effort above this session's own is "
          "not accepted. " + WORKFLOW + " After a run, the report says the agents launched and finished and what "
          "they spent.")
# The plan rule. A plan is Claude Code's own to write and ezexe's to approve, and p4-phi builds no plan of its own:
# - tools-reference.md: `EnterPlanMode` "Switches to plan mode to design an approach before coding", with no
#   permission required, and `ExitPlanMode` "Presents a plan for approval and exits plan mode", with one required.
# - commands.md: "`/plan` switches into plan mode before a large change", and `/plan [description]` is "Enter plan
#   mode directly from the prompt."
# - common-workflows.md, "Plan before editing": "For changes you want to review before they touch disk, switch to
#   plan mode. Claude reads files and proposes a plan but makes no edits until you approve."
# - permission-modes.md, "Analyze before you edit with plan mode": "Approving a plan exits plan mode and switches the
#   session to the permission mode each approve option describes".
# - The tool's own text names when: a task that "can be solved in several different ways", one that "requires
#   choosing between patterns or technologies", one that "will likely touch more than 2-3 files", and "If you would
#   use AskUserQuestion to clarify the approach, use EnterPlanMode instead". PLAN_OPEN says those three in the
#   rule's words. The same text skips it for "Tasks where the user has given very specific, detailed instructions".
# - The plan file is plan mode's: `ExitPlanMode` "will read the plan from the file you wrote", and p4's settings
#   keeper points `plansDirectory` at the store's folder p4conf.PLANS, which the rule names from there and never
#   spells by itself. How a plan is shaped and where it moves once it is done is p4-temportal's skill `plan-planner`.
# What that text lacks is the session another session started. It says "Use this tool proactively", and there no
# person answers the approval: docs/plugin-development.html, "Plan mode for a worker", has the card seen in the
# desktop app, answered by ezexe alone. So such a session is told to enter no plan mode. sub-agents.md, "Built-in
# subagents", Plan: "A research agent used during plan mode to gather context before presenting a plan", with
# read-only tools, so it raises no card, and the session's starter approves by a message, which the sentences of
# GOAL_STARTER already count toward a condition. An allow at `classic.PermissionRequest` settles `ExitPlanMode` with
# no person, seen in the desktop app on Claude Code 2.1.326, and p4-phi builds nothing on it: that would be a part
# of the set of what it settles with no approval card, which is ezexe's to say yes to.
# The rule has a switch of its own, `phi.plan_mode`, as each built-in rule has: a project whose sessions enter plan
# mode only when asked, as an output style can say, leaves this rule out and keeps the act-don't-wait rule.
PLANS_DIR = p4conf.PLANS            # from the store's root, as the keeper has it: no line names a place under the app's own folder
PLAN_OPEN = ("a change that could be made in more than one way, that decides a structure, or that reaches past two "
             "or three files")
PLAN_AT = ("built-in, plan-mode: a change whose approach is open is planned before it is edited, and the plan is "
           "Claude Code's own to write and ezexe's to approve. Where a message asks for " + PLAN_OPEN + ", and this "
           "session has the tool `EnterPlanMode`, call it before any edit: it is the mode ezexe enters with `/plan`. "
           "The plan goes into the file plan mode names, whose folder p4's settings keeper points at `"
           + PLANS_DIR + "` in the project's store, shaped as the skill `plan-planner` of the plugin p4-temportal "
           "says where that plugin is installed. The plan is written whole and then read as that skill says: "
           "no session started this one, so none starts a team's lead for it, and one `p4-phi:check` that has "
           "not seen the writing reads the plan, what it finds is mended or answered, and one more "
           "`p4-phi:check` reads the mends, with no read after that. Until ezexe approves the whole plan, no "
           "session that writes is started and no file but the plan is edited. Put the finished plan to ezexe "
           "with `ExitPlanMode`, whose approval "
           "card ezexe answers by a button: that approval is ezexe's go for the plan's edits, and no other question "
           "asks for it. Once it is approved, its sections go to workers by the start calls `phi.py sections "
           "<the plan file>` prints, one for each run of sections. A change the message spells "
           "out, or one a sentence "
           "describes, is made with no plan, and no plan is written into a file elsewhere.")
PLAN_STARTED = ("built-in, plan-mode: a change whose approach is open is planned before it is edited. Another "
                "session started this one, and no person answers a plan's approval here, so this session calls "
                "neither `EnterPlanMode` nor `ExitPlanMode`, unless a message of ezexe's own in this conversation "
                "asks for plan mode or this session was started in plan mode, as a planner is: it then writes its "
                "plan file there whole, asks the session that started it in one SendMessage for the coworkers of "
                "its plan, each the lead of an agent team for one group of its sections, as the skill "
                "`plan-planner` of the plugin p4-temportal words that ask, has each group read in rounds, mending "
                "what held after each, until a round of the group has nothing to mend or its held findings are "
                "more than the round before, and ends its turn with "
                "`ExitPlanMode`, whose approval card ezexe answers in this "
                "session. Once that returns approved, it has a terminal worker land its sections, which "
                "`phi.py coworkers \"<its plan file>\" --land` writes the start file, the brief and the report's name "
                "of into the worker's node, and prints the terminal call that starts, from a session in auto or "
                "bypass mode: it makes that call, and reads the report file the worker writes, which `phi.py "
                "coworkers \"<its plan file>\" --wait --report <that file>` waits for, in place of an answer by "
                "message. Where that command says it starts none, it runs `phi.py sections \"<its plan "
                "file>\"` and starts one `p4-phi:integrator` subagent for each run, "
                "never a session, in a git worktree it makes from `origin/main`, and sends the session that "
                "started it one message naming each branch, its commits "
                "and its check results, which ends its work: it awaits no reply, sets no wait for one and stops "
                "each background task it started. It pushes nothing, merges nothing and raises no version, unless its "
                "brief says it builds nothing. Where its task asks for " + PLAN_OPEN + ", and its brief does not "
                "settle how, it has the built-in `Plan` subagent design the change, which only reads and raises no approval "
                "card, sends that plan to the session that started it in one SendMessage, and takes that session's "
                "message as the approval. A change the brief spells out, or one a sentence describes, is made with "
                "no plan.")
plans.BUILT_INS = tuple(x.split(": ", 1)[0].replace("built-in, ", "") for x in (BUILT_IN, PLAN_AT, LEVELS))   # plans.py's names
LEVELS_ON = True              # p4.json phi.levels: false leaves the delegation rule and its checks out
PLAN_MODE = True              # p4.json phi.plan_mode: false leaves the plan rule out of a project
GOAL_REVIEW = True            # p4.json phi.goal_review: false leaves the review of the change out of a worker's goal
TOP_ORCHESTRATES = True       # p4.json phi.top_orchestrates: false keeps an orchestrator's work in it
UPKEEP = False                # p4.json phi.upkeep: true has a session that started others keep them by itself


def project_conf(store):
    """The project's own keys of p4.json's `phi` section, read from the store where the session runs, not from a
    shared store, each with its P4_* variable ahead of it, by p4conf.load."""
    global ACT_DONT_WAIT, TOP_ORCHESTRATES, LEVELS_ON, PLAN_MODE, GOAL_REVIEW, UPKEEP
    try:
        d = p4conf.section(store, "phi", write=False) if store else {}
    except Exception:  # noqa: BLE001
        d = {}
    if not isinstance(d, dict):                    # a `phi` that is no section sets every key back to its default
        d = {}
    ACT_DONT_WAIT = d.get("act_dont_wait") is not False
    TOP_ORCHESTRATES = d.get("top_orchestrates") is not False
    LEVELS_ON = d.get("levels") is not False
    PLAN_MODE = d.get("plan_mode") is not False
    GOAL_REVIEW = d.get("goal_review") is not False
    UPKEEP = d.get("upkeep") is True
    relay.UPKEEP = controls.UPKEEP = UPKEEP     # the words that leave an archive to ezexe go with it on
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


NEW_TOP = starts.NEW_TOP       # a new orchestrator's brief line, which starts.use_worktree reads too
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
    lacks, the files the brief covers on its `Files:` line and the two moves that detach the session to top level. In a
    turn ezexe did not begin it names no `initiation`: what such a turn may start, and the card it proposes, are that
    tool's own text. It passes `use_worktree: false`, as starts.use_worktree gives every start."""
    if ASK_ROUTE:
        return ASK_ROUTE
    how = ("Start it with `mcp__ccd_session__start_session`, `initiation` `user_asked`" if owner_turn else
           "Give it to `mcp__ccd_session__start_session`")
    return (f"{how}, `context` `fresh`, {plans.TOP_TREE}, with the `model` and `effort` its kind of work gets, "
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
               "`mcp__ccd_session__start_session`, `initiation` `user_asked`, `context` `fresh`, " + plans.OWN_TREE
               + " for every part, with a `Files:` line in the brief of a part that writes; where the app refuses that start, the part is shown as a "
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
    implementation guide before it creates anything, said once. '' for an orchestrator, a later message, the prompt
    of an event such as a background report, and a session that writes nothing."""
    if not spawned_from(s) or not clean(s.get("task")) or load_turns(home, s["sessionId"]):
        return ""
    if s.get("researchSaid") or s.get("turnBy") == "event":
        return ""
    files = s.get("fileSet")
    if not (files if isinstance(files, list) else issues.writing(s.get("task"))):
        return ""
    s["researchSaid"] = True
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
    sessions, said once. '' for an orchestrator, a later message, the prompt of an event such as a background
    report, a session in plan mode, which starts nothing that writes, a session with no task, and one a cap
    holds."""
    if not LEVELS_ON or not spawned_from(s) or not clean(s.get("task")) or load_turns(home, s["sessionId"]):
        return ""
    if s.get("firstSplitSaid") or s.get("turnBy") == "event" or s.get("planMode") is True:
        return ""
    if caps_text(home, s):
        return ""
    s["firstSplitSaid"] = True
    RAN["first_split"] = True
    return FIRST_SPLIT


def from_peer(prompt, by=""):
    """True for another session's message: by its origin, rows.whose, and where the origin does not say, by the
    wrapper Claude Code puts around one."""
    return by == "session" or (not by and bool(re.search(r"<cross-session-message\b", str(prompt or ""))))


def split_text(home, s, prompt, by=""):
    """A turn another session's message started. What such a turn may start, and the card it proposes, are the start
    tool's own text, so this line holds only what that text lacks: the caps, the files a brief names, and
    for an orchestrator the brief line that detaches a new orchestrator to top level. It is short and keeps no
    state, so every such turn carries it whole. '' for ezexe's own turns, the app's events and a session with no
    task."""
    if not clean(s.get("task")) or not from_peer(prompt, by):
        return ""
    cap = caps_text(home, s)
    RAN["split"] = "cap" if cap else "brief"
    return "phi (p4-phi): " + cap if cap else _split_full(home, s)


def _split_full(home, s):
    """What a brief written in a turn another session began holds beyond what the start tool asks of it: a
    child's, its `Files:` line and its level line; a new orchestrator's, those and the line on which it is detached
    to top level, or for a controlled orchestrator the request to its puppeteer. Every start passes
    `use_worktree: false`, as starts.use_worktree gives."""
    if spawned_from(s):
        return ("phi (p4-phi): a task of its own in this turn, outside this session's task, goes out by "
                "`mcp__ccd_session__start_session` with a brief that names the files it covers on a line "
                f"`Files: <paths>`. {plans.LEVEL_CARD}")
    head = "phi (p4-phi): a topic in this turn outside this orchestrator's task gets a new orchestrator of its own. "
    if ASK_ROUTE:
        ask = PHI_LEAD.sub("", controls.ask_text(s))
        return head + ask[:1].upper() + ask[1:]
    return (head + "It goes out by `mcp__ccd_session__start_session`, `context` `fresh`, `use_worktree: false`, "
            "with the `model` and `effort` its kind of work gets, said in one line of its brief, which names "
            f"the files it covers on a line `Files: <paths>` and carries the line \"{NEW_TOP_BRIEF}\": on that line "
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


def builtin_text(started=False):
    """The rules p4-phi carries itself, so they hold in every project, with memories or none, a store or none; ''
    where the project's p4.json turns each off. `started` says the session was started by another session, which
    the plan rule reads."""
    own = built_in(started)
    if not own:
        return ""
    head = "a rule built into p4-phi" if len(own) == 1 else "the rules built into p4-phi"
    return f"phi (p4-phi): {head}, for every session:\n" + "\n".join("- " + x for x in own)


def built_in(started=False):
    """The built-in rules that are on, each as its line. The plan rule is in the words for a session ezexe is at or,
    with `started`, in the words for a session another session started."""
    return (([BUILT_IN] if ACT_DONT_WAIT else []) + ([PLAN_STARTED if started else PLAN_AT] if PLAN_MODE else [])
            + ([LEVELS] if LEVELS_ON else []))


def rules_section():
    """The text of the section the plugin's hooks module adds to the system prompt at `prompt.compose`: the rules
    built into p4-phi, whole, for the session this process runs for. plugins/mods/reference.md, "Prompts and what
    Claude reads": `prompt.compose` fires when "Claude Code renders a system prompt" and a hook answers "`{ sections
    }`, a list of `{ id, text, scope }` in the order they're sent". The system prompt goes with every request and is
    sent anew after a compaction, so no hook hands the rules at a start, a clear or a compaction.
    '' where a setting turns the rules off: P4_PHI=0, P4_PHI_RULES=0, `rules: false` in the store's phi.json, or
    `phi.act_dont_wait`, `phi.plan_mode` and `phi.levels` all false in the project's p4.json, which Me reads from the session's own
    store. A project with no store has no phi.json and gets the rules, as every session does.
    The store's feedback and user memories are no part of it: memory.md, "Auto memory", says the app loads the first
    200 lines of MEMORY.md at the start of every conversation, and CLAUDE.md is read again after a compaction, so
    live_rules hands a line only for a memory that changes after the start."""
    if os.environ.get("P4_PHI") == "0":
        return ""
    me = Me()
    if me.home and os.path.isdir(me.home):
        configure(me.home)                         # phi.json's `rules`, and P4_PHI_RULES ahead of it
    elif os.environ.get("P4_PHI_RULES") in ("0", "1"):
        globals()["RULES"] = os.environ["P4_PHI_RULES"] == "1"
    if not RULES:
        return ""
    above = spawned_from(me.rec)                   # the app's record says so with a store or none
    if not above and me.home and me.id:
        above = spawned_from(load_session(me.home, me.id))
    return builtin_text(started=bool(above))


PLAN_TOOL = "EnterPlanMode"


def withheld_tools(text):
    """The tools the model of a session is not offered, for the rules' text the session is handed: `EnterPlanMode`
    where the text holds the plan rule in the words for a session another session started. That rule keeps such a
    session out of plan mode in a sentence, and where Claude Code has the event `tool.offer`, from 2.1.328 on, the
    hooks module answers it for this tool, so the model is not shown what it is told not to call. `ExitPlanMode`
    stays offered, so the session still plans where ezexe enters plan mode there with `/plan`."""
    return [PLAN_TOOL] if PLAN_STARTED in str(text or "") else []


def rules_main():
    """`phi.py rules`: one JSON line for the hooks module, `{"rules": <the section's text>, "withholds": <the tools
    the session's model is not offered>}`. A failure prints nothing, so the module adds no section and withholds
    nothing, and leaves its line in the session's log."""
    try:
        text = rules_section()
        sys.stdout.write(json.dumps({"rules": text, "withholds": withheld_tools(text)}) + "\n")
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
    asks(s)
    text = plans.record(me.home, s, inp)
    if isinstance(inp.get("items"), list):        # the task list's first whole list, or a revision of it
        s = load_session(me.home, me.id) or s
        cap = caps_text(me.home, s)
        advise = plans.split_advice if spawned_from(s) else plans.top_advice if TOP_ORCHESTRATES else None
        if advise is plans.top_advice and controls.is_puppeteer(s, me.store):
            advise = None                          # a puppeteer's steps are its own; it hands none out
            RAN["pair"] = "puppeteer"
        planning = mode_now(me, s, payload) == "plan"
        if advise and planning:
            advise = None                          # a plan is being written: nothing is handed out before its approval
            RAN["pair"] = "planning"
        advice = advise(me.home, s, plans.load(me.home, me.id), s.get("turnBy", "user") == "user", cap)             if advise else ""                      # none where the orchestrator does its own steps
        RAN["split"] = "advised" if advice else ""
        feat = "" if planning else feature_steps_text(me.home, s, plans.load(me.home, me.id),
                                                      s.get("turnBy", "user") == "user")
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


def approved_runs_text(payload, s):
    """At a plan's approval: the command that prints one start call for each run of the approved plan, with how many
    sections and runs it holds. hooks.md, "ExitPlanMode": "In `PostToolUse`, `tool_response` is an object with `plan`
    and `filePath` fields holding the approved plan". '' where the response names no file that is there, and for a
    plan with no section that names files on a `Files:` line. A session ezexe is at makes the calls in its own turn.
    A session another session started lands the runs itself by integrator subagents, each in a worktree it makes,
    since the app refuses a start that runs at once in a turn ezexe's own message did not begin, and it reports the
    branches to its starter, which reviews, tests, merges and pushes them; only a brief that says it builds nothing
    has it hand the command back."""
    resp = payload.get("tool_response") if isinstance(payload.get("tool_response"), dict) else {}
    path = str(resp.get("filePath") or "")
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            _, found = sections.parse(f.read(), str(payload.get("cwd") or s.get("cwd") or ""))
    except (OSError, ValueError):
        return ""
    if not found:
        return ""
    shown = path.replace("\\", "/")
    n, k = len(found), len(sections.runs(found))
    head = (f"phi (p4-phi): the approved plan `{shown}` holds {n} section{'s' * (n != 1)} that change files, in "
            f"{k} run{'s' * (k != 1)}. `{commands()} sections \"{shown}\"` prints one start call for each run, each "
            "an integrator's in a git worktree of its own.")
    RAN["runs"] = k
    if spawned_from(s):
        return (head + " Another session started this one, so this session lands the plan itself, in this turn. "
                       f"Where this session is in auto or bypass permissions mode, `{commands()} coworkers \"{shown}\" "
                       "--land` writes the start file, the brief and the report's name of one "
                       "terminal worker for each group not landed and prints the terminal call that starts it: make "
                       "that call, and take the report file the worker writes, which the same command with `--wait "
                       "--report <that file>` waits for, as that group's report, with no message. Where the command "
                       "says it starts none, and for every run no such worker lands, run the `sections` command above, "
                       "and for each such run it prints, first make that run's git worktree, standing "
                       "outside it, from `origin/main` freshly fetched, by `git -C <main checkout> fetch origin` and "
                       "then `git -C <main checkout> worktree add -b <run> <main checkout>/.claude/worktrees/<run> "
                       "origin/main`, and then start one `p4-phi:integrator` subagent on `sonnet` at `medium` effort "
                       "in that worktree, in parallel where runs share no file. These are subagents and never "
                       "sessions, since the app refuses a start that runs at once in a turn ezexe's own message did "
                       "not begin, and a subagent waits on no card. Each brief is the call's `prompt`, which names "
                       "the plan by its full path and its sections by number, carries their `Files:` line and "
                       "`Checks:` command as what done looks like and has the agent stop and report where a fence "
                       "does not fit, with two lines added: the worktree's path, and one commit per section there. "
                       "Mend such a fence from the plan and send the mend to the same agent with SendMessage. "
                       "Neither this session nor any run pushes, merges or raises a version. Once every run has "
                       "reported with its checks passing, send the session that started this one one message that "
                       "names each branch, its commits and its check results: that message is this session's done. "
                       "Await no reply to it, set no wait for one, and stop each background task, watch and "
                       "subscription this session started before that turn ends. "
                       "That session reads each branch's change, raises the version, runs the plugin's whole test "
                       "folder, pushes by fast-forward and closes the plan. Only where this session's brief says it "
                       "builds nothing does it hand that command back in its report for that session to run.")
    return head + " Run it now and make the calls it prints, in this turn."


def h_plan_mode(payload):
    """PostToolUse on EnterPlanMode and ExitPlanMode: whether this session plans, kept for mode_now, since no hook
    event tells of a change of the permission mode and the two tools change it inside a turn. hooks.md has
    PostToolUse run "immediately after a tool completes successfully", so `ExitPlanMode`'s is the approval, and at
    it every session is handed the command that prints the approved plan's runs, approved_runs_text, and an
    orchestrator what plan mode held back: the advice on its open work steps and the feature line, as h_plan
    builds them."""
    me = Me(payload)
    if not me.home or not me.id or payload.get("agent_id") or payload.get("hook_event_name") != "PostToolUse":
        return None                                # a subagent's call, or one that failed, such as a plan sent
                                                   # back, changed no mode here
    s = ensure_session(me.home, me.id, me.rec, me.cli)
    s["planMode"] = str(payload.get("tool_name") or "") == "EnterPlanMode"
    save_session(me.home, s)
    RAN["pair"] = "planning" if s["planMode"] else "approved"
    runs = "" if s["planMode"] else approved_runs_text(payload, s)
    if s["planMode"] or spawned_from(s) or not TOP_ORCHESTRATES or controls.is_puppeteer(s, me.store):
        return runs or None
    plan = plans.load(me.home, me.id)
    if not plan.get("steps"):
        return runs or None
    owner = s.get("turnBy", "user") == "user"
    advice = plans.top_advice(me.home, s, plan, owner, caps_text(me.home, s))
    feat = feature_steps_text(me.home, s, plan, owner)
    nudge_arm(me, load_session(me.home, me.id) or s)
    return "\n\n".join(p for p in (runs, feat, advice) if p) or None


# --- the nudge: an orchestrator doing a work step itself ------------------------------------------------------
#
# The marker <store>/phi/.nudge/<CLI session id> exists while an orchestrator's step in progress is a work step it
# has not been nudged on. The plugin's hooks module runs the check of a session's own edit only while this marker or
# a puppeteer's names the session, and that of its plain shell call only then or where the store's failure model
# weighs shell calls, so every other such call starts no python.

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
    if not st or st.get("status") == "completed" or plans.handed(st) or plans.top_stays(text):
        return None                                # the advice's own answer
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
    step it is told once that the rest is a read for the subagent `p4-phi:finder`. None while they are few."""
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
    if mode_now(me, s, payload) == "plan":         # a plan is being written: the step is nudged once it is approved
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
    if level != "session":                         # a read, a run and a team's question each need no worker
        return (f"phi (p4-phi): this is the orchestrator, kept free for orchestration, and step "
                f"{st.get('addr')}, \"{cut(clean(st.get('content')), 120)}\", {plans.LEVEL_WHAT[level]}: hand it to "
                f"{plans.LEVEL_WHERE[level]}. "
                f"Said once for this step.")
    return (f"phi (p4-phi): this is the orchestrator, kept free for orchestration, and step {st.get('addr')}, "
            f"\"{cut(clean(st.get('content')), 120)}\", is work: hand it to a worker with "
            f"`mcp__ccd_session__start_session`, `context` `fresh`, {plans.OWN_TREE}, "
            f"{plans.level_words(st.get('content'))}, its brief that step, a "
            f"line `Files: <the paths it may write>`, the line `{plans.level_line(plans.child_level(st.get('content')))}` "
            f"and \"report when done\", and keep this session for planning, messaging and landing. Said once for this "
            f"step.")


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
        # a project with no .claude/p4 yet has nothing to hand: the rules p4-phi carries itself are in its system
        # prompt, as rules_section says
        RAN["start"] = "no store"
        return share_notice(payload) or None       # read from the main checkout's store, which needs none here
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
    share = share_notice(payload)
    if share:
        notices.append(share)
    first = ""
    if source == "compact" and controls.is_puppeteer(s, me.store):
        first = controls.compacted(me.home, s)     # a puppeteer's board path before anything else
        RAN["pair"] = "compacted"
    elif source in ("compact", "clear"):
        first = controls.state_first(me.home, s)   # a standing worker's or coworker's state page first
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
    is the app's to write. When the text passes the cap and the parts in `keep` alone pass the preview, READ_ALL
    leads them, since the app does not ask Claude to read its file."""
    parts = [p for p in parts if p]
    kept = {id(p) for p in keep if p}
    first = [p for p in parts if id(p) in kept]
    text = "\n\n".join(first + [p for p in parts if id(p) not in kept])
    if len(text) > APP_CAP and sum(len(p) + 2 for p in first) + len(READ_ALL) > APP_PREVIEW:
        RAN["read_all"] = True
        return READ_ALL + "\n\n" + text
    return text


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
    s.pop("waitEnded", None)                       # the wait the turn before ended on: this turn's end says anew
    if payload.get("permission_mode"):             # hooks.md: the mode the session is in, kept for mode_now
        s["permissionMode"] = str(payload["permission_mode"])
        s["planMode"] = s["permissionMode"] == "plan"   # a prompt's own mode, over what a plan mode tool said before
    if not plans.woken(payload.get("prompt")):
        s.pop("woke", None)                        # a turn no wake started: the hooks module's count starts over
    plans.clear_in_flight(s, payload.get("prompt"))   # a completion notice ends its entry
    if upkeep.notice_came(s, payload.get("prompt")):  # an idle notice spends the subscription it answers
        RAN["notice"] = True
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
    stand = (controls.worker_first(me.home, s, payload.get("prompt"), me.store)
             if spawned_from(s) and not load_turns(me.home, s["sessionId"]) else "")
    first_split = first_split_text(me.home, s)
    if first_split:
        parts.insert(0, notice(first_split))
    if stand:                                      # a puppeteer's standing worker or coworker: what it is
        RAN["standing"] = s.get("standingKind")
        parts.insert(0, notice(stand))
    usage = controls.usage_line(me.home, s, payload.get("prompt"), me.store, by)
    if usage:                                      # a puppeteer watches its worker's and coworkers' context
        RAN["usage"] = True
        parts.insert(0, notice(usage))
    research = research_text(me.home, s)
    if research:
        parts.insert(0, notice(research))
    if detached_now:
        parts.insert(0, notice("phi (p4-phi): this session's brief marks it a new orchestrator, so p4-phi detached it "
                        "to top level at this first message. Now call `mcp__ccd_session_mgmt__detach_session` with "
                        "`\"self\"` before anything else, so the app stops nesting it under its parent session and its "
                        "reports stop going there; it orchestrates its own topic, and the other orchestrators are "
                        "its siblings."))
    # ezexe's own message: a handed-over task is none, and to a puppeteer, neither is one the app marks as another
    # session's; an orchestrator's routing still reads the work another session hands it
    ezexes = req if req and not handed_over(payload.get("prompt")) else ""
    if ezexes and puppeteer.from_session(payload.get("prompt"), by) and controls.is_puppeteer(s, me.store):
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
    split = split_text(me.home, s, payload.get("prompt"), by) if not route else ""
    last = route or "\n\n".join(x for x in (book_line, split) if x)
    save_session(me.home, s)
    # the rebase check, on every message: its warnings lead, then the notices, then what the sessions beside this
    # one changed and the rest, whole
    text, _ = relay.rebase(me.home, s["sessionId"], RELAY_CHARS, fair_cut, touches_of(me.home, s))
    RAN["relay"] = len(text)
    stop, changed = relay.stop_line(text)
    return acting_first([stop, changed, last] + parts, [stop] + keep)


def pair_parts(me, s, req, changed="", notice=lambda text: text):
    """Beside an orchestrator's message. A puppeteer gets what it is, once; the orchestrators it
    started, now controlled; an orchestrator ezexe started beside them; the controlled sessions' reports by reference; at a
    turn ezexe began, the requests addressed to it and where ezexe's message belongs; a boundary; once a controlled
    tree closed or reported done, the open issues no live session holds, each to route or start; and its board
    rewritten. Any other orchestrator gets its puppeteer, once, and what became of the requests it sent it."""
    out = []
    if not controls.is_puppeteer(s, me.store):
        told = controls.pair_text(s, me.store)
        if told:
            RAN["pair"] = "controlled"
        asks(s)
        answers = controls.answers_text(me.home, s) if s.get("puppeteer") else ""
        return [p for p in (told, answers) if p]
    RAN["pair"] = "puppeteer"
    controls.mark_puppeteer(me.store or me.home, me.cli)   # so the hooks module hands phi.py each edit and shell call
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
    waits, waited = [], []
    step = None if spawned_from(now_s) else plans.waiting_step(me.home, now_s["sessionId"])
    if not spawned_from(now_s) and controls.is_puppeteer(now_s, me.store):
        waits = controls.waited_on(now_s)          # its turn may end on a step that waits on its controlled sessions
        RAN["waits_on"] = len(waits)
        controls.board(me.home, now_s)
    named = ""
    if not waits and not spawned_from(now_s):      # a plain orchestrator waiting on the sessions of its tree
        pairs = waited_on(me.home, now_s, turn.get("calls") or [], ids=True) if step else []
        waits, waited = [w for _, w in pairs], [k for k, _ in pairs]
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
    # a turn that ends on a waiting step: kept for the look that follows, which names what the wait leaves to move
    wait_kept(me.home, now_s["sessionId"], row["id"], step if waits and not why else None, waited)
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
    relay.mark_paths(me.home, me.store or me.home)
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


def waited_on(home, s, calls=(), ids=False):
    """The titles of the sessions an orchestrator's waiting step still waits on, or with `ids` each as its id and
    its title: each worker or session it messaged that is inside a turn, or whose report it has not been handed yet.
    The sessions it messaged are kept on its record."""
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
            out.append((k, title_of(ks)) if ids else title_of(ks))
    return out


# --- what the hooks module is answered: a worker's starter, and the work a wait leaves to move ----------------------
#
# hooks/register.ts runs `phi.py look` for a session and acts on two keys of its answer, which no command hook could.
# `starter` is where the report of a worker's turn goes, by `$.session.send`: plugins/mods/api.md, "Send and receive
# messages between sessions", says the call "makes the same delivery the SendMessage tool makes", and
# cross-session-messaging.md, "Message delivery", that "When the receiving session is idle, Claude Code starts a new
# turn with the message." `move` is the prompt of a turn the module starts in a session whose turn ended on a wait
# while other work of it can move, ezexe/p4#193. A live probe between two desktop sessions on Claude Code 2.1.326
# showed both, as ezexe/p4#157 records.

TURN_TAIL = 65536             # bytes from the end of a turns.jsonl that hold its latest row
BESIDES_MAX = 8               # children with unlanded work named beside a wait


def starter_cli(home, s):
    """The session that started `s`, as the address `$.session.send({ to: { sessionId } })` takes: the CLI session
    id on the app's record of the starter, which is what `$.session.id()` answers there, else the last one its
    session.json holds. '' for a session nobody started, for a starter no record names a CLI session of, and for a
    puppeteer's standing worker or coworker, whose own first line asks it for the message its turn ends with."""
    above = spawned_from(s)
    if not above or s.get("standingKind") in ("worker", "coworker"):
        return ""
    cli = str(app_record(above).get("cliSessionId") or "")
    if not cli:
        held = [c for c in load_session(home, above).get("cliSessionIds") or [] if isinstance(c, str) and c]
        cli = held[-1] if held else ""
    return cli


def wait_kept(home, sid, turn_id, step, waited=()):
    """At a turn's end: the waiting step the turn ended on, kept on session.json as `waitEnded` with the turn's id
    and the sessions waited on, and taken off where the turn ended on none. It is written under the session's lock
    and straight to the file, as plans.keep_going writes its count."""
    path = os.path.join(session_dir(home, sid), "session.json")
    with relay.locked(path):
        disk = relay._read_json(path)
        if not disk.get("sessionId") or (not step and "waitEnded" not in disk):
            return
        disk.pop("waitEnded", None)
        if step:
            disk["waitEnded"] = {"turn": str(turn_id or ""), "step": str(step.get("addr") or ""),
                                 "waited": [str(k) for k in waited][:40], "time": now()}
        relay._write_json(path, disk)


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
    sessions unless phi.json turns them off, with `app_sections` for a puppeteer, which has it ask the sidebar's
    sections too. The verdict of a goal already set is read first, at every look, whatever phi.json's `goal` says,
    since a session may have asked for its own, goal_ask."""
    out = puppeteer.look(me.home, me.id, net=a.net, folder_only=False)
    due = ""
    if APP_TOOLS and not out.get("off"):
        out["app_tools"] = True
        try:                                       # a puppeteer's filing needs the sidebar's sections too
            if controls.is_puppeteer(load_session(me.home, safe_id(me.id)), me.store):
                out["app_sections"] = True
        except Exception as e:  # noqa: BLE001
            log_failure("app_sections", {}, e)
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


def ended_turn(home, sid):
    """The id of the turn a session's last Stop hook ended, when no prompt reached the session since, else ''. It is
    read from the session's log, as puppeteer.working reads it. A turn that ended on an error or with the session
    logs no turn id, so it answers ''."""
    last = {}
    for r in read_rows(os.path.join(session_dir(home, sid), "log.jsonl"), 256 * 1024):
        if r.get("hook") in ("user-prompt-submit", "stop"):
            last = r
    return str(last.get("turn") or "") if last.get("hook") == "stop" else ""


def movable_besides(home, s, step, waited):
    """What a session whose turn ended on a waiting step can still move, one line each: each child it does not wait
    on whose latest turn is done with a commit that closes an issue and has not landed, as issues.landed reads
    origin's branches, and each other open step that depends on no wait. A step that lands or checks work, waits on
    sessions or on ezexe, is a matter of ezexe's authority, or that a live child holds as its root step depends on
    the wait and is not named, and neither is a start request, which only ezexe's press starts. At most BESIDES_MAX
    children are named, and a child's closing commits are kept on the record as kidCommits by its latest turn, so a
    child is read again only once it reports again."""
    sid, out = s["sessionId"], []
    kids = [(k, ks) for k, ks in relay._sessions(home).items()
            if relay._parent(ks) == sid and not ks.get("stale") and not relay.archived_in_app(ks)]
    held = {str(ks.get("rootStep") or "") for _, ks in kids
            if not relay.gone(home, ks) and not ks.get("rootLeft")} - {""}
    kept = dict(s.get("kidCommits") or {}) if isinstance(s.get("kidCommits"), dict) else {}
    seen = dict(kept)
    for k, ks in kids:                             # a child counted as finished may still hold unlanded work
        if len(out) >= BESIDES_MAX:
            break
        last = last_turn_row(home, k)
        if k in waited or not last.get("done"):
            continue
        mark = f"{last.get('id')}@{last.get('time')}"
        was = kept.get(k) if isinstance(kept.get(k), dict) and kept[k].get("mark") == mark else None
        if was and was.get("landed"):              # every closing commit of this turn was found landed before
            continue
        commits = was["commits"] if was else [list(c) for c in relay.closing_commits(home, k, ks)]
        late = [c for c in commits if not issues.landed(c[0], c[1], c[3])]
        seen[k] = {"mark": mark, "landed": not late, "commits": commits if late else []}
        if late:
            path, sha, subject, closes = late[0]
            out.append(f"\"{title_of(ks)}\" reported done, and its commit {sha} \"{cut(clean(subject), 80)}\", "
                       f"which closes {', '.join(closes)}, is on no branch of origin: land it")
    if seen != kept:
        path = os.path.join(session_dir(home, sid), "session.json")
        with relay.locked(path):
            disk = relay._read_json(path)
            if disk.get("sessionId"):
                disk["kidCommits"] = dict(list(seen.items())[-200:])
                relay._write_json(path, disk)
    for x in plans.load(home, sid).get("steps") or []:
        if x.get("status") == "completed" or x.get("addr") == step.get("addr") or str(x.get("addr")) in held:
            continue
        text = str(x.get("content") or "")
        if plans.AWAITS.search(text) or plans.top_stays(text) or plans.AUTHORITY.search(text) \
                or plans.WAITS_ON_OWNER.search(text):
            continue
        out.append(f"step {x.get('addr')}, \"{cut(clean(x.get('content')), 100)}\", depends on no wait: do it")
    return out


def move_text(home, sid):
    """What `phi.py look` answers as `move`, the prompt of a turn the hooks module starts: the work of a session
    that its last turn's wait left unmoved, '' for none. It is answered once for a turn, and only while the turn the
    Stop hook kept as `waitEnded` is the last one that ended and no prompt has reached the session since. Each
    answer counts as one wake on `woke`, and none is given once the wakes in a row and the Stop hook's send-backs of
    that turn together reach plans.KEEP_GOING_MAX."""
    s = load_session(home, sid)
    wait = s.get("waitEnded") if isinstance(s.get("waitEnded"), dict) else {}
    turn = str(wait.get("turn") or "")
    if not turn or wait.get("moved") or relay.gone(home, s) or ended_turn(home, sid) != turn:
        return ""
    if plans.wakes(s) + plans.sent_back(s, turn) >= plans.KEEP_GOING_MAX:
        return ""
    step = next((x for x in plans.load(home, sid).get("steps") or []
                 if str(x.get("addr")) == str(wait.get("step")) and x.get("status") != "completed"), None)
    besides = movable_besides(home, s, step, [str(k) for k in wait.get("waited") or []]) if step else []
    if not besides:
        return ""
    path = os.path.join(session_dir(home, sid), "session.json")
    with relay.locked(path):
        disk = relay._read_json(path)
        held = disk.get("waitEnded") if isinstance(disk.get("waitEnded"), dict) else {}
        if str(held.get("turn") or "") != turn or held.get("moved"):
            return ""                              # another look answered it, or a turn began meanwhile
        held["moved"] = now()
        disk["woke"] = {"n": plans.wakes(disk) + 1, "time": now()}
        relay._write_json(path, disk)
    return (f"{plans.WAKE_MARK} step {step.get('addr')}, \"{cut(clean(step.get('content')), 100)}\", which waits on "
            "other sessions, and a wait stops only the work that depends on it. p4-phi's hooks module started this "
            "turn, and ezexe sent no message. Move these, then end the turn on the wait:\n"
            + "\n".join(f"- {b}" for b in besides[:12])
            + (f"\n- and {len(besides) - 12} more" if len(besides) > 12 else ""))


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
    if not spawned_from(s) and controls.is_puppeteer(s, me.store):
        import asks as requests                    # the request this turn opened goes to the session messaged
        try:
            requests.on_send(me.home, s, target, message)
        except Exception:  # noqa: BLE001
            pass
    return None


def h_start_advice(payload):
    """PreToolUse on mcp__ccd_session__start_session. It denies two starts: a controlled session's new
    orchestrator, which its puppeteer starts instead, and a puppeteer's second standing worker. For the rest it
    advises fork or fresh by relay.advise_start, from the parent's transcript size and how much of the parent's scope
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
    base = str(payload.get("cwd") or load_session(me.home, me.id).get("cwd") or "")
    here = str(inp.get("target") or "local") == "local" and not any(inp.get(k) for k in relay.ELSEWHERE)
    brief = str(inp.get("prompt") or "")
    if brief and here and not NEW_TOP.search(brief) and starts.writes(brief, base):
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
    if brief and NEW_TOP.search(brief):
        mine = load_session(me.home, me.id)
        if not spawned_from(mine) and controls.ask_text(mine) and controls.puppeteer_of(mine, me.store)[0]:
            RAN["asked_of_puppeteer"] = True       # asked of its puppeteer, never started here
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": (
                                               "phi (p4-phi): this start is refused: "
                                               + PHI_LEAD.sub("", controls.ask_text(mine)))}}
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
ROUTED["nudge"] = ("PreToolUse", h_nudge)
ROUTED["puppeteer-tool"] = ("PreToolUse", h_puppeteer_tool)
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
                 "request", "proof", "controls", "gaps", "upkeep", "goal", "app_tools", "cards", "conf", "sections",
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
            p.add_argument("plan", help="the plan file ezexe approved, whose runs of sections are printed as starts")
        if name == "coworkers":
            p.add_argument("plan", help="the plan file whose groups of sections are printed, each with its coworker")
            p.add_argument("--for", dest="planner", default="",
                           help="the session id of the planner the coworkers send their lists to, this session's "
                                "when left out")
            p.add_argument("--checkout", default="", help="the repository the coworkers and workers run in, the "
                                                          "folder this is run from when left out")
            p.add_argument("--start", action="store_true",
                           help="give each coworker a node, a store nested in the planner's, write its settings "
                                "file and start file there, and print the terminal call that starts each")
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
        if a.cmd == "sections":                    # an approved plan's runs, each as the start of the worker that lands it
            if not os.path.isfile(os.path.abspath(a.plan)):
                print(f"phi: no plan file at {os.path.abspath(a.plan)}", file=sys.stderr)
                return 2
            out = sections.calls(os.path.abspath(a.plan), os.getcwd())
            if not out:
                print("phi: no section of that plan names files on a `Files:` line, so it has no run to start",
                      file=sys.stderr)
                return 2
            for call in out:
                print("`mcp__ccd_session__start_session` with " + json.dumps(call, ensure_ascii=False))
            print(sections.CARD)
            return 0
        if a.cmd == "coworkers":                   # a plan's groups, each as the coworker that reads and lands it
            import coworker
            plan = os.path.abspath(a.plan)
            if not os.path.isfile(plan):
                print(f"phi: no plan file at {plan}", file=sys.stderr)
                return 2
            checkout = os.path.abspath(a.checkout or os.getcwd()).replace("\\", "/")
            who = safe_id(a.planner or me.id)
            planner_sid = who
            title = str((load_session(me.home, who) or {}).get("title") or "") if who else ""
            who = title or ("" if a.planner else who)
            if a.planner and not who:
                print(f"phi: no session {a.planner} with a title is in this store, so the coworkers would have "
                      "nobody to send their lists to", file=sys.stderr)
                return 2
            mode = upkeep.mode_of(safe_id(me.id)) if me.id else ""
            # each terminal session is a node nested in the store that holds the planner's folder
            node_of = {"home": me.home, "starter": planner_sid,
                       "store": relay.nodes(me.home).get(planner_sid) or me.home}

            def started(found):
                """Writes each new node's files and prints the call that starts it, and for a name that has a node
                already, that its session was started; the entries written."""
                new = [one for one in found if one.get("folder")]
                coworker.write(new, checkout, me.home)
                for one in found:
                    if one.get("started"):
                        print(f"phi: a session named `{one['name']}` was started already, from its node "
                              f"{one['started']}, so nothing is written for it", file=sys.stderr)
                return new
            if a.land:                             # a terminal worker for each group not landed, in LAND_MODE
                try:
                    found = coworker.land(plan, checkout, who, mode, claim=True, **node_of)
                except ValueError as e:
                    print(f"phi: {e}", file=sys.stderr)
                    return 2
                if not found:
                    print("phi: no section of that plan is left to land: each names no files or holds its "
                          "`Evidence:`", file=sys.stderr)
                    return 2
                new = started(found)
                if not new:
                    return 2
                for one in new:
                    print(f"worker `{one['name']}`: sections {', '.join(one['sections'])}, its report "
                          f"{one['report']}")
                    print("`mcp__terminal__run_in_terminal` with " + json.dumps(
                        {"title": one["name"], "cwd": checkout, "command": one["typed"]}, ensure_ascii=False))
                return 0
            if a.wait is not None and a.report:    # a terminal worker's one sign is its report file
                report = os.path.abspath(a.report).replace("\\", "/")
                tab = os.path.basename(report)[len("report-"):].rsplit(".", 1)[0]
                how, waited = coworker.wait_report(report, me.home, tab)
                print(f"done: {report} is there, after {waited} seconds" if how == "done" else
                      f"long: {report} is not there after {waited} seconds: look at the terminal tab `{tab}`")
                return 0
            if a.wait is not None:                 # a round's wait, which only reads
                # the names the starter answered with, since a mend can move a section into another group
                try:
                    names = a.wait or [one["name"] for one in coworker.drafts(plan, checkout, who) if one["team"]]
                except ValueError as e:
                    print(f"phi: {e}", file=sys.stderr)
                    return 2
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
            try:
                found = coworker.drafts(plan, checkout, who, mode, claim=a.start, **node_of)
            except ValueError as e:
                print(f"phi: {e}", file=sys.stderr)
                return 2
            if not found:
                print("phi: no section of that plan names files on a `Files:` line, so it has no group to read",
                      file=sys.stderr)
                return 2
            if a.start:
                if not started(found) and any(one.get("started") for one in found):
                    return 2
                if mode not in upkeep.NO_ASK:      # a mode that asks, or none the app's record names
                    print(f"phi: this session's permission mode is {f'`{mode}`' if mode else 'not known'}, so each "
                          "coworker may ask in its tab before an edit or a command: these coworkers only read, so "
                          "say so to the planner, which lands their groups by integrator subagents")
            for one in found:
                nums = ", ".join(one["sections"])
                if not one["team"]:
                    print(f"sections {nums}, {one['fences']} fences and no check: one `p4-phi:check` reads them, "
                          "which the planner starts")
                    continue
                print(f"coworker `{one['name']}`: sections {nums}, {one['fences']} fences, a team of three")
                if one.get("folder"):
                    print("`mcp__terminal__run_in_terminal` with " + json.dumps(
                        {"title": one["name"], "cwd": checkout, "command": one["typed"]}, ensure_ascii=False))
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
