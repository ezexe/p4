"""starts.py: start requests, the children a session wants but cannot start, carried by the store.

The app refuses `mcp__ccd_session__start_session` with `initiation` `user_asked` in a turn ezexe did not begin:
a child's turn that another session's message started, or an app event. Such a session used to fall back to a card
or ask ezexe to type "go". Instead it writes each child it wants as a start request into the store,
`phi.py request "<title>" --brief "<brief>"`, and carries on. At the next turn ezexe's own words begin, in any
session of the same store, that session is handed every pending request, one line each with the exact call. When
the start happens, the brief's marker line tells phi, at the child's first message, whose child it is: phi records
the requester as its parent, so the child's spawnedFrom, its relays and its archive line go there. The app keeps
the starter as the parent in its own nesting, claude-code#109282. A request not started within EXPIRE_S is dropped.

<home>/phi/start-requests.jsonl holds one row a change: `request` with the brief, `claimed` when a start_session
call carrying its marker is about to run, `started` when the child's first message arrived.

A request can wait behind a busy writer (#38): pioneer queues a draft whose files a running session holds with
`after`, that session's id, and the request is handed out only once that session is no longer busy.
"""

import hashlib
import json
import os
import re
import time

import relay

EXPIRE_S = 24 * 3600            # a request no turn of ezexe's has started by then is dropped
CLAIM_S = 15 * 60               # a claimed request whose child never arrived is handed again after this
MARK_RE = re.compile(r"phi start request (req-[0-9a-f]{10}) for (\S+?)\.?(?:\s|$)")
ISSUE = "claude-code#109282"
BACKGROUND_MIN = 80             # #37: the app refuses a fresh start whose background is shorter


def path_of(home):
    return os.path.join(home, "phi", "start-requests.jsonl")


def _append(home, row):
    p = path_of(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def marker(rid, requester):
    return f"phi start request {rid} for {requester}."


def state(home, at=None):
    """{id: request row, with `claimed` (by, at) and `started` (child) folded in} of every request on file."""
    out = {}
    for r in relay._rows(path_of(home)):
        rid = r.get("id")
        if not isinstance(rid, str):
            continue
        if r.get("kind") == "request":
            out[rid] = dict(r)
        elif rid in out and r.get("kind") == "claimed":
            out[rid]["claimed"] = {"by": r.get("by"), "at": r.get("at")}
        elif rid in out and r.get("kind") == "started":
            out[rid]["started"] = r.get("child")
    return out


def pending(home, at=None):
    """The requests still to start, oldest first: not started, not past EXPIRE_S, and not claimed in the last
    CLAIM_S."""
    at = time.time() if at is None else at
    out = []
    for r in state(home).values():
        if r.get("started") or at - float(r.get("at") or 0) > EXPIRE_S:
            continue
        c = r.get("claimed") or {}
        if c and at - float(c.get("at") or 0) < CLAIM_S:
            continue
        if r.get("after") and _busy(home, r["after"]):
            continue                              # queued behind a writer that is still at work
        out.append(r)
    return sorted(out, key=lambda r: float(r.get("at") or 0))


def _busy(home, sid):
    try:
        import puppeteer
        return puppeteer.busy(home, sid)
    except Exception:  # noqa: BLE001
        return False


def background_of(home, requester, given=""):
    """A request's background: the one given, else one built from the requester's task and the store's project,
    never shorter than BACKGROUND_MIN characters."""
    text = " ".join(str(given or "").split())
    if not text:
        s = relay._session(home, requester)
        task = relay._short(" ".join(str(s.get("task") or "").split()), 600)
        project = relay.norm(os.path.dirname(os.path.dirname(os.path.abspath(home))))
        text = (f"Requested by the session \"{relay._title(s)}\" ({requester}) in the project {project}"
                + (f", whose task is: {task}" if task else "") + ".")
    if len(text) < BACKGROUND_MIN:
        text += (" phi (p4-phi) carried this start request through the store; the brief says what the child must "
                 "do and leave done.")
    return text


def add(home, requester, title, brief, context="fresh", at=None, background="", after=""):
    """Keep a start request -> (its id, True when new). The same brief from the same session, still pending, is
    kept once. Its background is the one given or one built from the requester (#37). With `after`, it waits
    behind that session while it is a busy writer (#38)."""
    title, brief = " ".join(str(title or "").split()), str(brief or "").strip()
    if len(title) < 3:
        raise ValueError("a start request needs the child's title")
    if len(" ".join(brief.split())) < 20:
        raise ValueError("a start request needs the child's whole brief")
    rid = "req-" + hashlib.sha1(f"{requester}\n{title}\n{brief}".encode("utf-8", "replace")).hexdigest()[:10]
    held = state(home).get(rid)
    if held and not held.get("started") and (time.time() if at is None else at) - float(held.get("at") or 0) <= EXPIRE_S:
        return rid, False
    at = time.time() if at is None else at
    _append(home, {"kind": "request", "id": rid, "at": at, "time": time.strftime("%Y-%m-%d %H:%M"),
                   **({"after": after} if after else {}),
                   "requester": requester, "requesterTitle": relay._title(relay._session(home, requester)),
                   "title": title, "brief": brief, "context": "fork" if context == "fork" else "fresh",
                   "background": background_of(home, requester, background)})
    return rid, True


def call_of(r, home=""):
    """The exact start_session input that starts a request. Always fresh: a fork would carry the starter's
    conversation, not the requester's. It carries the request's background, which the app requires (#37); a request
    kept before backgrounds were is given one built now."""
    bg = str(r.get("background") or "")
    if len(bg) < BACKGROUND_MIN:
        bg = background_of(home, r["requester"], bg) if home else (
            bg + " " + background_of("", r["requester"], "")).strip()
    return {"initiation": "user_asked", "title": r["title"], "context": "fresh", "use_worktree": False,
            "background": bg, "prompt": r["brief"] + "\n\n" + marker(r["id"], r["requester"])}


def hand_text(home, sid, at=None):
    """The lines a session is handed at a turn ezexe began: each pending request with its exact call. ''
    when none is pending."""
    rows = pending(home, at)
    if not rows:
        return ""
    lines = [f"- \"{r['title']}\" for \"{r.get('requesterTitle') or r['requester']}\" ({r['requester']}): "
             f"`mcp__ccd_session__start_session` with {json.dumps(call_of(r, home), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): start requests from sessions whose turns ezexe did not begin, so the app refused "
            "them `user_asked`. This turn ezexe began, so start each now, with exactly the call given, before "
            "the rest of this turn's work:\n" + "\n".join(lines) + "\n"
            f"The app keeps this session as each child's parent in its own nesting, {ISSUE}; phi records the "
            f"requester as the parent, so the child's spawnedFrom, its relays and its archive line go to the "
            f"requester. Pass nothing on: the requester gets the child's reports in full.")


def requested_text(rid, new):
    return ((f"kept as start request {rid}" if new else f"start request {rid} was already kept") +
            ": the next turn ezexe begins, in any session of this store, starts it with `user_asked`, and phi "
            "makes it this session's child, its spawnedFrom, relays and archive line coming here. Do not ask "
            "ezexe to type anything or click a card; carry on with the rest of the task.")


def claim(home, prompt, by, at=None):
    """A start_session call carrying a request's marker is about to run: the request is not handed again for
    CLAIM_S. Returns the request id, '' when the prompt carries none."""
    m = MARK_RE.search(str(prompt or ""))
    if not m or m.group(1) not in state(home):
        return ""
    _append(home, {"kind": "claimed", "id": m.group(1), "by": by, "at": time.time() if at is None else at})
    return m.group(1)


def requester_of(home, prompt):
    """(request id, requester) a started session's first message names by its marker; ('', '') for none."""
    m = MARK_RE.search(str(prompt or ""))
    if not m:
        return "", ""
    r = state(home).get(m.group(1))
    if not r or r.get("requester") != m.group(2):
        return "", ""
    return m.group(1), r["requester"]


def started(home, rid, child, at=None):
    _append(home, {"kind": "started", "id": rid, "child": child, "at": time.time() if at is None else at})
