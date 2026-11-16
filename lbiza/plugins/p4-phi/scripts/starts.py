"""starts.py: start requests, the children a session wants but cannot start, carried by the store.

The app refuses `mcp__ccd_session__start_session` with `initiation` `user_asked` in a turn ezexe did not begin:
a child's turn that another session's message started, or an app event. Such a session used to fall back to a card
or ask ezexe to type "go". Instead it writes each child it wants as a start request into the store,
`phi.py request "<title>" --brief "<brief>"`, and carries on. At the next turn ezexe's own words begin, in any
session of the same store, that session is handed every pending request, one line each with the exact call. When
the start happens, the brief's marker line tells phi, at the child's first message, whose child it is: phi records
the requester as its parent, so the child's spawnedFrom, its relays and its archive line go there. The app keeps
the starter as the parent in its own nesting, claude-code#109282. A request not started within EXPIRE_S is dropped.

Since #58 a request is handed only to the session that filed it, at the next turn ezexe begins in that session, so
the app's parent and phi's agree: handed to any session of the store, a puppeteer ran the call and the app nested
the child under the puppeteer. A session whose turn another session began shows the child as a proposal card first
and files a request only when the card is refused too. A request filed with `to`, a puppeteer's id, asks that
puppeteer for a new top session: it is never handed to its requester, and the puppeteer's hooks read it here.

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


# --- file sets: one writer per file in the single work tree (#48) -----------------------------------------------------
#
# Every brief declares the files its session may write, on a line `Files: <paths>`, or `Files: none` for a session
# that writes nothing. No two sessions write the same file at once: a start whose file set overlaps a live session's
# is held until that session reports done. A queue is split by these sets: tasks that share a file go to one child
# as a serial run, and tasks with disjoint files each get a child and run at the same time.

FILES_LINE = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?(?:files?|file set)(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
NO_FILES = re.compile(r"^\W*(?:none|nothing|no files?|read[- ]only)\b", re.I)
FILES_WANTED = ("a brief declares its file set (ezexe/p4#48): add a line `Files: <each path this session may write, "
                "comma separated>`, or `Files: none` for a session that writes nothing. One writer per file: tasks "
                "that share a file go to one child as a serial run, and tasks with disjoint files each get a child.")


LIST_END = re.compile(r"(?<=[\w`/\\)*\"'])[.:]\s+(?=[A-Z`\"'(])")   # where the list ends and a sentence begins


def _is_root(entry, base):
    """True for the repository's root or the session's own folder: named on a `Files:` line, it is context."""
    return "/" in entry and (entry == relay.norm(base or "") or os.path.exists(os.path.join(entry, ".git")))


def files_of(brief, base=""):
    """The file set a brief declares: [] for `Files: none`, None when it has no such line. A path with a folder is
    normalized under `base`; a bare file name is kept as its lower-case name. Only the paths listed after `Files:`
    up to the end of that line are read, and only up to where the list ends and a sentence begins. A path that is
    an ancestor of another listed path, or a repository's root, is context and is not held, unless it is the only
    path on the line (#62: a checkout's path named beside `dox/` made a child hold the whole repository)."""
    m = FILES_LINE.search(str(brief or ""))
    if not m:
        return None
    value = LIST_END.split(m.group(1).strip(), 1)[0].strip().rstrip(".")
    if NO_FILES.match(value):
        return []
    out = _listed(value, base)
    if len(out) > 1:
        whole = {e: e if "/" in e else relay.norm(e, base) for e in out}    # a bare name may be a folder here
        context = [e for e in out if _is_root(whole[e], base) or any(
            o != e and "/" in o and relay.covers(whole[e], o) for o in out)]
        out = [e for e in out if e not in context] or out[:1]
    return out


def _listed(value, base):
    out = []
    for tok in re.split(r"\s*(?:,|;|\band\b)\s*", value):
        ticked = re.findall(r"`([^`\s]+)`", tok)
        plain = tok.strip().strip("'\"").rstrip(".").strip()
        for name in ticked or ([plain.split(" ")[0]] if plain else []):
            name = name.strip("`'\"").rstrip(".")
            if not name:
                continue
            entry = relay.norm(name, base) if re.search(r"[\\/]", name) else name.lower()
            if entry not in out:
                out.append(entry)
    return out


def files_overlap(a, b):
    """The entries two file sets share: equal or nested paths, or a bare name that is the other's file name."""
    hit = []
    for x in a or []:
        for y in b or []:
            if "/" in x and "/" in y:
                same = relay.overlap(x, y)
            else:
                same = x.rsplit("/", 1)[-1] == y.rsplit("/", 1)[-1]
            if same and x not in hit:
                hit.append(x)
    return hit


def above(home, sid):
    """A session and every session above it: a parent's file set covers its children's and never holds them."""
    out, cur = [], sid
    while cur and cur not in out and len(out) < 12:
        out.append(cur)
        cur = relay._parent(relay._session(home, cur))
    return out


def stopped(s):
    """True when the app's record shows a session's last turn was stopped (`lastTurnStopped`, read 2026-11-16 on the
    record of a session stopped with the app's stop). Nothing in phi's own files says it, and a stopped session's
    replacement was held behind it (#58). Its next turn clears the mark."""
    relay.archived_in_app(s)                      # the app's records are read through relay, which phi hands them to
    sid = str(s.get("sessionId") or "")
    try:
        return bool(relay.RECORD and sid.startswith("local_") and relay.RECORD(sid).get("lastTurnStopped"))
    except Exception:  # noqa: BLE001
        return False


def writers(home, skip=()):
    """[(sessionId, title, its file set)] of the live sessions that declared files and have not reported done. An
    archived session holds nothing, and neither does one the app shows as stopped."""
    out = []
    for sid, s in relay._sessions(home).items():
        files = s.get("fileSet")
        if sid in skip or not isinstance(files, list) or not files or relay.gone(home, s) or stopped(s):
            continue
        turns = relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl"))
        if turns and turns[-1].get("done"):
            continue                              # it reported done: its files are free again
        out.append((sid, relay._title(s), files))
    return out


def held_by(home, requester, files, earlier=()):
    """(who, the shared files) of the first live writer, or request handed out before it, whose file set overlaps
    `files`; ('', []) when the start is free to go."""
    if not files:
        return "", []
    for sid, title, theirs in writers(home, skip=above(home, requester)):
        hit = files_overlap(files, theirs)
        if hit:
            return f"\"{title}\" ({sid})", hit
    for r in earlier:
        hit = files_overlap(files, r.get("files") or [])
        if hit:
            return f"start request {r.get('id')} \"{r.get('title')}\"", hit
    return "", []


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


def open_rows(home, at=None):
    """Every request not started and not past EXPIRE_S, oldest first, whoever it is for."""
    at = time.time() if at is None else at
    return sorted((r for r in state(home).values()
                   if not r.get("started") and at - float(r.get("at") or 0) <= EXPIRE_S),
                  key=lambda r: float(r.get("at") or 0))


def pending(home, at=None):
    """The requests still to start, oldest first: not started, not past EXPIRE_S, and not claimed in the last
    CLAIM_S. One addressed to a puppeteer is not among them: the puppeteer's hooks read it (#58)."""
    at = time.time() if at is None else at
    out = []
    for r in state(home).values():
        if r.get("started") or r.get("to") or at - float(r.get("at") or 0) > EXPIRE_S:
            continue
        c = r.get("claimed") or {}
        if c and at - float(c.get("at") or 0) < CLAIM_S:
            continue
        if r.get("after") and _busy(home, r["after"]):
            continue                              # queued behind a writer that is still at work
        out.append(r)
    free = []
    for r in sorted(out, key=lambda r: float(r.get("at") or 0)):
        who, _ = held_by(home, r.get("requester"), r.get("files") or [], free + _handed(home, r, at))
        if not who:                               # #48: held while a live writer or an earlier start has its files
            free.append(r)
    return free


def _handed(home, r, at):
    """The requests claimed or started before `r` whose child has not arrived or not reported done yet, and that
    declared files: an overlapping one holds `r`."""
    out = []
    for x in state(home).values():
        if x.get("id") == r.get("id") or not x.get("files") or float(x.get("at") or 0) > float(r.get("at") or 0):
            continue
        child = x.get("started")
        if child and child != "withdrawn":
            continue                              # its child is a live writer or gone: writers() answers for it
        c = x.get("claimed") or {}
        if not child and c and at - float(c.get("at") or 0) < CLAIM_S:
            out.append(x)                         # handed out, its child not arrived yet
    return out


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


def add(home, requester, title, brief, context="fresh", at=None, background="", after="", declared=False,
        to=""):
    """Keep a start request -> (its id, True when new). The same brief from the same session, still pending, is
    kept once. Its background is the one given or one built from the requester (#37). With `after`, it waits
    behind that session while it is a busy writer (#38). The file set its brief declares is kept on it; with
    `declared`, a brief that declares none is refused (#48). With `to`, a puppeteer's id, it asks that puppeteer
    for a new top session (#58)."""
    title, brief = " ".join(str(title or "").split()), str(brief or "").strip()
    if len(title) < 3:
        raise ValueError("a start request needs the child's title")
    if len(" ".join(brief.split())) < 20:
        raise ValueError("a start request needs the child's whole brief")
    files = files_of(brief, str(relay._session(home, requester).get("cwd") or ""))
    if declared and files is None:
        raise ValueError(FILES_WANTED)
    rid = "req-" + hashlib.sha1(f"{requester}\n{title}\n{brief}\n{to}".encode("utf-8", "replace")).hexdigest()[:10] \
        if to else "req-" + hashlib.sha1(f"{requester}\n{title}\n{brief}".encode("utf-8", "replace")).hexdigest()[:10]
    held = state(home).get(rid)
    if held and not held.get("started") and (time.time() if at is None else at) - float(held.get("at") or 0) <= EXPIRE_S:
        return rid, False
    at = time.time() if at is None else at
    _append(home, {"kind": "request", "id": rid, "at": at, "time": time.strftime("%Y-%m-%d %H:%M"),
                   **({"after": after} if after else {}), **({"files": files} if files else {}),
                   **({"to": to} if to else {}),
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
    import plans                                   # #61: the model and effort its brief's kind of work gets
    return plans.with_level({"initiation": "user_asked", "title": r["title"], "context": "fresh",
                             "use_worktree": False, "background": bg,
                             "prompt": r["brief"] + "\n\n" + marker(r["id"], r["requester"])},
                            r["title"] + "\n" + r["brief"])


def hand_text(home, sid, at=None):
    """The lines a session is handed at a turn ezexe began in it: each pending request it filed itself, with
    its exact call. '' when none of its own is pending. No other session is handed a request, a puppeteer
    included, so the app nests the child under the session that asked (#58)."""
    rows = [r for r in pending(home, at) if r.get("requester") == sid]
    if not rows:
        return ""
    lines = [f"- \"{r['title']}\": `mcp__ccd_session__start_session` with "
             f"{json.dumps(call_of(r, home), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): start requests this session filed in turns ezexe did not begin, when the app refused "
            "them `user_asked`. This turn ezexe began here, so start each now, with exactly the call given, "
            "before the rest of this turn's work:\n" + "\n".join(lines) + "\n"
            "Each is this session's own child, in the app's nesting and in phi's, and its reports come here in "
            "full.")


def requested_text(rid, new):
    return ((f"kept as start request {rid}" if new else f"start request {rid} was already kept") +
            ": the next turn ezexe begins in this session starts it with `user_asked`, as this session's own "
            "child. No other session is handed it. Carry on with the rest of the task, and say in this turn's "
            "report that a child waits on ezexe's next message here.")


def asked_text(rid, new, title):
    """What a session is told when it asked its puppeteer for a new top session."""
    return ((f"kept as request {rid} to this session's puppeteer" if new else f"request {rid} was already kept") +
            f": \"{title}\" is handed to it at the next turn ezexe begins there, and it starts the session, files "
            "it in this environment's section and takes it under control, or declines it. Start nothing for it "
            "here, and carry on with the rest of the task.")


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


def started(home, rid, child, at=None, by=""):
    _append(home, {"kind": "started", "id": rid, "child": child, "at": time.time() if at is None else at,
                   **({"by": by} if by else {})})


def withdraw(home, rid, by="", at=None):
    """Withdraw a pending start request by its id -> the line to print. Kept as a row in start-requests.jsonl, so
    `pending`, `open_rows` and `hand_text` leave it out and the record of it stays (#50). An unknown id, or a
    request already started or withdrawn, is refused."""
    r = state(home).get(rid)
    if not r:
        raise ValueError(f"no start request {rid} is on file in this store")
    if r.get("started") == "withdrawn":
        raise ValueError(f"start request {rid} was withdrawn already")
    if r.get("started"):
        raise ValueError(f"start request {rid} was started already, as {r['started']}: stop or message that "
                         f"session instead")
    started(home, rid, "withdrawn", at, by)
    return (f"withdrawn: start request {rid} \"{r.get('title')}\", filed by \"{r.get('requesterTitle') or r.get('requester')}\", "
            f"is handed to no session now. Its row stays in start-requests.jsonl.")
