"""asks.py: the request ledger of a puppeteer, one row per request of ezexe's, kept beside its board.

A puppeteer reacts to each of ezexe's messages as it comes; the ledger keeps what became of each. A row holds the
request's topic, the session that holds it by full title and id, its state and what waits on ezexe. The rows are
appended to <puppeteer folder>/asks.jsonl, folded by id and compacted in steps as the file grows; asks.md is the
page, rewritten when it changes, and a short line naming it is handed beside each of the puppeteer's messages.

  opened   a message of ezexe's that holds a request opens a row, whatever its length and also while another row
           waits on ezexe: a work word, outside a status question, past a reply's first words and a row's id. A
           message the app marks as another session's opens none, and phi.py hands only ezexe's own messages here.
           The topic is a short phrase of at most TOPIC_CHARS, never a run of ezexe's message. The same words again
           join their row while it is live, and open a new row once it is finished or on another day.
  holder   the session the puppeteer sends a request to with SendMessage, read at the send by phi.h_go_guard, or an
           orchestrator newly under its control: the open row whose topic their own words share, else, for a send to
           a controlled session or a start, the row the turn works on. Its turns are counted in its own store, found
           from the app's record when it is not a controlled session; when no store is found, only its turns ended
           after the row took it count, read by their exact times.
  state    open until the row's next message reads the turn on it: it waits on ezexe when that turn ended on a
           question or offered ezexe buttons with mcp__ccd_turn__wrap_up, and is answered when the turn ended without
           either. It is carried when ezexe's next message comes before any turn ended; another session's message,
           which can come inside the turn, carries nothing. A held row is routed or started, working while the holder
           is inside a turn, reported once the holder ended a turn since it took the request, and done for good once
           one of those turns was shown done. A holder the address book leaves out is read from its own store. It is
           closed for good once the holder is archived or no longer live with no such turn. A held row whose holder
           is not inside a turn and ended none for KEEP_S ends as it stands: reported once it reported, else carried.
           A row shows a finished state only with its end kept.
  waits    the last line of that turn, or the question its buttons answer, with their labels, until a message of
           ezexe's answers it: a button's label, the row's id, a reply such as "yes, push it" or "go ahead", or any
           other that holds no request and is no question. A reply answers the waiting row whose topic it shares
           SHARED words with, else the latest. What follows a reply's first words or a row's id, when it asks for
           work on another topic in SHARED words of its own, opens a row of its own; a reply then answers the wait as
           well only when that request is a quick thing's words, and a row's id always does. A question of ezexe's
           leaves the wait.

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
ASKS = re.compile(r"\b(?:publish|push|merg|releas|deploy|archiv|start|run|send|install|sync|land|ship)\w*\b", re.I)
QUESTION = re.compile(r"\?\s*$")
# a question of where things stand; "can you" or "would you" asks for work in a question's form, and "do" or "have"
# opens a request as often as a question
STATUS = re.compile(r"^\W*(?:where|what|when|why|how|who|which|whether|is|are|was|were|has|had|does|did)\b",
                    re.I)
ROW_ID = re.compile(r"\bask-(\d+)\b")
# a reply to the question a row waits on: its first words say yes, no, go or wait
REPLY = re.compile(r"^\W*(?:yes|yeah|yep|no|nope|ok|okay|sure|fine|agreed|approved|go ahead|go|do it|wait|hold|"
                   r"not yet|don't|do not)\b", re.I)
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
    """A request's key: its words and its day, so the same request on a later day opens a row of its own."""
    said = time.strftime("%Y-%m-%d") + " " + " ".join(str(text or "").split())
    return hashlib.sha1(said.encode("utf-8")).hexdigest()[:12]


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
                        "home": "", "base": 0, "how": "", "routed": "", "at": "", "waits": "", "offered": [],
                        "asked": [], "end": "", "ended": ""}
            continue
        if rid not in out:
            continue
        if kind == "holder" and not out[rid]["holder"]:
            out[rid].update(holder=r.get("holder", ""), home=r.get("home", ""), base=r.get("base") or 0,
                            how=r.get("how", ""), waits="", routed=r.get("time", ""), at=r.get("at", ""), end="",
                            ended="")
        elif kind == "waits":
            out[rid]["waits"] = r.get("waits", "")
            out[rid]["offered"] = [x for x in r.get("offered") or [] if isinstance(x, str)]
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
                      **{k: r[k] for k in ("holder", "home", "base", "how", "routed", "at", "waits", "offered",
                                           "asked", "end", "ended")}})
    _phi().write_atomic(path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
    state["compactedAt"] = len(lines)


def words(text):
    return _phi().puppeteer.words(text)


def quick(text):
    """True for a message of fewer content words than a quick thing has, such as "push it"."""
    return len(words(text)) < _phi().puppeteer.QUICK_WORDS


def _label(text):
    return " ".join(re.sub(r"[^\w\s']", " ", str(text or "").lower()).split())


def _rest(text):
    """A message past the ids of rows it names and a reply's first words: what it asks besides its answer."""
    rest = ROW_ID.sub(" ", str(text or ""))
    m = REPLY.match(rest)
    return (rest[m.end():] if m else rest).strip(" \t\n,.;:!-")


def asking(text):
    """True for a question of ezexe's that is no request: one that opens with a question word, as "where does it
    stand", or ends on a question mark."""
    first = " ".join(str(text or "").split())
    return bool(STATUS.match(first) or QUESTION.search(first))


def request(text):
    """True when a message of ezexe's asks for work: any message with a work word, a change or an act such as a
    publish, a push or a start, that is not a status question such as "where does it stand" or "did it land"."""
    text = str(text or "")
    if STATUS.match(" ".join(text.split())):
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
    """A row takes its holder, with the count of the holder's turns so far in its own store, which tells a later
    report. With no folder of the holder's in `store`, the count is -1, and only its turns after this one count."""
    known = bool(store) and os.path.isdir(relay._dir(store, target))
    _add(home, sid, {"kind": "holder", "id": rid, "holder": target, "home": store if known else "", "how": how,
                     "base": len(_turn_lines(store, target)) if known else -1, "at": _phi().now_exact()})


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
    message worked on; each row that message worked on, still with no holder and no wait, waits on ezexe when a turn
    since ended on a question or offered buttons, and is answered when a turn ended without either. When none
    ended, ezexe's message carries it, and another session's message, which can come inside the turn, leaves it to
    work on. Then this message, `req`, ezexe's own, '' for any other: a button's label answers the row that offered
    it; a row's id answers that row; a reply such as "yes, push it" answers the row whose topic it shares or else
    the latest. What follows a reply's first words or a row's id, when it is a request of more than a quick thing's
    words on another topic, opens a row of its own, and a reply that holds one answers nothing. Any other request
    opens a row, a question leaves every wait in place, and any other message answers the latest row that waits.
    Returns the row this turn works on, '' for none."""
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
    keep = []
    for mine in [r for r in have if r["id"] in [now] + list(state.get("also") or [])]:
        if mine["holder"] or mine["waits"] or mine["end"]:
            continue
        rid = mine["id"]
        if turn and turn != mine["turnBefore"] and turn not in mine["asked"]:
            report = str(t.get("report") or "").strip()
            offered = [x for x in t.get("offered") or [] if isinstance(x, str) and x.strip()]
            if report and QUESTION.search(report) or offered:
                said = str(t.get("ask") or "").strip() or report.rsplit("\n", 1)[-1]
                _add(home, sid, {"kind": "waits", "id": rid, "turn": turn, "waits": said[-300:],
                                 "offered": offered[:6]})
            else:
                _add(home, sid, {"kind": "end", "id": rid, "end": "answered"})
        elif req:
            _add(home, sid, {"kind": "end", "id": rid, "end": "carried"})   # ezexe moved on before its turn ended
        else:
            keep.append(rid)                       # another session's message, maybe inside the turn: still on it
    have = rows(home, sid)
    now, also = (keep[0], keep[1:]) if keep else ("", [])
    if req:
        waiting = [r for r in have if r["waits"]]
        named = ROW_ID.search(req)
        pressed = next((r for r in reversed(waiting) if _label(req) in {_label(x) for x in r["offered"]}), None)
        hit = pressed or next((r for r in waiting if named and r["id"] == f"ask-{named.group(1)}"), None)
        rest = _rest(req)
        if not hit and waiting and REPLY.match(req):
            hit = next((r for r in reversed(waiting) if len(words(req) & words(r["topic"])) >= SHARED),
                       None) or waiting[-1]
        new = ""                                   # a request beside the answer, on another topic than its row's
        if hit and not pressed and request(rest) and len(words(rest) & words(hit["topic"])) < SHARED \
                and len(words(rest) - words(hit["topic"]) - words(hit["waits"])) >= SHARED:
            new = rest                             # "push it" asks nothing new; "sync the stores" does
            if not named and not quick(rest):      # "ok, now start the billing dashboard": a request, no answer
                hit = None
        if hit and new or not hit and request(req):
            new = new or req
            same = next((r for r in have if r["said"] == _key(new) and _live(r)), None)
            if same:                               # the same words again, while their row is live
                now = "" if same["holder"] or same["waits"] else same["id"]
            else:
                now = f"ask-{len(have) + 1}"
                _add(home, sid, {"kind": "opened", "id": now, "topic": topic_of(new), "said": _key(new),
                                 "turnBefore": turn})
        elif not hit and waiting and not asking(req):
            hit = next((r for r in reversed(waiting) if len(words(req) & words(r["topic"])) >= SHARED),
                       None) or waiting[-1]
        if hit:                                    # ezexe's answer: the row works on again from this message
            _add(home, sid, {"kind": "waits", "id": hit["id"], "waits": "", "offered": []})
            _add(home, sid, {"kind": "opened", "id": hit["id"], "topic": hit["topic"], "said": hit["said"],
                             "time": hit["opened"], "turnBefore": turn})
            if now and now != hit["id"]:
                also.append(hit["id"])             # answered beside a new request: read at the next message too
            now = now or hit["id"]
    state["now"], state["also"] = now, [x for x in also if x != now]
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
    if r:                                          # its own store: a controlled session's, else the app's record's
        _hold(home, sid, r["id"], target, ctl.get(target) or controls.store_of(target) or "", "routed")


# --- the page ----------------------------------------------------------------------------------------------------------

def _end(home, sid, r, end):
    """A row's end, kept on its log and on the row in hand."""
    _add(home, sid, {"kind": "end", "id": r["id"], "end": end})
    r.update(end=end, ended=_now())
    return end


def _stamp(row):
    """A turn's end as a string that orders by time: its exact time when it has one, else its minute."""
    return str(row.get("at") or row.get("time") or "")


def state_of(home, sid, r, entries, seen):
    """A row's state, read from its holder's turns since it took the request, in the holder's own store: the
    address book's entry when it has one, else the store the row kept or the app's record names. A done, a closed
    and the end of a row whose holder went quiet for KEEP_S are kept on the row, so it closes for good and a
    finished state is never shown without its end. `seen` keeps each holder's turn lines and whether it is working,
    read once per render."""
    if r["waits"]:
        return "waits on ezexe"
    if r["end"]:
        return r["end"]
    k = r["holder"]
    if not k:
        return "open"
    e = entries.get(k)
    where = e["home"] if e else (r["home"] or controls.store_of(k) or home)
    if k not in seen:
        seen[k] = (_turn_lines(where, k), _phi().puppeteer.working(where, k))
    lines, working = seen[k]
    counted = r["base"] >= 0 and r["home"] and relay.norm(r["home"]) == relay.norm(where)
    since = []
    for raw in (lines[r["base"]:] if counted else lines):   # only the turns since the holder took the request
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not counted:                            # counted in another store, or none: only a turn ended after it
            at, held = _stamp(row), str(r.get("at") or r.get("routed") or "")
            if (at <= held) if row.get("at") and r.get("at") else (at[:16] < held[:16]):
                continue
        since.append(row)
        if row.get("done"):
            return _end(home, sid, r, "done")
    if not e:
        ks = relay._session(where, k) if where else {}
        if ks.get("sessionId") and controls.out_of_tree(ks):
            return _end(home, sid, r, "closed")
    if working:
        return "working"
    last = max([_stamp(x) for x in since] + [str(r.get("at") or r.get("routed") or "")])
    try:
        quiet = time.time() - time.mktime(time.strptime(last[:16], "%Y-%m-%d %H:%M")) > KEEP_S
    except ValueError:
        quiet = False
    if quiet:                                      # a long-lived holder that never shows it done
        return _end(home, sid, r, "reported" if since else "carried")
    return "reported" if since else (r["how"] or "routed")


def _live(r):
    """True for a row not yet finished: open, held and not done or closed, or waiting on ezexe."""
    return not r["end"]


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
