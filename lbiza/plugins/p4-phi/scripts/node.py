"""node.py: the content words two texts share, and the node each session is: its level and its address.

phi.py imports it whenever it runs. The start background phi.py builds lists the notes of the sessions above and
the last turns of the siblings in the order `by_overlap` gives: the most content words shared with the session's
task first. `level`, `addresses`, `leaves` and `record` give the view `phi.py tree` and `phi.py node` print, from
the store's records and the folders of its nodes. node.py uses the standard library and relay.py, which imports no
node; `level` reads controls.py where it can.
"""

import json
import os
import re

import relay


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
# A session's address is that of the store that holds its folder, read from the store's path under the root store:
# the i-th child of a store is `.claude` i times and then `p4` under it, relay.store_of.

SHORT = 32                       # the most characters of an address a line of the tree prints whole


def parent(a):
    """The address a child's address grew from, None for "1"."""
    return None if a == "1" else a[:-1].rstrip("0")


def child(a, i):
    """The address of the i-th child, i from 1, of the node at address `a`: "101", "1001", "10001" under "1"."""
    return a + "0" * i + "1"


def short(a, places):
    """`a` where it is at most 32 characters, else "1/" and the places joined by "/"."""
    return a if len(a) <= SHORT else "1/" + "/".join(str(p) for p in places)


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _parent(s):
    sp = s.get("spawnedFrom") if isinstance(s, dict) else None
    return str(sp.get("sessionId") or "") if isinstance(sp, dict) else ""


def top(s, sessions):
    """True where the record has no parent or its parent has no record in the store."""
    above = _parent(s)
    return not above or above not in sessions


def level(s, sessions):
    """"puppeteer", "orchestrator" or "worker", from the store's records alone. A top is a puppeteer where it
    started a session, else an orchestrator; any other session is an orchestrator."""
    sid = s.get("sessionId")
    if top(s, sessions):
        return "puppeteer" if any(_parent(v) == sid for v in sessions.values()) else "orchestrator"
    return "orchestrator"


def place_of(home, store):
    """(address, places) of a store from its path under the root store `home`: ("1", []) for the root, and
    child(a, i) for each step of i `.claude` folders and a `p4`. A path that is no store's under `home` is the root's."""
    try:
        rel = os.path.relpath(store, home)
    except ValueError:
        return "1", []
    parts = [] if rel == "." else rel.replace("\\", "/").split("/")
    address, places, run = "1", [], 0
    for part in parts:
        if part == ".claude":
            run += 1
        elif part == "p4" and run:
            address, places, run = child(address, run), places + [run], 0
        else:
            return "1", []
    return (address, places) if not run else ("1", [])


def _store(home, sid):
    """The store that holds a session's folder: its node's, else the root."""
    return relay.nodes(home).get(relay._safe(sid)) or home


def addresses(home, sessions):
    """{sid: address}: the address of the store that holds each session's folder, so every flat session is "1" and
    a started session's address is its node's. A reparented session keeps its store, so its address can differ
    from the line it is printed under."""
    return {sid: place_of(home, _store(home, sid))[0] for sid in sessions}


def _tasks(plan):
    for st in plan.get("steps") or []:
        if isinstance(st, dict):
            yield from (st.get("tasks") or [])
    yield from plan.get("loose") or []


def leaves(home, sid):
    """What works under a session with no session folder, in this order: its subagents, its teammates, its
    terminal sessions of upkeep.json, and the reading teams and terminal workers whose node names it as parent,
    each {level: "subagent" | "teammate" | "terminal", name, state}, and a node's with its `address`."""
    d = relay._dir(home, sid)
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
    safe = relay._safe(sid)
    for name, store in relay.nodes(home).items() if safe else ():
        n = relay.node_record(home, name)
        if n.get("parent") != safe or n.get("kind") not in ("reader", "worker"):
            continue
        report = os.path.join(store, "phi", f"report-{name}.md")
        out.append({"level": "terminal", "name": name, "address": place_of(home, store)[0],
                    "state": "reported" if n["kind"] == "worker" and os.path.isfile(report) else "started"})
    return out


def record(home, sid, sessions):
    """{id, title, level, parent, address, places, paths, leaves} of a session; `paths` is its shard, else its
    fileSet."""
    s = sessions.get(sid) or {}
    address, places = place_of(home, _store(home, sid))
    paths = relay.paths_of(s)
    title = s.get("title") or " ".join(str(s.get("task") or "").split())[:60] or str(sid)[:14]
    return {"id": sid, "title": title, "level": level(s, sessions) if s else "",
            "parent": "" if top(s, sessions) else _parent(s), "address": address, "places": places,
            "paths": [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else [], "leaves": leaves(home, sid)}
