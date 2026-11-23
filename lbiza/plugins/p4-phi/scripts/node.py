"""node.py: the content words two texts share, and the node each session is: its level and its address.

phi.py imports it whenever it runs. The start background phi.py builds lists the notes of the sessions above and
the last turns of the siblings in the order `by_overlap` gives: the most content words shared with the session's
task first. `level`, `addresses`, `leaves` and `record` give the view `phi.py tree` and `phi.py node` print, from
the store's records alone. node.py uses the standard library; `level` reads controls.py where it can.
"""

import json
import os
import re


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


# --- the node: the level and the address of a session ---------------------------------------------------------------
# The address rule is ezexe/phi's lbiza/phi_rank/tree.py:99-112, written again here and not imported: the top is "1",
# a child is its parent's address with one more "0" for each child before it and then a "1", so no address holds "11".

SHORT = 32                       # the most characters of an address a line of the tree prints whole
CHILDREN = "children.jsonl"      # <session folder>/children.jsonl: one {"id"} line for each session the session started


def parent(a):
    """The address a child's address grew from, None for "1"."""
    return None if a == "1" else a[:-1].rstrip("0")


def child(a, i):
    """The address of the i-th child, i from 1, of the node at address `a`: "101", "1001", "10001" under "1"."""
    return a + "0" * i + "1"


def short(a, places):
    """`a` where it is at most 32 characters, else "1/" and the places joined by "/"."""
    return a if len(a) <= SHORT else "1/" + "/".join(str(p) for p in places)


def _dir(home, sid):
    return os.path.join(home, "phi", "sessions", re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or ""))[:80])


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _rows(path):
    """The rows of a .jsonl file, as phi.read_rows gives them: a line that is not a JSON object is passed over."""
    try:
        with open(path, "rb") as f:
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


def _parent(s):
    sp = s.get("spawnedFrom") if isinstance(s, dict) else None
    return str(sp.get("sessionId") or "") if isinstance(sp, dict) else ""


def top(s, sessions):
    """True where the record has no parent or its parent has no record in the store."""
    above = _parent(s)
    return not above or above not in sessions


def _controlled(s):
    try:
        import controls
        return controls.controlled(s)
    except Exception:                                 # node.py used where controls.py cannot be read
        return [e for e in s.get("controls") or [] if isinstance(e, dict) and e.get("sessionId")]


def level(s, sessions):
    """"puppeteer", "orchestrator" or "worker", from the store's records alone. A top is a puppeteer where it
    controls a session or holds a standing worker, else an orchestrator; any other session is an orchestrator
    where it started sessions, else a worker."""
    if top(s, sessions):
        return "puppeteer" if _controlled(s) or s.get("standingWorker") else "orchestrator"
    sid = s.get("sessionId")
    return "orchestrator" if any(_parent(v) == sid for v in sessions.values()) else "worker"


def ids(home, sid):
    """The ids in <session folder>/children.jsonl, each once, in the order they first stand: a child's place is its
    index here from 1."""
    out = []
    for r in _rows(os.path.join(_dir(home, sid), CHILDREN)):
        c = str(r.get("id") or "")
        if c and c not in out:
            out.append(c)
    return out


def _chain(home, sid, sessions, held):
    """(address, places) of a session, ("", []) where it or a session above it has no place yet. `held` keeps each
    parent's list, read once."""
    up, cur = [], sid
    while cur in sessions and cur not in up:
        up.append(cur)
        if top(sessions[cur], sessions):
            break
        cur = _parent(sessions[cur])
    else:
        return "", []
    address, places = "1", []
    for c in reversed(up[:-1]):
        above = _parent(sessions[c])
        if above not in held:
            held[above] = ids(home, above)
        if c not in held[above]:
            return "", []
        place = held[above].index(c) + 1
        address, places = child(address, place), places + [place]
    return address, places


def addresses(home, sessions):
    """{sid: address}: every top is "1"; any other session is its parent's address grown by its place in its
    parent's list. One not yet in that list has no address, and neither has anything under it."""
    held, out = {}, {}
    for sid in sessions:
        a, _ = _chain(home, sid, sessions, held)
        if a:
            out[sid] = a
    return out


def _tasks(plan):
    for st in plan.get("steps") or []:
        if isinstance(st, dict):
            yield from (st.get("tasks") or [])
    yield from plan.get("loose") or []


def _terminals(folder):
    """The entries of <session folder>/terminals.json, a list."""
    try:
        with open(os.path.join(folder, "terminals.json"), encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return []
    return [t for t in rows if isinstance(t, dict) and t.get("name")] if isinstance(rows, list) else []


def leaves(home, sid):
    """What works under a session with no session folder, in this order: its subagents, its teammates, its
    terminal sessions of upkeep.json and those of terminals.json, each {level: "subagent" | "teammate" |
    "terminal", name, state}."""
    d = _dir(home, sid)
    out = []
    for t in _tasks(_json(os.path.join(d, "plan.json"))):
        if isinstance(t, dict) and t.get("agent"):
            out.append({"level": "subagent", "name": str(t.get("stepText") or t.get("id") or ""),
                        "state": str(t.get("status") or "")})
    rows = _json(os.path.join(d, "team.json")).get("teammates")
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("name"):
            out.append({"level": "teammate", "name": str(r["name"]), "state": str(r.get("state") or "")})
    for t in _json(os.path.join(d, "upkeep.json")).get("terminals") or []:
        if isinstance(t, dict) and t.get("name"):
            out.append({"level": "terminal", "name": str(t["name"]),
                        "state": "removed" if t.get("removed") else "started"})
    for t in _terminals(d):
        report = str(t.get("report") or "")
        out.append({"level": "terminal", "name": str(t["name"]),
                    "state": "reported" if t.get("kind") == "worker" and report and os.path.isfile(report)
                    else "started"})
    return out


def record(home, sid, sessions):
    """{id, title, level, parent, address, places, paths, leaves} of a session; `paths` is its shard, else its
    fileSet."""
    s = sessions.get(sid) or {}
    address, places = _chain(home, sid, sessions, {})
    paths = s.get("shard") or s.get("fileSet") or []
    title = s.get("title") or " ".join(str(s.get("task") or "").split())[:60] or str(sid)[:14]
    return {"id": sid, "title": title, "level": level(s, sessions) if s else "",
            "parent": "" if top(s, sessions) else _parent(s), "address": address, "places": places,
            "paths": [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else [], "leaves": leaves(home, sid)}
