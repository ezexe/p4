#!/usr/bin/env python3
"""phi.py: the memo on the session tree.

A session is a node. The session that started it is its parent, and a session nobody started is a child of the
store's base node, `root`. A node's memo is what its children start from; a child's play belongs to its parent's
goal by where it stands, not by its words; a child's exit rolls up into its parent. In the owner's words: "a kept
play weather it scores or not is always memorized. from the first memorization on you revisit it ghosted tainted
by its memo so anything memoized gets executed if as you exit theres nothing that closed the request thats a new
memo moment fed by the context the birthed ghost adorned".

  node     <home>/phi/nodes/<node id>/: node.json (parent, title, goal, what it was told), plays.jsonl, notes.jsonl,
           rollup.jsonl (its children's exits), log.jsonl (a line a hook call) and memo.md, the same things as one page
           anyone can read. The node id
           is the app's session id (CLAUDE_CODE_HOST_SESSION_ID, in a hook's environment), or the CLI's session id
           where no app runs it.
  parent   a hook's payload names no parent. The app keeps a record for each session,
           claude-code-sessions/<account>/<organization>/<node id>.json, whose `spawnedFrom.sessionId` is the
           session that started it. The app writes that field a moment after the session exists: at a child's
           SessionStart it is not there, and at its first message it may not be yet (seen live, 2026-11-11). So
           a session in the app is told nothing at its start. At a handed-over first message with no recorded
           starter, the starter is read from the message's own shared notes folder, which the app names after
           it (three of three live sessions), and the record corrects it when it comes (it had come by the
           turn's end in each). A handed-over message that names no folder waits for the record (`wait_s`,
           2 s; live, a wait of 2 s once ended without it). Once read from the record the parent is kept in
           node.json, which is the tree from then on: `reparent` moves a node by rewriting it, whatever the
           app shows.
  home     the store the family's nodes live in: the top session's <project>/.claude/p4. A child in a worktree or
           another folder has no store of its own and uses its parent's, found through the parent's record.
  arrive   SessionStart: the node is made if new. After a compaction or a clear, and at the start of a session no
           app runs, the session is told what it starts from (the ghost): the goals of the line above it, the
           notes kept there, the plays its siblings made, and its own plays. Nothing where nothing is memoized.
  prompt   UserPromptSubmit: the first request becomes the node's goal; the ghost, where the start did not give it;
           and the exits of this node's children since it last looked, whole (the app relays 400 characters).
  exit     Stop: the turn is memoized as a play, scored or not: the request, the files edited, the commands that
           worked, the sessions started, the failures, the reply. `closed` when the session ran `close --check`
           in the turn, `open` otherwise. It is appended to the parent's rollup.

  steer    a session holds one goal, its first request. Turning it to whatever the owner says next is how a session
           ends up spun around its target, and a new session started by hand for the new thing lacks the state
           this one built. So the session is told its goal and the rule once (and again after a compaction): a
           message of the owner's that steers off the goal is shipped to a child session forked from this one,
           which has this session's exact state and shares its checkout, and this session stays where it was;
           the child's exit comes back whole. Beside each later message of the owner's goes one line with the
           goal. The session judges what is off its goal; the hook matches nothing. `goal "<new goal>"` re-aims
           the node when the owner says the goal itself has changed.

Commands for a session: `note "<claim>" --source "<where checked>"`, `close --check "<what showed it scored>"`,
`goal "<the new goal>"`, `memo [node]`, `tree`, `ghost`, `reparent <node> <new parent>`.

Settings: <home>/phi/phi.json, every key optional: `ghost`, `rollup`, `exit`, `steer` (false: off),
`ghost_chars`, `rollup_chars`, `wait_s`. P4_PHI=0 in the environment turns the plugin off, P4_PHI_STEER=0 the steer.

Nothing here matches a request to a play by its words: that was built in p4-recall 0.8.17 to 0.8.20, measured
(the nearest earlier play's files touched again 0.06 to 0.13 of the time) and removed.
"""

import glob
import hashlib
import json
import os
import re
import sys
import time

GHOST = True
ROLLUP = True
EXIT = True
STEER = True
STEER_GOAL = 400                 # of the goal, in the rule
STEER_LINE = 160                 # of the goal, in the line beside a message
GHOST_CHARS = 3000
ROLLUP_CHARS = 6000
CLOSING_CHARS = 4000
GOAL_CHARS = 1200
PLAY_STEPS = 12
LINE_MAX = 8                     # ancestors followed, from a node up
SIBLINGS = 5
OWN = 3
TAIL_BYTES = 256 * 1024          # of a rollup, for a ghost
TRANSCRIPT_BYTES = 8 * 1024 * 1024
WAIT_S = 2.0                     # how long a handed-over first message waits for the app to record its starter
SCAN_RECORDS = 60                # the newest app records searched for a CLI session id, when the host id is missing
ROOT = "root"
SETTINGS = {"steer": "STEER", "ghost": "GHOST", "rollup": "ROLLUP", "exit": "EXIT", "ghost_chars": "GHOST_CHARS",
            "rollup_chars": "ROLLUP_CHARS", "wait_s": "WAIT_S"}
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


def safe_id(nid):
    return SAFE.sub("_", str(nid or ""))[:80]


def node_dir(home, nid):
    return os.path.join(home, "phi", "nodes", safe_id(nid))


def configure(home):
    d = read_json(os.path.join(home, "phi", "phi.json"))
    for key, name in SETTINGS.items():
        if key in d and type(d[key]) is type(globals()[name]):
            globals()[name] = d[key]
    if os.environ.get("P4_PHI_STEER") in ("0", "1"):
        globals()["STEER"] = os.environ["P4_PHI_STEER"] == "1"


# --- the app's records: who started whom ---------------------------------------------------------------------------

def app_roots():
    """The folders that may hold the app's session records (claude-code-sessions), likeliest first."""
    given = os.environ.get("P4_PHI_APP_SESSIONS")
    if given:
        return [given]
    out = []
    exe = os.environ.get("CLAUDE_CODE_EXECPATH") or ""
    d = os.path.dirname(exe)
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


def app_record(host):
    """The app's record of a session, {} when there is none to read."""
    name = safe_id(host) + ".json"
    if not host or not name.startswith("local_"):
        return {}
    if host in RECORDS:
        return RECORDS[host]
    RECORDS[host] = d = read_record(name)
    return d


RECORDS = {}


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


def parent_of_record(rec):
    s = rec.get("spawnedFrom") if isinstance(rec, dict) else None
    return str(s.get("sessionId") or "") if isinstance(s, dict) else ""


def store_at(folder):
    if not folder:
        return ""
    p = os.path.join(folder, ".claude", "p4")
    return p if os.path.isdir(p) else ""


def home_of_record(rec, depth=0):
    """The store a session's family lives in: its starter's, and its own folder's where nobody started it."""
    if not rec or depth > LINE_MAX:
        return ""
    parent = parent_of_record(rec)
    if parent:
        h = home_of_record(app_record(parent), depth + 1)
        if h:
            return h
    return store_at(rec.get("cwd")) or store_at(rec.get("originCwd"))


class Me:
    """Who a hook or a command is running for: its node id, its CLI session, the app's record, its home."""

    def __init__(self, payload=None, node="", p4="", hint=""):
        payload = payload or {}
        self.hint = ""
        self.cli = str(payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
        host = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
        self.rec = app_record(node or host) if (node or host) else record_of_cli(self.cli)
        self.id = node or host or str(self.rec.get("sessionId") or "") or self.cli
        project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        self.home = p4 or ""
        if not self.home:
            parent = parent_of_record(self.rec)
            if not parent and hint and hint != self.id:
                parent = self.hint = hint
            self.home = (home_of_record(app_record(parent)) if parent else "") or store_at(project) \
                or home_of_record(self.rec)


# --- nodes ---------------------------------------------------------------------------------------------------

def load_node(home, nid):
    return read_json(os.path.join(node_dir(home, nid), "node.json"))


def save_node(home, node):
    write_atomic(os.path.join(node_dir(home, node["id"]), "node.json"),
                 json.dumps(node, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def ensure_node(home, nid, rec=None, cli="", depth=0, hint=""):
    """The node, made if new, with its line above it made too (an ancestor this plugin never ran in gets its node
    from the app's record). node.json's parent is the tree: the record is read for a new node, and for a node that
    was hung on the base node before its record could be read."""
    nid = safe_id(nid)
    node = load_node(home, nid)
    if nid == ROOT:
        if not node:
            node = {"id": ROOT, "parent": "", "title": "the base node of this store", "created": now()}
            save_node(home, node)
        return node
    changed = False
    if not node.get("id"):
        node = {"id": nid, "parent": "", "title": "", "created": now(), "sessions": [], "goal": "", "seen": 0,
                "ghosted": {}}
        changed = True
    if not node.get("parent") or (node["parent"] == ROOT or node.get("parent_from") == "hint") and not node.get("moved"):
        rec = rec if rec is not None else app_record(nid)
        parent, source = safe_id(parent_of_record(rec)), "record"
        if not parent and node.get("parent_from") == "hint":
            parent, source = node["parent"], "hint"
        if not parent and hint:
            parent, source = safe_id(hint), "hint"
        if not parent or parent == nid:
            parent, source = ROOT, ""
        if parent != node.get("parent") or source != node.get("parent_from", ""):
            node["parent"], node["parent_from"] = parent, source
            changed = True
    title = clean(rec.get("title"))[:120] if rec else ""
    if title and title != node.get("title"):      # the app titles a session after it has started
        node["title"] = title
        changed = True
    if cli and cli not in node.setdefault("sessions", []):
        node["sessions"].append(cli)
        changed = True
    if changed:
        save_node(home, node)
    if depth < LINE_MAX:
        if not load_node(home, node["parent"]).get("id"):
            ensure_node(home, node["parent"], depth=depth + 1)
    return node


def title_of(node):
    return node.get("title") or cut(clean(node.get("goal")), 60) or str(node.get("id") or "")[:14]


def line_of(home, nid):
    """The ids above a node, nearest first, the base node left out."""
    out, cur = [], load_node(home, nid).get("parent") or ""
    while cur and cur != ROOT and cur not in out and len(out) < LINE_MAX:
        out.append(cur)
        cur = load_node(home, cur).get("parent") or ""
    return out


def load_plays(home, nid):
    """A node's plays, oldest first, each turn once (its latest exit)."""
    by = {}
    for r in read_rows(os.path.join(node_dir(home, nid), "plays.jsonl")):
        if r.get("id"):
            by[r["id"]] = r
    return list(by.values())


def load_notes(home, nid):
    return read_rows(os.path.join(node_dir(home, nid), "notes.jsonl"))


def load_rollup(home, nid, tail=None):
    return read_rows(os.path.join(node_dir(home, nid), "rollup.jsonl"), tail)


def latest_exits(rows, skip=""):
    """From rollup rows, each child's latest exit, newest first. A child moved away is dropped."""
    by = {}
    for r in rows:
        child = r.get("child") or r.get("moved")
        if not child:
            continue
        by.pop(child, None)
        if r.get("child") and isinstance(r.get("play"), dict):
            by[child] = r
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
    """Does a message look like a task another session handed over: the wrapper, the family reminder, or the
    shared notes folder. Such a session has a starter, whether or not the app has recorded it yet."""
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
    call after it. A message of the harness (a child's exit relayed, a notification) opens no turn."""
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
    """A command as a play's step: past its `cd x &&`, up to its first pipe."""
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


def play_of(turn, reply):
    """A turn as a play: what was asked, the files edited and the commands that worked and the sessions started,
    in order, the failures met, and how it ended."""
    steps, avoid = [], []

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
                add(avoid, failure_note(cmd, c.get("result")))
            elif program(cmd) not in LOOKING and "<<" not in cmd and len(cmd) <= 400:
                add(steps, f"ran `{run_shape(cmd)}`")
        elif name.endswith("start_session"):
            add(steps, f"started the session \"{cut(clean(inp.get('title') or inp.get('name')), 80)}\"")
        elif name in ("Agent", "Task"):
            add(steps, f"ran a subagent: {cut(clean(inp.get('description')), 80)}")
    goal = cut(turn.get("prompt") or "", GOAL_CHARS)
    uuid = turn.get("uuid") or ""
    return {"id": uuid or "play-" + hashlib.sha1(goal.encode("utf-8", "replace")).hexdigest()[:12],
            "goal": goal, "steps": steps[:PLAY_STEPS], "avoid": avoid[:4],
            "closing": (reply or "").strip()[:CLOSING_CHARS], "state": "open", "check": ""}


# --- what a session is told ------------------------------------------------------------------------------------------

def play_lines(title, p, closing=300, goal=200):
    how = p.get("state") or "open"
    if how == "closed" and p.get("check"):
        how += ", checked by: " + cut(clean(p["check"]), 160)
    out = [f"- \"{title}\" ({how}; {p.get('time', '')}): {cut(clean(p.get('goal')), goal)}"]
    if p.get("steps"):
        out.append("  steps: " + cut("; ".join(p["steps"]), 400))
    if p.get("children"):
        out.append("  its sessions: " + cut("; ".join(p["children"]), 300))
    if p.get("avoid"):
        out.append("  avoid: " + cut("; ".join(p["avoid"]), 300))
    if p.get("closing"):
        text = p["closing"] if closing >= CLOSING_CHARS else clean(p["closing"])
        out.append("  ended: " + cut(text, closing))
    return out


def commands():
    script = os.path.abspath(__file__).replace("\\", "/")
    return f'python -I -X utf8 "{script}"'


def ghost_text(home, node, own=False):
    """What a session starts from: the goals of the line above it, the notes kept there, the plays made under its
    parent before it, and with `own` its own plays. '' when none of that exists."""
    nid, parent = node["id"], node.get("parent") or ROOT
    line = [load_node(home, x) for x in line_of(home, nid)]
    body = []
    goals = [f"- \"{title_of(n)}\": {cut(clean(n.get('goal')), 500 if k == 0 else 200)}"
             for k, n in enumerate(line) if n.get("goal")]
    if goals:
        body += ["The goals above this session, nearest first (this session's task serves the first):"] + goals
    notes = []
    for n in line:
        for r in load_notes(home, n["id"]):
            kind = f"{r['kind']}; " if r.get("kind") else ""
            notes.append(f"- {cut(clean(r.get('claim')), 300)} ({kind}source: {cut(clean(r.get('source')), 120)})")
    if notes:
        body += ["Established above (do not work these out again):"] + notes[:12]
    exits = [r for r in latest_exits(load_rollup(home, parent, TAIL_BYTES), skip=nid)[:SIBLINGS * 3]
             if (load_node(home, r["child"]).get("parent") or ROOT) == parent][:SIBLINGS]
    if exits:
        where = "by this repository's sessions before this one" if parent == ROOT else \
            f"under \"{title_of(line[0]) if line else parent}\" before this session"
        body += [f"Plays made {where} (a closed one scored; an open one stopped where it says):"]
        for r in exits:
            body += play_lines(r.get("title") or r["child"][:14], r["play"])
    if own:
        mine = load_plays(home, nid)[-OWN:]
        if mine:
            body += ["This session's own plays so far:"]
            for p in reversed(mine):
                body += play_lines(title_of(node), p)
    if not body:
        return ""
    if parent == ROOT:
        head = ("phi (p4-phi): this repository's sessions keep their plays on a tree, and this session starts "
                "from them. Execute what a play holds where it fits; do not work it out again.")
    else:
        head = (f"phi (p4-phi): this session is the node \"{title_of(node)}\" of a session tree, started by "
                f"\"{title_of(line[0]) if line else parent}\". It starts from the memo above it: execute what the "
                f"memo holds where it fits; do not work it out again.")
    memo = os.path.join(node_dir(home, parent), "memo.md").replace("\\", "/")
    tail = (f"The memo above, whole: {memo}. Keep a finding the next session would have to rediscover: "
            f"`{commands()} note \"<claim>\" --source \"<where it was checked>\"`. When something shows the goal "
            f"scored: `{commands()} close --check \"<what was run and what it showed>\"`. The exit is memoized "
            f"either way and handed to the session above.")
    room = GHOST_CHARS - len(head) - len(tail) - 2
    text = "\n".join(body)
    if len(text) > room:
        text = text[:max(0, room - 4)].rsplit("\n", 1)[0] + "\n..."
    return "\n".join((head, text, tail))[:GHOST_CHARS]


def rollup_text(home, node):
    """The exits of this node's children since it last looked, whole, and how many rows that covers."""
    rows = load_rollup(home, node["id"])
    seen = node.get("seen") if isinstance(node.get("seen"), int) else 0
    new = latest_exits(rows[seen:])
    if not new:
        return "", len(rows)
    out = ["phi (p4-phi): exits of the sessions this one started, since it last looked. The app relays 400 "
           "characters of a report; this is the play."]
    room = ROLLUP_CHARS - len(out[0])
    each = max(600, room // len(new))
    for r in reversed(new):
        lines = play_lines(r.get("title") or r["child"][:14], r["play"], closing=CLOSING_CHARS, goal=300)
        text = cut("\n".join(lines), each)
        memo = os.path.join(node_dir(home, r["child"]), "memo.md").replace("\\", "/")
        out += [text, f"  its memo: {memo}"]
    return "\n".join(out), len(rows)


def render_memo(home, nid):
    """memo.md: the node as one page (its goal, notes, plays and children), rewritten from the node's files."""
    node = load_node(home, nid)
    if not node.get("id"):
        return
    out = [f"# {title_of(node)}", ""]
    if nid != ROOT:
        out += [f"Node `{nid}` under `{node.get('parent') or ROOT}`.", ""]
        if node.get("goal"):
            out += ["## Goal", "", node["goal"].strip(), ""]
        notes = load_notes(home, nid)
        if notes:
            out += ["## Notes", ""]
            out += [f"- {clean(r.get('claim'))} (source: {clean(r.get('source'))}; {r.get('time', '')})" for r in notes]
            out.append("")
        plays = load_plays(home, nid)
        if plays:
            out += ["## Plays", ""]
            for p in plays:
                out += play_lines(title_of(node), p, closing=1200, goal=400)
            out.append("")
    exits = latest_exits(load_rollup(home, nid, TAIL_BYTES))[:40]
    if exits:
        out += ["## Sessions under this node, newest first", ""]
        for r in exits:
            out += play_lines(r.get("title") or r["child"][:14], r["play"], closing=600, goal=300)
            out.append(f"  node: `{r['child']}`")
        out.append("")
    write_atomic(os.path.join(node_dir(home, nid), "memo.md"), "\n".join(out))


# --- the hooks -------------------------------------------------------------------------------------------------------

def told(node, me, home, own=False):
    """The ghost, when this CLI session has not been given it under this parent; marks it given."""
    if not GHOST:
        return ""
    ghosted = node.setdefault("ghosted", {})
    if not isinstance(ghosted, dict):
        ghosted = node["ghosted"] = {}
    if not own and ghosted.get(me.cli) == node.get("parent"):
        return ""
    ghosted[me.cli] = node.get("parent")
    return ghost_text(home, node, own=own)


def steer_text(home, node, me, owner=True, again=False):
    """The steer: the rule in full the first time this CLI session has a goal to hold (and again after a
    compaction), then one line with the goal beside each message of the owner's. '' with no goal, and beside
    the harness's messages."""
    goal = clean(node.get("goal"))
    if not STEER or not goal:
        return ""
    steered = node.setdefault("steered", {})
    if not isinstance(steered, dict):
        steered = node["steered"] = {}
    if again or not steered.get(me.cli):
        steered[me.cli] = now()
        RAN["steer"] = "rule"
        memo = os.path.join(node_dir(home, node["id"]), "memo.md").replace("\\", "/")
        return (f"phi (p4-phi): this session is a node with one goal: \"{cut(goal, STEER_GOAL)}\" "
                f"When a message of the owner's steers off that goal, do not turn this session to it. Ship it: "
                f"start a child session for it with `mcp__ccd_session__start_session` (initiation `user_asked`, "
                f"context `fork`, so the child has this session's exact state and shares its checkout), tell the "
                f"owner in one line which session has it, and stay on the goal. This is the owner's standing "
                f"instruction for this repository, so it is started, not offered as a card. The child's exit "
                f"comes back here whole. What a few tool calls settle is answered here. When the owner says the "
                f"goal itself has changed, re-aim: `{commands()} goal \"<the new goal>\"`. This node's page: "
                f"{memo}.")
    if not owner:
        return ""
    RAN["steer"] = "line"
    return (f"phi (p4-phi): this session's goal is \"{cut(goal, STEER_LINE)}\" If this message steers off it, "
            f"ship it to a forked child session and stay; otherwise go on.")


def h_arrive(payload):
    me = Me(payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    node = ensure_node(me.home, me.id, me.rec, me.cli)
    RAN.update(home=me.home, node=node["id"], parent=node.get("parent"), cli=me.cli)
    source = payload.get("source") or "startup"
    RAN["source"] = source
    if source == "startup" and node.get("parent") == ROOT and not node.get("goal") \
            and os.environ.get("CLAUDE_CODE_HOST_SESSION_ID"):
        return None             # the app has not recorded this session's starter yet: the first message tells it
    lost = source in ("compact", "clear")
    text = told(node, me, me.home, own=lost or len(node.get("sessions") or []) > 1)
    rule = steer_text(me.home, node, me, owner=False, again=lost) if lost else ""
    save_node(me.home, node)
    return "\n\n".join(p for p in (text, rule) if p)


def starter(me, payload):
    """A handed-over message whose session has no recorded starter yet: wait for the app to write it, and failing
    that take the starter from the message's notes folder. Returns the Me to go on with."""
    prompt = payload.get("prompt")
    if parent_of_record(me.rec) or not me.id.startswith("local_") or not handed_over(prompt):
        return me
    if me.home:
        node = load_node(me.home, me.id)
        if node.get("goal") or node.get("moved") or node.get("parent") not in (None, "", ROOT):
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
        if parent_of_record(app_record(me.id)):
            RAN["waited_ms"] = round((time.time() - started) * 1000)
            return Me(payload)
    RAN["waited_ms"] = round((time.time() - started) * 1000)
    return me


def h_prompt(payload):
    me = starter(Me(payload), payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    node = ensure_node(me.home, me.id, me.rec, me.cli, hint=me.hint)
    RAN.update(home=me.home, node=node["id"], parent=node.get("parent"), cli=me.cli,
               parent_from=node.get("parent_from", ""))
    req = request_of(payload.get("prompt"))
    if req and not node.get("goal"):
        node["goal"] = cut(req, GOAL_CHARS)
        node["goal_time"] = now()
    parts = [told(node, me, me.home)]
    if ROLLUP:
        text, seen = rollup_text(me.home, node)
        node["seen"] = seen
        parts.append(text)
    parts.append(steer_text(me.home, node, me, owner=bool(req)))
    save_node(me.home, node)
    return "\n\n".join(p for p in parts if p)


def h_exit(payload):
    me = Me(payload)
    if not me.home or not me.id:
        return None
    configure(me.home)
    if not EXIT:
        return None
    node = ensure_node(me.home, me.id, me.rec, me.cli)
    RAN.update(home=me.home, node=node["id"], parent=node.get("parent"), cli=me.cli)
    reply = payload.get("last_assistant_message") or ""
    turn = last_turn(payload.get("transcript_path") or "")
    if not turn and node.get("goal"):
        turn = {"prompt": node["goal"], "uuid": "", "calls": []}
    if not turn:
        return None
    play = play_of(turn, reply if isinstance(reply, str) else "")
    play.update({"time": now(), "node": node["id"], "session": me.cli})
    check = node.get("check") if isinstance(node.get("check"), dict) else None
    if check and clean(check.get("text")):
        play.update({"state": "closed", "check": clean(check["text"])[:400]})
    play["children"] = [f"\"{r.get('title') or r['child'][:14]}\": {r['play'].get('state', 'open')}"
                        for r in latest_exits(load_rollup(me.home, node["id"]))][:PLAY_STEPS]
    append_line(os.path.join(node_dir(me.home, node["id"]), "plays.jsonl"), play)
    parent = node.get("parent") or ROOT
    append_line(os.path.join(node_dir(me.home, parent), "rollup.jsonl"),
                {"time": play["time"], "child": node["id"], "title": title_of(node), "play": play})
    node.pop("check", None)
    if not node.get("goal"):
        node["goal"] = play["goal"]
        node["goal_time"] = play["time"]
    save_node(me.home, node)
    render_memo(me.home, node["id"])
    render_memo(me.home, parent)
    RAN.update(play=play["id"], state=play["state"])
    return None


RAN = {}       # what the running hook learned, for its line in the node's log


def log_run(name, text, started):
    """One line a hook call in <node>/log.jsonl: what ran, for whom, how much it said and how long it took. This
    is what the plugin is measured from."""
    if not RAN.get("home") or not RAN.get("node"):
        return
    row = {"time": now(), "hook": name, "said": len(text or ""), "ms": round((time.time() - started) * 1000),
           "host_in_env": bool(os.environ.get("CLAUDE_CODE_HOST_SESSION_ID"))}
    row.update({k: v for k, v in RAN.items() if k not in ("home", "node")})
    append_line(os.path.join(node_dir(RAN["home"], RAN["node"]), "log.jsonl"), row)


HOOKS = {"arrive": ("SessionStart", h_arrive), "prompt": ("UserPromptSubmit", h_prompt), "exit": ("Stop", h_exit)}


def hook_main(name):
    """A hook never fails a call and says nothing without something to say."""
    try:
        if os.environ.get("P4_PHI") == "0" or name not in HOOKS:
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        event, fn = HOOKS[name]
        started = time.time()
        text = fn(payload)
        log_run(name, text, started)
        if text:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    except Exception:  # noqa: BLE001
        pass
    return 0


# --- the commands ----------------------------------------------------------------------------------------------------

def note_add(home, nid, claim, source, kind="", session=""):
    claim, source = clean(claim), clean(source)
    if len(claim) < 12:
        raise ValueError("a note is a whole sentence")
    if not source:
        raise ValueError("a note needs its source: the file and line, the command, or the measurement that showed it")
    if any(clean(r.get("claim")).lower() == claim.lower() for r in load_notes(home, nid)):
        return False
    append_line(os.path.join(node_dir(home, nid), "notes.jsonl"),
                {"time": now(), "claim": claim[:600], "source": source[:300], "kind": clean(kind), "session": session})
    render_memo(home, nid)
    return True


def reparent(home, nid, new):
    """Move a node under another parent: node.json's parent is rewritten, its latest play is handed to the new
    parent, and the old parent's rollup notes that it left. The app's own nesting does not follow."""
    nid, new = safe_id(nid), safe_id(new)
    node = load_node(home, nid)
    if not node.get("id") or nid == ROOT:
        raise ValueError(f"no node {nid}")
    if new != ROOT:
        ensure_node(home, new)
    if new == nid or nid in line_of(home, new):
        raise ValueError("a node cannot hang under itself or under a node below it")
    old = node.get("parent") or ROOT
    if old == new:
        return False
    node["parent"], node["moved"] = new, {"from": old, "time": now()}
    node.pop("ghosted", None)
    save_node(home, node)
    append_line(os.path.join(node_dir(home, old), "rollup.jsonl"), {"time": now(), "moved": nid, "to": new})
    plays = load_plays(home, nid)
    if plays:
        append_line(os.path.join(node_dir(home, new), "rollup.jsonl"),
                    {"time": now(), "child": nid, "title": title_of(node), "play": plays[-1]})
    for x in (nid, old, new):
        render_memo(home, x)
    return True


def tree_text(home):
    nodes = {}
    for p in glob.glob(os.path.join(home, "phi", "nodes", "*", "node.json")):
        d = read_json(p)
        if d.get("id") and d["id"] != ROOT:
            nodes[d["id"]] = d
    kids = {}
    for n in sorted(nodes.values(), key=lambda n: n.get("created", "")):
        parent = n.get("parent") if n.get("parent") in nodes else ROOT
        kids.setdefault(parent, []).append(n)
    out = []

    def walk(pid, depth):
        for n in kids.get(pid, []):
            plays = load_plays(home, n["id"])
            state = plays[-1].get("state", "open") if plays else "no play yet"
            out.append(f"{'  ' * depth}- {title_of(n)} ({n['id']}): {state}, {len(plays)} play{'s' * (len(plays) != 1)}")
            if depth < 30:
                walk(n["id"], depth + 1)
    walk(ROOT, 0)
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        return hook_main(argv[1] if len(argv) > 1 else "")
    import argparse
    ap = argparse.ArgumentParser(description="phi: the memo on the session tree")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("note", "close", "goal", "memo", "tree", "ghost", "reparent"):
        s = sub.add_parser(name)
        s.add_argument("--p4", default="", help="the store the tree lives in (default: this session's)")
        s.add_argument("--node", default="", help="the node (default: this session's)")
        if name == "note":
            s.add_argument("claim")
            s.add_argument("--source", default="")
            s.add_argument("--kind", default="", help="ruled-out, decision, machine, code")
        if name == "close":
            s.add_argument("--check", required=True, help="what was run or read that showed the goal scored")
        if name == "goal":
            s.add_argument("text")
        if name == "memo":
            s.add_argument("which", nargs="?", default="")
        if name == "reparent":
            s.add_argument("moved")
            s.add_argument("parent")
    a = ap.parse_args(argv)
    me = Me(node=a.node, p4=a.p4)
    if not me.home or not os.path.isdir(me.home):
        print("phi: no store found; pass --p4 <repository>/.claude/p4", file=sys.stderr)
        return 2
    configure(me.home)
    try:
        if a.cmd == "tree":
            print(tree_text(me.home) or "no nodes yet")
            return 0
        if a.cmd == "reparent":
            print("moved" if reparent(me.home, a.moved, a.parent) else "already there")
            return 0
        if a.cmd == "memo":
            nid = safe_id(a.which or me.id)
            render_memo(me.home, nid)
            path = os.path.join(node_dir(me.home, nid), "memo.md")
            if not os.path.exists(path):
                print(f"phi: no node {nid}", file=sys.stderr)
                return 2
            with open(path, encoding="utf-8") as f:
                sys.stdout.write(f.read())
            return 0
        if not me.id:
            print("phi: this is not a session (no session id in the environment); pass --node", file=sys.stderr)
            return 2
        node = ensure_node(me.home, me.id, me.rec, me.cli)
        if a.cmd == "note":
            kept = note_add(me.home, node["id"], a.claim, a.source, a.kind, me.cli)
            print("kept" if kept else "already kept")
        elif a.cmd == "close":
            if len(clean(a.check)) < 8:
                raise ValueError("a check says what was run and what it showed")
            node["check"] = {"text": clean(a.check)[:400], "time": now()}
            save_node(me.home, node)
            print("this turn's play will be kept closed")
        elif a.cmd == "goal":
            goal = cut(a.text.strip(), GOAL_CHARS)
            if len(clean(goal)) < 12:
                raise ValueError("a goal is a whole sentence")
            if node.get("goal"):
                node.setdefault("goals", []).append({"goal": node["goal"], "until": now()})
            node["goal"], node["goal_time"] = goal, now()
            node.pop("steered", None)
            save_node(me.home, node)
            render_memo(me.home, node["id"])
            print("this node's goal is changed; the goal before it is kept in node.json")
        else:
            print(ghost_text(me.home, node, own=True) or "nothing is memoized above this session")
    except ValueError as e:
        print(f"phi: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
