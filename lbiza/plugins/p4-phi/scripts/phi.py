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
           finished a turn since it last looked (the app relays the first 400 characters). And the user's
           standing instruction for a message about something else (`new_task`): start a forked session for it
           and stay with the task; once in full, then a line beside each of the user's messages.
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
import relay  # noqa: E402  (shards, deltas, anchors: linked sessions kept in step while they work)

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


def read_record(name):
    acct, org = os.environ.get("CLAUDE_CODE_ACCOUNT_UUID") or "", os.environ.get("CLAUDE_CODE_ORGANIZATION_UUID") or ""
    for root in app_roots():
        if acct and org:
            d = read_json(os.path.join(root, acct, org, name))
            if d:
                return d
        for p in glob.glob(os.path.join(root, "*", "*", name)):
            d = read_json(p)
            if d:
                return d
    return {}


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
        self.rec = app_record(session or host) if (session or host) else record_of_cli(self.cli)
        self.id = session or host or str(self.rec.get("sessionId") or "") or self.cli
        project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        self.home = p4 or ""
        if not self.home:
            above = spawned_from(self.rec)
            if not above and hint and hint != self.id:
                above = self.hint = hint
            self.home = (home_of_record(app_record(above)) if above else "") or store_at(project) \
                or home_of_record(self.rec)


# --- sessions --------------------------------------------------------------------------------------------------------

def load_session(home, sid):
    return read_json(os.path.join(session_dir(home, sid), "session.json")) if sid else {}


def save_session(home, s):
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
    if source not in ("detached", "reparented") and (not held or source == "notes folder"):
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
                cur = {"prompt": req, "uuid": str(d.get("uuid") or ""), "calls": [],
                       "time": str(d.get("timestamp") or "")[:16].replace("T", " ")}
        elif d.get("type") == "assistant" and cur is not None:
            for b in c if isinstance(c, list) else []:
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


def background_text(home, s, own=False):
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
            notes.append(f"- {cut(clean(r.get('claim')), 300)} ({kind}source: {cut(clean(r.get('source')), 120)})")
    notes = nd.by_overlap(notes, own_task)      # with this session's task known, the notes nearest it come first
    if notes:
        body += ["Notes of the sessions above (already checked; do not work these out again):"] + notes[:12]
    others = [r for r in latest_reports(load_reports(home, above, TAIL_BYTES), skip=sid)[:OTHERS * 3]
              if spawned_from(load_session(home, r["sessionId"])) == above][:OTHERS]
    others = nd.by_overlap(others, own_task, key=lambda r: f"{r.get('title', '')} {r.get('turn', {}).get('prompt', '')}")
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


def new_task_text(home, s, me, user=True, again=False):
    """The user's standing instruction for a message about something else: once in full for a CLI session that
    has a task (and again after a compaction), then a line with the task beside each of the user's messages.
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
        return (f"phi (p4-phi): this session's task: \"{cut(task, RULE_TASK)}\" When a message from the user is "
                f"about something else, do not turn this session to it. Start a session for it with "
                f"`mcp__ccd_session__start_session` (initiation `user_asked`, context `fork`, so it has this whole "
                f"conversation and shares this checkout), tell the user in one line which session has it, and "
                f"stay with the task. A message about a path inside another session's shard is that session's: "
                f"send it there with SendMessage instead, and start a new session only for what no shard covers"
                f"{shards}. This is the user's standing instruction for this project, so the session "
                f"is started, not offered as a card. Its report comes back here in full. A quick thing (a "
                f"question, a few tool calls) stays here. When the user says the task itself has changed: "
                f"`{commands()} task \"<the new task>\"`. This session's page: {page_path(home, s['sessionId'])}.")
    if not user:
        return ""
    RAN["new_task"] = "line"
    return (f"phi (p4-phi): this session's task is \"{cut(task, LINE_TASK)}\" If this message is about something "
            f"else, start a forked session for it and stay with the task; otherwise carry on.")


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


def rules_text(home, room):
    """The store's rules for a session's start, a line each, in at most `room` characters. '' with none."""
    rules = memory_rules(home) if RULES and home else []
    if not rules or room < 600:
        return ""
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
    names = [f"- {name}: " for name, _ in rules]
    room -= len(head) + sum(len(x) + 1 for x in names) + 2
    RAN["rules"] = len(rules)
    return "\n".join([head] + [a + b for a, b in zip(names, fair_cut([rule_of(b) for _, b in rules], room))])


# --- the hooks -------------------------------------------------------------------------------------------------------

def given(s, me, home, own=False):
    """The background, when this CLI session has not been given it under the session that started it; marks it
    given."""
    if not BACKGROUND:
        return ""
    told = s.setdefault("backgroundGivenFor", {})
    if not isinstance(told, dict):
        told = s["backgroundGivenFor"] = {}
    above = spawned_from(s)
    if not own and told.get(me.cli) == above:
        return ""
    told[me.cli] = above
    text = background_text(home, s, own=own)
    if above and not s.get("forked"):
        piece = relay.slice_text(home, s)          # a fresh child starts with exactly what the parent has for it
        text = "\n\n".join(p for p in (text, piece) if p)
    if above and "anchorSeen" not in s:
        # the start is the child's base: a fresh child's slice or a fork's inherited conversation already holds the
        # anchor as it is now, so the rebase check hands over only what changes after it
        s["anchorSeen"] = relay.anchor_version(home, above)
        s["marksGiven"] = relay.mark_keys(home, above)
    return text


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
        return None
    p4conf.migrate_layout(me.home)        # the memory read below is where the other plugins will have moved it
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
    pin = relay.pin_text(s) if s.get("forked") else ""
    text = "\n\n".join(p for p in (pin, text) if p)
    rules = rules_text(me.home, HOOK_CHARS - len(text) - len(rule) - 4) if source != "resume" else ""
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


def h_user_prompt_submit(payload):
    me = started_by(Me(payload), payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    s = ensure_session(me.home, me.id, me.rec, me.cli, hint=me.hint)
    ran_for(s, me)
    req = request_of(payload.get("prompt"))
    mark_fork(s, me, payload)
    if req and not s.get("task"):
        s["task"] = cut(req, TASK_CHARS)
        s["taskAt"] = now()
    parts = [relay.pin_text(s) if s.get("forked") else "", given(s, me, me.home)]
    if REPORTS:
        text, seen = reports_text(me.home, s)
        s["reportsSeen"] = seen
        parts.append(text)
    route = relay.route_text(me.home, s["sessionId"], req, s.get("cwd") or "") if req else ""
    parts.append(route or new_task_text(me.home, s, me, user=bool(req)))
    save_session(me.home, s)
    # the rebase check, on every message: what the nodes beside this one changed, and the warnings, first
    used = sum(len(p) for p in parts if p)
    text, _ = relay.rebase(me.home, s["sessionId"], HOOK_CHARS - used, fair_cut)
    RAN["relay"] = len(text)
    return "\n\n".join(p for p in [text] + parts if p)


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
    for node in (above, s["sessionId"]):           # the anchor of the node above, and this node's own for its children
        a = relay.make_anchor(me.home, node, row["time"])
        if a and node == above:
            RAN["anchor"] = a.get("version")
    render_page(me.home, s["sessionId"])
    render_page(me.home, above)
    RAN.update(turn=row["id"], done=bool(row["done"]))
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
        # the user's rule: a child works on the parent's branch in the parent's checkout
        reasons.append("p4-phi: the user's rule is no worktrees and no branches of a child's own; pass "
                       "`use_worktree: false`, leave out branch_name and source_branch, and let the child work on "
                       "this session's branch in this checkout.")
    if not reasons:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": " ".join(reasons)}}


BRANCHING = re.compile(r"\bgit\b[^\n|;&]*?\b(worktree\s+add|switch\s+(-c|--create|-C)|checkout\s+(-b|-B)|"
                       r"branch\s+(?!-)[\w./-]+\s*$|branch\s+(?!-)[\w./-]+\s+[\w./-]+)")


def h_branch_guard(payload):
    """PreToolUse on EnterWorktree and Bash in a session another one started: making a worktree or a branch of its
    own is asked first, the user's rule being that a child works on its parent's branch. Silent otherwise."""
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
    elif name in SHELL_TOOLS and BRANCHING.search(str(inp.get("command") or "")):
        what = "making a worktree or branch of its own"
    else:
        return None
    RAN["branch_guard"] = what
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": f"p4-phi: this session is a child, and {what} goes "
                                                               f"against the user's rule: a child works on its "
                                                               f"parent's branch in the parent's checkout, so its work "
                                                               f"needs no merge."}}


HOOKS = {"session-start": ("SessionStart", h_session_start),
         "user-prompt-submit": ("UserPromptSubmit", h_user_prompt_submit),
         "stop": ("Stop", h_stop),
         "start-advice": ("PreToolUse", h_start_advice),
         "branch-guard": ("PreToolUse", h_branch_guard)}
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
    started = {}
    for s in sorted(sessions.values(), key=lambda s: s.get("createdAt", "")):
        above = spawned_from(s)
        started.setdefault(above if above in sessions else "", []).append(s)
    out = []

    def walk(above, depth):
        for s in started.get(above, []):
            turns = load_turns(home, s["sessionId"])
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
    for name in ("note", "done", "task", "show", "tree", "background", "detach", "reparent", "shard"):
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
        if name in ("detach", "reparent"):
            p.add_argument("moved")
        if name == "shard":
            p.add_argument("paths", nargs="*", help="paths or globs this session alone may change; none shows it")
        if name == "reparent":
            p.add_argument("under")
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
