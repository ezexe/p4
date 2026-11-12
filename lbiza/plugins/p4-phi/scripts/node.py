"""node.py: a session's place in the app's session tree, as p4-phi's background and its recall both read it.

Standard library only, and cheap: the recall hook runs it on every message.

A node is one session read at the time of one message (.docs/p4/recall-node.md):

  own   the session's own task: its first request
  up    the tasks of the sessions above it, nearest first, and their notes
  side  the tasks of the other sessions started by the same session

The tree has two sources. `PhiTree` reads phi's files, `phi/sessions/<sessionId>/session.json` and `notes.jsonl`,
which phi keeps for every session it runs in: the live road. `RecordTree` reads the app's session records,
`claude-code-sessions/**/<sessionId>.json`, which name each session's CLI id and the session that started it, and
takes the tasks' words from recall's `tasks.tsv`: the road for messages older than phi.

Only what existed before the message counts: `at(..., when)` drops a task, a note or a session dated after it.
"""

import csv
import glob
import json
import os
import re

CHAIN_MAX = 8            # sessions followed upward
SIDE_MAX = 5             # sibling sessions read
NOTES_MAX = 10           # notes read per session
SAFE = re.compile(r"[^A-Za-z0-9_.-]")


WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STOP = frozenset("""the and for that this with from are was were not but its his her their them they you your our
into onto than then when what which who whom how why where there here have has had been being out off any all each
every one two own same such only also just very more most less over under again once both some none nor too can
will would should could may might must shall per via about after before between while during without within upon
those these ever never always still yet already itself session sessions task""".split())


def words(text):
    """The content words of a text: lower case, three letters or more, not a common word."""
    return {w for w in (m.lower() for m in WORD.findall(str(text or ""))) if len(w) >= 3 and w not in STOP}


def by_overlap(items, task, key=lambda x: x):
    """`items` ordered by how many content words each shares with `task`, most first; ties keep their order. With
    no task the order is kept."""
    want = words(task)
    if not want:
        return list(items)
    scored = [(-len(words(key(x)) & want), k, x) for k, x in enumerate(items)]
    return [x for _, _, x in sorted(scored, key=lambda t: (t[0], t[1]))]


class Node:
    def __init__(self, sid, own="", up=None, notes=None, side=None):
        self.sid = sid
        self.own = own
        self.up = list(up or [])          # [(sessionId, task)], nearest first
        self.notes = list(notes or [])    # [claim]
        self.side = list(side or [])      # [(sessionId, task)]

    def __bool__(self):
        return bool(self.own or self.up or self.notes or self.side)

    def text(self, side=False):
        """The node's words as one text: the own task, the tasks above, the notes, and the siblings' if asked."""
        parts = [self.own] + [t for _, t in self.up] + self.notes + ([t for _, t in self.side] if side else [])
        return "\n".join(p for p in parts if p)

    def __repr__(self):
        return f"Node({self.sid!r}, own={self.own[:40]!r}, up={len(self.up)}, notes={len(self.notes)}, side={len(self.side)})"


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _parent(rec):
    s = rec.get("spawnedFrom")
    if isinstance(s, str):
        try:
            s = json.loads(s)
        except ValueError:
            m = re.search(r"'sessionId':\s*'([^']+)'", s)
            s = {"sessionId": m.group(1)} if m else None
    p = s.get("sessionId") if isinstance(s, dict) else None
    return p or rec.get("forkedFromSessionId") or ""


def _stamp(v):
    """'YYYY-MM-DD HH:MM' from a phi time string or an app epoch in milliseconds; '' when unknown."""
    if isinstance(v, (int, float)) and v > 0:
        import time
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(v / 1000 if v > 1e11 else v))
    return str(v or "")[:16]


class Tree:
    """sessions: {sessionId: {"parent", "cli": [ids], "created", "tasks": [(time, text)], "notes": [(time, text)]}}."""

    def __init__(self):
        self.sessions = {}
        self.by_cli = {}
        self.children = {}

    def add(self, sid, parent="", cli=(), created="", tasks=(), notes=()):
        s = self.sessions.setdefault(sid, {"parent": "", "cli": [], "created": "", "tasks": [], "notes": []})
        s["parent"] = s["parent"] or parent
        s["created"] = s["created"] or created
        for c in cli:
            if c and c not in s["cli"]:
                s["cli"].append(c)
                self.by_cli[c] = sid
                self.by_cli.setdefault(c[:8], sid)
        s["tasks"].extend(t for t in tasks if t[1])
        s["notes"].extend(n for n in notes if n[1])

    def finish(self):
        self.children = {}
        for sid, s in self.sessions.items():
            s["tasks"].sort()
            s["notes"].sort()
            if s["parent"]:
                self.children.setdefault(s["parent"], []).append(sid)
        return self

    def session_of(self, cli_or_sid):
        k = str(cli_or_sid or "")
        if k in self.sessions:
            return k
        return self.by_cli.get(k) or self.by_cli.get(k[:8]) or ""

    def task(self, sid, when=""):
        """The session's own task: its first request dated no later than `when`."""
        for t, text in self.sessions.get(sid, {}).get("tasks", []):
            if not when or not t or t <= when:
                return text
            break
        return ""

    def at(self, cli_or_sid, when=""):
        """The node of a session at `when` ('YYYY-MM-DD HH:MM'; '' for now), or None when the session is unknown."""
        sid = self.session_of(cli_or_sid)
        if not sid:
            return None
        s = self.sessions[sid]
        own = self.task(sid, when)
        up, notes, seen = [], [], {sid}
        p = s["parent"]
        while p and p not in seen and len(up) < CHAIN_MAX:
            seen.add(p)
            ps = self.sessions.get(p)
            if ps is None:
                break
            t = self.task(p, when)
            if t:
                up.append((p, t))
            notes.extend(n for w, n in ps["notes"][-NOTES_MAX:] if not when or not w or w <= when)
            p = ps["parent"]
        notes.extend(n for w, n in s["notes"][-NOTES_MAX:] if not when or not w or w <= when)
        side = []
        for o in self.children.get(s["parent"], []) if s["parent"] else []:
            if o == sid or len(side) >= SIDE_MAX:
                continue
            os_ = self.sessions[o]
            if when and os_["created"] and os_["created"] > when:
                continue
            t = self.task(o, when)
            if t:
                side.append((o, t))
        return Node(sid, own, up, notes, side)


def phi_tree(p4):
    """The tree from phi's files under <p4>/phi/sessions."""
    tree = Tree()
    for path in glob.glob(os.path.join(p4, "phi", "sessions", "*", "session.json")):
        d = _read_json(path)
        sid = d.get("sessionId") or os.path.basename(os.path.dirname(path))
        tasks = [(_stamp(d.get("createdAt")), d.get("task") or "")] if d.get("task") else []
        notes = []
        try:
            with open(os.path.join(os.path.dirname(path), "notes.jsonl"), encoding="utf-8") as f:
                for line in f:
                    try:
                        n = json.loads(line)
                    except ValueError:
                        continue
                    notes.append((_stamp(n.get("time")), str(n.get("claim") or n.get("text") or "")))
        except OSError:
            pass
        tree.add(sid, _parent(d), d.get("cliSessionIds") or [], _stamp(d.get("createdAt")), tasks, notes)
    return tree.finish()


def records_dirs():
    """The folders that may hold the app's session records, likeliest first."""
    home = os.path.expanduser("~")
    out = []
    for base in (os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"),
                 os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"),
                 os.path.join(home, "Library", "Application Support")):
        for d in glob.glob(os.path.join(base, "Claude*", "*", "claude-code-sessions")) + \
                glob.glob(os.path.join(base, "Claude*", "claude-code-sessions")):
            if os.path.isdir(d) and d not in out:
                out.append(d)
    return out


def record_tree(tasks_tsv=None, dirs=None, tree=None):
    """The tree from the app's session records, the tasks' words from recall's tasks.tsv (rows whose `session`
    names a CLI id or its first 8 characters). Added to `tree` when one is given."""
    tree = tree or Tree()
    for d in dirs if dirs is not None else records_dirs():
        for path in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            r = _read_json(path)
            sid = r.get("sessionId")
            if not sid:
                continue
            cli = [r.get("cliSessionId")] + list(r.get("cliSessionIds") or [])
            tree.add(sid, _parent(r), [c for c in cli if c], _stamp(r.get("createdAt")))
    tree.finish()
    if tasks_tsv and os.path.exists(tasks_tsv):
        with open(tasks_tsv, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                sid = tree.session_of(row.get("session") or "")
                if sid and row.get("text"):
                    tree.sessions[sid]["tasks"].append(((row.get("time") or "")[:16], row["text"]))
        for s in tree.sessions.values():
            s["tasks"].sort()
    return tree


def live(p4, cli_session=""):
    """The node of the running session, from phi's files: the session named by CLAUDE_CODE_HOST_SESSION_ID, else
    the one whose CLI ids hold `cli_session`. None when phi keeps no record of it."""
    if not os.path.isdir(os.path.join(p4, "phi", "sessions")):
        return None
    tree = phi_tree(p4)
    host = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
    for k in (host, SAFE.sub("_", host)[:80], cli_session):
        if k and tree.session_of(k):
            return tree.at(k)
    return None
