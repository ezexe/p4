"""asks.py: the request ledger of a puppeteer, one row per request of ezexe's, kept beside its board.

A puppeteer reacts to each of ezexe's messages as it comes; the ledger keeps what became of each. A row holds the
request's topic, the session that holds it by full title and id, its state and what waits on ezexe. The rows are
appended to <puppeteer folder>/asks.jsonl and folded by id; asks.md is the page, rewritten when it changes, and a
short line naming it is handed beside each of the puppeteer's messages.

  opened   a message of ezexe's to the puppeteer that asks for work, a request that is not a quick thing, opens a
           row; a status question opens none.
  holder   the session the puppeteer sends the request to with SendMessage in that turn, read at the send by
           phi.h_go_guard; or an orchestrator newly under control by the puppeteer's next message, started for it.
  state    read through the address book, book.py, at each render: open with no holder; routed or started; working
           while the holder is inside a turn; reported once it ended a turn since it took the request; done once
           that turn was shown done; closed once it left the book.
  waits    the last line of the puppeteer's turn on a request with no holder, when it ended on a question for ezexe,
           set once per turn, until ezexe answers with a quick message.

controls.PHI is phi.py, set when phi.py is imported; every function here is called from phi.py.
"""

import hashlib
import json
import os
import re
import time

import book
import controls
import issues
import relay

LOG = "asks.jsonl"
PAGE = "asks.md"
TOPIC_CHARS = 140
SHOWN = 6                        # rows named in the line beside a message; the rest are on the page
ASKS = re.compile(r"\b(?:publish|push|merg|releas|deploy|archiv|start|run|send|install)\w*\b", re.I)
QUESTION = re.compile(r"\?\s*$")


def _phi():
    return controls.PHI


def log_path(home, sid):
    return os.path.join(relay._dir(home, sid), LOG)


def page_path(home, sid):
    return os.path.join(relay._dir(home, sid), PAGE).replace("\\", "/")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _key(text):
    return hashlib.sha1(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()[:12]


def _add(home, sid, row):
    row = dict(row, time=_now())
    path = log_path(home, sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rows(home, sid):
    """The requests, oldest first, each folded from its rows by id."""
    out = {}
    for r in relay._rows(log_path(home, sid)):
        rid = r.get("id")
        if not rid:
            continue
        if r.get("kind") == "opened":
            out[rid] = {"id": rid, "topic": r.get("topic", ""), "said": r.get("said", ""),
                        "opened": r.get("time", ""), "holder": "", "home": "", "base": 0, "how": "",
                        "waits": "", "asked": []}
        elif rid in out:
            if r.get("kind") == "holder" and not out[rid]["holder"]:
                out[rid].update(holder=r.get("holder", ""), home=r.get("home", ""), base=r.get("base") or 0,
                                how=r.get("how", ""), waits="")
            elif r.get("kind") == "waits":
                out[rid]["waits"] = r.get("waits", "")
                if r.get("turn"):
                    out[rid]["asked"].append(r["turn"])
    return list(out.values())


def request(text):
    """True when a message of ezexe's asks for work: a change, or an act such as a publish, a push or a start, in more
    than a quick thing's words. A question about where things stand asks for none."""
    text = str(text or "")
    if quick(text):
        return False
    return issues.writing(text) or bool(ASKS.search(issues.PATH_WORDS.sub(" ", text)))


def quick(text):
    return len(_phi().puppeteer.words(text)) < _phi().puppeteer.QUICK_WORDS


def _state_path(home, sid):
    return os.path.join(relay._dir(home, sid), "asks.json")


def _turns(home, sid):
    return len(relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl"))) if home and sid else 0


def _hold(home, sid, rid, target, store, how):
    """A row takes its holder, with the count of the holder's turns so far, which tells a later report."""
    _add(home, sid, {"kind": "holder", "id": rid, "holder": target, "home": store, "how": how,
                     "base": _turns(store, target)})


# --- the hooks ---------------------------------------------------------------------------------------------------------

def on_message(home, s, req, last_turn=None):
    """At each message of a puppeteer, before its other lines. First what the turn before did: an orchestrator newly
    under control since then was started for the row that turn opened, and a turn that answered a row with no
    holder and ended on a question leaves that row waiting on ezexe, once per turn. Then this message: a quick one
    from ezexe answers the row that waits, and a request opens a row, which this turn's sends take as theirs.
    `req` is ezexe's message, '' for any other. Returns the open row's id, '' for none."""
    sid = s["sessionId"]
    state = relay._read_json(_state_path(home, sid))
    now = state.get("now") or ""
    have = rows(home, sid)
    ctl = {e["sessionId"]: e.get("store") or home for e in controls.controlled(s)}
    if "known" in state:
        for k in [k for k in ctl if k not in state["known"]]:
            if now and any(r["id"] == now and not r["holder"] for r in have):
                _hold(home, sid, now, k, ctl[k], "started")
                have = rows(home, sid)
    state["known"] = sorted(ctl)
    t = last_turn if isinstance(last_turn, dict) else {}
    report = str(t.get("report") or "").strip()
    turn = str(t.get("id") or "")
    if report and QUESTION.search(report):
        said = _key(t.get("prompt"))
        for r in have:
            if r["said"] == said and not r["holder"] and turn not in r["asked"]:
                _add(home, sid, {"kind": "waits", "id": r["id"], "turn": turn,
                                 "waits": report.rsplit("\n", 1)[-1][-300:]})
    have = rows(home, sid)
    now = ""
    if req and quick(req):
        waiting = [r for r in have if r["waits"]]
        if waiting:
            _add(home, sid, {"kind": "waits", "id": waiting[-1]["id"], "waits": ""})
            now = waiting[-1]["id"]
    elif req and request(req):
        key = _key(req)
        if not any(r["said"] == key for r in have):
            now = f"ask-{len(have) + 1}"
            topic = _phi().cut(_phi().clean(req.split("\n", 1)[0]), TOPIC_CHARS)
            _add(home, sid, {"kind": "opened", "id": now, "topic": topic, "said": key})
    state["now"] = now
    relay._write_json(_state_path(home, sid), state)
    return now


def on_send(home, s, target):
    """At the puppeteer's SendMessage: the row its turn opened takes the target as its holder."""
    sid = s["sessionId"]
    target = _phi().safe_id(target) if target else ""
    now = relay._read_json(_state_path(home, sid)).get("now") or ""
    if not now or not target or target == sid:
        return
    if any(r["id"] == now and not r["holder"] for r in rows(home, sid)):
        store = next((e.get("store") or home for e in controls.controlled(s) if e["sessionId"] == target), home)
        _hold(home, sid, now, target, store, "routed")


# --- the page ----------------------------------------------------------------------------------------------------------

def state_of(r, entries):
    """A row's state, read from its holder's entry in the address book and the turns it ended since it took the
    request."""
    if r["waits"]:
        return "waits on ezexe"
    k = r["holder"]
    if not k:
        return "open"
    e = entries.get(k)
    if not e:
        return "closed"
    turns = relay._rows(os.path.join(relay._dir(e["home"], k), "turns.jsonl"))
    if len(turns) > r["base"] and turns[-1].get("done"):
        return "done"
    if _phi().puppeteer.working(e["home"], k):
        return "working"
    if len(turns) > r["base"]:
        return "reported"
    return r["how"] or "routed"


def render(home, s, store=""):
    """asks.md, rewritten when it changed, and the rows with their states and holders' titles."""
    sid = s["sessionId"]
    have = rows(home, sid)
    entries = book.entries(home, sid, store) if have else {}
    out = []
    for r in have:
        st = state_of(r, entries)
        k = r["holder"]
        title = (entries[k]["title"] if k in entries else book.title(k)) if k else ""
        out.append(dict(r, state=st, title=title))
    lines = [f"# Requests of ezexe's to \"{book.title(sid, s)}\" `{sid}`", "",
             "Rewritten by p4-phi's hooks, never by hand: one row per request of ezexe's, with the session that "
             "holds it, its state and what waits on ezexe.", ""]
    for r in out:
        who = f"held by \"{r['title']}\" `{r['holder']}`" if r["holder"] else "held by no session yet"
        state = f"{r['state']}: {r['waits']}" if r["waits"] else r["state"]
        lines.append(f"- {r['id']}, {r['opened'][:16]}: {r['topic']} | {who} | {state}")
    if not out:
        lines.append("None yet.")
    text = "\n".join(lines) + "\n"
    path = page_path(home, sid)
    try:
        with open(path, encoding="utf-8") as f:
            same = f.read() == text
    except OSError:
        same = False
    if not same:
        _phi().write_atomic(path, text)
    return out


def line(home, s, store=""):
    """The short form beside a puppeteer's message: the counts by state, the rows that wait on ezexe or have no
    holder, and the page; '' with no rows."""
    out = render(home, s, store)
    if not out:
        return ""
    counts = {}
    for r in out:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    head = ", ".join(f"{n} {st}" for st, n in sorted(counts.items(), key=lambda x: -x[1]))
    note = [r for r in out if r["state"] in ("waits on ezexe", "open")][-SHOWN:]
    text = (f"phi (p4-phi): ezexe's requests to this puppeteer, {len(out)} in all: {head}. Whole on "
            f"{page_path(home, s['sessionId'])}.")
    if any(r["waits"] for r in note):
        text += (" A request that waits on ezexe is put to it as the question of this turn's `mcp__ccd_turn__wrap_up`,"
                 " with buttons that answer it.")
    if note:
        text += "\n" + "\n".join(f"- {r['id']}: {r['topic']} | {r['state']}"
                                 + (f": {r['waits']}" if r["waits"] else "") for r in note)
    return text
