"""asks.py: the request ledger of a puppeteer, one row per request of ezexe's, kept beside its board.

A puppeteer reacts to each of ezexe's messages as it comes; the ledger keeps what became of each. A row holds the
request's topic, the session that holds it by full title and id, its state and what waits on ezexe. The rows are
appended to <puppeteer folder>/asks.jsonl, folded by id and compacted in steps as the file grows; asks.md is the
page, rewritten when it changes, and a short line naming it is handed beside each of the puppeteer's messages.

  opened   a message of ezexe's that asks for work opens a row: a message the app marks as another session's, a
           question and a quick answer open none, and phi.py hands only ezexe's own messages here. The topic is a
           short phrase of at most TOPIC_CHARS, never a run of ezexe's message.
  holder   the session the puppeteer sends a request to with SendMessage, read at the send by phi.h_go_guard, or an
           orchestrator newly under its control: the open row whose topic their own words share, else, for a send to
           a controlled session or a start, the row the turn works on.
  state    open until the row's next message reads the turn on it: it waits on ezexe when that turn ended on a
           question, is answered when the turn ended without one, and is carried when no turn ended before the next
           message. A held row is routed or started, working while the holder is inside a turn, reported once the
           holder ended a turn since it took the request, and done for good once one of those turns was shown done;
           closed for good once the holder left the address book, archived or no longer live, with no such turn.
  waits    the last line of that turn, until ezexe's next message, which answers the row it names or else the latest.

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
TOPIC_CHARS = 60
SHOWN = 6                        # rows named in the line beside a message; the rest are on the page
SHARED = 2                       # content words a send's or a start's text shares with a row's topic, to hold it
KEEP_S = 24 * 3600               # a finished row stays on the page this long
COMPACT = 400                    # rows asks.jsonl grows by between two compactions
ASKS = re.compile(r"\b(?:publish|push|merg|releas|deploy|archiv|start|run|send|install)\w*\b", re.I)
QUESTION = re.compile(r"\?\s*$")
ASKING = re.compile(r"^\W*(?:where|what|when|why|how|who|which|whether|is|are|was|were|has|have|had|does|do|did|can|"
                    r"could|should|would|will)\b", re.I)
ROW_ID = re.compile(r"\bask-(\d+)\b")
FINISHED = ("done", "closed", "answered", "carried")


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
    row = dict(row, time=row.get("time") or _now())
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
        kind = r.get("kind")
        if kind == "opened":
            out[rid] = {"id": rid, "topic": r.get("topic", ""), "said": r.get("said", ""),
                        "opened": r.get("time", ""), "turnBefore": r.get("turnBefore", ""), "holder": "",
                        "home": "", "base": 0, "how": "", "routed": "", "waits": "", "asked": [], "end": "",
                        "ended": ""}
            continue
        if rid not in out:
            continue
        if kind == "holder" and not out[rid]["holder"]:
            out[rid].update(holder=r.get("holder", ""), home=r.get("home", ""), base=r.get("base") or 0,
                            how=r.get("how", ""), waits="", routed=r.get("time", ""), end="", ended="")
        elif kind == "waits":
            out[rid]["waits"] = r.get("waits", "")
            if r.get("turn"):
                out[rid]["asked"].append(r["turn"])
        elif kind == "end":                        # answered, carried or done: kept, never read again
            out[rid].update(end=r.get("end", ""), ended=r.get("time", ""))
        elif kind == "folded":                     # a compacted row: every field as it stood
            out[rid].update({k: v for k, v in r.items() if k not in ("id", "kind", "time")})
    return list(out.values())


def _compact(home, sid, state):
    """asks.jsonl written again as two rows per request, once it has grown by COMPACT rows since the last time."""
    path = log_path(home, sid)
    try:
        with open(path, "rb") as f:
            n = f.read().count(b"\n")
    except OSError:
        return
    if n <= int(state.get("compactedAt") or 0) + COMPACT:
        return
    lines = []
    for r in rows(home, sid):
        lines.append({"kind": "opened", "id": r["id"], "topic": r["topic"], "said": r["said"], "time": r["opened"],
                      "turnBefore": r["turnBefore"]})
        lines.append({"kind": "folded", "id": r["id"], "time": _now(),
                      **{k: r[k] for k in ("holder", "home", "base", "how", "routed", "waits", "asked", "end",
                                           "ended")}})
    _phi().write_atomic(path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    state["compactedAt"] = len(lines)


def words(text):
    return _phi().puppeteer.words(text)


def quick(text):
    return len(words(text)) < _phi().puppeteer.QUICK_WORDS


def question(text):
    """True for a message that asks where things stand rather than for work."""
    first = " ".join(str(text or "").split())
    return bool(QUESTION.search(first) or ASKING.match(first))


def request(text):
    """True when a message of ezexe's asks for work: a change, or an act such as a publish, a push or a start, in more
    than a quick thing's words, and not a question."""
    text = str(text or "")
    if quick(text) or question(text):
        return False
    return issues.writing(text) or bool(ASKS.search(issues.PATH_WORDS.sub(" ", text)))


def topic_of(text):
    """A short phrase for a request: its first line cut at a clause, at most TOPIC_CHARS."""
    first = _phi().clean(str(text or "").strip().split("\n", 1)[0])
    return relay.clause_cut(first, TOPIC_CHARS)


def _state_path(home, sid):
    return os.path.join(relay._dir(home, sid), "asks.json")


def _turn_lines(home, sid):
    """A session's turns.jsonl as its raw lines, counted without parsing."""
    try:
        with open(os.path.join(relay._dir(home, sid), "turns.jsonl"), "rb") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _hold(home, sid, rid, target, store, how):
    """A row takes its holder, with the count of the holder's turns so far, which tells a later report."""
    _add(home, sid, {"kind": "holder", "id": rid, "holder": target, "home": store, "how": how,
                     "base": len(_turn_lines(store, target))})


def _credit(have, text):
    """The row with no holder whose topic shares the most content words with `text`, at least SHARED; None. A row the
    puppeteer answered itself, or one finished past KEEP_S, takes no holder."""
    said = words(text)
    best, score = None, SHARED - 1
    for r in have:
        if r["holder"] or r["end"] == "answered" or r["end"] and _old(r):
            continue
        n = len(said & words(r["topic"]))
        if n > score:
            best, score = r, n
    return best


# --- the hooks ---------------------------------------------------------------------------------------------------------

def on_message(home, s, req, last_turn=None):
    """At each message of a puppeteer, before its other lines. First what came since the message before: an
    orchestrator newly under its control holds the row its title and task share words with, else the row that
    message worked on; that row, still with no holder and no wait, waits on ezexe when a turn since ended on a
    question, is answered when a turn ended without one, and is carried when none ended. Then this message, `req`,
    ezexe's own, '' for any other: it answers the row that waits, the one it names or else the latest, and a request
    opens a row. Returns the row this turn works on, '' for none."""
    sid = s["sessionId"]
    state = relay._read_json(_state_path(home, sid))
    now = state.get("now") or ""
    have = rows(home, sid)
    t = last_turn if isinstance(last_turn, dict) else {}
    turn = str(t.get("id") or "")
    ctl = {e["sessionId"]: e.get("store") or home for e in controls.controlled(s)}
    if "known" in state:
        for k in [k for k in ctl if k not in state["known"]]:
            ks = relay._session(ctl[k], k) if ctl[k] else {}
            r = _credit(have, f"{book.title(k, ks)} {ks.get('task') or ''}") or next(
                (x for x in have if x["id"] == now and not x["holder"]), None)
            if r:                                  # credited by its words, else a start of that message's turn
                _hold(home, sid, r["id"], k, ctl[k], "started")
                r["holder"] = k
    state["known"] = sorted(ctl)
    mine = next((r for r in have if r["id"] == now), None)
    if mine and not mine["holder"] and not mine["waits"] and not mine["end"]:
        if turn and turn != mine["turnBefore"] and turn not in mine["asked"]:
            report = str(t.get("report") or "").strip()
            if report and QUESTION.search(report):
                _add(home, sid, {"kind": "waits", "id": now, "turn": turn,
                                 "waits": report.rsplit("\n", 1)[-1][-300:]})
            else:
                _add(home, sid, {"kind": "end", "id": now, "end": "answered"})
        else:
            _add(home, sid, {"kind": "end", "id": now, "end": "carried"})   # ezexe moved on before its turn ended
    have = rows(home, sid)
    now = ""
    if req:
        waiting = [r for r in have if r["waits"]]
        hit = None
        if waiting:
            named = ROW_ID.search(req)
            hit = next((r for r in waiting if named and r["id"] == f"ask-{named.group(1)}"), None) \
                or next((r for r in reversed(waiting) if len(words(req) & words(r["topic"])) >= SHARED), None) \
                or waiting[-1]
        elif request(req) and not any(r["said"] == _key(req) for r in have):
            now = f"ask-{len(have) + 1}"
            _add(home, sid, {"kind": "opened", "id": now, "topic": topic_of(req), "said": _key(req),
                             "turnBefore": turn})
        if hit:                                    # ezexe's answer: the row works on again from this message
            _add(home, sid, {"kind": "waits", "id": hit["id"], "waits": ""})
            _add(home, sid, {"kind": "opened", "id": hit["id"], "topic": hit["topic"], "said": hit["said"],
                             "time": hit["opened"], "turnBefore": turn})
            now = hit["id"]
    state["now"] = now
    _compact(home, sid, state)
    relay._write_json(_state_path(home, sid), state)
    return now


def on_send(home, s, target, message=""):
    """At the puppeteer's SendMessage: the row whose topic the message's own words share takes the target as its
    holder; failing that, a send to a controlled session holds the row this turn works on. A message on no
    request's topic to a session it does not control, such as its standing worker, holds none."""
    sid = s["sessionId"]
    target = _phi().safe_id(target) if target else ""
    if not target or target == sid:
        return
    have = rows(home, sid)
    ctl = {e["sessionId"]: e.get("store") or home for e in controls.controlled(s)}
    r = _credit(have, message)
    if not r and target in ctl:
        now = relay._read_json(_state_path(home, sid)).get("now") or ""
        r = next((x for x in have if x["id"] == now and not x["holder"]), None)
    if r:
        _hold(home, sid, r["id"], target, ctl.get(target, home), "routed")


# --- the page ----------------------------------------------------------------------------------------------------------

def state_of(home, sid, r, entries, seen):
    """A row's state, read from its holder's entry in the address book and the turns it ended since it took the
    request. A done, and a holder gone from the book, are kept on the row, so it closes for good. `seen` keeps each
    holder's turn lines and whether it is working, read once per render."""
    if r["waits"]:
        return "waits on ezexe"
    if r["end"]:
        return r["end"]
    k = r["holder"]
    if not k:
        return "open"
    e = entries.get(k)
    where = e["home"] if e else (r["home"] or home)
    if k not in seen:
        seen[k] = (_turn_lines(where, k), bool(e) and _phi().puppeteer.working(where, k))
    lines, working = seen[k]
    since = lines[r["base"]:]
    for raw in since:                              # only the turns since the holder took the request are parsed
        try:
            if json.loads(raw).get("done"):
                _add(home, sid, {"kind": "end", "id": r["id"], "end": "done"})
                return "done"
        except ValueError:
            continue
    if not e:
        ks = relay._session(where, k) if where else {}
        if ks.get("sessionId") and controls.out_of_tree(ks):
            _add(home, sid, {"kind": "end", "id": r["id"], "end": "closed"})
        return "closed"                            # one no store holds stays closed until it leaves the page
    if working:
        return "working"
    return "reported" if since else (r["how"] or "routed")


def _old(r):
    """True for a finished row past KEEP_S since it ended."""
    when = r.get("ended") or r.get("routed") or r.get("opened") or ""
    try:
        return time.time() - time.mktime(time.strptime(when[:19], "%Y-%m-%d %H:%M:%S")) > KEEP_S
    except ValueError:
        return False


def render(home, s, store=""):
    """asks.md, rewritten when it changed, and the rows on it with their states and holders' titles: every row but
    a finished one past a day."""
    sid = s["sessionId"]
    have = rows(home, sid)
    live = [r for r in have if not (r["end"] and _old(r))]
    entries = book.entries(home, sid, store) if any(r["holder"] and not r["end"] for r in live) else {}
    seen, out = {}, []
    for r in live:
        st = state_of(home, sid, r, entries, seen)
        if st in FINISHED and _old(r):
            continue
        k = r["holder"]
        title = (entries[k]["title"] if k in entries else book.title(k)) if k else ""
        out.append(dict(r, state=st, title=title))
    lines = [f"# Requests of ezexe's to \"{book.title(sid, s)}\" `{sid}`", "",
             "Rewritten by p4-phi's hooks, never by hand: one row per request of ezexe's, with the session that "
             "holds it, its state and what waits on ezexe. A finished row leaves the page a day after.", ""]
    for r in out:
        who = f"held by \"{r['title']}\" `{r['holder']}`" if r["holder"] else "held by no session yet"
        state = f"{r['state']}: {r['waits']}" if r["waits"] else r["state"]
        lines.append(f"- {r['id']}, {r['opened'][:16]}: {r['topic']} | {who} | {state}")
    if not out:
        lines.append("None open.")
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
    holder, and the page; '' with no rows on it."""
    out = render(home, s, store)
    if not out:
        return ""
    counts = {}
    for r in out:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    head = ", ".join(f"{n} {st}" for st, n in sorted(counts.items(), key=lambda x: -x[1]))
    note = [r for r in out if r["state"] in ("waits on ezexe", "open")][-SHOWN:]
    text = (f"phi (p4-phi): ezexe's requests to this puppeteer, {len(out)} on the page: {head}. Whole on "
            f"{page_path(home, s['sessionId'])}.")
    if any(r["waits"] for r in note):
        text += (" A request that waits on ezexe is put to it as the question of this turn's `mcp__ccd_turn__wrap_up`,"
                 " with buttons that answer it.")
    if note:
        text += "\n" + "\n".join(f"- {r['id']}: {r['topic']} | {r['state']}"
                                 + (f": {r['waits']}" if r["waits"] else "") for r in note)
    return text
